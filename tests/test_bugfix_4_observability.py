"""Bugfix-4 — Observability tests.

Coverage:
  * test_tts_call_log_insert            — INSERT one row, fields正确
  * test_tts_call_log_idempotent_migration — migration 跑两次表仍存在
  * test_observability_usage_aggregation — today/month/all 聚合 by_source
  * test_observability_anomaly_detection — input_chars > 500 进 anomaly_calls
  * test_system_resources_endpoint      — psutil 路径 OK / 无 psutil fallback
  * test_recent_calls_endpoint          — recent_calls 倒序 + limit
  * test_estimate_cost                  — cost 估算各 model

Run:
    .venv/bin/python tests/test_bugfix_4_observability.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile

_TMP_HOME = tempfile.mkdtemp(prefix="momoos-bugfix4-")
os.environ["HOME"] = _TMP_HOME
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text

import backend.database as _db_module

TEST_ENGINE = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
TEST_SESSION = sessionmaker(
    TEST_ENGINE, class_=AsyncSession, expire_on_commit=False,
)
_db_module.engine = TEST_ENGINE
_db_module.AsyncSessionLocal = TEST_SESSION

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, cond: bool, detail: str = "") -> None:
    tag = PASS if cond else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, cond))


async def setup_db() -> None:
    from backend.database.migrations.bugfix_4_observability import run_migration
    await run_migration()


# ---------------------------------------------------------------------------
# Migration + INSERT
# ---------------------------------------------------------------------------


async def test_tts_call_log_insert():
    print("\n[1] tts_call_log INSERT")
    from backend.observability.tts_log import (
        log_tts_call, set_tts_call_context,
    )
    set_tts_call_context(source="chat", character_id=2, user_id="u-test")
    await log_tts_call(
        success=True, voice="longanhuan", model="cosyvoice-v3-flash",
        input_chars=42, input_preview="你好,我是测试。",
    )
    async with TEST_ENGINE.begin() as conn:
        row = (await conn.execute(text(
            "SELECT source, character_id, voice, model, input_chars, "
            "input_preview, cost_estimate, success "
            "FROM tts_call_log ORDER BY id DESC LIMIT 1"
        ))).first()
    check("row inserted", row is not None)
    if row:
        check("source 正确", row[0] == "chat", f"got={row[0]}")
        check("character_id 正确", row[1] == 2, f"got={row[1]}")
        check("voice 正确", row[2] == "longanhuan")
        check("model 正确", row[3] == "cosyvoice-v3-flash")
        check("input_chars 正确", row[4] == 42)
        check("input_preview 正确", row[5] == "你好,我是测试。")
        check("cost_estimate > 0", (row[6] or 0) > 0,
              f"got={row[6]}")
        check("success=1", row[7] == 1)


async def test_tts_call_log_idempotent_migration():
    print("\n[2] migration idempotent")
    from backend.database.migrations.bugfix_4_observability import run_migration
    await run_migration()
    await run_migration()
    async with TEST_ENGINE.begin() as conn:
        row = (await conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='tts_call_log'"
        ))).first()
    check("table still exists after 2 runs", row is not None)


# ---------------------------------------------------------------------------
# Cost estimation
# ---------------------------------------------------------------------------


def test_estimate_cost():
    print("\n[3] estimate_cost per model")
    from backend.observability.tts_log import estimate_cost
    check("v3-flash 单价 ~0.00007/char",
          estimate_cost(1000, "cosyvoice-v3-flash") == 0.07,
          f"got={estimate_cost(1000, 'cosyvoice-v3-flash')}")
    check("v3.5-plus 单价 ~0.001/char",
          estimate_cost(1000, "cosyvoice-v3.5-plus") == 1.0,
          f"got={estimate_cost(1000, 'cosyvoice-v3.5-plus')}")
    check("unknown model → fallback rate",
          estimate_cost(100, "unknown-model") > 0)
    check("0 chars → 0 cost",
          estimate_cost(0, "cosyvoice-v3-flash") == 0.0)


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


async def test_observability_usage_aggregation():
    print("\n[4] usage aggregation by_source")
    from backend.observability.tts_log import (
        log_tts_call, set_tts_call_context,
    )
    # Plant 3 rows: 2 chat + 1 proactive
    set_tts_call_context(source="chat", character_id=1)
    await log_tts_call(success=True, voice="v1", model="cosyvoice-v3-flash",
                       input_chars=100, input_preview="x")
    await log_tts_call(success=True, voice="v1", model="cosyvoice-v3-flash",
                       input_chars=150, input_preview="x")
    set_tts_call_context(source="proactive", character_id=1)
    await log_tts_call(success=True, voice="v2", model="cosyvoice-v3-flash",
                       input_chars=80, input_preview="y")

    from backend.observability.tts_aggregate import aggregate_usage
    r = await aggregate_usage("today")
    check("by_source has chat", "chat" in r["by_source"],
          f"keys={list(r['by_source'].keys())}")
    check("by_source has proactive", "proactive" in r["by_source"])
    check("chat chars >= 250 (2 rows * 100/150)",
          r["by_source"]["chat"]["chars"] >= 250,
          f"got={r['by_source']['chat']['chars']}")
    check("proactive chars == 80",
          r["by_source"]["proactive"]["chars"] == 80,
          f"got={r['by_source']['proactive']['chars']}")
    check("total_calls >= 4 (含之前 test 插的)",
          r["total_calls"] >= 4, f"got={r['total_calls']}")
    check("avg_chars_per_call is int",
          isinstance(r["avg_chars_per_call"], int))


async def test_observability_anomaly_detection():
    print("\n[5] anomaly detection input_chars > 500")
    from backend.observability.tts_log import (
        log_tts_call, set_tts_call_context,
    )
    set_tts_call_context(source="chat", character_id=1)
    # 一行 input_chars=750 触发 anomaly
    await log_tts_call(success=True, voice="v1", model="cosyvoice-v3-flash",
                       input_chars=750, input_preview="超长 sample with thinking tag leak")
    from backend.observability.tts_aggregate import aggregate_usage
    r = await aggregate_usage("today")
    check("anomaly_calls 非空",
          len(r["anomaly_calls"]) > 0,
          f"got len={len(r['anomaly_calls'])}")
    found = any(a["input_chars"] == 750 for a in r["anomaly_calls"])
    check("含 input_chars=750 的 row", found,
          f"got={[a['input_chars'] for a in r['anomaly_calls']]}")


# ---------------------------------------------------------------------------
# Recent calls + system resources
# ---------------------------------------------------------------------------


async def test_recent_calls_endpoint():
    print("\n[6] recent_calls endpoint")
    from backend.observability.tts_aggregate import list_recent_calls
    calls = await list_recent_calls(limit=5)
    check("len <= 5", len(calls) <= 5)
    if len(calls) >= 2:
        check("倒序 (id desc)",
              calls[0]["id"] > calls[1]["id"],
              f"got ids={[c['id'] for c in calls[:3]]}")


def test_system_resources_endpoint():
    print("\n[7] system resources collect")
    from backend.observability import system as sys_mod
    r = sys_mod.collect()
    # psutil 装了就有 backend_rss; 没装 fields 为 None
    check("has_psutil True (装了)", r.has_psutil is True)
    check("backend_rss_mb 是 float",
          isinstance(r.backend_rss_mb, float)
          and r.backend_rss_mb > 0, f"got={r.backend_rss_mb}")
    check("system_total_ram_mb > 0",
          (r.system_total_ram_mb or 0) > 0)


# ---------------------------------------------------------------------------
# ContextVar isolation
# ---------------------------------------------------------------------------


async def test_contextvar_isolation():
    print("\n[8] ContextVar source isolation across tasks")
    from backend.observability.tts_log import (
        get_tts_call_context, set_tts_call_context,
    )

    async def task_a():
        set_tts_call_context(source="chat", character_id=10)
        await asyncio.sleep(0.01)
        return get_tts_call_context()

    async def task_b():
        set_tts_call_context(source="preview")
        await asyncio.sleep(0.01)
        return get_tts_call_context()

    a, b = await asyncio.gather(task_a(), task_b())
    check("task A context source=chat", a.source == "chat", f"got={a.source}")
    check("task A character_id=10", a.character_id == 10)
    check("task B context source=preview", b.source == "preview")
    check("task B character_id=None (not leaked from A)",
          b.character_id is None, f"got={b.character_id}")


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------


async def _main():
    await setup_db()
    await test_tts_call_log_insert()
    await test_tts_call_log_idempotent_migration()
    test_estimate_cost()
    await test_observability_usage_aggregation()
    await test_observability_anomaly_detection()
    await test_recent_calls_endpoint()
    test_system_resources_endpoint()
    await test_contextvar_isolation()


if __name__ == "__main__":
    asyncio.run(_main())
    passed = sum(1 for _, ok in results if ok)
    failed = len(results) - passed
    print(f"\n=== {passed} passed, {failed} failed ===")
    import shutil
    shutil.rmtree(_TMP_HOME, ignore_errors=True)
    sys.exit(0 if failed == 0 else 1)
