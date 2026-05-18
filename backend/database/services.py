from datetime import datetime
from typing import List, Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.models import (
    CharacterState,
    ChatHistory,
    Memory,
    PendingBriefing,
    Todo,
    User,
)

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
        query = query.where(
            or_(Memory.character_id == character_id, Memory.character_id.is_(None))
        )
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

    v4-beta Stage 2 supersede+墓碑 Phase B:**仅当该行 ``expires_at IS NULL``
    (持久事实)** 时,在同事务里把 (user_id, content, embedding, character_id)
    INSERT 进 ``memory_tombstone`` —— 防止下次 worker / save_memory 又把同一
    事实重抽进 memory 表。**只读** ``expires_at`` 判 NULL,**绝不写/改它**。
    时效性提醒(``expires_at`` 有值)→ 不写墓碑,照常硬删
    (recall 侧已按 ``active_only=True`` 自动过滤过期,无需墓碑挡)。
    本表 / 列由 v4_0_0_memory_tombstone migration 保证存在(幂等)。
    """
    result = await session.execute(select(Memory).where(Memory.id == memory_id))
    memory = result.scalar_one_or_none()
    if memory is not None:
        # 墓碑写入(仅 expires_at IS NULL 的持久事实)。同事务,与 session.delete
        # 一起 commit;任一失败会回滚两边。
        if memory.expires_at is None:
            await session.execute(text(
                "INSERT INTO memory_tombstone "
                "(user_id, content, embedding, character_id) "
                "VALUES (:u, :c, :e, :cid)"
            ), {
                "u": memory.user_id,
                "c": memory.content,
                "e": memory.embedding,
                "cid": memory.character_id,
            })
        await session.delete(memory)
        await session.commit()


# ---------------------------------------------------------------------------
# Todos / Alarms
# ---------------------------------------------------------------------------


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
    proactive_trigger: Optional[str] = None,
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
        proactive_trigger: v3-G chunk 2. Trigger name when kind='proactive'
                         (e.g. 'morning_briefing'). NULL otherwise. Coerced
                         to NULL when kind != 'proactive' so callers can
                         pass it unconditionally without polluting normal rows.

    Returns the persisted ChatHistory instance.
    """
    if kind not in _VALID_CHAT_KINDS:
        kind = "normal"
    if kind != "proactive":
        proactive_trigger = None
    message = ChatHistory(
        user_id=user_id,
        role=role,
        content=content,
        conversation_id=conversation_id,
        character_id=character_id,
        interrupted_at=interrupted_at,
        kind=kind,
        proactive_trigger=proactive_trigger,
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


async def get_last_assistant_turn(
    session: AsyncSession, user_id: str,
) -> Optional[ChatHistory]:
    """v3-G chunk 2.6 helper —— 拿用户最近一行 assistant chat_history。

    用途：wake_call stage 2 检测，确认上一条 assistant turn 的
    ``proactive_trigger == 'wake_call'`` 才注入 addendum。其他用户也可
    复用此 helper（如未来 follow-up 链路）。
    """
    row = (await session.execute(
        select(ChatHistory)
        .where(ChatHistory.user_id == user_id)
        .where(ChatHistory.role == "assistant")
        .order_by(ChatHistory.created_at.desc(), ChatHistory.id.desc())
        .limit(1)
    )).scalar_one_or_none()
    return row


# ---------------------------------------------------------------------------
# v3-G chunk 2.6 — pending_briefings CRUD
# ---------------------------------------------------------------------------

async def add_pending_briefing(
    session: AsyncSession,
    *,
    user_id: str,
    trigger_name: str,
    briefing_data_json: str,
    character_id: int,
    conversation_id: int,
    ttl_minutes: int = 30,
) -> PendingBriefing:
    """写入一行 pending_briefing。``created_at`` 用 ``datetime.utcnow()``
    显式赋值（不走 server_default），保证 stage 2 比较的 ``created_at``
    与 server-side ``utcnow`` 时区一致。
    """
    row = PendingBriefing(
        user_id=user_id,
        trigger_name=trigger_name,
        briefing_data_json=briefing_data_json,
        character_id=character_id,
        conversation_id=conversation_id,
        created_at=datetime.utcnow(),
        ttl_minutes=int(ttl_minutes),
        consumed_at=None,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def get_active_pending_briefing(
    session: AsyncSession,
    user_id: str,
    trigger_name: Optional[str] = None,
    now: Optional[datetime] = None,
) -> Optional[PendingBriefing]:
    """拿最近一行 ``consumed_at IS NULL`` 且未超 TTL 的 pending_briefing。

    Args:
        trigger_name: 可选 filter（默认任意 trigger）
        now: 测试可注入；正式路径用 ``datetime.utcnow()``

    返回 None 表示没有"刚被叫早还没回应"的状态。

    实现说明：用 SQLite 不支持 timezone-aware ``utcnow`` 与 ORM
    ``datetime`` 比较时统一走 naive utc。``ttl_minutes`` 算成秒后用
    Python 端二次过滤——纯 SQL ``DATETIME(now) - DATETIME(created_at)``
    SQLite 不直观，宁可多取一行后过滤。
    """
    if now is None:
        now = datetime.utcnow()
    query = (
        select(PendingBriefing)
        .where(PendingBriefing.user_id == user_id)
        .where(PendingBriefing.consumed_at.is_(None))
    )
    if trigger_name is not None:
        query = query.where(PendingBriefing.trigger_name == trigger_name)
    query = query.order_by(
        PendingBriefing.created_at.desc(), PendingBriefing.id.desc(),
    ).limit(1)
    row = (await session.execute(query)).scalar_one_or_none()
    if row is None:
        return None
    # TTL 过期 → 视为不存在（不删行；后台 housekeeping 后续做）
    age = now - row.created_at
    if age.total_seconds() > row.ttl_minutes * 60:
        return None
    return row


async def consume_pending_briefing(
    session: AsyncSession,
    pending_id: int,
    now: Optional[datetime] = None,
) -> bool:
    """把一行 pending 的 ``consumed_at`` 设为 now。已消费再调返 False
    （idempotent，幂等不抛错）。"""
    if now is None:
        now = datetime.utcnow()
    row = (await session.execute(
        select(PendingBriefing).where(PendingBriefing.id == pending_id)
    )).scalar_one_or_none()
    if row is None or row.consumed_at is not None:
        return False
    row.consumed_at = now
    await session.commit()
    return True


# ---------------------------------------------------------------------------
# v3-G chunk 3b — character_states CRUD
# ---------------------------------------------------------------------------

#: chunk 3b mood enum；application 层校验，不下放 DB（未来加 mood 不需 schema 迁移）
VALID_MOODS = frozenset({"happy", "sad", "curious", "calm", "excited", "tired", "neutral"})

#: 亲密度上下界，clamping 在所有写入路径
INTIMACY_MIN = 0
INTIMACY_MAX = 100

#: 单轮 LLM 通过 ``<state_update intimacy_delta>`` 一次最多调整的幅度
INTIMACY_DELTA_PER_TURN_MAX = 2


def _clamp_intimacy(v: int) -> int:
    return max(INTIMACY_MIN, min(INTIMACY_MAX, int(v)))


def _normalize_mood(m: Optional[str]) -> Optional[str]:
    if not isinstance(m, str):
        return None
    cleaned = m.strip().lower()
    return cleaned if cleaned in VALID_MOODS else None


async def get_or_create_character_state(
    session: AsyncSession, character_id: int,
) -> CharacterState:
    """每个 character 一行 state；缺失时按默认值创建。"""
    row = (await session.execute(
        select(CharacterState).where(CharacterState.character_id == character_id)
    )).scalar_one_or_none()
    if row is not None:
        return row
    now = datetime.utcnow()
    row = CharacterState(
        character_id=character_id,
        mood="neutral",
        intimacy=0,
        current_thought=None,
        current_activity=None,
        last_interaction_at=now,
        updated_at=now,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def update_character_state(
    session: AsyncSession,
    character_id: int,
    *,
    mood: Optional[str] = None,
    intimacy_delta: Optional[int] = None,
    intimacy_absolute: Optional[int] = None,
    thought: Optional[str] = None,
    activity: Optional[str] = None,
    bump_last_interaction: bool = False,
) -> CharacterState:
    """统一更新接口。每个参数可选；只更新传入的字段。

    * ``mood`` 不在 enum 内 → 静默忽略（不抛错，避免 LLM 拼错时整轮挂掉）
    * ``intimacy_delta`` clamp 到 ``[-INTIMACY_DELTA_PER_TURN_MAX, +X]`` 后
      累加到当前值，再 clamp 到 [0, 100]
    * ``intimacy_absolute`` 直接赋（用于 reset / decay 路径），优先级高于 delta
    * ``thought`` / ``activity`` 长度太长截断到 60 字
    * ``bump_last_interaction``: True 时把 ``last_interaction_at`` 设为 utcnow
      （任何 user message 入 ChatAgent 时调）
    """
    row = await get_or_create_character_state(session, character_id)
    changed = False

    norm_mood = _normalize_mood(mood)
    if norm_mood is not None and norm_mood != row.mood:
        row.mood = norm_mood
        changed = True

    if intimacy_absolute is not None:
        new_val = _clamp_intimacy(intimacy_absolute)
        if new_val != row.intimacy:
            row.intimacy = new_val
            changed = True
    elif intimacy_delta is not None:
        d = max(-INTIMACY_DELTA_PER_TURN_MAX, min(INTIMACY_DELTA_PER_TURN_MAX, int(intimacy_delta)))
        if d != 0:
            row.intimacy = _clamp_intimacy(row.intimacy + d)
            changed = True

    if thought is not None:
        new_thought = thought.strip()[:60] or None
        if new_thought != row.current_thought:
            row.current_thought = new_thought
            changed = True

    if activity is not None:
        new_activity = activity.strip()[:60] or None
        if new_activity != row.current_activity:
            row.current_activity = new_activity
            changed = True

    now = datetime.utcnow()
    if bump_last_interaction:
        row.last_interaction_at = now
        changed = True
    if changed:
        row.updated_at = now
        await session.commit()
        await session.refresh(row)
    return row


async def reset_character_state(
    session: AsyncSession, character_id: int,
) -> CharacterState:
    """把指定 character 的 state 重置为出厂默认。设置面板"重置亲密度"按钮调用。"""
    row = await get_or_create_character_state(session, character_id)
    now = datetime.utcnow()
    row.mood = "neutral"
    row.intimacy = 0
    row.current_thought = None
    row.current_activity = None
    row.last_interaction_at = now
    row.updated_at = now
    await session.commit()
    await session.refresh(row)
    return row


async def list_all_character_ids(session: AsyncSession) -> List[int]:
    """枚举所有 ``characters.id`` —— 给 intimacy_decay cron 遍历用。"""
    from backend.database.models import Character
    result = await session.execute(select(Character.id))
    return [int(r) for r in result.scalars().all()]


async def list_state_character_ids(session: AsyncSession) -> List[int]:
    """枚举所有 ``character_states.character_id`` —— intimacy_decay 实际遍历对象。

    与 ``list_all_character_ids`` 区别：本函数返"已有 state 行"的角色，避免
    全表扫 Character 后大量 0-intimacy 0-decay 空转；同时支持运行时只为部分
    character 创建 state 的场景。
    """
    result = await session.execute(select(CharacterState.character_id))
    return [int(r) for r in result.scalars().all()]
