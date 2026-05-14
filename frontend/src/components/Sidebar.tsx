import {
  Boxes,
  MessageCircle,
  Settings,
  Users,
  Wrench,
  type LucideIcon,
} from 'lucide-react';
import { useAppStore } from '../store';
import ConnectionDot from './ConnectionDot';

type PanelView =
  | 'chat'
  | 'characters'
  | 'capabilities'
  | 'settings_v2'
  | 'settings';

// bugfix-2: 拆 Setting 为 能力 + 设置 顶级双项。老 'settings' 保留作 "高级"
// 入口(降回归风险, Bugfix-4 后再决定是否删)。
const navItems: { view: PanelView; Icon: LucideIcon; label: string }[] = [
  { view: 'chat',         Icon: MessageCircle, label: '聊天' },
  { view: 'characters',   Icon: Users,         label: '角色' },
  { view: 'capabilities', Icon: Boxes,         label: '能力' },
  { view: 'settings_v2',  Icon: Settings,      label: '设置' },
  { view: 'settings',     Icon: Wrench,        label: '高级（旧设置）' },
];

export default function Sidebar() {
  const panelView    = useAppStore((s) => s.panelView);
  const setPanelView = useAppStore((s) => s.setPanelView);

  return (
    <div
      className="w-16 flex flex-col items-center py-4 gap-2 shrink-0"
      style={{
        background: 'color-mix(in srgb, var(--color-bg-surface) 60%, transparent)',
        borderRight: '1px solid var(--color-border-subtle)',
      }}
    >
      {navItems.map(({ view, Icon, label }) => {
        const active = panelView === view;
        return (
          <button
            key={view}
            className="w-10 h-10 rounded-xl flex items-center justify-center transition"
            style={
              active
                ? {
                    background: 'color-mix(in srgb, var(--color-accent) 25%, transparent)',
                    color: 'var(--color-text-accent)',
                  }
                : { color: 'var(--color-text-secondary)' }
            }
            onClick={() => setPanelView(view)}
            title={label}
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
