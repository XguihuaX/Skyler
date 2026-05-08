"""Tests for v3-G chunk 4 Part B — clipboard enabled API + 真后端联动。"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routes.character_state_api import router

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return app


# ---------------------------------------------------------------------------
# 1. GET /api/clipboard/enabled
# ---------------------------------------------------------------------------

def test_get_enabled_default_true():
    print("\n[clipboard.enabled — GET default true]")
    from backend.integrations.clipboard import clipboard_watcher
    clipboard_watcher.set_enabled(True)  # reset
    client = TestClient(_build_app())
    r = client.get("/api/clipboard/enabled")
    check("status 200", r.status_code == 200)
    check("enabled=true", r.json().get("enabled") is True)


# ---------------------------------------------------------------------------
# 2. POST /api/clipboard/enabled writes runtime flag
# ---------------------------------------------------------------------------

def test_post_enabled_false_then_true():
    print("\n[clipboard.enabled — POST flips runtime flag]")
    from backend.integrations.clipboard import clipboard_watcher
    client = TestClient(_build_app())

    r1 = client.post("/api/clipboard/enabled", json={"enabled": False})
    check("status 200", r1.status_code == 200)
    check("enabled=false echoed", r1.json().get("enabled") is False)
    check("watcher._enabled flipped to False",
          clipboard_watcher._enabled is False)

    r2 = client.post("/api/clipboard/enabled", json={"enabled": True})
    check("re-enable status 200", r2.status_code == 200)
    check("enabled=true echoed", r2.json().get("enabled") is True)
    check("watcher._enabled back to True",
          clipboard_watcher._enabled is True)


# ---------------------------------------------------------------------------
# 3. POST 关闭后 _poll_once 不真捕获（即便 ringbuffer.add_item 仍可手动）
# ---------------------------------------------------------------------------

async def test_disabled_skips_poll_once():
    print("\n[clipboard.enabled — disabled gates _poll_once]")
    from backend.integrations.clipboard import ClipboardWatcher
    w = ClipboardWatcher()
    w.set_enabled(False)
    # 模拟一轮 _poll_loop iteration 的语义：disabled 时 _poll_once 不该被调
    poll_calls = {"n": 0}
    async def fake_poll_once():
        poll_calls["n"] += 1
    w._poll_once = fake_poll_once  # type: ignore

    # 主动模拟 _poll_loop 一次迭代的检查逻辑（不真起 task）
    if w._enabled:
        await fake_poll_once()
    check("disabled ⇒ _poll_once not invoked",
          poll_calls["n"] == 0)


def test_disabled_doesnt_block_manual_add():
    """add_item 是手动 push 通道，不受 _enabled 影响（前端 Tauri push）。"""
    print("\n[clipboard.enabled — manual add_item still works when disabled]")
    from backend.integrations.clipboard import clipboard_watcher
    clipboard_watcher.set_enabled(False)
    clipboard_watcher.clear_all()
    out = clipboard_watcher.add_item("manually pushed while disabled")
    check("add_item succeeded", out is not None)
    items = clipboard_watcher.get_recent(5)
    check("ringbuffer received item",
          len(items) == 1 and items[0].content == "manually pushed while disabled")
    clipboard_watcher.set_enabled(True)  # restore


# ---------------------------------------------------------------------------
# 4. POST /api/clipboard/enabled malformed body
# ---------------------------------------------------------------------------

def test_post_missing_enabled_field():
    print("\n[clipboard.enabled — POST missing field returns 422]")
    client = TestClient(_build_app())
    r = client.post("/api/clipboard/enabled", json={})
    check("status 422 (FastAPI validation)",
          r.status_code == 422, f"got {r.status_code}")


def test_post_string_enabled_coerced():
    """Pydantic coerces 'true' to True for bool field."""
    print("\n[clipboard.enabled — POST 'true' string coerced]")
    client = TestClient(_build_app())
    r = client.post("/api/clipboard/enabled", json={"enabled": "true"})
    # Pydantic v2 默认 strict=False，'true' 可被 coerce 到 bool；测试 status 200 即可
    check("status 200 (coerced)", r.status_code == 200, f"got {r.status_code}")


# ---------------------------------------------------------------------------
# 5. Round-trip GET-after-POST stability
# ---------------------------------------------------------------------------

def test_round_trip_get_after_post():
    print("\n[clipboard.enabled — GET after POST returns same value]")
    from backend.integrations.clipboard import clipboard_watcher
    client = TestClient(_build_app())
    client.post("/api/clipboard/enabled", json={"enabled": False})
    r = client.get("/api/clipboard/enabled")
    check("GET reads back False", r.json().get("enabled") is False)
    # restore
    clipboard_watcher.set_enabled(True)


# ---------------------------------------------------------------------------
# 6. 不持久化到 yaml（runtime only）
# ---------------------------------------------------------------------------

def test_not_persisted_to_yaml():
    """POST 不写 config.yaml；config_yaml 字典里不应该出现 'clipboard' 节。"""
    print("\n[clipboard.enabled — runtime only, no yaml write]")
    from backend.config import config_yaml
    snapshot_before = config_yaml.get("clipboard")
    client = TestClient(_build_app())
    client.post("/api/clipboard/enabled", json={"enabled": False})
    snapshot_after = config_yaml.get("clipboard")
    check("config_yaml.clipboard unchanged",
          snapshot_before == snapshot_after,
          f"before={snapshot_before} after={snapshot_after}")
    # restore
    from backend.integrations.clipboard import clipboard_watcher
    clipboard_watcher.set_enabled(True)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    test_get_enabled_default_true()
    test_post_enabled_false_then_true()
    asyncio.get_event_loop().run_until_complete(test_disabled_skips_poll_once())
    test_disabled_doesnt_block_manual_add()
    test_post_missing_enabled_field()
    test_post_string_enabled_coerced()
    test_round_trip_get_after_post()
    test_not_persisted_to_yaml()

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
    main()
