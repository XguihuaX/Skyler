import { useAppStore } from '../store';

export default function VadBar() {
  const recording = useAppStore((s) => s.recording);
  const vadState  = useAppStore((s) => s.vadState);

  // bugfix-4 (4.3): idle 时不渲染 — 老逻辑用 border-40% 作 idle 色,在小窗模式
  // 显示成一道横线,用户视觉上误以为是 chrome / 分割线。只有 recording / VAD
  // active 时才显示反馈条。
  const isActive = recording
    || vadState === 'recording'
    || vadState === 'active';
  if (!isActive) {
    return null;
  }

  // 录音中 → 强调色;VAD active → 弱亮
  const fillColor =
    recording || vadState === 'recording'
      ? 'color-mix(in srgb, var(--color-accent) 80%, transparent)'
      : 'color-mix(in srgb, var(--color-text-secondary) 40%, transparent)';

  return (
    <div
      className="h-1 w-full rounded-full transition-colors duration-200"
      style={{ background: fillColor }}
    />
  );
}
