"""Memory panel REST API.

Mounted at /api in main.py.  Full URL map:
  GET    /api/memory/list
  POST   /api/memory/add
  PATCH  /api/memory/{id}
  DELETE /api/memory/{id}

(2026-05-19: /api/todos/* + bare /api/profile 已退役 — todos 链路全清,
profile_summary 由 chunk 11 profile_data 取代;真"用户画像"前端走
/api/users/{uid}/profile_data。)
"""
import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

from backend.config import config_yaml
from backend.database import get_session
from backend.database.models import Memory
from backend.database.services import (
    add_memory as db_add_memory,
    delete_memory as db_delete_memory,
    get_all_memories,
)

_MEMORY_TYPES = {"fact", "instruction", "emotion", "activity", "daily"}

router = APIRouter()

_DEFAULT_UID: str = config_yaml.get("default_user_id", "default")


def _uid(user_id: Optional[str]) -> str:
    return (user_id or "").strip() or _DEFAULT_UID


def _fmt_dt(dt: Optional[datetime]) -> Optional[str]:
    return dt.strftime("%Y-%m-%d %H:%M:%S") if dt else None


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class MemoryAddBody(BaseModel):
    role: str
    type: str
    content: str
    expires_at: Optional[datetime] = None
    user_id: Optional[str] = None


class MemoryPatchBody(BaseModel):
    content: Optional[str] = None
    type: Optional[str] = None
    expires_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# /memory
# ---------------------------------------------------------------------------

@router.get("/memory/list")
async def list_memories(
    user_id: Optional[str] = Query(None),
    character_id: Optional[int] = Query(None),
    active_only: bool = Query(True),
    session: AsyncSession = Depends(get_session),
) -> List[dict]:
    """v3.5 chunk 9 Part 3：默认返 user 级**全部** memory（不按当前角色过滤）。

    ``character_id`` query param 仍保留 —— 用户在 MemoryManagerDrawer 若
    主动按角色筛选可显式传值；不传则返当前 user 在所有角色下的 memory。
    save_memory tool 仍记录 character_id（来源 audit），UI 通过 ``[由 Momo
    记] / [由八重神子记]`` 角标显示来源。
    """
    rows = await get_all_memories(
        session,
        _uid(user_id),
        active_only=active_only,
        character_id=character_id,
    )
    return [
        {
            "id": m.id,
            "user_id": m.user_id,
            "character_id": m.character_id,
            "role": m.role,
            "type": m.type,
            "content": m.content,
            "expires_at": _fmt_dt(m.expires_at),
            "created_at": _fmt_dt(m.created_at),
            # v3.5 chunk 10：新字段（commit 1 加列）
            "entry_type": m.entry_type,
            "extraction_source": m.extraction_source or "legacy",
            "confidence": m.confidence,
            "extracted_at": _fmt_dt(m.extracted_at),
            "source_turn_id": m.source_turn_id,
        }
        for m in rows
    ]


@router.post("/memory/add", status_code=201)
async def add_memory_endpoint(
    body: MemoryAddBody,
    session: AsyncSession = Depends(get_session),
) -> dict:
    uid = _uid(body.user_id)

    # Generate embedding; on failure, log and persist the row with embedding=NULL
    # so the user's add operation still succeeds.
    embedding_blob: Optional[bytes] = None
    try:
        from backend.memory.long_term import generate_embedding
        embedding_blob = await generate_embedding(body.content)
    except Exception as e:
        logger.error(
            "Embedding generation failed for content '%s...': %s",
            body.content[:50], e,
        )

    m = await db_add_memory(
        session,
        user_id=uid,
        role=body.role,
        type=body.type,
        content=body.content,
        embedding=embedding_blob,
        expires_at=body.expires_at,
    )
    return {
        "id": m.id,
        "user_id": m.user_id,
        "role": m.role,
        "type": m.type,
        "content": m.content,
        "expires_at": _fmt_dt(m.expires_at),
        "created_at": _fmt_dt(m.created_at),
    }


@router.patch("/memory/{memory_id}", status_code=200)
async def update_memory_endpoint(
    memory_id: int,
    body: MemoryPatchBody,
    session: AsyncSession = Depends(get_session),
) -> dict:
    result = await session.execute(select(Memory).where(Memory.id == memory_id))
    m = result.scalar_one_or_none()
    if m is None:
        raise HTTPException(status_code=404, detail="memory not found")

    updates = body.model_dump(exclude_unset=True)

    if "type" in updates and updates["type"] not in _MEMORY_TYPES:
        raise HTTPException(status_code=422, detail="invalid type")

    if "content" in updates:
        new_content = updates["content"] or ""
        m.content = new_content
        try:
            from backend.memory.long_term import generate_embedding
            m.embedding = await generate_embedding(new_content)
        except Exception as e:
            # Embedding generation failed — keep the row but flag for re-encoding later.
            import logging
            logging.getLogger(__name__).warning(
                "embedding regen failed for memory %s: %s", memory_id, e
            )
            m.embedding = None

    if "type" in updates:
        m.type = updates["type"]

    if "expires_at" in updates:
        m.expires_at = updates["expires_at"]

    await session.commit()
    await session.refresh(m)

    return {
        "id": m.id,
        "user_id": m.user_id,
        "role": m.role,
        "type": m.type,
        "content": m.content,
        "expires_at": _fmt_dt(m.expires_at),
        "created_at": _fmt_dt(m.created_at),
    }


@router.delete("/memory/{memory_id}", status_code=204)
async def delete_memory_endpoint(
    memory_id: int,
    session: AsyncSession = Depends(get_session),
) -> None:
    await db_delete_memory(session, memory_id)
