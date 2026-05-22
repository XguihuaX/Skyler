/**
 * v4-fan chunk 4 — Character Detail Modal。
 *
 * 进入路径:Gallery browse 态点中心卡 → Gallery setMode('detail', char)
 *  → 本 modal 全屏 overlay 渲染。
 *
 * Hero animation(framer-motion shared layout):
 *   - 每张 CharacterCard wrapper 在 FanLayout 里都包了
 *     ``<motion.div layoutId={`fan-card-${id}`}>``。
 *   - 本 modal 渲染 ``<motion.div layoutId={`fan-card-${selected.id}`}>``,
 *     framer 自动 from(browse rect)→ to(detail rect)平滑过渡。
 *   - browse 卡在 hero 期间:由 FanLayout 接收 ``hideHeroForId`` prop,把
 *     该卡 wrapper opacity → 0(避免两张同 layoutId 视觉打架)。
 *   - AnimatePresence + initial/animate/exit:fade backdrop;layoutId 自带
 *     反向 reverse animation。
 *
 * 字段缺位处理:
 *   - tagline / interests:DB 暂无字段,显示空段不渲染(留 Fan-6 决策)
 *   - persona:nullable;长 > 200 字符 truncate + 「展开」(本地 state)
 *   - character_state:per-modal mount 拉一次 ``/api/characters/{id}/state``,
 *     失败静默(不阻断 modal)。store.currentCharacterState 只覆盖 *active*
 *     角色,detail 显示的可能是别的角色。
 *
 * ESC + 点 backdrop 都关闭。CTA "切换到这个角色" → onSwitch(id)(由 Gallery
 * 决定后续:setCurrentCharacterId + galleryOpen=false)。
 */
import { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import { X, Sparkles } from 'lucide-react';
import CharacterCard from './CharacterCard';
import { fetchCharacterState, type CharacterStateResponse, type CharacterMood } from '../../lib/integrations';
import type { CharacterRow } from '../../lib/config';
// v4 segment 2 D-S2-1:用 active variant 取代旧 character.persona 文本展示
import { getActivePersona, type CharacterPersonaRow } from '../../lib/personas';
// v4.0 voice greeting:onMount 随机播放 voice line(per PM dispatch 2026-05-22)
import { playRandomVoiceGreeting } from '../../lib/voice_lines';

const MOOD_EMOJI: Record<CharacterMood, string> = {
  happy: '😊', sad: '😢', curious: '🤔', calm: '😌',
  excited: '✨', tired: '😴', neutral: '🙂',
};
const MOOD_LABEL: Record<CharacterMood, string> = {
  happy: '开心', sad: '低落', curious: '好奇', calm: '平静',
  excited: '兴奋', tired: '疲惫', neutral: '平和',
};

interface CharacterDetailModalProps {
  character: CharacterRow;
  onClose: () => void;
  onSwitch: (id: number) => void;
}

export default function CharacterDetailModal({
  character, onClose, onSwitch,
}: CharacterDetailModalProps) {
  const [state, setState] = useState<CharacterStateResponse | null>(null);
  // v4 segment 2:展示 active variant 名 + description + style_preset
  // 替代 character.persona 自由文本(后者在 v4 已 deprecated)。
  const [activePersona, setActivePersona] = useState<CharacterPersonaRow | null>(null);

  // ESC close
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  // Per-mount fetch character state(detail 角色可能不是当前 active 角色)
  useEffect(() => {
    let cancelled = false;
    setState(null);
    fetchCharacterState(character.id)
      .then((s) => {
        if (!cancelled) setState(s);
      })
      .catch((err) => {
        // 静默:detail modal 不该因 state 拉取失败而崩
        console.warn('[CharacterDetailModal] fetchCharacterState failed:', err);
      });
    return () => { cancelled = true; };
  }, [character.id]);

  // v4 segment 2:per-mount 拉 active variant。无 active(eg 老 character 没
  // run segment-1 migration)→ 仍 silent,只是 Persona 区不出现。
  useEffect(() => {
    let cancelled = false;
    setActivePersona(null);
    getActivePersona(character.id)
      .then((p) => { if (!cancelled) setActivePersona(p); })
      .catch(() => { /* silent — 旧角色无 active variant 时 404 是正常 */ });
    return () => { cancelled = true; };
  }, [character.id]);

  // v4.0 voice greeting · per PM dispatch 2026-05-22:
  // 立绘馆放大 onEnter(本 modal mount)→ fetch 1 random voice line + play。
  // 空 list / fetch fail 静默不播(per spec);unmount 时 pause 防 leak。
  useEffect(() => {
    let cancelled = false;
    let audioEl: HTMLAudioElement | null = null;
    playRandomVoiceGreeting(character.id).then((a) => {
      if (cancelled) {
        // 用户已 close modal,pause 当前 audio(若有)
        if (a) a.pause();
      } else {
        audioEl = a;
      }
    });
    return () => {
      cancelled = true;
      if (audioEl) {
        try { audioEl.pause(); } catch { /* ignore */ }
      }
    };
  }, [character.id]);

  return (
    <>
      {/* Backdrop:fade + blur(brightness 压住底层 fan)。click 关闭。
          backdrop-filter 已在 Fan-2 spike 验证 ≥55fps,只一层 overlay 风险低。 */}
      <motion.div
        className="fixed inset-0 z-[1000]"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={{ duration: 0.25, ease: 'easeOut' }}
        style={{
          backdropFilter:        'blur(8px) brightness(0.45)',
          WebkitBackdropFilter:  'blur(8px) brightness(0.45)',
          background:            'rgba(0, 0, 0, 0.25)',
        }}
        onClick={onClose}
      />

      {/* 内容层。click 不冒泡到 backdrop。 */}
      <div
        className="fixed inset-0 z-[1001] pointer-events-none flex items-center justify-center"
      >
        <div
          className="relative pointer-events-auto flex gap-8 items-center"
          onClick={(e) => e.stopPropagation()}
        >
          {/* Hero 卡片(共享 layoutId,framer-motion 从 browse → detail 自动 morph) */}
          <motion.div
            layoutId={`fan-card-${character.id}`}
            // initial / animate / exit 不需要——layoutId 自身带 from-to 动画
            transition={{
              layout: { duration: 0.45, ease: [0.22, 1, 0.36, 1] },
            }}
            style={{ zIndex: 2 }}
          >
            <CharacterCard
              character={character}
              variant="detail"
            />
          </motion.div>

          {/* 信息面板 */}
          <motion.div
            initial={{ opacity: 0, x: 24 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: 24 }}
            transition={{ duration: 0.35, ease: 'easeOut', delay: 0.15 }}
            className="w-[360px] rounded-2xl p-6 shadow-2xl"
            style={{
              background:
                'color-mix(in srgb, var(--color-bg-surface) 88%, transparent)',
              border: '1px solid var(--color-border-subtle)',
              color:  'var(--color-text-primary)',
              maxHeight: '600px',
              overflowY: 'auto',
            }}
          >
            <h2 className="text-2xl font-semibold mb-1 leading-tight">
              {character.name}
            </h2>

            {/* tagline:DB 暂无字段。Fan-6 决定加 schema 后再渲染。
                现在留这个段只为 visual layout 占位:不渲染。 */}

            {/* character state(per-mount fetch) */}
            {state && (
              <div
                className="text-xs mb-4 flex items-center gap-2"
                style={{ color: 'var(--color-text-secondary)' }}
              >
                <span title={MOOD_LABEL[state.mood]} style={{ fontSize: 16 }}>
                  {MOOD_EMOJI[state.mood] ?? '🙂'}
                </span>
                <span>{MOOD_LABEL[state.mood] ?? state.mood}</span>
                <span style={{ opacity: 0.5 }}>·</span>
                <span>亲密度 {state.intimacy}</span>
              </div>
            )}

            {/* v4 segment 2 D-S2-1:展示 active variant 名 + description,
                替代旧 character.persona 自由文本(后者已 deprecated)。 */}
            {activePersona && (
              <div className="mb-5">
                <div
                  className="text-[10px] uppercase tracking-wider mb-1.5"
                  style={{ color: 'var(--color-text-secondary)', opacity: 0.7 }}
                >
                  Persona
                </div>
                <div className="flex items-baseline gap-2 mb-1 flex-wrap">
                  <span
                    className="text-base font-medium"
                    style={{ color: 'var(--color-text-primary)' }}
                  >
                    {activePersona.identity?.name?.trim()
                      || activePersona.variant_name}
                  </span>
                  <span
                    className="text-[10px] px-1.5 py-0.5 rounded"
                    style={{
                      background: activePersona.is_builtin
                        ? 'color-mix(in srgb, var(--color-accent) 40%, transparent)'
                        : 'var(--color-bg-elevated)',
                      color: 'var(--color-text-secondary)',
                    }}
                  >
                    {activePersona.variant_name}
                    {activePersona.is_builtin ? ' · 系统预设' : ' · 自定义'}
                  </span>
                </div>
                {activePersona.description && (
                  <p
                    className="text-sm leading-relaxed"
                    style={{ color: 'var(--color-text-primary)' }}
                  >
                    {activePersona.description}
                  </p>
                )}
                <p
                  className="text-[11px] mt-1"
                  style={{ color: 'var(--color-text-secondary)' }}
                >
                  风格预设:{activePersona.style_preset}
                </p>
              </div>
            )}

            {/* state thought / activity 闲笔(state 有值时显示) */}
            {state && (state.thought || state.activity) && (
              <div className="mb-5 space-y-1.5">
                {state.thought && (
                  <p
                    className="text-xs italic"
                    style={{ color: 'var(--color-text-secondary)' }}
                  >
                    💭 {state.thought}
                  </p>
                )}
                {state.activity && (
                  <p
                    className="text-xs italic"
                    style={{ color: 'var(--color-text-secondary)' }}
                  >
                    🌀 {state.activity}
                  </p>
                )}
              </div>
            )}

            {/* CTA */}
            <button
              type="button"
              onClick={() => onSwitch(character.id)}
              className="mt-2 w-full rounded-lg px-4 py-2.5 text-sm font-medium transition flex items-center justify-center gap-2"
              style={{
                background: 'var(--color-accent)',
                color:      'var(--color-bubble-user-text)',
              }}
              onMouseEnter={(e) =>
                (e.currentTarget.style.background = 'var(--color-accent-hover)')
              }
              onMouseLeave={(e) =>
                (e.currentTarget.style.background = 'var(--color-accent)')
              }
            >
              <Sparkles size={14} />
              切换到这个角色
            </button>
          </motion.div>

          {/* close button(modal 角) */}
          <motion.button
            type="button"
            initial={{ opacity: 0, scale: 0.85 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.85 }}
            transition={{ duration: 0.25, delay: 0.1 }}
            onClick={onClose}
            className="absolute -top-3 -right-3 w-9 h-9 rounded-full flex items-center justify-center transition shadow-lg"
            style={{
              background: 'var(--color-bg-elevated)',
              color:      'var(--color-text-primary)',
              border:     '1px solid var(--color-border)',
            }}
            title="关闭(Esc)"
          >
            <X size={16} />
          </motion.button>
        </div>
      </div>
    </>
  );
}
