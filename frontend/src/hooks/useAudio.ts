import { useEffect, useRef, useCallback } from 'react';
import { useAppStore } from '../store';

interface UseAudioParams {
  sendVoice: (audioBase64: string) => void;
}

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

export function useAudio({ sendVoice }: UseAudioParams): UseAudioReturn {
  const audioContextRef = useRef<AudioContext | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const dataArrayRef = useRef<Uint8Array | null>(null);
  const rafIdRef = useRef<number | null>(null);
  const silenceStartRef = useRef<number | null>(null);
  const lastRecordingEndRef = useRef<number>(Date.now());
  const recordedChunksRef = useRef<Blob[]>([]);

  const store = useAppStore;

  // 始终持有最新 sendVoice 引用（避免 useCallback 闭包过期）
  const sendVoiceRef = useRef(sendVoice);
  useEffect(() => { sendVoiceRef.current = sendVoice; });

  /** 申请麦克风权限并初始化 AudioContext + Analyser */
  const initStream = useCallback(async (): Promise<MediaStream> => {
    if (streamRef.current) return streamRef.current;
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    streamRef.current = stream;
    const ctx = new AudioContext();
    audioContextRef.current = ctx;
    const source = ctx.createMediaStreamSource(stream);
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 1024;
    source.connect(analyser);
    analyserRef.current = analyser;
    dataArrayRef.current = new Uint8Array(analyser.frequencyBinCount);
    return stream;
  }, []);

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

    analyser.getByteFrequencyData(dataArray);
    let max = 0;
    for (let i = 0; i < dataArray.length; i++) {
      if (dataArray[i] > max) max = dataArray[i];
    }
    // store.vadThreshold 是 0–100，映射到 0–255
    const threshold = (store.getState().vadThreshold / 100) * 255;
    const vadState = store.getState().vadState;
    const recording = store.getState().recording;
    const micMuted = store.getState().micMuted;

    if (micMuted) {
      // Momo 说话期间跳过检测，但保持 stream 开启
      rafIdRef.current = requestAnimationFrame(vadLoop);
      return;
    }

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
  }, [startRecorder, stopAndSend, store]);

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
      if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
        mediaRecorderRef.current.stop();
      }
      if (streamRef.current) {
        streamRef.current.getTracks().forEach((t) => t.stop());
      }
      if (audioContextRef.current) {
        audioContextRef.current.close();
      }
    };
  }, []);

  return { startManual, stopManualAndSend, toggleVad };
}
