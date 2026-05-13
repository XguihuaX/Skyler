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
  ChevronDown,
  ChevronRight,
  RefreshCw,
  XCircle,
  AlertCircle,
  Key,
  Plus,
  Trash2,
} from 'lucide-react';
import {
  deleteMCPServer,
  fetchMCPClients,
  fetchMCPCredentials,
  setMCPClientEnabled,
  setMCPCredentials,
  setMCPToolEnabled,
  type MCPClientCreatePayload,
  type MCPClientCreateResponse,
  type MCPClientStatus,
  type MCPToolStatus,
} from '../lib/mcp_clients';
import AddMCPServerForm from './extensions/AddMCPServerForm';

interface ExtensionsSectionProps {
  showToast: (text: string) => void;
}

export default function ExtensionsSection({ showToast }: ExtensionsSectionProps) {
  const [clients, setClients] = useState<MCPClientStatus[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState<string | null>(null);
  const [toggling, setToggling] = useState<string | null>(null);
  const [credModalFor, setCredModalFor] = useState<MCPClientStatus | null>(null);
  // UX-001：accordion expand state per server name + per-tool toggle 进行中标记
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [toolToggling, setToolToggling] = useState<string | null>(null);
  // Stage 2.1.2: add server modal 显示控制 + delete 确认对话框 + delete 进行中
  const [showAddForm, setShowAddForm] = useState(false);
  const [deleteConfirmFor, setDeleteConfirmFor] = useState<MCPClientStatus | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);

  const toggleExpand = (name: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  };

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

  // UX-001：单 tool toggle。乐观更新（不等 refetch）+ 失败回滚 + 全量 refresh
  const onToolToggle = async (
    server: MCPClientStatus, tool: MCPToolStatus, next: boolean,
  ) => {
    const key = `${server.name}::${tool.name}`;
    setToolToggling(key);
    // 乐观更新（立即反馈）
    setClients((prev) => prev.map((c) => c.name !== server.name ? c : {
      ...c,
      tools: c.tools.map((t) => t.name === tool.name ? { ...t, enabled: next } : t),
      tool_count: next ? c.tool_count + 1 : Math.max(0, c.tool_count - 1),
    }));
    try {
      await setMCPToolEnabled(server.name, tool.name, next);
      // 后端权威值
      await refresh();
    } catch (e) {
      showToast(`tool 操作失败：${(e as Error).message}`);
      await refresh();
    } finally {
      setToolToggling(null);
    }
  };

  // Stage 2.1.2: POST 成功后回调
  //
  // 流程:
  //   1. refresh 列表(新 server 应出现)
  //   2. 提取 env 里的 ${VAR_NAME} → envPlaceholders;非空 → 合成
  //      synthetic MCPClientStatus 打开 CredentialsModal 让用户填 token
  //   3. 否则只 toast + close form
  //
  // connect 失败时(response.error 非空)backend 仍返 201,server 已写入 yaml
  // + in-memory;用户在 toast 看到失败原因后可点 toggle 重试或 Delete 删掉。
  const onAddSuccess = (
    response: MCPClientCreateResponse,
    envPlaceholders: string[],
    payload: MCPClientCreatePayload,
  ) => {
    setShowAddForm(false);
    void refresh();

    if (response.error) {
      showToast(`${response.name} 已添加但连接失败:${response.error}`);
    } else if (response.connected) {
      showToast(`${response.name} 已添加并连接(${response.tool_count} 个 tools)`);
    } else {
      showToast(`${response.name} 已添加(未启用)`);
    }

    if (envPlaceholders.length > 0) {
      // 合成 minimal MCPClientStatus:CredentialsModal 只读 ``server.name`` +
      // ``server.env_required``。其他字段给合理默认避免类型抱怨。
      const synthetic: MCPClientStatus = {
        name: response.name,
        description: payload.description ?? '',
        enabled: response.enabled,
        connected: response.connected,
        transport: response.transport,
        tool_count: response.tool_count,
        expose_via_server: payload.expose_via_skyler_server ?? true,
        last_error: response.error,
        env_required: envPlaceholders,
        missing_credentials: envPlaceholders,
        tools: [],
      };
      setCredModalFor(synthetic);
    }
  };

  const onDeleteConfirm = async (server: MCPClientStatus) => {
    setDeleting(server.name);
    setDeleteConfirmFor(null);
    try {
      await deleteMCPServer(server.name);
      showToast(`${server.name} 已删除`);
      await refresh();
    } catch (e) {
      // 500 yaml-prune 失败 → backend detail 含"retry DELETE";其他错误也透传
      showToast(`删除失败:${(e as Error).message}`);
      await refresh();
    } finally {
      setDeleting(null);
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
            isExpanded={expanded.has(c.name)}
            onExpand={() => toggleExpand(c.name)}
            onToggle={onToggle}
            onConfigure={() => setCredModalFor(c)}
            onToolToggle={onToolToggle}
            toolToggling={toolToggling}
            onDelete={() => setDeleteConfirmFor(c)}
            deleteDisabled={deleting === c.name}
          />
        ))}
        <div className="flex justify-between items-center pt-1">
          <button
            type="button"
            onClick={() => setShowAddForm(true)}
            className="text-[11px] inline-flex items-center gap-1 px-2 py-1 rounded hover:opacity-80"
            style={{
              background: 'var(--color-accent)',
              color: 'var(--color-bubble-user-text)',
            }}
            title="新增一个 MCP server entry"
          >
            <Plus size={11} />
            新增 server
          </button>
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
      {showAddForm && (
        <AddMCPServerForm
          onClose={() => setShowAddForm(false)}
          onSuccess={onAddSuccess}
        />
      )}
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
      {deleteConfirmFor && (
        <DeleteConfirmDialog
          server={deleteConfirmFor}
          onCancel={() => setDeleteConfirmFor(null)}
          onConfirm={() => void onDeleteConfirm(deleteConfirmFor)}
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
  isExpanded: boolean;
  onExpand: () => void;
  onToggle: (c: MCPClientStatus, next: boolean) => void;
  onConfigure: () => void;
  onToolToggle: (server: MCPClientStatus, tool: MCPToolStatus, next: boolean) => void;
  toolToggling: string | null;
  // Stage 2.1.2:
  onDelete: () => void;
  deleteDisabled: boolean;
}

function ClientRow({
  client,
  disabled,
  isExpanded,
  onExpand,
  onToggle,
  onConfigure,
  onToolToggle,
  toolToggling,
  onDelete,
  deleteDisabled,
}: ClientRowProps) {
  const missing = client.missing_credentials.length > 0;
  const status = badgeFor(client);
  const toggleDisabled = disabled || missing;
  // UX-001：connected server 才显示 tool 列表（disconnected 时 tools=[]，
  // caret 仍渲染但点开"暂无 tool 列表，先启用此 server"占位）
  const expandable = client.tools.length > 0 || client.connected;

  return (
    <div
      className="py-2"
      style={{ borderTop: '1px solid var(--color-border)' }}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-0.5">
            {expandable ? (
              <button
                type="button"
                onClick={onExpand}
                className="p-0.5 -ml-1 rounded hover:opacity-80"
                aria-label={isExpanded ? '折叠' : '展开'}
                style={{ color: 'var(--color-text-secondary)' }}
              >
                {isExpanded
                  ? <ChevronDown size={12} />
                  : <ChevronRight size={12} />}
              </button>
            ) : (
              <span style={{ width: 16, display: 'inline-block' }} />
            )}
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
            {/* UX-001：tool count 角标（独立于 status badge 里的 "running · N tools"）*/}
            {client.tools.length > 0 && (
              <span
                className="text-[10px] px-1.5 py-0.5 rounded"
                style={{
                  background: 'var(--color-bg-elevated)',
                  color: 'var(--color-text-secondary)',
                }}
              >
                {client.tool_count}/{client.tools.length} cap
              </span>
            )}
          </div>
          <div
            className="text-xs"
            style={{ color: 'var(--color-text-secondary)', marginLeft: 16 }}
          >
            {client.description || '(无描述)'}
          </div>
          {client.last_error && (
            <div
              className="text-[10px] mt-1"
              style={{ color: 'rgb(244, 63, 94)', marginLeft: 16 }}
            >
              错误：{client.last_error}
            </div>
          )}
          {missing && (
            <div
              className="text-[10px] mt-1"
              style={{ color: 'var(--color-text-secondary)', marginLeft: 16 }}
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
          {/* Stage 2.1.2: 删除按钮(in-flight tool call 由 backend disable 路径
              先 disconnect 再 prune yaml,无 race) */}
          <button
            type="button"
            onClick={onDelete}
            disabled={deleteDisabled}
            className="text-[10px] inline-flex items-center gap-1 px-2 py-0.5 rounded hover:opacity-80 disabled:opacity-50"
            style={{
              background: 'var(--color-bg-elevated)',
              color: 'rgb(244, 63, 94)',
              border: '1px solid var(--color-border)',
            }}
            title="删除该 server entry"
          >
            <Trash2 size={10} />
            删除
          </button>
        </div>
      </div>
      {/*
        hotfix-6 Part 1: 这是 ClientRow 内**唯一**渲染 tool 列表的位置。
        以前 audit 怀疑还有别的路径 — 排查结论是无（line 263 是 caret icon、
        line 284-294 是 "X/Y cap" 文本 badge，不是 tool 列表）。本块整体只
        在 isExpanded=true 时渲染；isExpanded 来自 useState<Set<string>>(new Set())
        初始化的 expanded Set，因此首次渲染恒为 false（折叠）。**不要**把这
        段从 isExpanded gate 里挪出去 —— 否则会回归到"server 默认全展开 +
        所有 capability 平铺一长串"的 UX-001 之前形态。
      */}
      {isExpanded ? (
        <ToolList
          client={client}
          toolToggling={toolToggling}
          onToolToggle={onToolToggle}
        />
      ) : null}
    </div>
  );
}


// ---------------------------------------------------------------------------
// ToolList — accordion 展开后的 capability 列表块。
//   抽出 sub-component 让"渲染 tool 列表"这个 side effect 集中在一个组件里，
//   防止未来 refactor 时不小心把 map 路径泄露到 isExpanded gate 外。
// ---------------------------------------------------------------------------

function ToolList({
  client,
  toolToggling,
  onToolToggle,
}: {
  client: MCPClientStatus;
  toolToggling: string | null;
  onToolToggle: (server: MCPClientStatus, tool: MCPToolStatus, next: boolean) => void;
}) {
  return (
    <div
      className="mt-2"
      style={{
        marginLeft: 16,
        paddingLeft: 8,
        borderLeft: '1px dashed var(--color-border)',
      }}
    >
      {client.tools.length === 0 ? (
        <div
          className="text-[11px] py-1"
          style={{ color: 'var(--color-text-secondary)' }}
        >
          （未连接或暂无 capability —— 先启用本 server）
        </div>
      ) : (
        client.tools.map((t) => (
          <ToolRow
            key={t.name}
            server={client}
            tool={t}
            disabled={!client.enabled || toolToggling === `${client.name}::${t.name}`}
            onChange={(next) => onToolToggle(client, t, next)}
          />
        ))
      )}
    </div>
  );
}


// ---------------------------------------------------------------------------
// ToolRow（UX-001：accordion 展开后的单 capability 行）
// ---------------------------------------------------------------------------

function ToolRow({
  server,
  tool,
  disabled,
  onChange,
}: {
  server: MCPClientStatus;
  tool: MCPToolStatus;
  disabled: boolean;
  onChange: (next: boolean) => void;
}) {
  // UX-001：server 关时 tool 行展示但 toggle 禁用 + "随 server 关" 提示
  const dimmed = !server.enabled;
  return (
    <div
      className="flex items-center justify-between py-1"
    >
      <div className="min-w-0 pr-2">
        <div
          className="text-xs font-mono truncate"
          style={{
            color: dimmed
              ? 'var(--color-text-secondary)'
              : 'var(--color-text-primary)',
          }}
        >
          {tool.name}
        </div>
        {tool.description && (
          <div
            className="text-[10px] truncate"
            style={{ color: 'var(--color-text-secondary)' }}
          >
            {tool.description}
          </div>
        )}
      </div>
      <ToggleSmall
        value={tool.enabled && server.enabled}
        disabled={disabled}
        onChange={onChange}
      />
    </div>
  );
}


function ToggleSmall({
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
      className="relative w-8 h-4 rounded-full transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
      style={{ background: value ? 'var(--color-accent)' : 'var(--color-bg-elevated)' }}
    >
      <span
        className={`absolute top-0.5 w-3 h-3 rounded-full bg-white shadow transition-all ${
          value ? 'left-[18px]' : 'left-0.5'
        }`}
      />
    </button>
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


// ---------------------------------------------------------------------------
// Stage 2.1.2: DeleteConfirmDialog
//
// 与 native ``confirm()`` 区分:阻塞式 confirm 在 Tauri WebView 体验不佳
// 而且无法贴主题色。styled modal 复用 CredentialsModal 的 fixed-overlay
// 形态,保持视觉一致。
// ---------------------------------------------------------------------------

interface DeleteConfirmDialogProps {
  server: MCPClientStatus;
  onCancel: () => void;
  onConfirm: () => void;
}

function DeleteConfirmDialog({
  server,
  onCancel,
  onConfirm,
}: DeleteConfirmDialogProps) {
  return (
    <div
      className="fixed inset-0 z-[55] flex items-center justify-center"
      style={{
        background: 'color-mix(in srgb, var(--color-bg-base) 60%, transparent)',
      }}
      onClick={onCancel}
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
          删除 {server.name}?
        </h4>
        <p
          className="text-xs mb-1"
          style={{ color: 'var(--color-text-secondary)' }}
        >
          该 server 的所有 in-flight tool call 会断,所有已注册 capability 将从
          LLM 工具列表中移除。
        </p>
        <p
          className="text-xs mb-4"
          style={{ color: 'var(--color-text-secondary)' }}
        >
          config.yaml entry + mcp_credentials / mcp_tool_state DB 痕迹都会清除。
          后续可以重新添加同名 server(不会复用旧凭证)。
        </p>
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="px-3 py-1.5 text-xs rounded-md transition"
            style={{
              background: 'var(--color-bg-elevated)',
              color: 'var(--color-text-primary)',
            }}
          >
            取消
          </button>
          <button
            type="button"
            onClick={onConfirm}
            className="px-3 py-1.5 text-xs rounded-md transition"
            style={{
              background: 'rgb(244, 63, 94)',
              color: 'white',
            }}
          >
            确认删除
          </button>
        </div>
      </div>
    </div>
  );
}
