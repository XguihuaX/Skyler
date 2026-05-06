// v3-G chunk 1.5 — frontend client for MCP server / clients management.

const BACKEND_BASE = 'http://127.0.0.1:8000';

export interface MCPServerStatus {
  enabled: boolean;
  endpoint: string;
  bearer_token_configured: boolean;
  bearer_token: string | null;
  exposed_tool_count: number;
  exposed_tool_names: string[];
}

export async function fetchMcpServerStatus(): Promise<MCPServerStatus> {
  const res = await fetch(`${BACKEND_BASE}/api/mcp/server/status`);
  if (!res.ok) throw new Error(`mcp server status failed: ${res.status}`);
  return (await res.json()) as MCPServerStatus;
}

export interface MCPClientStatusItem {
  name: string;
  description: string;
  enabled: boolean;
  connected: boolean;
  transport: string;
  tool_count: number;
  expose_via_server: boolean;
  last_error: string | null;
}

export interface MCPClientsStatus {
  clients: MCPClientStatusItem[];
}

export async function fetchMcpClientsStatus(): Promise<MCPClientsStatus> {
  const res = await fetch(`${BACKEND_BASE}/api/mcp/clients/status`);
  if (!res.ok) throw new Error(`mcp clients status failed: ${res.status}`);
  return (await res.json()) as MCPClientsStatus;
}

export async function reconnectMcpClient(name: string): Promise<{status: string; detail: string | null}> {
  const res = await fetch(
    `${BACKEND_BASE}/api/mcp/clients/${encodeURIComponent(name)}/reconnect`,
    { method: 'POST' },
  );
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`reconnect ${name} failed: ${text}`);
  }
  return (await res.json()) as {status: string; detail: string | null};
}
