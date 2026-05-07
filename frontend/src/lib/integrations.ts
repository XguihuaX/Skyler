// v3-G chunk 1 — frontend client for /api/integrations/*.

const BACKEND_BASE = 'http://127.0.0.1:8000';

export interface GoogleStatusResponse {
  credentials_present: boolean;
  authorized: boolean;
  account_hint: string | null;
}

export interface GoogleAuthResponse {
  status: string;
  detail: string | null;
}

export async function fetchGoogleStatus(): Promise<GoogleStatusResponse> {
  const res = await fetch(`${BACKEND_BASE}/api/integrations/google/status`);
  if (!res.ok) throw new Error(`google status failed: ${res.status}`);
  return (await res.json()) as GoogleStatusResponse;
}

export async function startGoogleAuth(): Promise<GoogleAuthResponse> {
  // 长 timeout：后端 run_local_server 等用户在浏览器点同意，最多几分钟。
  // fetch 默认无超时，浏览器可能受到 max-fetch-time 限制；先按默认走，
  // 真实生产里如果一直挂前端 UI 会阻塞 —— v0.1 接受。
  const res = await fetch(`${BACKEND_BASE}/api/integrations/google/auth`, {
    method: 'POST',
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`google auth failed (${res.status}): ${text}`);
  }
  return (await res.json()) as GoogleAuthResponse;
}

export async function revokeGoogleAuth(): Promise<GoogleAuthResponse> {
  const res = await fetch(`${BACKEND_BASE}/api/integrations/google/revoke`, {
    method: 'POST',
  });
  if (!res.ok) throw new Error(`google revoke failed: ${res.status}`);
  return (await res.json()) as GoogleAuthResponse;
}

// ---------------------------------------------------------------------------
// v3-G chunk 1 — 起床简报测试触发
// ---------------------------------------------------------------------------

export interface BriefingTestResponse {
  text: string;
  audio_path: string | null;
  audio_bytes: number;
  voice_model: string | null;
}

export async function triggerTestBriefing(
  mode: 'auto' | 'wake_call' | 'morning' = 'auto',
): Promise<BriefingTestResponse> {
  const url = `${BACKEND_BASE}/api/briefing/test?mode=${encodeURIComponent(mode)}`;
  const res = await fetch(url, { method: 'POST' });
  if (!res.ok) throw new Error(`briefing test failed: ${res.status}`);
  return (await res.json()) as BriefingTestResponse;
}
