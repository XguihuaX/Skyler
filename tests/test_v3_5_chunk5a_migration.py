"""v3.5 chunk 5a migration 幂等 + 字段验证。

跑两次 ``run_migration`` 不应炸；新字段 nullable，类型 TEXT。
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text

from backend.database import engine, init_db
from backend.database.migrations.v3_5_chunk5a_character_background import (
    run_migration,
)

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))


async def _column_info(table: str, column: str):
    """Return (exists, type_text, nullable_bool) for the column."""
    async with engine.connect() as conn:
        rows = (await conn.execute(text(f"PRAGMA table_info({table})"))).fetchall()
    for row in rows:
        # cid, name, type, notnull, dflt_value, pk
        if row[1] == column:
            return True, row[2], (row[3] == 0)
    return False, None, None


async def test_idempotent_double_run():
    print("\n[chunk5a migration — 幂等：跑两次不炸]")
    await init_db()
    await run_migration()
    exists1, _, _ = await _column_info("characters", "background_path")
    check("first run: column exists", exists1)

    await run_migration()
    exists2, type_text, nullable = await _column_info("characters", "background_path")
    check("second run: column still exists", exists2)
    check("type is TEXT", (type_text or "").upper() == "TEXT", f"got {type_text!r}")
    check("nullable (notnull == 0)", nullable is True)


async def test_default_null_for_new_rows():
    print("\n[chunk5a — 新插入 row 默认 NULL]")
    # 不污染主 characters 表，用临时 row + 立刻删
    async with engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO characters (id, name, persona) "
            "VALUES (:id, :name, :persona)"
        ), {"id": 9501, "name": "_chunk5a_test", "persona": "test"})
    try:
        async with engine.connect() as conn:
            row = (await conn.execute(text(
                "SELECT background_path FROM characters WHERE id = 9501"
            ))).first()
        check("background_path NULL by default", row is not None and row[0] is None)
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM characters WHERE id = 9501"))


async def main():
    await test_idempotent_double_run()
    await test_default_null_for_new_rows()

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
