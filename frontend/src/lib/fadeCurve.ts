// UX-007 — Momo 主区消息按 age 渐进淡化的曲线。
//
// 用户决策的视觉规范(任务 spec):
//   age (since message sent)  opacity   scale
//   0 - 60s                    100%      100%      焦点期
//   60s - 2min                 100% → 60% 100%     主要淡化区间
//   2min - 5min                60% → 30%  100% → 92%
//   5min+                      25%(固定) 92%(固定)
//
// 哲学:Live2D **始终是视觉主体**。新消息 1 min 高亮供阅读;之后逐步
// 让位给角色立绘 / 表情。5 min+ 仍保留 25% 可读但不挡焦点。

const MIN_OPACITY = 0.25;
const MIN_SCALE = 0.92;

export interface FadeStyle {
  opacity: number;        // 0..1
  scale: number;          // 0.92..1
}

/**
 * 纯函数:ageMs(performance.now() - msg.ts)→ ``{opacity, scale}``。
 *
 * **不**含 hover 状态 / TTS 例外 — 调用方在外层叠加这些。
 */
export function fadeForAge(ageMs: number): FadeStyle {
  if (!Number.isFinite(ageMs) || ageMs <= 0) {
    return { opacity: 1, scale: 1 };
  }
  const sec = ageMs / 1000;
  // 阶段 1: 0 - 60s,完全可见
  if (sec < 60) return { opacity: 1, scale: 1 };
  // 阶段 2: 60s - 120s,opacity 100% → 60%,scale 不变
  if (sec < 120) {
    const t = (sec - 60) / 60;       // 0 → 1
    return { opacity: 1 - 0.4 * t, scale: 1 };
  }
  // 阶段 3: 120s - 300s,opacity 60% → 30%,scale 100% → 92%
  if (sec < 300) {
    const t = (sec - 120) / 180;     // 0 → 1
    return {
      opacity: 0.6 - 0.3 * t,
      scale: 1 - 0.08 * t,
    };
  }
  // 阶段 4: 300s+,固定 25% / 92%
  return { opacity: MIN_OPACITY, scale: MIN_SCALE };
}
