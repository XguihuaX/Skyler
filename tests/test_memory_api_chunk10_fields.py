"""v3.5 chunk 10 commit 6 — /api/memory/list 返 chunk 10 新字段。"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, text

from backend.database import AsyncSessionLocal, Base, engine
from backend.database.models import Memory, User
from backend.routes.memory_api import router as memory_router

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))


TEST_USER = "chunk10_memory_api_test"


async def _setup_rows() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSessionLocal() as session:
        await session.execute(delete(Memory).where(Memory.user_id == TEST_USER))
        u = (await session.execute(
            select(User).where(User.user_id == TEST_USER)
        )).scalar_one_or_none()
        if u is None:
            session.add(User(user_id=TEST_USER, user_name=TEST_USER))
        await session.commit()

    # 插一条 legacy + 一条 worker + 一条 llm_save_memory
    async with engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO memory "
            "(user_id, role, type, content, extraction_source, access_count) "
            "VALUES (:u, 'user', 'fact', '旧 entry', 'legacy', 0)"
        ), {"u": TEST_USER})
        await conn.execute(text(
            "INSERT INTO memory "
            "(user_id, role, type, content, "
            " entry_type, extraction_source, confidence, access_count) "
            "VALUES (:u, 'user', 'fact', '猫叫 Mochi', "
            "        'fact', 'worker', 0.9, 0)"
        ), {"u": TEST_USER})
        await conn.execute(text(
            "INSERT INTO memory "
            "(user_id, role, type, content, "
            " entry_type, extraction_source, confidence, access_count) "
            "VALUES (:u, 'user', 'instruction', '用户要求记的偏好', "
            "        'preference', 'llm_save_memory', 1.0, 0)"
        ), {"u": TEST_USER})


async def _teardown() -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(delete(Memory).where(Memory.user_id == TEST_USER))
        await session.execute(delete(User).where(User.user_id == TEST_USER))
        await session.commit()


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(memory_router, prefix="/api")
    return TestClient(app)


def test_memory_list_returns_chunk10_fields():
    print("\n[api] /memory/list 返新字段 entry_type / extraction_source / confidence")
    asyncio.run(_setup_rows())
    r = _client().get(f"/api/memory/list?user_id={TEST_USER}")
    check("status 200", r.status_code == 200)
    rows = r.json()
    check("3 行", len(rows) == 3)
    by_content = {row["content"]: row for row in rows}

    legacy = by_content.get("旧 entry")
    check("legacy 行 extraction_source = 'legacy'",
          legacy is not None and legacy["extraction_source"] == "legacy")
    check("legacy 行 entry_type = None",
          legacy is not None and legacy["entry_type"] is None)
    check("legacy 行 confidence = None",
          legacy is not None and legacy["confidence"] is None)

    worker = by_content.get("猫叫 Mochi")
    check("worker 行 extraction_source = 'worker'",
          worker is not None and worker["extraction_source"] == "worker")
    check("worker 行 entry_type = 'fact'",
          worker is not None and worker["entry_type"] == "fact")
    check("worker 行 confidence = 0.9",
          worker is not None and abs((worker["confidence"] or 0) - 0.9) < 0.01)

    llm = by_content.get("用户要求记的偏好")
    check("llm_save_memory 行 source 字段",
          llm is not None and llm["extraction_source"] == "llm_save_memory")
    check("llm_save_memory 行 entry_type = 'preference'",
          llm is not None and llm["entry_type"] == "preference")

    asyncio.run(_teardown())


def test_drawer_imports_extraction_source_labels():
    print("\n[ui] drawer 含 SOURCE_LABEL + entry_type tab OPTIONS")
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "frontend/src/components/MemoryManagerDrawer.tsx",
    )
    src = open(path, "r", encoding="utf-8").read()
    for label in ['自动提取', '你说要记', '手动', '旧']:
        check(f"SOURCE_LABEL 含 {label!r}", label in src)
    for opt in ['事实', '偏好', '事件', '承诺']:
        check(f"TYPE_OPTIONS 含 {opt!r}", opt in src)
    check("confidence 字段显示",
          "confidence" in src
          and "m.confidence" in src)
    check("extraction_source 显示", "m.extraction_source" in src)
    check("entry_type tab 过滤逻辑",
          "m.entry_type === filter" in src)


def main():
    test_memory_list_returns_chunk10_fields()
    test_drawer_imports_extraction_source_labels()

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
