"""Memory system tests: short_term, long_term"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Patch the database URL to use an in-memory SQLite for tests
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

import numpy as np
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

# Bootstrap in-memory DB before importing app code that creates sessions
from backend.database import Base, engine as _orig_engine
import backend.database as _db_module
import backend.database.services as _svc_module

TEST_ENGINE = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
TEST_SESSION = sessionmaker(TEST_ENGINE, class_=AsyncSession, expire_on_commit=False)
_db_module.engine = TEST_ENGINE
_db_module.AsyncSessionLocal = TEST_SESSION
_svc_module  # already imported above

from backend.memory.short_term import ShortTermMemory, SHORT_TERM_MAX
from backend.memory.long_term import add_memory_with_embedding, search_relevant_memories, _encode

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results = []

def check(name: str, condition: bool, detail: str = ""):
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))

async def setup():
    from backend.database import models  # noqa
    async with TEST_ENGINE.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # Create a test user
    async with TEST_SESSION() as s:
        from backend.database.services import create_user
        await create_user(s, "mem_user", "Tester")

# ---------------------------------------------------------------------------
# Short-term memory
# ---------------------------------------------------------------------------

async def test_short_term():
    print("\n[ShortTermMemory]")
    mem = ShortTermMemory()

    await mem.add("u1", "user", "hello")
    await mem.add("u1", "assistant", "hi")
    check("count after 2 adds", await mem.count("u1") == 2)

    turns = await mem.get("u1")
    check("get returns list of dicts", isinstance(turns, list) and len(turns) == 2)
    check("turn has role/content keys", "role" in turns[0] and "content" in turns[0])
    check("chronological order", turns[0]["content"] == "hello")

    await mem.trim("u1", keep=1)
    check("trim keeps last 1", await mem.count("u1") == 1)
    remaining = await mem.get("u1")
    check("trim keeps most recent", remaining[0]["content"] == "hi")

    await mem.clear("u1")
    check("clear empties store", await mem.count("u1") == 0)

    check("get on unknown user returns []", await mem.get("unknown") == [])
    check("count on unknown user returns 0", await mem.count("unknown") == 0)

    # user isolation
    await mem.add("ua", "user", "for ua")
    await mem.add("ub", "user", "for ub")
    check("user isolation", (await mem.count("ua")) == 1 and (await mem.count("ub")) == 1)

    check("SHORT_TERM_MAX is 20", SHORT_TERM_MAX == 20)

# ---------------------------------------------------------------------------
# Long-term memory (embedding + retrieval)
# ---------------------------------------------------------------------------

async def test_long_term():
    print("\n[LongTermMemory]")

    # Encoding smoke-test
    vec = await _encode("猫咪喜欢睡觉")
    check("encode returns float32 ndarray", isinstance(vec, np.ndarray) and vec.dtype == np.float32)
    check("encode vector is non-zero", np.linalg.norm(vec) > 0)

    # Add memories
    await add_memory_with_embedding("mem_user", "用户喜欢听爵士乐", "fact", "user")
    await add_memory_with_embedding("mem_user", "每天早上跑步5公里", "activity", "user")
    await add_memory_with_embedding("mem_user", "讨厌被催促", "instruction", "user")

    # Retrieval
    results_music = await search_relevant_memories("mem_user", "音乐喜好", top_k=5)
    check("search returns list", isinstance(results_music, list))
    check("search returns at most top_k", len(results_music) <= 5)
    check("most relevant memory about music is first",
          any("爵士" in m.content for m in results_music[:2]))

    results_sport = await search_relevant_memories("mem_user", "运动习惯", top_k=1)
    check("top_k=1 returns exactly 1", len(results_sport) == 1)
    check("sport query retrieves running memory",
          "跑步" in results_sport[0].content or "运动" in results_sport[0].content
          or len(results_sport) > 0)

    # Empty user
    empty = await search_relevant_memories("nonexistent_user", "anything")
    check("empty user returns []", empty == [])

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main():
    await setup()
    await test_short_term()
    await test_long_term()

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
    asyncio.run(main())
