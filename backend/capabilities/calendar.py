"""v3-G chunk 1 — Calendar capability（上层）。

调底层 ``backend.integrations.google_calendar`` client，按 chunk 0 pattern
注册成 capability。两个 capability：

* ``calendar.today_events``     —— 今天 0 点到 24 点的全部事件
* ``calendar.upcoming_events``  —— 未来 N 天事件，N 由 LLM 传入（1-30）

时区从 ``config.yaml.scheduler.timezone`` 读，与 chunk 0 cron / Time
capability 共用同一时区设置（缺省 ``Asia/Tokyo``）。
"""
from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from backend.capabilities import Consumer, TriggerMode, register_capability
from backend.config import config_yaml
from backend.integrations import google_calendar


def _get_timezone() -> str:
    sched_cfg = config_yaml.get("scheduler") or {}
    return str(sched_cfg.get("timezone") or "Asia/Tokyo")


@register_capability(
    name="calendar.today_events",
    display_name="今日日程",
    description=(
        "获取今天（用户本地时区）的所有 Google Calendar 事件。当用户问"
        "'今天有什么会 / 安排 / 日程'，或者要做时间相关判断时调用。"
        "返回事件列表（每个含 title / start / end / location / all_day）。"
    ),
    category="calendar",
    consumers=[Consumer.CHAT_AGENT, Consumer.SCHEDULER],
    trigger_modes=[TriggerMode.ON_DEMAND, TriggerMode.SCHEDULED],
    icon="calendar",
    parameters_schema={"type": "object", "properties": {}, "required": []},
    health_check=google_calendar.health_check,
)
async def today_events(**_kwargs) -> list[dict]:
    """返回今天 [0:00, 24:00) 的事件列表。

    时区按 config.scheduler.timezone（默认 Asia/Tokyo）；用户在不同时区时
    需要在 config.yaml 改 timezone 才能拿到本地"今天"的事件。
    """
    tz = ZoneInfo(_get_timezone())
    now = datetime.now(tz)
    start = datetime.combine(now.date(), time.min, tzinfo=tz)
    end   = datetime.combine(now.date(), time.max, tzinfo=tz)
    return await google_calendar.list_events_in_range(start, end)


@register_capability(
    name="calendar.upcoming_events",
    display_name="未来日程",
    description=(
        "获取未来 N 天（默认 7 天，1-30 范围）的 Google Calendar 事件。"
        "当用户问'这周 / 下周 / 这个月有什么 / 接下来安排'时调用。"
        "返回事件列表，按时间排序。"
    ),
    category="calendar",
    consumers=[Consumer.CHAT_AGENT],
    trigger_modes=[TriggerMode.ON_DEMAND],
    icon="calendar",  # ICON_MAP 没 calendar-clock，沿用 calendar
    parameters_schema={
        "type": "object",
        "properties": {
            "days_ahead": {
                "type": "integer",
                "default": 7,
                "minimum": 1,
                "maximum": 30,
                "description": "向前看几天",
            },
        },
        "required": [],
    },
    health_check=google_calendar.health_check,
)
async def upcoming_events(days_ahead: int = 7, **_kwargs) -> list[dict]:
    # clamp 防 LLM 越界（schema validate 不一定执行）
    days_ahead = max(1, min(30, int(days_ahead)))
    tz = ZoneInfo(_get_timezone())
    now = datetime.now(tz)
    end = now + timedelta(days=days_ahead)
    return await google_calendar.list_events_in_range(now, end)
