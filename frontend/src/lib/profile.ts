// v3.5 chunk 9 — frontend API client for users.profile_summary.
//
// 与 lib/mcp_clients.ts / lib/live2d.ts 平行。后端 single source of truth；
// backend 路径见 backend/routes/users_api.py。

const BACKEND_BASE = 'http://127.0.0.1:8000';

export interface UserProfile {
  user_id: string;
  user_name: string | null;
  nickname: string | null;
  language: string | null;
  profile_summary: string | null;
}

export interface ProfileRegenerateResponse {
  status: string;
  profile_summary: string | null;
  detail: string | null;
}

// ---------------------------------------------------------------------------
// API calls
// ---------------------------------------------------------------------------

export async function fetchUserProfile(userId: string): Promise<UserProfile> {
  const r = await fetch(`${BACKEND_BASE}/api/users/${encodeURIComponent(userId)}/profile`);
  if (!r.ok) throw new Error(`fetch profile failed: HTTP ${r.status}`);
  return (await r.json()) as UserProfile;
}

export async function patchProfileSummary(
  userId: string,
  summary: string,
): Promise<UserProfile> {
  const r = await fetch(
    `${BACKEND_BASE}/api/users/${encodeURIComponent(userId)}/profile_summary`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ summary }),
    },
  );
  if (!r.ok) throw new Error(`patch profile_summary failed: HTTP ${r.status}`);
  return (await r.json()) as UserProfile;
}

export async function deleteProfileSummary(userId: string): Promise<void> {
  const r = await fetch(
    `${BACKEND_BASE}/api/users/${encodeURIComponent(userId)}/profile_summary`,
    { method: 'DELETE' },
  );
  if (!r.ok && r.status !== 204) {
    throw new Error(`delete profile_summary failed: HTTP ${r.status}`);
  }
}

export async function regenerateProfileSummary(
  userId: string,
): Promise<ProfileRegenerateResponse> {
  const r = await fetch(
    `${BACKEND_BASE}/api/users/${encodeURIComponent(userId)}/profile_summary/regenerate`,
    { method: 'POST' },
  );
  if (!r.ok) {
    throw new Error(`regenerate profile_summary failed: HTTP ${r.status}`);
  }
  return (await r.json()) as ProfileRegenerateResponse;
}
