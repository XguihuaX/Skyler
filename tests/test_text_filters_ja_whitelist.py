"""bugfix-D1 — ``SUSPICIOUS_TAG_RE`` 白名单豁免 ``<ja>`` / ``<en>``。

背景: Mai persona (character_id=1) TTS 走 ``ja`` voice;
早期 LLM 输出 ``中文。<ja>「日语」</ja>`` 完美交替,聊几轮后退化成全中文,
触发 "日语 voice 念中文" 音色错乱。根因: 第 4 道防线持久化前
``SUSPICIOUS_TAG_RE`` 用 ``<\\1>...</\\1>`` 通配匹配**任意 paired tag** →
把 ws.py ``extract_tts_text`` 合法消费的 ``<ja>...</ja>`` 也 strip 了 →
DB 入库全中文 → LLM 看自己 short_term 无 ja 锚点 → round-trip 失锚 →
越聊越漏标。修法: 加白名单 ``frozenset({'ja', 'en'})``,callable replacement
跳过白名单内 tag。

文本过滤 unit level,不动 DB / network。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.utils.text_filters import (  # noqa: E402
    _SUSPICIOUS_TAG_WHITELIST,
    count_suspicious_tags,
    sanitize_suspicious_tags,
)

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))


# ---------------------------------------------------------------------------
# 1. 白名单 sanity
# ---------------------------------------------------------------------------


def test_whitelist_membership():
    print("\n[whitelist] _SUSPICIOUS_TAG_WHITELIST 含 ja + en")
    check("ja in whitelist", "ja" in _SUSPICIOUS_TAG_WHITELIST)
    check("en in whitelist", "en" in _SUSPICIOUS_TAG_WHITELIST)
    check("emotion NOT in whitelist",
          "emotion" not in _SUSPICIOUS_TAG_WHITELIST)
    check("thinking NOT in whitelist",
          "thinking" not in _SUSPICIOUS_TAG_WHITELIST)


# ---------------------------------------------------------------------------
# 2. ja/en 保留 —— D1 修复主目标
# ---------------------------------------------------------------------------


def test_ja_tag_survives_suspicious_strip():
    print("\n[ja survive] 单条 <ja>...</ja> 配对必须保留")
    inp = "中文句。<ja>「日本語」</ja>中文句 2。"
    out = sanitize_suspicious_tags(inp)
    check("含 <ja> 开标签", "<ja>" in out)
    check("含 </ja> 闭标签", "</ja>" in out)
    check("inner 日语保留", "「日本語」" in out)
    check("中文正文保留", "中文句。" in out and "中文句 2。" in out)
    check("count == 0 (白名单不计)", count_suspicious_tags(inp) == 0)


def test_en_tag_survives_suspicious_strip():
    print("\n[en survive] 单条 <en>...</en> 配对必须保留")
    inp = "中文。<en>English</en>"
    out = sanitize_suspicious_tags(inp)
    check("出参 == <en>English</en>", "<en>English</en>" in out)
    check("count == 0 (白名单不计)", count_suspicious_tags(inp) == 0)


def test_ja_multi_occurrence_survives():
    print("\n[ja multi] 多条 <ja>...</ja> 全保留 (segment2-3 merge_short 场景)")
    inp = "嗨。<ja>こんにちは</ja>今天好吗?<ja>元気ですか</ja>"
    out = sanitize_suspicious_tags(inp)
    check("第一个 <ja>こんにちは</ja> 在",
          "<ja>こんにちは</ja>" in out)
    check("第二个 <ja>元気ですか</ja> 在",
          "<ja>元気ですか</ja>" in out)
    check("count == 0", count_suspicious_tags(inp) == 0)


def test_ja_case_insensitive():
    print("\n[ja case] <JA> / <Ja> 大小写不敏感同样保留")
    inp1 = "中文<JA>X</JA>"
    inp2 = "中文<Ja>X</Ja>"
    check("upper-case JA 保留",
          "<JA>X</JA>" in sanitize_suspicious_tags(inp1))
    check("mixed-case Ja 保留",
          "<Ja>X</Ja>" in sanitize_suspicious_tags(inp2))


def test_ja_self_closing_survives():
    print("\n[ja self-close] <ja /> 自闭合也豁免 (走 group(2) 分支)")
    inp = "中文 <ja /> 中文"
    out = sanitize_suspicious_tags(inp)
    # 注:正常 LLM 不会输出 <ja />,但白名单契约应对两分支对称
    check("<ja /> self-close 保留", "<ja" in out and "/>" in out)
    check("count == 0", count_suspicious_tags(inp) == 0)


# ---------------------------------------------------------------------------
# 3. 未知 tag 仍剥 —— 兜底行为不能退化
# ---------------------------------------------------------------------------


def test_unknown_tag_still_stripped():
    print("\n[unknown strip] <foo>bar</foo> 非白名单仍剥")
    inp = "中文<foo>bar</foo>"
    out = sanitize_suspicious_tags(inp)
    check("<foo> 开标签 已剥", "<foo>" not in out)
    check("</foo> 闭标签 已剥", "</foo>" not in out)
    check("inner 'bar' 已剥", "bar" not in out)
    check("中文正文保留", "中文" in out)
    check("count == 1 (未白名单计入)", count_suspicious_tags(inp) == 1)


def test_capability_tag_still_stripped():
    print("\n[unknown strip] capability-name-as-tag 仍剥 (回归保证)")
    inp = '前缀<netease.daily_recommend>{"k":1}</netease.daily_recommend>后缀'
    out = sanitize_suspicious_tags(inp)
    check("netease.* 已剥", "netease.daily_recommend" not in out)
    check("前缀 + 后缀 保留", "前缀" in out and "后缀" in out)


def test_emotion_thinking_still_stripped_via_suspicious():
    print("\n[unknown strip] <emotion> / <thinking> 兜底也仍剥 (双保险)")
    # SUSPICIOUS 是兜底层,主路径由 _strip_emotion / _strip_thinking 处理。
    # 这里 lock 当前行为:即便主路径漏掉,SUSPICIOUS 仍剥 (不在白名单内)。
    inp_e = "X<emotion>happy</emotion>Y"
    inp_t = "X<thinking>independent thought</thinking>Y"
    check("<emotion> 仍剥",
          "<emotion>" not in sanitize_suspicious_tags(inp_e))
    check("<thinking> 仍剥",
          "<thinking>" not in sanitize_suspicious_tags(inp_t))


# ---------------------------------------------------------------------------
# 4. 混合场景 —— ja 保留 + 其他剥除并存
# ---------------------------------------------------------------------------


def test_mixed_ja_and_unknown():
    print("\n[mixed] <ja> 保留 + <foo> 剥除 同句共存")
    inp = "前<ja>日本語</ja>中<foo>x</foo>后"
    out = sanitize_suspicious_tags(inp)
    check("<ja>日本語</ja> 保留", "<ja>日本語</ja>" in out)
    check("<foo>x</foo> 剥光", "foo" not in out and "x</" not in out)
    check("前/中/后 保留", "前" in out and "中" in out and "后" in out)
    # count: 只 <foo> 计入
    check("count == 1 (只 <foo>)", count_suspicious_tags(inp) == 1)


def test_mixed_ja_and_emotion():
    print("\n[mixed] <ja> 保留 + <emotion> 剥除 (实际 Mai 输出形态)")
    inp = "<emotion>happy</emotion>嗨。<ja>こんにちは</ja>"
    out = sanitize_suspicious_tags(inp)
    check("<emotion> 剥光", "<emotion>" not in out and "happy" not in out)
    check("<ja>こんにちは</ja> 保留", "<ja>こんにちは</ja>" in out)


# ---------------------------------------------------------------------------
# 5. 边缘 case —— 空/None/纯文本 不退化
# ---------------------------------------------------------------------------


def test_empty_and_none_unchanged():
    print("\n[edge] 空 / None / 纯文本 不退化")
    check("sanitize('') == ''", sanitize_suspicious_tags("") == "")
    check("sanitize(None) is None", sanitize_suspicious_tags(None) is None)
    check("count('') == 0", count_suspicious_tags("") == 0)
    check("count(None) == 0", count_suspicious_tags(None) == 0)
    plain = "Mai 今天放了一首日推。"
    check("纯文本原样", sanitize_suspicious_tags(plain) == plain)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main():
    test_whitelist_membership()
    test_ja_tag_survives_suspicious_strip()
    test_en_tag_survives_suspicious_strip()
    test_ja_multi_occurrence_survives()
    test_ja_case_insensitive()
    test_ja_self_closing_survives()
    test_unknown_tag_still_stripped()
    test_capability_tag_still_stripped()
    test_emotion_thinking_still_stripped_via_suspicious()
    test_mixed_ja_and_unknown()
    test_mixed_ja_and_emotion()
    test_empty_and_none_unchanged()

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
