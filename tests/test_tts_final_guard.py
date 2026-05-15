"""bugfix-D1.1 — ``_tts_input_final_guard`` 兜底字面 ``<ja>``/``<en>`` 漏出。

背景: D1 修了 SUSPICIOUS_TAG_RE 不剥 ``<ja>``/``<en>``;但 stream cancel 截断
或 LLM 输出未闭合 paired tag 时,``extract_tts_text`` fallback (text_filters
.py:323-327) 会把带字面 ``<ja>`` 开标签的 raw_text 原样送 TTS engine →
cosyvoice 收到 ``"\\n<ja>「...`` → 418 InvalidParameter。本 guard 是 TTS
provider 调用前最后一道防线。

文本过滤 unit level,不动 DB / network。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.tts import _tts_input_final_guard, preprocess_tts_text  # noqa: E402

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))


# ---------------------------------------------------------------------------
# 1. _tts_input_final_guard 直接行为契约
# ---------------------------------------------------------------------------


def test_guard_paired_ja_strips_tags():
    print("\n[guard] 配对 <ja>...</ja> → 剥 tag 返 inner")
    out = _tts_input_final_guard("<ja>「日本語」</ja>")
    check("非 None", out is not None)
    check("无 <ja> 残骸", out is not None and "<ja>" not in out)
    check("无 </ja> 残骸", out is not None and "</ja>" not in out)
    check("inner 「日本語」 保留",
          out is not None and "「日本語」" in out)


def test_guard_paired_en_strips_tags():
    print("\n[guard] 配对 <en>...</en> → 剥 tag 返 inner")
    out = _tts_input_final_guard("<en>English text</en>")
    check("非 None", out is not None)
    check("inner 'English text' 保留",
          out is not None and "English text" in out)
    check("无 tag 残骸",
          out is not None and "<en>" not in out and "</en>" not in out)


def test_guard_orphan_open_ja_real_bug_log():
    print("\n[guard] 现场 bug: 截断未闭合 <ja>「あなたは？... (今日 18:53:23 log)")
    inp = '"\n<ja>「あなたは？またコンビニ？胃が悲鳴を上げるわよ。'
    out = _tts_input_final_guard(inp)
    # 实际行为:剥 <ja> 后留下日语正文,不再 418 触发。
    # 上层 `_PreprocessingEngine` 调真实 engine 拿到的就是这段干净文本。
    check("非 None (清洗后仍可用作 ja TTS 输入)", out is not None)
    check("无 <ja> 字面", out is not None and "<ja>" not in out)
    check("日语正文保留",
          out is not None and "あなたは" in out and "コンビニ" in out)
    check("头尾 stray 引号被剥",
          out is not None and not out.startswith('"'))


def test_guard_orphan_close_ja():
    print("\n[guard] 孤立 </ja> 闭标签也剥 (无对应 open)")
    inp = "正文。</ja>"
    out = _tts_input_final_guard(inp)
    check("非 None", out is not None)
    check("</ja> 剥光",
          out is not None and "</ja>" not in out and "/ja" not in out)


def test_guard_plain_chinese_unchanged():
    print("\n[guard] 纯中文正文 → 原样返")
    inp = "学姐，你今天怎么样？"
    out = _tts_input_final_guard(inp)
    check("== 原文", out == inp)


def test_guard_plain_japanese_unchanged():
    print("\n[guard] 纯日语 (无 tag) → 原样返")
    inp = "「日本語」"
    out = _tts_input_final_guard(inp)
    check("== 原文", out == inp)


def test_guard_unknown_tag_rejected():
    print("\n[guard] 剥 ja/en 后仍残留未知 tag → None (其他兜底链漏的兜底)")
    # ja 剥掉后还有 <foo>,说明上游有其他漏网,本 guard 直接拒绝整句
    inp = "<ja>x</ja><foo>"
    out = _tts_input_final_guard(inp)
    check("== None", out is None)


def test_guard_empty_after_strip_rejected():
    print("\n[guard] 剥 + strip 后空 → None (避免空字符串送 TTS)")
    check("仅 <ja></ja> → None",
          _tts_input_final_guard("<ja></ja>") is None)
    check("仅引号 → None",
          _tts_input_final_guard('"\'"') is None)
    check("仅空白 → None",
          _tts_input_final_guard("   \n\t  ") is None)


def test_guard_empty_and_none():
    print("\n[guard] 空 / None 输入 → None")
    check("'' → None", _tts_input_final_guard("") is None)
    check("None → None", _tts_input_final_guard(None) is None)


def test_guard_case_insensitive():
    print("\n[guard] <JA> / <Ja> / <EN> 大小写不敏感剥除")
    check("<JA>X</JA>",
          _tts_input_final_guard("<JA>X</JA>") == "X")
    check("<Ja>X</Ja>",
          _tts_input_final_guard("<Ja>X</Ja>") == "X")
    check("<EN>x</EN>",
          _tts_input_final_guard("<EN>x</EN>") == "x")


# ---------------------------------------------------------------------------
# 2. preprocess_tts_text 集成 —— 链尾 guard 不破坏已有行为
# ---------------------------------------------------------------------------


def test_preprocess_orphan_ja_returns_empty():
    print("\n[integ] preprocess_tts_text 拿 orphan <ja> + 仅引号 → '' (skip synth)")
    # 这是会触发 guard 拒绝的真实形态,主路径应返 "" 走 skip synth 静默降级
    inp = '<ja>"  '
    out = preprocess_tts_text(inp)
    check("== '' (caller skip synth)", out == "")


def test_preprocess_paired_ja_falls_through():
    print("\n[integ] preprocess_tts_text 拿 <ja>inner</ja> → inner 干净送 TTS")
    inp = "<ja>「こんにちは」</ja>"
    out = preprocess_tts_text(inp)
    check("含 inner 「こんにちは」", "「こんにちは」" in out)
    check("无 <ja> 残骸", "<ja>" not in out)


def test_preprocess_plain_text_unchanged():
    print("\n[integ] preprocess_tts_text 纯文本 → 不被 guard 干扰")
    inp = "今天天气真好。"
    out = preprocess_tts_text(inp)
    check("含原文", "今天天气真好。" in out)


def test_preprocess_emotion_tag_still_stripped():
    print("\n[integ] preprocess_tts_text 仍剥 <emotion> 等已知 tag (链上游)")
    inp = "<emotion>happy</emotion>正文"
    out = preprocess_tts_text(inp)
    check("emotion 已剥", "<emotion>" not in out and "happy" not in out)
    check("正文保留", "正文" in out)


def test_preprocess_empty_input():
    print("\n[integ] preprocess_tts_text 空 / None → ''")
    check("'' → ''", preprocess_tts_text("") == "")
    check("None → ''", preprocess_tts_text(None) == "")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main():
    test_guard_paired_ja_strips_tags()
    test_guard_paired_en_strips_tags()
    test_guard_orphan_open_ja_real_bug_log()
    test_guard_orphan_close_ja()
    test_guard_plain_chinese_unchanged()
    test_guard_plain_japanese_unchanged()
    test_guard_unknown_tag_rejected()
    test_guard_empty_after_strip_rejected()
    test_guard_empty_and_none()
    test_guard_case_insensitive()
    test_preprocess_orphan_ja_returns_empty()
    test_preprocess_paired_ja_falls_through()
    test_preprocess_plain_text_unchanged()
    test_preprocess_emotion_tag_still_stripped()
    test_preprocess_empty_input()

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
