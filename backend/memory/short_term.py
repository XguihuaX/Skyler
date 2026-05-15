"""Per-user in-memory short-term conversation store.

Holds up to ``SHORT_TERM_MAX_TURNS`` turns per user(每 turn = user + assistant
message,= 2 entries in ``_store``)。Long-term promotion happens via the
LLM-driven ``save_memory`` tool in ``backend/agents/chat.py`` rather than a
standalone summariser.

**Bugfix(input tokens bloat audit § 修法 A)**:旧版 ``.add()`` 不 trim,
``SHORT_TERM_MAX`` 是 dead constant —— long session 下 short_term 无上限
增长,贡献 5-15k tokens / LLM call。本版 enforce trim on every ``.add()``。
完整诊断:``docs/audit_input_tokens_bloat.md`` + ``audit_chat_history_cleanliness.md``。
"""
import logging
from typing import Dict, List

logger = logging.getLogger(__name__)


#: 上限 turns 数(用户语义层)。1 turn ≈ 1 user + 1 assistant message。
#: 30 turns = 60 messages —— 实测 Mai 复刻 voice 场景下足以覆盖近 5-10 min
#: 对话上下文,同时把单次 LLM input 控制在 ~5-8k token 历史预算内。
SHORT_TERM_MAX_TURNS: int = 30

#: 上限 messages 数(实际 trim 比较值)= turns × 2(user + assistant)。
#: 暴露的 canonical constant —— 部分 caller(test 之类)按 message-count 校验。
SHORT_TERM_MAX: int = SHORT_TERM_MAX_TURNS * 2  # = 60


class ShortTermMemory:
    def __init__(self) -> None:
        self._store: Dict[str, List[dict]] = {}

    async def add(self, user_id: str, role: str, content: str) -> None:
        """Append a turn to the user's short-term buffer。

        Bugfix § 修法 A:append 后 enforce ``SHORT_TERM_MAX``,超出则 trim
        oldest。**所有写入路径**(ws.py 主聊天、proactive engine wake_call /
        run_trigger、main.py restore 等 5+ 处)共享此 trim,无需各调用方
        单独 enforce。
        """
        if user_id not in self._store:
            self._store[user_id] = []
        self._store[user_id].append({"role": role, "content": content})
        if len(self._store[user_id]) > SHORT_TERM_MAX:
            trimmed = len(self._store[user_id]) - SHORT_TERM_MAX
            self._store[user_id] = self._store[user_id][-SHORT_TERM_MAX:]
            logger.debug(
                "[short_term] user=%s trimmed %d old messages, kept %d (= %d turns)",
                user_id, trimmed, SHORT_TERM_MAX, SHORT_TERM_MAX_TURNS,
            )

    async def get(self, user_id: str) -> List[dict]:
        """Return all turns for the user in chronological order."""
        return list(self._store.get(user_id, []))

    async def count(self, user_id: str) -> int:
        """Return the number of stored turns for the user."""
        return len(self._store.get(user_id, []))

    async def trim(self, user_id: str, keep: int) -> None:
        """Keep only the most recent *keep* turns, discarding the rest."""
        buf = self._store.get(user_id)
        if buf is not None:
            self._store[user_id] = buf[-keep:]

    async def clear(self, user_id: str) -> None:
        """Remove all stored turns for the user."""
        self._store.pop(user_id, None)


short_term_memory = ShortTermMemory()
