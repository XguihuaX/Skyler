import { useAppStore } from '../store';
import ChatHistory from './ChatHistory';

/**
 * 右侧固定聊天历史栏(方案 1)— 取代 ChatHistoryDrawer。
 *
 * 与原 drawer 区别:
 *   * **可推拉**(与左侧 ConversationList 对称),不是固定钉死也不是 slide-in 抽屉。
 *     ``chatPanelCollapsed=true`` → ``w-0``;``=false`` → ``w-[420px]``。
 *   * 中间立绘区 ``flex-1`` 在两侧任意推拉组合下都自适应填满剩余,Galgame
 *     立绘竖图等比例缩放不变形。
 *   * 两侧都收起时 = 纯 Galgame 立绘沉浸(原始体验不丢)。
 *   * 不写 ``chatMessages`` — 仅读;由 ConversationList / App.tsx /
 *     CharacterSwitcher / useWebSocket 等多处写入。
 *
 * M1 Air 小屏(< 1280px)首次启动 ``initialCollapsedDefault`` 自动 true,
 * 优先保立绘 + 输入框可用;用户后续手动展开会持久化到 localStorage。
 */
export default function ChatHistoryPanel() {
  const collapsed = useAppStore((s) => s.chatPanelCollapsed);
  // 2026-05-19 可拖拽宽度。collapsed=true → 强制 0;否则用 store 持久化值。
  const chatHistoryWidth = useAppStore((s) => s.chatHistoryWidth);

  return (
    <div
      className="shrink-0 h-full flex flex-col overflow-hidden transition-[width] duration-200 ease-out"
      style={{
        width: collapsed ? 0 : chatHistoryWidth,
        // 2026-06-02 · 玻璃化 · 核心阅读区,78% 略压实 + blur(10px) 统一面板节奏
        background: 'color-mix(in srgb, var(--color-bg-surface) 78%, transparent)',
        backdropFilter: collapsed ? undefined : 'blur(10px)',
        WebkitBackdropFilter: collapsed ? undefined : 'blur(10px)',
        borderLeft: collapsed ? 'none' : '1px solid var(--color-border-subtle)',
      }}
    >
      <div
        className="h-12 px-4 flex items-center shrink-0"
        style={{ borderBottom: '1px solid var(--color-border-subtle)' }}
      >
        <h3
          className="text-sm font-medium"
          style={{ color: 'var(--color-text-primary)' }}
        >
          聊天记录
        </h3>
      </div>
      <ChatHistory />
    </div>
  );
}
