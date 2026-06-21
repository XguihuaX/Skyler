import { useMemo, useEffect, useState } from 'react';
import { useAppStore, applyGlassCustom } from './store';
import { useWebSocket } from './hooks/useWebSocket';
import { useAudio } from './hooks/useAudio';
import Widget from './modes/Widget';
import Panel from './modes/Panel';
import NotificationToast from './components/NotificationToast';
import CharacterStatePanel from './components/CharacterStatePanel';
import ActivityPermissionModal from './components/ActivityPermissionModal';
import MCPConfirmModal from './components/MCPConfirmModal';
import LoadingScreen from './components/loading/LoadingScreen';
import CharacterGallery from './components/character/CharacterGallery';
import { AppApiContext, AppApi } from './contexts/appApi';
import { applyModeWindowProps, fetchConfig } from './lib/window';
import {
  fetchCharacters,
  fetchConversations,
  fetchHealth,
  fetchMessages,
  fetchUserProfile,
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

  // 进入动画 LoadingScreen 挂载 · cut4 修法:
  //   - 每次启动都挂(不依赖 warming / 后端是否在暖)
  //   - engine 跑 max(7s 地板, appReady) · done 时回调 setLoadingDone(true) → unmount
  //   - appReady 4 路(embedding/whisper/ws/live2d)只喂闸 · 不决定挂不挂
  //   - 旧 splash 视频(SplashOverlay + /splash/intro.mp4)已删 · LoadingScreen 顶位
  const [loadingDone, setLoadingDone] = useState(false);

  // V2.5-D — sync the Tauri window size to the persisted mode on first paint.
  // The store's `mode` is hydrated from localStorage at module init, but
  // tauri.conf.json always boots at the widget-size 350x500. Without this the
  // restored mode would render Panel UI inside a tiny widget-sized window.
  // v3-A — 同时把持久化的主题写到 <html data-theme>，否则首屏会闪默认 dusk。
  useEffect(() => {
    void applyModeWindowProps(useAppStore.getState().mode);
    useAppStore.getState().setTheme(useAppStore.getState().theme);
    // 2026-06-20 · 玻璃外观自定义 init · setTheme 已会 re-apply 一次,这里
    // 保险再调一次(空指针 / first paint race 也能稳定挂上)。
    applyGlassCustom(useAppStore.getState().glassCustom);
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
            // V4 持久化:优先用 users.current_character_id(上次选的角色)·
            // 拉 user profile · 校验 id 在 chars 里存在(防指向已删角色)·
            // 任一步失败/没值 → fallback chars[0](保持老行为)。
            let pickedId: number = chars[0].id;
            try {
              const profile = await fetchUserProfile(userId);
              if (cancelled) return;
              const persisted = profile.current_character_id;
              if (
                persisted !== null && persisted !== undefined &&
                chars.some((c) => c.id === persisted)
              ) {
                pickedId = persisted;
              }
            } catch (e) {
              console.warn('[App] fetchUserProfile failed · fallback chars[0]:', e);
            }
            useAppStore.getState().setCurrentCharacterId(pickedId);
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
      // 第三刀 · health poll 只负责写 per-model ready 进 store,**不再翻
      // warming**(否则后端已 ready 时 LoadingScreen 引擎还没起就被 unmount,
      // 进入动画完全看不到)。warming 由 LoadingScreen engine onDone 翻 ·
      // 60s 安全网 timeout 兜底防 engine 永远 done 不了。
      const setE = useAppStore.getState().setEmbeddingReady;
      const setW = useAppStore.getState().setWhisperReady;
      // 继续 poll · 直到组件 unmount(给 LoadingScreen 实时喂 ready 状态)
      while (!cancelled) {
        try {
          const h = await fetchHealth();
          if (!cancelled) {
            setE(h.models?.embedding === 'ready');
            setW(h.models?.whisper === 'ready');
          }
        } catch {
          // backend not up yet — keep polling
        }
        await new Promise((r) => setTimeout(r, 500));
      }
    })();
    // 60s 安全网:engine 永远没 done(比如 live2d 加载失败 / appReady 某路卡住)
    // 也别永远卡 loading · 强制 unmount 主 UI 露出。
    const safetyTimer = window.setTimeout(() => {
      if (!cancelled) {
        console.warn('[App] LoadingScreen safety net 60s · force unmount');
        setLoadingDone(true);
      }
    }, 60_000);
    return () => {
      cancelled = true;
      window.clearTimeout(safetyTimer);
    };
  }, []);

  const {
    sendText, sendVoice, sendInterrupt, sendTouch, sendCharacterSwitch,
    sendMcpToolConfirmResponse,
  } = useWebSocket();
  const { startManual, stopManualAndSend, toggleVad } = useAudio({
    sendVoice, sendInterrupt,
  });

  const api: AppApi = useMemo(
    () => ({
      sendText, sendVoice, sendInterrupt, sendTouch, sendCharacterSwitch,
      sendMcpToolConfirmResponse,
      startManual, stopManualAndSend, toggleVad,
    }),
    [
      sendText, sendVoice, sendInterrupt, sendTouch, sendCharacterSwitch,
      sendMcpToolConfirmResponse,
      startManual, stopManualAndSend, toggleVad,
    ],
  );

  return (
    <AppApiContext.Provider value={api}>
      <div
        className="w-screen h-screen bg-transparent overflow-hidden relative"
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
        <MCPConfirmModal />
      </div>
      {/* v4-fan chunk 4: Character Gallery overlay。store.galleryOpen 由
          TopBar GalleryThumbnails 按钮翻动;Gallery 自身管 close/Esc/CTA
          复位。z=990 压在主 UI 上方,LoadingScreen (z 9999) 之下。 */}
      {galleryOpen && <CharacterGallery />}
      {/* 进入动画 · 每次启动无条件挂 · engine 跑 max(7s, appReady) · done 后
          自 fade 400ms · onDone() → setLoadingDone(true) → 本块 unmount。
          挂在 AppApiContext 下 + 主 UI div 兄弟,层级 z-9999 全屏盖。 */}
      {!loadingDone && <LoadingScreen onDone={() => setLoadingDone(true)} />}
    </AppApiContext.Provider>
  );
}

export default App;
