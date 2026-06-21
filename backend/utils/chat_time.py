"""DailyAgent Stage 1 — 时间地基工具。

两类辅助:

1. ``now_local(tz_name)`` — 取本地当前时间(scheduler timezone),供
   system prompt 拼"现在 X" 与 daily_plan 生成"今天日期"使用。
2. ``format_history_time_prefix(created_at_utc, tz_name, now_local_dt)`` —
   chat.py 拼 short_term history 时,把每条 turn 的 ``created_at``(UTC)
   渲染成 ``[今天 12:31]`` / ``[昨天 22:10]`` / ``[6月19日 20:00]`` 前缀。
   created_at 缺失 → 返 ``""``(caller 不前缀,优雅降级)。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

try:
    from zoneinfo import ZoneInfo  # py>=3.9
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore[assignment]


_WEEKDAY_ZH = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def _resolve_tz(tz_name: Optional[str]):
    """zoneinfo 加载;失败回退 UTC。"""
    if not tz_name or ZoneInfo is None:
        return timezone.utc
    try:
        return ZoneInfo(tz_name)
    except Exception:
        return timezone.utc


def get_scheduler_tz_name() -> str:
    """从 ``config.yaml`` ``scheduler.timezone`` 读;缺省 Asia/Tokyo。

    与 ``backend/scheduler/cron.py:_get_timezone`` 同源,避免重复读取。
    每次调用都重读 config_yaml(支持 ``reload_config_yaml`` 热更),
    不缓存。
    """
    try:
        from backend.config import config_yaml
        sched_cfg = config_yaml.get("scheduler") or {}
        return str(sched_cfg.get("timezone") or "Asia/Tokyo")
    except Exception:
        return "Asia/Tokyo"


def now_local(tz_name: Optional[str] = None) -> datetime:
    """返回当前**带 tzinfo** 的本地 datetime;tz_name=None → 用 scheduler tz。"""
    return datetime.now(_resolve_tz(tz_name or get_scheduler_tz_name()))


def weekday_zh(dt: datetime) -> str:
    """周一..周日。"""
    return _WEEKDAY_ZH[dt.weekday()]


def format_now_prompt(tz_name: Optional[str] = None) -> str:
    """system prompt 用:`2026-06-21 周日 14:30`(默认 scheduler tz)。"""
    dt = now_local(tz_name)
    return f"{dt.strftime('%Y-%m-%d')} {weekday_zh(dt)} {dt.strftime('%H:%M')}"


def _to_local(created_at_utc: datetime, tz):
    """UTC datetime → 带 tzinfo 的本地 datetime。

    旧 row 若是 naive(server_default=CURRENT_TIMESTAMP 写的),按 UTC 解读。
    """
    if created_at_utc.tzinfo is None:
        return created_at_utc.replace(tzinfo=timezone.utc).astimezone(tz)
    return created_at_utc.astimezone(tz)


def format_history_time_prefix(
    created_at_utc: Optional[datetime],
    tz_name: Optional[str] = None,
    now_local_dt: Optional[datetime] = None,
) -> str:
    """chat.py 拼 history 用:返回 ``[今天 HH:MM]`` / ``[昨天 HH:MM]`` /
    ``[M月D日 HH:MM]`` / ``""``(无 ts → 不前缀)。

    - **不**带尾随空格,caller 决定怎么拼(通常 ``f"{prefix} {content}"``)
    - now_local_dt 可外传(同一 turn 批量拼,共享同一"现在"),省 ZoneInfo
      重建开销;省略则内取一次
    - tz_name 缺省 → scheduler.timezone(默 Asia/Tokyo)
    """
    if created_at_utc is None:
        return ""
    tz = _resolve_tz(tz_name or get_scheduler_tz_name())
    if now_local_dt is None:
        now_local_dt = datetime.now(tz)
    local_dt = _to_local(created_at_utc, tz)

    today = now_local_dt.date()
    that_day = local_dt.date()
    delta_days = (today - that_day).days

    hhmm = local_dt.strftime("%H:%M")
    if delta_days == 0:
        return f"[今天 {hhmm}]"
    if delta_days == 1:
        return f"[昨天 {hhmm}]"
    # 旧消息:M月D日 HH:MM(无年份 — short_term 上限 60 条 ≈ 不会跨年)
    return f"[{local_dt.month}月{local_dt.day}日 {hhmm}]"


__all__ = [
    "get_scheduler_tz_name",
    "now_local",
    "weekday_zh",
    "format_now_prompt",
    "format_history_time_prefix",
]
