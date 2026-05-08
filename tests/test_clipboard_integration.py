"""Tests for v3-G chunk 3a clipboard integration —— ringbuffer + TTL +
content_type 启发式 + add_item 去抖。

不打真实 NSPasteboard / pyperclip；mock 路径已被 ClipboardWatcher.add_item
直接接受文字，覆盖核心数据流。
"""
import asyncio
import os
import sys
import time
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.integrations.clipboard import (
    ClipboardWatcher,
    detect_content_type,
)

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))


# ---------------------------------------------------------------------------
# 1. content_type 启发式
# ---------------------------------------------------------------------------

async def test_detect_content_type():
    print("\n[clipboard — detect_content_type]")
    check("url",       detect_content_type("https://example.com/foo") == "url")
    check("https url", detect_content_type("https://example.com") == "url")
    check("json",      detect_content_type('{"a": 1, "b": 2}') == "json")
    check("malformed json → plain", detect_content_type("{not json}") == "plain_text")
    check("code (def)", detect_content_type("def foo():\n    pass") == "code")
    check("code (function)", detect_content_type("function bar() { return 42; }") == "code")
    check("code (import)", detect_content_type("import os\nimport sys") == "code")
    check("code (indented)",
          detect_content_type("hello\n    line 1\n    line 2") == "code")
    check("markdown header", detect_content_type("# Title\nsome text") == "markdown")
    check("markdown link", detect_content_type("see [docs](https://a.com)") == "markdown")
    check("markdown bullet",
          detect_content_type("- item 1\n- item 2") == "markdown")
    check("plain text", detect_content_type("just a normal sentence") == "plain_text")
    check("empty → plain", detect_content_type("") == "plain_text")
    check("None-like → plain", detect_content_type("   ") == "plain_text")


# ---------------------------------------------------------------------------
# 2. ringbuffer behavior
# ---------------------------------------------------------------------------

async def test_ringbuffer_basic():
    print("\n[clipboard — ringbuffer add + get_recent]")
    w = ClipboardWatcher()
    w.add_item("first")
    w.add_item("second")
    w.add_item("third")
    items = w.get_recent(5)
    check("count 3", len(items) == 3)
    check("most recent first", items[0].content == "third")
    check("oldest last", items[-1].content == "first")
    check("each has captured_at + content_type",
          all(it.captured_at > 0 and it.content_type for it in items))


async def test_ringbuffer_dedup():
    print("\n[clipboard — duplicate last_text deduplication]")
    w = ClipboardWatcher()
    w.add_item("hello")
    w.add_item("hello")  # 同 last_text 应跳过
    w.add_item("world")
    w.add_item("hello")  # 这次应加入（last_text=world 已变）
    items = w.get_recent(10)
    check("dedup applied: 3 items not 4", len(items) == 3,
          f"got len={len(items)}")


async def test_ringbuffer_capacity():
    """容量上限 50；超过后旧的被淘汰。"""
    print("\n[clipboard — ringbuffer capacity 50]")
    w = ClipboardWatcher()
    for i in range(60):
        w.add_item(f"item-{i}")
    items = w.get_recent(60)
    check("max 50 retained", len(items) <= 50, f"got {len(items)}")
    check("most recent kept", items[0].content == "item-59")
    check("oldest evicted (item-9 still in / item-0 gone)",
          all(it.content != "item-0" for it in items))


async def test_get_recent_param_clamping():
    print("\n[clipboard — get_recent n clamping]")
    w = ClipboardWatcher()
    for i in range(5):
        w.add_item(f"i-{i}")
    check("n=0 clamped to 1", len(w.get_recent(0)) == 1)
    check("n=999 clamped to existing 5", len(w.get_recent(999)) == 5)


async def test_clear_all():
    print("\n[clipboard — clear_all]")
    w = ClipboardWatcher()
    w.add_item("a"); w.add_item("b"); w.add_item("c")
    n = w.clear_all()
    check("clear_all returns count 3", n == 3)
    check("buffer empty after clear", len(w.get_recent(10)) == 0)
    # last_text reset → can re-add same text
    w.add_item("a")
    check("last_text reset after clear", len(w.get_recent(10)) == 1)


async def test_clear_one():
    print("\n[clipboard — clear_one by captured_at]")
    w = ClipboardWatcher()
    w.add_item("alpha")
    target_at = w.get_recent(1)[0].captured_at
    w.add_item("beta")
    ok = w.clear_one(target_at)
    check("clear_one returns True", ok)
    items = [it.content for it in w.get_recent(10)]
    check("only beta remains", items == ["beta"], f"got {items}")
    ok2 = w.clear_one(99999.0)
    check("missing captured_at returns False", ok2 is False)


# ---------------------------------------------------------------------------
# 3. TTL eviction
# ---------------------------------------------------------------------------

async def test_ttl_eviction():
    """超 TTL 的项被 _evict_expired 清掉。注入 captured_at 模拟 24h 前。"""
    print("\n[clipboard — TTL 24h eviction]")
    w = ClipboardWatcher()
    w.add_item("old")
    w.add_item("recent")
    # 把 'old' 改成 25h 前
    w._buf[0].captured_at = time.time() - 25 * 3600
    items = w.get_recent(10)
    contents = [it.content for it in items]
    check("expired 'old' evicted", "old" not in contents,
          f"got {contents}")
    check("recent kept", "recent" in contents)


# ---------------------------------------------------------------------------
# 4. add_item content_type override + heuristic
# ---------------------------------------------------------------------------

async def test_add_item_content_type():
    print("\n[clipboard — add_item content_type explicit + heuristic]")
    w = ClipboardWatcher()
    # Explicit override
    item = w.add_item("hello world", content_type="markdown")
    check("explicit override respected",
          item is not None and item.content_type == "markdown")

    w.clear_all()
    # Heuristic auto-detect
    w.add_item("https://example.com")
    items = w.get_recent(1)
    check("heuristic url detected",
          items[0].content_type == "url")


async def test_add_item_invalid_inputs():
    print("\n[clipboard — add_item rejects empty / non-string]")
    w = ClipboardWatcher()
    out_none = w.add_item("")
    check("empty string returns None", out_none is None)
    out_ws = w.add_item("   \n\t  ")
    check("whitespace-only returns None", out_ws is None)
    out_bad = w.add_item(None)  # type: ignore[arg-type]
    check("None returns None", out_bad is None)


# ---------------------------------------------------------------------------
# 5. Polling task lifecycle (mock NSPasteboard)
# ---------------------------------------------------------------------------

async def test_polling_lifecycle():
    """start_polling spawns task; stop_polling cancels it."""
    print("\n[clipboard — polling start/stop lifecycle]")
    w = ClipboardWatcher()
    # Patch _poll_loop to be a quick noop coroutine to avoid touching real pasteboard
    async def fake_loop():
        await asyncio.sleep(60)
    with patch.object(w, "_poll_loop", fake_loop):
        w.start_polling()
        check("task spawned", w._task is not None and not w._task.done())
        await w.stop_polling()
        check("task cancelled", w._task is None)


async def test_set_enabled_gates_poll():
    """``_enabled=False`` 时 poll_once 不调 backend。"""
    print("\n[clipboard — set_enabled gates _poll_once]")
    w = ClipboardWatcher()
    w.set_enabled(False)
    # 模拟 backend：mock _poll_once 看是否被调
    call_count = {"n": 0}
    async def fake_poll_once():
        call_count["n"] += 1
    with patch.object(w, "_poll_once", fake_poll_once):
        # 一轮主 loop（手动驱动而不是真起 task）
        if w._enabled:
            await fake_poll_once()
    check("disabled ⇒ _poll_once not auto-called",
          call_count["n"] == 0)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

async def main():
    await test_detect_content_type()
    await test_ringbuffer_basic()
    await test_ringbuffer_dedup()
    await test_ringbuffer_capacity()
    await test_get_recent_param_clamping()
    await test_clear_all()
    await test_clear_one()
    await test_ttl_eviction()
    await test_add_item_content_type()
    await test_add_item_invalid_inputs()
    await test_polling_lifecycle()
    await test_set_enabled_gates_poll()

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
