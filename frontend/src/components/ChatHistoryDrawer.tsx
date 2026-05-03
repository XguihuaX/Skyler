import { useEffect } from 'react';
import { X } from 'lucide-react';
import ChatHistory from './ChatHistory';

interface Props {
  open: boolean;
  onClose: () => void;
}

/**
 * Right-side slide-in drawer hosting the full ChatHistory.
 * 抽屉常驻挂载，靠 translate-x 切换；off-screen 时 pointer-events 关闭。
 */
export default function ChatHistoryDrawer({ open, onClose }: Props) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  return (
    <div
      className={`fixed inset-0 z-40 ${open ? '' : 'pointer-events-none'}`}
      aria-hidden={!open}
    >
      {/* Click-outside catcher: covers the chat-area space NOT occupied by the drawer */}
      <div
        className={`absolute inset-0 right-[60%] transition-opacity duration-300 ${
          open ? 'opacity-100' : 'opacity-0'
        }`}
        onClick={onClose}
        aria-label="关闭历史抽屉"
      />

      {/* Drawer panel */}
      <div
        className={`absolute top-0 right-0 h-full w-[60%]
                    backdrop-blur-lg shadow-2xl pt-10
                    transition-transform duration-300 ease-out
                    flex flex-col
                    ${open ? 'translate-x-0' : 'translate-x-full'}`}
        style={{
          background: 'color-mix(in srgb, var(--color-bg-surface) 85%, transparent)',
          borderLeft: '1px solid var(--color-border-subtle)',
        }}
      >
        <div
          className="h-12 px-4 flex items-center justify-between shrink-0"
          style={{ borderBottom: '1px solid var(--color-border-subtle)' }}
        >
          <h3
            className="text-sm font-medium"
            style={{ color: 'var(--color-text-primary)' }}
          >
            聊天记录
          </h3>
          <button
            type="button"
            className="w-8 h-8 rounded-md flex items-center justify-center transition hover:bg-[color-mix(in_srgb,var(--color-bg-elevated)_60%,transparent)]"
            style={{ color: 'var(--color-text-secondary)' }}
            onClick={onClose}
            title="关闭"
            aria-label="关闭"
          >
            <X size={18} />
          </button>
        </div>
        <ChatHistory />
      </div>
    </div>
  );
}
