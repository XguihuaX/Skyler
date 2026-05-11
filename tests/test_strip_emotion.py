"""v3.5 chunk 6b hotfix-4 — strip_emotion 边缘 case + ws.py 入库链集成。

hotfix-4 把 ``strip_emotion`` 从只服务 TTS preprocessor 扩到入库链
（``_update_memory`` / ``_save_interrupted_turn`` 第二道防线），消 Part 3
SUSPICIOUS_TAG_RE 兜底的 ``[sanitize] suspicious tags`` 每轮 warning。

本文件断言：
  * strip_emotion 7 个边缘 case（单 / 多 / 嵌套 / 中间有内容 / 空闭合 /
    自闭合 / 非闭合 partial）
  * ws.py 入库链集成：``<emotion>`` 在写库前已被合法剥，到 Part 3
    SUSPICIOUS_TAG_RE 时 count == 0（不再触发 warning）
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.utils.text_filters import (
    count_suspicious_tags,
    strip_emotion,
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
# 7 个 strip_emotion 边缘 case
# ---------------------------------------------------------------------------


def test_single_pair():
    print("\n[1] 单 <emotion>X</emotion>")
    check("剥后空", strip_emotion("<emotion>happy</emotion>") == "")
    check("中间内容保留",
          strip_emotion("<emotion>happy</emotion>正文").strip() == "正文")


def test_multiple_pairs():
    print("\n[2] 多个 <emotion> 标签（LLM 乱打多次）")
    t = "<emotion>happy</emotion>段1<emotion>sad</emotion>段2"
    check("两个都剥",
          strip_emotion(t).strip() == "段1段2")


def test_nested_inner_tags():
    print("\n[3] 嵌套内含其他 tag (LLM 偶发把 thinking 嵌进 emotion)")
    t = "<emotion>含<thinking>嵌套</thinking>tag</emotion>"
    out = strip_emotion(t)
    check("配对整段剥", out == "")


def test_inner_multiline_content():
    print("\n[4] 中间含多行 / 标点（[\\s\\S]*? 容许）")
    t = "<emotion>多 \n 行 \n 内容</emotion>正文"
    check("剥后保留正文", strip_emotion(t).strip() == "正文")


def test_self_closing_no_attrs():
    print("\n[5] 自闭合 <emotion/> 与 <emotion />")
    check("无空格", strip_emotion("<emotion/>") == "")
    check("带空格", strip_emotion("<emotion />") == "")
    check("混合正文", strip_emotion("前<emotion/>后").strip() == "前后")


def test_self_closing_with_attrs():
    print("\n[6] 自闭合带 attrs <emotion mood=\"x\" />")
    t = '<emotion mood="happy" intensity="0.8" />'
    check("attrs 自闭合剥", strip_emotion(t) == "")


def test_partial_unclosed_left_alone():
    print("\n[7] 非闭合 partial（``<emotion`` 没 ``>``）不动")
    # 与 strip_state_update 同语义：只剥完整对 / 完整自闭合，未闭合留下
    # 由前端 cosmetic / SUSPICIOUS 兜底处理（避免误删后续内容）
    t = "<emotion 还没完"
    check("partial 不剥", strip_emotion(t) == t)


# ---------------------------------------------------------------------------
# 大小写不敏感（chat.py LLM 偶发大写）
# ---------------------------------------------------------------------------


def test_case_insensitive():
    print("\n[+] 大小写不敏感")
    check("upper", strip_emotion("<EMOTION>X</EMOTION>") == "")
    check("mixed", strip_emotion("<Emotion>X</Emotion>") == "")


# ---------------------------------------------------------------------------
# ws.py 入库链集成：消 SUSPICIOUS 误报
# ---------------------------------------------------------------------------


def test_write_chain_integration_no_suspicious_warning():
    print("\n[chain] _update_memory 入库链 emotion 剥后 SUSPICIOUS hit == 0")
    # 与 ws.py:_update_memory 同顺序：thinking → state_update → tool_call_fallback → emotion
    reply = "<emotion>happy</emotion>今天天气真好！"
    cleaned = strip_emotion(
        strip_tool_call_fallback(strip_state_update(strip_thinking(reply)))
    )
    check("链尾无 <emotion>",
          "<emotion" not in cleaned and "</emotion>" not in cleaned)
    check("保留正文", "今天天气真好" in cleaned)
    check("SUSPICIOUS 兜底 hit == 0（不再触发 warning）",
          count_suspicious_tags(cleaned) == 0)


def test_write_chain_with_state_update_and_emotion():
    print("\n[chain] 联合 <emotion> + <state_update/> 也都被合法剥")
    reply = (
        '<emotion>happy</emotion>'
        '<state_update mood="happy" intimacy_delta="+1"/>'
        '今天聊得开心~'
    )
    cleaned = strip_emotion(
        strip_tool_call_fallback(strip_state_update(strip_thinking(reply)))
    )
    check("链尾无 emotion / state_update 残骸",
          "<emotion" not in cleaned and "<state_update" not in cleaned)
    check("正文 OK", "今天聊得开心" in cleaned)
    check("SUSPICIOUS 不再触发",
          count_suspicious_tags(cleaned) == 0)


def test_write_chain_unknown_capability_still_caught_by_suspicious():
    print("\n[chain] 未知 ``<x.y>`` 仍由 Part 3 SUSPICIOUS 兜底（行为不变）")
    # hotfix-4 不改 SUSPICIOUS_TAG_RE —— capability-name-as-tag 仍命中
    reply = "<netease.daily_recommend></netease.daily_recommend>放好啦"
    cleaned = strip_emotion(
        strip_tool_call_fallback(strip_state_update(strip_thinking(reply)))
    )
    # tool_call_fallback chunk 4 hotfix-1 已含 capability-name-as-tag pattern
    # （hotfix-3 Part 2 加的）—— 这里应已剥
    check("capability tag 由 fallback strip 剥（hotfix-3 行为不变）",
          "<netease." not in cleaned)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main():
    test_single_pair()
    test_multiple_pairs()
    test_nested_inner_tags()
    test_inner_multiline_content()
    test_self_closing_no_attrs()
    test_self_closing_with_attrs()
    test_partial_unclosed_left_alone()
    test_case_insensitive()
    test_write_chain_integration_no_suspicious_warning()
    test_write_chain_with_state_update_and_emotion()
    test_write_chain_unknown_capability_still_caught_by_suspicious()

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
