import { getCurrentWindow } from '@tauri-apps/api/window';
import { ChevronsUp, Minus, X } from 'lucide-react';
import { useAppStore } from '../store';
import { applyModeWindowProps } from '../lib/window';
import CharacterSwitcher from './CharacterSwitcher';

export default function TopBar() {
  const setMode = useAppStore((s) => s.setMode);

  // bugfix-2.6: Gallery 入口已挪到 Sidebar(🎴 角色图鉴),TopBar 不再有
  // GalleryThumbnails 按钮 + setGalleryOpen 订阅。

  const handleCollapse = async () => {
    await applyModeWindowProps('widget');
    setMode('widget');
  };

  const handleMinimize = async () => {
    await getCurrentWindow().minimize();
  };

  const handleClose = async () => {
    await getCurrentWindow().close();
  };

  return (
    <div
      className="relative z-50 flex items-center h-10 select-none shrink-0"
      style={{
        background: 'color-mix(in srgb, var(--color-bg-surface) 80%, transparent)',
        borderBottom: '1px solid var(--color-border-subtle)',
      }}
    >
      {/* Drag region — title lives here so clicks on text still drag */}
      <div
        data-tauri-drag-region
        className="flex-1 flex items-center pl-4 h-full cursor-grab active:cursor-grabbing"
      >
        <span
          className="text-sm font-semibold pointer-events-none"
          style={{ color: 'var(--color-text-primary)' }}
        >
          MomoOS
        </span>
      </div>

      {/* Character switcher — sits before the window controls so dropdown
          opens within TopBar's stacking context. */}
      <div className="pr-2">
        <CharacterSwitcher />
      </div>

      {/* Window control buttons — must NOT be inside drag region */}
      <div className="flex items-center gap-1 pr-2">
        <button
          className="w-7 h-7 rounded-md flex items-center justify-center transition hover:bg-[color-mix(in_srgb,var(--color-bg-elevated)_70%,transparent)]"
          style={{ color: 'var(--color-text-secondary)' }}
          onClick={handleCollapse}
          title="切回 Widget 模式"
        >
          <ChevronsUp size={16} />
        </button>
        <button
          className="w-7 h-7 rounded-md flex items-center justify-center transition hover:bg-[color-mix(in_srgb,var(--color-bg-elevated)_70%,transparent)]"
          style={{ color: 'var(--color-text-secondary)' }}
          onClick={handleMinimize}
          title="最小化"
        >
          <Minus size={16} />
        </button>
        <button
          className="w-7 h-7 rounded-md flex items-center justify-center transition hover:bg-rose-500/80 hover:text-white"
          style={{ color: 'var(--color-text-secondary)' }}
          onClick={handleClose}
          title="关闭"
        >
          <X size={16} />
        </button>
      </div>
    </div>
  );
}
