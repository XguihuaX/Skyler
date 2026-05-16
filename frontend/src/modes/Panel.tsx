import { useCallback, useState } from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { useAppStore } from '../store';
import CapabilitiesPanel from '../components/capabilities/CapabilitiesPanel';
import CharacterPanel from '../components/CharacterPanel';
import CharacterStatePanel from '../components/CharacterStatePanel';
import CharacterView from '../components/CharacterView';
import ChatHistoryPanel from '../components/ChatHistoryPanel';
import ChatInput from '../components/ChatInput';
import ConversationList from '../components/ConversationList';
import SettingsPanelV2 from '../components/settings/SettingsPanelV2';
import Sidebar from '../components/Sidebar';
import TopBar from '../components/TopBar';

interface ToastInfo {
  id: number;
  text: string;
}

export default function Panel() {
  const panelView   = useAppStore((s) => s.panelView);
  const collapsed   = useAppStore((s) => s.conversationListCollapsed);
  const setCollapsed = useAppStore((s) => s.setConversationListCollapsed);
  // 方案 1:右侧 chat panel 推拉,与左侧 conv list 对称。
  const chatPanelCollapsed   = useAppStore((s) => s.chatPanelCollapsed);
  const setChatPanelCollapsed = useAppStore((s) => s.setChatPanelCollapsed);

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
      className="w-full h-full flex flex-col overflow-hidden"
      style={{
        background: 'var(--color-bg-base)',
        color: 'var(--color-text-primary)',
      }}
    >
      <TopBar />

      <div className="flex flex-1 overflow-hidden">
        <Sidebar />

        {panelView === 'chat' ? (
          <>
            <ConversationList />

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

            <ChatHistoryPanel />
          </>
        ) : panelView === 'characters' ? (
          <div className="flex flex-1 flex-col overflow-hidden">
            <CharacterPanel />
          </div>
        ) : panelView === 'capabilities' ? (
          <CapabilitiesPanel showToast={showToast} />
        ) : (
          // bugfix-2.2: 'settings_v2' 是新规范唯一 settings view。任何遗留
          // 'settings' 字符串(老 localStorage / state 残留)也兜底到 V2 而非
          // legacy panel —— 老 panel 不再出现在 UI。
          <SettingsPanelV2 showToast={showToast} />
        )}
      </div>

      {/* bugfix-2: 顶层 toast surface 给 V2 panels 用 */}
      {toasts.length > 0 && (
        <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 pointer-events-none">
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
    </div>
  );
}
