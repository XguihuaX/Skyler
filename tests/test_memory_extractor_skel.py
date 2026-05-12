"""v3.5 chunk 10 commit 2 — MemoryExtractor 骨架 + state tracking。

* config getters 默认值 + 类型容错
* ``get_last_processed_turn_id`` / ``update_last_processed_turn_id`` upsert
* ``fetch_user_turns_after`` 过滤 role / kind + id > after_id
* ``MemoryExtractor.run_loop`` + ``stop()`` lifecycle
* ``_extract_batch`` 占位实现：仅推进 state，不写 memory
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.database import AsyncSessionLocal, Base, engine
from backend.database.models import ChatHistory, User
from backend.memory import extractor as ex_mod

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))


TEST_USER = "chunk10_extractor_test"


async def _setup_clean_state() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSessionLocal() as session:
        from sqlalchemy import select, delete
        await session.execute(delete(ChatHistory).where(
            ChatHistory.user_id == TEST_USER,
        ))
        existing = (await session.execute(
            select(User).where(User.user_id == TEST_USER)
        )).scalar_one_or_none()
        if existing is None:
            session.add(User(user_id=TEST_USER, user_name=TEST_USER))
        await session.commit()
    # 重置 state 表
    from sqlalchemy import text
    async with engine.begin() as conn:
        await conn.execute(text(
            "DELETE FROM memory_extractor_state WHERE user_id = :u"
        ), {"u": TEST_USER})


async def _teardown() -> None:
    async with AsyncSessionLocal() as session:
        from sqlalchemy import delete
        await session.execute(delete(ChatHistory).where(
            ChatHistory.user_id == TEST_USER,
        ))
        await session.execute(delete(User).where(User.user_id == TEST_USER))
        await session.commit()
    from sqlalchemy import text
    async with engine.begin() as conn:
        await conn.execute(text(
            "DELETE FROM memory_extractor_state WHERE user_id = :u"
        ), {"u": TEST_USER})


# ---------------------------------------------------------------------------
# Config getters
# ---------------------------------------------------------------------------


def test_config_getters_defaults():
    print("\n[config] 默认值 + 类型容错")
    check("enabled bool", isinstance(ex_mod.get_extractor_enabled(), bool))
    check("interval int > 0",
          ex_mod.get_extractor_interval_seconds() > 0)
    check("batch_size int > 0",
          ex_mod.get_extractor_batch_size() > 0)
    check("min_confidence float 0-1",
          0 <= ex_mod.get_extractor_min_confidence() <= 1)
    check("llm_judge_enabled bool",
          isinstance(ex_mod.get_extractor_llm_judge_enabled(), bool))
    check("dup_threshold float 0-1",
          0 <= ex_mod.get_extractor_dup_threshold() <= 1)


# ---------------------------------------------------------------------------
# State tracking
# ---------------------------------------------------------------------------


async def test_state_tracking_initial_zero():
    print("\n[state] 新 user → last_processed_turn_id = 0")
    await _setup_clean_state()
    last = await ex_mod.get_last_processed_turn_id(TEST_USER)
    check("初始 0", last == 0)


async def test_state_tracking_upsert():
    print("\n[state] update upsert：第一次 INSERT，第二次 UPDATE")
    await _setup_clean_state()
    await ex_mod.update_last_processed_turn_id(TEST_USER, 42)
    check("写后 == 42",
          await ex_mod.get_last_processed_turn_id(TEST_USER) == 42)
    await ex_mod.update_last_processed_turn_id(TEST_USER, 99)
    check("再次写 == 99（UPDATE 路径）",
          await ex_mod.get_last_processed_turn_id(TEST_USER) == 99)


# ---------------------------------------------------------------------------
# fetch_user_turns_after
# ---------------------------------------------------------------------------


async def test_fetch_filters_role_and_kind():
    print("\n[fetch] 只取 role='user' kind='normal'，按 id 升序")
    await _setup_clean_state()
    async with AsyncSessionLocal() as session:
        for content, role, kind in [
            ("用户 1", "user",      "normal"),
            ("AI 回复", "assistant", "normal"),
            ("touch 占位", "user",      "touch"),
            ("用户 2", "user",      "normal"),
        ]:
            session.add(ChatHistory(
                user_id=TEST_USER,
                role=role,
                content=content,
                kind=kind,
            ))
        await session.commit()

    turns = await ex_mod.fetch_user_turns_after(
        TEST_USER, after_id=0, batch_size=10,
    )
    check("只 2 条 user/normal", len(turns) == 2)
    check("升序 id_1 < id_2", turns[0].id < turns[1].id)
    check("内容正确",
          turns[0].content == "用户 1" and turns[1].content == "用户 2")


async def test_fetch_after_id_filter():
    print("\n[fetch] after_id 过滤")
    await _setup_clean_state()
    async with AsyncSessionLocal() as session:
        for c in ["A", "B", "C", "D"]:
            session.add(ChatHistory(
                user_id=TEST_USER, role="user",
                content=c, kind="normal",
            ))
        await session.commit()
    # 拿前 2 条的 id
    all_turns = await ex_mod.fetch_user_turns_after(
        TEST_USER, after_id=0, batch_size=10,
    )
    check("全 4 条", len(all_turns) == 4)
    cut = all_turns[1].id
    rest = await ex_mod.fetch_user_turns_after(
        TEST_USER, after_id=cut, batch_size=10,
    )
    check("after_id=B.id → 剩 2 条（C/D）",
          len(rest) == 2
          and rest[0].content == "C" and rest[1].content == "D")


async def test_fetch_batch_size_cap():
    print("\n[fetch] batch_size 限流")
    await _setup_clean_state()
    async with AsyncSessionLocal() as session:
        for i in range(5):
            session.add(ChatHistory(
                user_id=TEST_USER, role="user",
                content=f"msg {i}", kind="normal",
            ))
        await session.commit()
    out = await ex_mod.fetch_user_turns_after(
        TEST_USER, after_id=0, batch_size=2,
    )
    check("batch_size=2 限制返 2 条", len(out) == 2)


# ---------------------------------------------------------------------------
# MemoryExtractor._extract_batch 占位 + run_loop / stop
# ---------------------------------------------------------------------------


async def test_extract_batch_advances_state_pointer():
    print("\n[batch] 占位 _extract_batch 仅推进 state pointer")
    await _setup_clean_state()
    async with AsyncSessionLocal() as session:
        for i in range(3):
            session.add(ChatHistory(
                user_id=TEST_USER, role="user",
                content=f"msg {i}", kind="normal",
            ))
        await session.commit()
    initial = await ex_mod.get_last_processed_turn_id(TEST_USER)
    check("初始 last_id == 0", initial == 0)

    ex = ex_mod.MemoryExtractor()
    await ex._extract_batch()
    final = await ex_mod.get_last_processed_turn_id(TEST_USER)
    check("batch 后 last_id > 0", final > 0)

    # 二次 batch：没新 turn → state 不变
    await ex._extract_batch()
    final2 = await ex_mod.get_last_processed_turn_id(TEST_USER)
    check("二次 batch 无新 turn → state 不变", final == final2)


async def test_run_loop_and_stop_lifecycle():
    print("\n[loop] run_loop + stop() 生命周期")
    ex = ex_mod.MemoryExtractor()

    # 强制 interval 很短，让循环快速跑一两次
    with patch.object(ex_mod, "get_extractor_interval_seconds",
                      return_value=0.05):
        ex._task = asyncio.create_task(ex.run_loop())
        await asyncio.sleep(0.2)  # 让循环转几圈
        await ex.stop()

    check("loop 完成 stop 不抛", True)


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


async def test_cleanup():
    print("\n[cleanup]")
    await _teardown()
    check("teardown OK", True)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


async def amain():
    await test_state_tracking_initial_zero()
    await test_state_tracking_upsert()
    await test_fetch_filters_role_and_kind()
    await test_fetch_after_id_filter()
    await test_fetch_batch_size_cap()
    await test_extract_batch_advances_state_pointer()
    await test_run_loop_and_stop_lifecycle()
    await test_cleanup()


def main():
    test_config_getters_defaults()
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
