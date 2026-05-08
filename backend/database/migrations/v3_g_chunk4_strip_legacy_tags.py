"""V3-G chunk 4 部分 D-3 — 一次性扫 chat_history 全表，剥离历史 LLM 标签
脏数据。

# 背景

v3-D / v3-F / v3-G chunk 3b 引入的 ``<emotion>`` / ``<thinking>`` /
``<state_update>`` 标签在各自 chunk 落地时都加了流式 + 写库前 strip，但
**之前**入库的历史行可能还含原始标签（chunk 2.6 footgun 教训：单道剥离
有边界漏网）。这些行进 profile_summary 重写时会污染用户画像。

本 migration 一次性扫表 + 剥离 + 写回。**幂等**：每行检查是否含任一标签，
不含则跳过，避免无意义 UPDATE。

# 处理范围

* ``<thinking>...</thinking>`` 完整对（``utils.text_filters.strip_thinking``）
* ``<state_update ... />`` 自闭合 + 容错变体（``strip_state_update``）
* ``<emotion>X</emotion>`` 单标签（自实现简单 regex）

不处理 ``<motion>`` —— per-segment 标签，用户视角已经被 ``_parse_motion``
按段剥离；任何残骸用户已经看见过了，留着不污染下游。

# 执行时机

lifespan 启动时跑一次。后续重启行已无标签，规则跳过零开销。
"""
import asyncio
import logging
import re

from sqlalchemy import text

from backend.database import engine
from backend.utils.text_filters import strip_state_update, strip_thinking

logger = logging.getLogger(__name__)


_EMOTION_TAG_RE = re.compile(r"<emotion>[^<]*</emotion>", re.IGNORECASE)


def _has_any_tag(content: str) -> bool:
    if not content:
        return False
    if "<emotion>" in content.lower():
        return True
    if "<thinking>" in content.lower():
        return True
    if "<state_update" in content.lower():
        return True
    return False


def _scrub(content: str) -> str:
    out = strip_thinking(content)
    out = strip_state_update(out)
    out = _EMOTION_TAG_RE.sub("", out)
    # 多余前导 / 尾随空白合并
    return out.strip()


async def run_migration() -> None:
    """V3-G chunk 4 D-3 主迁移。幂等：仅扫含标签的行。"""
    async with engine.begin() as conn:
        # 先用 LIKE 粗筛，避免全表 Python 端比对（百万行场景仍可接受）
        rows = (await conn.execute(text(
            "SELECT id, content FROM chat_history "
            "WHERE content LIKE '%<emotion>%' "
            "   OR content LIKE '%<thinking>%' "
            "   OR content LIKE '%<state_update%'"
        ))).fetchall()

        scrubbed = 0
        skipped_no_change = 0
        for row in rows:
            row_id = row[0]
            old_content = row[1] or ""
            if not _has_any_tag(old_content):
                continue  # 应不会命中（LIKE 已筛过），保险
            new_content = _scrub(old_content)
            if new_content == old_content:
                skipped_no_change += 1
                continue  # regex 不匹配（极端：``<thinking>`` 在变量名里之类）
            await conn.execute(
                text(
                    "UPDATE chat_history SET content = :c WHERE id = :i"
                ),
                {"c": new_content, "i": row_id},
            )
            scrubbed += 1

        logger.info(
            "V3-G-chunk4 D-3: chat_history 标签剥离完成 "
            "candidates=%d scrubbed=%d unchanged=%d",
            len(rows), scrubbed, skipped_no_change,
        )

    logger.info("V3-G chunk 4 D-3 migration done")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    asyncio.run(run_migration())
