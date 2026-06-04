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
// 方案 1(右侧 chat panel 推拉)— 与 conv list 推拉对称。同样持久化到 localStorage。
const CHAT_PANEL_COLLAPSED_KEY = 'momoos.chatPanelCollapsed';
// 2026-06-05 · VAD/ASR LS keys — 从 SettingsPanelLegacy 搬过来,store init 直读
// 直写,取代原 AsrVadSection useEffect[] 懒 hydrate 模式(走"组件 mount 才同步"
// 路径会让 store 默认值在用户打开设置前一直跟 LS 不一致 · 切角色 / WS 重连 /
// 启动都不会拉齐 · 还存在 lazy hydrate 把上次 LS=vad 灌进当前 session 的 desync)。
const LS_RECORDING_MODE        = 'momoos.recordingMode';
const LS_VAD_POSITIVE          = 'momoos.vadPositiveThreshold';
const LS_VAD_REDEMPTION_MS     = 'momoos.vadRedemptionMs';
const LS_MUTE_SPEAKING         = 'momoos.muteWhileSpeaking';

const RECORDING_MODE_DEFAULT: 'manual' | 'vad' = 'manual';
// INV-17 v3.4 (2026-05-28) 实测:0.6 解决麦底噪 0.3-0.5 误触发。
const VAD_POSITIVE_DEFAULT = 0.6;
const VAD_POSITIVE_MIN = 0.1;
const VAD_POSITIVE_MAX = 0.9;
const VAD_REDEMPTION_MS_DEFAULT = 1400;
const VAD_REDEMPTION_MS_MIN = 500;
const VAD_REDEMPTION_MS_MAX = 3000;
const MUTE_SPEAKING_DEFAULT = true;

function readRecordingModeFromStorage(): 'manual' | 'vad' {
  try {
    const v = localStorage.getItem(LS_RECORDING_MODE);
    if (v === 'manual' || v === 'vad') return v;
    return RECORDING_MODE_DEFAULT;
  } catch { return RECORDING_MODE_DEFAULT; }
}
function writeRecordingModeToStorage(v: 'manual' | 'vad'): void {
  try { localStorage.setItem(LS_RECORDING_MODE, v); } catch { /* swallow */ }
}
function readVadPositiveFromStorage(): number {
  try {
    const raw = localStorage.getItem(LS_VAD_POSITIVE);
    if (raw === null) return VAD_POSITIVE_DEFAULT;
    const n = parseFloat(raw);
    if (Number.isFinite(n) && n >= VAD_POSITIVE_MIN && n <= VAD_POSITIVE_MAX) return n;
    return VAD_POSITIVE_DEFAULT;
  } catch { return VAD_POSITIVE_DEFAULT; }
}
function writeVadPositiveToStorage(v: number): void {
  try { localStorage.setItem(LS_VAD_POSITIVE, String(v)); } catch { /* swallow */ }
}
function readVadRedemptionMsFromStorage(): number {
  try {
    const raw = localStorage.getItem(LS_VAD_REDEMPTION_MS);
    if (raw === null) return VAD_REDEMPTION_MS_DEFAULT;
    const n = parseFloat(raw);
    if (Number.isFinite(n) && n >= VAD_REDEMPTION_MS_MIN && n <= VAD_REDEMPTION_MS_MAX) {
      return Math.round(n);
    }
    return VAD_REDEMPTION_MS_DEFAULT;
  } catch { return VAD_REDEMPTION_MS_DEFAULT; }
}
function writeVadRedemptionMsToStorage(v: number): void {
  try { localStorage.setItem(LS_VAD_REDEMPTION_MS, String(v)); } catch { /* swallow */ }
}
function readMuteSpeakingFromStorage(): boolean {
  try {
    const v = localStorage.getItem(LS_MUTE_SPEAKING);
    if (v === 'true') return true;
    if (v === 'false') return false;
    return MUTE_SPEAKING_DEFAULT;
  } catch { return MUTE_SPEAKING_DEFAULT; }
}
function writeMuteSpeakingToStorage(v: boolean): void {
  try { localStorage.setItem(LS_MUTE_SPEAKING, String(v)); } catch { /* swallow */ }
}

// 2026-05-19 — ConversationList 可拖拽宽度。default 240 (= 旧 w-60),clamp [160,400]。
const CONV_LIST_WIDTH_KEY = 'momoos.convListWidth';
export const CONV_LIST_WIDTH_DEFAULT = 240;
export const CONV_LIST_WIDTH_MIN = 160;
export const CONV_LIST_WIDTH_MAX = 400;
// 2026-05-19 — ChatHistoryPanel 可拖拽宽度。default 420 (= 旧 w-[420px]),
// clamp [320,600]:MIN 320 保证聊天可读;MAX 600 给立绘区留足最小宽度,
// 与 ConversationList MAX 400 + 各 handles/buttons 共存时立绘不会被挤没。
const CHAT_HISTORY_WIDTH_KEY = 'momoos.chatHistoryWidth';
export const CHAT_HISTORY_WIDTH_DEFAULT = 420;
export const CHAT_HISTORY_WIDTH_MIN = 320;
export const CHAT_HISTORY_WIDTH_MAX = 600;
// 2026-06-04 · Round 4 ③ — ChatHistoryPanel 可拖拽高度(px)。原 Round 3.5 浮卡
// 用 bottom:100 让高度跟视口走;现改固定 height 用户可调,左下角拖拽手柄同时
// 改宽 + 高。default 600 = 原 720-800 视口下 bottom:100 实际渲染高度的折中。
// clamp [240, 1200]:MIN 240 = 顶部 h-12 + ~6 条消息可读下限;MAX 1200 = 大屏
// 防无限拉(超过常见视口高度的极限值)。
const CHAT_HISTORY_HEIGHT_KEY = 'momoos.chatHistoryHeight';
export const CHAT_HISTORY_HEIGHT_DEFAULT = 600;
export const CHAT_HISTORY_HEIGHT_MIN = 240;
export const CHAT_HISTORY_HEIGHT_MAX = 1200;

// M1 Air 小屏降级阈值。视口 inner width < SMALL_VIEWPORT_PX → 默认两侧抽屉
// 都收起,优先保立绘 + 输入框;用户仍可手动展开。13" M1 Air 默认逻辑分辨率
// 1280×800,选 1280 作为分界让 13" 起就降级,15" 之上正常 expand。
export const SMALL_VIEWPORT_PX = 1280;

function readBoolStorage(key: string, defaultVal: boolean): boolean {
  try {
    const raw = localStorage.getItem(key);
    if (raw === 'true') return true;
    if (raw === 'false') return false;
    return defaultVal;
  } catch {
    return defaultVal;
  }
}

function writeBoolStorage(key: string, v: boolean): void {
  try {
    localStorage.setItem(key, v ? 'true' : 'false');
  } catch {
    // localStorage unavailable (private mode / disabled) — silently ignore
  }
}

function initialCollapsedDefault(): boolean {
  // 小屏首次启动两侧默认收起。已有持久化值 → 尊重用户上次选择。
  if (typeof window === 'undefined') return false;
  return window.innerWidth < SMALL_VIEWPORT_PX;
}

function readCollapsedFromStorage(): boolean {
  // 2026-06-03 · Round 3.4 · ConvList chip 化后默认收起(干净桌面)·
  // 已有 localStorage 值 → 尊重用户上次选择 · 没有 → 默认 true 显 chip。
  // 若想默认展开,把 true 改回 initialCollapsedDefault()。
  return readBoolStorage(CONV_LIST_COLLAPSED_KEY, true);
}

function writeCollapsedToStorage(v: boolean): void {
  writeBoolStorage(CONV_LIST_COLLAPSED_KEY, v);
}

function readChatPanelCollapsedFromStorage(): boolean {
  return readBoolStorage(CHAT_PANEL_COLLAPSED_KEY, initialCollapsedDefault());
}

function writeChatPanelCollapsedToStorage(v: boolean): void {
  writeBoolStorage(CHAT_PANEL_COLLAPSED_KEY, v);
}

function clampConvListWidth(v: number): number {
  if (!Number.isFinite(v)) return CONV_LIST_WIDTH_DEFAULT;
  if (v < CONV_LIST_WIDTH_MIN) return CONV_LIST_WIDTH_MIN;
  if (v > CONV_LIST_WIDTH_MAX) return CONV_LIST_WIDTH_MAX;
  return Math.round(v);
}

function readConvListWidthFromStorage(): number {
  try {
    const raw = localStorage.getItem(CONV_LIST_WIDTH_KEY);
    if (raw === null) return CONV_LIST_WIDTH_DEFAULT;
    const n = Number(raw);
    return clampConvListWidth(n);
  } catch {
    return CONV_LIST_WIDTH_DEFAULT;
  }
}

function writeConvListWidthToStorage(v: number): void {
  try {
    localStorage.setItem(CONV_LIST_WIDTH_KEY, String(v));
  } catch {
    // localStorage unavailable — silently ignore
  }
}

function clampChatHistoryWidth(v: number): number {
  if (!Number.isFinite(v)) return CHAT_HISTORY_WIDTH_DEFAULT;
  if (v < CHAT_HISTORY_WIDTH_MIN) return CHAT_HISTORY_WIDTH_MIN;
  if (v > CHAT_HISTORY_WIDTH_MAX) return CHAT_HISTORY_WIDTH_MAX;
  return Math.round(v);
}

function readChatHistoryWidthFromStorage(): number {
  try {
    const raw = localStorage.getItem(CHAT_HISTORY_WIDTH_KEY);
    if (raw === null) return CHAT_HISTORY_WIDTH_DEFAULT;
    const n = Number(raw);
    return clampChatHistoryWidth(n);
  } catch {
    return CHAT_HISTORY_WIDTH_DEFAULT;
  }
}

function writeChatHistoryWidthToStorage(v: number): void {
  try {
    localStorage.setItem(CHAT_HISTORY_WIDTH_KEY, String(v));
  } catch {
    // localStorage unavailable — silently ignore
  }
}

function clampChatHistoryHeight(v: number): number {
  if (!Number.isFinite(v)) return CHAT_HISTORY_HEIGHT_DEFAULT;
  if (v < CHAT_HISTORY_HEIGHT_MIN) return CHAT_HISTORY_HEIGHT_MIN;
  if (v > CHAT_HISTORY_HEIGHT_MAX) return CHAT_HISTORY_HEIGHT_MAX;
  return Math.round(v);
}

function readChatHistoryHeightFromStorage(): number {
  try {
    const raw = localStorage.getItem(CHAT_HISTORY_HEIGHT_KEY);
    if (raw === null) return CHAT_HISTORY_HEIGHT_DEFAULT;
    const n = Number(raw);
    return clampChatHistoryHeight(n);
  } catch {
    return CHAT_HISTORY_HEIGHT_DEFAULT;
  }
}

function writeChatHistoryHeightToStorage(v: number): void {
  try {
    localStorage.setItem(CHAT_HISTORY_HEIGHT_KEY, String(v));
  } catch {
    // localStorage unavailable — silently ignore
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

// 2026-06-02 · UI redesign step 1: 全局场景背景层(壁纸,跨角色共享)。
// 跟 character.background_path 的关系:character bg 是 per-character、挂在
// CharacterView 内 z-0;globalScene 是 app 级、挂在 Panel 容器 z-0,更底层。
// character bg 设了就盖住该区域的 globalScene;没设就透出来。
// 主题(8 套色)只换 --color-* token,不动 globalScene,所以换皮跟换壁纸独立。
export type GlobalSceneType = 'image' | 'video';
export interface GlobalScene {
  type: GlobalSceneType;
  path: string; // 本地路径 / URL / asset path,前端按后缀分发到 <img> / <video>
}
const GLOBAL_SCENE_KEY = 'momoos.globalScene';

function _readGlobalSceneFromStorage(): GlobalScene | null {
  try {
    const raw = localStorage.getItem(GLOBAL_SCENE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<GlobalScene>;
    if (parsed && (parsed.type === 'image' || parsed.type === 'video')
        && typeof parsed.path === 'string' && parsed.path.trim() !== '') {
      return { type: parsed.type, path: parsed.path };
    }
    return null;
  } catch {
    return null;
  }
}

function _writeGlobalSceneToStorage(v: GlobalScene | null): void {
  try {
    if (v === null) localStorage.removeItem(GLOBAL_SCENE_KEY);
    else localStorage.setItem(GLOBAL_SCENE_KEY, JSON.stringify(v));
  } catch {
    // localStorage unavailable — silently ignore
  }
}

// 2026-06-02 · UI redesign step 2: 浮层路由(磨砂浮层取代整页 settings/capabilities)。
// session-only · 不持久化(打开浮层 = UI 临时态,关 app 后默认回主聊天)。
export type ActiveOverlay = 'capabilities' | 'settings' | null;

interface AppState {
  // 窗口模式
  mode: AppMode;
  setMode: (mode: AppMode) => void;

  // v3-A — UI 主题（8 套，见 styles/themes.css）
  theme: ThemeKey;
  setTheme: (theme: ThemeKey) => void;

  // 2026-06-02 · 全局场景背景层(壁纸,跨角色共享 · localStorage 持久化)
  globalScene: GlobalScene | null;
  setGlobalScene: (scene: GlobalScene | null) => void;

  // 2026-06-02 · 浮层路由 · session-only,不持久化
  activeOverlay: ActiveOverlay;
  setActiveOverlay: (overlay: ActiveOverlay) => void;

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
  //
  // bugfix-2.2：老 'settings'/SettingsPanel 完全弃用,sidebar 也不再有入口。
  // 4 个 view: chat / characters / capabilities / settings_v2(新 ⚙ 设置)。
  panelView: 'chat' | 'characters' | 'capabilities' | 'settings_v2';
  setPanelView: (v: 'chat' | 'characters' | 'capabilities' | 'settings_v2') => void;

  // ConversationList 折叠状态（持久化到 localStorage）
  conversationListCollapsed: boolean;
  setConversationListCollapsed: (v: boolean) => void;

  // 方案 1：右侧 ChatHistoryPanel 折叠状态（与左侧 conv list 推拉对称,
  // 持久化到 localStorage,M1 Air 小屏首次启动默认收起）
  chatPanelCollapsed: boolean;
  setChatPanelCollapsed: (v: boolean) => void;

  // 2026-05-19 — ConversationList 可拖拽宽度(px)。collapsed=false 时生效,
  // collapsed=true 时整体 width=0(收起)。clamp [160, 400] 防过窄/过宽吞立绘。
  conversationListWidth: number;
  setConversationListWidth: (v: number) => void;

  // 2026-05-19 — ChatHistoryPanel 可拖拽宽度(px)。chatPanelCollapsed=false 时生效。
  // clamp [320, 600]:聊天可读下限 + 给立绘区留足最小宽度上限。
  // 2026-06-04 · Round 4 ③ 起,ChatHistoryPanel 改成"右上锚 + 左下角拖拽手柄
  // 同时改宽高",这个字段重新生效(Round 3.5 期间曾被硬编码 width:400 覆盖)。
  chatHistoryWidth: number;
  setChatHistoryWidth: (v: number) => void;

  // 2026-06-04 · Round 4 ③ — ChatHistoryPanel 可拖拽高度(px)。原 Round 3.5
  // bottom:100 固定贴边改为固定 height 用户可调。clamp [240, 1200]。
  chatHistoryHeight: number;
  setChatHistoryHeight: (v: number) => void;

  // 诊断用：用户最近一次发送 user message 的 performance.now() 时间戳
  // 仅前端 in-memory，所有前端 WS 接收 timer 都相对它计算 elapsed
  lastSendTimestamp: number;
  setLastSendTimestamp: (t: number) => void;

  // VAD 状态
  vadState: VadState;
  setVadState: (s: VadState) => void;

  // INV-17 v3 (2026-05-28): silero web 接管 VAD · vadCurrentMax (max amplitude)
  // 语义已废 · 改为 vadConfidence (silero isSpeech probability 0-1) · 给
  // VadBar 实时显示 confidence + hysteresis markers。silero onFrameProcessed
  // 每 ~32ms 写一次 · pause/sleep 时清零。
  vadConfidence: number;
  setVadConfidence: (n: number) => void;
  // silero 是否 init 成功 · 失败时 fallback 到 manual mode + 给 UI hint。
  vadReady: boolean;
  setVadReady: (v: boolean) => void;

  // 麦克风全局静音（Momo 说话时）
  micMuted: boolean;
  setMicMuted: (v: boolean) => void;

  // 通知 / 闹钟队列（最近 5 条，UI 用）
  notifications: AppNotification[];
  pushNotification: (n: { type: 'notify' | 'alarm'; content: string; todoId?: number }) => void;

  // v3.5 chunk 8a — 后端权限自检失败 push 的 hint，前端 ActivityPermissionModal 弹窗。
  // null = 不需要弹；string = 弹出 + 显示 hint。用户点 [打开系统设置] 跳转后由
  // setActivityPermissionHint(null) 关掉。
  activityPermissionHint: string | null;
  setActivityPermissionHint: (v: string | null) => void;

  // INV-17 v3 (2026-05-28): silero web 接管 · vadThreshold/silenceTimeoutMs 语义
  // 改为 silero MicVAD 参数(positiveSpeechThreshold / redemptionMs)。
  // negativeSpeechThreshold / minSpeechMs / preSpeechPadMs 用 silero default ·
  // 不暴露 UI(per decision #5)。
  vadPositiveThreshold: number; // 默认 0.3 · silero 进 speech 阈值 · range 0.1-0.9
  setVadPositiveThreshold: (v: number) => void;
  vadRedemptionMs: number;      // 默认 1400 · silero 离开 speech 等待 ms · range 500-3000
  setVadRedemptionMs: (v: number) => void;
  vadIdleTimeoutMs: number;     // 默认 60000 · VAD active 状态 60s 无录音回 sleep
  muteWhileSpeaking: boolean;   // 默认 true · Momo 说话时静音麦克风
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

  // UX-004: 当前 LLM 正在调用的 tool 名(``calendar.today_events`` 等)
  // null = 没有 tool 在跑(LLM 在普通文本流模式)
  // 由 WS 'tool_use_start' 写入,'tool_use_done' 清空。前端按 tool name
  // 前缀做 label mapping(``calendar.* → 查日历``);多 tool 并行只显示
  // 最近 set 的(用户主要关注当下卡顿点)。
  currentToolName: string | null;
  setCurrentToolName: (v: string | null) => void;

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

  // v4-fan chunk 4 — Character Gallery 全屏入口。true → CharacterGallery
  // overlay 接管视觉(fan browse + detail modal),false → 正常主 UI。
  // ESC / 关闭按钮 / CTA 切换都会复位 false。Widget 模式不开放入口
  // (TopBar 不渲染),只 Panel 模式可达。
  galleryOpen: boolean;
  setGalleryOpen: (v: boolean) => void;

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

  // 2026-06-02 · UI redesign step 1
  globalScene: _readGlobalSceneFromStorage(),
  setGlobalScene: (scene) => {
    _writeGlobalSceneToStorage(scene);
    set({ globalScene: scene });
  },
  activeOverlay: null,
  setActiveOverlay: (overlay) => set({ activeOverlay: overlay }),

  status: 'idle',
  setStatus: (status) => set({ status }),

  recording: false,
  setRecording: (recording) => set({ recording }),
  // 2026-06-05 · 单源 LS:store init 直读 · setter 直写。取代原 AsrVadSection
  // useEffect[] 懒 hydrate 模式(只有用户打开能力浮层才同步,导致 store ≠ LS
  // 长期 desync · 切角色 / 重启都不读)。
  recordingMode: readRecordingModeFromStorage(),
  setRecordingMode: (recordingMode) => {
    writeRecordingModeToStorage(recordingMode);
    set({ recordingMode });
  },

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

  chatPanelCollapsed: readChatPanelCollapsedFromStorage(),
  setChatPanelCollapsed: (chatPanelCollapsed) => {
    writeChatPanelCollapsedToStorage(chatPanelCollapsed);
    set({ chatPanelCollapsed });
  },

  conversationListWidth: readConvListWidthFromStorage(),
  setConversationListWidth: (v) => {
    const clamped = clampConvListWidth(v);
    writeConvListWidthToStorage(clamped);
    set({ conversationListWidth: clamped });
  },

  chatHistoryWidth: readChatHistoryWidthFromStorage(),
  setChatHistoryWidth: (v) => {
    const clamped = clampChatHistoryWidth(v);
    writeChatHistoryWidthToStorage(clamped);
    set({ chatHistoryWidth: clamped });
  },

  chatHistoryHeight: readChatHistoryHeightFromStorage(),
  setChatHistoryHeight: (v) => {
    const clamped = clampChatHistoryHeight(v);
    writeChatHistoryHeightToStorage(clamped);
    set({ chatHistoryHeight: clamped });
  },

  lastSendTimestamp: 0,
  setLastSendTimestamp: (lastSendTimestamp) => set({ lastSendTimestamp }),

  vadState: 'sleep',
  setVadState: (vadState) => set({ vadState }),

  // INV-17 v3 — silero VAD diagnostic + ready flag
  vadConfidence: 0,
  setVadConfidence: (vadConfidence) => set({ vadConfidence }),
  vadReady: false,
  setVadReady: (vadReady) => set({ vadReady }),

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

  activityPermissionHint: null,
  setActivityPermissionHint: (activityPermissionHint) => set({ activityPermissionHint }),

  // INV-17 v3 · silero MicVAD 参数 default(只暴露这 2 个 · 其他用 silero default)
  // INV-17 v3.4 (2026-05-28): 0.3 → 0.6 · 真机实测安静环境麦克底噪 confidence
  // 0.3-0.5 误触发录音 · 0.6 解决。silero 库 default 0.3 同款问题。AsrVadSection
  // hydrate localStorage missing/错值时保持 store default · 故只改这里即可。
  // 2026-06-05 · 同款 LS 直读直写 · 取代 AsrVadSection 懒 hydrate。
  vadPositiveThreshold: readVadPositiveFromStorage(),
  setVadPositiveThreshold: (vadPositiveThreshold) => {
    writeVadPositiveToStorage(vadPositiveThreshold);
    set({ vadPositiveThreshold });
  },
  vadRedemptionMs: readVadRedemptionMsFromStorage(),
  setVadRedemptionMs: (vadRedemptionMs) => {
    writeVadRedemptionMsToStorage(vadRedemptionMs);
    set({ vadRedemptionMs });
  },
  vadIdleTimeoutMs: 60000,
  muteWhileSpeaking: readMuteSpeakingFromStorage(),
  setMuteWhileSpeaking: (muteWhileSpeaking) => {
    writeMuteSpeakingToStorage(muteWhileSpeaking);
    set({ muteWhileSpeaking });
  },

  ttsEnabled: true,
  setTtsEnabled: (ttsEnabled) => set({ ttsEnabled }),

  currentThinking: null,
  setCurrentThinking: (currentThinking) => set({ currentThinking }),
  clearCurrentThinking: () => set({ currentThinking: null }),

  currentToolName: null,
  setCurrentToolName: (currentToolName) => set({ currentToolName }),

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

  galleryOpen: false,
  setGalleryOpen: (galleryOpen) => set({ galleryOpen }),

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
