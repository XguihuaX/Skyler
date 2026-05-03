"""Tests for backend/agents/memory.py and the new services.py CRUD functions."""
import asyncio
import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

# ── bootstrap in-memory DB ──────────────────────────────────────────────────
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
import backend.database as _db_mod

_ENGINE = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
_SESSION = sessionmaker(_ENGINE, class_=AsyncSession, expire_on_commit=False)
_db_mod.engine = _ENGINE
_db_mod.AsyncSessionLocal = _SESSION

from backend.database import Base
from backend.database import models as _m  # noqa – registers ORM

# Import MemoryAgent AFTER DB patch
import backend.agents.memory as _mem_agent_mod
from backend.agents.memory import (
    MemoryAgent,
    _parse_dt,
    _memory_to_dict,
    _personality_to_dict,
    _todo_to_dict,
)
from backend.agents.base import IAgent

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))


# ── DB setup ─────────────────────────────────────────────────────────────────

async def setup():
    async with _ENGINE.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with _SESSION() as s:
        from backend.database.services import create_user
        await create_user(s, "mem_u", "Tester")

    # Stub out add_memory_with_embedding to avoid loading sentence-transformers
    async def _stub_embed(user_id, content, type, role, expires_at=None):
        async with _SESSION() as s:
            from backend.database.services import add_memory as _svc_add
            await _svc_add(s, user_id=user_id, role=role, type=type, content=content,
                           expires_at=expires_at)
    _mem_agent_mod.add_memory_with_embedding = _stub_embed


# ── helpers ───────────────────────────────────────────────────────────────────

def _msg(function: str, args: dict) -> dict:
    return {"agent": "MemoryAgent", "payload": {"function": function, "args": args}}

DUE = (datetime.utcnow() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")


# ── 1. Utility helpers ────────────────────────────────────────────────────────

async def test_parse_dt():
    print("\n[_parse_dt]")
    dt = _parse_dt("2026-04-29 08:00:00")
    check("parses YYYY-MM-DD HH:MM:SS",    isinstance(dt, datetime))
    check("correct year",                  dt.year == 2026)
    check("None input → None",             _parse_dt(None) is None)
    try:
        _parse_dt("not-a-date")
        check("bad string raises ValueError", False)
    except ValueError:
        check("bad string raises ValueError", True)


# ── 2. New services — search_memory ──────────────────────────────────────────

async def test_search_memory():
    print("\n[search_memory service]")
    from backend.database.services import add_memory, search_memory

    async with _SESSION() as s:
        await add_memory(s, "mem_u", "user", "fact",    "用户喜欢爵士乐")
        await add_memory(s, "mem_u", "user", "emotion", "用户今天很开心")
        await add_memory(s, "mem_u", "system", "daily", "每天早上运动")

    async with _SESSION() as s:
        all_rows  = await search_memory(s, "mem_u")
        fact_rows = await search_memory(s, "mem_u", type="fact")
        user_rows = await search_memory(s, "mem_u", role="user")
        kw_rows   = await search_memory(s, "mem_u", content="爵士")

    check("all rows returned",           len(all_rows) >= 3)
    check("filter by type=fact",         all(r.type == "fact"   for r in fact_rows))
    check("filter by role=user",         all(r.role == "user"   for r in user_rows))
    check("substring content filter",    len(kw_rows) >= 1 and "爵士" in kw_rows[0].content)

    # time range filter
    future = (datetime.utcnow() + timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
    async with _SESSION() as s:
        none_rows = await search_memory(s, "mem_u", start_time=_parse_dt(future))
    check("future start_time → empty",   len(none_rows) == 0)


# ── 3. New services — personality ────────────────────────────────────────────

async def test_personality_services():
    print("\n[delete_personality / search_personality services]")
    from backend.database.services import upsert_personality, delete_personality, search_personality

    async with _SESSION() as s:
        await upsert_personality(s, "mem_u", "preference", "music",    "爵士")
        await upsert_personality(s, "mem_u", "preference", "coffee",   "拿铁")
        await upsert_personality(s, "mem_u", "personality", "openness","high")

    async with _SESSION() as s:
        all_p   = await search_personality(s, "mem_u")
        pref    = await search_personality(s, "mem_u", type="preference")
        by_tag  = await search_personality(s, "mem_u", tag="music")

    check("all rows returned",           len(all_p) >= 3)
    check("filter by type=preference",   all(r.type == "preference" for r in pref))
    check("filter by tag=music",         len(by_tag) == 1 and by_tag[0].tag == "music")

    async with _SESSION() as s:
        await delete_personality(s, "mem_u", "preference", "coffee")
        remaining = await search_personality(s, "mem_u", tag="coffee")
    check("delete removes row",          len(remaining) == 0)

    async with _SESSION() as s:
        await delete_personality(s, "mem_u", "preference", "ghost")  # no-op
    check("delete on missing row is no-op", True)


# ── 4. New services — todo ────────────────────────────────────────────────────

async def test_todo_services():
    print("\n[delete_todo / search_todo services]")
    from backend.database.services import create_todo, delete_todo, search_todo

    due = datetime.utcnow() + timedelta(hours=2)
    async with _SESSION() as s:
        t1 = await create_todo(s, "mem_u", "alarm",    "alarm",    due)
        t2 = await create_todo(s, "mem_u", "schedule", "meeting",  due, "project sync")

    async with _SESSION() as s:
        all_t   = await search_todo(s, "mem_u")
        alarm_t = await search_todo(s, "mem_u", owner_type="alarm")
        kw_t    = await search_todo(s, "mem_u", description="project")

    check("all todos returned",         len(all_t) >= 2)
    check("filter by owner_type",       all(t.owner_type == "alarm" for t in alarm_t))
    check("description substring match",len(kw_t) >= 1)

    async with _SESSION() as s:
        await delete_todo(s, "mem_u", t1.id)
        after = await search_todo(s, "mem_u", id=t1.id)
    check("delete_todo removes row",    len(after) == 0)

    async with _SESSION() as s:
        await delete_todo(s, "mem_u", 99999)  # no-op
    check("delete_todo on missing is no-op", True)


# ── 5. MemoryAgent.handle() — routing ─────────────────────────────────────────

async def test_handle_add_memory():
    print("\n[MemoryAgent — add_memory]")
    agent = MemoryAgent()
    r = await agent.handle(_msg("add_memory", {
        "user_id": "mem_u", "role": "user", "type": "fact", "content": "喜欢猫"
    }))
    check("status success",   r["status"] == "success")
    check("agent label",      r["agent"] == "MemoryAgent")
    check("message returned", "message" in r["payload"]["result"])


async def test_handle_search_memory():
    print("\n[MemoryAgent — search_memory]")
    agent = MemoryAgent()
    r = await agent.handle(_msg("search_memory", {"user_id": "mem_u", "type": "fact"}))
    check("status success",   r["status"] == "success")
    check("result is list",   isinstance(r["payload"]["result"], list))
    if r["payload"]["result"]:
        row = r["payload"]["result"][0]
        check("row has required keys",
              all(k in row for k in ("id", "user_id", "role", "type", "content")))


async def test_handle_delete_memory():
    print("\n[MemoryAgent — delete_memory]")
    from backend.database.services import add_memory, search_memory
    async with _SESSION() as s:
        m = await add_memory(s, "mem_u", "user", "daily", "to be deleted")

    agent = MemoryAgent()
    r = await agent.handle(_msg("delete_memory", {"user_id": "mem_u", "memory_id": m.id}))
    check("status success", r["status"] == "success")

    async with _SESSION() as s:
        after = await search_memory(s, "mem_u", content="to be deleted")
    check("row removed from DB", len(after) == 0)


async def test_handle_personality_ops():
    print("\n[MemoryAgent — personality CRUD]")
    agent = MemoryAgent()

    # add
    r = await agent.handle(_msg("add_personality", {
        "user_id": "mem_u", "type": "preference", "tag": "tea", "content": "绿茶"
    }))
    check("add_personality success",  r["status"] == "success")
    row = r["payload"]["result"]
    check("returned row has tag",     row.get("tag") == "tea")

    # search
    r = await agent.handle(_msg("search_personality", {
        "user_id": "mem_u", "type": "preference"
    }))
    check("search_personality success", r["status"] == "success")
    check("result is list",             isinstance(r["payload"]["result"], list))

    # delete
    r = await agent.handle(_msg("delete_personality", {
        "user_id": "mem_u", "type": "preference", "tag": "tea"
    }))
    check("delete_personality success", r["status"] == "success")


async def test_handle_todo_ops():
    print("\n[MemoryAgent — todo CRUD]")
    agent = MemoryAgent()

    # add_todo
    r = await agent.handle(_msg("add_todo", {
        "user_id": "mem_u", "owner_type": "alarm",
        "title": "morning run", "due_time": DUE,
        "description": "5km", "status": "pending",
    }))
    check("add_todo success",      r["status"] == "success")
    todo_id = r["payload"]["result"]["id"]
    check("todo id assigned",      todo_id is not None)

    # search_todo
    r = await agent.handle(_msg("search_todo", {
        "user_id": "mem_u", "owner_type": "alarm"
    }))
    check("search_todo success",   r["status"] == "success")
    check("result is list",        isinstance(r["payload"]["result"], list))

    # update_todo_status
    r = await agent.handle(_msg("update_todo_status", {
        "todo_id": todo_id, "status": "completed"
    }))
    check("update_todo_status success", r["status"] == "success")

    # delete_todo
    r = await agent.handle(_msg("delete_todo", {"user_id": "mem_u", "id": todo_id}))
    check("delete_todo success",   r["status"] == "success")


# ── 6. Error handling ─────────────────────────────────────────────────────────

async def test_validation_errors():
    print("\n[MemoryAgent — validation errors]")
    agent = MemoryAgent()

    # Missing function
    r = await agent.handle({"payload": {}})
    check("missing function → error",      r["status"] == "error")

    # Unknown function
    r = await agent.handle(_msg("do_something_fake", {}))
    check("unknown function → error",      r["status"] == "error")

    # Missing required arg
    r = await agent.handle(_msg("add_memory", {"user_id": "u"}))
    check("missing role/type/content → error", r["status"] == "error")

    r = await agent.handle(_msg("add_todo", {"user_id": "mem_u", "owner_type": "alarm"}))
    check("missing title/due_time → error", r["status"] == "error")

    r = await agent.handle(_msg("delete_memory", {"user_id": "mem_u"}))
    check("missing memory_id → error",     r["status"] == "error")


# ── 7. IAgent compliance ──────────────────────────────────────────────────────

async def test_iagent_compliance():
    print("\n[IAgent compliance]")
    check("subclasses IAgent",   issubclass(MemoryAgent, IAgent))
    check("handle is coroutine", asyncio.iscoroutinefunction(MemoryAgent.handle))


# ── main ──────────────────────────────────────────────────────────────────────

async def main():
    await setup()
    await test_parse_dt()
    await test_search_memory()
    await test_personality_services()
    await test_todo_services()
    await test_handle_add_memory()
    await test_handle_search_memory()
    await test_handle_delete_memory()
    await test_handle_personality_ops()
    await test_handle_todo_ops()
    await test_validation_errors()
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
