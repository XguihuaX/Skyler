"""Tests for v3-G chunk 4 部分 A — tool_call_resilience。

覆盖三种 fallback pattern + 边界 + ToolRegistry 整合 + 不重复执行 + 不污
染 chat_history。
"""
import asyncio
import json
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.agents.tool_call_resilience import (
    detect_and_execute_fallback_tool_calls,
    _coerce_param_value,
)

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))


# 临时 ToolRegistry 注入：每个测试用 fresh 的 _tools dict，避免互相污染。
def _patched_registry(tools_dict: dict):
    """用 patch 把 ToolRegistry 切到 tools_dict + 配套 _tools 引用。"""
    from backend.tools.registry import ToolRegistry
    return patch.multiple(
        "backend.tools.registry",
        _tools=tools_dict,
    )


# ---------------------------------------------------------------------------
# 1. _coerce_param_value
# ---------------------------------------------------------------------------

async def test_coerce_param_value():
    print("\n[resilience — _coerce_param_value]")
    check("'true' → True",  _coerce_param_value("true") is True)
    check("'False' → False (case-insensitive)", _coerce_param_value("False") is False)
    check("'null' → None", _coerce_param_value("null") is None)
    check("'42' → int 42", _coerce_param_value("42") == 42)
    check("'3.14' → float 3.14", _coerce_param_value("3.14") == 3.14)
    check("JSON list → list", _coerce_param_value("[1,2,3]") == [1, 2, 3])
    check("JSON dict → dict",
          _coerce_param_value('{"a": 1}') == {"a": 1})
    check("plain string → str", _coerce_param_value("hello world") == "hello world")
    check("empty → ''", _coerce_param_value("   ") == "")
    check("None → None", _coerce_param_value(None) is None)


# ---------------------------------------------------------------------------
# 2. Qwen XML pattern
# ---------------------------------------------------------------------------

async def test_qwen_xml_basic():
    print("\n[resilience — qwen_xml: <tool_call>{json}</tool_call>]")

    calls: list = []
    async def fake_tool(user_id=None, character_id=None, minutes=None, **_):
        calls.append({"user_id": user_id, "minutes": minutes, "character_id": character_id})
        return {"ok": True}

    with _patched_registry({"proactive.snooze_wake_call": fake_tool}):
        text = '好的<tool_call>{"name": "proactive.snooze_wake_call", "arguments": {"minutes": 5}}</tool_call>，5 分钟后再叫你～'
        cleaned, executed = await detect_and_execute_fallback_tool_calls(
            text, user_id="default", character_id=1,
        )

    check("1 fallback executed", len(executed) == 1)
    check("pattern=qwen_xml", executed and executed[0]["pattern"] == "qwen_xml")
    check("name correct",
          executed and executed[0]["name"] == "proactive.snooze_wake_call")
    check("args parsed", executed and executed[0]["args"] == {"minutes": 5})
    check("tool actually called", len(calls) == 1 and calls[0]["minutes"] == 5)
    check("user_id auto-injected", calls and calls[0]["user_id"] == "default")
    check("character_id auto-injected", calls and calls[0]["character_id"] == 1)
    check("XML stripped",
          "<tool_call>" not in cleaned and "</tool_call>" not in cleaned,
          f"got: {cleaned!r}")
    check("preserves surrounding text",
          "好的" in cleaned and "5 分钟后再叫你" in cleaned)


async def test_qwen_xml_double_encoded_arguments():
    print("\n[resilience — qwen_xml: arguments 二次 JSON 编码]")
    calls: list = []
    async def fake_tool(user_id=None, character_id=None, minutes=None, **_):
        calls.append(minutes); return {"ok": True}
    with _patched_registry({"proactive.snooze_wake_call": fake_tool}):
        # 部分模型 arguments 是 JSON 字符串而非对象
        text = '<tool_call>{"name": "proactive.snooze_wake_call", "arguments": "{\\"minutes\\": 10}"}</tool_call>'
        _, executed = await detect_and_execute_fallback_tool_calls(
            text, user_id="u1",
        )
    check("double-encoded args parsed", len(executed) == 1 and executed[0]["args"].get("minutes") == 10)
    check("tool called with int 10", calls == [10])


async def test_qwen_xml_unknown_tool_skipped():
    print("\n[resilience — qwen_xml: unknown tool not executed]")
    with _patched_registry({}):
        text = '<tool_call>{"name": "foo.bar.nonexistent", "arguments": {}}</tool_call>'
        cleaned, executed = await detect_and_execute_fallback_tool_calls(
            text, user_id="u1",
        )
    check("nothing executed", executed == [])
    check("XML still stripped (not business text)",
          "<tool_call>" not in cleaned)


async def test_qwen_xml_invalid_json_skipped():
    print("\n[resilience — qwen_xml: invalid JSON tolerated]")
    with _patched_registry({}):
        text = '<tool_call>{not valid json}</tool_call>剩余'
        cleaned, executed = await detect_and_execute_fallback_tool_calls(
            text, user_id="u1",
        )
    check("nothing executed", executed == [])
    check("XML still stripped", "<tool_call>" not in cleaned)
    check("remainder kept", "剩余" in cleaned)


async def test_qwen_xml_multiple_calls():
    print("\n[resilience — qwen_xml: multiple calls per text]")
    calls: list = []
    async def fake_a(user_id=None, **_): calls.append("a"); return {"ok": True}
    async def fake_b(user_id=None, **_): calls.append("b"); return {"ok": True}
    with _patched_registry({"a": fake_a, "b": fake_b}):
        text = (
            '<tool_call>{"name": "a", "arguments": {}}</tool_call>'
            '中间文字'
            '<tool_call>{"name": "b", "arguments": {}}</tool_call>'
        )
        cleaned, executed = await detect_and_execute_fallback_tool_calls(
            text, user_id="u1",
        )
    check("both executed", len(executed) == 2)
    check("order preserved a then b", calls == ["a", "b"])
    check("middle text preserved", "中间文字" in cleaned)
    check("no XML residue", "<tool_call>" not in cleaned)


async def test_qwen_xml_capability_exec_failure_caught():
    print("\n[resilience — qwen_xml: handler raises → captured as error]")
    async def boom(**_): raise RuntimeError("boom")
    with _patched_registry({"x": boom}):
        text = '<tool_call>{"name": "x", "arguments": {}}</tool_call>'
        cleaned, executed = await detect_and_execute_fallback_tool_calls(
            text, user_id="u1",
        )
    check("executed entry recorded", len(executed) == 1)
    check("result.error contains 'boom'",
          isinstance(executed[0]["result"], dict) and "boom" in executed[0]["result"].get("error", ""))


# ---------------------------------------------------------------------------
# 3. Anthropic invoke pattern
# ---------------------------------------------------------------------------

async def test_anthropic_invoke_basic():
    print("\n[resilience — anthropic_invoke: <function_calls><invoke>...</invoke></function_calls>]")
    calls: list = []
    async def fake(user_id=None, character_id=None, minutes=None, **_):
        calls.append({"minutes": minutes}); return {"ok": True}
    with _patched_registry({"proactive.snooze_wake_call": fake}):
        text = (
            '好的，'
            '<function_calls>'
            '<invoke name="proactive.snooze_wake_call">'
            '<parameter name="minutes">5</parameter>'
            '</invoke>'
            '</function_calls>'
            '马上推迟。'
        )
        cleaned, executed = await detect_and_execute_fallback_tool_calls(
            text, user_id="u1", character_id=1,
        )
    check("1 fallback executed", len(executed) == 1)
    check("pattern=anthropic_invoke",
          executed and executed[0]["pattern"] == "anthropic_invoke")
    check("name parsed",
          executed and executed[0]["name"] == "proactive.snooze_wake_call")
    check("minutes coerced to int 5", calls and calls[0]["minutes"] == 5)
    check("invoke block stripped",
          "<function_calls>" not in cleaned and "<invoke" not in cleaned)
    check("surrounding text kept",
          "好的，" in cleaned and "马上推迟。" in cleaned)


async def test_anthropic_invoke_multiple_params():
    print("\n[resilience — anthropic_invoke: multiple params + boolean coercion]")
    calls: list = []
    async def fake(user_id=None, character_id=None, **kw):
        calls.append(kw); return {"ok": True}
    with _patched_registry({"foo": fake}):
        text = (
            '<function_calls><invoke name="foo">'
            '<parameter name="enabled">true</parameter>'
            '<parameter name="count">3</parameter>'
            '<parameter name="title">hello world</parameter>'
            '<parameter name="payload">{"x": 1}</parameter>'
            '</invoke></function_calls>'
        )
        _, executed = await detect_and_execute_fallback_tool_calls(text, user_id="u1")
    check("1 executed", len(executed) == 1)
    args = executed[0]["args"] if executed else {}
    check("enabled coerced to bool True", args.get("enabled") is True)
    check("count coerced to int 3", args.get("count") == 3)
    check("title kept as str", args.get("title") == "hello world")
    check("payload coerced to dict", args.get("payload") == {"x": 1})


async def test_anthropic_invoke_no_params():
    print("\n[resilience — anthropic_invoke: no params, empty args dict]")
    async def fake(user_id=None, character_id=None, **kw):
        return {"args_count": len(kw)}
    with _patched_registry({"q": fake}):
        text = '<function_calls><invoke name="q"></invoke></function_calls>'
        _, executed = await detect_and_execute_fallback_tool_calls(text, user_id="u1")
    check("empty args dict", executed and executed[0]["args"] == {})


async def test_anthropic_invoke_unknown_tool_skipped():
    print("\n[resilience — anthropic_invoke: unknown tool skipped]")
    with _patched_registry({}):
        text = '<function_calls><invoke name="ghost"></invoke></function_calls>'
        cleaned, executed = await detect_and_execute_fallback_tool_calls(text, user_id="u1")
    check("nothing executed", executed == [])
    check("block still stripped", "<invoke" not in cleaned)


# ---------------------------------------------------------------------------
# 4. Markdown JSON pattern
# ---------------------------------------------------------------------------

async def test_markdown_json_basic():
    print("\n[resilience — markdown_json fenced block]")
    calls: list = []
    async def fake(user_id=None, character_id=None, **kw):
        calls.append(kw); return {"ok": True}
    with _patched_registry({"clipboard.translate": fake}):
        text = (
            '当然可以\n'
            '```json\n'
            '{"name": "clipboard.translate", "arguments": {"item_index": 0, "target_lang": "zh"}}\n'
            '```\n'
            '稍等。'
        )
        cleaned, executed = await detect_and_execute_fallback_tool_calls(
            text, user_id="u1",
        )
    check("1 executed", len(executed) == 1)
    check("pattern=markdown_json",
          executed and executed[0]["pattern"] == "markdown_json")
    check("args present", calls and calls[0].get("target_lang") == "zh")
    check("fenced block stripped",
          "```json" not in cleaned and "```" not in cleaned)
    check("surrounding text kept",
          "当然可以" in cleaned and "稍等。" in cleaned)


async def test_markdown_json_without_name_field_ignored():
    """JSON 块没 ``name`` 字段——可能是用户 paste 的代码——不当 tool call。"""
    print("\n[resilience — markdown_json without 'name' field NOT executed]")
    async def fake(user_id=None, **_): return {"ok": True}
    with _patched_registry({"x": fake}):
        text = '```json\n{"data": [1,2,3], "comment": "just data"}\n```'
        _, executed = await detect_and_execute_fallback_tool_calls(text, user_id="u1")
    check("nothing executed (no 'name' field)", executed == [])


# ---------------------------------------------------------------------------
# 5. Pattern interaction
# ---------------------------------------------------------------------------

async def test_patterns_dont_double_execute():
    """qwen_xml 块内容若也含 markdown json（交叉），不应被两个 pattern 都执行。"""
    print("\n[resilience — patterns don't double-execute]")
    calls: list = []
    async def fake(user_id=None, **_): calls.append("c"); return {"ok": True}
    with _patched_registry({"foo": fake}):
        text = '<tool_call>{"name": "foo", "arguments": {}}</tool_call>'
        _, executed = await detect_and_execute_fallback_tool_calls(text, user_id="u1")
    check("only 1 execution", len(executed) == 1)
    check("only 1 actual call", len(calls) == 1)


async def test_real_openai_tool_call_text_no_match():
    """正经 OpenAI function_call 协议下，content 通常是空 / 普通文本。
    本兜底层不应误伤普通文本。"""
    print("\n[resilience — normal content text untouched]")
    text = "我已经把闹钟改到下午六点啦。"
    cleaned, executed = await detect_and_execute_fallback_tool_calls(
        text, user_id="u1",
    )
    check("no executions", executed == [])
    check("text untouched", cleaned == text)


# ---------------------------------------------------------------------------
# 6. user_id / character_id injection contract
# ---------------------------------------------------------------------------

async def test_user_id_cannot_be_overridden_by_args():
    """LLM 在 fallback args 里写 user_id 应被抹掉，由会话级注入决定。"""
    print("\n[resilience — user_id injection: LLM cannot override session]")
    received: list = []
    async def fake(user_id=None, **_): received.append(user_id); return {"ok": True}
    with _patched_registry({"f": fake}):
        text = '<tool_call>{"name": "f", "arguments": {"user_id": "evil"}}</tool_call>'
        await detect_and_execute_fallback_tool_calls(text, user_id="real_user")
    check("session user_id wins", received == ["real_user"])


async def test_character_id_only_injected_when_missing():
    """LLM 显式指定 character_id 优先；缺失时 session 注入。"""
    print("\n[resilience — character_id: explicit > session injection]")
    received: list = []
    async def fake(user_id=None, character_id=None, **_):
        received.append(character_id); return {"ok": True}
    with _patched_registry({"f": fake}):
        # 缺失：session 注入
        await detect_and_execute_fallback_tool_calls(
            '<tool_call>{"name": "f", "arguments": {}}</tool_call>',
            user_id="u1", character_id=42,
        )
        check("session character_id used when arg absent",
              received == [42])
        # 显式：保留
        received.clear()
        await detect_and_execute_fallback_tool_calls(
            '<tool_call>{"name": "f", "arguments": {"character_id": 99}}</tool_call>',
            user_id="u1", character_id=42,
        )
        check("explicit character_id wins", received == [99])


# ---------------------------------------------------------------------------
# 7. End-to-end: chunk 2.6 / chunk 3 footgun real fixes
# ---------------------------------------------------------------------------

async def test_e2e_snooze_via_qwen_xml():
    """模拟 chunk 2.6 footgun 4：Qwen 用 XML 输出 snooze 调用 → 现在能真触发。"""
    print("\n[resilience — chunk 2.6 footgun 4 真解：Qwen XML snooze]")
    received_minutes: list = []
    async def fake_snooze(user_id=None, character_id=None, minutes=30, **_):
        received_minutes.append(minutes); return {"ok": True, "minutes": minutes}
    with _patched_registry({"proactive.snooze_wake_call": fake_snooze}):
        text = (
            '好的，再给你赖床 5 分钟～'
            '<tool_call>{"name": "proactive.snooze_wake_call", "arguments": {"minutes": 5}}</tool_call>'
        )
        cleaned, executed = await detect_and_execute_fallback_tool_calls(
            text, user_id="default", character_id=1,
        )
    check("snooze真实触发 (chunk 2.6 quirk 真解)",
          received_minutes == [5])
    check("回复文本无 XML 残骸", "<tool_call>" not in cleaned)
    check("用户看到的回复保留",
          "好的，再给你赖床 5 分钟～" in cleaned or "好的" in cleaned)


async def test_e2e_translate_via_anthropic_invoke():
    print("\n[resilience — chunk 3 footgun 7 真解：Anthropic invoke clipboard.translate]")
    received: list = []
    async def fake_translate(user_id=None, character_id=None, **kw):
        received.append(kw); return {"translation": "你好"}
    with _patched_registry({"clipboard.translate": fake_translate}):
        text = (
            '好的，'
            '<function_calls>'
            '<invoke name="clipboard.translate">'
            '<parameter name="item_index">0</parameter>'
            '<parameter name="target_lang">zh</parameter>'
            '</invoke>'
            '</function_calls>'
            '翻好啦。'
        )
        cleaned, executed = await detect_and_execute_fallback_tool_calls(
            text, user_id="u1",
        )
    check("translate真实触发 (chunk 3 quirk 真解)",
          received and received[0].get("target_lang") == "zh")
    check("invoke block stripped", "<invoke" not in cleaned and "</function_calls>" not in cleaned)


# ---------------------------------------------------------------------------
# 8. logging
# ---------------------------------------------------------------------------

async def test_logger_emits_fallback_path():
    print("\n[resilience — logger emits [tool_resilience] fallback=...]")
    import logging
    from io import StringIO
    handler = logging.StreamHandler(StringIO())
    handler.setLevel(logging.INFO)
    fmt = logging.Formatter("%(message)s")
    handler.setFormatter(fmt)
    target_logger = logging.getLogger("backend.agents.tool_call_resilience")
    target_logger.addHandler(handler)
    target_logger.setLevel(logging.INFO)

    async def fake(user_id=None, **_): return {"ok": True}
    with _patched_registry({"snooze": fake}):
        await detect_and_execute_fallback_tool_calls(
            '<tool_call>{"name": "snooze", "arguments": {}}</tool_call>',
            user_id="u1",
        )
    out = handler.stream.getvalue()
    check("log line contains 'fallback=qwen_xml'",
          "fallback=qwen_xml" in out, f"got: {out!r}")
    target_logger.removeHandler(handler)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

async def main():
    await test_coerce_param_value()
    await test_qwen_xml_basic()
    await test_qwen_xml_double_encoded_arguments()
    await test_qwen_xml_unknown_tool_skipped()
    await test_qwen_xml_invalid_json_skipped()
    await test_qwen_xml_multiple_calls()
    await test_qwen_xml_capability_exec_failure_caught()
    await test_anthropic_invoke_basic()
    await test_anthropic_invoke_multiple_params()
    await test_anthropic_invoke_no_params()
    await test_anthropic_invoke_unknown_tool_skipped()
    await test_markdown_json_basic()
    await test_markdown_json_without_name_field_ignored()
    await test_patterns_dont_double_execute()
    await test_real_openai_tool_call_text_no_match()
    await test_user_id_cannot_be_overridden_by_args()
    await test_character_id_only_injected_when_missing()
    await test_e2e_snooze_via_qwen_xml()
    await test_e2e_translate_via_anthropic_invoke()
    await test_logger_emits_fallback_path()

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
    asyncio.run(main())
