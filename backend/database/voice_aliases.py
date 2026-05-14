"""Bugfix-3.4 — voice_aliases DB service。

Schema 见 migrations/bugfix_3_4_voice_aliases.py。本 module 提供 4 个 async
CRUD helper + 一个 ``resolve_display_name(voice_id, fallback)`` 用作所有
"显示这个 voice 友好名"路径的入口。
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import text

from backend.database import engine

logger = logging.getLogger(__name__)


async def list_aliases() -> dict[str, str]:
    """返回 ``{voice_id: display_name}`` map (全表)。"""
    async with engine.begin() as conn:
        rows = (await conn.execute(text(
            "SELECT voice_id, display_name FROM voice_aliases"
        ))).fetchall()
    return {r[0]: r[1] for r in rows}


async def get_alias(voice_id: str) -> Optional[str]:
    """单查;不存在 → None。"""
    async with engine.begin() as conn:
        row = (await conn.execute(
            text("SELECT display_name FROM voice_aliases WHERE voice_id = :v"),
            {"v": voice_id},
        )).first()
    return row[0] if row else None


async def set_alias(voice_id: str, display_name: str) -> None:
    """Upsert。``display_name`` 非空,空 / 仅空白 → 等价 delete_alias。"""
    if not display_name or not display_name.strip():
        await delete_alias(voice_id)
        return
    async with engine.begin() as conn:
        await conn.execute(text("""
            INSERT INTO voice_aliases (voice_id, display_name, updated_at)
            VALUES (:v, :n, CURRENT_TIMESTAMP)
            ON CONFLICT(voice_id) DO UPDATE SET
                display_name = excluded.display_name,
                updated_at = CURRENT_TIMESTAMP
        """), {"v": voice_id, "n": display_name.strip()})


async def delete_alias(voice_id: str) -> int:
    """删 alias。返回 row count (0/1)。下次 UI 走 fallback。"""
    async with engine.begin() as conn:
        result = await conn.execute(
            text("DELETE FROM voice_aliases WHERE voice_id = :v"),
            {"v": voice_id},
        )
    return getattr(result, "rowcount", 0) or 0


def resolve_display_name_sync(
    voice_id: str, alias_map: dict[str, str], fallback: Optional[str] = None,
) -> str:
    """**同步**版本: caller 提前批量 ``await list_aliases()`` 后, 这里
    O(1) 查 + fallback。fallback 优先级:alias > caller-provided > raw voice_id 截断。
    """
    alias = alias_map.get(voice_id)
    if alias:
        return alias
    if fallback:
        return fallback
    if len(voice_id) > 28:
        return voice_id[:24] + "…"
    return voice_id
