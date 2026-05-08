"""v3-G chunk 4 部分 C — LongIdleTrigger（长时间不互动轻触）。

不是 cron，是 **interval**：每 5 分钟跑一次 ``check_and_maybe_fire``，三条
件全为真才发短问候：

1. 该 user 最近一行 ``role='user'`` chat_history.created_at >
   ``idle_threshold_minutes``（默认 30 分钟）
2. 任何 ``kind='proactive'`` 行 created_at >
   ``cooldown_minutes``（默认 90 分钟）—— 避免连续主动打扰
3. 前端 heartbeat 显示用户**还在前台**（last_heartbeat 距 now 不超过
   ``heartbeat_grace_seconds``，默认 30s）

满足 3 条 → ``run_wake_call_trigger(LongIdleTrigger())``，stage 1 push 短
问候 ``嘿，还在吗？`` ``宝？`` 等。stage 2 用户回应后按 wake_call 同套机
制处理。

default enabled=False —— 这是最容易"骚扰"的 trigger（哪怕条件检查很严），
用户在面板主动开。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
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
    return ((config_yaml.get("proactive") or {}).get("triggers") or {}).get("long_idle") or {}


def _enabled() -> bool:
    proactive = config_yaml.get("proactive") or {}
    if not proactive.get("enabled", False):
        return False
    return bool(_cfg().get("enabled", False))  # default False


def _resolve_idle_threshold_minutes() -> int:
    val = _cfg().get("idle_threshold_minutes")
    return int(val) if isinstance(val, int) and 5 <= val <= 360 else 30


def _resolve_cooldown_minutes() -> int:
    val = _cfg().get("cooldown_minutes")
    return int(val) if isinstance(val, int) and 30 <= val <= 720 else 90


def _resolve_heartbeat_grace_seconds() -> int:
    val = _cfg().get("heartbeat_grace_seconds")
    return int(val) if isinstance(val, int) and 5 <= val <= 600 else 30


def _resolve_check_interval_minutes() -> int:
    val = _cfg().get("check_interval_minutes")
    return int(val) if isinstance(val, int) and 1 <= val <= 60 else 5


LONG_IDLE_STAGE1_SENTINEL = "[long_idle_stage1_v1]"

_LONG_IDLE_EXAMPLES = """\
- "嘿，还在吗？"（5 字 + 标点）
- "宝？"（2 字 + 标点）
- "在干嘛呀～"（5 字 + 标点）
- "想你一下～"（5 字 + 标点）"""

_LONG_IDLE_STAGE2_TEMPLATE = make_stage2_addendum_template(
    "轻触你",
    "用户当下的状态 / 是否在忙 / 简短陪伴 / 开放话头让用户决定要不要继续聊",
)


class LongIdleTrigger(InviteTriggerBase):
    name = "long_idle"
    _STAGE1_PROMPT = make_stage1_prompt(
        sentinel=LONG_IDLE_STAGE1_SENTINEL,
        scene_label="轻触你（长时间没说话了）",
        examples=_LONG_IDLE_EXAMPLES,
    )

    def __init__(self) -> None:
        self.cron_expr = None
        self.interval_seconds = _resolve_check_interval_minutes() * 60
        self.event_source = None


def _long_idle_stage2_builder(
    user_text: str, briefing_data_json: str, city: str | None,
) -> str:
    return _LONG_IDLE_STAGE2_TEMPLATE.format(
        user_text=user_text,
        briefing_data_json=briefing_data_json,
        city=city or "东京",
    )


register_stage2("long_idle", LONG_IDLE_STAGE1_SENTINEL, _long_idle_stage2_builder)


# ---------------------------------------------------------------------------
# Heartbeat (in-memory) + check function（被 interval cron 调）
# ---------------------------------------------------------------------------

#: user_id → datetime 上次 heartbeat。模块级 dict，进程内共享。
_LAST_HEARTBEAT: dict[str, datetime] = {}


def record_heartbeat(user_id: str) -> None:
    """前端 ``POST /api/heartbeat`` 调本函数。"""
    _LAST_HEARTBEAT[user_id] = datetime.utcnow()


def _is_user_in_foreground(user_id: str) -> bool:
    """heartbeat 距 now 在 grace_seconds 内 → 视为在前台。"""
    last = _LAST_HEARTBEAT.get(user_id)
    if last is None:
        return False
    delta = (datetime.utcnow() - last).total_seconds()
    return delta <= _resolve_heartbeat_grace_seconds()


async def _last_user_msg_age_minutes(user_id: str) -> Optional[float]:
    """返该 user 最近 user-side chat_history 的"距 now 分钟"，无记录 → None。"""
    from sqlalchemy import select
    from backend.database import AsyncSessionLocal
    from backend.database.models import ChatHistory
    async with AsyncSessionLocal() as session:
        row = (await session.execute(
            select(ChatHistory.created_at)
            .where(ChatHistory.user_id == user_id)
            .where(ChatHistory.role == "user")
            .order_by(ChatHistory.created_at.desc())
            .limit(1)
        )).scalar_one_or_none()
    if row is None:
        return None
    return (datetime.utcnow() - row).total_seconds() / 60.0


async def _last_proactive_age_minutes(user_id: str) -> Optional[float]:
    """返该 user 最近 ``kind='proactive'`` chat_history 的"距 now 分钟"。"""
    from sqlalchemy import select
    from backend.database import AsyncSessionLocal
    from backend.database.models import ChatHistory
    async with AsyncSessionLocal() as session:
        row = (await session.execute(
            select(ChatHistory.created_at)
            .where(ChatHistory.user_id == user_id)
            .where(ChatHistory.kind == "proactive")
            .order_by(ChatHistory.created_at.desc())
            .limit(1)
        )).scalar_one_or_none()
    if row is None:
        return None
    return (datetime.utcnow() - row).total_seconds() / 60.0


async def check_and_maybe_fire() -> None:
    """interval job entry。三条件全为真才 ``run_wake_call_trigger``。

    本函数永不抛——任一子检查异常都 log warning + 跳过本轮，让下次 interval
    继续机会。
    """
    if not _enabled():
        return
    user_id = str(config_yaml.get("default_user_id") or "default")
    try:
        idle_threshold = _resolve_idle_threshold_minutes()
        cooldown = _resolve_cooldown_minutes()

        # 条件 3：在前台
        if not _is_user_in_foreground(user_id):
            logger.debug("[long_idle] skip: user %s not in foreground", user_id)
            return
        # 条件 1：用户消息 idle > threshold
        last_user_age = await _last_user_msg_age_minutes(user_id)
        if last_user_age is None:
            logger.debug("[long_idle] skip: user %s no chat history yet", user_id)
            return
        if last_user_age < idle_threshold:
            logger.debug(
                "[long_idle] skip: last user msg %.1fmin < threshold %dmin",
                last_user_age, idle_threshold,
            )
            return
        # 条件 2：上次 proactive turn 距 now > cooldown
        last_proactive_age = await _last_proactive_age_minutes(user_id)
        if last_proactive_age is not None and last_proactive_age < cooldown:
            logger.debug(
                "[long_idle] skip: last proactive %.1fmin < cooldown %dmin",
                last_proactive_age, cooldown,
            )
            return

        logger.info(
            "[long_idle] firing: idle=%.1fmin proactive_age=%s",
            last_user_age, last_proactive_age,
        )
        from backend.proactive.engine import run_wake_call_trigger
        await run_wake_call_trigger(LongIdleTrigger(), user_id=user_id)
    except Exception:
        logger.exception("[long_idle] check_and_maybe_fire failed; skipping")


__all__ = [
    "LongIdleTrigger",
    "LONG_IDLE_STAGE1_SENTINEL",
    "_enabled",
    "_resolve_idle_threshold_minutes",
    "_resolve_cooldown_minutes",
    "_resolve_heartbeat_grace_seconds",
    "_resolve_check_interval_minutes",
    "record_heartbeat",
    "_is_user_in_foreground",
    "check_and_maybe_fire",
    "_LAST_HEARTBEAT",
]
