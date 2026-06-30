/**
 * v4 segment 2 — character_personas REST API client.
 *
 * Mirrors backend/routes/persona_api.py。所有 Tier-1 + Tier-2 字段在 server
 * 端 json.loads 后返回,前端拿到的就是结构化 dict/list,无需再 parse。
 */

const BACKEND_BASE = 'http://127.0.0.1:8000';

// ---------------------------------------------------------------------------
// Types (mirror server-side _to_dict shape)
// ---------------------------------------------------------------------------

export interface PersonaIdentity {
  name: string;
  aliases?: string[];
  self_reference?: string;
  age?: number | null;
  occupation?: string | null;
  origin?: string | null;
  /** Segment 2 §1.1:双梯级 self_intro。key 必须是字符串 ``'0-69'`` / ``'70-100'``。 */
  self_intro?: { '0-69'?: string; '70-100'?: string } | null;
}

export interface PersonaPersonalityCore {
  core_traits?: string[];
  contrasts?: string[];
  energy_level?: 'low' | 'medium' | 'high';
  default_emotion?: string;
  /** Segment 2 §1.3:愤怒模式描述,可空。 */
  anger_style?: string | null;
  /** Persona v2 · 助手卡专属:她真正想要的(渲染进 C2b) */
  deepest_want?: string | null;
  /** Persona v2 · 助手卡专属:她最怕的(渲染进 C2b) */
  core_fear?: string | null;
}

export interface PersonaSpeechStyle {
  vocabulary?: string;
  sentence_rhythm?: string;
  user_address?: string;
  emoji_habit?: string;
  punctuation_quirk?: string;
  /** 0.0~1.0;Segment 2 §1.2 voice_samples filter 用。 */
  cliche_tolerance?: number;
  /** Persona v2 · 助手卡专属:怎么读用户、怎么决定接话(渲染进 C3a) */
  behavior?: string | null;
  /** Persona v2 · 助手卡专属:几条说话铁律(渲染进 C3a-2) */
  voice_rules?: string[];
}

export interface VoiceSample {
  scene: string;
  text: string;
  /** 双滑块 [min, max],各 0.0~1.0。Segment 2 §1.2。 */
  tolerance_range?: [number, number];
}

export interface PersonaForbiddenPhrases {
  _global?: string[];
  _character?: string[];
  _qwen?: string[];
  _deepseek?: string[];
}

export interface PersonaRelationshipToUser {
  type?: 'companion' | 'lover' | 'mentor' | 'companion_secretary' | string;
  intimacy_progression?: 'linear' | 'milestone' | string;
  initial_intimacy?: number;
  intimacy_rules?: Record<string, unknown>;
  /** Persona v2 · 助手卡专属:与用户的定位陈述(渲染进 C1c) */
  positioning?: string | null;
  /** Persona v2 · 助手卡专属:边界声明(渲染进 C1c) */
  boundary?: string | null;
}

/** Persona v2 · 卡型枚举。'社交' = DailyAgent + 主动陪伴;'助手' = 无独立日程,
 *  通过用户驱动接话。后端 character_personas.card_type 列(seg3 迁移)。 */
export type PersonaCardType = '社交' | '助手';

export interface CharacterPersonaRow {
  id: number;
  character_id: number;
  variant_name: string;
  is_builtin: boolean;
  is_active: boolean;
  display_order: number;
  description: string | null;
  // Tier-1
  identity: PersonaIdentity;
  personality_core: PersonaPersonalityCore;
  speech_style: PersonaSpeechStyle;
  signature_phrases: string[];
  voice_samples: VoiceSample[];
  forbidden_phrases: PersonaForbiddenPhrases;
  relationship_to_user: PersonaRelationshipToUser;
  // Tier-2(MVP UI 仅 read-only 显示,不编辑;v4.2 加全字段编辑)
  taboo_topics: unknown | null;
  lore: unknown | null;
  /** @deprecated v4.2 → DROP COLUMN · 0 模板引用 · 编辑器不暴露 */
  capability_overrides: unknown | null;
  /** @deprecated v4.2 → DROP COLUMN · 编辑器不暴露 · CharacterDetailModal 仅只读展示 */
  style_preset: string;
  /** Persona v2 · '社交' | '助手' · gate 元数据 · 前端编辑器分表单 */
  card_type: PersonaCardType | string;
  created_at: string | null;
  updated_at: string | null;
}

// ---------------------------------------------------------------------------
// CRUD client
// ---------------------------------------------------------------------------

async function _handleJson<T>(resp: Response, action: string): Promise<T> {
  if (!resp.ok) {
    let msg = `${action} failed: ${resp.status}`;
    try {
      const j = await resp.json();
      if (j?.detail) msg = String(j.detail);
    } catch { /* ignore */ }
    throw new Error(msg);
  }
  return (await resp.json()) as T;
}

export async function listPersonas(
  characterId: number,
): Promise<CharacterPersonaRow[]> {
  const res = await fetch(
    `${BACKEND_BASE}/api/characters/${characterId}/personas`,
  );
  return _handleJson<CharacterPersonaRow[]>(res, 'list personas');
}

export async function getActivePersona(
  characterId: number,
): Promise<CharacterPersonaRow> {
  const res = await fetch(
    `${BACKEND_BASE}/api/characters/${characterId}/personas/active`,
  );
  return _handleJson<CharacterPersonaRow>(res, 'get active persona');
}

export async function getPersona(personaId: number): Promise<CharacterPersonaRow> {
  const res = await fetch(`${BACKEND_BASE}/api/personas/${personaId}`);
  return _handleJson<CharacterPersonaRow>(res, 'get persona');
}

/** Create body 必含 Tier-1 7 字段;Tier-2 可选。 */
export interface CreatePersonaBody {
  variant_name: string;
  description?: string | null;
  /** @deprecated v4.2 · 编辑器不再传 · backend 默认 'anime_classic' */
  style_preset?: string | null;
  display_order?: number;
  /** Persona v2 · '社交' | '助手' · 缺省 '社交' */
  card_type?: PersonaCardType | string | null;
  identity: PersonaIdentity;
  personality_core: PersonaPersonalityCore;
  speech_style: PersonaSpeechStyle;
  signature_phrases: string[];
  voice_samples: VoiceSample[];
  forbidden_phrases: PersonaForbiddenPhrases;
  relationship_to_user: PersonaRelationshipToUser;
  taboo_topics?: unknown | null;
  lore?: unknown | null;
  /** @deprecated v4.2 */
  capability_overrides?: unknown | null;
}

export async function createPersona(
  characterId: number, body: CreatePersonaBody,
): Promise<CharacterPersonaRow> {
  const res = await fetch(
    `${BACKEND_BASE}/api/characters/${characterId}/personas`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    },
  );
  return _handleJson<CharacterPersonaRow>(res, 'create persona');
}

export type PatchPersonaBody = Partial<CreatePersonaBody>;

export async function patchPersona(
  personaId: number, body: PatchPersonaBody,
): Promise<CharacterPersonaRow> {
  const res = await fetch(`${BACKEND_BASE}/api/personas/${personaId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return _handleJson<CharacterPersonaRow>(res, 'patch persona');
}

export async function deletePersona(personaId: number): Promise<void> {
  const res = await fetch(`${BACKEND_BASE}/api/personas/${personaId}`, {
    method: 'DELETE',
  });
  if (!res.ok && res.status !== 204) {
    let msg = `delete persona failed: ${res.status}`;
    try {
      const j = await res.json();
      if (j?.detail) msg = String(j.detail);
    } catch { /* ignore */ }
    throw new Error(msg);
  }
}

export interface ActivatePersonaResponse extends CharacterPersonaRow {
  just_switched: boolean;
}

export async function activatePersona(
  personaId: number,
): Promise<ActivatePersonaResponse> {
  const res = await fetch(
    `${BACKEND_BASE}/api/personas/${personaId}/activate`,
    { method: 'POST' },
  );
  return _handleJson<ActivatePersonaResponse>(res, 'activate persona');
}

export async function restorePersonaToBuiltin(
  personaId: number,
): Promise<CharacterPersonaRow> {
  const res = await fetch(
    `${BACKEND_BASE}/api/personas/${personaId}/restore_to_builtin`,
    { method: 'POST' },
  );
  return _handleJson<CharacterPersonaRow>(res, 'restore persona');
}
