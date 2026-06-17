"""TTS Models CRUD REST API · INV (2026-06-11)。

Mounted at /api in main.py. URL map:
  GET    /api/tts/models?provider=gsv          list (optional filter)
  POST   /api/tts/models                       create
  GET    /api/tts/models/{id}                  detail
  PATCH  /api/tts/models/{id}                  update
  DELETE /api/tts/models/{id}                  delete (builtin 也允许)

PM SPEC-LOCK:
  - 仅 provider='gsv' 用此表 · 字段集偏 GSV(weights / lab_dir / wav_remote_dir
    / inference_params / default_emotion)· fish/cosyvoice 仍走 tts_models.json
  - CRUD setter 写 DB 后 reload tts_models_cache · 同步给 GSVTTS / registry
  - 加 model 表单不含 server_url(全局 · 走 ai_providers)、不含 emotion 列表
    (动态来源 = lab_dir/*.lab glob,加 model 后用户单独 upload .lab)
  - builtin row DELETE 允许 · 类比 ai_providers builtin policy
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text

from backend.database import engine
from backend.tts.tts_models_cache import reload_gsv_models_cache

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class TtsModelCreate(BaseModel):
    provider: str = Field(..., pattern="^(gsv|fish|cosyvoice)$")
    model_id: str = Field(..., min_length=1, max_length=120)
    label: str = Field(..., min_length=1, max_length=200)
    mode: Optional[str] = Field(default="trained", max_length=40)
    tts_language: Optional[str] = Field(default=None, pattern="^(zh|ja|en)?$")
    gpt_weights: Optional[str] = Field(default=None, max_length=400)
    sovits_weights: Optional[str] = Field(default=None, max_length=400)
    lab_dir: Optional[str] = Field(default=None, max_length=400)
    wav_remote_dir: Optional[str] = Field(default=None, max_length=400)
    default_emotion: Optional[str] = Field(default=None, max_length=80)
    inference_params: Optional[dict[str, Any]] = Field(default=None)


class TtsModelPatch(BaseModel):
    label: Optional[str] = Field(default=None, min_length=1, max_length=200)
    mode: Optional[str] = Field(default=None, max_length=40)
    tts_language: Optional[str] = Field(default=None, pattern="^(zh|ja|en)?$")
    gpt_weights: Optional[str] = Field(default=None, max_length=400)
    sovits_weights: Optional[str] = Field(default=None, max_length=400)
    lab_dir: Optional[str] = Field(default=None, max_length=400)
    wav_remote_dir: Optional[str] = Field(default=None, max_length=400)
    default_emotion: Optional[str] = Field(default=None, max_length=80)
    inference_params: Optional[dict[str, Any]] = Field(default=None)
    enabled: Optional[bool] = Field(default=None)


class TtsModelOut(BaseModel):
    id: int
    provider: str
    model_id: str
    label: str
    mode: Optional[str] = None
    tts_language: Optional[str] = None
    gpt_weights: Optional[str] = None
    sovits_weights: Optional[str] = None
    lab_dir: Optional[str] = None
    wav_remote_dir: Optional[str] = None
    default_emotion: Optional[str] = None
    inference_params: Optional[dict[str, Any]] = None
    enabled: bool
    builtin: bool


class TtsModelsListResponse(BaseModel):
    models: list[TtsModelOut]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_COLS = (
    "id, provider, model_id, label, mode, tts_language, "
    "gpt_weights, sovits_weights, lab_dir, wav_remote_dir, "
    "default_emotion, inference_params, enabled, builtin"
)


def _row_to_out(row: Any) -> TtsModelOut:
    (id_, provider, model_id, label, mode, tts_language,
     gpt_weights, sovits_weights, lab_dir, wav_remote_dir,
     default_emotion, inference_params, enabled, builtin) = row
    ip: Optional[dict[str, Any]] = None
    if inference_params:
        try:
            parsed = json.loads(inference_params)
            if isinstance(parsed, dict):
                ip = parsed
        except (json.JSONDecodeError, TypeError):
            ip = None
    return TtsModelOut(
        id=int(id_),
        provider=str(provider),
        model_id=str(model_id),
        label=str(label),
        mode=mode,
        tts_language=tts_language,
        gpt_weights=gpt_weights,
        sovits_weights=sovits_weights,
        lab_dir=lab_dir,
        wav_remote_dir=wav_remote_dir,
        default_emotion=default_emotion,
        inference_params=ip,
        enabled=bool(enabled),
        builtin=bool(builtin),
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/tts/models", response_model=TtsModelsListResponse)
async def list_tts_models(
    provider: Optional[str] = Query(None, pattern="^(gsv|fish|cosyvoice)$"),
) -> TtsModelsListResponse:
    async with engine.begin() as conn:
        if provider:
            rows = (await conn.execute(text(
                f"SELECT {_COLS} FROM tts_models WHERE provider=:p ORDER BY id"
            ), {"p": provider})).fetchall()
        else:
            rows = (await conn.execute(text(
                f"SELECT {_COLS} FROM tts_models ORDER BY provider, id"
            ))).fetchall()
    return TtsModelsListResponse(models=[_row_to_out(r) for r in rows])


@router.post("/tts/models", response_model=TtsModelOut, status_code=201)
async def create_tts_model(body: TtsModelCreate) -> TtsModelOut:
    ip_json = json.dumps(body.inference_params) if body.inference_params else None
    async with engine.begin() as conn:
        # 业务唯一 key 校验
        existing = (await conn.execute(text(
            "SELECT id FROM tts_models WHERE provider=:p AND model_id=:m"
        ), {"p": body.provider, "m": body.model_id})).first()
        if existing:
            raise HTTPException(
                status_code=409,
                detail=f"(provider={body.provider}, model_id={body.model_id}) "
                       f"already exists (id={existing[0]})",
            )
        result = await conn.execute(text("""
            INSERT INTO tts_models (
                provider, model_id, label, mode, tts_language,
                gpt_weights, sovits_weights, lab_dir, wav_remote_dir,
                default_emotion, inference_params, enabled, builtin
            ) VALUES (
                :provider, :model_id, :label, :mode, :tts_language,
                :gpt_weights, :sovits_weights, :lab_dir, :wav_remote_dir,
                :default_emotion, :inference_params, 1, 0
            )
        """), {
            "provider": body.provider,
            "model_id": body.model_id,
            "label": body.label,
            "mode": body.mode,
            "tts_language": body.tts_language,
            "gpt_weights": body.gpt_weights,
            "sovits_weights": body.sovits_weights,
            "lab_dir": body.lab_dir,
            "wav_remote_dir": body.wav_remote_dir,
            "default_emotion": body.default_emotion,
            "inference_params": ip_json,
        })
        new_id = int(result.lastrowid)  # type: ignore[attr-defined]
        row = (await conn.execute(
            text(f"SELECT {_COLS} FROM tts_models WHERE id=:i"), {"i": new_id},
        )).first()
    if body.provider == "gsv":
        reload_gsv_models_cache()
    return _row_to_out(row)


@router.get("/tts/models/{model_pk}", response_model=TtsModelOut)
async def get_tts_model(model_pk: int) -> TtsModelOut:
    async with engine.begin() as conn:
        row = (await conn.execute(
            text(f"SELECT {_COLS} FROM tts_models WHERE id=:i"),
            {"i": model_pk},
        )).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"tts_model {model_pk} not found")
    return _row_to_out(row)


@router.patch("/tts/models/{model_pk}", response_model=TtsModelOut)
async def patch_tts_model(model_pk: int, body: TtsModelPatch) -> TtsModelOut:
    fields: list[str] = []
    params: dict[str, Any] = {"id": model_pk}
    for field_name in (
        "label", "mode", "tts_language", "gpt_weights", "sovits_weights",
        "lab_dir", "wav_remote_dir", "default_emotion",
    ):
        v = getattr(body, field_name)
        if v is not None:
            fields.append(f"{field_name} = :{field_name}")
            params[field_name] = v
    if body.inference_params is not None:
        fields.append("inference_params = :inference_params")
        params["inference_params"] = json.dumps(body.inference_params)
    if body.enabled is not None:
        fields.append("enabled = :enabled")
        params["enabled"] = 1 if body.enabled else 0
    if not fields:
        # no-op · 返当前值
        return await get_tts_model(model_pk)
    fields.append("updated_at = CURRENT_TIMESTAMP")
    async with engine.begin() as conn:
        result = await conn.execute(text(
            f"UPDATE tts_models SET {', '.join(fields)} WHERE id=:id"
        ), params)
        if result.rowcount == 0:  # type: ignore[attr-defined]
            raise HTTPException(
                status_code=404, detail=f"tts_model {model_pk} not found",
            )
        row = (await conn.execute(
            text(f"SELECT {_COLS} FROM tts_models WHERE id=:i"),
            {"i": model_pk},
        )).first()
    if row and row[1] == "gsv":  # provider
        reload_gsv_models_cache()
    return _row_to_out(row)


@router.delete("/tts/models/{model_pk}", status_code=204)
async def delete_tts_model(model_pk: int) -> None:
    """Delete tts_model · builtin 也允许(类比 ai_providers builtin policy)。

    删了不复活:migrate_inv_tts_models_table_and_seed 的 INSERT 仅在 CREATE
    TABLE 分支内执行 · 重启不会重塞 mai_v4。需要复活手动 INSERT 或 POST。
    """
    async with engine.begin() as conn:
        row = (await conn.execute(
            text("SELECT provider FROM tts_models WHERE id=:i"),
            {"i": model_pk},
        )).first()
        if not row:
            raise HTTPException(
                status_code=404, detail=f"tts_model {model_pk} not found",
            )
        provider = row[0]
        await conn.execute(
            text("DELETE FROM tts_models WHERE id=:i"), {"i": model_pk},
        )
    if provider == "gsv":
        reload_gsv_models_cache()
