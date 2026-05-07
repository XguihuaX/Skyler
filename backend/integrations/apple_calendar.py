"""v3-G chunk 1.6 — Apple Calendar 底层 client (macOS EventKit)。

职责（**只是底层**，不带 ``@register_capability``）：

* macOS EventKit 权限申请（macOS 14+ 用 ``requestFullAccessToEventsWithCompletion_``，
  旧版 fallback 到 ``requestAccessToEntityType_completion_``）
* EKEventStore 单例
* list / create / delete event
* health_check —— 区分 ``healthy`` / ``warn``：未授权 / macOS 12 以下 /
  非 macOS 平台都是 warn（不是 error，符合 chunk 1 Google Calendar 的"国
  内常态降级 warn"传统）

跨平台
======
非 macOS 平台 import 时**优雅降级** —— 不抛 ImportError 阻塞 lifespan，全部
公开函数以 health_check 为入口返 warn，调用类函数抛 ``RuntimeError`` 由
capability 层捕获返 ``{"isError": True, ...}``。

asyncio 集成
============
EventKit API 是同步阻塞 + Cocoa run loop callback 风格。我们用
``asyncio.to_thread`` 把所有同步调用包到线程，避免堵 FastAPI event loop。
权限申请回调跑在 main run loop —— 用 ``threading.Event`` 把回调结果同步到
当前线程，整体仍然是 ``asyncio.to_thread`` 友好的（详见 _request_access_blocking）。
"""
from __future__ import annotations

import logging
import platform
import sys
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 平台检测 + 模块级 EventKit lazy import
# ---------------------------------------------------------------------------

IS_MACOS = sys.platform == "darwin"
_macos_major = 0
if IS_MACOS:
    try:
        # platform.mac_ver()[0] like "26.2" / "14.5" / "13.6"
        _macos_major = int(platform.mac_ver()[0].split(".")[0])
    except Exception:
        _macos_major = 0


# EventKit / Foundation 只在 macOS 上 import；其它平台保持 None
EventKit = None  # type: ignore[assignment]
NSDate = None    # type: ignore[assignment]

if IS_MACOS:
    try:
        import EventKit as _EventKit  # type: ignore
        from Foundation import NSDate as _NSDate  # type: ignore
        EventKit = _EventKit
        NSDate = _NSDate
    except ImportError as exc:
        logger.warning(
            "[apple_calendar] pyobjc-framework-EventKit not installed: %s", exc,
        )


# ---------------------------------------------------------------------------
# EKEventStore 单例
# ---------------------------------------------------------------------------

_store: Any = None


def _get_store() -> Any:
    global _store
    if EventKit is None:
        raise RuntimeError("Apple Calendar 仅 macOS 可用")
    if _store is None:
        _store = EventKit.EKEventStore.alloc().init()
    return _store


def _reset_store_cache() -> None:
    """测试 / 撤销权限后重建单例。"""
    global _store
    _store = None


# ---------------------------------------------------------------------------
# 权限申请（macOS 14+ 新 API + 旧版兜底）
# ---------------------------------------------------------------------------

def _is_authorized_sync() -> bool:
    """同步看当前授权状态。FullAccess (3) / Authorized (3) 都算授权通过。"""
    if EventKit is None:
        return False
    status = EventKit.EKEventStore.authorizationStatusForEntityType_(
        EventKit.EKEntityTypeEvent
    )
    # macOS 14+ FullAccess = 3；旧版 Authorized = 3。两个常量值相同，直接比 3。
    return status == 3


def _request_access_blocking(timeout: float = 30.0) -> bool:
    """触发系统权限弹框。**阻塞**等用户点 允许 / 拒绝。

    macOS 14+ 用 ``requestFullAccessToEventsWithCompletion_``；之前版本回
    退到 ``requestAccessToEntityType_completion_``。
    callback 跑在 main run loop，用 threading.Event 同步到调用线程。
    超时返 False（用户没点对话框）。
    """
    if EventKit is None:
        return False
    store = _get_store()

    done = threading.Event()
    granted = {"value": False, "error": None}

    def _cb(grant_result, error):
        granted["value"] = bool(grant_result)
        if error is not None:
            granted["error"] = str(error)
        done.set()

    if _macos_major >= 14 and hasattr(store, "requestFullAccessToEventsWithCompletion_"):
        store.requestFullAccessToEventsWithCompletion_(_cb)
    else:
        store.requestAccessToEntityType_completion_(EventKit.EKEntityTypeEvent, _cb)

    if not done.wait(timeout):
        logger.warning("[apple_calendar] permission prompt timed out")
        return False
    if granted["error"]:
        logger.warning("[apple_calendar] permission error: %s", granted["error"])
    return granted["value"]


# ---------------------------------------------------------------------------
# 公开 API（同步内核 + asyncio.to_thread 在 capability 层包装）
# ---------------------------------------------------------------------------

def _datetime_to_nsdate(dt: datetime) -> Any:
    """Python datetime → NSDate。要求 dt 已带 tzinfo（避免本地化二义）。"""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return NSDate.dateWithTimeIntervalSince1970_(dt.timestamp())


def _nsdate_to_iso(nsdate: Any, tz: timezone) -> str:
    """NSDate → ISO 8601。NSDate 内部是 absolute time（没有时区），按指定 tz 格式化。"""
    if nsdate is None:
        return ""
    ts = nsdate.timeIntervalSince1970()
    return datetime.fromtimestamp(ts, tz=tz).isoformat()


def _normalise_event(ev: Any, tz: timezone) -> dict:
    """EKEvent → 统一 dict shape（与 google_calendar._normalise_event 对齐）。"""
    return {
        "id":       str(ev.eventIdentifier()) if ev.eventIdentifier() else "",
        "title":    str(ev.title()) if ev.title() else "(无标题)",
        "start":    _nsdate_to_iso(ev.startDate(), tz),
        "end":      _nsdate_to_iso(ev.endDate(), tz),
        "all_day":  bool(ev.isAllDay()),
        "location": str(ev.location()) if ev.location() else "",
        "description": str(ev.notes()) if ev.notes() else "",
        "calendar": str(ev.calendar().title()) if ev.calendar() else "",
    }


def _list_events_sync(start: datetime, end: datetime, tz: timezone) -> list[dict]:
    if not _is_authorized_sync():
        # 第一次调用的"惰性请求授权"路径 —— 触发系统弹框
        if not _request_access_blocking():
            raise PermissionError("Apple Calendar 未授权（用户拒绝或超时）")
        _reset_store_cache()
    store = _get_store()
    cals = store.calendarsForEntityType_(EventKit.EKEntityTypeEvent)
    pred = store.predicateForEventsWithStartDate_endDate_calendars_(
        _datetime_to_nsdate(start),
        _datetime_to_nsdate(end),
        cals,
    )
    events = store.eventsMatchingPredicate_(pred) or []
    return [_normalise_event(e, tz) for e in events]


def _create_event_sync(
    title: str,
    start: datetime,
    duration_minutes: int,
    description: Optional[str],
    calendar_name: Optional[str],
    tz: timezone,
) -> str:
    if not _is_authorized_sync():
        if not _request_access_blocking():
            raise PermissionError("Apple Calendar 未授权（用户拒绝或超时）")
        _reset_store_cache()
    store = _get_store()
    event = EventKit.EKEvent.eventWithEventStore_(store)
    event.setTitle_(title)
    event.setStartDate_(_datetime_to_nsdate(start))
    end_dt = start + timedelta(minutes=max(1, int(duration_minutes)))
    event.setEndDate_(_datetime_to_nsdate(end_dt))
    if description:
        event.setNotes_(description)

    # 选 calendar
    chosen = None
    if calendar_name:
        for cal in store.calendarsForEntityType_(EventKit.EKEntityTypeEvent):
            if str(cal.title()) == calendar_name:
                chosen = cal
                break
    if chosen is None:
        chosen = store.defaultCalendarForNewEvents()
    if chosen is None:
        raise RuntimeError("找不到可用日历（系统默认日历未设置？）")
    event.setCalendar_(chosen)

    # span = ThisEvent (0)；commit=True 立即落盘
    success, err = store.saveEvent_span_commit_error_(event, 0, True, None)
    if not success:
        msg = str(err) if err else "unknown error"
        raise RuntimeError(f"保存事件失败：{msg}")
    eid = event.eventIdentifier()
    return str(eid) if eid else ""


def _delete_event_sync(event_id: str) -> bool:
    if not _is_authorized_sync():
        if not _request_access_blocking():
            raise PermissionError("Apple Calendar 未授权（用户拒绝或超时）")
        _reset_store_cache()
    store = _get_store()
    event = store.eventWithIdentifier_(event_id)
    if event is None:
        return False
    success, err = store.removeEvent_span_commit_error_(event, 0, True, None)
    if not success:
        msg = str(err) if err else "unknown error"
        raise RuntimeError(f"删除事件失败：{msg}")
    return True


# ---------------------------------------------------------------------------
# Async wrappers
# ---------------------------------------------------------------------------

import asyncio


async def list_events_in_range(
    start: datetime, end: datetime, tz: Optional[timezone] = None,
) -> list[dict]:
    if tz is None:
        tz = timezone.utc
    return await asyncio.to_thread(_list_events_sync, start, end, tz)


async def create_event(
    title: str,
    start: datetime,
    duration_minutes: int = 30,
    description: Optional[str] = None,
    calendar_name: Optional[str] = None,
    tz: Optional[timezone] = None,
) -> str:
    if tz is None:
        tz = timezone.utc
    return await asyncio.to_thread(
        _create_event_sync, title, start, duration_minutes,
        description, calendar_name, tz,
    )


async def delete_event(event_id: str) -> bool:
    return await asyncio.to_thread(_delete_event_sync, event_id)


async def health_check() -> dict:
    """三档：

    * ``warn`` —— 非 macOS / pyobjc-framework-EventKit 没装 / 未授权
    * ``healthy`` —— 已授权且能拿到日历列表
    * ``error`` —— 不会返回；意外异常被吞成 warn
    """
    if not IS_MACOS:
        return {
            "status": "warn",
            "error": f"Apple Calendar 仅 macOS 可用（当前平台 {sys.platform}）",
        }
    if EventKit is None:
        return {
            "status": "warn",
            "error": "pyobjc-framework-EventKit 未安装；pip install -r requirements.txt",
        }
    if _macos_major and _macos_major < 12:
        return {
            "status": "warn",
            "error": f"Apple Calendar 集成需要 macOS 12+（当前 {_macos_major}）",
        }
    try:
        if not _is_authorized_sync():
            return {
                "status": "warn",
                "error": "未授权访问日历。第一次调用日历相关 capability 时 macOS 会弹权限框；或在系统设置 → 隐私与安全性 → 日历 中手动授予。",
            }
        # 已授权 → 试拿一次日历列表，验证 EKEventStore 真能用
        store = _get_store()
        cals = store.calendarsForEntityType_(EventKit.EKEntityTypeEvent)
        return {
            "status": "healthy",
            "error": None,
            "calendar_count": len(cals or []),
        }
    except Exception as exc:
        return {"status": "warn", "error": f"健康检查异常：{exc}"}


# ---------------------------------------------------------------------------
# 测试钩子
# ---------------------------------------------------------------------------

def _is_macos() -> bool:
    """仅供测试 mock。"""
    return IS_MACOS
