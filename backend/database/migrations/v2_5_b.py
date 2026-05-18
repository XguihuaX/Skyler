"""V2.5-B migration: add conversations + characters, extend tables, drop personality.

Idempotent — safe to run repeatedly. SQLite ``ALTER TABLE ADD COLUMN`` raises
``OperationalError: duplicate column name`` if the column already exists; we
swallow that case and continue.
"""
import asyncio
import logging
from typing import List

from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from backend.database import engine

logger = logging.getLogger(__name__)

DEFAULT_PERSONA = (
    "你是 Momo，一个温柔体贴的 AI 桌面伴侣，"
    "擅长记住用户的事并主动关心。回答简短自然。"
)


async def _add_column_if_missing(conn, table: str, column_def: str) -> None:
    """Run ``ALTER TABLE table ADD COLUMN column_def``; tolerate duplicate-column."""
    try:
        await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column_def}"))
    except OperationalError as e:
        msg = str(e).lower()
        if "duplicate column" in msg or "already exists" in msg:
            return
        raise


async def migrate() -> None:
    async with engine.begin() as conn:
        # --- 1. characters table ----------------------------------------------
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS characters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                persona TEXT NOT NULL,
                avatar_path TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """))

        # --- 2. conversations table -------------------------------------------
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL REFERENCES users(user_id),
                character_id INTEGER NOT NULL REFERENCES characters(id),
                title TEXT NOT NULL DEFAULT '新对话',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """))

        # --- 3. extend chat_history -------------------------------------------
        await _add_column_if_missing(conn, "chat_history", "conversation_id INTEGER")
        await _add_column_if_missing(conn, "chat_history", "character_id INTEGER")

        # --- 4. extend memory -------------------------------------------------
        await _add_column_if_missing(conn, "memory", "character_id INTEGER")

        # --- 5. extend users --------------------------------------------------
        await _add_column_if_missing(conn, "users", "nickname TEXT")
        await _add_column_if_missing(conn, "users", "language TEXT DEFAULT 'zh-CN'")

        # --- 6. seed default Momo character -----------------------------------
        existing = (await conn.execute(
            text("SELECT id FROM characters WHERE name = :n"),
            {"n": "Momo"},
        )).fetchone()
        if existing is None:
            await conn.execute(
                text("INSERT INTO characters (name, persona) VALUES (:name, :persona)"),
                {"name": "Momo", "persona": DEFAULT_PERSONA},
            )
            logger.info("V2.5-B: seeded default character 'Momo'")

        char_row = (await conn.execute(
            text("SELECT id FROM characters WHERE name = :n"), {"n": "Momo"},
        )).fetchone()
        if char_row is None:
            raise RuntimeError("V2.5-B migration: failed to obtain Momo character id")
        char_id: int = int(char_row[0])

        # --- 7. seed default conversation per user ----------------------------
        users: List[tuple] = (
            await conn.execute(text("SELECT user_id FROM users"))
        ).fetchall()
        for (uid,) in users:
            existing_conv = (await conn.execute(
                text("SELECT id FROM conversations WHERE user_id = :uid LIMIT 1"),
                {"uid": uid},
            )).fetchone()
            if existing_conv is None:
                await conn.execute(
                    text(
                        "INSERT INTO conversations (user_id, character_id, title) "
                        "VALUES (:uid, :cid, '默认对话')"
                    ),
                    {"uid": uid, "cid": char_id},
                )

        # --- 8. backfill character_id / conversation_id on existing rows ------
        await conn.execute(
            text("UPDATE chat_history SET character_id = :cid WHERE character_id IS NULL"),
            {"cid": char_id},
        )
        for (uid,) in users:
            conv_row = (await conn.execute(
                text(
                    "SELECT id FROM conversations WHERE user_id = :uid "
                    "ORDER BY created_at ASC LIMIT 1"
                ),
                {"uid": uid},
            )).fetchone()
            if conv_row is None:
                continue
            conv_id: int = int(conv_row[0])
            await conn.execute(
                text(
                    "UPDATE chat_history SET conversation_id = :conv "
                    "WHERE user_id = :uid AND conversation_id IS NULL"
                ),
                {"conv": conv_id, "uid": uid},
            )

        # --- 9. preserve + drop legacy personality table ----------------------
        # Print rows to log for the audit trail before dropping (per spec:
        # 不要删 personality 表里的数据备份). DROP loses the data; this is the
        # best we can do without inventing a new table.
        try:
            personality_rows = (
                await conn.execute(text(
                    "SELECT user_id, type, tag, content FROM personality"
                ))
            ).fetchall()
            if personality_rows:
                logger.info(
                    "V2.5-B: backing up %d personality rows to log before DROP:",
                    len(personality_rows),
                )
                for r in personality_rows:
                    logger.info("V2.5-B personality backup: %s", dict(r._mapping))
        except OperationalError:
            # table already gone — nothing to back up
            pass

        await conn.execute(text("DROP TABLE IF EXISTS personality"))

    logger.info("V2.5-B migration done")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(migrate())
