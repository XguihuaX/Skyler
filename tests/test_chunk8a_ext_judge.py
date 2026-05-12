"""chunk 8a-ext — ActivityJudge worker + judge_poll_handler 全场景回归。

Part A: ActivityJudge unit(parse / fence / throttle / config / maybe_judge)
Part B: judge_poll_handler 4 道闸 + fire 路径
Part C: ActivityWatcher stay_info + poll_listener 注册
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.integrations import activity_watcher as aw
from backend.integrations.activity_watcher import ActivityState
from backend.proactive import activity_judge as judge
from backend.proactive import activity_smart as smart


@pytest.fixture(autouse=True)
def _reset_state():
    judge.reset_state_for_test()
    smart.reset_state_for_test()
    aw.reset_for_test()
    yield
    judge.reset_state_for_test()
    smart.reset_state_for_test()
    aw.reset_for_test()


# ===========================================================================
# Part A: ActivityJudge unit
# ===========================================================================


# --- parse / fence 容错 -----------------------------------------------------


def test_parse_judge_output_plain_json() -> None:
    raw = '{"speak": true, "reason": "学习中", "topic_hint": "聊聊在学啥"}'
    d = judge._parse_judge_output(raw)
    assert d is not None
    assert d.speak is True
    assert d.reason == "学习中"
    assert d.topic_hint == "聊聊在学啥"


def test_parse_judge_output_with_markdown_fence() -> None:
    raw = '```json\n{"speak": false, "reason": "沉浸观影", "topic_hint": ""}\n```'
    d = judge._parse_judge_output(raw)
    assert d is not None
    assert d.speak is False
    assert d.topic_hint is None  # 空 string → None


def test_parse_judge_output_with_plain_fence() -> None:
    raw = '```\n{"speak": true, "reason": "找工作", "topic_hint": "问要不要帮忙"}\n```'
    d = judge._parse_judge_output(raw)
    assert d is not None
    assert d.speak is True


def test_parse_judge_output_speak_as_string() -> None:
    """LLM 偶尔输出 ``"speak": "true"`` 字符串而非 bool。"""
    raw = '{"speak": "true", "reason": "ok", "topic_hint": "x"}'
    d = judge._parse_judge_output(raw)
    assert d is not None
    assert d.speak is True


def test_parse_judge_output_speak_as_int() -> None:
    raw = '{"speak": 0, "reason": "no"}'
    d = judge._parse_judge_output(raw)
    assert d is not None
    assert d.speak is False


def test_parse_judge_output_invalid_json() -> None:
    assert judge._parse_judge_output("not json at all") is None
    assert judge._parse_judge_output("") is None
    assert judge._parse_judge_output(None) is None


def test_parse_judge_output_missing_speak() -> None:
    raw = '{"reason": "no speak field"}'
    assert judge._parse_judge_output(raw) is None


def test_parse_judge_output_top_level_not_dict() -> None:
    raw = '[{"speak": true}]'
    assert judge._parse_judge_output(raw) is None


# --- prompt build ----------------------------------------------------------


def test_build_judge_prompt_truncates_long_snippet() -> None:
    long_snippet = "X" * 5000
    p = judge._build_judge_prompt(
        app="Chrome", url="https://x.com", title="T",
        content_snippet=long_snippet,
        minutes=7.5, since_last_speak_minutes=12.0,
        today_count=2, daily_cap=5, max_chars=200,
    )
    # snippet 出现的位置应被截断到 ~200 字符 + ellipsis
    assert "XXX" in p
    # 全长 not present
    assert long_snippet not in p


def test_build_judge_prompt_handles_missing_fields() -> None:
    p = judge._build_judge_prompt(
        app=None, url=None, title="",
        content_snippet="",
        minutes=5.0, since_last_speak_minutes=None,
        today_count=0, daily_cap=5, max_chars=2000,
    )
    assert "(未知)" in p           # app=None
    assert "未知 / 从未聊过" in p   # since_last_speak=None


def test_build_judge_prompt_since_last_speak_hours() -> None:
    p = judge._build_judge_prompt(
        app="X", url=None, title="", content_snippet="",
        minutes=5.0, since_last_speak_minutes=120.0,
        today_count=0, daily_cap=5, max_chars=2000,
    )
    assert "2.0 小时" in p


# --- maybe_judge 主入口 ----------------------------------------------------


async def test_maybe_judge_disabled_returns_none() -> None:
    with patch.object(judge, "get_judge_enabled", return_value=False):
        d = await judge.maybe_judge(
            stay_info={"key": "url:x", "duration_seconds": 600,
                       "app": "C", "url": "u", "title": "t"},
            today_count=0, daily_cap=5,
        )
    assert d is None


async def test_maybe_judge_below_min_stay() -> None:
    # 默 min_stay = 5 min = 300s; 给 100s
    d = await judge.maybe_judge(
        stay_info={"key": "url:x", "duration_seconds": 100,
                   "app": "C", "url": "u", "title": "t"},
        today_count=0, daily_cap=5,
    )
    assert d is None


async def test_maybe_judge_throttle_same_key() -> None:
    """同 stay_key 10 min 内不重 judge。"""
    judge._record_judged("url:x")  # 模拟刚 judge 过
    d = await judge.maybe_judge(
        stay_info={"key": "url:x", "duration_seconds": 600,
                   "app": "C", "url": "u", "title": "t"},
        today_count=0, daily_cap=5,
    )
    assert d is None


async def test_maybe_judge_calls_llm_when_eligible() -> None:
    mocked = AsyncMock(return_value='{"speak": true, "reason": "学习", "topic_hint": "问问"}')
    with patch.object(judge, "_call_judge_llm", mocked):
        d = await judge.maybe_judge(
            stay_info={"key": "url:abc", "duration_seconds": 600,
                       "app": "Chrome", "url": "https://docs.x.com",
                       "title": "docs"},
            content_snippet="some article content",
            today_count=1, daily_cap=5,
        )
    assert d is not None
    assert d.speak is True
    assert d.topic_hint == "问问"
    mocked.assert_awaited_once()


async def test_maybe_judge_llm_exception_returns_none() -> None:
    """LLM 抛异常 / 返 None → maybe_judge 返 None,但记账了节流(防 retry storm)。"""
    mocked = AsyncMock(return_value=None)
    with patch.object(judge, "_call_judge_llm", mocked):
        d = await judge.maybe_judge(
            stay_info={"key": "url:err", "duration_seconds": 600,
                       "app": "C", "url": "u", "title": "t"},
            today_count=0, daily_cap=5,
        )
    assert d is None
    # 即便 LLM 失败,也记账(防 retry storm)
    assert judge._is_throttled("url:err", 600)


# ===========================================================================
# Part B: judge_poll_handler 4 道闸
# ===========================================================================


def _state_with_stay(app: str = "Chrome", url: str = "https://x.com",
                     title: str = "X") -> ActivityState:
    return ActivityState(
        active_app=app,
        browser={"browser": "chrome", "url": url, "title": title},
        document=None, url_content=None, timestamp=time.time(),
    )


def _seed_stay(watcher: aw.ActivityWatcher, key: str = "url:https://x.com",
               duration_sec: float = 600.0) -> None:
    """直接设 watcher 内部时间游标,让 get_current_stay_info 返预设值。"""
    now = time.time()
    if key.startswith("url:"):
        watcher._url_dwell_start = now - duration_sec
        watcher._app_focus_start = now - duration_sec
    else:
        watcher._app_focus_start = now - duration_sec
        watcher._url_dwell_start = 0.0
    state = ActivityState(
        active_app="Chrome",
        browser={"browser": "chrome",
                 "url": key.replace("url:", ""), "title": "X"} if key.startswith("url:") else None,
        document=None, url_content=None, timestamp=now,
    )
    watcher._last_state = state


async def test_judge_handler_skip_when_disabled() -> None:
    with patch.object(judge, "get_judge_enabled", return_value=False), \
         patch.object(smart, "_active_conversation_recent",
                      AsyncMock(return_value=False)):
        mocked_run = AsyncMock()
        with patch("backend.proactive.engine.run_trigger", mocked_run):
            await smart.judge_poll_handler(_state_with_stay())
    mocked_run.assert_not_called()


async def test_judge_handler_skip_active_conversation() -> None:
    """5 min 内有 user turn → 跳过 (不调 LLM)。"""
    judge_mock = AsyncMock()
    with patch.object(judge, "maybe_judge", judge_mock), \
         patch.object(smart, "_active_conversation_recent",
                      AsyncMock(return_value=True)):
        await smart.judge_poll_handler(_state_with_stay())
    judge_mock.assert_not_called()


async def test_judge_handler_skip_when_fire_throttled() -> None:
    """同 label 30 min 内已 fire → 不调 judge LLM(节省成本)。"""
    smart._last_fire_per_label["activity_judge_chime_in"] = time.time()
    judge_mock = AsyncMock()
    with patch.object(judge, "maybe_judge", judge_mock), \
         patch.object(smart, "_active_conversation_recent",
                      AsyncMock(return_value=False)):
        await smart.judge_poll_handler(_state_with_stay())
    judge_mock.assert_not_called()


async def test_judge_handler_skip_when_daily_cap_reached() -> None:
    smart._today_count = 5
    smart._today_date = datetime.now().date().isoformat()
    judge_mock = AsyncMock()
    with patch.object(judge, "maybe_judge", judge_mock), \
         patch.object(smart, "_active_conversation_recent",
                      AsyncMock(return_value=False)), \
         patch.object(smart, "get_max_daily_triggers", return_value=5):
        await smart.judge_poll_handler(_state_with_stay())
    judge_mock.assert_not_called()


async def test_judge_handler_fires_when_speak_true() -> None:
    """4 道闸通过 + judge=yes → fire ActivityProactiveTrigger。"""
    _seed_stay(aw.activity_watcher)
    decision = judge.JudgeDecision(speak=True, reason="学习中", topic_hint="问在学啥")
    mocked_run = AsyncMock()
    with patch.object(smart, "_active_conversation_recent",
                      AsyncMock(return_value=False)), \
         patch.object(smart, "_minutes_since_last_user_turn",
                      AsyncMock(return_value=10.0)), \
         patch.object(judge, "maybe_judge",
                      AsyncMock(return_value=decision)), \
         patch("backend.proactive.engine.run_trigger", mocked_run):
        await smart.judge_poll_handler(_state_with_stay())
    mocked_run.assert_awaited_once()
    # trigger label 正确
    trigger_arg = mocked_run.call_args.args[0]
    assert trigger_arg.name == "activity_judge_chime_in"
    assert trigger_arg.detail.get("topic_hint") == "问在学啥"
    # _today_count 增加(共享 daily_cap)
    assert smart._today_count == 1
    # _last_fire_per_label 记账
    assert "activity_judge_chime_in" in smart._last_fire_per_label


async def test_judge_handler_no_fire_when_speak_false() -> None:
    """judge=no → 不 fire, _today_count 不增。"""
    _seed_stay(aw.activity_watcher)
    decision = judge.JudgeDecision(speak=False, reason="沉浸观影", topic_hint=None)
    mocked_run = AsyncMock()
    with patch.object(smart, "_active_conversation_recent",
                      AsyncMock(return_value=False)), \
         patch.object(smart, "_minutes_since_last_user_turn",
                      AsyncMock(return_value=10.0)), \
         patch.object(judge, "maybe_judge",
                      AsyncMock(return_value=decision)), \
         patch("backend.proactive.engine.run_trigger", mocked_run):
        await smart.judge_poll_handler(_state_with_stay())
    mocked_run.assert_not_called()
    assert smart._today_count == 0


async def test_judge_handler_shares_daily_cap_with_fast_path() -> None:
    """快路径 fire 4 次 → 慢路径 judge speak=yes 时第 5 次 fire 成功 ↑ count =5;
    第 6 次(超 cap)被 daily_cap 闸挡。"""
    smart._today_count = 4
    smart._today_date = datetime.now().date().isoformat()
    _seed_stay(aw.activity_watcher)
    decision = judge.JudgeDecision(speak=True, reason="学习", topic_hint="x")
    mocked_run = AsyncMock()
    with patch.object(smart, "_active_conversation_recent",
                      AsyncMock(return_value=False)), \
         patch.object(smart, "_minutes_since_last_user_turn",
                      AsyncMock(return_value=10.0)), \
         patch.object(judge, "maybe_judge",
                      AsyncMock(return_value=decision)), \
         patch.object(smart, "get_max_daily_triggers", return_value=5), \
         patch("backend.proactive.engine.run_trigger", mocked_run):
        # 5th allowed (count: 4 → 5)
        await smart.judge_poll_handler(_state_with_stay())
    assert mocked_run.await_count == 1
    assert smart._today_count == 5
    # 6th blocked (5 >= 5)
    # 重置 fire-throttle 让 fire-throttle 不挡(只测 daily_cap)
    smart._last_fire_per_label["activity_judge_chime_in"] = 0.0
    with patch.object(smart, "_active_conversation_recent",
                      AsyncMock(return_value=False)), \
         patch.object(judge, "maybe_judge",
                      AsyncMock(return_value=decision)), \
         patch.object(smart, "get_max_daily_triggers", return_value=5), \
         patch("backend.proactive.engine.run_trigger", mocked_run):
        await smart.judge_poll_handler(_state_with_stay())
    assert mocked_run.await_count == 1  # 不增,被 daily_cap 闸挡


# ===========================================================================
# Part C: ActivityWatcher stay_info + poll_listener
# ===========================================================================


def test_get_current_stay_info_when_no_state() -> None:
    w = aw.ActivityWatcher()
    assert w.get_current_stay_info() is None


def test_get_current_stay_info_url_priority() -> None:
    """URL 在时优先 URL key(更细粒度)。"""
    w = aw.ActivityWatcher()
    _seed_stay(w, key="url:https://example.com", duration_sec=400.0)
    info = w.get_current_stay_info()
    assert info is not None
    assert info["key"] == "url:https://example.com"
    assert info["duration_seconds"] >= 399


def test_get_current_stay_info_app_fallback_when_no_url() -> None:
    """没有 URL 时 fall back app key。"""
    w = aw.ActivityWatcher()
    now = time.time()
    w._app_focus_start = now - 300.0
    w._url_dwell_start = 0.0
    w._last_state = ActivityState(
        active_app="VSCode", browser=None, document=None,
        url_content=None, timestamp=now,
    )
    info = w.get_current_stay_info()
    assert info is not None
    assert info["key"] == "app:VSCode"
    assert info["app"] == "VSCode"
    assert info["url"] is None


def test_register_poll_listener_idempotent() -> None:
    w = aw.ActivityWatcher()

    async def fn1(state):
        pass

    w.register_poll_listener(fn1)
    w.register_poll_listener(fn1)  # 重复
    assert len(w._poll_listeners) == 1


def test_clear_listeners_drops_both_lists() -> None:
    w = aw.ActivityWatcher()

    async def change_fn(c):
        pass

    async def poll_fn(s):
        pass

    w.register_change_listener(change_fn)
    w.register_poll_listener(poll_fn)
    w.clear_listeners()
    assert w._listeners == []
    assert w._poll_listeners == []


async def test_poll_listener_called_per_poll() -> None:
    """run_loop 一拍调 change_listeners + poll_listeners(无 change 时也调
    poll_listeners)。"""
    w = aw.ActivityWatcher()
    poll_calls: list = []

    async def poll_listener(state: ActivityState) -> None:
        poll_calls.append(state.active_app)

    w.register_poll_listener(poll_listener)
    with patch.object(aw, "get_enabled", return_value=True), \
         patch.object(aw, "get_poll_interval_seconds", return_value=5), \
         patch.object(aw, "get_fetch_url_content", return_value=False), \
         patch.object(aw, "get_blocked_apps", return_value=[]), \
         patch.object(aw, "get_blocked_url_patterns", return_value=[]), \
         patch.object(aw._am, "get_active_app", return_value="Code"), \
         patch.object(aw._am, "get_chrome_active_tab", return_value=None), \
         patch.object(aw._am, "get_safari_active_tab", return_value=None), \
         patch.object(aw._am, "get_active_document_path", return_value=None):
        w.start_polling()
        await asyncio.sleep(0.08)  # 让 loop 跑一拍
        await w.stop_polling()
    assert "Code" in poll_calls


# ===========================================================================
# Part D: lifespan registration
# ===========================================================================


def test_main_py_registers_poll_listener_for_judge() -> None:
    """main.py lifespan 必须挂 ``register_poll_listener(judge_poll_handler)``。"""
    main_py = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "backend/main.py",
    )
    with open(main_py, encoding="utf-8") as f:
        src = f.read()
    assert "judge_poll_handler" in src
    assert "register_poll_listener(judge_poll_handler)" in src
