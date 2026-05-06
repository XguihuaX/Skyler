"""v3-G chunk 0 — Time capability.

第一个内置 capability。给 ChatAgent 一个权威的"现在几点"调用入口（不再
靠 LLM 自己根据 prompt 里的时间戳推），同时也是 SCHEDULER consumer 的
demo 配方：cron / interval 触发的任务可以直接调 ``get_current_time()``
拿权威时间。

时区：与 cron scheduler 共用 ``config.yaml`` ``scheduler.timezone`` 配置，
保证 cron 触发时间与 capability 返回的"now"在同一时区。
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from backend.capabilities import Consumer, TriggerMode, register_capability
from backend.config import config_yaml


def _get_timezone() -> str:
    sched_cfg = config_yaml.get("scheduler") or {}
    return str(sched_cfg.get("timezone") or "Asia/Tokyo")


_WEEKDAY_ZH = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


async def _time_health_check() -> dict:
    """ZoneInfo 拿不到 = 异常；正常返回 healthy。"""
    try:
        ZoneInfo(_get_timezone())
        return {"status": "healthy"}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


@register_capability(
    name="time.now",
    display_name="获取当前时间",
    description=(
        "获取当前的精确时间、时区和星期。当用户问'现在几点'或需要做时间"
        "相关判断（晚安提醒 / 工作日识别 / 时段问候）时调用。"
    ),
    category="system",
    consumers=[Consumer.CHAT_AGENT, Consumer.SCHEDULER],
    trigger_modes=[TriggerMode.ON_DEMAND],
    icon="clock",
    parameters_schema={"type": "object", "properties": {}, "required": []},
    health_check=_time_health_check,
)
async def get_current_time(**_kwargs) -> dict:
    """返回 ``{iso, timezone, human, weekday, is_weekend}``。

    ``**_kwargs`` 兜住 ChatAgent 注入的 ``user_id``（capability 本身不需要）。
    """
    tz_name = _get_timezone()
    tz = ZoneInfo(tz_name)
    now = datetime.now(tz)
    weekday_idx = now.weekday()  # Mon=0, Sun=6
    return {
        "iso": now.isoformat(),
        "timezone": tz_name,
        "human": now.strftime("%Y-%m-%d %H:%M:%S"),
        "weekday": _WEEKDAY_ZH[weekday_idx],
        "is_weekend": weekday_idx >= 5,
    }
