"""V3-E1 Step Z.2 migration: 给 chat_history 表增加 kind TEXT NOT NULL DEFAULT 'normal' 列。

幂等：先用 PRAGMA table_info(chat_history) 检查列是否已存在，再决定是否
执行 ALTER TABLE。重复执行不会报错。

字段语义：
    kind — 这一行 chat_history 是怎么产生的，决定下游是否纳入 profile_summary 等分析。
        'normal'    默认。用户文字 / 语音输入正常对话产生的 user / assistant 行。
        'touch'     v3-E1 step 3 触摸 Live2D 触发的对话（user 占位 [touch] +
                    LLM 主动回复一句）。profile_summary 重写时白名单过滤掉。
        'proactive' 预留给 v3-F'：后端定时调度器（饭点 / 睡前 / 长时无互动）
                    主动开启的对话。同样不应作为 profile_summary 样本。
    valid set 在 application 层校验（services.add_chat_history），不下放到 DB
    enum / CHECK 约束 —— 避免下次新增 kind 时还要再写一次 schema migration。

旧记录全部认为是 'normal'（DEFAULT 子句生效）。即便是 v3-E1 step 3 之后
入库的实际 [touch] 旧行也算 normal —— profile_summary 已经吃过这些样本，
现在反过来"考古标记"反而 risky；让它们留在样本里，新行从此往后干净。
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
    """V3-E1 Step Z.2 主迁移函数。幂等，可重复执行。"""
    async with engine.begin() as conn:
        if await _column_exists(conn, "chat_history", "kind"):
            logger.info("V3-E1-Z.2: chat_history.kind 已存在，跳过")
            return

        await conn.execute(
            text(
                "ALTER TABLE chat_history "
                "ADD COLUMN kind TEXT NOT NULL DEFAULT 'normal'"
            )
        )
        logger.info("V3-E1-Z.2: chat_history.kind 列已添加（默认 'normal'）")

    logger.info("V3-E1-Z.2 migration done")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    asyncio.run(run_migration())
