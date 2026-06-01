import { useAppStore } from '../store';

/**
 * INV-17 v3 (2026-05-28): silero MicVAD 接管后 VadBar 显示 confidence + 双 marker。
 *
 * 显示语义变更:
 *   旧(INV-15 P2):raw max amplitude 0-255 / threshold(单点)
 *   新(INV-17 v3):silero isSpeech probability 0-1 / positiveSpeechThreshold +
 *                  negativeSpeechThreshold(hysteresis 双 marker)
 *
 * 数字 readout:"conf X.XX / pos X.XX / neg X.XX"
 * - max ≥ positive · accent 色 · 进 speech 段
 * - max < negative · secondary 色 · 离开 speech
 * - 中间(positive > max > negative)· 等待 hysteresis · 中性色
 */
export default function VadBar() {
  const recording      = useAppStore((s) => s.recording);
  const vadState       = useAppStore((s) => s.vadState);
  const vadConfidence  = useAppStore((s) => s.vadConfidence);
  const vadPositive    = useAppStore((s) => s.vadPositiveThreshold);
  // silero negative threshold default 0.25 · 不暴露 UI · 直接渲染默认位置
  const NEGATIVE_THRESHOLD_DEFAULT = 0.25;

  // bugfix-4 (4.3): idle 时不渲染 — 避免一道线幻觉。
  const isActive = recording
    || vadState === 'recording'
    || vadState === 'active';
  if (!isActive) {
    return null;
  }

  // confidence 0-1 → 0-100% fill ratio
  const confPct = Math.min(100, Math.max(0, vadConfidence * 100));
  const posPct = Math.min(100, Math.max(0, vadPositive * 100));
  const negPct = Math.min(100, Math.max(0, NEGATIVE_THRESHOLD_DEFAULT * 100));

  // 三档颜色 · 反映 silero hysteresis 状态
  const exceedsPositive = vadConfidence >= vadPositive;
  const belowNegative   = vadConfidence < NEGATIVE_THRESHOLD_DEFAULT;
  // 录音中 → accent · 阈值上 → accent · 中间档 → secondary · 阈值下 → muted
  const fillColor =
    recording || vadState === 'recording' || exceedsPositive
      ? 'color-mix(in srgb, var(--color-accent) 85%, transparent)'
      : belowNegative
        ? 'color-mix(in srgb, var(--color-text-secondary) 35%, transparent)'
        : 'color-mix(in srgb, var(--color-text-secondary) 55%, transparent)';

  return (
    <div className="flex items-center gap-2 px-1">
      {/* progress bar + 双 marker(positive 实线 accent · negative 虚线 secondary) */}
      <div
        className="relative flex-1 h-1.5 rounded-full overflow-hidden"
        style={{ background: 'color-mix(in srgb, var(--color-border) 50%, transparent)' }}
      >
        {/* confidence fill */}
        <div
          className="absolute inset-y-0 left-0 transition-all duration-75"
          style={{
            width: `${confPct}%`,
            background: fillColor,
          }}
        />
        {/* negativeSpeechThreshold marker · secondary 虚线 */}
        <div
          className="absolute inset-y-0 w-px"
          style={{
            left: `${negPct}%`,
            background: 'linear-gradient(to bottom, var(--color-text-secondary) 50%, transparent 50%)',
            backgroundSize: '1px 4px',
            opacity: 0.5,
          }}
          title={`negative: ${NEGATIVE_THRESHOLD_DEFAULT.toFixed(2)}`}
        />
        {/* positiveSpeechThreshold marker · accent 实线 */}
        <div
          className="absolute inset-y-0 w-px"
          style={{
            left: `${posPct}%`,
            background: 'var(--color-text-accent)',
            opacity: 0.75,
          }}
          title={`positive: ${vadPositive.toFixed(2)}`}
        />
      </div>
      {/* 数字诊断 · "conf 0.42 / pos 0.30 / neg 0.25" · 等宽字体让数字位稳 */}
      <div
        className="text-[10px] font-mono tabular-nums select-none leading-tight"
        style={{ color: 'var(--color-text-secondary)' }}
        title="silero isSpeech 实时 / 进入阈值 / 离开阈值 · 数字不动 = stream stale or silero not ready"
      >
        <div>
          <span style={{
            color: exceedsPositive
              ? 'var(--color-text-accent)'
              : 'var(--color-text-secondary)',
          }}>
            conf {vadConfidence.toFixed(2)}
          </span>
        </div>
        <div style={{ opacity: 0.65 }}>
          pos {vadPositive.toFixed(2)} / neg {NEGATIVE_THRESHOLD_DEFAULT.toFixed(2)}
        </div>
      </div>
    </div>
  );
}
