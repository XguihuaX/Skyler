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
