/**
 * v3-G chunk 3b — 角色状态浮动小条。
 *
 * Round 4 ①(2026-06-04)起改成小心情标:默认只渲 emoji + 词,hover 或 click
 * 锁定展开完整卡(intimacy 数字 + 进度条 + activity / thought)。
 *
 * Widget 模式:锚 App 外层 relative 容器右下角(right:8 bottom:8)。
 * Panel 模式:锚 Panel 根容器(整窗)左上角(left:8 top:48)· TopBar 下方 8px ·
 * dock 上方(dock 垂直居中,顶端远在心情标下方)· ConvList 浮卡左上(ConvList
 * 在 left:80 top:60)→ 三者错位,关 / 开会话两态都不重叠。
 *
 * 数据源：
 *   1. store.currentCharacterState（WS 'state_update' 实时更新）
 *   2. mount 时 fetchCharacterState 拉一次（避免空白）
 *
 * 隐藏开关：store.showCharacterStatePanel（SettingsPanel [角色] section 的
 * "显示状态条" toggle 控制；默认 on，localStorage 持久）。
 */
import { memo, useEffect, useState } from 'react';
import { useAppStore } from '../store';
import {
  fetchCharacterState,
  type CharacterMood,
  type CharacterStateResponse,
} from '../lib/integrations';

const MOOD_EMOJI: Record<CharacterMood, string> = {
  happy: '😊',
  sad: '😢',
  curious: '🤔',
  calm: '😌',
  excited: '✨',
  tired: '😴',
  neutral: '🙂',
};

const MOOD_LABEL: Record<CharacterMood, string> = {
  happy: '开心',
  sad: '低落',
  curious: '好奇',
  calm: '平静',
  excited: '兴奋',
  tired: '疲惫',
  neutral: '平和',
};

interface CharacterStatePanelProps {
  /**
   * Position preset:
   *   - 'widget' — Widget 模式右下角小条
   *   - 'panel'  — Panel 模式 CharacterView 顶部稍偏右
   */
  position?: 'widget' | 'panel';
}

const CharacterStatePanel = memo(function CharacterStatePanel({
  position = 'widget',
}: CharacterStatePanelProps) {
  const show           = useAppStore((s) => s.showCharacterStatePanel);
  const state          = useAppStore((s) => s.currentCharacterState);
  const setState       = useAppStore((s) => s.setCurrentCharacterState);
  const characterId    = useAppStore((s) => s.currentCharacterId);

  // 2026-06-04 · Round 4 ① 心情小标 · 默认 emoji+词,hover/click 展开成完整卡。
  // 2026-06-06 · widget 态:展开态也去 glass 壳(展开后 intimacy/进度条/activity/
  // thought 全部裸显 + text-shadow,无 glass 容器/border/radius/shadow/blur);
  // hover/click 展开行为保留(照常能开卡看信息)。panel 态完整 glass 容器不动。
  const [pinned, setPinned] = useState(false);
  const [hovering, setHovering] = useState(false);
  const isWidget = position === 'widget';
  const expanded = pinned || hovering;

  // mount + character switch 时拉一次（保证 panel 一开就有内容，无需等 WS 推送）
  useEffect(() => {
    let cancelled = false;
    if (characterId == null) return;
    fetchCharacterState(characterId)
      .then((r: CharacterStateResponse) => { if (!cancelled) setState(r); })
      .catch((e) => console.warn('[CharacterStatePanel] fetch failed:', e));
    return () => { cancelled = true; };
  }, [characterId, setState]);

  if (!show) return null;
  if (!state) return null;

  const mood = (state.mood as CharacterMood) || 'neutral';
  const emoji = MOOD_EMOJI[mood] ?? '🙂';
  const label = MOOD_LABEL[mood] ?? mood;
  const intimacy = state.intimacy ?? 0;

  // intimacy 0-100 → 进度条颜色温度(蓝→绿→粉)。
  // Round 4 ④ 后续(2026-06-04):饱和度 70% → 40% 降跳,跟蓝壁纸 + 暖角色不打架。
  // 数字本身改 var(--color-accent) 跟主题主色绑,见下方 JSX(不再消费 intimacyColor)。
  const intimacyHue = 200 - Math.round(intimacy * 1.5); // 200 (cool blue) → 50 (warm pink)
  const intimacyBarColor = `hsl(${intimacyHue}, 40%, 60%)`;

  const containerStyle: React.CSSProperties = {
    position: 'absolute',
    // Round 4 ④(2026-06-04):吃 glass-* 统一 token · radius 12 → 16 跟齐 ·
    // blur 8 → 12 跟齐 · alpha 65% → 58%(--glass-bg)· 删硬编码 shadow 改用
    // glass-shadow · 文字色改 glass-text(标题)/ glass-text-muted(label)/ 加
    // glass-text-shadow 让字在花壁纸上能读清。
    // 2026-06-06 · widget 态不分收/展开都去 glass 壳(emoji/词/intimacy/进度条/
    // activity/thought 全部裸显 + textShadow 防糊);panel 态完整 glass 容器不动。
    //   - widget:transparent / no border / radius 0 / no shadow / no blur ·
    //     padding 4 0 让收起态视觉高度跟左侧 StatusBadge 同款(StatusBadge =
    //     text-xs 12px + line-height 16 + py-1 = 24px 总高 · 心情标 padding 4
    //     0 + emoji 16 + label 12 + line-height 16 同样 24px 总高,横向左右对齐)。
    //   - panel:--glass-* 一整套(多行内容容器仍是阅读需要)。
    ...(isWidget
      ? {
          background: 'transparent',
          border: 'none',
          borderRadius: 0,
          padding: '4px 0',
          boxShadow: 'none',
          // backdropFilter 显式 none · 防主题切换时 var fallback 漏 blur
          backdropFilter: 'none',
          WebkitBackdropFilter: 'none',
        }
      : {
          background: 'var(--glass-bg)',
          backdropFilter: 'blur(var(--glass-blur))',
          WebkitBackdropFilter: 'blur(var(--glass-blur))',
          border: 'var(--glass-border)',
          borderRadius: 'var(--glass-radius)',
          padding: '8px 12px',
          boxShadow: 'var(--glass-shadow)',
        }),
    fontSize: '13px',
    color: 'var(--glass-text)',
    textShadow: 'var(--glass-text-shadow)',
    zIndex: 30,
    pointerEvents: 'auto',
    // Round 4 ① 心情小标 · minWidth 移除让默认态按内容紧凑撑 · transition 过渡。
    transition: 'all 0.15s ease',
    cursor: 'pointer',
    // Panel:left:8 top:48 锚 Panel 根容器(整窗) · TopBar h-10(40px) 下方 8px ·
    //   dock(垂直居中) / ConvList 浮卡(top:60 left:80) 均在它右下方 · 不重叠。
    // Widget(2026-06-06 五次挪位):right:12 top:12 跟左上 StatusBadge(left:12
    //   top:12)左右平齐 · 视觉同高度同款角标(StatusBadge / 心情标都用 24px 总高 ·
    //   见上方 padding 注释)。
    //   历史:① right:8 bottom:8 撞底部坨 → ② left:12 top:44 飘空气 →
    //   ③ right:12 top:44 贴她中部偏上 → ④ right:8 top:8 顶死右上 →
    //   ⑤ right:12 top:12 跟 StatusBadge 平齐(本次)。
    ...(position === 'widget'
      ? { right: '12px', top: '12px' }
      : { left: '8px', top: '48px' }),
  };

  return (
    <div
      className="character-state-panel"
      style={containerStyle}
      onClick={(e) => { e.stopPropagation(); setPinned((p) => !p); }}
      onMouseEnter={() => setHovering(true)}
      onMouseLeave={() => setHovering(false)}
      role="button"
      tabIndex={0}
      aria-label={pinned ? '收起心情卡' : '展开心情卡'}
    >
      <div className="flex items-center gap-2">
        {/* widget 态:emoji 16 + label 12 + line-height 16 → 跟左侧 StatusBadge
            (text-xs 12 / line-height 16 / py-1)同视觉高度 24px。panel 态保留
            原 18 / 11 紧凑卡视觉。 */}
        <span style={{ fontSize: isWidget ? '16px' : '18px', lineHeight: isWidget ? '16px' : 1 }}>{emoji}</span>
        <span style={{
          color: 'var(--glass-text-muted)',
          fontSize: isWidget ? '12px' : '11px',
          lineHeight: isWidget ? '16px' : undefined,
        }}>
          {label}
        </span>
        {expanded && (
          <>
            <div className="flex-1" style={{ minWidth: '8px' }} />
            <span
              className="tabular-nums"
              style={{ fontSize: '12px', color: 'var(--color-accent)', fontWeight: 600 }}
              title={`亲密度 ${intimacy}/100`}
            >
              {intimacy}<span style={{ opacity: 0.5 }}>/100</span>
            </span>
          </>
        )}
      </div>
      {expanded && (
        <div
          style={{
            height: '3px',
            marginTop: '6px',
            background: 'var(--color-bg-input)',
            borderRadius: '2px',
            overflow: 'hidden',
          }}
        >
          <div
            style={{
              width: `${intimacy}%`,
              height: '100%',
              background: intimacyBarColor,
              transition: 'width 0.4s ease',
            }}
          />
        </div>
      )}
      {expanded && (state.thought || state.activity) && (
        <div
          style={{
            marginTop: '8px',
            paddingTop: '8px',
            borderTop: '1px dashed var(--color-border-subtle)',
            color: 'var(--glass-text-muted)',
            // Round 4 ④ 后续:显式 textShadow(虽然 CSS text-shadow 本身从父继承,
            // 但 muted 浅色文字在 50% 透玻璃 + 花壁纸上最容易糊 · 显式声明防御
            // 未来谁加 textShadow: none 把它清掉 + 阅读代码时意图清晰)。
            textShadow: 'var(--glass-text-shadow)',
            fontSize: '11px',
            lineHeight: 1.4,
          }}
        >
          {state.activity && (
            <div>📍 {state.activity}</div>
          )}
          {state.thought && (
            <div style={{ marginTop: '2px' }}>💭 {state.thought}</div>
          )}
        </div>
      )}
    </div>
  );
});

export default CharacterStatePanel;
