"""v4 persona engineering segment 1 — character_personas + builtin_seed tables.

新增两张表，并为 ``characters`` 表里现存的每个角色 seed 一行 ``variant_name='default'``：

* ``character_personas``        — 多 variant 主表（一个 character 可有多个 persona variant），
  partial UNIQUE INDEX 保证同 character 同时只有一行 ``is_active=1``。Tier-1
  7 个 JSON 字段必填（identity / personality_core / speech_style /
  signature_phrases / voice_samples / forbidden_phrases / relationship_to_user），
  Tier-2 可选（taboo_topics / lore / capability_overrides / style_preset）。
* ``character_personas_builtin_seed`` — builtin seed 备份表，记录每个 character
  v4 出厂 default variant 的完整 JSON。后续用户编辑 active variant 时这里保留
  原始 fingerprint，可用于"重置成出厂"操作。

幂等：CREATE TABLE / CREATE UNIQUE INDEX 都带 IF NOT EXISTS；seed 阶段先
``SELECT 1 FROM character_personas WHERE character_id=? AND variant_name='default'``
判断，已存在则 skip（log skipped 计数），不存在才 INSERT + 写 seed 备份表。

default_emotion 取数（D-4 sign-off）：v4 起 ``personality_core.default_emotion``
是真相源。本 migration 读旧 ``backend/config/characters.yaml`` 抓 yaml 5 个内
建角色的 ``default_emotion`` 做迁移；id=1（DB ``Momo``）映射到 yaml key ``默认``；
yaml 缺失（如 id=99 ``一般路过猫娘``/id=100 ``祥子-test``）→ ``"calm"`` 兜底。

D-1 sign-off：本 migration 不动 ``_TOOL_PROMPT_ADDENDUM``；那段 prose 在
``backend/agents/prompt/templates/layer_b.j2`` 通过 jinja include 原样嵌入，
Phase 2 完成。

D-3 sign-off：12 行 ``character_states`` 孤儿行不在本 segment 处理，留 v4.1
cleanup migration。
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict

import yaml
from sqlalchemy import text

from backend.database import engine

logger = logging.getLogger(__name__)


# yaml 路径：``<repo>/backend/config/characters.yaml``，相对当前 migrations 文件
# 上两级到 backend 再 + config/。
_YAML_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "characters.yaml"

# DB.characters.name → yaml top-level key 的特殊映射（仅 Momo (id=1) 与 yaml
# key ``默认`` 错位，其他都是同名）。
_YAML_KEY_OVERRIDE_BY_DB_ID: Dict[int, str] = {1: "默认"}


def _load_yaml_emotions() -> Dict[str, str]:
    """读 ``characters.yaml`` 抽 ``{name: default_emotion}`` 映射。

    yaml 缺失 / 解析失败 → 空 dict，下游 fallback ``"calm"``。
    """
    if not _YAML_PATH.exists():
        logger.warning("[v4_persona_seg1] characters.yaml not found at %s", _YAML_PATH)
        return {}
    try:
        data = yaml.safe_load(_YAML_PATH.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        logger.warning("[v4_persona_seg1] yaml parse failed: %s", exc)
        return {}
    out: Dict[str, str] = {}
    for name, cfg in (data.get("characters") or {}).items():
        emo = (cfg or {}).get("default_emotion")
        if isinstance(emo, str) and emo.strip():
            out[name] = emo.strip()
    return out


def _build_default_seed(
    char_id: int, char_name: str, yaml_emotions: Dict[str, str],
) -> Dict[str, Any]:
    """生成单个 character 的 default variant seed dict（7 字段必填 + 元数据）。

    yaml lookup：先查 ``_YAML_KEY_OVERRIDE_BY_DB_ID`` 特殊映射（id=1 → ``默认``），
    再回退到 ``char_name`` 同名查 yaml，最后默认 ``"calm"``。
    """
    yaml_key = _YAML_KEY_OVERRIDE_BY_DB_ID.get(char_id, char_name)
    default_emo = yaml_emotions.get(yaml_key, "calm")
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
            "default_emotion": default_emo,
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


_CREATE_PERSONAS_TABLE = """
CREATE TABLE IF NOT EXISTS character_personas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    character_id INTEGER NOT NULL REFERENCES characters(id) ON DELETE CASCADE,

    variant_name TEXT NOT NULL,
    is_builtin BOOLEAN DEFAULT 0,
    is_active BOOLEAN DEFAULT 0,
    display_order INTEGER DEFAULT 0,
    description TEXT,

    -- Tier 1 必填（JSON，SQLite TEXT 存，Python json.dumps/loads）
    identity TEXT NOT NULL,
    personality_core TEXT NOT NULL,
    speech_style TEXT NOT NULL,
    signature_phrases TEXT NOT NULL,
    voice_samples TEXT NOT NULL,
    forbidden_phrases TEXT NOT NULL,
    relationship_to_user TEXT NOT NULL,

    -- Tier 2 可选
    taboo_topics TEXT,
    lore TEXT,
    capability_overrides TEXT,
    style_preset TEXT DEFAULT 'anime_classic',

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(character_id, variant_name)
)
"""

_CREATE_SEED_BACKUP_TABLE = """
CREATE TABLE IF NOT EXISTS character_personas_builtin_seed (
    character_id INTEGER NOT NULL,
    variant_name TEXT NOT NULL,
    seed_data TEXT NOT NULL,
    PRIMARY KEY(character_id, variant_name)
)
"""

_CREATE_ACTIVE_UNIQUE_INDEX = (
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_persona_active_per_char "
    "ON character_personas(character_id) WHERE is_active = 1"
)

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
    yaml_emotions = _load_yaml_emotions()

    async with engine.begin() as conn:
        await conn.execute(text(_CREATE_PERSONAS_TABLE))
        await conn.execute(text(_CREATE_SEED_BACKUP_TABLE))
        await conn.execute(text(_CREATE_ACTIVE_UNIQUE_INDEX))

        rows = (await conn.execute(text(
            "SELECT id, name FROM characters ORDER BY id"
        ))).all()

        seeded = 0
        skipped = 0
        for char_id, char_name in rows:
            # 存在性检查:看该角色是否已有任意 active variant(语义与 Seg-2
            # ensure_defaults 对齐 · 都用 is_active=1 锚)。
            #
            # 修复历史:原来检查 variant_name='default' · 假设"只有 Seg-1 自己 seed
            # 'default' variant,用户不会自建 active variant"。Persona v2(card_type
            # 上线)+ PersonaEditorModal "新建 variant" 允许用户自定义名字并激活
            # → 假设被打破:若用户给某 cid 建了 variant_name='X'(X != 'default')
            # 且激活,Seg-1 老逻辑视为"无 default"会强插新 'default' is_active=1 行
            # → 撞 partial UNIQUE INDEX idx_persona_active_per_char(WHERE is_active=1)
            # → IntegrityError: UNIQUE constraint failed: character_personas.character_id
            # → backend 启动崩。本次改 SELECT 锚定 is_active=1 与语义对齐 + 兜住该场景。
            exists = (await conn.execute(
                text(
                    "SELECT 1 FROM character_personas "
                    "WHERE character_id = :cid AND is_active = 1"
                ),
                {"cid": char_id},
            )).first()
            if exists:
                skipped += 1
                continue

            seed = _build_default_seed(char_id, char_name, yaml_emotions)
            await conn.execute(text(_INSERT_PERSONA), {
                "cid": char_id,
                "desc": "v4 builtin default variant",
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
        "[v4_persona_seg1] character_personas + builtin_seed ensured; "
        "seeded=%d skipped=%d total_chars=%d",
        seeded, skipped, len(rows),
    )


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    asyncio.run(run_migration())
