import { useMemo, useEffect, useState } from 'react';
import { useAppStore } from './store';
import { useWebSocket } from './hooks/useWebSocket';
import { useAudio } from './hooks/useAudio';
import Widget from './modes/Widget';
import Panel from './modes/Panel';
import NotificationToast from './components/NotificationToast';
import CharacterStatePanel from './components/CharacterStatePanel';
import ActivityPermissionModal from './components/ActivityPermissionModal';
import SplashOverlay from './components/SplashOverlay';
import CharacterGallery from './components/character/CharacterGallery';
import { AppApiContext, AppApi } from './contexts/appApi';
import { applyModeWindowProps, fetchConfig } from './lib/window';
import {
  fetchCharacters,
  fetchConversations,
  fetchHealth,
  fetchMessages,
} from './lib/config';
import { fetchLive2DModels } from './lib/live2d';
import { fetchTtsVoices } from './lib/tts';

// 方便子组件统一从 App 导入
export { useAppApi } from './contexts/appApi';

// v4-fan chunk 4 retire ``?fan=1`` dev path:Gallery 走真入口(TopBar
// GalleryThumbnails 按钮 → store.galleryOpen),不再需要 URL query 短路。
// FanLayout 仍可被独立 import 用于其他地方;现在只 CharacterGallery 用。

function App() {
  return <MainApp />;
}

function MainApp() {
  const mode = useAppStore((s) => s.mode);
  // Gallery overlay 状态:由 store 持,TopBar 按钮 / CharacterGallery
  // 自身的 close / CTA 三处翻动。
  const galleryOpen = useAppStore((s) => s.galleryOpen);

  const [warming, setWarming] = useState(true);
  // v3.5 chunk 5b：splash 完成前主视图 opacity=0；splash silent-skip 时
  // SplashOverlay 内部立即 onFinished()，所以这里默认 false（"未完成"）但
  // 几乎不会被用户察觉。
  const [splashDone, setSplashDone] = useState(false);

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

        // v3-E2 patch：eager-load live2d 扫描结果。Widget 模式下用户可能
        // 永远不打开 CharacterPanel，但 CharacterView 解析角色 live2d_model
        // 依赖这个 store 字段；不在这里 fetch，widget-only 用户切换角色后
        // 会因 store 空 → resolveLive2dModelUrl 走 hardcode 兜底 → 命中
        // 不到的 slug 直接 fallback 静态图。
        try {
          const live2d = await fetchLive2DModels();
          if (cancelled) return;
          useAppStore.getState().setLive2dModels(live2d.models);
        } catch (e) {
          console.error('[App] fetchLive2DModels failed:', e);
        }

        // v3-G' chunk 1b：eager-load TTS providers + voices，CharacterPanel
        // 下拉数据源。失败不阻塞 —— 没数据时下拉 fallback 到"未配置"，用户
        // 仍能编辑现有 character（v3-G' 之前的旧 plain JSON 文本框模式）。
        try {
          const tts = await fetchTtsVoices();
          if (cancelled) return;
          useAppStore.getState().setTtsProviders(tts.providers);
        } catch (e) {
          console.error('[App] fetchTtsVoices failed:', e);
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
                  kind: r.kind ?? 'normal',
                  proactiveTrigger: r.proactive_trigger ?? undefined,
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

  const {
    sendText, sendVoice, sendInterrupt, sendTouch, sendCharacterSwitch,
  } = useWebSocket();
  const { startManual, stopManualAndSend, toggleVad } = useAudio({
    sendVoice, sendInterrupt,
  });

  const api: AppApi = useMemo(
    () => ({
      sendText, sendVoice, sendInterrupt, sendTouch, sendCharacterSwitch,
      startManual, stopManualAndSend, toggleVad,
    }),
    [
      sendText, sendVoice, sendInterrupt, sendTouch, sendCharacterSwitch,
      startManual, stopManualAndSend, toggleVad,
    ],
  );

  return (
    <AppApiContext.Provider value={api}>
      <div
        className="w-screen h-screen bg-transparent overflow-hidden relative"
        style={{
          // v3.5 chunk 5b：splash 期间主视图 fade-out；splash 跳过后 300ms 内
          // fade-in。silent-skip 时几乎无感（splashDone 在 mount 同 tick 翻 true）。
          opacity: splashDone ? 1 : 0,
          transition: 'opacity 300ms ease-out',
        }}
      >
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
        {/* v3-G chunk 3b: 角色状态浮动小条；位置随 mode 切换。控制开关
            在 SettingsPanel [角色] section（store.showCharacterStatePanel）。

            UX-003 hotfix: 仅 widget 模式在这里渲染 —— widget 整个视口 ≈
            CharacterView，``right: 8px / bottom: 8px`` 锚到 App 外层 ``relative``
            container 的视口角 → 视觉上就在 CharacterView 角。
            Panel 模式由 ``Panel.tsx`` 内部 chat-view container 渲染,锚到
            CharacterView 实际容器边界(避免 App 外层 relative 让 ``left: 16px``
            落在 Sidebar 区域而非 CharacterView 区域)。 */}
        {mode === 'widget' && <CharacterStatePanel position="widget" />}
        <ActivityPermissionModal />
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
      {/* v4-fan chunk 4: Character Gallery overlay。store.galleryOpen 由
          TopBar GalleryThumbnails 按钮翻动;Gallery 自身管 close/Esc/CTA
          复位。z=990 压在主 UI 上方,SplashOverlay (z 10000) 之下。 */}
      {galleryOpen && <CharacterGallery />}
      {/* v3.5 chunk 5b：splash overlay。z-index 高于一切（10000），自己管
          自己的存在感（disabled / 404 → mount 同 tick 立即 onFinished）。 */}
      {!splashDone && <SplashOverlay onFinished={() => setSplashDone(true)} />}
    </AppApiContext.Provider>
  );
}

export default App;
