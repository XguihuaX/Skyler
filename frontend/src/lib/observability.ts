/**
 * Bugfix-4 — Observability REST client.
 */

const _BACKEND_BASE = 'http://127.0.0.1:8000';

export type UsageRange = 'today' | 'month' | 'all';

export interface SourceUsage {
  calls: number;
  chars: number;
  cost: number;
}

export interface AnomalyCall {
  id: number;
  timestamp: string | null;
  source: string | null;
  character_id: number | null;
  voice: string | null;
  input_chars: number;
  input_preview: string | null;
  success: boolean;
  error_message: string | null;
}

export interface TtsUsage {
  range: string;
  total_calls: number;
  total_chars: number;
  total_cost_yuan: number;
  by_source: Record<string, SourceUsage>;
  avg_chars_per_call: number | null;
  anomaly_calls: AnomalyCall[];
}

export interface RecentCall {
  id: number;
  timestamp: string | null;
  source: string | null;
  character_id: number | null;
  voice: string | null;
  model: string | null;
  input_chars: number;
  input_preview: string | null;
  cost_estimate: number | null;
  success: boolean;
  error_message: string | null;
}

export interface SystemResources {
  has_psutil: boolean;
  backend_rss_mb: number | null;
  backend_cpu_percent: number | null;
  system_total_ram_mb: number | null;
  system_used_ram_mb: number | null;
  system_ram_percent: number | null;
  whisper_loaded: boolean;
  whisper_size: string | null;
  whisper_disk_mb: number | null;
  net_recv_kbps: number | null;
  net_sent_kbps: number | null;
}

export async function fetchTtsUsage(range: UsageRange = 'today'): Promise<TtsUsage> {
  const r = await fetch(`${_BACKEND_BASE}/api/observability/tts/usage?range=${range}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return (await r.json()) as TtsUsage;
}

export async function fetchRecentCalls(limit = 20): Promise<RecentCall[]> {
  const r = await fetch(`${_BACKEND_BASE}/api/observability/tts/recent_calls?limit=${limit}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  const j = (await r.json()) as { calls: RecentCall[] };
  return j.calls ?? [];
}

export async function fetchSystemResources(): Promise<SystemResources> {
  const r = await fetch(`${_BACKEND_BASE}/api/observability/system/resources`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return (await r.json()) as SystemResources;
}

const _SOURCE_LABELS: Record<string, string> = {
  chat: '主聊天',
  proactive: '主动陪伴',
  activity_smart: '活动感知',
  preview: '试听预览',
  unknown: '未分类',
};

export function sourceLabel(s: string | null | undefined): string {
  if (!s) return _SOURCE_LABELS.unknown;
  return _SOURCE_LABELS[s] ?? s;
}
