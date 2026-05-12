"""v3.5 chunk 11 — structured profile schema 定义。

profile_data 取代 chunk 9 的 profile_summary 自然语言段落：
* string 字段 + list[string] 字段，**仅客观事实**
* LLM hallucinate 反推性内容（"温柔陪伴" / "亲密关系" / "需要被关心"）的空间被
  schema 边界禁掉

7 个字段都必填（无值用 null / []），LLM 输出多字段被 validator 剥离，
缺字段被 reject。

存储：``users.profile_data`` TEXT 列存 JSON 字符串。SQLite 无原生 JSON，
所有 read/write 都通过 ``json.loads`` / ``json.dumps``。

Schema 演进（未来 v2 时）：保留 ``schema_version`` 字段在 wrapper level，
或新加 ``profile_data_v2`` 列双写一段，再 deprecate v1。当前 v1 不写
version 字段，让 JSON 干净一档。
"""
from __future__ import annotations

from typing import Any, Optional


#: v1 schema：7 个字段，全部必填（无值 null / []）。
#:
#: 字段类型枚举：
#:   "string|null"  允许 None 或非空字符串
#:   "list[string]" 必须是 list；空 list 用 ``[]``；不允许 None
PROFILE_SCHEMA_V1: dict[str, str] = {
    "profession":            "string|null",
    "current_projects":      "list[string]",
    "communication_style":   "string|null",
    "interests":             "list[string]",
    "language_preferences":  "string|null",
    "active_hours":          "string|null",
    "recurring_topics":      "list[string]",
}


def empty_profile() -> dict[str, Any]:
    """Return an all-null / empty-list profile dict matching v1 schema."""
    return {
        "profession":            None,
        "current_projects":      [],
        "communication_style":   None,
        "interests":             [],
        "language_preferences":  None,
        "active_hours":          None,
        "recurring_topics":      [],
    }


def field_type(name: str) -> Optional[str]:
    """Return schema type for *name*; None if name is not in schema."""
    return PROFILE_SCHEMA_V1.get(name)


def is_string_field(name: str) -> bool:
    return field_type(name) == "string|null"


def is_list_field(name: str) -> bool:
    return field_type(name) == "list[string]"


__all__ = [
    "PROFILE_SCHEMA_V1",
    "empty_profile",
    "field_type",
    "is_string_field",
    "is_list_field",
]
