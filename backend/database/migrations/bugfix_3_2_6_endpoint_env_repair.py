"""Bugfix-3.2.6 — endpoint_env_name 列 + enabled/active 一致性修补。

3 件:

1. ALTER TABLE ai_vendors ADD COLUMN endpoint_env_name (TEXT nullable)
   - 用 PRAGMA table_info 幂等检查, 列已存在则跳过

2. 给 4 个 builtin vendor 写 endpoint_env_name(只在当前为 NULL 时写,不覆盖用户改过的 custom)
   - qwen      → DASHSCOPE_BASE_URL
   - openai    → OPENAI_BASE_URL
   - anthropic → ANTHROPIC_BASE_URL
   - deepseek  → DEEPSEEK_BASE_URL

3. 修补 inconsistent state: is_active=1 AND enabled=0 → 强制 enabled=1
   现有 DB 可能因为 bugfix-3.2.5 之前的 bug 留下这种自相矛盾的行,本 migration
   一次性扫表修。dispatcher 校验 enabled 会把 active+disabled 当成 no_db_active
   错乱。

幂等:
  - ALTER TABLE 用 PRAGMA table_info 提前检查列存在与否
  - UPDATE endpoint_env_name 用 WHERE endpoint_env_name IS NULL
  - UPDATE enabled 用 WHERE is_active=1 AND enabled=0
"""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy import text

from backend.database import engine

logger = logging.getLogger(__name__)


_VENDOR_ENV_NAME_MAP = {
    "qwen":      "DASHSCOPE_BASE_URL",
    "openai":    "OPENAI_BASE_URL",
    "anthropic": "ANTHROPIC_BASE_URL",
    "deepseek":  "DEEPSEEK_BASE_URL",
}


async def _column_exists(conn, table: str, column: str) -> bool:
    rows = (await conn.execute(text(
        f"PRAGMA table_info({table})"
    ))).fetchall()
    return any(r[1] == column for r in rows)


async def run_migration() -> None:
    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA foreign_keys = ON"))

        # ---- 1. ALTER TABLE ai_vendors ADD COLUMN endpoint_env_name ----
        if not await _column_exists(conn, "ai_vendors", "endpoint_env_name"):
            await conn.execute(text(
                "ALTER TABLE ai_vendors ADD COLUMN endpoint_env_name TEXT"
            ))
            logger.info("[bugfix-3.2.6] ai_vendors.endpoint_env_name column added")
        else:
            logger.info("[bugfix-3.2.6] ai_vendors.endpoint_env_name exists, skip")

        # ---- 2. backfill endpoint_env_name for builtin vendors ----
        backfilled = 0
        for vendor_id, env_name in _VENDOR_ENV_NAME_MAP.items():
            result = await conn.execute(text("""
                UPDATE ai_vendors
                SET endpoint_env_name = :env_name, updated_at = CURRENT_TIMESTAMP
                WHERE id = :id AND endpoint_env_name IS NULL
            """), {"id": vendor_id, "env_name": env_name})
            backfilled += getattr(result, "rowcount", 0) or 0
        logger.info(
            "[bugfix-3.2.6] backfilled endpoint_env_name on %d vendor row(s)",
            backfilled,
        )

        # ---- 3. repair inconsistent is_active=1 AND enabled=0 ----
        repair = await conn.execute(text("""
            UPDATE ai_providers
            SET enabled = 1, updated_at = CURRENT_TIMESTAMP
            WHERE is_active = 1 AND enabled = 0
        """))
        repaired = getattr(repair, "rowcount", 0) or 0
        if repaired > 0:
            logger.warning(
                "[bugfix-3.2.6] repaired %d inconsistent provider(s) "
                "(is_active=1 AND enabled=0 → enabled=1)",
                repaired,
            )
        else:
            logger.info(
                "[bugfix-3.2.6] no inconsistent providers to repair"
            )

    logger.info("[bugfix-3.2.6] migration done")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    asyncio.run(run_migration())
