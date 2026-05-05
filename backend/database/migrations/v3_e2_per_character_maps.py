"""V3-E2 migration: per-character emotion / motion / hit-area map JSON 字段。

幂等：先用 PRAGMA table_info(characters) 检查列是否已存在，再决定是否
执行 ALTER TABLE。重复执行不会报错。

字段语义
--------
全部 TEXT NULL，存 JSON 字符串。NULL / 空 → 前端 ``resolveCharacterMaps``
回退到 v3-E1 的全局默认（``frontend/src/config/live2d.ts`` 里 emotionMap /
motionMap）。

    emotion_map_json  ← LLM emotion 词 → expression 文件名 / 参数偏移列表
    motion_map_json   ← LLM motion 词 → { group, index }
    hit_area_map_json ← Live2D hit area 名 → 触摸响应 motion group

V3-E1 阶段所有现有行（Hiyori / 默认 Momo）写入 NULL，体验完全不变。
v3-E2 起接入新模型时，给 character 写自己的 map JSON。

Schema 不下放 JSON 校验，前端 ``resolveCharacterMaps`` parse 失败兜底
回退默认 + console.warn —— 避免 DB CHECK 阻塞调试期 UI 试错。
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
    """V3-E2 主迁移函数。幂等，可重复执行。"""
    cols = ("emotion_map_json", "motion_map_json", "hit_area_map_json")
    async with engine.begin() as conn:
        for col in cols:
            if await _column_exists(conn, "characters", col):
                logger.info("V3-E2: characters.%s 已存在，跳过", col)
                continue
            await conn.execute(
                text(f"ALTER TABLE characters ADD COLUMN {col} TEXT")
            )
            logger.info("V3-E2: characters.%s 列已添加", col)

    logger.info("V3-E2 migration done")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    asyncio.run(run_migration())
