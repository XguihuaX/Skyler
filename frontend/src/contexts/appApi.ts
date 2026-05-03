import { createContext, useContext } from 'react';

export interface AppApi {
  sendText: (content: string) => void;
  sendVoice: (audioBase64: string) => void;
  // v3-F #4：用户说话 / 点击 🚫 触发，停 LLM stream + TTS playback
  sendInterrupt: () => void;
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
