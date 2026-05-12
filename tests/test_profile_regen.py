"""v3.5 chunk 11 — _regenerate_profile_data 4 模式 + prompt builder unit。"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.services import profile_regen as pr

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------


def test_prompt_includes_schema_fields():
    print("\n[prompt] 7 字段全在 prompt 里")
    p = pr.build_profile_extraction_prompt(None, ["用户消息 A"])
    for f in [
        "profession", "current_projects", "communication_style",
        "interests", "language_preferences", "active_hours",
        "recurring_topics",
    ]:
        check(f"含 {f}", f in p)


def test_prompt_warns_against_hallucination():
    print("\n[prompt] 文案禁反推性描述")
    p = pr.build_profile_extraction_prompt(None, ["msg"])
    check("含 '客观事实'", "客观事实" in p)
    check("含 '绝不写' 禁令", "绝不写" in p)
    check("含 'JSON' / '合法 JSON'", "JSON" in p or "json" in p)


def test_prompt_old_profile_null_renders_null():
    print("\n[prompt] old_profile=None 渲染 'null'")
    p = pr.build_profile_extraction_prompt(None, ["msg"])
    check("旧档案段为 'null'", "null" in p)


def test_prompt_old_profile_dict_renders_json():
    print("\n[prompt] old_profile dict 渲染 JSON")
    old = {"profession": "工程师", "current_projects": ["X"],
           "communication_style": None, "interests": [],
           "language_preferences": None, "active_hours": None,
           "recurring_topics": []}
    p = pr.build_profile_extraction_prompt(old, ["msg"])
    check("旧档案 JSON 含'工程师'", "工程师" in p)
    check("旧档案 JSON 含 'current_projects'", "current_projects" in p)


def test_prompt_empty_user_messages_uses_placeholder():
    print("\n[prompt] 空 user_messages → 显示 '(空)'")
    p = pr.build_profile_extraction_prompt(None, [])
    check("含 '(空)' 占位", "(空)" in p)


# ---------------------------------------------------------------------------
# config getters
# ---------------------------------------------------------------------------


def test_config_defaults():
    print("\n[config] 默认值")
    check("enabled bool", isinstance(pr.get_profile_structured_enabled(), bool))
    check("input_days int > 0", pr.get_profile_input_days() > 0)
    check("min_user_messages int > 0", pr.get_profile_min_user_messages() > 0)
    check("cron 表达式形如 X X * * *",
          len(pr.get_profile_cron_expr().split()) == 5)


# ---------------------------------------------------------------------------
# _regenerate_profile_data — 4 modes via mocked LLM + DB
# ---------------------------------------------------------------------------


VALID_LLM_OUTPUT = json.dumps({
    "profession": "程序员",
    "current_projects": ["Skyler v3.5"],
    "communication_style": "直接",
    "interests": ["LLM"],
    "language_preferences": "中文",
    "active_hours": "深夜",
    "recurring_topics": ["调 bug"],
}, ensure_ascii=False)


def _fake_llm_response(content: str):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


async def test_skip_disabled():
    print("\n[regen] skip_disabled when config enabled=false")
    with patch.object(pr, "get_profile_structured_enabled", return_value=False):
        status, p = await pr._regenerate_profile_data("u_test", mode="cron")
    check("status == skip_disabled", status == "skip_disabled")
    check("profile is None", p is None)


async def test_skip_too_few_user_msgs():
    print("\n[regen] skip_too_few_user_msgs when count < min")
    with patch.object(pr, "count_user_messages_within_days",
                      AsyncMock(return_value=3)), \
         patch.object(pr, "get_profile_min_user_messages", return_value=10):
        status, p = await pr._regenerate_profile_data("u_test", mode="cron")
    check("status == skip_too_few_user_msgs",
          status == "skip_too_few_user_msgs")
    check("profile is None", p is None)


async def test_skip_llm_failed():
    print("\n[regen] skip_llm_failed on LLM exception")
    from backend.llm.client import LLMError
    with patch.object(pr, "count_user_messages_within_days",
                      AsyncMock(return_value=50)), \
         patch.object(pr, "fetch_recent_user_messages",
                      AsyncMock(return_value=["msg 1", "msg 2"])), \
         patch.object(pr, "get_profile_data", AsyncMock(return_value=None)), \
         patch.object(pr, "call_llm",
                      AsyncMock(side_effect=LLMError("network"))):
        status, p = await pr._regenerate_profile_data("u_test", mode="cron")
    check("status == skip_llm_failed", status == "skip_llm_failed")


async def test_skip_validator_rejected():
    print("\n[regen] skip_validator_rejected on invalid LLM JSON")
    with patch.object(pr, "count_user_messages_within_days",
                      AsyncMock(return_value=50)), \
         patch.object(pr, "fetch_recent_user_messages",
                      AsyncMock(return_value=["msg"])), \
         patch.object(pr, "get_profile_data", AsyncMock(return_value=None)), \
         patch.object(pr, "call_llm",
                      AsyncMock(return_value=_fake_llm_response("not json"))):
        status, p = await pr._regenerate_profile_data("u_test", mode="cron")
    check("status == skip_validator_rejected",
          status == "skip_validator_rejected")
    check("profile is None", p is None)


async def test_regenerated_success_cron_mode():
    print("\n[regen] cron mode → regenerated + save_profile_data called")
    save_calls = []

    async def fake_save(user_id, data):
        save_calls.append((user_id, data))
        return True

    with patch.object(pr, "count_user_messages_within_days",
                      AsyncMock(return_value=50)), \
         patch.object(pr, "fetch_recent_user_messages",
                      AsyncMock(return_value=["msg"])), \
         patch.object(pr, "get_profile_data", AsyncMock(return_value=None)), \
         patch.object(pr, "call_llm",
                      AsyncMock(return_value=_fake_llm_response(VALID_LLM_OUTPUT))), \
         patch.object(pr, "save_profile_data", new=fake_save):
        status, p = await pr._regenerate_profile_data("u_test", mode="cron")
    check("status == regenerated", status == "regenerated")
    check("profile dict 7 字段", p is not None and len(p) == 7)
    check("save_profile_data 调过 1 次", len(save_calls) == 1)


async def test_manual_reset_drops_old_profile():
    print("\n[regen] manual_reset 模式：old_profile=None 喂 LLM")
    captured = {}

    async def fake_llm(*, messages, model, stream=False, **kw):
        captured["prompt"] = messages[0]["content"]
        return _fake_llm_response(VALID_LLM_OUTPUT)

    async def fake_get_old(user_id):
        return {"profession": "旧职业", "current_projects": [],
                "communication_style": None, "interests": [],
                "language_preferences": None, "active_hours": None,
                "recurring_topics": []}

    with patch.object(pr, "count_user_messages_within_days",
                      AsyncMock(return_value=50)), \
         patch.object(pr, "fetch_recent_user_messages",
                      AsyncMock(return_value=["msg A"])), \
         patch.object(pr, "get_profile_data", new=fake_get_old), \
         patch.object(pr, "call_llm", new=fake_llm), \
         patch.object(pr, "save_profile_data", AsyncMock(return_value=True)):
        status, _ = await pr._regenerate_profile_data(
            "u_test", mode="manual_reset",
        )
    check("status == regenerated", status == "regenerated")
    # manual_reset 路径：prompt 不应含"旧职业"（old_profile 被强制 None）
    check("manual_reset prompt 不含旧职业",
          "旧职业" not in captured.get("prompt", ""))
    # 旧档案段应渲染成 ``null``
    check("旧档案段为 'null'", "null" in captured.get("prompt", ""))


async def test_manual_incremental_keeps_old_profile():
    print("\n[regen] manual_incremental 模式：old_profile 喂 LLM")
    captured = {}

    async def fake_llm(*, messages, model, stream=False, **kw):
        captured["prompt"] = messages[0]["content"]
        return _fake_llm_response(VALID_LLM_OUTPUT)

    async def fake_get_old(user_id):
        return {"profession": "工程师_X", "current_projects": [],
                "communication_style": None, "interests": [],
                "language_preferences": None, "active_hours": None,
                "recurring_topics": []}

    with patch.object(pr, "count_user_messages_within_days",
                      AsyncMock(return_value=50)), \
         patch.object(pr, "fetch_recent_user_messages",
                      AsyncMock(return_value=["msg A"])), \
         patch.object(pr, "get_profile_data", new=fake_get_old), \
         patch.object(pr, "call_llm", new=fake_llm), \
         patch.object(pr, "save_profile_data", AsyncMock(return_value=True)):
        status, _ = await pr._regenerate_profile_data(
            "u_test", mode="manual_incremental",
        )
    check("status == regenerated", status == "regenerated")
    check("incremental prompt 含旧 profile 字段",
          "工程师_X" in captured.get("prompt", ""))


async def test_invalid_mode_falls_back_to_cron():
    print("\n[regen] 非法 mode → 默认 cron + log error")
    with patch.object(pr, "count_user_messages_within_days",
                      AsyncMock(return_value=3)):
        status, _ = await pr._regenerate_profile_data(
            "u_test", mode="bogus_mode",
        )
    # bogus_mode 被 fallback 到 cron，因为 user_msgs 不够 → skip_too_few
    check("status == skip_too_few_user_msgs",
          status == "skip_too_few_user_msgs")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


async def amain():
    await test_skip_disabled()
    await test_skip_too_few_user_msgs()
    await test_skip_llm_failed()
    await test_skip_validator_rejected()
    await test_regenerated_success_cron_mode()
    await test_manual_reset_drops_old_profile()
    await test_manual_incremental_keeps_old_profile()
    await test_invalid_mode_falls_back_to_cron()


def main():
    test_prompt_includes_schema_fields()
    test_prompt_warns_against_hallucination()
    test_prompt_old_profile_null_renders_null()
    test_prompt_old_profile_dict_renders_json()
    test_prompt_empty_user_messages_uses_placeholder()
    test_config_defaults()
    asyncio.run(amain())

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
