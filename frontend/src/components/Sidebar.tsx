import {
  Boxes,
  GalleryThumbnails,
  MessageCircle,
  MessagesSquare,
  Settings,
  type LucideIcon,
} from 'lucide-react';
import { useAppStore } from '../store';
import ConnectionDot from './ConnectionDot';

type PanelView = 'chat' | 'characters' | 'capabilities' | 'settings_v2';

// 2026-06-02 · UI redesign · 能力 / 设置改走 activeOverlay 磨砂浮层 ·
// 不再 setPanelView。聊天仍是 panelView 切换;角色图鉴 / 能力 / 设置三个
// 都是 overlay-style 入口(打开 = 浮层 · 关闭 = 回原主界面)。
//   💬 聊天(panelView) / 🎴 角色图鉴(overlay) / 📂 能力(overlay) / ⚙ 设置(overlay)
type NavItem =
  | { kind: 'view'; view: PanelView; Icon: LucideIcon; label: string }
  | { kind: 'action'; id: string; onClick: () => void; isActive: boolean; Icon: LucideIcon; label: string };

export default function Sidebar() {
  const panelView         = useAppStore((s) => s.panelView);
  const setPanelView      = useAppStore((s) => s.setPanelView);
  const galleryOpen       = useAppStore((s) => s.galleryOpen);
  const setGalleryOpen    = useAppStore((s) => s.setGalleryOpen);
  const activeOverlay     = useAppStore((s) => s.activeOverlay);
  const setActiveOverlay  = useAppStore((s) => s.setActiveOverlay);
  // Round 4 ②(2026-06-04):ConvList 唤回 chip 从左上撤掉 · 改用 dock 上的
  // 「会话列表」图标开/收 · 默认收起。
  const convListCollapsed    = useAppStore((s) => s.conversationListCollapsed);
  const setConvListCollapsed = useAppStore((s) => s.setConversationListCollapsed);

  const navItems: NavItem[] = [
    { kind: 'view',   view: 'chat',         Icon: MessageCircle,     label: '聊天' },
    {
      kind: 'action',
      id: 'conversations',
      Icon: MessagesSquare,
      label: '会话列表',
      isActive: !convListCollapsed,
      onClick: () => setConvListCollapsed(!convListCollapsed),
    },
    {
      kind: 'action',
      id: 'gallery',
      Icon: GalleryThumbnails,
      label: '角色图鉴',
      isActive: galleryOpen,
      onClick: () => setGalleryOpen(true),
    },
    {
      kind: 'action',
      id: 'capabilities',
      Icon: Boxes,
      label: '能力',
      isActive: activeOverlay === 'capabilities',
      onClick: () => setActiveOverlay('capabilities'),
    },
    {
      kind: 'action',
      id: 'settings',
      Icon: Settings,
      label: '设置',
      isActive: activeOverlay === 'settings',
      onClick: () => setActiveOverlay('settings'),
    },
  ];

  return (
    <div
      className="flex flex-col items-center gap-2"
      style={{
        // Round 4 ④(2026-06-04):吃 glass-* 统一 token(radius 20 → 16 跟其它
        // 浮件对齐 · alpha 55% → 58% · blur/border/shadow 全走 token)。
        position: 'absolute',
        left: '20px',
        top: '50%',
        transform: 'translateY(-50%)',
        padding: '12px 6px',
        borderRadius: 'var(--glass-radius)',
        background: 'var(--glass-bg)',
        backdropFilter: 'blur(var(--glass-blur))',
        WebkitBackdropFilter: 'blur(var(--glass-blur))',
        border: 'var(--glass-border)',
        boxShadow: 'var(--glass-shadow)',
        zIndex: 30,
      }}
    >
      {navItems.map((item) => {
        const active =
          item.kind === 'view' ? panelView === item.view : item.isActive;
        const onClick =
          item.kind === 'view'
            ? () => setPanelView(item.view)
            : item.onClick;
        const key = item.kind === 'view' ? item.view : item.id;
        const Icon = item.Icon;
        return (
          <button
            key={key}
            className="w-10 h-10 rounded-xl flex items-center justify-center transition"
            style={
              active
                ? {
                    background: 'color-mix(in srgb, var(--color-accent) 25%, transparent)',
                    color: 'var(--color-text-accent)',
                  }
                : { color: 'var(--glass-text-muted)' }
            }
            onClick={onClick}
            title={item.label}
          >
            <Icon size={18} />
          </button>
        );
      })}
      <div className="mt-auto mb-3">
        <ConnectionDot />
      </div>
    </div>
  );
}
