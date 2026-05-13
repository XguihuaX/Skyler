"""V3.5 chunk 14 — activity_sessions 表(每日活动记录 timeline)。

新表与 chat_history **平行**:chat_history 是用户跟 Momo 的对话流;
activity_sessions 是用户对 app / 浏览器 URL 的停留流。

Schema 决定
============
* ``app_name``           NOT NULL — 始终有 frontmost app(NSWorkspace 返值)
* ``browser_url``        NULLABLE — 只在浏览器是 frontmost 时填(hotfix-9 语义)
* ``browser_title``      NULLABLE — 同上
* ``category``           NULLABLE — backend session-writer 内推断;NULL 视作
                          "other",前端 timeline 也照样可显示
* ``is_idle_filtered``   INT 默 0 — chunk 8a-ext V2 idle 闸命中期间的 stay,
                          仍写表(给 timeline UI 看完整记录),但 capability
                          summary 计算时可选 exclude(SettingsPanel toggle)
* ``duration_seconds``   INT NOT NULL — 写入前 caller 算好;短 session
                          (< 30s)由 caller 直接 skip,**表中不存在**

幂等
====
* 沿 chunk 7 / chunk 10 pattern:``sqlite_master`` 检查表是否存在,在则跳过
* 跑前 ``shutil.copyfile`` 备份 momoos.db(对齐 chunk 6b hotfix-3 模板,
  备份已存在则 skip 幂等)
* 两 index 用 ``CREATE INDEX IF NOT EXISTS`` 二次跑无副作用
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

_BACKUP_SUFFIX = ".backup-before-chunk14"


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
        logger.info("V3.5-chunk14: non-sqlite or memory DB, skip backup")
        return None
    if not src.exists():
        logger.info("V3.5-chunk14: DB file %s not found, skip backup", src)
        return None
    dst = src.with_name(src.name + _BACKUP_SUFFIX)
    if dst.exists():
        logger.info(
            "V3.5-chunk14: backup already at %s, skip (idempotent)", dst,
        )
        return dst
    shutil.copyfile(src, dst)
    logger.info("V3.5-chunk14: DB backed up %s -> %s", src, dst)
    return dst


async def _table_exists(conn, table: str) -> bool:
    rows = (await conn.execute(text(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=:n"
    ), {"n": table})).fetchall()
    return len(rows) > 0


async def run_migration() -> None:
    """V3.5 chunk 14 主迁移函数。幂等。"""
    _maybe_backup_db()

    async with engine.begin() as conn:
        if await _table_exists(conn, "activity_sessions"):
            logger.info(
                "V3.5-chunk14: activity_sessions already exists, skip"
            )
        else:
            await conn.execute(text("""
                CREATE TABLE activity_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL DEFAULT 'default',
                    start_at DATETIME NOT NULL,
                    end_at DATETIME NOT NULL,
                    duration_seconds INTEGER NOT NULL,
                    app_name TEXT NOT NULL,
                    browser_url TEXT,
                    browser_title TEXT,
                    category TEXT,
                    is_idle_filtered INTEGER NOT NULL DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))
            logger.info("V3.5-chunk14: activity_sessions table created")

        # 两个 index 都 IF NOT EXISTS,二次跑安全
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_activity_sessions_user_date "
            "ON activity_sessions(user_id, start_at)"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_activity_sessions_app "
            "ON activity_sessions(app_name)"
        ))

    logger.info("[activity_timeline] sessions table ready")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
    )
    asyncio.run(run_migration())
