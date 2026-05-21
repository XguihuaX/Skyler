"""v3-G chunk 3b — 角色状态 capability。

2 个 capability(2026-05-21 退役 set_activity 后):
* ``character.get_state()`` — CHAT_AGENT，无参，返当前 character_id 的
  state（mood / intimacy / current_thought / current_activity）
* ``character.intimacy_decay()`` — SCHEDULER，每天 0:00 跑，每个 character
  intimacy -1（min 0）

**没有** ``set_activity`` / ``update_mood`` / ``update_intimacy`` capability
—— 全走 ``<state_update activity="..." thought="..." mood="..." intimacy_delta="..." />``
标签解析路径(chat.py:219-260 _parse_state_update + ws.py _apply_and_push_state_update),
避免 LLM 滥用工具刷高自己 / 每轮机械更新。
mood / intimacy / activity / thought 写入路径只有：
1. `<state_update>` 标签 → ws.py 解析后写(LLM 主路径)
2. `intimacy_decay` cron → 写(每日衰减)
3. `reset_character_state` API → 用户主动重置

INV-6 §1 P3 (2026-05-21):character.set_activity cap 退役,功能 100% 由
<state_update activity=... /> tag 路径承接;详 INV-6 §1。
"""
from __future__ import annotations

import logging
from typing import Optional

from backend.capabilities import Consumer, TriggerMode, register_capability
from backend.database import AsyncSessionLocal
from backend.database.services import (
    INTIMACY_MIN,
    get_or_create_character_state,
    list_state_character_ids,
    update_character_state,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. character.get_state
# ---------------------------------------------------------------------------

@register_capability(
    name="character.get_state",
    display_name="查看当前角色状态",
    description=(
        "查看你（当前角色）此刻的 mood / intimacy / current_thought / "
        "current_activity。当用户问「你最近怎么样」「在干什么」「你状态如何」"
        "等关心你近况的话时调用。返回 dict，所有字段有合理默认。"
    ),
    category="character",
    consumers=[Consumer.CHAT_AGENT],
    trigger_modes=[TriggerMode.ON_DEMAND],
    icon="heart",
    parameters_schema={"type": "object", "properties": {}, "required": []},
)
async def get_state(character_id: Optional[int] = None, **_kwargs) -> dict:
    """``character_id`` 由 ChatAgent 从 turn payload 自动注入；用户不传。"""
    if character_id is None:
        return {"error": "character_id missing in context"}
    async with AsyncSessionLocal() as session:
        state = await get_or_create_character_state(session, int(character_id))
    return _serialize_state(state)


# ---------------------------------------------------------------------------
# 2. character.set_activity — 2026-05-21 退役 (INV-6 §1 P3)
# 改走 <state_update activity="..." thought="..." /> inline tag 路径
# (chat.py:219-260 _parse_state_update + ws.py _apply_and_push_state_update),
# 100% 功能重叠且 tag 多支持 mood/intimacy_delta。
# 历史 commit 可追溯;handler / decorator 整段 75 行删除。
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 3. character.intimacy_decay (SCHEDULER)
# ---------------------------------------------------------------------------

@register_capability(
    name="character.intimacy_decay",
    display_name="每日亲密度衰减",
    description=(
        "（SCHEDULER）每天 0:00 自动调用：每个 character 的 intimacy 自减 1，"
        "下界 0。让长期不互动的关系慢慢冷淡，重新互动时升回来。"
        "用户不直接调；ChatAgent 也不调（不是 CHAT_AGENT consumer）。"
    ),
    category="character",
    consumers=[Consumer.SCHEDULER],
    trigger_modes=[TriggerMode.SCHEDULED],
    icon="trending-down",
    user_visible=False,
    parameters_schema={"type": "object", "properties": {}, "required": []},
)
async def intimacy_decay(**_kwargs) -> dict:
    """遍历所有 character 各自 -1。返回 ``{decayed_count}``。"""
    decayed = 0
    async with AsyncSessionLocal() as session:
        char_ids = await list_state_character_ids(session)

    for cid in char_ids:
        try:
            async with AsyncSessionLocal() as session:
                state = await get_or_create_character_state(session, cid)
                if state.intimacy > INTIMACY_MIN:
                    await update_character_state(
                        session, cid, intimacy_delta=-1,
                    )
                    decayed += 1
        except Exception:
            logger.exception(
                "[intimacy_decay] failed for character_id=%s", cid,
            )

    logger.info("[intimacy_decay] decayed=%d total chars=%d", decayed, len(char_ids))
    return {"decayed_count": decayed, "total_chars": len(char_ids)}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _serialize_state(state) -> dict:
    return {
        "character_id": state.character_id,
        "mood": state.mood,
        "intimacy": state.intimacy,
        "thought": state.current_thought,
        "activity": state.current_activity,
        "last_interaction_at": state.last_interaction_at.isoformat()
            if state.last_interaction_at else None,
        "updated_at": state.updated_at.isoformat() if state.updated_at else None,
    }
