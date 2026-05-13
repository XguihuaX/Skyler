// v3-E2 commit 3b — frontend API client for /api/live2d/models.
//
// 放在 src/lib/ 而不是 src/api/，跟 lib/config.ts 的 fetchCharacters /
// fetchMessages 等 API helper 保持一致。Skyler 至今所有 API 调用都在
// lib/ 下，不再额外开 api/ 目录避免双源。

const BACKEND_BASE = 'http://127.0.0.1:8000';

// 与 backend/services/live2d_scanner.py Live2DModelInfo 对齐。
// 后端 single source of truth，前端 schema drift 时立刻 build error。
export interface Live2DModel {
  slug: string;
  model3_path: string;
  moc3_path: string;
  moc3_version: number | null;
  moc3_version_label: string;
  pixi_compatible: boolean;
  warnings: string[];
}

export interface Live2DScanResponse {
  scan_dir: string;
  models: Live2DModel[];
}

export async function fetchLive2DModels(): Promise<Live2DScanResponse> {
  const res = await fetch(`${BACKEND_BASE}/api/live2d/models`);
  if (!res.ok) throw new Error(`fetch live2d models failed: ${res.status}`);
  return (await res.json()) as Live2DScanResponse;
}

// ---------------------------------------------------------------------------
// Stage 2.2.1 — POST /api/live2d/upload(zip 上传)
// ---------------------------------------------------------------------------

export interface Live2DMotionEntry {
  group: string;
  index: number;
}

export interface Live2DUploadResult {
  slug: string;
  moc3_version: number;
  moc3_version_label: string;
  textures_count: number;
  motions_count: number;
  // 后端 ``_build_motion_map`` 生成的默认值;前端决定是否写到
  // ``character.motion_map_json``
  motion_map: Record<string, Live2DMotionEntry>;
  // vite static url 如 ``/live2d/<slug>/<foo>.model3.json``
  model_path: string;
}

/** POST /api/live2d/upload — 上传 .zip model package。
 *
 * 错误处理:除了 fetch 网络错,backend 用 status code + ``detail`` 字段:
 *  - 422 zip 格式 / 缺 .moc3 / 缺 .model3.json / moc3 ver=5 / path traversal /
 *        per-file size limit / slug 非法
 *  - 409 slug 已存在
 *  - 500 解压异常
 *
 * 抛 Error,挂 ``.status`` 让调用方按 code 给不同 UX(如 409 → 弹改名 input)。
 */
export async function uploadLive2DModel(
  zipFile: File,
  slug?: string,
): Promise<Live2DUploadResult> {
  const fd = new FormData();
  fd.append('file', zipFile);
  let url = `${BACKEND_BASE}/api/live2d/upload`;
  if (slug && slug.trim()) {
    url += `?slug=${encodeURIComponent(slug.trim())}`;
  }
  const res = await fetch(url, { method: 'POST', body: fd });
  if (!res.ok) {
    let msg = `upload live2d failed: ${res.status}`;
    try {
      const j = await res.json();
      if (j?.detail) msg = String(j.detail);
    } catch { /* ignore */ }
    const err = new Error(msg) as Error & { status?: number };
    err.status = res.status;
    throw err;
  }
  return (await res.json()) as Live2DUploadResult;
}
