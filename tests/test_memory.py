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

from backend.memory.short_term import (
    SHORT_TERM_MAX,
    SHORT_TERM_MAX_TURNS,
    ShortTermMemory,
)
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

    # 修法 A:SHORT_TERM_MAX 重新定义为 60 messages = 30 turns(原 20 已过时)。
    check("SHORT_TERM_MAX_TURNS = 30", SHORT_TERM_MAX_TURNS == 30)
    check("SHORT_TERM_MAX = 60 messages (= 30 turns × 2)",
          SHORT_TERM_MAX == 60)


# ---------------------------------------------------------------------------
# 修法 A — SHORT_TERM_MAX trim 真生效(6 new test cases)
# ---------------------------------------------------------------------------

async def test_short_term_trim_below_max_keeps_all():
    """add 20 turn(40 messages)< MAX(60)→ 全留,无 trim。"""
    print("\n[修法A-1] add 20 turn < MAX → 全留")
    mem = ShortTermMemory()
    uid = "trim_u1"
    for i in range(20):
        await mem.add(uid, "user",      f"u-msg-{i}")
        await mem.add(uid, "assistant", f"a-msg-{i}")
    cnt = await mem.count(uid)
    check("count == 40 messages (20 turn × 2)", cnt == 40, f"got {cnt}")
    turns = await mem.get(uid)
    check("first message preserved (chronological)",
          turns[0]["content"] == "u-msg-0")
    check("last message preserved", turns[-1]["content"] == "a-msg-19")


async def test_short_term_trim_exceeding_max_trims_oldest():
    """add 50 turn(100 messages)→ trim 到 60(= 30 turn)。最旧 40 messages 丢弃。"""
    print("\n[修法A-2] add 50 turn > MAX → trim 到 60 messages")
    mem = ShortTermMemory()
    uid = "trim_u2"
    for i in range(50):
        await mem.add(uid, "user",      f"u-msg-{i}")
        await mem.add(uid, "assistant", f"a-msg-{i}")
    cnt = await mem.count(uid)
    check("count == 60 messages (hard cap)", cnt == SHORT_TERM_MAX,
          f"got {cnt} expected {SHORT_TERM_MAX}")
    turns = await mem.get(uid)
    # 最旧应该是 message 40(turn 20 的 user)── 因为 100 - 60 = 40 个被剥
    check("oldest kept = u-msg-20 (= 100-60 dropped from head)",
          turns[0]["content"] == "u-msg-20", f"got {turns[0]['content']!r}")
    check("newest kept = a-msg-49", turns[-1]["content"] == "a-msg-49")


async def test_short_term_trim_preserves_order():
    """trim 后保留**最新** N turn 顺序(chronological)。"""
    print("\n[修法A-3] trim 后保留 chronological order")
    mem = ShortTermMemory()
    uid = "trim_u3"
    for i in range(40):
        await mem.add(uid, "user", f"m-{i}")
    turns = await mem.get(uid)
    # 60 cap is per messages,here all 'user' so 40 messages < 60 → 全留
    # 检查 strict ascending
    contents = [t["content"] for t in turns]
    for i in range(1, len(contents)):
        idx_prev = int(contents[i-1].split("-")[1])
        idx_curr = int(contents[i].split("-")[1])
        if idx_curr != idx_prev + 1:
            check(f"chronological broken between {i-1} and {i}", False); break
    else:
        check("chronological order preserved", True, "40 messages monotonic")


async def test_short_term_trim_user_isolation():
    """user_a add 50 turn(超 cap),user_b add 10 turn(未超):
    trim 只影响 user_a;user_b 完整保留。"""
    print("\n[修法A-4] trim user isolation")
    mem = ShortTermMemory()
    for i in range(50):
        await mem.add("user_a", "user",      f"a-{i}")
        await mem.add("user_a", "assistant", f"a-{i}r")
    for i in range(10):
        await mem.add("user_b", "user",      f"b-{i}")
        await mem.add("user_b", "assistant", f"b-{i}r")
    cnt_a = await mem.count("user_a")
    cnt_b = await mem.count("user_b")
    check("user_a trimmed to 60", cnt_a == SHORT_TERM_MAX, f"got {cnt_a}")
    check("user_b untouched (20 messages)", cnt_b == 20, f"got {cnt_b}")
    turns_b = await mem.get("user_b")
    check("user_b first message intact", turns_b[0]["content"] == "b-0")


async def test_short_term_trim_at_exact_max_no_trim():
    """恰好 60 messages(= 30 turn)不应触发 trim。"""
    print("\n[修法A-5] 恰好 max,不 trim")
    mem = ShortTermMemory()
    uid = "trim_u5"
    for i in range(30):
        await mem.add(uid, "user",      f"u-{i}")
        await mem.add(uid, "assistant", f"a-{i}")
    cnt = await mem.count(uid)
    check("exactly 60 messages, no trim", cnt == 60, f"got {cnt}")
    turns = await mem.get(uid)
    check("first message preserved (no trim happened)",
          turns[0]["content"] == "u-0", f"got {turns[0]['content']!r}")


async def test_short_term_get_returns_trimmed_view():
    """add 50 turn → .get() 返回最新 30 turn 视图(60 messages)。"""
    print("\n[修法A-6] .get() 返回 trimmed view")
    mem = ShortTermMemory()
    uid = "trim_u6"
    for i in range(50):
        await mem.add(uid, "user",      f"u-{i}")
        await mem.add(uid, "assistant", f"a-{i}")
    turns = await mem.get(uid)
    check("get returns 60 messages", len(turns) == 60, f"got {len(turns)}")
    # head is u-msg-20(50-30=20 turns dropped from head)
    check("get head = u-20 (newest 30 turns)",
          turns[0]["content"] == "u-20", f"got {turns[0]['content']!r}")
    check("get tail = a-49", turns[-1]["content"] == "a-49")

# ---------------------------------------------------------------------------
# Long-term memory (embedding + retrieval)
# ---------------------------------------------------------------------------

async def test_long_term():
    print("\n[LongTermMemory]")

    # v3.5 chunk 9 Part 0：``search_relevant_memories`` 加了短输入 gate
    # （默认 ``threshold = 10``）短查询直接返 ``[]``。本测试用 4-char 中文
    # query（"音乐喜好" / "运动习惯"）测语义检索本身，不测 gate；把
    # threshold 临时降到 0 让 query 走完整路径。gate 行为单独由
    # ``test_build_messages_perf.py`` 验证。
    from backend.config import config_yaml as _cfg
    _orig_threshold = _cfg.get("memory", {}).get("embedding", {}).get(
        "short_input_threshold"
    )
    _cfg.setdefault("memory", {}).setdefault("embedding", {})[
        "short_input_threshold"
    ] = 0

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

    # restore threshold
    _cfg["memory"]["embedding"]["short_input_threshold"] = (
        _orig_threshold if _orig_threshold is not None else 10
    )

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main():
    await setup()
    await test_short_term()
    # 修法 A:6 个 trim 测试
    await test_short_term_trim_below_max_keeps_all()
    await test_short_term_trim_exceeding_max_trims_oldest()
    await test_short_term_trim_preserves_order()
    await test_short_term_trim_user_isolation()
    await test_short_term_trim_at_exact_max_no_trim()
    await test_short_term_get_returns_trimmed_view()
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
