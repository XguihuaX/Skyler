"""UX-001 — ``mcp_tool_state`` 表（per-tool enable override，server 级 toggle 之外）。

chunk 7 ``mcp_client_state`` 跟踪 server 级 enabled override；本表跟踪
**单 capability** 级 override：server enabled 时也可以单独把某个 tool 关掉。

不存"默认 enabled"——只存"差异"。未在表里的 tool 视为 ``enabled=True``，
与 chunk 7 ``mcp_client_state`` 同语义。

幂等：``sqlite_master`` 探表存在则跳过。
"""
from __future__ import annotations

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
    async with engine.begin() as conn:
        if await _table_exists(conn, "mcp_tool_state"):
            logger.info("[migration] mcp_tool_state already exists, skipping")
            return
        await conn.execute(text("""
            CREATE TABLE mcp_tool_state (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                server_name TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                enabled BOOLEAN NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(server_name, tool_name)
            )
        """))
        await conn.execute(text(
            "CREATE INDEX idx_mcp_tool_state_server ON mcp_tool_state(server_name)"
        ))
        logger.info("[migration] mcp_tool_state created")
