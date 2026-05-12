/**
 * v3-G chunk 3b — 角色状态浮动小条。
 *
 * 显示当前 mood emoji + intimacy 数字，hover 展开 thought / activity 两行
 * 闲笔。Widget 模式右下角；Panel 模式 CharacterView 顶部（位置由父组件决
 * 定，本组件只负责"绝对定位 + 内容"）。
 *
 * 数据源：
 *   1. store.currentCharacterState（WS 'state_update' 实时更新）
 *   2. mount 时 fetchCharacterState 拉一次（避免空白）
 *
 * 隐藏开关：store.showCharacterStatePanel（SettingsPanel [角色] section 的
 * "显示状态条" toggle 控制；默认 on，localStorage 持久）。
 */
import { memo, useEffect } from 'react';
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

  // intimacy 0-100 → 颜色温度（蓝→绿→粉）
  const intimacyHue = 200 - Math.round(intimacy * 1.5); // 200 (cool blue) → 50 (warm pink)
  const intimacyColor = `hsl(${intimacyHue}, 70%, 60%)`;

  const containerStyle: React.CSSProperties = {
    position: 'absolute',
    background: 'color-mix(in srgb, var(--color-bg-surface) 88%, transparent)',
    backdropFilter: 'blur(4px)',
    border: '1px solid var(--color-border-subtle)',
    borderRadius: '12px',
    padding: '8px 12px',
    fontSize: '13px',
    color: 'var(--color-text-primary)',
    boxShadow: '0 2px 8px rgba(0,0,0,0.08)',
    zIndex: 30,
    pointerEvents: 'auto',
    minWidth: '120px',
    transition: 'all 0.15s ease',
    // UX-001：Panel 模式 TopBar 高度 = h-10 (40px) + z-50；旧 top: 12px 让
    // CharacterStatePanel 物理上落在 TopBar 0-40px 范围内并被它压住（panel
    // z-30 < TopBar z-50）。这里把 top 抬到 ``calc(TopBar_h + 8px)``，状
    // 态条整体放在 TopBar 下方右侧，不再被 TopBar 遮。z-index 维持 30 即
    // 可（不需要浮在 TopBar 之上）。
    // Widget 模式无 TopBar，沿用右下角不变。
    ...(position === 'widget'
      ? { right: '8px', bottom: '8px' }
      : { right: '16px', top: '48px' }),
  };

  return (
    <div className="character-state-panel group" style={containerStyle}>
      <div className="flex items-center gap-2">
        <span style={{ fontSize: '18px', lineHeight: 1 }}>{emoji}</span>
        <span style={{ color: 'var(--color-text-secondary)', fontSize: '11px' }}>
          {label}
        </span>
        <div className="flex-1" />
        <span
          className="tabular-nums"
          style={{ fontSize: '12px', color: intimacyColor, fontWeight: 600 }}
          title={`亲密度 ${intimacy}/100`}
        >
          {intimacy}<span style={{ opacity: 0.5 }}>/100</span>
        </span>
      </div>
      {/* Intimacy bar */}
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
            background: intimacyColor,
            transition: 'width 0.4s ease',
          }}
        />
      </div>
      {/* Hover-only：thought / activity（容器 group-hover；用 CSS pseudo 简化为始终
          展示但 max-height 0 折叠 + group-hover 展开）*/}
      {(state.thought || state.activity) && (
        <div
          className="hidden group-hover:block"
          style={{
            marginTop: '8px',
            paddingTop: '8px',
            borderTop: '1px dashed var(--color-border-subtle)',
            color: 'var(--color-text-secondary)',
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
