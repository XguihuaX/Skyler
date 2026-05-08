"""v3-G chunk 4 部分 C — BedtimeChatTrigger（睡前问候）。

cron 默认 ``30 22 * * *``（晚 22:30）。default enabled=False —— 用户睡眠
习惯敏感，主动开默认要用户在面板手动开。

stage 1 ``今天累不累？`` / ``宝，准备睡了吗～`` 等。stage 2 一日 review +
明日预告（briefing_data 含今日 chat_history kind='normal' 摘要 + 明日
calendar.upcoming_events）。
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
    return ((config_yaml.get("proactive") or {}).get("triggers") or {}).get("bedtime_chat") or {}


def _enabled() -> bool:
    proactive = config_yaml.get("proactive") or {}
    if not proactive.get("enabled", False):
        return False
    return bool(_cfg().get("enabled", False))  # default False


def _resolve_cron() -> str:
    val = _cfg().get("cron")
    return val.strip() if isinstance(val, str) and val.strip() else "30 22 * * *"


BEDTIME_CHAT_STAGE1_SENTINEL = "[bedtime_chat_stage1_v1]"

_BEDTIME_EXAMPLES = """\
- "今天累不累？"（5 字 + 标点）
- "宝，准备睡了吗～"（7 字 + 标点）
- "今晚还好吗～"（5 字 + 标点）
- "晚安前来抱抱～"（6 字 + 标点）"""

_BEDTIME_STAGE2_TEMPLATE = make_stage2_addendum_template(
    "睡前问候",
    "用户的疲惫程度 / 今日感受 / 明日预告 / 安抚情绪 / 鼓励早睡",
)


class BedtimeChatTrigger(InviteTriggerBase):
    name = "bedtime_chat"
    _STAGE1_PROMPT = make_stage1_prompt(
        sentinel=BEDTIME_CHAT_STAGE1_SENTINEL,
        scene_label="睡前问候",
        examples=_BEDTIME_EXAMPLES,
    )

    def __init__(self) -> None:
        self.cron_expr = _resolve_cron()
        self.interval_seconds = None
        self.event_source = None


def _bedtime_stage2_builder(
    user_text: str, briefing_data_json: str, city: str | None,
) -> str:
    return _BEDTIME_STAGE2_TEMPLATE.format(
        user_text=user_text,
        briefing_data_json=briefing_data_json,
        city=city or "东京",
    )


register_stage2("bedtime_chat", BEDTIME_CHAT_STAGE1_SENTINEL, _bedtime_stage2_builder)


__all__ = [
    "BedtimeChatTrigger",
    "BEDTIME_CHAT_STAGE1_SENTINEL",
    "_enabled",
    "_resolve_cron",
]
