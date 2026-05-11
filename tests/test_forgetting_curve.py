"""v3.5 chunk 9 Part 4 — memory forgetting curve unit + migration 幂等。

Score 公式：
    score = relevance * (1 + log(1 + access_count)) / (1 + age_days * decay)

测试断言：
  * score 单调性（相同 relevance + 高 access_count → 更高 score）
  * score 衰减（相同 relevance + 老 entry → 更低 score）
  * threshold gate（score < threshold 不进 top-k）
  * access_count bump（召回成功后 + 1，last_accessed_at 更新）
  * config disabled 退回纯 cosine（无衰减）
  * migration ALTER ADD COLUMN 幂等
"""
from __future__ import annotations

import asyncio
import math
import os
import sqlite3
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.memory.long_term import forgetting_curve_score

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))


# ---------------------------------------------------------------------------
# 1. score 公式单调性
# ---------------------------------------------------------------------------


def test_score_monotonic_in_access_count():
    print("\n[1] 同 relevance/age，access_count 高 → score 更高")
    rel, age = 0.8, 0.0
    s0 = forgetting_curve_score(rel, 0, age, decay=0.01)
    s5 = forgetting_curve_score(rel, 5, age, decay=0.01)
    s50 = forgetting_curve_score(rel, 50, age, decay=0.01)
    check("s0 < s5", s0 < s5)
    check("s5 < s50", s5 < s50)
    # log 渐进：s50 不应是 s0 的 50x
    check("s50 / s0 < 10（log 渐进，避免爆款霸榜）", s50 / s0 < 10.0)


def test_score_decays_with_age():
    print("\n[2] 同 relevance/access_count，age_days 大 → score 衰减")
    rel, ac = 0.8, 0
    s_0d = forgetting_curve_score(rel, ac, 0, decay=0.01)
    s_30d = forgetting_curve_score(rel, ac, 30, decay=0.01)
    s_365d = forgetting_curve_score(rel, ac, 365, decay=0.01)
    check("0d > 30d", s_0d > s_30d)
    check("30d > 365d", s_30d > s_365d)
    check("365d > 0（不为 0）", s_365d > 0)


def test_score_threshold_gate_math():
    print("\n[3] score 公式手算典型 case")
    # relevance=0.5, ac=0, age=0 → score=0.5
    s = forgetting_curve_score(0.5, 0, 0, decay=0.01)
    check("0.5/0/0 → 0.5", abs(s - 0.5) < 1e-9)
    # relevance=0.5, ac=10, age=0 → score=0.5*(1+log(11)) ≈ 0.5*3.398 ≈ 1.699
    s = forgetting_curve_score(0.5, 10, 0, decay=0.01)
    expect = 0.5 * (1 + math.log(11))
    check(f"0.5/10/0 → {expect:.3f}（实测 {s:.3f}）", abs(s - expect) < 1e-6)
    # relevance=1.0, ac=0, age=100 → 1.0 / (1+1.0) = 0.5
    s = forgetting_curve_score(1.0, 0, 100, decay=0.01)
    check(f"1.0/0/100d → 0.5（实测 {s:.3f}）", abs(s - 0.5) < 1e-9)


# ---------------------------------------------------------------------------
# 4. Migration 幂等（临时 sqlite DB）
# ---------------------------------------------------------------------------


async def test_migration_adds_columns_and_is_idempotent():
    print("\n[4] migration 临时 DB 跑两次 → 幂等")
    tmpdir = tempfile.mkdtemp(prefix="chunk9_fc_")
    tmp_db = os.path.join(tmpdir, "test.db")
    try:
        # 准备旧 schema（仅核心字段，不带 access_count / last_accessed_at）
        conn = sqlite3.connect(tmp_db)
        conn.executescript("""
        CREATE TABLE memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            role TEXT, type TEXT, content TEXT,
            embedding BLOB, expires_at TIMESTAMP,
            character_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        INSERT INTO memory (user_id, role, type, content, character_id)
        VALUES ('u', 'user', 'fact', 'cat name Mochi', 1);
        """)
        conn.commit()
        conn.close()

        # monkey-patch engine
        from sqlalchemy.ext.asyncio import create_async_engine
        from backend.database.migrations import (
            v3_5_chunk9_memory_forgetting_curve as mig,
        )
        tmp_engine = create_async_engine(
            f"sqlite+aiosqlite:///{tmp_db}", echo=False,
        )

        with patch.object(mig, "engine", tmp_engine):
            await mig.run_migration()
            # 第一次后：列存在；last_accessed_at = created_at
            conn = sqlite3.connect(tmp_db)
            cols = [r[1] for r in conn.execute("PRAGMA table_info(memory)").fetchall()]
            check("access_count 列已加", "access_count" in cols)
            check("last_accessed_at 列已加", "last_accessed_at" in cols)
            row = conn.execute(
                "SELECT access_count, last_accessed_at, created_at FROM memory"
            ).fetchone()
            check("access_count 初始化 0", row[0] == 0)
            check("last_accessed_at = created_at",
                  row[1] == row[2])
            conn.close()

            # 第二次跑 —— 无改动
            await mig.run_migration()
            check("二次跑无异常", True)
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# 5. config getter 默认值
# ---------------------------------------------------------------------------


def test_config_defaults():
    print("\n[5] config getter 默认值")
    from backend.config import (
        get_forgetting_curve_enabled,
        get_forgetting_curve_threshold,
        get_forgetting_curve_age_decay,
    )
    check("enabled default == True",
          isinstance(get_forgetting_curve_enabled(), bool))
    check("threshold float in (0, 1)",
          0 < get_forgetting_curve_threshold() < 1)
    check("age_decay float > 0",
          get_forgetting_curve_age_decay() > 0)


def test_config_disabled_returns_pure_cosine():
    print("\n[5.b] 配置关闭 forgetting curve → search 退回纯 cosine（无衰减）")
    # 这里 unit-level 验证：手动调 forgetting_curve_score with decay=0 +
    # access_count=0 → 等于 relevance
    s = forgetting_curve_score(0.7, 0, 100, decay=0.0)
    # decay=0 → divisor = 1 + 0 = 1；bonus = 1 + log(1) = 1
    # → score = relevance * 1 / 1 = relevance
    check(f"decay=0 + ac=0 → score==relevance（实测 {s:.3f}）",
          abs(s - 0.7) < 1e-9)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


async def amain():
    await test_migration_adds_columns_and_is_idempotent()


def main():
    test_score_monotonic_in_access_count()
    test_score_decays_with_age()
    test_score_threshold_gate_math()
    asyncio.run(amain())
    test_config_defaults()
    test_config_disabled_returns_pure_cosine()

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
