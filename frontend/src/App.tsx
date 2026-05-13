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
import FanLayout from './components/character/FanLayout';
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

// v4-fan chunk 3: ?fan=1 dev demo entry。在 module scope 一次性算,
// 避免任何 hook 顺序问题。FanLayout overlay 渲染在 MainApp 内部,
// MainApp 的 fetchCharacters / WS 等 hooks 仍正常执行,只是把主视
// 图 (Widget / Panel) 替换为全屏 fan demo。Fan-6 ship 后由真入口
// (TopBar 按钮 / Sidebar entry)取代,这个 dev 短路可一并删。
//
// 用 location 而非 hook,因为路由判定一次锁定生命周期(URL 变化要
// 整个 App reload 才生效,符合 dev 切换 UX)。
//
// v4-fan chunk 3.1:支持 query 调参,用户不改源码就能 sweep。
//   ?fan=1&vc=5         visibleCount = 5
//   ?fan=1&r=750        radius = 750
//   ?fan=1&arc=140      arcDegree = 140
//   ?fan=1&dur=300      transitionDuration = 300
//   ?fan=1&cy=900       centerOffsetY = 900 (绕 viewportH+100 默认)
//   ?fan=1&debug=1      启用 FanLayout 内部 debug overlay
const _FAN_QUERY = (() => {
  if (typeof window === 'undefined') return null;
  const sp = new URLSearchParams(window.location.search);
  if (sp.get('fan') !== '1') return null;
  const numOrUndef = (key: string): number | undefined => {
    const v = sp.get(key);
    if (v == null) return undefined;
    const n = Number(v);
    return Number.isFinite(n) ? n : undefined;
  };
  return {
    enabled:            true,
    debug:              sp.get('debug') === '1',
    visibleCount:       numOrUndef('vc'),
    radius:             numOrUndef('r'),
    arcDegree:          numOrUndef('arc'),
    transitionDuration: numOrUndef('dur'),
    centerOffsetY:      numOrUndef('cy'),
  };
})();
const _FAN_DEMO: boolean = _FAN_QUERY?.enabled ?? false;

function App() {
  return <MainApp />;
}

function MainApp() {
  const mode = useAppStore((s) => s.mode);
  // v4-fan chunk 3: ?fan=1 demo 用 store characters / currentCharacterId,
  // setCurrentCharacterId(id) 走现有 reactive 链(Live2DCanvas / WS 都
  // 自动跟随,无 backend 调用)。仅在 _FAN_DEMO 时实际渲染,但 hooks
  // 必须无条件订阅(rules-of-hooks)。开销:3 个 selector,可忽略。
  const characters         = useAppStore((s) => s.characters);
  const currentCharacterId = useAppStore((s) => s.currentCharacterId);
  const setCurrentCharacterId = useAppStore((s) => s.setCurrentCharacterId);

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

  const { sendText, sendVoice, sendInterrupt, sendTouch } = useWebSocket();
  const { startManual, stopManualAndSend, toggleVad } = useAudio({
    sendVoice, sendInterrupt,
  });

  const api: AppApi = useMemo(
    () => ({
      sendText, sendVoice, sendInterrupt, sendTouch,
      startManual, stopManualAndSend, toggleVad,
    }),
    [sendText, sendVoice, sendInterrupt, sendTouch, startManual, stopManualAndSend, toggleVad],
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
      {/* v4-fan chunk 3 dev demo:?fan=1 → 全屏 FanLayout overlay 接管视觉,
          压在 Widget/Panel 之上但低于 SplashOverlay(z 999 vs 10000)。
          Hooks (WS / audio / fetchCharacters) 仍然走;只是把主视图遮住。
          Fan-6 把 FanLayout 接到真入口(TopBar 按钮)后,这段 _FAN_DEMO
          连同 module 顶部的路由判定一起删。 */}
      {_FAN_DEMO && characters.length > 0 && (
        <div
          className="fixed inset-0 z-[999]"
          style={{
            background:
              'radial-gradient(circle at 50% 60%, '
              + 'var(--color-bg-elevated) 0%, '
              + 'var(--color-bg-surface) 50%, '
              + 'var(--color-bg-base) 100%)',
          }}
        >
          <FanLayout
            characters={characters}
            selectedCharId={currentCharacterId}
            onSelectCharacter={setCurrentCharacterId}
            debug={_FAN_QUERY?.debug ?? false}
            // 只透传非 undefined 的 override,defaults 由 FanLayout 兜底
            layoutParams={{
              ...(_FAN_QUERY?.visibleCount       != null && { visibleCount:       _FAN_QUERY.visibleCount }),
              ...(_FAN_QUERY?.radius             != null && { radius:             _FAN_QUERY.radius }),
              ...(_FAN_QUERY?.arcDegree          != null && { arcDegree:          _FAN_QUERY.arcDegree }),
              ...(_FAN_QUERY?.transitionDuration != null && { transitionDuration: _FAN_QUERY.transitionDuration }),
              ...(_FAN_QUERY?.centerOffsetY      != null && { centerOffsetY:      _FAN_QUERY.centerOffsetY }),
            }}
          />
          <div
            className="fixed top-3 left-3 font-mono text-xs rounded-md px-3 py-2 pointer-events-none"
            style={{
              color: 'var(--color-text-primary)',
              background: 'rgba(0, 0, 0, 0.55)',
              border: '1px solid var(--color-border-subtle)',
              maxWidth: 360,
              lineHeight: 1.5,
            }}
          >
            Fan-3.1 demo · ?fan=1<br />
            <span style={{ opacity: 0.75 }}>
              N={characters.length} · selected:{characters.find((c) => c.id === currentCharacterId)?.name ?? '—'}<br />
              query: vc={_FAN_QUERY?.visibleCount ?? 7} r={_FAN_QUERY?.radius ?? 600} arc={_FAN_QUERY?.arcDegree ?? 120} dur={_FAN_QUERY?.transitionDuration ?? 500}<br />
              点非中心卡 → 最短路径转到 top
            </span>
          </div>
        </div>
      )}
      {_FAN_DEMO && characters.length === 0 && (
        <div
          className="fixed inset-0 z-[999] flex items-center justify-center font-mono text-sm"
          style={{
            color: 'var(--color-text-primary)',
            background: 'var(--color-bg-base)',
          }}
        >
          loading characters… (确保 backend 在跑 + /api/characters/list 可达)
        </div>
      )}
      {/* v3.5 chunk 5b：splash overlay。z-index 高于一切（10000），自己管
          自己的存在感（disabled / 404 → mount 同 tick 立即 onFinished）。 */}
      {!splashDone && <SplashOverlay onFinished={() => setSplashDone(true)} />}
    </AppApiContext.Provider>
  );
}

export default App;
