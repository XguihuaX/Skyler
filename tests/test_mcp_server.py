"""Tests for v3-G chunk 1.5 — MCP server expose layer."""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 锁定 token —— /mcp 鉴权需要
os.environ.setdefault("MCP_BEARER_TOKEN", "test-mcp-token")

from backend.capabilities import (
    Capability,
    CapabilityRegistry,
    Consumer,
    TriggerMode,
)
from backend.mcp import server as mcp_server

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))


def _fresh_registry():
    reg = CapabilityRegistry()
    reg.reset_for_test()
    return reg


# ---------------------------------------------------------------------------
# 1. _is_exposable filter
# ---------------------------------------------------------------------------

async def test_exposable_filter():
    print("\n[mcp.server — exposable filter]")
    reg = _fresh_registry()

    async def h(**_kwargs):
        return None

    chat_cap = Capability(
        name="cap.chat", display_name="x", description="x",
        category="system", consumers=[Consumer.CHAT_AGENT],
        trigger_modes=[TriggerMode.ON_DEMAND], handler=h,
    )
    cron_only = Capability(
        name="cap.cron_only", display_name="x", description="x",
        category="system", consumers=[Consumer.SCHEDULER],
        trigger_modes=[TriggerMode.SCHEDULED], handler=h,
    )
    not_exposed = Capability(
        name="cap.private", display_name="x", description="x",
        category="system", consumers=[Consumer.CHAT_AGENT],
        trigger_modes=[TriggerMode.ON_DEMAND], handler=h,
        metadata={"expose_via_server": False},
    )
    reg.register(chat_cap)
    reg.register(cron_only)
    reg.register(not_exposed)

    check("CHAT_AGENT cap is exposable", mcp_server._is_exposable(chat_cap))
    check("SCHEDULER-only cap not exposable", not mcp_server._is_exposable(cron_only))
    check("expose_via_server=False not exposable", not mcp_server._is_exposable(not_exposed))


# ---------------------------------------------------------------------------
# 2. list_tools 派生
# ---------------------------------------------------------------------------

async def test_list_tools_derivation():
    print("\n[mcp.server — list_tools]")
    reg = _fresh_registry()

    async def h(**_kwargs):
        return None

    reg.register(Capability(
        name="echo", display_name="echo", description="Echo a value",
        category="system", consumers=[Consumer.CHAT_AGENT],
        trigger_modes=[TriggerMode.ON_DEMAND], handler=h,
        parameters_schema={"type": "object", "properties": {"x": {"type": "string"}}, "required": []},
    ))
    reg.register(Capability(
        name="hidden", display_name="hidden", description="hidden",
        category="system", consumers=[Consumer.CHAT_AGENT],
        trigger_modes=[TriggerMode.ON_DEMAND], handler=h,
        metadata={"expose_via_server": False},
    ))

    # 直接调内部 _list_tools (decorated handler) — 通过 server._list_tools_handler
    tools = await mcp_server._list_tools()
    names = {t.name for t in tools}
    check("echo exposed", "echo" in names)
    check("hidden filtered", "hidden" not in names)

    echo_tool = next(t for t in tools if t.name == "echo")
    check("description carried over", echo_tool.description == "Echo a value")
    check(
        "inputSchema carried over",
        echo_tool.inputSchema == {"type": "object", "properties": {"x": {"type": "string"}}, "required": []},
    )


async def test_list_tools_default_schema():
    print("\n[mcp.server — default empty inputSchema]")
    reg = _fresh_registry()

    async def h(**_kwargs):
        return None

    reg.register(Capability(
        name="noop", display_name="noop", description="x",
        category="system", consumers=[Consumer.CHAT_AGENT],
        trigger_modes=[TriggerMode.ON_DEMAND], handler=h,
        # parameters_schema=None
    ))

    tools = await mcp_server._list_tools()
    noop = next(t for t in tools if t.name == "noop")
    check(
        "None schema → empty object schema",
        noop.inputSchema == {"type": "object", "properties": {}, "required": []},
    )


# ---------------------------------------------------------------------------
# 3. call_tool routing + json serialisation
# ---------------------------------------------------------------------------

async def test_call_tool_dispatches():
    print("\n[mcp.server — call_tool dispatch]")
    reg = _fresh_registry()

    async def h(x: str = "default", **_kwargs):
        return {"echoed": x, "user_id": _kwargs.get("user_id")}

    reg.register(Capability(
        name="echo", display_name="echo", description="x",
        category="system", consumers=[Consumer.CHAT_AGENT],
        trigger_modes=[TriggerMode.ON_DEMAND], handler=h,
        parameters_schema={"type": "object", "properties": {"x": {"type": "string"}}, "required": []},
    ))

    contents = await mcp_server._call_tool("echo", {"x": "hi"})
    check("returns 1 TextContent", len(contents) == 1)
    payload = json.loads(contents[0].text)
    check("payload.echoed", payload["echoed"] == "hi")
    check("user_id default injected", payload["user_id"] == "default")


async def test_call_tool_unknown():
    print("\n[mcp.server — call_tool unknown]")
    _fresh_registry()
    raised = False
    try:
        await mcp_server._call_tool("does_not_exist", {})
    except ValueError as exc:
        raised = "unknown tool" in str(exc)
    check("unknown tool raises ValueError", raised)


async def test_call_tool_not_exposed():
    print("\n[mcp.server — call_tool blocks non-exposed]")
    reg = _fresh_registry()

    async def h(**_kwargs):
        return {"private": True}

    reg.register(Capability(
        name="private_one", display_name="x", description="x",
        category="system", consumers=[Consumer.CHAT_AGENT],
        trigger_modes=[TriggerMode.ON_DEMAND], handler=h,
        metadata={"expose_via_server": False},
    ))

    raised = False
    try:
        await mcp_server._call_tool("private_one", {})
    except ValueError as exc:
        raised = "not exposed" in str(exc)
    check("not-exposed tool blocks via server", raised)


async def test_call_tool_handler_error_wrapped():
    print("\n[mcp.server — call_tool handler error wrapped]")
    reg = _fresh_registry()

    async def boom(**_kwargs):
        raise RuntimeError("boom!")

    reg.register(Capability(
        name="boomer", display_name="x", description="x",
        category="system", consumers=[Consumer.CHAT_AGENT],
        trigger_modes=[TriggerMode.ON_DEMAND], handler=boom,
    ))

    raised = False
    try:
        await mcp_server._call_tool("boomer", {})
    except ValueError as exc:
        raised = "boom!" in str(exc)
    check("handler exception → ValueError with msg", raised)


# ---------------------------------------------------------------------------
# 4. server status helpers
# ---------------------------------------------------------------------------

async def test_status_helpers():
    print("\n[mcp.server — status helpers]")
    reg = _fresh_registry()

    async def h(**_kwargs):
        return None

    reg.register(Capability(
        name="visible", display_name="x", description="x",
        category="system", consumers=[Consumer.CHAT_AGENT],
        trigger_modes=[TriggerMode.ON_DEMAND], handler=h,
    ))
    reg.register(Capability(
        name="hidden", display_name="x", description="x",
        category="system", consumers=[Consumer.CHAT_AGENT],
        trigger_modes=[TriggerMode.ON_DEMAND], handler=h,
        metadata={"expose_via_server": False},
    ))

    names = mcp_server.list_exposed_tool_names()
    check("only exposed in status list", names == ["visible"])

    token = mcp_server.get_bearer_token()
    check("token reads from env", token == "test-mcp-token")


# ---------------------------------------------------------------------------
# 5. registry runtime register / unregister
# ---------------------------------------------------------------------------

async def test_registry_runtime_register():
    print("\n[capabilities.registry — register_runtime / unregister_runtime]")
    reg = _fresh_registry()

    async def h(**_kwargs):
        return {"ok": True}

    cap = Capability(
        name="rt.one", display_name="x", description="x",
        category="ext", consumers=[Consumer.CHAT_AGENT],
        trigger_modes=[TriggerMode.ON_DEMAND], handler=h,
    )
    reg.register_runtime(cap)
    check("runtime cap registered", reg.get("rt.one") is not None)

    from backend.tools.registry import ToolRegistry
    check("rt.one in ToolRegistry", "rt.one" in ToolRegistry.list_tools())

    ok = reg.unregister_runtime("rt.one")
    check("unregister returns True", ok)
    check("rt.one cleared from registry", reg.get("rt.one") is None)
    check("rt.one cleared from ToolRegistry", "rt.one" not in ToolRegistry.list_tools())

    check("unregister missing → False", reg.unregister_runtime("nope") is False)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

async def main():
    await test_exposable_filter()
    await test_list_tools_derivation()
    await test_list_tools_default_schema()
    await test_call_tool_dispatches()
    await test_call_tool_unknown()
    await test_call_tool_not_exposed()
    await test_call_tool_handler_error_wrapped()
    await test_status_helpers()
    await test_registry_runtime_register()

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
