// v3.5 chunk 8a — frontend API client for activity_watcher status + config.
//
// Backend single source of truth; 字段对齐 backend/routes/activity_api.py。

const BACKEND_BASE = 'http://127.0.0.1:8000';

export interface ActivityStateLite {
  active_app: string | null;
  browser: { browser: string; url: string; title: string } | null;
  document: { path: string; type: string; basename: string } | null;
  url_content: { title: string; content: string } | null;
  timestamp: number;
}

export interface ActivityStatusResponse {
  enabled: boolean;
  running: boolean;
  poll_interval_seconds: number;
  fetch_url_content: boolean;
  last_state: ActivityStateLite | null;
  daily_triggers_today: number;
  daily_cap: number;
  throttle_minutes: number;
}

export interface ActivityConfigResponse {
  enabled: boolean;
  poll_interval_seconds: number;
  fetch_url_content: boolean;
  blocked_apps: string[];
  blocked_url_patterns: string[];
  trigger_throttle_minutes: number;
  max_daily_triggers: number;
  // chunk 8a-ext: 慢路径 judge 配置
  judge_enabled: boolean;
  judge_model: string;
  judge_min_stay_minutes: number;
  judge_throttle_minutes: number;
}

export interface ActivityConfigPatch {
  enabled?: boolean;
  blocked_apps?: string[];
  blocked_url_patterns?: string[];
  fetch_url_content?: boolean;
  judge_enabled?: boolean;     // chunk 8a-ext 智能陪伴 toggle
}

export async function fetchActivityStatus(): Promise<ActivityStatusResponse> {
  const r = await fetch(`${BACKEND_BASE}/api/activity/status`);
  if (!r.ok) throw new Error(`fetch activity status failed: HTTP ${r.status}`);
  return (await r.json()) as ActivityStatusResponse;
}

export async function fetchActivityConfig(): Promise<ActivityConfigResponse> {
  const r = await fetch(`${BACKEND_BASE}/api/activity/config`);
  if (!r.ok) throw new Error(`fetch activity config failed: HTTP ${r.status}`);
  return (await r.json()) as ActivityConfigResponse;
}

export async function patchActivityConfig(
  body: ActivityConfigPatch,
): Promise<ActivityConfigResponse> {
  const r = await fetch(`${BACKEND_BASE}/api/activity/config`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    let msg = `patch activity config failed: HTTP ${r.status}`;
    try {
      const j = await r.json();
      if (j?.detail) msg = String(j.detail);
    } catch { /* ignore */ }
    throw new Error(msg);
  }
  return (await r.json()) as ActivityConfigResponse;
}
