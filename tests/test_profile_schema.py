"""v3.5 chunk 11 — profile_schema PROFILE_SCHEMA_V1 / empty_profile helpers."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.utils.profile_schema import (
    PROFILE_SCHEMA_V1,
    empty_profile,
    field_type,
    is_list_field,
    is_string_field,
)

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, condition: bool) -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}")
    results.append((name, condition))


def test_schema_keys_match_spec():
    print("\n[schema] 7 字段全在 + 与 spec 一致")
    expected = {
        "profession", "current_projects", "communication_style",
        "interests", "language_preferences", "active_hours",
        "recurring_topics",
    }
    check("精确 7 字段", set(PROFILE_SCHEMA_V1.keys()) == expected)


def test_empty_profile_has_all_keys():
    print("\n[empty] empty_profile 含全部字段")
    ep = empty_profile()
    check("7 字段都存在",
          set(ep.keys()) == set(PROFILE_SCHEMA_V1.keys()))
    check("string|null 字段都是 None",
          all(ep[k] is None for k in PROFILE_SCHEMA_V1
              if is_string_field(k)))
    check("list[string] 字段都是 []",
          all(ep[k] == [] for k in PROFILE_SCHEMA_V1
              if is_list_field(k)))


def test_field_type_unknown_returns_none():
    print("\n[helper] unknown field → None")
    check("unknown 返 None", field_type("__nonexistent__") is None)


def test_is_string_field_and_list_field_disjoint():
    print("\n[helper] string vs list 字段不重叠")
    for k in PROFILE_SCHEMA_V1:
        s, l = is_string_field(k), is_list_field(k)
        check(f"{k} 只属一类", s != l)


def main():
    test_schema_keys_match_spec()
    test_empty_profile_has_all_keys()
    test_field_type_unknown_returns_none()
    test_is_string_field_and_list_field_disjoint()

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
