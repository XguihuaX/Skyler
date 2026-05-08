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

// ---------------------------------------------------------------------------
// v3-G chunk 3b — character state
// ---------------------------------------------------------------------------

export type CharacterMood = 'happy' | 'sad' | 'curious' | 'calm' | 'excited' | 'tired' | 'neutral';

export interface CharacterStateResponse {
  character_id: number;
  mood: CharacterMood;
  intimacy: number;
  thought: string | null;
  activity: string | null;
  last_interaction_at: string | null;
  updated_at: string | null;
}

export async function fetchCharacterState(characterId: number): Promise<CharacterStateResponse> {
  const res = await fetch(`${BACKEND_BASE}/api/characters/${characterId}/state`);
  if (!res.ok) throw new Error(`fetch character state failed: ${res.status}`);
  return (await res.json()) as CharacterStateResponse;
}

export async function resetCharacterState(characterId: number): Promise<CharacterStateResponse> {
  const res = await fetch(`${BACKEND_BASE}/api/characters/${characterId}/reset_state`, {
    method: 'POST',
  });
  if (!res.ok) throw new Error(`reset character state failed: ${res.status}`);
  return (await res.json()) as CharacterStateResponse;
}

// ---------------------------------------------------------------------------
// v3-G chunk 3a — clipboard
// ---------------------------------------------------------------------------

export type ClipboardContentType = 'url' | 'code' | 'plain_text' | 'markdown' | 'json';

export interface ClipboardItem {
  content: string;
  content_type: ClipboardContentType;
  captured_at: number;
  captured_iso: string;
}

export async function fetchClipboardEnabled(): Promise<boolean> {
  const res = await fetch(`${BACKEND_BASE}/api/clipboard/enabled`);
  if (!res.ok) throw new Error(`fetch clipboard enabled failed: ${res.status}`);
  const data = (await res.json()) as { enabled: boolean };
  return data.enabled;
}

export async function setClipboardEnabled(enabled: boolean): Promise<boolean> {
  const res = await fetch(`${BACKEND_BASE}/api/clipboard/enabled`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ enabled }),
  });
  if (!res.ok) throw new Error(`set clipboard enabled failed: ${res.status}`);
  const data = (await res.json()) as { enabled: boolean };
  return data.enabled;
}

export async function captureClipboard(content: string, contentType?: string): Promise<{ ok: boolean; size: number }> {
  const res = await fetch(`${BACKEND_BASE}/api/clipboard/captured`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content, content_type: contentType }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`clipboard capture failed (${res.status}): ${text}`);
  }
  return (await res.json()) as { ok: boolean; size: number };
}
