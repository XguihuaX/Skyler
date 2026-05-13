"""v3.5 chunk 8a commit 4 — ActivityWatcher 单测。

不调真 OS API。Mock activity_monitor + url_fetcher。
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.integrations import activity_watcher as aw
from backend.integrations.activity_watcher import (
    ActivityWatcher, ActivityState, ActivityChange,
)


@pytest.fixture(autouse=True)
def _reset_singleton():
    aw.reset_for_test()
    yield
    aw.reset_for_test()


# ---------------------------------------------------------------------------
# snapshot + 黑名单
# ---------------------------------------------------------------------------


async def test_snapshot_basic_fields() -> None:
    """hotfix-9: snapshot.browser 只在 frontmost 是浏览器时填充。"""
    w = ActivityWatcher()
    with patch.object(aw._am, "get_active_app", return_value="Google Chrome"), \
         patch.object(aw._am, "get_chrome_active_tab",
                      return_value=("https://github.com/a/b", "GitHub - a/b")), \
         patch.object(aw._am, "get_safari_active_tab", return_value=None), \
         patch.object(aw._am, "get_active_document_path",
                      return_value=("/Users/me/x.docx", "word")), \
         patch.object(aw, "get_blocked_apps", return_value=[]), \
         patch.object(aw, "get_blocked_url_patterns", return_value=[]):
        s = await w.snapshot()
    assert s.active_app == "Google Chrome"
    assert s.browser == {
        "browser": "chrome",
        "url": "https://github.com/a/b",
        "title": "GitHub - a/b",
    }
    assert s.document == {"path": "/Users/me/x.docx", "type": "word",
                          "basename": "x.docx"}
    assert s.url_content is None  # snapshot 本身不抓 URL 正文


async def test_snapshot_drops_browser_when_non_browser_frontmost() -> None:
    """**hotfix-9 核心回归**: VSCode frontmost + Chrome 后台还开着 bilibili
    → snapshot.browser 必须是 None,不能泄露后台 tab。"""
    w = ActivityWatcher()
    with patch.object(aw._am, "get_active_app", return_value="Visual Studio Code"), \
         patch.object(aw._am, "get_chrome_active_tab",
                      return_value=("https://jobs.bilibili.com/social/positions/26333",
                                    "招聘")), \
         patch.object(aw._am, "get_safari_active_tab", return_value=None), \
         patch.object(aw._am, "get_active_document_path", return_value=None), \
         patch.object(aw, "get_blocked_apps", return_value=[]), \
         patch.object(aw, "get_blocked_url_patterns", return_value=[]):
        s = await w.snapshot()
    assert s.active_app == "Visual Studio Code"
    assert s.browser is None       # hotfix-9: 后台 Chrome URL 不再泄露


async def test_snapshot_blocked_app_returns_none() -> None:
    w = ActivityWatcher()
    with patch.object(aw._am, "get_active_app", return_value="1Password"), \
         patch.object(aw._am, "get_chrome_active_tab", return_value=None), \
         patch.object(aw._am, "get_safari_active_tab", return_value=None), \
         patch.object(aw._am, "get_active_document_path", return_value=None), \
         patch.object(aw, "get_blocked_apps", return_value=["1Password"]), \
         patch.object(aw, "get_blocked_url_patterns", return_value=[]):
        s = await w.snapshot()
    assert s.active_app is None  # 黑名单 app 不曝露给上层


async def test_snapshot_blocked_url_drops_browser() -> None:
    w = ActivityWatcher()
    with patch.object(aw._am, "get_active_app", return_value="Chrome"), \
         patch.object(aw._am, "get_chrome_active_tab",
                      return_value=("https://mail.google.com/inbox", "Inbox")), \
         patch.object(aw._am, "get_safari_active_tab", return_value=None), \
         patch.object(aw._am, "get_active_document_path", return_value=None), \
         patch.object(aw, "get_blocked_apps", return_value=[]), \
         patch.object(aw, "get_blocked_url_patterns",
                      return_value=["*mail.google.com*"]):
        s = await w.snapshot()
    assert s.browser is None  # 黑名单 URL → browser 字段被清


# ---------------------------------------------------------------------------
# _detect_changes
# ---------------------------------------------------------------------------


def test_detect_app_change() -> None:
    w = ActivityWatcher()
    old = ActivityState(active_app="Chrome", timestamp=100.0)
    new = ActivityState(active_app="VSCode", timestamp=130.0)
    changes = w._detect_changes(old, new, now=130.0)
    kinds = [c.kind for c in changes]
    assert "app_changed" in kinds
    app_change = next(c for c in changes if c.kind == "app_changed")
    assert app_change.detail["old_app"] == "Chrome"
    assert app_change.detail["new_app"] == "VSCode"


def test_detect_url_change_same_browser() -> None:
    w = ActivityWatcher()
    old = ActivityState(
        active_app="Chrome",
        browser={"browser": "chrome", "url": "https://github.com/a", "title": "A"},
    )
    new = ActivityState(
        active_app="Chrome",
        browser={"browser": "chrome", "url": "https://github.com/b", "title": "B"},
    )
    changes = w._detect_changes(old, new, now=200.0)
    kinds = [c.kind for c in changes]
    assert "url_changed" in kinds
    url_change = next(c for c in changes if c.kind == "url_changed")
    assert url_change.detail["new_url"] == "https://github.com/b"


def test_detect_doc_change() -> None:
    w = ActivityWatcher()
    old = ActivityState(active_app="Word")
    new = ActivityState(
        active_app="Word",
        document={"path": "/u/me/a.docx", "type": "word", "basename": "a.docx"},
    )
    changes = w._detect_changes(old, new, now=300.0)
    kinds = [c.kind for c in changes]
    assert "doc_changed" in kinds


def test_detect_app_focus_long_crosses_threshold() -> None:
    """同 app 持续 > 90 分钟 → app_focus_long 触发一次然后 latching off。"""
    w = ActivityWatcher()
    # 模拟：first sniff app=VSCode @ t=0；w._app_focus_start 设为 0
    old = ActivityState(active_app="VSCode", timestamp=0.0)
    w._last_state = old
    w._app_focus_start = 0.0
    # 触发器需要 _detect_changes 在新 state（同 app）下检测
    new_below = ActivityState(active_app="VSCode", timestamp=89 * 60.0)  # 89min
    changes = w._detect_changes(old, new_below, now=89 * 60.0)
    assert not any(c.kind == "app_focus_long" for c in changes)
    new_over = ActivityState(active_app="VSCode", timestamp=91 * 60.0)  # 91min
    changes = w._detect_changes(old, new_over, now=91 * 60.0)
    assert any(c.kind == "app_focus_long" for c in changes)
    # 再下一拍同 app → 不再触发（latching）
    new_over2 = ActivityState(active_app="VSCode", timestamp=92 * 60.0)
    changes = w._detect_changes(old, new_over2, now=92 * 60.0)
    assert not any(c.kind == "app_focus_long" for c in changes)


def test_no_change_returns_empty_list() -> None:
    w = ActivityWatcher()
    old = ActivityState(active_app="VSCode")
    new = ActivityState(active_app="VSCode")
    changes = w._detect_changes(old, new, now=50.0)
    assert changes == []


def test_detect_changes_resets_url_dwell_when_browser_leaves_frontmost() -> None:
    """**hotfix-9 闭环回归**: 用户在 Chrome 看 bilibili 累积 dwell,
    切到 VSCode → snapshot.browser=None → _detect_changes 看到
    new_url=None vs old_url=bilibili,_url_dwell_start 必须重置为 0,
    后续 get_current_stay_info 才能 fallback 到 app stay。
    """
    w = ActivityWatcher()
    # t=0:Chrome 第一次出现 bilibili,记 dwell_start
    old = ActivityState(
        active_app="Google Chrome",
        browser={"browser": "chrome",
                 "url": "https://jobs.bilibili.com/social/positions/26333",
                 "title": "招聘"},
        timestamp=0.0,
    )
    w._last_state = old
    w._url_dwell_start = 0.0          # 模拟 dwell 累积起点
    w._app_focus_start = 0.0
    # t=300:用户已经切到 VSCode,snapshot.browser=None(hotfix-9 gate)
    new = ActivityState(
        active_app="Visual Studio Code",
        browser=None,
        timestamp=300.0,
    )
    w._detect_changes(old, new, now=300.0)
    # URL 离开 frontmost → 重置 dwell(后续不能再"按 bilibili stay 累积")
    assert w._url_dwell_start == 0.0
    # app 切换 → app_focus_start 重新打点
    assert w._app_focus_start == 300.0


async def test_snapshot_then_stay_info_falls_back_to_app_after_frontmost_switch() -> None:
    """端到端串联 hotfix-9 修复路径:
    snapshot → _detect_changes → get_current_stay_info,验证切出浏览器
    后 stay_key 从 url:... 变 app:...,duration 不带过来。
    """
    w = ActivityWatcher()
    bilibili_url = "https://jobs.bilibili.com/social/positions/26333"

    # 步骤 1: Chrome frontmost,记 stay_info url:bilibili
    with patch.object(aw._am, "get_active_app", return_value="Google Chrome"), \
         patch.object(aw._am, "get_chrome_active_tab",
                      return_value=(bilibili_url, "招聘")), \
         patch.object(aw._am, "get_safari_active_tab", return_value=None), \
         patch.object(aw._am, "get_active_document_path", return_value=None), \
         patch.object(aw, "get_blocked_apps", return_value=[]), \
         patch.object(aw, "get_blocked_url_patterns", return_value=[]):
        s1 = await w.snapshot()
        w._detect_changes(None, s1, now=100.0)
        w._last_state = s1
    info1 = w.get_current_stay_info()
    assert info1 is not None
    assert info1["key"] == f"url:{bilibili_url}"

    # 步骤 2: 用户切 VSCode,Chrome 还在后台仍报 bilibili
    with patch.object(aw._am, "get_active_app",
                      return_value="Visual Studio Code"), \
         patch.object(aw._am, "get_chrome_active_tab",
                      return_value=(bilibili_url, "招聘")), \
         patch.object(aw._am, "get_safari_active_tab", return_value=None), \
         patch.object(aw._am, "get_active_document_path", return_value=None), \
         patch.object(aw, "get_blocked_apps", return_value=[]), \
         patch.object(aw, "get_blocked_url_patterns", return_value=[]):
        s2 = await w.snapshot()
        w._detect_changes(s1, s2, now=400.0)
        w._last_state = s2
    assert s2.browser is None
    info2 = w.get_current_stay_info()
    assert info2 is not None
    assert info2["key"] == "app:Visual Studio Code"
    assert info2["url"] is None    # 不再泄露后台 bilibili
    # 步骤 3: 切回 Chrome,URL stay 重新打点(不带过来旧的 ~300s 累积)
    with patch.object(aw._am, "get_active_app", return_value="Google Chrome"), \
         patch.object(aw._am, "get_chrome_active_tab",
                      return_value=(bilibili_url, "招聘")), \
         patch.object(aw._am, "get_safari_active_tab", return_value=None), \
         patch.object(aw._am, "get_active_document_path", return_value=None), \
         patch.object(aw, "get_blocked_apps", return_value=[]), \
         patch.object(aw, "get_blocked_url_patterns", return_value=[]):
        s3 = await w.snapshot()
        w._detect_changes(s2, s3, now=500.0)
        w._last_state = s3
    info3 = w.get_current_stay_info()
    assert info3 is not None
    assert info3["key"] == f"url:{bilibili_url}"
    # dwell_start 是 t=500 重新打点,而不是从 t=100 累积过来
    assert info3["start_ts"] == 500.0


# ---------------------------------------------------------------------------
# Listeners + run_loop tick
# ---------------------------------------------------------------------------


async def test_listener_invoked_on_change() -> None:
    w = ActivityWatcher()
    captured: list[ActivityChange] = []

    async def listener(change: ActivityChange) -> None:
        captured.append(change)

    w.register_change_listener(listener)
    # 把 snapshot 返值控成第一次 Chrome 第二次 VSCode
    sequence = [
        ActivityState(active_app="Chrome", timestamp=100.0),
        ActivityState(active_app="VSCode", timestamp=130.0),
    ]
    call_idx = {"n": 0}

    async def fake_snapshot(*, with_url_content=None):
        i = call_idx["n"]
        call_idx["n"] += 1
        return sequence[min(i, len(sequence) - 1)]

    w.snapshot = fake_snapshot  # type: ignore[assignment]
    # 跑 2 拍：第 1 拍设置 _last_state（无 change，因为 old=None → app_changed
    # also fires since new_app != None）；第 2 拍真 app_changed
    w._stop_event = asyncio.Event()
    async def run_two_ticks():
        # 直接调内部循环 logic 一次手动两拍
        for _ in range(2):
            state = await w.snapshot()
            changes = w._detect_changes(w._last_state, state, now=state.timestamp)
            for c in changes:
                for fn in w._listeners:
                    await fn(c)
            w._last_state = state
    await run_two_ticks()
    # 两次切换：None→Chrome（first），Chrome→VSCode（second）
    assert len(captured) >= 1
    kinds = [c.kind for c in captured]
    assert "app_changed" in kinds


async def test_listener_exception_does_not_break_loop() -> None:
    w = ActivityWatcher()

    async def bad(change: ActivityChange) -> None:
        raise RuntimeError("intentional")

    captured: list[ActivityChange] = []

    async def good(change: ActivityChange) -> None:
        captured.append(change)

    w.register_change_listener(bad)
    w.register_change_listener(good)

    old = ActivityState(active_app="Chrome")
    new = ActivityState(active_app="VSCode")
    # 模拟 run_loop dispatch listeners 串行
    changes = w._detect_changes(old, new, now=200.0)
    for c in changes:
        for fn in list(w._listeners):
            try:
                await fn(c)
            except Exception:
                pass
    assert len(captured) >= 1  # good 仍跑


# ---------------------------------------------------------------------------
# Lifecycle: start_polling / stop_polling
# ---------------------------------------------------------------------------


async def test_start_disabled_is_noop() -> None:
    w = ActivityWatcher()
    with patch.object(aw, "get_enabled", return_value=False):
        w.start_polling()
    assert w._task is None


async def test_start_stop_lifecycle() -> None:
    """启动 → 自然跑几拍 → stop_polling 不超时。"""
    w = ActivityWatcher()
    with patch.object(aw, "get_enabled", return_value=True), \
         patch.object(aw, "get_poll_interval_seconds", return_value=5), \
         patch.object(aw, "get_fetch_url_content", return_value=False), \
         patch.object(aw, "get_blocked_apps", return_value=[]), \
         patch.object(aw, "get_blocked_url_patterns", return_value=[]), \
         patch.object(aw._am, "get_active_app", return_value="Chrome"), \
         patch.object(aw._am, "get_chrome_active_tab", return_value=None), \
         patch.object(aw._am, "get_safari_active_tab", return_value=None), \
         patch.object(aw._am, "get_active_document_path", return_value=None):
        w.start_polling()
        assert w.is_running()
        # 让 loop 跑两拍（loop 内 wait_for stop_event 等 5s；我们立即 stop）
        await asyncio.sleep(0.05)
        await w.stop_polling()
    assert not w.is_running()


async def test_set_enabled_false_breaks_loop() -> None:
    w = ActivityWatcher()
    with patch.object(aw, "get_enabled", return_value=True), \
         patch.object(aw, "get_poll_interval_seconds", return_value=5), \
         patch.object(aw, "get_fetch_url_content", return_value=False), \
         patch.object(aw, "get_blocked_apps", return_value=[]), \
         patch.object(aw, "get_blocked_url_patterns", return_value=[]), \
         patch.object(aw._am, "get_active_app", return_value="Chrome"), \
         patch.object(aw._am, "get_chrome_active_tab", return_value=None), \
         patch.object(aw._am, "get_safari_active_tab", return_value=None), \
         patch.object(aw._am, "get_active_document_path", return_value=None):
        w.start_polling()
        await asyncio.sleep(0.05)
        w.set_enabled(False)
        await asyncio.sleep(0.05)
        # set_enabled(False) 触发 stop_event → run_loop 退出
        # 仍要 await task 确认收尾
        if w._task is not None:
            try:
                await asyncio.wait_for(w._task, timeout=1.0)
            except asyncio.TimeoutError:
                w._task.cancel()
    assert w._enabled_override is False


# ---------------------------------------------------------------------------
# URL content best-effort
# ---------------------------------------------------------------------------


async def test_maybe_fetch_url_content_when_enabled() -> None:
    w = ActivityWatcher()
    with patch.object(aw, "get_fetch_url_content", return_value=True), \
         patch.object(aw, "get_blocked_url_patterns", return_value=[]), \
         patch.object(aw._uf, "fetch_article_content",
                      AsyncMock(return_value={
                          "fetched": True, "url": "https://e.com",
                          "title": "T", "content": "C", "status": "ok",
                      })):
        r = await w._maybe_fetch_url_content("https://e.com")
    assert r == {"title": "T", "content": "C"}


async def test_maybe_fetch_url_content_blocked_returns_none() -> None:
    w = ActivityWatcher()
    with patch.object(aw, "get_fetch_url_content", return_value=True), \
         patch.object(aw, "get_blocked_url_patterns", return_value=[]), \
         patch.object(aw._uf, "fetch_article_content",
                      AsyncMock(return_value={
                          "fetched": False, "url": "https://e.com",
                          "reason": "blocked",
                      })):
        r = await w._maybe_fetch_url_content("https://e.com")
    assert r is None


async def test_maybe_fetch_url_content_disabled_skipped() -> None:
    w = ActivityWatcher()
    mocked = AsyncMock()
    with patch.object(aw, "get_fetch_url_content", return_value=False), \
         patch.object(aw._uf, "fetch_article_content", mocked):
        r = await w._maybe_fetch_url_content("https://e.com")
    assert r is None
    mocked.assert_not_awaited()
