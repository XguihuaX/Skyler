"""Tests for CapabilityRegistry — v3-G chunk 0."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.capabilities import (
    Capability,
    CapabilityRegistry,
    Consumer,
    TriggerMode,
    register_capability,
)
from backend.tools.registry import ToolRegistry

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))


def _fresh_registry() -> CapabilityRegistry:
    """每个 case 跑前清空，避免互相污染。"""
    reg = CapabilityRegistry()
    reg.reset_for_test()
    return reg


# ---------------------------------------------------------------------------
# 1. register + get round-trip
# ---------------------------------------------------------------------------

async def test_register_and_get():
    print("\n[CapabilityRegistry — register/get]")
    reg = _fresh_registry()

    async def handler(**_kwargs):
        return {"ok": True}

    cap = Capability(
        name="test.echo",
        display_name="测试回声",
        description="just a test",
        category="system",
        consumers=[Consumer.CHAT_AGENT],
        trigger_modes=[TriggerMode.ON_DEMAND],
        handler=handler,
        parameters_schema={"type": "object", "properties": {}, "required": []},
    )
    reg.register(cap)

    got = reg.get("test.echo")
    check("get returns registered cap", got is not None and got.name == "test.echo")
    check("missing name returns None", reg.get("nonexistent") is None)


# ---------------------------------------------------------------------------
# 2. CHAT_AGENT consumer 触发 ToolRegistry 同步
# ---------------------------------------------------------------------------

async def test_chat_agent_propagates_to_tool_registry():
    print("\n[CapabilityRegistry — ToolRegistry sync]")
    _fresh_registry()

    async def handler(**_kwargs):
        return {"ping": "pong"}

    @register_capability(
        name="test.ping",
        display_name="ping",
        description="Returns pong",
        category="system",
        consumers=[Consumer.CHAT_AGENT],
        trigger_modes=[TriggerMode.ON_DEMAND],
        parameters_schema={"type": "object", "properties": {}, "required": []},
    )
    async def _ping(**_kwargs):
        return await handler()

    check("ToolRegistry got the entry", "test.ping" in ToolRegistry.list_tools())
    schemas = [s for s in ToolRegistry.list_schemas() if s["function"]["name"] == "test.ping"]
    check("ToolRegistry schema present", len(schemas) == 1)
    if schemas:
        sch = schemas[0]
        check(
            "schema has correct shape",
            sch["type"] == "function" and sch["function"]["description"] == "Returns pong",
        )

    # ChatAgent 调用形态：ToolRegistry.call(name, user_id=..., **args)
    result = await ToolRegistry.call("test.ping", user_id="u1")
    check("ToolRegistry.call dispatches handler", result == {"ping": "pong"})


# ---------------------------------------------------------------------------
# 3. SCHEDULER-only capability 不进 ToolRegistry
# ---------------------------------------------------------------------------

async def test_scheduler_only_does_not_touch_tool_registry():
    print("\n[CapabilityRegistry — non-CHAT_AGENT skips ToolRegistry]")
    _fresh_registry()

    async def handler(**_kwargs):
        return None

    cap = Capability(
        name="test.cron_only",
        display_name="cron only",
        description="x",
        category="system",
        consumers=[Consumer.SCHEDULER],
        trigger_modes=[TriggerMode.SCHEDULED],
        handler=handler,
    )
    CapabilityRegistry().register(cap)
    check(
        "scheduler-only capability not in ToolRegistry",
        "test.cron_only" not in ToolRegistry.list_tools(),
    )


# ---------------------------------------------------------------------------
# 4. list filters
# ---------------------------------------------------------------------------

async def test_list_filters():
    print("\n[CapabilityRegistry — list filters]")
    reg = _fresh_registry()

    async def h(**_kwargs):
        return None

    reg.register(Capability(
        name="a.visible_chat", display_name="a", description="x",
        category="system", consumers=[Consumer.CHAT_AGENT],
        trigger_modes=[TriggerMode.ON_DEMAND], handler=h,
    ))
    reg.register(Capability(
        name="b.hidden_chat", display_name="b", description="x",
        category="creative", consumers=[Consumer.CHAT_AGENT],
        trigger_modes=[TriggerMode.ON_DEMAND], handler=h,
        user_visible=False,
    ))
    reg.register(Capability(
        name="c.cron_only", display_name="c", description="x",
        category="system", consumers=[Consumer.SCHEDULER],
        trigger_modes=[TriggerMode.SCHEDULED], handler=h,
    ))

    chat_caps = reg.list_for_consumer(Consumer.CHAT_AGENT)
    check("list_for_consumer CHAT_AGENT count", len(chat_caps) == 2)

    visible = reg.list_user_visible()
    check("list_user_visible drops hidden", len(visible) == 2)
    check("list_user_visible includes a + c", {c.name for c in visible} == {"a.visible_chat", "c.cron_only"})

    by_cat = reg.list_by_category()
    check("list_by_category groups system", "system" in by_cat and len(by_cat["system"]) == 2)


# ---------------------------------------------------------------------------
# 5. duplicate registration raises
# ---------------------------------------------------------------------------

async def test_duplicate_raises():
    print("\n[CapabilityRegistry — duplicate registration]")
    reg = _fresh_registry()

    async def h(**_kwargs):
        return None

    cap = Capability(
        name="dup.x", display_name="x", description="x",
        category="system", consumers=[Consumer.SCHEDULER],
        trigger_modes=[TriggerMode.SCHEDULED], handler=h,
    )
    reg.register(cap)
    raised = False
    try:
        reg.register(cap)
    except ValueError:
        raised = True
    check("duplicate name raises ValueError", raised)


# ---------------------------------------------------------------------------
# 6. health_check_all
# ---------------------------------------------------------------------------

async def test_health_check_all():
    print("\n[CapabilityRegistry — health_check_all]")
    reg = _fresh_registry()

    async def h(**_kwargs):
        return None

    async def healthy_check():
        return {"status": "healthy"}

    def warn_check_sync():
        return "warn"

    def boom_check():
        raise RuntimeError("simulated failure")

    reg.register(Capability(
        name="hc.healthy", display_name="x", description="x",
        category="system", consumers=[Consumer.SCHEDULER],
        trigger_modes=[TriggerMode.SCHEDULED], handler=h,
        health_check=healthy_check,
    ))
    reg.register(Capability(
        name="hc.warn", display_name="x", description="x",
        category="system", consumers=[Consumer.SCHEDULER],
        trigger_modes=[TriggerMode.SCHEDULED], handler=h,
        health_check=warn_check_sync,
    ))
    reg.register(Capability(
        name="hc.error", display_name="x", description="x",
        category="system", consumers=[Consumer.SCHEDULER],
        trigger_modes=[TriggerMode.SCHEDULED], handler=h,
        health_check=boom_check,
    ))
    reg.register(Capability(
        name="hc.none", display_name="x", description="x",
        category="system", consumers=[Consumer.SCHEDULER],
        trigger_modes=[TriggerMode.SCHEDULED], handler=h,
        # 无 health_check
    ))

    out = await reg.health_check_all()
    check("returns a dict", isinstance(out, dict))
    check("healthy entry", out.get("hc.healthy", {}).get("status") == "healthy")
    check("warn entry", out.get("hc.warn", {}).get("status") == "warn")
    check("error entry", out.get("hc.error", {}).get("status") == "error")
    check("error entry has error msg", "simulated failure" in (out.get("hc.error", {}).get("error") or ""))
    check("no health_check → unknown", out.get("hc.none", {}).get("status") == "unknown")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

async def main():
    await test_register_and_get()
    await test_chat_agent_propagates_to_tool_registry()
    await test_scheduler_only_does_not_touch_tool_registry()
    await test_list_filters()
    await test_duplicate_raises()
    await test_health_check_all()

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
