"""V3.5 chunk 5a — characters.background_path 列。

让每个 character 可以独立绑定一段背景资产（图 / 视频），CharacterView
在 Live2D 之后的背景层渲染。无值时回退到现有静态 jpeg fallback，与
chunk 5 之前行为完全一致。

幂等：先 PRAGMA table_info 检查列是否已存在；存在则跳过（与 v3-G chunk 2
同 pattern）。

字段语义：
    background_path — TEXT NULL。Vite static URL（以 ``/`` 开头），如
    ``/backgrounds/tokyo_rain.mp4`` 或 ``/backgrounds/shrine_night.jpg``。
    后缀决定前端用 ``<img>`` 还是 ``<video>``。
    - NULL                  未配置 → CharacterView 继续原 fallback 链
    - ``/backgrounds/...``  per-character 背景

不下放到 DB enum / CHECK：后缀白名单由 backend/routes/backgrounds_api.py
scanner + frontend dispatch 维护，schema 不强校验，避免新增 codec 时还得
跑 migration。
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
    """V3.5 chunk 5a 主迁移函数。幂等。"""
    async with engine.begin() as conn:
        if await _column_exists(conn, "characters", "background_path"):
            logger.info(
                "V3.5-chunk5a: characters.background_path 已存在，跳过",
            )
            return

        await conn.execute(
            text(
                "ALTER TABLE characters "
                "ADD COLUMN background_path TEXT NULL"
            )
        )
        logger.info(
            "V3.5-chunk5a: characters.background_path 列已添加（NULL 默认）",
        )

    logger.info("V3.5 chunk 5a migration done")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    asyncio.run(run_migration())
