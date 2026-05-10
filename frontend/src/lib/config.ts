const BACKEND_BASE = 'http://127.0.0.1:8000';

export interface AppConfig {
  default_model: string;
  default_user_id: string;
  memory: {
    long_term_enabled: boolean;
    profile_enabled: boolean;
  };
  search: {
    enable_search: boolean;
  };
  cache: {
    profile_ttl_seconds: number;
  };
  tts: {
    enabled: boolean;
  };
  // v3-G chunk 2 / 2.6: 主动陪伴（proactive engine）配置。前端 SettingsPanel
  // 主动陪伴 section 镜像它，写回经 setConfigField + /api/config/reload。
  proactive: {
    enabled: boolean;
    // chunk 2.6: mode 互斥决定哪个 trigger 上 cron
    // 'wake_call' = 模式 B 邀请对话（推荐）
    // 'morning_briefing' = 模式 A 单方面播报
    // 'off' = 不注册任何 cron
    mode: 'wake_call' | 'morning_briefing' | 'off';
    character_id_override: number | null;
    morning_briefing: {
      enabled: boolean;
      cron: string;
      city: string;
    };
    wake_call_briefing: {
      cron: string;
      pending_ttl_minutes: number;
      default_snooze_minutes: number;
      city: string;
    };
  };
}

export type ProactiveMode = 'wake_call' | 'morning_briefing' | 'off';

export async function fetchConfig(): Promise<AppConfig> {
  const res = await fetch(`${BACKEND_BASE}/api/config`);
  if (!res.ok) throw new Error(`fetch config failed: ${res.status}`);
  return (await res.json()) as AppConfig;
}

export interface HealthResponse {
  status: 'ready' | 'warming' | string;
  models: Record<string, string>;
}

export async function fetchHealth(): Promise<HealthResponse> {
  const res = await fetch(`${BACKEND_BASE}/api/health`);
  if (!res.ok) throw new Error(`fetch health failed: ${res.status}`);
  return (await res.json()) as HealthResponse;
}

// ---------------------------------------------------------------------------
// v3-B 补丁: 通用设定 (base_instruction)
// ---------------------------------------------------------------------------

export interface BaseInstructionResponse {
  base_instruction: string;
}

export async function fetchBaseInstruction(): Promise<string> {
  const res = await fetch(`${BACKEND_BASE}/api/config/base_instruction`);
  if (!res.ok) throw new Error(`fetch base_instruction failed: ${res.status}`);
  const data = (await res.json()) as BaseInstructionResponse;
  return data.base_instruction ?? '';
}

export async function updateBaseInstruction(value: string): Promise<void> {
  const res = await fetch(`${BACKEND_BASE}/api/config/base_instruction`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ base_instruction: value }),
  });
  if (!res.ok) {
    let msg = `update base_instruction failed: ${res.status}`;
    try {
      const j = await res.json();
      if (j?.detail) msg = String(j.detail);
    } catch { /* ignore */ }
    throw new Error(msg);
  }
}

// ---------------------------------------------------------------------------
// V2.5-C: characters / conversations / messages
// ---------------------------------------------------------------------------

export interface CharacterRow {
  id: number;
  name: string;
  persona: string;
  avatar_path: string | null;
  // v3-B: 角色专属 TTS 音色标识，留空表示沿用全局默认（仅存不用）
  voice_model: string | null;
  // v3-E1: Live2D 模型目录名（对应 frontend/public/live2d/<name>/）。
  // 留空表示该角色不启用 Live2D，渲染层回退到 avatar_path 静态图片。
  live2d_model: string | null;
  // v3-E2: per-character emotion / motion / hit-area map，JSON 字符串。
  // null / 空 / parse 失败 → resolveCharacterMaps 回退到 config/live2d.ts
  // 全局默认（v3-E1 已 ship 的 motionMap / emotionMap）。
  emotion_map_json:  string | null;
  motion_map_json:   string | null;
  hit_area_map_json: string | null;
  // v3.5 chunk 5a: per-character 背景层 URL（image / video）。null = 用
  // CharacterView 原 fallback 链（Live2D → 静态 jpeg），完全兼容旧角色。
  background_path:   string | null;
  created_at: string | null;
}

export interface ConversationRow {
  id: number;
  user_id: string;
  character_id: number;
  title: string;
  created_at: string | null;
  updated_at: string | null;
  message_count: number;
}

// v3-E1 Step Z.2：chat_history.kind —— 'normal' 默认；'touch' 是用户点击 Live2D
// 触发的对话（user 占位 [touch] + AI 主动回应一句）；'proactive' 预留给 v3-F'
// 后端定时调度器主动开启的对话。前端按 kind 做渲染区分（user 侧 [touch] 显示
// 成"（碰了一下）"灰字而不是裸字符串）。
export type ChatKind = 'normal' | 'touch' | 'proactive';

export interface ChatMessageRow {
  id: number;
  role: 'user' | 'assistant';
  content: string;
  conversation_id: number | null;
  character_id: number | null;
  created_at: string | null;
  kind: ChatKind;
  // v3-G chunk 2: 当 kind='proactive' 时记录 trigger.name（'morning_briefing'）；
  // 其他 kind 为 null。
  proactive_trigger?: string | null;
}

export async function fetchCharacters(): Promise<CharacterRow[]> {
  const res = await fetch(`${BACKEND_BASE}/api/characters/list`);
  if (!res.ok) throw new Error(`fetch characters failed: ${res.status}`);
  return (await res.json()) as CharacterRow[];
}

export async function createCharacter(body: {
  name: string;
  persona: string;
  avatar_path?: string | null;
  voice_model?: string | null;
  live2d_model?: string | null;
  // v3-E2 可选 per-character maps
  emotion_map_json?: string | null;
  motion_map_json?: string | null;
  hit_area_map_json?: string | null;
  // v3.5 chunk 5a
  background_path?: string | null;
}): Promise<CharacterRow> {
  const res = await fetch(`${BACKEND_BASE}/api/characters/create`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let msg = `create character failed: ${res.status}`;
    try {
      const j = await res.json();
      if (j?.detail) msg = String(j.detail);
    } catch { /* ignore */ }
    throw new Error(msg);
  }
  return (await res.json()) as CharacterRow;
}

export async function patchCharacter(
  id: number,
  body: {
    name?: string;
    persona?: string;
    avatar_path?: string | null;
    voice_model?: string | null;
    live2d_model?: string | null;
    // v3-E2 可选 per-character maps
    emotion_map_json?: string | null;
    motion_map_json?: string | null;
    hit_area_map_json?: string | null;
    // v3.5 chunk 5a：null 表示清除，字符串覆盖
    background_path?: string | null;
  },
): Promise<CharacterRow> {
  const res = await fetch(`${BACKEND_BASE}/api/characters/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let msg = `patch character failed: ${res.status}`;
    try {
      const j = await res.json();
      if (j?.detail) msg = String(j.detail);
    } catch { /* ignore */ }
    throw new Error(msg);
  }
  return (await res.json()) as CharacterRow;
}

export async function deleteCharacter(id: number): Promise<void> {
  const res = await fetch(`${BACKEND_BASE}/api/characters/${id}`, {
    method: 'DELETE',
  });
  if (!res.ok && res.status !== 204) {
    let msg = `delete character failed: ${res.status}`;
    try {
      const j = await res.json();
      if (j?.detail) msg = String(j.detail);
    } catch { /* ignore */ }
    throw new Error(msg);
  }
}

export async function fetchConversations(
  userId: string,
  characterId?: number,
): Promise<ConversationRow[]> {
  const url = new URL(`${BACKEND_BASE}/api/conversations/list`);
  url.searchParams.set('user_id', userId);
  if (characterId !== undefined) {
    url.searchParams.set('character_id', String(characterId));
  }
  const res = await fetch(url.toString());
  if (!res.ok) throw new Error(`fetch conversations failed: ${res.status}`);
  return (await res.json()) as ConversationRow[];
}

export async function fetchMessages(conversationId: number): Promise<ChatMessageRow[]> {
  const res = await fetch(`${BACKEND_BASE}/api/conversations/${conversationId}/messages`);
  if (!res.ok) throw new Error(`fetch messages failed: ${res.status}`);
  return (await res.json()) as ChatMessageRow[];
}

export async function createConversation(
  userId: string,
  characterId: number,
  title?: string,
): Promise<ConversationRow> {
  const body: Record<string, unknown> = { user_id: userId, character_id: characterId };
  if (title) body.title = title;
  const res = await fetch(`${BACKEND_BASE}/api/conversations/create`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`create conversation failed: ${res.status}`);
  return (await res.json()) as ConversationRow;
}

export async function patchConversation(
  conversationId: number,
  patch: { title?: string },
): Promise<ConversationRow> {
  const res = await fetch(`${BACKEND_BASE}/api/conversations/${conversationId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  });
  if (!res.ok) throw new Error(`patch conversation failed: ${res.status}`);
  return (await res.json()) as ConversationRow;
}

export async function deleteConversation(conversationId: number): Promise<void> {
  const res = await fetch(`${BACKEND_BASE}/api/conversations/${conversationId}`, {
    method: 'DELETE',
  });
  if (!res.ok && res.status !== 204) {
    throw new Error(`delete conversation failed: ${res.status}`);
  }
}
