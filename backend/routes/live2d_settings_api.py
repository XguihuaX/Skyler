"""2026-06-16 INV · per-Live2D-model 设置容器路由(framing 第一块)。

挂模型(model_key = scanner slug · 等于 frontend/public/live2d/<slug>/ 目录名 ·
也等于 character.live2d_model)· 不挂 character.id —— 模型原生比例决定怎么裁,
共用 slug 的角色共享 framing。

routes:
  GET   /api/live2d/models/{model_key}/settings
  PATCH /api/live2d/models/{model_key}/settings

PATCH 是 merge 语义 —— 读出现有容器 → {**existing, framing: new} → 写回。
其它键(将来的 param_map / director)透传不动,本期只写 framing。

clamp:scale ∈ [0.3, 5.0],offsetX/Y ∈ [-2000, 2000]。前端 + 后端双 clamp 防呆。
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_session
from backend.database.models import Live2DModelSettings

logger = logging.getLogger(__name__)
router = APIRouter()


# clamp 边界(跟前端 lib/live2d/settings.ts::clampFraming 同步;diff 即 bug)
_SCALE_MIN = 0.3
_SCALE_MAX = 5.0
_OFFSET_MIN = -2000.0
_OFFSET_MAX = 2000.0


class FramingBody(BaseModel):
    scale:   float = Field(..., description="放大倍率(叠加在 _fit base scale 上)")
    offsetX: float = Field(..., description="像素偏移(叠加在 _fit base position 上)")
    offsetY: float = Field(..., description="像素偏移(下移 / 上移 · 正数下移)")


class Live2DSettingsResponse(BaseModel):
    """整个容器原样返。前端按需读 framing 段。

    PM SPEC:容器里其它键(将来的 param_map / director)透传 · 不在本路由识别。
    """
    model_key: str
    framing: FramingBody
    # 整段透传:不识别的字段也带出来 · 给前端将来读 param_map / director 用
    extra: dict[str, Any] = Field(default_factory=dict)


class PatchFramingBody(BaseModel):
    framing: FramingBody


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _clamp_framing(f: FramingBody) -> FramingBody:
    return FramingBody(
        scale=_clamp(f.scale, _SCALE_MIN, _SCALE_MAX),
        offsetX=_clamp(f.offsetX, _OFFSET_MIN, _OFFSET_MAX),
        offsetY=_clamp(f.offsetY, _OFFSET_MIN, _OFFSET_MAX),
    )


def _default_framing() -> FramingBody:
    return FramingBody(scale=1.0, offsetX=0.0, offsetY=0.0)


def _parse_container(raw: Optional[str]) -> dict:
    """settings_json 字符串 → dict。空 / parse 失败 → {} · 不抛。"""
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning(
            "[live2d_settings] settings_json parse failed (%s) · 回退空容器",
            exc,
        )
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _extract_framing(container: dict) -> FramingBody:
    """容器里取 framing · 缺 / 格式错 → default_framing。"""
    framing_raw = container.get("framing")
    if not isinstance(framing_raw, dict):
        return _default_framing()
    try:
        return _clamp_framing(FramingBody(
            scale=float(framing_raw.get("scale", 1.0)),
            offsetX=float(framing_raw.get("offsetX", 0.0)),
            offsetY=float(framing_raw.get("offsetY", 0.0)),
        ))
    except (TypeError, ValueError):
        return _default_framing()


def _build_response(model_key: str, container: dict) -> Live2DSettingsResponse:
    framing = _extract_framing(container)
    extra = {k: v for k, v in container.items() if k != "framing"}
    return Live2DSettingsResponse(
        model_key=model_key, framing=framing, extra=extra,
    )


@router.get(
    "/live2d/models/{model_key}/settings",
    response_model=Live2DSettingsResponse,
)
async def get_live2d_model_settings(
    model_key: str,
    session: AsyncSession = Depends(get_session),
) -> Live2DSettingsResponse:
    """无 row → 返 default framing + 空 extra(不写库;首次 PATCH 才落盘)。"""
    row = (await session.execute(
        select(Live2DModelSettings).where(
            Live2DModelSettings.model_key == model_key
        )
    )).scalar_one_or_none()
    container = _parse_container(row.settings_json) if row else {}
    return _build_response(model_key, container)


@router.patch(
    "/live2d/models/{model_key}/settings",
    response_model=Live2DSettingsResponse,
)
async def patch_live2d_model_settings(
    model_key: str,
    body: PatchFramingBody,
    session: AsyncSession = Depends(get_session),
) -> Live2DSettingsResponse:
    """Merge 语义 · 只动 framing 段 · 其它键(param_map / director)透传不替换。

    无 row → INSERT;有 row → UPDATE settings_json + updated_at 自动 NOW。
    """
    clamped = _clamp_framing(body.framing)

    row = (await session.execute(
        select(Live2DModelSettings).where(
            Live2DModelSettings.model_key == model_key
        )
    )).scalar_one_or_none()

    container = _parse_container(row.settings_json) if row else {}
    container["framing"] = clamped.model_dump()
    new_json = json.dumps(container, ensure_ascii=False)

    if row is None:
        row = Live2DModelSettings(model_key=model_key, settings_json=new_json)
        session.add(row)
    else:
        row.settings_json = new_json
    try:
        await session.commit()
    except Exception as exc:  # noqa: BLE001
        await session.rollback()
        logger.exception(
            "[live2d_settings] PATCH model_key=%s 写入失败", model_key,
        )
        raise HTTPException(
            status_code=500, detail=f"settings write failed: {exc}",
        )
    return _build_response(model_key, container)
