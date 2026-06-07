"""V4 · users.current_character_id 列。

让 "上次选的角色" 持久化 — 重启 / reload 后回到上次。

幂等:先 PRAGMA table_info 检查列是否已存在;存在则跳过(同 v3.5 chunk 5a 风格)。

字段语义:
    current_character_id — INTEGER NULL。指向 ``characters.id`` 的软引用。
    - NULL          未选过 · 启动取 ``chars[0]`` 兜底
    - <int>         上次 character_switch 持久值;校验失败(角色已删 / id 不存在)
                    时静默回落 Momo · 永不崩

不设 FK 约束:SQLite FK 默认不强制;且需求明确"指向已删角色 → 静默回落 Momo
别崩"· 应用层校验更直接(``_resolve_conv_char`` 反查 characters 表存在性 + 前端
``chars.find(c.id===N)`` 校验)。
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
    """V4 users.current_character_id migration · 幂等。"""
    async with engine.begin() as conn:
        if await _column_exists(conn, "users", "current_character_id"):
            logger.info(
                "V4-users-current-char: users.current_character_id 已存在,跳过",
            )
            return

        await conn.execute(
            text(
                "ALTER TABLE users "
                "ADD COLUMN current_character_id INTEGER NULL"
            )
        )
        logger.info(
            "V4-users-current-char: users.current_character_id 列已添加(NULL 默认)",
        )

    logger.info("V4 users.current_character_id migration done")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    asyncio.run(run_migration())
