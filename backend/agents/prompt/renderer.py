"""v4 segment 1 — 5-layer prompt renderer 主入口。

按 Layer A → B → C → D(→ Transition,可选)顺序渲染 4 个 Jinja 模板,
``"\n\n".join`` 成最终 ``system_prompt`` 字符串。renderer 是**纯函数**:
caller(``backend/agents/chat.py::_build_messages``)负责 gather 一切数据
(profile / activity / memory / extra_system / proactive_briefing / vendor /
motions),renderer 不读 DB(只通过 ``persona_loader`` 取 persona + state)。

Sanitize invariant(A1 sign-off):本模块**不产生**任何会进 LLM 输出契约的
新格式 —— ``<emotion>`` / ``<thinking>`` / ``<motion>`` / ``<state_update />``
全部 paired-tag 形式,与现有 ``backend/agents/chat.py`` 状态机一致。
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

from backend.agents.prompt.briefing_sanitize import validate_and_sanitize_briefing
from backend.agents.prompt.mode import Mode, determine_mode
from backend.agents.prompt.persona_loader import (
    LoadedPersona,
    LoadedState,
    load_active_persona,
    load_character_state,
)

logger = logging.getLogger(__name__)


_TEMPLATES_DIR = Path(__file__).parent / "templates"

# autoescape=False:prompt 是给 LLM 看的纯文本,HTML escape 反而会把
# ``<emotion>`` 误转成 ``&lt;emotion&gt;`` 破坏 sanitize 链路约定。
_jinja_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=select_autoescape(disabled_extensions=("j2",)),
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=False,
)

# 防御性:degenerate thought(全单字符重复,如 60 个 x)直接 None,避免脏数
# 据原文进 prompt。Phase 0 audit §0.3 实测 character_id=304 的 thought
# 就是 60 个 'x',D-3 sign-off 把孤儿清理留 v4.1,本侧只保护 prompt 不被
# 污染。
_DEGENERATE_THOUGHT_RE = re.compile(r"^(.)\1{10,}$")

# 防御性:thought 过长 → 截断 + log。Phase 0 audit 未定上限,200 是与
# state_update 标签里 thought 属性约束(< 50 字)对齐的宽松上限。
_THOUGHT_MAX_LEN = 200


def sanitize_thought(thought: Optional[str]) -> Optional[str]:
    """对 ``LoadedState.current_thought`` 做三道:空 / 过长 / 全同字符 → None / 截断。"""
    if not thought:
        return None
    if _DEGENERATE_THOUGHT_RE.match(thought):
        logger.warning("[layer_c4] thought is degenerate (%d chars same), skipping",
                       len(thought))
        return None
    if len(thought) > _THOUGHT_MAX_LEN:
        logger.warning("[layer_c4] thought too long (%d chars), truncating",
                       len(thought))
        return thought[:_THOUGHT_MAX_LEN] + "..."
    return thought


def _render_layer_a(available_motions: Optional[List[str]]) -> str:
    return _jinja_env.get_template("layer_a.j2").render(
        available_motions=available_motions or [],
    )


def _render_layer_b(
    mode: Mode, tool_prompt_addendum: Optional[str],
) -> str:
    return _jinja_env.get_template("layer_b.j2").render(
        mode=mode,
        tool_prompt_addendum=tool_prompt_addendum,
    )


def _render_layer_c(
    persona: LoadedPersona,
    states: LoadedState,
    safe_thought: Optional[str],
    llm_vendor: str,
) -> str:
    return _jinja_env.get_template("layer_c.j2").render(
        persona=persona,
        states=states,
        safe_thought=safe_thought,
        llm_vendor=llm_vendor,
    )


def _render_layer_d(
    user_profile: Optional[str],
    today_activity: Optional[str],
    long_memory_top5: Optional[List[str]],
    tool_results: Optional[str],
    temp_instructions: Optional[str],
    proactive_briefing: Any,
) -> str:
    return _jinja_env.get_template("layer_d.j2").render(
        user_profile=user_profile,
        today_activity=today_activity,
        long_memory_top5=long_memory_top5 or [],
        tool_results=tool_results,
        temp_instructions=temp_instructions,
        proactive_briefing=proactive_briefing,
    )


def _render_transition(new_variant_name: str) -> str:
    return _jinja_env.get_template("transition.j2").render(
        new_variant_name=new_variant_name,
    )


async def render_system_prompt(
    character_id: Optional[int],
    *,
    turn_origin: str = "user",
    just_switched_variant: bool = False,
    tool_prompt_addendum: Optional[str] = None,
    user_profile: Optional[str] = None,
    today_activity: Optional[str] = None,
    long_memory_top5: Optional[List[str]] = None,
    tool_results: Optional[str] = None,
    temp_instructions: Optional[str] = None,
    proactive_briefing_raw: Optional[Dict[str, Any]] = None,
    available_motions: Optional[List[str]] = None,
    llm_vendor: str = "qwen",
) -> str:
    """渲染 5 层 system prompt。

    Args:
        character_id: 当前角色 id。None → 调用方应在外层 fallback(本函数会
            ``raise RuntimeError``)。
        turn_origin: 见 ``mode.determine_mode`` doc。
        just_switched_variant: 是否刚切 variant,True 时尾部加 transition 段。
        tool_prompt_addendum: D-1 sign-off,原 ``_TOOL_PROMPT_ADDENDUM`` 字符串
            直接传入,本侧不拆分不重构。
        user_profile / today_activity / long_memory_top5 / tool_results /
            temp_instructions / proactive_briefing_raw: 见 Layer D 模板各 if 段。
            None / 空 → 该段跳过渲染。
        available_motions: Layer A 第 3 项注入 Live2D 可用动作清单。
            None / 空 → 不出现该子项。
        llm_vendor: ``"qwen"`` / ``"deepseek"`` / 其他。Layer C 的
            ``forbidden_phrases`` vendor-aware 注入用。

    Returns:
        完整 system prompt 字符串(已 "\n\n".join)。
    """
    if character_id is None:
        # caller 决定 fallback:这里 fast-fail 比静默渲染 default persona 安全
        raise RuntimeError(
            "render_system_prompt requires character_id; caller must fallback"
        )

    mode = determine_mode(turn_origin)
    persona = await load_active_persona(character_id)
    states = await load_character_state(character_id)

    safe_thought = sanitize_thought(states.current_thought)
    briefing = validate_and_sanitize_briefing(proactive_briefing_raw)

    parts: List[str] = [
        _render_layer_a(available_motions),
        _render_layer_b(mode, tool_prompt_addendum),
        _render_layer_c(persona, states, safe_thought, llm_vendor),
        _render_layer_d(
            user_profile, today_activity, long_memory_top5,
            tool_results, temp_instructions, briefing,
        ),
    ]
    if just_switched_variant:
        parts.append(_render_transition(persona.variant_name))

    out = "\n\n".join(p.strip() for p in parts if p and p.strip())
    logger.debug(
        "[renderer] mode=%s variant=%s character_id=%s chars=%d",
        mode.value, persona.variant_name, character_id, len(out),
    )
    return out
