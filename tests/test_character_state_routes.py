"""Tests for v3-G chunk 3 character_state + clipboard REST routes (FastAPI test client)。"""
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


async def _setup_db() -> None:
    from backend.database import init_db
    from backend.database.migrations.v3_g_chunk3_character_states import run_migration
    await init_db()
    await run_migration()


# ---------------------------------------------------------------------------
# 1. GET /api/characters/{id}/state
# ---------------------------------------------------------------------------

def test_get_state_returns_default():
    print("\n[route — GET /api/characters/{id}/state]")
    asyncio.get_event_loop().run_until_complete(_setup_db())
    client = TestClient(_build_app())
    r = client.get("/api/characters/600/state")
    check("status 200", r.status_code == 200, f"got {r.status_code}")
    data = r.json()
    check("character_id echoed", data.get("character_id") == 600)
    check("mood neutral default", data.get("mood") == "neutral")
    check("intimacy 0 default", data.get("intimacy") == 0)


# ---------------------------------------------------------------------------
# 2. POST /api/characters/{id}/reset_state
# ---------------------------------------------------------------------------

def test_reset_resets_to_default():
    print("\n[route — POST /api/characters/{id}/reset_state]")
    asyncio.get_event_loop().run_until_complete(_setup_db())
    # 先用 services 把某 character 设成非默认
    from backend.database import AsyncSessionLocal
    from backend.database.services import update_character_state

    async def setup():
        async with AsyncSessionLocal() as session:
            await update_character_state(
                session, character_id=601,
                mood="happy", intimacy_delta=2, thought="x", activity="y",
            )
    asyncio.get_event_loop().run_until_complete(setup())

    client = TestClient(_build_app())
    r = client.post("/api/characters/601/reset_state")
    check("status 200", r.status_code == 200)
    data = r.json()
    check("mood neutral", data.get("mood") == "neutral")
    check("intimacy 0", data.get("intimacy") == 0)
    check("thought None", data.get("thought") is None)
    check("activity None", data.get("activity") is None)


# ---------------------------------------------------------------------------
# 3. POST /api/clipboard/captured
# ---------------------------------------------------------------------------

def test_clipboard_captured_writes_ringbuffer():
    print("\n[route — POST /api/clipboard/captured writes buffer]")
    from backend.integrations.clipboard import clipboard_watcher
    clipboard_watcher.clear_all()

    client = TestClient(_build_app())
    r = client.post("/api/clipboard/captured", json={
        "content": "hello via route", "content_type": "plain_text",
    })
    check("status 200", r.status_code == 200)
    data = r.json()
    check("ok=True", data.get("ok") is True)
    items = clipboard_watcher.get_recent(5)
    check("ringbuffer received item",
          any("hello via route" in it.content for it in items))


def test_clipboard_captured_rejects_empty():
    print("\n[route — POST /api/clipboard/captured rejects empty]")
    client = TestClient(_build_app())
    r = client.post("/api/clipboard/captured", json={"content": "   "})
    check("status 400 on empty", r.status_code == 400, f"got {r.status_code}")


# ---------------------------------------------------------------------------
# 4. GET /api/clipboard/recent
# ---------------------------------------------------------------------------

def test_clipboard_recent_lists_items():
    print("\n[route — GET /api/clipboard/recent]")
    from backend.integrations.clipboard import clipboard_watcher
    clipboard_watcher.clear_all()
    clipboard_watcher.add_item("first")
    clipboard_watcher.add_item("second")

    client = TestClient(_build_app())
    r = client.get("/api/clipboard/recent?n=5")
    check("status 200", r.status_code == 200)
    data = r.json()
    check("count >= 2", data.get("count", 0) >= 2)
    contents = [it["content"] for it in data.get("items", [])]
    check("most recent first", contents and contents[0] == "second")
    check("contains 'first'", "first" in contents)


def test_clipboard_clear_route():
    print("\n[route — POST /api/clipboard/clear]")
    from backend.integrations.clipboard import clipboard_watcher
    clipboard_watcher.add_item("to-be-cleared")

    client = TestClient(_build_app())
    r = client.post("/api/clipboard/clear")
    check("status 200", r.status_code == 200)
    items = clipboard_watcher.get_recent(5)
    check("ringbuffer empty after clear", len(items) == 0)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    test_get_state_returns_default()
    test_reset_resets_to_default()
    test_clipboard_captured_writes_ringbuffer()
    test_clipboard_captured_rejects_empty()
    test_clipboard_recent_lists_items()
    test_clipboard_clear_route()

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
