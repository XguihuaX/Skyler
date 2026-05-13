/**
 * Stage 2.1.2 — 新增 MCP server 表单(modal)。
 *
 * Modal vs inline 选择:沿用 CredentialsModal 的 fixed-overlay 形态——
 * inline 展开会把整个 server 列表往下推一两屏,modal 不扰动现有视觉。
 *
 * Transport conditional 字段:
 *   - stdio  → command (必填) + args (string[]) + env (key-value pairs)
 *   - http   → url (必填) + env (key-value pairs)
 *
 * env 用 key-value pairs UI 而非 JSON editor:配 secrets 是平常 90% 场景,
 * 用户输 ``BRAVE_API_KEY=${BRAVE_API_KEY}`` 比写 JSON 直观。
 *
 * args 用"每行一个 input + [+]/[×]"的列表 UI:同上,贴近用户对命令行
 * 参数的心智模型。
 *
 * Submit 成功流程:
 *   1. POST → 201 / 200(connect 失败但 yaml 已写时也是 OK)
 *   2. parent ``onSuccess(response, envPlaceholders)`` 回调:
 *      - parent 拿 envPlaceholders 决定是否打开 CredentialsModal
 *      - parent 决定 toast 文案("已连接" vs "连接失败:{error}")
 *   3. 表单本身只关 modal,不主动 refresh / toast
 */
import { useState } from 'react';
import { Plus, X } from 'lucide-react';
import {
  addMCPServer,
  extractEnvPlaceholders,
  type MCPClientCreatePayload,
  type MCPClientCreateResponse,
} from '../../lib/mcp_clients';

interface AddMCPServerFormProps {
  onClose: () => void;
  onSuccess: (
    response: MCPClientCreateResponse,
    envPlaceholders: string[],
    payload: MCPClientCreatePayload,
  ) => void;
}

interface KVPair {
  key: string;
  value: string;
}

export default function AddMCPServerForm({
  onClose,
  onSuccess,
}: AddMCPServerFormProps) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [transport, setTransport] = useState<'stdio' | 'http'>('stdio');
  const [command, setCommand] = useState('');
  const [args, setArgs] = useState<string[]>(['']);
  const [url, setUrl] = useState('');
  const [envPairs, setEnvPairs] = useState<KVPair[]>([{ key: '', value: '' }]);
  const [enabled, setEnabled] = useState(true);

  const [submitting, setSubmitting] = useState(false);
  // server-side error inline 显示(409 / 422 / 500)
  const [submitError, setSubmitError] = useState<string | null>(null);

  // 客户端最基础的"submit-enable" 判定 —— 真校验交给 backend(更权威)
  const canSubmit = (() => {
    if (!name.trim()) return false;
    if (transport === 'stdio' && !command.trim()) return false;
    if (transport === 'http' && !url.trim()) return false;
    return true;
  })();

  const onArgChange = (idx: number, val: string) => {
    setArgs((prev) => prev.map((a, i) => (i === idx ? val : a)));
  };
  const onArgAdd = () => setArgs((prev) => [...prev, '']);
  const onArgRemove = (idx: number) => {
    setArgs((prev) =>
      prev.length === 1 ? [''] : prev.filter((_, i) => i !== idx),
    );
  };

  const onEnvChange = (idx: number, field: 'key' | 'value', val: string) => {
    setEnvPairs((prev) =>
      prev.map((p, i) => (i === idx ? { ...p, [field]: val } : p)),
    );
  };
  const onEnvAdd = () =>
    setEnvPairs((prev) => [...prev, { key: '', value: '' }]);
  const onEnvRemove = (idx: number) => {
    setEnvPairs((prev) =>
      prev.length === 1 ? [{ key: '', value: '' }] : prev.filter((_, i) => i !== idx),
    );
  };

  const onSubmit = async () => {
    if (!canSubmit || submitting) return;
    setSubmitError(null);
    setSubmitting(true);

    const cleanedArgs = args.map((a) => a.trim()).filter((a) => a !== '');
    const cleanedEnv: Record<string, string> = {};
    for (const { key, value } of envPairs) {
      const k = key.trim();
      if (k !== '') cleanedEnv[k] = value;
    }

    const payload: MCPClientCreatePayload = {
      name: name.trim(),
      description: description.trim() || undefined,
      transport,
      enabled,
    };
    if (transport === 'stdio') {
      payload.command = command.trim();
      if (cleanedArgs.length > 0) payload.args = cleanedArgs;
      if (Object.keys(cleanedEnv).length > 0) payload.env = cleanedEnv;
    } else {
      payload.url = url.trim();
      if (Object.keys(cleanedEnv).length > 0) payload.env = cleanedEnv;
    }

    try {
      const response = await addMCPServer(payload);
      const placeholders = extractEnvPlaceholders(payload.env);
      onSuccess(response, placeholders, payload);
      // 成功后由 parent close modal(在 onSuccess 内部)
    } catch (e) {
      const err = e as Error & { status?: number };
      let msg = err.message || '提交失败';
      // 409 / 422 / 500 都走 detail 字段,backend 已经在 detail 里说人话
      if (err.status === 409) msg = `已存在同名 server:${name.trim()}`;
      setSubmitError(msg);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-[55] flex items-center justify-center"
      style={{
        background:
          'color-mix(in srgb, var(--color-bg-base) 60%, transparent)',
      }}
      onClick={onClose}
    >
      <div
        className="rounded-lg p-5 w-[460px] max-h-[85vh] overflow-y-auto shadow-2xl"
        style={{
          background: 'var(--color-bg-surface)',
          border: '1px solid var(--color-border)',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <h4
          className="text-sm font-semibold mb-3"
          style={{ color: 'var(--color-text-primary)' }}
        >
          新增 MCP server
        </h4>

        {/* name */}
        <Field label="名称" required>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="brave-search"
            className="w-full rounded-md px-2 py-1.5 text-sm focus:outline-none"
            style={fieldStyle}
            autoComplete="off"
          />
        </Field>

        {/* description */}
        <Field label="描述(可选)">
          <input
            type="text"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Web search via Brave API"
            className="w-full rounded-md px-2 py-1.5 text-sm focus:outline-none"
            style={fieldStyle}
            autoComplete="off"
          />
        </Field>

        {/* transport */}
        <Field label="Transport">
          <select
            value={transport}
            onChange={(e) => setTransport(e.target.value as 'stdio' | 'http')}
            className="w-full rounded-md px-2 py-1.5 text-sm focus:outline-none"
            style={fieldStyle}
          >
            <option value="stdio">stdio(子进程 / npx)</option>
            <option value="http">http(远程 streamable HTTP)</option>
          </select>
        </Field>

        {/* stdio fields */}
        {transport === 'stdio' && (
          <>
            <Field label="Command" required>
              <input
                type="text"
                value={command}
                onChange={(e) => setCommand(e.target.value)}
                placeholder="npx"
                className="w-full rounded-md px-2 py-1.5 text-sm focus:outline-none"
                style={fieldStyle}
                autoComplete="off"
              />
            </Field>

            <Field label="Args(每行一项,从前到后传入命令)">
              <div className="space-y-1">
                {args.map((a, i) => (
                  <div key={i} className="flex items-center gap-1">
                    <input
                      type="text"
                      value={a}
                      onChange={(e) => onArgChange(i, e.target.value)}
                      placeholder={
                        i === 0 ? '-y' : i === 1
                          ? '@modelcontextprotocol/server-brave-search'
                          : ''
                      }
                      className="flex-1 rounded-md px-2 py-1.5 text-sm focus:outline-none"
                      style={fieldStyle}
                      autoComplete="off"
                    />
                    <RowBtn
                      onClick={() => onArgRemove(i)}
                      title="删除这一项"
                    >
                      <X size={12} />
                    </RowBtn>
                  </div>
                ))}
                <button
                  type="button"
                  onClick={onArgAdd}
                  className="text-[11px] inline-flex items-center gap-1 px-2 py-1 rounded hover:opacity-80"
                  style={{
                    color: 'var(--color-text-secondary)',
                    border: '1px dashed var(--color-border)',
                  }}
                >
                  <Plus size={11} />
                  添加一项
                </button>
              </div>
            </Field>
          </>
        )}

        {/* http fields */}
        {transport === 'http' && (
          <Field label="URL" required>
            <input
              type="text"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="http://localhost:3000/mcp"
              className="w-full rounded-md px-2 py-1.5 text-sm focus:outline-none"
              style={fieldStyle}
              autoComplete="off"
            />
          </Field>
        )}

        {/* env */}
        <Field
          label="Env(可选)"
          hint="Secrets 用 ${VAR_NAME} 模板,不要写明文 token。提交后会弹出凭证 modal 填真实值。"
        >
          <div className="space-y-1">
            {envPairs.map((p, i) => (
              <div key={i} className="flex items-center gap-1">
                <input
                  type="text"
                  value={p.key}
                  onChange={(e) => onEnvChange(i, 'key', e.target.value)}
                  placeholder="BRAVE_API_KEY"
                  className="flex-1 rounded-md px-2 py-1.5 text-sm focus:outline-none font-mono"
                  style={fieldStyle}
                  autoComplete="off"
                />
                <span style={{ color: 'var(--color-text-secondary)' }}>=</span>
                <input
                  type="text"
                  value={p.value}
                  onChange={(e) => onEnvChange(i, 'value', e.target.value)}
                  placeholder="${BRAVE_API_KEY}"
                  className="flex-1 rounded-md px-2 py-1.5 text-sm focus:outline-none font-mono"
                  style={fieldStyle}
                  autoComplete="off"
                />
                <RowBtn onClick={() => onEnvRemove(i)} title="删除这一项">
                  <X size={12} />
                </RowBtn>
              </div>
            ))}
            <button
              type="button"
              onClick={onEnvAdd}
              className="text-[11px] inline-flex items-center gap-1 px-2 py-1 rounded hover:opacity-80"
              style={{
                color: 'var(--color-text-secondary)',
                border: '1px dashed var(--color-border)',
              }}
            >
              <Plus size={11} />
              添加一项
            </button>
          </div>
        </Field>

        {/* enabled */}
        <label className="flex items-center gap-2 my-3 cursor-pointer">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(e) => setEnabled(e.target.checked)}
            className="cursor-pointer"
          />
          <span
            className="text-xs"
            style={{ color: 'var(--color-text-primary)' }}
          >
            启用 server(立即尝试连接)
          </span>
        </label>

        {submitError && (
          <div
            className="text-xs px-2 py-1.5 rounded my-2"
            style={{
              background: 'rgba(244, 63, 94, 0.10)',
              border: '1px solid rgba(244, 63, 94, 0.30)',
              color: 'rgb(244, 63, 94)',
            }}
          >
            {submitError}
          </div>
        )}

        <div className="flex justify-end gap-2 pt-3">
          <button
            type="button"
            onClick={onClose}
            disabled={submitting}
            className="px-3 py-1.5 text-xs rounded-md transition disabled:opacity-50"
            style={{
              background: 'var(--color-bg-elevated)',
              color: 'var(--color-text-primary)',
            }}
          >
            取消
          </button>
          <button
            type="button"
            onClick={() => void onSubmit()}
            disabled={!canSubmit || submitting}
            className="px-3 py-1.5 text-xs rounded-md transition disabled:opacity-50"
            style={{
              background: 'var(--color-accent)',
              color: 'var(--color-bubble-user-text)',
            }}
          >
            {submitting ? '提交中…' : '添加'}
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Local sub-components (private; not exported)
// ---------------------------------------------------------------------------

const fieldStyle: React.CSSProperties = {
  background: 'var(--color-bg-input)',
  border: '1px solid var(--color-border)',
  color: 'var(--color-text-primary)',
};

function Field({
  label,
  required,
  hint,
  children,
}: {
  label: string;
  required?: boolean;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="mb-3">
      <label
        className="block text-xs mb-1"
        style={{ color: 'var(--color-text-primary)' }}
      >
        {label}
        {required && (
          <span style={{ color: 'rgb(244, 63, 94)' }}> *</span>
        )}
      </label>
      {children}
      {hint && (
        <div
          className="text-[10px] mt-1"
          style={{ color: 'var(--color-text-secondary)' }}
        >
          {hint}
        </div>
      )}
    </div>
  );
}

function RowBtn({
  onClick,
  title,
  children,
}: {
  onClick: () => void;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      className="p-1 rounded hover:opacity-80"
      style={{
        color: 'var(--color-text-secondary)',
        border: '1px solid var(--color-border)',
        background: 'var(--color-bg-elevated)',
      }}
    >
      {children}
    </button>
  );
}
