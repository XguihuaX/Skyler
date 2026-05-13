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
      {/* Click-outside catcher: covers the chat-area space NOT occupied by the drawer.
          UX-007: 加 40% 黑半透明 + 8px backdrop-blur,让 Live2D 在左侧透着柔化可见
          (而非彻底被白屏盖)。rgba(0,0,0,0.4) 在所有主题下行为一致(浅色 → 适度变暗,
          暗色 → 进一步加深 — 跟 system modal scrim 行为对齐)。 */}
      <div
        className={`absolute inset-0 right-[60%] transition-opacity duration-300 ${
          open ? 'opacity-100' : 'opacity-0'
        }`}
        style={{
          background: 'rgba(0, 0, 0, 0.4)',
          backdropFilter: 'blur(8px)',
          WebkitBackdropFilter: 'blur(8px)',  // Safari prefix
        }}
        onClick={onClose}
        aria-label="关闭历史抽屉"
      />

      {/* Drawer panel
          UX-007: surface 85% → 95% 让消息卡片更清晰(用户专门来看历史,要求文字
          稳定可读)。backdrop-blur-lg 仍保留 — 用户拖窗或 Live2D 大幅运动时
          panel 边缘不显得突兀。 */}
      <div
        className={`absolute top-0 right-0 h-full w-[60%]
                    backdrop-blur-lg shadow-2xl pt-10
                    transition-transform duration-300 ease-out
                    flex flex-col
                    ${open ? 'translate-x-0' : 'translate-x-full'}`}
        style={{
          background: 'color-mix(in srgb, var(--color-bg-surface) 95%, transparent)',
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
