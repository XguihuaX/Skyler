import { useEffect, useRef, useCallback } from 'react';
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

// INV-15 Option H (2026-05-27): 周期 stream 健康检查 frame 间隔。
// vadLoop ~60fps · 每 60 frame ≈ 1s 检查一次 track.readyState · 避免 onended
// 漏 fire(权限快速 revoke / Tauri webview suspend 等场景某些浏览器不 fire)。
const STREAM_HEALTH_CHECK_FRAMES = 60;

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

  const store = useAppStore;

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
    // Option G · 写 store 给 VadBar 实时显示 · 每帧写无防抖(Zustand set 轻量 ·
    // VadBar 一个 div text 渲染开销可忽略 · 用户看 60fps 平滑数字)。
    store.getState().setVadCurrentMax(max);

    // store.vadThreshold 是 0–100，映射到 0–255
    const threshold = (store.getState().vadThreshold / 100) * 255;
    const vadState = store.getState().vadState;
    const recording = store.getState().recording;
    const micMuted = store.getState().micMuted;

    if (micMuted) {
      // Momo 说话期间不录音，但 v3-F #4 在此监听打断：用户说话足够久（连续
      // INTERRUPT_FRAMES 帧高于阈值）就 sendInterrupt。冷却 INTERRUPT_COOLDOWN_MS
      // 防止打断后短时间内被状态切换 race 反复触发。
      const status = store.getState().status;
      const isAiSpeaking = status === 'speaking' || status === 'thinking';
      const cooledDown =
        Date.now() - lastInterruptAtRef.current > INTERRUPT_COOLDOWN_MS;
      if (isAiSpeaking && cooledDown) {
        if (max >= threshold) {
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

    if (vadState === 'active' && max >= threshold && !recording) {
      const stream = streamRef.current;
      if (stream) {
        startRecorder(stream);
        store.getState().setVadState('recording');
        silenceStartRef.current = null;
      }
    } else if (vadState === 'recording' && recording) {
      if (max < threshold) {
        if (silenceStartRef.current === null) {
          silenceStartRef.current = Date.now();
        } else if (Date.now() - silenceStartRef.current >= store.getState().silenceTimeoutMs) {
          stopAndSend().then(() => {
            store.getState().setVadState('active');
            silenceStartRef.current = null;
          });
        }
      } else {
        silenceStartRef.current = null;
      }
    } else if (vadState === 'active' && !recording) {
      // idle timeout：60s 无录音回 sleep
      if (Date.now() - lastRecordingEndRef.current >= store.getState().vadIdleTimeoutMs) {
        store.getState().setVadState('sleep');
        // 不释放 stream，下次 toggleVad 可复用
      }
    }

    rafIdRef.current = requestAnimationFrame(vadLoop);
  }, [recoverStream, startRecorder, stopAndSend, store]);

  const toggleVad = useCallback(async (): Promise<void> => {
    const current = store.getState().vadState;
    if (current === 'sleep') {
      await initStream();
      store.getState().setVadState('active');
      lastRecordingEndRef.current = Date.now();
      if (rafIdRef.current === null) {
        rafIdRef.current = requestAnimationFrame(vadLoop);
      }
    } else {
      // active 或 recording → sleep
      if (store.getState().recording) {
        await stopAndSend();
      }
      store.getState().setVadState('sleep');
      // Option G · sleep 时把 currentMax 清零 · VadBar 不显示陈旧数字
      store.getState().setVadCurrentMax(0);
      if (rafIdRef.current !== null) {
        cancelAnimationFrame(rafIdRef.current);
        rafIdRef.current = null;
      }
    }
  }, [initStream, vadLoop, stopAndSend, store]);

  // 卸载清理
  useEffect(() => {
    return () => {
      if (rafIdRef.current !== null) cancelAnimationFrame(rafIdRef.current);
      teardownAudioGraph();
    };
  }, [teardownAudioGraph]);

  return { startManual, stopManualAndSend, toggleVad };
}
