"""v4 segment 1 — turn mode classification(deterministic,无 LLM classifier)。

v1 仅两态 ``ROLEPLAY`` / ``PROACTIVE``,由 ``turn_origin``(caller 传入字符串)
deterministic 映射。``TASK`` 占位留 v1.x 扩展,本 segment 渲染时 fallback
到 ROLEPLAY。

PROACTIVE_ORIGINS 名单按 spec sign-off 写,**仅 cron/activity_smart 路径**
被标 PROACTIVE;未列入名单(如 long_idle / morning_briefing / bedtime_chat
等若未来加进 trigger pack)默认 fallback 到 ROLEPLAY —— 行为安全(走标准
B1 directive)。新增 trigger 需要走 PROACTIVE B1 directive 时,**显式**把
trigger name 加进 PROACTIVE_ORIGINS。
"""
from __future__ import annotations

from enum import Enum


class Mode(str, Enum):
    ROLEPLAY = "roleplay"
    PROACTIVE = "proactive"
    TASK = "task"  # v1 不实施,渲染时 layer_b 走 else 分支 fallback to roleplay text


PROACTIVE_ORIGINS = frozenset({
    "cron",
    "activity_smart",
    "wake_call",
    "lunch_call_weekday",
    "lunch_call_weekend",
    "dinner_call",
})


def determine_mode(turn_origin: str) -> Mode:
    """v1 deterministic mode classifier。

    ``turn_origin`` 由 caller(ws.py / proactive/engine.py)在 chat_msg context
    里写入。约定:
      * ws.py 用户消息路径:``"user"``
      * proactive engine 路径:``trigger.name``(如 ``"wake_call"`` /
        ``"activity_smart"`` / ``"cron"`` 等)

    未知 origin / None / 空串 → ``Mode.ROLEPLAY``(安全 fallback)。
    """
    if turn_origin and turn_origin in PROACTIVE_ORIGINS:
        return Mode.PROACTIVE
    return Mode.ROLEPLAY
