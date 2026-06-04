import { useEffect, useRef, useCallback } from 'react';
import type { MicVAD } from '@ricky0123/vad-web';
import { useAppStore } from '../store';

interface UseAudioParams {
  sendVoice: (audioBase64: string) => void;
  // v3-F #4: VAD 在 AI 说话期间检测到持续语音 → 触发打断
  sendInterrupt: () => void;
}

// VAD 触发打断的阈值：连续 N 帧（≈ N/60 秒）高于音量阈值才算"用户说话"，
// 滤掉扬声器外溢 / 偶发噪声引发的假打断。
const INTERRUPT_FRAMES = 6;
const INTERRUPT_COOLDOWN_MS = 1500;

// INV-17 v3.1 (2026-05-28): interrupt threshold 独立常量 raw 0-255 量级。
// 修 v3 误把 silero confidence(0-1)* 255 用作 raw byte frequency 阈值 ·
// 两个不同物理量不能直接相乘 · 误把敏感度降到 raw 76 → AI 说话期小噪音
// 误触发打断。raw 165 跟 INV-17 v3 前 vadThreshold=65 (65/100 * 255 = 165)
// 等价 · 维持改前的 interrupt 敏感度。
// 与 silero VAD 主路径完全解耦 · 不再 follow positiveSpeechThreshold。
const INTERRUPT_THRESHOLD = 165;

// INV-15 Option H (2026-05-27): 周期 stream 健康检查 frame 间隔。
// vadLoop ~60fps · 每 60 frame ≈ 1s 检查一次 track.readyState · 避免 onended
// 漏 fire(权限快速 revoke / Tauri webview suspend 等场景某些浏览器不 fire)。
const STREAM_HEALTH_CHECK_FRAMES = 60;

// 2026-05-31 race-fix · vadLoop 自愈门槛:连续 N 帧 max amplitude=0 且
// AudioContext.state !== 'running' → 主动 recoverStream(不再静默 skip)。
// 与 STREAM_HEALTH_CHECK_FRAMES(查 track.readyState)互补 — 后者抓 track
// 死,本常量抓 ctx 死/挂起(背景态 / Tauri suspend 后 ctx suspended)。
const ZERO_AMP_RECOVERY_FRAMES = 60;

interface UseAudioReturn {
  startManual: () => Promise<void>;
  stopManualAndSend: () => Promise<void>;
  toggleVad: () => Promise<void>;
}

/** Blob → base64（去掉 data URL 前缀） */
function blobToBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result as string;
      resolve(result.split(',')[1]);
    };
    reader.onerror = reject;
    reader.readAsDataURL(blob);
  });
}

/**
 * INV-17 v3 (2026-05-28): Float32Array @ 16kHz mono → WAV → base64。
 * silero MicVAD.onSpeechEnd 给 Float32Array(silero 内部固定 16kHz 单声道)·
 * backend `whisper_asr.transcribe_b64` 走 faster-whisper (ffmpeg under hood) ·
 * 接受任何 ffmpeg 支持的 audio format · WAV 16-bit PCM 完全兼容。
 *
 * WAV header(44 bytes · RIFF/WAVE/fmt /data chunks)+ 16-bit PCM samples。
 * 国际通用 little-endian。
 */
function float32ToWavBase64(samples: Float32Array, sampleRate = 16000): string {
  const numChannels = 1;
  const bitsPerSample = 16;
  const bytesPerSample = bitsPerSample / 8;
  const blockAlign = numChannels * bytesPerSample;
  const byteRate = sampleRate * blockAlign;
  const dataSize = samples.length * bytesPerSample;

  const buf = new ArrayBuffer(44 + dataSize);
  const view = new DataView(buf);

  // RIFF chunk descriptor
  writeAscii(view, 0, 'RIFF');
  view.setUint32(4, 36 + dataSize, true);   // ChunkSize = 36 + Subchunk2Size
  writeAscii(view, 8, 'WAVE');
  // fmt sub-chunk
  writeAscii(view, 12, 'fmt ');
  view.setUint32(16, 16, true);             // Subchunk1Size = 16(PCM)
  view.setUint16(20, 1, true);              // AudioFormat = 1(PCM)
  view.setUint16(22, numChannels, true);    // NumChannels
  view.setUint32(24, sampleRate, true);     // SampleRate
  view.setUint32(28, byteRate, true);       // ByteRate
  view.setUint16(32, blockAlign, true);     // BlockAlign
  view.setUint16(34, bitsPerSample, true);  // BitsPerSample
  // data sub-chunk
  writeAscii(view, 36, 'data');
  view.setUint32(40, dataSize, true);       // Subchunk2Size

  // PCM 16-bit signed samples · float -1.0~1.0 → int16
  let offset = 44;
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
    offset += 2;
  }

  // ArrayBuffer → base64(Uint8Array 安全分块 · 长 audio 防 stack overflow)
  const bytes = new Uint8Array(buf);
  let binary = '';
  const CHUNK = 0x8000;
  for (let i = 0; i < bytes.length; i += CHUNK) {
    binary += String.fromCharCode.apply(null, Array.from(bytes.subarray(i, i + CHUNK)));
  }
  return btoa(binary);
}

function writeAscii(view: DataView, offset: number, s: string): void {
  for (let i = 0; i < s.length; i++) {
    view.setUint8(offset + i, s.charCodeAt(i));
  }
}

export function useAudio({ sendVoice, sendInterrupt }: UseAudioParams): UseAudioReturn {
  const audioContextRef = useRef<AudioContext | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const dataArrayRef = useRef<Uint8Array | null>(null);
  const rafIdRef = useRef<number | null>(null);
  const silenceStartRef = useRef<number | null>(null);
  const lastRecordingEndRef = useRef<number>(Date.now());
  const recordedChunksRef = useRef<Blob[]>([]);
  // INV-15 Option H/I: 周期健康检查 frame 计数 + recovery-in-progress 锁
  const healthCheckFramesRef = useRef<number>(0);
  const recoveryInFlightRef = useRef<boolean>(false);
  // 2026-05-31 race-fix · vadLoop 自愈累计:连续 max=0 帧数
  const zeroAmpFramesRef = useRef<number>(0);
  // 2026-05-31 race-fix · toggleVad 重入闸:防快按导致 start/pause 在
  // 前一次 silero resume/pause(getUserMedia / new AudioContext / track.stop)
  // 未结算时并发触发,把半就绪的 stream/analyser 搞挂。
  const toggleInFlightRef = useRef<boolean>(false);
  // INV-17 v3: silero MicVAD instance · eager init at mount · destroy at unmount
  const micVadRef = useRef<MicVAD | null>(null);

  const store = useAppStore;
  // 2026-06-05 · 订阅 recordingMode 给下方 auto-pause-on-mode-manual effect 用。
  // 单值 selector · 切 'vad' 不重渲染下面那个 effect 逻辑里只关心 manual 翻转。
  const recordingMode = useAppStore((s) => s.recordingMode);

  // 始终持有最新 sendVoice 引用（避免 useCallback 闭包过期）
  const sendVoiceRef = useRef(sendVoice);
  useEffect(() => { sendVoiceRef.current = sendVoice; });
  // v3-F #4：VAD 打断 hook 同样要保新鲜引用
  const sendInterruptRef = useRef(sendInterrupt);
  useEffect(() => { sendInterruptRef.current = sendInterrupt; });
  // 连续高于阈值的帧数 + 上次打断时间（debounce）
  const interruptFramesAboveRef = useRef(0);
  const lastInterruptAtRef = useRef(0);

  // ── INV-15 P2 (2026-05-27) · stream stale recovery 三件套 ─────────────
  // Option H · initStream 加 track.readyState + AudioContext.state 健康检查
  // Option I · MediaStreamTrack.onended listener 自动 recovery
  // Option G · vadLoop 写 vadCurrentMax 给 VadBar 实时显示
  //
  // 真因(audit INV-15 §2):原 initStream 只判 `if (streamRef.current) return`,
  // 不 verify track 是否仍 'live' / AudioContext 是否 suspended · 系统切 mic 源 /
  // 应用后台 / Tauri webview suspend 后无 recovery · 用户感知 "VAD 卡空闲"。
  //
  // 修法:
  //   - initStream 复用前先 health-check · 不健康 teardown 重建
  //   - 拿到 stream 立刻挂 .onended · track 死时自动 recover(若 VAD 非 sleep)
  //   - vadLoop 每 STREAM_HEALTH_CHECK_FRAMES 帧再 verify 一次 readyState ·
  //     onended 漏 fire 兜底
  //   - 每帧把 max amplitude 写 store · VadBar 实时显示 "now: X / threshold: Y"
  //     给 PM 自助诊断(数字不动 = stream stale · 数字动但 < threshold = 阈值高)

  /** 拆掉旧 audio 图(关 tracks · 关 AudioContext · 清 refs)· idempotent。*/
  const teardownAudioGraph = useCallback((): void => {
    try {
      if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
        mediaRecorderRef.current.stop();
      }
    } catch (e) {
      console.warn('[Audio] mediaRecorder stop failed during teardown:', e);
    }
    mediaRecorderRef.current = null;

    const stream = streamRef.current;
    if (stream) {
      try {
        stream.getTracks().forEach((t) => t.stop());
      } catch (e) {
        console.warn('[Audio] stream tracks stop failed during teardown:', e);
      }
    }
    streamRef.current = null;

    const ctx = audioContextRef.current;
    if (ctx && ctx.state !== 'closed') {
      ctx.close().catch((e) => console.warn('[Audio] AudioContext close failed:', e));
    }
    audioContextRef.current = null;
    analyserRef.current = null;
    dataArrayRef.current = null;
  }, []);

  /** 创建新 audio 图(getUserMedia + AudioContext + Analyser + onended hook)。*/
  const createAudioGraph = useCallback(async (): Promise<MediaStream> => {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    streamRef.current = stream;

    // Option I · onended listener · track 死时(系统切源 / 权限 revoke / 浏览器
    // suspend mic)自动 mark stale + 尝试 recover。
    stream.getTracks().forEach((track) => {
      track.addEventListener('ended', () => {
        console.warn(
          '[Audio] mic track ended unexpectedly (kind=%s label=%s)',
          track.kind, track.label,
        );
        void recoverStream('track-ended');
      });
    });

    const ctx = new AudioContext();
    audioContextRef.current = ctx;
    const source = ctx.createMediaStreamSource(stream);
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 1024;
    source.connect(analyser);
    analyserRef.current = analyser;
    dataArrayRef.current = new Uint8Array(analyser.frequencyBinCount);
    return stream;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /** 健康检查:tracks 全 'live' + AudioContext !closed · 返 true 表示可复用。*/
  const isAudioGraphHealthy = useCallback((): boolean => {
    const stream = streamRef.current;
    const ctx = audioContextRef.current;
    if (!stream || !ctx) return false;
    const tracks = stream.getTracks();
    if (tracks.length === 0) return false;
    if (!tracks.every((t) => t.readyState === 'live')) return false;
    if (ctx.state === 'closed') return false;
    return true;
  }, []);

  /** 申请麦克风权限并初始化 AudioContext + Analyser(健康检查 + 复用兼容)。*/
  const initStream = useCallback(async (): Promise<MediaStream> => {
    // 复用 path · audio 图健康直接返
    if (isAudioGraphHealthy()) {
      const ctx = audioContextRef.current!;
      // 尝试 resume suspended(浏览器 autoplay policy / app 后台后切回)
      if (ctx.state === 'suspended') {
        try {
          await ctx.resume();
        } catch (e) {
          console.warn('[Audio] AudioContext.resume failed · 走重建路径:', e);
          teardownAudioGraph();
          return await createAudioGraph();
        }
      }
      return streamRef.current!;
    }
    // 不健康 · teardown 重建
    if (streamRef.current || audioContextRef.current) {
      const tracks = streamRef.current?.getTracks() || [];
      console.warn(
        '[Audio] audio graph stale (tracks=%o · ctx=%s) · re-initializing',
        tracks.map((t) => t.readyState),
        audioContextRef.current?.state ?? '<null>',
      );
      teardownAudioGraph();
    }
    return await createAudioGraph();
  }, [createAudioGraph, isAudioGraphHealthy, teardownAudioGraph]);

  /** Option I · track ended / 周期检查发现 stale 时自动恢复。
   *  Only re-init if VAD 非 sleep(用户主动切 sleep 时尊重 · 不偷偷重申 mic)。
   */
  const recoverStream = useCallback(async (reason: string): Promise<void> => {
    if (recoveryInFlightRef.current) {
      // 多事件源(onended + 周期 check)可能同时触发 · 单飞行锁防 race
      return;
    }
    const vadState = store.getState().vadState;
    if (vadState === 'sleep') {
      // 用户已 sleep · teardown 不 recover · 等下次 toggleVad 再 init
      teardownAudioGraph();
      console.log('[Audio] stream recover (%s) skipped · VAD sleep state', reason);
      return;
    }
    recoveryInFlightRef.current = true;
    try {
      // 停 RAF 防 race 期间 vadLoop 用 stale analyser
      if (rafIdRef.current !== null) {
        cancelAnimationFrame(rafIdRef.current);
        rafIdRef.current = null;
      }
      teardownAudioGraph();
      await createAudioGraph();
      // 重启 RAF
      if (rafIdRef.current === null) {
        rafIdRef.current = requestAnimationFrame(vadLoop);
      }
      console.log('[Audio] stream recovered (%s) · vadLoop resumed', reason);
    } catch (e) {
      console.error('[Audio] stream recovery failed (%s):', reason, e);
      // recover 失败(eg permission denied)· 强制 sleep + 给前端展示 status
      store.getState().setVadState('sleep');
    } finally {
      recoveryInFlightRef.current = false;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [createAudioGraph, teardownAudioGraph, store]);

  /** 启动 MediaRecorder */
  const startRecorder = useCallback((stream: MediaStream): void => {
    recordedChunksRef.current = [];
    const mr = new MediaRecorder(stream, { mimeType: 'audio/webm;codecs=opus' });
    mr.ondataavailable = (e) => {
      if (e.data.size > 0) recordedChunksRef.current.push(e.data);
    };
    mediaRecorderRef.current = mr;
    mr.start();
    store.getState().setRecording(true);
    store.getState().setStatus('listening');
  }, [store]);

  /** 停止录音，base64 化后发送 */
  const stopAndSend = useCallback((): Promise<void> => {
    const mr = mediaRecorderRef.current;
    if (!mr || mr.state === 'inactive') return Promise.resolve();
    return new Promise((resolve) => {
      mr.onstop = async () => {
        const blob = new Blob(recordedChunksRef.current, { type: 'audio/webm' });
        recordedChunksRef.current = [];
        store.getState().setRecording(false);
        store.getState().setStatus('idle');
        try {
          const base64 = await blobToBase64(blob);
          if (!store.getState().micMuted) {
            sendVoiceRef.current(base64);
          } else {
            console.log('[Audio] mic muted, drop voice');
          }
        } catch (e) {
          console.error('[Audio] blob→base64 error:', e);
        }
        lastRecordingEndRef.current = Date.now();
        resolve();
      };
      mr.stop();
    });
  }, [store]);

  // ── 手动模式 ────────────────────────────────────────────────────────────────

  const startManual = useCallback(async (): Promise<void> => {
    if (store.getState().micMuted) {
      console.log('[Audio] mic muted, ignore startManual');
      return;
    }
    const stream = await initStream();
    startRecorder(stream);
  }, [initStream, startRecorder, store]);

  const stopManualAndSend = useCallback(async (): Promise<void> => {
    await stopAndSend();
  }, [stopAndSend]);

  // ── VAD 模式 ─────────────────────────────────────────────────────────────────

  const vadLoop = useCallback((): void => {
    const analyser = analyserRef.current;
    const dataArray = dataArrayRef.current;
    if (!analyser || !dataArray) return;

    // Option H · 周期 stream 健康检查 · 每 STREAM_HEALTH_CHECK_FRAMES 帧 verify
    // 一次 track.readyState · onended 漏 fire 兜底。
    healthCheckFramesRef.current += 1;
    if (healthCheckFramesRef.current >= STREAM_HEALTH_CHECK_FRAMES) {
      healthCheckFramesRef.current = 0;
      const stream = streamRef.current;
      if (stream) {
        const tracks = stream.getTracks();
        if (tracks.length === 0 || !tracks.every((t) => t.readyState === 'live')) {
          console.warn(
            '[Audio] periodic health check found stale stream (tracks=%o)',
            tracks.map((t) => t.readyState),
          );
          void recoverStream('periodic-check');
          return;  // skip 本帧 vadLoop · recoverStream 会重启 RAF
        }
      }
    }

    analyser.getByteFrequencyData(dataArray);
    let max = 0;
    for (let i = 0; i < dataArray.length; i++) {
      if (dataArray[i] > max) max = dataArray[i];
    }
    // INV-17 v3 · vadCurrentMax 写入已删 · silero onFrameProcessed 写 vadConfidence
    // 代替。max 仍计算 · 供 interrupt detection 用(下面 micMuted 分支)。

    // 2026-05-31 race-fix · 自愈:连续 ZERO_AMP_RECOVERY_FRAMES 帧 max=0
    // 且 ctx 不在 running → 不再等 STREAM_HEALTH_CHECK_FRAMES,主动 recover。
    // 抓 "stream 看着活但 ctx suspended / analyser 挂死" 的隐性卡死(快按
    // toggleVad 导致 start/pause race · ctx 提前 close 等)。
    if (max === 0) {
      zeroAmpFramesRef.current += 1;
      const ctxState = audioContextRef.current?.state ?? null;
      if (
        zeroAmpFramesRef.current >= ZERO_AMP_RECOVERY_FRAMES &&
        ctxState !== 'running'
      ) {
        console.warn(
          '[Audio] zero-amp self-heal · ctx.state=%s frames=%d',
          ctxState ?? '<null>', zeroAmpFramesRef.current,
        );
        zeroAmpFramesRef.current = 0;
        void recoverStream('zero-amp-self-heal');
        return;  // recoverStream 重启 RAF
      }
    } else {
      zeroAmpFramesRef.current = 0;
    }

    const vadState = store.getState().vadState;
    const micMuted = store.getState().micMuted;

    if (micMuted) {
      // Momo 说话期间不录音，但 v3-F #4 在此监听打断:用户说话足够久(连续
      // INTERRUPT_FRAMES 帧高于阈值)就 sendInterrupt。冷却 INTERRUPT_COOLDOWN_MS
      // 防止打断后短时间内被状态切换 race 反复触发。
      // INV-17 v3.1: interrupt 跟 silero VAD 主路径完全解耦 · 用顶部独立常量
      // INTERRUPT_THRESHOLD(raw byte freq 0-255 量级)· 不再 follow
      // vadPositiveThreshold(silero 0-1 confidence)。物理量不同不能相乘。
      const status = store.getState().status;
      const isAiSpeaking = status === 'speaking' || status === 'thinking';
      const cooledDown =
        Date.now() - lastInterruptAtRef.current > INTERRUPT_COOLDOWN_MS;
      if (isAiSpeaking && cooledDown) {
        if (max >= INTERRUPT_THRESHOLD) {
          interruptFramesAboveRef.current += 1;
          if (interruptFramesAboveRef.current >= INTERRUPT_FRAMES) {
            console.log('[VAD] sustained speech during AI playback → interrupt');
            sendInterruptRef.current();
            lastInterruptAtRef.current = Date.now();
            interruptFramesAboveRef.current = 0;
          }
        } else {
          interruptFramesAboveRef.current = 0;
        }
      }
      rafIdRef.current = requestAnimationFrame(vadLoop);
      return;
    }
    // 不在说话状态：重置打断计数
    interruptFramesAboveRef.current = 0;

    // INV-17 v3 · 删:
    //   - active → recording 触发(silero onSpeechStart 接管)
    //   - recording → silence countdown endpoint(silero onSpeechEnd 接管)
    // 保留:
    //   - active idle timeout(60s 无录音 → sleep)· 与 silero 状态无关 · 跟
    //     INV-15 P2 stream lifecycle 一致。
    if (vadState === 'active') {
      if (Date.now() - lastRecordingEndRef.current >= store.getState().vadIdleTimeoutMs) {
        // INV-17 v3.1: idle 超时进 sleep 时也需 pause silero · 否则 silero
        // 内部 onnxruntime worker 持续跑空转浪费 CPU。toggleVad sleep 分支
        // 同款处理(pause + setRecording(false) + setVadConfidence(0))。
        // pauseStream callback 会 teardownAudioGraph 不释放底层 stream ·
        // 下次 toggleVad → resumeStream 仍复用同一 MediaStream(INV-15 P2)。
        try {
          micVadRef.current?.pause();
        } catch (e) {
          console.error('[silero] idle pause failed:', e);
        }
        store.getState().setVadState('sleep');
        store.getState().setRecording(false);
        store.getState().setVadConfidence(0);
      }
    }

    rafIdRef.current = requestAnimationFrame(vadLoop);
  }, [recoverStream, store]);

  const toggleVad = useCallback(async (): Promise<void> => {
    // INV-17 v3 · silero MicVAD 接管:start/pause + 内部 onSpeech callback
    // 驱动 vadState transitions。toggleVad 仅决定 silero 开关 + RAF 启停。
    //
    // 2026-05-31 race-fix · 三条防御:
    //   1. toggleInFlightRef 重入闸:防快按二次进入在前一次 start/pause 的
    //      getUserMedia / new AudioContext / track.stop / ctx.close 链路未
    //      结算时并发触发,把半就绪的 stream/analyser 搞挂(原 bug 根因)。
    //   2. v.start() / v.pause() 全部 await:silero 内部 resumeStream /
    //      pauseStream 是异步,不 await 会让"已设 vadState='active'"和
    //      "ctx/stream 仍在初始化"撞车。
    //   3. sleep→active 起步失败显式回滚 setVadState('sleep'):状态不卡半切换。
    if (toggleInFlightRef.current) {
      console.warn('[silero] toggleVad re-entered while previous transition in flight · ignoring');
      return;
    }
    const v = micVadRef.current;
    const ready = store.getState().vadReady;
    if (!v || !ready) {
      console.warn('[silero] toggleVad called but MicVAD not ready · ignoring');
      return;
    }
    toggleInFlightRef.current = true;
    try {
      const current = store.getState().vadState;
      if (current === 'sleep') {
        try {
          // silero.start() → 内部 resumeStream(我们 inject 的 initStream)→ 拿
          // INV-15 P2 健康检查过的 stream + 开 AudioWorklet
          await v.start();
        } catch (e) {
          console.error('[silero] start failed · roll back to sleep:', e);
          // 起步失败 · 显式回滚到 sleep · 不让 UI / 状态卡在半切换
          store.getState().setVadState('sleep');
          store.getState().setRecording(false);
          store.getState().setVadConfidence(0);
          return;
        }
        store.getState().setVadState('active');
        lastRecordingEndRef.current = Date.now();
        zeroAmpFramesRef.current = 0;  // 清自愈计数 · 新启动重新观察
        if (rafIdRef.current === null) {
          rafIdRef.current = requestAnimationFrame(vadLoop);
        }
      } else {
        // active 或 recording → sleep
        try {
          // silero.pause() → 内部 pauseStream(我们 inject 的 teardownAudioGraph)
          await v.pause();
        } catch (e) {
          // pause 失败仍走清理路径 · 状态归零比抛错更安全(下次 toggle 能恢复)
          console.error('[silero] pause failed · 仍走清理路径:', e);
        }
        store.getState().setVadState('sleep');
        store.getState().setRecording(false);
        store.getState().setVadConfidence(0);
        zeroAmpFramesRef.current = 0;
        if (rafIdRef.current !== null) {
          cancelAnimationFrame(rafIdRef.current);
          rafIdRef.current = null;
        }
      }
    } finally {
      toggleInFlightRef.current = false;
    }
  }, [vadLoop, store]);

  // 2026-06-05 · 切到手动时自动 pause silero(避免引擎仍在 active 听话/送 voice)。
  // 原 bug:onRecordingMode 仅改字段 + 写 LS,完全不碰 silero 引擎 → 用户在 VAD
  // active 状态下切手动 → silero 实例仍 active,onSpeechEnd 仍向 WS 送 voice,
  // 且按 ChatInput mic 还会并行 startManual → 双路 send voice。
  // 修法:用 useEffect 订阅 recordingMode 字段(单源 from store),manual 翻转时
  // 主动调 toggleVad 让引擎走 active→sleep 同款 race-safe 路径(toggleInFlightRef
  // 防快按、v.pause + AudioContext teardown 同 UI 触发的 toggleVad 一致)。
  // 切回 VAD 不自动 start —— 用户按 mic 才启,跟现状一致(避免后台监听)。
  useEffect(() => {
    if (recordingMode !== 'manual') return;
    if (store.getState().vadState === 'sleep') return;
    void toggleVad();
  }, [recordingMode, toggleVad, store]);

  // ── INV-17 v3 · eager init MicVAD at mount ───────────────────────────────
  // 模块 import 用 dynamic import 避开 SSR / Tauri prerender 期 navigator.
  // mediaDevices 未定义。失败 → setVadReady(false) + setRecordingMode('manual')
  // + 通知用户。需要 ref 中转 initStream/teardown helpers 给 silero callback。
  // (callbacks 在 useEffect[] 闭包内创建 · 用 latest-value ref pattern)。
  const initStreamRef = useRef(initStream);
  useEffect(() => { initStreamRef.current = initStream; });
  const teardownRef = useRef(teardownAudioGraph);
  useEffect(() => { teardownRef.current = teardownAudioGraph; });

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        // dynamic import · 防 SSR / Tauri prerender · 同时让 silero ~70KB +
        // onnxruntime-web wasm 在 mount 时一次性 fetch + warm
        const { MicVAD } = await import('@ricky0123/vad-web');
        const v = await MicVAD.new({
          // INV-17 v3 自托管 · 资源在 public/silero/ + public/silero/ort/
          baseAssetPath: '/silero/',
          onnxWASMBasePath: '/silero/ort/',
          // 路径 B · 注入我们 INV-15 P2 管理的 stream
          getStream: async () => initStreamRef.current(),
          pauseStream: async (_stream: MediaStream) => {
            // silero default 是 stop tracks · 我们走 INV-15 P2 teardown
            // (含 close AudioContext + 清 refs)
            teardownRef.current();
          },
          resumeStream: async (_stream: MediaStream) => {
            // 重建 audio graph + 新 stream(initStream 内部健康检查 + 创建)
            return initStreamRef.current();
          },
          // 用户可调 · 通过 store · 注意:silero 文档示意 thresholds 是构造
          // 时一次性 · 改动需 destroy+new 重建(本期 ship 不支持热更 · 改后
          // 重启 frontend)。
          positiveSpeechThreshold: store.getState().vadPositiveThreshold,
          // negativeSpeechThreshold default 0.25 · 不暴露 UI(per decision #5)
          // minSpeechMs / preSpeechPadMs / frame_samples 用 silero default
          redemptionMs: store.getState().vadRedemptionMs,
          // model default 'legacy'(per decision #8 · 不传 = 用 default)
          onFrameProcessed: (probs) => {
            // 实时 confidence 写 store 给 VadBar 显示
            store.getState().setVadConfidence(probs.isSpeech);
          },
          onSpeechStart: () => {
            // silero 检测到 speech 进 recording 状态 · status='listening' 同
            // 旧 startRecorder 路径语义。silero 内部已开始 buffer audio · 我
            // 们不需要 MediaRecorder。
            store.getState().setVadState('recording');
            store.getState().setRecording(true);
            store.getState().setStatus('listening');
          },
          onSpeechEnd: (audio: Float32Array) => {
            // silero 收尾 · 给完整 Float32 段(16kHz mono)
            // 注:audio 长度含 preSpeechPadMs(800ms default)前 padding
            store.getState().setRecording(false);
            store.getState().setStatus('idle');
            store.getState().setVadState('active');
            lastRecordingEndRef.current = Date.now();
            if (store.getState().micMuted) {
              console.log('[silero] mic muted · drop voice segment');
              return;
            }
            try {
              const b64 = float32ToWavBase64(audio, 16000);
              sendVoiceRef.current(b64);
            } catch (e) {
              console.error('[silero] Float32→WAV→base64 failed:', e);
            }
          },
          onVADMisfire: () => {
            // 段太短(< minSpeechMs default 400)· silero 视作 false positive ·
            // 不送 ASR · 回 active 待新段
            console.log('[silero] VAD misfire (segment < minSpeechMs)');
            store.getState().setRecording(false);
            store.getState().setStatus('idle');
            store.getState().setVadState('active');
          },
        });
        if (cancelled) {
          // mount 期间组件已卸载 · destroy 避免泄漏
          try { v.destroy(); } catch {/* ignore */}
          return;
        }
        micVadRef.current = v;
        store.getState().setVadReady(true);
        console.log('[silero] MicVAD ready');
      } catch (e) {
        console.error('[silero] init failed · fallback to manual mode:', e);
        if (cancelled) return;
        store.getState().setVadReady(false);
        // 强制 manual mode · 用户 mic 按钮仍能 startManual 走 MediaRecorder
        store.getState().setRecordingMode('manual');
        store.getState().pushNotification({
          type: 'notify',
          content: 'VAD 初始化失败 · 已切换手动录音',
        });
      }
    })();
    return () => {
      cancelled = true;
      const v = micVadRef.current;
      micVadRef.current = null;
      if (v) {
        try { v.destroy(); } catch {/* ignore */}
      }
    };
    // 仅 mount 一次 · 配置改动(positiveSpeechThreshold / redemptionMs)需要
    // destroy+new · 本期 ship 不支持热更 · 改后重启 frontend(per spec 限制)。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 卸载清理
  useEffect(() => {
    return () => {
      if (rafIdRef.current !== null) cancelAnimationFrame(rafIdRef.current);
      // micVadRef destroy 由上一 useEffect cleanup 处理 · 这里仅 audio graph
      teardownAudioGraph();
    };
  }, [teardownAudioGraph]);

  return { startManual, stopManualAndSend, toggleVad };
}
