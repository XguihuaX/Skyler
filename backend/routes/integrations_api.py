"""v3-G chunk 1 — 外部集成 OAuth / 鉴权管理路由。

* ``POST /api/integrations/google/auth``   —— 触发 OAuth flow（阻塞调用，
  浏览器自动打开。后端跑 ``run_local_server`` 等 Google redirect 回来）
* ``POST /api/integrations/google/revoke`` —— 删 token.json
* ``GET  /api/integrations/google/status`` —— 当前授权状态 + （能拿到时）
  授权账号信息
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.integrations import google_calendar

logger = logging.getLogger(__name__)
router = APIRouter()


class GoogleStatusResponse(BaseModel):
    credentials_present: bool
    authorized: bool
    account_hint: str | None  # 不一定能拿到 email；返回 client_id 或 None


class GoogleAuthResponse(BaseModel):
    status: str
    detail: str | None = None


@router.get("/integrations/google/status", response_model=GoogleStatusResponse)
async def google_status() -> GoogleStatusResponse:
    return GoogleStatusResponse(
        credentials_present=google_calendar.is_credentials_present(),
        authorized=google_calendar.is_authorized(),
        account_hint=google_calendar.get_authorized_email(),
    )


@router.post("/integrations/google/auth", response_model=GoogleAuthResponse)
async def google_auth() -> GoogleAuthResponse:
    """触发首次 OAuth flow。**阻塞**到用户在浏览器完成授权或拒绝。

    用 ``asyncio.to_thread`` 把同步 ``run_oauth_flow`` 放进线程，避免堵
    FastAPI event loop（其它 HTTP 请求仍能处理）。
    """
    if not google_calendar.is_credentials_present():
        raise HTTPException(
            status_code=400,
            detail=(
                "missing credentials.json — see docs/google-calendar-setup.md "
                "to download Desktop OAuth client and place it at "
                "~/.skyler/google_credentials.json"
            ),
        )
    try:
        await asyncio.to_thread(google_calendar.run_oauth_flow)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("[google] OAuth flow failed")
        raise HTTPException(status_code=500, detail=f"OAuth failed: {exc}")
    return GoogleAuthResponse(status="ok", detail="authorized")


@router.post("/integrations/google/revoke", response_model=GoogleAuthResponse)
async def google_revoke() -> GoogleAuthResponse:
    removed = google_calendar.revoke_token()
    google_calendar._reset_service_cache()
    return GoogleAuthResponse(
        status="ok",
        detail="token removed" if removed else "no token to remove",
    )
