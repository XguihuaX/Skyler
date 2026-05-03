"""V3-F migration: 给 chat_history 表增加 interrupted_at DATETIME NULL 列。

幂等：先用 PRAGMA table_info(chat_history) 检查列是否已存在，再决定是否
执行 ALTER TABLE。重复执行不会报错。

字段语义：
    interrupted_at — assistant 行被语音 / UI 打断生成时记录的时间戳。
                     None 表示该轮正常生成完毕；非空表示这一行的内容是
                     被中途截断的"半截回复"。仅 assistant role 写入。
                     v3-F #4 使用，前端可据此画灰色 "被打断" 视觉标记。
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
    """V3-F 主迁移函数。幂等，可重复执行。"""
    async with engine.begin() as conn:
        if await _column_exists(conn, "chat_history", "interrupted_at"):
            logger.info("V3-F: chat_history.interrupted_at 已存在，跳过")
            return

        await conn.execute(
            text("ALTER TABLE chat_history ADD COLUMN interrupted_at DATETIME")
        )
        logger.info("V3-F: chat_history.interrupted_at 列已添加")

    logger.info("V3-F migration done")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    asyncio.run(run_migration())
