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
