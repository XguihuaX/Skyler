// 2026-06-16 INV · per-Live2D-model 设置容器(framing 第一块)。
//
// 挂模型(model_key = scanner slug · 等于 frontend/public/live2d/<slug>/ 目录名
// · 也等于 character.live2d_model)· 不挂 character.id —— 模型原生比例决定怎么裁,
// 共用 slug 的角色共享 framing。
//
// 后端真源:backend/routes/live2d_settings_api.py
// schema drift 时 tsc build 立即失败。
//
// clamp 边界跟后端 _SCALE_MIN/MAX + _OFFSET_MIN/MAX 同步;diff = bug。

const BACKEND_BASE = 'http://127.0.0.1:8000';

export interface Live2DFraming {
  /** 放大倍率 · 叠加在 pixiCubism4._fit 算出的 base scale 之上(乘) */
  scale:   number;
  /** 像素偏移 · 叠加在 base position 之上(加)· 正数右移 */
  offsetX: number;
  /** 像素偏移 · 正数下移(让脚出框 = 半身锚底) */
  offsetY: number;
}

export interface Live2DSettings {
  model_key: string;
  framing:   Live2DFraming;
  // 容器留扩展位:将来的 param_map / director 走 extra 透传 · 本期不读
  extra:     Record<string, unknown>;
}

export const DEFAULT_FRAMING: Live2DFraming = {
  scale:   1.0,
  offsetX: 0,
  offsetY: 0,
};

export const FRAMING_SCALE_MIN  = 0.3;
export const FRAMING_SCALE_MAX  = 5.0;
export const FRAMING_SCALE_STEP = 0.05;
export const FRAMING_OFFSET_MIN = -2000;
export const FRAMING_OFFSET_MAX =  2000;

export function clampFraming(f: Live2DFraming): Live2DFraming {
  const clamp = (v: number, lo: number, hi: number) =>
    Math.max(lo, Math.min(hi, v));
  return {
    scale:   clamp(f.scale,   FRAMING_SCALE_MIN,  FRAMING_SCALE_MAX),
    offsetX: clamp(f.offsetX, FRAMING_OFFSET_MIN, FRAMING_OFFSET_MAX),
    offsetY: clamp(f.offsetY, FRAMING_OFFSET_MIN, FRAMING_OFFSET_MAX),
  };
}

export function framingEqual(a: Live2DFraming, b: Live2DFraming): boolean {
  return a.scale === b.scale
      && a.offsetX === b.offsetX
      && a.offsetY === b.offsetY;
}

/** Slug 可能含中文(如 ``阿芙洛狄忒``)· 必须 encode 才能进 REST path · 后端
 *  FastAPI path param 自动 decode。 */
function _slugPath(slug: string): string {
  return encodeURIComponent(slug);
}

export async function fetchLive2DSettings(
  modelKey: string,
): Promise<Live2DSettings> {
  const res = await fetch(
    `${BACKEND_BASE}/api/live2d/models/${_slugPath(modelKey)}/settings`,
  );
  if (!res.ok) {
    throw new Error(`fetch live2d settings failed: ${res.status}`);
  }
  return (await res.json()) as Live2DSettings;
}

export async function patchLive2DFraming(
  modelKey: string,
  framing: Live2DFraming,
): Promise<Live2DSettings> {
  const res = await fetch(
    `${BACKEND_BASE}/api/live2d/models/${_slugPath(modelKey)}/settings`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ framing }),
    },
  );
  if (!res.ok) {
    let msg = `patch framing failed: ${res.status}`;
    try {
      const j = await res.json();
      if (j?.detail) msg = String(j.detail);
    } catch { /* ignore */ }
    throw new Error(msg);
  }
  return (await res.json()) as Live2DSettings;
}
