"""V3.5 chunk 11 — users.profile_data 列（structured profile）。

新加 column 到 ``users`` 表：

* ``profile_data`` TEXT NULL  —— 存 JSON 字符串（SQLite 无原生 JSON）。
  schema 见 ``backend/utils/profile_schema.py PROFILE_SCHEMA_V1``。

向后兼容：``profile_summary`` (chunk 9) 字段**保留不删**。chunk 11
注入逻辑优先 ``profile_data``，fallback 到 legacy ``profile_summary``。
等 N 个版本后真删 legacy（README Known Problems 标 low 优先级 backlog）。

# 幂等

``PRAGMA table_info(users)`` 探 column 是否存在；缺失才 ``ALTER TABLE ADD
COLUMN``。SQLite ADD COLUMN 不支持 IF NOT EXISTS，前置 PRAGMA 检查（与
chunk 9 forgetting_curve / chunk 6b hotfix-3 同 pattern）。

# 初始化

不显式回填 —— 现有 user 行 ``profile_data`` 默认 NULL；chunk 11 cron
（每天 23:55）触发后自动填充。``_compute_profile_summary`` legacy 路径
保留 profile_summary 字段直到用户主动迁移。
"""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy import text

from backend.database import engine

logger = logging.getLogger(__name__)


async def _column_exists(conn, table: str, column: str) -> bool:
    rows = (await conn.execute(text(f"PRAGMA table_info({table})"))).fetchall()
    return any(r[1] == column for r in rows)


async def run_migration() -> None:
    """V3.5 chunk 11 主迁移。幂等。"""
    async with engine.begin() as conn:
        if not await _column_exists(conn, "users", "profile_data"):
            await conn.execute(text(
                "ALTER TABLE users ADD COLUMN profile_data TEXT"
            ))
            logger.info("V3.5-chunk11: users.profile_data 列已加（NULL 初始）")
        else:
            logger.info("V3.5-chunk11: users.profile_data 已存在，跳过")

        # 统计 candidates / initialized 给 log 看（不写 default 值）
        rows = (await conn.execute(text(
            "SELECT COUNT(*) FROM users"
        ))).fetchone()
        candidate_n = int(rows[0] if rows else 0)
        null_rows = (await conn.execute(text(
            "SELECT COUNT(*) FROM users WHERE profile_data IS NULL"
        ))).fetchone()
        null_n = int(null_rows[0] if null_rows else 0)
        logger.info(
            "V3.5-chunk11: users 总 %d 行 / profile_data IS NULL %d 行 "
            "（cron 首次触发后自动填充）",
            candidate_n, null_n,
        )

    logger.info("V3.5 chunk 11 migration done")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    asyncio.run(run_migration())
