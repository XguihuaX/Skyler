"""Tests for v3-G chunk 2 ``backend.scheduler.briefing`` 薄包装 + migration 幂等。

chunk 1 的 template 文本生成器（``_format_event_for_briefing`` /
``generate_morning_briefing``）已删除，本文件相应缩成只测：
  1. ``deliver_morning_briefing`` 是 ``run_trigger(MorningBriefingTrigger())`` 的薄包装
  2. 返回字典含向后兼容字段（``audio_path`` / ``voice_model``）
  3. v3_g_chunk2_proactive migration 幂等：重复执行不报错且不重复加列
"""
import asyncio
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.scheduler import briefing as briefing_module

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))


# ---------------------------------------------------------------------------
# 1. deliver_morning_briefing 是 run_trigger 的薄包装
# ---------------------------------------------------------------------------

async def test_deliver_calls_run_trigger():
    print("\n[briefing — deliver delegates to run_trigger]")
    captured: dict = {}

    async def fake_run_trigger(trigger, user_id):
        captured["trigger_name"] = trigger.name
        captured["user_id"] = user_id
        return {
            "text": "fake briefing",
            "character_id": 1,
            "conversation_id": 5,
            "proactive_trigger": "morning_briefing",
            "audio_bytes": 0,
        }

    with patch.object(briefing_module, "run_trigger", fake_run_trigger):
        out = await briefing_module.deliver_morning_briefing()

    check("called with MorningBriefingTrigger.name",
          captured.get("trigger_name") == "morning_briefing",
          f"got {captured.get('trigger_name')}")
    check("called with default user_id",
          captured.get("user_id") == briefing_module._default_user_id())
    check("returns text", out["text"] == "fake briefing")
    check("returns proactive_trigger field",
          out.get("proactive_trigger") == "morning_briefing")
    check("backwards-compat: audio_path key present (None)",
          "audio_path" in out and out["audio_path"] is None)
    check("backwards-compat: voice_model key present (None)",
          "voice_model" in out and out["voice_model"] is None)


# ---------------------------------------------------------------------------
# 2. v3_g_chunk2_proactive migration 幂等
# ---------------------------------------------------------------------------

async def test_migration_idempotent():
    print("\n[migration — v3_g_chunk2_proactive idempotent]")
    from backend.database import init_db, engine
    from backend.database.migrations.v3_g_chunk2_proactive import (
        run_migration, _column_exists,
    )
    from sqlalchemy import text

    await init_db()

    # 跑一次（init_db 实际上已经把列加上了；migration 应该 detect 后 skip）
    await run_migration()
    async with engine.begin() as conn:
        check("column exists after first run",
              await _column_exists(conn, "chat_history", "proactive_trigger"))

    # 第二次跑：应该 detect 已存在 + skip 不抛
    try:
        await run_migration()
        check("second run does not raise", True)
    except Exception as exc:
        check("second run does not raise", False, f"raised {exc}")

    # 验证 PRAGMA 不报告重复列（只数 occurrences == 1）
    async with engine.begin() as conn:
        rows = (await conn.execute(text("PRAGMA table_info(chat_history)"))).fetchall()
    occurrences = sum(1 for r in rows if r[1] == "proactive_trigger")
    check("column count == 1 after two runs",
          occurrences == 1, f"got {occurrences}")


# ---------------------------------------------------------------------------
# 3. add_chat_history with proactive_trigger
# ---------------------------------------------------------------------------

async def test_add_chat_history_persists_proactive_trigger():
    print("\n[chat_history — proactive_trigger field round-trip]")
    from backend.database import init_db, AsyncSessionLocal
    from backend.database.migrations.v3_e1_z import run_migration as _m_z
    from backend.database.migrations.v3_f import run_migration as _m_f
    from backend.database.migrations.v3_g_chunk2_proactive import (
        run_migration as _m_chunk2,
    )
    await init_db(); await _m_f(); await _m_z(); await _m_chunk2()
    # placeholder no-op to dedupe init below
    from backend.database.services import (
        add_chat_history, create_user, get_user,
    )
    from backend.database.models import ChatHistory
    from sqlalchemy import select

    await init_db()
    async with AsyncSessionLocal() as session:
        if await get_user(session, "test_pt") is None:
            await create_user(session, "test_pt", "TestPT")

    async with AsyncSessionLocal() as session:
        row = await add_chat_history(
            session, "test_pt", "assistant", "morning briefing content",
            kind="proactive",
            proactive_trigger="morning_briefing",
        )
        rid = row.id

    async with AsyncSessionLocal() as session:
        fetched = (await session.execute(
            select(ChatHistory).where(ChatHistory.id == rid)
        )).scalar_one_or_none()

    check("row persisted", fetched is not None)
    if fetched:
        check("kind = 'proactive'", fetched.kind == "proactive")
        check("proactive_trigger = 'morning_briefing'",
              fetched.proactive_trigger == "morning_briefing")


async def test_add_chat_history_coerces_trigger_to_null_for_non_proactive():
    """non-proactive kind 即使传 proactive_trigger 也应被 coerce 成 NULL。
    这样调用方可以无脑传 trigger，不污染普通行。"""
    print("\n[chat_history — non-proactive rows coerce trigger to NULL]")
    from backend.database import init_db, AsyncSessionLocal
    from backend.database.migrations.v3_e1_z import run_migration as _m_z
    from backend.database.migrations.v3_f import run_migration as _m_f
    from backend.database.migrations.v3_g_chunk2_proactive import (
        run_migration as _m_chunk2,
    )
    await init_db(); await _m_f(); await _m_z(); await _m_chunk2()
    # placeholder no-op to dedupe init below
    from backend.database.services import (
        add_chat_history, create_user, get_user,
    )
    from backend.database.models import ChatHistory
    from sqlalchemy import select

    await init_db()
    async with AsyncSessionLocal() as session:
        if await get_user(session, "test_pt2") is None:
            await create_user(session, "test_pt2", "TestPT2")

    async with AsyncSessionLocal() as session:
        row = await add_chat_history(
            session, "test_pt2", "user", "hi",
            kind="normal",
            proactive_trigger="morning_briefing",  # 应被忽略
        )
        rid = row.id

    async with AsyncSessionLocal() as session:
        fetched = (await session.execute(
            select(ChatHistory).where(ChatHistory.id == rid)
        )).scalar_one_or_none()

    check("kind stays 'normal'", fetched.kind == "normal")
    check("proactive_trigger coerced to NULL on non-proactive row",
          fetched.proactive_trigger is None,
          f"got {fetched.proactive_trigger!r}")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

async def main():
    await test_deliver_calls_run_trigger()
    await test_migration_idempotent()
    await test_add_chat_history_persists_proactive_trigger()
    await test_add_chat_history_coerces_trigger_to_null_for_non_proactive()

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
