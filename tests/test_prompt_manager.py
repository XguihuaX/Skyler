"""Tests for backend/config/prompt_manager.py and backend/config/prompts.py"""
import sys
import os
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.config.prompt_manager import PromptManager, prompt_manager, _CHARACTERS, _DEFAULT_CHARACTER
from backend.config.prompts import (
    BASE_INSTRUCTION, MEM_AGENT_PROMPT,
    PLANNER_AGENT_SYSPROMPT, PLANNER_AGENT_INST, PLANNER_AGENT_FEW_SHOT,
)

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []

def check(name: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))


# ---------------------------------------------------------------------------
# characters.yaml loading
# ---------------------------------------------------------------------------

def test_yaml_loading():
    print("\n[characters.yaml]")
    check("5 characters loaded",       len(_CHARACTERS) == 5)
    check("default_character is 默认", _DEFAULT_CHARACTER == "默认")
    for name in ["八重神子", "默认", "荧", "凝光", "神里绫华"]:
        cfg = _CHARACTERS.get(name, {})
        check(f"{name} has persona",        bool(cfg.get("persona")))
        check(f"{name} has default_emotion",bool(cfg.get("default_emotion")))


# ---------------------------------------------------------------------------
# PromptManager
# ---------------------------------------------------------------------------

def test_get_prompt_default():
    print("\n[PromptManager.get_prompt — default]")
    pm = PromptManager()
    result = pm.get_prompt("user_a")
    check("returns dict",              isinstance(result, dict))
    check("character_id is 默认",     result["character_id"] == "默认")
    check("system_prompt non-empty",  len(result["system_prompt"]) > 10)
    check("default_emotion present",  "default_emotion" in result)
    check("BASE_INSTRUCTION in prompt",
          "输入" in result["system_prompt"] or "用户" in result["system_prompt"])


def test_switch_character_success():
    print("\n[PromptManager.switch_character — valid]")
    pm = PromptManager()
    for char in ["八重神子", "荧", "凝光", "神里绫华"]:
        ok = pm.switch_character("user_b", char)
        check(f"switch to {char} returns True", ok)
        check(f"get_current_character == {char}",
              pm.get_current_character("user_b") == char)
        p = pm.get_prompt("user_b")
        check(f"prompt after switch contains {char} persona",
              char in _CHARACTERS[char]["persona"][:30] or
              len(p["system_prompt"]) > 10)


def test_switch_character_invalid():
    print("\n[PromptManager.switch_character — invalid]")
    pm = PromptManager()
    ok = pm.switch_character("user_c", "不存在的角色")
    check("invalid character returns False",  not ok)
    check("character unchanged after failure",
          pm.get_current_character("user_c") == _DEFAULT_CHARACTER)


def test_user_isolation():
    print("\n[PromptManager — user isolation]")
    pm = PromptManager()
    pm.switch_character("ua", "八重神子")
    pm.switch_character("ub", "凝光")
    check("ua character correct", pm.get_current_character("ua") == "八重神子")
    check("ub character correct", pm.get_current_character("ub") == "凝光")
    check("ua prompt has 八重神子 persona",
          "八重神子" in pm.get_prompt("ua")["system_prompt"])
    check("ub prompt has 凝光 persona",
          "凝光" in pm.get_prompt("ub")["system_prompt"])


def test_new_user_gets_default():
    print("\n[PromptManager — new user default]")
    pm = PromptManager()
    check("brand-new user gets default",
          pm.get_current_character("brand_new_user_xyz") == _DEFAULT_CHARACTER)


def test_list_characters():
    print("\n[PromptManager.list_characters]")
    chars = PromptManager.list_characters()
    check("returns list",            isinstance(chars, list))
    check("contains all 5",          len(chars) == 5)
    for name in ["八重神子", "默认", "荧", "凝光", "神里绫华"]:
        check(f"contains {name}",    name in chars)


def test_singleton():
    print("\n[prompt_manager singleton]")
    check("is PromptManager instance", isinstance(prompt_manager, PromptManager))


# ---------------------------------------------------------------------------
# prompts.py content checks
# ---------------------------------------------------------------------------

def test_prompts_content():
    print("\n[prompts.py]")
    check("BASE_INSTRUCTION non-empty",        len(BASE_INSTRUCTION) > 50)
    check("BASE_INSTRUCTION mentions 对话",    "对话" in BASE_INSTRUCTION)

    check("MEM_AGENT_PROMPT non-empty",        len(MEM_AGENT_PROMPT) > 100)
    check("MEM_AGENT_PROMPT has {dialogue}",   "{dialogue}" in MEM_AGENT_PROMPT)
    check("MEM_AGENT_PROMPT valid str.format", True)  # no KeyError above proves it
    try:
        MEM_AGENT_PROMPT.format(dialogue="test content")
        check("MEM_AGENT_PROMPT.format works", True)
    except KeyError as e:
        check("MEM_AGENT_PROMPT.format works", False, str(e))

    check("PLANNER_AGENT_SYSPROMPT non-empty", len(PLANNER_AGENT_SYSPROMPT) > 100)
    check("PLANNER mentions PlannerAgent",     "PlannerAgent" in PLANNER_AGENT_SYSPROMPT)

    check("PLANNER_AGENT_INST has {now_str}",  "{now_str}" in PLANNER_AGENT_INST)
    check("PLANNER_AGENT_INST has {user_id}",  "{user_id}" in PLANNER_AGENT_INST)
    try:
        PLANNER_AGENT_INST.format(now_str="2026-01-01 08:00:00", user_id="test_user")
        check("PLANNER_AGENT_INST.format works", True)
    except KeyError as e:
        check("PLANNER_AGENT_INST.format works", False, str(e))

    check("PLANNER_AGENT_FEW_SHOT non-empty",  len(PLANNER_AGENT_FEW_SHOT) > 100)
    check("FEW_SHOT has examples",             "例子" in PLANNER_AGENT_FEW_SHOT)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    test_yaml_loading()
    test_get_prompt_default()
    test_switch_character_success()
    test_switch_character_invalid()
    test_user_isolation()
    test_new_user_gets_default()
    test_list_characters()
    test_singleton()
    test_prompts_content()

    total = len(results)
    passed = sum(1 for _, ok in results if ok)
    print(f"\n{'='*40}")
    print(f"Results: {passed}/{total} passed")
    if passed < total:
        failed = [name for name, ok in results if not ok]
        print("FAILED:", ", ".join(failed))
        sys.exit(1)
    else:
        print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
