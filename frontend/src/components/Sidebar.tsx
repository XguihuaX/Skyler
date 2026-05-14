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

// bugfix-2.6: sidebar 严格 4 项, Gallery 入口从 TopBar 挪过来。
//   💬 聊天 / 🎴 角色图鉴(overlay 触发) / 📂 能力 / ⚙ 设置
// 'characters' panelView 不再走 sidebar(CharacterSwitcher 的"管理角色…"
// 仍可用; CharacterPanel 也通过 ⚙ 设置 → 角色管理 section 访问)。
// Gallery 是 overlay 不是 panel — 点 sidebar 仅 setGalleryOpen(true), 关闭
// 后回原 panelView, 不"占用"主 panel。
type NavItem =
  | { kind: 'view'; view: PanelView; Icon: LucideIcon; label: string }
  | { kind: 'action'; id: string; onClick: () => void; isActive: boolean; Icon: LucideIcon; label: string };

export default function Sidebar() {
  const panelView      = useAppStore((s) => s.panelView);
  const setPanelView   = useAppStore((s) => s.setPanelView);
  const galleryOpen    = useAppStore((s) => s.galleryOpen);
  const setGalleryOpen = useAppStore((s) => s.setGalleryOpen);

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
    { kind: 'view',   view: 'capabilities', Icon: Boxes,             label: '能力' },
    { kind: 'view',   view: 'settings_v2',  Icon: Settings,          label: '设置' },
  ];

  return (
    <div
      className="w-16 flex flex-col items-center py-4 gap-2 shrink-0"
      style={{
        background: 'color-mix(in srgb, var(--color-bg-surface) 60%, transparent)',
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
