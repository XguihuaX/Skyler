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
from backend.utils.chat_time import format_now_prompt

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


def filter_samples_by_tolerance(
    samples: List[Dict[str, Any]],
    tolerance: float,
) -> List[Dict[str, Any]]:
    """按 ``speech_style.cliche_tolerance`` 过滤 voice_samples。

    每条 sample 可带 ``tolerance_range = [min, max]``(0.0~1.0)字段,表示这条
    样本适用的"糖度区间"。当前 character 的 tolerance 落入区间内 → 命中。
    无 ``tolerance_range`` → 视为全域 [0.0, 1.0],总命中(向后兼容 segment 1
    Mai 灌入前的旧数据)。

    Fallback 决策点:若 filter 后 0 条命中 → 返回**全部** samples 并 log
    warning。理由:LLM 看到 0 条 voice_sample 等于丢了风格锚点,比"看到错配
    糖度的样本"更糟。
    """
    if not samples:
        return []
    matched: List[Dict[str, Any]] = []
    for s in samples:
        rng = s.get("tolerance_range") if isinstance(s, dict) else None
        if not rng or not isinstance(rng, (list, tuple)) or len(rng) != 2:
            matched.append(s)
            continue
        try:
            lo, hi = float(rng[0]), float(rng[1])
        except (TypeError, ValueError):
            matched.append(s)
            continue
        if lo <= tolerance <= hi:
            matched.append(s)
    if not matched:
        logger.warning(
            "[renderer] cliche_tolerance=%.2f filtered all %d samples to 0; "
            "falling back to full sample list to keep style anchor",
            tolerance, len(samples),
        )
        return list(samples)
    return matched


def _render_layer_a(
    available_motions: Optional[List[str]],
    tts_language: str = "zh",
    voice_provider: str = "cosyvoice",
    voice_model_name: Optional[str] = None,
) -> str:
    # INV-11 Stage 0' V2'' per-(provider, model) prompt 段架构:
    # voice_model_name 来自 character.voice_model JSON 的 `model` 字段
    # (例如 'mai_v4' / 'cosyvoice-v3.5-plus' / 's2-pro') · jinja 模板按
    # `voice_provider == 'gsv' and voice_model_name == 'mai_v4'` 路由 V2''
    # GSV mai_v4 段。None / 空 / 任意值都安全 — jinja `==` 与 None 比较
    # 返 False · 该 character 不命中该 sub-template 即自然跳过。
    return _jinja_env.get_template("layer_a.j2").render(
        available_motions=available_motions or [],
        tts_language=tts_language,
        voice_provider=voice_provider,
        voice_model_name=voice_model_name,
    )


def _render_layer_b(
    mode: Mode, tool_prompt_addendum: Optional[str],
) -> str:
    return _jinja_env.get_template("layer_b.j2").render(
        mode=mode,
        tool_prompt_addendum=tool_prompt_addendum,
    )


def _render_layer_c_stable(
    persona: LoadedPersona,
    states: LoadedState,
    llm_vendor: str,
    filtered_samples: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """渲染 Layer C 稳定段(C1/C1b/C2/C3/C3b/C3c/C3d) — 不含 C4 运行时状态。

    INV-5 子轨 A 路径 1:为 prompt caching 把 Layer C 拆 stable + runtime
    两段,stable 段进 messages[0] content blocks 第一块,标 cache_control。

    依赖:persona 全字段 + states.intimacy(用于 C1b self_intro 阈值切换)+
         llm_vendor(forbidden_phrases 分支) + filtered_samples。
    ⚠️ intimacy 跨过 70 阈值时 C1b 文字段会切换 → 单次 cache miss(已知,
    INV-5 §1.2 矩阵已识别为预期 thrash)。

    ``filtered_samples``:已按 ``speech_style.cliche_tolerance`` 过滤过的
    voice_samples 列表。None → 默认用 ``persona.voice_samples`` 全集
    (backward compat,segment 1 tests / 旧数据无 tolerance_range 也能跑)。
    """
    if filtered_samples is None:
        filtered_samples = persona.voice_samples or []
    return _jinja_env.get_template("layer_c_stable.j2").render(
        persona=persona,
        states=states,
        llm_vendor=llm_vendor,
        filtered_samples=filtered_samples,
    )


def _render_layer_c_runtime(
    states: LoadedState,
    safe_thought: Optional[str],
) -> str:
    """渲染 Layer C 运行时段(C4 [当前时间] / [当前状态]) — 每 turn 可变,
    放 variable 段。

    依赖:states.mood / intimacy / activity + safe_thought + 当前本地时间
    (scheduler tz)。DailyAgent Stage 1 时间地基:把"现在 YYYY-MM-DD 周X
    HH:MM" 注入 prompt,让 LLM 自然贴合现在几点和角色当下活动说话。
    """
    return _jinja_env.get_template("layer_c_runtime.j2").render(
        states=states,
        safe_thought=safe_thought,
        now_str=format_now_prompt(),
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
    tts_language: str = "zh",
    voice_provider: str = "cosyvoice",
    voice_model_name: Optional[str] = None,
) -> tuple[str, str]:
    """渲染 5 层 system prompt,返 (stable_prefix, variable_suffix) 二元组。

    INV-5 子轨 A 路径 1 重构:把 system prompt 切成 stable + variable 两段,
    便于 caller 拼 messages[0] content blocks 并在 stable 块上标 cache_control。

    Args:
        character_id: 当前角色 id。None → 调用方应在外层 fallback(本函数会
            ``raise RuntimeError``)。
        turn_origin: 见 ``mode.determine_mode`` doc。
        just_switched_variant: 是否刚切 variant,True 时 variable 末尾加
            transition 段(transition 是 per-turn 一次性内容,自然属 variable)。
        tool_prompt_addendum: D-1 sign-off,原 ``_TOOL_PROMPT_ADDENDUM`` 字符串
            直接传入,本侧不拆分不重构。属 stable 段。
        user_profile / today_activity / long_memory_top5 / tool_results /
            temp_instructions / proactive_briefing_raw: 见 Layer D 模板各 if 段。
            None / 空 → 该段跳过渲染。全属 variable 段。
        available_motions: Layer A 第 3 项注入 Live2D 可用动作清单。属 stable 段。
        llm_vendor: ``"qwen"`` / ``"deepseek"`` / 其他。Layer C 的
            ``forbidden_phrases`` vendor-aware 注入用。属 stable 段。

    Returns:
        ``(stable, variable)`` —— 两个 string,各自已 ``"\\n\\n".join``。

        stable: Layer A + Layer B + Layer C stable 段(C1/C1b/C2/C3/C3b-d)+
                addendum。per-turn 字节稳定(除非 mode / vendor / intimacy
                跨阈值 / variant 切换;见 INV-5 §1.2 矩阵)。
        variable: Layer C runtime 段(C4 [当前状态])+ Layer D + transition(若 just_switched_variant)。
                每 turn 可变,不进 cache 前缀。

        若 variable 空(罕见:Layer D 全无内容 + 未切 variant),caller 可
        按 single-string 路径回退(直接拼 stable 作 messages[0].content)。
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

    # v4 segment 2 §1.2:按 cliche_tolerance 过滤 voice_samples。tolerance 缺
    # 失 / 非数字 → 0.5 兜底。filter 结果空 → fallback 到全集(filter 内部
    # 已 log warning)。
    try:
        _tolerance = float(persona.speech_style.get("cliche_tolerance", 0.5))
    except (TypeError, ValueError):
        _tolerance = 0.5
    filtered_samples = filter_samples_by_tolerance(
        persona.voice_samples or [], _tolerance,
    )

    # ── stable 段:Layer A + B + C stable + (addendum 已在 B 内) ──────────
    stable_parts: List[str] = [
        _render_layer_a(available_motions, tts_language, voice_provider, voice_model_name),
        _render_layer_b(mode, tool_prompt_addendum),
        _render_layer_c_stable(persona, states, llm_vendor, filtered_samples),
    ]
    stable = "\n\n".join(p.strip() for p in stable_parts if p and p.strip())

    # ── variable 段:Layer C runtime + Layer D + (transition 若有) ────────
    variable_parts: List[str] = [
        _render_layer_c_runtime(states, safe_thought),
        _render_layer_d(
            user_profile, today_activity, long_memory_top5,
            tool_results, temp_instructions, briefing,
        ),
    ]
    if just_switched_variant:
        variable_parts.append(_render_transition(persona.variant_name))
    variable = "\n\n".join(p.strip() for p in variable_parts if p and p.strip())

    logger.debug(
        "[renderer] mode=%s variant=%s character_id=%s stable_chars=%d variable_chars=%d",
        mode.value, persona.variant_name, character_id, len(stable), len(variable),
    )
    return stable, variable
