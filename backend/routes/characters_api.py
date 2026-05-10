"""Characters REST API.

Mounted at /api in main.py.  Full URL map:
  GET    /api/characters/list
  POST   /api/characters/create
  PATCH  /api/characters/{id}
  DELETE /api/characters/{id}
"""
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_session
from backend.database.models import Character

router = APIRouter()


DEFAULT_CHARACTER_NAME = "Momo"


def _fmt_dt(dt: Optional[datetime]) -> Optional[str]:
    return dt.strftime("%Y-%m-%d %H:%M:%S") if dt else None


def _to_dict(c: Character) -> dict:
    return {
        "id": c.id,
        "name": c.name,
        "persona": c.persona,
        "avatar_path": c.avatar_path,
        "voice_model": c.voice_model,
        "live2d_model": c.live2d_model,
        # v3-E2: per-character map JSON 字段。NULL → 前端 resolveCharacterMaps
        # 回退到 config/live2d.ts 全局默认。
        "emotion_map_json":  c.emotion_map_json,
        "motion_map_json":   c.motion_map_json,
        "hit_area_map_json": c.hit_area_map_json,
        # v3.5 chunk 5a: per-character 背景层 URL（image / video）。NULL =
        # 用现有 fallback 链（Live2D / 静态 jpeg），CharacterView 透明处理。
        "background_path":   c.background_path,
        "created_at": _fmt_dt(c.created_at),
    }


class CharacterCreateBody(BaseModel):
    name: str
    persona: str
    avatar_path: Optional[str] = None
    voice_model: Optional[str] = None
    live2d_model: Optional[str] = None
    # v3-E2: per-character maps（JSON 字符串），可选。Schema 不下放校验，
    # 前端 parse 失败兜底回退默认 + console.warn。
    emotion_map_json:  Optional[str] = None
    motion_map_json:   Optional[str] = None
    hit_area_map_json: Optional[str] = None
    # v3.5 chunk 5a: 可选背景资产 URL。None / 空串都视为"未配置"。
    background_path:   Optional[str] = None


class CharacterPatchBody(BaseModel):
    name: Optional[str] = None
    persona: Optional[str] = None
    avatar_path: Optional[str] = None
    voice_model: Optional[str] = None
    live2d_model: Optional[str] = None
    emotion_map_json:  Optional[str] = None
    motion_map_json:   Optional[str] = None
    hit_area_map_json: Optional[str] = None
    # v3.5 chunk 5a: PATCH 时传 None 表示清除；传字符串覆盖。
    background_path:   Optional[str] = None


@router.get("/characters/list")
async def list_characters(
    session: AsyncSession = Depends(get_session),
) -> List[dict]:
    rows = list((await session.execute(
        select(Character).order_by(Character.id.asc())
    )).scalars().all())
    return [_to_dict(c) for c in rows]


@router.post("/characters/create", status_code=201)
async def create_character(
    body: CharacterCreateBody,
    session: AsyncSession = Depends(get_session),
) -> dict:
    if not body.name.strip() or not body.persona.strip():
        raise HTTPException(status_code=422, detail="name and persona are required")
    existing = (await session.execute(
        select(Character).where(Character.name == body.name)
    )).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="character name already exists")
    c = Character(
        name=body.name,
        persona=body.persona,
        avatar_path=body.avatar_path,
        voice_model=body.voice_model,
        live2d_model=body.live2d_model,
        emotion_map_json=body.emotion_map_json,
        motion_map_json=body.motion_map_json,
        hit_area_map_json=body.hit_area_map_json,
        background_path=body.background_path,
    )
    session.add(c)
    await session.commit()
    await session.refresh(c)
    return _to_dict(c)


@router.patch("/characters/{character_id}")
async def patch_character(
    character_id: int,
    body: CharacterPatchBody,
    session: AsyncSession = Depends(get_session),
) -> dict:
    c = (await session.execute(
        select(Character).where(Character.id == character_id)
    )).scalar_one_or_none()
    if c is None:
        raise HTTPException(status_code=404, detail="character not found")
    updates = body.model_dump(exclude_unset=True)
    if "name" in updates and updates["name"]:
        c.name = updates["name"]
    if "persona" in updates and updates["persona"]:
        c.persona = updates["persona"]
    if "avatar_path" in updates:
        c.avatar_path = updates["avatar_path"]
    if "voice_model" in updates:
        c.voice_model = updates["voice_model"]
    if "live2d_model" in updates:
        c.live2d_model = updates["live2d_model"]
    if "emotion_map_json" in updates:
        c.emotion_map_json = updates["emotion_map_json"]
    if "motion_map_json" in updates:
        c.motion_map_json = updates["motion_map_json"]
    if "hit_area_map_json" in updates:
        c.hit_area_map_json = updates["hit_area_map_json"]
    if "background_path" in updates:
        # 空串等价 NULL，避免 frontend "(无)" 传空串时落库残留 ""
        bp = updates["background_path"]
        c.background_path = bp if (isinstance(bp, str) and bp.strip()) else None
    await session.commit()
    await session.refresh(c)
    return _to_dict(c)


@router.delete("/characters/{character_id}", status_code=204)
async def delete_character(
    character_id: int,
    session: AsyncSession = Depends(get_session),
) -> None:
    c = (await session.execute(
        select(Character).where(Character.id == character_id)
    )).scalar_one_or_none()
    if c is None:
        raise HTTPException(status_code=404, detail="character not found")
    if c.name == DEFAULT_CHARACTER_NAME:
        raise HTTPException(status_code=403, detail="cannot delete the default Momo character")
    await session.delete(c)
    await session.commit()
