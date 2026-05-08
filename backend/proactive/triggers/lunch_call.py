"""v3-G chunk 4 部分 C — LunchCallTrigger（午饭轻触发）。

cron 默认工作日 ``0 12 * * 1-5``（中午 12:00），周末 ``30 11 * * 0,6``
（11:30 早一点，周末通常起得晚但也想早点吃）。两条 cron 在 main.py 各自
独立注册（job id 区分 weekday / weekend）。

stage 1 短句（8-15 字）：``嘿，饿了吗？`` / ``午饭吃啥呀～`` 等。
stage 2 自适应：聚合 briefing_data_json 含天气 + 上次饮食偏好（profile_summary
摘要 + instruction memory 含"喜欢 X"）。
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
    return ((config_yaml.get("proactive") or {}).get("triggers") or {}).get("lunch_call") or {}


def _enabled() -> bool:
    proactive = config_yaml.get("proactive") or {}
    if not proactive.get("enabled", False):
        return False
    return bool(_cfg().get("enabled", False))


def _resolve_cron_weekday() -> str:
    val = _cfg().get("cron_weekday")
    return val.strip() if isinstance(val, str) and val.strip() else "0 12 * * 1-5"


def _resolve_cron_weekend() -> str:
    val = _cfg().get("cron_weekend")
    return val.strip() if isinstance(val, str) and val.strip() else "30 11 * * 0,6"


LUNCH_CALL_STAGE1_SENTINEL = "[lunch_call_stage1_v1]"

_LUNCH_EXAMPLES = """\
- "嘿，饿了吗？"（5 字 + 标点）
- "午饭吃啥呀～"（6 字 + 标点）
- "宝，吃饭啦～"（6 字 + 标点）
- "中午想吃什么？"（7 字 + 标点）"""

_LUNCH_STAGE2_SCENE = "午饭呼叫"
_LUNCH_STAGE2_FOCUS = "用户的胃口 / 餐食偏好 / 是否在外就餐 / 简单做饭建议"


class LunchCallTrigger(InviteTriggerBase):
    name = "lunch_call"
    _STAGE1_PROMPT = make_stage1_prompt(
        sentinel=LUNCH_CALL_STAGE1_SENTINEL,
        scene_label="叫吃午饭",
        examples=_LUNCH_EXAMPLES,
    )

    def __init__(self, *, weekend: bool = False) -> None:
        self.cron_expr = _resolve_cron_weekend() if weekend else _resolve_cron_weekday()
        self.interval_seconds = None
        self.event_source = None


_LUNCH_STAGE2_TEMPLATE = make_stage2_addendum_template(
    _LUNCH_STAGE2_SCENE, _LUNCH_STAGE2_FOCUS,
)


def _lunch_stage2_builder(
    user_text: str, briefing_data_json: str, city: str | None,
) -> str:
    return _LUNCH_STAGE2_TEMPLATE.format(
        user_text=user_text,
        briefing_data_json=briefing_data_json,
        city=city or "东京",
    )


register_stage2("lunch_call", LUNCH_CALL_STAGE1_SENTINEL, _lunch_stage2_builder)


__all__ = [
    "LunchCallTrigger",
    "LUNCH_CALL_STAGE1_SENTINEL",
    "_enabled",
    "_resolve_cron_weekday",
    "_resolve_cron_weekend",
]
