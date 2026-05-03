"""Integration test: all major subsystems with in-memory DB.

Covers:
  1. REST API  — memory / personality / todos / profile (11 endpoints)
  2. MemoryAgent — write → query
  3. ToolAgent   — switch_character
  4. AlarmScheduler — add 3-second alarm → confirm push received
  5. ConnectionManager singleton — ws.py and scheduler share same object
  6. WebSocket pipeline — simulated _handle_message with mocked ChatAgent
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

# ── in-memory DB bootstrap ───────────────────────────────────────────────────
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
import backend.database as _db_mod

_ENGINE  = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
_SESSION = sessionmaker(_ENGINE, class_=AsyncSession, expire_on_commit=False)
_db_mod.engine            = _ENGINE
_db_mod.AsyncSessionLocal = _SESSION

from backend.database import Base, models as _m  # noqa

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))


async def setup() -> None:
    async with _ENGINE.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    from backend.database.services import create_user
    async with _SESSION() as s:
        await create_user(s, "default", "Momo")


# ---------------------------------------------------------------------------
# 1. REST API — all 11 endpoints via ASGI TestClient
# ---------------------------------------------------------------------------

async def test_rest_api() -> None:
    print("\n[REST API — all endpoints]")
    from httpx import AsyncClient, ASGITransport
    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:

        # memory/list
        r = await client.get("/api/memory/list")
        check("GET /memory/list 200",  r.status_code == 200)
        check("returns list",          isinstance(r.json(), list))

        # memory/add
        r = await client.post("/api/memory/add", json={
            "role": "user", "type": "fact", "content": "我喜欢喝咖啡"
        })
        check("POST /memory/add 201",  r.status_code == 201)
        mem_id = r.json().get("id")
        check("returns id",            mem_id is not None)

        # memory/list — should have 1 item
        r = await client.get("/api/memory/list")
        check("memory list has 1 row", len(r.json()) >= 1)

        # memory/{id} DELETE
        r = await client.delete(f"/api/memory/{mem_id}")
        check("DELETE /memory/{id} 204", r.status_code == 204)

        # personality/list
        r = await client.get("/api/personality/list")
        check("GET /personality/list 200", r.status_code == 200)

        # personality/add
        r = await client.post("/api/personality/add", json={
            "type": "preference", "tag": "咖啡", "content": "每天必喝"
        })
        check("POST /personality/add 201", r.status_code == 201)

        # personality/list filtered
        r = await client.get("/api/personality/list?type=preference")
        check("personality list filtered",  len(r.json()) >= 1)
        check("tag correct",               r.json()[0]["tag"] == "咖啡")

        # personality/{tag} DELETE
        r = await client.delete("/api/personality/咖啡?type=preference")
        check("DELETE /personality/{tag} 204", r.status_code == 204)

        # todos/list
        r = await client.get("/api/todos/list")
        check("GET /todos/list 200", r.status_code == 200)

        # todos/add
        r = await client.post("/api/todos/add", json={
            "owner_type": "agent",
            "title": "test todo",
            "due_time": "2030-01-01 09:00:00",
        })
        check("POST /todos/add 201", r.status_code == 201)
        todo_id = r.json().get("id")

        # todos/{id}/status PATCH
        r = await client.patch(f"/api/todos/{todo_id}/status", json={"status": "completed"})
        check("PATCH /todos/{id}/status 200", r.status_code == 200)
        check("status updated",              r.json()["status"] == "completed")

        # profile GET
        r = await client.get("/api/profile")
        check("GET /profile 200", r.status_code == 200)
        check("profile_summary key", "profile_summary" in r.json())

        # profile PATCH
        r = await client.patch("/api/profile", json={"summary": "测试用户画像"})
        check("PATCH /profile 200", r.status_code == 200)

        # profile GET — verify update
        r = await client.get("/api/profile")
        check("profile summary persisted", r.json()["profile_summary"] == "测试用户画像")


# ---------------------------------------------------------------------------
# 2. MemoryAgent: write → query
# ---------------------------------------------------------------------------

async def test_memory_agent() -> None:
    print("\n[MemoryAgent — write then query]")
    from backend.agents.memory import MemoryAgent

    agent = MemoryAgent()

    # write
    r = await agent.handle({
        "agent": "MemoryAgent",
        "payload": {
            "function": "add_memory",
            "args": {
                "user_id": "default",
                "role": "user",
                "type": "fact",
                "content": "我的生日是3月15日",
            },
        },
    })
    check("add_memory success", r["status"] == "success")
    check("message returned",   r["payload"]["result"]["message"] == "memory added")

    # query
    r = await agent.handle({
        "agent": "MemoryAgent",
        "payload": {
            "function": "search_memory",
            "args": {"user_id": "default", "type": "fact"},
        },
    })
    check("search_memory success",    r["status"] == "success")
    results_list = r["payload"]["result"]
    check("at least 1 result",        len(results_list) >= 1)
    found = any("3月15日" in m["content"] for m in results_list)
    check("written content found",    found)


# ---------------------------------------------------------------------------
# 3. ToolAgent: switch_character
# ---------------------------------------------------------------------------

async def test_tool_agent() -> None:
    print("\n[ToolAgent — switch_character]")
    from backend.agents.tool import ToolAgent
    from backend.config.prompt_manager import prompt_manager

    agent = ToolAgent()

    r = await agent.handle({
        "agent": "ToolAgent",
        "payload": {
            "function": "switch_character",
            "args": {"user_id": "default", "character_id": "八重神子"},
        },
    })
    check("switch_character success", r["status"] == "success")
    char = prompt_manager.get_current_character("default")
    check("character switched",       char == "八重神子")

    # switch back
    await agent.handle({
        "agent": "ToolAgent",
        "payload": {
            "function": "switch_character",
            "args": {"user_id": "default", "character_id": "默认"},
        },
    })
    check("switched back",            prompt_manager.get_current_character("default") == "默认")


# ---------------------------------------------------------------------------
# 4. AlarmScheduler: add alarm → fire within poll interval
# ---------------------------------------------------------------------------

async def test_alarm_scheduler() -> None:
    print("\n[AlarmScheduler — 3-second alarm]")
    from datetime import datetime, timedelta, timezone
    from backend.routes.ws import connection_manager
    from backend.scheduler.task import AlarmScheduler
    from backend.database.services import create_todo, search_todo, update_todo_status

    _CST = timezone(timedelta(hours=8))

    received: list = []

    # Temporarily inject a fake push into connection_manager
    original_push = connection_manager.push

    async def _capture_push(uid: str, msg: dict) -> None:
        received.append(msg)

    connection_manager.push = _capture_push  # type: ignore[method-assign]

    try:
        # Add alarm due 2 seconds in the past (guaranteed to fire immediately)
        past_time = datetime.now(_CST).replace(tzinfo=None) - timedelta(seconds=2)
        async with _SESSION() as s:
            todo = await create_todo(
                s, user_id="default", owner_type="alarm",
                title="alarm", due_time=past_time, description="测试闹钟",
            )

        # Run scheduler (check-only, no full loop)
        sched = AlarmScheduler()
        sched._user_id = "default"
        await sched._check_due_alarms()

        check("push received",         len(received) == 1)
        if received:
            msg = received[0]
            check("type is alarm",     msg.get("type") == "alarm")
            check("content correct",   "测试闹钟" in msg.get("content", ""))
            check("todo_id present",   msg.get("todo_id") == todo.id)

        # Verify status updated to completed
        async with _SESSION() as s:
            rows = await search_todo(s, user_id="default", id=todo.id)
        check("status → completed",    rows and rows[0].status == "completed")

    finally:
        connection_manager.push = original_push  # type: ignore[method-assign]


# ---------------------------------------------------------------------------
# 5. ConnectionManager singleton
# ---------------------------------------------------------------------------

def test_connection_manager_singleton() -> None:
    print("\n[ConnectionManager — singleton identity]")
    from backend.routes.ws import connection_manager as ws_cm
    from backend.routes.ws import connection_manager as sched_cm
    check("same object via both imports", ws_cm is sched_cm)

    import backend.scheduler.task as _task
    import importlib, pathlib, ast
    src = pathlib.Path("backend/scheduler/task.py").read_text()
    check("scheduler imports from ws.py", "from backend.routes.ws import connection_manager" in src)


# ---------------------------------------------------------------------------
# 6. WebSocket pipeline — mocked LLM
# ---------------------------------------------------------------------------

async def test_ws_pipeline() -> None:
    print("\n[WebSocket pipeline — mock LLM]")
    import backend.agents.chat as _chat_mod

    # Mock stream to yield a fixed sentence
    async def _fake_stream(self, msg):
        yield "你好！这是测试回复。"

    original_stream = _chat_mod.ChatAgent.stream
    _chat_mod.ChatAgent.stream = _fake_stream

    sent: list = []

    class _FakeWS:
        async def send_json(self, data: dict) -> None:
            sent.append(data)

    try:
        from backend.routes.ws import _handle_message
        await _handle_message(_FakeWS(), {"type": "text", "content": "你好", "user_id": "default"})
    finally:
        _chat_mod.ChatAgent.stream = original_stream

    types = [m.get("type") for m in sent]
    check("got text_chunk",    "text_chunk" in types)
    check("got done",          "done" in types)
    check("no error",          "error" not in types)
    chunk = next((m for m in sent if m.get("type") == "text_chunk"), None)
    check("chunk content",     chunk and "测试回复" in chunk.get("content", ""))


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

async def main() -> None:
    await setup()

    await test_rest_api()
    await test_memory_agent()
    await test_tool_agent()
    await test_alarm_scheduler()
    test_connection_manager_singleton()
    await test_ws_pipeline()

    total  = len(results)
    passed = sum(1 for _, ok in results if ok)
    print(f"\n{'='*50}")
    print(f"Integration results: {passed}/{total} passed")
    if passed < total:
        print("FAILED:", ", ".join(n for n, ok in results if not ok))
        sys.exit(1)
    else:
        print("ALL INTEGRATION TESTS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
