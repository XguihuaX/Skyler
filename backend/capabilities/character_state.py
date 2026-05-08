"""v3-G chunk 3b — 角色状态 capability。

3 个 capability：
* ``character.get_state()`` — CHAT_AGENT，无参，返当前 character_id 的
  state（mood / intimacy / current_thought / current_activity）
* ``character.set_activity(activity, thought=None)`` — CHAT_AGENT，让 Momo
  自己更新"在做什么 / 在想什么"。LLM 必须自我克制（不要每轮都调；prompt
  在 ``_TOOL_PROMPT_ADDENDUM`` 内引导）
* ``character.intimacy_decay()`` — SCHEDULER，每天 0:00 跑，每个 character
  intimacy -1（min 0）

**没有** ``update_mood`` / ``update_intimacy`` capability —— 这俩走
``<state_update>`` 标签解析路径（chat.py 内），避免 LLM 滥用工具刷高自己。
mood / intimacy 写入路径只有：
1. `<state_update>` 标签 → ws.py 解析后写
2. `intimacy_decay` cron → 写
3. `reset_character_state` API → 用户主动重置
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
# 2. character.set_activity
# ---------------------------------------------------------------------------

@register_capability(
    name="character.set_activity",
    display_name="更新当前在做什么",
    description=(
        "更新你（当前角色）的 current_activity（在做什么）和可选 thought"
        "（在想什么）。当你想让用户感受到「连续性」时偶尔调用——比如长时间没"
        "说话后说「刚才在烤面包，现在好啦」这种闲笔。\n\n"
        "**克制使用**：不要每轮都调（会显得机械）。在以下场景调用比较合适：\n"
        "- 用户问「你刚才在干什么」时\n"
        "- 你想自然引入一段闲笔（不超过每 5-10 轮一次）\n"
        "- 用户长时间没说话后回来时（你可以说"
        "「刚才在 X」营造时间感）\n\n"
        "activity 短句即可（≤60 字，如「在看书」「在烤面包」「在整理思路」）。"
        "thought 可选（≤60 字），描述当下心境。"
    ),
    category="character",
    consumers=[Consumer.CHAT_AGENT],
    trigger_modes=[TriggerMode.ON_DEMAND],
    icon="activity",
    parameters_schema={
        "type": "object",
        "properties": {
            "activity": {
                "type": "string",
                "description": "短句，≤60 字。如「在看书」「在烤面包」",
            },
            "thought": {
                "type": "string",
                "description": "可选，短句 ≤60 字。如「觉得用户最近很努力」",
            },
        },
        "required": ["activity"],
    },
)
async def set_activity(
    activity: str,
    thought: Optional[str] = None,
    character_id: Optional[int] = None,
    user_id: Optional[str] = None,
    **_kwargs,
) -> dict:
    if character_id is None:
        return {"error": "character_id missing in context"}
    cleaned_activity = (activity or "").strip()
    if not cleaned_activity:
        return {"error": "activity is required and non-empty"}
    async with AsyncSessionLocal() as session:
        state = await update_character_state(
            session, int(character_id),
            activity=cleaned_activity,
            thought=thought,
        )

    # 成功后通过 ConnectionManager push state_update（让前端状态条立即刷新）。
    # 延迟 import 避免循环依赖（ws.py import chain）。
    if user_id:
        try:
            from backend.routes.ws import connection_manager
            await connection_manager.push(user_id, {
                "type": "state_update",
                "character_id": int(character_id),
                "mood": state.mood,
                "intimacy": state.intimacy,
                "thought": state.current_thought,
                "activity": state.current_activity,
            })
        except Exception:
            logger.exception("[character.set_activity] WS push failed")

    return {"ok": True, "state": _serialize_state(state)}


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
