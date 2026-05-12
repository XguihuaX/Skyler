"""Users REST API.

Mounted at /api in main.py.  Full URL map:
  GET    /api/users/{user_id}/profile
  PATCH  /api/users/{user_id}/profile             —— nickname / language only

  # chunk 9 legacy（自然语言 profile_summary 段）—— 保留作 fallback。
  # 新前端用下方 chunk 11 endpoints；调用 legacy endpoint log warning。
  PATCH  /api/users/{user_id}/profile_summary     —— 用户手动编辑 (chunk 9)
  DELETE /api/users/{user_id}/profile_summary
  POST   /api/users/{user_id}/profile_summary/regenerate

  # chunk 11 structured profile_data（JSON schema 严格）
  GET    /api/users/{user_id}/profile_data        —— 返当前 7 字段 JSON
  PATCH  /api/users/{user_id}/profile_data        —— 字段级 partial merge
  DELETE /api/users/{user_id}/profile_data        —— 清空 (SET NULL)
  POST   /api/users/{user_id}/profile_data/regenerate
                                                  —— body {"mode": "incremental"
                                                    | "reset"}，默认
                                                    incremental。同步 LLM 重算
"""
import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_session
from backend.database.models import User
from backend.database.services import update_profile_summary
from backend.utils.profile_schema import (
    PROFILE_SCHEMA_V1,
    empty_profile,
    is_list_field,
    is_string_field,
)
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

    .. deprecated:: chunk 11
       新前端应改用 ``PATCH /users/{user_id}/profile_data``（结构化 JSON）。
       legacy endpoint 保留作 fallback。
    """
    logger.warning(
        "[deprecated] PATCH /users/%s/profile_summary called — "
        "chunk 11 prefers PATCH /profile_data (structured JSON)",
        user_id,
    )
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
    logger.warning(
        "[deprecated] DELETE /users/%s/profile_summary called — "
        "chunk 11 prefers DELETE /profile_data",
        user_id,
    )
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

    .. deprecated:: chunk 11
       新前端用 ``POST /profile_data/regenerate``（结构化）。legacy 保留。
    """
    logger.warning(
        "[deprecated] POST /users/%s/profile_summary/regenerate called — "
        "chunk 11 prefers POST /profile_data/regenerate",
        user_id,
    )
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


# ---------------------------------------------------------------------------
# v3.5 chunk 11：structured profile_data endpoints
# ---------------------------------------------------------------------------


class ProfileDataPatchBody(BaseModel):
    """字段级 partial merge。

    所有字段都是 Optional —— 未传字段不动；显式传 ``null`` 清空 string
    字段；显式传 ``[]`` 清空 list 字段。
    """
    profession:            Optional[str] = None
    current_projects:      Optional[list[str]] = None
    communication_style:   Optional[str] = None
    interests:             Optional[list[str]] = None
    language_preferences:  Optional[str] = None
    active_hours:          Optional[str] = None
    recurring_topics:      Optional[list[str]] = None

    class Config:
        extra = "forbid"  # 拒绝 schema 外字段


class ProfileDataRegenerateBody(BaseModel):
    """POST /profile_data/regenerate request body。"""
    mode: str = "incremental"  # "incremental" | "reset"


class ProfileDataRegenerateResponse(BaseModel):
    """同步 regenerate 返回结构。

    ``status`` 与 ``profile_regen._regenerate_profile_data`` 同 enum：
    ``regenerated`` / ``skip_disabled`` / ``skip_too_few_user_msgs`` /
    ``skip_llm_failed`` / ``skip_validator_rejected`` /
    ``skip_user_not_found``。
    """
    status: str
    profile_data: Optional[dict] = None
    detail: Optional[str] = None


def _sanitize_profile_value(value: Any) -> Any:
    """单字段 sanitize：string 过 SUSPICIOUS sanitize；list 元素同处理。"""
    if isinstance(value, str):
        if count_suspicious_tags(value) > 0:
            return sanitize_suspicious_tags(value).strip() or None
        return value
    if isinstance(value, list):
        out = []
        for item in value:
            if not isinstance(item, str):
                continue
            cleaned = (
                sanitize_suspicious_tags(item).strip()
                if count_suspicious_tags(item) > 0
                else item.strip()
            )
            if cleaned:
                out.append(cleaned)
        return out
    return value


@router.get("/users/{user_id}/profile_data")
async def get_user_profile_data(
    user_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """返回当前 ``users.profile_data`` JSON。

    * profile_data 存在 → ``{ "user_id": ..., "profile_data": {...} }``
    * profile_data NULL → ``{ "user_id": ..., "profile_data": null }``
    * user 不存在 → 404
    """
    u = (await session.execute(
        select(User).where(User.user_id == user_id)
    )).scalar_one_or_none()
    if u is None:
        raise HTTPException(status_code=404, detail="user not found")

    import json as _json
    data: Optional[dict] = None
    if u.profile_data:
        try:
            parsed = _json.loads(u.profile_data)
            if isinstance(parsed, dict):
                data = parsed
        except _json.JSONDecodeError:
            logger.warning(
                "[profile_data] corrupt JSON for user=%s, returning None",
                user_id,
            )
    return {"user_id": u.user_id, "profile_data": data}


@router.patch("/users/{user_id}/profile_data")
async def patch_user_profile_data(
    user_id: str,
    body: ProfileDataPatchBody,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """字段级 partial merge 更新 ``profile_data``。

    * 未传字段保持不变（``model_dump(exclude_unset=True)``）
    * 写入前每字段过 SUSPICIOUS sanitize（防用户粘贴 XML）
    * schema 外字段 → Pydantic ``extra=forbid`` → 422
    * 旧 profile_data IS NULL → 从 ``empty_profile()`` 起 merge
    """
    u = (await session.execute(
        select(User).where(User.user_id == user_id)
    )).scalar_one_or_none()
    if u is None:
        raise HTTPException(status_code=404, detail="user not found")

    import json as _json
    if u.profile_data:
        try:
            current = _json.loads(u.profile_data) or {}
            if not isinstance(current, dict):
                current = empty_profile()
        except _json.JSONDecodeError:
            current = empty_profile()
    else:
        current = empty_profile()

    patch = body.model_dump(exclude_unset=True)
    for key, value in patch.items():
        if key not in PROFILE_SCHEMA_V1:
            # Pydantic extra=forbid 已过；此处 belt-and-suspenders
            continue
        cleaned = _sanitize_profile_value(value)
        if is_string_field(key):
            # 空白 / 全 sanitize 掉的视同 None
            if isinstance(cleaned, str):
                cleaned = cleaned.strip() or None
            current[key] = cleaned
        elif is_list_field(key):
            current[key] = cleaned if isinstance(cleaned, list) else []

    u.profile_data = _json.dumps(current, ensure_ascii=False)
    await session.commit()
    return {"user_id": u.user_id, "profile_data": current}


@router.delete("/users/{user_id}/profile_data", status_code=204)
async def delete_user_profile_data(
    user_id: str,
    session: AsyncSession = Depends(get_session),
) -> None:
    """清空 ``profile_data`` (SET NULL)。"""
    u = (await session.execute(
        select(User).where(User.user_id == user_id)
    )).scalar_one_or_none()
    if u is None:
        raise HTTPException(status_code=404, detail="user not found")
    u.profile_data = None
    await session.commit()


@router.post("/users/{user_id}/profile_data/regenerate")
async def regenerate_user_profile_data(
    user_id: str,
    body: ProfileDataRegenerateBody | None = None,
    session: AsyncSession = Depends(get_session),
) -> ProfileDataRegenerateResponse:
    """v3.5 chunk 11：同步触发 LLM 重算 profile_data。

    Body ``{"mode": "incremental" | "reset"}``；默认 incremental。
    * incremental → 用 ``_regenerate_profile_data(mode='manual_incremental')``
    * reset       → 用 ``_regenerate_profile_data(mode='manual_reset')``
                    （丢弃旧 profile，从近期数据完全重写）
    """
    u = (await session.execute(
        select(User).where(User.user_id == user_id)
    )).scalar_one_or_none()
    if u is None:
        raise HTTPException(status_code=404, detail="user not found")

    mode_in = (body.mode if body else "incremental") or "incremental"
    if mode_in == "reset":
        regen_mode = "manual_reset"
    elif mode_in == "incremental":
        regen_mode = "manual_incremental"
    else:
        raise HTTPException(
            status_code=422,
            detail=f"invalid mode {mode_in!r} (expected 'incremental' or 'reset')",
        )

    # 延迟 import 避免循环（routes → services → ... → routes 不会真循环，
    # 但保持 chunk 9 同 pattern）
    from backend.services.profile_regen import _regenerate_profile_data

    try:
        status, profile = await _regenerate_profile_data(
            user_id, mode=regen_mode,
        )
    except Exception as exc:
        logger.exception(
            "[profile_data] regenerate endpoint crashed user=%s mode=%s",
            user_id, regen_mode,
        )
        raise HTTPException(status_code=500, detail=str(exc))

    # 拿最新 profile_data（regenerated 时 service 已写库；skip 时可能未动）
    await session.refresh(u)
    import json as _json
    current_data: Optional[dict] = None
    if u.profile_data:
        try:
            parsed = _json.loads(u.profile_data)
            if isinstance(parsed, dict):
                current_data = parsed
        except _json.JSONDecodeError:
            pass

    detail_map = {
        "regenerated":            None,
        "skip_disabled":          "结构化 profile 在 config 中关闭",
        "skip_too_few_user_msgs": "过去 7 天 user 消息不足（< min_user_messages）",
        "skip_llm_failed":        "LLM 调用失败，旧 profile 已保留",
        "skip_validator_rejected": "LLM 输出 schema 不合法，旧 profile 已保留",
        "skip_user_not_found":    "用户不存在",
    }
    return ProfileDataRegenerateResponse(
        status=status,
        profile_data=current_data,
        detail=detail_map.get(status),
    )
