"""v3.5 chunk 6b hotfix-3 — SUSPICIOUS_TAG_RE 边缘 case + count + sanitize。

文本过滤 unit level，不动 DB / network。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.utils.text_filters import (
    SUSPICIOUS_TAG_RE,
    count_suspicious_tags,
    has_partial_open_tag,
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
# 1. positives：必须命中
# ---------------------------------------------------------------------------


def test_capability_tag_paired_empty():
    print("\n[positive] capability-name-as-tag 配对空内容")
    t = "<netease.daily_recommend></netease.daily_recommend>"
    check("count == 1", count_suspicious_tags(t) == 1)
    check("sanitize empty", sanitize_suspicious_tags(t) == "")


def test_capability_tag_self_closed():
    print("\n[positive] capability-name-as-tag 自闭合")
    t = "<netease.daily_recommend />"
    check("count == 1", count_suspicious_tags(t) == 1)
    check("sanitize empty", sanitize_suspicious_tags(t) == "")


def test_capability_tag_with_inner_json():
    print("\n[positive] capability-name-as-tag 带 JSON inner")
    t = '前缀<netease.daily_recommend>{"keyword":"a"}</netease.daily_recommend>后缀'
    check("count == 1", count_suspicious_tags(t) == 1)
    check("inner + tags 都剥",
          sanitize_suspicious_tags(t).strip() == "前缀后缀")


def test_multiple_suspicious_tags():
    print("\n[positive] 多 tag 累计 >= threshold")
    t = ("<a.b></a.b>"
         "<emotion>开心</emotion>"
         "<thinking>x</thinking>"
         "<c.d/>")
    check("count == 4 (>= profile NULL 阈值 3)",
          count_suspicious_tags(t) == 4)


def test_self_closed_with_attrs():
    print("\n[positive] self-close with attrs 也命中")
    t = '<state_update mood="happy" intimacy_delta="0.1" />'
    n = count_suspicious_tags(t)
    check("count >= 1", n >= 1)
    check("sanitize 空", sanitize_suspicious_tags(t).strip() == "")


# ---------------------------------------------------------------------------
# 2. negatives：必须不命中
# ---------------------------------------------------------------------------


def test_emoticon_lt3():
    print("\n[negative] ``<3`` emoticon 不算 tag")
    t = "我爱你 <3"
    check("count == 0", count_suspicious_tags(t) == 0)
    check("sanitize 原样", sanitize_suspicious_tags(t) == t)


def test_le_operator():
    print("\n[negative] ``<=`` 运算符不算 tag")
    t = "x <= 10"
    check("count == 0", count_suspicious_tags(t) == 0)


def test_mismatched_open_close():
    print("\n[negative] 开闭 tag 不同名 不算配对（\\1 反向引用）")
    t = "<a.b>x</c.d>"
    check("count == 0", count_suspicious_tags(t) == 0)


def test_plain_prose():
    print("\n[negative] 纯文本")
    t = "Momo 今天放了一首日推，叫《夜空中最亮的星》。"
    check("count == 0", count_suspicious_tags(t) == 0)


def test_empty_and_none():
    print("\n[negative] 空 / None")
    check("count('') == 0", count_suspicious_tags("") == 0)
    check("count(None) == 0", count_suspicious_tags(None) == 0)
    check("sanitize('') == ''", sanitize_suspicious_tags("") == "")
    check("sanitize(None) == None", sanitize_suspicious_tags(None) is None)


# ---------------------------------------------------------------------------
# 3. partial-open 检测互动（hotfix-3 Part 2 加的）
# ---------------------------------------------------------------------------


def test_has_partial_open_capability_tag():
    print("\n[partial] capability-name 开标签未闭合 → True")
    check("open only no >", has_partial_open_tag("<netease.daily_recommend"))
    check("open block未闭合",
          has_partial_open_tag('<netease.daily_recommend>{"k":1}'))


def test_has_partial_open_capability_complete():
    print("\n[partial] capability-name 完整闭合 → False")
    check("paired",
          not has_partial_open_tag(
              "<netease.daily_recommend></netease.daily_recommend>"))
    check("self closed",
          not has_partial_open_tag("<netease.daily_recommend />"))
    check("self closed nospace",
          not has_partial_open_tag("<netease.daily_recommend/>"))


def test_has_partial_open_plain_html_not_capability():
    print("\n[partial] 普通 HTML 不算 capability tag（没 dot）")
    # 注意：``has_partial_open_tag`` 仍可能返 True 因为 thinking / tool_call
    # 一类有自己的 open block 表；这里只测：``<div>`` 完整闭合时不触发
    check("div paired closed",
          not has_partial_open_tag("<div>hi</div>"))


# ---------------------------------------------------------------------------
# 4. backref \1 防 cross-tag 错配
# ---------------------------------------------------------------------------


def test_nested_same_name():
    print("\n[edge] 同名嵌套（非贪婪 + DOTALL，外层残留 orphan close 可接受）")
    t = "<a.b>outer<a.b>inner</a.b>tail</a.b>"
    # 非贪婪 + 反向引用：第一遍只剥内层 ``<a.b>inner</a.b>`` + 它前导，
    # 剩 ``tail</a.b>``（orphan close）。两遍后**开标签**确认剥光。
    out2 = sanitize_suspicious_tags(sanitize_suspicious_tags(t))
    check("无 <a.b 开标签残骸", "<a.b>" not in out2 and "<a.b " not in out2)
    # 实际 LLM 极少嵌套同名 tag；残留 orphan close 是已知边界、属于可接受
    # 残骸（前端渲染层会再过一道正则做 cosmetic 兜底）。


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main():
    test_capability_tag_paired_empty()
    test_capability_tag_self_closed()
    test_capability_tag_with_inner_json()
    test_multiple_suspicious_tags()
    test_self_closed_with_attrs()
    test_emoticon_lt3()
    test_le_operator()
    test_mismatched_open_close()
    test_plain_prose()
    test_empty_and_none()
    test_has_partial_open_capability_tag()
    test_has_partial_open_capability_complete()
    test_has_partial_open_plain_html_not_capability()
    test_nested_same_name()

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
