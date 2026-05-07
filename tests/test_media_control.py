"""v3-H chunk 1 — media.* capability 测试（subprocess 全 mock）。"""
import asyncio
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import backend.capabilities.media_control as mc

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))


# ---------------------------------------------------------------------------
# 1. 5 个 capability 都注册
# ---------------------------------------------------------------------------

def test_caps_registered():
    print("\n[media — registration]")
    from backend.capabilities import CapabilityRegistry, Consumer
    reg = CapabilityRegistry()
    expected = [
        "media.next_track",
        "media.previous_track",
        "media.play_pause",
        "media.now_playing",
        "media.set_volume",
    ]
    for name in expected:
        cap = reg.get(name)
        check(f"{name} registered", cap is not None)
        if cap is not None:
            check(
                f"{name} CHAT_AGENT consumer",
                Consumer.CHAT_AGENT in cap.consumers,
            )


# ---------------------------------------------------------------------------
# 2. health_check 各档
# ---------------------------------------------------------------------------

async def test_health_non_macos():
    print("\n[media — health: non-macOS warn]")
    with patch.object(mc, "IS_MACOS", False):
        h = await mc.health_check()
    check("non-macOS warn", h["status"] == "warn")
    check("提示仅 macOS", "macOS" in (h.get("error") or ""))


async def test_health_no_cli():
    print("\n[media — health: nowplaying-cli missing → warn]")
    with patch.object(mc, "IS_MACOS", True), \
         patch.object(mc.shutil, "which", return_value=None):
        h = await mc.health_check()
    check("warn", h["status"] == "warn")
    check("提示 brew install", "brew install nowplaying-cli" in (h.get("error") or ""))


async def test_health_ok():
    print("\n[media — health: macOS + cli installed → healthy]")
    with patch.object(mc, "IS_MACOS", True), \
         patch.object(mc.shutil, "which", return_value="/opt/homebrew/bin/nowplaying-cli"):
        h = await mc.health_check()
    check("healthy", h["status"] == "healthy")


# ---------------------------------------------------------------------------
# 3. next / previous / play_pause invoke nowplaying-cli
# ---------------------------------------------------------------------------

async def _run_with_fake_subprocess(coro_fn, *, rc=0, stdout="", stderr=""):
    """patch _has_nowplaying_cli=True + _run_sync to record cmd + return canned."""
    captured: dict = {"cmd": None}
    def fake_run(cmd):
        captured["cmd"] = cmd
        return rc, stdout, stderr
    with patch.object(mc, "_has_nowplaying_cli", return_value=True), \
         patch.object(mc, "IS_MACOS", True), \
         patch.object(mc, "_run_sync", side_effect=fake_run):
        out = await coro_fn()
    return out, captured["cmd"]


async def test_next_track():
    print("\n[media — next_track invokes 'nowplaying-cli next']")
    out, cmd = await _run_with_fake_subprocess(mc.next_track, rc=0)
    check("ok True", out["ok"] is True)
    check("cmd correct", cmd == ["nowplaying-cli", "next"])


async def test_previous_track():
    print("\n[media — previous_track invokes 'nowplaying-cli previous']")
    out, cmd = await _run_with_fake_subprocess(mc.previous_track, rc=0)
    check("ok True", out["ok"] is True)
    check("cmd correct", cmd == ["nowplaying-cli", "previous"])


async def test_play_pause():
    print("\n[media — play_pause invokes togglePlayPause]")
    out, cmd = await _run_with_fake_subprocess(mc.play_pause, rc=0)
    check("ok True", out["ok"] is True)
    check("cmd correct", cmd == ["nowplaying-cli", "togglePlayPause"])


async def test_next_track_failure_passes_stderr():
    print("\n[media — next_track propagates stderr on failure]")
    out, _cmd = await _run_with_fake_subprocess(
        mc.next_track, rc=1, stderr="some error",
    )
    check("ok False", out["ok"] is False)
    check("error message", out["error"] == "some error")


# ---------------------------------------------------------------------------
# 4. now_playing parsing
# ---------------------------------------------------------------------------

async def test_now_playing_parses_three_lines():
    print("\n[media — now_playing parses title/artist/album lines]")
    out, cmd = await _run_with_fake_subprocess(
        mc.now_playing,
        rc=0,
        stdout="夜空中最亮的星\n逃跑计划\n世界\n",
    )
    check("title", out["title"] == "夜空中最亮的星")
    check("artist", out["artist"] == "逃跑计划")
    check("album", out["album"] == "世界")
    check("playing True", out["playing"] is True)
    check("cmd has get title artist album", cmd == ["nowplaying-cli", "get", "title", "artist", "album"])


async def test_now_playing_nothing_playing():
    print("\n[media — now_playing returns nulls when nothing playing]")
    out, _cmd = await _run_with_fake_subprocess(
        mc.now_playing, rc=0, stdout="\n\n\n",
    )
    check("title None", out["title"] is None)
    check("artist None", out["artist"] is None)
    check("album None", out["album"] is None)
    check("playing False", out["playing"] is False)


async def test_now_playing_null_string_treated_as_none():
    print("\n[media — now_playing treats literal 'null' as None]")
    out, _cmd = await _run_with_fake_subprocess(
        mc.now_playing, rc=0, stdout="null\nnull\nnull\n",
    )
    check("title None (was 'null')", out["title"] is None)
    check("playing False", out["playing"] is False)


async def test_now_playing_no_cli():
    print("\n[media — now_playing with cli missing returns playing=False]")
    with patch.object(mc, "_has_nowplaying_cli", return_value=False):
        out = await mc.now_playing()
    check("playing False", out["playing"] is False)
    check("error 提示 brew", "brew install nowplaying-cli" in (out.get("error") or ""))


# ---------------------------------------------------------------------------
# 5. set_volume via osascript
# ---------------------------------------------------------------------------

async def test_set_volume_clamps_and_calls_osascript():
    print("\n[media — set_volume clamps + invokes osascript]")
    captured: dict = {}
    def fake_run(cmd):
        captured["cmd"] = cmd
        return 0, "", ""
    with patch.object(mc, "IS_MACOS", True), \
         patch.object(mc, "_run_sync", side_effect=fake_run):
        out_high = await mc.set_volume(level=150)
        cmd_high = captured["cmd"]
        out_neg  = await mc.set_volume(level=-5)
        cmd_neg  = captured["cmd"]
        out_mid  = await mc.set_volume(level=42)
        cmd_mid  = captured["cmd"]
    check("clamp upper to 100", out_high["level"] == 100)
    check("upper script", cmd_high == ["osascript", "-e", "set volume output volume 100"])
    check("clamp lower to 0", out_neg["level"] == 0)
    check("lower script", cmd_neg == ["osascript", "-e", "set volume output volume 0"])
    check("mid stays 42", out_mid["level"] == 42)
    check("mid script", cmd_mid == ["osascript", "-e", "set volume output volume 42"])


async def test_set_volume_non_macos():
    print("\n[media — set_volume on non-macOS returns error]")
    with patch.object(mc, "IS_MACOS", False):
        out = await mc.set_volume(level=50)
    check("ok False", out["ok"] is False)
    check("error mentions macOS", "macOS" in (out.get("error") or ""))


# ---------------------------------------------------------------------------
# 6. timeout / FileNotFoundError handling in _run_sync
# ---------------------------------------------------------------------------

def test_run_sync_timeout():
    print("\n[media — _run_sync handles TimeoutExpired]")
    import subprocess as sp
    def boom(*a, **kw):
        raise sp.TimeoutExpired(cmd=a[0] if a else "?", timeout=2)
    with patch.object(mc.subprocess, "run", side_effect=boom):
        rc, stdout, stderr = mc._run_sync(["whatever"])
    check("rc=-1 on timeout", rc == -1)
    check("stderr=timeout", stderr == "timeout")


def test_run_sync_filenotfound():
    print("\n[media — _run_sync handles FileNotFoundError]")
    def boom(*a, **kw):
        raise FileNotFoundError("no such binary")
    with patch.object(mc.subprocess, "run", side_effect=boom):
        rc, _stdout, stderr = mc._run_sync(["whatever"])
    check("rc=-2 on FileNotFoundError", rc == -2)
    check("stderr captured", "no such binary" in stderr)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

async def main():
    test_caps_registered()
    await test_health_non_macos()
    await test_health_no_cli()
    await test_health_ok()
    await test_next_track()
    await test_previous_track()
    await test_play_pause()
    await test_next_track_failure_passes_stderr()
    await test_now_playing_parses_three_lines()
    await test_now_playing_nothing_playing()
    await test_now_playing_null_string_treated_as_none()
    await test_now_playing_no_cli()
    await test_set_volume_clamps_and_calls_osascript()
    await test_set_volume_non_macos()
    test_run_sync_timeout()
    test_run_sync_filenotfound()

    total = len(results)
    passed = sum(1 for _, ok in results if ok)
    print(f"\n{'=' * 40}")
    print(f"Results: {passed}/{total} passed")
    if passed < total:
        print("FAILED:", ", ".join(n for n, ok in results if not ok))
        sys.exit(1)
    else:
        print("ALL TESTS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
