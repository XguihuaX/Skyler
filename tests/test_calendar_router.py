"""Tests for v3-G chunk 1.6 — calendar router + Google chunk 1 namespace rename."""
import asyncio
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Trigger registrations (apple + google + router)
import backend.capabilities.apple_calendar     # noqa: F401
import backend.capabilities.google_calendar    # noqa: F401
import backend.capabilities.calendar           # noqa: F401
from backend.capabilities import CapabilityRegistry, Consumer
from backend.capabilities import calendar as cal_router

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))


# ---------------------------------------------------------------------------
# 1. 命名空间 — chunk 1 calendar.* 重命名为 google_calendar.*
# ---------------------------------------------------------------------------

async def test_google_namespace_renamed():
    print("\n[calendar router — google chunk 1 namespace renamed]")
    reg = CapabilityRegistry()
    check("google_calendar.today_events exists", reg.get("google_calendar.today_events") is not None)
    check("google_calendar.upcoming_events exists", reg.get("google_calendar.upcoming_events") is not None)
    # router 占用 calendar.* 名字
    check("calendar.today_events exists (router)", reg.get("calendar.today_events") is not None)


async def test_google_namespace_consumers_demoted():
    print("\n[calendar router — google direct caps SCHEDULER-only (LLM bloat reduction)]")
    reg = CapabilityRegistry()
    g_today = reg.get("google_calendar.today_events")
    check(
        "google_calendar.today_events not in CHAT_AGENT",
        Consumer.CHAT_AGENT not in g_today.consumers,
        f"consumers={[c.value for c in g_today.consumers]}",
    )
    check(
        "google_calendar.today_events still SCHEDULER",
        Consumer.SCHEDULER in g_today.consumers,
    )


async def test_router_is_chat_agent_visible():
    print("\n[calendar router — router caps in CHAT_AGENT]")
    reg = CapabilityRegistry()
    r_today = reg.get("calendar.today_events")
    check("calendar.today_events in CHAT_AGENT", Consumer.CHAT_AGENT in r_today.consumers)
    check("calendar.today_events in SCHEDULER", Consumer.SCHEDULER in r_today.consumers)


# ---------------------------------------------------------------------------
# 2. 路由 — default_source=apple
# ---------------------------------------------------------------------------

async def test_route_to_apple():
    print("\n[calendar router — default_source=apple]")
    fake_yaml = {"calendar": {"default_source": "apple"}}

    apple_called = {"n": 0}
    google_called = {"n": 0}

    async def fake_apple_today(**_kw):
        apple_called["n"] += 1
        return [{"src": "apple", "title": "晨会"}]
    async def fake_google_today(**_kw):
        google_called["n"] += 1
        return []

    with patch.object(cal_router, "config_yaml", fake_yaml), \
         patch("backend.capabilities.apple_calendar.today_events", fake_apple_today), \
         patch("backend.capabilities.google_calendar.today_events", fake_google_today):
        out = await cal_router._route_today_events()

    check("apple handler called once", apple_called["n"] == 1)
    check("google handler not called", google_called["n"] == 0)
    check("apple result returned", out == [{"src": "apple", "title": "晨会"}])


async def test_route_to_google():
    print("\n[calendar router — default_source=google]")
    fake_yaml = {"calendar": {"default_source": "google"}}

    apple_called = {"n": 0}
    google_called = {"n": 0}

    async def fake_apple_today(**_kw):
        apple_called["n"] += 1
        return []
    async def fake_google_today(**_kw):
        google_called["n"] += 1
        return [{"src": "google"}]

    with patch.object(cal_router, "config_yaml", fake_yaml), \
         patch("backend.capabilities.apple_calendar.today_events", fake_apple_today), \
         patch("backend.capabilities.google_calendar.today_events", fake_google_today):
        out = await cal_router._route_today_events()

    check("google handler called", google_called["n"] == 1)
    check("apple handler not called", apple_called["n"] == 0)
    check("google result returned", out == [{"src": "google"}])


async def test_route_unknown_source_falls_back_to_apple():
    print("\n[calendar router — unknown source → apple fallback]")
    fake_yaml = {"calendar": {"default_source": "yahoo"}}

    apple_called = {"n": 0}

    async def fake_apple_today(**_kw):
        apple_called["n"] += 1
        return []

    with patch.object(cal_router, "config_yaml", fake_yaml), \
         patch("backend.capabilities.apple_calendar.today_events", fake_apple_today):
        await cal_router._route_today_events()
    check("unknown source → apple called", apple_called["n"] == 1)


async def test_route_no_config_default_apple():
    print("\n[calendar router — missing config → default apple]")
    apple_called = {"n": 0}

    async def fake_apple_today(**_kw):
        apple_called["n"] += 1
        return []

    with patch.object(cal_router, "config_yaml", {}), \
         patch("backend.capabilities.apple_calendar.today_events", fake_apple_today):
        await cal_router._route_today_events()
    check("missing calendar block → apple", apple_called["n"] == 1)


# ---------------------------------------------------------------------------
# 3. upcoming_events 转发 days_ahead
# ---------------------------------------------------------------------------

async def test_upcoming_forwards_days_ahead():
    print("\n[calendar router — upcoming forwards days_ahead]")
    fake_yaml = {"calendar": {"default_source": "apple"}}
    captured = {}

    async def fake_apple_up(days_ahead=7, **_kw):
        captured["days"] = days_ahead
        return []

    with patch.object(cal_router, "config_yaml", fake_yaml), \
         patch("backend.capabilities.apple_calendar.upcoming_events", fake_apple_up):
        await cal_router._route_upcoming_events(days_ahead=14)
    check("days_ahead forwarded", captured.get("days") == 14)


# ---------------------------------------------------------------------------
# 4. google_calendar disabled gating
# ---------------------------------------------------------------------------

async def test_google_disabled_returns_empty_no_oauth_call():
    print("\n[google_calendar gated when disabled]")
    fake_yaml = {"google_calendar": {"enabled": False}}
    from backend.capabilities import google_calendar as g

    api_called = {"n": 0}
    async def fake_list(*a, **kw):
        api_called["n"] += 1
        return []

    with patch.object(g, "config_yaml", fake_yaml), \
         patch("backend.integrations.google_calendar.list_events_in_range", fake_list):
        out = await g.today_events()
    check("disabled returns []", out == [])
    check("API not called when disabled", api_called["n"] == 0)


async def test_google_disabled_health_check():
    print("\n[google_calendar disabled health is warn + 启用提示]")
    fake_yaml = {"google_calendar": {"enabled": False}}
    from backend.capabilities import google_calendar as g

    with patch.object(g, "config_yaml", fake_yaml):
        h = await g._gated_health_check()
    check("disabled → warn", h["status"] == "warn")
    check("启用提示文案", "启用 Google" in (h.get("error") or "") or "google_calendar.enabled" in (h.get("error") or ""))


# ---------------------------------------------------------------------------
# 5. briefing 模块仍正常 import calendar.today_events
# ---------------------------------------------------------------------------

async def test_briefing_import_still_works():
    print("\n[briefing — import calendar.today_events still works]")
    from backend.scheduler.briefing import generate_morning_briefing
    fake_yaml = {"calendar": {"default_source": "apple"}, "scheduler": {"timezone": "Asia/Tokyo"}}

    async def fake_apple_today(**_kw):
        return []  # no events → 应触发 "今天没有日程" friendly text

    with patch.object(cal_router, "config_yaml", fake_yaml), \
         patch("backend.capabilities.apple_calendar.today_events", fake_apple_today):
        text = await generate_morning_briefing()
    check("briefing generates text", isinstance(text, str) and len(text) > 0)
    check("正确选 apple → 没有日程文案（route worked）", "没有日程" in text, f"got: {text!r}")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

async def main():
    await test_google_namespace_renamed()
    await test_google_namespace_consumers_demoted()
    await test_router_is_chat_agent_visible()
    await test_route_to_apple()
    await test_route_to_google()
    await test_route_unknown_source_falls_back_to_apple()
    await test_route_no_config_default_apple()
    await test_upcoming_forwards_days_ahead()
    await test_google_disabled_returns_empty_no_oauth_call()
    await test_google_disabled_health_check()
    await test_briefing_import_still_works()

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
