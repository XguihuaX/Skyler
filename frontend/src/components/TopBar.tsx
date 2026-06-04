import { getCurrentWindow } from '@tauri-apps/api/window';
import { ChevronsUp, Maximize2, Minimize2, Minus, X } from 'lucide-react';
import { useAppStore } from '../store';
import { applyModeWindowProps } from '../lib/window';
import { useFullscreen } from '../hooks/useFullscreen';
import CharacterSwitcher from './CharacterSwitcher';

export default function TopBar() {
  const setMode = useAppStore((s) => s.setMode);

  // bugfix-2.6: Gallery 入口已挪到 Sidebar(🎴 角色图鉴),TopBar 不再有
  // GalleryThumbnails 按钮 + setGalleryOpen 订阅。
  // bugfix-extra: 加全屏 / 退出全屏切换按钮(Maximize2 / Minimize2),
  // 状态自动跟随 Tauri window onResized + 系统 fullscreenchange 事件。
  const { isFullscreen, toggle: toggleFullscreen } = useFullscreen();

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
        // Round 4 ④(2026-06-04):吃 glass-bg / glass-blur 统一 token · 顶部
        // 贴视口边,radius/border/shadow 例外不加(顶贴边时这三项视觉违和)。
        background: 'var(--glass-bg)',
        backdropFilter: 'blur(var(--glass-blur))',
        WebkitBackdropFilter: 'blur(var(--glass-blur))',
      }}
    >
      {/* Drag region — title lives here so clicks on text still drag */}
      <div
        data-tauri-drag-region
        className="flex-1 flex items-center pl-4 h-full cursor-grab active:cursor-grabbing"
      >
        <span
          className="text-sm font-semibold pointer-events-none"
          style={{
            color: 'var(--glass-text)',
            textShadow: 'var(--glass-text-shadow)',
          }}
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
          style={{ color: 'var(--glass-text-muted)' }}
          onClick={handleCollapse}
          title="切回 Widget 模式"
        >
          <ChevronsUp size={16} />
        </button>
        <button
          className="w-7 h-7 rounded-md flex items-center justify-center transition hover:bg-[color-mix(in_srgb,var(--color-bg-elevated)_70%,transparent)]"
          style={{ color: 'var(--glass-text-muted)' }}
          onClick={handleMinimize}
          title="最小化"
        >
          <Minus size={16} />
        </button>
        <button
          className="w-7 h-7 rounded-md flex items-center justify-center transition hover:bg-[color-mix(in_srgb,var(--color-bg-elevated)_70%,transparent)]"
          style={{ color: 'var(--glass-text-muted)' }}
          onClick={() => void toggleFullscreen()}
          title={isFullscreen ? '退出全屏' : '进入全屏'}
          aria-label={isFullscreen ? '退出全屏' : '进入全屏'}
        >
          {isFullscreen ? <Minimize2 size={16} /> : <Maximize2 size={16} />}
        </button>
        <button
          className="w-7 h-7 rounded-md flex items-center justify-center transition hover:bg-rose-500/80 hover:text-white"
          style={{ color: 'var(--glass-text-muted)' }}
          onClick={handleClose}
          title="关闭"
        >
          <X size={16} />
        </button>
      </div>
    </div>
  );
}
