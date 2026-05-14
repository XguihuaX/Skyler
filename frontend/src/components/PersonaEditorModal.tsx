/**
 * v4 segment 2 — PersonaEditorModal (MVP, Tier-1 7 字段 + tolerance sliders)
 *
 * Per D-S2-4 sign-off:Tier-1 7 字段全编辑 + cliche_tolerance / voice_samples
 * tolerance_range 滑块。Tier-2(taboo_topics / lore / capability_overrides)
 * 在 v4.2 加,本 MVP 只**只读保留**这些字段(不显示编辑入口)。
 *
 * 编辑流程:
 *   - existing persona → PATCH /api/personas/{id}
 *   - new variant → POST /api/characters/{character_id}/personas
 * 保存成功 → onSaved() 回调,父组件 refresh personas 列表。
 */

import { useEffect, useState } from 'react';
import { X, Plus, Trash2 } from 'lucide-react';
import {
  CharacterPersonaRow,
  CreatePersonaBody,
  PatchPersonaBody,
  VoiceSample,
  createPersona,
  patchPersona,
} from '../lib/personas';

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface PersonaEditorModalProps {
  characterId: number;
  /** Existing variant(edit mode)or null(create mode)。 */
  existing: CharacterPersonaRow | null;
  onClose: () => void;
  onSaved: (saved: CharacterPersonaRow) => void;
}

// ---------------------------------------------------------------------------
// Local form state(plain shapes,save 时序列化成 API body)
// ---------------------------------------------------------------------------

interface FormState {
  variant_name: string;
  description: string;
  style_preset: string;
  // Tier-1 7 字段(对外是 dict / list,内部 form 保持同形)
  identity_name: string;
  identity_aliases_csv: string;
  identity_self_reference: string;
  identity_age: string;       // 用 string 给 input,save 时 parseInt
  identity_occupation: string;
  identity_origin: string;
  identity_self_intro_0_69: string;
  identity_self_intro_70_100: string;
  pc_core_traits_csv: string;
  pc_contrasts: string;       // 多行,一行一条
  pc_energy_level: 'low' | 'medium' | 'high';
  pc_default_emotion: string;
  pc_anger_style: string;
  ss_vocabulary: string;
  ss_sentence_rhythm: string;
  ss_user_address: string;
  ss_emoji_habit: string;
  ss_punctuation_quirk: string;
  ss_cliche_tolerance: number;   // 0~1 滑块
  signature_phrases_csv: string;
  voice_samples: VoiceSample[];
  fp_global_csv: string;
  fp_character_csv: string;
  fp_qwen_csv: string;
  fp_deepseek_csv: string;
  rel_type: string;
  rel_intimacy_progression: string;
  rel_initial_intimacy: number;
}

const EMPTY_FORM: FormState = {
  variant_name: '',
  description: '',
  style_preset: 'anime_classic',
  identity_name: '',
  identity_aliases_csv: '',
  identity_self_reference: '我',
  identity_age: '',
  identity_occupation: '',
  identity_origin: '',
  identity_self_intro_0_69: '',
  identity_self_intro_70_100: '',
  pc_core_traits_csv: '',
  pc_contrasts: '',
  pc_energy_level: 'medium',
  pc_default_emotion: 'calm',
  pc_anger_style: '',
  ss_vocabulary: 'neutral',
  ss_sentence_rhythm: 'medium',
  ss_user_address: '你',
  ss_emoji_habit: 'rare',
  ss_punctuation_quirk: 'standard',
  ss_cliche_tolerance: 0.5,
  signature_phrases_csv: '',
  voice_samples: [],
  fp_global_csv: '作为AI,作为一个助手',
  fp_character_csv: '',
  fp_qwen_csv: '',
  fp_deepseek_csv: '',
  rel_type: 'companion',
  rel_intimacy_progression: 'linear',
  rel_initial_intimacy: 50,
};

// CSV 工具:逗号 / 中文逗号 / 换行均算分隔
const csvToArr = (s: string): string[] =>
  s.split(/[,，\n]/).map((x) => x.trim()).filter(Boolean);

const arrToCsv = (a: string[] | undefined): string =>
  (a ?? []).join(', ');

function _existingToForm(p: CharacterPersonaRow): FormState {
  return {
    variant_name: p.variant_name,
    description: p.description ?? '',
    style_preset: p.style_preset ?? 'anime_classic',
    identity_name: p.identity.name ?? '',
    identity_aliases_csv: arrToCsv(p.identity.aliases),
    identity_self_reference: p.identity.self_reference ?? '我',
    identity_age: p.identity.age != null ? String(p.identity.age) : '',
    identity_occupation: p.identity.occupation ?? '',
    identity_origin: p.identity.origin ?? '',
    identity_self_intro_0_69: p.identity.self_intro?.['0-69'] ?? '',
    identity_self_intro_70_100: p.identity.self_intro?.['70-100'] ?? '',
    pc_core_traits_csv: arrToCsv(p.personality_core.core_traits),
    pc_contrasts: (p.personality_core.contrasts ?? []).join('\n'),
    pc_energy_level: (p.personality_core.energy_level ?? 'medium') as
      'low' | 'medium' | 'high',
    pc_default_emotion: p.personality_core.default_emotion ?? 'calm',
    pc_anger_style: p.personality_core.anger_style ?? '',
    ss_vocabulary: p.speech_style.vocabulary ?? 'neutral',
    ss_sentence_rhythm: p.speech_style.sentence_rhythm ?? 'medium',
    ss_user_address: p.speech_style.user_address ?? '你',
    ss_emoji_habit: p.speech_style.emoji_habit ?? 'rare',
    ss_punctuation_quirk: p.speech_style.punctuation_quirk ?? 'standard',
    ss_cliche_tolerance: p.speech_style.cliche_tolerance ?? 0.5,
    signature_phrases_csv: arrToCsv(p.signature_phrases),
    voice_samples: p.voice_samples ?? [],
    fp_global_csv: arrToCsv(p.forbidden_phrases._global),
    fp_character_csv: arrToCsv(p.forbidden_phrases._character),
    fp_qwen_csv: arrToCsv(p.forbidden_phrases._qwen),
    fp_deepseek_csv: arrToCsv(p.forbidden_phrases._deepseek),
    rel_type: p.relationship_to_user.type ?? 'companion',
    rel_intimacy_progression: p.relationship_to_user.intimacy_progression ?? 'linear',
    rel_initial_intimacy: p.relationship_to_user.initial_intimacy ?? 50,
  };
}

function _formToCreateBody(f: FormState): CreatePersonaBody {
  const selfIntro: { '0-69'?: string; '70-100'?: string } = {};
  if (f.identity_self_intro_0_69.trim()) selfIntro['0-69'] = f.identity_self_intro_0_69;
  if (f.identity_self_intro_70_100.trim()) selfIntro['70-100'] = f.identity_self_intro_70_100;

  const ageStr = f.identity_age.trim();
  const age = ageStr ? parseInt(ageStr, 10) : null;

  return {
    variant_name: f.variant_name.trim(),
    description: f.description.trim() || null,
    style_preset: f.style_preset || 'anime_classic',
    display_order: 0,
    identity: {
      name: f.identity_name.trim(),
      aliases: csvToArr(f.identity_aliases_csv),
      self_reference: f.identity_self_reference.trim() || '我',
      age: Number.isFinite(age) ? age : null,
      occupation: f.identity_occupation.trim() || null,
      origin: f.identity_origin.trim() || null,
      ...(Object.keys(selfIntro).length > 0 ? { self_intro: selfIntro } : {}),
    },
    personality_core: {
      core_traits: csvToArr(f.pc_core_traits_csv),
      contrasts: f.pc_contrasts.split('\n').map((s) => s.trim()).filter(Boolean),
      energy_level: f.pc_energy_level,
      default_emotion: f.pc_default_emotion.trim() || 'calm',
      anger_style: f.pc_anger_style.trim() || null,
    },
    speech_style: {
      vocabulary: f.ss_vocabulary.trim() || 'neutral',
      sentence_rhythm: f.ss_sentence_rhythm.trim() || 'medium',
      user_address: f.ss_user_address.trim() || '你',
      emoji_habit: f.ss_emoji_habit.trim() || 'rare',
      punctuation_quirk: f.ss_punctuation_quirk.trim() || 'standard',
      cliche_tolerance: Math.max(0, Math.min(1, f.ss_cliche_tolerance)),
    },
    signature_phrases: csvToArr(f.signature_phrases_csv),
    voice_samples: f.voice_samples,
    forbidden_phrases: {
      _global: csvToArr(f.fp_global_csv),
      _character: csvToArr(f.fp_character_csv),
      _qwen: csvToArr(f.fp_qwen_csv),
      _deepseek: csvToArr(f.fp_deepseek_csv),
    },
    relationship_to_user: {
      type: f.rel_type.trim() || 'companion',
      intimacy_progression: f.rel_intimacy_progression.trim() || 'linear',
      initial_intimacy: Math.max(0, Math.min(100, f.rel_initial_intimacy)),
    },
  };
}

function _formToPatchBody(f: FormState): PatchPersonaBody {
  // PATCH 可全字段传(server-side 只更新 not-None;不影响未变更的列)
  return _formToCreateBody(f);
}

// ---------------------------------------------------------------------------
// Tolerance label
// ---------------------------------------------------------------------------

function toleranceLabel(t: number): string {
  if (t < 0.25) return '自然偏淡';
  if (t < 0.55) return '常规中性';
  if (t < 0.75) return '稍微放糖';
  return '放大版 (糖度高)';
}

// ---------------------------------------------------------------------------
// Voice sample row
// ---------------------------------------------------------------------------

function VoiceSampleRow({
  sample,
  onChange,
  onDelete,
}: {
  sample: VoiceSample;
  onChange: (next: VoiceSample) => void;
  onDelete: () => void;
}) {
  const rng = sample.tolerance_range ?? [0, 1];
  const inputStyle: React.CSSProperties = {
    background: 'var(--color-bg-input)',
    border: '1px solid var(--color-border)',
    color: 'var(--color-text-primary)',
  };

  return (
    <div
      className="rounded-md p-2 space-y-2"
      style={{ border: '1px solid var(--color-border-subtle)' }}
    >
      <div className="flex items-center gap-2">
        <input
          type="text"
          value={sample.scene}
          onChange={(e) => onChange({ ...sample, scene: e.target.value })}
          placeholder="场景(如 起床问候)"
          className="flex-1 rounded px-2 py-1 text-xs focus:outline-none"
          style={inputStyle}
        />
        <button
          type="button"
          onClick={onDelete}
          className="w-7 h-7 rounded flex items-center justify-center hover:bg-rose-700/30 text-rose-300"
          title="删除样本"
        >
          <Trash2 size={14} />
        </button>
      </div>
      <textarea
        value={sample.text}
        onChange={(e) => onChange({ ...sample, text: e.target.value })}
        placeholder="该场景下角色的真实台词样本"
        rows={2}
        className="w-full rounded px-2 py-1 text-xs focus:outline-none resize-y"
        style={inputStyle}
      />
      <div>
        <label
          className="block text-[10px] mb-1"
          style={{ color: 'var(--color-text-secondary)' }}
        >
          糖度区间:{rng[0].toFixed(2)} ~ {rng[1].toFixed(2)}
        </label>
        <div className="flex items-center gap-2">
          <input
            type="range"
            min={0} max={1} step={0.05}
            value={rng[0]}
            onChange={(e) => {
              const v = parseFloat(e.target.value);
              onChange({
                ...sample,
                tolerance_range: [Math.min(v, rng[1]), rng[1]],
              });
            }}
            className="flex-1"
          />
          <input
            type="range"
            min={0} max={1} step={0.05}
            value={rng[1]}
            onChange={(e) => {
              const v = parseFloat(e.target.value);
              onChange({
                ...sample,
                tolerance_range: [rng[0], Math.max(v, rng[0])],
              });
            }}
            className="flex-1"
          />
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main modal
// ---------------------------------------------------------------------------

export default function PersonaEditorModal({
  characterId,
  existing,
  onClose,
  onSaved,
}: PersonaEditorModalProps) {
  const [form, setForm] = useState<FormState>(
    existing ? _existingToForm(existing) : EMPTY_FORM,
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setForm(existing ? _existingToForm(existing) : EMPTY_FORM);
    setError(null);
  }, [existing]);

  const inputStyle: React.CSSProperties = {
    background: 'var(--color-bg-input)',
    border: '1px solid var(--color-border)',
    color: 'var(--color-text-primary)',
  };

  const sectionStyle: React.CSSProperties = {
    background: 'color-mix(in srgb, var(--color-bg-surface) 60%, transparent)',
    border: '1px solid var(--color-border-subtle)',
  };

  const handleSave = async () => {
    if (!form.variant_name.trim()) {
      setError('variant_name 必填');
      return;
    }
    if (!form.identity_name.trim()) {
      setError('identity.name 必填');
      return;
    }
    setError(null);
    setSaving(true);
    try {
      let saved: CharacterPersonaRow;
      if (existing) {
        saved = await patchPersona(existing.id, _formToPatchBody(form));
      } else {
        saved = await createPersona(characterId, _formToCreateBody(form));
      }
      onSaved(saved);
      onClose();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const addVoiceSample = () => {
    setForm({
      ...form,
      voice_samples: [
        ...form.voice_samples,
        { scene: '', text: '', tolerance_range: [0, 1] },
      ],
    });
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
      onClick={onClose}
    >
      <div
        className="rounded-xl w-full max-w-3xl max-h-[90vh] overflow-y-auto p-5"
        style={{
          background: 'var(--color-bg-elevated)',
          border: '1px solid var(--color-border)',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between mb-4">
          <h2
            className="text-base font-medium"
            style={{ color: 'var(--color-text-primary)' }}
          >
            {existing ? `编辑 persona — ${existing.variant_name}` : '新建 persona variant'}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="w-8 h-8 rounded-md hover:bg-white/10 flex items-center justify-center"
            style={{ color: 'var(--color-text-secondary)' }}
          >
            <X size={18} />
          </button>
        </div>

        {error && (
          <div
            className="text-xs rounded-md p-2 mb-3"
            style={{
              background: 'color-mix(in srgb, #ef4444 20%, transparent)',
              color: 'var(--color-text-primary)',
            }}
          >
            {error}
          </div>
        )}

        <div className="space-y-3">
          {/* —— 基本 —— */}
          <section className="rounded-md p-3 space-y-2" style={sectionStyle}>
            <h3
              className="text-xs font-medium"
              style={{ color: 'var(--color-text-secondary)' }}
            >
              基本
            </h3>
            <div className="grid grid-cols-2 gap-2">
              <input
                type="text"
                value={form.variant_name}
                onChange={(e) => setForm({ ...form, variant_name: e.target.value })}
                placeholder="variant_name * (如 default / 病娇)"
                disabled={!!existing && existing.is_builtin}
                className="rounded px-2 py-1 text-xs focus:outline-none disabled:opacity-50"
                style={inputStyle}
              />
              <select
                value={form.style_preset}
                onChange={(e) => setForm({ ...form, style_preset: e.target.value })}
                className="rounded px-2 py-1 text-xs focus:outline-none"
                style={inputStyle}
              >
                <option value="anime_classic">anime_classic</option>
                <option value="realistic_grounded">realistic_grounded</option>
                <option value="mixed">mixed</option>
              </select>
            </div>
            <input
              type="text"
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
              placeholder="一句话描述 (description)"
              className="w-full rounded px-2 py-1 text-xs focus:outline-none"
              style={inputStyle}
            />
          </section>

          {/* —— 身份卡 (identity) —— */}
          <section className="rounded-md p-3 space-y-2" style={sectionStyle}>
            <h3 className="text-xs font-medium" style={{ color: 'var(--color-text-secondary)' }}>
              身份卡 (identity)
            </h3>
            <div className="grid grid-cols-2 gap-2">
              <input
                type="text" value={form.identity_name}
                onChange={(e) => setForm({ ...form, identity_name: e.target.value })}
                placeholder="name * (如 樱岛麻衣)"
                className="rounded px-2 py-1 text-xs focus:outline-none" style={inputStyle}
              />
              <input
                type="text" value={form.identity_self_reference}
                onChange={(e) => setForm({ ...form, identity_self_reference: e.target.value })}
                placeholder="自称 (我 / 本小姐 / 本喵)"
                className="rounded px-2 py-1 text-xs focus:outline-none" style={inputStyle}
              />
              <input
                type="text" value={form.identity_aliases_csv}
                onChange={(e) => setForm({ ...form, identity_aliases_csv: e.target.value })}
                placeholder="aliases (逗号分隔)"
                className="rounded px-2 py-1 text-xs focus:outline-none" style={inputStyle}
              />
              <input
                type="text" value={form.identity_age}
                onChange={(e) => setForm({ ...form, identity_age: e.target.value })}
                placeholder="age (可空)"
                className="rounded px-2 py-1 text-xs focus:outline-none" style={inputStyle}
              />
              <input
                type="text" value={form.identity_occupation}
                onChange={(e) => setForm({ ...form, identity_occupation: e.target.value })}
                placeholder="occupation"
                className="rounded px-2 py-1 text-xs focus:outline-none" style={inputStyle}
              />
              <input
                type="text" value={form.identity_origin}
                onChange={(e) => setForm({ ...form, identity_origin: e.target.value })}
                placeholder="origin (作品 / 出身)"
                className="rounded px-2 py-1 text-xs focus:outline-none" style={inputStyle}
              />
            </div>
            <textarea
              value={form.identity_self_intro_0_69}
              onChange={(e) => setForm({ ...form, identity_self_intro_0_69: e.target.value })}
              placeholder="self_intro 0-69(公开版,亲密度低时用)"
              rows={2}
              className="w-full rounded px-2 py-1 text-xs focus:outline-none resize-y" style={inputStyle}
            />
            <textarea
              value={form.identity_self_intro_70_100}
              onChange={(e) => setForm({ ...form, identity_self_intro_70_100: e.target.value })}
              placeholder="self_intro 70-100(深度版,亲密度高时用)"
              rows={2}
              className="w-full rounded px-2 py-1 text-xs focus:outline-none resize-y" style={inputStyle}
            />
          </section>

          {/* —— 性格 (personality_core) —— */}
          <section className="rounded-md p-3 space-y-2" style={sectionStyle}>
            <h3 className="text-xs font-medium" style={{ color: 'var(--color-text-secondary)' }}>
              性格 (personality_core)
            </h3>
            <input
              type="text" value={form.pc_core_traits_csv}
              onChange={(e) => setForm({ ...form, pc_core_traits_csv: e.target.value })}
              placeholder="core_traits 3-5 个 (逗号分隔,如:温柔, 内向, 倔强)"
              className="w-full rounded px-2 py-1 text-xs focus:outline-none" style={inputStyle}
            />
            <textarea
              value={form.pc_contrasts}
              onChange={(e) => setForm({ ...form, pc_contrasts: e.target.value })}
              placeholder="contrasts(反差点,每行一条;让角色立体的关键)"
              rows={3}
              className="w-full rounded px-2 py-1 text-xs focus:outline-none resize-y" style={inputStyle}
            />
            <div className="grid grid-cols-2 gap-2">
              <select
                value={form.pc_energy_level}
                onChange={(e) =>
                  setForm({ ...form, pc_energy_level: e.target.value as FormState['pc_energy_level'] })}
                className="rounded px-2 py-1 text-xs focus:outline-none" style={inputStyle}
              >
                <option value="low">能量:低</option>
                <option value="medium">能量:中</option>
                <option value="high">能量:高</option>
              </select>
              <input
                type="text" value={form.pc_default_emotion}
                onChange={(e) => setForm({ ...form, pc_default_emotion: e.target.value })}
                placeholder="default_emotion (calm / happy / ...)"
                className="rounded px-2 py-1 text-xs focus:outline-none" style={inputStyle}
              />
            </div>
            <input
              type="text" value={form.pc_anger_style}
              onChange={(e) => setForm({ ...form, pc_anger_style: e.target.value })}
              placeholder="anger_style(愤怒时的表现,可空)"
              className="w-full rounded px-2 py-1 text-xs focus:outline-none" style={inputStyle}
            />
          </section>

          {/* —— 说话风格 (speech_style) + cliche_tolerance 滑块 —— */}
          <section className="rounded-md p-3 space-y-2" style={sectionStyle}>
            <h3 className="text-xs font-medium" style={{ color: 'var(--color-text-secondary)' }}>
              说话风格 (speech_style)
            </h3>
            <div className="grid grid-cols-2 gap-2">
              <textarea
                value={form.ss_vocabulary} rows={2}
                onChange={(e) => setForm({ ...form, ss_vocabulary: e.target.value })}
                placeholder="vocabulary 词汇偏好"
                className="rounded px-2 py-1 text-xs focus:outline-none resize-y" style={inputStyle}
              />
              <textarea
                value={form.ss_sentence_rhythm} rows={2}
                onChange={(e) => setForm({ ...form, ss_sentence_rhythm: e.target.value })}
                placeholder="sentence_rhythm 句式节奏"
                className="rounded px-2 py-1 text-xs focus:outline-none resize-y" style={inputStyle}
              />
              <input
                type="text" value={form.ss_user_address}
                onChange={(e) => setForm({ ...form, ss_user_address: e.target.value })}
                placeholder="user_address 称呼用户"
                className="rounded px-2 py-1 text-xs focus:outline-none" style={inputStyle}
              />
              <input
                type="text" value={form.ss_emoji_habit}
                onChange={(e) => setForm({ ...form, ss_emoji_habit: e.target.value })}
                placeholder="emoji_habit (rare / none / occasional)"
                className="rounded px-2 py-1 text-xs focus:outline-none" style={inputStyle}
              />
            </div>
            <input
              type="text" value={form.ss_punctuation_quirk}
              onChange={(e) => setForm({ ...form, ss_punctuation_quirk: e.target.value })}
              placeholder="punctuation_quirk 标点癖好"
              className="w-full rounded px-2 py-1 text-xs focus:outline-none" style={inputStyle}
            />
            <div>
              <label
                className="block text-[11px] mb-1"
                style={{ color: 'var(--color-text-secondary)' }}
              >
                cliche_tolerance: {form.ss_cliche_tolerance.toFixed(2)} —{' '}
                <span style={{ color: 'var(--color-accent)' }}>
                  {toleranceLabel(form.ss_cliche_tolerance)}
                </span>
              </label>
              <input
                type="range" min={0} max={1} step={0.05}
                value={form.ss_cliche_tolerance}
                onChange={(e) =>
                  setForm({ ...form, ss_cliche_tolerance: parseFloat(e.target.value) })}
                className="w-full"
              />
              <p className="text-[10px] mt-1" style={{ color: 'var(--color-text-secondary)' }}>
                越高 → 越接受甜糖句式;voice_samples 按 tolerance_range 自动过滤。
              </p>
            </div>
          </section>

          {/* —— signature_phrases —— */}
          <section className="rounded-md p-3 space-y-2" style={sectionStyle}>
            <h3 className="text-xs font-medium" style={{ color: 'var(--color-text-secondary)' }}>
              口头禅 (signature_phrases)
            </h3>
            <input
              type="text" value={form.signature_phrases_csv}
              onChange={(e) => setForm({ ...form, signature_phrases_csv: e.target.value })}
              placeholder="1-3 个 (逗号分隔)"
              className="w-full rounded px-2 py-1 text-xs focus:outline-none" style={inputStyle}
            />
          </section>

          {/* —— voice_samples(可加多条,每条带 tolerance_range 双滑块)—— */}
          <section className="rounded-md p-3 space-y-2" style={sectionStyle}>
            <div className="flex items-center justify-between">
              <h3 className="text-xs font-medium" style={{ color: 'var(--color-text-secondary)' }}>
                真实样本 (voice_samples) — 共 {form.voice_samples.length} 条
              </h3>
              <button
                type="button"
                onClick={addVoiceSample}
                className="px-2 py-1 text-[11px] rounded flex items-center gap-1"
                style={{ background: 'var(--color-accent)', color: 'var(--color-bubble-user-text)' }}
              >
                <Plus size={12} /> 添加
              </button>
            </div>
            {form.voice_samples.length === 0 && (
              <p className="text-[10px]" style={{ color: 'var(--color-text-secondary)' }}>
                未添加;LLM 会缺少风格锚点。建议至少 3-6 条覆盖不同 tolerance 区间。
              </p>
            )}
            <div className="space-y-2">
              {form.voice_samples.map((sample, idx) => (
                <VoiceSampleRow
                  key={idx}
                  sample={sample}
                  onChange={(next) => {
                    const arr = [...form.voice_samples];
                    arr[idx] = next;
                    setForm({ ...form, voice_samples: arr });
                  }}
                  onDelete={() => {
                    setForm({
                      ...form,
                      voice_samples: form.voice_samples.filter((_, i) => i !== idx),
                    });
                  }}
                />
              ))}
            </div>
          </section>

          {/* —— forbidden_phrases —— */}
          <section className="rounded-md p-3 space-y-2" style={sectionStyle}>
            <h3 className="text-xs font-medium" style={{ color: 'var(--color-text-secondary)' }}>
              禁止句式 (forbidden_phrases)
            </h3>
            <textarea
              value={form.fp_global_csv}
              onChange={(e) => setForm({ ...form, fp_global_csv: e.target.value })}
              placeholder="_global (所有 vendor 都禁;逗号分隔)"
              rows={2}
              className="w-full rounded px-2 py-1 text-xs focus:outline-none resize-y" style={inputStyle}
            />
            <textarea
              value={form.fp_character_csv}
              onChange={(e) => setForm({ ...form, fp_character_csv: e.target.value })}
              placeholder="_character (本角色专属禁词;逗号分隔)"
              rows={2}
              className="w-full rounded px-2 py-1 text-xs focus:outline-none resize-y" style={inputStyle}
            />
            <div className="grid grid-cols-2 gap-2">
              <textarea
                value={form.fp_qwen_csv}
                onChange={(e) => setForm({ ...form, fp_qwen_csv: e.target.value })}
                placeholder="_qwen (Qwen vendor 专属)"
                rows={2}
                className="rounded px-2 py-1 text-xs focus:outline-none resize-y" style={inputStyle}
              />
              <textarea
                value={form.fp_deepseek_csv}
                onChange={(e) => setForm({ ...form, fp_deepseek_csv: e.target.value })}
                placeholder="_deepseek (DeepSeek 专属)"
                rows={2}
                className="rounded px-2 py-1 text-xs focus:outline-none resize-y" style={inputStyle}
              />
            </div>
          </section>

          {/* —— relationship_to_user —— */}
          <section className="rounded-md p-3 space-y-2" style={sectionStyle}>
            <h3 className="text-xs font-medium" style={{ color: 'var(--color-text-secondary)' }}>
              关系 (relationship_to_user)
            </h3>
            <div className="grid grid-cols-3 gap-2">
              <select
                value={form.rel_type}
                onChange={(e) => setForm({ ...form, rel_type: e.target.value })}
                className="rounded px-2 py-1 text-xs focus:outline-none" style={inputStyle}
              >
                <option value="companion">companion 陪伴</option>
                <option value="mentor">mentor 引导</option>
                <option value="lover">lover 恋人</option>
                <option value="friend">friend 朋友</option>
              </select>
              <select
                value={form.rel_intimacy_progression}
                onChange={(e) => setForm({ ...form, rel_intimacy_progression: e.target.value })}
                className="rounded px-2 py-1 text-xs focus:outline-none" style={inputStyle}
              >
                <option value="linear">linear 线性</option>
                <option value="milestone">milestone 里程碑</option>
                <option value="reset_on_argue">reset_on_argue</option>
              </select>
              <input
                type="number" min={0} max={100} value={form.rel_initial_intimacy}
                onChange={(e) =>
                  setForm({ ...form, rel_initial_intimacy: parseInt(e.target.value, 10) || 0 })}
                placeholder="initial_intimacy 0-100"
                className="rounded px-2 py-1 text-xs focus:outline-none" style={inputStyle}
              />
            </div>
          </section>

          {/* Tier-2 read-only 提示 */}
          {existing && (existing.taboo_topics || existing.lore || existing.capability_overrides) && (
            <div
              className="rounded-md p-3 text-[11px]"
              style={{
                background: 'color-mix(in srgb, var(--color-warning, #f59e0b) 15%, transparent)',
                color: 'var(--color-text-secondary)',
              }}
            >
              ⓘ 本 persona 含 Tier-2 字段(taboo_topics / lore / capability_overrides),
              MVP 编辑器暂不支持编辑,保存时**保留不动**。v4.2 加全字段编辑。
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex justify-end gap-2 mt-5">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-1.5 text-xs rounded-md transition"
            style={{
              background: 'var(--color-bg-input)',
              border: '1px solid var(--color-border)',
              color: 'var(--color-text-primary)',
            }}
          >
            取消
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={saving}
            className="px-4 py-1.5 text-xs rounded-md transition disabled:opacity-50"
            style={{
              background: 'var(--color-accent)',
              color: 'var(--color-bubble-user-text)',
            }}
          >
            {saving ? '保存中...' : existing ? '保存' : '创建'}
          </button>
        </div>
      </div>
    </div>
  );
}
