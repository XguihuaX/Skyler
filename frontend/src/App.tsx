import { useMemo, useEffect, useState } from 'react';
import { useAppStore } from './store';
import { useWebSocket } from './hooks/useWebSocket';
import { useAudio } from './hooks/useAudio';
import Widget from './modes/Widget';
import Panel from './modes/Panel';
import NotificationToast from './components/NotificationToast';
import { AppApiContext, AppApi } from './contexts/appApi';
import { applyModeWindowProps, fetchConfig } from './lib/window';
import {
  fetchCharacters,
  fetchConversations,
  fetchHealth,
  fetchMessages,
} from './lib/config';

// 方便子组件统一从 App 导入
export { useAppApi } from './contexts/appApi';

function App() {
  const mode = useAppStore((s) => s.mode);
  const [warming, setWarming] = useState(true);

  // V2.5-D — sync the Tauri window size to the persisted mode on first paint.
  // The store's `mode` is hydrated from localStorage at module init, but
  // tauri.conf.json always boots at the widget-size 350x500. Without this the
  // restored mode would render Panel UI inside a tiny widget-sized window.
  // v3-A — 同时把持久化的主题写到 <html data-theme>，否则首屏会闪默认 dusk。
  useEffect(() => {
    void applyModeWindowProps(useAppStore.getState().mode);
    useAppStore.getState().setTheme(useAppStore.getState().theme);
    // run once at mount; subsequent mode flips already call applyModeWindowProps
    // at their click sites (Widget.tsx / TopBar.tsx).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const cfg = await fetchConfig();
        if (cancelled) return;
        useAppStore.getState().syncFromConfig(cfg);
        console.log('[App] fetchConfig ok:', cfg);

        // V2.5-C — eager-load characters / conversations / messages
        const userId = useAppStore.getState().defaultUserId;

        try {
          const chars = await fetchCharacters();
          if (cancelled) return;
          useAppStore.getState().setCharacters(chars);
          if (chars.length > 0) {
            useAppStore.getState().setCurrentCharacterId(chars[0].id);
          }
        } catch (e) {
          console.error('[App] fetchCharacters failed:', e);
        }

        const charId = useAppStore.getState().currentCharacterId;
        try {
          const convs = await fetchConversations(
            userId,
            charId ?? undefined,
          );
          if (cancelled) return;
          useAppStore.getState().setConversations(convs);
          if (convs.length > 0) {
            const firstId = convs[0].id;
            useAppStore.getState().setCurrentConversationId(firstId);
            try {
              const msgs = await fetchMessages(firstId);
              if (cancelled) return;
              useAppStore.getState().setChatMessages(
                msgs.map((r) => ({
                  id: `s-${r.id}`,
                  role: r.role,
                  content: r.content,
                  streaming: false,
                  ts: 0,
                })),
              );
            } catch (e) {
              console.error('[App] fetchMessages failed:', e);
            }
          }
        } catch (e) {
          console.error('[App] fetchConversations failed:', e);
        }
      } catch (e) {
        console.error('[App] fetchConfig failed:', e);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      // Poll /api/health every 500ms, capped at 60s (120 attempts).
      for (let i = 0; i < 120; i++) {
        if (cancelled) return;
        try {
          const h = await fetchHealth();
          if (h.status === 'ready') {
            if (!cancelled) setWarming(false);
            return;
          }
        } catch {
          // backend not up yet — keep polling
        }
        await new Promise((r) => setTimeout(r, 500));
      }
      // Timeout — drop the overlay so the user can at least try to use it.
      if (!cancelled) {
        console.warn('[App] /api/health did not return ready within 60s');
        setWarming(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const { sendText, sendVoice } = useWebSocket();
  const { startManual, stopManualAndSend, toggleVad } = useAudio({ sendVoice });

  const api: AppApi = useMemo(
    () => ({ sendText, sendVoice, startManual, stopManualAndSend, toggleVad }),
    [sendText, sendVoice, startManual, stopManualAndSend, toggleVad],
  );

  return (
    <AppApiContext.Provider value={api}>
      <div className="w-screen h-screen bg-transparent overflow-hidden relative">
        {/* Widget-only top drag strip. Panel mode has its own TopBar (with
            data-tauri-drag-region) flush to the window top, so a global strip
            there would cover the close/minimize buttons. */}
        {mode === 'widget' && (
          <div
            data-tauri-drag-region
            className="fixed top-0 left-0 right-0 h-6 z-[9999]"
            style={{ pointerEvents: 'auto', backgroundColor: 'transparent' }}
          />
        )}
        {mode === 'widget' && <Widget />}
        {mode === 'panel' && <Panel />}
        <NotificationToast />
        {warming && (
          <div
            className="fixed inset-0 z-[9999] backdrop-blur-sm flex items-center justify-center"
            style={{ background: 'color-mix(in srgb, var(--color-bg-base) 80%, transparent)' }}
          >
            <div
              className="flex flex-col items-center gap-3"
              style={{ color: 'var(--color-text-primary)' }}
            >
              <div
                className="w-10 h-10 border-4 rounded-full animate-spin"
                style={{
                  borderColor: 'var(--color-border)',
                  borderTopColor: 'var(--color-accent)',
                }}
              />
              <div className="text-sm">正在启动模型...</div>
            </div>
          </div>
        )}
      </div>
    </AppApiContext.Provider>
  );
}

export default App;
