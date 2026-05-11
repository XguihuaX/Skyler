"""V3.5 chunk 6b hotfix-3 — 一次性清存量污染。

# 背景

hotfix-1/2 修了 4 个场景 capability 的 fall-through bug；hotfix-3 又发现
Qwen 偶发把 ``capability name`` 当 XML 标签直接打到 ``delta.content``：

    <netease.daily_recommend>
    </netease.daily_recommend>

chunk 4 resilience 三条 fallback regex 全不命中 → 字面文本进
``chat_history`` / ``memory`` / ``users.profile_summary`` → 下一轮 LLM
in-context learning 自循环。

hotfix-3 已在源头加 ``SUSPICIOUS_TAG_RE`` + resilience 第 4 种 fallback +
strip 4 道防线第 4 种 pattern 的"未来污染防御"。本 migration 处理**已经
入库**的脏数据。

# 处理范围

1. ``chat_history`` —— 仅 ``role='assistant'`` 行（``role='user'`` 用户原文
   可能正经发 HTML / code，不动）。SUSPICIOUS_TAG_RE 命中即剥。
2. ``memory.content`` —— 全表（``role`` 列允许 user / system 但都是
   memory.py 生成的内部文本，非用户原文，可安全剥）。
3. ``users.profile_summary`` —— SUSPICIOUS_TAG_RE 命中 **>= 3** 处 → 整段
   ``SET NULL``（污染严重，重生比修补稳）；< 3 处则就地剥。

# 备份

跑前自动 ``shutil.copyfile`` 备份 ``momoos.db`` 到
``momoos.db.backup-before-hotfix3``。已存在则跳过（幂等：二次跑不覆盖
首次备份，避免连续多跑造成首次备份被脏数据覆盖丢失）。

# 幂等

每次跑前都先扫表，**只对仍含 SUSPICIOUS_TAG_RE 命中的行 UPDATE**。第二次
跑 candidates = 0 → scrubbed = 0，自然幂等。
"""
from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path
from typing import Optional

from sqlalchemy import text

from backend.database import engine
from backend.utils.text_filters import (
    SUSPICIOUS_TAG_RE,
    count_suspicious_tags,
    sanitize_suspicious_tags,
)

logger = logging.getLogger(__name__)

_BACKUP_SUFFIX = ".backup-before-hotfix3"
_PROFILE_NUKE_THRESHOLD = 3  # >= N 命中 → SET NULL（污染严重重生）


def _resolve_db_path() -> Optional[Path]:
    """从 engine URL 解析 SQLite 文件路径。非 SQLite / 内存 DB 返 None。"""
    try:
        url = engine.url
    except Exception:
        return None
    if (url.get_backend_name() or "").lower() != "sqlite":
        return None
    db = url.database
    if not db or db == ":memory:":
        return None
    return Path(db).resolve()


def _maybe_backup_db() -> Optional[Path]:
    """跑前备份 momoos.db；已存在备份 → 跳过（幂等）。"""
    src = _resolve_db_path()
    if src is None:
        logger.info("V3.5-chunk6b-hotfix3: non-sqlite or memory DB, skip backup")
        return None
    if not src.exists():
        logger.info("V3.5-chunk6b-hotfix3: DB file %s not found, skip backup", src)
        return None
    dst = src.with_name(src.name + _BACKUP_SUFFIX)
    if dst.exists():
        logger.info(
            "V3.5-chunk6b-hotfix3: backup already at %s, skip (idempotent)",
            dst,
        )
        return dst
    shutil.copyfile(src, dst)
    logger.info("V3.5-chunk6b-hotfix3: DB backed up %s -> %s", src, dst)
    return dst


async def _scrub_chat_history(conn) -> tuple[int, int]:
    """剥 ``role='assistant'`` 行的 SUSPICIOUS_TAG_RE 命中。返 (candidates, scrubbed)。"""
    # LIKE 粗筛：含 ``</`` 或 ``/>`` 的行候选；Python 端 regex 精筛。
    # 全表 Python regex 在百万行规模不可接受，但 hotfix 期间用户 DB 几十万级
    # 完全可受 —— 仍用 LIKE 粗筛减负。
    rows = (await conn.execute(text(
        "SELECT id, content FROM chat_history "
        "WHERE role = 'assistant' "
        "  AND content IS NOT NULL "
        "  AND (content LIKE '%</%' OR content LIKE '%/>%')"
    ))).fetchall()
    scrubbed = 0
    for row in rows:
        row_id = row[0]
        old = row[1] or ""
        if not SUSPICIOUS_TAG_RE.search(old):
            continue
        new = sanitize_suspicious_tags(old).strip()
        if new == old:
            continue
        await conn.execute(
            text("UPDATE chat_history SET content = :c WHERE id = :i"),
            {"c": new, "i": row_id},
        )
        scrubbed += 1
    return len(rows), scrubbed


async def _scrub_memory(conn) -> tuple[int, int]:
    """剥 ``memory.content`` 的 SUSPICIOUS_TAG_RE 命中。返 (candidates, scrubbed)。"""
    rows = (await conn.execute(text(
        "SELECT id, content FROM memory "
        "WHERE content IS NOT NULL "
        "  AND (content LIKE '%</%' OR content LIKE '%/>%')"
    ))).fetchall()
    scrubbed = 0
    for row in rows:
        row_id = row[0]
        old = row[1] or ""
        if not SUSPICIOUS_TAG_RE.search(old):
            continue
        new = sanitize_suspicious_tags(old).strip()
        if new == old:
            continue
        await conn.execute(
            text("UPDATE memory SET content = :c WHERE id = :i"),
            {"c": new, "i": row_id},
        )
        scrubbed += 1
    return len(rows), scrubbed


async def _scrub_profile_summary(conn) -> tuple[int, int, int]:
    """处理 ``users.profile_summary``。

    返 ``(candidates, scrubbed_inline, cleared_to_null)``。
    """
    rows = (await conn.execute(text(
        "SELECT user_id, profile_summary FROM users "
        "WHERE profile_summary IS NOT NULL "
        "  AND (profile_summary LIKE '%</%' OR profile_summary LIKE '%/>%')"
    ))).fetchall()
    scrubbed = 0
    cleared = 0
    for row in rows:
        user_id = row[0]
        old = row[1] or ""
        hit = count_suspicious_tags(old)
        if hit == 0:
            continue
        if hit >= _PROFILE_NUKE_THRESHOLD:
            await conn.execute(
                text("UPDATE users SET profile_summary = NULL WHERE user_id = :u"),
                {"u": user_id},
            )
            cleared += 1
            logger.warning(
                "V3.5-chunk6b-hotfix3: profile_summary cleared user_id=%s "
                "(hit=%d >= threshold=%d)",
                user_id, hit, _PROFILE_NUKE_THRESHOLD,
            )
        else:
            new = sanitize_suspicious_tags(old).strip()
            if new == old:
                continue
            await conn.execute(
                text("UPDATE users SET profile_summary = :s WHERE user_id = :u"),
                {"s": new, "u": user_id},
            )
            scrubbed += 1
    return len(rows), scrubbed, cleared


async def run_migration() -> None:
    """V3.5 chunk 6b hotfix-3 主迁移。幂等。"""
    _maybe_backup_db()

    async with engine.begin() as conn:
        chat_cand, chat_scrub = await _scrub_chat_history(conn)
        mem_cand, mem_scrub = await _scrub_memory(conn)
        prof_cand, prof_scrub, prof_clear = await _scrub_profile_summary(conn)

    logger.info(
        "V3.5-chunk6b-hotfix3: chat_history: candidates=%d scrubbed=%d",
        chat_cand, chat_scrub,
    )
    logger.info(
        "V3.5-chunk6b-hotfix3: memory: candidates=%d scrubbed=%d",
        mem_cand, mem_scrub,
    )
    logger.info(
        "V3.5-chunk6b-hotfix3: profile_summary: candidates=%d "
        "scrubbed=%d cleared=%d",
        prof_cand, prof_scrub, prof_clear,
    )
    logger.info("V3.5 chunk 6b hotfix-3 migration done")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    asyncio.run(run_migration())
