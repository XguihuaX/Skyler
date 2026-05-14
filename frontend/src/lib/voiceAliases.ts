/**
 * Bugfix-3.4 — voice_aliases REST client.
 *
 * voice_id → display_name 自定义友好名。aliases 表后端在 bugfix-3.4 migration
 * 中 auto-seed (角色绑的 cloned voice → ``<角色名> voice``);用户可在 UI 重命名。
 */

const _BACKEND_BASE = 'http://127.0.0.1:8000';

export interface VoiceAliasMap {
  aliases: Record<string, string>;
}

export async function fetchVoiceAliases(): Promise<Record<string, string>> {
  const r = await fetch(`${_BACKEND_BASE}/api/tts/voices/aliases`);
  if (!r.ok) throw new Error(`fetch aliases failed: ${r.status}`);
  const j = (await r.json()) as VoiceAliasMap;
  return j.aliases ?? {};
}

export async function setVoiceAlias(voiceId: string, displayName: string): Promise<void> {
  const r = await fetch(
    `${_BACKEND_BASE}/api/tts/voices/aliases/${encodeURIComponent(voiceId)}`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ display_name: displayName }),
    },
  );
  if (!r.ok) {
    let detail = `HTTP ${r.status}`;
    try {
      const j = await r.json();
      if (j?.detail) detail = String(j.detail);
    } catch { /* ignore */ }
    throw new Error(detail);
  }
}

export async function deleteVoiceAlias(voiceId: string): Promise<void> {
  const r = await fetch(
    `${_BACKEND_BASE}/api/tts/voices/aliases/${encodeURIComponent(voiceId)}`,
    { method: 'DELETE' },
  );
  if (!r.ok) throw new Error(`delete alias failed: ${r.status}`);
}

/**
 * Resolve display name. Priority: alias > fallback > truncated voice_id.
 */
export function resolveVoiceName(
  voiceId: string,
  aliases: Record<string, string>,
  fallback?: string,
): string {
  if (aliases[voiceId]) return aliases[voiceId];
  if (fallback) return fallback;
  if (voiceId.length > 28) return voiceId.slice(0, 24) + '…';
  return voiceId;
}
