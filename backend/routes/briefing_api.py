"""v3-G chunk 1 — 起床简报测试触发路由。

cron 默认早 9 点跑，调试 / 验收时不能等到 9 点 —— 提供一个 ``POST
/api/briefing/test`` 立刻触发同一函数，返回 metadata（text + audio_bytes
+ audio_path + voice_model），方便前端面板按钮验证整链路。
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter

from backend.scheduler.briefing import deliver_morning_briefing

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/briefing/test")
async def trigger_test_briefing() -> dict[str, Any]:
    """立刻跑一次简报，返回 metadata。"""
    return await deliver_morning_briefing()
