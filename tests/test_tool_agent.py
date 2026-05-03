"""Tests for ToolAgent, ToolRegistry, and built-in tools."""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.tools.registry import ToolRegistry
from backend.tools.builtin import switch_character, clear_short_term
from backend.agents.tool import ToolAgent
from backend.agents.base import IAgent
from backend.memory.short_term import short_term_memory
from backend.config.prompt_manager import prompt_manager

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))


def _msg(function: str, args: dict) -> dict:
    return {"agent": "ToolAgent", "payload": {"function": function, "args": args}}


# ---------------------------------------------------------------------------
# 1. ToolRegistry
# ---------------------------------------------------------------------------

async def test_registry_basics():
    print("\n[ToolRegistry — basics]")

    # builtins auto-registered on import
    tools = ToolRegistry.list_tools()
    check("switch_character registered", "switch_character" in tools)
    check("clear_short_term registered", "clear_short_term" in tools)

    # get() returns the callable
    fn = ToolRegistry.get("switch_character")
    check("get returns callable", callable(fn))

    # unknown tool raises KeyError
    try:
        ToolRegistry.get("nonexistent_tool")
        check("unknown tool raises KeyError", False)
    except KeyError:
        check("unknown tool raises KeyError", True)


async def test_registry_custom_tool():
    print("\n[ToolRegistry — custom tool registration]")

    # register a sync callable
    def _sync_add(a: int, b: int) -> int:
        return a + b

    ToolRegistry.register("_test_sync_add", _sync_add)
    result = await ToolRegistry.call("_test_sync_add", a=3, b=4)
    check("sync callable invoked", result == 7)

    # register an async callable
    async def _async_greet(name: str) -> str:
        return f"hello {name}"

    ToolRegistry.register("_test_async_greet", _async_greet)
    result = await ToolRegistry.call("_test_async_greet", name="world")
    check("async callable invoked", result == "hello world")

    # wrong kwargs → TypeError propagates
    try:
        await ToolRegistry.call("_test_sync_add", x=1)
        check("wrong kwargs raises TypeError", False)
    except TypeError:
        check("wrong kwargs raises TypeError", True)


# ---------------------------------------------------------------------------
# 2. Built-in: switch_character
# ---------------------------------------------------------------------------

async def test_builtin_switch_character():
    print("\n[builtin — switch_character]")

    # valid character
    result = await switch_character("u_tool", "荧")
    check("switch success returns dict",    isinstance(result, dict))
    check("message key present",           "message" in result)
    check("character_id echoed back",      result.get("character_id") == "荧")
    check("prompt_manager updated",
          prompt_manager.get_current_character("u_tool") == "荧")

    # restore to 默认
    await switch_character("u_tool", "默认")
    check("switch back to 默认",
          prompt_manager.get_current_character("u_tool") == "默认")

    # unknown character raises ValueError
    try:
        await switch_character("u_tool", "不存在角色")
        check("unknown character raises ValueError", False)
    except ValueError as exc:
        check("unknown character raises ValueError", True, str(exc))


# ---------------------------------------------------------------------------
# 3. Built-in: clear_short_term
# ---------------------------------------------------------------------------

async def test_builtin_clear_short_term():
    print("\n[builtin — clear_short_term]")

    # seed some history
    await short_term_memory.add("u_clear", "user", "你好")
    await short_term_memory.add("u_clear", "assistant", "你好！")
    count_before = await short_term_memory.count("u_clear")
    check("seeded 2 turns", count_before == 2)

    result = await clear_short_term("u_clear")
    check("returns dict",         isinstance(result, dict))
    check("message key present",  "message" in result)

    count_after = await short_term_memory.count("u_clear")
    check("buffer cleared",       count_after == 0)

    # clearing an empty buffer is idempotent
    result2 = await clear_short_term("u_clear_empty")
    check("clear on unknown user is no-op", isinstance(result2, dict))


# ---------------------------------------------------------------------------
# 4. ToolAgent.handle()
# ---------------------------------------------------------------------------

async def test_handle_switch_character():
    print("\n[ToolAgent — switch_character]")
    agent = ToolAgent()

    r = await agent.handle(_msg("switch_character", {
        "user_id": "u_agent", "character_id": "凝光"
    }))
    check("status success",        r["status"] == "success")
    check("agent label",           r["agent"] == "ToolAgent")
    check("result has character_id",
          r["payload"]["result"].get("character_id") == "凝光")

    # unknown character → error
    r = await agent.handle(_msg("switch_character", {
        "user_id": "u_agent", "character_id": "幻想角色"
    }))
    check("unknown char → error",  r["status"] == "error")
    check("error message present", "error" in r["payload"])


async def test_handle_clear_short_term():
    print("\n[ToolAgent — clear_short_term]")
    agent = ToolAgent()

    await short_term_memory.add("u_agent2", "user", "测试消息")
    r = await agent.handle(_msg("clear_short_term", {"user_id": "u_agent2"}))
    check("status success",   r["status"] == "success")
    check("message in result", "message" in r["payload"]["result"])
    count = await short_term_memory.count("u_agent2")
    check("buffer cleared",   count == 0)


async def test_handle_errors():
    print("\n[ToolAgent — error handling]")
    agent = ToolAgent()

    # missing function
    r = await agent.handle({"payload": {}})
    check("missing function → error",   r["status"] == "error")
    check("agent label on error",       r["agent"] == "ToolAgent")

    # unknown tool name
    r = await agent.handle(_msg("nonexistent_tool", {}))
    check("unknown tool → error",       r["status"] == "error")

    # wrong argument types (missing required kwarg)
    r = await agent.handle(_msg("switch_character", {"user_id": "u_agent"}))
    check("missing character_id → error", r["status"] == "error")

    # null args dict coerced to {}
    r = await agent.handle({"payload": {"function": "nonexistent", "args": None}})
    check("null args → error (unknown tool)", r["status"] == "error")


# ---------------------------------------------------------------------------
# 5. IAgent compliance
# ---------------------------------------------------------------------------

async def test_iagent_compliance():
    print("\n[IAgent compliance]")
    check("subclasses IAgent",    issubclass(ToolAgent, IAgent))
    check("handle is coroutine",  asyncio.iscoroutinefunction(ToolAgent.handle))


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

async def main():
    await test_registry_basics()
    await test_registry_custom_tool()
    await test_builtin_switch_character()
    await test_builtin_clear_short_term()
    await test_handle_switch_character()
    await test_handle_clear_short_term()
    await test_handle_errors()
    await test_iagent_compliance()

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
