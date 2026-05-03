# v3-C: 已被 ChatAgent 统一接管，保留文件备用。
"""MemoryAgent: CRUD dispatcher for memory, todo, and profile tables.

Receives MCP-style payloads from PlannerAgent and routes to the appropriate
database service function.  All write operations on the memory table also
generate vector embeddings via the long-term memory module.

Message contract (in)
---------------------
{
    "agent": "MemoryAgent",
    "payload": {
        "function": str,    # one of the supported function names below
        "args": { ... }     # kwargs forwarded to the handler
    }
}

Message contract (out)
----------------------
{
    "status":  "success" | "error",
    "agent":   "MemoryAgent",
    "payload": {
        "result": <serialisable data>,   # on success
        "error":  str                    # on error only
    }
}

Supported functions
-------------------
Memory  : add_memory, delete_memory, search_memory
Todo    : add_todo, delete_todo, search_todo, update_todo_status
Profile : get_profile_summary, update_profile_summary
"""
import logging
from datetime import datetime
from typing import Any, Callable, Coroutine, Dict, Optional

from backend.agents.base import IAgent
from backend.database import AsyncSessionLocal
from backend.database.models import Memory, Todo
from backend.database.services import (
    add_memory as db_add_memory,
    delete_memory as db_delete_memory,
    search_memory,
    create_todo,
    delete_todo,
    search_todo,
    update_todo_status,
    get_profile_summary,
    update_profile_summary,
)
from backend.memory.long_term import add_memory_with_embedding

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------

def _fmt_dt(dt: Optional[datetime]) -> Optional[str]:
    return dt.strftime("%Y-%m-%d %H:%M:%S") if dt else None


def _memory_to_dict(m: Memory) -> dict:
    return {
        "id": m.id,
        "user_id": m.user_id,
        "role": m.role,
        "type": m.type,
        "content": m.content,
        "expires_at": _fmt_dt(m.expires_at),
        "created_at": _fmt_dt(m.created_at),
    }


def _todo_to_dict(t: Todo) -> dict:
    return {
        "id": t.id,
        "user_id": t.user_id,
        "owner_type": t.owner_type,
        "title": t.title,
        "description": t.description,
        "due_time": _fmt_dt(t.due_time),
        "status": t.status,
        "created_at": _fmt_dt(t.created_at),
    }


def _parse_dt(value: Any) -> Optional[datetime]:
    """Parse a datetime string or return None.

    Accepted formats: 'YYYY-MM-DD HH:MM:SS', 'YYYY-MM-DDTHH:MM:SS', 'YYYY-MM-DD'.
    Raises ValueError on unparseable input (not None).
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(value), fmt)
        except ValueError:
            continue
    raise ValueError(f"Cannot parse datetime: {value!r}")


def _require(args: dict, *keys: str) -> None:
    """Raise KeyError with a clear message if any required key is absent or empty."""
    for k in keys:
        if args.get(k) is None or args.get(k) == "":
            raise KeyError(f"required argument '{k}' is missing or empty")


# ---------------------------------------------------------------------------
# Individual operation handlers
# ---------------------------------------------------------------------------

async def _handle_add_memory(args: dict) -> dict:
    _require(args, "user_id", "role", "type", "content")
    expires_at = _parse_dt(args.get("expires_at"))
    await add_memory_with_embedding(
        user_id=args["user_id"],
        content=args["content"],
        type=args["type"],
        role=args["role"],
        expires_at=expires_at,
    )
    return {"message": "memory added"}


async def _handle_delete_memory(args: dict) -> dict:
    _require(args, "user_id", "memory_id")
    async with AsyncSessionLocal() as session:
        await db_delete_memory(session, int(args["memory_id"]))
    return {"message": "memory deleted"}


async def _handle_search_memory(args: dict) -> list:
    _require(args, "user_id")
    # active_only defaults to True; callers can override with active_only=False
    active_only: bool = args.get("active_only", True)
    async with AsyncSessionLocal() as session:
        rows = await search_memory(
            session,
            user_id=args["user_id"],
            role=args.get("role"),
            type=args.get("type"),
            content=args.get("content"),
            start_time=_parse_dt(args.get("start_time")),
            end_time=_parse_dt(args.get("end_time")),
            active_only=active_only,
        )
    return [_memory_to_dict(m) for m in rows]


async def _handle_add_todo(args: dict) -> dict:
    _require(args, "user_id", "owner_type", "title", "due_time")
    due_time = _parse_dt(args["due_time"])
    if due_time is None:
        raise ValueError("due_time is required and must be a valid datetime string")
    status = args.get("status", "pending")
    async with AsyncSessionLocal() as session:
        todo = await create_todo(
            session,
            user_id=args["user_id"],
            owner_type=args["owner_type"],
            title=args["title"],
            due_time=due_time,
            description=args.get("description"),
        )
        if status != "pending":
            await update_todo_status(session, todo.id, status)
            todo.status = status
    return _todo_to_dict(todo)


async def _handle_delete_todo(args: dict) -> dict:
    _require(args, "user_id", "id")
    async with AsyncSessionLocal() as session:
        await delete_todo(session, user_id=args["user_id"], todo_id=int(args["id"]))
    return {"message": "todo deleted"}


async def _handle_search_todo(args: dict) -> list:
    _require(args, "user_id")
    async with AsyncSessionLocal() as session:
        rows = await search_todo(
            session,
            user_id=args["user_id"],
            id=args.get("id"),
            owner_type=args.get("owner_type"),
            title=args.get("title"),
            description=args.get("description"),
            status=args.get("status"),
            due_start=_parse_dt(args.get("due_start")),
            due_end=_parse_dt(args.get("due_end")),
            created_start=_parse_dt(args.get("created_start")),
            created_end=_parse_dt(args.get("created_end")),
        )
    return [_todo_to_dict(t) for t in rows]


async def _handle_update_todo_status(args: dict) -> dict:
    _require(args, "todo_id", "status")
    async with AsyncSessionLocal() as session:
        await update_todo_status(session, int(args["todo_id"]), args["status"])
    return {"message": "todo status updated"}


async def _handle_get_profile_summary(args: dict) -> dict:
    _require(args, "user_id")
    async with AsyncSessionLocal() as session:
        summary = await get_profile_summary(session, args["user_id"])
    return {"profile_summary": summary}


async def _handle_update_profile_summary(args: dict) -> dict:
    _require(args, "user_id", "summary")
    async with AsyncSessionLocal() as session:
        await update_profile_summary(session, args["user_id"], args["summary"])
    return {"message": "profile_summary updated"}


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------

_HANDLERS: Dict[str, Callable[..., Coroutine]] = {
    # Memory
    "add_memory":             _handle_add_memory,
    "delete_memory":          _handle_delete_memory,
    "search_memory":          _handle_search_memory,
    # Todo
    "add_todo":               _handle_add_todo,
    "delete_todo":            _handle_delete_todo,
    "search_todo":            _handle_search_todo,
    "update_todo_status":     _handle_update_todo_status,
    # Profile summary
    "get_profile_summary":    _handle_get_profile_summary,
    "update_profile_summary": _handle_update_profile_summary,
}


# ---------------------------------------------------------------------------
# MemoryAgent
# ---------------------------------------------------------------------------

def _ok(result: Any) -> dict:
    return {"status": "success", "agent": "MemoryAgent", "payload": {"result": result}}


def _err(msg: str) -> dict:
    return {"status": "error", "agent": "MemoryAgent", "payload": {"error": msg}}


class MemoryAgent(IAgent):

    async def handle(self, message: dict) -> dict:
        """Dispatch the requested function and return a standardised response."""
        payload = message.get("payload", {})
        function: str = payload.get("function", "")
        args: dict = payload.get("args", {}) or {}

        if not function:
            return _err("payload.function is required")

        handler = _HANDLERS.get(function)
        if handler is None:
            return _err(f"unknown function: '{function}'")

        try:
            result = await handler(args)
            return _ok(result)
        except KeyError as exc:
            return _err(f"missing argument: {exc}")
        except ValueError as exc:
            return _err(f"invalid argument: {exc}")
        except Exception as exc:
            logger.exception("MemoryAgent error in %s", function)
            return _err(f"internal error: {exc}")
