"""墓碑 dup-check 助手(v4-beta Stage 2 supersede+墓碑 Phase B).

# 用途

worker(``backend/utils/memory_entry_validator.py::validate_and_filter_entries``)
和 save_memory tool(``backend/agents/chat.py::_tool_save_memory``)在原有
"对比 active memories cosine ≥ dup_threshold" 之外、之前,先调本模块
``is_tombstone_suppressed(content, user_id)``:

  * **精确 content 相等** → 视同被压(用户精确表达过又被删)
  * **cosine ≥ ``_TOMBSTONE_MATCH_THRESHOLD`` (0.92)** → 视同被压(近义)

任一命中 → 调用方跳过该 entry,**不 INSERT memory 表**,log info 留底。

# 与 dup_threshold 的区别

``dup_threshold`` (默认 0.9)是 _活_ memory 间去重(同事实不存两条);
本模块阈值 0.92 是 _墓碑_ 与新 candidate 间的压制阈值(略高,因为墓碑的代价
是"用户明确不要这条",误压一条新事实比误存一条重复更糟)。

# 与 expires_at 的边界

墓碑表只存 ``expires_at IS NULL`` 那批("持久事实"),写入由
``services.delete_memory`` 守门。本模块**不读/不写** ``expires_at`` 任何字段;
只读 ``memory_tombstone`` 表自己的 (content, embedding, user_id)。

# 范围

按 ``user_id`` scope(墓碑跨 character:用户在 Momo 下删的,八重也不该再加)。
不按 character_id 过滤。
"""
from __future__ import annotations

import logging
from typing import Optional

import numpy as np
from sqlalchemy import text

from backend.database import engine
from backend.memory.long_term import _cosine, _encode

logger = logging.getLogger(__name__)


#: 墓碑 cosine 匹配阈值。高于活 memory 的 ``dup_threshold=0.9``,因为压制墓碑
#: 是"用户明确删过"的强信号,要求新 candidate 与墓碑更接近才认为是同一事实。
_TOMBSTONE_MATCH_THRESHOLD: float = 0.92


async def is_tombstone_suppressed(content: str, user_id: str) -> bool:
    """检查 (content, user_id) 是否被已删事实墓碑命中。

    匹配规则(任一命中即返 True):
      1. 与某条墓碑行 ``content`` **精确字符串相等**(strip 后)
      2. 否则,若双方都有 embedding,**cosine ≥ 0.92** → 视同同一事实

    Returns:
        True  → 调用方应跳过本 entry,不写 memory 表
        False → 通过,继续走原有 dup-vs-active-memories 检查

    任何 DB / encode 异常 → 返 False(fail-open,不阻塞写入;log 留底)。
    """
    if not content:
        return False
    needle = content.strip()
    if not needle:
        return False

    try:
        async with engine.begin() as conn:
            rows = (await conn.execute(text(
                "SELECT content, embedding FROM memory_tombstone "
                "WHERE user_id = :u"
            ), {"u": user_id})).fetchall()
    except Exception:
        logger.exception(
            "[tombstone] fetch failed user=%s — treating as not-suppressed",
            user_id,
        )
        return False

    if not rows:
        return False

    # 第 1 道:精确 content 相等(快路径,无 encode 开销)
    for r in rows:
        ex_content = (r[0] or "").strip()
        if ex_content and ex_content == needle:
            logger.info(
                "[tombstone] exact match suppress user=%s preview=%r",
                user_id, needle[:80],
            )
            return True

    # 第 2 道:cosine ≥ 0.92(需双方都有 embedding)
    try:
        new_vec = await _encode(needle)
    except Exception:
        logger.exception(
            "[tombstone] encode candidate failed user=%s — skip cosine check",
            user_id,
        )
        return False

    for r in rows:
        emb_blob: Optional[bytes] = r[1]
        if not emb_blob:
            continue
        try:
            ex_vec = np.frombuffer(emb_blob, dtype=np.float32)
            if _cosine(new_vec, ex_vec) >= _TOMBSTONE_MATCH_THRESHOLD:
                logger.info(
                    "[tombstone] cosine match suppress user=%s "
                    "threshold=%.2f preview=%r",
                    user_id, _TOMBSTONE_MATCH_THRESHOLD, needle[:80],
                )
                return True
        except Exception:
            logger.exception(
                "[tombstone] cosine compare failed user=%s — continue scan",
                user_id,
            )
            continue

    return False


__all__ = [
    "is_tombstone_suppressed",
    "_TOMBSTONE_MATCH_THRESHOLD",
]
