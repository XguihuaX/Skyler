"""加载 active persona variant 与 character_states 到 LoadedPersona / LoadedState。

renderer 不直接读 DB,通过本模块拿 dataclass。json 字段在这里 ``json.loads``
解析,模板侧拿到的就是 dict / list / None,不再二次 parse。

Phase 0 audit 已 confirm:
  * ``AsyncSessionLocal`` 在 ``backend/database/__init__.py``(spec 写的
    ``backend/database/session`` 是错的,已修正)
  * ``Character`` / ``CharacterPersona`` / ``CharacterState`` 三张表在
    ``backend/database/models.py``
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from sqlalchemy import select

from backend.database import AsyncSessionLocal
from backend.database.models import CharacterPersona, CharacterState

logger = logging.getLogger(__name__)


@dataclass
class LoadedPersona:
    character_id: int
    variant_name: str

    # Tier-1 必填(已 json.loads)
    identity: Dict[str, Any]
    personality_core: Dict[str, Any]
    speech_style: Dict[str, Any]
    signature_phrases: List[Any]
    voice_samples: List[Dict[str, Any]]
    forbidden_phrases: Dict[str, List[str]]
    relationship_to_user: Dict[str, Any]

    # Tier-2 可选(json.loads or None)
    # 注:实际 schema = {"hard_no": [{topic, her_reaction}], "soft_no": [...]} dict,
    # 旧注解 List[str] 类型漂移已修(Persona v2 D)· 模板 layer_c_stable.j2:75-90
    # 按 dict 读 .hard_no / .soft_no(loose typing 实测一直 work)。
    taboo_topics: Optional[Dict[str, Any]] = None
    lore: Optional[Dict[str, Any]] = None
    capability_overrides: Optional[Dict[str, Any]] = None
    style_preset: str = "anime_classic"
    # Persona v2 Slice 1:'社交' | '助手' · gate 元数据,不进 prompt
    card_type: str = "社交"


@dataclass
class LoadedState:
    """精简 view of ``character_states``,供 layer_c.j2 C4 段渲染。

    没有匹配行 / character_id is None 时由 ``_default_state()`` 兜底,
    避免模板 KeyError 阻塞主对话。
    """
    mood: str = "neutral"
    intimacy: int = 0
    activity: Optional[str] = None
    current_thought: Optional[str] = None


def _default_state() -> LoadedState:
    return LoadedState()


def _safe_json_loads(value: Optional[str], default: Any) -> Any:
    """Tier-2 可选字段:NULL / 空串 / 解析失败 → default 兜底。"""
    if not value:
        return default
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        logger.warning(
            "[persona_loader] json parse failed for value=%r, falling back",
            value[:80] if isinstance(value, str) else value,
        )
        return default


async def load_active_persona(character_id: int) -> LoadedPersona:
    """按 ``character_id`` 找 ``is_active=1`` 的 variant 行。

    Raises:
        RuntimeError: 没找到 active variant —— 调用方应自行兜底(eg 回退到
            旧 ``characters.persona`` 文本 + ``BASE_INSTRUCTION``)。
    """
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(CharacterPersona).where(
                CharacterPersona.character_id == character_id,
                CharacterPersona.is_active == True,  # noqa: E712
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            raise RuntimeError(
                f"No active persona for character_id={character_id}; "
                "did migration v4_persona_thickening_segment1 run?"
            )

        # Tier-1 必填:解析失败应被视为数据脏(migration 写错),raise 让上游
        # logger.exception 暴露。
        try:
            identity             = json.loads(row.identity)
            personality_core     = json.loads(row.personality_core)
            speech_style         = json.loads(row.speech_style)
            signature_phrases    = json.loads(row.signature_phrases)
            voice_samples        = json.loads(row.voice_samples)
            forbidden_phrases    = json.loads(row.forbidden_phrases)
            relationship_to_user = json.loads(row.relationship_to_user)
        except json.JSONDecodeError as exc:
            logger.exception(
                "[persona_loader] Tier-1 json parse failed for "
                "character_id=%s variant=%s", character_id, row.variant_name,
            )
            raise RuntimeError(
                f"Persona data corrupt for character_id={character_id}: {exc}"
            )

        return LoadedPersona(
            character_id=row.character_id,
            variant_name=row.variant_name,
            identity=identity,
            personality_core=personality_core,
            speech_style=speech_style,
            signature_phrases=signature_phrases,
            voice_samples=voice_samples,
            forbidden_phrases=forbidden_phrases,
            relationship_to_user=relationship_to_user,
            taboo_topics=_safe_json_loads(row.taboo_topics, None),
            lore=_safe_json_loads(row.lore, None),
            capability_overrides=_safe_json_loads(row.capability_overrides, None),
            style_preset=row.style_preset or "anime_classic",
            card_type=row.card_type or "社交",
        )


async def load_character_state(character_id: Optional[int]) -> LoadedState:
    """读 ``character_states`` 当前行;无 character_id / 无对应行 → 默认值。

    D-3 sign-off:12 行孤儿 state 不在本 segment 处理。如 character_id 对应
    孤儿行(``characters`` 表无此 id 但 ``character_states`` 有)—— **会按
    孤儿行的实际值返回**(不刻意过滤;FK 约束未加,本模块不该做 cleanup 决策)。
    """
    if character_id is None:
        return _default_state()
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(CharacterState).where(
                    CharacterState.character_id == character_id
                )
            )
            row = result.scalar_one_or_none()
            if row is None:
                return _default_state()
            return LoadedState(
                mood=row.mood or "neutral",
                intimacy=int(row.intimacy or 0),
                activity=row.current_activity,
                current_thought=row.current_thought,
            )
    except Exception:
        logger.exception(
            "[persona_loader] load_character_state failed character_id=%s",
            character_id,
        )
        return _default_state()
