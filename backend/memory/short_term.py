"""Per-(user, character) in-memory short-term conversation store。

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

**Bug 1 修法(audit_lost_replies.md 主因 a)**:b5b0a47 path-7 修法只解决
"跨 character 泄漏",同一 character 下不同 conversation 的历史 turn 仍合并
喂 LLM,导致用户新建对话发"你好"仍被 LLM 当复读(看到 conv 38 + conv 40
两次"你好")。本修:**每个 entry 记录 ``conv_id``**(``add`` 时写、``get``
时按 caller 给的 ``conversation_id`` 精确过滤),桶仍按 (user, char) 不变
保留 path-7 修法语义,只是桶内额外按 conv_id 分隔。
- ``conversation_id=None`` 在 ``add`` 时表示该 entry 不绑 conv(legacy / test
  / proactive 无 conv 场景)。``get`` 给 ``conversation_id=None`` 时返回**全部
  entry**(无过滤,backward compat);给具体 conv_id 时严格匹配。
- restore 时 (main.py) 把 chat_history.conversation_id 同步到 entry,这样
  重启后跨 conv 历史也能按 conv 隔离。
"""
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


#: 上限 turns 数(用户语义层)。1 turn ≈ 1 user + 1 assistant message。
#: 30 turns = 60 messages —— 实测 Mai 复刻 voice 场景下足以覆盖近 5-10 min
#: 对话上下文,同时把单次 LLM input 控制在 ~5-8k token 历史预算内。
SHORT_TERM_MAX_TURNS: int = 25

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
        conversation_id: Optional[int] = None,
        created_at: Optional[datetime] = None,
    ) -> None:
        """Append a turn to the (user_id, character_id) buffer。

        路径 7 修法:``character_id`` 进 key,**不同 character 物理隔离**。
        Bug 1 修法:``conversation_id`` 进 entry 元数据(不进 key),让
        ``get(conversation_id=X)`` 能精确过滤,同 character 不同 conv 不串。
        修法 A:append 后 enforce ``SHORT_TERM_MAX``,超出则 trim oldest。
        trim 按 bucket-level(per (user, char)),保留 60 messages cap;
        conv 维度的"过滤"在 read 端做,不影响写入 cap 语义。

        DailyAgent Stage 1 时间地基:每条 entry 记 ``created_at``(UTC),
        供 chat.py 拼 prompt 时给 history 行前缀 ``[今天 HH:MM]`` 等。
        ``created_at`` 缺省 = 当前 utcnow;restore_memory 走 chat_history
        实际时间。
        """
        key: _Key = (user_id, character_id)
        if key not in self._store:
            self._store[key] = []
        self._store[key].append({
            "role": role,
            "content": content,
            "conv_id": conversation_id,
            "created_at": created_at if created_at is not None else datetime.utcnow(),
        })
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
        self, user_id: str,
        character_id: Optional[int] = None,
        conversation_id: Optional[int] = None,
    ) -> List[dict]:
        """Return turns for (user_id, character_id),optionally filtered by conv。

        Bug 1 修法:
          * ``conversation_id is None`` → 返回桶内**所有** entry(legacy / test
            / 不关心 conv 隔离的调用方,backward compat)。
          * ``conversation_id`` 给具体值 → 严格匹配 entry.conv_id == 给定值。
            entry.conv_id is None 的 entry **不匹配**(它们是不绑 conv 的
            legacy / proactive 数据,跨 conv 不应被 normal chat 看到)。
        返回的 dict 也带 ``conv_id`` 字段(caller 通常只取 role / content,
        多一个 key 无害;有用例时可直接读)。
        """
        bucket = self._store.get((user_id, character_id), [])
        if conversation_id is None:
            return list(bucket)
        return [e for e in bucket if e.get("conv_id") == conversation_id]

    async def count(
        self, user_id: str,
        character_id: Optional[int] = None,
        conversation_id: Optional[int] = None,
    ) -> int:
        """Return entry count for the bucket, optionally filtered by conv。"""
        bucket = self._store.get((user_id, character_id), [])
        if conversation_id is None:
            return len(bucket)
        return sum(1 for e in bucket if e.get("conv_id") == conversation_id)

    async def trim(
        self, user_id: str, keep: int,
        character_id: Optional[int] = None,
    ) -> None:
        """Keep only the most recent *keep* turns in (user_id, character_id) bucket。

        Bucket-level trim — 跨 conv 一起 trim(保留修法 A 的 60-cap 语义)。
        conv 维度按 read-side filter 处理,写入 cap 不分 conv。
        """
        key: _Key = (user_id, character_id)
        buf = self._store.get(key)
        if buf is not None:
            self._store[key] = buf[-keep:]

    async def clear(
        self, user_id: str,
        character_id: Optional[int] = None,
        conversation_id: Optional[int] = None,
    ) -> None:
        """Remove turns for (user_id, character_id)[, optionally only one conv]。

        Bug 1 修法:
          * ``conversation_id is None`` → 删整个 (user, char) bucket(原行为)
          * ``conversation_id`` 给具体值 → 桶内仅删 entry.conv_id == 给定值 的
            entry,其他 conv 保留。
        路径 7 修法:精确按 bucket 清,不波及其他 character bucket。
        清空所有 character 用 ``clear_all_for_user`` (admin / shutdown 用)。
        """
        key: _Key = (user_id, character_id)
        if conversation_id is None:
            self._store.pop(key, None)
            return
        buf = self._store.get(key)
        if buf is None:
            return
        self._store[key] = [e for e in buf if e.get("conv_id") != conversation_id]

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
