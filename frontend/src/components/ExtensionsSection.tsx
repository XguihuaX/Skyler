/**
 * v3.5 chunk 7 — SettingsPanel [扩展能力] section。
 *
 * 列出 config.yaml ``mcp_clients`` 配置的所有外部 MCP server，提供：
 *  - 启用 / 禁用 toggle（持久化到 mcp_client_state 表，重启沿用）
 *  - 状态徽章：🟢 running / 🔴 error / ⚪ disabled
 *  - 凭证未配置时 toggle disabled + 灰字提示
 *  - [配置凭证] modal：列出每个 env_required key 的 password input
 *
 * 复用 chunk 1.5 backend/mcp/client.py + 本 chunk 新增的 routes/mcp_api.py
 * enable/credentials endpoints；不重建任何 MCP 基础设施。
 */
import { useCallback, useEffect, useState } from 'react';
import {
  CheckCircle2,
  RefreshCw,
  XCircle,
  AlertCircle,
  Key,
} from 'lucide-react';
import {
  fetchMCPClients,
  fetchMCPCredentials,
  setMCPClientEnabled,
  setMCPCredentials,
  type MCPClientStatus,
} from '../lib/mcp_clients';

interface ExtensionsSectionProps {
  showToast: (text: string) => void;
}

export default function ExtensionsSection({ showToast }: ExtensionsSectionProps) {
  const [clients, setClients] = useState<MCPClientStatus[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState<string | null>(null);
  const [toggling, setToggling] = useState<string | null>(null);
  const [credModalFor, setCredModalFor] = useState<MCPClientStatus | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchMCPClients();
      setClients(data.clients);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const onToggle = async (c: MCPClientStatus, next: boolean) => {
    setToggling(c.name);
    try {
      const r = await setMCPClientEnabled(c.name, next);
      if (next && r.connected) {
        showToast(`${c.name} 已启用（${r.tool_count} 个 tools）`);
      } else if (!next) {
        showToast(`${c.name} 已禁用`);
      } else if (next && !r.connected) {
        showToast(`${c.name} 已启用但未连接：${r.detail || '未知错误'}`);
      }
      await refresh();
    } catch (e) {
      showToast(`操作失败：${(e as Error).message}`);
      await refresh();
    } finally {
      setToggling(null);
    }
  };

  return (
    <>
      <Section title="扩展能力 (MCP)">
        {loading && clients.length === 0 && (
          <div
            className="text-xs py-2"
            style={{ color: 'var(--color-text-secondary)' }}
          >
            加载中…
          </div>
        )}
        {error && (
          <div
            className="text-xs py-2"
            style={{ color: 'var(--color-text-secondary)' }}
          >
            列表加载失败：{error}
          </div>
        )}
        {clients.length === 0 && !loading && !error && (
          <div
            className="text-xs py-2"
            style={{ color: 'var(--color-text-secondary)' }}
          >
            未在 config.yaml 配置任何 mcp_clients。
          </div>
        )}
        {clients.map((c) => (
          <ClientRow
            key={c.name}
            client={c}
            disabled={toggling === c.name}
            onToggle={onToggle}
            onConfigure={() => setCredModalFor(c)}
          />
        ))}
        <div className="flex justify-end pt-1">
          <button
            type="button"
            onClick={() => void refresh()}
            disabled={loading}
            className="text-[10px] inline-flex items-center gap-1 px-1.5 py-0.5 rounded hover:opacity-80 disabled:opacity-50"
            style={{ color: 'var(--color-text-secondary)' }}
            title="重新拉取 server 状态"
          >
            <RefreshCw size={10} className={loading ? 'animate-spin' : ''} />
            刷新状态
          </button>
        </div>
      </Section>
      {credModalFor && (
        <CredentialsModal
          server={credModalFor}
          onClose={() => setCredModalFor(null)}
          onSaved={() => {
            setCredModalFor(null);
            void refresh();
            showToast(`${credModalFor.name} 凭证已保存`);
          }}
          showToast={showToast}
        />
      )}
    </>
  );
}


// ---------------------------------------------------------------------------
// Section wrapper（与 SettingsPanel 内 Section 同模板，避免依赖那边私有函数）
// ---------------------------------------------------------------------------

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-4">
      <h3
        className="text-sm font-semibold mb-2"
        style={{ color: 'var(--color-text-primary)' }}
      >
        {title}
      </h3>
      <div
        className="rounded-md px-3 py-1"
        style={{
          background: 'var(--color-bg-surface)',
          border: '1px solid var(--color-border)',
        }}
      >
        {children}
      </div>
    </section>
  );
}


// ---------------------------------------------------------------------------
// ClientRow
// ---------------------------------------------------------------------------

interface ClientRowProps {
  client: MCPClientStatus;
  disabled: boolean;
  onToggle: (c: MCPClientStatus, next: boolean) => void;
  onConfigure: () => void;
}

function ClientRow({ client, disabled, onToggle, onConfigure }: ClientRowProps) {
  const missing = client.missing_credentials.length > 0;
  const status = badgeFor(client);
  const toggleDisabled = disabled || missing;

  return (
    <div
      className="py-2"
      style={{ borderTop: '1px solid var(--color-border)' }}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-0.5">
            <span
              className="text-sm font-medium"
              style={{ color: 'var(--color-text-primary)' }}
            >
              {client.name}
            </span>
            <span
              className="text-[10px] inline-flex items-center gap-1 px-1.5 py-0.5 rounded"
              style={status.style}
            >
              {status.icon}
              {status.label}
            </span>
          </div>
          <div
            className="text-xs"
            style={{ color: 'var(--color-text-secondary)' }}
          >
            {client.description || '(无描述)'}
          </div>
          {client.last_error && (
            <div
              className="text-[10px] mt-1"
              style={{ color: 'rgb(244, 63, 94)' }}
            >
              错误：{client.last_error}
            </div>
          )}
          {missing && (
            <div
              className="text-[10px] mt-1"
              style={{ color: 'var(--color-text-secondary)' }}
            >
              请先配置：{client.missing_credentials.join(', ')}
            </div>
          )}
        </div>
        <div className="flex flex-col items-end gap-1 flex-shrink-0">
          <Toggle
            value={client.enabled}
            disabled={toggleDisabled}
            onChange={(v) => onToggle(client, v)}
          />
          {client.env_required.length > 0 && (
            <button
              type="button"
              onClick={onConfigure}
              className="text-[10px] inline-flex items-center gap-1 px-2 py-0.5 rounded hover:opacity-80"
              style={{
                background: 'var(--color-bg-elevated)',
                color: 'var(--color-text-primary)',
                border: '1px solid var(--color-border)',
              }}
            >
              <Key size={10} />
              配置凭证
            </button>
          )}
        </div>
      </div>
    </div>
  );
}


function badgeFor(c: MCPClientStatus) {
  if (c.connected) {
    return {
      icon: <CheckCircle2 size={10} />,
      label: `running · ${c.tool_count} tools`,
      style: { background: 'var(--color-accent)', color: 'var(--color-bubble-ai-text)' },
    };
  }
  if (c.last_error) {
    return {
      icon: <XCircle size={10} />,
      label: 'error',
      style: { background: 'rgba(244, 63, 94, 0.15)', color: 'rgb(244, 63, 94)' },
    };
  }
  if (c.missing_credentials.length > 0) {
    return {
      icon: <AlertCircle size={10} />,
      label: '需配置凭证',
      style: { background: 'var(--color-bg-elevated)', color: 'var(--color-text-secondary)' },
    };
  }
  return {
    icon: <span style={{ width: 10, height: 10, display: 'inline-block' }} />,
    label: 'disabled',
    style: { background: 'var(--color-bg-elevated)', color: 'var(--color-text-secondary)' },
  };
}


// ---------------------------------------------------------------------------
// Toggle（本地拷贝，避免依赖 SettingsPanel 内私有 Toggle）
// ---------------------------------------------------------------------------

function Toggle({
  value,
  disabled,
  onChange,
}: {
  value: boolean;
  disabled: boolean;
  onChange: (next: boolean) => void;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={value}
      disabled={disabled}
      onClick={() => onChange(!value)}
      className="relative w-11 h-6 rounded-full transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
      style={{ background: value ? 'var(--color-accent)' : 'var(--color-bg-elevated)' }}
    >
      <span
        className={`absolute top-0.5 w-5 h-5 rounded-full bg-white shadow transition-all ${
          value ? 'left-[22px]' : 'left-0.5'
        }`}
      />
    </button>
  );
}


// ---------------------------------------------------------------------------
// CredentialsModal
// ---------------------------------------------------------------------------

interface CredentialsModalProps {
  server: MCPClientStatus;
  onClose: () => void;
  onSaved: () => void;
  showToast: (text: string) => void;
}

function CredentialsModal({ server, onClose, onSaved, showToast }: CredentialsModalProps) {
  // 初始 values：env_required 中每个 key 一个空 string
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(server.env_required.map((k) => [k, ''])),
  );
  const [configuredKeys, setConfiguredKeys] = useState<Set<string>>(new Set());
  const [submitting, setSubmitting] = useState(false);

  // mount 时拉一份已配置 key 列表（不返 value，只显示 ✓ 状态）
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const data = await fetchMCPCredentials(server.name);
        if (cancelled) return;
        setConfiguredKeys(new Set(data.keys.filter((k) => k.configured).map((k) => k.key_name)));
      } catch (e) {
        console.warn('[Extensions] fetch credentials failed:', e);
      }
    })();
    return () => { cancelled = true; };
  }, [server.name]);

  const onSubmit = async () => {
    // 只发非空 input —— 空 input 不覆盖已配置的 key
    const nonEmpty = Object.fromEntries(
      Object.entries(values).filter(([, v]) => v.trim() !== ''),
    );
    if (Object.keys(nonEmpty).length === 0) {
      showToast('请至少输入一个凭证值');
      return;
    }
    setSubmitting(true);
    try {
      await setMCPCredentials(server.name, nonEmpty);
      onSaved();
    } catch (e) {
      showToast(`保存失败：${(e as Error).message}`);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-[55] flex items-center justify-center"
      style={{ background: 'color-mix(in srgb, var(--color-bg-base) 60%, transparent)' }}
      onClick={onClose}
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
          className="text-sm font-semibold mb-3"
          style={{ color: 'var(--color-text-primary)' }}
        >
          配置 {server.name} 凭证
        </h4>
        <p
          className="text-xs mb-3"
          style={{ color: 'var(--color-text-secondary)' }}
        >
          凭证将以明文存入本地 SQLite（``mcp_credentials`` 表），不会写入 .env 文件。
          已配置的字段会显示 ✓；输入空值不会覆盖现有值。
        </p>
        <div className="space-y-2">
          {server.env_required.map((key) => (
            <div key={key}>
              <label
                className="flex items-center gap-1 text-xs mb-1"
                style={{ color: 'var(--color-text-primary)' }}
              >
                {key}
                {configuredKeys.has(key) && (
                  <CheckCircle2 size={12} style={{ color: 'var(--color-accent)' }} />
                )}
              </label>
              <input
                type="password"
                value={values[key] || ''}
                onChange={(e) => setValues((v) => ({ ...v, [key]: e.target.value }))}
                placeholder={
                  configuredKeys.has(key) ? '已配置（留空保持不变）' : '输入新值'
                }
                className="w-full rounded-md px-2 py-1.5 text-sm focus:outline-none"
                style={{
                  background: 'var(--color-bg-input)',
                  border: '1px solid var(--color-border)',
                  color: 'var(--color-text-primary)',
                }}
                autoComplete="off"
              />
            </div>
          ))}
        </div>
        <div className="flex justify-end gap-2 pt-4">
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
            disabled={submitting}
            className="px-3 py-1.5 text-xs rounded-md transition disabled:opacity-50"
            style={{
              background: 'var(--color-accent)',
              color: 'var(--color-bubble-user-text)',
            }}
          >
            {submitting ? '保存中…' : '保存'}
          </button>
        </div>
      </div>
    </div>
  );
}
