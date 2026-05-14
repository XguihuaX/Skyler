"""v4 persona engineering segment 2 — ensure every character has a default
active variant (D-S2-2)。

Segment 1 migration ran when 7 characters existed → seeded 7 default variants.
Any character row inserted **after** Segment 1 ship has no corresponding
``character_personas`` row → renderer path raises ``RuntimeError`` and falls
back to legacy ``prompt_manager`` with a deprecated-warning log.

This migration scans ``characters`` for rows missing an active variant and
seeds an empty Tier-1 default variant for each (identity.name = character.name,
其他字段全 empty / sensible default;identical structure to Segment 1's
``_build_default_seed`` minus the yaml ``default_emotion`` lookup since this
runs purely defensive without yaml dependency)。

幂等:``WHERE NOT EXISTS`` 子句保证已有 default variant 的 character 不被
重复 seed;``character_personas_builtin_seed`` 表也只 INSERT OR REPLACE 当
当前 character 真的新建了行时同步写一份 backup。
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict

from sqlalchemy import text

from backend.database import engine

logger = logging.getLogger(__name__)


def _build_empty_default_seed(char_name: str) -> Dict[str, Any]:
    """Seg-1 ``_build_default_seed`` 的精简版 ── 无 yaml 依赖,所有空字段。

    与 segment 1 builtin_seed shape 完全一致(7 Tier-1 字段),保证后续 restore_to_builtin
    能正确从 seed_data 反序列化。default_emotion 兜底 'calm' 而非 yaml lookup,
    因为本 migration 是**防御性**——targeted at characters created **after** segment-1
    yaml seed snapshot,yaml 里基本不会有匹配项。
    """
    return {
        "identity": {
            "name": char_name,
            "aliases": [],
            "self_reference": "我",
            "age": None,
            "occupation": None,
            "origin": None,
        },
        "personality_core": {
            "core_traits": [],
            "contrasts": [],
            "energy_level": "medium",
            "default_emotion": "calm",
        },
        "speech_style": {
            "vocabulary": "neutral",
            "sentence_rhythm": "medium",
            "user_address": "你",
            "emoji_habit": "rare",
            "punctuation_quirk": "standard",
            "cliche_tolerance": 0.5,
        },
        "signature_phrases": [],
        "voice_samples": [],
        "forbidden_phrases": {
            "_global": ["作为AI", "作为一个助手", "我会尽力", "很抱歉", "请允许我"],
            "_qwen": ["总的来说", "综上所述"],
            "_deepseek": ["我会尽力", "请允许我"],
        },
        "relationship_to_user": {
            "type": "companion",
            "intimacy_progression": "linear",
        },
    }


_FIND_MISSING_SQL = """
SELECT c.id, c.name
FROM characters c
WHERE NOT EXISTS (
    SELECT 1 FROM character_personas cp
    WHERE cp.character_id = c.id
      AND cp.is_active = 1
)
ORDER BY c.id
"""

_INSERT_PERSONA = """
INSERT INTO character_personas (
    character_id, variant_name, is_builtin, is_active, display_order,
    description, identity, personality_core, speech_style,
    signature_phrases, voice_samples, forbidden_phrases,
    relationship_to_user
) VALUES (
    :cid, 'default', 1, 1, 0,
    :desc, :ident, :pcore, :sstyle,
    :sphr, :vsam, :fphr,
    :rel
)
"""

_INSERT_SEED_BACKUP = """
INSERT OR REPLACE INTO character_personas_builtin_seed
(character_id, variant_name, seed_data)
VALUES (:cid, 'default', :sd)
"""


async def run_migration() -> None:
    async with engine.begin() as conn:
        missing = (await conn.execute(text(_FIND_MISSING_SQL))).all()
        if not missing:
            logger.info("[v4_seg2_ensure_defaults] all characters already have active variant")
            return

        seeded = 0
        for char_id, char_name in missing:
            seed = _build_empty_default_seed(char_name or f"char_{char_id}")
            await conn.execute(text(_INSERT_PERSONA), {
                "cid": char_id,
                "desc": "v4 builtin default variant (ensure-defaults backfill)",
                "ident":  json.dumps(seed["identity"],             ensure_ascii=False),
                "pcore":  json.dumps(seed["personality_core"],     ensure_ascii=False),
                "sstyle": json.dumps(seed["speech_style"],         ensure_ascii=False),
                "sphr":   json.dumps(seed["signature_phrases"],    ensure_ascii=False),
                "vsam":   json.dumps(seed["voice_samples"],        ensure_ascii=False),
                "fphr":   json.dumps(seed["forbidden_phrases"],    ensure_ascii=False),
                "rel":    json.dumps(seed["relationship_to_user"], ensure_ascii=False),
            })
            await conn.execute(text(_INSERT_SEED_BACKUP), {
                "cid": char_id,
                "sd": json.dumps(seed, ensure_ascii=False),
            })
            seeded += 1
            logger.info(
                "[v4_seg2_ensure_defaults] backfilled default variant for "
                "character_id=%s name=%s", char_id, char_name,
            )

    logger.info(
        "[v4_seg2_ensure_defaults] backfill complete; rows_added=%d", seeded,
    )


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    asyncio.run(run_migration())
