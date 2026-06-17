// 2026-06-15 ⑤ · MCP tool 调用前确认 modal
//
// 显示场景:LLM 触发 dangerous tool(如 github.delete_repository / xhs.publish_note
// / email.send_email)· backend confirm_gate.request_confirmation 推 WS event
// 'mcp_tool_confirm_request' · useWebSocket case 写 store.mcpConfirmRequest ·
// 本组件挂在 App.tsx 顶层 · 看到非 null 就弹。
//
// 行为:
//   - accept → ws.send mcp_tool_confirm_response { accept: true } → backend
//     confirm_gate.resolve_confirmation 唤醒 capability handler · 真 call_tool
//   - reject → 同上 · accept: false · backend 抛 ToolConfirmationRejected ·
//     handler 捕获后返"已取消"给 LLM
//   - 关闭 modal(setMcpConfirmRequest(null))由 sendMcpToolConfirmResponse 内部
//     调 · 用户点按钮后立即关 · 不允许 ESC 关(防误关绕过)。
//
// 不复制 NotificationToast pattern · 它是 stack 推送式;本 modal 是同步 blocking
// 决策 · 风格更像 ActivityPermissionModal(全屏遮罩 + 中央对话框)。
import { useAppStore } from '../store';
import { useAppApi } from '../contexts/appApi';

export default function MCPConfirmModal() {
  // 2026-06-15 batch 2 [confirm 边界] · 读队首 · 并发多 confirm 不互相覆盖
  const queue = useAppStore((s) => s.mcpConfirmQueue);
  const req = queue[0];
  const remaining = queue.length;
  const api = useAppApi();

  if (!req) return null;

  const accept = () => {
    api.sendMcpToolConfirmResponse(req.request_id, true);
  };
  const reject = () => {
    api.sendMcpToolConfirmResponse(req.request_id, false);
  };

  return (
    <div
      className="fixed inset-0 z-[1000] flex items-center justify-center"
      style={{ background: 'rgba(0, 0, 0, 0.55)' }}
    >
      <div
        className="rounded-lg p-5 w-[520px] max-h-[80vh] overflow-y-auto shadow-2xl"
        style={{
          background: 'var(--color-bg-surface)',
          border: '1px solid var(--color-border)',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2 mb-3">
          <span className="text-2xl">⚠️</span>
          <h2 className="text-base font-medium flex-1"
            style={{ color: 'var(--color-text-primary)' }}>
            确认调用工具
          </h2>
          {remaining > 1 && (
            <span className="text-[10px] px-2 py-0.5 rounded"
              style={{
                background: 'var(--color-bg-elevated)',
                color: 'var(--color-text-secondary)',
              }}>
              队列 +{remaining - 1}
            </span>
          )}
        </div>
        <p className="text-xs mb-3"
          style={{ color: 'var(--color-text-secondary)' }}>
          LLM 想调用一个标记为危险操作的工具(写入 / 删除 / 发布类)。
          确认前请检查参数,避免误删 / 误发。
        </p>
        <div className="rounded-md px-3 py-2 mb-3 text-xs"
          style={{
            background: 'var(--color-bg-input)',
            border: '1px solid var(--color-border-subtle)',
          }}>
          <div className="mb-1">
            <span style={{ color: 'var(--color-text-secondary)' }}>
              Server:
            </span>{' '}
            <span className="font-mono"
              style={{ color: 'var(--color-text-primary)' }}>
              {req.server_name}
            </span>
          </div>
          <div className="mb-1">
            <span style={{ color: 'var(--color-text-secondary)' }}>
              Tool:
            </span>{' '}
            <span className="font-mono"
              style={{ color: 'var(--color-text-primary)' }}>
              {req.tool_name}
            </span>
          </div>
        </div>

        <div className="mb-1 text-[11px]"
          style={{ color: 'var(--color-text-secondary)' }}>
          参数预览(截断):
        </div>
        <pre
          className="rounded-md px-3 py-2 mb-4 text-[11px] font-mono whitespace-pre-wrap break-all"
          style={{
            background: 'var(--color-bg-input)',
            border: '1px solid var(--color-border-subtle)',
            color: 'var(--color-text-primary)',
            maxHeight: 200,
            overflow: 'auto',
          }}
        >
          {req.args_preview || '(无参数)'}
        </pre>

        <p className="text-[10px] mb-4"
          style={{ color: 'var(--color-text-secondary)' }}>
          未在 120 秒内确认将自动取消。
        </p>

        <div className="flex justify-end gap-2">
          <button
            type="button" onClick={reject}
            className="text-xs px-4 py-1.5 rounded-md"
            style={{
              background: 'var(--color-bg-elevated)',
              color: 'var(--color-text-primary)',
            }}
          >
            取消
          </button>
          <button
            type="button" onClick={accept}
            className="text-xs px-4 py-1.5 rounded-md"
            style={{ background: 'rgb(239, 68, 68)', color: '#fff' }}
          >
            确认执行
          </button>
        </div>
      </div>
    </div>
  );
}
