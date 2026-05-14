"""Bugfix-1 — LLM hallucinated tag 泄露 + TTS 误读修复 unit tests。

覆盖：
  * 新加 ``<docx.create(args)>`` 函数调用风格 regex（_TOOL_CALL_FALLBACK_STRIP_PATTERNS 第 6 条）
  * ``sanitize_llm_output`` 全套入口（code-block-aware）

文本过滤 unit 层，不动 DB / network。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.utils.text_filters import (
    sanitize_llm_output,
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
# 1. positives：新 regex 必须命中真实泄露 case
# ---------------------------------------------------------------------------


def test_strip_state_update_tag():
    """``<state_update ... />`` 自闭合保留行为（_STATE_UPDATE_RE 已有，回归保护）。"""
    print("\n[positive] state_update 自闭合")
    t = '<state_update mood="calm" thought="..." />tail'
    out = sanitize_llm_output(t)
    check("state_update 剥干净", out == "tail", f"got={out!r}")


def test_strip_self_closing():
    """通用 self-closing 兜底（SUSPICIOUS）。"""
    print("\n[positive] self-closing unknown tag")
    t = "<unknown_tag attr='x' />after"
    out = sanitize_llm_output(t)
    check("unknown self-close 剥干净", out == "after", f"got={out!r}")


def test_strip_docx_create_func_style():
    """**核心 bug case**：``<docx.create(filename=..., paragraphs=[...])>``。"""
    print("\n[positive] 函数调用风格 <docx.create(...)>")
    t = '<docx.create(filename="MomoOS_测试漏洞记录", title="MomoOS 测试漏洞记录", paragraphs=[1,2,3])>tail'
    out = strip_tool_call_fallback(t)
    check("strip_tool_call_fallback 剥干净", out == "tail", f"got={out!r}")
    out2 = sanitize_llm_output(t)
    check("sanitize_llm_output 剥干净", out2 == "tail", f"got={out2!r}")


def test_strip_func_style_no_args():
    """``<docx.create()>`` 空 args 也要剥。"""
    print("\n[positive] 函数调用风格空 args")
    t = "<docx.create()>x"
    out = strip_tool_call_fallback(t)
    check("空 args 剥干净", out == "x", f"got={out!r}")


def test_strip_combined_leak():
    """用户真机看到的完整泄露 sample（state_update + docx.create 混合）。"""
    print("\n[positive] 用户真机泄露样本")
    t = (
        "✨(主动陪伴)\n"
        '<state_update mood="calm" thought="用户触发了信号" />\n'
        '<docx.create(filename="MomoOS_测试漏洞记录", title="MomoOS 测试漏洞记录", paragraphs=[1,2,3])>\n'
        "我帮你存好了。"
    )
    out = sanitize_llm_output(t)
    check(
        "剥后含正文",
        "我帮你存好了。" in out,
        f"got={out!r}",
    )
    check(
        "剥后无 state_update",
        "state_update" not in out,
        f"got={out!r}",
    )
    check(
        "剥后无 docx.create",
        "docx.create" not in out,
        f"got={out!r}",
    )


# ---------------------------------------------------------------------------
# 2. 保留：inline code / fenced code 内的合法引用不剥
# ---------------------------------------------------------------------------


def test_preserve_inline_code_in_backticks():
    """`` `<thinking>` `` 是用户在引用 tag 名，不能剥。"""
    print("\n[preserve] inline code 内的 tag 名")
    t = "Use `<thinking>` for internal thoughts, like `<state_update mood=\"x\" />`."
    out = sanitize_llm_output(t)
    check("`<thinking>` 保留", "`<thinking>`" in out, f"got={out!r}")
    check(
        "`<state_update ... />` 保留",
        '`<state_update mood="x" />`' in out,
        f"got={out!r}",
    )


def test_preserve_fenced_code():
    """fenced ``` 内整段不动（教学/文档示例）。"""
    print("\n[preserve] fenced code block 内的 tag")
    t = (
        "示例输出：\n"
        "```xml\n"
        "<emotion>happy</emotion>\n"
        "<docx.create(filename=\"x\")>\n"
        "```\n"
        "就像这样用。"
    )
    out = sanitize_llm_output(t)
    check("fenced 内 emotion 保留", "<emotion>happy</emotion>" in out, f"got={out!r}")
    check(
        "fenced 内 docx.create 保留",
        '<docx.create(filename="x")>' in out,
        f"got={out!r}",
    )
    check("fenced 外正文保留", "就像这样用。" in out, f"got={out!r}")


def test_preserve_normal_text():
    """普通中文 / 英文 / 标点 / emoji 0 修改。"""
    print("\n[preserve] 普通文本零修改")
    cases = [
        "今天天气真好，我们去散步吧 ☀️",
        "Hello world! This is a normal sentence.",
        "Math: 2 < 3 and 5 > 4.",
        "心情：开心 ❤️",
        "",
    ]
    for c in cases:
        out = sanitize_llm_output(c)
        check(f"text 不变 ({c[:30]!r})", out == c, f"got={out!r}")


# ---------------------------------------------------------------------------
# 3. negatives：不能误伤 HTML attrs（name 后必须紧跟 ``(``）
# ---------------------------------------------------------------------------


def test_html_attrs_not_eaten_by_func_call_regex():
    """``<a href="x">`` ``<img src="y" />`` 不应被 func-call regex 误判。

    注意：``sanitize_suspicious_tags``（SUSPICIOUS_TAG_RE）是白名单否定，会剥
    所有 ``<name>...</name>`` —— 这是设计行为（assistant 回复正常文本不该出
    现 HTML）。本测试用 ``strip_tool_call_fallback`` 单独验证新 regex 不误伤。
    """
    print("\n[negative] HTML attrs 不被 func-call regex 误剥")
    for t in ['<a href="x">link</a>', '<img src="y" />', "<div class='c'>x</div>"]:
        out = strip_tool_call_fallback(t)
        check(f"HTML 不变 ({t!r})", out == t, f"got={out!r}")


def test_func_call_with_nested_brackets():
    """``<func(arr=[1,2,3])>`` 含 ``[...]`` nested 也要剥。"""
    print("\n[positive] 函数调用 args 含 [...] nested")
    t = "<docx.create(items=[1,2,3], opts={\"k\": \"v\"})>after"
    out = strip_tool_call_fallback(t)
    check("nested args 剥干净", out == "after", f"got={out!r}")


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------


def main() -> int:
    test_strip_state_update_tag()
    test_strip_self_closing()
    test_strip_docx_create_func_style()
    test_strip_func_style_no_args()
    test_strip_combined_leak()
    test_preserve_inline_code_in_backticks()
    test_preserve_fenced_code()
    test_preserve_normal_text()
    test_html_attrs_not_eaten_by_func_call_regex()
    test_func_call_with_nested_brackets()

    passed = sum(1 for _, ok in results if ok)
    failed = len(results) - passed
    print(f"\n=== {passed} passed, {failed} failed ===")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
