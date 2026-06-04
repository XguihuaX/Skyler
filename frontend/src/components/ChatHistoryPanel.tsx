import { useCallback, useEffect, useRef, useState } from 'react';
import { CornerDownLeft, X } from 'lucide-react';
import { useAppStore } from '../store';
import ChatHistory from './ChatHistory';

/**
 * 右侧浮动对话暖巷(Round 3.5,2026-06-03 重构 · Round 4 ③ 2026-06-04 可伸缩)。
 *
 * 当前形态:
 *   * 锚右上角:absolute · top:20 · right:20 · width = store.chatHistoryWidth ·
 *     height = store.chatHistoryHeight(不再用 bottom:100 贴边)。
 *   * 圆角 + glass token + shadow,跟输入丸视觉节奏一致。
 *   * 收起按钮内置(顶部标题旁 X);chatPanelCollapsed=true 时 Panel.tsx 在外层
 *     渲染右上唤出 chip(ChevronLeft)取代浮卡。
 *   * 左下角(右上锚的自由角)拖拽手柄,同时改 width + height —— 鼠标往左 = 宽增,
 *     鼠标往下 = 高增;clamp 由 store setter 内部完成。
 *   * 不写 chatMessages;仅读。渲染逻辑下沉到 ChatHistory.tsx。
 */
export default function ChatHistoryPanel() {
  const collapsed     = useAppStore((s) => s.chatPanelCollapsed);
  const setCollapsed  = useAppStore((s) => s.setChatPanelCollapsed);
  const width         = useAppStore((s) => s.chatHistoryWidth);
  const setWidth      = useAppStore((s) => s.setChatHistoryWidth);
  const height        = useAppStore((s) => s.chatHistoryHeight);
  const setHeight     = useAppStore((s) => s.setChatHistoryHeight);

  // 拖拽起点缓存:pointerDown 记录鼠标坐标 + 当时宽高,move 时算 delta · clamp
  // 在 store setter 内部完成,不在这里夹(交给 store 收口避免重复)。
  const dragStartRef = useRef<{ x: number; y: number; w: number; h: number } | null>(null);
  const [dragging, setDragging] = useState(false);

  const onResizeStart = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    dragStartRef.current = { x: e.clientX, y: e.clientY, w: width, h: height };
    setDragging(true);
    (e.currentTarget as HTMLElement).setPointerCapture?.(e.pointerId);
  }, [width, height]);

  const onResizeMove = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    if (!dragStartRef.current) return;
    const dx = e.clientX - dragStartRef.current.x;
    const dy = e.clientY - dragStartRef.current.y;
    // 右上锚 → 左下自由角:鼠标往左(dx<0)= 宽增,鼠标往下(dy>0)= 高增。
    setWidth(dragStartRef.current.w - dx);
    setHeight(dragStartRef.current.h + dy);
  }, [setWidth, setHeight]);

  const onResizeEnd = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    if (!dragStartRef.current) return;
    dragStartRef.current = null;
    setDragging(false);
    try { (e.currentTarget as HTMLElement).releasePointerCapture?.(e.pointerId); } catch { /* swallow */ }
  }, []);

  // 拖拽时给 body 设 cursor + 禁止文字选择,避免拖出手柄区域光标变回箭头 / 选中文字。
  useEffect(() => {
    if (!dragging) return;
    const prevCursor = document.body.style.cursor;
    const prevSelect = document.body.style.userSelect;
    document.body.style.cursor = 'sw-resize';
    document.body.style.userSelect = 'none';
    return () => {
      document.body.style.cursor = prevCursor;
      document.body.style.userSelect = prevSelect;
    };
  }, [dragging]);

  if (collapsed) return null;

  return (
    <div
      className="absolute flex flex-col overflow-hidden"
      style={{
        top: '20px',
        right: '20px',
        width: `${width}px`,
        height: `${height}px`,
        borderRadius: 'var(--glass-radius)',
        background: 'var(--glass-bg)',
        backdropFilter: 'blur(var(--glass-blur))',
        WebkitBackdropFilter: 'blur(var(--glass-blur))',
        border: 'var(--glass-border)',
        boxShadow: 'var(--glass-shadow)',
        zIndex: 20,
      }}
    >
      {/* 顶部标题 + 收起按钮 */}
      <div
        className="h-12 px-4 flex items-center justify-between shrink-0"
        style={{ borderBottom: '1px solid var(--color-border-subtle)' }}
      >
        <h3
          className="text-sm font-medium"
          style={{ color: 'var(--glass-text)', textShadow: 'var(--glass-text-shadow)' }}
        >
          聊天记录
        </h3>
        <button
          type="button"
          onClick={() => setCollapsed(true)}
          className="p-1 rounded hover:opacity-80 transition"
          style={{ color: 'var(--glass-text-muted)' }}
          aria-label="收起聊天记录"
        >
          <X size={14} />
        </button>
      </div>
      <ChatHistory />

      {/* Round 4 ③ 左下角拖拽手柄(自由角)· 同时改宽高 ·
          CornerDownLeft 图标朝 ↙ 视觉提示拖拽方向 · 16×16 + 4px padding 易点。 */}
      <div
        onPointerDown={onResizeStart}
        onPointerMove={onResizeMove}
        onPointerUp={onResizeEnd}
        onPointerCancel={onResizeEnd}
        className="absolute flex items-center justify-center"
        style={{
          left: '4px',
          bottom: '4px',
          width: '20px',
          height: '20px',
          cursor: 'sw-resize',
          color: 'var(--glass-text-muted)',
          opacity: dragging ? 1 : 0.5,
          transition: 'opacity 120ms ease',
          touchAction: 'none',
          zIndex: 1,
        }}
        aria-label="拖拽调整聊天记录大小"
      >
        <CornerDownLeft size={14} />
      </div>
    </div>
  );
}
