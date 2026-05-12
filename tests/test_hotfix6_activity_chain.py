"""hotfix-6 Part 2 — activity 触发链回归 + INFO log 锁定。

锁住三件事：
1. ``_classify`` 识别 macOS 实际 localizedName（``Code``、``IntelliJ IDEA CE``
   等），不只品牌名
2. 4 道闸每道命中时都 emit 唯一可 grep 的 INFO log（``classify`` / ``skipped:
   reason=active_conversation`` / ``throttled`` / ``skipped: reason=daily_cap``
   / ``proactive trigger fired`` / ``proactive trigger sent``）
3. ActivityWatcher.run_loop 内 ``app detected`` / ``app changed`` 等 INFO log
   在检测到状态变化的拍上出现
"""
from __future__ import annotations

import logging
import os
import sys
import time
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.integrations import activity_watcher as aw
from backend.integrations.activity_watcher import ActivityChange, ActivityState
from backend.proactive import activity_smart as smart


@pytest.fixture(autouse=True)
def _reset():
    smart.reset_state_for_test()
    yield
    smart.reset_state_for_test()


# ---------------------------------------------------------------------------
# Part A — IDE recognition: macOS NSWorkspace 实际返值匹配
# ---------------------------------------------------------------------------


def _app_changed(new_app: str, *, hour: int = 14) -> ActivityChange:
    ts = datetime.now().replace(
        hour=hour, minute=0, second=0, microsecond=0,
    ).timestamp()
    return ActivityChange(
        kind="app_changed",
        old=None,
        new=ActivityState(active_app=new_app, timestamp=ts),
        detail={"old_app": "Finder", "new_app": new_app},
    )


def test_classify_code_recognized_as_ide() -> None:
    """⭐ hotfix-6 主修复：NSWorkspace 返 ``Code`` 也算 IDE。"""
    assert smart._classify(_app_changed("Code")) == "activity_ide_open"


def test_classify_cursor_recognized() -> None:
    assert smart._classify(_app_changed("Cursor")) == "activity_ide_open"


def test_classify_intellij_ce_recognized() -> None:
    assert smart._classify(_app_changed("IntelliJ IDEA CE")) == "activity_ide_open"


def test_classify_pycharm_professional_recognized() -> None:
    assert smart._classify(_app_changed("PyCharm Professional")) == "activity_ide_open"


def test_classify_phpstorm_recognized() -> None:
    assert smart._classify(_app_changed("PhpStorm")) == "activity_ide_open"


def test_classify_zed_recognized() -> None:
    assert smart._classify(_app_changed("Zed")) == "activity_ide_open"


def test_classify_unknown_app_returns_none() -> None:
    """Finder / Chrome 等普通 app 不触发。"""
    assert smart._classify(_app_changed("Finder")) is None
    assert smart._classify(_app_changed("Google Chrome")) is None
    assert smart._classify(_app_changed("Mail")) is None


def test_classify_late_night_code() -> None:
    """凌晨 3 点切 ``Code`` → 用 late_night prompt（更温柔）。"""
    label = smart._classify(_app_changed("Code", hour=3))
    assert label == "activity_late_night_ide"


# ---------------------------------------------------------------------------
# Part B — INFO log 锁回归 (smart_handler 4 道闸)
# ---------------------------------------------------------------------------


async def test_log_classify_not_matched(caplog: pytest.LogCaptureFixture) -> None:
    """不命中规则的 change 仍 emit ``classify: matched=False`` log。"""
    caplog.set_level(logging.INFO, logger="backend.proactive.activity_smart")
    with patch.object(smart, "_active_conversation_recent",
                      AsyncMock(return_value=False)):
        await smart.activity_smart_handler(_app_changed("Finder"))
    msgs = [r.message for r in caplog.records]
    assert any("classify: matched=False" in m and "Finder" in m for m in msgs), \
        f"缺 classify=False log；实际: {msgs}"


async def test_log_classify_matched(caplog: pytest.LogCaptureFixture) -> None:
    """命中规则 emit ``classify: matched=True`` log。"""
    caplog.set_level(logging.INFO, logger="backend.proactive.activity_smart")
    with patch.object(smart, "_active_conversation_recent",
                      AsyncMock(return_value=False)), \
         patch("backend.proactive.engine.run_trigger", AsyncMock()):
        await smart.activity_smart_handler(_app_changed("Code"))
    msgs = [r.message for r in caplog.records]
    assert any("classify: matched=True" in m and "activity_ide_open" in m for m in msgs), \
        f"缺 classify=True log；实际: {msgs}"


async def test_log_skip_active_conversation(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="backend.proactive.activity_smart")
    with patch.object(smart, "_active_conversation_recent",
                      AsyncMock(return_value=True)), \
         patch("backend.proactive.engine.run_trigger", AsyncMock()):
        await smart.activity_smart_handler(_app_changed("Code"))
    msgs = [r.message for r in caplog.records]
    assert any("skipped: reason=active_conversation" in m for m in msgs), \
        f"缺 active_conversation skip log；实际: {msgs}"


async def test_log_throttled(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="backend.proactive.activity_smart")
    with patch.object(smart, "_active_conversation_recent",
                      AsyncMock(return_value=False)), \
         patch("backend.proactive.engine.run_trigger", AsyncMock()), \
         patch.object(smart, "get_throttle_minutes", return_value=30), \
         patch.object(smart, "get_max_daily_triggers", return_value=10):
        await smart.activity_smart_handler(_app_changed("Code"))
        await smart.activity_smart_handler(_app_changed("Cursor"))  # same label
    msgs = [r.message for r in caplog.records]
    assert any("throttled: label=activity_ide_open" in m for m in msgs), \
        f"缺 throttled log；实际: {msgs}"
    # 必须含 ``last_fired=`` + ``remaining=`` 让用户能看到具体节流时点
    throttled = [m for m in msgs if "throttled:" in m][0]
    assert "last_fired=" in throttled
    assert "remaining=" in throttled


async def test_log_daily_cap(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="backend.proactive.activity_smart")
    with patch.object(smart, "_active_conversation_recent",
                      AsyncMock(return_value=False)), \
         patch("backend.proactive.engine.run_trigger", AsyncMock()), \
         patch.object(smart, "get_throttle_minutes", return_value=30), \
         patch.object(smart, "get_max_daily_triggers", return_value=1):
        await smart.activity_smart_handler(_app_changed("Code"))      # ide_open
        await smart.activity_smart_handler(_app_changed("Spotify"))   # music
    msgs = [r.message for r in caplog.records]
    assert any("skipped: reason=daily_cap" in m for m in msgs), \
        f"缺 daily_cap skip log；实际: {msgs}"


async def test_log_fired_and_sent(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="backend.proactive.activity_smart")
    with patch.object(smart, "_active_conversation_recent",
                      AsyncMock(return_value=False)), \
         patch("backend.proactive.engine.run_trigger", AsyncMock()), \
         patch.object(smart, "get_throttle_minutes", return_value=30), \
         patch.object(smart, "get_max_daily_triggers", return_value=10):
        await smart.activity_smart_handler(_app_changed("Code"))
    msgs = [r.message for r in caplog.records]
    assert any("proactive trigger fired: label=activity_ide_open" in m for m in msgs), \
        f"缺 fired log；实际: {msgs}"
    assert any("proactive trigger sent: label=activity_ide_open" in m for m in msgs), \
        f"缺 sent log；实际: {msgs}"


# ---------------------------------------------------------------------------
# Part C — ActivityWatcher run_loop INFO log
# ---------------------------------------------------------------------------


async def test_log_app_detected_and_changed(caplog: pytest.LogCaptureFixture) -> None:
    """走一次 _detect_changes，验 watcher log 里有 ``app detected`` 和 ``app changed``。

    这里不跑真 run_loop（涉及 sleep），手动模拟 run_loop 关键 path。
    """
    aw.reset_for_test()
    caplog.set_level(logging.INFO, logger="backend.integrations.activity_watcher")
    w = aw.ActivityWatcher()

    # 把日志 emit 路径绕开 run_loop 实际 sleep——直接在 caplog 范围内手工调
    # _detect_changes + 让 run_loop log code path 实际跑。最干脆的做法是
    # 启 polling 一拍，立即 stop。
    with patch.object(aw._am, "get_active_app", return_value="Code"), \
         patch.object(aw._am, "get_chrome_active_tab", return_value=None), \
         patch.object(aw._am, "get_safari_active_tab", return_value=None), \
         patch.object(aw._am, "get_active_document_path", return_value=None), \
         patch.object(aw, "get_enabled", return_value=True), \
         patch.object(aw, "get_poll_interval_seconds", return_value=5), \
         patch.object(aw, "get_fetch_url_content", return_value=False), \
         patch.object(aw, "get_blocked_apps", return_value=[]), \
         patch.object(aw, "get_blocked_url_patterns", return_value=[]):
        w.start_polling()
        import asyncio
        await asyncio.sleep(0.08)   # 让 loop 至少跑一拍
        await w.stop_polling()
    msgs = [r.message for r in caplog.records]
    assert any("app detected: tick=" in m and "Code" in m for m in msgs), \
        f"缺 ``app detected`` log；实际: {msgs}"
    # 第一拍 last_state=None → 必然触发 app_changed: None → Code
    assert any("app changed: from=None to='Code'" in m for m in msgs), \
        f"缺 ``app changed`` log；实际: {msgs}"


# ---------------------------------------------------------------------------
# Part D — End-to-end smoke: app=Code → fired log + run_trigger called
# ---------------------------------------------------------------------------


async def test_e2e_code_switch_fires_trigger(caplog: pytest.LogCaptureFixture) -> None:
    """⭐ 主修复回归：切到 ``Code`` 走完 4 道闸 + 调 run_trigger。"""
    caplog.set_level(logging.INFO, logger="backend.proactive.activity_smart")
    mocked_run = AsyncMock()
    with patch.object(smart, "_active_conversation_recent",
                      AsyncMock(return_value=False)), \
         patch("backend.proactive.engine.run_trigger", mocked_run), \
         patch.object(smart, "get_throttle_minutes", return_value=30), \
         patch.object(smart, "get_max_daily_triggers", return_value=10):
        await smart.activity_smart_handler(_app_changed("Code"))
    mocked_run.assert_awaited_once()
    # 传给 run_trigger 的 trigger.name 应是 ``activity_ide_open``
    args, kwargs = mocked_run.call_args
    trigger = args[0] if args else kwargs.get("trigger")
    assert trigger.name == "activity_ide_open"
    # log 确认 fired
    msgs = [r.message for r in caplog.records]
    assert any("proactive trigger fired" in m for m in msgs)
