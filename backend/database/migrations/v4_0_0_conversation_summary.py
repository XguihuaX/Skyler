"""v4.0.0 — conversation_summary 表(有界滚动摘要层).

# 背景

audit_z5(Stage 1)+ Stage 2 第一刀(/tmp/diag_z5_report.md)实锤:
- 默认用户 memory 表 0 行
- 真因:chat_history 容量薄(4 短 turn)+ extraction prompt 门槛严
  → LLM 主动判 ``[]`` → 0 写入(LLM 没抛任何异常)
- short_term cap 30 turn + long-term 经常 0 行 = 用户体感"超 30 turn 后角色完全失忆"

本次新增**有界滚动摘要层**:旧 turn 被 short_term cap 挤出窗口时,
**有界重压缩**进单个 ``summary_text`` 字段(而非 append),让 prompt 始终能拿到
对该对话历史的语义级浓缩。

# 范围(Phase A 核对结论)

按 ``(user_id, character_id, conversation_id)`` **三级隔离**,**不退**到 (user, char):
- ``eeb427a`` Bug 1 修法的 short_term per-conversation 过滤就是为了防"老对话串新对话"
- summary 若在 (user, char) 范围会让新对话注入老对话摘要,违背 Bug 1 invariant
- 同时与现有 ``delete_conversation`` 硬删 chat_history 的语义对齐(summary 随 conv 走)

# 独立于 memory_extractor_state

本表自带 ``last_folded_chat_history_id`` 列,**完全不读/不写**
``memory_extractor_state``(那个 pointer 对 default 用户卡死在 804,搭车会一起卡死)。

# 表设计

- ``(user_id, character_id, conversation_id)`` UNIQUE — 一个 conv 一行
- ``summary_text TEXT`` — 当前压缩态摘要,**最长 ~ token_budget 个 token**;空摘要 → ''
- ``last_folded_chat_history_id INTEGER`` — 上次折叠覆盖到的 chat_history.id,**fold 前不读不写 memory_extractor_state**
- ``token_budget INTEGER`` — 该 conv 的摘要预算上限,init = config.memory.summary.token_budget
- ``updated_at TIMESTAMP``

# 幂等性

``CREATE TABLE IF NOT EXISTS``;新增列若已存在则跳过(本 migration 首跑创建,
无 alter 模式)。**不动现存 memory / memory_extractor_state / chat_history / users
等任何表**。
"""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy import text

from backend.database import engine

logger = logging.getLogger(__name__)


_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS conversation_summary (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id                     TEXT    NOT NULL,
    character_id                INTEGER,
    conversation_id             INTEGER,
    summary_text                TEXT    NOT NULL DEFAULT '',
    last_folded_chat_history_id INTEGER NOT NULL DEFAULT 0,
    token_budget                INTEGER NOT NULL,
    updated_at                  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, character_id, conversation_id)
)
"""

_CREATE_IDX_SQL = """
CREATE INDEX IF NOT EXISTS idx_conversation_summary_lookup
ON conversation_summary(user_id, character_id, conversation_id)
"""


async def run_migration() -> None:
    async with engine.begin() as conn:
        await conn.execute(text(_CREATE_SQL))
        await conn.execute(text(_CREATE_IDX_SQL))
    logger.info(
        "[v4_0_0_conversation_summary] table conversation_summary "
        "ensured (CREATE IF NOT EXISTS, idempotent)"
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(run_migration())
