"""v3-G chunk 2 — 早晨简报薄包装。

历史
====

* chunk 1 (v0.1)：模板拼接 ``"早上好，今天你有：A; B; C。"`` + 同步合成 wav
  落到 ``~/.skyler/last_briefing.wav``。template / wav 现已**废弃**：chunk 2
  全面切到 ChatAgent 智能生成，wav 路径不再写盘（全程流式 audio_chunk 推
  前端，落盘没有意义）。
* chunk 2：本文件缩成薄包装 —— 仅 ``deliver_morning_briefing()`` 一个函数，
  调 ``backend.proactive.engine.run_trigger(MorningBriefingTrigger(), user_id)``。
  cron 注册 + ``POST /api/briefing/test`` 复用此路径。

为什么不删掉这个文件
====================

1. ``main.py.lifespan`` cron 注册时 import 路径 ``from backend.scheduler.briefing
   import deliver_morning_briefing`` 是 chunk 1 留下的稳定 API；保留这一
   入口让 lifespan 不动。
2. ``backend.routes.briefing_api`` 也 import 同一函数；保留 = 路由零改动。
3. 后续 chunk 真正走 v3-F' 多 trigger 时，``schedule_briefing_cron`` 这种
   薄注册函数也归在这里方便 housekeeping。
"""
from __future__ import annotations

import logging
from typing import Any

from backend.config import config_yaml
from backend.proactive.engine import run_trigger
from backend.proactive.triggers.morning_briefing import MorningBriefingTrigger

logger = logging.getLogger(__name__)


def _default_user_id() -> str:
    return str(config_yaml.get("default_user_id") or "default")


async def deliver_morning_briefing() -> dict[str, Any]:
    """执行一次早晨简报。返回 engine.run_trigger 的 metadata。

    返回 dict 形状（向后兼容 chunk 1 ``BriefingTestResponse`` 字段名）::

        {
            "text":              str,        # 完整简报文本
            "character_id":      int | None,
            "conversation_id":   int | None,
            "proactive_trigger": "morning_briefing",
            "audio_bytes":       int,        # 流式推送时为 0（不再落盘）
            "audio_path":        None,       # chunk 1 兼容字段，永远 None
            "voice_model":       str | None, # chunk 1 兼容字段，从 character 读
        }
    """
    user_id = _default_user_id()
    result = await run_trigger(MorningBriefingTrigger(), user_id)

    # chunk 1 旧字段填充：让 frontend 旧 `BriefingTestResponse` schema 不炸
    result.setdefault("audio_path", None)
    result.setdefault("voice_model", None)
    return result
