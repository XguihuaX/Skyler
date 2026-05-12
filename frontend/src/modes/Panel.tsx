import { useState } from 'react';
import { ChevronLeft, ChevronRight, ScrollText } from 'lucide-react';
import { useAppStore } from '../store';
import CharacterDialogueBubble from '../components/CharacterDialogueBubble';
import CharacterPanel from '../components/CharacterPanel';
import CharacterStatePanel from '../components/CharacterStatePanel';
import CharacterView from '../components/CharacterView';
import ChatHistoryDrawer from '../components/ChatHistoryDrawer';
import ChatInput from '../components/ChatInput';
import ConversationList from '../components/ConversationList';
import SettingsPanel from '../components/SettingsPanel';
import Sidebar from '../components/Sidebar';
import TopBar from '../components/TopBar';

export default function Panel() {
  const panelView   = useAppStore((s) => s.panelView);
  const collapsed   = useAppStore((s) => s.conversationListCollapsed);
  const setCollapsed = useAppStore((s) => s.setConversationListCollapsed);

  const [historyDrawerOpen, setHistoryDrawerOpen] = useState(false);

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

            {/* Chat main area — galgame-style: full-bleed character + floating overlays */}
            <div className="relative flex-1 h-full overflow-hidden">
              <CharacterView className="absolute inset-0 w-full h-full z-0" />

              {/* UX-003 hotfix: 情绪状态条挂在 chat-view ``relative`` 容器内
                  (不是 App 外层 relative),让 ``left: 16px / top: 48px`` 锚到
                  CharacterView 实际占据的子区域,不会落在 Sidebar /
                  ConversationList 列内。z-30 仍低于 TopBar (z-50) / 历史按钮
                  (z-30) — 历史按钮在右上角 ``right-4 top-4`` 不冲突。 */}
              <CharacterStatePanel position="panel" />

              <CharacterDialogueBubble />

              <button
                type="button"
                className="absolute top-4 right-4 z-30 px-3 py-1.5 rounded-lg
                           backdrop-blur-md text-sm flex items-center gap-1.5 transition"
                style={{
                  background: 'color-mix(in srgb, var(--color-bg-surface) 60%, transparent)',
                  color: 'var(--color-text-primary)',
                }}
                onClick={() => setHistoryDrawerOpen(true)}
                title="打开聊天记录"
              >
                <ScrollText size={16} />
                <span>历史</span>
              </button>

              <div className="absolute bottom-0 left-0 right-0 z-20">
                <ChatInput />
              </div>

              <ChatHistoryDrawer
                open={historyDrawerOpen}
                onClose={() => setHistoryDrawerOpen(false)}
              />
            </div>
          </>
        ) : panelView === 'characters' ? (
          <div className="flex flex-1 flex-col overflow-hidden">
            <CharacterPanel />
          </div>
        ) : (
          <div className="flex flex-1 flex-col overflow-hidden">
            <SettingsPanel />
          </div>
        )}
      </div>
    </div>
  );
}
