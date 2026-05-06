"""Tests for v3-G chunk 1 — 起床简报 v0.1 文本生成。

只测纯函数（``generate_morning_briefing`` + 事件格式化），不测完整 delivery
（涉及 DB / WS / TTS，集成层走 curl 验证更直接）。
"""
import asyncio
import os
import sys
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.scheduler import briefing

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))


# ---------------------------------------------------------------------------
# 1. 事件格式化
# ---------------------------------------------------------------------------

async def test_format_event_timed():
    print("\n[briefing — format timed event]")
    tz = ZoneInfo("Asia/Tokyo")
    e = {
        "title": "晨会",
        "start": "2026-05-07T09:00:00+09:00",
        "all_day": False,
    }
    out = briefing._format_event_for_briefing(e, tz)
    check("9点 → 上午9点 晨会", out == "上午9点 晨会", f"got {out!r}")

    e2 = {
        "title": "下午茶",
        "start": "2026-05-07T15:30:00+09:00",
        "all_day": False,
    }
    out2 = briefing._format_event_for_briefing(e2, tz)
    check("15:30 → 下午3点30 下午茶", out2 == "下午3点30 下午茶", f"got {out2!r}")


async def test_format_event_all_day():
    print("\n[briefing — format all-day event]")
    tz = ZoneInfo("Asia/Tokyo")
    e = {"title": "团建", "start": "2026-05-07", "all_day": True}
    out = briefing._format_event_for_briefing(e, tz)
    check("all-day → 全天 团建", out == "全天 团建", f"got {out!r}")


async def test_format_event_fallback_no_start():
    print("\n[briefing — format event missing start]")
    tz = ZoneInfo("Asia/Tokyo")
    e = {"title": "随便", "start": "", "all_day": False}
    out = briefing._format_event_for_briefing(e, tz)
    check("空 start → 标题兜底", out == "随便", f"got {out!r}")


# ---------------------------------------------------------------------------
# 2. generate_morning_briefing — 三种状态
# ---------------------------------------------------------------------------

async def test_generate_no_events():
    print("\n[briefing — generate: no events]")
    async def empty_today_events(**_):
        return []
    with patch.object(briefing, "today_events", empty_today_events):
        text = await briefing.generate_morning_briefing()
    check("no events → 没有日程文案", "没有日程" in text, f"got {text!r}")


async def test_generate_with_events():
    print("\n[briefing — generate: with events]")
    async def fake_today_events(**_):
        return [
            {"title": "晨会", "start": "2026-05-07T09:00:00+09:00", "all_day": False},
            {"title": "团建", "start": "2026-05-07", "all_day": True},
        ]
    with patch.object(briefing, "today_events", fake_today_events):
        text = await briefing.generate_morning_briefing()
    check("starts with 早上好", text.startswith("早上好"), f"got {text!r}")
    check("contains 晨会", "晨会" in text)
    check("contains 团建", "团建" in text)
    check("uses ；separator", "；" in text)


async def test_generate_calendar_failure_friendly_fallback():
    print("\n[briefing — generate: calendar failure → friendly fallback]")
    async def boom(**_):
        raise RuntimeError("network down")
    with patch.object(briefing, "today_events", boom):
        text = await briefing.generate_morning_briefing()
    check(
        "fallback contains 早上好",
        text.startswith("早上好"),
        f"got {text!r}",
    )
    check(
        "fallback mentions 日历...连不上",
        "日历" in text and ("连不上" in text or "暂时" in text),
        f"got {text!r}",
    )


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

async def main():
    await test_format_event_timed()
    await test_format_event_all_day()
    await test_format_event_fallback_no_start()
    await test_generate_no_events()
    await test_generate_with_events()
    await test_generate_calendar_failure_friendly_fallback()

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
