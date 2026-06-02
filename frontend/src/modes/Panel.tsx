import { useCallback, useEffect, useRef, useState } from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import {
  useAppStore,
  CONV_LIST_WIDTH_MIN,
  CONV_LIST_WIDTH_MAX,
  CONV_LIST_WIDTH_DEFAULT,
  CHAT_HISTORY_WIDTH_MIN,
  CHAT_HISTORY_WIDTH_MAX,
  CHAT_HISTORY_WIDTH_DEFAULT,
} from '../store';
import CapabilitiesPanel from '../components/capabilities/CapabilitiesPanel';
import CharacterPanel from '../components/CharacterPanel';
import CharacterStatePanel from '../components/CharacterStatePanel';
import CharacterView from '../components/CharacterView';
import ChatHistoryPanel from '../components/ChatHistoryPanel';
import ChatInput from '../components/ChatInput';
import ConversationList from '../components/ConversationList';
import OverlayShell from '../components/OverlayShell';
import SceneBackground from '../components/SceneBackground';
import SettingsPanelV2 from '../components/settings/SettingsPanelV2';
import Sidebar from '../components/Sidebar';
import TopBar from '../components/TopBar';

interface ToastInfo {
  id: number;
  text: string;
}

export default function Panel() {
  const panelView   = useAppStore((s) => s.panelView);
  // 2026-06-02 · UI redesign · 浮层路由(取代原 capabilities/settings_v2 整页 view)
  const activeOverlay    = useAppStore((s) => s.activeOverlay);
  const setActiveOverlay = useAppStore((s) => s.setActiveOverlay);
  const collapsed   = useAppStore((s) => s.conversationListCollapsed);
  const setCollapsed = useAppStore((s) => s.setConversationListCollapsed);
  // 方案 1:右侧 chat panel 推拉,与左侧 conv list 对称。
  const chatPanelCollapsed   = useAppStore((s) => s.chatPanelCollapsed);
  const setChatPanelCollapsed = useAppStore((s) => s.setChatPanelCollapsed);

  // 2026-05-19 — ConversationList 右边缘可拖拽 resize handle。
  // 拖拽改 store.conversationListWidth (clamp 已在 store 内做),立绘区
  // (Panel.tsx 中 ``flex-1 min-w-0`` 容器) 自动响应,Live2D runtime
  // (pixiCubism4.ts:234) ResizeObserver 实时重算 canvas 尺寸,不变形。
  const convListWidth = useAppStore((s) => s.conversationListWidth);
  const setConvListWidth = useAppStore((s) => s.setConversationListWidth);
  const dragStartRef = useRef<{ x: number; w: number } | null>(null);
  const [dragging, setDragging] = useState(false);

  const onResizeStart = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    e.preventDefault();
    dragStartRef.current = { x: e.clientX, w: convListWidth };
    setDragging(true);
    // 锁住 pointer 避免拖快脱离 handle 时停掉
    (e.currentTarget as HTMLElement).setPointerCapture?.(e.pointerId);
  }, [convListWidth]);

  const onResizeMove = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    if (!dragStartRef.current) return;
    const dx = e.clientX - dragStartRef.current.x;
    const next = dragStartRef.current.w + dx;
    setConvListWidth(next); // store 内部 clamp [MIN, MAX]
  }, [setConvListWidth]);

  const onResizeEnd = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    if (!dragStartRef.current) return;
    dragStartRef.current = null;
    setDragging(false);
    try {
      (e.currentTarget as HTMLElement).releasePointerCapture?.(e.pointerId);
    } catch { /* swallow */ }
  }, []);

  // 2026-05-19 — 右侧 ChatHistoryPanel 左边缘 resize handle (镜像左侧)。
  // ⚠️ dx 取反:handle 在右侧栏左边缘,右拖 dx>0 → panel 应**变窄**
  // (而左侧栏右边缘 handle 右拖 dx>0 → 它变宽,方向相反)。
  const chatHistoryWidth = useAppStore((s) => s.chatHistoryWidth);
  const setChatHistoryWidth = useAppStore((s) => s.setChatHistoryWidth);
  const dragChatStartRef = useRef<{ x: number; w: number } | null>(null);
  const [draggingChat, setDraggingChat] = useState(false);

  const onChatResizeStart = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    e.preventDefault();
    dragChatStartRef.current = { x: e.clientX, w: chatHistoryWidth };
    setDraggingChat(true);
    (e.currentTarget as HTMLElement).setPointerCapture?.(e.pointerId);
  }, [chatHistoryWidth]);

  const onChatResizeMove = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    if (!dragChatStartRef.current) return;
    const dx = e.clientX - dragChatStartRef.current.x;
    // 取反:右拖(dx 正)→ panel 变窄;左拖(dx 负)→ panel 变宽。
    const next = dragChatStartRef.current.w - dx;
    setChatHistoryWidth(next); // store 内部 clamp [MIN, MAX]
  }, [setChatHistoryWidth]);

  const onChatResizeEnd = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    if (!dragChatStartRef.current) return;
    dragChatStartRef.current = null;
    setDraggingChat(false);
    try {
      (e.currentTarget as HTMLElement).releasePointerCapture?.(e.pointerId);
    } catch { /* swallow */ }
  }, []);

  // 拖拽时给 body 设 col-resize cursor + 禁用 user-select,防止
  // 拖出 handle 区域时光标变回箭头或选中文本。任一 handle 在拖即生效。
  useEffect(() => {
    if (!dragging && !draggingChat) return;
    const prevCursor = document.body.style.cursor;
    const prevSelect = document.body.style.userSelect;
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
    return () => {
      document.body.style.cursor = prevCursor;
      document.body.style.userSelect = prevSelect;
    };
  }, [dragging, draggingChat]);

  // bugfix-2: 共享 toast 给 CapabilitiesPanel / SettingsPanelV2(老 SettingsPanel
  // 自己内置 toast,不接入)。
  const [toasts, setToasts] = useState<ToastInfo[]>([]);
  const showToast = useCallback((text: string) => {
    const id = Date.now() + Math.random();
    setToasts((prev) => [...prev, { id, text }]);
    setTimeout(() => setToasts((prev) => prev.filter((t) => t.id !== id)), 3000);
  }, []);

  return (
    <div
      className="w-full h-full flex flex-col overflow-hidden relative"
      style={{
        // 2026-06-02 · UI redesign · 容器背景改透明,让 SceneBackground 在 z-0 铺底。
        // 没设场景时 SceneBackground 渲染 null,这里背景透明 → 露出 App.tsx 顶层
        // bg-transparent → 露出窗口本底色(--color-bg-base 由各组件玻璃化半透展现)。
        // 为防"完全没壁纸 + 玻璃组件后面太透看着发白",再加一层兜底 fallback color。
        background: 'var(--color-bg-base)',
        color: 'var(--color-text-primary)',
      }}
    >
      {/* 2026-06-02 · UI redesign · 全局场景背景层(壁纸)· z-0 整窗铺底 ·
          没设场景时不渲染、不挡 Panel 容器的 fallback bg-base。 */}
      <SceneBackground />

      {/* 主 UI 层 · 包整个 TopBar + 主区 · 相对定位让它浮在 SceneBackground 之上 */}
      <div className="relative z-10 flex flex-col flex-1 overflow-hidden">
      <TopBar />

      <div className="flex flex-1 overflow-hidden">
        <Sidebar />

        {panelView === 'chat' ? (
          <>
            <ConversationList />

            {/* 2026-05-19 — ConversationList 右边缘 resize handle。
                仅 collapsed=false 时显示;collapsed=true 时整栏 width=0,handle
                也无意义。4px 宽热区(给鼠标足够命中面积),内部 1px 高亮线;
                hover/dragging 时加粗加亮。pointer events 走 onResize* 三件套
                (capture + move + release)。 */}
            {!collapsed && (
              <div
                role="separator"
                aria-orientation="vertical"
                aria-label="拖拽调整对话列表宽度"
                aria-valuenow={convListWidth}
                aria-valuemin={CONV_LIST_WIDTH_MIN}
                aria-valuemax={CONV_LIST_WIDTH_MAX}
                onPointerDown={onResizeStart}
                onPointerMove={onResizeMove}
                onPointerUp={onResizeEnd}
                onPointerCancel={onResizeEnd}
                onDoubleClick={() => setConvListWidth(CONV_LIST_WIDTH_DEFAULT)}
                className="shrink-0 h-full relative group"
                style={{
                  width: 4,
                  cursor: 'col-resize',
                  touchAction: 'none',
                }}
                title="拖拽调整宽度 · 双击重置"
              >
                <div
                  className="absolute top-0 bottom-0 left-1/2 -translate-x-1/2 transition-colors"
                  style={{
                    width: dragging ? 2 : 1,
                    background: dragging
                      ? 'var(--color-accent)'
                      : 'var(--color-border-subtle)',
                  }}
                />
                <div
                  className="absolute top-0 bottom-0 left-1/2 -translate-x-1/2 opacity-0 group-hover:opacity-100 transition-opacity"
                  style={{
                    width: 2,
                    background: 'var(--color-accent)',
                  }}
                />
              </div>
            )}

            {/* Vertical collapse toggle — always visible in chat view */}
            <button
              type="button"
              className="group w-6 shrink-0 h-full flex items-center justify-center transition-colors"
              style={{
                background: 'color-mix(in srgb, var(--color-bg-surface) 60%, transparent)',
                borderRight: '1px solid var(--color-border-subtle)',
                color: 'var(--color-text-secondary)',
              }}
              onClick={() => setCollapsed(!collapsed)}
              title={collapsed ? '展开对话列表' : '折叠对话列表'}
              aria-label={collapsed ? '展开对话列表' : '折叠对话列表'}
            >
              {collapsed ? <ChevronRight size={14} /> : <ChevronLeft size={14} />}
            </button>

            {/* Chat main area — galgame-style: full-bleed character + floating overlays。
                方案 1:中央立绘区 flex-1 自适应剩余,两侧 ConversationList +
                ChatHistoryPanel 各自推拉,任意组合下立绘竖图等比缩放不变形。
                两侧都收起 = 纯 Galgame 沉浸。删除右上角"历史"按钮 +
                ChatHistoryDrawer + CharacterDialogueBubble(audit_chat_panel 方案
                1 决策:聊天列已显示全列表,浮动单气泡冗余)。 */}
            <div className="relative flex-1 h-full overflow-hidden min-w-0">
              <CharacterView className="absolute inset-0 w-full h-full z-0" />

              {/* UX-003 hotfix: 情绪状态条挂在 chat-view ``relative`` 容器内,
                  ``left: 16px / top: 48px`` 锚到 CharacterView 实际占据的子区域。 */}
              <CharacterStatePanel position="panel" />

              <div className="absolute bottom-0 left-0 right-0 z-20">
                <ChatInput />
              </div>
            </div>

            {/* 右侧推拉切换 button(镜像左侧的 ConversationList 折叠 button)。
                Chevron 方向相反:展开时 ▶ → 收起 / 收起时 ◀ → 展开。 */}
            <button
              type="button"
              className="group w-6 shrink-0 h-full flex items-center justify-center transition-colors"
              style={{
                background: 'color-mix(in srgb, var(--color-bg-surface) 60%, transparent)',
                borderLeft: '1px solid var(--color-border-subtle)',
                color: 'var(--color-text-secondary)',
              }}
              onClick={() => setChatPanelCollapsed(!chatPanelCollapsed)}
              title={chatPanelCollapsed ? '展开聊天记录' : '收起聊天记录'}
              aria-label={chatPanelCollapsed ? '展开聊天记录' : '收起聊天记录'}
            >
              {chatPanelCollapsed ? <ChevronLeft size={14} /> : <ChevronRight size={14} />}
            </button>

            {/* 2026-05-19 — ChatHistoryPanel 左边缘 resize handle (镜像左侧 handle)。
                仅 chatPanelCollapsed=false 时显示。dx 取反:右拖 panel 变窄、立绘
                变大;左拖 panel 变宽、立绘变小。同 4px 热区 + 1px/2px 灰/accent
                高亮 + col-resize cursor + 双击重置 DEFAULT(420)。 */}
            {!chatPanelCollapsed && (
              <div
                role="separator"
                aria-orientation="vertical"
                aria-label="拖拽调整聊天记录宽度"
                aria-valuenow={chatHistoryWidth}
                aria-valuemin={CHAT_HISTORY_WIDTH_MIN}
                aria-valuemax={CHAT_HISTORY_WIDTH_MAX}
                onPointerDown={onChatResizeStart}
                onPointerMove={onChatResizeMove}
                onPointerUp={onChatResizeEnd}
                onPointerCancel={onChatResizeEnd}
                onDoubleClick={() => setChatHistoryWidth(CHAT_HISTORY_WIDTH_DEFAULT)}
                className="shrink-0 h-full relative group"
                style={{
                  width: 4,
                  cursor: 'col-resize',
                  touchAction: 'none',
                }}
                title="拖拽调整宽度 · 双击重置"
              >
                <div
                  className="absolute top-0 bottom-0 left-1/2 -translate-x-1/2 transition-colors"
                  style={{
                    width: draggingChat ? 2 : 1,
                    background: draggingChat
                      ? 'var(--color-accent)'
                      : 'var(--color-border-subtle)',
                  }}
                />
                <div
                  className="absolute top-0 bottom-0 left-1/2 -translate-x-1/2 opacity-0 group-hover:opacity-100 transition-opacity"
                  style={{
                    width: 2,
                    background: 'var(--color-accent)',
                  }}
                />
              </div>
            )}

            <ChatHistoryPanel />
          </>
        ) : panelView === 'characters' ? (
          <div className="flex flex-1 flex-col overflow-hidden">
            <CharacterPanel />
          </div>
        ) : null
        /* 2026-06-02 · UI redesign · 'capabilities' / 'settings_v2' 整页 view
           已退役 · 改走 activeOverlay 磨砂浮层(本组件底部条件渲染)。任何遗留
           panelView=='capabilities'/'settings_v2' 字符串 → 主区显示空(null)而
           非 chat,因为它们的入口被 sidebar onClick 改成 setActiveOverlay 了 ·
           未来若彻底清掉 panelView 类型字面值再删此条注释。
           panelView=='chat' 走上面 chat 分支;其它(characters / legacy)各走各的。*/
        }
      </div>
      </div>

      {/* bugfix-2: 顶层 toast surface 给 V2 panels 用 */}
      {toasts.length > 0 && (
        <div className="fixed bottom-4 right-4 z-[900] flex flex-col gap-2 pointer-events-none">
          {toasts.map((t) => (
            <div
              key={t.id}
              className="text-sm px-3 py-2 rounded shadow-lg pointer-events-auto"
              style={{
                background: 'color-mix(in srgb, var(--color-bg-surface) 90%, transparent)',
                border: '1px solid rgba(244, 63, 94, 0.6)',
                color: 'var(--color-text-primary)',
              }}
            >
              {t.text}
            </div>
          ))}
        </div>
      )}

      {/* 2026-06-02 · UI redesign · 磨砂浮层 · z-[800] · 高于状态条 30 /
          低于立绘馆 990 · ESC 或 backdrop click 关闭。
          原 CapabilitiesPanel / SettingsPanelV2 从整页 panelView 移到这里浮层化 ·
          关掉 = 回主聊天、场景重新清晰。Sidebar 的 "能力" / "设置" 按钮触发。 */}
      {activeOverlay === 'capabilities' && (
        <OverlayShell onClose={() => setActiveOverlay(null)}>
          <CapabilitiesPanel showToast={showToast} />
        </OverlayShell>
      )}
      {activeOverlay === 'settings' && (
        <OverlayShell onClose={() => setActiveOverlay(null)}>
          <SettingsPanelV2 showToast={showToast} />
        </OverlayShell>
      )}
    </div>
  );
}
