import { useCallback, useState } from 'react';
// Round 3.4(2026-06-03):ConvList 也 chip 化后 · flex 流里 resize handle +
// collapse button 全删 · ChevronLeft 用于右侧 ChatHistoryPanel 唤回 chip。
// Round 4 ②(2026-06-04):删左上 ConvList 唤回 chip(ChevronRight),改用
// Sidebar dock 上的「会话列表」图标(MessagesSquare)开/收。
import { ChevronLeft } from 'lucide-react';
import { useAppStore } from '../store';
import CapabilitiesPanel from '../components/capabilities/CapabilitiesPanel';
import CharacterPanel from '../components/CharacterPanel';
import CharacterStatePanel from '../components/CharacterStatePanel';
import CharacterView from '../components/CharacterView';
import ChatHistoryPanel from '../components/ChatHistoryPanel';
import ChatInput from '../components/ChatInput';
import ConversationList from '../components/ConversationList';
import OverlayShell from '../components/OverlayShell';
import SceneBackground from '../components/SceneBackground';
import SettingsPanelV2 from '../components/settings/SettingsPanelV2';
import Sidebar from '../components/Sidebar';
import SystemPanel from '../components/system/SystemPanel';
import TopBar from '../components/TopBar';

interface ToastInfo {
  id: number;
  text: string;
}

export default function Panel() {
  const panelView   = useAppStore((s) => s.panelView);
  // 2026-06-02 · UI redesign · 浮层路由(取代原 capabilities/settings_v2 整页 view)
  const activeOverlay    = useAppStore((s) => s.activeOverlay);
  const setActiveOverlay = useAppStore((s) => s.setActiveOverlay);
  // Round 4 ②:ConvList 开/收已移到 Sidebar dock 的「会话列表」图标 ·
  // Panel 仅订阅 collapsed 用于条件渲染浮卡 · setCollapsed 由 Sidebar / ConvList
  // 内部 X 按钮调用。
  const collapsed   = useAppStore((s) => s.conversationListCollapsed);
  // 方案 1:右侧 chat panel 推拉,与左侧 conv list 对称。
  const chatPanelCollapsed   = useAppStore((s) => s.chatPanelCollapsed);
  const setChatPanelCollapsed = useAppStore((s) => s.setChatPanelCollapsed);

  // Round 3.4(2026-06-03):ConvList chip 化后 · 左侧 resize handle 也删 ·
  // 浮卡固定 width:280 · convListWidth + conversationListWidth resize 相关
  // store 字段保留(数据架构不动)· view 层不再消费 · 跟 chatHistoryWidth 同
  // 处理。

  // bugfix-2: 共享 toast 给 CapabilitiesPanel / SettingsPanelV2(老 SettingsPanel
  // 自己内置 toast,不接入)。
  const [toasts, setToasts] = useState<ToastInfo[]>([]);
  const showToast = useCallback((text: string) => {
    const id = Date.now() + Math.random();
    setToasts((prev) => [...prev, { id, text }]);
    setTimeout(() => setToasts((prev) => prev.filter((t) => t.id !== id)), 3000);
  }, []);

  return (
    <div
      className="w-full h-full flex flex-col overflow-hidden relative"
      style={{
        // 2026-06-03 撤销:上一轮删 bg-base 试图让"app 内空区露 OS 桌面"
        // 走偏了 — 透出了终端等其它程序,这不是"app 内不透明壁纸"是"真桌面集成"
        // (推迟项)。恢复 bg-base 作为壁纸**不存在时**的不透明兜底色 ·
        // SceneBackground(fixed inset-0 z-0)在它之上铺设定的壁纸图 ·
        // 玻璃 UI 在 SceneBackground 之上 z-10/20/30。
        // 没设壁纸 → 看到 bg-base(主题色 · 不透明)
        // 设了壁纸 → SceneBackground 图盖住 bg-base
        // 整 Panel 模式窗口内任何空区永远是 app 内自渲染色,不会透 OS 桌面。
        background: 'var(--color-bg-base)',
        color: 'var(--color-text-primary)',
      }}
    >
      {/* 2026-06-02 · UI redesign · 全局场景背景层(壁纸)· z-0 整窗铺底 ·
          没设场景时不渲染、不挡 Panel 容器的 fallback bg-base。 */}
      <SceneBackground />

      {/* Round 4 ② 续(2026-06-04):心情小标锚 Panel 根容器(整窗左上角),
          不再嵌 chat main area —— 让它在 dock 上方、ConvList 浮卡左侧 / 上方
          那块空角(关会话 = 安静待在左上;开会话 = ConvList 在右下展开,不重叠)。
          z 由组件内自带(zIndex:30)高于 z-10 主 UI wrapper。 */}
      <CharacterStatePanel position="panel" />

      {/* 主 UI 层 · 包整个 TopBar + 主区 · 相对定位让它浮在 SceneBackground 之上 */}
      <div className="relative z-10 flex flex-col flex-1 overflow-hidden">
      <TopBar />

      {/* Round 3.4 · Sidebar 浮 dock 后从 flex 流抽出(不占宽度)· 给 flex 父
          加 padding-left:80px(dock left:20 + width:52 + 右余白 = ~80)避免
          后面 ConvList 等 flex 子撞 dock。flex 父挂 relative 让 Sidebar
          absolute 锚定这里(不是 z-10 wrapper 含 TopBar 区域)· dock 垂直
          居中算 chat 主区高度,不含 TopBar 那 40px。 */}
      <div className="flex flex-1 overflow-hidden relative" style={{ paddingLeft: '80px' }}>
        <Sidebar />

        {panelView === 'chat' ? (
          <>
            {/* 2026-06-04 · Round 4 ② · ConvList 折进 dock:展开浮卡仍 absolute
                · 收起态不再渲左上唤回 chip(被 dock 上的 MessagesSquare「会话列表」
                图标取代)。chip 删后左上彻底清爽,只剩心情小标。 */}
            {!collapsed && <ConversationList />}

            {/* Chat main area — galgame-style: full-bleed character + floating overlays。
                方案 1:中央立绘区 flex-1 自适应剩余,两侧 ConversationList +
                ChatHistoryPanel 各自推拉,任意组合下立绘竖图等比缩放不变形。
                两侧都收起 = 纯 Galgame 沉浸。删除右上角"历史"按钮 +
                ChatHistoryDrawer + CharacterDialogueBubble(audit_chat_panel 方案
                1 决策:聊天列已显示全列表,浮动单气泡冗余)。

                2026-06-03 · Round 3.1 角色落位(B 修订版):
                第一版用 60% 宽 + 92% 高 wrapper 压缩 → 角色被裁/偏小。
                改为 wrapper 保持满高满宽(inset-0),让 ResizeObserver 拿到完整
                尺寸 · Live2D 按全高等比饱满渲染(整只不裁、回到 3.1 之前的尺寸
                饱满感)· 用 CSS transform: translateX(-17%) 把整个 wrapper 内容
                左移到画面 ~33% 横向位 · 右侧 40% 留位由 3.5 暖巷以浮层盖在角色
                之上来完成,**不**靠压扁容器。runtime / background_path /
                panelOverlayStyle 不动。 */}
            <div className="relative flex-1 h-full overflow-hidden min-w-0">
              {/* 角色容器 · 满高满宽 · CSS transform 整体左移 · 底落地 */}
              <div
                className="absolute inset-0 z-0"
                style={{
                  transform: 'translateX(0)',
                }}
              >
                <CharacterView className="absolute inset-0 w-full h-full" />
                {/* 脚下光台 · 跟着 wrapper 左移 · 在 wrapper 中心底部一片柔光 ·
                    width 缩到 30%(原 55% 是给 60% 压扁 wrapper 算的,现满宽
                    要按总画面比例算) · pointer-events-none. */}
                <div
                  className="absolute pointer-events-none"
                  style={{
                    bottom: '4%',
                    left: '50%',
                    transform: 'translateX(-50%)',
                    width: '30%',
                    height: '36px',
                    background:
                      'radial-gradient(ellipse at center, rgba(255,255,255,0.20) 0%, rgba(255,255,255,0.06) 50%, transparent 75%)',
                    filter: 'blur(10px)',
                    zIndex: 1,
                  }}
                  aria-hidden="true"
                />
              </div>

              {/* Round 4 ② 续(2026-06-04):CharacterStatePanel 已从这里搬到
                  Panel 根容器(SceneBackground 旁),锚整窗左上角(top:48 left:8),
                  不再跟着 chat main area paddingLeft:80 偏移。关闭会话时纯净
                  待在左上,打开会话列表(ConvList top:60 left:80)在它右下方
                  展开,两者不重叠。 */}

              {/* 2026-06-03 · Round 3.5 对话暖巷:ChatHistoryPanel 从 flex 流贴边
                  满高栏剥离,改 absolute 浮动定位挂在 chat main area 内部 z-20 ·
                  四周留白 + 圆角 + glass + scrim · chatPanelCollapsed=true 时
                  改渲染唤出 chip(右上角 chevron)而非整个浮动条。
                  TODO(v2): 收起时显示她最新一条 assistant/proactive 消息的
                  "浮角色身边、几秒淡出"临时气泡,本批不做。 */}
              {!chatPanelCollapsed ? (
                <ChatHistoryPanel />
              ) : (
                <button
                  type="button"
                  onClick={() => setChatPanelCollapsed(false)}
                  className="absolute flex items-center justify-center transition hover:opacity-80"
                  style={{
                    top: '20px',
                    right: '20px',
                    width: '36px',
                    height: '36px',
                    borderRadius: '999px',
                    background: 'var(--glass-bg)',
                    backdropFilter: 'blur(var(--glass-blur))',
                    WebkitBackdropFilter: 'blur(var(--glass-blur))',
                    border: 'var(--glass-border)',
                    boxShadow: 'var(--glass-shadow)',
                    color: 'var(--glass-text-muted)',
                    zIndex: 20,
                  }}
                  title="展开聊天记录"
                  aria-label="展开聊天记录"
                >
                  <ChevronLeft size={16} />
                </button>
              )}

              {/* 2026-06-19 · Build 1 决策 ②:输入丸包装层从这里(paddingLeft:80
                  父内)挪到 z-10 wrapper 直接子(下方)· 解 W/2+40 右偏 bug ·
                  实现真窗口正中(W/2)· 跟角色 / SceneBackground 中线对齐。
                  原:left:50% translateX(-50%) 在 paddingLeft:80 父内 = 80 + (W-80)/2
                  现:挪到 z-10 wrapper 直接子 · left:50% = 真 W/2 */}
            </div>

            {/* Round 3.5 起删除原 flex 流里的 collapse button + resize handle +
                ChatHistoryPanel 三块(共 62 行) · 全部改成 chat main area 内部
                浮动定位(上方条件渲染暖巷 / chip)· chat main area 自然变宽 ·
                角色 wrapper(translateX -17%)仍偏左到画面 ~1/3 横向位 · 暖巷
                浮在右侧 ~33%-100% 区域,左右平衡。 */}
          </>
        ) : panelView === 'characters' ? (
          <div className="flex flex-1 flex-col overflow-hidden">
            <CharacterPanel />
          </div>
        ) : null
        /* 2026-06-02 · UI redesign · 'capabilities' / 'settings_v2' 整页 view
           已退役 · 改走 activeOverlay 磨砂浮层(本组件底部条件渲染)。任何遗留
           panelView=='capabilities'/'settings_v2' 字符串 → 主区显示空(null)而
           非 chat,因为它们的入口被 sidebar onClick 改成 setActiveOverlay 了 ·
           未来若彻底清掉 panelView 类型字面值再删此条注释。
           panelView=='chat' 走上面 chat 分支;其它(characters / legacy)各走各的。*/
        }
      </div>

      {/* 2026-06-19 · Build 1 决策 ② · 输入丸包装层挪到这里 ·
          直接挂在 z-10 wrapper(100% W,不含 paddingLeft:80)· left:50% =
          真窗口正中(W/2)· 不再 W/2+40 右偏。
          - 仅 panelView==='chat' 时渲染(跟上方 chat 分支同条件)
          - 宽度走 var(--input-width)(themes.css clamp(400px, 66%, 840px))·
            决策 ③:统一 CSS 变量驱动尺寸 · Build 2 设置项可实时调
          - bottom:20 保留 / z-20 保留(对齐其它玻璃浮件) */}
      {panelView === 'chat' && (
        <div
          className="absolute z-20"
          style={{
            bottom: '20px',
            left: '50%',
            transform: 'translateX(-50%)',
            width: 'var(--input-width)',
          }}
        >
          <ChatInput />
        </div>
      )}
      </div>

      {/* bugfix-2: 顶层 toast surface 给 V2 panels 用 */}
      {toasts.length > 0 && (
        <div className="fixed bottom-4 right-4 z-[900] flex flex-col gap-2 pointer-events-none">
          {toasts.map((t) => (
            <div
              key={t.id}
              className="text-sm px-3 py-2 rounded shadow-lg pointer-events-auto"
              style={{
                background: 'color-mix(in srgb, var(--color-bg-surface) 90%, transparent)',
                border: '1px solid rgba(244, 63, 94, 0.6)',
                color: 'var(--color-text-primary)',
              }}
            >
              {t.text}
            </div>
          ))}
        </div>
      )}

      {/* 2026-06-02 · UI redesign · 磨砂浮层 · z-[800] · 高于状态条 30 /
          低于立绘馆 990 · ESC 或 backdrop click 关闭。
          原 CapabilitiesPanel / SettingsPanelV2 从整页 panelView 移到这里浮层化 ·
          关掉 = 回主聊天、场景重新清晰。Sidebar 的 "能力" / "设置" 按钮触发。 */}
      {activeOverlay === 'capabilities' && (
        <OverlayShell onClose={() => setActiveOverlay(null)}>
          <CapabilitiesPanel showToast={showToast} />
        </OverlayShell>
      )}
      {activeOverlay === 'settings' && (
        <OverlayShell onClose={() => setActiveOverlay(null)}>
          <SettingsPanelV2 showToast={showToast} />
        </OverlayShell>
      )}
      {activeOverlay === 'system' && (
        <OverlayShell onClose={() => setActiveOverlay(null)}>
          <SystemPanel />
        </OverlayShell>
      )}
    </div>
  );
}
