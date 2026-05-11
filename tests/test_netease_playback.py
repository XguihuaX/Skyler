"""v3.5 chunk 6b — netease_playback 6 capability + chunk 1 collision check。

Mock NeteaseClient + mpv_player.get_player()，不真启动 mpv，不真打 NCM API。
"""
import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 触发 register
import backend.capabilities.netease_music   # chunk 1
import backend.capabilities.netease_playback as caps
from backend.capabilities import CapabilityRegistry
from backend.tools.registry import ToolRegistry

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))


EXPECTED_LOCAL_CAPS = [
    "netease.local_play_song",
    "netease.local_play_playlist",
    "netease.local_pause",
    "netease.local_resume",
    "netease.local_stop",
    "netease.local_next_in_queue",
]


# ---------------------------------------------------------------------------
# 1. Registration (no collision with chunk 1)
# ---------------------------------------------------------------------------

def test_six_local_caps_registered():
    print("\n[chunk 6b — 6 个 local_* capability 全部注册]")
    reg = CapabilityRegistry()
    names = {c.name for c in reg.list_all()}
    for cap in EXPECTED_LOCAL_CAPS:
        check(f"{cap} present", cap in names)


def test_chunk1_still_present():
    print("\n[chunk 1 — play_song / play_playlist 仍存在（无 collision）]")
    reg = CapabilityRegistry()
    names = {c.name for c in reg.list_all()}
    check("netease.play_song still registered (chunk 1)",
          "netease.play_song" in names)
    check("netease.play_playlist still registered (chunk 1)",
          "netease.play_playlist" in names)


def test_no_namespace_collision():
    print("\n[ToolRegistry — no duplicate names]")
    tool_names = [
        s["function"]["name"]
        for s in ToolRegistry.list_schemas()
        if "function" in s
    ]
    dups = [n for n in tool_names if tool_names.count(n) > 1]
    check("no duplicates", len(dups) == 0, f"dups: {set(dups)}")


# ---------------------------------------------------------------------------
# 2. Missing args / mpv_not_installed
# ---------------------------------------------------------------------------

async def test_play_song_missing_id():
    print("\n[local_play_song — 缺 song_id]")
    r = await caps.play_song(song_id=0)
    check("missing_song_id", r.get("error") == "missing_song_id")


async def test_play_song_mpv_missing():
    print("\n[local_play_song — mpv 未装]")
    with patch.object(caps._mpv, "health_check",
                      AsyncMock(return_value={"status": "error",
                                              "error": "mpv_not_installed"})):
        r = await caps.play_song(song_id=12345)
        check("returns mpv_not_installed", r.get("error") == "mpv_not_installed")


async def test_play_song_cookie_missing():
    print("\n[local_play_song — mpv OK 但 cookie 未配]")
    fake_client = MagicMock()
    fake_client.has_credentials = False
    with patch.object(caps._mpv, "health_check",
                      AsyncMock(return_value={"status": "healthy"})), \
         patch.object(caps._nem, "get_client", return_value=fake_client):
        r = await caps.play_song(song_id=12345)
        check("cookie_required", r.get("error") == "cookie_required")


async def test_play_song_url_unavailable():
    print("\n[local_play_song — song/url 返空 url]")
    fake_client = MagicMock()
    fake_client.has_credentials = True
    fake_client.get_song_url = MagicMock(return_value={
        "song_id": 12345, "url": "", "is_trial": False,
    })
    with patch.object(caps._mpv, "health_check",
                      AsyncMock(return_value={"status": "healthy"})), \
         patch.object(caps._nem, "get_client", return_value=fake_client):
        r = await caps.play_song(song_id=12345)
        check("url_unavailable", r.get("error") == "url_unavailable")


async def test_play_song_happy():
    print("\n[local_play_song — happy 路径 mpv 播+ trial flag]")
    fake_client = MagicMock()
    fake_client.has_credentials = True
    fake_client.get_song_url = MagicMock(return_value={
        "song_id": 12345, "url": "http://m.music.com/a.mp3",
        "is_trial": True, "br": 320000,
    })
    fake_player = MagicMock()
    fake_player.play = AsyncMock(return_value={"status": "playing"})
    with patch.object(caps._mpv, "health_check",
                      AsyncMock(return_value={"status": "healthy"})), \
         patch.object(caps._mpv, "get_player", return_value=fake_player), \
         patch.object(caps._nem, "get_client", return_value=fake_client):
        r = await caps.play_song(song_id=12345)
        check("status playing", r.get("status") == "playing")
        check("is_trial flag echoed", r.get("is_trial") is True)
        check("note mentions 试听", "试听" in (r.get("note") or ""))


# ---------------------------------------------------------------------------
# 3. Transport controls
# ---------------------------------------------------------------------------

async def test_pause_resume_stop():
    print("\n[transport — pause / resume / stop / next_in_queue]")
    fake_player = MagicMock()
    fake_player.pause = AsyncMock(return_value={"status": "paused"})
    fake_player.resume = AsyncMock(return_value={"status": "playing"})
    fake_player.stop = AsyncMock(return_value={"status": "stopped"})
    fake_player.play_next = AsyncMock(return_value={"status": "queue_empty"})
    fake_player.queue_clear = MagicMock()
    with patch.object(caps._mpv, "get_player", return_value=fake_player):
        r = await caps.pause()
        check("pause → paused", r["status"] == "paused")
        r = await caps.resume()
        check("resume → playing", r["status"] == "playing")
        r = await caps.stop()
        check("stop → stopped", r["status"] == "stopped")
        check("stop clears queue", fake_player.queue_clear.called)
        r = await caps.next_in_queue()
        check("next_in_queue → queue_empty", r["status"] == "queue_empty")


# ---------------------------------------------------------------------------
# 4. play_playlist (orchestration)
# ---------------------------------------------------------------------------

async def test_play_playlist_happy():
    print("\n[local_play_playlist — first plays + rest queued]")
    fake_client = MagicMock()
    fake_client.has_credentials = True
    fake_client.playlist_detail = MagicMock(return_value={"tracks": [
        {"id": 1, "name": "Song A", "ar": [{"name": "Artist A"}]},
        {"id": 2, "name": "Song B", "ar": [{"name": "Artist B"}]},
        {"id": 3, "name": "Song C", "ar": []},
    ]})

    def fake_get_url(sid):
        return {"song_id": sid, "url": f"http://m.music.com/{sid}.mp3",
                "is_trial": False}
    fake_client.get_song_url = fake_get_url

    fake_player = MagicMock()
    fake_player.play = AsyncMock(return_value={"status": "playing"})
    fake_player.queue_extend = MagicMock()
    fake_player.queue_clear = MagicMock()

    with patch.object(caps._mpv, "health_check",
                      AsyncMock(return_value={"status": "healthy"})), \
         patch.object(caps._mpv, "get_player", return_value=fake_player), \
         patch.object(caps._nem, "get_client", return_value=fake_client):
        r = await caps.play_playlist(playlist_id=999, limit=10)
        check("status playing", r.get("status") == "playing")
        check("playlist_id echoed", r.get("playlist_id") == 999)
        check("first_song_id = 1", r.get("first_song_id") == 1)
        check("queued count 3 (1 first + 2 rest)", r.get("queued") == 3)
        check("queue_clear called", fake_player.queue_clear.called)


async def test_play_playlist_empty():
    print("\n[local_play_playlist — 空歌单 → empty_playlist]")
    fake_client = MagicMock()
    fake_client.has_credentials = True
    fake_client.playlist_detail = MagicMock(return_value={"tracks": []})
    with patch.object(caps._mpv, "health_check",
                      AsyncMock(return_value={"status": "healthy"})), \
         patch.object(caps._nem, "get_client", return_value=fake_client):
        r = await caps.play_playlist(playlist_id=999)
        check("empty_playlist error", r.get("error") == "empty_playlist")


# ---------------------------------------------------------------------------
# 5. **_kwargs contract
# ---------------------------------------------------------------------------

async def test_handlers_accept_user_id():
    print("\n[handler — 接 user_id kwarg 不炸]")
    fake_player = MagicMock()
    fake_player.pause = AsyncMock(return_value={"status": "paused"})
    fake_player.resume = AsyncMock(return_value={"status": "playing"})
    fake_player.stop = AsyncMock(return_value={"status": "stopped"})
    fake_player.play_next = AsyncMock(return_value={"status": "queue_empty"})
    fake_player.queue_clear = MagicMock()
    with patch.object(caps._mpv, "get_player", return_value=fake_player):
        r = await caps.pause(user_id="u1")
        check("pause accepts user_id", isinstance(r, dict))
        r = await caps.next_in_queue(user_id="u1")
        check("next_in_queue accepts user_id", isinstance(r, dict))


# ---------------------------------------------------------------------------
# 6. System prompt has 【网易云本地 mpv...】section
# ---------------------------------------------------------------------------

def test_addendum_has_local_section():
    print("\n[chat addendum — 网易云本地 mpv 段 verbatim]")
    from backend.agents.chat import _TOOL_PROMPT_ADDENDUM
    check("contains '网易云本地 mpv'", "网易云本地 mpv" in _TOOL_PROMPT_ADDENDUM)
    check("contains 'local_play_song'",
          "netease.local_play_song" in _TOOL_PROMPT_ADDENDUM)
    check("contains '首选'",
          "首选" in _TOOL_PROMPT_ADDENDUM)
    check("contains '试听片段'",
          "试听片段" in _TOOL_PROMPT_ADDENDUM)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

async def amain():
    await test_play_song_missing_id()
    await test_play_song_mpv_missing()
    await test_play_song_cookie_missing()
    await test_play_song_url_unavailable()
    await test_play_song_happy()
    await test_pause_resume_stop()
    await test_play_playlist_happy()
    await test_play_playlist_empty()
    await test_handlers_accept_user_id()


def main():
    test_six_local_caps_registered()
    test_chunk1_still_present()
    test_no_namespace_collision()
    asyncio.run(amain())
    test_addendum_has_local_section()

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
