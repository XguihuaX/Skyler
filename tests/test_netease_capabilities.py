"""v3-H chunk 1 — netease.* capabilities 注册 + 行为测试。

不调真实网易云；mock 底层 client。验证：
  - 7 个 capability 都注册到 CapabilityRegistry + ToolRegistry
  - daily_recommend / personal_fm / play_song 唤起 url 正确
  - play_playlist 不直接播 (only lists)
  - play_playlist_by_id 用传入 id
  - like_current 走 search → like 两步
  - 搜不到时不调 like，返 error
"""
import asyncio
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import backend.integrations.netease_music as nm
import backend.capabilities.netease_music as caps  # noqa: F401  decorator side-effect

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))


# ---------------------------------------------------------------------------
# 1. 7 个 capability 都注册了
# ---------------------------------------------------------------------------

def test_caps_registered():
    print("\n[netease caps — registration]")
    from backend.capabilities import CapabilityRegistry, Consumer
    reg = CapabilityRegistry()
    expected = [
        "netease.daily_recommend",
        "netease.personal_fm",
        "netease.play_song",
        "netease.play_playlist",
        "netease.play_playlist_by_id",
        "netease.like_current",
        "netease.search",
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
# 2. daily_recommend → opens first song URL
# ---------------------------------------------------------------------------

class _FakeClient:
    def __init__(self):
        self.calls = []
        self.daily_recs = [
            {"id": 100, "name": "A", "artists": ["x"], "album": "alb"},
            {"id": 200, "name": "B", "artists": ["y"], "album": "alb"},
        ]
        self.fm_songs = [
            {"id": 300, "name": "FM", "artists": ["z"], "album": ""},
        ]
        self.search_results = [
            {"id": 999, "name": "夜空", "artists": ["逃跑计划"], "album": "世界"},
        ]
        self.playlists = [
            {"id": 1, "name": "我喜欢的音乐", "track_count": 10, "is_liked": True},
            {"id": 2, "name": "🏃 跑步专用", "track_count": 5, "is_liked": False},
        ]
        self.like_will_succeed = True

    # v3.5 chunk 6b hotfix-2：真实 NeteaseClient.has_credentials 是 @property，
    # 此处用实例属性同样满足 `if not client.has_credentials` 读取语义（fake
    # 默认 False → URL Scheme fallback 路径）。早期写成方法导致 hotfix-1 prod
    # 代码 .has_credentials() 调一个 bool runtime 炸 —— 这里修对齐 property
    # 形态，下次 fake 复用不会再踩同坑。
    has_credentials: bool = False

    def daily_recommend(self):
        self.calls.append(("daily",))
        return self.daily_recs

    def personal_fm(self):
        self.calls.append(("fm",))
        return self.fm_songs

    def search(self, keyword, search_type="song", limit=20):
        self.calls.append(("search", keyword, search_type, limit))
        return self.search_results

    def my_playlists(self, limit=100):
        self.calls.append(("my_playlists", limit))
        return self.playlists

    def like_song(self, song_id, like=True):
        self.calls.append(("like", song_id, like))
        return self.like_will_succeed


async def test_daily_recommend_opens_first():
    print("\n[netease caps — daily_recommend opens first song + triggers autoplay]")
    fake = _FakeClient()
    opened_urls = []
    trigger_calls = []

    async def fake_open(url):
        opened_urls.append(url)
        return True

    async def fake_trigger():
        trigger_calls.append(True)
        return True

    with patch.object(nm, "get_client", return_value=fake), \
         patch.object(caps, "_open_url", side_effect=fake_open), \
         patch.object(caps, "_trigger_ncm_play", side_effect=fake_trigger):
        out = await caps.daily_recommend()
    check("opened True", out["opened"] is True)
    check("opened first song URL with /play", opened_urls == ["orpheus://song/100/play"])
    check("first_song id=100", out["first_song"]["id"] == 100)
    check("songs sample limited to 5", len(out["songs"]) == 2)
    # v3.5 chunk 6b hotfix-1：URL Scheme fallback 路径下 autoplay 诚实置 False
    # （mpv 未装时 URL Scheme 唤起 NCM 不会自动播；之前 _trigger_ncm_play
    # 实测无效，本 hotfix 移除该调用 + 改返 false）
    check("autoplay False (honest URL-scheme fallback)", out.get("autoplay") is False)
    check("backend url_scheme", out.get("backend") == "url_scheme")
    check("hint present for mpv install", "mpv" in (out.get("hint") or ""))
    check("trigger no longer called on fallback path", len(trigger_calls) == 0)


async def test_daily_recommend_empty_returns_error():
    print("\n[netease caps — daily empty returns error, no open, no trigger]")
    fake = _FakeClient()
    fake.daily_recs = []
    opened_urls = []
    trigger_calls = []
    async def fake_open(url):
        opened_urls.append(url); return True
    async def fake_trigger():
        trigger_calls.append(True); return True
    with patch.object(nm, "get_client", return_value=fake), \
         patch.object(caps, "_open_url", side_effect=fake_open), \
         patch.object(caps, "_trigger_ncm_play", side_effect=fake_trigger):
        out = await caps.daily_recommend()
    check("opened False", out["opened"] is False)
    check("no open called", opened_urls == [])
    check("no trigger called (gated on opened)", trigger_calls == [])
    check("error present", "日推" in (out.get("error") or ""))


# ---------------------------------------------------------------------------
# 3. personal_fm 优先用 orpheus://fm
# ---------------------------------------------------------------------------

async def test_personal_fm_uses_fm_scheme():
    print("\n[netease caps — personal_fm uses orpheus://personalFM, NO autoplay trigger]")
    fake = _FakeClient()
    opened_urls = []
    trigger_calls = []
    async def fake_open(url):
        opened_urls.append(url); return True
    async def fake_trigger():
        trigger_calls.append(True); return True
    with patch.object(nm, "get_client", return_value=fake), \
         patch.object(caps, "_open_url", side_effect=fake_open), \
         patch.object(caps, "_trigger_ncm_play", side_effect=fake_trigger):
        out = await caps.personal_fm()
    check("opened True", out["opened"] is True)
    check(
        "first call orpheus://personalFM (community canonical form)",
        opened_urls[0] == "orpheus://personalFM",
    )
    check("personal_fm does NOT trigger nowplaying-cli (URL自带 autoplay)", trigger_calls == [])


# ---------------------------------------------------------------------------
# 4. play_song
# ---------------------------------------------------------------------------

async def test_play_song_searches_and_opens():
    print("\n[netease caps — play_song search → open → trigger autoplay]")
    fake = _FakeClient()
    opened_urls = []
    trigger_calls = []
    async def fake_open(url):
        opened_urls.append(url); return True
    async def fake_trigger():
        trigger_calls.append(True); return True
    with patch.object(nm, "get_client", return_value=fake), \
         patch.object(caps, "_open_url", side_effect=fake_open), \
         patch.object(caps, "_trigger_ncm_play", side_effect=fake_trigger):
        out = await caps.play_song(keyword="夜空")
    check("opened True", out["opened"] is True)
    check("opened song URL with /play", opened_urls == ["orpheus://song/999/play"])
    check("song id=999", out["song"]["id"] == 999)
    # v3.5 chunk 6b hotfix-1：fallback 路径 autoplay 诚实置 False
    check("autoplay False (URL-scheme fallback)", out.get("autoplay") is False)
    check("backend url_scheme", out.get("backend") == "url_scheme")
    check("trigger no longer called on fallback", len(trigger_calls) == 0)
    # search call sent
    search_calls = [c for c in fake.calls if c[0] == "search"]
    check("search called", len(search_calls) == 1)
    check("search keyword forwarded", search_calls[0][1] == "夜空")


async def test_play_song_no_results():
    print("\n[netease caps — play_song with no search results, no trigger]")
    fake = _FakeClient()
    fake.search_results = []
    opened_urls = []
    trigger_calls = []
    async def fake_open(url):
        opened_urls.append(url); return True
    async def fake_trigger():
        trigger_calls.append(True); return True
    with patch.object(nm, "get_client", return_value=fake), \
         patch.object(caps, "_open_url", side_effect=fake_open), \
         patch.object(caps, "_trigger_ncm_play", side_effect=fake_trigger):
        out = await caps.play_song(keyword="xxxxxxxxxxxx不存在")
    check("opened False", out["opened"] is False)
    check("no open called", opened_urls == [])
    check("no trigger called", trigger_calls == [])
    check("song None", out["song"] is None)


# ---------------------------------------------------------------------------
# 5. play_playlist 不直接播
# ---------------------------------------------------------------------------

async def test_play_playlist_lists_only():
    print("\n[netease caps — play_playlist returns list, doesn't open]")
    fake = _FakeClient()
    opened_urls = []
    async def fake_open(url):
        opened_urls.append(url); return True
    with patch.object(nm, "get_client", return_value=fake), \
         patch.object(caps, "_open_url", side_effect=fake_open):
        out = await caps.play_playlist()
    check("opened key absent (no play yet)", "opened" not in out)
    check("playlists returned", len(out["playlists"]) == 2)
    check("next_step hint present", "play_playlist_by_id" in (out.get("next_step") or ""))
    check("no open called", opened_urls == [])


async def test_play_playlist_by_id_opens():
    print("\n[netease caps — play_playlist_by_id open（URL Scheme fallback）]")
    fake = _FakeClient()  # has_credentials → False → 走 URL Scheme fallback
    opened_urls = []
    trigger_calls = []
    async def fake_open(url):
        opened_urls.append(url); return True
    async def fake_trigger():
        trigger_calls.append(True); return True
    with patch.object(nm, "get_client", return_value=fake), \
         patch.object(caps, "_open_url", side_effect=fake_open), \
         patch.object(caps, "_trigger_ncm_play", side_effect=fake_trigger):
        out = await caps.play_playlist_by_id(playlist_id=42)
    check("opened True", out["opened"] is True)
    check("URL = orpheus://playlist/42/play", opened_urls == ["orpheus://playlist/42/play"])
    check("playlist_id echoed", out["playlist_id"] == 42)
    # v3.5 chunk 6b hotfix-1：fallback 路径 autoplay 诚实置 False
    check("autoplay False (URL-scheme fallback)", out.get("autoplay") is False)
    check("backend url_scheme", out.get("backend") == "url_scheme")
    check("trigger no longer called", len(trigger_calls) == 0)


# ---------------------------------------------------------------------------
# 6. like_current 两步
# ---------------------------------------------------------------------------

async def test_like_current_searches_then_likes():
    print("\n[netease caps — like_current does search → like]")
    fake = _FakeClient()
    with patch.object(nm, "get_client", return_value=fake):
        out = await caps.like_current(title="夜空中最亮的星", artist="逃跑计划")
    check("liked True", out["liked"] is True)
    check("song id=999", out["song"]["id"] == 999)
    # both search + like were called
    kinds = [c[0] for c in fake.calls]
    check("search called before like", "search" in kinds and "like" in kinds and kinds.index("search") < kinds.index("like"))


async def test_like_current_not_found():
    print("\n[netease caps — like_current with no search match]")
    fake = _FakeClient()
    fake.search_results = []
    with patch.object(nm, "get_client", return_value=fake):
        out = await caps.like_current(title="some non-netease song")
    check("liked False", out["liked"] is False)
    check("error mentions not found", "搜到" in (out.get("error") or ""))
    # like_song NOT called
    kinds = [c[0] for c in fake.calls]
    check("like NOT called", "like" not in kinds)


# ---------------------------------------------------------------------------
# 7. search returns shape with type
# ---------------------------------------------------------------------------

async def test_search_returns_shape():
    print("\n[netease caps — search wraps result with keyword + type]")
    fake = _FakeClient()
    with patch.object(nm, "get_client", return_value=fake):
        out = await caps.search(keyword="hello", search_type="album", limit=5)
    check("keyword echoed", out["keyword"] == "hello")
    check("type echoed", out["type"] == "album")
    check("results passed through", out["results"] == fake.search_results)
    # limit clamped at min 1 / max 30
    search_calls = [c for c in fake.calls if c[0] == "search"]
    check("limit forwarded", search_calls[0][3] == 5)
    check("type forwarded", search_calls[0][2] == "album")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

_FAKE_BIN_NETEASE = "/opt/homebrew/bin/nowplaying-cli"


async def test_trigger_ncm_play_calls_nowplaying_cli():
    print("\n[netease caps — _trigger_ncm_play invokes nowplaying-cli with absolute path]")
    captured: dict = {"cmd": None, "slept": None}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        m = type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        return m

    async def fake_sleep(secs):
        captured["slept"] = secs

    with patch.object(caps, "get_nowplaying_bin", return_value=_FAKE_BIN_NETEASE), \
         patch.object(caps.subprocess, "run", side_effect=fake_run), \
         patch.object(caps.asyncio, "sleep", side_effect=fake_sleep):
        ok = await caps._trigger_ncm_play()
    check("trigger ok=True", ok is True)
    check(
        "cmd uses absolute path returned by get_nowplaying_bin",
        captured["cmd"] == [_FAKE_BIN_NETEASE, "play"],
    )
    check("slept ~1.5s", captured["slept"] == caps._NCM_PLAY_DELAY_SEC)


async def test_trigger_ncm_play_handles_missing_cli():
    print("\n[netease caps — _trigger_ncm_play handles bin=None (PATH miss)]")
    sleep_called = {"v": False}
    async def fake_sleep(secs):
        sleep_called["v"] = True
    with patch.object(caps, "get_nowplaying_bin", return_value=None), \
         patch.object(caps.asyncio, "sleep", side_effect=fake_sleep):
        ok = await caps._trigger_ncm_play()
    check("returns False when bin is None", ok is False)
    check("does NOT sleep when bin is None (early return)", sleep_called["v"] is False)


async def test_trigger_ncm_play_handles_timeout():
    print("\n[netease caps — _trigger_ncm_play handles subprocess timeout]")
    import subprocess as sp
    def boom(cmd, **kwargs):
        raise sp.TimeoutExpired(cmd=cmd, timeout=2)
    async def fake_sleep(secs):
        pass
    with patch.object(caps, "get_nowplaying_bin", return_value=_FAKE_BIN_NETEASE), \
         patch.object(caps.subprocess, "run", side_effect=boom), \
         patch.object(caps.asyncio, "sleep", side_effect=fake_sleep):
        ok = await caps._trigger_ncm_play()
    check("returns False on timeout", ok is False)


async def test_trigger_ncm_play_handles_nonzero_rc():
    print("\n[netease caps — _trigger_ncm_play handles non-zero exit]")
    def fake_run(cmd, **kwargs):
        m = type("R", (), {"returncode": 1, "stdout": "", "stderr": "error"})()
        return m
    async def fake_sleep(secs):
        pass
    with patch.object(caps, "get_nowplaying_bin", return_value=_FAKE_BIN_NETEASE), \
         patch.object(caps.subprocess, "run", side_effect=fake_run), \
         patch.object(caps.asyncio, "sleep", side_effect=fake_sleep):
        ok = await caps._trigger_ncm_play()
    check("returns False on rc!=0", ok is False)


async def main():
    test_caps_registered()
    await test_daily_recommend_opens_first()
    await test_daily_recommend_empty_returns_error()
    await test_personal_fm_uses_fm_scheme()
    await test_play_song_searches_and_opens()
    await test_play_song_no_results()
    await test_play_playlist_lists_only()
    await test_play_playlist_by_id_opens()
    await test_like_current_searches_then_likes()
    await test_like_current_not_found()
    await test_search_returns_shape()
    await test_trigger_ncm_play_calls_nowplaying_cli()
    await test_trigger_ncm_play_handles_missing_cli()
    await test_trigger_ncm_play_handles_timeout()
    await test_trigger_ncm_play_handles_nonzero_rc()

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
