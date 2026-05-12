"""v3.5 chunk 10 — memory 表 schema 扩展 + migration 幂等。

* 6 个新 column 都加上
* 老 entries DEFAULT 'legacy'
* memory_extractor_state 表存在 + UNIQUE 约束
* 二次跑 migration 无副作用
"""
from __future__ import annotations

import asyncio
import os
import sqlite3
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))


async def test_migration_full_lifecycle():
    print("\n[migration] 新 DB 跑两次 → 列加齐 + 二次幂等")
    tmpdir = tempfile.mkdtemp(prefix="chunk10_schema_")
    tmp_db = os.path.join(tmpdir, "test.db")
    try:
        # 模拟旧 schema（含 chunk 9 forgetting curve 列）
        conn = sqlite3.connect(tmp_db)
        conn.executescript("""
        CREATE TABLE memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL, role TEXT, type TEXT, content TEXT,
            embedding BLOB, expires_at TIMESTAMP,
            character_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            access_count INTEGER DEFAULT 0,
            last_accessed_at TIMESTAMP
        );
        INSERT INTO memory (user_id, role, type, content, character_id)
        VALUES ('u', 'user', 'fact', '旧 entry', 1);
        """)
        conn.commit()
        conn.close()

        from sqlalchemy.ext.asyncio import create_async_engine
        from backend.database.migrations import (
            v3_5_chunk10_memory_structured as mig,
        )
        tmp_engine = create_async_engine(
            f"sqlite+aiosqlite:///{tmp_db}", echo=False,
        )

        with patch.object(mig, "engine", tmp_engine):
            await mig.run_migration()
            # 验列
            conn = sqlite3.connect(tmp_db)
            cols = [r[1] for r in conn.execute("PRAGMA table_info(memory)").fetchall()]
            for new_col in [
                "extracted_at", "source_turn_id", "confidence",
                "quality_score", "entry_type", "extraction_source",
            ]:
                check(f"{new_col} 列已加", new_col in cols)
            # 老 entry DEFAULT 'legacy'
            row = conn.execute(
                "SELECT extraction_source FROM memory WHERE content = '旧 entry'"
            ).fetchone()
            check("老 entry extraction_source='legacy'", row[0] == "legacy")
            # extractor_state 表
            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()]
            check("memory_extractor_state 表存在",
                  "memory_extractor_state" in tables)
            # UNIQUE 约束
            try:
                conn.execute(
                    "INSERT INTO memory_extractor_state (user_id, last_processed_turn_id) "
                    "VALUES ('u1', 0)"
                )
                conn.execute(
                    "INSERT INTO memory_extractor_state (user_id, last_processed_turn_id) "
                    "VALUES ('u1', 5)"
                )
                conn.commit()
                check("UNIQUE(user_id) 约束生效", False, "duplicate insert succeeded")
            except sqlite3.IntegrityError:
                check("UNIQUE(user_id) 约束生效", True)
            conn.close()

            # 二次跑无副作用
            await mig.run_migration()
            check("二次跑无异常", True)
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def main():
    asyncio.run(test_migration_full_lifecycle())

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
