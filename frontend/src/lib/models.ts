// v3-G chunk 1.7 — LLM 模型切换 API client
//
// Backend：backend/routes/settings_api.py
//   GET  /api/settings/model  → { current, available }
//   POST /api/settings/model  body { model } → 同上 shape
//
// 切换是热的：写回 config.yaml 后端立即 reload，下一条用户消息就用新 model。

const BACKEND_BASE = 'http://127.0.0.1:8000';

export type ModelTier = 'stable' | 'preview';

export interface ModelInfo {
  id: string;
  display_name: string;
  description: string;
  tier: ModelTier;
}

export interface ModelState {
  current: string;
  available: ModelInfo[];
}

export async function fetchModels(): Promise<ModelState> {
  const r = await fetch(`${BACKEND_BASE}/api/settings/model`);
  if (!r.ok) throw new Error(`fetch models failed: ${r.status}`);
  return (await r.json()) as ModelState;
}

export async function setModel(modelId: string): Promise<ModelState> {
  const r = await fetch(`${BACKEND_BASE}/api/settings/model`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model: modelId }),
  });
  if (!r.ok) {
    let detail = `set model failed: ${r.status}`;
    try {
      const body = await r.json();
      if (body?.detail) detail = String(body.detail);
    } catch {/* keep default */}
    throw new Error(detail);
  }
  return (await r.json()) as ModelState;
}
