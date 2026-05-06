// v3-G chunk 0 — frontend client for /api/capabilities.
//
// 命名 / 位置约定与 lib/tts.ts、lib/live2d.ts 一致：lib 下平铺，等到 ≥ 5 个
// API helper 文件再考虑迁 src/api/。

const BACKEND_BASE = 'http://127.0.0.1:8000';

// 与 backend/routes/capabilities_api.py 的 CapabilityDTO 对齐。
// schema drift 时 build 阶段立即报错。
export interface CapabilityHealth {
  status: 'healthy' | 'warn' | 'error' | 'unknown';
  error?: string;
}

export interface CapabilityDTO {
  name: string;
  display_name: string;
  description: string;
  category: string;
  consumers: string[];        // "chat_agent" | "scheduler" | "webhook"
  trigger_modes: string[];    // "on_demand" | "scheduled" | "event_driven"
  icon: string;
  user_visible: boolean;
  has_health_check: boolean;
  health: CapabilityHealth;
  // v3-G chunk 1.5 — 外部 MCP 反向注册的 capability 携带来源 server 名
  source_server: string | null;
  expose_via_server: boolean;
}

export interface CapabilitiesResponse {
  capabilities: CapabilityDTO[];
  by_category: Record<string, CapabilityDTO[]>;
}

export interface HealthCheckResponse {
  name: string;
  health: CapabilityHealth;
}

export async function fetchCapabilities(): Promise<CapabilitiesResponse> {
  const res = await fetch(`${BACKEND_BASE}/api/capabilities`);
  if (!res.ok) throw new Error(`fetch capabilities failed: ${res.status}`);
  return (await res.json()) as CapabilitiesResponse;
}

export async function runHealthCheck(name: string): Promise<HealthCheckResponse> {
  const res = await fetch(
    `${BACKEND_BASE}/api/capabilities/${encodeURIComponent(name)}/healthcheck`,
    { method: 'POST' },
  );
  if (!res.ok) throw new Error(`healthcheck ${name} failed: ${res.status}`);
  return (await res.json()) as HealthCheckResponse;
}
