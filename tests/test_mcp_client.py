"""Tests for v3-G chunk 1.5 — MCP client (external server connect + reverse register).

不连真实 MCP server（需要 npx + 网络）；mock _connect_one 只验证：

  * config 解析 + 环境变量插值
  * capability 反向注册到 CapabilityRegistry + ToolRegistry
  * closure 正确捕获 tool name（多 tool 不互相覆盖）
  * disconnect 清干净 capabilities
  * 启动失败不阻塞 + last_error 记录
  * list_status 序列化形态
"""
import asyncio
import os
import sys
from contextlib import AsyncExitStack
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.capabilities import CapabilityRegistry
from backend.mcp import client as mcp_client
from backend.tools.registry import ToolRegistry

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))


def _reset_all():
    CapabilityRegistry().reset_for_test()
    mcp_client.reset_for_test()


# ---------------------------------------------------------------------------
# 1. env interpolation
# ---------------------------------------------------------------------------

async def test_env_interpolation():
    print("\n[mcp.client — env var interpolation]")
    os.environ["TEST_BRAVE_KEY"] = "secret-abc"
    out = mcp_client._expand_str({
        "args": ["--root", "${HOME}/Documents", "--key", "${TEST_BRAVE_KEY}"],
        "env": {"BRAVE_API_KEY": "${TEST_BRAVE_KEY}"},
    })
    check("HOME expanded", os.environ["HOME"] in out["args"][1])
    check("custom env expanded in args", out["args"][3] == "secret-abc")
    check("custom env expanded in env", out["env"]["BRAVE_API_KEY"] == "secret-abc")


# ---------------------------------------------------------------------------
# 2. capability 反向注册 + closure 隔离
# ---------------------------------------------------------------------------

class _FakeTool:
    def __init__(self, name, description="t", inputSchema=None):
        self.name = name
        self.description = description
        self.inputSchema = inputSchema or {"type": "object", "properties": {}, "required": []}


async def test_reverse_register_and_closure_isolation():
    print("\n[mcp.client — reverse register + closure isolation]")
    _reset_all()

    handle = mcp_client._ClientHandle(
        "filesystem",
        {"transport": "stdio", "command": "npx", "args": ["..."], "enabled": True,
         "expose_via_skyler_server": True, "description": "fs server"},
    )

    # 模拟 ClientSession：每次 call_tool 收到不同 tool name 时返回不同 result
    fake_session = MagicMock()
    async def _fake_call_tool(name, args):
        m = MagicMock()
        m.isError = False
        # 制造一个 text content block
        block = MagicMock()
        block.type = "text"
        block.text = f"called:{name} with {args}"
        m.content = [block]
        return m
    fake_session.call_tool = _fake_call_tool

    tools = [
        _FakeTool("read_file", "读文件"),
        _FakeTool("write_file", "写文件"),
        _FakeTool("list_dir",   "列目录"),
    ]

    # 注册 3 个 capability（直接调内部 helper 跳过真实 transport）
    for t in tools:
        cap = mcp_client._capability_from_external_tool(handle, fake_session, t)
        CapabilityRegistry().register_runtime(cap)

    reg = CapabilityRegistry()
    names = sorted([c.name for c in reg.list_all()])
    check("3 capabilities registered", names == [
        "ext.filesystem.list_dir",
        "ext.filesystem.read_file",
        "ext.filesystem.write_file",
    ])
    # 3 个都应进 ToolRegistry
    tools_in_reg = ToolRegistry.list_tools()
    check(
        "all 3 in ToolRegistry",
        all(f"ext.filesystem.{tn}" in tools_in_reg for tn in ["read_file","write_file","list_dir"]),
    )

    # 关键：closure 隔离 —— 调 read_file 必须命中 read_file，不是被最后一次循环覆盖
    cap_read  = reg.get("ext.filesystem.read_file")
    cap_write = reg.get("ext.filesystem.write_file")
    cap_list  = reg.get("ext.filesystem.list_dir")

    r1 = await cap_read.handler(path="/x", user_id="u1")
    r2 = await cap_write.handler(path="/y", content="hi", user_id="u1")
    r3 = await cap_list.handler(path="/z", user_id="u1")
    check("read_file routes correctly", "called:read_file" in r1["text"])
    check("write_file routes correctly", "called:write_file" in r2["text"])
    check("list_dir routes correctly", "called:list_dir" in r3["text"])
    # user_id 不能泄露给外部 server（外部 schema 没这个字段）
    check("user_id stripped before forwarding", "user_id" not in r1["text"])

    _reset_all()


# ---------------------------------------------------------------------------
# 3. metadata 表现
# ---------------------------------------------------------------------------

async def test_metadata_for_external_caps():
    print("\n[mcp.client — metadata: source_server + expose flag]")
    _reset_all()

    handle = mcp_client._ClientHandle(
        "brave-search",
        {"transport": "stdio", "command": "npx",
         "expose_via_skyler_server": False, "enabled": True, "description": "brave"},
    )
    fake_session = MagicMock()
    fake_session.call_tool = AsyncMock(return_value=MagicMock(isError=False, content=[]))

    cap = mcp_client._capability_from_external_tool(
        handle, fake_session, _FakeTool("search", "Brave web search"),
    )
    check("source_server set", cap.metadata.get("source_server") == "brave-search")
    check("expose_via_server False (per config)", cap.metadata.get("expose_via_server") is False)
    check("category mcp_external", cap.category == "mcp_external")
    check("icon link-2", cap.icon == "link-2")
    check("display_name has [server] prefix", cap.display_name == "[brave-search] search")
    check("name uses ext.<server>.<tool>", cap.name == "ext.brave-search.search")


# ---------------------------------------------------------------------------
# 4. failed connect doesn't block + last_error captured
# ---------------------------------------------------------------------------

async def test_init_failure_non_blocking():
    print("\n[mcp.client — init failure non-blocking]")
    _reset_all()

    # config: 一个会成功（mock _connect_one 直接返回），一个会失败
    fake_yaml = {
        "mcp_clients": {
            "ok-server": {"enabled": True, "transport": "stdio", "command": "echo"},
            "broken":    {"enabled": True, "transport": "stdio", "command": "this_command_definitely_does_not_exist_xyz"},
        }
    }

    async def _fake_connect_one(handle):
        if handle.name == "broken":
            raise FileNotFoundError("command not found in PATH: nope")
        # 成功路径：直接置状态
        handle.connected = True
        handle.tool_count = 0
        handle.session = MagicMock()
        handle.exit_stack = AsyncExitStack()

    with patch.object(mcp_client, "config_yaml", fake_yaml), \
         patch.object(mcp_client, "_connect_one", side_effect=_fake_connect_one):
        await mcp_client.init_clients_from_config()

    statuses = {s["name"]: s for s in await mcp_client.list_status()}
    check("ok-server connected", statuses["ok-server"]["connected"] is True)
    check("ok-server no last_error", statuses["ok-server"]["last_error"] is None)
    check("broken not connected", statuses["broken"]["connected"] is False)
    check(
        "broken records last_error",
        "command not found" in (statuses["broken"]["last_error"] or ""),
    )
    _reset_all()


# ---------------------------------------------------------------------------
# 5. disconnect cleans up capabilities
# ---------------------------------------------------------------------------

async def test_disconnect_cleans_capabilities():
    print("\n[mcp.client — disconnect unregisters capabilities]")
    _reset_all()

    handle = mcp_client._ClientHandle(
        "filesystem", {"transport": "stdio", "command": "npx", "enabled": True},
    )
    fake_session = MagicMock()
    cap1 = mcp_client._capability_from_external_tool(handle, fake_session, _FakeTool("a"))
    cap2 = mcp_client._capability_from_external_tool(handle, fake_session, _FakeTool("b"))
    CapabilityRegistry().register_runtime(cap1)
    CapabilityRegistry().register_runtime(cap2)
    handle.connected = True
    handle.exit_stack = AsyncExitStack()
    handle.tool_count = 2

    await mcp_client._disconnect_one(handle)

    check(
        "cap a removed",
        CapabilityRegistry().get("ext.filesystem.a") is None,
    )
    check(
        "cap b removed",
        CapabilityRegistry().get("ext.filesystem.b") is None,
    )
    check("handle.connected False", handle.connected is False)
    check("handle.tool_count 0", handle.tool_count == 0)
    _reset_all()


# ---------------------------------------------------------------------------
# 6. list_status shape
# ---------------------------------------------------------------------------

async def test_list_status_shape():
    print("\n[mcp.client — list_status payload shape]")
    _reset_all()

    handle = mcp_client._ClientHandle(
        "x", {"transport": "stdio", "command": "echo", "enabled": True,
              "description": "test", "expose_via_skyler_server": True},
    )
    handle.connected = True
    handle.tool_count = 5
    mcp_client._clients["x"] = handle

    statuses = await mcp_client.list_status()
    check("returns list of dict", isinstance(statuses, list) and len(statuses) == 1)
    s = statuses[0]
    # v3.5 chunk 7：env_required / missing_credentials 字段新增
    expected_keys = {"name", "description", "enabled", "connected", "transport",
                     "tool_count", "expose_via_server", "last_error",
                     "env_required", "missing_credentials"}
    check("DTO keys complete", set(s.keys()) == expected_keys,
          f"got {set(s.keys())!r}")
    check("connected=True", s["connected"] is True)
    check("transport=stdio", s["transport"] == "stdio")
    check("expose_via_server=True", s["expose_via_server"] is True)
    _reset_all()


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

async def main():
    await test_env_interpolation()
    await test_reverse_register_and_closure_isolation()
    await test_metadata_for_external_caps()
    await test_init_failure_non_blocking()
    await test_disconnect_cleans_capabilities()
    await test_list_status_shape()

    total = len(results)
    passed = sum(1 for _, ok in results if ok)
    print(f"\n{'='*40}")
    print(f"Results: {passed}/{total} passed")
    if passed < total:
        print("FAILED:", ", ".join(n for n, ok in results if not ok))
        sys.exit(1)
    else:
        print("ALL TESTS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
