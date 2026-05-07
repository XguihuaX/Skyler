"""v3-G chunk 1+2+2.6 — 起床简报测试触发路由。

* chunk 1：``POST /api/briefing/test`` 立刻跑一次简报。
* chunk 2：默认走 proactive engine + ChatAgent 智能生成。
* chunk 2.6：加 ``?mode=wake_call|morning|auto`` query。``auto``（默认）
  按 ``config.proactive.mode`` 路由；强制 ``wake_call`` / ``morning``
  分别绕过 mode 配置直接跑对应 deliver（前端 SettingsPanel mode radio
  的"立即测试"按钮按 UI 当前选中传过来；旧前端不传走 auto）。
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query

from backend.scheduler.briefing import (
    deliver_active_briefing,
    deliver_morning_briefing,
    deliver_wake_call_briefing,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/briefing/test")
async def trigger_test_briefing(
    mode: Optional[str] = Query(
        default="auto",
        description="`auto` (config 路由) / `wake_call` / `morning`",
    ),
) -> dict[str, Any]:
    """立刻跑一次简报，返回 metadata。"""
    mode_norm = (mode or "auto").strip().lower()
    if mode_norm in ("auto", ""):
        return await deliver_active_briefing()
    if mode_norm in ("wake_call", "wake-call", "wakecall"):
        return await deliver_wake_call_briefing()
    if mode_norm in ("morning", "morning_briefing"):
        return await deliver_morning_briefing()
    raise HTTPException(
        status_code=400,
        detail=f"unknown mode={mode!r}; expected auto / wake_call / morning",
    )
