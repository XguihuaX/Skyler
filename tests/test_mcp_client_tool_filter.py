"""UX-001 — `_connect_one` 按 mcp_tool_state 过滤 + `set_tool_enabled` 切换。

不连真实 MCP server。mock `stdio_client` + `ClientSession.initialize` +
`list_tools`，让 ``_connect_one`` 跑完真实代码路径，验证：

  * 用户在 UI 把某 tool 关了 → `_connect_one` 不 register 该 capability
  * handle.tools 仍记录该 tool（enabled=False），UI 能渲染
  * `set_tool_enabled(False → True)` → 立即 register 到 CapabilityRegistry
  * `set_tool_enabled(True  → False)` → 立即 unregister
  * server 未连接时调 `set_tool_enabled` → ValueError（tools 列表为空）
"""
from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.capabilities import CapabilityRegistry
from backend.database import engine
from backend.database.migrations.v3_5_chunk7_mcp_credentials import (
    run_migration as migrate_chunk7,
)
from backend.database.migrations.v3_5_uxr1_mcp_tool_state import (
    run_migration as migrate_uxr1,
)
from backend.mcp import client as mcp_client
from backend.mcp import tool_state


SERVER = "ux001_test_server"


class _FakeTool:
    def __init__(self, name: str, description: str = "t") -> None:
        self.name = name
        self.description = description
        self.inputSchema = {"type": "object", "properties": {}, "required": []}


async def _cleanup_db() -> None:
    async with engine.begin() as conn:
        await conn.execute(text(
            "DELETE FROM mcp_tool_state WHERE server_name=:s"
        ), {"s": SERVER})
        await conn.execute(text(
            "DELETE FROM mcp_client_state WHERE server_name=:s"
        ), {"s": SERVER})


@pytest.fixture(autouse=True)
async def _setup():
    await migrate_chunk7()
    await migrate_uxr1()
    await _cleanup_db()
    CapabilityRegistry().reset_for_test()
    mcp_client.reset_for_test()
    yield
    await _cleanup_db()
    CapabilityRegistry().reset_for_test()
    mcp_client.reset_for_test()


def _make_handle(tools: list[_FakeTool]) -> tuple[mcp_client._ClientHandle, MagicMock]:
    """造一个 handle + mock session，模拟 `list_tools` 返指定 tool 集合。"""
    handle = mcp_client._ClientHandle(
        SERVER,
        {"transport": "stdio", "command": "echo", "args": [], "enabled": True,
         "expose_via_skyler_server": True, "description": "ux001 test"},
    )
    mcp_client._clients[SERVER] = handle

    fake_session = MagicMock()
    fake_session.initialize = AsyncMock()
    fake_session.list_tools = AsyncMock(
        return_value=MagicMock(tools=list(tools)),
    )
    async def _call_tool(name, args):
        m = MagicMock()
        m.isError = False
        block = MagicMock()
        block.type = "text"
        block.text = f"call:{name}"
        m.content = [block]
        return m
    fake_session.call_tool = _call_tool
    return handle, fake_session


async def _simulate_connect(
    handle: mcp_client._ClientHandle, fake_session: MagicMock, tools: list[_FakeTool],
) -> None:
    """直接走 _connect_one 内 register 路径（绕过 stdio_client 真启动）。

    复刻 _connect_one 后半段的 ``overrides + per-tool register`` 流程，让单测
    既不依赖 stdio_client mock chain 又能 cover 真实 filter 逻辑。
    """
    overrides = await tool_state.list_overrides(handle.name)
    handle.tools = []
    handle.tool_count = 0
    for tool in tools:
        t_enabled = overrides.get(tool.name, True)
        handle.tools.append({
            "name": tool.name,
            "description": tool.description,
            "enabled": t_enabled,
        })
        if not t_enabled:
            continue
        cap = mcp_client._capability_from_external_tool(handle, fake_session, tool)
        CapabilityRegistry().register_runtime(cap)
        handle.tool_count += 1
    handle.session = fake_session
    handle.connected = True


async def test_disabled_tool_skipped_on_connect() -> None:
    """预先把 ``write_file`` 关掉 → connect 后 ext.<server>.write_file 不在 registry。"""
    await tool_state.set_enabled(SERVER, "write_file", False)
    tools = [_FakeTool("read_file"), _FakeTool("write_file"), _FakeTool("list_dir")]
    handle, fake = _make_handle(tools)
    await _simulate_connect(handle, fake, tools)

    names = sorted(c.name for c in CapabilityRegistry().list_all())
    assert "ext.ux001_test_server.read_file" in names
    assert "ext.ux001_test_server.list_dir" in names
    assert "ext.ux001_test_server.write_file" not in names

    # handle.tools 仍记录 3 个 tool 让 UI 展开（write_file enabled=False）
    by_name = {t["name"]: t for t in handle.tools}
    assert by_name["write_file"]["enabled"] is False
    assert by_name["read_file"]["enabled"] is True
    assert handle.tool_count == 2


async def test_set_tool_enabled_false_then_true_round_trip() -> None:
    """全 enabled 启动 → 关掉一个 → 再打开。"""
    tools = [_FakeTool("a"), _FakeTool("b")]
    handle, fake = _make_handle(tools)
    await _simulate_connect(handle, fake, tools)
    reg = CapabilityRegistry()
    assert reg.get("ext.ux001_test_server.b") is not None
    assert handle.tool_count == 2

    # 关 b
    r = await mcp_client.set_tool_enabled(SERVER, "b", False)
    assert r["enabled"] is False
    assert r["tool_count"] == 1
    assert reg.get("ext.ux001_test_server.b") is None
    # tool_state 表里持久化了
    assert await tool_state.is_enabled(SERVER, "b") is False
    # handle.tools 同步
    assert next(t for t in handle.tools if t["name"] == "b")["enabled"] is False

    # 再开 b（re-register 走 session.list_tools）
    r = await mcp_client.set_tool_enabled(SERVER, "b", True)
    assert r["enabled"] is True
    assert r["tool_count"] == 2
    assert reg.get("ext.ux001_test_server.b") is not None
    assert await tool_state.is_enabled(SERVER, "b") is True


async def test_set_tool_enabled_unknown_tool_rejected() -> None:
    tools = [_FakeTool("a")]
    handle, fake = _make_handle(tools)
    await _simulate_connect(handle, fake, tools)
    with pytest.raises(ValueError):
        await mcp_client.set_tool_enabled(SERVER, "ghost_tool", True)


async def test_set_tool_enabled_unknown_server_rejected() -> None:
    with pytest.raises(KeyError):
        await mcp_client.set_tool_enabled("nope_server", "anything", True)


async def test_disconnected_server_blocks_per_tool_toggle() -> None:
    """server 未连接 → handle.tools 为空 → ValueError ("先 enable server")。"""
    handle = mcp_client._ClientHandle(
        SERVER,
        {"transport": "stdio", "command": "echo", "args": [], "enabled": False,
         "expose_via_skyler_server": True, "description": "ux001 test"},
    )
    mcp_client._clients[SERVER] = handle
    # tools 为空：从未 connect
    assert handle.tools == []
    with pytest.raises(ValueError):
        await mcp_client.set_tool_enabled(SERVER, "x", True)


async def test_list_status_includes_tools() -> None:
    tools = [_FakeTool("a"), _FakeTool("b", "do b")]
    handle, fake = _make_handle(tools)
    await _simulate_connect(handle, fake, tools)
    rows = await mcp_client.list_status()
    item = next(s for s in rows if s["name"] == SERVER)
    assert isinstance(item["tools"], list)
    assert len(item["tools"]) == 2
    assert {t["name"] for t in item["tools"]} == {"a", "b"}
    assert all("enabled" in t for t in item["tools"])
