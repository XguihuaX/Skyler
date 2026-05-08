import { create } from 'zustand';
import type { AppConfig, CharacterRow, ChatKind, ConversationRow, ProactiveMode } from '../lib/config';
import type { CharacterStateResponse } from '../lib/integrations';
import type { Live2DModel } from '../lib/live2d';
import type { TtsProvider } from '../lib/tts';

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
  // v3-E1 Step Z.2：与后端 chat_history.kind 同步。store 创建侧默认 'normal'，
  // API 加载侧透传后端值。'touch' 行 user-side 渲染成"（碰了一下）"灰字。
  kind: ChatKind;
  // v3-G chunk 2: proactive 行的触发器名（'morning_briefing' / null）。
  // ChatHistory 按这个字段映射 "🌅（早安简报）" 灰字前缀；非 proactive 行始
  // 终为空。流式期间由 useWebSocket 从 WS chunk 的 proactive_trigger 字段
  // 写入；历史加载时由后端 conversations API 透传。
  proactiveTrigger?: string;
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

// v3-G chunk 3b — 状态条显示开关。SettingsPanel [角色] section 控；默认 on。
const SHOW_STATE_PANEL_KEY = 'momoos.showStatePanel';

function _readShowStatePanelFromStorage(): boolean {
  try {
    const raw = localStorage.getItem(SHOW_STATE_PANEL_KEY);
    if (raw === 'false') return false;
    return true;
  } catch {
    return true;
  }
}

function _writeShowStatePanelToStorage(v: boolean): void {
  try {
    localStorage.setItem(SHOW_STATE_PANEL_KEY, v ? 'true' : 'false');
  } catch {
    // localStorage unavailable — silently ignore
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

  // v3-F: AI 内心独白（每轮最多一次，由后端 thinking 消息推送）
  // null = 当前轮没有 thinking。由 WS 'thinking' 消息写入；新轮开始（用户发送）
  // 时由调用方 clear。UI 在 StatusBadge 旁短暂显示。
  currentThinking: string | null;
  setCurrentThinking: (v: string | null) => void;
  clearCurrentThinking: () => void;

  // v3-E1 step5: AI 当轮情感（每轮最多一次，由后端 emotion 消息推送）
  // null = 当前轮无 emotion 标签（中性消息）/ 还没收到。由 WS 'emotion' 消息
  // 写入；新轮开始时由调用方 clear。
  // 值为 LLM 原始输出，透传不归一化（happy / sad / angry / surprised /
  // fearful / disgusted 等英文枚举，详见 config.yaml emotions）。
  // 当前消费方：Live2DCanvas useEffect 监听点（v3-E1 step5 仅 console.log；
  // v3-E2 换模型后接入 emotionMap → expression / param 调用）。
  currentEmotion: string | null;
  setCurrentEmotion: (v: string | null) => void;
  clearCurrentEmotion: () => void;

  // v3-E1 step6: AI 当段动作（每段可命中一次，由后端 motion 消息推送）
  // null = 当前没有待触发动作（新轮开始 / 上次已消费完）。WS 'motion' 写入；
  // 调用方在 sendText / sendVoice / sendTouch 开始新轮时 clear。
  // 值为 LLM 输出的中文动作名（可用词以 config/live2d.ts motionMap 为准）。
  // 与 currentEmotion 区别：emotion per-turn 一次，motion per-segment 多次。
  // 消费方：Live2DCanvas useEffect 通过 motionMap 查 group/index 调
  // model.motion(group, index, NORMAL)。motionMap 没覆盖的词降级 no-op。
  currentMotion: string | null;
  setCurrentMotion: (v: string | null) => void;
  clearCurrentMotion: () => void;

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

  // v3-G chunk 2 / 2.6 — 主动陪伴 (proactive engine) 配置镜像。SettingsPanel
  // [主动陪伴] section 写回经 setConfigField；/api/config GET 时由
  // syncFromConfig 拉回填。
  proactiveEnabled: boolean;
  setProactiveEnabled: (v: boolean) => void;
  proactiveMode: ProactiveMode;
  setProactiveMode: (v: ProactiveMode) => void;
  proactiveCharOverride: number | null;
  setProactiveCharOverride: (v: number | null) => void;
  morningBriefingEnabled: boolean;
  setMorningBriefingEnabled: (v: boolean) => void;
  morningBriefingCron: string;
  setMorningBriefingCron: (v: string) => void;
  morningBriefingCity: string;
  setMorningBriefingCity: (v: string) => void;
  wakeCallCron: string;
  setWakeCallCron: (v: string) => void;
  wakeCallPendingTtlMinutes: number;
  setWakeCallPendingTtlMinutes: (v: number) => void;
  wakeCallDefaultSnoozeMinutes: number;
  setWakeCallDefaultSnoozeMinutes: (v: number) => void;
  wakeCallCity: string;
  setWakeCallCity: (v: string) => void;

  // v3-G chunk 3b — 角色状态。WS 'state_update' 事件 / 启动时 fetch 写入。
  // null = 还没加载。CharacterStatePanel 监听显示 mood emoji + intimacy。
  currentCharacterState: CharacterStateResponse | null;
  setCurrentCharacterState: (v: CharacterStateResponse | null) => void;
  showCharacterStatePanel: boolean;
  setShowCharacterStatePanel: (v: boolean) => void;

  // V2.5-C — characters / conversations / chat history
  characters: CharacterRow[];
  setCharacters: (v: CharacterRow[]) => void;
  currentCharacterId: number | null;
  setCurrentCharacterId: (v: number | null) => void;

  // v3-E2 commit 3b — Live2D 模型扫描结果，CharacterPanel 下拉数据源。
  // 由 GET /api/live2d/models 填充；CharacterPanel mount 和点击刷新按钮时拉。
  live2dModels: Live2DModel[];
  setLive2dModels: (v: Live2DModel[]) => void;

  // v3-G' chunk 1b — TTS provider + voice 清单，CharacterPanel 两级下拉数据源。
  // 由 GET /api/tts/voices 填充；App.tsx mount 时 eager-load。
  ttsProviders: TtsProvider[];
  setTtsProviders: (v: TtsProvider[]) => void;

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

  currentThinking: null,
  setCurrentThinking: (currentThinking) => set({ currentThinking }),
  clearCurrentThinking: () => set({ currentThinking: null }),

  currentEmotion: null,
  setCurrentEmotion: (currentEmotion) => set({ currentEmotion }),
  clearCurrentEmotion: () => set({ currentEmotion: null }),

  currentMotion: null,
  setCurrentMotion: (currentMotion) => set({ currentMotion }),
  clearCurrentMotion: () => set({ currentMotion: null }),

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

  proactiveEnabled: true,
  setProactiveEnabled: (proactiveEnabled) => set({ proactiveEnabled }),
  proactiveMode: 'wake_call',
  setProactiveMode: (proactiveMode) => set({ proactiveMode }),
  proactiveCharOverride: null,
  setProactiveCharOverride: (proactiveCharOverride) => set({ proactiveCharOverride }),
  morningBriefingEnabled: true,
  setMorningBriefingEnabled: (morningBriefingEnabled) => set({ morningBriefingEnabled }),
  morningBriefingCron: '0 9 * * *',
  setMorningBriefingCron: (morningBriefingCron) => set({ morningBriefingCron }),
  morningBriefingCity: '东京',
  setMorningBriefingCity: (morningBriefingCity) => set({ morningBriefingCity }),
  wakeCallCron: '0 8 * * *',
  setWakeCallCron: (wakeCallCron) => set({ wakeCallCron }),
  wakeCallPendingTtlMinutes: 30,
  setWakeCallPendingTtlMinutes: (wakeCallPendingTtlMinutes) => set({ wakeCallPendingTtlMinutes }),
  wakeCallDefaultSnoozeMinutes: 30,
  setWakeCallDefaultSnoozeMinutes: (wakeCallDefaultSnoozeMinutes) =>
    set({ wakeCallDefaultSnoozeMinutes }),
  wakeCallCity: '东京',
  setWakeCallCity: (wakeCallCity) => set({ wakeCallCity }),

  currentCharacterState: null,
  setCurrentCharacterState: (currentCharacterState) => set({ currentCharacterState }),
  showCharacterStatePanel: _readShowStatePanelFromStorage(),
  setShowCharacterStatePanel: (showCharacterStatePanel) => {
    _writeShowStatePanelToStorage(showCharacterStatePanel);
    set({ showCharacterStatePanel });
  },

  characters: [],
  setCharacters: (characters) => set({ characters }),
  currentCharacterId: null,
  setCurrentCharacterId: (currentCharacterId) => set({ currentCharacterId }),

  live2dModels: [],
  setLive2dModels: (live2dModels) => set({ live2dModels }),

  ttsProviders: [],
  setTtsProviders: (ttsProviders) => set({ ttsProviders }),

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
      proactiveEnabled: c.proactive?.enabled ?? true,
      proactiveMode: c.proactive?.mode ?? 'wake_call',
      proactiveCharOverride: c.proactive?.character_id_override ?? null,
      morningBriefingEnabled: c.proactive?.morning_briefing?.enabled ?? true,
      morningBriefingCron: c.proactive?.morning_briefing?.cron ?? '0 9 * * *',
      morningBriefingCity: c.proactive?.morning_briefing?.city ?? '东京',
      wakeCallCron: c.proactive?.wake_call_briefing?.cron ?? '0 8 * * *',
      wakeCallPendingTtlMinutes:
        c.proactive?.wake_call_briefing?.pending_ttl_minutes ?? 30,
      wakeCallDefaultSnoozeMinutes:
        c.proactive?.wake_call_briefing?.default_snooze_minutes ?? 30,
      wakeCallCity: c.proactive?.wake_call_briefing?.city ?? '东京',
    }),
}));
