"""V3-B migration: 给 characters 表增加 voice_model TEXT NULL 列。

幂等：先用 PRAGMA table_info(characters) 检查列是否已存在，再决定是否
执行 ALTER TABLE。重复执行不会报错。

字段语义：
    voice_model — 角色专属 TTS 音色标识，留空表示沿用全局默认。
                 例如 "zh-CN-XiaoxiaoNeural" 或 SoVITS 模型路径。
                 v3-B 阶段只存不用，等后续 SoVITS 接入时消费。
"""
import asyncio
import logging

from sqlalchemy import text

from backend.database import engine

logger = logging.getLogger(__name__)


async def _column_exists(conn, table: str, column: str) -> bool:
    """通过 PRAGMA table_info 判断列是否存在。"""
    rows = (await conn.execute(text(f"PRAGMA table_info({table})"))).fetchall()
    # PRAGMA table_info 每行第二列是列名
    return any(row[1] == column for row in rows)


async def run_migration() -> None:
    """V3-B 主迁移函数。幂等，可重复执行。"""
    async with engine.begin() as conn:
        if await _column_exists(conn, "characters", "voice_model"):
            logger.info("V3-B: characters.voice_model 已存在，跳过")
            return

        await conn.execute(
            text("ALTER TABLE characters ADD COLUMN voice_model TEXT")
        )
        logger.info("V3-B: characters.voice_model 列已添加")

    logger.info("V3-B migration done")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    asyncio.run(run_migration())
