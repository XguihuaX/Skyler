"""Tests for v3-G chunk 2.6 pending_briefings DB CRUD + TTL + 索引行为。"""
import asyncio
import json
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select, text

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))


async def _setup_db() -> None:
    from backend.database import init_db
    from backend.database.migrations.v3_e1_z import run_migration as m_z
    from backend.database.migrations.v3_f import run_migration as m_f
    from backend.database.migrations.v3_g_chunk2_proactive import run_migration as m_c2
    from backend.database.migrations.v3_g_chunk2_6_pending_briefing import (
        run_migration as m_c26,
    )
    await init_db()
    await m_f(); await m_z(); await m_c2(); await m_c26()


async def _ensure_user(uid: str) -> None:
    from backend.database import AsyncSessionLocal
    from backend.database.services import create_user, get_user
    async with AsyncSessionLocal() as session:
        if await get_user(session, uid) is None:
            await create_user(session, uid, f"User-{uid}")


# ---------------------------------------------------------------------------
# 1. CRUD round-trip
# ---------------------------------------------------------------------------

async def test_add_and_get_active():
    print("\n[pending_briefing — add + get_active round-trip]")
    await _setup_db()
    await _ensure_user("pb_user1")

    from backend.database import AsyncSessionLocal
    from backend.database.services import (
        add_pending_briefing, get_active_pending_briefing,
    )

    async with AsyncSessionLocal() as session:
        row = await add_pending_briefing(
            session,
            user_id="pb_user1",
            trigger_name="wake_call",
            briefing_data_json=json.dumps({"city": "东京", "weather": "晴"}),
            character_id=1,
            conversation_id=1,
            ttl_minutes=30,
        )
        check("inserted with id", isinstance(row.id, int) and row.id > 0)
        check("consumed_at NULL", row.consumed_at is None)
        check("trigger_name persisted", row.trigger_name == "wake_call")
        check("ttl_minutes persisted", row.ttl_minutes == 30)

    async with AsyncSessionLocal() as session:
        active = await get_active_pending_briefing(session, "pb_user1")

    check("get_active returns the row", active is not None and active.id == row.id)
    check("data_json round-trips",
          json.loads(active.briefing_data_json).get("city") == "东京")


async def test_filter_by_trigger_name():
    print("\n[pending_briefing — filter by trigger_name]")
    await _setup_db()
    await _ensure_user("pb_user_filter")

    from backend.database import AsyncSessionLocal
    from backend.database.services import (
        add_pending_briefing, get_active_pending_briefing,
    )

    async with AsyncSessionLocal() as session:
        await add_pending_briefing(
            session, user_id="pb_user_filter", trigger_name="meal_call",
            briefing_data_json="{}", character_id=1, conversation_id=1,
        )

    async with AsyncSessionLocal() as session:
        wake = await get_active_pending_briefing(
            session, "pb_user_filter", trigger_name="wake_call",
        )
        meal = await get_active_pending_briefing(
            session, "pb_user_filter", trigger_name="meal_call",
        )

    check("filter by 'wake_call' returns None", wake is None)
    check("filter by 'meal_call' returns row", meal is not None)


# ---------------------------------------------------------------------------
# 2. TTL boundary
# ---------------------------------------------------------------------------

async def test_ttl_expiry():
    """Pending row 超过 TTL 应被 get_active 过滤掉。"""
    print("\n[pending_briefing — TTL expiry filter]")
    await _setup_db()
    await _ensure_user("pb_user_ttl")

    from backend.database import AsyncSessionLocal
    from backend.database.services import (
        add_pending_briefing, get_active_pending_briefing,
    )

    async with AsyncSessionLocal() as session:
        row = await add_pending_briefing(
            session, user_id="pb_user_ttl", trigger_name="wake_call",
            briefing_data_json="{}", character_id=1, conversation_id=1,
            ttl_minutes=30,
        )

    # 注入"未来 31 分钟"作为 now，应判超时
    future_now = row.created_at + timedelta(minutes=31)
    async with AsyncSessionLocal() as session:
        active = await get_active_pending_briefing(
            session, "pb_user_ttl", now=future_now,
        )
    check("expired row filtered out", active is None)

    # 边界：未来 29 分钟仍在 TTL 内
    near_now = row.created_at + timedelta(minutes=29)
    async with AsyncSessionLocal() as session:
        active2 = await get_active_pending_briefing(
            session, "pb_user_ttl", now=near_now,
        )
    check("within TTL still returned", active2 is not None)


# ---------------------------------------------------------------------------
# 3. consume idempotency
# ---------------------------------------------------------------------------

async def test_consume_marks_consumed_at():
    print("\n[pending_briefing — consume marks consumed_at]")
    await _setup_db()
    await _ensure_user("pb_user_consume")

    from backend.database import AsyncSessionLocal
    from backend.database.models import PendingBriefing
    from backend.database.services import (
        add_pending_briefing, consume_pending_briefing, get_active_pending_briefing,
    )

    async with AsyncSessionLocal() as session:
        row = await add_pending_briefing(
            session, user_id="pb_user_consume", trigger_name="wake_call",
            briefing_data_json="{}", character_id=1, conversation_id=1,
        )

    async with AsyncSessionLocal() as session:
        ok1 = await consume_pending_briefing(session, row.id)
        ok2 = await consume_pending_briefing(session, row.id)  # idempotent

    check("first consume returns True", ok1 is True)
    check("second consume returns False (already consumed)", ok2 is False)

    async with AsyncSessionLocal() as session:
        fetched = (await session.execute(
            select(PendingBriefing).where(PendingBriefing.id == row.id)
        )).scalar_one_or_none()

    check("consumed_at populated", fetched is not None and fetched.consumed_at is not None)

    # consumed 后 get_active 不再返回
    async with AsyncSessionLocal() as session:
        active = await get_active_pending_briefing(session, "pb_user_consume")
    check("consumed row excluded from get_active", active is None)


async def test_consume_unknown_id():
    print("\n[pending_briefing — consume unknown id]")
    await _setup_db()
    from backend.database import AsyncSessionLocal
    from backend.database.services import consume_pending_briefing
    async with AsyncSessionLocal() as session:
        ok = await consume_pending_briefing(session, 999999)
    check("unknown id returns False (no raise)", ok is False)


# ---------------------------------------------------------------------------
# 4. multi-row ordering: get_active returns most recent
# ---------------------------------------------------------------------------

async def test_get_active_returns_most_recent():
    print("\n[pending_briefing — get_active returns most recent unconsumed]")
    await _setup_db()
    await _ensure_user("pb_user_multi")

    from backend.database import AsyncSessionLocal
    from backend.database.services import (
        add_pending_briefing, get_active_pending_briefing,
    )

    async with AsyncSessionLocal() as session:
        await add_pending_briefing(
            session, user_id="pb_user_multi", trigger_name="wake_call",
            briefing_data_json='{"v":1}', character_id=1, conversation_id=1,
        )
        await asyncio.sleep(0.01)
        row2 = await add_pending_briefing(
            session, user_id="pb_user_multi", trigger_name="wake_call",
            briefing_data_json='{"v":2}', character_id=1, conversation_id=1,
        )

    async with AsyncSessionLocal() as session:
        active = await get_active_pending_briefing(session, "pb_user_multi")

    check("returns the second (most recent) row",
          active is not None and active.id == row2.id,
          f"got id={active.id if active else None} expected={row2.id}")


# ---------------------------------------------------------------------------
# 5. 索引存在性（performance proxy）
# ---------------------------------------------------------------------------

async def test_index_created():
    print("\n[pending_briefing — index 'idx_pending_briefings_lookup' exists]")
    await _setup_db()
    from backend.database import engine
    async with engine.begin() as conn:
        rows = (await conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND tbl_name='pending_briefings'"
        ))).fetchall()
    names = [r[0] for r in rows]
    check("index present", "idx_pending_briefings_lookup" in names,
          f"got {names}")


# ---------------------------------------------------------------------------
# 6. migration 幂等
# ---------------------------------------------------------------------------

async def test_migration_idempotent():
    print("\n[migration — v3_g_chunk2_6 idempotent]")
    from backend.database import engine
    from backend.database.migrations.v3_g_chunk2_6_pending_briefing import (
        run_migration,
    )
    await run_migration()
    try:
        await run_migration()
        check("second run does not raise", True)
    except Exception as exc:
        check("second run does not raise", False, f"raised {exc}")
    async with engine.begin() as conn:
        rows = (await conn.execute(text(
            "SELECT count(*) FROM sqlite_master WHERE type='table' "
            "AND name='pending_briefings'"
        ))).fetchone()
    check("table count == 1 after two runs", rows[0] == 1, f"got {rows[0]}")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

async def main():
    await test_add_and_get_active()
    await test_filter_by_trigger_name()
    await test_ttl_expiry()
    await test_consume_marks_consumed_at()
    await test_consume_unknown_id()
    await test_get_active_returns_most_recent()
    await test_index_created()
    await test_migration_idempotent()

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
