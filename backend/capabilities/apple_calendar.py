"""v3-G chunk 1.6 — Apple Calendar capability（上层）。

调底层 ``backend.integrations.apple_calendar`` client，按 chunk 0 pattern 注
册 4 个 capability：

* ``apple_calendar.today_events``     —— 今天所有事件
* ``apple_calendar.upcoming_events``  —— 未来 N 天事件（1-30）
* ``apple_calendar.create_event``     —— 创建事件（自然语言录入入口；为
                                          chunk 2.5 智能录入铺路）
* ``apple_calendar.delete_event``     —— 按 event_id 删

时区：跟 chunk 0 / chunk 1 一致从 ``config.yaml.scheduler.timezone`` 读
（默认 ``Asia/Tokyo``）。
"""
from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from backend.capabilities import Consumer, TriggerMode, register_capability
from backend.config import config_yaml
from backend.integrations import apple_calendar as ac


def _get_timezone():
    sched_cfg = config_yaml.get("scheduler") or {}
    return ZoneInfo(str(sched_cfg.get("timezone") or "Asia/Tokyo"))


# ---------------------------------------------------------------------------
# 1. 今日事件
# ---------------------------------------------------------------------------

@register_capability(
    name="apple_calendar.today_events",
    display_name="今日日程（Apple）",
    description=(
        "获取 macOS Apple Calendar 今天的所有事件（本地时区）。优先用 "
        "calendar.today_events 路由版本；本接口给高级用户 / scheduler 直接"
        "锁定 Apple 数据源用。"
    ),
    category="calendar",
    consumers=[Consumer.CHAT_AGENT, Consumer.SCHEDULER],
    trigger_modes=[TriggerMode.ON_DEMAND, TriggerMode.SCHEDULED],
    icon="calendar",
    parameters_schema={"type": "object", "properties": {}, "required": []},
    health_check=ac.health_check,
)
async def today_events(**_kwargs) -> list[dict]:
    tz = _get_timezone()
    now = datetime.now(tz)
    start = datetime.combine(now.date(), time.min, tzinfo=tz)
    end   = datetime.combine(now.date(), time.max, tzinfo=tz)
    return await ac.list_events_in_range(start, end, tz=tz)


# ---------------------------------------------------------------------------
# 2. 未来事件
# ---------------------------------------------------------------------------

@register_capability(
    name="apple_calendar.upcoming_events",
    display_name="未来日程（Apple）",
    description=(
        "获取 macOS Apple Calendar 未来 N 天（默认 7，1-30 范围）事件。"
        "优先用 calendar.upcoming_events 路由版本；本接口锁定 Apple 数据源。"
    ),
    category="calendar",
    consumers=[Consumer.CHAT_AGENT, Consumer.SCHEDULER],
    trigger_modes=[TriggerMode.ON_DEMAND],
    icon="calendar",
    parameters_schema={
        "type": "object",
        "properties": {
            "days_ahead": {
                "type": "integer", "default": 7, "minimum": 1, "maximum": 30,
                "description": "向前看几天",
            },
        },
        "required": [],
    },
    health_check=ac.health_check,
)
async def upcoming_events(days_ahead: int = 7, **_kwargs) -> list[dict]:
    days_ahead = max(1, min(30, int(days_ahead)))
    tz = _get_timezone()
    now = datetime.now(tz)
    end = now + timedelta(days=days_ahead)
    return await ac.list_events_in_range(now, end, tz=tz)


# ---------------------------------------------------------------------------
# 3. 创建事件（chunk 2.5 自然语言录入的关键入口）
# ---------------------------------------------------------------------------

@register_capability(
    name="apple_calendar.create_event",
    display_name="创建日历事件",
    description=(
        "在 macOS Apple Calendar 创建一个事件。当用户说「提醒我 X 点 Y "
        "事 / 帮我记一下 / 明天 X 点 Y / 把 X 加到日历」时调用。start_iso "
        "必须是 ISO 8601 字符串（含时区，如 2026-05-08T10:00:00+09:00）；"
        "如果用户只给了相对时间（'明天上午 10 点'），先调 time.now 拿当前"
        "时间再算出准确 ISO。calendar_name 留空 = 默认日历。"
    ),
    category="calendar",
    consumers=[Consumer.CHAT_AGENT],
    trigger_modes=[TriggerMode.ON_DEMAND],
    icon="calendar",
    parameters_schema={
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "事件标题，简短描述（如 '看牙医' / '团队同步会'）",
            },
            "start_iso": {
                "type": "string",
                "description": "ISO 8601 开始时间，含时区，如 2026-05-08T10:00:00+09:00",
            },
            "duration_minutes": {
                "type": "integer",
                "default": 30,
                "minimum": 1,
                "maximum": 1440,
                "description": "持续时长，分钟，默认 30",
            },
            "description": {
                "type": "string",
                "description": "事件备注 / 详细说明（可选）",
            },
            "calendar_name": {
                "type": "string",
                "description": "目标日历名（可选；默认用系统默认日历）",
            },
        },
        "required": ["title", "start_iso"],
    },
    health_check=ac.health_check,
)
async def create_event(
    title: str,
    start_iso: str,
    duration_minutes: int = 30,
    description: str | None = None,
    calendar_name: str | None = None,
    **_kwargs,
) -> dict:
    """返回 ``{"event_id": "...", "title": ..., "start": ..., "calendar": ...}``。

    LLM 不能自己生成 event_id —— 创建后 Apple 系统给一个稳定标识符，调
    delete_event 时会用。
    """
    try:
        start_dt = datetime.fromisoformat(start_iso)
    except ValueError as exc:
        raise ValueError(
            f"start_iso 不是合法 ISO 8601: {exc}（示例：2026-05-08T10:00:00+09:00）"
        )
    if start_dt.tzinfo is None:
        # 没带时区 → 按配置时区解释（避免 UTC 漂移）
        start_dt = start_dt.replace(tzinfo=_get_timezone())
    eid = await ac.create_event(
        title=title,
        start=start_dt,
        duration_minutes=int(duration_minutes),
        description=description,
        calendar_name=calendar_name,
        tz=start_dt.tzinfo,
    )
    return {
        "event_id": eid,
        "title": title,
        "start": start_dt.isoformat(),
        "duration_minutes": int(duration_minutes),
        "calendar": calendar_name or "默认日历",
    }


# ---------------------------------------------------------------------------
# 4. 删除事件
# ---------------------------------------------------------------------------

@register_capability(
    name="apple_calendar.delete_event",
    display_name="删除日历事件",
    description=(
        "按 event_id 删除 macOS Apple Calendar 事件。**调用前必须先**用 "
        "apple_calendar.today_events / upcoming_events 找到要删的事件、"
        "拿到它的 event_id；不要凭空生成 event_id。"
    ),
    category="calendar",
    consumers=[Consumer.CHAT_AGENT],
    trigger_modes=[TriggerMode.ON_DEMAND],
    icon="calendar",
    parameters_schema={
        "type": "object",
        "properties": {
            "event_id": {
                "type": "string",
                "description": "事件 ID（来自 today_events / upcoming_events 返回的 id 字段）",
            },
        },
        "required": ["event_id"],
    },
    health_check=ac.health_check,
)
async def delete_event(event_id: str, **_kwargs) -> dict:
    success = await ac.delete_event(event_id)
    return {"deleted": bool(success), "event_id": event_id}
