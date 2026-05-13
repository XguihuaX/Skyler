// v3.5 chunk 7 — frontend API client for MCP clients (status + enable + credentials).
//
// 与 lib/live2d.ts / lib/backgrounds.ts 平行。后端 single source of truth；
// 字段 drift 时立即 build error。chunk 1.5 已有 status 路径，本文件
// 补 chunk 7 新增 enable / credentials endpoints。

const BACKEND_BASE = 'http://127.0.0.1:8000';

export interface MCPToolStatus {
  name: string;
  description: string;
  enabled: boolean;
}

export interface MCPClientStatus {
  name: string;
  description: string;
  enabled: boolean;
  connected: boolean;
  transport: string;
  tool_count: number;
  expose_via_server: boolean;
  last_error: string | null;
  env_required: string[];
  missing_credentials: string[];
  // UX-001：connected server 暴露的 tool 列表 + 单 tool enabled override。
  // disconnected → []。
  tools: MCPToolStatus[];
}

export interface MCPToolEnabledResponse {
  server_name: string;
  tool_name: string;
  enabled: boolean;
  tool_count: number;
  tools: MCPToolStatus[];
}

export interface MCPClientsStatusResponse {
  clients: MCPClientStatus[];
}

export interface MCPCredentialKey {
  key_name: string;
  configured: boolean;
  updated_at: string | null;
}

export interface MCPCredentialsListResponse {
  server_name: string;
  keys: MCPCredentialKey[];
}

export interface MCPEnabledResponse {
  status: string;
  name: string;
  enabled: boolean;
  connected: boolean;
  tool_count: number;
  detail: string | null;
}

// ---------------------------------------------------------------------------
// API calls
// ---------------------------------------------------------------------------

export async function fetchMCPClients(): Promise<MCPClientsStatusResponse> {
  const res = await fetch(`${BACKEND_BASE}/api/mcp/clients/status`);
  if (!res.ok) throw new Error(`fetch mcp clients failed: ${res.status}`);
  return (await res.json()) as MCPClientsStatusResponse;
}

export async function setMCPClientEnabled(
  name: string,
  enabled: boolean,
): Promise<MCPEnabledResponse> {
  const res = await fetch(
    `${BACKEND_BASE}/api/mcp/clients/${encodeURIComponent(name)}/enabled`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled }),
    },
  );
  if (!res.ok) {
    // FastAPI 422/500 error 走 detail 字段
    let msg = `set enabled failed: ${res.status}`;
    try {
      const j = await res.json();
      if (j?.detail) msg = String(j.detail);
    } catch { /* ignore */ }
    throw new Error(msg);
  }
  return (await res.json()) as MCPEnabledResponse;
}

export async function fetchMCPCredentials(
  name: string,
): Promise<MCPCredentialsListResponse> {
  const res = await fetch(
    `${BACKEND_BASE}/api/mcp/clients/${encodeURIComponent(name)}/credentials`,
  );
  if (!res.ok) throw new Error(`fetch credentials failed: ${res.status}`);
  return (await res.json()) as MCPCredentialsListResponse;
}

// UX-001：单 tool enable/disable
export async function setMCPToolEnabled(
  serverName: string,
  toolName: string,
  enabled: boolean,
): Promise<MCPToolEnabledResponse> {
  const res = await fetch(
    `${BACKEND_BASE}/api/mcp/clients/${encodeURIComponent(serverName)}` +
      `/tools/${encodeURIComponent(toolName)}/enabled`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled }),
    },
  );
  if (!res.ok) {
    let msg = `set tool enabled failed: ${res.status}`;
    try {
      const j = await res.json();
      if (j?.detail) msg = String(j.detail);
    } catch { /* ignore */ }
    throw new Error(msg);
  }
  return (await res.json()) as MCPToolEnabledResponse;
}

export async function setMCPCredentials(
  name: string,
  credentials: Record<string, string>,
): Promise<MCPCredentialsListResponse> {
  const res = await fetch(
    `${BACKEND_BASE}/api/mcp/clients/${encodeURIComponent(name)}/credentials`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ credentials }),
    },
  );
  if (!res.ok) {
    let msg = `set credentials failed: ${res.status}`;
    try {
      const j = await res.json();
      if (j?.detail) msg = String(j.detail);
    } catch { /* ignore */ }
    throw new Error(msg);
  }
  return (await res.json()) as MCPCredentialsListResponse;
}

// ---------------------------------------------------------------------------
// Stage 2.1.2 — POST / DELETE 新建 / 删除 MCP client entry
//
// 与 backend/routes/mcp_api.py CreateClientBody / CreateClientResponse 对齐。
// schema drift 时 tsc 立即报错。
// ---------------------------------------------------------------------------

export interface MCPClientCreatePayload {
  name: string;
  description?: string;
  transport: 'stdio' | 'http';
  command?: string;
  args?: string[];
  env?: Record<string, string>;
  url?: string;
  enabled?: boolean;                    // 默认 true(backend)
  expose_via_skyler_server?: boolean;   // 默认 true(backend)
}

export interface MCPClientCreateResponse {
  name: string;
  transport: string;
  enabled: boolean;
  connected: boolean;
  tool_count: number;
  // connect 失败时 backend 返 200 +error;HTTP 错误统一走 throw new Error
  error: string | null;
}

export interface MCPClientDeleteResponse {
  status: string;
  name: string;
}

/** POST /api/mcp/clients — 新建 MCP server entry。
 *
 * 错误码:
 *  - 409 name 重复
 *  - 422 字段验证失败(stdio 缺 command / http 缺 url)
 *  - 500 yaml 写失败
 * connect 失败:返 201 + ``error`` 字段,**不算 throw**(用户能看到原因决定 retry/delete)
 */
export async function addMCPServer(
  payload: MCPClientCreatePayload,
): Promise<MCPClientCreateResponse> {
  const res = await fetch(`${BACKEND_BASE}/api/mcp/clients`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    let msg = `add mcp server failed: ${res.status}`;
    try {
      const j = await res.json();
      if (j?.detail) msg = String(j.detail);
    } catch { /* ignore */ }
    const err = new Error(msg) as Error & { status?: number };
    err.status = res.status;
    throw err;
  }
  return (await res.json()) as MCPClientCreateResponse;
}

/** DELETE /api/mcp/clients/{name} — 删除 MCP server entry。
 *
 * 错误码:
 *  - 404 name 不存在
 *  - 500 yaml prune 失败(server 已 in-memory 删除,但下次启动可能复活)
 */
export async function deleteMCPServer(
  name: string,
): Promise<MCPClientDeleteResponse> {
  const res = await fetch(
    `${BACKEND_BASE}/api/mcp/clients/${encodeURIComponent(name)}`,
    { method: 'DELETE' },
  );
  if (!res.ok) {
    let msg = `delete mcp server failed: ${res.status}`;
    try {
      const j = await res.json();
      if (j?.detail) msg = String(j.detail);
    } catch { /* ignore */ }
    const err = new Error(msg) as Error & { status?: number };
    err.status = res.status;
    throw err;
  }
  return (await res.json()) as MCPClientDeleteResponse;
}

/** 提取 env 字符串值里 ``${VAR_NAME}`` 占位符的变量名列表(去重 + 顺序保留)。
 *
 * 用法:AddMCPServerForm 提交后调,把返回的 list 当作 ``env_required`` 注入
 * 一个 synthetic MCPClientStatus,driver CredentialsModal 让用户填真实 token。
 *
 * - ``${BRAVE_API_KEY}`` → ["BRAVE_API_KEY"]
 * - ``foo${A}bar${B}`` → ["A", "B"]
 * - ``literal value`` → []
 */
export function extractEnvPlaceholders(
  env: Record<string, string> | undefined,
): string[] {
  if (!env) return [];
  const seen = new Set<string>();
  const out: string[] = [];
  // 与 backend ``os.path.expandvars`` 接受的模式对齐:``${NAME}`` 形式
  // (大小写字母 / 数字 / 下划线;以非数字开头较稳)
  const re = /\$\{([A-Za-z_][A-Za-z0-9_]*)\}/g;
  for (const value of Object.values(env)) {
    if (typeof value !== 'string') continue;
    let m: RegExpExecArray | null;
    while ((m = re.exec(value)) !== null) {
      const name = m[1];
      if (!seen.has(name)) {
        seen.add(name);
        out.push(name);
      }
    }
  }
  return out;
}
