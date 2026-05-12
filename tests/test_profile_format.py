"""v3.5 chunk 11 — format_profile_for_prompt 机械模板化 + chat.py 注入。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.services.profile_regen import format_profile_for_prompt
from backend.utils.profile_schema import empty_profile

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))


# ---------------------------------------------------------------------------
# 1. 边界情况
# ---------------------------------------------------------------------------


def test_none_returns_empty_string():
    print("\n[edge] None / 非 dict → ''")
    check("None", format_profile_for_prompt(None) == "")
    check("空 dict", format_profile_for_prompt({}) == "")
    check("非 dict（list）", format_profile_for_prompt([]) == "")  # type: ignore[arg-type]


def test_all_empty_fields_returns_empty():
    print("\n[edge] 全 None / 空 list → ''")
    ep = empty_profile()
    check("empty_profile → ''", format_profile_for_prompt(ep) == "")


# ---------------------------------------------------------------------------
# 2. 全字段
# ---------------------------------------------------------------------------


def test_all_fields_full_output():
    print("\n[happy] 7 字段全填 → 含全 7 行 + 已知用户：标题")
    p = {
        "profession": "程序员",
        "current_projects": ["Skyler v3.5"],
        "communication_style": "直接、紧凑",
        "interests": ["LLM 工程", "音乐"],
        "language_preferences": "中文",
        "active_hours": "深夜",
        "recurring_topics": ["调 bug", "Live2D"],
    }
    out = format_profile_for_prompt(p)
    check("含 '已知用户：'", "已知用户：" in out)
    check("职业 行", "- 职业：程序员" in out)
    check("当前项目 行 + 逗号 join", "- 当前项目：Skyler v3.5" in out)
    check("沟通风格 行", "- 沟通风格：直接、紧凑" in out)
    check("长期兴趣 逗号 join", "- 长期兴趣：LLM 工程, 音乐" in out)
    check("语言偏好 行", "- 语言偏好：中文" in out)
    check("活跃时段 行", "- 活跃时段：深夜" in out)
    check("反复出现的话题 行",
          "- 反复出现的话题：调 bug, Live2D" in out)


# ---------------------------------------------------------------------------
# 3. 字段缺失组合
# ---------------------------------------------------------------------------


def test_partial_fields_skip_empty():
    print("\n[partial] 只填 profession → 只有 1 行 + 标题")
    p = {
        "profession": "工程师",
        "current_projects": [],
        "communication_style": None,
        "interests": [],
        "language_preferences": None,
        "active_hours": None,
        "recurring_topics": [],
    }
    out = format_profile_for_prompt(p)
    lines = out.splitlines()
    check("标题 + 1 字段 = 2 行", len(lines) == 2)
    check("职业行存在", "- 职业：工程师" in out)
    check("其他字段不打印（空 list / None 都跳过）",
          "- 当前项目" not in out and "- 沟通风格" not in out)


def test_only_list_fields_partial_filtering():
    print("\n[partial] list 含 None / 空 string → 过滤后剥")
    p = {
        "profession": None,
        "current_projects": ["", None, "  ", "Skyler"],  # type: ignore[list-item]
        "communication_style": None,
        "interests": [],
        "language_preferences": None,
        "active_hours": None,
        "recurring_topics": [],
    }
    out = format_profile_for_prompt(p)
    check("只剩 Skyler",
          "- 当前项目：Skyler" in out
          and "  " not in out.split("当前项目：")[1].split("\n")[0])


def test_string_whitespace_skipped():
    print("\n[partial] string 空白 → 跳过")
    p = {
        "profession": "   ",
        "current_projects": [],
        "communication_style": "x",
        "interests": [], "language_preferences": None,
        "active_hours": None, "recurring_topics": [],
    }
    out = format_profile_for_prompt(p)
    check("空白 profession 不打印", "- 职业：" not in out)
    check("communication_style 仍打印", "- 沟通风格：x" in out)


# ---------------------------------------------------------------------------
# 4. chat.py 注入 contract
# ---------------------------------------------------------------------------


def test_chat_py_uses_format_profile_for_prompt():
    print("\n[chat.py] _build_messages 注入用 format_profile_for_prompt + legacy fallback")
    import backend.agents.chat as chat_mod
    src = open(chat_mod.__file__, "r", encoding="utf-8").read()
    check("import format_profile_for_prompt",
          "format_profile_for_prompt" in src)
    check("import get_profile_data",
          "get_profile_data" in src and "from backend.services.profile_regen" in src)
    check("legacy fallback：profile_summary 仍 import",
          "get_profile_summary" in src)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main():
    test_none_returns_empty_string()
    test_all_empty_fields_returns_empty()
    test_all_fields_full_output()
    test_partial_fields_skip_empty()
    test_only_list_fields_partial_filtering()
    test_string_whitespace_skipped()
    test_chat_py_uses_format_profile_for_prompt()

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
