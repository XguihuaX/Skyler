"""UX-001 — backend/mcp/tool_state.py per-tool override 存储层 + migration。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from sqlalchemy import text

from backend.database import engine
from backend.database.migrations.v3_5_uxr1_mcp_tool_state import (
    run_migration as migrate_uxr1,
)
from backend.mcp import tool_state


SERVER = "unit_test_server"


async def _cleanup() -> None:
    async with engine.begin() as conn:
        await conn.execute(text(
            "DELETE FROM mcp_tool_state WHERE server_name=:s"
        ), {"s": SERVER})


@pytest.fixture(autouse=True)
async def _ensure_schema():
    await migrate_uxr1()
    await _cleanup()
    yield
    await _cleanup()


async def test_default_enabled_when_no_override() -> None:
    """未登记的 (server, tool) 默认 enabled=True。"""
    assert await tool_state.is_enabled(SERVER, "anything") is True


async def test_set_enabled_then_query() -> None:
    await tool_state.set_enabled(SERVER, "create_page", False)
    assert await tool_state.is_enabled(SERVER, "create_page") is False
    await tool_state.set_enabled(SERVER, "create_page", True)
    assert await tool_state.is_enabled(SERVER, "create_page") is True


async def test_list_overrides_only_diff() -> None:
    """list_overrides 不返默认 enabled=True 的 tool（只返存了行的）。"""
    await tool_state.set_enabled(SERVER, "a", False)
    await tool_state.set_enabled(SERVER, "b", True)
    overrides = await tool_state.list_overrides(SERVER)
    assert overrides == {"a": False, "b": True}
    # 没设过的 tool 不在 dict 里
    assert "c" not in overrides
    # 但仍可查（默认 True）
    assert await tool_state.is_enabled(SERVER, "c") is True


async def test_upsert_overwrites() -> None:
    """同 (server, tool) UPSERT 不重复行 + 后写赢。"""
    await tool_state.set_enabled(SERVER, "x", True)
    await tool_state.set_enabled(SERVER, "x", False)
    await tool_state.set_enabled(SERVER, "x", True)
    async with engine.begin() as conn:
        rows = (await conn.execute(text(
            "SELECT COUNT(*) FROM mcp_tool_state WHERE server_name=:s AND tool_name='x'"
        ), {"s": SERVER})).first()
    assert rows[0] == 1
    assert await tool_state.is_enabled(SERVER, "x") is True


async def test_delete_for_server_clears_all() -> None:
    await tool_state.set_enabled(SERVER, "a", False)
    await tool_state.set_enabled(SERVER, "b", True)
    n = await tool_state.delete_for_server(SERVER)
    assert n == 2
    assert await tool_state.list_overrides(SERVER) == {}


async def test_set_enabled_rejects_empty_names() -> None:
    with pytest.raises(ValueError):
        await tool_state.set_enabled("", "x", True)
    with pytest.raises(ValueError):
        await tool_state.set_enabled(SERVER, "", True)


async def test_migration_idempotent() -> None:
    """二次跑 migration 无异常 + 表仍在。"""
    await migrate_uxr1()
    await migrate_uxr1()
    async with engine.begin() as conn:
        rows = (await conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='mcp_tool_state'"
        ))).fetchall()
    assert len(rows) == 1
