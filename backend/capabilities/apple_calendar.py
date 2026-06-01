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
# 4 internal handlers (per INV-6 §3 P1.apple_calendar fold, 2026-05-21):
# today_events / upcoming_events / create_event / delete_event
# 走 dispatcher `apple_calendar(action=...)`,不再单独 @register_capability。
# ---------------------------------------------------------------------------


async def _handle_today_events(**_kwargs) -> list[dict]:
    tz = _get_timezone()
    now = datetime.now(tz)
    start = datetime.combine(now.date(), time.min, tzinfo=tz)
    end   = datetime.combine(now.date(), time.max, tzinfo=tz)
    return await ac.list_events_in_range(start, end, tz=tz)


async def _handle_upcoming_events(days_ahead: int = 7, **_kwargs) -> list[dict]:
    days_ahead = max(1, min(30, int(days_ahead)))
    tz = _get_timezone()
    now = datetime.now(tz)
    end = now + timedelta(days=days_ahead)
    return await ac.list_events_in_range(now, end, tz=tz)


async def _handle_create_event(
    title: str,
    start_iso: str,
    duration_minutes: int = 30,
    description: str | None = None,
    calendar_name: str | None = None,
    alarm_minutes_before: int = 0,
    **_kwargs,
) -> dict:
    """返回 ``{"event_id": "...", "title": ..., "start": ..., "calendar": ...}``。

    LLM 不能自己生成 event_id —— 创建后 Apple 系统给一个稳定标识符,
    调 delete_event 时会用。

    2026-05-28: alarm_minutes_before(默 0 = 事件发生时提醒)· 用户说"提前 X 分钟
    提醒" → LLM 传 X。内部转 alarm_offset_seconds = -alarm_minutes_before * 60
    (EKAlarm 用 relative offset 秒 · 负值 = 事件 start 前)。
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
    alarm_offset_seconds = -int(alarm_minutes_before) * 60
    eid = await ac.create_event(
        title=title,
        start=start_dt,
        duration_minutes=int(duration_minutes),
        description=description,
        calendar_name=calendar_name,
        tz=start_dt.tzinfo,
        alarm_offset_seconds=alarm_offset_seconds,
    )
    return {
        "event_id": eid,
        "title": title,
        "start": start_dt.isoformat(),
        "duration_minutes": int(duration_minutes),
        "calendar": calendar_name or "默认日历",
        "alarm_minutes_before": int(alarm_minutes_before),
    }


async def _handle_delete_event(event_id: str, **_kwargs) -> dict:
    success = await ac.delete_event(event_id)
    return {"deleted": bool(success), "event_id": event_id}


# ---------------------------------------------------------------------------
# apple_calendar dispatcher (INV-6 §3 P1.apple_calendar template reuse #1)
# ---------------------------------------------------------------------------

_APPLE_CALENDAR_ACTION_HANDLERS = {
    "today_events":    _handle_today_events,
    "upcoming_events": _handle_upcoming_events,
    "create_event":    _handle_create_event,
    "delete_event":    _handle_delete_event,
}


@register_capability(
    name="apple_calendar",
    display_name="Apple Calendar 日历操作",
    description=(
        "macOS Apple Calendar 日历操作。按 action 选具体操作:\n"
        "- today_events:今天所有事件(用户说'今天有什么安排')\n"
        "- upcoming_events:未来 N 天事件(用户说'下周/这周日程',days_ahead 默 7,1-30)\n"
        "- create_event:创建事件(用户说'提醒我 X 点 Y 事 / 把 X 加到日历',需 title + start_iso "
        "ISO 8601 含时区如 2026-05-08T10:00:00+09:00;相对时间如'明天上午 10 点'**先调 "
        "time.now** 拿当前时间再算 ISO;duration_minutes 默 30,calendar_name 留空 = 默认日历)\n"
        "- delete_event:按 event_id 删(**调用前必须先**用 today/upcoming_events 找到 event_id,"
        "不要凭空生成)\n"
        "优先走 calendar.today_events / upcoming_events router(自动选 apple/google 源);"
        "本 cap 用于高级用户 / scheduler 直接锁定 Apple 数据源。"
    ),
    category="calendar",
    consumers=[Consumer.CHAT_AGENT, Consumer.SCHEDULER],  # §3.3 特异 c1: 保 SCHEDULER metadata
    trigger_modes=[TriggerMode.ON_DEMAND, TriggerMode.SCHEDULED],
    icon="calendar",
    health_check=ac.health_check,
    parameters_schema={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": list(_APPLE_CALENDAR_ACTION_HANDLERS.keys()),
                "description": "Apple Calendar 操作类型",
            },
            "days_ahead": {
                "type": "integer", "minimum": 1, "maximum": 30, "default": 7,
                "description": "仅 action=upcoming_events 时用,向前看几天(默 7)",
            },
            "title": {
                "type": "string",
                "description": "仅 action=create_event 必填,事件标题(简短,如'看牙医')",
            },
            "start_iso": {
                "type": "string",
                "description": "仅 action=create_event 必填,ISO 8601 含时区如 2026-05-08T10:00:00+09:00",
            },
            "duration_minutes": {
                "type": "integer", "minimum": 1, "maximum": 1440, "default": 30,
                "description": "仅 action=create_event,持续时长分钟,默 30",
            },
            "description": {
                "type": "string",
                "description": "仅 action=create_event 可选,事件备注",
            },
            "calendar_name": {
                "type": "string",
                "description": "仅 action=create_event 可选,目标日历名(默系统默认)",
            },
            "event_id": {
                "type": "string",
                "description": "仅 action=delete_event 必填,event_id 来自 today/upcoming_events 返回",
            },
        },
        "required": ["action"],
    },
)
async def apple_calendar_dispatch(action: str = "", **params) -> dict | list[dict]:
    """Dispatcher: 按 action 路由到对应 _handle_* 函数,含 action-specific required 校验。"""
    handler = _APPLE_CALENDAR_ACTION_HANDLERS.get(action)
    if handler is None:
        return {
            "ok": False,
            "error": (
                f"unknown action: {action!r}; "
                f"valid: {list(_APPLE_CALENDAR_ACTION_HANDLERS.keys())}"
            ),
        }
    # action-specific required 字段校验
    if action == "create_event":
        if not params.get("title"):
            return {"ok": False, "error": "title required when action=create_event"}
        if not params.get("start_iso"):
            return {"ok": False, "error": "start_iso required when action=create_event"}
    elif action == "delete_event":
        if not params.get("event_id"):
            return {"ok": False, "error": "event_id required when action=delete_event"}
    return await handler(**params)


# ---------------------------------------------------------------------------
# Backward-compat aliases (INV-6 §3.8 fix, 2026-05-21)
#
# `backend/capabilities/calendar.py` router(D1 决策保留不动)内部 Python
# module-level import 硬编码 handler 函数名:
#   from backend.capabilities.apple_calendar import today_events as ac_today
#   from backend.capabilities.apple_calendar import upcoming_events as ac_up
# P1.apple_calendar fold 改 handler 名为 _handle_*,这 2 处 import 会
# ImportError。Smoke 2 实测暴露后,按 PM 拍板 option A 加 alias 兜底:
#
#   - 不动 calendar router(与 D1 决策"calendar router 保留不动"对齐)
#   - alias 是 Python 名字绑定,**不进 ToolRegistry,不增 schema token**
#   - **不是 LLM-visible**;LLM 主路径走 `apple_calendar(action=...)` dispatcher
#   - **新代码不要依赖** these aliases — backward-compat only
# ---------------------------------------------------------------------------

today_events = _handle_today_events
upcoming_events = _handle_upcoming_events
