"""v3-G chunk 1.6 — calendar 路由 capability。

历史：chunk 1 此文件直接调 Google Calendar；chunk 1.6 接入 Apple 后改为
**统一路由层**：

* ``calendar.today_events`` / ``calendar.upcoming_events`` 是 LLM 看到的
  正路（CHAT_AGENT + SCHEDULER consumer），按 ``config.yaml.calendar.
  default_source`` 路由到 ``apple`` 或 ``google``
* 路由不带读写副作用；纯 dispatch + 错误兜底
* 简报模块（``backend/scheduler/briefing.py``）仍然 ``from
  backend.capabilities.calendar import today_events`` —— 路由对它透明，
  无需改

用户视角：改一行 yaml 切换 source，所有"今天有什么会"自动换数据源。
高级用户路径：直接调 ``apple_calendar.*`` / ``google_calendar.*``（详见
对应 capability module 的 docstring）。
"""
from __future__ import annotations

import logging
from typing import Any

from backend.capabilities import Consumer, TriggerMode, register_capability
from backend.config import config_yaml

logger = logging.getLogger(__name__)


def _get_default_source() -> str:
    cfg = config_yaml.get("calendar") or {}
    src = str(cfg.get("default_source") or "apple").lower()
    if src not in {"apple", "google"}:
        logger.warning(
            "[calendar] unknown default_source=%s, falling back to apple", src,
        )
        src = "apple"
    return src


async def _route_today_events(**kwargs) -> list[dict]:
    src = _get_default_source()
    if src == "apple":
        from backend.capabilities.apple_calendar import today_events as ac_today
        return await ac_today(**kwargs)
    elif src == "google":
        # google_calendar.today_events 在 google_calendar 禁用时返 [] 不抛
        from backend.capabilities.google_calendar import today_events as gc_today
        return await gc_today(**kwargs)
    return []


async def _route_upcoming_events(days_ahead: int = 7, **kwargs) -> list[dict]:
    src = _get_default_source()
    if src == "apple":
        from backend.capabilities.apple_calendar import upcoming_events as ac_up
        return await ac_up(days_ahead=days_ahead, **kwargs)
    elif src == "google":
        from backend.capabilities.google_calendar import upcoming_events as gc_up
        return await gc_up(days_ahead=days_ahead, **kwargs)
    return []


async def _router_health_check() -> dict:
    """转发到当前默认 source 的 health_check。"""
    src = _get_default_source()
    if src == "apple":
        from backend.integrations import apple_calendar as ac
        h = await ac.health_check()
    else:
        from backend.capabilities.google_calendar import _gated_health_check
        h = await _gated_health_check()
    # 在 message 里标明当前路由 source，便于面板调试
    if isinstance(h, dict):
        h = dict(h)
        h["error"] = f"[默认 source={src}] {h.get('error', '') or ''}".strip()
    return h


@register_capability(
    name="calendar.today_events",
    display_name="今日日程",
    description=(
        "获取今天的所有日历事件（本地时区）。当用户问'今天有什么会 / 安排"
        "/ 日程'，或者要做时间相关判断（比如简报、提醒）时调用。返回事件"
        "列表，每个含 title / start / end / location / all_day。底层数据"
        "源由 config.yaml calendar.default_source 决定（apple = macOS 原生 / "
        "google = Google Calendar）。"
    ),
    category="calendar",
    consumers=[Consumer.CHAT_AGENT, Consumer.SCHEDULER],
    trigger_modes=[TriggerMode.ON_DEMAND, TriggerMode.SCHEDULED],
    icon="calendar",
    parameters_schema={"type": "object", "properties": {}, "required": []},
    health_check=_router_health_check,
)
async def today_events(**_kwargs) -> list[dict]:
    return await _route_today_events(**_kwargs)


@register_capability(
    name="calendar.upcoming_events",
    display_name="未来日程",
    description=(
        "获取未来 N 天（默认 7 天，1-30）的日历事件。当用户问'这周 / 下周"
        "/ 这个月有什么 / 接下来安排'时调用。返回事件列表，按时间排序。"
        "底层数据源由 config.yaml calendar.default_source 决定。"
    ),
    category="calendar",
    consumers=[Consumer.CHAT_AGENT],
    trigger_modes=[TriggerMode.ON_DEMAND],
    icon="calendar",
    parameters_schema={
        "type": "object",
        "properties": {
            "days_ahead": {
                "type": "integer",
                "default": 7, "minimum": 1, "maximum": 30,
                "description": "向前看几天",
            },
        },
        "required": [],
    },
    health_check=_router_health_check,
)
async def upcoming_events(days_ahead: int = 7, **_kwargs) -> list[dict]:
    return await _route_upcoming_events(days_ahead=days_ahead, **_kwargs)
