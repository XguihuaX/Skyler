"""V3-E1 migration: 给 characters 表增加 live2d_model TEXT NULL 列。

幂等：先用 PRAGMA table_info(characters) 检查列是否已存在，再决定是否
执行 ALTER TABLE。重复执行不会报错。

字段语义：
    live2d_model — 角色专属 Live2D 模型标识，对应
                   frontend/public/live2d/<live2d_model>/ 目录名。
                   留空 / NULL 表示该角色不启用 Live2D，渲染层回退到
                   静态 avatar_path 图片。
                   v3-E1 阶段只存不用，等 Step 2 CharacterView 改造接通
                   PIXI 渲染管道后才会真正消费此字段。
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
    """V3-E1 主迁移函数。幂等，可重复执行。"""
    async with engine.begin() as conn:
        if await _column_exists(conn, "characters", "live2d_model"):
            logger.info("V3-E1: characters.live2d_model 已存在，跳过")
            return

        await conn.execute(
            text("ALTER TABLE characters ADD COLUMN live2d_model TEXT")
        )
        logger.info("V3-E1: characters.live2d_model 列已添加")

    logger.info("V3-E1 migration done")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    asyncio.run(run_migration())
