"""Conversations REST API.

Mounted at /api in main.py.  Full URL map:
  GET    /api/conversations/list?user_id=&character_id=
  POST   /api/conversations/create
  PATCH  /api/conversations/{id}
  DELETE /api/conversations/{id}
  GET    /api/conversations/{id}/messages
"""
import asyncio
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import config_yaml
from backend.database import get_session
from backend.database.models import ChatHistory, Conversation

router = APIRouter()


def _uid(user_id: Optional[str]) -> str:
    return (user_id or "").strip() or config_yaml.get("default_user_id", "default")


def _fmt_dt(dt: Optional[datetime]) -> Optional[str]:
    return dt.strftime("%Y-%m-%d %H:%M:%S") if dt else None


class ConversationCreateBody(BaseModel):
    user_id: Optional[str] = None
    character_id: int
    title: Optional[str] = None


class ConversationPatchBody(BaseModel):
    title: Optional[str] = None


async def _row_to_dict(session: AsyncSession, c: Conversation) -> dict:
    msg_count = (await session.execute(
        select(func.count(ChatHistory.id)).where(ChatHistory.conversation_id == c.id)
    )).scalar_one()
    return {
        "id": c.id,
        "user_id": c.user_id,
        "character_id": c.character_id,
        "title": c.title,
        "created_at": _fmt_dt(c.created_at),
        "updated_at": _fmt_dt(c.updated_at),
        "message_count": int(msg_count or 0),
    }


@router.get("/conversations/list")
async def list_conversations(
    user_id: Optional[str] = None,
    character_id: Optional[int] = None,
    session: AsyncSession = Depends(get_session),
) -> List[dict]:
    query = select(Conversation).where(Conversation.user_id == _uid(user_id))
    if character_id is not None:
        query = query.where(Conversation.character_id == character_id)
    query = query.order_by(Conversation.updated_at.desc())
    rows = list((await session.execute(query)).scalars().all())
    return [await _row_to_dict(session, c) for c in rows]


@router.post("/conversations/create", status_code=201)
async def create_conversation(
    body: ConversationCreateBody,
    session: AsyncSession = Depends(get_session),
) -> dict:
    c = Conversation(
        user_id=_uid(body.user_id),
        character_id=body.character_id,
        title=body.title or "新对话",
    )
    session.add(c)
    await session.commit()
    await session.refresh(c)
    return await _row_to_dict(session, c)


@router.patch("/conversations/{conversation_id}")
async def patch_conversation(
    conversation_id: int,
    body: ConversationPatchBody,
    session: AsyncSession = Depends(get_session),
) -> dict:
    c = (await session.execute(
        select(Conversation).where(Conversation.id == conversation_id)
    )).scalar_one_or_none()
    if c is None:
        raise HTTPException(status_code=404, detail="conversation not found")

    updates = body.model_dump(exclude_unset=True)
    if "title" in updates and updates["title"]:
        c.title = updates["title"]
    c.updated_at = datetime.utcnow()
    await session.commit()
    await session.refresh(c)
    return await _row_to_dict(session, c)


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: int,
    session: AsyncSession = Depends(get_session),
) -> None:
    c = (await session.execute(
        select(Conversation).where(Conversation.id == conversation_id)
    )).scalar_one_or_none()
    if c is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    # Capture the owner before deletion — needed to refresh profile_summary
    # against whatever chat_history remains for this user.
    owner_user_id = c.user_id
    # Cascade-delete chat_history rows tied to this conversation.
    await session.execute(
        delete(ChatHistory).where(ChatHistory.conversation_id == conversation_id)
    )
    # Patch A(audit_z5 + Stage 2):源头 reconcile extractor 指针。
    # 删完 chat_history 后,若 ``memory_extractor_state.last_processed_turn_id``
    # 越过用户剩余 chat_history 的 MAX(id) → clamp 到该 MAX(无行则 0)。
    # 死守两点(Phase A §5 风险旗):
    #   ① MAX 按 user_id 算"剩余行",绝不按"被删 conv max id"(scope 错配会
    #      跳别 conv 幸存高 id 行,违反不变量 ii);
    #   ② WHERE ... AND last_processed_turn_id > ... 这个 guard 必须在,只
    #      在真越界时动、只 clamp 不前进 → 幂等,已抽过 / 正常的指针不乱动。
    # 与 Patch B(f712625 worker 自愈)是纵深关系:本句删时即修对,worker
    # 那道是"漏改任何删除路径就兜底"的兜底,**互不耦合**。
    await session.execute(text(
        "UPDATE memory_extractor_state "
        "SET last_processed_turn_id = COALESCE("
        "  (SELECT MAX(id) FROM chat_history WHERE user_id = :u), 0) "
        "WHERE user_id = :u "
        "  AND last_processed_turn_id > COALESCE("
        "    (SELECT MAX(id) FROM chat_history WHERE user_id = :u), 0)"
    ), {"u": owner_user_id})
    await session.delete(c)
    await session.commit()

    # V2.5-D — kick the profile_summary background task so the impression
    # adjusts to (or clears against) the remaining chat_history. Imported
    # locally to avoid circular import with backend.routes.ws.
    from backend.routes.ws import _regenerate_profile_summary
    asyncio.create_task(_regenerate_profile_summary(owner_user_id))


@router.get("/conversations/{conversation_id}/messages")
async def list_conversation_messages(
    conversation_id: int,
    session: AsyncSession = Depends(get_session),
) -> List[dict]:
    """Return all chat_history rows for the given conversation, oldest first."""
    c = (await session.execute(
        select(Conversation).where(Conversation.id == conversation_id)
    )).scalar_one_or_none()
    if c is None:
        raise HTTPException(status_code=404, detail="conversation not found")

    rows = list((await session.execute(
        select(ChatHistory)
        .where(ChatHistory.conversation_id == conversation_id)
        .order_by(ChatHistory.created_at.asc(), ChatHistory.id.asc())
    )).scalars().all())
    return [
        {
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "conversation_id": m.conversation_id,
            "character_id": m.character_id,
            "created_at": _fmt_dt(m.created_at),
            # v3-E1 Step Z.2：让前端区分 'touch' / 'proactive' 行做特殊渲染
            "kind": m.kind or "normal",
            # v3-G chunk 2：proactive 行的触发器名（'morning_briefing' / null）
            "proactive_trigger": m.proactive_trigger,
        }
        for m in rows
    ]
