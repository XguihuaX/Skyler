from datetime import datetime
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.models import ChatHistory, Memory, Todo, User

# ---------------------------------------------------------------------------
# Re-exported for convenience: callers can do
#   from backend.database.services import search_memory
# without knowing which module houses each function.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


async def create_user(
    session: AsyncSession, user_id: str, user_name: str
) -> User:
    """Create and persist a new user row.

    Returns the newly created User instance.
    Raises IntegrityError if user_id already exists.
    """
    user = User(user_id=user_id, user_name=user_name)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def get_user(session: AsyncSession, user_id: str) -> Optional[User]:
    """Return the User with the given user_id, or None if not found."""
    result = await session.execute(select(User).where(User.user_id == user_id))
    return result.scalar_one_or_none()


async def update_profile_summary(
    session: AsyncSession, user_id: str, summary: Optional[str]
) -> None:
    """Overwrite the free-text profile_summary for *user_id*.

    Pass ``None`` to clear the column (used after the user wipes all chat
    history). Silently does nothing if the user does not exist.
    """
    result = await session.execute(select(User).where(User.user_id == user_id))
    user = result.scalar_one_or_none()
    if user is not None:
        user.profile_summary = summary
        await session.commit()


async def get_profile_summary(
    session: AsyncSession, user_id: str
) -> Optional[str]:
    """Return the profile_summary string for *user_id*, or None."""
    result = await session.execute(select(User).where(User.user_id == user_id))
    user = result.scalar_one_or_none()
    return user.profile_summary if user else None


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------


async def add_memory(
    session: AsyncSession,
    user_id: str,
    role: str,
    type: str,
    content: str,
    embedding: Optional[bytes] = None,
    expires_at: Optional[datetime] = None,
    character_id: Optional[int] = None,
) -> Memory:
    """Insert a new long-term memory record.

    Args:
        session:    Active async DB session.
        user_id:    Owner of the memory.
        role:       'user' or 'system'.
        type:       One of 'fact', 'instruction', 'emotion', 'activity', 'daily'.
        content:    Text content of the memory.
        embedding:  Optional serialised numpy vector (bytes) for similarity search.
        expires_at: Optional expiry datetime; NULL means permanent.  Use for
                    transient states (e.g. "currently studying for exams").

    Returns the persisted Memory instance.
    """
    memory = Memory(
        user_id=user_id,
        role=role,
        type=type,
        content=content,
        embedding=embedding,
        expires_at=expires_at,
        character_id=character_id,
    )
    session.add(memory)
    await session.commit()
    await session.refresh(memory)
    return memory


async def get_all_memories(
    session: AsyncSession,
    user_id: str,
    active_only: bool = True,
    character_id: Optional[int] = None,
) -> List[Memory]:
    """Return long-term memory rows for *user_id*, oldest first.

    Args:
        active_only:  When True (default), exclude rows whose expires_at is in
                      the past.  Pass False to include all rows regardless of
                      expiry, e.g. for administrative queries.
        character_id: When provided, only memories tagged with this character
                      are returned. The startup backfill assigns NULL rows to
                      Momo so legacy memories remain visible under Momo.
    """
    from sqlalchemy import or_
    query = select(Memory).where(Memory.user_id == user_id)
    if character_id is not None:
        query = query.where(Memory.character_id == character_id)
    if active_only:
        now = datetime.utcnow()
        query = query.where(
            or_(Memory.expires_at.is_(None), Memory.expires_at > now)
        )
    query = query.order_by(Memory.created_at.asc())
    result = await session.execute(query)
    return list(result.scalars().all())


async def get_recent_memories(
    session: AsyncSession, user_id: str, limit: int = 10
) -> List[Memory]:
    """Return the most recent `limit` memory rows for the given user.

    Results are returned in chronological order (oldest → newest).
    """
    result = await session.execute(
        select(Memory)
        .where(Memory.user_id == user_id)
        .order_by(Memory.created_at.desc())
        .limit(limit)
    )
    rows = list(result.scalars().all())
    # Reverse so callers get oldest-first within the window.
    rows.reverse()
    return rows


async def delete_memory(session: AsyncSession, memory_id: int) -> None:
    """Delete a single memory row by its primary key.

    Silently does nothing if the row does not exist.
    """
    result = await session.execute(select(Memory).where(Memory.id == memory_id))
    memory = result.scalar_one_or_none()
    if memory is not None:
        await session.delete(memory)
        await session.commit()


# ---------------------------------------------------------------------------
# Todos / Alarms
# ---------------------------------------------------------------------------


async def create_todo(
    session: AsyncSession,
    user_id: str,
    owner_type: str,
    title: str,
    due_time: datetime,
    description: Optional[str] = None,
) -> Todo:
    """Create a new todo / alarm entry.

    Args:
        session:     Active async DB session.
        user_id:     Owner of the todo.
        owner_type:  'alarm', 'agent', or 'schedule'.
        title:       Short title shown to the user.
        due_time:    When the todo is due / should fire.
        description: Optional longer description.

    Returns the newly created Todo instance with status 'pending'.
    """
    todo = Todo(
        user_id=user_id,
        owner_type=owner_type,
        title=title,
        due_time=due_time,
        description=description,
        status="pending",
    )
    session.add(todo)
    await session.commit()
    await session.refresh(todo)
    return todo


async def get_pending_todos(
    session: AsyncSession, user_id: str
) -> List[Todo]:
    """Return all todos with status 'pending' for the given user, ordered by due_time."""
    result = await session.execute(
        select(Todo)
        .where(Todo.user_id == user_id, Todo.status == "pending")
        .order_by(Todo.due_time.asc())
    )
    return list(result.scalars().all())


async def get_todos(
    session: AsyncSession, user_id: str, status: Optional[str] = None
) -> List[Todo]:
    """Return todos for the given user, optionally filtered by status.

    Args:
        session: Active async DB session.
        user_id: Owner filter.
        status:  If provided, only rows matching this status are returned.
                 Pass None to retrieve all statuses.

    Results are ordered by due_time ascending.
    """
    query = select(Todo).where(Todo.user_id == user_id)
    if status is not None:
        query = query.where(Todo.status == status)
    query = query.order_by(Todo.due_time.asc())

    result = await session.execute(query)
    return list(result.scalars().all())


async def update_todo_status(
    session: AsyncSession, todo_id: int, status: str
) -> None:
    """Update the status of an existing todo.

    Args:
        session:  Active async DB session.
        todo_id:  Primary key of the todo to update.
        status:   New status value: 'pending', 'completed', 'failed', or 'multiple'.

    Silently does nothing if the todo_id does not exist.
    """
    result = await session.execute(select(Todo).where(Todo.id == todo_id))
    todo = result.scalar_one_or_none()
    if todo is not None:
        todo.status = status
        await session.commit()


# ---------------------------------------------------------------------------
# Memory — flexible search (extends get_all_memories / get_recent_memories)
# ---------------------------------------------------------------------------


async def search_memory(
    session: AsyncSession,
    user_id: str,
    role: Optional[str] = None,
    type: Optional[str] = None,
    content: Optional[str] = None,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    active_only: bool = True,
) -> List[Memory]:
    """Return memory rows for *user_id* filtered by optional predicates.

    Args:
        role:        Filter by role ('user' or 'system').
        type:        Filter by type ('fact', 'instruction', etc.).
        content:     Substring match on content (case-sensitive).
        start_time:  Include rows where created_at >= start_time.
        end_time:    Include rows where created_at < end_time.
        active_only: When True (default), exclude rows whose expires_at has
                     already passed.  Pass False to include expired rows.

    Results are ordered oldest-first.
    """
    from sqlalchemy import or_
    query = select(Memory).where(Memory.user_id == user_id)
    if role is not None:
        query = query.where(Memory.role == role)
    if type is not None:
        query = query.where(Memory.type == type)
    if content is not None:
        query = query.where(Memory.content.contains(content))
    if start_time is not None:
        query = query.where(Memory.created_at >= start_time)
    if end_time is not None:
        query = query.where(Memory.created_at < end_time)
    if active_only:
        now = datetime.utcnow()
        query = query.where(
            or_(Memory.expires_at.is_(None), Memory.expires_at > now)
        )
    query = query.order_by(Memory.created_at.asc())
    result = await session.execute(query)
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Todos — delete + flexible search
# ---------------------------------------------------------------------------


async def delete_todo(
    session: AsyncSession, user_id: str, todo_id: int
) -> None:
    """Delete the todo identified by *todo_id* belonging to *user_id*.

    Silently does nothing if the row does not exist or belongs to a different user.
    """
    result = await session.execute(
        select(Todo).where(Todo.id == todo_id, Todo.user_id == user_id)
    )
    todo = result.scalar_one_or_none()
    if todo is not None:
        await session.delete(todo)
        await session.commit()


async def search_todo(
    session: AsyncSession,
    user_id: str,
    id: Optional[int] = None,
    owner_type: Optional[str] = None,
    title: Optional[str] = None,
    description: Optional[str] = None,
    status: Optional[str] = None,
    due_start: Optional[datetime] = None,
    due_end: Optional[datetime] = None,
    created_start: Optional[datetime] = None,
    created_end: Optional[datetime] = None,
) -> List[Todo]:
    """Return todo rows for *user_id* filtered by optional predicates.

    Args:
        id:            Exact match on todo primary key.
        owner_type:    Exact match on owner_type.
        title:         Substring match on title.
        description:   Substring match on description.
        status:        Exact match on status.
        due_start:     Include rows where due_time >= due_start.
        due_end:       Include rows where due_time < due_end.
        created_start: Include rows where created_at >= created_start.
        created_end:   Include rows where created_at < created_end.

    Results are ordered by due_time ascending.
    """
    query = select(Todo).where(Todo.user_id == user_id)
    if id is not None:
        query = query.where(Todo.id == id)
    if owner_type is not None:
        query = query.where(Todo.owner_type == owner_type)
    if title is not None:
        query = query.where(Todo.title.contains(title))
    if description is not None:
        query = query.where(Todo.description.contains(description))
    if status is not None:
        query = query.where(Todo.status == status)
    if due_start is not None:
        query = query.where(Todo.due_time >= due_start)
    if due_end is not None:
        query = query.where(Todo.due_time < due_end)
    if created_start is not None:
        query = query.where(Todo.created_at >= created_start)
    if created_end is not None:
        query = query.where(Todo.created_at < created_end)
    query = query.order_by(Todo.due_time.asc())
    result = await session.execute(query)
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Chat History
# ---------------------------------------------------------------------------


_VALID_CHAT_KINDS = frozenset({"normal", "touch", "proactive"})


async def add_chat_history(
    session: AsyncSession,
    user_id: str,
    role: str,
    content: str,
    conversation_id: Optional[int] = None,
    character_id: Optional[int] = None,
    interrupted_at: Optional[datetime] = None,
    kind: str = "normal",
) -> ChatHistory:
    """Append a message to the persistent chat history for the given user.

    Args:
        session: Active async DB session.
        user_id: Owner of the message.
        role:    'user' or 'assistant'.
        content: Message text.
        conversation_id: V2.5-B optional fk to conversations.id.
        character_id:    V2.5-B optional fk to characters.id.
        interrupted_at:  v3-F. Non-None marks this assistant row as a partial
                         reply truncated by user interrupt. Only assistant
                         rows should set this.
        kind:            v3-E1 Step Z.2. 'normal' (default) / 'touch' /
                         'proactive'. Unknown values silently coerced to
                         'normal' so a typo upstream never blocks persistence.

    Returns the persisted ChatHistory instance.
    """
    if kind not in _VALID_CHAT_KINDS:
        kind = "normal"
    message = ChatHistory(
        user_id=user_id,
        role=role,
        content=content,
        conversation_id=conversation_id,
        character_id=character_id,
        interrupted_at=interrupted_at,
        kind=kind,
    )
    session.add(message)
    await session.commit()
    await session.refresh(message)
    return message


async def get_chat_history(
    session: AsyncSession,
    user_id: str,
    limit: int = 50,
    kinds: Optional[List[str]] = None,
) -> List[ChatHistory]:
    """Return the most recent `limit` chat messages for the given user.

    Args:
        kinds: Optional whitelist of `kind` values to include. When None,
               all kinds are returned (back-compat for short_term restore /
               legacy callers). Pass e.g. `['normal']` to exclude touch /
               proactive turns from profile_summary regen.

    Results are returned in chronological order (oldest → newest) so they
    can be fed directly into a messages list without further sorting.
    """
    query = select(ChatHistory).where(ChatHistory.user_id == user_id)
    if kinds is not None:
        query = query.where(ChatHistory.kind.in_(list(kinds)))
    query = query.order_by(
        ChatHistory.created_at.desc(), ChatHistory.id.desc()
    ).limit(limit)
    result = await session.execute(query)
    rows = list(result.scalars().all())
    rows.reverse()
    return rows
