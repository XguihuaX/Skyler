"""Bugfix-3.4 — voice_aliases 表 + 从 characters 自动 seed 友好名。

复刻 voice 的 raw id 是 ``cosyvoice-v3.5-plus-bailian-<32hex>``,无意义。
本 stage 加 voice_aliases 表存 voice_id → display_name 映射, 让 UI 在
gallery / dropdown / picker 都用友好名显示。

Schema
------
voice_aliases:
  - voice_id    TEXT PRIMARY KEY        — DashScope voice id (任意 string,
                                          含系统 longxxx_v3 / 复刻 cosyvoice-* )
  - display_name TEXT NOT NULL          — 用户起的友好名
  - created_at  TIMESTAMP DEFAULT now
  - updated_at  TIMESTAMP DEFAULT now

Auto-seed
---------
跑 migration 时反查 characters.voice_model JSON:任一角色绑了 cloned voice
(以 ``cosyvoice-v3.5-plus-bailian-`` 前缀判)→ INSERT alias ``<角色名> voice``
(eg "八重神子 voice")。**INSERT OR IGNORE** 保不覆盖用户已自定义的 alias。

幂等
----
- ``CREATE TABLE IF NOT EXISTS``
- seed 用 ``INSERT OR IGNORE`` (PK 已存在 = 跳过)
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from sqlalchemy import text

from backend.database import engine

logger = logging.getLogger(__name__)


_CLONED_VOICE_PREFIX = "cosyvoice-v3.5-plus-bailian-"


def _parse_voice_id(vm_str: Optional[str]) -> Optional[str]:
    if not vm_str:
        return None
    try:
        data = json.loads(vm_str)
        if isinstance(data, dict):
            v = data.get("voice")
            return v if isinstance(v, str) and v else None
    except json.JSONDecodeError:
        return None
    return None


async def run_migration() -> None:
    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA foreign_keys = ON"))

        # ---- 1. CREATE TABLE IF NOT EXISTS ----
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS voice_aliases (
                voice_id     TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        logger.info("[bugfix-3.4] voice_aliases table ensured")

        # ---- 2. auto-seed from characters.voice_model ----
        # 反查每个角色绑的 cloned voice,INSERT OR IGNORE 友好名 "<name> voice"
        # 仅 cloned voice (cosyvoice-v3.5-plus-bailian-* 前缀) 自动 seed;
        # 系统 longxxx 默认 fallback 走 yaml available_voices.label,不在此 seed。
        rows = (await conn.execute(text(
            "SELECT id, name, voice_model FROM characters "
            "WHERE voice_model IS NOT NULL"
        ))).fetchall()
        seeded = 0
        for row in rows:
            cid, cname, vm_str = row[0], row[1], row[2]
            voice_id = _parse_voice_id(vm_str)
            if not voice_id or not voice_id.startswith(_CLONED_VOICE_PREFIX):
                continue
            default_alias = f"{cname} voice"
            result = await conn.execute(text("""
                INSERT OR IGNORE INTO voice_aliases (voice_id, display_name)
                VALUES (:vid, :name)
            """), {"vid": voice_id, "name": default_alias})
            inserted = getattr(result, "rowcount", 0) or 0
            if inserted > 0:
                logger.info(
                    "[bugfix-3.4] seeded alias %r → %r (from character id=%s)",
                    voice_id, default_alias, cid,
                )
                seeded += 1

        logger.info(
            "[bugfix-3.4] auto-seed done: %d new alias(es) (existing kept)",
            seeded,
        )


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    asyncio.run(run_migration())
