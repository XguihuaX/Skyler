"""Tests for ws.py helper functions and main.py startup logic.

WebSocket connection itself is not tested here (requires ASGI test client);
the helpers that form the business logic are tested in isolation.
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

# ── Bootstrap in-memory DB ───────────────────────────────────────────────────
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
import backend.database as _db_mod

_ENGINE  = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
_SESSION = sessionmaker(_ENGINE, class_=AsyncSession, expire_on_commit=False)
_db_mod.engine          = _ENGINE
_db_mod.AsyncSessionLocal = _SESSION

from backend.database import Base
from backend.database import models as _m  # noqa — registers ORM

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))


async def setup():
    async with _ENGINE.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


# ---------------------------------------------------------------------------
# Import helpers after DB patch
# ---------------------------------------------------------------------------

import backend.routes.ws as _ws_mod
from backend.routes.ws import (
    _run_plan,
    _aggregate_tool_results,
    _update_memory,
    _default_user_id,
)
from backend.memory.short_term import short_term_memory
from backend.database.services import create_user, get_chat_history


# ---------------------------------------------------------------------------
# 1. _default_user_id
# ---------------------------------------------------------------------------

def test_default_user_id():
    print("\n[_default_user_id]")
    uid = _default_user_id()
    check("returns a string",      isinstance(uid, str))
    check("non-empty",             len(uid) > 0)
    # With our config.yaml it should be "default"
    check("matches config",        uid == "default")


# ---------------------------------------------------------------------------
# 2. _run_plan
# ---------------------------------------------------------------------------

async def test_run_plan_unknown_agent():
    print("\n[_run_plan — unknown agent]")
    plan = {"agent": "GhostAgent", "payload": {}}
    result = await _run_plan(plan)
    check("status error",   result["status"] == "error")
    check("agent echoed",   result["agent"] == "GhostAgent")
    check("error message",  "Unknown agent" in result["payload"]["error"])


async def test_run_plan_memory_agent():
    print("\n[_run_plan — MemoryAgent stub]")

    # Install a fake MemoryAgent that always returns success
    class _FakeAgent:
        async def handle(self, msg):
            return {"status": "success", "agent": "MemoryAgent",
                    "payload": {"result": {"message": "ok"}}}

    original = _ws_mod._plan_agents.get("MemoryAgent")
    _ws_mod._plan_agents["MemoryAgent"] = _FakeAgent()
    try:
        plan   = {"agent": "MemoryAgent", "payload": {"function": "search_memory",
                                                       "args": {"user_id": "u"}}}
        result = await _run_plan(plan)
        check("dispatched to MemoryAgent", result["status"] == "success")
        check("agent label correct",       result["agent"] == "MemoryAgent")
    finally:
        _ws_mod._plan_agents["MemoryAgent"] = original


# ---------------------------------------------------------------------------
# 3. _aggregate_tool_results
# ---------------------------------------------------------------------------

def test_aggregate_empty():
    print("\n[_aggregate_tool_results — empty / all errors]")
    check("empty list",   _aggregate_tool_results([]) == "")
    check("only exceptions",
          _aggregate_tool_results([RuntimeError("x"), ValueError("y")]) == "")


def test_aggregate_memory_search_result():
    print("\n[_aggregate_tool_results — MemoryAgent search result]")
    # MemoryAgent list results (search_memory / search_todo etc.) are injected into context.
    mr = {
        "status": "success",
        "agent":  "MemoryAgent",
        "payload": {
            "result": [
                {"id": 1, "role": "user", "type": "fact", "content": "我喜欢喝咖啡"},
            ]
        },
    }
    text = _aggregate_tool_results([mr])
    check("memory result in output",    "咖啡" in text)
    check("wrapped in query label",     "记忆查询结果" in text)


def test_aggregate_tool_confirmation():
    print("\n[_aggregate_tool_results — ToolAgent confirmation]")
    tr = {
        "status": "success",
        "agent":  "ToolAgent",
        "payload": {"result": {"message": "角色已切换为荧", "character_id": "荧"}},
    }
    text = _aggregate_tool_results([tr])
    check("switch message included", "角色" in text)


def test_aggregate_memory_write_dropped():
    print("\n[_aggregate_tool_results — MemoryAgent write result dropped]")
    # Write operations (add/delete) return a dict — not injected into context.
    mr = {
        "status": "success",
        "agent":  "MemoryAgent",
        "payload": {"result": {"message": "memory added"}},
    }
    text = _aggregate_tool_results([mr])
    check("MemoryAgent write result excluded", text == "")


def test_aggregate_mixed():
    print("\n[_aggregate_tool_results — mixed results]")
    results = [
        RuntimeError("net error"),                           # exception → skip
        {"status": "error", "agent": "MemoryAgent",         # error status → skip
         "payload": {"error": "timeout"}},
        {"status": "success", "agent": "MemoryAgent",       # list → inject
         "payload": {"result": [{"content": "我喜欢咖啡"}]}},
        {"status": "success", "agent": "MemoryAgent",       # dict write → dropped
         "payload": {"result": {"message": "memory added"}}},
        {"status": "success", "agent": "ToolAgent",
         "payload": {"result": {"message": "角色已切换"}}},
    ]
    text = _aggregate_tool_results(results)
    check("memory search result included",  "咖啡" in text)
    check("tool confirmation included",     "角色" in text)
    check("memory write result excluded",   "memory added" not in text)
    check("error skipped",                  "timeout" not in text)


# ---------------------------------------------------------------------------
# 4. _update_memory
# ---------------------------------------------------------------------------

async def test_update_memory():
    print("\n[_update_memory]")

    # Create a test user in the DB
    async with _SESSION() as s:
        await create_user(s, "ws_u", "WSTester")

    # Reset short-term buffer
    await short_term_memory.clear("ws_u")

    await _update_memory("ws_u", "用户说的话", "助手的回复")

    # Short-term buffer should have 2 new turns
    count = await short_term_memory.count("ws_u")
    check("2 turns added to short-term", count == 2)

    turns = await short_term_memory.get("ws_u")
    check("user turn correct",     turns[0] == {"role": "user",      "content": "用户说的话"})
    check("assistant turn correct",turns[1] == {"role": "assistant", "content": "助手的回复"})

    # Chat history should be in DB
    async with _SESSION() as s:
        history = await get_chat_history(s, "ws_u", limit=10)
    check("2 rows in chat_history", len(history) == 2)
    check("user row",       history[0].role == "user"      and history[0].content == "用户说的话")
    check("assistant row",  history[1].role == "assistant" and history[1].content == "助手的回复")


async def test_update_memory_does_not_raise():
    print("\n[_update_memory — non-existing user is handled]")
    # DB will error on FK violation; _update_memory should catch it
    try:
        await _update_memory("nonexistent_user_xyz", "hi", "hello")
        check("no exception raised", True)
    except Exception:
        check("no exception raised", False)


# ---------------------------------------------------------------------------
# 5. main.py lifespan helpers (DB + user creation)
# ---------------------------------------------------------------------------

async def test_main_startup_creates_user():
    print("\n[main.py lifespan — default user creation]")
    from backend.database.services import get_user, create_user

    # Simulate: user does not exist → create
    async with _SESSION() as s:
        user = await get_user(s, "default_test")
    check("user absent before create", user is None)

    async with _SESSION() as s:
        await create_user(s, "default_test", "Momo")

    async with _SESSION() as s:
        user = await get_user(s, "default_test")
    check("user present after create",  user is not None)
    check("user_name correct",          user.user_name == "Momo")


async def test_main_startup_restores_memory():
    print("\n[main.py lifespan — short-term memory restore from chat_history]")
    from backend.database.services import add_chat_history

    async with _SESSION() as s:
        await create_user(s, "restore_u", "Tester")
        await add_chat_history(s, "restore_u", "user",      "你好")
        await add_chat_history(s, "restore_u", "assistant", "你好！")

    await short_term_memory.clear("restore_u")

    # Simulate the lifespan restore logic
    async with _SESSION() as s:
        history = await get_chat_history(s, "restore_u", limit=20)
    for msg in history:
        await short_term_memory.add("restore_u", msg.role, msg.content)

    count = await short_term_memory.count("restore_u")
    check("2 turns restored",      count == 2)
    turns = await short_term_memory.get("restore_u")
    check("first turn is user",    turns[0]["role"] == "user")
    check("second turn assistant", turns[1]["role"] == "assistant")


# ---------------------------------------------------------------------------
# 6. Config switches in ChatAgent._build_messages
# ---------------------------------------------------------------------------

async def test_memory_switches():
    print("\n[ChatAgent — memory config switches]")
    import backend.agents.chat as _chat_mod
    from backend.agents.chat import _build_messages

    called = {"lt": False, "profile": False}

    original_search = _chat_mod.search_relevant_memories
    original_getper = _chat_mod.get_personality

    async def _fake_search(*a, **kw):
        called["lt"] = True
        return []

    async def _fake_getper(session, uid):
        called["profile"] = True
        return []

    _chat_mod.search_relevant_memories = _fake_search
    _chat_mod.get_personality          = _fake_getper

    # Create a user so the DB session doesn't error
    async with _SESSION() as s:
        try:
            from backend.database.services import create_user as _cu
            await _cu(s, "cfg_u", "CfgTester")
        except Exception:
            pass

    try:
        # Both enabled
        _chat_mod.config_yaml = {"memory": {"long_term_enabled": True, "profile_enabled": True}}
        await _build_messages("cfg_u", "test", None)
        check("long_term called when enabled",  called["lt"])
        check("profile called when enabled",    called["profile"])

        # Both disabled
        called.update({"lt": False, "profile": False})
        _chat_mod.config_yaml = {"memory": {"long_term_enabled": False, "profile_enabled": False}}
        await _build_messages("cfg_u", "test", None)
        check("long_term skipped when disabled",  not called["lt"])
        check("profile skipped when disabled",    not called["profile"])
    finally:
        _chat_mod.search_relevant_memories = original_search
        _chat_mod.get_personality          = original_getper
        from backend.config import config_yaml
        _chat_mod.config_yaml              = config_yaml


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

async def main():
    await setup()

    test_default_user_id()
    await test_run_plan_unknown_agent()
    await test_run_plan_memory_agent()
    test_aggregate_empty()
    test_aggregate_memory_search_result()
    test_aggregate_tool_confirmation()
    test_aggregate_memory_write_dropped()
    test_aggregate_mixed()
    await test_update_memory()
    await test_update_memory_does_not_raise()
    await test_main_startup_creates_user()
    await test_main_startup_restores_memory()
    await test_memory_switches()

    total  = len(results)
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
