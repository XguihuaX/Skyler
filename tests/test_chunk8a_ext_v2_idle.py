"""chunk 8a-ext V2 — 用户活跃度 idle 闸回归。

Part A: get_idle_seconds 单元(ioreg subprocess + 跨平台 graceful)
Part B: get_idle_threshold_seconds config 读取
Part C: maybe_judge idle 闸全场景(idle < threshold → 继续 / idle > threshold
        → skip / idle=None → V1 兼容 / threshold=0 → 绕过)
Part D: idle 闸顺序(_record_judged 之后,LLM call 之前)
"""
from __future__ import annotations

import asyncio  # noqa: F401 — pytest-asyncio 通过 anyio backend 隐式拉起
import os
import subprocess
import sys
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.integrations import activity_monitor as am
from backend.proactive import activity_judge as judge


@pytest.fixture(autouse=True)
def _reset_judge_state():
    judge.reset_state_for_test()
    yield
    judge.reset_state_for_test()


# ===========================================================================
# Part A: get_idle_seconds
# ===========================================================================


_IOREG_SAMPLE_NORMAL = """\
+-o IOHIDSystem  <class IOHIDSystem, id 0x100000abc, registered, matched, active>
    {
      "HIDIdleTime" = 146795750
      "HIDPointerAcceleration" = 393216
    }
"""

_IOREG_SAMPLE_LONG_IDLE = """\
+-o IOHIDSystem  <class IOHIDSystem>
    {
      "HIDIdleTime" = 600000000000
    }
"""

_IOREG_SAMPLE_NO_FIELD = """\
+-o IOHIDSystem  <class IOHIDSystem>
    {
      "HIDPointerAcceleration" = 393216
    }
"""


def _mock_completed(stdout: str = "", returncode: int = 0,
                    stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=["ioreg", "-c", "IOHIDSystem"],
        returncode=returncode, stdout=stdout, stderr=stderr,
    )


def test_get_idle_seconds_normal_output() -> None:
    """ioreg 标准 output → HIDIdleTime / 1e9 秒。"""
    with patch.object(am, "IS_MACOS", True), \
         patch("backend.integrations.activity_monitor.shutil.which",
               return_value="/usr/sbin/ioreg"), \
         patch("backend.integrations.activity_monitor.subprocess.run",
               return_value=_mock_completed(_IOREG_SAMPLE_NORMAL)):
        idle = am.get_idle_seconds()
    assert idle is not None
    # 146795750 ns / 1e9 ≈ 0.147 s
    assert 0.14 < idle < 0.15


def test_get_idle_seconds_long_idle() -> None:
    """10 min idle = 600 * 1e9 ns。"""
    with patch.object(am, "IS_MACOS", True), \
         patch("backend.integrations.activity_monitor.shutil.which",
               return_value="/usr/sbin/ioreg"), \
         patch("backend.integrations.activity_monitor.subprocess.run",
               return_value=_mock_completed(_IOREG_SAMPLE_LONG_IDLE)):
        idle = am.get_idle_seconds()
    assert idle == pytest.approx(600.0, abs=0.01)


def test_get_idle_seconds_non_macos_returns_none() -> None:
    with patch.object(am, "IS_MACOS", False):
        assert am.get_idle_seconds() is None


def test_get_idle_seconds_ioreg_missing_returns_none() -> None:
    with patch.object(am, "IS_MACOS", True), \
         patch("backend.integrations.activity_monitor.shutil.which",
               return_value=None):
        assert am.get_idle_seconds() is None


def test_get_idle_seconds_subprocess_timeout_returns_none() -> None:
    def _raise_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="ioreg", timeout=2)
    with patch.object(am, "IS_MACOS", True), \
         patch("backend.integrations.activity_monitor.shutil.which",
               return_value="/usr/sbin/ioreg"), \
         patch("backend.integrations.activity_monitor.subprocess.run",
               side_effect=_raise_timeout):
        assert am.get_idle_seconds() is None


def test_get_idle_seconds_subprocess_exception_returns_none() -> None:
    with patch.object(am, "IS_MACOS", True), \
         patch("backend.integrations.activity_monitor.shutil.which",
               return_value="/usr/sbin/ioreg"), \
         patch("backend.integrations.activity_monitor.subprocess.run",
               side_effect=OSError("boom")):
        assert am.get_idle_seconds() is None


def test_get_idle_seconds_nonzero_returncode_returns_none() -> None:
    with patch.object(am, "IS_MACOS", True), \
         patch("backend.integrations.activity_monitor.shutil.which",
               return_value="/usr/sbin/ioreg"), \
         patch("backend.integrations.activity_monitor.subprocess.run",
               return_value=_mock_completed(returncode=1, stderr="denied")):
        assert am.get_idle_seconds() is None


def test_get_idle_seconds_regex_no_match_returns_none() -> None:
    """HIDIdleTime 字段缺失(极端 macOS 版本) → None。"""
    with patch.object(am, "IS_MACOS", True), \
         patch("backend.integrations.activity_monitor.shutil.which",
               return_value="/usr/sbin/ioreg"), \
         patch("backend.integrations.activity_monitor.subprocess.run",
               return_value=_mock_completed(_IOREG_SAMPLE_NO_FIELD)):
        assert am.get_idle_seconds() is None


# ===========================================================================
# Part B: get_idle_threshold_seconds (config 读取)
# ===========================================================================


def test_idle_threshold_default_when_unset() -> None:
    with patch.object(judge, "_cfg", return_value={}):
        assert judge.get_idle_threshold_seconds() == 300


def test_idle_threshold_custom_value() -> None:
    with patch.object(judge, "_cfg", return_value={"idle_threshold_seconds": 120}):
        assert judge.get_idle_threshold_seconds() == 120


def test_idle_threshold_zero_means_disabled() -> None:
    with patch.object(judge, "_cfg", return_value={"idle_threshold_seconds": 0}):
        assert judge.get_idle_threshold_seconds() == 0


def test_idle_threshold_negative_clamped_to_zero() -> None:
    with patch.object(judge, "_cfg", return_value={"idle_threshold_seconds": -5}):
        assert judge.get_idle_threshold_seconds() == 0


def test_idle_threshold_invalid_type_falls_back() -> None:
    with patch.object(judge, "_cfg", return_value={"idle_threshold_seconds": "abc"}):
        assert judge.get_idle_threshold_seconds() == 300
    with patch.object(judge, "_cfg", return_value={"idle_threshold_seconds": None}):
        assert judge.get_idle_threshold_seconds() == 300


# ===========================================================================
# Part C: maybe_judge idle 闸场景
# ===========================================================================


_STAY_OK = {
    "key": "url:https://idle-test.example",
    "duration_seconds": 600,  # 10 min, > min_stay 5 min
    "app": "Chrome", "url": "https://idle-test.example", "title": "T",
}


async def test_maybe_judge_idle_below_threshold_continues_to_llm() -> None:
    """idle=100s, threshold=300s → 不挡,LLM 被调。"""
    llm_mock = AsyncMock(return_value='{"speak": true, "reason": "ok", "topic_hint": "x"}')
    with patch.object(judge, "get_idle_threshold_seconds", return_value=300), \
         patch("backend.integrations.activity_monitor.get_idle_seconds",
               return_value=100.0), \
         patch.object(judge, "_call_judge_llm", llm_mock):
        d = await judge.maybe_judge(stay_info=_STAY_OK, today_count=0, daily_cap=5)
    assert d is not None
    assert d.speak is True
    llm_mock.assert_awaited_once()


async def test_maybe_judge_idle_above_threshold_skips_llm() -> None:
    """idle=600s, threshold=300s → 挡,LLM 不调,返 None。"""
    llm_mock = AsyncMock()
    with patch.object(judge, "get_idle_threshold_seconds", return_value=300), \
         patch("backend.integrations.activity_monitor.get_idle_seconds",
               return_value=600.0), \
         patch.object(judge, "_call_judge_llm", llm_mock):
        d = await judge.maybe_judge(stay_info=_STAY_OK, today_count=0, daily_cap=5)
    assert d is None
    llm_mock.assert_not_called()


async def test_maybe_judge_idle_none_continues_v1_behavior() -> None:
    """get_idle_seconds 返 None (非 macOS / ioreg 失败) → fallback 不挡。"""
    llm_mock = AsyncMock(return_value='{"speak": false, "reason": "no", "topic_hint": ""}')
    with patch.object(judge, "get_idle_threshold_seconds", return_value=300), \
         patch("backend.integrations.activity_monitor.get_idle_seconds",
               return_value=None), \
         patch.object(judge, "_call_judge_llm", llm_mock):
        d = await judge.maybe_judge(stay_info=_STAY_OK, today_count=0, daily_cap=5)
    assert d is not None  # V1 行为: LLM 被调,返 decision
    llm_mock.assert_awaited_once()


async def test_maybe_judge_idle_exception_continues_v1_behavior() -> None:
    """get_idle_seconds 抛异常 → silent None fallback,LLM 仍调。"""
    llm_mock = AsyncMock(return_value='{"speak": true, "reason": "ok"}')
    with patch.object(judge, "get_idle_threshold_seconds", return_value=300), \
         patch("backend.integrations.activity_monitor.get_idle_seconds",
               side_effect=RuntimeError("boom")), \
         patch.object(judge, "_call_judge_llm", llm_mock):
        d = await judge.maybe_judge(stay_info=_STAY_OK, today_count=0, daily_cap=5)
    assert d is not None
    llm_mock.assert_awaited_once()


async def test_maybe_judge_idle_threshold_zero_bypasses_gate() -> None:
    """threshold=0 → 闸关闭,get_idle_seconds 都不会被调。"""
    llm_mock = AsyncMock(return_value='{"speak": true, "reason": "ok"}')
    idle_mock = AsyncMock()
    with patch.object(judge, "get_idle_threshold_seconds", return_value=0), \
         patch("backend.integrations.activity_monitor.get_idle_seconds",
               idle_mock), \
         patch.object(judge, "_call_judge_llm", llm_mock):
        d = await judge.maybe_judge(stay_info=_STAY_OK, today_count=0, daily_cap=5)
    assert d is not None
    idle_mock.assert_not_called()
    llm_mock.assert_awaited_once()


# ===========================================================================
# Part D: idle 闸顺序(记账 → idle 闸 → LLM)
# ===========================================================================


async def test_idle_gate_runs_after_record_judged() -> None:
    """idle 触发 skip 时,_record_judged 已经写入(throttle 计时按 idle skip 起算)。

    这是有意的:LLM 没跑,但 throttle 闸照样有效 — 人 5 min 内回到电脑
    不会触发 retry storm,下一次 stay tick 自然重新过完整闸。
    """
    judge_throttle_min = judge.get_judge_throttle_minutes()
    with patch.object(judge, "get_idle_threshold_seconds", return_value=300), \
         patch("backend.integrations.activity_monitor.get_idle_seconds",
               return_value=600.0):
        d = await judge.maybe_judge(stay_info=_STAY_OK, today_count=0, daily_cap=5)
    assert d is None
    # _record_judged 已经写入: 同 key 下一拍立刻被 throttle 闸挡
    assert judge._is_throttled(_STAY_OK["key"], judge_throttle_min * 60) is True


async def test_idle_gate_runs_after_min_stay_and_throttle() -> None:
    """min_stay 不够 → 不到 idle 闸(idle 不被查)。"""
    idle_mock = AsyncMock()
    short_stay = dict(_STAY_OK, duration_seconds=60)  # 1 min < 5 min min_stay
    with patch.object(judge, "get_idle_threshold_seconds", return_value=300), \
         patch("backend.integrations.activity_monitor.get_idle_seconds",
               idle_mock):
        d = await judge.maybe_judge(stay_info=short_stay, today_count=0, daily_cap=5)
    assert d is None
    idle_mock.assert_not_called()


async def test_idle_gate_runs_after_judge_disabled() -> None:
    """judge_enabled=False → idle 闸不查(短路返回)。"""
    idle_mock = AsyncMock()
    with patch.object(judge, "get_judge_enabled", return_value=False), \
         patch("backend.integrations.activity_monitor.get_idle_seconds",
               idle_mock):
        d = await judge.maybe_judge(stay_info=_STAY_OK, today_count=0, daily_cap=5)
    assert d is None
    idle_mock.assert_not_called()
