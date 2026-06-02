import {
  Boxes,
  GalleryThumbnails,
  MessageCircle,
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

  const navItems: NavItem[] = [
    { kind: 'view',   view: 'chat',         Icon: MessageCircle,     label: '聊天' },
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
      className="w-16 flex flex-col items-center py-4 gap-2 shrink-0"
      style={{
        // 2026-06-02 · 玻璃化 · 加 backdrop-blur 让 SceneBackground 透出
        background: 'color-mix(in srgb, var(--color-bg-surface) 60%, transparent)',
        backdropFilter: 'blur(10px)',
        WebkitBackdropFilter: 'blur(10px)',
        borderRight: '1px solid var(--color-border-subtle)',
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
                : { color: 'var(--color-text-secondary)' }
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
