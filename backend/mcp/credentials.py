"""v3.5 chunk 7 — MCP server credentials + runtime enable override 存储层。

不暴露原始 ``value`` 给前端；只回 ``{key_name, configured: bool, updated_at}``
列表（``status`` 路径）。``get_env(server_name)`` 给 ``backend/mcp/client.py``
在启动子进程前注入到 env。

设计准则：
  - 明文存（V1）—— SQLite 文件在 ``~/.skyler/`` 已具系统级权限隔离。ROADMAP
    backlog "MCP 凭证加密" 等 OS keyring 接入时再升级
  - 全部用 ``aiosqlite`` async API + ``engine.begin()`` 事务，与 chunk 1.5 /
    chunk 5a / chunk 3b services 同模式
  - 不缓存——每次启动子进程前现读 DB，避免 stale env
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import text

from backend.database import engine

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Credentials CRUD
# ---------------------------------------------------------------------------

async def get_env(server_name: str) -> dict[str, str]:
    """Return ``{key_name: value}`` dict for the given server (empty if none).

    Used by ``backend/mcp/client.py`` to inject into the subprocess env right
    before ``stdio_client`` launches.
    """
    async with engine.begin() as conn:
        rows = (await conn.execute(text(
            "SELECT key_name, value FROM mcp_credentials WHERE server_name=:n"
        ), {"n": server_name})).fetchall()
    return {r[0]: r[1] for r in rows}


async def list_keys(server_name: str) -> list[dict]:
    """Return list of ``{key_name, configured: True, updated_at}`` — no values.

    Frontend uses this to render "API key configured ✓" badges without
    receiving secrets.
    """
    async with engine.begin() as conn:
        rows = (await conn.execute(text(
            "SELECT key_name, updated_at FROM mcp_credentials "
            "WHERE server_name=:n ORDER BY key_name"
        ), {"n": server_name})).fetchall()
    return [
        {"key_name": r[0], "configured": True, "updated_at": str(r[1]) if r[1] else None}
        for r in rows
    ]


async def upsert(server_name: str, key_name: str, value: str) -> None:
    """Insert or update a single credential. Empty value → delete."""
    key_name = key_name.strip()
    if not key_name:
        raise ValueError("key_name cannot be empty")
    async with engine.begin() as conn:
        if not value or not value.strip():
            await conn.execute(text(
                "DELETE FROM mcp_credentials WHERE server_name=:n AND key_name=:k"
            ), {"n": server_name, "k": key_name})
            return
        # SQLite UPSERT
        await conn.execute(text("""
            INSERT INTO mcp_credentials (server_name, key_name, value, updated_at)
            VALUES (:n, :k, :v, CURRENT_TIMESTAMP)
            ON CONFLICT(server_name, key_name) DO UPDATE SET
              value=excluded.value,
              updated_at=CURRENT_TIMESTAMP
        """), {"n": server_name, "k": key_name, "v": value})


async def delete_all(server_name: str) -> int:
    """Clear all credentials for one server. Returns rows deleted."""
    async with engine.begin() as conn:
        res = await conn.execute(text(
            "DELETE FROM mcp_credentials WHERE server_name=:n"
        ), {"n": server_name})
        return getattr(res, "rowcount", 0) or 0


# ---------------------------------------------------------------------------
# Runtime enable override
# ---------------------------------------------------------------------------

async def get_enabled_override(server_name: str) -> Optional[bool]:
    """Return True/False if user toggled in UI; None means "no override → use config.yaml default"."""
    async with engine.begin() as conn:
        row = (await conn.execute(text(
            "SELECT enabled FROM mcp_client_state WHERE server_name=:n"
        ), {"n": server_name})).first()
    if row is None:
        return None
    return bool(row[0])


async def set_enabled(server_name: str, enabled: bool) -> None:
    """Persist user's UI toggle. Subsequent client launches read this."""
    async with engine.begin() as conn:
        await conn.execute(text("""
            INSERT INTO mcp_client_state (server_name, enabled, updated_at)
            VALUES (:n, :e, CURRENT_TIMESTAMP)
            ON CONFLICT(server_name) DO UPDATE SET
              enabled=excluded.enabled,
              updated_at=CURRENT_TIMESTAMP
        """), {"n": server_name, "e": 1 if enabled else 0})


async def list_all_state() -> list[dict]:
    """Return all rows for diagnostic/debugging routes."""
    async with engine.begin() as conn:
        rows = (await conn.execute(text(
            "SELECT server_name, enabled, updated_at FROM mcp_client_state "
            "ORDER BY server_name"
        ))).fetchall()
    return [
        {"server_name": r[0], "enabled": bool(r[1]), "updated_at": str(r[2]) if r[2] else None}
        for r in rows
    ]
