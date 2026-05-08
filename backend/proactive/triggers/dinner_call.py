"""v3-G chunk 4 部分 C — DinnerCallTrigger（晚饭轻触发）。

cron 默认 ``30 18 * * *``（傍晚 18:30）。stage 1 ``忙完了？要吃啥？`` 等。
"""
from __future__ import annotations

import logging
from typing import Optional

from backend.config import config_yaml
from backend.proactive.triggers._invite_base import (
    InviteTriggerBase,
    make_stage1_prompt,
    make_stage2_addendum_template,
)
from backend.proactive.triggers._stage2_registry import register_stage2

logger = logging.getLogger(__name__)


def _cfg() -> dict:
    return ((config_yaml.get("proactive") or {}).get("triggers") or {}).get("dinner_call") or {}


def _enabled() -> bool:
    proactive = config_yaml.get("proactive") or {}
    if not proactive.get("enabled", False):
        return False
    return bool(_cfg().get("enabled", False))


def _resolve_cron() -> str:
    val = _cfg().get("cron")
    return val.strip() if isinstance(val, str) and val.strip() else "30 18 * * *"


DINNER_CALL_STAGE1_SENTINEL = "[dinner_call_stage1_v1]"

_DINNER_EXAMPLES = """\
- "忙完了？要吃啥？"（7 字 + 标点）
- "晚饭吃了吗～"（6 字 + 标点）
- "宝，下班啦～"（6 字 + 标点）
- "饿了没？要点什么？"（8 字 + 标点）"""

_DINNER_STAGE2_TEMPLATE = make_stage2_addendum_template(
    "晚饭呼叫",
    "用户的疲惫程度 / 是否还在工作 / 餐食偏好 / 简单做饭建议 / 外卖建议",
)


class DinnerCallTrigger(InviteTriggerBase):
    name = "dinner_call"
    _STAGE1_PROMPT = make_stage1_prompt(
        sentinel=DINNER_CALL_STAGE1_SENTINEL,
        scene_label="叫吃晚饭",
        examples=_DINNER_EXAMPLES,
    )

    def __init__(self) -> None:
        self.cron_expr = _resolve_cron()
        self.interval_seconds = None
        self.event_source = None


def _dinner_stage2_builder(
    user_text: str, briefing_data_json: str, city: str | None,
) -> str:
    return _DINNER_STAGE2_TEMPLATE.format(
        user_text=user_text,
        briefing_data_json=briefing_data_json,
        city=city or "东京",
    )


register_stage2("dinner_call", DINNER_CALL_STAGE1_SENTINEL, _dinner_stage2_builder)


__all__ = [
    "DinnerCallTrigger",
    "DINNER_CALL_STAGE1_SENTINEL",
    "_enabled",
    "_resolve_cron",
]
