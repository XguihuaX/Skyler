"""v3.5 chunk 11 — profile_validator 全路径单测。

Hard reject（返 None）：
  * JSON 解析失败
  * 顶层不是 dict
  * 必填字段缺失
  * 字段类型错（string 字段是 list / list 字段是 string）
  * 任一 string / list[string] cell 命中 SUSPICIOUS_TAG_RE

Soft accept（返 dict + log）：
  * schema 外字段 → 剥离
  * 反推词命中 → 接受 + log warning
  * string 空白 → 视同 None
  * list 含 None / 空字符串 → 过滤
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.utils.profile_validator import validate_profile_json

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))


VALID_JSON = """
{
  "profession": "程序员",
  "current_projects": ["Skyler v3.5"],
  "communication_style": "直接、紧凑",
  "interests": ["LLM 工程", "音乐"],
  "language_preferences": "中文",
  "active_hours": "深夜",
  "recurring_topics": ["调 bug", "Live2D"]
}
"""


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


def test_valid_json_returns_dict():
    print("\n[happy] 合法 JSON → 完整 dict")
    d = validate_profile_json(VALID_JSON, user_id="u1")
    check("非 None", d is not None)
    if d is not None:
        check("7 字段都在", set(d.keys()) == {
            "profession", "current_projects", "communication_style",
            "interests", "language_preferences", "active_hours",
            "recurring_topics",
        })
        check("profession 是 string", d["profession"] == "程序员")
        check("current_projects 是 list", d["current_projects"] == ["Skyler v3.5"])


def test_markdown_fence_stripped():
    print("\n[happy] ```json fence 自动剥")
    wrapped = "```json\n" + VALID_JSON + "\n```"
    d = validate_profile_json(wrapped, user_id="u1")
    check("剥 fence 后 parse 成功", d is not None)


def test_extra_fields_stripped():
    print("\n[happy] schema 外字段被剥（容忍 + log info）")
    raw = """
    {
      "profession": null, "current_projects": [], "communication_style": null,
      "interests": [], "language_preferences": null, "active_hours": null,
      "recurring_topics": [],
      "favorite_color": "蓝色",
      "evil_field": "should not appear"
    }
    """
    d = validate_profile_json(raw, user_id="u1")
    check("非 None", d is not None)
    if d is not None:
        check("favorite_color 被剥", "favorite_color" not in d)
        check("evil_field 被剥", "evil_field" not in d)


def test_empty_lists_and_nulls_ok():
    print("\n[happy] 所有 null / [] 也 OK（首轮无数据）")
    raw = """
    {
      "profession": null, "current_projects": [], "communication_style": null,
      "interests": [], "language_preferences": null, "active_hours": null,
      "recurring_topics": []
    }
    """
    d = validate_profile_json(raw, user_id="u1")
    check("接受 + 全 None/[]", d is not None
          and d["profession"] is None and d["recurring_topics"] == [])


def test_string_whitespace_to_none():
    print("\n[normalize] string 空白 → None")
    raw = """
    {
      "profession": "   ", "current_projects": [], "communication_style": null,
      "interests": [], "language_preferences": null, "active_hours": null,
      "recurring_topics": []
    }
    """
    d = validate_profile_json(raw, user_id="u1")
    check("非 None", d is not None)
    if d is not None:
        check("空白 string 归一为 None", d["profession"] is None)


def test_list_filters_empty_and_non_string():
    print("\n[normalize] list 过滤 None / 空 string / 非 string")
    raw = """
    {
      "profession": null, "current_projects": ["A", "  ", "", null, 123, "B"],
      "communication_style": null,
      "interests": [], "language_preferences": null, "active_hours": null,
      "recurring_topics": []
    }
    """
    d = validate_profile_json(raw, user_id="u1")
    check("非 None", d is not None)
    if d is not None:
        check("非法元素过滤后只剩 [A, B]",
              d["current_projects"] == ["A", "B"])


# ---------------------------------------------------------------------------
# Reject paths
# ---------------------------------------------------------------------------


def test_reject_json_parse_error():
    print("\n[reject] JSON parse error")
    check("非合法 JSON → None",
          validate_profile_json("{not json", user_id="u1") is None)
    check("空 string → None",
          validate_profile_json("", user_id="u1") is None)


def test_reject_top_level_not_dict():
    print("\n[reject] 顶层不是 dict")
    check("array → None", validate_profile_json("[]", user_id="u1") is None)
    check("string → None", validate_profile_json('"hi"', user_id="u1") is None)
    check("number → None", validate_profile_json('123', user_id="u1") is None)


def test_reject_missing_field():
    print("\n[reject] 必填字段缺失")
    raw = """
    {
      "profession": null, "current_projects": [], "communication_style": null,
      "interests": [], "language_preferences": null, "active_hours": null
    }
    """
    # recurring_topics 缺失
    check("缺一字段 → None",
          validate_profile_json(raw, user_id="u1") is None)


def test_reject_type_mismatch_string_is_list():
    print("\n[reject] string 字段塞了 list")
    raw = """
    {
      "profession": ["程序员"], "current_projects": [], "communication_style": null,
      "interests": [], "language_preferences": null, "active_hours": null,
      "recurring_topics": []
    }
    """
    check("string 字段 list → None",
          validate_profile_json(raw, user_id="u1") is None)


def test_reject_type_mismatch_list_is_string():
    print("\n[reject] list 字段塞了 string")
    raw = """
    {
      "profession": null, "current_projects": "Skyler",
      "communication_style": null,
      "interests": [], "language_preferences": null, "active_hours": null,
      "recurring_topics": []
    }
    """
    check("list 字段 string → None",
          validate_profile_json(raw, user_id="u1") is None)


def test_reject_suspicious_tag_in_string():
    print("\n[reject] string 字段含 <netease.x> 可疑 tag → None")
    raw = """
    {
      "profession": "程序员 <netease.daily_recommend/>",
      "current_projects": [], "communication_style": null,
      "interests": [], "language_preferences": null, "active_hours": null,
      "recurring_topics": []
    }
    """
    check("SUSPICIOUS hit → None",
          validate_profile_json(raw, user_id="u1") is None)


def test_reject_suspicious_tag_in_list_item():
    print("\n[reject] list item 含可疑 tag → None")
    raw = """
    {
      "profession": null,
      "current_projects": ["项目 A", "<a.b></a.b>"],
      "communication_style": null,
      "interests": [], "language_preferences": null, "active_hours": null,
      "recurring_topics": []
    }
    """
    check("SUSPICIOUS in list → None",
          validate_profile_json(raw, user_id="u1") is None)


# ---------------------------------------------------------------------------
# Soft warn (accept) paths
# ---------------------------------------------------------------------------


def test_accept_backinference_keywords_but_warn():
    print("\n[soft warn] 反推词命中 → accept（fail-open，让 UI 编辑）")
    raw = """
    {
      "profession": "程序员",
      "current_projects": ["细腻敏感的内心"],
      "communication_style": "需要被陪伴",
      "interests": [],
      "language_preferences": null, "active_hours": null,
      "recurring_topics": []
    }
    """
    d = validate_profile_json(raw, user_id="u_backref")
    check("反推词不 reject", d is not None)
    if d is not None:
        check("内容原样保留（不剥）",
              d["communication_style"] == "需要被陪伴"
              and "细腻敏感的内心" in d["current_projects"])


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main():
    test_valid_json_returns_dict()
    test_markdown_fence_stripped()
    test_extra_fields_stripped()
    test_empty_lists_and_nulls_ok()
    test_string_whitespace_to_none()
    test_list_filters_empty_and_non_string()
    test_reject_json_parse_error()
    test_reject_top_level_not_dict()
    test_reject_missing_field()
    test_reject_type_mismatch_string_is_list()
    test_reject_type_mismatch_list_is_string()
    test_reject_suspicious_tag_in_string()
    test_reject_suspicious_tag_in_list_item()
    test_accept_backinference_keywords_but_warn()

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
