"""v3.5 chunk 6b hotfix-1 — 场景类 capability fall-through 测试。

覆盖 4 个改过的 capability 在 **mpv-available** 分支的行为（旧
test_netease_capabilities.py 覆盖 mpv-unavailable / URL Scheme fallback
分支）：

  - netease.daily_recommend
  - netease.personal_fm
  - netease.play_song (keyword)
  - netease.play_playlist_by_id

通过 patch ``_mpv_available_and_cookie_ok`` 与 ``mpv_player.get_player``
模拟 mpv healthy；patch ``client.get_song_url`` / ``playlist_detail``
模拟 NCM API。
"""
from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.capabilities import netease_music as caps
from backend.integrations import netease_music as nm

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))


# ---------------------------------------------------------------------------
# Fake client with has_credentials + get_song_url
# ---------------------------------------------------------------------------


class _MpvFakeClient:
    """支持 chunk 6b 接口（has_credentials / get_song_url / playlist_detail）。"""

    def __init__(self):
        self.calls: list = []
        self.daily_recs = [
            {"id": 1001, "name": "Song A", "ar": [{"name": "Artist A"}]},
            {"id": 1002, "name": "Song B", "ar": [{"name": "Artist B"}]},
        ]
        self.fm_songs = [
            {"id": 2001, "name": "FM 1", "ar": [{"name": "FM Artist"}]},
        ]
        self.search_results = [
            {"id": 3001, "name": "夜空", "ar": [{"name": "逃跑计划"}]},
        ]
        # playlist_detail returns dict {tracks: [...]}
        self._playlist_tracks = [
            {"id": 4001, "name": "Pl 1", "ar": []},
            {"id": 4002, "name": "Pl 2", "ar": []},
        ]

    # v3.5 chunk 6b hotfix-2：对齐真实 NeteaseClient.has_credentials @property
    # 语义 —— 属性读取（而非方法调用）。早期方法形态使 prod 代码 .has_credentials()
    # 调一个 bool 在 runtime 炸 ('bool' object is not callable)。
    has_credentials: bool = True

    def daily_recommend(self):
        return self.daily_recs

    def personal_fm(self):
        return self.fm_songs

    def search(self, keyword, search_type="song", limit=20):
        self.calls.append(("search", keyword, search_type))
        return self.search_results

    def playlist_detail(self, playlist_id):
        self.calls.append(("playlist_detail", playlist_id))
        return {"tracks": self._playlist_tracks}

    def get_song_url(self, song_id, br=320000):
        self.calls.append(("get_song_url", song_id))
        return {
            "song_id": song_id,
            "url": f"http://m.music.com/{song_id}.mp3",
            "is_trial": False,
            "br": br,
        }


# ---------------------------------------------------------------------------
# 1. daily_recommend — mpv available branch
# ---------------------------------------------------------------------------

async def test_daily_recommend_mpv_path_autoplay_true():
    print("\n[daily_recommend — mpv healthy → autoplay=True, backend=mpv]")
    fake = _MpvFakeClient()
    fake_player = MagicMock()
    fake_player.play = AsyncMock(return_value={"status": "playing"})
    fake_player.queue_clear = MagicMock()
    fake_player.queue_extend = MagicMock()

    with patch.object(nm, "get_client", return_value=fake), \
         patch.object(caps, "_mpv_available_and_cookie_ok",
                      AsyncMock(return_value=True)), \
         patch.object(caps._mpv, "get_player", return_value=fake_player):
        out = await caps.daily_recommend()

    check("opened True", out.get("opened") is True)
    check("autoplay True (mpv)", out.get("autoplay") is True)
    check("backend mpv", out.get("backend") == "mpv")
    check("first_song id 1001", out["first_song"]["id"] == 1001)
    check("queued >= 1", (out.get("queued") or 0) >= 1)
    check("mpv.play called", fake_player.play.called)
    check("queue_clear called once", fake_player.queue_clear.call_count == 1)


async def test_daily_recommend_mpv_fail_falls_back():
    print("\n[daily_recommend — mpv healthy but play_song fails → URL Scheme fallback]")
    fake = _MpvFakeClient()

    def bad_song_url(sid, br=320000):
        return {"song_id": sid, "url": "", "is_trial": False}  # url empty → url_unavailable
    fake.get_song_url = bad_song_url

    opened_urls = []
    async def fake_open(url):
        opened_urls.append(url)
        return True

    with patch.object(nm, "get_client", return_value=fake), \
         patch.object(caps, "_mpv_available_and_cookie_ok",
                      AsyncMock(return_value=True)), \
         patch.object(caps, "_open_url", side_effect=fake_open):
        out = await caps.daily_recommend()

    check("falls back to URL Scheme", out.get("backend") == "url_scheme")
    check("autoplay False (honest)", out.get("autoplay") is False)
    check("hint mentions mpv", "mpv" in (out.get("hint") or ""))
    check("URL Scheme was attempted", len(opened_urls) == 1)


# ---------------------------------------------------------------------------
# 2. personal_fm — mpv available
# ---------------------------------------------------------------------------

async def test_personal_fm_mpv_path_autoplay_true():
    print("\n[personal_fm — mpv healthy → mpv 真闭环 + autoplay=True]")
    fake = _MpvFakeClient()
    fake_player = MagicMock()
    fake_player.play = AsyncMock(return_value={"status": "playing"})
    fake_player.queue_clear = MagicMock()
    fake_player.queue_extend = MagicMock()

    with patch.object(nm, "get_client", return_value=fake), \
         patch.object(caps, "_mpv_available_and_cookie_ok",
                      AsyncMock(return_value=True)), \
         patch.object(caps._mpv, "get_player", return_value=fake_player):
        out = await caps.personal_fm()

    check("opened True", out.get("opened") is True)
    check("autoplay True (mpv)", out.get("autoplay") is True)
    check("backend mpv", out.get("backend") == "mpv")
    check("mpv.play called", fake_player.play.called)


# ---------------------------------------------------------------------------
# 3. play_song(keyword) — mpv available
# ---------------------------------------------------------------------------

async def test_play_song_keyword_mpv_path():
    print("\n[play_song(keyword) — mpv healthy → mpv play + autoplay=True]")
    fake = _MpvFakeClient()
    fake_player = MagicMock()
    fake_player.play = AsyncMock(return_value={"status": "playing"})

    with patch.object(nm, "get_client", return_value=fake), \
         patch.object(caps, "_mpv_available_and_cookie_ok",
                      AsyncMock(return_value=True)), \
         patch.object(caps._mpv, "get_player", return_value=fake_player):
        out = await caps.play_song(keyword="夜空")

    check("opened True", out.get("opened") is True)
    check("autoplay True", out.get("autoplay") is True)
    check("backend mpv", out.get("backend") == "mpv")
    check("song echoed", out.get("song", {}).get("id") == 3001)
    check("mpv.play called", fake_player.play.called)


async def test_play_song_keyword_no_results_no_mpv_call():
    print("\n[play_song(keyword) — empty search → no mpv call + autoplay=False]")
    fake = _MpvFakeClient()
    fake.search_results = []
    fake_player = MagicMock()
    fake_player.play = AsyncMock(return_value={"status": "playing"})

    with patch.object(nm, "get_client", return_value=fake), \
         patch.object(caps, "_mpv_available_and_cookie_ok",
                      AsyncMock(return_value=True)), \
         patch.object(caps._mpv, "get_player", return_value=fake_player):
        out = await caps.play_song(keyword="不存在")

    check("opened False", out.get("opened") is False)
    check("autoplay False", out.get("autoplay") is False)
    check("error present", "没搜到" in (out.get("error") or ""))
    check("mpv.play NOT called", not fake_player.play.called)


# ---------------------------------------------------------------------------
# 4. play_playlist_by_id — mpv available
# ---------------------------------------------------------------------------

async def test_play_playlist_by_id_mpv_path():
    print("\n[play_playlist_by_id — mpv healthy → mpv queue + autoplay=True]")
    fake = _MpvFakeClient()
    fake_player = MagicMock()
    fake_player.play = AsyncMock(return_value={"status": "playing"})
    fake_player.queue_clear = MagicMock()
    fake_player.queue_extend = MagicMock()

    with patch.object(nm, "get_client", return_value=fake), \
         patch.object(caps, "_mpv_available_and_cookie_ok",
                      AsyncMock(return_value=True)), \
         patch.object(caps._mpv, "get_player", return_value=fake_player):
        out = await caps.play_playlist_by_id(playlist_id=42)

    check("opened True", out.get("opened") is True)
    check("autoplay True", out.get("autoplay") is True)
    check("backend mpv", out.get("backend") == "mpv")
    check("first_song_id 4001", out.get("first_song_id") == 4001)
    check("queued >= 1", (out.get("queued") or 0) >= 1)
    check("queue_clear called", fake_player.queue_clear.call_count == 1)


# ---------------------------------------------------------------------------
# 5. mpv-availability helper
# ---------------------------------------------------------------------------

async def test_mpv_availability_combined():
    print("\n[_mpv_available_and_cookie_ok — 组合检查]")
    fake = _MpvFakeClient()
    # cookie OK + mpv healthy → True
    with patch.object(nm, "get_client", return_value=fake), \
         patch.object(caps._mpv, "health_check",
                      AsyncMock(return_value={"status": "healthy"})):
        check("cookie OK + mpv healthy → True",
              await caps._mpv_available_and_cookie_ok() is True)

    # cookie missing → False (短路，不调 health_check)
    fake.has_credentials = False
    with patch.object(nm, "get_client", return_value=fake), \
         patch.object(caps._mpv, "health_check",
                      AsyncMock(return_value={"status": "healthy"})):
        check("cookie missing → False",
              await caps._mpv_available_and_cookie_ok() is False)

    # cookie OK + mpv not_installed → False
    fake.has_credentials = True
    with patch.object(nm, "get_client", return_value=fake), \
         patch.object(caps._mpv, "health_check",
                      AsyncMock(return_value={"status": "error",
                                              "error": "mpv_not_installed"})):
        check("mpv unhealthy → False",
              await caps._mpv_available_and_cookie_ok() is False)


# ---------------------------------------------------------------------------
# 6. No music:// scheme bug (audit verification)
# ---------------------------------------------------------------------------

def test_no_music_scheme_bug():
    print("\n[Audit — codebase has no music:// scheme reference]")
    import pathlib
    backend = pathlib.Path(__file__).parent.parent / "backend"
    found_music_scheme = []
    for py in backend.rglob("*.py"):
        try:
            text = py.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        if "music://" in text:
            found_music_scheme.append(str(py))
    check("No 'music://' references in backend/", not found_music_scheme,
          f"found in: {found_music_scheme}")
    # And orpheus:// IS used (sanity check)
    found_orpheus = []
    for py in backend.rglob("*.py"):
        try:
            text = py.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        if "orpheus://" in text:
            found_orpheus.append(str(py))
    check("orpheus:// scheme present (canonical NCM)",
          len(found_orpheus) > 0)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

async def amain():
    await test_daily_recommend_mpv_path_autoplay_true()
    await test_daily_recommend_mpv_fail_falls_back()
    await test_personal_fm_mpv_path_autoplay_true()
    await test_play_song_keyword_mpv_path()
    await test_play_song_keyword_no_results_no_mpv_call()
    await test_play_playlist_by_id_mpv_path()
    await test_mpv_availability_combined()


def main():
    asyncio.run(amain())
    test_no_music_scheme_bug()

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
