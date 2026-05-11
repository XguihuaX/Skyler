"""V3.5 chunk 9 Part 4 — memory 表加 forgetting curve 元数据。

新加 2 个 column 到 ``memory`` 表：

* ``access_count`` INTEGER DEFAULT 0    —— 累计被 top-k 召回次数（每次召
  回 ``UPDATE access_count = access_count + 1``）
* ``last_accessed_at`` TIMESTAMP        —— 最近被召回时间；初始化为
  ``created_at``（"老 entry 但从未访问"的衰减从创建时间起算）

# Score 公式（``backend/memory/long_term.py`` 实现）

  score = relevance * (1 + log(1 + access_count)) / (1 + age_days * decay)

* ``relevance``           cosine 相似度（0-1）
* ``access_count``        命中频繁加权（log 渐进，不让爆款 entry 永久霸榜）
* ``age_days``            ``(now - last_accessed_at).days``
* ``decay``               config ``memory.forgetting_curve.age_decay_factor``
                          默认 0.01（每天衰减 1%）

# Threshold

config ``memory.forgetting_curve.threshold``（默认 0.3）—— score < 阈值
的 entry 不进 top-k 返回（保留在 DB，可被 UI 删 / 编辑 / 后续召回上来）。

# 幂等

``PRAGMA table_info(memory)`` 检测 column 是否已存在，仅缺失则 ``ALTER
TABLE ADD COLUMN``。SQLite ``ADD COLUMN`` 不支持 ``IF NOT EXISTS``，但
我们前置 PRAGMA 检查（chunk 6b hotfix-3 migration 同 pattern）。

初始化 ``last_accessed_at = created_at`` 用一条 ``UPDATE WHERE
last_accessed_at IS NULL``，二次跑空回写 0 行，自然幂等。
"""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy import text

from backend.database import engine

logger = logging.getLogger(__name__)


async def _column_exists(conn, table: str, column: str) -> bool:
    rows = (await conn.execute(text(f"PRAGMA table_info({table})"))).fetchall()
    return any(r[1] == column for r in rows)


async def run_migration() -> None:
    """V3.5 chunk 9 Part 4 主迁移。幂等。"""
    async with engine.begin() as conn:
        # 1. access_count
        if not await _column_exists(conn, "memory", "access_count"):
            await conn.execute(text(
                "ALTER TABLE memory ADD COLUMN access_count INTEGER DEFAULT 0"
            ))
            logger.info(
                "V3.5-chunk9: memory.access_count 列已加（DEFAULT 0）"
            )
        else:
            logger.info("V3.5-chunk9: memory.access_count 已存在，跳过")

        # 2. last_accessed_at
        if not await _column_exists(conn, "memory", "last_accessed_at"):
            await conn.execute(text(
                "ALTER TABLE memory ADD COLUMN last_accessed_at TIMESTAMP"
            ))
            logger.info(
                "V3.5-chunk9: memory.last_accessed_at 列已加"
            )
        else:
            logger.info("V3.5-chunk9: memory.last_accessed_at 已存在，跳过")

        # 3. 老 entry 初始化 last_accessed_at = created_at
        # 幂等：仅 ``WHERE last_accessed_at IS NULL`` 的行被回填；二次跑 0 影响
        result = await conn.execute(text(
            "UPDATE memory SET last_accessed_at = created_at "
            "WHERE last_accessed_at IS NULL"
        ))
        affected = getattr(result, "rowcount", 0) or 0
        logger.info(
            "V3.5-chunk9: 回填 last_accessed_at = created_at "
            "（影响 %d 行；二次跑应为 0）",
            affected,
        )

    logger.info("V3.5 chunk 9 Part 4 migration done")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    asyncio.run(run_migration())
