// v3.5 chunk 14 — frontend API client for activity_timeline (sessions DB)。
//
// 字段对齐 backend/routes/activity_api.py TimelineResponse pydantic model。

const BACKEND_BASE = 'http://127.0.0.1:8000';

export interface ActivitySessionRow {
  id: number;
  start_at: string;          // ISO-like 'YYYY-MM-DD HH:MM:SS' (UTC,SQLite 写入)
  end_at: string;
  duration_seconds: number;
  app_name: string;          // chunk 14 + hotfix-10: 英文 bundle 名
  browser_url: string | null;
  browser_title: string | null;
  category: string | null;   // 'ide' / 'browser' / 'music' / 'video' / 'social' / 'tech_doc' / 'other'
  is_idle_filtered: boolean;
}

export interface ActivityAppSummary {
  app_name: string;
  total_seconds: number;
  session_count: number;
  category: string | null;
  top_urls: { url: string; title: string; seconds: number }[];
}

export interface TimelineResponse {
  date: string;
  days: number;
  total_active_seconds: number;
  sessions: ActivitySessionRow[];
  summary_by_app: ActivityAppSummary[];
  summary_by_category: Record<string, number>;
}

export async function fetchTimeline(opts: {
  date?: string;        // YYYY-MM-DD
  days?: number;        // 1-90,默 1
  includeIdle?: boolean;// 默 true
} = {}): Promise<TimelineResponse> {
  const qs = new URLSearchParams();
  if (opts.date) qs.set('date', opts.date);
  if (opts.days !== undefined) qs.set('days', String(opts.days));
  if (opts.includeIdle !== undefined) qs.set('include_idle', String(opts.includeIdle));
  const r = await fetch(`${BACKEND_BASE}/api/activity/timeline?${qs.toString()}`);
  if (!r.ok) throw new Error(`fetch timeline failed: HTTP ${r.status}`);
  return (await r.json()) as TimelineResponse;
}

export async function deleteSession(id: number): Promise<{ deleted: boolean }> {
  const r = await fetch(`${BACKEND_BASE}/api/activity/timeline/${id}`, {
    method: 'DELETE',
  });
  if (!r.ok) {
    let msg = `delete session failed: HTTP ${r.status}`;
    try {
      const j = await r.json();
      if (j?.detail) msg = String(j.detail);
    } catch { /* ignore */ }
    throw new Error(msg);
  }
  return (await r.json()) as { deleted: boolean };
}

export async function deleteTimelineByDate(
  date: string,                       // 'YYYY-MM-DD' 或 'all'
): Promise<{ deleted_count: number; date: string }> {
  const qs = new URLSearchParams({ date });
  const r = await fetch(`${BACKEND_BASE}/api/activity/timeline?${qs.toString()}`, {
    method: 'DELETE',
  });
  if (!r.ok) {
    let msg = `delete timeline failed: HTTP ${r.status}`;
    try {
      const j = await r.json();
      if (j?.detail) msg = String(j.detail);
    } catch { /* ignore */ }
    throw new Error(msg);
  }
  return (await r.json()) as { deleted_count: number; date: string };
}

// 工具:秒数 → "1h 30min" 友好串(UI 用,后端 capability 用中文版)
export function formatDuration(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}min`;
  const h = Math.floor(seconds / 3600);
  const m = Math.round((seconds % 3600) / 60);
  return m === 0 ? `${h}h` : `${h}h ${m}min`;
}

// 工具:UTC ISO 字符串 → user-local 'HH:MM' 显示
export function formatLocalTime(iso: string): string {
  try {
    // SQLite 返 'YYYY-MM-DD HH:MM:SS' (UTC naive), 加 'Z' 让 JS 当 UTC 解析
    const d = new Date(iso.replace(' ', 'T') + (iso.endsWith('Z') ? '' : 'Z'));
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  } catch { return iso; }
}

// 工具:今天的 YYYY-MM-DD(local)
export function todayLocalISO(): string {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}
