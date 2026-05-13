"""V4-fan chunk 1 — characters.splash_art_url 列。

为 Fan UI(扇面卡牌选角)加每角色立绘字段。卡牌底图主视觉,与现有
``avatar_path`` / ``live2d_model`` / ``background_path`` 平级 —— 各自负责
不同视觉位:

    avatar_path     — 圆形小头像(TopBar / list)
    live2d_model    — 沉浸态(选定后的主视图,渲染管道)
    background_path — 沉浸态背景层(可与 Live2D 同框)
    splash_art_url  — 扇面浏览态卡牌底图(本字段,新增)

幂等:先 PRAGMA table_info 检查列是否已存在,与 v3-E1 / v3.5-chunk5a 同
pattern。

字段语义:
    splash_art_url — TEXT NULL。Vite static URL(以 ``/`` 开头),如
    ``/splash-art/2.jpg`` 或 ``/splash-art/5.png``。
    - NULL                  未配置 → Fan UI 走 fallback 占位
    - ``/splash-art/...``   已上传立绘
    后端 ``POST /api/characters/{id}/splash-art`` 接收 multipart 单图,
    落到 ``frontend/public/splash-art/<id>.<ext>``,文件名以 character.id
    为 key(改名安全 + 删 character 时 cleanup 简单)。

不下放到 DB enum / CHECK:扩展名白名单由 backend/routes/characters_api.py
upload endpoint 维护,schema 不强校验,避免新增格式时还得跑 migration。
"""
import asyncio
import logging

from sqlalchemy import text

from backend.database import engine

logger = logging.getLogger(__name__)


async def _column_exists(conn, table: str, column: str) -> bool:
    """通过 PRAGMA table_info 判断列是否存在。"""
    rows = (await conn.execute(text(f"PRAGMA table_info({table})"))).fetchall()
    return any(row[1] == column for row in rows)


async def run_migration() -> None:
    """V4-fan chunk 1 主迁移函数。幂等,可重复执行。"""
    async with engine.begin() as conn:
        if await _column_exists(conn, "characters", "splash_art_url"):
            logger.info(
                "V4-fan-chunk1: characters.splash_art_url 已存在,跳过",
            )
            return

        await conn.execute(
            text("ALTER TABLE characters ADD COLUMN splash_art_url TEXT")
        )
        logger.info("V4-fan-chunk1: characters.splash_art_url 列已添加")

    logger.info("V4-fan-chunk1 migration done")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    asyncio.run(run_migration())
