"""Users REST API.

Mounted at /api in main.py.  Full URL map:
  GET    /api/users/{user_id}/profile
  PATCH  /api/users/{user_id}/profile
  DELETE /api/users/{user_id}/profile_summary
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_session
from backend.database.models import User

router = APIRouter()


class UserProfilePatchBody(BaseModel):
    nickname: Optional[str] = None
    language: Optional[str] = None


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
