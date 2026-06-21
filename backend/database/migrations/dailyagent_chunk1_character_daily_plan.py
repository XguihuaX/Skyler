"""DailyAgent chunk 1 — character_daily_plans 表(每角色每日活动日程)。

一行 = 一个 character 在某一本地日期(scheduler timezone)的全天 plan。
plan 列存 JSON 字符串(SQLite 无原生 JSON 类型),数组:

    [{"start": "07:00", "end": "08:30", "activity": "起床 + 早饭"}, ...]

UNIQUE(character_id, date) 防同日重复 — ticker 每 5min 查今日 row 命中
slot → 写 ``character_states.current_activity``。

幂等
====
* 沿 chunk 14 pattern:``sqlite_master`` 检查表是否存在,在则跳过
* 跑前 ``shutil.copyfile`` 备份 momoos.db(备份已存在则 skip 幂等)
* UNIQUE 约束 + 一个查询 index 用 ``CREATE INDEX IF NOT EXISTS`` 二次跑无副作用
"""
from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path
from typing import Optional

from sqlalchemy import text

from backend.database import engine

logger = logging.getLogger(__name__)

_BACKUP_SUFFIX = ".backup-before-dailyagent-chunk1"


def _resolve_db_path() -> Optional[Path]:
    """从 engine URL 解析 SQLite 文件路径。非 SQLite / 内存 DB 返 None。"""
    try:
        url = engine.url
    except Exception:
        return None
    if (url.get_backend_name() or "").lower() != "sqlite":
        return None
    db = url.database
    if not db or db == ":memory:":
        return None
    return Path(db).resolve()


def _maybe_backup_db() -> Optional[Path]:
    """跑前备份 momoos.db;已存在备份 → 跳过(幂等)。"""
    src = _resolve_db_path()
    if src is None:
        logger.info("DailyAgent-chunk1: non-sqlite or memory DB, skip backup")
        return None
    if not src.exists():
        logger.info("DailyAgent-chunk1: DB file %s not found, skip backup", src)
        return None
    dst = src.with_name(src.name + _BACKUP_SUFFIX)
    if dst.exists():
        logger.info(
            "DailyAgent-chunk1: backup already at %s, skip (idempotent)", dst,
        )
        return dst
    shutil.copyfile(src, dst)
    logger.info("DailyAgent-chunk1: DB backed up %s -> %s", src, dst)
    return dst


async def _table_exists(conn, table: str) -> bool:
    rows = (await conn.execute(text(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=:n"
    ), {"n": table})).fetchall()
    return len(rows) > 0


async def run_migration() -> None:
    """DailyAgent chunk 1 主迁移函数。幂等。"""
    _maybe_backup_db()

    async with engine.begin() as conn:
        if await _table_exists(conn, "character_daily_plans"):
            logger.info(
                "DailyAgent-chunk1: character_daily_plans already exists, skip"
            )
        else:
            await conn.execute(text("""
                CREATE TABLE character_daily_plans (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    character_id INTEGER NOT NULL,
                    date DATE NOT NULL,
                    plan TEXT NOT NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    CONSTRAINT uq_character_daily_plans_char_date
                        UNIQUE (character_id, date)
                )
            """))
            logger.info("DailyAgent-chunk1: character_daily_plans table created")

        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_character_daily_plans_char_date "
            "ON character_daily_plans(character_id, date)"
        ))

    logger.info("[daily_plan] character_daily_plans table ready")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
    )
    asyncio.run(run_migration())
