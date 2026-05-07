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
         patch.object(mc, "_NOWPLAYING_BIN", None):
        h = await mc.health_check()
    check("warn", h["status"] == "warn")
    check("提示 brew install", "brew install nowplaying-cli" in (h.get("error") or ""))


async def test_health_ok_returns_binary_path():
    print("\n[media — health: macOS + cli resolved → healthy + binary]")
    FAKE_BIN = "/opt/homebrew/bin/nowplaying-cli"
    with patch.object(mc, "IS_MACOS", True), \
         patch.object(mc, "_NOWPLAYING_BIN", FAKE_BIN):
        h = await mc.health_check()
    check("healthy", h["status"] == "healthy")
    check("binary path returned", h.get("binary") == FAKE_BIN)


# ---------------------------------------------------------------------------
# 2.5. 路径解析（PATH-found / fallback / both-miss）
# ---------------------------------------------------------------------------

def test_resolver_prefers_shutil_which():
    print("\n[media — resolver: shutil.which hit takes priority]")
    with patch.object(mc.shutil, "which", return_value="/some/path/nowplaying-cli"):
        out = mc._resolve_nowplaying_bin()
    check("uses PATH result", out == "/some/path/nowplaying-cli")


def test_resolver_falls_back_to_homebrew_apple_silicon():
    print("\n[media — resolver: PATH miss → /opt/homebrew/bin fallback]")
    HB = "/opt/homebrew/bin/nowplaying-cli"
    def fake_isfile(p):
        return p == HB
    def fake_access(p, mode):
        return p == HB
    with patch.object(mc.shutil, "which", return_value=None), \
         patch.object(mc.os.path, "isfile", side_effect=fake_isfile), \
         patch.object(mc.os, "access", side_effect=fake_access):
        out = mc._resolve_nowplaying_bin()
    check("falls back to /opt/homebrew", out == HB)


def test_resolver_falls_back_to_homebrew_intel():
    print("\n[media — resolver: PATH miss + /opt/homebrew miss → /usr/local/bin]")
    USR_LOCAL = "/usr/local/bin/nowplaying-cli"
    def fake_isfile(p):
        return p == USR_LOCAL
    def fake_access(p, mode):
        return p == USR_LOCAL
    with patch.object(mc.shutil, "which", return_value=None), \
         patch.object(mc.os.path, "isfile", side_effect=fake_isfile), \
         patch.object(mc.os, "access", side_effect=fake_access):
        out = mc._resolve_nowplaying_bin()
    check("falls back to /usr/local", out == USR_LOCAL)


def test_resolver_returns_none_when_all_miss():
    print("\n[media — resolver: PATH miss + Homebrew miss → None]")
    with patch.object(mc.shutil, "which", return_value=None), \
         patch.object(mc.os.path, "isfile", return_value=False):
        out = mc._resolve_nowplaying_bin()
    check("returns None", out is None)


def test_refresh_updates_module_global():
    print("\n[media — refresh_nowplaying_bin re-runs resolution]")
    original = mc._NOWPLAYING_BIN
    try:
        with patch.object(mc, "_resolve_nowplaying_bin", return_value="/x/y/nowplaying-cli"):
            out = mc.refresh_nowplaying_bin()
        check("module global updated", mc._NOWPLAYING_BIN == "/x/y/nowplaying-cli")
        check("return value matches", out == "/x/y/nowplaying-cli")
    finally:
        mc._NOWPLAYING_BIN = original


# ---------------------------------------------------------------------------
# 3. next / previous / play_pause invoke nowplaying-cli
# ---------------------------------------------------------------------------

_FAKE_BIN = "/opt/homebrew/bin/nowplaying-cli"


async def _run_with_fake_subprocess(coro_fn, *, rc=0, stdout="", stderr=""):
    """patch _NOWPLAYING_BIN=fake + _run_sync to record cmd + return canned."""
    captured: dict = {"cmd": None}
    def fake_run(cmd):
        captured["cmd"] = cmd
        return rc, stdout, stderr
    with patch.object(mc, "_NOWPLAYING_BIN", _FAKE_BIN), \
         patch.object(mc, "IS_MACOS", True), \
         patch.object(mc, "_run_sync", side_effect=fake_run):
        out = await coro_fn()
    return out, captured["cmd"]


async def test_next_track():
    print("\n[media — next_track invokes nowplaying-cli with absolute path]")
    out, cmd = await _run_with_fake_subprocess(mc.next_track, rc=0)
    check("ok True", out["ok"] is True)
    check("cmd uses absolute path", cmd == [_FAKE_BIN, "next"])


async def test_previous_track():
    print("\n[media — previous_track invokes nowplaying-cli with absolute path]")
    out, cmd = await _run_with_fake_subprocess(mc.previous_track, rc=0)
    check("ok True", out["ok"] is True)
    check("cmd uses absolute path", cmd == [_FAKE_BIN, "previous"])


async def test_play_pause():
    print("\n[media — play_pause invokes togglePlayPause with absolute path]")
    out, cmd = await _run_with_fake_subprocess(mc.play_pause, rc=0)
    check("ok True", out["ok"] is True)
    check("cmd uses absolute path", cmd == [_FAKE_BIN, "togglePlayPause"])


async def test_next_track_failure_passes_stderr():
    print("\n[media — next_track propagates stderr on failure]")
    out, _cmd = await _run_with_fake_subprocess(
        mc.next_track, rc=1, stderr="some error",
    )
    check("ok False", out["ok"] is False)
    check("error message", out["error"] == "some error")


async def test_next_track_with_no_cli_short_circuits():
    print("\n[media — next_track with _NOWPLAYING_BIN=None short-circuits]")
    captured = {"called": False}
    def fake_run(cmd):
        captured["called"] = True
        return 0, "", ""
    with patch.object(mc, "_NOWPLAYING_BIN", None), \
         patch.object(mc, "IS_MACOS", True), \
         patch.object(mc, "_run_sync", side_effect=fake_run):
        out = await mc.next_track()
    check("ok False", out["ok"] is False)
    check("error mentions install", "brew install" in (out.get("error") or ""))
    check("subprocess NOT invoked when bin is None", captured["called"] is False)


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
    check("cmd uses absolute path + get fields", cmd == [_FAKE_BIN, "get", "title", "artist", "album"])


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
    print("\n[media — now_playing with bin=None returns playing=False]")
    with patch.object(mc, "_NOWPLAYING_BIN", None), \
         patch.object(mc, "IS_MACOS", True):
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
    await test_health_ok_returns_binary_path()
    test_resolver_prefers_shutil_which()
    test_resolver_falls_back_to_homebrew_apple_silicon()
    test_resolver_falls_back_to_homebrew_intel()
    test_resolver_returns_none_when_all_miss()
    test_refresh_updates_module_global()
    await test_next_track()
    await test_next_track_with_no_cli_short_circuits()
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
