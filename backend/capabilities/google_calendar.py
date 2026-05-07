"""v3-G chunk 1.6 — Google Calendar capability（上层；chunk 1 重命名）。

历史：本文件源自 chunk 1 的 ``backend/capabilities/calendar.py``（git mv 保
留 history）。chunk 1.6 接入 Apple Calendar 后，为避免命名空间冲突 + 让
LLM 看到的 calendar tool 数量不爆炸，做以下调整：

* 名字 ``calendar.today_events`` / ``calendar.upcoming_events`` → 移到新
  ``backend/capabilities/calendar.py`` 作**路由 capability**（按 config 选 source）
* 本文件改名 ``google_calendar.today_events`` / ``google_calendar.upcoming_events``，
  **从 LLM tool surface 降级为 SCHEDULER 专用**（user_visible=True 让能力面
  板仍看得到，但 ChatAgent 不会被 6 个日历相关 tool 噪音）
* 创建 / 删除事件 chunk 1 没有；chunk 1.6 的 ``apple_calendar.create_event /
  .delete_event`` 走 Apple，Google 这条路径暂不补（OAuth scope 也不允许；
  要补需要先在 ``backend/integrations/google_calendar.py`` 加 ``calendar.events``
  scope + 重新授权，详见 docs/google-calendar-setup.md §六）

启用：``config.yaml`` 顶层 ``google_calendar.enabled: true``，并按 docs/
google-calendar-setup.md 完成 OAuth。disabled 时 health_check 会返 warn 标
记"已禁用，启用请改 config.yaml"，capability 本身仍注册（便于能力面板看到
+ 高级用户直接调）。
"""
from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from backend.capabilities import Consumer, TriggerMode, register_capability
from backend.config import config_yaml
from backend.integrations import google_calendar as gc


def _get_timezone() -> str:
    sched_cfg = config_yaml.get("scheduler") or {}
    return str(sched_cfg.get("timezone") or "Asia/Tokyo")


def _is_enabled() -> bool:
    cfg = config_yaml.get("google_calendar") or {}
    # 默认 False（chunk 1.6 起 Apple 是默认 source；Google 需要主动启用）
    return bool(cfg.get("enabled", False))


async def _gated_health_check() -> dict:
    """禁用时返 warn + 启用提示；启用时透传底层 health_check。"""
    if not _is_enabled():
        return {
            "status": "warn",
            "error": "已禁用（chunk 1.6 起 Apple Calendar 是默认 source）。"
                     "要启用 Google: 改 config.yaml google_calendar.enabled=true，"
                     "并按 docs/google-calendar-setup.md 完成 OAuth。",
        }
    return await gc.health_check()


@register_capability(
    name="google_calendar.today_events",
    display_name="今日日程（Google）",
    description=(
        "获取今天（本地时区）的 Google Calendar 事件。优先用 calendar."
        "today_events 路由版本；本接口给 scheduler 直接锁定 Google 数据源用。"
    ),
    category="calendar",
    # SCHEDULER 而非 CHAT_AGENT —— 降低 LLM tool surface 噪音；用户直接想用
    # Google 时通过 calendar.* 路由 + config.default_source=google 切换
    consumers=[Consumer.SCHEDULER],
    trigger_modes=[TriggerMode.ON_DEMAND, TriggerMode.SCHEDULED],
    icon="calendar",
    parameters_schema={"type": "object", "properties": {}, "required": []},
    health_check=_gated_health_check,
)
async def today_events(**_kwargs) -> list[dict]:
    if not _is_enabled():
        return []
    tz = ZoneInfo(_get_timezone())
    now = datetime.now(tz)
    start = datetime.combine(now.date(), time.min, tzinfo=tz)
    end   = datetime.combine(now.date(), time.max, tzinfo=tz)
    return await gc.list_events_in_range(start, end)


@register_capability(
    name="google_calendar.upcoming_events",
    display_name="未来日程（Google）",
    description=(
        "获取未来 N 天（默认 7，1-30）的 Google Calendar 事件。优先用 "
        "calendar.upcoming_events 路由版本；本接口锁定 Google 数据源。"
    ),
    category="calendar",
    consumers=[Consumer.SCHEDULER],
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
    health_check=_gated_health_check,
)
async def upcoming_events(days_ahead: int = 7, **_kwargs) -> list[dict]:
    if not _is_enabled():
        return []
    days_ahead = max(1, min(30, int(days_ahead)))
    tz = ZoneInfo(_get_timezone())
    now = datetime.now(tz)
    end = now + timedelta(days=days_ahead)
    return await gc.list_events_in_range(now, end)
