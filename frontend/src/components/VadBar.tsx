import { useAppStore } from '../store';

export default function VadBar() {
  const recording = useAppStore((s) => s.recording);
  const vadState  = useAppStore((s) => s.vadState);
  // INV-15 P2 Option G(2026-05-27): 实时 max + threshold 数字诊断
  const vadCurrentMax = useAppStore((s) => s.vadCurrentMax);
  const vadThreshold  = useAppStore((s) => s.vadThreshold);

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

  // INV-15 P2 Option G · 0-255 raw max 映射到 0-100 显示尺度(跟 vadThreshold 同
  // 量级)· 用户对比直观。
  const maxDisplay = Math.round((vadCurrentMax / 255) * 100);
  // bar 填充比例 · cap 100% · 超过 threshold 时着重显示(语义上"该录音了")
  const barPctRaw = Math.min(100, (vadCurrentMax / 255) * 100);
  const barPct = Math.max(0, barPctRaw);
  const exceedsThreshold = maxDisplay >= vadThreshold;

  return (
    <div className="flex items-center gap-2 px-1">
      {/* progress bar + threshold marker */}
      <div className="relative flex-1 h-1.5 rounded-full overflow-hidden"
        style={{ background: 'color-mix(in srgb, var(--color-border) 50%, transparent)' }}
      >
        {/* fill (current max) */}
        <div
          className="absolute inset-y-0 left-0 transition-all duration-75"
          style={{
            width: `${barPct}%`,
            background: exceedsThreshold
              ? 'color-mix(in srgb, var(--color-accent) 90%, transparent)'
              : fillColor,
          }}
        />
        {/* threshold marker · 垂直虚线 */}
        <div
          className="absolute inset-y-0 w-px"
          style={{
            left: `${vadThreshold}%`,
            background: 'var(--color-text-secondary)',
            opacity: 0.6,
          }}
        />
      </div>
      {/* 数字诊断 readout · "now / threshold" · 等宽字体让数字位稳 */}
      <div className="text-[10px] font-mono tabular-nums select-none"
        style={{ color: 'var(--color-text-secondary)' }}
        title="左:当前麦克风音量 · 右:触发阈值 · 数字不动 = mic 流可能 stale"
      >
        <span style={{
          color: exceedsThreshold
            ? 'var(--color-text-accent)'
            : 'var(--color-text-secondary)',
        }}>
          {String(maxDisplay).padStart(3, ' ')}
        </span>
        <span style={{ opacity: 0.5 }}> / {vadThreshold}</span>
      </div>
    </div>
  );
}
