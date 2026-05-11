"""v3.5 chunk 9 Part 0.5 — strip_motion 边缘 case + ws.py 入库链覆盖。

audit 发现 ``<motion>`` 是 4 个 Skyler 自有 meta tag 中唯一没在写库链 strip
的（emotion / state_update / thinking 已覆盖），导致：
  * chat_history 入库带字面 ``<motion>害羞</motion>`` 文本
  * hotfix-3 Part 3 SUSPICIOUS_TAG_RE 兜底剥 + 每轮报 [sanitize] warning

本 commit 补完。测试断言：
  * strip_motion 7 个边缘 case（mirror test_strip_emotion）
  * strip_all_for_tts 链覆盖 motion
  * 入库链尾 SUSPICIOUS hit == 0（不再触发 warning）
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.utils.text_filters import (
    count_suspicious_tags,
    strip_all_for_tts,
    strip_emotion,
    strip_motion,
    strip_state_update,
    strip_thinking,
    strip_tool_call_fallback,
)

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))


# ---------------------------------------------------------------------------
# 7 个 strip_motion 边缘 case (与 test_strip_emotion 风格一致)
# ---------------------------------------------------------------------------


def test_single_pair():
    print("\n[1] 单 <motion>X</motion>")
    check("剥后空", strip_motion("<motion>害羞</motion>") == "")
    check("中间内容保留",
          strip_motion("<motion>害羞</motion>正文").strip() == "正文")


def test_multiple_pairs():
    print("\n[2] 多个 <motion> 标签")
    t = "<motion>害羞</motion>段1<motion>低头</motion>段2"
    check("两个都剥", strip_motion(t).strip() == "段1段2")


def test_inner_multiline_content():
    print("\n[3] 多行 / 复杂 inner（[\\s\\S]*? 容许）")
    t = "<motion>多 \n 行 \n 动作</motion>正文"
    check("剥后保留正文", strip_motion(t).strip() == "正文")


def test_self_closing_no_attrs():
    print("\n[4] 自闭合 <motion/> 与 <motion />")
    check("无空格", strip_motion("<motion/>") == "")
    check("带空格", strip_motion("<motion />") == "")
    check("混合正文", strip_motion("前<motion/>后").strip() == "前后")


def test_self_closing_with_attrs():
    print("\n[5] 自闭合带 attrs")
    t = '<motion type="bow" duration="0.5" />'
    check("attrs 自闭合剥", strip_motion(t) == "")


def test_partial_unclosed_left_alone():
    print("\n[6] 非闭合 partial 留下（与 strip_emotion 同语义）")
    t = "<motion 还没完"
    check("partial 不剥", strip_motion(t) == t)


def test_case_insensitive():
    print("\n[7] 大小写不敏感")
    check("upper", strip_motion("<MOTION>X</MOTION>") == "")
    check("mixed", strip_motion("<Motion>X</Motion>") == "")


# ---------------------------------------------------------------------------
# TTS chain 覆盖
# ---------------------------------------------------------------------------


def test_strip_all_for_tts_covers_motion():
    print("\n[chain] strip_all_for_tts 链覆盖 motion（chunk 9 Part 0.5 加入）")
    t = "<emotion>happy</emotion><motion>挥手</motion>你好！"
    check("链尾无 motion / emotion 残骸",
          "<motion" not in strip_all_for_tts(t)
          and "<emotion" not in strip_all_for_tts(t))
    check("保留正文", "你好" in strip_all_for_tts(t))


# ---------------------------------------------------------------------------
# 入库链集成（与 ws.py:_update_memory / _save_interrupted_turn 顺序一致）
# ---------------------------------------------------------------------------


def test_write_chain_no_suspicious_warning():
    print("\n[chain] 入库链 motion 剥后 SUSPICIOUS hit == 0（不再触发 warning）")
    reply = "<emotion>happy</emotion>嘿嘿，被你发现啦~<motion>害羞</motion>"
    cleaned = strip_motion(strip_emotion(
        strip_tool_call_fallback(strip_state_update(strip_thinking(reply)))
    ))
    check("链尾无 <motion>",
          "<motion" not in cleaned and "</motion>" not in cleaned)
    check("链尾无 <emotion>", "<emotion" not in cleaned)
    check("保留正文", "嘿嘿，被你发现啦" in cleaned)
    check("SUSPICIOUS 兜底 hit == 0",
          count_suspicious_tags(cleaned) == 0)


def test_write_chain_full_4_meta_tags():
    print("\n[chain] 4 个 Skyler 自有 meta tag 全合法剥（chunk 9 covered）")
    reply = (
        '<emotion>sad</emotion>'
        '<thinking>嗯...</thinking>'
        '<state_update mood="sad" intimacy_delta="-1" />'
        '正文'
        '<motion>低头</motion>'
    )
    cleaned = strip_motion(strip_emotion(
        strip_tool_call_fallback(strip_state_update(strip_thinking(reply)))
    ))
    check("链尾无 4 meta tag 任何残骸",
          all(t not in cleaned for t in
              ["<emotion", "<thinking", "<state_update", "<motion"]))
    check("正文 OK", cleaned.strip() == "正文")
    check("SUSPICIOUS 兜底 hit == 0",
          count_suspicious_tags(cleaned) == 0)


def test_write_chain_unknown_capability_still_caught_by_suspicious():
    print("\n[chain] 未知 ``<x.y>`` 仍由 SUSPICIOUS 兜底（chunk 9 行为不变）")
    reply = "<netease.daily_recommend></netease.daily_recommend>放好啦"
    cleaned = strip_motion(strip_emotion(
        strip_tool_call_fallback(strip_state_update(strip_thinking(reply)))
    ))
    # tool_call_fallback 中 capability-name-as-tag pattern 已合法剥
    check("capability tag 由 fallback strip 剥",
          "<netease." not in cleaned)


# ---------------------------------------------------------------------------
# Inventory：4 个 Skyler 自有 meta tag 全部 strip 链覆盖（contract 验证）
# ---------------------------------------------------------------------------


def test_all_4_skyler_meta_tags_have_strip_helper():
    print("\n[contract] 4 个 Skyler 自有 meta tag 都有独立 strip helper")
    from backend.utils import text_filters as tf
    check("strip_emotion 存在", hasattr(tf, "strip_emotion"))
    check("strip_thinking 存在", hasattr(tf, "strip_thinking"))
    check("strip_state_update 存在", hasattr(tf, "strip_state_update"))
    check("strip_motion 存在（chunk 9 Part 0.5 加）", hasattr(tf, "strip_motion"))


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main():
    test_single_pair()
    test_multiple_pairs()
    test_inner_multiline_content()
    test_self_closing_no_attrs()
    test_self_closing_with_attrs()
    test_partial_unclosed_left_alone()
    test_case_insensitive()
    test_strip_all_for_tts_covers_motion()
    test_write_chain_no_suspicious_warning()
    test_write_chain_full_4_meta_tags()
    test_write_chain_unknown_capability_still_caught_by_suspicious()
    test_all_4_skyler_meta_tags_have_strip_helper()

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
