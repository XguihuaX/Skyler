"""INV-9 §1 · sanitize A1 fix · extract_tts_text 6 case unit test。

per INV-8 §1.5.2 sanitize bug audit verdict + INV-8 §1.收口.6 Q1 lock:
  - PM bug #1 "中日语一起全给 TTS" — 半截 <ja> fallback skip(NEW)
  - PM bug #2 "切 zh voice 仍带日语" — zh 路径剥 <ja>/<en> 整段(NEW)

backward compat 保证:
  - ja_path 真无 tag(LLM 漏标整段)— 原 fallback 行为不动(降级送原文)
  - ja_path 单 / 多 / 跟其它 meta tag 混排理想 case — 完美抽取(回归保证)
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.utils.text_filters import (  # noqa: E402
    extract_tts_text,
    _has_unclosed_ja_en_tag,
)

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))


# ---------------------------------------------------------------------------
# Case 1 · ja_path A1 · 单一 <ja> 块(回归保证 — 理想 case 不退化)
# ---------------------------------------------------------------------------
def test_case_1_ja_single_block():
    print("\n[case 1] ja_path · 单 <ja> 块 · 回归保证")
    raw = "嗯,去吧。<ja>「うん、行きなさい。」</ja>"
    out = extract_tts_text(raw, "ja")
    check("纯日语提取", out == "「うん、行きなさい。」",
          detail=f"got {out!r}")
    check("不含中文", "嗯" not in out and "去吧" not in out)
    check("不含字面 <ja>", "<ja>" not in out and "</ja>" not in out)


# ---------------------------------------------------------------------------
# Case 2 · ja_path A2 · 多 <ja> 穿插(回归保证 — bugfix-segment2-3 .findall)
# ---------------------------------------------------------------------------
def test_case_2_ja_multi_blocks():
    print("\n[case 2] ja_path · 多 <ja> 穿插 · 回归保证 (bugfix-segment2-3)")
    raw = (
        '嗯,去吧。<ja>「うん、行きなさい。」</ja>'
        '专心看完。<ja>「ゆっくり読んで。」</ja>'
    )
    out = extract_tts_text(raw, "ja")
    check("两段日语顺序拼接",
          out == "「うん、行きなさい。」「ゆっくり読んで。」",
          detail=f"got {out!r}")
    check("不含中文", "嗯" not in out and "专心" not in out)


# ---------------------------------------------------------------------------
# Case 3 · ja_path A4 · 跟 emotion/state_update/motion/thinking 混排
#   (回归保证 — sanitize chain 各 strip 函数协作)
# ---------------------------------------------------------------------------
def test_case_3_ja_with_other_meta_tags():
    print("\n[case 3] ja_path · 跟 emotion/state_update/motion/thinking 混排 · 回归")
    raw = (
        "<thinking>内部思考</thinking>"
        "<emotion>happy</emotion>"
        "开心。<ja>「嬉しいね。」</ja>"
        "<state_update mood=+2 />"
        "<motion>nod</motion>"
    )
    out = extract_tts_text(raw, "ja")
    check("纯日语提取", out == "「嬉しいね。」", detail=f"got {out!r}")
    check("无 thinking 泄漏", "思考" not in out)
    check("无 emotion 泄漏", "happy" not in out)
    check("无 state_update 泄漏", "mood" not in out)
    check("无 motion 泄漏", "nod" not in out)


# ---------------------------------------------------------------------------
# Case 4 · ja_path A5 · 半截 <ja> 未闭合 → return "" skip synth (NEW fix · PM bug #1)
# ---------------------------------------------------------------------------
def test_case_4_ja_half_open_skip():
    print("\n[case 4] ja_path · 半截 <ja> 未闭合 · NEW fix (PM bug #1)")
    raw = "嗯。<ja>「うん、まだ書き..."
    out = extract_tts_text(raw, "ja")
    check("半截 <ja> → return ''", out == "",
          detail=f"got {out!r} (期望 '' skip synth,避免中日混送)")
    # 关键 invariant:不返中文 + 半截日语混合
    check("不返含中文 raw", "嗯" not in out)
    check("不返半截日语", "書き" not in out)


# ---------------------------------------------------------------------------
# Case 5 · zh_path B1 · 切 zh + 含 <ja> → 剥 <ja> 整段 (NEW fix · PM bug #2)
# ---------------------------------------------------------------------------
def test_case_5_zh_strip_ja_block():
    print("\n[case 5] zh_path · 切 zh 含 <ja> · NEW fix (PM bug #2)")
    raw = "嗯,去吧。<ja>「うん、行きなさい。」</ja>"
    out = extract_tts_text(raw, "zh")
    check("仅中文",
          out == "嗯,去吧。",
          detail=f"got {out!r}")
    check("不含字面 <ja>", "<ja>" not in out and "</ja>" not in out)
    check("不含日语内容",
          "うん" not in out and "行きなさい" not in out and "「" not in out)


def test_case_5b_zh_strip_en_block():
    print("\n[case 5b] zh_path · 切 zh 含 <en> · NEW fix 对称")
    raw = "早上好。<en>Morning.</en>"
    out = extract_tts_text(raw, "zh")
    check("仅中文",
          out == "早上好。",
          detail=f"got {out!r}")
    check("不含字面 <en>", "<en>" not in out and "</en>" not in out)
    check("不含 English 内容", "Morning" not in out)


# ---------------------------------------------------------------------------
# Case 6 · zh_path · 切 zh + 半截 <ja> → return "" skip synth (NEW fix bonus)
# ---------------------------------------------------------------------------
def test_case_6_zh_half_open_skip():
    print("\n[case 6] zh_path · 切 zh 半截 <ja> · NEW fix bonus")
    raw = "嗯。<ja>「うん、まだ書き..."
    out = extract_tts_text(raw, "zh")
    check("半截残留 → return ''", out == "",
          detail=f"got {out!r} (期望 '' skip synth)")
    check("不含中文 raw", "嗯" not in out)


# ---------------------------------------------------------------------------
# Backward compat · ja_path 真无 tag(LLM 漏标整段)→ fallback 原行为保留
# ---------------------------------------------------------------------------
def test_backward_compat_ja_no_tag_fallback():
    print("\n[backward compat] ja_path · 真无 <ja> tag(LLM 漏标整段)· fallback")
    raw = "嗯,去吧。"  # 无 <ja> 字面
    out = extract_tts_text(raw, "ja")
    # 原行为:fallback strip_all_for_tts(raw) → 送原中文(日语 voice 会念中文,
    # 降级体验但不崩链);此 case 不进 NEW skip 分支(因无字面 <ja>)
    check("fallback 送原文(降级)", out == "嗯,去吧。",
          detail=f"got {out!r}")


# ---------------------------------------------------------------------------
# Empty / None / 默认值
# ---------------------------------------------------------------------------
def test_edge_empty():
    print("\n[edge] 空 / None / 默认 lang")
    check("extract('', 'ja') == ''", extract_tts_text("", "ja") == "")
    check("extract(None, 'ja') == ''", extract_tts_text(None, "ja") == "")
    check("extract('hi', '') == strip_all('hi')",
          extract_tts_text("你好。", "") == "你好。")
    check("extract('hi', None) == strip_all('hi')",
          extract_tts_text("你好。", None) == "你好。")


# ---------------------------------------------------------------------------
# Helper · _has_unclosed_ja_en_tag 行为锁
# ---------------------------------------------------------------------------
def test_helper_unclosed_detection():
    print("\n[helper] _has_unclosed_ja_en_tag 行为锁")
    check("完整闭合 → False",
          _has_unclosed_ja_en_tag("嗯。<ja>こんにちは</ja>") is False)
    check("半截 <ja → True",
          _has_unclosed_ja_en_tag("嗯。<ja>「うん...") is True)
    check("半截 </ja → True(罕见 stream cancel)",
          _has_unclosed_ja_en_tag("...こんにちは</ja>") is True)
    check("纯中文无 tag → False",
          _has_unclosed_ja_en_tag("嗯。") is False)
    check("空 → False",
          _has_unclosed_ja_en_tag("") is False)
    check("半截 <en → True",
          _has_unclosed_ja_en_tag("Hi. <en>Morning...") is True)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main():
    test_case_1_ja_single_block()
    test_case_2_ja_multi_blocks()
    test_case_3_ja_with_other_meta_tags()
    test_case_4_ja_half_open_skip()
    test_case_5_zh_strip_ja_block()
    test_case_5b_zh_strip_en_block()
    test_case_6_zh_half_open_skip()
    test_backward_compat_ja_no_tag_fallback()
    test_edge_empty()
    test_helper_unclosed_detection()

    total = len(results)
    passed = sum(1 for _, ok in results if ok)
    print(f"\n{'='*60}")
    print(f"Results: {passed}/{total} passed")
    if passed < total:
        print("FAILED:", ", ".join(n for n, ok in results if not ok))
        sys.exit(1)
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
