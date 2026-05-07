"""V3-G chunk 2 — chat_history.proactive_trigger 列。

伴随 v3-G chunk 2 通用 proactive engine 落地，给 chat_history 加一个可空的
``proactive_trigger`` 字段，记录这一行（kind='proactive'）是被哪个 trigger
拉起的（如 'morning_briefing'）。kind='normal'/'touch' 的行该列为 NULL。

幂等：先 PRAGMA table_info 检查列是否已存在；存在则跳过。

字段语义：
    proactive_trigger — TEXT NULL。trigger.name 写入这里（最长 64 字符 by
    convention，但 DB 用 TEXT 不强制 —— application 层 ProactiveTrigger 抽象
    类校验长度即可）。
    - NULL                  非 proactive 行（kind='normal' or 'touch'）
    - 'morning_briefing'    早晨简报（默认 cron 09:00）
    - 'meal_*' / 'evening' / ... 未来 v3-F' 加新 trigger 时按 trigger 自己的 name 写入

不下放到 DB enum / CHECK：未来加 trigger 不应需要 schema migration。
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
    """V3-G chunk 2 主迁移函数。幂等。"""
    async with engine.begin() as conn:
        if await _column_exists(conn, "chat_history", "proactive_trigger"):
            logger.info("V3-G-chunk2: chat_history.proactive_trigger 已存在，跳过")
            return

        await conn.execute(
            text(
                "ALTER TABLE chat_history "
                "ADD COLUMN proactive_trigger TEXT NULL"
            )
        )
        logger.info(
            "V3-G-chunk2: chat_history.proactive_trigger 列已添加（NULL 默认）"
        )

    logger.info("V3-G chunk 2 migration done")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    asyncio.run(run_migration())
