"""UX-001 — per-tool enable override 存储层。

chunk 7 ``mcp_client_state`` 跟踪 server 级 enabled override；本模块跟踪
**单 capability**（``ext.<server>.<tool>``）级 override。

设计准则：
  - 只存差异。表里没有的 (server, tool) 视为 ``enabled=True`` —— 默认放过
  - server 关 ⇒ 所有 tool **自动关**，但语义不污染本表（清不清都行）。
    实际由 ``client.py _connect_one`` 在 server 关时根本不 register tools
    实现，无需查 tool_state
  - 无内存缓存——每次问 DB。规模小（一个 server 最多几十 tool），且
    server-level toggle 已经覆盖了热路径
"""
from __future__ import annotations

import logging

from sqlalchemy import text

from backend.database import engine

logger = logging.getLogger(__name__)


async def is_enabled(server_name: str, tool_name: str) -> bool:
    """``True`` 除非用户在 UI 显式翻 OFF。"""
    async with engine.begin() as conn:
        row = (await conn.execute(text(
            "SELECT enabled FROM mcp_tool_state "
            "WHERE server_name=:s AND tool_name=:t"
        ), {"s": server_name, "t": tool_name})).first()
    if row is None:
        return True
    return bool(row[0])


async def list_overrides(server_name: str) -> dict[str, bool]:
    """Return ``{tool_name: enabled}`` for tools that have an override set.

    Tools without an override row are absent (caller treats as enabled=True).
    """
    async with engine.begin() as conn:
        rows = (await conn.execute(text(
            "SELECT tool_name, enabled FROM mcp_tool_state WHERE server_name=:s"
        ), {"s": server_name})).fetchall()
    return {r[0]: bool(r[1]) for r in rows}


async def set_enabled(server_name: str, tool_name: str, enabled: bool) -> None:
    """Upsert per-tool enabled override。"""
    if not server_name or not tool_name:
        raise ValueError("server_name and tool_name required")
    async with engine.begin() as conn:
        await conn.execute(text("""
            INSERT INTO mcp_tool_state (server_name, tool_name, enabled, updated_at)
            VALUES (:s, :t, :e, CURRENT_TIMESTAMP)
            ON CONFLICT(server_name, tool_name) DO UPDATE SET
              enabled=excluded.enabled,
              updated_at=CURRENT_TIMESTAMP
        """), {"s": server_name, "t": tool_name, "e": 1 if enabled else 0})


async def delete_for_server(server_name: str) -> int:
    """Clear all per-tool overrides for one server (e.g. after server uninstall)."""
    async with engine.begin() as conn:
        res = await conn.execute(text(
            "DELETE FROM mcp_tool_state WHERE server_name=:s"
        ), {"s": server_name})
        return getattr(res, "rowcount", 0) or 0
