import { create } from 'zustand';
import type { AppConfig, CharacterRow, ConversationRow } from '../lib/config';

export type AppMode = 'widget' | 'panel';
export type AiStatus = 'idle' | 'listening' | 'thinking' | 'speaking' | 'interrupted';
export type RecordingMode = 'manual' | 'vad';
export type InputMode = 'voice' | 'text';
export type ConnectionStatus = 'disconnected' | 'connecting' | 'connected';
export type VadState = 'sleep' | 'active' | 'recording';

interface AppNotification {
  id: string;
  type: 'notify' | 'alarm';
  content: string;
  todoId?: number;
  ts: number;
}

// V2.5-C — chat history rendering (in-memory; per-conversation refresh on switch)
export interface ChatMessage {
  id: string;            // client-side id; for assistant streaming this stays stable
  role: 'user' | 'assistant';
  content: string;
  streaming: boolean;    // true while text_chunks still arriving for an assistant msg
  ts: number;            // performance.now() at create-time, used as React key tie-breaker
}

// V2.5-C2 — ConversationList collapse persistence
const CONV_LIST_COLLAPSED_KEY = 'momoos.convListCollapsed';

function readCollapsedFromStorage(): boolean {
  try {
    const raw = localStorage.getItem(CONV_LIST_COLLAPSED_KEY);
    return raw === 'true';
  } catch {
    return false;
  }
}

function writeCollapsedToStorage(v: boolean): void {
  try {
    localStorage.setItem(CONV_LIST_COLLAPSED_KEY, v ? 'true' : 'false');
  } catch {
    // localStorage unavailable (private mode / disabled) — silently ignore
  }
}

// V2.5-D — start-up mode persistence. First-run default is 'panel' so a fresh
// install lands the user in the full UI; subsequent launches restore whatever
// they last selected.
const MODE_KEY = 'momoos.mode';

function readModeFromStorage(): AppMode {
  try {
    const raw = localStorage.getItem(MODE_KEY);
    if (raw === 'widget' || raw === 'panel') return raw;
  } catch {
    // fall through
  }
  return 'panel';
}

function writeModeToStorage(m: AppMode): void {
  try {
    localStorage.setItem(MODE_KEY, m);
  } catch {
    // localStorage unavailable — silently ignore
  }
}

// v3-A — 主题持久化。8 套主题 key 见 themes.css；默认 dusk。
const THEME_KEY = 'momoos.theme';
const VALID_THEMES = [
  'morandi', 'dusk', 'glass', 'watercolor',
  'aurora', 'sakura', 'cyber', 'lavender',
] as const;
export type ThemeKey = (typeof VALID_THEMES)[number];

function readThemeFromStorage(): ThemeKey {
  try {
    const raw = localStorage.getItem(THEME_KEY);
    if (raw && (VALID_THEMES as readonly string[]).includes(raw)) return raw as ThemeKey;
  } catch {
    // fall through
  }
  return 'dusk';
}

function writeThemeToStorage(t: ThemeKey): void {
  try {
    localStorage.setItem(THEME_KEY, t);
  } catch {
    // localStorage unavailable — silently ignore
  }
}

function applyThemeToDom(t: ThemeKey): void {
  if (typeof document !== 'undefined') {
    document.documentElement.dataset.theme = t;
  }
}

interface AppState {
  // 窗口模式
  mode: AppMode;
  setMode: (mode: AppMode) => void;

  // v3-A — UI 主题（8 套，见 styles/themes.css）
  theme: ThemeKey;
  setTheme: (theme: ThemeKey) => void;

  // AI 状态
  status: AiStatus;
  setStatus: (status: AiStatus) => void;

  // 录音
  recording: boolean;
  setRecording: (v: boolean) => void;
  recordingMode: RecordingMode;
  setRecordingMode: (m: RecordingMode) => void;

  // 输入模式
  inputMode: InputMode;
  setInputMode: (m: InputMode) => void;

  // 连接状态
  connection: ConnectionStatus;
  setConnection: (c: ConnectionStatus) => void;

  // ASR 回显（模块 7 才接真实数据，本模块只放接口）
  asrText: string;
  setAsrText: (t: string) => void;
  asrTimestamp: number; // 最后一次 setAsrText 的时间戳，用于 5 秒淡出

  // Panel 子视图
  panelView: 'chat' | 'settings' | 'characters';
  setPanelView: (v: 'chat' | 'settings' | 'characters') => void;

  // ConversationList 折叠状态（持久化到 localStorage）
  conversationListCollapsed: boolean;
  setConversationListCollapsed: (v: boolean) => void;

  // 诊断用：用户最近一次发送 user message 的 performance.now() 时间戳
  // 仅前端 in-memory，所有前端 WS 接收 timer 都相对它计算 elapsed
  lastSendTimestamp: number;
  setLastSendTimestamp: (t: number) => void;

  // VAD 状态
  vadState: VadState;
  setVadState: (s: VadState) => void;

  // 麦克风全局静音（Momo 说话时）
  micMuted: boolean;
  setMicMuted: (v: boolean) => void;

  // 通知 / 闹钟队列（最近 5 条，UI 用）
  notifications: AppNotification[];
  pushNotification: (n: { type: 'notify' | 'alarm'; content: string; todoId?: number }) => void;

  // VAD 参数（v2 模块 9 设置面板才能改，本模块用默认值）
  vadThreshold: number;       // 默认 65（0–100 区间）
  setVadThreshold: (v: number) => void;
  silenceTimeoutMs: number;   // 默认 1500
  setSilenceTimeoutMs: (v: number) => void;
  vadIdleTimeoutMs: number;   // 默认 60000，VAD active 状态 60s 无录音回 sleep
  muteWhileSpeaking: boolean; // 默认 true，Momo 说话时静音麦克风
  setMuteWhileSpeaking: (v: boolean) => void;

  // TTS 开关
  ttsEnabled: boolean;
  setTtsEnabled: (v: boolean) => void;

  // 镜像 GET /api/config 的字段（启动时由 syncFromConfig 写入）
  defaultUserId: string;
  setDefaultUserId: (v: string) => void;
  defaultModel: string;
  setDefaultModel: (v: string) => void;
  longTermEnabled: boolean;
  setLongTermEnabled: (v: boolean) => void;
  profileEnabled: boolean;
  setProfileEnabled: (v: boolean) => void;
  enableSearch: boolean;
  setEnableSearch: (v: boolean) => void;

  // V2.5-C — characters / conversations / chat history
  characters: CharacterRow[];
  setCharacters: (v: CharacterRow[]) => void;
  currentCharacterId: number | null;
  setCurrentCharacterId: (v: number | null) => void;

  conversations: ConversationRow[];
  setConversations: (v: ConversationRow[]) => void;
  upsertConversation: (c: ConversationRow) => void;
  removeConversation: (id: number) => void;
  currentConversationId: number | null;
  setCurrentConversationId: (v: number | null) => void;

  chatMessages: ChatMessage[];
  setChatMessages: (v: ChatMessage[]) => void;
  appendChatMessage: (m: ChatMessage) => void;
  // Append text to the message identified by *id* without re-creating the array.
  // Returns nothing; callers don't need the message instance back.
  appendChatMessageContent: (id: string, delta: string) => void;
  // Flip streaming false on the message identified by *id*.
  finishChatMessage: (id: string) => void;
  // Drop the message identified by *id* (used for error rollback).
  removeChatMessage: (id: string) => void;
  // Streaming context — id of the currently in-flight assistant message
  streamingMessageId: string | null;
  setStreamingMessageId: (v: string | null) => void;

  syncFromConfig: (c: AppConfig) => void;
}

export const useAppStore = create<AppState>((set) => ({
  mode: readModeFromStorage(),
  setMode: (mode) => {
    writeModeToStorage(mode);
    set({ mode });
  },

  theme: readThemeFromStorage(),
  setTheme: (theme) => {
    writeThemeToStorage(theme);
    applyThemeToDom(theme);
    set({ theme });
  },

  status: 'idle',
  setStatus: (status) => set({ status }),

  recording: false,
  setRecording: (recording) => set({ recording }),
  recordingMode: 'manual',
  setRecordingMode: (recordingMode) => set({ recordingMode }),

  inputMode: 'voice',
  setInputMode: (inputMode) => set({ inputMode }),

  connection: 'disconnected',
  setConnection: (connection) => set({ connection }),

  asrText: '',
  asrTimestamp: 0,
  setAsrText: (asrText) => set({ asrText, asrTimestamp: Date.now() }),

  panelView: 'chat',
  setPanelView: (panelView) => set({ panelView }),

  conversationListCollapsed: readCollapsedFromStorage(),
  setConversationListCollapsed: (conversationListCollapsed) => {
    writeCollapsedToStorage(conversationListCollapsed);
    set({ conversationListCollapsed });
  },

  lastSendTimestamp: 0,
  setLastSendTimestamp: (lastSendTimestamp) => set({ lastSendTimestamp }),

  vadState: 'sleep',
  setVadState: (vadState) => set({ vadState }),

  micMuted: false,
  setMicMuted: (micMuted) => set({ micMuted }),

  notifications: [],
  pushNotification: ({ type, content, todoId }) =>
    set((s) => ({
      notifications: [
        ...s.notifications.slice(-4),
        { id: `${Date.now()}-${Math.random()}`, type, content, todoId, ts: Date.now() },
      ],
    })),

  vadThreshold: 65,
  setVadThreshold: (vadThreshold) => set({ vadThreshold }),
  silenceTimeoutMs: 1500,
  setSilenceTimeoutMs: (silenceTimeoutMs) => set({ silenceTimeoutMs }),
  vadIdleTimeoutMs: 60000,
  muteWhileSpeaking: true,
  setMuteWhileSpeaking: (muteWhileSpeaking) => set({ muteWhileSpeaking }),

  ttsEnabled: true,
  setTtsEnabled: (ttsEnabled) => set({ ttsEnabled }),

  defaultUserId: 'default',
  setDefaultUserId: (defaultUserId) => set({ defaultUserId }),
  defaultModel: '',
  setDefaultModel: (defaultModel) => set({ defaultModel }),
  longTermEnabled: true,
  setLongTermEnabled: (longTermEnabled) => set({ longTermEnabled }),
  profileEnabled: true,
  setProfileEnabled: (profileEnabled) => set({ profileEnabled }),
  enableSearch: true,
  setEnableSearch: (enableSearch) => set({ enableSearch }),

  characters: [],
  setCharacters: (characters) => set({ characters }),
  currentCharacterId: null,
  setCurrentCharacterId: (currentCharacterId) => set({ currentCharacterId }),

  conversations: [],
  setConversations: (conversations) => set({ conversations }),
  upsertConversation: (c) =>
    set((s) => {
      const idx = s.conversations.findIndex((x) => x.id === c.id);
      if (idx === -1) return { conversations: [c, ...s.conversations] };
      const next = s.conversations.slice();
      next[idx] = c;
      return { conversations: next };
    }),
  removeConversation: (id) =>
    set((s) => ({ conversations: s.conversations.filter((c) => c.id !== id) })),
  currentConversationId: null,
  setCurrentConversationId: (currentConversationId) => set({ currentConversationId }),

  chatMessages: [],
  setChatMessages: (chatMessages) => set({ chatMessages }),
  appendChatMessage: (m) =>
    set((s) => ({ chatMessages: [...s.chatMessages, m] })),
  // Mutate-in-place on the streaming message: replace ONLY that one entry in the
  // array, leave all others by-reference. React + zustand's shallow comparison
  // re-renders only ChatHistory's last child whose key matches the changed id.
  appendChatMessageContent: (id, delta) =>
    set((s) => {
      const idx = s.chatMessages.findIndex((m) => m.id === id);
      if (idx === -1) return {};
      const next = s.chatMessages.slice();
      const old = next[idx];
      next[idx] = { ...old, content: old.content + delta };
      return { chatMessages: next };
    }),
  finishChatMessage: (id) =>
    set((s) => {
      const idx = s.chatMessages.findIndex((m) => m.id === id);
      if (idx === -1) return {};
      const next = s.chatMessages.slice();
      next[idx] = { ...next[idx], streaming: false };
      return { chatMessages: next };
    }),
  removeChatMessage: (id) =>
    set((s) => ({ chatMessages: s.chatMessages.filter((m) => m.id !== id) })),
  streamingMessageId: null,
  setStreamingMessageId: (streamingMessageId) => set({ streamingMessageId }),

  syncFromConfig: (c) =>
    set({
      defaultUserId: c.default_user_id,
      defaultModel: c.default_model,
      longTermEnabled: c.memory.long_term_enabled,
      profileEnabled: c.memory.profile_enabled,
      enableSearch: c.search.enable_search,
      ttsEnabled: c.tts.enabled,
    }),
}));
