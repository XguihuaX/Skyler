"""V3.5 chunk 7 — MCP server credentials + runtime enable override 表。

为 chunk 7 姿态 B（外部 MCP server 一键启用）持久化两份元数据：

1. ``mcp_credentials``    用户从 SettingsPanel 配的 API key / token，启动子
                          进程时注入到 env。明文存（V1 spec：SQLite 已在
                          ``~/.skyler/``，比写 ``.env`` 风险等价；ROADMAP
                          backlog 加密 backlog）
2. ``mcp_client_state``   runtime enable override。``config.yaml mcp_clients``
                          那 ``enabled: false`` 是 default；用户在 UI 翻 ON
                          后这里持久化，重启沿用。仅存"差异"——未列条目
                          走 config.yaml 默认。

幂等：先 ``PRAGMA table_info`` / ``sqlite_master`` 检查，存在则跳过；与
chunk 2/3 / chunk 5a migration 同 pattern。
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
    """V3.5 chunk 7 主迁移函数。幂等。"""
    async with engine.begin() as conn:
        if not await _table_exists(conn, "mcp_credentials"):
            await conn.execute(text("""
                CREATE TABLE mcp_credentials (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    server_name TEXT NOT NULL,
                    key_name TEXT NOT NULL,
                    value TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(server_name, key_name)
                )
            """))
            await conn.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_mcp_creds_server "
                "ON mcp_credentials(server_name)"
            ))
            logger.info("V3.5-chunk7: mcp_credentials 表已创建")
        else:
            logger.info("V3.5-chunk7: mcp_credentials 已存在，跳过")

        if not await _table_exists(conn, "mcp_client_state"):
            await conn.execute(text("""
                CREATE TABLE mcp_client_state (
                    server_name TEXT PRIMARY KEY,
                    enabled INTEGER NOT NULL DEFAULT 0,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
            logger.info("V3.5-chunk7: mcp_client_state 表已创建")
        else:
            logger.info("V3.5-chunk7: mcp_client_state 已存在，跳过")

    logger.info("V3.5 chunk 7 migration done")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    asyncio.run(run_migration())
