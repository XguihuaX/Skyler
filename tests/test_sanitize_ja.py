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
    _has_japanese_kana,
    _extract_corner_bracketed,
    _extract_kana_runs,
    _count_japanese_chars,
    _FISH_TIMEOUT_CAP_CHARS,
    _FISH_KANJI_RATIO_CAP,
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
# Case 4 · ja_path 半闭合 <ja> · v2 hotfix(2026-05-22)
#   v1 行为:半截 <ja> → skip
#   v2 行为(PM 任务 1 v2 spec):半闭合按"无 <ja>"处理 → 走 fallback A/B,
#                                 抽 kana runs + post-cap
# ---------------------------------------------------------------------------
def test_case_4_ja_half_open_v2_fallback():
    print("\n[case 4] hotfix v2 · 半闭合 <ja> → fallback B kana run 抽")
    raw = "嗯。<ja>「うん、まだ書き..."
    out = extract_tts_text(raw, "ja")
    # v2:fallback B regex `[぀-ヿ]+[぀-ヿ一-鿿]*` 抽两段 "うん" + "まだ書き"
    # join → "うんまだ書き"(5 kana + 1 kanji,ratio=1/6≈17% ≤ 30% → send)
    check("v2 半闭合 → fallback B kana run 抽 'うんまだ書き'",
          out == "うんまだ書き",
          detail=f"got {out!r}")
    check("不返含中文字符", "嗯" not in out)


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
# Case A7 · Phase 2 真机 hotfix · ja_path 无 <ja> + sentence 中日切分场景
#   PM 实测日志(13:39:45-51):LLM 输出 "嗯，下午好。「うん、こんにちは。」"
#   chat.py _safe_boundary 按句末 "。" 切句 → 第一句"嗯，下午好。"(纯中文)
#   skip,第二句"「うん、こんにちは。」"(含假名)fallback send。
# ---------------------------------------------------------------------------
def test_case_a7_hotfix_split_sentence_zh_then_ja():
    print("\n[case A7] hotfix · ja_path 无 <ja> · sentence 切分后中文 skip / 日语 send")
    # sentence yield 切分后的第一句:纯中文 + 无 <ja>
    sent_zh = "嗯，下午好。"
    out_zh = extract_tts_text(sent_zh, "ja")
    check("纯中文 sentence skip(return '')", out_zh == "",
          detail=f"got {out_zh!r}")
    # 第二句:纯日语含假名 + 无 <ja>(含 「」)
    # v2 行为:fallback A 「」 抽 inner(drop 「」 wrapper)
    sent_ja = "「うん、こんにちは。」"
    out_ja = extract_tts_text(sent_ja, "ja")
    check("纯日语 sentence v2 fallback A 抽 「」 inner",
          out_ja == "うん、こんにちは。", detail=f"got {out_ja!r}")


# ---------------------------------------------------------------------------
# Case A8 · Phase 2 hotfix · ja_path 无 <ja> + 纯中文 → skip + WARNING
#   原 backward compat 行为(fallback 送原文 → ja voice 念中文音色错乱)反转。
# ---------------------------------------------------------------------------
def test_case_a8_hotfix_ja_path_zh_only_skip():
    print("\n[case A8] hotfix · ja_path 无 <ja> + 纯中文 · skip 不送 ja voice")
    raw = "嗯,去吧。"  # 纯中文 · 无假名 · 无 <ja>
    out = extract_tts_text(raw, "ja")
    check("纯中文 skip(return '')", out == "",
          detail=f"got {out!r} (期望 '' avoid ja voice 念中文)")
    check("不返中文 raw", "嗯" not in out)


# ---------------------------------------------------------------------------
# Case A9 · Phase 2 hotfix · ja_path 无 <ja> + 纯日语含假名 → fallback send
#   LLM 漏 tag 但内容确是日语 → fallback 仍送(保持有 audio 体验)。
# ---------------------------------------------------------------------------
def test_case_a9_hotfix_ja_path_kana_only_fallback_send():
    print("\n[case A9] hotfix · ja_path 无 <ja> + 纯日语含假名 · fallback B regex")
    # v2 行为:fallback B regex 抽连续假名 run,不含句末 "。"(标点 break)
    raw = "おはようございます。"  # 纯日语 · 平假名 · 无 <ja>
    out = extract_tts_text(raw, "ja")
    check("v2 fallback B 抽 kana run(不含 句末。)",
          out == "おはようございます", detail=f"got {out!r}")


def test_case_a9_hotfix_katakana_only():
    print("\n[case A9.1] hotfix · ja_path 无 <ja> + 片假名 · fallback B regex")
    raw = "コンニチハ。"  # 纯片假名
    out = extract_tts_text(raw, "ja")
    check("v2 片假名 fallback B(不含 。)", out == "コンニチハ",
          detail=f"got {out!r}")


def test_case_a9_hotfix_mixed_kana_kanji():
    print("\n[case A9.2] hotfix · ja_path 无 <ja> + 假名+日语汉字 · fallback B")
    # 注:v2 改了 — v1 是直接 fallback 送 raw,v2 是 fallback B regex 抽 kana
    # runs。原 raw "今日は天気がいいですね。" 经 regex `[぀-ヿ]+[぀-ヿ一-鿿]*`
    # 抽:"今" 是 kanji 不能起头;从 "日" 不行;实际从 "は" 起?"は" 是 kana,
    # 但前是 "今日"(kanji)— regex 不要求前导,从 "は" start match:"は天気が"
    # ("は" kana + "天気" kanji + "が" kana 都在 char class)→ extend 到 "ね"
    # 前的 "。" 标点 break。 实际跑后看 verify。
    raw = "今日は天気がいいですね。"
    out = extract_tts_text(raw, "ja")
    # v2: fallback B 抽出 + post-cap kanji ratio check
    # 此 case 主要 verify 不 raise + 不返空(LLM 漏 tag 但内容确是日语)
    check("假名+汉字 不返空(v2 fallback B 抽出 + post-cap pass)",
          out != "", detail=f"got {out!r}")
    check("含假名内容", any(0x3040 <= ord(c) <= 0x30FF for c in out))


# ---------------------------------------------------------------------------
# Case A10-A15 · Phase 2 真机 hotfix v2 · 5 层 fallback 增强
# ---------------------------------------------------------------------------
def test_case_a10_fallback_a_corner_brackets():
    print("\n[case A10] hotfix v2 · Fallback A 「」 corner brackets 抽")
    raw = "我说「こんにちは」吧"
    out = extract_tts_text(raw, "ja")
    check("抽 「」 内日语", out == "こんにちは", detail=f"got {out!r}")
    check("不含句外中文", "我说" not in out and "吧" not in out)


def test_case_a11_fallback_a_katakana_in_brackets():
    print("\n[case A11] hotfix v2 · Fallback A 「」 内片假名书名 · 中文 skip")
    raw = "我读「カラマゾフ」这本书。"
    out = extract_tts_text(raw, "ja")
    check("抽 「」 内片假名", out == "カラマゾフ", detail=f"got {out!r}")
    check("不含中文", "我读" not in out and "这本书" not in out)


def test_case_a12_fallback_b_kana_run():
    print("\n[case A12] hotfix v2 · 无 <ja> 无 「」 · Fallback B regex 抽假名 run")
    raw = "我说こんにちは你好"
    out = extract_tts_text(raw, "ja")
    # regex 从 "こ" 起头 1+ kana,greedy 接续 kana/kanji * 至 EOS:
    # "こんにちは你好" (5 kana + 2 kanji,ratio=2/7≈28.6% ≤ 30%) → send
    check("Fallback B 抽 kana-starting run", out == "こんにちは你好",
          detail=f"got {out!r}")


def test_case_a13_half_open_ja_with_corner():
    print("\n[case A13] hotfix v2 · 半闭合 <ja> + 「」 · 走 Fallback A")
    raw = "嗯。<ja>「うん」"  # <ja> 半闭合,「」 完整
    out = extract_tts_text(raw, "ja")
    # main path matches=[];fallback A 「うん」 → send
    check("半闭合 <ja> + 「」 → Fallback A 抽 「」 内",
          out == "うん", detail=f"got {out!r}")


def test_case_a14_post_cap_length():
    print("\n[case A14] hotfix v2 · Post-cap A · 抽出 > 200 chars → skip")
    long_ja = "おはようございます。" * 25  # ~10 chars × 25 = 250 chars
    out = extract_tts_text(long_ja, "ja")
    check(f"抽出 > {_FISH_TIMEOUT_CAP_CHARS} → skip (return '')",
          out == "",
          detail=f"got {out!r}(len input ~{len(long_ja)})")


def test_case_a15_post_cap_kanji_ratio():
    print("\n[case A15] hotfix v2 · Post-cap B · kanji ratio > 30% → skip")
    # 5 kana + 9 kanji = 14 chars,ratio = 9/14 ≈ 64% > 30%
    raw = "我说こんにちは但是你好朋友哥哥姐姐"
    out = extract_tts_text(raw, "ja")
    check(f"kanji ratio > {_FISH_KANJI_RATIO_CAP*100}% → skip (return '')",
          out == "",
          detail=f"got {out!r}")


# ---------------------------------------------------------------------------
# Helper · _extract_corner_bracketed / _extract_kana_runs / _count_japanese_chars
# ---------------------------------------------------------------------------
def test_helper_extract_corner_brackets():
    print("\n[helper] _extract_corner_bracketed 行为锁")
    check("单 「」", _extract_corner_bracketed("我说「こんにちは」") == ["こんにちは"])
    check("多 「」", _extract_corner_bracketed("「a」b「c」") == ["a", "c"])
    check("无 「」", _extract_corner_bracketed("我说こんにちは") == [])
    check("半闭合 「(无 」)", _extract_corner_bracketed("「うん、まだ") == [])
    check("空 「」 跳过", _extract_corner_bracketed("「」「a」") == ["a"])
    check("空 / None", _extract_corner_bracketed("") == []
          and _extract_corner_bracketed(None) == [])


def test_helper_extract_kana_runs():
    print("\n[helper] _extract_kana_runs 行为锁")
    check("纯日语", _extract_kana_runs("こんにちは") == ["こんにちは"])
    check("中日混 · kana-starting run greedy",
          _extract_kana_runs("我说こんにちは你好") == ["こんにちは你好"])
    check("punct break · 「」 内", _extract_kana_runs("「うん、まだ書き") ==
          ["うん", "まだ書き"])
    check("纯中文(无 kana-starting)→ []",
          _extract_kana_runs("我说你好") == [])
    check("纯 ASCII → []", _extract_kana_runs("hello world") == [])


def test_helper_count_japanese_chars():
    print("\n[helper] _count_japanese_chars 行为锁")
    check("纯平假名", _count_japanese_chars("こんにちは") == (0, 5))
    check("纯 kanji(中日共享)", _count_japanese_chars("我说你好") == (4, 0))
    check("混合", _count_japanese_chars("こんにちは你好") == (2, 5))
    check("空 / None",
          _count_japanese_chars("") == (0, 0)
          and _count_japanese_chars(None) == (0, 0))
    check("含标点 / ASCII 不计", _count_japanese_chars("Hi! 你, こ。") == (1, 1))


# ---------------------------------------------------------------------------
# Helper · _has_japanese_kana 行为锁
# ---------------------------------------------------------------------------
def test_helper_kana_detection():
    print("\n[helper] _has_japanese_kana 行为锁")
    check("平假名 → True", _has_japanese_kana("おはよう") is True)
    check("片假名 → True", _has_japanese_kana("コンニチハ") is True)
    check("半角片假名 → True", _has_japanese_kana("ハロー") is True)
    check("中日混排(含假名)→ True",
          _has_japanese_kana("我说こんにちは") is True)
    check("纯中文 → False", _has_japanese_kana("嗯,去吧。") is False)
    check("纯 ASCII → False", _has_japanese_kana("hello world") is False)
    check("空字符串 → False", _has_japanese_kana("") is False)
    check("None → False", _has_japanese_kana(None) is False)
    check("纯日语汉字(無假名)→ False(共享字符,Unicode 不判 ja)",
          _has_japanese_kana("中国人") is False)


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
    test_case_4_ja_half_open_v2_fallback()
    test_case_5_zh_strip_ja_block()
    test_case_5b_zh_strip_en_block()
    test_case_6_zh_half_open_skip()
    test_case_a7_hotfix_split_sentence_zh_then_ja()
    test_case_a8_hotfix_ja_path_zh_only_skip()
    test_case_a9_hotfix_ja_path_kana_only_fallback_send()
    test_case_a9_hotfix_katakana_only()
    test_case_a9_hotfix_mixed_kana_kanji()
    test_case_a10_fallback_a_corner_brackets()
    test_case_a11_fallback_a_katakana_in_brackets()
    test_case_a12_fallback_b_kana_run()
    test_case_a13_half_open_ja_with_corner()
    test_case_a14_post_cap_length()
    test_case_a15_post_cap_kanji_ratio()
    test_helper_extract_corner_brackets()
    test_helper_extract_kana_runs()
    test_helper_count_japanese_chars()
    test_helper_kana_detection()
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
