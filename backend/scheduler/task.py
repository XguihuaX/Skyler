"""Alarm scheduler: polls the DB every 30 s and fires due alarms.

On startup call:
    await scheduler.start(user_id)

On shutdown call:
    await scheduler.stop()

New alarms created at runtime are picked up automatically by the next
polling cycle — no explicit registration required.  The public
``schedule_alarm`` method is kept as an API hook for future use.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

_CHECK_INTERVAL = 30  # seconds
# due_time is stored as naive Beijing datetime (set by PlannerAgent)
_CST = timezone(timedelta(hours=8))


class AlarmScheduler:
    def __init__(self) -> None:
        self._running: bool = False
        self._task: Optional[asyncio.Task] = None
        self._user_id: str = ""

    async def start(self, user_id: str) -> None:
        """Start the polling loop for *user_id*. Safe to call multiple times."""
        if self._running:
            return
        self._user_id = user_id
        self._running = True
        await self._mark_stale_alarms_failed()
        self._task = asyncio.create_task(self._loop())
        logger.info("AlarmScheduler started for user %s", user_id)

    async def stop(self) -> None:
        """Cancel the polling loop gracefully."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("AlarmScheduler stopped")

    async def schedule_alarm(self, todo_id: int) -> None:
        """Hook called after a new alarm is persisted.

        With poll-based scheduling the loop picks it up automatically,
        so no extra work is needed here.
        """

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _mark_stale_alarms_failed(self) -> None:
        """On startup, mark pending alarms that are already past due as failed."""
        from backend.database import AsyncSessionLocal
        from backend.database.services import search_todo, update_todo_status

        if not self._user_id:
            return

        now = datetime.now(_CST).replace(tzinfo=None)
        async with AsyncSessionLocal() as session:
            stale = await search_todo(
                session,
                user_id=self._user_id,
                owner_type="alarm",
                due_end=now,
            )

        for todo in stale:
            if todo.status not in ("pending", "multiple"):
                continue
            try:
                async with AsyncSessionLocal() as session:
                    await update_todo_status(session, todo.id, "failed")
                logger.info(
                    "AlarmScheduler: marked stale alarm %d as failed (was due %s)",
                    todo.id, todo.due_time,
                )
            except Exception:
                logger.exception("AlarmScheduler: failed to mark alarm %d as failed", todo.id)

    async def _loop(self) -> None:
        while self._running:
            try:
                await self._check_due_alarms()
            except Exception:
                logger.exception("AlarmScheduler: error during alarm check")
            await asyncio.sleep(_CHECK_INTERVAL)

    async def _check_due_alarms(self) -> None:
        from backend.database import AsyncSessionLocal
        from backend.database.services import search_todo, update_todo_status
        from backend.routes.ws import connection_manager

        if not self._user_id:
            return

        # Beijing time as naive datetime — matches how PlannerAgent stores due_time
        now = datetime.now(_CST).replace(tzinfo=None)
        # Add 1 s so the filter (due_time < due_end) effectively catches due_time <= now
        due_end = now + timedelta(seconds=1)

        async with AsyncSessionLocal() as session:
            candidates = await search_todo(
                session,
                user_id=self._user_id,
                owner_type="alarm",
                due_end=due_end,
            )

        due = [t for t in candidates if t.status in ("pending", "multiple")]
        if not due:
            return

        for todo in due:
            try:
                content = todo.description or todo.title
                await connection_manager.push(
                    todo.user_id,
                    {"type": "alarm", "content": content, "todo_id": todo.id},
                )
                logger.info(
                    "Alarm fired: todo_id=%d user=%s content=%r",
                    todo.id, todo.user_id, content,
                )
                async with AsyncSessionLocal() as session:
                    await update_todo_status(session, todo.id, "completed")
            except Exception:
                logger.exception("AlarmScheduler: failed to fire alarm %d", todo.id)


scheduler = AlarmScheduler()
