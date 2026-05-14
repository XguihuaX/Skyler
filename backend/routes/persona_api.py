"""v4 segment 2 — character_personas REST API.

Mounted at /api in main.py。URL map:
  GET    /api/characters/{character_id}/personas
  GET    /api/characters/{character_id}/personas/active
  GET    /api/personas/{persona_id}
  POST   /api/characters/{character_id}/personas    body=Tier-1+2 JSON
  PATCH  /api/personas/{persona_id}                 body=partial Tier-1+2 JSON
  DELETE /api/personas/{persona_id}                 (is_active=1 → 422)
  POST   /api/personas/{persona_id}/activate
  POST   /api/personas/{persona_id}/restore_to_builtin

Response shape:**所有 Tier-1 7 字段 + Tier-2 4 字段已 json.loads**(前端
拿到不用二次 parse)。

Tier-1 必填(POST 时):identity / personality_core / speech_style /
signature_phrases / voice_samples / forbidden_phrases / relationship_to_user。
Tier-2 可选:taboo_topics / lore / capability_overrides / style_preset。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import AsyncSessionLocal, get_session
from backend.database.models import Character, CharacterPersona

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_json_loads(value: Optional[str], default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default


def _to_dict(p: CharacterPersona) -> dict:
    """Flatten ORM → JSON-parsed dict for API response。"""
    return {
        "id": p.id,
        "character_id": p.character_id,
        "variant_name": p.variant_name,
        "is_builtin": bool(p.is_builtin),
        "is_active": bool(p.is_active),
        "display_order": int(p.display_order or 0),
        "description": p.description,
        "identity":             _safe_json_loads(p.identity, {}),
        "personality_core":     _safe_json_loads(p.personality_core, {}),
        "speech_style":         _safe_json_loads(p.speech_style, {}),
        "signature_phrases":    _safe_json_loads(p.signature_phrases, []),
        "voice_samples":        _safe_json_loads(p.voice_samples, []),
        "forbidden_phrases":    _safe_json_loads(p.forbidden_phrases, {}),
        "relationship_to_user": _safe_json_loads(p.relationship_to_user, {}),
        "taboo_topics":          _safe_json_loads(p.taboo_topics, None),
        "lore":                  _safe_json_loads(p.lore, None),
        "capability_overrides":  _safe_json_loads(p.capability_overrides, None),
        "style_preset": p.style_preset or "anime_classic",
        "created_at": p.created_at.strftime("%Y-%m-%d %H:%M:%S") if p.created_at else None,
        "updated_at": p.updated_at.strftime("%Y-%m-%d %H:%M:%S") if p.updated_at else None,
    }


# Tier-1 7 字段必填的 key 集合。POST 时检查。
_TIER1_REQUIRED = (
    "identity", "personality_core", "speech_style",
    "signature_phrases", "voice_samples", "forbidden_phrases",
    "relationship_to_user",
)

# 所有可写字段名 → ORM 列名 + 是否是 JSON 字段
_WRITABLE_FIELDS = {
    # 标量字段:直接写 ORM 列
    "variant_name":  ("variant_name", False),
    "description":   ("description", False),
    "style_preset":  ("style_preset", False),
    "display_order": ("display_order", False),
    # JSON-in-TEXT 字段:dict / list → json.dumps 再写
    "identity":             ("identity", True),
    "personality_core":     ("personality_core", True),
    "speech_style":         ("speech_style", True),
    "signature_phrases":    ("signature_phrases", True),
    "voice_samples":        ("voice_samples", True),
    "forbidden_phrases":    ("forbidden_phrases", True),
    "relationship_to_user": ("relationship_to_user", True),
    "taboo_topics":         ("taboo_topics", True),
    "lore":                 ("lore", True),
    "capability_overrides": ("capability_overrides", True),
}


def _apply_writable_fields(p: CharacterPersona, body: dict) -> None:
    """把 body 里出现的可写字段写到 ORM 实例(不 commit)。"""
    for key, value in body.items():
        if key not in _WRITABLE_FIELDS:
            continue
        col_name, is_json = _WRITABLE_FIELDS[key]
        if is_json:
            if value is None:
                setattr(p, col_name, None)
            else:
                setattr(p, col_name, json.dumps(value, ensure_ascii=False))
        else:
            setattr(p, col_name, value)


# ---------------------------------------------------------------------------
# Pydantic body schemas(create / patch 共用宽容 dict body —— Tier-1 字段
# 类型在 server-side 做最小校验,避免 pydantic 跟 jinja 的 dict 形状不一致。)
# ---------------------------------------------------------------------------

class CreatePersonaBody(BaseModel):
    variant_name: str = Field(..., min_length=1, max_length=128)
    description: Optional[str] = None
    style_preset: Optional[str] = None
    display_order: int = 0
    identity: Dict[str, Any]
    personality_core: Dict[str, Any]
    speech_style: Dict[str, Any]
    signature_phrases: List[Any]
    voice_samples: List[Any]
    forbidden_phrases: Dict[str, Any]
    relationship_to_user: Dict[str, Any]
    taboo_topics: Optional[Any] = None
    lore: Optional[Any] = None
    capability_overrides: Optional[Any] = None


class PatchPersonaBody(BaseModel):
    """全字段可选;只更新出现的 key。pydantic 直接接 dict-like JSON。"""
    variant_name: Optional[str] = None
    description: Optional[str] = None
    style_preset: Optional[str] = None
    display_order: Optional[int] = None
    identity: Optional[Dict[str, Any]] = None
    personality_core: Optional[Dict[str, Any]] = None
    speech_style: Optional[Dict[str, Any]] = None
    signature_phrases: Optional[List[Any]] = None
    voice_samples: Optional[List[Any]] = None
    forbidden_phrases: Optional[Dict[str, Any]] = None
    relationship_to_user: Optional[Dict[str, Any]] = None
    taboo_topics: Optional[Any] = None
    lore: Optional[Any] = None
    capability_overrides: Optional[Any] = None


# ---------------------------------------------------------------------------
# Endpoints — list / read
# ---------------------------------------------------------------------------

@router.get("/characters/{character_id}/personas")
async def list_personas(
    character_id: int,
    session: AsyncSession = Depends(get_session),
) -> List[dict]:
    """List all persona variants for ``character_id`` (ordered by display_order, then id)。"""
    result = await session.execute(
        select(CharacterPersona).where(
            CharacterPersona.character_id == character_id,
        ).order_by(
            CharacterPersona.display_order, CharacterPersona.id,
        )
    )
    rows = result.scalars().all()
    return [_to_dict(p) for p in rows]


@router.get("/characters/{character_id}/personas/active")
async def get_active_persona(
    character_id: int,
    session: AsyncSession = Depends(get_session),
) -> dict:
    result = await session.execute(
        select(CharacterPersona).where(
            CharacterPersona.character_id == character_id,
            CharacterPersona.is_active == True,  # noqa: E712
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"No active persona for character_id={character_id}",
        )
    return _to_dict(row)


@router.get("/personas/{persona_id}")
async def get_persona(
    persona_id: int,
    session: AsyncSession = Depends(get_session),
) -> dict:
    p = await session.get(CharacterPersona, persona_id)
    if p is None:
        raise HTTPException(status_code=404, detail=f"persona id={persona_id} not found")
    return _to_dict(p)


# ---------------------------------------------------------------------------
# Endpoints — create / update / delete
# ---------------------------------------------------------------------------

@router.post("/characters/{character_id}/personas")
async def create_persona(
    character_id: int,
    body: CreatePersonaBody,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Create a new user-custom variant (is_builtin=0, is_active=0)。"""
    # 1. character 存在性检查
    char = await session.get(Character, character_id)
    if char is None:
        raise HTTPException(
            status_code=404, detail=f"character id={character_id} not found",
        )

    # 2. variant_name 唯一性检查(UniqueConstraint 也会兜底,提前 400)
    dup = (await session.execute(
        select(CharacterPersona).where(
            CharacterPersona.character_id == character_id,
            CharacterPersona.variant_name == body.variant_name,
        )
    )).scalar_one_or_none()
    if dup is not None:
        raise HTTPException(
            status_code=409,
            detail=f"variant_name={body.variant_name!r} already exists for character_id={character_id}",
        )

    p = CharacterPersona(
        character_id=character_id,
        variant_name=body.variant_name,
        is_builtin=False,
        is_active=False,
        display_order=body.display_order,
        description=body.description,
        style_preset=body.style_preset or "anime_classic",
        identity=             json.dumps(body.identity,             ensure_ascii=False),
        personality_core=     json.dumps(body.personality_core,     ensure_ascii=False),
        speech_style=         json.dumps(body.speech_style,         ensure_ascii=False),
        signature_phrases=    json.dumps(body.signature_phrases,    ensure_ascii=False),
        voice_samples=        json.dumps(body.voice_samples,        ensure_ascii=False),
        forbidden_phrases=    json.dumps(body.forbidden_phrases,    ensure_ascii=False),
        relationship_to_user= json.dumps(body.relationship_to_user, ensure_ascii=False),
        taboo_topics=         json.dumps(body.taboo_topics, ensure_ascii=False) if body.taboo_topics is not None else None,
        lore=                 json.dumps(body.lore, ensure_ascii=False) if body.lore is not None else None,
        capability_overrides= json.dumps(body.capability_overrides, ensure_ascii=False) if body.capability_overrides is not None else None,
    )
    session.add(p)
    await session.commit()
    await session.refresh(p)
    logger.info(
        "[persona_api] created persona id=%s character_id=%s variant=%s",
        p.id, character_id, body.variant_name,
    )
    return _to_dict(p)


@router.patch("/personas/{persona_id}")
async def patch_persona(
    persona_id: int,
    body: PatchPersonaBody,
    session: AsyncSession = Depends(get_session),
) -> dict:
    p = await session.get(CharacterPersona, persona_id)
    if p is None:
        raise HTTPException(status_code=404, detail=f"persona id={persona_id} not found")
    # pydantic dump 时排除 None(以 model_dump 兼容 v1/v2 写两种 fallback)
    body_dict = body.model_dump(exclude_unset=True) if hasattr(body, "model_dump") else body.dict(exclude_unset=True)
    if not body_dict:
        return _to_dict(p)

    # variant_name 修改时检查唯一性
    if "variant_name" in body_dict and body_dict["variant_name"] != p.variant_name:
        dup = (await session.execute(
            select(CharacterPersona).where(
                CharacterPersona.character_id == p.character_id,
                CharacterPersona.variant_name == body_dict["variant_name"],
                CharacterPersona.id != p.id,
            )
        )).scalar_one_or_none()
        if dup is not None:
            raise HTTPException(
                status_code=409,
                detail=f"variant_name={body_dict['variant_name']!r} already exists",
            )

    _apply_writable_fields(p, body_dict)
    p.updated_at = datetime.utcnow()
    await session.commit()
    await session.refresh(p)
    logger.info(
        "[persona_api] patched persona id=%s fields=%s",
        persona_id, sorted(body_dict.keys()),
    )
    return _to_dict(p)


@router.delete("/personas/{persona_id}")
async def delete_persona(
    persona_id: int,
    session: AsyncSession = Depends(get_session),
) -> dict:
    p = await session.get(CharacterPersona, persona_id)
    if p is None:
        raise HTTPException(status_code=404, detail=f"persona id={persona_id} not found")
    if p.is_active:
        raise HTTPException(
            status_code=409,
            detail="active variant cannot be deleted; activate another variant first",
        )
    cid, name = p.character_id, p.variant_name
    await session.delete(p)
    await session.commit()
    logger.info(
        "[persona_api] deleted persona id=%s character_id=%s variant=%s",
        persona_id, cid, name,
    )
    return {"ok": True, "deleted_id": persona_id}


# ---------------------------------------------------------------------------
# Endpoints — activate / restore_to_builtin
# ---------------------------------------------------------------------------

@router.post("/personas/{persona_id}/activate")
async def activate_persona(
    persona_id: int,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Activate variant + deactivate其他 same-character variants。

    partial UNIQUE INDEX 阻止同 character 双 is_active,所以这里必须**先**清
    旧 active 再设新 active。两步同 transaction。
    """
    p = await session.get(CharacterPersona, persona_id)
    if p is None:
        raise HTTPException(status_code=404, detail=f"persona id={persona_id} not found")
    if p.is_active:
        # 已 active,no-op + 返当前
        return {**_to_dict(p), "just_switched": False}

    # 1. 先 deactivate 同 character 当前 active
    await session.execute(sa_text(
        "UPDATE character_personas SET is_active = 0, updated_at = CURRENT_TIMESTAMP "
        "WHERE character_id = :cid AND id != :pid AND is_active = 1"
    ), {"cid": p.character_id, "pid": persona_id})

    # 2. 再 activate 目标
    p.is_active = True
    p.updated_at = datetime.utcnow()
    await session.commit()
    await session.refresh(p)
    logger.info(
        "[persona_api] activated persona id=%s character_id=%s variant=%s",
        persona_id, p.character_id, p.variant_name,
    )
    # session flag just_switched_variant 由前端在下一次 chat_msg 发送时
    # 透传给 ChatAgent.stream(context.just_switched_variant=True)。本 API
    # 直接告知前端是否真的发生了切换。
    return {**_to_dict(p), "just_switched": True}


@router.post("/personas/{persona_id}/restore_to_builtin")
async def restore_to_builtin(
    persona_id: int,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Reset variant 字段为 ``character_personas_builtin_seed`` 备份的初始值。

    约束:**must be is_builtin=1**。用户自定义的非 builtin variant 无 seed
    backup,不能 restore(应该用 DELETE)。
    """
    p = await session.get(CharacterPersona, persona_id)
    if p is None:
        raise HTTPException(status_code=404, detail=f"persona id={persona_id} not found")
    if not p.is_builtin:
        raise HTTPException(
            status_code=409,
            detail="only builtin variant has seed backup; user variant 应该用 DELETE",
        )

    # 拉 seed
    row = (await session.execute(sa_text(
        "SELECT seed_data FROM character_personas_builtin_seed "
        "WHERE character_id = :cid AND variant_name = :vn"
    ), {"cid": p.character_id, "vn": p.variant_name})).first()
    if row is None:
        raise HTTPException(
            status_code=500,
            detail=f"no seed backup for character_id={p.character_id} variant={p.variant_name!r}",
        )
    seed = _safe_json_loads(row[0], None)
    if not isinstance(seed, dict):
        raise HTTPException(
            status_code=500,
            detail="seed_data corrupt (not a dict after json.loads)",
        )

    # Apply seed dict's 7 Tier-1 字段(+ Tier-2 if present)。**不动**
    # is_active / is_builtin / variant_name / display_order / description /
    # style_preset(用户编辑的元数据保留;只重置 persona 内核 7+4 字段)。
    _apply_writable_fields(p, seed)
    p.updated_at = datetime.utcnow()
    await session.commit()
    await session.refresh(p)
    logger.info(
        "[persona_api] restored persona id=%s to builtin seed", persona_id,
    )
    return _to_dict(p)
