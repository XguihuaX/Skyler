"""A2 翻译架构 — characters.response_language 列。

LLM 输出语种字段:字符 per-character 配置 LLM 应输出哪种语言("zh" / "ja" / "en")。
翻译层读此字段决定是否翻译(response_language != tts_language → translate)。

幂等:先 PRAGMA table_info 检查列是否已存在;已存在则跳过。
backfill:存量行全部回填 'zh'(现有所有角色 LLM 输出中文)。
"""
import asyncio
import logging

from sqlalchemy import text

from backend.database import engine

logger = logging.getLogger(__name__)


async def _column_exists(conn, table: str, column: str) -> bool:
    rows = (await conn.execute(text(f"PRAGMA table_info({table})"))).fetchall()
    return any(row[1] == column for row in rows)


async def run_migration() -> None:
    """A2 characters.response_language migration · 幂等。"""
    async with engine.begin() as conn:
        if await _column_exists(conn, "characters", "response_language"):
            logger.info(
                "A2-response-language: characters.response_language 已存在,跳过",
            )
            return

        await conn.execute(
            text(
                "ALTER TABLE characters "
                "ADD COLUMN response_language TEXT DEFAULT 'zh'"
            )
        )
        await conn.execute(
            text(
                "UPDATE characters SET response_language = 'zh' "
                "WHERE response_language IS NULL"
            )
        )
        logger.info(
            "A2-response-language: characters.response_language 列已添加并回填 'zh'",
        )

    logger.info("A2 characters.response_language migration done")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    asyncio.run(run_migration())
