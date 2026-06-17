"""INV (2026-06-15) ⑤ — mcp_tool_state 加 require_confirmation 列。

⑤ confirm gate:dangerous tool 调用前 WS 弹确认窗。三态:
  - enabled=1, require_confirmation=0:正常调用,无确认
  - enabled=1, require_confirmation=1:调用前 push WS event,await accept
  - enabled=0:LLM 见不到工具(原 UX-001 语义不变)

config.yaml entry 的 `dangerous_tools: [...]` 在 backend/mcp/client.py
_holder_task ENTER 时 seed `require_confirmation=1`(幂等 · 不覆盖已有 override),
让用户在 UI 仍可手动取消"调用前确认"(对自己负责的场景)。

幂等:`PRAGMA table_info` 检查列是否存在 · SQLite ALTER TABLE ADD COLUMN
不可重入,加前置 check 防 OperationalError。
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


async def _column_exists(conn, table: str, column: str) -> bool:
    rows = (await conn.execute(text(
        f"PRAGMA table_info({table})"
    ))).fetchall()
    return any(r[1] == column for r in rows)


async def run_migration() -> None:
    async with engine.begin() as conn:
        if not await _table_exists(conn, "mcp_tool_state"):
            logger.info(
                "[mcp_tool_confirmation] mcp_tool_state table missing · "
                "UX-001 migration not yet applied · skip"
            )
            return
        if await _column_exists(conn, "mcp_tool_state", "require_confirmation"):
            logger.info(
                "[mcp_tool_confirmation] require_confirmation column exists · skip"
            )
            return
        await conn.execute(text(
            "ALTER TABLE mcp_tool_state ADD COLUMN "
            "require_confirmation INTEGER NOT NULL DEFAULT 0"
        ))
        logger.info(
            "[mcp_tool_confirmation] added require_confirmation column to mcp_tool_state"
        )
