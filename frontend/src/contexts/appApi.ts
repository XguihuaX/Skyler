import { createContext, useContext } from 'react';

export interface AppApi {
  sendText: (content: string) => void;
  sendVoice: (audioBase64: string) => void;
  // v3-F #4：用户说话 / 点击 🚫 触发，停 LLM stream + TTS playback
  sendInterrupt: () => void;
  // v3-E1 step3：点 Live2D canvas 触发主动对话
  sendTouch: () => void;
  // Rule B(绑定语义)— 切角色时通知 backend 当前 UI char/conv。
  // backend ``ConnectionManager.set_current`` 收到后做为 proactive 投递 gate
  // 的 source of truth。不触发 LLM,仅同步状态 + 等一条 ``character_switch_ack``。
  sendCharacterSwitch: (
    characterId: number, conversationId: number | null,
  ) => void;
  // 2026-06-15 ⑤ · MCP tool 调用前确认 modal 回应
  sendMcpToolConfirmResponse: (requestId: string, accept: boolean) => void;
  startManual: () => Promise<void>;
  stopManualAndSend: () => Promise<void>;
  toggleVad: () => Promise<void>;
}

export const AppApiContext = createContext<AppApi | null>(null);

export function useAppApi(): AppApi {
  const ctx = useContext(AppApiContext);
  if (!ctx) throw new Error('useAppApi must be used within AppApiProvider');
  return ctx;
}
