"""Tests for v3-G chunk 1.6 — Apple Calendar integration + capabilities.

EventKit / macOS 系统调用全 mock。CI 跨平台跑也不依赖真实日历。
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import backend.integrations.apple_calendar as ac

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))


# ---------------------------------------------------------------------------
# 1. health_check 各档
# ---------------------------------------------------------------------------

async def test_health_check_non_macos():
    print("\n[apple_calendar — health: non-macOS warn]")
    with patch.object(ac, "IS_MACOS", False), \
         patch.object(ac, "EventKit", None):
        h = await ac.health_check()
    check("non-macOS → warn", h["status"] == "warn")
    check("非 macOS message", "macOS" in (h.get("error") or ""))


async def test_health_check_eventkit_missing():
    print("\n[apple_calendar — health: pyobjc not installed warn]")
    with patch.object(ac, "IS_MACOS", True), \
         patch.object(ac, "EventKit", None):
        h = await ac.health_check()
    check("EventKit None → warn", h["status"] == "warn")
    check("Mentions pyobjc", "pyobjc" in (h.get("error") or ""))


async def test_health_check_unauthorized_warn():
    print("\n[apple_calendar — health: unauthorized warn]")
    fake_ek = MagicMock()
    fake_ek.EKEntityTypeEvent = 0
    fake_ek.EKEventStore.authorizationStatusForEntityType_.return_value = 0  # NotDetermined
    with patch.object(ac, "IS_MACOS", True), \
         patch.object(ac, "EventKit", fake_ek), \
         patch.object(ac, "_macos_major", 14):
        h = await ac.health_check()
    check("unauthorized → warn", h["status"] == "warn")
    check("授权 hint 文案", "未授权" in (h.get("error") or ""))


async def _run_health_with_status(status_value: int, macos_major: int = 14) -> dict:
    fake_ek = MagicMock()
    fake_ek.EKEntityTypeEvent = 0
    fake_ek.EKEventStore.authorizationStatusForEntityType_.return_value = status_value
    fake_store = MagicMock()
    fake_store.calendarsForEntityType_.return_value = [MagicMock(), MagicMock(), MagicMock()]
    fake_ek.EKEventStore.alloc.return_value.init.return_value = fake_store

    with patch.object(ac, "IS_MACOS", True), \
         patch.object(ac, "EventKit", fake_ek), \
         patch.object(ac, "_macos_major", macos_major), \
         patch.object(ac, "_store", None):
        return await ac.health_check()


async def test_health_check_authorized_healthy():
    print("\n[apple_calendar — health: FullAccess (5, macOS 14+) → healthy]")
    h = await _run_health_with_status(5)
    check("status=5 FullAccess → healthy", h["status"] == "healthy", f"got {h}")
    check("calendar_count = 3", h.get("calendar_count") == 3)


async def test_health_check_legacy_authorized_healthy():
    print("\n[apple_calendar — health: legacy Authorized (3, macOS 13-) → healthy]")
    h = await _run_health_with_status(3, macos_major=13)
    check("status=3 legacy Authorized → healthy", h["status"] == "healthy", f"got {h}")


async def test_health_check_write_only_warn():
    print("\n[apple_calendar — health: WriteOnly (4) → warn]")
    h = await _run_health_with_status(4)
    check("status=4 WriteOnly → warn", h["status"] == "warn", f"got {h}")
    check("WriteOnly hint mentions 未授权", "未授权" in (h.get("error") or ""))


async def test_health_check_denied_warn():
    print("\n[apple_calendar — health: Denied (2) → warn]")
    h = await _run_health_with_status(2)
    check("status=2 Denied → warn", h["status"] == "warn", f"got {h}")


async def test_health_check_old_macos_warn():
    print("\n[apple_calendar — health: macOS < 12 warn]")
    fake_ek = MagicMock()
    with patch.object(ac, "IS_MACOS", True), \
         patch.object(ac, "EventKit", fake_ek), \
         patch.object(ac, "_macos_major", 11):
        h = await ac.health_check()
    check("macOS 11 → warn", h["status"] == "warn")
    check("提示 macOS 12+", "12+" in (h.get("error") or ""))


# ---------------------------------------------------------------------------
# 2. event normalisation
# ---------------------------------------------------------------------------

async def test_event_normalisation():
    print("\n[apple_calendar — _normalise_event payload shape]")
    fake_ek = MagicMock()
    with patch.object(ac, "IS_MACOS", True), \
         patch.object(ac, "EventKit", fake_ek):
        # 构造 fake EKEvent
        fake_event = MagicMock()
        fake_event.eventIdentifier.return_value = "ABCDEF"
        fake_event.title.return_value = "晨会"
        fake_cal = MagicMock()
        fake_cal.title.return_value = "工作"
        fake_event.calendar.return_value = fake_cal
        fake_event.location.return_value = "Zoom"
        fake_event.notes.return_value = "讨论 Q3 路线图"
        fake_event.isAllDay.return_value = False

        ts = datetime(2026, 5, 7, 9, 0, tzinfo=timezone.utc).timestamp()
        fake_start = MagicMock()
        fake_start.timeIntervalSince1970.return_value = ts
        fake_event.startDate.return_value = fake_start
        fake_end = MagicMock()
        fake_end.timeIntervalSince1970.return_value = ts + 3600
        fake_event.endDate.return_value = fake_end

        out = ac._normalise_event(fake_event, timezone.utc)
    check("id passed through", out["id"] == "ABCDEF")
    check("title passed through", out["title"] == "晨会")
    check("calendar name", out["calendar"] == "工作")
    check("location", out["location"] == "Zoom")
    check("description = notes", out["description"] == "讨论 Q3 路线图")
    check("all_day False", out["all_day"] is False)
    check("start ISO contains 2026-05-07", "2026-05-07" in out["start"])


async def test_event_fallback_no_title():
    print("\n[apple_calendar — _normalise_event empty title fallback]")
    fake_ek = MagicMock()
    with patch.object(ac, "IS_MACOS", True), \
         patch.object(ac, "EventKit", fake_ek):
        fake_event = MagicMock()
        fake_event.eventIdentifier.return_value = "X"
        fake_event.title.return_value = None  # empty
        fake_event.calendar.return_value = None
        fake_event.location.return_value = ""
        fake_event.notes.return_value = ""
        fake_event.isAllDay.return_value = True
        fake_event.startDate.return_value = None
        fake_event.endDate.return_value = None

        out = ac._normalise_event(fake_event, timezone.utc)
    check("no title → (无标题) fallback", out["title"] == "(无标题)")
    check("None startDate → empty string", out["start"] == "")
    check("all_day True", out["all_day"] is True)


# ---------------------------------------------------------------------------
# 3. capability surface (registration + LLM exposure)
# ---------------------------------------------------------------------------

async def test_apple_caps_registered():
    print("\n[capabilities.apple_calendar — registration]")
    # import 触发装饰器副作用
    from backend.capabilities import CapabilityRegistry, Consumer
    import backend.capabilities.apple_calendar  # noqa: F401

    reg = CapabilityRegistry()
    expected = [
        "apple_calendar.today_events",
        "apple_calendar.upcoming_events",
        "apple_calendar.create_event",
        "apple_calendar.delete_event",
    ]
    for name in expected:
        check(f"{name} registered", reg.get(name) is not None)

    # CHAT_AGENT 暴露：所有 4 个都可由 LLM 调（按用户 spec）
    create_cap = reg.get("apple_calendar.create_event")
    check(
        "create_event in CHAT_AGENT",
        Consumer.CHAT_AGENT in create_cap.consumers,
    )

    # parameters_schema required
    check(
        "create_event requires title + start_iso",
        set(create_cap.parameters_schema["required"]) == {"title", "start_iso"},
    )


# ---------------------------------------------------------------------------
# 4. capability create_event ISO parsing
# ---------------------------------------------------------------------------

async def test_create_event_invalid_iso():
    print("\n[capabilities.apple_calendar — create_event invalid ISO raises]")
    from backend.capabilities.apple_calendar import create_event

    raised = False
    try:
        await create_event(title="x", start_iso="not-a-date")
    except ValueError as exc:
        raised = "ISO 8601" in str(exc) or "iso" in str(exc).lower()
    check("invalid ISO → ValueError", raised)


async def test_create_event_dispatches():
    print("\n[capabilities.apple_calendar — create_event dispatches with parsed dt]")
    from backend.capabilities.apple_calendar import create_event

    called = {}
    async def fake_create(title, start, duration_minutes, description, calendar_name, tz):
        called["title"] = title
        called["start"] = start
        called["duration"] = duration_minutes
        called["calendar"] = calendar_name
        return "EVT-123"

    with patch.object(ac, "create_event", fake_create):
        result = await create_event(
            title="看牙医",
            start_iso="2026-05-08T10:00:00+09:00",
            duration_minutes=45,
            calendar_name="个人",
        )

    check("event_id returned", result["event_id"] == "EVT-123")
    check("title forwarded", called["title"] == "看牙医")
    check("duration forwarded", called["duration"] == 45)
    check("calendar forwarded", called["calendar"] == "个人")
    check("start parsed to datetime", isinstance(called["start"], datetime))
    check("start tz preserved", called["start"].utcoffset() == timedelta(hours=9))


# ---------------------------------------------------------------------------
# 5. delete_event
# ---------------------------------------------------------------------------

async def test_delete_event():
    print("\n[capabilities.apple_calendar — delete_event passthrough]")
    from backend.capabilities.apple_calendar import delete_event

    async def fake_delete(eid):
        return eid == "exists"

    with patch.object(ac, "delete_event", fake_delete):
        r1 = await delete_event(event_id="exists")
        r2 = await delete_event(event_id="missing")
    check("existing → deleted=True", r1["deleted"] is True)
    check("missing → deleted=False", r2["deleted"] is False)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

async def main():
    await test_health_check_non_macos()
    await test_health_check_eventkit_missing()
    await test_health_check_unauthorized_warn()
    await test_health_check_authorized_healthy()
    await test_health_check_legacy_authorized_healthy()
    await test_health_check_write_only_warn()
    await test_health_check_denied_warn()
    await test_health_check_old_macos_warn()
    await test_event_normalisation()
    await test_event_fallback_no_title()
    await test_apple_caps_registered()
    await test_create_event_invalid_iso()
    await test_create_event_dispatches()
    await test_delete_event()

    total = len(results)
    passed = sum(1 for _, ok in results if ok)
    print(f"\n{'='*40}")
    print(f"Results: {passed}/{total} passed")
    if passed < total:
        print("FAILED:", ", ".join(n for n, ok in results if not ok))
        sys.exit(1)
    else:
        print("ALL TESTS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
