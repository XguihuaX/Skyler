import { useEffect, useRef, useState } from 'react';
import { ChevronDown, Circle, UserRound } from 'lucide-react';
import { useAppStore } from '../store';

/**
 * Compact character switcher placed in TopBar.
 *
 * 显示当前角色（头像 + 名字 + ▾），下拉列出所有角色；底部一行跳转到角色管理页。
 * v3-B 起角色管理是 Panel 的独立子视图（panelView='characters'），不再用 Drawer。
 */
export default function CharacterSwitcher() {
  const characters         = useAppStore((s) => s.characters);
  const currentCharacterId = useAppStore((s) => s.currentCharacterId);
  const setCurrentCharacterId = useAppStore((s) => s.setCurrentCharacterId);
  const setPanelView       = useAppStore((s) => s.setPanelView);

  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement | null>(null);

  // Close on outside click / ESC
  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', onClick);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onClick);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  const current = characters.find((c) => c.id === currentCharacterId) ?? null;

  const renderAvatar = (path: string | null, size: 'sm' | 'md') => {
    const dim = size === 'md' ? 'w-6 h-6' : 'w-5 h-5';
    const iconSize = size === 'md' ? 14 : 12;
    if (path) {
      return <img src={path} alt="" className={`${dim} rounded-full object-cover`} />;
    }
    return (
      <span
        className={`${dim} rounded-full flex items-center justify-center`}
        style={{
          background: 'var(--color-bg-elevated)',
          color: 'var(--color-text-secondary)',
        }}
      >
        <UserRound size={iconSize} />
      </span>
    );
  };

  return (
    <div ref={wrapRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 px-2 py-1 rounded-md transition text-sm hover:bg-[color-mix(in_srgb,var(--color-bg-elevated)_70%,transparent)]"
        style={{ color: 'var(--color-text-primary)' }}
        title="切换角色"
      >
        {renderAvatar(current?.avatar_path ?? null, 'md')}
        <span className="max-w-[8rem] truncate">{current?.name ?? '未选择'}</span>
        <ChevronDown size={14} style={{ color: 'var(--color-text-secondary)' }} />
      </button>

      {open && (
        <div
          className="absolute right-0 top-full mt-1 w-56 z-[60] rounded-lg shadow-2xl overflow-hidden"
          style={{
            background: 'var(--color-bg-elevated)',
            border: '1px solid var(--color-border)',
          }}
        >
          <ul className="max-h-72 overflow-y-auto py-1">
            {characters.length === 0 ? (
              <li
                className="px-3 py-2 text-xs"
                style={{ color: 'var(--color-text-secondary)' }}
              >
                暂无角色
              </li>
            ) : (
              characters.map((c) => {
                const active = c.id === currentCharacterId;
                return (
                  <li key={c.id}>
                    <button
                      type="button"
                      onClick={() => {
                        if (!active) setCurrentCharacterId(c.id);
                        setOpen(false);
                      }}
                      className="w-full flex items-center gap-2 px-3 py-2 text-sm transition"
                      style={
                        active
                          ? {
                              background: 'color-mix(in srgb, var(--color-accent) 35%, transparent)',
                              color: 'var(--color-text-primary)',
                            }
                          : { color: 'var(--color-text-primary)' }
                      }
                      onMouseEnter={(e) => {
                        if (!active) {
                          e.currentTarget.style.background =
                            'color-mix(in srgb, var(--color-bg-surface) 60%, transparent)';
                        }
                      }}
                      onMouseLeave={(e) => {
                        if (!active) e.currentTarget.style.background = 'transparent';
                      }}
                    >
                      {renderAvatar(c.avatar_path, 'sm')}
                      <span className="flex-1 truncate text-left">{c.name}</span>
                      {active && (
                        <Circle
                          size={10}
                          fill="currentColor"
                          style={{ color: 'var(--color-text-accent)' }}
                        />
                      )}
                    </button>
                  </li>
                );
              })
            )}
          </ul>
          <div style={{ borderTop: '1px solid var(--color-border-subtle)' }}>
            <button
              type="button"
              onClick={() => {
                setOpen(false);
                setPanelView('characters');
              }}
              className="w-full px-3 py-2 text-sm transition text-left"
              style={{ color: 'var(--color-text-primary)' }}
              onMouseEnter={(e) =>
                (e.currentTarget.style.background =
                  'color-mix(in srgb, var(--color-bg-surface) 60%, transparent)')
              }
              onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
            >
              管理角色…
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
