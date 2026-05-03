import { useAppStore } from '../store';

export default function VadBar() {
  const recording = useAppStore((s) => s.recording);
  const vadState  = useAppStore((s) => s.vadState);

  // 录音中 → 强调色；VAD active → 弱亮；其他 → 边框色
  const fillColor =
    vadState === 'recording' || recording
      ? 'color-mix(in srgb, var(--color-accent) 80%, transparent)'
      : vadState === 'active'
      ? 'color-mix(in srgb, var(--color-text-secondary) 40%, transparent)'
      : 'color-mix(in srgb, var(--color-border) 40%, transparent)';

  return (
    <div
      className="h-1 w-full rounded-full transition-colors duration-200"
      style={{ background: fillColor }}
    />
  );
}
