import { type ReactNode, type ComponentType } from 'react';
import { type LucideProps } from 'lucide-react';

/**
 * bugfix-2: 共用 two-pane shell —— 左侧子导航(标题 + N 个 section 按钮)+
 * 右侧 active section content。CapabilitiesPanel 和 SettingsPanelV2 都用。
 *
 * 没引入 router(避免大改),纯组件 state 由父级用 useState 持。
 */

export interface PaneSection {
  id: string;
  label: string;
  Icon: ComponentType<LucideProps>;
  disabled?: boolean;
  disabledHint?: string;
  render: () => ReactNode;
}

interface TwoPaneShellProps {
  title: string;
  sections: PaneSection[];
  activeId: string;
  onActiveChange: (id: string) => void;
}

export default function TwoPaneShell({
  title,
  sections,
  activeId,
  onActiveChange,
}: TwoPaneShellProps) {
  const active = sections.find((s) => s.id === activeId) ?? sections[0];

  return (
    <div className="flex flex-1 overflow-hidden">
      {/* Left sub-nav */}
      <aside
        className="w-52 shrink-0 flex flex-col py-4 px-2 gap-1 overflow-y-auto"
        style={{
          background: 'color-mix(in srgb, var(--color-bg-surface) 40%, transparent)',
          borderRight: '1px solid var(--color-border-subtle)',
        }}
      >
        <div
          className="px-3 pb-3 text-xs font-semibold uppercase tracking-wide"
          style={{ color: 'var(--color-text-secondary)' }}
        >
          {title}
        </div>
        {sections.map(({ id, label, Icon, disabled, disabledHint }) => {
          const isActive = id === active.id;
          return (
            <button
              key={id}
              type="button"
              disabled={disabled}
              onClick={() => !disabled && onActiveChange(id)}
              className="flex items-center gap-2 px-3 py-2 rounded-md text-sm text-left transition"
              style={
                isActive
                  ? {
                      background: 'color-mix(in srgb, var(--color-accent) 18%, transparent)',
                      color: 'var(--color-text-accent)',
                    }
                  : {
                      color: disabled
                        ? 'var(--color-text-tertiary, var(--color-text-secondary))'
                        : 'var(--color-text-primary)',
                      opacity: disabled ? 0.55 : 1,
                      cursor: disabled ? 'not-allowed' : 'pointer',
                    }
              }
              title={disabled ? (disabledHint ?? '即将推出') : label}
            >
              <Icon size={16} />
              <span className="flex-1 truncate">{label}</span>
              {disabled && (
                <span
                  className="text-[10px] px-1.5 py-0.5 rounded"
                  style={{
                    background: 'var(--color-bg-elevated)',
                    color: 'var(--color-text-secondary)',
                  }}
                >
                  即将推出
                </span>
              )}
            </button>
          );
        })}
      </aside>

      {/* Right content */}
      <div className="flex-1 overflow-y-auto">
        {active.render()}
      </div>
    </div>
  );
}

interface PlaceholderProps {
  title: string;
  hint: string;
  emoji?: string;
}

/**
 * 占位 section：未启用 / 即将推出。标题居中 + 一行说明。
 */
export function SectionPlaceholder({ title, hint, emoji }: PlaceholderProps) {
  return (
    <div className="h-full flex flex-col items-center justify-center px-8 text-center">
      {emoji && <div className="text-5xl mb-4 select-none">{emoji}</div>}
      <h2
        className="text-lg font-medium mb-2"
        style={{ color: 'var(--color-text-primary)' }}
      >
        {title}
      </h2>
      <p
        className="text-sm max-w-md"
        style={{ color: 'var(--color-text-secondary)' }}
      >
        {hint}
      </p>
    </div>
  );
}
