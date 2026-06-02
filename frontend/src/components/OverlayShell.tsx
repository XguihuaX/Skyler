/**
 * 2026-06-02 · UI redesign step 2 · 通用磨砂浮层壳。
 *
 * z-index:[800] — 高于状态条(30)、低于立绘馆(990)、低于 modal/splash(1000+)。
 * Backdrop:复用 CharacterDetailModal.tsx:122-142 模板,但 brightness 调亮
 *   (modal 是 0.45,这里 0.65,让壁纸透出来)、rgba 黑遮罩降到 0.20。
 *
 * 关闭路径:
 *   1. 点击 backdrop(stopPropagation 的内容卡片除外)
 *   2. ESC 键
 *   3. 内部容器透传 onClose 给具体浮层(如 SettingsPanel 顶部"关"按钮)
 */
import { useEffect } from 'react';

interface OverlayShellProps {
  onClose: () => void;
  children: React.ReactNode;
  /** 是否禁用 backdrop click 关闭(防意外点穿) · 默认 false 允许 */
  disableBackdropClose?: boolean;
}

export default function OverlayShell({
  onClose,
  children,
  disableBackdropClose,
}: OverlayShellProps) {
  // ESC 关
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <>
      {/* Backdrop · 磨砂 + 轻暗化 · 让壁纸透出来 */}
      <div
        className="fixed inset-0 z-[800]"
        style={{
          backdropFilter: 'blur(8px) brightness(0.65)',
          WebkitBackdropFilter: 'blur(8px) brightness(0.65)',
          background: 'rgba(0, 0, 0, 0.20)',
        }}
        onClick={() => {
          if (!disableBackdropClose) onClose();
        }}
      />
      {/* 内容容器 · z-[801] · pointer-events:none 让 backdrop 接 click,
          内部具体卡片用 pointer-events:auto 自取 */}
      <div className="fixed inset-0 z-[801] pointer-events-none flex items-stretch justify-center p-6">
        <div
          className="pointer-events-auto w-full max-w-[1100px] h-full rounded-2xl overflow-hidden flex flex-col"
          style={{
            background: 'color-mix(in srgb, var(--color-bg-surface) 78%, transparent)',
            border: '1px solid var(--color-border-subtle)',
            boxShadow: 'var(--shadow-card-lift)',
            backdropFilter: 'blur(12px)',
            WebkitBackdropFilter: 'blur(12px)',
          }}
          onClick={(e) => e.stopPropagation()}
        >
          {children}
        </div>
      </div>
    </>
  );
}
