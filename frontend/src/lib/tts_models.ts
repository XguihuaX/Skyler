// INV (2026-06-11) · TTS Models CRUD wrapper · 跟 backend/routes/tts_models_api.py 对接。
//
// PM SPEC-LOCK:仅 provider='gsv' 用此表 · CRUD 后 backend reload tts_models_cache ·
// 前端 GsvTTSCard 调 refresh 重 fetch /api/tts/providers 看新 model 列表。

const BACKEND_BASE = 'http://127.0.0.1:8000';

export interface TtsModel {
  id: number;
  provider: 'gsv' | 'fish' | 'cosyvoice';
  model_id: string;
  label: string;
  mode?: string | null;
  tts_language?: string | null;
  gpt_weights?: string | null;
  sovits_weights?: string | null;
  lab_dir?: string | null;
  wav_remote_dir?: string | null;
  default_emotion?: string | null;
  inference_params?: Record<string, unknown> | null;
  enabled: boolean;
  builtin: boolean;
}

export interface TtsModelCreate {
  provider: 'gsv' | 'fish' | 'cosyvoice';
  model_id: string;
  label: string;
  mode?: string;
  tts_language?: 'zh' | 'ja' | 'en';
  gpt_weights?: string;
  sovits_weights?: string;
  lab_dir?: string;
  wav_remote_dir?: string;
  default_emotion?: string;
  inference_params?: Record<string, unknown>;
}

export type TtsModelPatch = Partial<TtsModelCreate> & { enabled?: boolean };

export async function listTtsModels(provider?: string): Promise<TtsModel[]> {
  const url = provider
    ? `${BACKEND_BASE}/api/tts/models?provider=${encodeURIComponent(provider)}`
    : `${BACKEND_BASE}/api/tts/models`;
  const r = await fetch(url);
  if (!r.ok) throw new Error(`listTtsModels HTTP ${r.status}`);
  const j = (await r.json()) as { models: TtsModel[] };
  return j.models;
}

export async function createTtsModel(body: TtsModelCreate): Promise<TtsModel> {
  const r = await fetch(`${BACKEND_BASE}/api/tts/models`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const detail = await r.text();
    throw new Error(`createTtsModel HTTP ${r.status}: ${detail}`);
  }
  return r.json();
}

export async function patchTtsModel(
  id: number, body: TtsModelPatch,
): Promise<TtsModel> {
  const r = await fetch(`${BACKEND_BASE}/api/tts/models/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const detail = await r.text();
    throw new Error(`patchTtsModel HTTP ${r.status}: ${detail}`);
  }
  return r.json();
}

export async function deleteTtsModel(id: number): Promise<void> {
  const r = await fetch(`${BACKEND_BASE}/api/tts/models/${id}`, {
    method: 'DELETE',
  });
  if (r.status !== 204) {
    const detail = await r.text();
    throw new Error(`deleteTtsModel HTTP ${r.status}: ${detail}`);
  }
}

// ---- Global GSV server_url ----

export interface GsvServerUrl {
  server_url: string | null;
  source: 'global' | 'default';
}

export async function getGsvServerUrl(): Promise<GsvServerUrl> {
  const r = await fetch(`${BACKEND_BASE}/api/tts/gsv/server_url`);
  if (!r.ok) throw new Error(`getGsvServerUrl HTTP ${r.status}`);
  return r.json();
}

export async function setGsvServerUrl(
  server_url: string | null,
): Promise<GsvServerUrl> {
  const r = await fetch(`${BACKEND_BASE}/api/tts/gsv/server_url`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ server_url }),
  });
  if (!r.ok) {
    const detail = await r.text();
    throw new Error(`setGsvServerUrl HTTP ${r.status}: ${detail}`);
  }
  return r.json();
}

// ---- Emotion coverage (read-only view) ----

export interface EmotionCoverageEntry {
  name: string;
  has_local_lab: boolean;
  lab_size?: number | null;
  lab_preview?: string | null;
}

export interface EmotionCoverage {
  model_id: string;
  lab_dir: string | null;
  default_emotion: string | null;
  default_present: boolean;
  emotions: EmotionCoverageEntry[];
}

export async function getEmotionCoverage(modelId: string): Promise<EmotionCoverage> {
  const r = await fetch(
    `${BACKEND_BASE}/api/tts/gsv/models/${encodeURIComponent(modelId)}/emotion_coverage`,
  );
  if (!r.ok) throw new Error(`getEmotionCoverage HTTP ${r.status}`);
  return r.json();
}
