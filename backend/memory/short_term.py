"""Per-(user, character) in-memory short-term conversation store.

Holds up to ``SHORT_TERM_MAX_TURNS`` turns per **(user_id, character_id)**
bucket (每 turn = user + assistant message,= 2 entries in ``_store``)。
Long-term promotion happens via the LLM-driven ``save_memory`` tool in
``backend/agents/chat.py`` rather than a standalone summariser.

**修法 A(input tokens bloat audit)**:旧版 ``.add()`` 不 trim,
``SHORT_TERM_MAX`` 是 dead constant —— long session 下 short_term 无上限
增长,贡献 5-15k tokens / LLM call。本版 enforce trim on every ``.add()``。
完整诊断:``docs/audit_input_tokens_bloat.md`` + ``audit_chat_history_cleanliness.md``。

**路径 7 修法(audit_role_switch.md + audit_ja_persist.md)**:旧版 key=user_id,
切角色后旧角色历史(含 ``<ja>`` precedent)被原样喂给新角色 LLM → 八重输出
"我是麻衣" / 中文角色仍出日语等持续 bug。本版 key=(user_id, character_id),
每角色独立 bucket,跨角色不再泄漏。``character_id=None`` 保留作为 legacy /
test fallback bucket(不带角色信息的调用进此 bucket,与具体角色 bucket 不混)。
"""
import logging
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


#: 上限 turns 数(用户语义层)。1 turn ≈ 1 user + 1 assistant message。
#: 30 turns = 60 messages —— 实测 Mai 复刻 voice 场景下足以覆盖近 5-10 min
#: 对话上下文,同时把单次 LLM input 控制在 ~5-8k token 历史预算内。
SHORT_TERM_MAX_TURNS: int = 30

#: 上限 messages 数(实际 trim 比较值)= turns × 2(user + assistant)。
#: 暴露的 canonical constant —— 部分 caller(test 之类)按 message-count 校验。
SHORT_TERM_MAX: int = SHORT_TERM_MAX_TURNS * 2  # = 60


_Key = Tuple[str, Optional[int]]


class ShortTermMemory:
    def __init__(self) -> None:
        self._store: Dict[_Key, List[dict]] = {}

    async def add(
        self,
        user_id: str,
        role: str,
        content: str,
        character_id: Optional[int] = None,
    ) -> None:
        """Append a turn to the (user_id, character_id) buffer。

        路径 7 修法:``character_id`` 进 key,**不同 character 物理隔离**。
        当前 character_id=None 时落入 None bucket(legacy / test path)。
        修法 A:append 后 enforce ``SHORT_TERM_MAX``,超出则 trim oldest。
        """
        key: _Key = (user_id, character_id)
        if key not in self._store:
            self._store[key] = []
        self._store[key].append({"role": role, "content": content})
        if len(self._store[key]) > SHORT_TERM_MAX:
            trimmed = len(self._store[key]) - SHORT_TERM_MAX
            self._store[key] = self._store[key][-SHORT_TERM_MAX:]
            logger.debug(
                "[short_term] user=%s char=%s trimmed %d old messages, "
                "kept %d (= %d turns)",
                user_id, character_id, trimmed,
                SHORT_TERM_MAX, SHORT_TERM_MAX_TURNS,
            )

    async def get(
        self, user_id: str, character_id: Optional[int] = None,
    ) -> List[dict]:
        """Return all turns for (user_id, character_id) in chronological order."""
        return list(self._store.get((user_id, character_id), []))

    async def count(
        self, user_id: str, character_id: Optional[int] = None,
    ) -> int:
        """Return the number of stored turns in the (user_id, character_id) bucket."""
        return len(self._store.get((user_id, character_id), []))

    async def trim(
        self, user_id: str, keep: int,
        character_id: Optional[int] = None,
    ) -> None:
        """Keep only the most recent *keep* turns in (user_id, character_id) bucket."""
        key: _Key = (user_id, character_id)
        buf = self._store.get(key)
        if buf is not None:
            self._store[key] = buf[-keep:]

    async def clear(
        self, user_id: str, character_id: Optional[int] = None,
    ) -> None:
        """Remove all stored turns for (user_id, character_id) bucket。

        路径 7 修法:精确按 bucket 清,不波及其他 character bucket。
        清空所有 character 用 ``clear_all_for_user`` (admin / shutdown 用)。
        """
        self._store.pop((user_id, character_id), None)

    async def clear_all_for_user(self, user_id: str) -> None:
        """Remove **all** buckets belonging to *user_id*(跨所有 character)。

        admin / shutdown / 严重污染时强清用。普通用户级 ``clear_short_term``
        tool 不调此方法 —— 那个走 ``clear(user_id, character_id=cur)``,只清
        当前角色 bucket。
        """
        keys_to_drop = [k for k in self._store if k[0] == user_id]
        for k in keys_to_drop:
            self._store.pop(k, None)


short_term_memory = ShortTermMemory()
