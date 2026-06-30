/**
 * v4-fan chunk 4 — Character Detail Modal · Build 1 充实版。
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
 *
 * Build 1 改动(2026-06-20):
 *   - persona 展示从「200 字截断 description」升级成 Tier-1 全字段平铺
 *     (identity / personality_core / speech_style / signature_phrases /
 *      lore / relationship_to_user)· 空字段显示「未设置」占位
 *   - 加「编辑人设」按钮 → 复用现成 PersonaEditorModal · 保存后 refetch
 *     getActivePersona 刷新本面板
 *   - Live2D 引用行(只读 character.live2d_model + 跳能力页 CTA)
 *   - 3 个「即将推出」占位卡:生活(dailyagent)/ 生活记忆 / 立绘生成(ComfyUI)
 *   - 信息面板宽度从 360px → 460px,maxHeight 600 → 80vh,内容铺得开
 *
 * 编辑器层级处理:PersonaEditorModal 用 z-50,本 modal 用 z-[1001]。
 * 用 wrapper ``position: relative; zIndex: 2000`` 给 editor 创建新 stacking
 * context · 让它的 fixed 子元素叠在本 modal 之上 · 同时本 modal 不 unmount
 * (避免 layoutId hero 动画反向闪)。
 */
import { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import { X, Sparkles, Edit3, ChevronDown, ChevronRight } from 'lucide-react';
import CharacterCard from './CharacterCard';
import { fetchCharacterState, type CharacterStateResponse, type CharacterMood } from '../../lib/integrations';
import type { CharacterRow } from '../../lib/config';
// v4 segment 2 D-S2-1:用 active variant 取代旧 character.persona 文本展示
import { getActivePersona, type CharacterPersonaRow } from '../../lib/personas';
// DailyAgent Stage1-viz:今日日程 live 区块
import { fetchTodayPlan, type TodayPlan } from '../../lib/daily_plan';
// v4.0 voice greeting:onMount 随机播放 voice line(per PM dispatch 2026-05-22)
import { playRandomVoiceGreeting } from '../../lib/voice_lines';
import PersonaEditorModal from '../PersonaEditorModal';
import { useAppStore } from '../../store';

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
  const [activePersona, setActivePersona] = useState<CharacterPersonaRow | null>(null);
  const [plan, setPlan] = useState<TodayPlan | null>(null);
  const [editorOpen, setEditorOpen] = useState(false);
  const setActiveOverlay = useAppStore((s) => s.setActiveOverlay);
  const setGalleryOpen = useAppStore((s) => s.setGalleryOpen);

  // ESC close(editor 打开时让 editor 自己处理 ESC,不重复)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !editorOpen) onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose, editorOpen]);

  // Per-mount fetch character state(detail 角色可能不是当前 active 角色)
  useEffect(() => {
    let cancelled = false;
    setState(null);
    fetchCharacterState(character.id)
      .then((s) => {
        if (!cancelled) setState(s);
      })
      .catch((err) => {
        console.warn('[CharacterDetailModal] fetchCharacterState failed:', err);
      });
    return () => { cancelled = true; };
  }, [character.id]);

  // v4 segment 2:per-mount 拉 active variant。无 active(老角色没 run
  // segment-1 migration)→ silent,Persona 区域显示「暂无 variant」占位。
  useEffect(() => {
    let cancelled = false;
    setActivePersona(null);
    getActivePersona(character.id)
      .then((p) => { if (!cancelled) setActivePersona(p); })
      .catch(() => { /* silent — 旧角色无 active variant 时 404 是正常 */ });
    return () => { cancelled = true; };
  }, [character.id]);

  // v4.0 voice greeting · per PM dispatch 2026-05-22:onMount 随机播放
  // voice line。空 list / fetch fail 静默不播;unmount 时 pause 防 leak。
  useEffect(() => {
    let cancelled = false;
    let audioEl: HTMLAudioElement | null = null;
    playRandomVoiceGreeting(character.id).then((a) => {
      if (cancelled) {
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

  // DailyAgent Stage1-viz:per-mount 拉今日日程。404 / 网络挂 → silent,
  // TodayPlanSection 自己按 plan===null 渲染"尚未生成"占位。
  useEffect(() => {
    let cancelled = false;
    setPlan(null);
    fetchTodayPlan(character.id)
      .then((p) => { if (!cancelled) setPlan(p); })
      .catch((err) => {
        console.warn('[CharacterDetailModal] fetchTodayPlan failed:', err);
      });
    return () => { cancelled = true; };
  }, [character.id]);

  // 保存 persona 后:refetch getActivePersona 刷新本面板(per PM Build 1 spec)
  const onPersonaSaved = () => {
    setEditorOpen(false);
    getActivePersona(character.id)
      .then((p) => setActivePersona(p))
      .catch(() => { /* silent */ });
  };

  // 跳能力页 → 用户再点 Live2D Models tab(CapabilitiesPanel 当前不接受
  // 外部 deeplink · 多一步点击换零跨组件耦合,Build 1 接受)
  const onJumpToCapabilities = () => {
    setActiveOverlay('capabilities');
    setGalleryOpen(false);
  };

  return (
    <>
      {/* Backdrop:fade + blur(brightness 压住底层 fan)。click 关闭。 */}
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
            className="w-[460px] rounded-2xl p-6 shadow-2xl"
            style={{
              background:
                'color-mix(in srgb, var(--color-bg-surface) 88%, transparent)',
              border: '1px solid var(--color-border-subtle)',
              color:  'var(--color-text-primary)',
              maxHeight: '80vh',
              overflowY: 'auto',
            }}
          >
            <h2 className="text-2xl font-semibold mb-1 leading-tight">
              {character.name}
            </h2>

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

            {/* state thought / activity 闲笔 */}
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

            {/* ── Persona section ──────────────────────────── */}
            <PersonaSection
              persona={activePersona}
              onEdit={() => setEditorOpen(true)}
            />

            {/* ── Live2D 引用 ──────────────────────────────── */}
            <SectionHeader>Live2D</SectionHeader>
            <div className="mb-1 text-sm">
              使用模型:
              {character.live2d_model
                ? (
                  <span style={{ color: 'var(--color-text-primary)' }}>
                    {' '}{character.live2d_model}
                  </span>
                ) : (
                  <span
                    className="italic"
                    style={{ color: 'var(--color-text-secondary)' }}
                  >
                    {' '}未配置(渲染回退到静态头像)
                  </span>
                )}
            </div>
            <button
              type="button"
              onClick={onJumpToCapabilities}
              className="text-[11px] underline-offset-2 hover:underline mb-5"
              style={{ color: 'var(--color-text-accent)' }}
              title="跳到能力页 · 在 Live2D Models tab 管理模型库"
            >
              → 在能力 → Live2D Models 管理
            </button>

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

            {/* ── 今日日程(live · DailyAgent Stage1-viz)──────────────────
                替换原「生活(dailyagent)」占位卡;由 DailyAgent 后端 cron
                生成 + ticker 命中,本块仅渲染,不触发生成。 */}
            <TodayPlanSection plan={plan} />

            {/* ── 即将推出占位卡 ──────────────────────────── */}
            <SectionHeader className="mt-6">即将推出</SectionHeader>
            <ComingSoonCard
              emoji="🧠"
              title="生活记忆"
              hint="长期生活轨迹与回忆体系 · 跨日聚类与情感加权的角色记忆库。"
            />
            <ComingSoonCard
              emoji="🎨"
              title="立绘生成(ComfyUI · anime)"
              hint="接入本地 ComfyUI 自动生成 / 迭代角色立绘。后端尚未接入 :8188。"
            />
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

      {/* PersonaEditorModal 用 z-50,本 modal 用 z-[1001] · wrapper 创建
          z-2000 stacking context · 让 editor 的 fixed 子元素叠在最上层。 */}
      {editorOpen && activePersona && (
        <div style={{ position: 'relative', zIndex: 2000 }}>
          <PersonaEditorModal
            characterId={character.id}
            existing={activePersona}
            onClose={() => setEditorOpen(false)}
            onSaved={onPersonaSaved}
          />
        </div>
      )}
    </>
  );
}


// ---------------------------------------------------------------------------
// SectionHeader · 灰色全大写小标
// ---------------------------------------------------------------------------

function SectionHeader({
  children, className = '',
}: { children: React.ReactNode; className?: string }) {
  return (
    <div
      className={`text-[10px] uppercase tracking-wider mb-1.5 ${className}`}
      style={{ color: 'var(--color-text-secondary)', opacity: 0.7 }}
    >
      {children}
    </div>
  );
}


// ---------------------------------------------------------------------------
// PersonaSection · Tier-1 全字段铺开
//
// 字段缺位策略:
//   - persona === null → 整段渲染"暂无 variant"占位(老角色未跑 v4 migration)
//   - persona 在但子字段空 → 子段渲染"未设置"小字
//   - voice_samples / forbidden_phrases 偏内部,本 Build 不展示
// ---------------------------------------------------------------------------

function PersonaSection({
  persona, onEdit,
}: { persona: CharacterPersonaRow | null; onEdit: () => void }) {
  if (!persona) {
    return (
      <>
        <SectionHeader>Persona</SectionHeader>
        <div
          className="mb-5 text-sm italic"
          style={{ color: 'var(--color-text-secondary)' }}
        >
          暂无 persona variant(老角色未跑 v4 segment-1 迁移,或刚新建)。
        </div>
      </>
    );
  }

  const id = persona.identity ?? {};
  const pc = persona.personality_core ?? {};
  const ss = persona.speech_style ?? {};
  const rel = persona.relationship_to_user ?? {};
  const sigs = persona.signature_phrases ?? [];
  const lore = persona.lore;

  return (
    <>
      <SectionHeader>Persona</SectionHeader>

      {/* variant header + 编辑按钮 */}
      <div className="flex items-baseline gap-2 mb-1 flex-wrap">
        <span
          className="text-base font-medium"
          style={{ color: 'var(--color-text-primary)' }}
        >
          {id.name?.trim() || persona.variant_name}
        </span>
        <span
          className="text-[10px] px-1.5 py-0.5 rounded"
          style={{
            background: persona.is_builtin
              ? 'color-mix(in srgb, var(--color-accent) 40%, transparent)'
              : 'var(--color-bg-elevated)',
            color: 'var(--color-text-secondary)',
          }}
        >
          {persona.variant_name}
          {persona.is_builtin ? ' · 系统预设' : ' · 自定义'}
        </span>
        <button
          type="button"
          onClick={onEdit}
          className="ml-auto text-[11px] inline-flex items-center gap-1 px-2 py-0.5 rounded hover:opacity-80"
          style={{
            background: 'var(--color-bg-elevated)',
            color: 'var(--color-text-primary)',
            border: '1px solid var(--color-border)',
          }}
          title="编辑当前 active persona"
        >
          <Edit3 size={10} />
          编辑人设
        </button>
      </div>

      {persona.description && (
        <p
          className="text-sm leading-relaxed mb-1"
          style={{ color: 'var(--color-text-primary)' }}
        >
          {persona.description}
        </p>
      )}
      <p
        className="text-[11px] mb-4"
        style={{ color: 'var(--color-text-secondary)' }}
      >
        卡型:{persona.card_type || '社交'}
      </p>

      {/* Identity ──── Stage1-viz 修订:今日日程接管主角位,Identity 默认收起,
          与其它子段一致 */}
      <SubSection title="Identity">
        {id.self_intro?.['0-69'] && (
          <FieldRow label="自介(0-69)">{id.self_intro['0-69']}</FieldRow>
        )}
        {id.self_intro?.['70-100'] && (
          <FieldRow label="自介(70-100)">{id.self_intro['70-100']}</FieldRow>
        )}
        <FieldRow label="别名">
          {id.aliases && id.aliases.length > 0 ? id.aliases.join('、') : '未设置'}
        </FieldRow>
        <FieldRow label="自称">{id.self_reference || '未设置'}</FieldRow>
        <FieldRow label="年龄">
          {id.age !== null && id.age !== undefined ? String(id.age) : '未设置'}
        </FieldRow>
        <FieldRow label="职业">{id.occupation || '未设置'}</FieldRow>
        <FieldRow label="出身">{id.origin || '未设置'}</FieldRow>
      </SubSection>

      {/* Personality core ─────────────────────────────── */}
      <SubSection title="性格核心">
        <FieldRow label="核心特质">
          <Chips items={pc.core_traits} />
        </FieldRow>
        <FieldRow label="对比面">
          <Chips items={pc.contrasts} />
        </FieldRow>
        <FieldRow label="能量水平">{pc.energy_level || '未设置'}</FieldRow>
        <FieldRow label="默认情绪">{pc.default_emotion || '未设置'}</FieldRow>
        <FieldRow label="愤怒模式">{pc.anger_style || '未设置'}</FieldRow>
      </SubSection>

      {/* Speech style ─────────────────────────────────── */}
      <SubSection title="说话风格">
        <FieldRow label="词汇">{ss.vocabulary || '未设置'}</FieldRow>
        <FieldRow label="句子节奏">{ss.sentence_rhythm || '未设置'}</FieldRow>
        <FieldRow label="用户称呼">{ss.user_address || '未设置'}</FieldRow>
        <FieldRow label="emoji 习惯">{ss.emoji_habit || '未设置'}</FieldRow>
        <FieldRow label="标点癖好">{ss.punctuation_quirk || '未设置'}</FieldRow>
      </SubSection>

      {/* Signature phrases ───────────────────────────── */}
      <SubSection title="招牌词">
        {sigs.length > 0 ? <Chips items={sigs} /> : (
          <span
            className="text-sm italic"
            style={{ color: 'var(--color-text-secondary)' }}
          >
            未设置
          </span>
        )}
      </SubSection>

      {/* Lore ─────────────────────────────────────────── */}
      <SubSection title="设定 / Lore">
        <LoreView lore={lore} />
      </SubSection>

      {/* Relationship to user ───────────────────────── */}
      <SubSection title="与用户的关系" lastChild>
        <FieldRow label="类型">{rel.type || '未设置'}</FieldRow>
        <FieldRow label="进展模式">{rel.intimacy_progression || '未设置'}</FieldRow>
        <FieldRow label="初始亲密度">
          {rel.initial_intimacy !== undefined && rel.initial_intimacy !== null
            ? String(rel.initial_intimacy) : '未设置'}
        </FieldRow>
      </SubSection>
    </>
  );
}


// 可折叠子段。默认 false 收起(PM Build 1 修订:面板被全 persona 撑满
// 后改 accordion)。借 UX-002 CapabilityRow 的 chevron + aria 模型,视觉
// 保持本地密集(text-[11px])· 不用 CapabilityRow 因其 leftIcon / statusBadge
// / briefDescription 在 MCP capability listing 语境下视觉重。
function SubSection({
  title, children, lastChild = false, defaultExpanded = false,
}: {
  title: string;
  children: React.ReactNode;
  lastChild?: boolean;
  defaultExpanded?: boolean;
}) {
  const [expanded, setExpanded] = useState<boolean>(defaultExpanded);
  return (
    <div className={lastChild ? 'mb-4' : 'mb-3'}>
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
        aria-label={expanded ? `收起 ${title}` : `展开 ${title}`}
        className="w-full flex items-center gap-1 mb-1 -ml-0.5 rounded hover:opacity-80"
        style={{ color: 'var(--color-text-secondary)' }}
      >
        {expanded
          ? <ChevronDown size={10} />
          : <ChevronRight size={10} />}
        <span className="text-[11px] font-medium">{title}</span>
      </button>
      {expanded && <div className="space-y-0.5 ml-3">{children}</div>}
    </div>
  );
}


function FieldRow({
  label, children,
}: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline gap-2 text-sm">
      <span
        className="text-[11px] flex-shrink-0"
        style={{ color: 'var(--color-text-secondary)', minWidth: 80 }}
      >
        {label}
      </span>
      <span
        className="flex-1 break-words"
        style={{ color: 'var(--color-text-primary)' }}
      >
        {children}
      </span>
    </div>
  );
}


function Chips({ items }: { items: string[] | undefined }) {
  if (!items || items.length === 0) {
    return (
      <span
        className="text-sm italic"
        style={{ color: 'var(--color-text-secondary)' }}
      >
        未设置
      </span>
    );
  }
  return (
    <div className="flex flex-wrap gap-1">
      {items.map((it, i) => (
        <span
          key={`${it}-${i}`}
          className="text-[11px] px-1.5 py-0.5 rounded"
          style={{
            background: 'var(--color-bg-elevated)',
            color: 'var(--color-text-primary)',
          }}
        >
          {it}
        </span>
      ))}
    </div>
  );
}


// lore 是 unknown · 防御性渲染:string 直显 / object 格式化 JSON / 空显未设置
function LoreView({ lore }: { lore: unknown }) {
  if (lore === null || lore === undefined) {
    return (
      <span
        className="text-sm italic"
        style={{ color: 'var(--color-text-secondary)' }}
      >
        未设置
      </span>
    );
  }
  if (typeof lore === 'string') {
    if (lore.trim() === '') {
      return (
        <span
          className="text-sm italic"
          style={{ color: 'var(--color-text-secondary)' }}
        >
          未设置
        </span>
      );
    }
    return (
      <p
        className="text-sm leading-relaxed"
        style={{ color: 'var(--color-text-primary)' }}
      >
        {lore}
      </p>
    );
  }
  // object / array · 防御性 JSON 展示(不崩 + 可读)
  let formatted: string;
  try {
    formatted = JSON.stringify(lore, null, 2);
  } catch {
    formatted = String(lore);
  }
  if (formatted === '{}' || formatted === '[]') {
    return (
      <span
        className="text-sm italic"
        style={{ color: 'var(--color-text-secondary)' }}
      >
        未设置
      </span>
    );
  }
  return (
    <pre
      className="text-[11px] font-mono p-2 rounded overflow-x-auto whitespace-pre-wrap"
      style={{
        background: 'var(--color-bg-input)',
        border: '1px solid var(--color-border)',
        color: 'var(--color-text-primary)',
        maxHeight: 200,
      }}
    >
      {formatted}
    </pre>
  );
}


// ---------------------------------------------------------------------------
// TodayPlanSection · DailyAgent Stage1-viz · 今日日程 live 区块
//
// 始终展开(本页新主角)· plan===null 或 plan.plan===null → muted 占位行;
// plan 数组渲染竖向时间线,当前命中 slot 按 (start,end) 全等高亮(accent
// 左边框 + 轻底色 + 行尾「● 现在」)。视觉复用 modal 现有 var(--color-*)
// token,不造新 chrome。
// ---------------------------------------------------------------------------

function TodayPlanSection({ plan }: { plan: TodayPlan | null }) {
  const cur = plan?.current_slot ?? null;
  const slots = plan?.plan ?? null;
  return (
    <div className="mt-6 mb-2">
      <div className="flex items-baseline gap-2 mb-2">
        <span
          className="text-sm font-medium"
          style={{ color: 'var(--color-text-primary)' }}
        >
          🌱 今日日程
        </span>
        {plan && (
          <span
            className="text-[11px] ml-auto"
            style={{ color: 'var(--color-text-secondary)' }}
          >
            {plan.weekday} · 现在 {plan.now_local}
          </span>
        )}
      </div>

      {slots === null ? (
        <div
          className="text-xs italic"
          style={{ color: 'var(--color-text-secondary)' }}
        >
          今日日程尚未生成
        </div>
      ) : (
        <div className="space-y-0.5">
          {slots.map((slot, i) => {
            const isCurrent =
              cur !== null &&
              slot.start === cur.start &&
              slot.end === cur.end;
            return (
              <div
                key={`${slot.start}-${slot.end}-${i}`}
                className="flex items-baseline gap-2 text-sm rounded px-2 py-1"
                style={{
                  background: isCurrent
                    ? 'color-mix(in srgb, var(--color-accent) 14%, transparent)'
                    : 'transparent',
                  borderLeft: isCurrent
                    ? '2px solid var(--color-accent)'
                    : '2px solid transparent',
                }}
              >
                <span
                  className="text-[11px] font-mono flex-shrink-0 tabular-nums"
                  style={{
                    color: 'var(--color-text-secondary)',
                    minWidth: 92,
                  }}
                >
                  {slot.start}–{slot.end}
                </span>
                <span
                  className="flex-1 break-words"
                  style={{ color: 'var(--color-text-primary)' }}
                >
                  {slot.activity}
                </span>
                {isCurrent && (
                  <span
                    className="text-[10px] flex-shrink-0 font-medium"
                    style={{ color: 'var(--color-text-accent)' }}
                  >
                    ● 现在
                  </span>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}


// ---------------------------------------------------------------------------
// ComingSoonCard · 诚实占位 · 不做假数据 · 样式同 Skills(.py) "即将推出"
// ---------------------------------------------------------------------------

function ComingSoonCard({
  emoji, title, hint,
}: { emoji: string; title: string; hint: string }) {
  return (
    <div
      className="mb-2 rounded-lg p-3 flex items-start gap-3"
      style={{
        background: 'var(--color-bg-elevated)',
        border: '1px solid var(--color-border-subtle)',
        opacity: 0.85,
      }}
    >
      <div className="text-xl select-none flex-shrink-0">{emoji}</div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-0.5">
          <span
            className="text-sm font-medium"
            style={{ color: 'var(--color-text-primary)' }}
          >
            {title}
          </span>
          <span
            className="text-[10px] px-1.5 py-0.5 rounded flex-shrink-0"
            style={{
              background: 'var(--color-bg-surface)',
              color: 'var(--color-text-secondary)',
            }}
          >
            即将推出
          </span>
        </div>
        <p
          className="text-[11px] leading-relaxed"
          style={{ color: 'var(--color-text-secondary)' }}
        >
          {hint}
        </p>
      </div>
    </div>
  );
}
