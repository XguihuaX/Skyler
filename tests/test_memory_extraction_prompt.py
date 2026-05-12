"""v3.5 chunk 10 commit 3 — extraction prompt + LLM call unit。"""
from __future__ import annotations

import asyncio
import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.prompts import memory_extraction as me

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))


def _fake_turn(tid, content):
    return SimpleNamespace(id=tid, content=content)


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------


def test_prompt_includes_schema_contract():
    print("\n[prompt] 含 schema 4 type + JSON list 输出契约")
    p = me.build_extraction_prompt([_fake_turn(1, "我喜欢日系音乐")])
    for tag in ['"fact"', '"preference"', '"event"', '"commitment"']:
        check(f"含 {tag}", tag in p)
    check("含 'JSON 列表'",
          "JSON 列表" in p or "JSON 数组" in p)
    check("含 'confidence'", "confidence" in p)


def test_prompt_warns_against_backinference():
    print("\n[prompt] 列出 14 反推词清单 让 LLM 避开")
    p = me.build_extraction_prompt([_fake_turn(1, "msg")])
    for kw in ["感觉", "情绪", "印象", "陪伴", "亲密", "温柔",
               "细腻", "敏感", "脆弱"]:
        check(f"含反推词 {kw!r}", kw in p)


def test_prompt_third_person_instruction():
    print("\n[prompt] 用第三人称客观陈述")
    p = me.build_extraction_prompt([_fake_turn(1, "msg")])
    check("含 '第三人称'",
          "第三人称" in p or "用户的" in p)


def test_prompt_turn_ids_rendered():
    print("\n[prompt] turn id 渲染到 input block")
    p = me.build_extraction_prompt([
        _fake_turn(42, "我猫叫 Mochi"),
        _fake_turn(43, "周五前要发布"),
    ])
    check("含 [turn=42]", "[turn=42]" in p)
    check("含 [turn=43]", "[turn=43]" in p)
    check("内容渲染", "我猫叫 Mochi" in p and "周五前要发布" in p)


def test_prompt_empty_turns_placeholder():
    print("\n[prompt] 空 turns → '(空)' 占位")
    p = me.build_extraction_prompt([])
    check("含 '(空)'", "(空)" in p)


def test_prompt_skips_empty_content():
    print("\n[prompt] 空 content 自动跳过 不进 input")
    p = me.build_extraction_prompt([
        _fake_turn(1, ""),
        _fake_turn(2, "   "),
        _fake_turn(3, "有内容"),
    ])
    check("[turn=1] 不存在（空 content）", "[turn=1]" not in p)
    check("[turn=2] 不存在（whitespace）", "[turn=2]" not in p)
    check("[turn=3] 存在", "[turn=3]" in p and "有内容" in p)


# ---------------------------------------------------------------------------
# call_extraction_llm
# ---------------------------------------------------------------------------


def _fake_response(content):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


async def test_call_llm_returns_raw_string():
    print("\n[llm] 成功调用返 raw string")
    raw = '[{"type":"fact","content":"x","confidence":0.9}]'
    with patch.object(me, "call_llm",
                      AsyncMock(return_value=_fake_response(raw))):
        out = await me.call_extraction_llm("prompt")
    check("返 raw string", out == raw)


async def test_call_llm_returns_none_on_LLMError():
    print("\n[llm] LLMError → None（不抛）")
    from backend.llm.client import LLMError
    with patch.object(me, "call_llm",
                      AsyncMock(side_effect=LLMError("network"))):
        out = await me.call_extraction_llm("prompt")
    check("返 None", out is None)


async def test_call_llm_returns_none_on_generic_exception():
    print("\n[llm] generic Exception → None（不抛）")
    with patch.object(me, "call_llm",
                      AsyncMock(side_effect=RuntimeError("oops"))):
        out = await me.call_extraction_llm("prompt")
    check("返 None", out is None)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


async def amain():
    await test_call_llm_returns_raw_string()
    await test_call_llm_returns_none_on_LLMError()
    await test_call_llm_returns_none_on_generic_exception()


def main():
    test_prompt_includes_schema_contract()
    test_prompt_warns_against_backinference()
    test_prompt_third_person_instruction()
    test_prompt_turn_ids_rendered()
    test_prompt_empty_turns_placeholder()
    test_prompt_skips_empty_content()
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
