/**
 * v3.5 chunk 8a — macOS AppleScript 权限缺失提示弹窗。
 *
 * 由 store.activityPermissionHint 触发：后端 startup 自检发现 AppleScript
 * 调用失败时 push ``activity_permission_missing`` WS message →
 * ``useWebSocket`` 把 hint 写入 store → 本组件渲染。
 *
 * 用户点 [打开系统设置] 用 ``window.open`` 跳 ``x-apple.systempreferences:``
 * URI scheme 进 隐私与安全性 → 自动化页面。
 */
import { ShieldAlert } from 'lucide-react';
import { useAppStore } from '../store';

const SYSPREFS_AUTOMATION_URL =
  'x-apple.systempreferences:com.apple.preference.security?Privacy_Automation';

export default function ActivityPermissionModal() {
  const hint = useAppStore((s) => s.activityPermissionHint);
  const setHint = useAppStore((s) => s.setActivityPermissionHint);

  if (!hint) return null;

  const openSettings = () => {
    try {
      window.open(SYSPREFS_AUTOMATION_URL, '_blank');
    } catch {
      // Tauri webview 可能拒打开外部 URI scheme；不报错，用户手动开
    }
    setHint(null);
  };

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center"
      style={{ background: 'color-mix(in srgb, var(--color-bg-base) 60%, transparent)' }}
      onClick={() => setHint(null)}
    >
      <div
        className="rounded-lg p-5 w-96 shadow-2xl"
        style={{
          background: 'var(--color-bg-surface)',
          border: '1px solid var(--color-border)',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <h4
          className="text-sm font-semibold mb-3 flex items-center gap-1"
          style={{ color: 'var(--color-text-primary)' }}
        >
          <ShieldAlert size={14} style={{ color: 'rgb(244, 63, 94)' }} />
          需要授权 Skyler 访问系统状态
        </h4>
        <p
          className="text-xs mb-3 leading-relaxed"
          style={{ color: 'var(--color-text-secondary)' }}
        >
          {hint || (
            <>
              Skyler 想读取你当前活跃的应用和浏览器标签，以便在合适的时机找你说话。
              首次启动 macOS 会弹出一个授权弹窗，如果错过了或不小心点了「不允许」，
              你可以前往 系统设置 → 隐私与安全性 → 自动化 重新开启对 Skyler 的授权。
            </>
          )}
        </p>
        <div className="flex justify-end gap-2 pt-2">
          <button
            type="button"
            onClick={() => setHint(null)}
            className="px-3 py-1.5 text-xs rounded-md transition"
            style={{
              background: 'var(--color-bg-elevated)',
              color: 'var(--color-text-primary)',
            }}
          >
            稍后
          </button>
          <button
            type="button"
            onClick={openSettings}
            className="px-3 py-1.5 text-xs rounded-md transition"
            style={{
              background: 'var(--color-accent)',
              color: 'var(--color-bubble-user-text)',
            }}
          >
            打开系统设置
          </button>
        </div>
      </div>
    </div>
  );
}
