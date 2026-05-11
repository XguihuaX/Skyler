"""v3.5 chunk 6b hotfix-2 — runtime smoke tests for 4 场景 capability。

hotfix-1 (commit 2d63a4a) 加的 fall-through 路径 65/65 单元测试全过，但
用户 runtime 调用 NCM API 真返了 `'bool' object is not callable` —— 旧
fake client 把 ``has_credentials`` 写成方法（真实 ``NeteaseClient`` 是
``@property``），单元测试与 prod 调用方约定不一致，bug 不会出现。

本文件目的：补一组**端到端 runtime smoke**，沿用 ChatAgent 真实 invoke
路径 (``ToolRegistry.call``)，只 stub 最底层 NCM HTTP API + ``_open_url``
+ ``mpv_player.get_player`` 避免网络 / subprocess 副作用。fake client
形态严格对齐**真实 NeteaseClient 出口契约**：

  - ``has_credentials`` 是 **属性** （不是 method）
  - ``daily_recommend / personal_fm / search / playlist_detail`` 返
    normalize 过的 dict（``artists: list[str]`` —— hotfix-1 错以为是
    ``[{name: ...}]`` 导致第二个 regression ``'str' object has no
    attribute 'get'``）

回归点保护：
  1. ``'bool' object is not callable`` —— hotfix-1 ``has_credentials()``
  2. ``'str' object has no attribute 'get'`` —— hotfix-1 raw NCM dict
     假设破在 ``_normalize_song`` 出口的字符串列表上

无论是否走 mpv / URL Scheme 路径都不能再炸 Python TypeError /
AttributeError —— 任何错误**必须**包成 capability dict 返回。
"""
from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.capabilities import netease_music as caps  # noqa: F401 — triggers register
from backend.capabilities import netease_playback  # noqa: F401 — 同上
from backend.integrations import netease_music as nm
from backend.tools.registry import ToolRegistry

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))


# ---------------------------------------------------------------------------
# 严格对齐真实 NeteaseClient 出口契约的 fake
# ---------------------------------------------------------------------------


class _RuntimeShapeFake:
    """模仿真实 ``NeteaseClient`` 暴露给 capability 的接口形态。

    关键差异 vs 旧 _MpvFakeClient / _FakeClient：
      * ``has_credentials`` 是属性（不是 method）—— 真实是 @property
      * ``daily_recommend / personal_fm / search`` 返 normalize 后的 dict
        （``artists: list[str]``，不是 raw ``ar: list[dict]``）

    单元测试还保留旧 fake（覆盖业务断言）；本 fake **专门**用于 smoke 期
    撞回 hotfix-1 那两类 runtime regression。
    """

    has_credentials: bool = True

    def __init__(self):
        # 真实 daily_recommend 出口形态（_normalize_song 后）：
        # {"id", "name", "artists": list[str], "album": str}
        self.daily_songs = [
            {"id": 22676165, "name": "Represent feat. Kimbara Chieko",
             "artists": ["DJ Okawari"], "album": "Kaleidoscope"},
            {"id": 1842025914, "name": "夜空中最亮的星",
             "artists": ["逃跑计划"], "album": "世界"},
        ]
        self.fm_songs = [
            {"id": 3001, "name": "Smooth Operator",
             "artists": ["Sade"], "album": "Diamond Life"},
        ]
        self.search_results = [
            {"id": 999, "name": "夜空中最亮的星",
             "artists": ["逃跑计划"], "album": "世界"},
        ]
        self.playlist_tracks = [
            {"id": 4001, "name": "Track A", "artists": ["Artist A"], "album": ""},
            {"id": 4002, "name": "Track B", "artists": ["Artist B"], "album": ""},
        ]

    def daily_recommend(self):
        return list(self.daily_songs)

    def personal_fm(self):
        return list(self.fm_songs)

    def search(self, keyword, search_type="song", limit=20):
        return list(self.search_results)

    def playlist_detail(self, playlist_id):
        return {"id": playlist_id, "name": "Test PL",
                "tracks": list(self.playlist_tracks)}

    def get_song_url(self, song_id, br=320000):
        return {
            "song_id": song_id,
            "url": f"http://m.music.com/{song_id}.mp3",
            "is_trial": False,
            "br": br,
        }


def _patches(fake_client):
    """共用 patch 上下文：fake 替换 get_client + no-op mpv + no-op _open_url。"""
    fake_player = MagicMock()
    fake_player.play = AsyncMock(return_value={"status": "playing"})
    fake_player.queue_clear = MagicMock()
    fake_player.queue_extend = MagicMock()
    async def fake_open(_url): return True
    return [
        patch.object(nm, "get_client", return_value=fake_client),
        patch.object(caps._mpv, "health_check",
                     AsyncMock(return_value={"status": "healthy"})),
        patch.object(caps._mpv, "get_player", return_value=fake_player),
        patch.object(caps, "_open_url", side_effect=fake_open),
    ]


def _no_python_crash(res, name: str) -> None:
    """Smoke 核心断言：任何 Python TypeError / AttributeError 都不能逃逸到 result。"""
    s = str(res)
    check(f"{name}: result is dict (handler 完整跑完)", isinstance(res, dict))
    check(f"{name}: 无 'bool' object is not callable", "'bool' object is not callable" not in s,
          detail=f"raw: {s[:200]}")
    check(f"{name}: 无 'str' object has no attribute", "'str' object has no attribute" not in s,
          detail=f"raw: {s[:200]}")
    err = res.get("error") if isinstance(res, dict) else ""
    if err:
        check(f"{name}: error 字段不含 'bool'", "bool" not in str(err))


# ---------------------------------------------------------------------------
# 4 个 capability runtime smoke
# ---------------------------------------------------------------------------


async def test_daily_recommend_runtime_smoke():
    print("\n[smoke] netease.daily_recommend via ToolRegistry.call")
    fake = _RuntimeShapeFake()
    cms = _patches(fake)
    for cm in cms: cm.__enter__()
    try:
        res = await ToolRegistry.call(
            "netease.daily_recommend",
            user_id="default", character_id=1,
        )
    finally:
        for cm in reversed(cms): cm.__exit__(None, None, None)
    _no_python_crash(res, "daily_recommend")
    # mpv 健康 + cookie 有 → 应走 mpv 路径
    check("daily_recommend: backend=mpv (mpv 全 healthy 路径)",
          res.get("backend") == "mpv")
    check("daily_recommend: autoplay True", res.get("autoplay") is True)


async def test_personal_fm_runtime_smoke():
    print("\n[smoke] netease.personal_fm via ToolRegistry.call")
    fake = _RuntimeShapeFake()
    cms = _patches(fake)
    for cm in cms: cm.__enter__()
    try:
        res = await ToolRegistry.call(
            "netease.personal_fm",
            user_id="default", character_id=1,
        )
    finally:
        for cm in reversed(cms): cm.__exit__(None, None, None)
    _no_python_crash(res, "personal_fm")
    check("personal_fm: backend=mpv", res.get("backend") == "mpv")
    check("personal_fm: autoplay True", res.get("autoplay") is True)


async def test_play_song_keyword_runtime_smoke():
    print("\n[smoke] netease.play_song(keyword='夜空') via ToolRegistry.call")
    fake = _RuntimeShapeFake()
    cms = _patches(fake)
    for cm in cms: cm.__enter__()
    try:
        res = await ToolRegistry.call(
            "netease.play_song",
            user_id="default", character_id=1,
            keyword="夜空中最亮的星",
        )
    finally:
        for cm in reversed(cms): cm.__exit__(None, None, None)
    _no_python_crash(res, "play_song")
    check("play_song: backend=mpv", res.get("backend") == "mpv")
    check("play_song: autoplay True", res.get("autoplay") is True)


async def test_play_playlist_by_id_runtime_smoke():
    print("\n[smoke] netease.play_playlist_by_id via ToolRegistry.call")
    fake = _RuntimeShapeFake()
    cms = _patches(fake)
    for cm in cms: cm.__enter__()
    try:
        res = await ToolRegistry.call(
            "netease.play_playlist_by_id",
            user_id="default", character_id=1,
            playlist_id=42,
        )
    finally:
        for cm in reversed(cms): cm.__exit__(None, None, None)
    _no_python_crash(res, "play_playlist_by_id")
    check("play_playlist_by_id: backend=mpv", res.get("backend") == "mpv")
    check("play_playlist_by_id: autoplay True", res.get("autoplay") is True)


# ---------------------------------------------------------------------------
# 再加 1 个 cookie-missing 路径（覆盖 _mpv_available_and_cookie_ok 属性读取）
# ---------------------------------------------------------------------------


async def test_daily_recommend_no_cookie_falls_back_no_crash():
    print("\n[smoke] daily_recommend — has_credentials=False 走 URL Scheme")
    fake = _RuntimeShapeFake()
    fake.has_credentials = False  # 属性读 False → mpv 短路 → URL Scheme
    cms = _patches(fake)
    for cm in cms: cm.__enter__()
    try:
        res = await ToolRegistry.call(
            "netease.daily_recommend",
            user_id="default", character_id=1,
        )
    finally:
        for cm in reversed(cms): cm.__exit__(None, None, None)
    _no_python_crash(res, "daily_recommend (no cookie)")
    check("daily_recommend (no cookie): backend=url_scheme",
          res.get("backend") == "url_scheme")
    check("daily_recommend (no cookie): autoplay False",
          res.get("autoplay") is False)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


async def amain():
    await test_daily_recommend_runtime_smoke()
    await test_personal_fm_runtime_smoke()
    await test_play_song_keyword_runtime_smoke()
    await test_play_playlist_by_id_runtime_smoke()
    await test_daily_recommend_no_cookie_falls_back_no_crash()


def main():
    asyncio.run(amain())
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
