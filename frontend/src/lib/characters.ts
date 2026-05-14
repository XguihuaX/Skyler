// v4-fan chunk 5 — Character splash art API client。
//
// 跟 lib/config.ts 的 fetchCharacters / patchCharacter 等 character CRUD
// 同 backend (characters_api.py),分文件只是把上传 / 删除立绘的两条
// 路径单独归类(避免 config.ts 进一步膨胀)。
//
// Backend ref: backend/routes/characters_api.py
//   POST   /api/characters/{id}/splash-art   (multipart, file=...)
//   DELETE /api/characters/{id}/splash-art
//
// 错误处理:沿用 lib/live2d.ts uploadLive2DModel 的 pattern —— 抛 Error
// + 挂 ``.status``。常见 status:
//   - 404: character 不存在
//   - 415: MIME / 扩展名不支持
//   - 413: 文件过大 (> 5 MB)
//   - 500: 磁盘错(rollback,backend 不留半文件)

const BACKEND_BASE = 'http://127.0.0.1:8000';

export interface SplashArtUploadResult {
  character_id: number;
  splash_art_url: string;
}

export interface SplashArtDeleteResult {
  character_id: number;
  deleted: true;
}

async function _throwHttp(res: Response, action: string): Promise<never> {
  let msg = `${action} failed: ${res.status}`;
  try {
    const j = await res.json();
    if (j?.detail) msg = String(j.detail);
  } catch {
    /* ignore json parse errors */
  }
  const err = new Error(msg) as Error & { status?: number };
  err.status = res.status;
  throw err;
}

/** POST /api/characters/{id}/splash-art — multipart 上传单图。 */
export async function uploadSplashArt(
  characterId: number,
  file: File,
): Promise<SplashArtUploadResult> {
  const fd = new FormData();
  fd.append('file', file);
  const res = await fetch(
    `${BACKEND_BASE}/api/characters/${characterId}/splash-art`,
    { method: 'POST', body: fd },
  );
  if (!res.ok) await _throwHttp(res, 'upload splash art');
  return (await res.json()) as SplashArtUploadResult;
}

/** DELETE /api/characters/{id}/splash-art — 清掉文件 + DB url=NULL。 */
export async function deleteSplashArt(
  characterId: number,
): Promise<SplashArtDeleteResult> {
  const res = await fetch(
    `${BACKEND_BASE}/api/characters/${characterId}/splash-art`,
    { method: 'DELETE' },
  );
  if (!res.ok) await _throwHttp(res, 'delete splash art');
  return (await res.json()) as SplashArtDeleteResult;
}
