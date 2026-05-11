"""Users REST API.

Mounted at /api in main.py.  Full URL map:
  GET    /api/users/{user_id}/profile
  PATCH  /api/users/{user_id}/profile             —— nickname / language only
  PATCH  /api/users/{user_id}/profile_summary     —— 用户手动编辑 profile_summary (chunk 9)
  DELETE /api/users/{user_id}/profile_summary
  POST   /api/users/{user_id}/profile_summary/regenerate  —— 同步 LLM 重算 (chunk 9)
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_session
from backend.database.models import User
from backend.database.services import update_profile_summary
from backend.utils.text_filters import (
    count_suspicious_tags,
    sanitize_suspicious_tags,
)

logger = logging.getLogger(__name__)

router = APIRouter()


class UserProfilePatchBody(BaseModel):
    nickname: Optional[str] = None
    language: Optional[str] = None


class ProfileSummaryPatchBody(BaseModel):
    """v3.5 chunk 9：用户手动编辑 profile_summary。"""
    summary: str


class ProfileSummaryRegenerateResponse(BaseModel):
    """同步 regenerate 返回结构。

    ``status`` 与 ``ws._compute_profile_summary`` 同 enum：
    ``regenerated`` / ``cleared`` / ``skip_too_few_rows`` /
    ``skip_llm_failed`` / ``skip_llm_too_short`` / ``skip_llm_suspicious``。
    """
    status: str
    profile_summary: Optional[str] = None
    detail: Optional[str] = None


@router.get("/users/{user_id}/profile")
async def get_user_profile(
    user_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict:
    u = (await session.execute(
        select(User).where(User.user_id == user_id)
    )).scalar_one_or_none()
    if u is None:
        raise HTTPException(status_code=404, detail="user not found")
    return {
        "user_id": u.user_id,
        "user_name": u.user_name,
        "nickname": u.nickname,
        "language": u.language,
        "profile_summary": u.profile_summary,
    }


@router.patch("/users/{user_id}/profile")
async def patch_user_profile(
    user_id: str,
    body: UserProfilePatchBody,
    session: AsyncSession = Depends(get_session),
) -> dict:
    u = (await session.execute(
        select(User).where(User.user_id == user_id)
    )).scalar_one_or_none()
    if u is None:
        raise HTTPException(status_code=404, detail="user not found")
    updates = body.model_dump(exclude_unset=True)
    if "nickname" in updates:
        u.nickname = updates["nickname"]
    if "language" in updates and updates["language"]:
        u.language = updates["language"]
    await session.commit()
    await session.refresh(u)
    return {
        "user_id": u.user_id,
        "user_name": u.user_name,
        "nickname": u.nickname,
        "language": u.language,
        "profile_summary": u.profile_summary,
    }


@router.patch("/users/{user_id}/profile_summary")
async def patch_user_profile_summary(
    user_id: str,
    body: ProfileSummaryPatchBody,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """v3.5 chunk 9：用户手动编辑 profile_summary。

    写入前过 ``SUSPICIOUS_TAG_RE`` sanitize（防用户粘贴时带 XML）；命中
    log warning（与 ``_update_memory`` / ``_regenerate_profile_summary``
    一致的写库前 sanitize 契约）。
    """
    u = (await session.execute(
        select(User).where(User.user_id == user_id)
    )).scalar_one_or_none()
    if u is None:
        raise HTTPException(status_code=404, detail="user not found")

    cleaned = (body.summary or "").strip()
    suspicious_n = count_suspicious_tags(cleaned)
    if suspicious_n > 0:
        logger.warning(
            "[sanitize] PATCH profile_summary suspicious tags hit=%d user=%s "
            "preview=%r",
            suspicious_n, user_id, cleaned[:200],
        )
        cleaned = sanitize_suspicious_tags(cleaned).strip()

    u.profile_summary = cleaned or None
    await session.commit()
    await session.refresh(u)
    return {
        "user_id": u.user_id,
        "profile_summary": u.profile_summary,
    }


@router.delete("/users/{user_id}/profile_summary", status_code=204)
async def reset_user_profile_summary(
    user_id: str,
    session: AsyncSession = Depends(get_session),
) -> None:
    u = (await session.execute(
        select(User).where(User.user_id == user_id)
    )).scalar_one_or_none()
    if u is None:
        raise HTTPException(status_code=404, detail="user not found")
    u.profile_summary = None
    await session.commit()


@router.post("/users/{user_id}/profile_summary/regenerate")
async def regenerate_user_profile_summary(
    user_id: str,
    session: AsyncSession = Depends(get_session),
) -> ProfileSummaryRegenerateResponse:
    """v3.5 chunk 9：同步触发 LLM 重算 profile_summary 并返回新内容。

    与背景 task（每 N 轮 fire-and-forget）路径共用 ``_compute_profile_summary``
    核心，但本 endpoint：
      * **同步**等结果 —— UI 点 [立刻重新生成] loading → 完成后刷新显示
      * ``min_user_rows=1`` —— 让少量对话场景也能预览
      * 不重置 ``turn_count_per_user`` counter（与 background 路径解耦）
    """
    # 先确认 user 存在
    u = (await session.execute(
        select(User).where(User.user_id == user_id)
    )).scalar_one_or_none()
    if u is None:
        raise HTTPException(status_code=404, detail="user not found")

    # 延迟 import 避免循环（routes.ws → 多个其他 routes）
    from backend.routes.ws import _compute_profile_summary

    try:
        status, summary = await _compute_profile_summary(
            user_id, min_user_rows=1,
        )
    except Exception as exc:
        logger.exception(
            "[profile_summary] regenerate endpoint failed user=%s", user_id,
        )
        raise HTTPException(status_code=500, detail=str(exc))

    # 拿最新 profile_summary（regenerated 时 compute 已写库；其他状态可能未动）
    await session.refresh(u)

    detail_map = {
        "regenerated": None,
        "cleared": "无对话记录，已清空",
        "skip_too_few_rows": "对话不足（需至少 1 条用户消息）",
        "skip_llm_failed": "LLM 调用失败，旧 profile 已保留",
        "skip_llm_too_short": "LLM 输出过短，旧 profile 已保留",
        "skip_llm_suspicious": "LLM 输出含可疑标签，旧 profile 已保留",
    }
    return ProfileSummaryRegenerateResponse(
        status=status,
        profile_summary=u.profile_summary,
        detail=detail_map.get(status),
    )
