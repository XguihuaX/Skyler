// v3.5 chunk 11 — frontend API client for users.profile_data (structured JSON).
//
// 与 lib/profile.ts (chunk 9 legacy) 平行，chunk 11 起前端用本文件而不是
// profile.ts。chunk 9 endpoints 仍可用作 fallback，但 backend 调用时
// log [deprecated] warning。

const BACKEND_BASE = 'http://127.0.0.1:8000';

export interface ProfileData {
  profession: string | null;
  current_projects: string[];
  communication_style: string | null;
  interests: string[];
  language_preferences: string | null;
  active_hours: string | null;
  recurring_topics: string[];
}

export interface ProfileDataResponse {
  user_id: string;
  profile_data: ProfileData | null;
}

export type ProfileDataPatch = Partial<ProfileData>;

export type ProfileDataRegenerateMode = 'incremental' | 'reset';

export interface ProfileDataRegenerateResponse {
  status: string;
  profile_data: ProfileData | null;
  detail: string | null;
}

// ---------------------------------------------------------------------------
// API calls
// ---------------------------------------------------------------------------

export async function fetchProfileData(
  userId: string,
): Promise<ProfileDataResponse> {
  const r = await fetch(
    `${BACKEND_BASE}/api/users/${encodeURIComponent(userId)}/profile_data`,
  );
  if (!r.ok) throw new Error(`fetch profile_data failed: HTTP ${r.status}`);
  return (await r.json()) as ProfileDataResponse;
}

export async function patchProfileData(
  userId: string,
  patch: ProfileDataPatch,
): Promise<ProfileDataResponse> {
  const r = await fetch(
    `${BACKEND_BASE}/api/users/${encodeURIComponent(userId)}/profile_data`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    },
  );
  if (!r.ok) throw new Error(`patch profile_data failed: HTTP ${r.status}`);
  return (await r.json()) as ProfileDataResponse;
}

export async function deleteProfileData(userId: string): Promise<void> {
  const r = await fetch(
    `${BACKEND_BASE}/api/users/${encodeURIComponent(userId)}/profile_data`,
    { method: 'DELETE' },
  );
  if (!r.ok && r.status !== 204) {
    throw new Error(`delete profile_data failed: HTTP ${r.status}`);
  }
}

export async function regenerateProfileData(
  userId: string,
  mode: ProfileDataRegenerateMode = 'incremental',
): Promise<ProfileDataRegenerateResponse> {
  const r = await fetch(
    `${BACKEND_BASE}/api/users/${encodeURIComponent(userId)}/profile_data/regenerate`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode }),
    },
  );
  if (!r.ok) {
    throw new Error(`regenerate profile_data failed: HTTP ${r.status}`);
  }
  return (await r.json()) as ProfileDataRegenerateResponse;
}
