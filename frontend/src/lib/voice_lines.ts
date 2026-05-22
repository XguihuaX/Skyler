// v4.0 voice greeting · API client for character voice lines
// per backend/routes/voice_lines.py · 4 endpoints

const BACKEND_BASE = 'http://127.0.0.1:8000';

export interface VoiceLine {
  id: number;
  character_id: number;
  audio_path: string;
  audio_url: string;
  text_description: string | null;
  language: string | null;
  duration_ms: number | null;
  created_at?: string;
}

export interface VoiceLineListResponse {
  character_id: number;
  count: number;
  items: VoiceLine[];
}

/**
 * GET /api/character/:cid/voice_lines · list per character
 */
export async function listVoiceLines(characterId: number): Promise<VoiceLineListResponse> {
  const resp = await fetch(`${BACKEND_BASE}/api/character/${characterId}/voice_lines`);
  if (!resp.ok) throw new Error(`listVoiceLines failed: ${resp.status}`);
  return resp.json();
}

/**
 * GET /api/character/:cid/voice_lines/random · 1 random;空 list → 404
 * 立绘馆 onEnter 主路径 · 失败时 caller 应静默不播(per PM spec)。
 */
export async function getRandomVoiceLine(characterId: number): Promise<VoiceLine | null> {
  const resp = await fetch(`${BACKEND_BASE}/api/character/${characterId}/voice_lines/random`);
  if (resp.status === 404) return null;  // 无 voice lines → 静默
  if (!resp.ok) throw new Error(`getRandomVoiceLine failed: ${resp.status}`);
  return resp.json();
}

/**
 * POST /api/character/:cid/voice_lines · multipart upload
 */
export async function uploadVoiceLine(
  characterId: number,
  file: File,
  options: { text_description?: string; language?: string } = {},
): Promise<VoiceLine> {
  const fd = new FormData();
  fd.append('file', file);
  if (options.text_description) fd.append('text_description', options.text_description);
  if (options.language) fd.append('language', options.language);
  const resp = await fetch(`${BACKEND_BASE}/api/character/${characterId}/voice_lines`, {
    method: 'POST',
    body: fd,
  });
  if (!resp.ok) {
    const msg = await resp.text().catch(() => '');
    throw new Error(`uploadVoiceLine failed: ${resp.status} ${msg}`);
  }
  return resp.json();
}

/**
 * DELETE /api/character/:cid/voice_lines/:lid · del file + DB row
 */
export async function deleteVoiceLine(
  characterId: number,
  lineId: number,
): Promise<{ deleted_id: number; audio_path: string }> {
  const resp = await fetch(
    `${BACKEND_BASE}/api/character/${characterId}/voice_lines/${lineId}`,
    { method: 'DELETE' },
  );
  if (!resp.ok) throw new Error(`deleteVoiceLine failed: ${resp.status}`);
  return resp.json();
}

/**
 * 立绘馆 onEnter 主路径辅助函数:fetch random + play audio。
 * 失败 / 空 list 静默不播(per PM spec)· return audio element 让 caller 控制(eg cleanup)。
 *
 * Audio URL 是 /static/voice_lines/<cid>/<uuid>.<ext>(per backend StaticFiles
 * mount),fetch base URL 从 API_BASE 推(去 /api 后缀)。
 */
export function playRandomVoiceGreeting(characterId: number): Promise<HTMLAudioElement | null> {
  return getRandomVoiceLine(characterId)
    .then((line) => {
      if (!line) return null;
      // audio_url 是 backend-relative path('/static/voice_lines/...');
      // 拼 BACKEND_BASE 拿绝对 URL(dev frontend 走 vite,backend 直 fetch):
      const audioUrl = `${BACKEND_BASE}${line.audio_url}`;
      const audio = new Audio(audioUrl);
      audio.play().catch((err) => {
        // play() failure(browser autoplay policy / format issue)静默
        console.warn('[voice_greeting] audio.play failed:', err);
      });
      return audio;
    })
    .catch((err) => {
      console.warn('[voice_greeting] random fetch failed:', err);
      return null;
    });
}
