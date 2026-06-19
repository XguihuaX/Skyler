import { useRef, useState } from 'react';
import {
  Boxes,
  GalleryThumbnails,
  Gauge,
  MessageCircle,
  MessagesSquare,
  Settings,
  type LucideIcon,
} from 'lucide-react';
import { useAppStore } from '../store';
import ConnectionDot from './ConnectionDot';

// 2026-06-19 · auto-hide(C2 决策锁定)· 默认收起 · hover 左缘 sliver 滑出
// 全 ms / px 常量集中 · 真机调整一处
const HOVER_CLOSE_DELAY_MS = 200;    // mouseLeave 延迟 200ms 收(防误闭)
const SLIDE_DURATION_MS = 220;       // transform transition
// 2026-06-19 真机调:拆成"触发热区(看不见)+ 可见色条(只视觉)"
// HOTZONE_WIDTH:鼠标触发宽度 · 5→20→40px 防贴边才出(真机两次微调)
// SLIVER_WIDTH:可见色条宽度 · 仍 5px 不变(只加宽看不见的触发区)
const HOTZONE_WIDTH = 40;            // 透明 · 屏幕最左 40px 接 mouseenter
const SLIVER_WIDTH = 5;              // C2 可见 5px 色条 · 视觉提示热区位置
const EDGE_BUFFER = 8;               // dock 边沿 8px 缓冲带 · mouseLeave 余量
const SLIVER_HEIGHT_PCT = 64;        // sliver 垂直高 · 跟 dock 高度近似
// 收起态 translateX:整外层(dock 52 + padding 8×2 = 68)+ 余量 12 推出窗口外
const COLLAPSED_TRANSLATE_X = 'calc(-100% - 12px)';

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

  // 2026-06-19 · auto-hide 状态 · 决策⑤ 局部 useState(不上 store)
  // hovered=false 默认 · sliver 入口 mouseenter 翻 true → dock 滑出
  // 鼠标离开 dock + 缓冲带 → setTimeout 200ms 收(防误闭)
  const [hovered, setHovered] = useState(false);
  const closeTimerRef = useRef<number | null>(null);

  const handleEnter = () => {
    if (closeTimerRef.current !== null) {
      window.clearTimeout(closeTimerRef.current);
      closeTimerRef.current = null;
    }
    setHovered(true);
  };
  const handleLeave = () => {
    if (closeTimerRef.current !== null) {
      window.clearTimeout(closeTimerRef.current);
    }
    closeTimerRef.current = window.setTimeout(() => {
      setHovered(false);
      closeTimerRef.current = null;
    }, HOVER_CLOSE_DELAY_MS);
  };

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
    {
      // 2026-06-05 · ② 系统状态页 · 实时仪表 + 后端 health 子状态 + 模型 active +
      // 角色/场景/资源监控 · 主用途:逮间歇 VAD bug + 一眼看后端模型加载/连接。
      kind: 'action',
      id: 'system',
      Icon: Gauge,
      label: '系统',
      isActive: activeOverlay === 'system',
      onClick: () => setActiveOverlay('system'),
    },
  ];

  return (
    <>
      {/* 2026-06-19 · auto-hide 触发热区(透明 20px)· 真机调:5px 太窄,
          要贴边才能触发 · 加宽看不见的触发区 · 视觉色条仍 5px 不变。
          - 收起态 pointer-events:auto 接 mouseenter
          - 展开后 pointer-events:none 不挡 dock / 主区内容点击 */}
      <div
        onMouseEnter={handleEnter}
        onMouseLeave={handleLeave}
        style={{
          position: 'absolute',
          left: 0,
          top: '50%',
          transform: 'translateY(-50%)',
          width: HOTZONE_WIDTH,
          height: `${SLIVER_HEIGHT_PCT}%`,
          maxHeight: '420px',
          background: 'transparent',
          zIndex: 29,
          cursor: 'pointer',
          pointerEvents: hovered ? 'none' : 'auto',
        }}
        aria-label="左栏 dock(hover 滑出)"
      />

      {/* 2026-06-19 · 可见 sliver 色条(决策① C2:5px)· 屏幕最左 5px ·
          仅视觉提示热区位置 · 不接鼠标事件(热区由上面透明 hotzone 接) */}
      <div
        style={{
          position: 'absolute',
          left: 0,
          top: '50%',
          transform: 'translateY(-50%)',
          width: SLIVER_WIDTH,
          height: `${SLIVER_HEIGHT_PCT}%`,
          maxHeight: '420px',
          background: 'color-mix(in srgb, var(--color-accent) 35%, transparent)',
          borderRadius: '0 4px 4px 0',
          zIndex: 28,
          opacity: hovered ? 0 : 0.7,
          transition: `opacity ${SLIDE_DURATION_MS}ms ease-out`,
          pointerEvents: 'none',
        }}
        aria-hidden="true"
      />

      {/* dock 包装层(决策 · 8px 缓冲带 + 平移容器)· left:12 = 20−8 让里层
          glass dock 视觉位置不变(里层 padding 8 抵消)· translateX 推出 / 回原 */}
      <div
        onMouseEnter={handleEnter}
        onMouseLeave={handleLeave}
        style={{
          position: 'absolute',
          left: 20 - EDGE_BUFFER,
          top: '50%',
          transform: hovered
            ? 'translateY(-50%) translateX(0)'
            : `translateY(-50%) translateX(${COLLAPSED_TRANSLATE_X})`,
          transition: `transform ${SLIDE_DURATION_MS}ms ease-out`,
          padding: EDGE_BUFFER,  // 8px 透明缓冲带 · mouseLeave 余量
          zIndex: 30,
        }}
      >
        <div
          className="flex flex-col items-center gap-2"
          style={{
            // Round 4 ④(2026-06-04):吃 glass-* 统一 token(radius 20 → 16 跟其它
            // 浮件对齐 · alpha 55% → 58% · blur/border/shadow 全走 token)。
            // 2026-06-19 · 平移逻辑挪到外层包装 · 里层只剩 glass token,视觉位置
            // (left:20)由外层 left:12 + padding:8 共同保持 · 视觉 0 偏移。
            padding: '12px 6px',
            borderRadius: 'var(--glass-radius)',
            background: 'var(--glass-bg)',
            backdropFilter: 'blur(var(--glass-blur))',
            WebkitBackdropFilter: 'blur(var(--glass-blur))',
            border: 'var(--glass-border)',
            boxShadow: 'var(--glass-shadow)',
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
      </div>
    </>
  );
}
