// v3.5 chunk 5a — frontend API client for /api/backgrounds.
//
// 与 lib/live2d.ts 平行。schema 后端 single source of truth（typing_extensions
// TypedDict → FastAPI response_model），前端类型 drift 时立刻 build error。

const BACKEND_BASE = 'http://127.0.0.1:8000';

// 与 backend/services/backgrounds_scanner.py BackgroundInfo 对齐
export interface BackgroundItem {
  name: string;          // 不含后缀的展示名
  path: string;          // /-prefixed Vite URL，前端可直接放进 src
  type: 'image' | 'video';
  size: number;          // 字节
}

export interface BackgroundsScanResponse {
  scan_dir: string;
  items: BackgroundItem[];
}

export async function fetchBackgrounds(): Promise<BackgroundsScanResponse> {
  const res = await fetch(`${BACKEND_BASE}/api/backgrounds`);
  if (!res.ok) throw new Error(`fetch backgrounds failed: ${res.status}`);
  return (await res.json()) as BackgroundsScanResponse;
}
