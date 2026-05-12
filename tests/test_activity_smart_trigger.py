"""v3.5 chunk 8a commit 5 — smart trigger 决策 + 节流 + 节流 + cap 单测。

不真起 ChatAgent / WS push。Mock ``run_trigger`` 让我们专注于决策路径。
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.integrations.activity_watcher import ActivityChange, ActivityState
from backend.proactive import activity_smart as smart
from backend.proactive.triggers.activity import ActivityProactiveTrigger


@pytest.fixture(autouse=True)
def _reset():
    smart.reset_state_for_test()
    yield
    smart.reset_state_for_test()


# ---------------------------------------------------------------------------
# _classify
# ---------------------------------------------------------------------------


def test_classify_ide_open() -> None:
    change = ActivityChange(
        kind="app_changed",
        old=None,
        new=ActivityState(active_app="Visual Studio Code", timestamp=time.time()),
        detail={"old_app": "Chrome", "new_app": "Visual Studio Code"},
    )
    # 注：时区敏感——白天时间分类成 ide_open，深夜则 late_night_ide
    label = smart._classify(change)
    assert label in ("activity_ide_open", "activity_late_night_ide")


def test_classify_late_night_ide() -> None:
    # 构造一个明确 0-5 点的 timestamp（今日凌晨 3 点）
    night = datetime.now().replace(hour=3, minute=0, second=0, microsecond=0)
    change = ActivityChange(
        kind="app_changed",
        old=None,
        new=ActivityState(active_app="Cursor", timestamp=night.timestamp()),
        detail={"old_app": None, "new_app": "Cursor"},
    )
    assert smart._classify(change) == "activity_late_night_ide"


def test_classify_music() -> None:
    change = ActivityChange(
        kind="app_changed",
        old=None,
        new=ActivityState(active_app="Spotify", timestamp=time.time()),
        detail={"old_app": "Chrome", "new_app": "Spotify"},
    )
    assert smart._classify(change) == "activity_music"


def test_classify_url_tech_doc() -> None:
    change = ActivityChange(
        kind="url_changed",
        old=None,
        new=ActivityState(timestamp=time.time()),
        detail={"new_url": "https://docs.python.org/3/library/asyncio.html",
                "title": "asyncio docs"},
    )
    assert smart._classify(change) == "activity_url_tech_doc"


def test_classify_non_tech_url_skipped() -> None:
    change = ActivityChange(
        kind="url_changed",
        old=None,
        new=ActivityState(timestamp=time.time()),
        detail={"new_url": "https://news.example.com/article",
                "title": "general news"},
    )
    assert smart._classify(change) is None


def test_classify_long_focus() -> None:
    change = ActivityChange(
        kind="app_focus_long",
        old=None,
        new=ActivityState(active_app="VSCode", timestamp=time.time()),
        detail={"app": "VSCode", "focus_seconds": 6000},
    )
    assert smart._classify(change) == "activity_long_focus"


def test_classify_unknown_kind() -> None:
    change = ActivityChange(
        kind="doc_changed", old=None,
        new=ActivityState(timestamp=time.time()), detail={},
    )
    # v1 conservative：doc_changed 不出 trigger
    assert smart._classify(change) is None


# ---------------------------------------------------------------------------
# Throttle + cap + active-conversation guard
# ---------------------------------------------------------------------------


def _ide_change() -> ActivityChange:
    return ActivityChange(
        kind="app_changed",
        old=None,
        # 用 12:00 中午 timestamp 强制走 ide_open 而非 late_night_ide
        new=ActivityState(
            active_app="VSCode",
            timestamp=datetime.now().replace(hour=12, minute=0, second=0, microsecond=0).timestamp(),
        ),
        detail={"old_app": "Chrome", "new_app": "VSCode"},
    )


async def test_classify_returns_none_then_no_fire() -> None:
    """非 IDE / 非音乐 / 非技术文档 → 不调 run_trigger。"""
    mocked = AsyncMock()
    change = ActivityChange(
        kind="app_changed",
        old=None,
        new=ActivityState(active_app="Finder", timestamp=time.time()),
        detail={"old_app": "Chrome", "new_app": "Finder"},
    )
    with patch.object(smart, "_active_conversation_recent",
                      AsyncMock(return_value=False)), \
         patch("backend.proactive.engine.run_trigger", mocked):
        await smart.activity_smart_handler(change)
    mocked.assert_not_called()


async def test_active_conversation_skips() -> None:
    mocked = AsyncMock()
    with patch.object(smart, "_active_conversation_recent",
                      AsyncMock(return_value=True)), \
         patch("backend.proactive.engine.run_trigger", mocked):
        await smart.activity_smart_handler(_ide_change())
    mocked.assert_not_called()


async def test_throttle_blocks_repeat() -> None:
    """同 label 立即重发 → 第二次 skip。"""
    mocked = AsyncMock()
    with patch.object(smart, "_active_conversation_recent",
                      AsyncMock(return_value=False)), \
         patch("backend.proactive.engine.run_trigger", mocked), \
         patch.object(smart, "get_throttle_minutes", return_value=30), \
         patch.object(smart, "get_max_daily_triggers", return_value=10):
        await smart.activity_smart_handler(_ide_change())
        await smart.activity_smart_handler(_ide_change())
    assert mocked.await_count == 1


async def test_daily_cap_blocks() -> None:
    """cap=1 → 第二次 skip（不同 label 也算同一 cap）。"""
    mocked = AsyncMock()
    music_change = ActivityChange(
        kind="app_changed",
        old=None,
        new=ActivityState(
            active_app="Spotify",
            timestamp=datetime.now().replace(hour=12, minute=0).timestamp(),
        ),
        detail={"old_app": "Chrome", "new_app": "Spotify"},
    )
    with patch.object(smart, "_active_conversation_recent",
                      AsyncMock(return_value=False)), \
         patch("backend.proactive.engine.run_trigger", mocked), \
         patch.object(smart, "get_throttle_minutes", return_value=30), \
         patch.object(smart, "get_max_daily_triggers", return_value=1):
        await smart.activity_smart_handler(_ide_change())   # 命中 cap=1
        await smart.activity_smart_handler(music_change)     # 应被 cap 挡
    assert mocked.await_count == 1


async def test_run_trigger_exception_does_not_propagate() -> None:
    """run_trigger 抛异常 → handler 吞掉不传上层。"""
    failing = AsyncMock(side_effect=RuntimeError("ws push broken"))
    with patch.object(smart, "_active_conversation_recent",
                      AsyncMock(return_value=False)), \
         patch("backend.proactive.engine.run_trigger", failing), \
         patch.object(smart, "get_throttle_minutes", return_value=30), \
         patch.object(smart, "get_max_daily_triggers", return_value=10):
        # 不应抛
        await smart.activity_smart_handler(_ide_change())


# ---------------------------------------------------------------------------
# Trigger class instantiation smoke
# ---------------------------------------------------------------------------


async def test_activity_trigger_builds_prompt() -> None:
    trig = ActivityProactiveTrigger(
        label="activity_ide_open",
        detail={"new_app": "Cursor"},
    )
    prompt = await trig.build_system_prompt(character=None)
    assert "Cursor" in prompt
    assert "40-80" in prompt   # 风格约束在 prompt 里


async def test_activity_trigger_label_validation() -> None:
    with pytest.raises(ValueError):
        ActivityProactiveTrigger(label="activity_unknown")


async def test_activity_trigger_no_search() -> None:
    trig = ActivityProactiveTrigger(label="activity_music", detail={"new_app": "Spotify"})
    assert trig.enable_search is False
    assert trig.cron_expr is None
    assert trig.interval_seconds is None
    assert trig.event_source is None
