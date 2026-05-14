"""Bugfix-3.2.9 — tool name sanitize layer tests。

防 DeepSeek/OpenAI strict tool name schema 拒掉(``^[a-zA-Z0-9_-]+$``)。

Coverage:
  * sanitize_tool_name — 各种非法字符替换 + 开头数字 + 空串兜底 + 幂等
  * sanitize_tools_for_llm — 批量 + reverse_map 构造 + 原 list 不变
  * 集成:LLM emit sanitized → dispatcher .get(reverse_map) 反查回 original

Run:
    .venv/bin/python tests/test_tool_name_sanitize.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.llm.tool_name_sanitize import (
    sanitize_tool_name,
    sanitize_tools_for_llm,
)

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, cond: bool, detail: str = "") -> None:
    tag = PASS if cond else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, cond))


# ---------------------------------------------------------------------------
# sanitize_tool_name
# ---------------------------------------------------------------------------


def test_sanitize_dot_to_underscore():
    print("\n[1] sanitize_dot_to_underscore")
    check("'clipboard.summarize' → 'clipboard_summarize'",
          sanitize_tool_name("clipboard.summarize") == "clipboard_summarize",
          f"got={sanitize_tool_name('clipboard.summarize')!r}")
    check("'apple_calendar.create_event' → 'apple_calendar_create_event'",
          sanitize_tool_name("apple_calendar.create_event")
              == "apple_calendar_create_event")
    check("'netease.play_song' → 'netease_play_song'",
          sanitize_tool_name("netease.play_song") == "netease_play_song")


def test_sanitize_chinese_to_underscore():
    print("\n[2] sanitize_chinese_to_underscore")
    # '记忆_保存' = 5 chars: 记/忆/_/保/存 → '_/_/_/_/_' (中文 4 个 + 原有 _ 1 个)
    check("'记忆_保存' → '_____'",
          sanitize_tool_name("记忆_保存") == "_____",
          f"got={sanitize_tool_name('记忆_保存')!r}")
    # 'tool_中文' = 7 chars: t/o/o/l/_/中/文 → 'tool___'
    check("'tool_中文' → 'tool___'",
          sanitize_tool_name("tool_中文") == "tool___",
          f"got={sanitize_tool_name('tool_中文')!r}")


def test_sanitize_idempotent():
    print("\n[3] sanitize_idempotent")
    cases = ["save_memory", "switch_character", "tool-name-1",
             "_unnamed", "a", "A_B_2-3"]
    for c in cases:
        check(f"已合规 {c!r} → 不变",
              sanitize_tool_name(c) == c,
              f"got={sanitize_tool_name(c)!r}")
    # 跑两次结果一致
    raw = "weird:tool/name with空格"
    once = sanitize_tool_name(raw)
    twice = sanitize_tool_name(once)
    check("二次 sanitize 等于一次", once == twice,
          f"once={once!r} twice={twice!r}")


def test_sanitize_leading_digit_prefix():
    print("\n[4] sanitize_leading_digit_prefix")
    check("'4o-mini' → '_4o-mini'",
          sanitize_tool_name("4o-mini") == "_4o-mini",
          f"got={sanitize_tool_name('4o-mini')!r}")
    check("'1_thing' → '_1_thing'",
          sanitize_tool_name("1_thing") == "_1_thing")
    check("'9' → '_9'", sanitize_tool_name("9") == "_9")


def test_sanitize_empty_or_invalid_only():
    print("\n[5] sanitize_empty_or_invalid_only")
    check("空串 → '_unnamed'", sanitize_tool_name("") == "_unnamed")
    # 全是非法字符 → 全替换为 _, 不算空串走 _unnamed 分支
    # '...///' = 6 chars (3 dots + 3 slashes) → 6 underscores
    check("'.../...' (all dots/slashes) → 6 个 _",
          sanitize_tool_name("...///") == "______",
          f"got={sanitize_tool_name('...///')!r}")


def test_sanitize_various_special_chars():
    print("\n[6] sanitize_various_special_chars")
    check("colon → _",
          sanitize_tool_name("ns:tool") == "ns_tool")
    check("slash → _",
          sanitize_tool_name("ns/tool") == "ns_tool")
    check("space → _",
          sanitize_tool_name("ns tool") == "ns_tool")
    check("hyphen 保留(合规字符)",
          sanitize_tool_name("ns-tool") == "ns-tool")


# ---------------------------------------------------------------------------
# sanitize_tools_for_llm
# ---------------------------------------------------------------------------


def test_sanitize_tools_reverse_map():
    print("\n[7] sanitize_tools_reverse_map")
    tools = [
        {"type": "function", "function": {"name": "save_memory",
                                          "description": "..."}},
        {"type": "function", "function": {"name": "clipboard.summarize",
                                          "description": "..."}},
        {"type": "function", "function": {"name": "apple_calendar.create_event",
                                          "description": "..."}},
        {"type": "function", "function": {"name": "switch_character",
                                          "description": "..."}},
    ]
    new_tools, rev = sanitize_tools_for_llm(tools)
    check("output length matches", len(new_tools) == 4)
    check("save_memory unchanged (合规 → 不进 reverse_map)",
          new_tools[0]["function"]["name"] == "save_memory"
          and "save_memory" not in rev)
    check("clipboard.summarize → clipboard_summarize",
          new_tools[1]["function"]["name"] == "clipboard_summarize")
    check("reverse_map 含 clipboard_summarize → clipboard.summarize",
          rev.get("clipboard_summarize") == "clipboard.summarize",
          f"got={rev}")
    check("apple_calendar.create_event 同样命中",
          new_tools[2]["function"]["name"] == "apple_calendar_create_event"
          and rev.get("apple_calendar_create_event") == "apple_calendar.create_event")
    check("switch_character 不进 reverse_map",
          "switch_character" not in rev)
    check("reverse_map 只含真正改过的 (2 entries)",
          len(rev) == 2, f"got={list(rev)}")


def test_sanitize_tools_does_not_mutate_input():
    print("\n[8] sanitize_tools_does_not_mutate_input")
    original = [{"type": "function",
                 "function": {"name": "clipboard.summarize",
                              "description": "summarize"}}]
    snapshot_name = original[0]["function"]["name"]
    snapshot_desc = original[0]["function"]["description"]
    _new, _rev = sanitize_tools_for_llm(original)
    check("input list[0].function.name 原值保留",
          original[0]["function"]["name"] == snapshot_name,
          f"input mutated to {original[0]['function']['name']!r}")
    check("description 原值保留",
          original[0]["function"]["description"] == snapshot_desc)


def test_reverse_map_tool_call_resolution():
    """集成场景: LLM emit sanitized name → caller .get(rev, fallback) 拿回原 key
    去查 ToolRegistry。"""
    print("\n[9] reverse_map_tool_call_resolution")
    tools = [
        {"type": "function", "function": {"name": "save_memory"}},
        {"type": "function", "function": {"name": "clipboard.summarize"}},
    ]
    _new, rev = sanitize_tools_for_llm(tools)

    # 模拟 LLM 回 emit
    llm_emitted_1 = "save_memory"            # 合规 name, 不在 reverse_map
    llm_emitted_2 = "clipboard_summarize"    # sanitized, 在 reverse_map

    resolved_1 = rev.get(llm_emitted_1, llm_emitted_1)
    resolved_2 = rev.get(llm_emitted_2, llm_emitted_2)

    check("合规 name 走 .get() fallback 不变",
          resolved_1 == "save_memory")
    check("sanitized name 反查回 'clipboard.summarize'",
          resolved_2 == "clipboard.summarize",
          f"got={resolved_2!r}")


def test_sanitize_tools_empty_list():
    print("\n[10] sanitize_tools_empty_list")
    new_tools, rev = sanitize_tools_for_llm([])
    check("空 list → 空 list + 空 map",
          new_tools == [] and rev == {})


def test_sanitize_tools_missing_function_key():
    """容错: tool dict 缺 'function' 字段不该崩(实际不会出现, 但 layer 保持宽松)。"""
    print("\n[11] sanitize_tools_missing_function_key")
    tools = [{"type": "function"}]
    new_tools, rev = sanitize_tools_for_llm(tools)
    check("缺 function → passthrough 不崩",
          len(new_tools) == 1 and rev == {})


# ---------------------------------------------------------------------------
# Audit-style verification: real capability names should all become sanitized
# ---------------------------------------------------------------------------


def test_real_capability_names_round_trip():
    """Audit 用:列出 Skyler 项目实际 capability name 的 prefix family
    (clipboard.* / apple_calendar.* / netease.* / bilibili.* / media.* /
    character.* / time.* / screen.* / activity.* / calendar.* /
    google_calendar.* / xhs.*) — 每个都该被 sanitize, 反查链通。"""
    print("\n[12] real_capability_names_round_trip")
    real_names = [
        "clipboard.summarize", "clipboard.translate", "clipboard.get_recent",
        "apple_calendar.create_event", "apple_calendar.delete_event",
        "apple_calendar.today_events", "apple_calendar.upcoming_events",
        "netease.daily_recommend", "netease.search", "netease.play_song",
        "netease.local_play_song", "netease.like_current",
        "bilibili.search_video", "bilibili.get_subtitles",
        "bilibili.get_my_history", "media.next_track", "media.now_playing",
        "media.play_pause", "media.set_volume",
        "character.get_state", "character.set_activity",
        "time.now", "screen.get_active_app", "screen.get_browser_url",
        "activity.get_today_summary", "calendar.today_events",
        "google_calendar.today_events", "xhs.parse_url",
    ]
    tools = [{"type": "function", "function": {"name": n}} for n in real_names]
    new_tools, rev = sanitize_tools_for_llm(tools)
    # 所有 sanitized name 必须符合 OpenAI/DeepSeek pattern
    import re
    pat = re.compile(r"^[a-zA-Z0-9_-]+$")
    bad = [t["function"]["name"] for t in new_tools
           if not pat.match(t["function"]["name"])]
    check("all sanitized names match ^[a-zA-Z0-9_-]+$",
          not bad, f"bad={bad}")
    # 每个原 name 都能从 reverse_map 反查
    for orig in real_names:
        san = orig.replace(".", "_")
        check(f"{orig!r} → {san!r} → reverse_map gives back orig",
              rev.get(san) == orig)


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------


def _main():
    test_sanitize_dot_to_underscore()
    test_sanitize_chinese_to_underscore()
    test_sanitize_idempotent()
    test_sanitize_leading_digit_prefix()
    test_sanitize_empty_or_invalid_only()
    test_sanitize_various_special_chars()
    test_sanitize_tools_reverse_map()
    test_sanitize_tools_does_not_mutate_input()
    test_reverse_map_tool_call_resolution()
    test_sanitize_tools_empty_list()
    test_sanitize_tools_missing_function_key()
    test_real_capability_names_round_trip()


if __name__ == "__main__":
    _main()
    passed = sum(1 for _, ok in results if ok)
    failed = len(results) - passed
    print(f"\n=== {passed} passed, {failed} failed ===")
    sys.exit(0 if failed == 0 else 1)
