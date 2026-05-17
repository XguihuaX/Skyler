"""v4.0.0 — memory_tombstone 表(删过的"持久事实"不再被重抽).

# 背景

Phase A 勘察实锤(/tmp/audit_z5 / Stage 2 第四刀 supersede+墓碑 Phase A):
- 删 memory 行 = 硬删,**0 墓碑 / 0 排除清单 / 0 blacklist**
- worker 与 save_memory tool 的 cosine dup-check 比对源都是 ``get_all_memories(active_only=True)``
- → 已删的行根本不在比对池里 → 用户再随口提同一事实,extractor 重抽,人工删不稳

本表是"删过的持久事实"墓碑:用户硬删一条 memory 行时,**如果该行是持久事实**
(``expires_at IS NULL``,见 ORM 注释"NULL = permanent;set for transient states"),
就把 (user_id, content, embedding, character_id) 复制一行进本表。后续 dup-check
**额外比对墓碑**:精确 content 相等 → 直接压;或 cosine ≥ 0.92 → 压。

# 范围

仅按 ``user_id`` 隔离(与现 dup-check 同 scope);``character_id`` 仅作 audit
metadata 不参与匹配(墓碑跨角色:用户在 Momo 下删的事实,八重那边也不该重抽)。

# 与 expires_at 的边界

**本刀绝不写/改 expires_at**,只读其 NULL-ness 决定写不写墓碑。
- expires_at IS NULL → 持久事实 → 删 + 写墓碑(防重抽)
- expires_at 有值 → 时效性提醒 → 不写墓碑,照常硬删
  (这种条目召回侧已按 ``active_only=True`` 自动过滤;不需要再用墓碑挡)

# 与 supersede 的边界

**本刀不实现 supersede**(supersede 用 expires_at 软失效是后续刀)。
本表只防"硬删后重抽",不动 supersede 机制。

# 幂等

CREATE TABLE IF NOT EXISTS + CREATE INDEX IF NOT EXISTS;不动现存 memory /
memory_extractor_state / conversation_summary / chat_history / users 等表。
"""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy import text

from backend.database import engine

logger = logging.getLogger(__name__)


_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS memory_tombstone (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      TEXT NOT NULL,
    content      TEXT NOT NULL,
    embedding    BLOB,
    character_id INTEGER,
    deleted_at   DATETIME DEFAULT CURRENT_TIMESTAMP
)
"""

_CREATE_IDX_SQL = """
CREATE INDEX IF NOT EXISTS idx_memory_tombstone_user
ON memory_tombstone(user_id)
"""


async def run_migration() -> None:
    async with engine.begin() as conn:
        await conn.execute(text(_CREATE_SQL))
        await conn.execute(text(_CREATE_IDX_SQL))
    logger.info(
        "[v4_0_0_memory_tombstone] table memory_tombstone "
        "ensured (CREATE IF NOT EXISTS, idempotent)"
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(run_migration())
