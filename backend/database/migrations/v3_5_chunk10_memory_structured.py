"""V3.5 chunk 10 — memory 表结构化 + extractor state 表。

# Schema 扩展（``memory`` 表）

新加 6 个 column：

  * ``extracted_at`` TIMESTAMP NULL    —— worker / save_memory tool 写入时间戳
  * ``source_turn_id`` INTEGER NULL    —— 触发提取的 chat_history.id（worker 路径）
  * ``confidence`` REAL NULL           —— LLM 自评 0-1（validator 阈值过滤用）
  * ``quality_score`` REAL NULL        —— 综合质量（未来引入，当前 NULL）
  * ``entry_type`` TEXT NULL           —— fact / preference / event / commitment
  * ``extraction_source`` TEXT NOT NULL DEFAULT 'legacy'
        —— 'worker' / 'llm_save_memory' / 'manual' / 'legacy'

老 entries 自动 ``extraction_source='legacy'``（DEFAULT），其他字段 NULL。
**不强制重处理** —— 用户在 UI 上看"旧"角标即可，新 entries 自动用新路径。

# Schema 新表（``memory_extractor_state``）

跟踪每个 user 的 ``last_processed_turn_id``，让 worker 知道下次从哪
开始扫：

  CREATE TABLE memory_extractor_state (
      id                       INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id                  TEXT NOT NULL UNIQUE,
      last_processed_turn_id   INTEGER NOT NULL DEFAULT 0,
      updated_at               TIMESTAMP DEFAULT CURRENT_TIMESTAMP
  )

# 幂等

``PRAGMA table_info(memory)`` 探每个 column 是否存在；缺失才 ALTER ADD
COLUMN。新表用 ``CREATE TABLE IF NOT EXISTS``。二次跑全 no-op（与
chunk 11 commit 1 migration 同 pattern）。
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


async def _table_exists(conn, table: str) -> bool:
    rows = (await conn.execute(text(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=:n"
    ), {"n": table})).fetchall()
    return len(rows) > 0


# 期望加的 column 与 DDL 片段
_NEW_COLUMNS: list[tuple[str, str]] = [
    ("extracted_at",       "TIMESTAMP"),
    ("source_turn_id",     "INTEGER"),
    ("confidence",         "REAL"),
    ("quality_score",      "REAL"),
    ("entry_type",         "TEXT"),
    ("extraction_source",  "TEXT NOT NULL DEFAULT 'legacy'"),
]


async def run_migration() -> None:
    """V3.5 chunk 10 主迁移。幂等。"""
    async with engine.begin() as conn:
        # 1. memory 表 6 个新 column
        added: list[str] = []
        skipped: list[str] = []
        for col, ddl in _NEW_COLUMNS:
            if await _column_exists(conn, "memory", col):
                skipped.append(col)
                continue
            await conn.execute(text(
                f"ALTER TABLE memory ADD COLUMN {col} {ddl}"
            ))
            added.append(col)
        if added:
            logger.info(
                "V3.5-chunk10: memory 表加列 %s（其他 %s 已存在跳过）",
                added, skipped,
            )
        else:
            logger.info(
                "V3.5-chunk10: memory 表 6 个 column 全部已存在，跳过"
            )

        # 2. memory_extractor_state 表
        if not await _table_exists(conn, "memory_extractor_state"):
            await conn.execute(text("""
                CREATE TABLE memory_extractor_state (
                    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id                TEXT NOT NULL UNIQUE,
                    last_processed_turn_id INTEGER NOT NULL DEFAULT 0,
                    updated_at             TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
            logger.info("V3.5-chunk10: memory_extractor_state 表已创建")
        else:
            logger.info(
                "V3.5-chunk10: memory_extractor_state 已存在，跳过"
            )

        # 3. log legacy / new 分布
        legacy = (await conn.execute(text(
            "SELECT COUNT(*) FROM memory WHERE extraction_source = 'legacy'"
        ))).fetchone()
        non_legacy = (await conn.execute(text(
            "SELECT COUNT(*) FROM memory WHERE extraction_source != 'legacy'"
        ))).fetchone()
        logger.info(
            "V3.5-chunk10: memory entries — legacy=%d / non-legacy=%d "
            "（worker 启动后新 entries 标 'worker' / 'llm_save_memory'）",
            int(legacy[0] if legacy else 0),
            int(non_legacy[0] if non_legacy else 0),
        )

    logger.info("V3.5 chunk 10 migration done")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    asyncio.run(run_migration())
