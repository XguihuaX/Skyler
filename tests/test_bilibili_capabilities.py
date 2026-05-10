"""v3.5 chunk 6a — 11 个 bilibili capability 注册 + handler 接 **_kwargs。

不测真实 B 站调用（已在 ``test_bilibili_integration.py`` 用 mock 覆盖）。
本文件只测 capability registry / ToolRegistry 接线 + handler 不炸。
"""
import asyncio
import os
import sys
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 触发 register side-effect
import backend.capabilities.bilibili  # noqa: F401
from backend.capabilities import CapabilityRegistry
from backend.tools.registry import ToolRegistry

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))


EXPECTED_CAPS = [
    "bilibili.search_video",
    "bilibili.get_video_info",
    "bilibili.search_user",
    "bilibili.get_user_videos",
    "bilibili.hot_videos",
    "bilibili.get_ranking",
    "bilibili.get_subtitles",
    "bilibili.get_my_history",
    "bilibili.get_my_followings",
    "bilibili.get_later_watch",
    "bilibili.get_favorites",
]


# ---------------------------------------------------------------------------
# 1. Registration coverage
# ---------------------------------------------------------------------------

def test_all_11_registered():
    print("\n[registry — 11 个 capability 都在 CapabilityRegistry]")
    reg = CapabilityRegistry()
    names = {c.name for c in reg.list_all()}
    for cap in EXPECTED_CAPS:
        check(f"{cap} present", cap in names)


def test_all_11_in_tool_registry():
    print("\n[ToolRegistry — 11 个 capability 都暴露 schema]")
    tool_names = {
        s["function"]["name"]
        for s in ToolRegistry.list_schemas()
        if "function" in s
    }
    for cap in EXPECTED_CAPS:
        check(f"{cap} in ToolRegistry", cap in tool_names)


def test_descriptions_strong_guidance():
    print("\n[descriptions — chunk 1.7 verbatim 强引导（含触发场景）]")
    reg = CapabilityRegistry()
    by_name = {c.name: c for c in reg.list_all()}
    for cap_name in EXPECTED_CAPS:
        cap = by_name.get(cap_name)
        if cap is None:
            check(f"{cap_name} found for desc check", False)
            continue
        desc = cap.description or ""
        check(
            f"{cap_name} description >= 80 chars",
            len(desc) >= 80,
            f"got {len(desc)} chars",
        )
        # 强引导：要么含 "用户说" 要么含 "适用场景" 要么含 "时调用"
        has_guidance = any(
            kw in desc for kw in ("用户说", "时调用", "适用场景", "杀手")
        )
        check(f"{cap_name} has guidance keyword", has_guidance,
              f"desc head: {desc[:60]!r}")


def test_consumers_chat_agent():
    print("\n[consumers — 全部 CHAT_AGENT 可见]")
    from backend.capabilities import Consumer
    reg = CapabilityRegistry()
    by_name = {c.name: c for c in reg.list_all()}
    for cap_name in EXPECTED_CAPS:
        cap = by_name[cap_name]
        check(f"{cap_name} CHAT_AGENT", Consumer.CHAT_AGENT in cap.consumers)


# ---------------------------------------------------------------------------
# 2. Handler signature 接 **_kwargs (cumulative contract)
# ---------------------------------------------------------------------------

def test_handlers_accept_user_id_kwarg():
    print("\n[handler 签名 — 接 user_id kwarg 不炸（**_kwargs 兜底）]")
    from backend.capabilities import bilibili as caps

    async def call(fn, **kw):
        return await fn(**kw)

    # Patch underlying integration to return canned dict
    with patch.object(caps._bili, "search_video",
                      AsyncMock(return_value={"result": []})):
        r = asyncio.run(call(caps.search_video, keyword="x", user_id="u1"))
        check("search_video accepts user_id", isinstance(r, dict))

    with patch.object(caps._bili, "get_video_info",
                      AsyncMock(return_value={"title": "x"})):
        r = asyncio.run(call(caps.get_video_info, bvid="BV1xx", user_id="u1"))
        check("get_video_info accepts user_id", isinstance(r, dict))

    with patch.object(caps._bili, "get_subtitles",
                      AsyncMock(return_value={"source": "none"})):
        r = asyncio.run(call(caps.get_subtitles, bvid="BV1xx", user_id="u1"))
        check("get_subtitles accepts user_id", isinstance(r, dict))

    with patch.object(caps._bili, "get_my_history",
                      AsyncMock(return_value={"result": []})):
        r = asyncio.run(call(caps.get_my_history, user_id="u1"))
        check("get_my_history accepts user_id", isinstance(r, dict))

    with patch.object(caps._bili, "get_later_watch",
                      AsyncMock(return_value={"result": []})):
        r = asyncio.run(call(caps.get_later_watch, user_id="u1"))
        check("get_later_watch accepts user_id", isinstance(r, dict))


def test_get_user_videos_missing_mid():
    print("\n[get_user_videos — 缺 mid 返 missing_mid 不炸]")
    from backend.capabilities import bilibili as caps
    r = asyncio.run(caps.get_user_videos(mid=0))
    check("missing_mid", r.get("error") == "missing_mid")


# ---------------------------------------------------------------------------
# 3. System prompt 含【B 站类】verbatim 块
# ---------------------------------------------------------------------------

def test_addendum_contains_bilibili_section():
    print("\n[chat.py _TOOL_PROMPT_ADDENDUM — 含【B 站类】verbatim 引导]")
    from backend.agents.chat import _TOOL_PROMPT_ADDENDUM
    check("contains 【B 站类】", "【B 站类】" in _TOOL_PROMPT_ADDENDUM)
    check("mentions get_subtitles", "bilibili.get_subtitles" in _TOOL_PROMPT_ADDENDUM)
    check("warns about 不要瞎编", "不要瞎编" in _TOOL_PROMPT_ADDENDUM
          or "不要原样输出字幕" in _TOOL_PROMPT_ADDENDUM)
    check("mentions cookie_required hint",
          "cookie_required" in _TOOL_PROMPT_ADDENDUM)
    check("red lines mentioned (投币/三连/弹幕/下载)",
          all(x in _TOOL_PROMPT_ADDENDUM for x in ("投币", "三连")))


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    test_all_11_registered()
    test_all_11_in_tool_registry()
    test_descriptions_strong_guidance()
    test_consumers_chat_agent()
    test_handlers_accept_user_id_kwarg()
    test_get_user_videos_missing_mid()
    test_addendum_contains_bilibili_section()

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
