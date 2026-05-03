"""Database layer tests: models.py + services.py"""
import asyncio
import sys
import os
from datetime import datetime, timedelta

# Make project root importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.database import models  # noqa: registers ORM classes
from backend.database.services import (
    create_user, get_user,
    add_memory, get_all_memories, get_recent_memories, delete_memory,
    upsert_personality, get_personality,
    create_todo, get_pending_todos, get_todos, update_todo_status,
    add_chat_history, get_chat_history,
)

TEST_DB = "sqlite+aiosqlite:///:memory:"

engine = create_async_engine(TEST_DB, echo=False)
AsyncTestSession = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"

results = []

def check(name: str, condition: bool, detail: str = ""):
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append(condition)

async def setup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def test_users():
    print("\n[Users]")
    async with AsyncTestSession() as s:
        u = await create_user(s, "u1", "Alice")
        check("create_user returns User", u.user_id == "u1")
        check("user_name stored", u.user_name == "Alice")

        found = await get_user(s, "u1")
        check("get_user finds existing", found is not None and found.user_id == "u1")

        missing = await get_user(s, "nobody")
        check("get_user returns None for unknown", missing is None)

async def test_memory():
    print("\n[Memory]")
    async with AsyncTestSession() as s:
        await create_user(s, "u2", "Bob")

        m1 = await add_memory(s, "u2", "user", "fact", "likes cats")
        check("add_memory returns Memory", m1.id is not None)
        check("content stored", m1.content == "likes cats")
        check("embedding None by default", m1.embedding is None)

        import numpy as np
        vec = np.array([0.1, 0.2, 0.3], dtype=np.float32)
        m2 = await add_memory(s, "u2", "system", "emotion", "happy", embedding=vec.tobytes())
        check("add_memory with embedding", m2.embedding is not None)

        all_mems = await get_all_memories(s, "u2")
        check("get_all_memories returns 2 rows", len(all_mems) == 2)

        recent = await get_recent_memories(s, "u2", limit=1)
        check("get_recent_memories limit=1 returns 1", len(recent) == 1)
        check("recent is chronological (oldest first within window)", recent[0].content in ["likes cats", "happy"])

        await delete_memory(s, m1.id)
        after_del = await get_all_memories(s, "u2")
        check("delete_memory removes row", len(after_del) == 1)

        await delete_memory(s, 9999)  # silent no-op
        check("delete_memory on missing id is no-op", True)

async def test_personality():
    print("\n[Personality]")
    async with AsyncTestSession() as s:
        await create_user(s, "u3", "Carol")

        p = await upsert_personality(s, "u3", "personality", "openness", "high")
        check("upsert creates new row", p.content == "high")

        p2 = await upsert_personality(s, "u3", "personality", "openness", "very high")
        check("upsert updates existing row", p2.content == "very high")

        await upsert_personality(s, "u3", "preference", "music", "jazz")
        rows = await get_personality(s, "u3")
        check("get_personality returns 2 rows", len(rows) == 2)

async def test_todos():
    print("\n[Todos]")
    async with AsyncTestSession() as s:
        await create_user(s, "u4", "Dave")

        due = datetime.utcnow() + timedelta(hours=1)
        t = await create_todo(s, "u4", "alarm", "Wake up", due, "morning alarm")
        check("create_todo returns Todo", t.id is not None)
        check("status defaults to pending", t.status == "pending")
        check("description stored", t.description == "morning alarm")

        pending = await get_pending_todos(s, "u4")
        check("get_pending_todos finds 1", len(pending) == 1)

        await update_todo_status(s, t.id, "completed")
        pending_after = await get_pending_todos(s, "u4")
        check("update_todo_status removes from pending", len(pending_after) == 0)

        all_todos = await get_todos(s, "u4")
        check("get_todos (no filter) returns 1", len(all_todos) == 1)

        completed = await get_todos(s, "u4", status="completed")
        check("get_todos filtered by completed returns 1", len(completed) == 1)

        await update_todo_status(s, 9999, "failed")  # silent no-op
        check("update_todo_status on missing id is no-op", True)

async def test_chat_history():
    print("\n[ChatHistory]")
    async with AsyncTestSession() as s:
        await create_user(s, "u5", "Eve")

        c1 = await add_chat_history(s, "u5", "user", "hello")
        c2 = await add_chat_history(s, "u5", "assistant", "hi there")
        check("add_chat_history user", c1.role == "user")
        check("add_chat_history assistant", c2.role == "assistant")

        hist = await get_chat_history(s, "u5")
        check("get_chat_history returns 2 in order", len(hist) == 2 and hist[0].content == "hello")

        hist_limited = await get_chat_history(s, "u5", limit=1)
        check("get_chat_history limit=1 returns 1", len(hist_limited) == 1)

async def main():
    await setup()
    await test_users()
    await test_memory()
    await test_personality()
    await test_todos()
    await test_chat_history()

    total = len(results)
    passed = sum(results)
    print(f"\n{'='*40}")
    print(f"Results: {passed}/{total} passed")
    if passed < total:
        print("SOME TESTS FAILED")
        sys.exit(1)
    else:
        print("ALL TESTS PASSED")

if __name__ == "__main__":
    asyncio.run(main())
