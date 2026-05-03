import { useEffect, useRef, useState } from 'react';
import { useAppStore } from '../store';

interface AsrPreviewProps {
  text: string;
  timestamp: number;
}

export default function AsrPreview({ text, timestamp }: AsrPreviewProps) {
  const recording = useAppStore((s) => s.recording);

  const [visible, setVisible] = useState(false);
  const [opacity, setOpacity] = useState(0);
  const [fadeDuration, setFadeDuration] = useState(250);
  const timerRef = useRef<number | null>(null);
  const fadeRef = useRef<number | null>(null);
  const rafRef = useRef<number | null>(null);
  const currentTimestampRef = useRef(timestamp);

  useEffect(() => {
    if (!text) return;

    currentTimestampRef.current = timestamp;

    if (timerRef.current !== null) clearTimeout(timerRef.current);
    if (fadeRef.current !== null) clearTimeout(fadeRef.current);
    if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);

    setVisible(true);
    setFadeDuration(250);
    setOpacity(0);

    rafRef.current = requestAnimationFrame(() => {
      rafRef.current = requestAnimationFrame(() => {
        setOpacity(1);
      });
    });

    const capturedTimestamp = timestamp;
    timerRef.current = window.setTimeout(() => {
      setFadeDuration(500);
      setOpacity(0);
      fadeRef.current = window.setTimeout(() => {
        if (currentTimestampRef.current === capturedTimestamp) {
          useAppStore.setState({ asrText: '' });
          setVisible(false);
        }
      }, 500);
    }, 5000);

    return () => {
      if (timerRef.current !== null) clearTimeout(timerRef.current);
      if (fadeRef.current !== null) clearTimeout(fadeRef.current);
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
    };
  }, [timestamp]);

  // 录音中但 ASR 结果未到：显示占位
  if (recording && !text) {
    return (
      <div
        className="max-w-[280px] backdrop-blur-md text-sm rounded-xl px-4 py-2"
        style={{
          background: 'color-mix(in srgb, var(--color-bg-surface) 70%, transparent)',
          color: 'var(--color-text-secondary)',
        }}
      >
        识别中…
      </div>
    );
  }

  if (!visible) return null;

  return (
    <div
      className="max-w-[280px] backdrop-blur-md text-sm rounded-xl px-4 py-2 line-clamp-3"
      style={{
        background: 'color-mix(in srgb, var(--color-bg-surface) 70%, transparent)',
        color: 'var(--color-text-primary)',
        opacity,
        transition: `opacity ${fadeDuration}ms ease`,
      }}
    >
      {text}
    </div>
  );
}
