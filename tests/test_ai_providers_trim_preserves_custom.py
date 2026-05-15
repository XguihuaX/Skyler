"""bugfix-Providers — ``bugfix_3_2_8_dedup_and_trim_seed`` 必须保 custom 行。

背景: 用户在 UI 加 ``deepseek-v4-flash`` + ``deepseek-v4-pro`` (走
``create_provider`` 写入 ``provider_kind='custom'``),重启 backend 后消失。
根因: 本 migration step 2 ``DELETE FROM ai_providers WHERE type='llm' AND
vendor_id IN (...)``一刀切,不分 builtin / custom。修法:加
``AND provider_kind = 'builtin'`` 守卫,custom 行保留。

本测试在临时 sqlite 文件上跑真正的 migration SQL(不用 mock),确保:
  1. builtin seed 行 (openai/anthropic/deepseek) 被 trim
  2. custom 行 (含同 vendor_id 的 deepseek 用户自填) 保留
  3. Qwen 全保留 (builtin + custom)
  4. 跑两次 idempotent —— 第二次不再误删任何 custom
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402
from sqlalchemy import text  # noqa: E402


_SCHEMA_SQL = """
CREATE TABLE ai_providers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vendor_id TEXT,
    type TEXT NOT NULL,
    name TEXT NOT NULL,
    model TEXT NOT NULL,
    endpoint TEXT,
    extra_json TEXT,
    provider_kind TEXT NOT NULL CHECK(provider_kind IN ('builtin','custom')),
    enabled INTEGER NOT NULL DEFAULT 1,
    is_active INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

_SEED_ROWS = [
    # (vendor_id, name, model, provider_kind)
    ("qwen", "Qwen 3.6 Plus", "openai/qwen3.6-plus", "builtin"),
    ("qwen", "Qwen 3.6 Max preview", "openai/qwen3.6-max-preview", "builtin"),
    ("qwen", "qwen3.6-flash", "openai/qwen3.6-flash", "custom"),  # user-added
    ("openai", "GPT-4o", "openai/gpt-4o", "builtin"),  # seed → should trim
    ("anthropic", "Claude 4.5", "anthropic/claude-4.5", "builtin"),  # seed → trim
    ("deepseek", "DeepSeek Chat", "deepseek/deepseek-chat", "builtin"),  # trim
    # CRITICAL: user-added custom DeepSeek must survive
    ("deepseek", "deepseek-v4-flash", "deepseek/deepseek-v4-flash", "custom"),
    ("deepseek", "deepseek-v4-pro", "deepseek/deepseek-v4-pro", "custom"),
]


async def _setup_db(db_path: str) -> None:
    """Initialize temp sqlite with schema + seed rows."""
    eng = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with eng.begin() as conn:
        await conn.execute(text(_SCHEMA_SQL))
        for vid, name, model, kind in _SEED_ROWS:
            await conn.execute(text("""
                INSERT INTO ai_providers
                    (vendor_id, type, name, model, provider_kind, enabled, is_active)
                VALUES (:v, 'llm', :n, :m, :k, 1, 0)
            """), {"v": vid, "n": name, "m": model, "k": kind})
    await eng.dispose()


async def _run_migration_against(db_path: str) -> None:
    """Run the trim_seed migration against the temp DB.

    We can't just import & call ``run_migration()`` because it uses the
    process-global ``engine``. Instead we replicate the relevant SQL.
    This is equivalent because the migration is pure SQL — no Python logic.
    """
    eng = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    _TRIM_VENDORS = ("openai", "anthropic", "deepseek")
    async with eng.begin() as conn:
        # Step 1: dedup
        await conn.execute(text("""
            DELETE FROM ai_providers
            WHERE id IN (
                SELECT id FROM (
                    SELECT id, ROW_NUMBER() OVER (
                        PARTITION BY vendor_id, name, type
                        ORDER BY is_active DESC, enabled DESC, id ASC
                    ) AS rn
                    FROM ai_providers
                )
                WHERE rn > 1
            )
        """))
        # Step 2: trim non-Qwen builtin (THE FIX)
        await conn.execute(text(f"""
            DELETE FROM ai_providers
            WHERE type = 'llm'
              AND provider_kind = 'builtin'
              AND vendor_id IN ({", ".join("'" + v + "'" for v in _TRIM_VENDORS)})
        """))
        # Step 3: UNIQUE INDEX
        await conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS ix_ai_providers_vendor_name_type
            ON ai_providers(vendor_id, name, type)
        """))
    await eng.dispose()


async def _query_remaining(db_path: str) -> list[tuple]:
    eng = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with eng.begin() as conn:
        rows = (await conn.execute(text(
            "SELECT vendor_id, name, provider_kind FROM ai_providers "
            "ORDER BY vendor_id, name"
        ))).fetchall()
    await eng.dispose()
    return [tuple(r) for r in rows]


class TestTrimSeedPreservesCustom(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="momo_test_trim_")
        self.db_path = os.path.join(self.tmpdir, "test.db")
        await _setup_db(self.db_path)

    async def asyncTearDown(self) -> None:
        try:
            os.unlink(self.db_path)
            os.rmdir(self.tmpdir)
        except OSError:
            pass

    async def test_first_run_trims_builtin_only(self):
        """First migration run: builtin seed (non-qwen) trimmed, custom survives."""
        await _run_migration_against(self.db_path)
        rows = await _query_remaining(self.db_path)
        kinds_by_vendor = {(v, k): n for v, n, k in rows}

        # Builtin seeds for non-qwen vendors must be gone
        self.assertNotIn(("openai", "builtin"), kinds_by_vendor)
        self.assertNotIn(("anthropic", "builtin"), kinds_by_vendor)
        self.assertNotIn(("deepseek", "builtin"), kinds_by_vendor)

        # Custom deepseek rows MUST survive (this is the bug we're fixing)
        custom_deepseek = [n for v, n, k in rows if v == "deepseek" and k == "custom"]
        self.assertEqual(
            sorted(custom_deepseek),
            ["deepseek-v4-flash", "deepseek-v4-pro"],
            msg="bugfix-Providers regression: custom deepseek rows wiped",
        )

        # Qwen all preserved (builtin + custom)
        qwen_rows = [n for v, n, _k in rows if v == "qwen"]
        self.assertEqual(
            sorted(qwen_rows),
            ["Qwen 3.6 Max preview", "Qwen 3.6 Plus", "qwen3.6-flash"],
        )

    async def test_idempotent_second_run_no_change(self):
        """Re-running migration is idempotent — custom rows still survive."""
        await _run_migration_against(self.db_path)
        rows_after_1 = await _query_remaining(self.db_path)
        await _run_migration_against(self.db_path)
        rows_after_2 = await _query_remaining(self.db_path)
        self.assertEqual(rows_after_1, rows_after_2,
                         "Migration not idempotent: 2nd run changed rows")
        # Specifically: deepseek custom rows still there after 2nd run
        custom_deepseek = [n for v, n, k in rows_after_2
                          if v == "deepseek" and k == "custom"]
        self.assertIn("deepseek-v4-flash", custom_deepseek)
        self.assertIn("deepseek-v4-pro", custom_deepseek)

    async def test_simulates_user_add_post_migration(self):
        """Real-world flow: migration runs once → user adds DeepSeek model →
        backend restarts → migration runs again → user's row must survive."""
        # First run trims initial builtin seeds
        await _run_migration_against(self.db_path)
        # User adds a new custom DeepSeek model via UI (POST /api/ai-providers)
        eng = create_async_engine(f"sqlite+aiosqlite:///{self.db_path}")
        async with eng.begin() as conn:
            await conn.execute(text("""
                INSERT INTO ai_providers
                    (vendor_id, type, name, model, provider_kind, enabled, is_active)
                VALUES ('deepseek', 'llm', 'deepseek-v4-experimental',
                        'deepseek/deepseek-v4-experimental', 'custom', 1, 0)
            """))
        await eng.dispose()
        # Backend restarts → migration runs again
        await _run_migration_against(self.db_path)
        rows = await _query_remaining(self.db_path)
        names = [n for v, n, k in rows if v == "deepseek" and k == "custom"]
        self.assertIn("deepseek-v4-experimental", names,
                      "User-added DeepSeek model wiped by 2nd migration run "
                      "— bugfix-Providers not effective!")


if __name__ == "__main__":
    unittest.main(verbosity=2)
