import { useEffect, useRef, useState } from 'react';
import { getTtsAnalyser } from '../lib/ttsAudio';

// v3-E1 step4: TTS 实时振幅 hook（用于 Live2D 口型同步）。
//
// 数据来源：lib/ttsAudio.ts 的 singleton AnalyserNode（fftSize=256，128 bins）。
// 每个 RAF tick 取 byte frequency data 的算术平均，归一化到 0-1，再做：
//   1. 静音阈值（< SILENCE_THRESHOLD 强制 0）—— 防 ambient bin 噪声让嘴乱抖
//   2. 动态范围拉伸（[SILENCE_THRESHOLD, RANGE_TOP] → [0, 1]）—— 实测人声
//      RMS 平均很少超过 0.3，直接传给 ParamMouthOpenY 视觉上嘴张幅极小，
//      所以把 0.05~0.4 这段拉满到 0~1，硬上限 1.0。
//   3. 指数移动平均（alpha=EMA_ALPHA）—— 防 bin 抖动让嘴抽搐
//
// 调参指引：
//   - 嘴张幅还不够 → 把 RANGE_TOP 减小（比如 0.3）
//   - 嘴抖动太厉害 → 把 EMA_ALPHA 减小（比如 0.2）
//   - 静音段嘴有微动 → 把 SILENCE_THRESHOLD 提高（比如 0.08）
//
// StrictMode 双 mount 安全：cleanup 取消 RAF，但**不**断开 analyser
// （analyser 是 module-level singleton，断了其他 Live2DCanvas 实例就没声音了）。
//
// 性能：返回 React state，每帧 setState 触发 setParameterValueById useEffect。
// 60fps state update 在现代 React 里是普通模式，本组件 JSX 极小，无视化压力。

const SILENCE_THRESHOLD = 0.05;
const RANGE_TOP = 0.4;
const RANGE_SPAN = RANGE_TOP - SILENCE_THRESHOLD;
const EMA_ALPHA = 0.3;

export function useAudioAmplitude(): number {
  const [amplitude, setAmplitude] = useState(0);
  const rafRef = useRef<number | null>(null);
  const smoothedRef = useRef(0);

  useEffect(() => {
    let analyser: AnalyserNode;
    try {
      analyser = getTtsAnalyser();
    } catch (err) {
      console.warn('[useAudioAmplitude] no analyser, lipsync disabled', err);
      return;
    }

    const buffer = new Uint8Array(analyser.frequencyBinCount);

    const tick = () => {
      analyser.getByteFrequencyData(buffer);
      let sum = 0;
      for (let i = 0; i < buffer.length; i++) sum += buffer[i];
      const raw = sum / buffer.length / 255;
      // 静音门 → 线性拉伸 [SILENCE_THRESHOLD, RANGE_TOP] 到 [0, 1] → 硬上限 1.0
      const target = raw < SILENCE_THRESHOLD
        ? 0
        : Math.min(1.0, (raw - SILENCE_THRESHOLD) / RANGE_SPAN);
      smoothedRef.current =
        smoothedRef.current * (1 - EMA_ALPHA) + target * EMA_ALPHA;
      setAmplitude(smoothedRef.current);
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);

    return () => {
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
      // singleton analyser 不 disconnect
    };
  }, []);

  return amplitude;
}
