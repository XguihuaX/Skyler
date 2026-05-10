"""v3.5 chunk 6b — backend/integrations/mpv_player.py 单元测试。

不真启动 mpv 子进程（CI / dev box 可能未装）。用 ``unittest.mock`` 替换
``asyncio.create_subprocess_exec`` 和 socket open。
"""
import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.integrations import mpv_player as mpv

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))


# ---------------------------------------------------------------------------
# 1. find_mpv_binary
# ---------------------------------------------------------------------------

def test_find_mpv_binary_real():
    print("\n[find_mpv_binary — 真实环境探测]")
    # 不强求 mpv 装了；只测函数返 str | None 不炸
    result = mpv.find_mpv_binary()
    check("returns str or None", result is None or isinstance(result, str))
    if result:
        check("path is executable", os.access(result, os.X_OK))


def test_find_mpv_binary_not_in_path():
    print("\n[find_mpv_binary — 全部路径 miss 时返 None]")
    with patch.object(mpv, "_MPV_BINARY_CANDIDATES",
                      ["/definitely/not/here", "/also/not/here", "no_such_bin"]):
        result = mpv.find_mpv_binary()
        check("returns None", result is None)


# ---------------------------------------------------------------------------
# 2. health_check
# ---------------------------------------------------------------------------

async def test_health_mpv_not_installed():
    print("\n[health_check — mpv 不存在]")
    with patch.object(mpv, "find_mpv_binary", return_value=None):
        r = await mpv.health_check()
        check("status error", r["status"] == "error")
        check("error mpv_not_installed", r["error"] == "mpv_not_installed")
        check("hint mentions brew install", "brew install mpv" in r["hint"])


async def test_health_mpv_version_ok():
    print("\n[health_check — mpv 装了 + --version OK]")
    fake_proc = MagicMock()
    fake_proc.communicate = AsyncMock(return_value=(b"mpv 0.40.0\n", b""))
    with patch.object(mpv, "find_mpv_binary", return_value="/fake/mpv"), \
         patch("asyncio.create_subprocess_exec", AsyncMock(return_value=fake_proc)):
        r = await mpv.health_check()
        check("status healthy", r["status"] == "healthy", f"got {r}")
        check("binary echoed", r["binary"] == "/fake/mpv")
        check("version captured", "mpv 0.40.0" in r["version"])


async def test_health_mpv_exec_failed():
    print("\n[health_check — mpv binary 在但跑不起来]")
    with patch.object(mpv, "find_mpv_binary", return_value="/fake/mpv"), \
         patch("asyncio.create_subprocess_exec",
               AsyncMock(side_effect=OSError("permission denied"))):
        r = await mpv.health_check()
        check("status warn", r["status"] == "warn", f"got {r}")
        check("error mpv_exec_failed", r["error"] == "mpv_exec_failed")


# ---------------------------------------------------------------------------
# 3. MpvPlayer state machine (no real spawn)
# ---------------------------------------------------------------------------

def test_player_initial_state():
    print("\n[MpvPlayer — 初始状态]")
    p = mpv.MpvPlayer("/fake/mpv")
    check("not running", not p.is_running())
    check("queue empty", p.queue() == [])
    check("current None", p.current() is None)


def test_player_queue_ops():
    print("\n[MpvPlayer — queue extend / clear]")
    p = mpv.MpvPlayer("/fake/mpv")
    p.queue_extend([
        {"url": "http://a.mp3", "meta": {"title": "A"}},
        {"url": "http://b.mp3", "meta": {"title": "B"}},
    ])
    check("queue length 2", len(p.queue()) == 2)
    check("first item correct", p.queue()[0]["url"] == "http://a.mp3")
    p.queue_clear()
    check("queue cleared", p.queue() == [])


async def test_player_play_next_empty():
    print("\n[MpvPlayer.play_next — 空队列]")
    p = mpv.MpvPlayer("/fake/mpv")
    r = await p.play_next()
    check("returns queue_empty", r["status"] == "queue_empty")


async def test_player_pause_not_running():
    print("\n[MpvPlayer.pause — 未启动时不炸]")
    p = mpv.MpvPlayer("/fake/mpv")
    r = await p.pause()
    check("not_running", r["status"] == "not_running")


async def test_player_stop_not_running():
    print("\n[MpvPlayer.stop — 未启动时不炸]")
    p = mpv.MpvPlayer("/fake/mpv")
    r = await p.stop()
    check("stopped", r["status"] == "stopped")


async def test_player_shutdown_noop_when_not_running():
    print("\n[MpvPlayer.shutdown — 未启动 no-op 不炸]")
    p = mpv.MpvPlayer("/fake/mpv")
    await p.shutdown()  # 不应抛
    check("shutdown idempotent", True)


# ---------------------------------------------------------------------------
# 4. Singleton
# ---------------------------------------------------------------------------

def test_get_player_singleton():
    print("\n[get_player — singleton + missing binary 时 raise]")
    mpv._reset_for_test()
    with patch.object(mpv, "find_mpv_binary", return_value=None):
        try:
            mpv.get_player()
            check("missing binary raises", False)
        except RuntimeError as exc:
            check("missing binary raises RuntimeError", True)
            check("error mentions brew install", "brew install mpv" in str(exc))
    mpv._reset_for_test()


async def test_shutdown_player_when_no_singleton():
    print("\n[shutdown_player — singleton 未创建时 no-op]")
    mpv._reset_for_test()
    await mpv.shutdown_player()  # 不应抛
    check("safe no-op", True)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

async def amain():
    await test_health_mpv_not_installed()
    await test_health_mpv_version_ok()
    await test_health_mpv_exec_failed()
    await test_player_play_next_empty()
    await test_player_pause_not_running()
    await test_player_stop_not_running()
    await test_player_shutdown_noop_when_not_running()
    await test_shutdown_player_when_no_singleton()


def main():
    test_find_mpv_binary_real()
    test_find_mpv_binary_not_in_path()
    asyncio.run(amain())
    test_player_initial_state()
    test_player_queue_ops()
    test_get_player_singleton()

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
    main()
