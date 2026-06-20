"""V4 — MCP server alias / 用户自定义昵称 侧表。

为啥独立侧表(不进 ``mcp_client_state``):
    ``mcp_client_state`` 表语义是 "行存在 = enabled override"。给一个 yaml
    enabled 但用户从未 UI toggle 过的 server 设别名会触发 INSERT,带
    ``enabled=0`` 默认值,**静默禁用它**。侧表 ``mcp_client_alias`` 与 override
    零交互:加别名不影响 enabled 状态;清别名 = 删行,不影响 enabled。

幂等:先 ``sqlite_master`` 检查表存在性,与 chunk 7 / chunk 5a migration 同
pattern。
"""
import asyncio
import logging

from sqlalchemy import text

from backend.database import engine

logger = logging.getLogger(__name__)


async def _table_exists(conn, table: str) -> bool:
    rows = (await conn.execute(text(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=:n"
    ), {"n": table})).fetchall()
    return len(rows) > 0


async def run_migration() -> None:
    """V4 mcp_client_alias 主迁移。幂等。"""
    async with engine.begin() as conn:
        if not await _table_exists(conn, "mcp_client_alias"):
            await conn.execute(text("""
                CREATE TABLE mcp_client_alias (
                    server_name TEXT PRIMARY KEY,
                    alias TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
            logger.info("V4 mcp_client_alias: 表已创建")
        else:
            logger.info("V4 mcp_client_alias: 已存在,跳过")

    logger.info("V4 mcp_client_alias migration done")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    asyncio.run(run_migration())
