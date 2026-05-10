"""v3.5 chunk 6a — backend/integrations/bilibili.py 单元测试。

完全 mock 网络层：``bilibili_api`` 模块的 ``hot.get_hot_videos`` /
``search.search_by_type`` / ``video.Video`` / ``user`` / etc. 通过
``unittest.mock.patch`` 替换。不打真实 B 站，不依赖 SESSDATA。

覆盖 :
  - 健康检查三档全场景（library 缺 / cookie 缺 / connectivity 失败 / 全好）
  - 11 个 client 方法 happy path
  - 错误归一化：cookie_required / library_missing / risk_control /
    rate_limited / network_error / invalid_args
  - 字幕选优：AI 优先 → 手动 → none fallback
  - ``<em>`` 高亮剥除
"""
from __future__ import annotations

import asyncio
import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.integrations import bilibili as bili

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))


# ---------------------------------------------------------------------------
# 1. health_check 四种场景
# ---------------------------------------------------------------------------

async def test_health_library_missing():
    print("\n[health — library 缺失]")
    # 强制走 import-failed 路径
    with patch.object(bili, "_LIB_AVAILABLE", False), \
         patch.object(bili, "_LIB_IMPORT_ERR", "fake import err"):
        r = await bili.health_check()
        check("status error", r["status"] == "error")
        check("error library_missing", r["error"] == "library_missing")


async def test_health_no_cookie_but_lib_ok():
    print("\n[health — lib ok / no cookie / connectivity ok]")
    fake_ba = MagicMock()
    fake_ba.hot.get_hot_videos = AsyncMock(return_value={"list": []})
    with patch.object(bili, "_try_import_lib", return_value=(fake_ba, None)), \
         patch.dict(os.environ, {"BILIBILI_SESSDATA": ""}, clear=False):
        if "BILIBILI_SESSDATA" in os.environ:
            del os.environ["BILIBILI_SESSDATA"]
        r = await bili.health_check()
        check("status warn", r["status"] == "warn", f"got {r}")
        check("cookie_configured False", r["cookie_configured"] is False)
        check("connectivity ok", r["connectivity"] == "ok")
        check("hint note present", r.get("note") and "BILIBILI_SESSDATA" in r["note"])


async def test_health_with_cookie():
    print("\n[health — lib ok / cookie ok / connectivity ok]")
    fake_ba = MagicMock()
    fake_ba.hot.get_hot_videos = AsyncMock(return_value={"list": []})
    with patch.object(bili, "_try_import_lib", return_value=(fake_ba, None)), \
         patch.dict(os.environ, {"BILIBILI_SESSDATA": "fake_cookie_value"}):
        r = await bili.health_check()
        check("status healthy", r["status"] == "healthy", f"got {r}")
        check("cookie_configured True", r["cookie_configured"] is True)


async def test_health_connectivity_fail():
    print("\n[health — lib ok but connectivity fail]")
    fake_ba = MagicMock()
    fake_ba.hot.get_hot_videos = AsyncMock(side_effect=Exception("network down"))
    with patch.object(bili, "_try_import_lib", return_value=(fake_ba, None)):
        r = await bili.health_check()
        check("status warn", r["status"] == "warn", f"got {r}")
        check("connectivity fail", r["connectivity"] == "fail")


# ---------------------------------------------------------------------------
# 2. No-cookie methods happy path (mock bilibili_api)
# ---------------------------------------------------------------------------

def _make_fake_ba_for_search_video():
    fake_ba = MagicMock()
    fake_ba.search.SearchObjectType.VIDEO = "video"
    fake_ba.search.search_by_type = AsyncMock(return_value={
        "result": [{
            "bvid": "BV1XX",
            "aid": 12345,
            "title": "<em class=\"keyword\">LLM</em> 教程",
            "author": "tester",
            "duration": "10:30",
            "play": 1000,
            "description": "hi",
        }],
        "numResults": 1,
        "page": 1,
    })
    return fake_ba


async def test_search_video_happy():
    print("\n[search_video — happy + <em> 剥除]")
    fake_ba = _make_fake_ba_for_search_video()
    with patch.object(bili, "_try_import_lib", return_value=(fake_ba, None)):
        r = await bili.search_video("LLM")
        check("has result", isinstance(r.get("result"), list) and r["result"])
        check("<em> stripped",
              "<em" not in r["result"][0]["title"]
              and "LLM" in r["result"][0]["title"])
        check("url built",
              r["result"][0]["url"] == "https://www.bilibili.com/video/BV1XX")


async def test_search_video_missing_keyword():
    print("\n[search_video — 空 keyword 拒]")
    fake_ba = _make_fake_ba_for_search_video()
    with patch.object(bili, "_try_import_lib", return_value=(fake_ba, None)):
        r = await bili.search_video("")
        check("missing_keyword", r.get("error") == "missing_keyword")


async def test_get_video_info_happy():
    print("\n[get_video_info — happy]")
    fake_ba = MagicMock()
    fake_video = MagicMock()
    fake_video.get_info = AsyncMock(return_value={
        "bvid": "BV1xx",
        "aid": 111,
        "cid": 222,
        "title": "测试视频",
        "desc": "描述",
        "duration": 300,
        "pubdate": 1700000000,
        "owner": {"mid": 999, "name": "UP"},
        "stat": {"view": 5000, "like": 100, "favorite": 50, "danmaku": 30,
                 "coin": 10, "share": 5, "reply": 2},
    })
    fake_ba.video.Video = MagicMock(return_value=fake_video)
    with patch.object(bili, "_try_import_lib", return_value=(fake_ba, None)):
        r = await bili.get_video_info(bvid="BV1xx")
        check("title", r.get("title") == "测试视频")
        check("owner.name", r.get("owner", {}).get("name") == "UP")
        check("stat.view", r.get("stat", {}).get("view") == 5000)


async def test_get_video_info_missing():
    print("\n[get_video_info — 缺 bvid/aid]")
    fake_ba = MagicMock()
    with patch.object(bili, "_try_import_lib", return_value=(fake_ba, None)):
        r = await bili.get_video_info()
        check("missing_bvid_or_aid", r.get("error") == "missing_bvid_or_aid")


async def test_hot_videos_happy():
    print("\n[hot_videos — happy]")
    fake_ba = MagicMock()
    fake_ba.hot.get_hot_videos = AsyncMock(return_value={"list": [
        {"bvid": "BV1", "aid": 1, "title": "热门 1", "duration": 100,
         "owner": {"name": "UP1"}, "stat": {"view": 10000}},
    ]})
    with patch.object(bili, "_try_import_lib", return_value=(fake_ba, None)):
        r = await bili.hot_videos()
        check("count 1", len(r.get("result", [])) == 1)
        check("owner flat", r["result"][0]["owner"] == "UP1")


async def test_get_ranking_happy():
    print("\n[get_ranking — happy]")
    fake_ba = MagicMock()
    fake_ba.rank.RankType.All = "all"
    fake_ba.rank.RankType.Rookie = "rookie"
    fake_ba.rank.RankType.Origin = "origin"
    fake_ba.rank.RankDayType.THREE_DAY = 3
    fake_ba.rank.RankDayType.SEVEN_DAY = 7
    fake_ba.rank.get_rank = AsyncMock(return_value={"list": [
        {"bvid": "BV2", "title": "排行 1", "owner": {"name": "UP"},
         "stat": {"view": 99999}, "score": 12345},
    ]})
    with patch.object(bili, "_try_import_lib", return_value=(fake_ba, None)):
        r = await bili.get_ranking(rank_type="all", day=3)
        check("result[0].bvid", r["result"][0]["bvid"] == "BV2")
        check("rank_type echoed", r["rank_type"] == "all")


async def test_search_user_happy():
    print("\n[search_user — happy]")
    fake_ba = MagicMock()
    fake_ba.search.SearchObjectType.USER = "user"
    fake_ba.search.search_by_type = AsyncMock(return_value={"result": [
        {"mid": 1, "uname": "<em>UP</em>主一号", "fans": 1000,
         "videos": 50, "level": 5, "usign": "签名"},
    ]})
    with patch.object(bili, "_try_import_lib", return_value=(fake_ba, None)):
        r = await bili.search_user("UP")
        check("name <em> stripped",
              "<em" not in r["result"][0]["name"]
              and "UP主一号" in r["result"][0]["name"])


async def test_get_user_videos_happy():
    print("\n[get_user_videos — happy]")
    fake_ba = MagicMock()
    fake_user = MagicMock()
    fake_user.get_videos = AsyncMock(return_value={
        "list": {"vlist": [
            {"bvid": "BVu", "aid": 100, "title": "video 1",
             "length": "5:00", "play": 500, "created": 1700000000},
        ]},
        "page": {"count": 1},
    })
    fake_ba.user.User = MagicMock(return_value=fake_user)
    with patch.object(bili, "_try_import_lib", return_value=(fake_ba, None)):
        r = await bili.get_user_videos(mid=999)
        check("videos count 1", len(r.get("videos", [])) == 1)
        check("mid echoed", r["mid"] == 999)


# ---------------------------------------------------------------------------
# 3. Cookie required — no cookie → cookie_required dict
# ---------------------------------------------------------------------------


def _clear_sessdata():
    os.environ.pop("BILIBILI_SESSDATA", None)


async def test_subtitles_no_cookie():
    print("\n[get_subtitles — no cookie → cookie_required]")
    fake_ba = MagicMock()
    fake_ba.Credential = MagicMock(return_value=MagicMock())
    with patch.object(bili, "_try_import_lib", return_value=(fake_ba, None)):
        _clear_sessdata()
        r = await bili.get_subtitles(bvid="BV1xx")
        check("cookie_required", r.get("error") == "cookie_required")
        check("hint present", "BILIBILI_SESSDATA" in (r.get("hint") or ""))


async def test_history_no_cookie():
    print("\n[get_my_history — no cookie → cookie_required]")
    fake_ba = MagicMock()
    fake_ba.Credential = MagicMock(return_value=MagicMock())
    with patch.object(bili, "_try_import_lib", return_value=(fake_ba, None)):
        _clear_sessdata()
        r = await bili.get_my_history()
        check("cookie_required", r.get("error") == "cookie_required")


# ---------------------------------------------------------------------------
# 4. Subtitle picker
# ---------------------------------------------------------------------------

def test_choose_subtitle_ai_priority():
    print("\n[_choose_subtitle — AI 优先]")
    subs = [
        {"lan": "zh-CN", "ai_type": 0},      # 手动
        {"lan": "ai-zh", "ai_type": 1},      # AI
    ]
    chosen, source = bili._choose_subtitle(subs)
    check("source ai", source == "ai")
    check("AI picked", chosen["ai_type"] == 1)


def test_choose_subtitle_manual_fallback():
    print("\n[_choose_subtitle — 无 AI 退到 manual zh]")
    subs = [{"lan": "zh-CN", "ai_type": 0}]
    chosen, source = bili._choose_subtitle(subs)
    check("source manual", source == "manual")


def test_choose_subtitle_empty():
    print("\n[_choose_subtitle — empty → none]")
    chosen, source = bili._choose_subtitle([])
    check("none", chosen is None and source == "none")


def test_strip_em():
    print("\n[_strip_em — 剥 <em> 高亮]")
    check("simple",
          bili._strip_em('<em class="keyword">x</em> y') == "x y")
    check("none safe", bili._strip_em(None) == "")


# ---------------------------------------------------------------------------
# 5. Risk control error mapping
# ---------------------------------------------------------------------------

def test_normalize_risk_codes():
    print("\n[_normalize_error — 风控 code 映射]")
    e1 = Exception("frequent")
    e1.code = -352
    r1 = bili._normalize_error(e1)
    check("-352 → risk_control", r1["error"] == "risk_control")
    check("code echoed", r1.get("bilibili_code") == -352)

    e2 = Exception("limit")
    e2.code = -412
    r2 = bili._normalize_error(e2)
    check("-412 → rate_limited", r2["error"] == "rate_limited")

    e3 = ValueError("random")
    r3 = bili._normalize_error(e3)
    check("unknown → bilibili_error", r3["error"] == "bilibili_error")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

async def amain():
    await test_health_library_missing()
    await test_health_no_cookie_but_lib_ok()
    await test_health_with_cookie()
    await test_health_connectivity_fail()

    await test_search_video_happy()
    await test_search_video_missing_keyword()
    await test_get_video_info_happy()
    await test_get_video_info_missing()
    await test_hot_videos_happy()
    await test_get_ranking_happy()
    await test_search_user_happy()
    await test_get_user_videos_happy()

    await test_subtitles_no_cookie()
    await test_history_no_cookie()


def main():
    asyncio.run(amain())
    test_choose_subtitle_ai_priority()
    test_choose_subtitle_manual_fallback()
    test_choose_subtitle_empty()
    test_strip_em()
    test_normalize_risk_codes()

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
