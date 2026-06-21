"""DailyAgent Stage 1 — activity ticker(5min interval)。

照 ``backend/proactive/triggers/long_idle.py`` 的 interval pattern,但语义
完全不同:long_idle 是 proactive 触发器(发消息),本 ticker 是**纯 DB
查表**(写 ``character_states.current_activity``,0 LLM)。

# 触发频率与意图

* APScheduler interval = 300 秒(5 分钟),与 long_idle 默认一致
* 每次 tick:
    1. 读 ``today_local`` 的 ``character_daily_plans`` row
    2. 找命中当前 HH:MM 的 slot
    3. 命中 → ``services.update_character_state(activity=slot["activity"])``
    4. 空档 → ``activity=""`` 清空 ``current_activity`` 为 NULL
       (Layer C4 模板 ``{%if states.activity%}`` 自动隐藏整行)
* 无今日 plan 时 → 不写(避免清掉 LLM 通过 ``<state_update>`` 写入的有效值)

# 与 <state_update> 的归属约定

Spec §3:Stage 1 由 ticker(日程)拥有 activity;``<state_update>`` 今天
也写。ticker 每 5min 重申日程值 → 漂 5min 内纠回。真机若频繁打架再决定
要不要 gate ``<state_update>`` 的 activity 写。

# Stage 1 MVP scope

只跑 ``DEFAULT_CHARACTER_ID = 1``,Stage 2 扩 multi-character。
"""
from __future__ import annotations

import logging

from backend.database import AsyncSessionLocal
from backend.database.services import update_character_state
from backend.services.daily_plan import (
    DEFAULT_CHARACTER_ID,
    _load_plan,
    find_current_slot,
)
from backend.utils.chat_time import get_scheduler_tz_name, now_local

logger = logging.getLogger(__name__)


async def daily_activity_ticker() -> None:
    """Interval entry — 每 5 分钟跑一次。"""
    try:
        tz_name = get_scheduler_tz_name()
        now = now_local(tz_name)
        today_local = now.date()
        now_hhmm = now.strftime("%H:%M")

        plan = await _load_plan(DEFAULT_CHARACTER_ID, today_local)
        if plan is None:
            # 今日 plan 未生成(cron 5 0 还没到 / 失败 / backfill 跳过)→
            # 不动 current_activity,避免把 <state_update> 写入的值无意清掉。
            logger.debug(
                "[daily_ticker] no plan for cid=%s date=%s — skip tick",
                DEFAULT_CHARACTER_ID, today_local,
            )
            return

        slot = find_current_slot(plan, now_hhmm)
        if slot is None:
            # 空档:清 current_activity 为 NULL(Layer C4 自动隐藏整行)。
            async with AsyncSessionLocal() as session:
                await update_character_state(
                    session, DEFAULT_CHARACTER_ID, activity="",
                )
            logger.debug(
                "[daily_ticker] gap @ %s cid=%s — cleared current_activity",
                now_hhmm, DEFAULT_CHARACTER_ID,
            )
            return

        activity_str = slot.get("activity") or ""
        if not activity_str:
            return
        async with AsyncSessionLocal() as session:
            await update_character_state(
                session, DEFAULT_CHARACTER_ID, activity=activity_str,
            )
        logger.debug(
            "[daily_ticker] slot %s-%s @ %s cid=%s → activity=%r",
            slot.get("start"), slot.get("end"), now_hhmm,
            DEFAULT_CHARACTER_ID, activity_str,
        )
    except Exception:
        # 任何异常都吞 + log,不要让 ticker 因单次 tick 失败而阻挡下次。
        logger.exception("[daily_ticker] tick failed cid=%s", DEFAULT_CHARACTER_ID)


__all__ = ["daily_activity_ticker"]
