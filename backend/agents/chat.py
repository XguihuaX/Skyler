"""ChatAgent: context assembly + streaming / non-streaming LLM response.

V2.5-B adds memory tool calling: the LLM can request save_memory /
delete_memory / list_memories / compress_memories during a turn. Tool calls
come back as deltas inside the streaming response; we collect them,
execute, append tool results to messages, and re-call the LLM until the
LLM returns a plain text answer.

Message contract (in)
---------------------
{
    "agent": "ChatAgent",
    "payload": {
        "user_id": str,
        "text":    str,
        "context": {                # optional
            "tool_result": str      # formatted tool output, if any
        }
    }
}

Message contract (out) — handle()
----------------------------------
{
    "status":  "success" | "error",
    "agent":   "ChatAgent",
    "payload": {
        "text":    str,             # full reply
        "error":   str              # only on error
    }
}

stream() yields complete sentences (str) as they arrive from the LLM.
"""
import json
import logging
import re
import time
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple, Union

from sqlalchemy import or_, select

from backend.agents.base import IAgent
from backend.config import (
    get_base_instruction,
    get_enable_search,
    get_enable_thinking,
    get_long_term_enabled,
    get_profile_enabled,
    get_tts_emotions,
)
from backend.config.prompt_manager import prompt_manager
from backend.config.prompts import BASE_INSTRUCTION
from backend.database import AsyncSessionLocal
from backend.database.models import Character, Memory
from backend.database.services import (
    add_memory as db_add_memory,
    delete_memory as db_delete_memory,
    get_all_memories,
)
from backend.llm.client import LLMError, call_llm, stream_llm
from backend.llm.tool_name_sanitize import sanitize_tools_for_llm
from backend.memory.long_term import generate_embedding, search_relevant_memories
from backend.memory.short_term import short_term_memory
from backend.tools.registry import ToolRegistry
from backend.utils.chat_time import format_history_time_prefix, now_local
from backend.utils.text_filters import has_partial_open_tag
from backend.utils.timer import timed

logger = logging.getLogger(__name__)
timing_logger = logging.getLogger("momoos.timing")

# ---------------------------------------------------------------------------
# v3-D: 情感标签
# ---------------------------------------------------------------------------

# 形如 "<emotion>开心</emotion>剩余正文..." 的标签匹配。
# V3b (2026-05-25 INV-11 §3 fix · per PM lock):去掉原 group(2) ``(.*)`` rest
# carrier · 改用 ``text[:m.start()] + text[m.end():]`` 重组 rest。原 regex
# group(2) 设计仅服务于 re.match 时代的"emotion 必须在最开头"语义,re.search
# 时代 group(2) 贪婪吃尾会让 ``.sub`` 误删尾巴,改成纯 tag-only 匹配。
_EMOTION_RE = re.compile(r"<emotion>(.*?)</emotion>", re.DOTALL)


def _parse_emotion(text: str) -> Tuple[str, str]:
    """解析并剥离情感标签。

    返回 (emotion, stripped_text)：
      - 命中 ``<emotion>X</emotion>`` (text 任意位置) → (X.strip(), 剥离后的剩余.strip())
      - 未命中 → ("默认", 原文)

    V3b (2026-05-25 INV-11 §3 NEW Finding · per PM lock):
    re.match → re.search。原 re.match 锚 ^ · 仅当 <emotion> tag 在文本最开头
    才命中;实测 (turn 10) LLM 真实输出 ``<thinking>...</thinking>
    <state_update .../><emotion>放松</emotion>真好啊`` 时 emotion 在 thinking
    之后 → re.match 抓不到 → 误 fallback "默认"。改 re.search 后任意位置都能
    命中;rest 用 ``text[:m.start()] + text[m.end():]`` 重组 = prefix(emotion
    之前的 thinking/state_update 等)+ suffix(emotion 之后的正文)· 保留
    emotion 之前的 tag 不丢失(由后续 _parse_thinking / _parse_state_update
    各自单独剥)。

    多个 <emotion> tag 行为:re.search 仍命中第一个(跟 re.match 一致);
    rest 重组仅剥第一个 tag · 后续 tag 若存在会留在 rest 里,由
    sanitize 链 (strip_emotion in text_filters.py) 兜底剥除。
    """
    if not text:
        return "默认", text
    m = _EMOTION_RE.search(text)
    if m:
        emotion = (m.group(1) or "").strip() or "默认"
        rest = (text[:m.start()] + text[m.end():]).strip()
        return emotion, rest
    return "默认", text


def _build_emotion_instruction() -> str:
    """生成注入 system prompt 的情感指令，告诉 LLM 必须打 <emotion> 标签。"""
    emotions = get_tts_emotions()
    return (
        "在每次回复的最开头，用 <emotion>情感词</emotion> 标签标注当前回复的情感。"
        f"只能从以下情感词中选一个：{'、'.join(emotions)}。"
        "示例：<emotion>happy</emotion>今天天气真好！"
        "标签只在最开头出现一次，正文里不再出现标签。"
    )


# ---------------------------------------------------------------------------
# v3-F：内心独白 <thinking> 标签
# ---------------------------------------------------------------------------

# 多行匹配；非贪婪，跨行用 [\s\S]
_THINKING_RE = re.compile(r"<thinking>([\s\S]*?)</thinking>", re.IGNORECASE)
_THINKING_OPEN_RE = re.compile(r"<thinking>", re.IGNORECASE)
_THINKING_CLOSE_RE = re.compile(r"</thinking>", re.IGNORECASE)


def _parse_thinking(text: str) -> Tuple[Optional[str], str]:
    """解析并剥离内心独白标签。

    Args:
        text: 原文本，可能含一个或多个 ``<thinking>X</thinking>`` 块。

    Returns:
        ``(first_thinking_content_or_none, text_with_all_blocks_removed)``。
        - 命中至少一个完整块 → first 是第一个块的内容（已 strip），剩余文本
          移除全部块后返回。
        - 无完整块（含开标签未闭合的情况）→ ``(None, text)``，原文不动，
          上游 ``_safe_boundary`` 已确保不会在未闭合时进入此函数。
    """
    if not text:
        return None, text
    m = _THINKING_RE.search(text)
    if not m:
        return None, text
    first = (m.group(1) or "").strip()
    stripped = _THINKING_RE.sub("", text).strip()
    return (first or None), stripped


def _build_thinking_instruction() -> str:
    """生成注入 system prompt 的内心独白指令。

    内心独白是可选的，鼓励但不强制。LLM 输出 ``<thinking>X</thinking>``
    放在 ``<emotion>`` 之后、正文之前；前端单独显示，不会读出口。
    """
    return (
        "你可以在回复正文之前，可选地用 <thinking>...</thinking> 标签写一段"
        "简短的内心独白（思考过程、感受、要怎么回应的考量）。"
        "标签内可以多行，但务必整段写在一对 <thinking>...</thinking> 内，"
        "且整段保持闭合再继续输出正文。"
        "示例：<emotion>happy</emotion><thinking>用户在打招呼，温柔回应一下</thinking>你好呀！"
        "内心独白只显示给用户看，不会被朗读。"
        "可以省略，不要每次都写；只在确实有想法值得展示时写。"
    )


# ---------------------------------------------------------------------------
# v3-E1 step6：动作标签 <motion>
# ---------------------------------------------------------------------------

# 形如 "...<motion>挥手</motion>..." —— 可出现在每段任意位置。
# 与 emotion 不同：emotion 整轮一次（re.match 锚定开头），motion 每段独立。
_MOTION_RE = re.compile(r"<motion>([^<]*)</motion>", re.IGNORECASE)


def _parse_motion(text: str) -> Tuple[Optional[str], str]:
    """解析并剥离单段文本中的 motion 标签。

    Args:
        text: 一段已成句的文本（_sentence_stream 切出的一句）。

    Returns:
        ``(motion_or_None, stripped_text)``：
          - 命中 → 第一个 <motion>X</motion> 的 X（已 strip），整段所有
            motion 标签一并从文本中剥掉（同段多个标签时只用第一个，剩余
            一并剥除避免下游再次看到）。
          - 未命中 → ``(None, text)`` 原样返回。

    与 ``_parse_emotion`` 的差异：emotion 整轮锁定（仅第一段命中后整轮共用），
    motion 每段独立解析，可在一轮回复中触发多次。
    """
    if not text:
        return None, text
    m = _MOTION_RE.search(text)
    if m is None:
        return None, text
    motion = (m.group(1) or "").strip() or None
    stripped = _MOTION_RE.sub("", text).strip()
    return motion, stripped


def _build_motion_instruction() -> str:
    """生成注入 system prompt 的 motion 指令。

    motion 是可选的；不打标签时 Live2D 模型保持 idle + 触摸响应，不做主动
    动作。可用名字目前在前端 ``config/live2d.ts`` 的 ``motionMap`` 维护，
    与 Hiyori 模型的 Flick* motion group 一一对应；换模型时改 map，不改这里。
    """
    return (
        "你可以在回复中嵌入 <motion>X</motion> 标签让虚拟形象做动作。"
        "当前可用动作（按语义分组，每组任选一个词使用即可）：\n"
        "- 放松 / 随意 / 慵懒 / 没事（自然甩手）\n"
        "- 害羞 / 不好意思 / 腼腆 / 小动作（双手别在身后）\n"
        "- 加油 / 兴奋 / 应援 / 欢呼 / 雀跃(小臂举起晃，像应援)\n"
        "- 撒娇 / 俏皮 / 调皮（活泼的复合表情动作）\n"
        "每段（句号 / 问号 / 感叹号断开的一段）最多 1 个 motion 标签，"
        "标签会被 TTS 自动剥除，不会读出来。"
        "不需要主动动作时不打标签，保持安静即可。"
        "注意：当前角色没有「挥手 / 打招呼 / 再见 / 点头 / 鞠躬」等具体动作，"
        "请不要使用这类词，否则动作不会被触发。"
        "示例：<emotion>happy</emotion>嘿嘿，被你发现啦~<motion>害羞</motion>"
    )


# ---------------------------------------------------------------------------
# v3-G chunk 3b：角色状态标签 <state_update>
# ---------------------------------------------------------------------------

# 自闭合标签：``<state_update mood="happy" intimacy_delta="+1" thought="..." />``
# 也容错带文本闭合：``<state_update ...>...</state_update>``
# 与 emotion / motion / thinking 的关系：
#   - emotion = per-turn 瞬时（"这一句开心"），不持久
#   - state_update.mood = 跨 turn 累积情绪（"今天整体心情"），持久 DB
# 两套独立不冲突。state_update 标签紧贴 ``<emotion>`` 之后由 LLM 可选输出。
_STATE_UPDATE_RE = re.compile(
    r"<state_update\b([^>]*?)/>"            # 标准自闭合
    r"|<state_update\b([^>]*?)>[\s\S]*?</state_update>",  # 容错变体
    re.IGNORECASE,
)
# 单个属性：``key="value"``。允许双引号 / 单引号 / 无引号简单值。
_STATE_UPDATE_ATTR_RE = re.compile(
    r"""(\w+)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s/>]+))""",
)


def _parse_state_update(text: str) -> Tuple[Optional[dict], str]:
    """解析并剥离 ``<state_update ... />`` 标签。

    Args:
        text: 原文本，可能含 1 个 state_update 标签。多个时只用第一个，其余
              一并剥除（与 motion 同 pattern）。

    Returns:
        ``(parsed_dict_or_None, stripped_text)``：
          - 命中 → 解析 mood / intimacy_delta / thought 三个属性，返 dict
            （字段缺失为 None）。整段所有 state_update 标签从文本剥掉。
          - 未命中 → ``(None, text)`` 原样返回。

    解析时不做业务校验（mood enum / delta clamp / thought 长度）—— 只做
    XML 属性切片；下游 ``services.update_character_state`` 负责校验 + 静默
    丢弃越界值，避免 LLM 拼错时整轮挂掉。
    """
    if not text:
        return None, text
    m = _STATE_UPDATE_RE.search(text)
    if m is None:
        return None, text
    attrs_str = (m.group(1) or m.group(2) or "").strip()
    parsed: dict = {"mood": None, "intimacy_delta": None, "thought": None}
    for attr_match in _STATE_UPDATE_ATTR_RE.finditer(attrs_str):
        key = (attr_match.group(1) or "").lower()
        val = (
            attr_match.group(2)
            or attr_match.group(3)
            or attr_match.group(4)
            or ""
        ).strip()
        if key == "mood":
            parsed["mood"] = val or None
        elif key == "intimacy_delta":
            try:
                parsed["intimacy_delta"] = int(val.replace("+", ""))
            except ValueError:
                parsed["intimacy_delta"] = None
        elif key == "thought":
            parsed["thought"] = val or None
        elif key == "activity":
            parsed["activity"] = val or None
    stripped = _STATE_UPDATE_RE.sub("", text).strip()
    return parsed, stripped


def _build_state_update_instruction(state: Optional[dict]) -> str:
    """生成 state_update 指令 + 当前 state 注入到 system prompt。

    Args:
        state: ``character_state`` dict 或 None（无 character_id 时）。

    Returns:
        多行 system 段落。无 state 时退化成"标签使用说明"，不展示当前值。
    """
    intro = (
        "你必须在 <emotion> 标签之后输出 <state_update /> 自闭合标签来"
        "记录这一轮的状态变化：\n\n"
        "**触发规则（满足任一就要输出）**：\n"
        "- 用户表达了情绪（开心 / 难过 / 累 / 兴奋 / 好奇 / 困）→ 输出对应"
        " mood\n"
        "- 用户分享了正向事情（完成任务 / 好消息 / 感谢你）→ 输出 "
        "intimacy_delta=\"+1\"\n"
        "- 用户表达了关心 / 主动找你聊天 / 称呼你时带感情 → 输出 "
        "intimacy_delta=\"+1\"\n"
        "- 用户表达了负面（生气 / 烦躁 / 抱怨你）→ 输出 intimacy_delta=\"-1\""
        " 配合相应 mood\n"
        "- 你想留下一句心境笔记 → 加 thought=\"...\"（≤60 字）\n\n"
        '示例：<emotion>happy</emotion><state_update mood="happy" intimacy_delta="+1" thought="觉得用户今天很努力" />嘿，辛苦啦！\n\n'
        "可用属性：\n"
        "- mood：happy / sad / curious / calm / excited / tired / neutral 七选一\n"
        "- intimacy_delta：-2 到 +2（系统 clamp，不能刷高；保守用 +1 / -1 即可）\n"
        '- thought：≤60 字，可选\n\n'
        "**只有在以下场景可以省略标签**：用户说的话是中性 chitchat（如\"几点了\"、\"在吗\"），既无情绪也无关怀。否则**必须**给一个 state_update。\n"
    )
    if not state:
        return intro
    mood = state.get("mood") or "neutral"
    intimacy = state.get("intimacy", 0)
    activity = state.get("activity") or "没什么特别的"
    thought = state.get("thought") or "没什么"
    return (
        intro
        + "\n[你的当前状态]\n"
        + f"心情：{mood}（happy/sad/curious/calm/excited/tired/neutral 之一）\n"
        + f"亲密度：{intimacy}/100\n"
        + f"当前正在做什么：{activity}\n"
        + f"当前在想：{thought}\n"
        + "请保持人设一致性。"
    )


# ---------------------------------------------------------------------------
# Sentence splitter
# ---------------------------------------------------------------------------

_SENT_END = frozenset("。！？!?")
_VALID_MEMORY_TYPES = {"fact", "instruction", "emotion", "activity", "daily"}


#: bugfix-1.1: meta tag paired form。``<state_update>X</state_update>`` 容错
#: 形态、``<emotion>happy</emotion>`` / ``<thinking>...</thinking>`` 等内
#: 部含句末标点时整段跳过, 等 ``</tag>`` 出现才考虑切句。普通 HTML
#: ``<a>`` ``<div>`` 不在此列 —— 仅跳开 opening tag 即可。
_BOUNDARY_PAIRED_TAGS = frozenset({
    "thinking", "emotion", "state_update", "motion",
    "tool_call", "function_calls", "invoke",
    # v4 segment 2 §2.4:ja / en 双语 TTS 模式 — <ja>「...バカ。」</ja> 内的
    # 全角句末标点必须不切句,等 </ja> 出现再 boundary。
    "ja", "en",
})

_BOUNDARY_TAG_NAME_RE = re.compile(r"<([a-zA-Z_][a-zA-Z_0-9]*)\b")


def _find_boundary(text: str) -> int:
    """Return the index of the first sentence-ending character, or -1.

    bugfix-1.1: 忽略 ``<tagname...>`` 标签内的句末标点。LLM 偶发输出
    ``<state_update thought="...粗心了, 赶紧补救。" />`` 这种 thought 属性
    含全角 ``。`` 的自闭合标签。旧实现按字符扫到 ``。`` 就切句 —— 把
    ``<state_update>`` 在中间劈成两半, 前半 ``<state_update mood="..."
    thought="...赶紧补救。`` 没有 ``/>`` 闭合, 下游 strip_state_update /
    SUSPICIOUS_TAG_RE 都要求闭合, 全漏 → 字面文本进 FE text_chunk + TTS
    念出"小于号 state update mood..."。

    修法：state machine 跳过 ``<...>`` 范围。
      * ``<`` 后跟字母 / ``_`` 才进 tag 检测 (``<3``/``2 < 3`` 不触发)
      * 自闭合 (``/>`` 结尾) 或非 paired-tag → 仅跳过 opening tag 段
      * paired-tag (``thinking`` / ``state_update`` / 等 meta tag) → 跳到
        对应 ``</tag>`` 之后
      * 任何 open 找不到 ``>`` 或 ``</tag>`` → 返回 -1 让 sentence stream
        等下个 chunk 把闭合带进来 (与 ``has_partial_open_tag`` 同语义)
    """
    n = len(text)
    i = 0
    while i < n:
        ch = text[i]
        if ch == "<" and i + 1 < n and (text[i + 1].isalpha() or text[i + 1] == "_"):
            m = _BOUNDARY_TAG_NAME_RE.match(text, i)
            if m is None:
                i += 1
                continue
            tag_name = m.group(1).lower()
            end_open = text.find(">", m.end())
            if end_open == -1:
                return -1  # unclosed opening — wait for next chunk
            is_self_close = end_open > 0 and text[end_open - 1] == "/"
            if is_self_close or tag_name not in _BOUNDARY_PAIRED_TAGS:
                i = end_open + 1
                continue
            close_pat = f"</{tag_name}>"
            end_close = text.lower().find(close_pat, end_open + 1)
            if end_close == -1:
                return -1  # unclosed paired — wait
            i = end_close + len(close_pat)
            continue
        if ch in _SENT_END:
            return i
        if ch == "." and i + 1 < n and text[i + 1] in (" ", "\n"):
            return i
        i += 1
    return -1


def _safe_boundary(buf: str) -> int:
    """v3-F：thinking-aware sentence boundary。

    若 ``buf`` 中有 ``<thinking>`` 但没有匹配的 ``</thinking>`` —— 当前正处
    于一段未闭合的内心独白中，``。``/``！``/``？`` 等可能出现在 thinking 内
    部，不能据此切句。返回 ``-1`` 让 ``_sentence_stream`` 继续累积，等下一个
    token 把 ``</thinking>`` 带进来。

    v3-G chunk 4 hotfix-1：同一原则扩展到 fallback tool_call 标签
    （``<tool_call>`` / ``<function_calls>`` / ``<invoke>`` / markdown json）—
    block 内常含 ``。"`` / ``，`` 等会误触发 boundary，把半截 XML 送到 TTS。
    用 ``has_partial_open_tag(buf)`` 一并检测。
    """
    open_m = _THINKING_OPEN_RE.search(buf)
    if open_m:
        close_m = _THINKING_CLOSE_RE.search(buf, open_m.end())
        if close_m is None:
            return -1
    if has_partial_open_tag(buf):
        return -1
    return _find_boundary(buf)


async def _sentence_stream(
    token_gen: AsyncGenerator[str, None],
) -> AsyncGenerator[str, None]:
    """Buffer tokens from *token_gen* and yield complete sentences.

    v3-F: thinking 标签内的标点不切句；用 ``_safe_boundary``。
    """
    buf = ""
    async for token in token_gen:
        buf += token
        while True:
            idx = _safe_boundary(buf)
            if idx == -1:
                break
            sentence = buf[: idx + 1].strip()
            buf = buf[idx + 1 :]
            if sentence:
                yield sentence
    remainder = buf.strip()
    if remainder:
        yield remainder


# ---------------------------------------------------------------------------
# Memory tools (OpenAI function-calling format; LiteLLM forwards as-is)
# ---------------------------------------------------------------------------

MEMORY_TOOLS: List[dict] = [
    {
        "type": "function",
        "function": {
            "name": "save_memory",
            "description": (
                "**仅在用户明确要求记住时**调用本工具。用户的明确信号：\n"
                "- '请记住 X'\n"
                "- '以后 X 都...'\n"
                "- '别忘了 X'\n"
                "- '你要记住 X'\n"
                "\n"
                "**日常对话事实的提取走 background worker（chunk 10），"
                "不需要本 tool**。不要主动推断'用户应该记住的事'调本 tool。\n"
                "\n"
                "（v3.5 chunk 10 起，server-side MemoryExtractor 每 5 分钟"
                "扫 role='user' 消息批量提取，本 tool 只负责显式入口。\n"
                "  对话主路径调本 tool 会触发同样的 SUSPICIOUS / 长度 / "
                "重复 quality filter；通过 filter 才入库，标 "
                "extraction_source='llm_save_memory'。）\n"
                "\n"
                "参数：\n"
                "- content: 用户明确说要记的内容\n"
                "- type: fact / instruction / activity / daily（默认 fact）"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "记忆内容，第一人称的事实陈述",
                    },
                    "type": {
                        "type": "string",
                        "description": "记忆类型，缺省 fact",
                        "enum": list(_VALID_MEMORY_TYPES),
                    },
                },
                "required": ["content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_memory",
            "description": (
                "当用户主动要求忘掉某件事时调用。"
                "通常先 list_memories 找到匹配项，再调此 tool 用 memory_id 删除。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "memory_id": {
                        "type": "integer",
                        "description": "memory 表的 id",
                    },
                },
                "required": ["memory_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_memories",
            "description": (
                "列出当前关于用户的所有记忆。"
                "当用户问'你都记得什么'，或需要查找特定记忆删除/修改时调用。"
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compress_memories",
            "description": (
                "整理 + 去重 + 合并记忆库。"
                "当用户要求'整理记忆'或记忆条数过多时调用。耗时较长。"
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
]

# UX-004: 工具调用前的过渡语行为规范。与 ``_TOOL_PROMPT_ADDENDUM`` 战术指令
# (when/how to call each tool) 分开 —— 本块只讲"调用前先说话"的 *Momo 哲学*。
#
# 注入位置: head_parts(emotion/thinking/motion/state/BASE_INSTRUCTION/persona)
# 末尾,在 chunk 11 profile / chunk 14 activity / memory recall *之前*。理由:
# tool 调用行为是输出格式约束,与 emotion/persona 同层级,不应跟语义层(用户
# 画像/今日活动/相关记忆)混在一起。
#
# v1 统一默认(用户决策):character-specific 过渡语示例不在本 commit 加 —
# 八重 / 未来角色靠自己 persona 自然变体即可。chunk 12 persona 加厚时再
# 引入 ``tool_transition_examples`` 字段(README Known Problems / tech debt
# 已记录)。
#
# TTS 决策(用户决策 Choice A):过渡语**只走文字流**(text_chunk),不预拆给
# TTS 单独合成。最终 TTS 仍是完整回复 full-utterance。Choice B(过渡语单独
# TTS interleave)需要 TTS 架构改 sentence-by-sentence streaming,留 chunk 15
# / UX-006(tech debt 已记录)。
_TOOL_BEHAVIOR_BLOCK = (
    "【工具调用行为】\n"
    "当你需要调用工具(查日历 / 看今日活动 / 查歌单 / 看 B 站 / 查网页 / "
    "看剪贴板 / 等)时,**必须先输出一句简短的过渡语**(6-15 字)让用户知道你在"
    "查询,然后再触发工具调用。\n\n"
    "过渡语要自然贴合你的人设,不要每次重复同一句。例如:\n"
    "  - \"嗯,让我看看\"\n"
    "  - \"等我查一下\"\n"
    "  - \"稍等,我看看日历\"\n"
    "  - \"好,我去查查\"\n"
    "  - (按当前角色 persona 自然变体)\n\n"
    "绝对避免:\n"
    "  - 直接 silent 调用工具不说话(用户体感'app 卡死')\n"
    "  - 过渡前输出长篇分析或解释(把分析留到工具返回后)"
)


# v4 segment 1 D-1 sign-off:_TOOL_PROMPT_ADDENDUM 原样搬到
# ``backend/agents/prompt/tool_addendum.py``。chat.py 与 renderer 都从此处
# import 同一常量 —— 一处真相。v4.1 重构(审 LiteLLM auto tools 重复行 +
# 保留 3 条策略并入 Layer B2 + 删冗余 prose)在那个文件里改。
from backend.agents.prompt.tool_addendum import (
    TOOL_PROMPT_ADDENDUM as _TOOL_PROMPT_ADDENDUM,
)


# ---------------------------------------------------------------------------
# 合并 memory tools 与 ToolRegistry 中的内置工具，统一暴露给 LLM
# ---------------------------------------------------------------------------

def _get_all_tools() -> List[dict]:
    """返回 LLM tools= 参数：MEMORY_TOOLS + ToolRegistry.list_schemas()。

    每次 LLM 调用前现算，便于运行时注册的 MCP 工具自动生效。
    """
    return MEMORY_TOOLS + ToolRegistry.list_schemas()


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

async def _tool_save_memory(
    user_id: str, args: dict, character_id: Optional[int] = None,
) -> dict:
    """v3.5 chunk 10：``save_memory`` 仍是 LLM 显式入口（用户明确要求时调），
    但**写入前过 quality filter**（与 worker 路径同 SUSPICIOUS / 长度 /
    重复 / 反推词检查），通过 filter 才入库。所有 entry 标
    ``extraction_source='llm_save_memory'``。
    """
    content = (args.get("content") or "").strip()
    if not content:
        return {"status": "error", "error": "content is required"}
    mem_type = args.get("type") or "fact"
    if mem_type not in _VALID_MEMORY_TYPES:
        mem_type = "fact"

    # v3.5 chunk 10：quality filter（防 LLM 把奇怪东西塞进来）
    # 1. 长度
    from backend.utils.memory_entry_validator import (
        MAX_CONTENT_LEN, MIN_CONTENT_LEN,
    )
    from backend.utils.text_filters import SUSPICIOUS_TAG_RE
    if not (MIN_CONTENT_LEN <= len(content) <= MAX_CONTENT_LEN):
        logger.warning(
            "[save_memory] length reject user=%s len=%d (need %d..%d)",
            user_id, len(content), MIN_CONTENT_LEN, MAX_CONTENT_LEN,
        )
        return {"status": "error", "error": "content_length_out_of_range"}
    # 2. SUSPICIOUS tag
    if SUSPICIOUS_TAG_RE.search(content):
        logger.warning(
            "[save_memory] SUSPICIOUS_TAG reject user=%s preview=%r",
            user_id, content[:120],
        )
        return {"status": "error", "error": "suspicious_tag_detected"}

    embedding_blob: Optional[bytes] = None
    try:
        embedding_blob = await generate_embedding(content)
    except Exception as exc:
        logger.error("save_memory: embedding generation failed: %s", exc)

    # v4-beta Stage 2 supersede+墓碑 Phase B:删过的"持久事实"墓碑压制。
    # 在原 cosine-vs-active-memories 之前先比对墓碑表(精确 content 或 cosine ≥ 0.92)
    # 命中即返回 status=tombstone_suppressed,不写 memory 表。
    from backend.memory.tombstone import is_tombstone_suppressed
    if await is_tombstone_suppressed(content, user_id):
        logger.info(
            "[save_memory] tombstone-suppressed user=%s preview=%r",
            user_id, content[:80],
        )
        return {
            "status": "tombstone_suppressed",
            "content": content,
        }

    # 3. 重复检测（用 cosine 与现有 memory 比较）
    from backend.memory.extractor import get_extractor_dup_threshold
    dup_th = get_extractor_dup_threshold()
    async with AsyncSessionLocal() as session:
        existing = await get_all_memories(session, user_id, active_only=True)
    if embedding_blob is not None and existing:
        import numpy as np
        from backend.memory.long_term import _cosine
        new_vec = np.frombuffer(embedding_blob, dtype=np.float32)
        for ex_m in existing:
            if not ex_m.embedding:
                continue
            ex_vec = np.frombuffer(ex_m.embedding, dtype=np.float32)
            if _cosine(new_vec, ex_vec) > dup_th:
                logger.info(
                    "[save_memory] duplicate reject user=%s preview=%r "
                    "(existing id=%d)",
                    user_id, content[:80], ex_m.id,
                )
                return {
                    "status": "duplicate",
                    "existing_memory_id": ex_m.id,
                    "content": content,
                }

    # 4. 入库 —— 用 raw SQL 写齐 chunk 10 新列（extraction_source / extracted_at）
    from datetime import datetime as _dt
    from sqlalchemy import text as _sql_text
    from backend.database import engine as _engine
    now = _dt.utcnow()
    async with _engine.begin() as conn:
        result = await conn.execute(_sql_text(
            "INSERT INTO memory "
            "(user_id, role, type, content, embedding, character_id, "
            " created_at, access_count, last_accessed_at, "
            " extracted_at, extraction_source) "
            "VALUES "
            "(:user_id, :role, :type, :content, :embedding, :character_id, "
            " :created_at, 0, :created_at, "
            " :extracted_at, :extraction_source)"
        ), {
            "user_id": user_id,
            "role": "user",
            "type": mem_type,
            "content": content,
            "embedding": embedding_blob,
            "character_id": character_id,
            "created_at": now,
            "extracted_at": now,
            "extraction_source": "llm_save_memory",
        })
        new_id = int(result.lastrowid) if result.lastrowid else None
    logger.info(
        "[save_memory] user=%s saved id=%s type=%s preview=%r "
        "extraction_source=llm_save_memory",
        user_id, new_id, mem_type, content[:80],
    )
    return {
        "status": "ok",
        "memory_id": new_id,
        "content": content,
        "type": mem_type,
        "extraction_source": "llm_save_memory",
    }


async def _tool_delete_memory(
    user_id: str, args: dict, character_id: Optional[int] = None,
) -> dict:
    raw = args.get("memory_id")
    try:
        mid = int(raw)
    except (TypeError, ValueError):
        return {"status": "error", "error": f"invalid memory_id: {raw!r}"}
    async with AsyncSessionLocal() as session:
        # Confirm the row belongs to this user before deleting.
        row = (await session.execute(
            select(Memory).where(Memory.id == mid, Memory.user_id == user_id)
        )).scalar_one_or_none()
        if row is None:
            return {"status": "error", "error": f"memory_id {mid} not found for user"}
        await db_delete_memory(session, mid)
    return {"status": "ok", "deleted_memory_id": mid}


async def _tool_list_memories(
    user_id: str, args: dict, character_id: Optional[int] = None,
) -> dict:
    async with AsyncSessionLocal() as session:
        rows = await get_all_memories(
            session, user_id, active_only=True, character_id=character_id,
        )
    return {
        "status": "ok",
        "count": len(rows),
        "memories": [
            {"id": m.id, "type": m.type, "content": m.content}
            for m in rows
        ],
    }


_COMPRESS_PROMPT = """\
以下是用户的全部记忆条目（JSON 数组）。请：
1. 删除明显过时或彼此冲突的旧条目。
2. 合并表达相同事实的重复项（保留信息最完整的版本）。
3. 不要发明用户没说过的事。
4. 输出新的精简记忆列表，只保留 JSON 数组，每项形如 {{"content": "...", "type": "..."}}，
   type 必须是 fact / instruction / emotion / activity / daily 之一。
不要输出任何 JSON 之外的文字。

旧记忆：
{memories_json}
"""


async def _tool_compress_memories(
    user_id: str, args: dict, character_id: Optional[int] = None,
) -> dict:
    """Replace the user's memory rows with an LLM-curated, deduped set.

    Transactional: the original rows are only removed inside the same DB
    session as the inserts, so an exception during insert rolls everything
    back via the AsyncSession context.
    """
    async with AsyncSessionLocal() as session:
        rows = await get_all_memories(
            session, user_id, active_only=True, character_id=character_id,
        )
    before_count = len(rows)
    if before_count == 0:
        return {"status": "ok", "before": 0, "after": 0, "message": "记忆库为空"}

    payload = [
        {"id": m.id, "type": m.type, "content": m.content} for m in rows
    ]
    prompt = _COMPRESS_PROMPT.format(
        memories_json=json.dumps(payload, ensure_ascii=False)
    )
    try:
        response = await call_llm(
            messages=[{"role": "user", "content": prompt}],
            stream=False,
        )
        raw = (response.choices[0].message.content or "").strip()
    except Exception as exc:
        logger.error("compress_memories: LLM call failed: %s", exc)
        return {"status": "error", "error": f"LLM error: {exc}"}

    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) >= 2 else raw
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.error("compress_memories: JSON parse failed: %s | raw=%r", exc, raw[:200])
        return {"status": "error", "error": f"LLM did not return valid JSON: {exc}"}

    if not isinstance(parsed, list):
        return {"status": "error", "error": "LLM response was not a JSON array"}

    # Validate + pre-compute embeddings outside the DB transaction.
    cleaned: List[dict] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        content = (item.get("content") or "").strip()
        mem_type = item.get("type") or "fact"
        if not content:
            continue
        if mem_type not in _VALID_MEMORY_TYPES:
            mem_type = "fact"
        try:
            blob = await generate_embedding(content)
        except Exception as exc:
            logger.warning("compress_memories: embedding failed for %r: %s", content[:30], exc)
            blob = None
        cleaned.append({"content": content, "type": mem_type, "embedding": blob})

    # Replace inside one transaction; rollback on any failure. Scope by
    # character_id when provided so compressing under one character doesn't
    # blow away another character's memories.
    async with AsyncSessionLocal() as session:
        try:
            existing_q = select(Memory).where(Memory.user_id == user_id)
            if character_id is not None:
                existing_q = existing_q.where(
                    or_(Memory.character_id == character_id, Memory.character_id.is_(None))
                )
            existing = list((await session.execute(existing_q)).scalars().all())
            for m in existing:
                await session.delete(m)
            for c in cleaned:
                session.add(Memory(
                    user_id=user_id,
                    role="user",
                    type=c["type"],
                    content=c["content"],
                    embedding=c["embedding"],
                    character_id=character_id,
                ))
            await session.commit()
        except Exception as exc:
            await session.rollback()
            logger.exception("compress_memories: transaction failed, rolled back")
            return {"status": "error", "error": f"DB error: {exc}"}

    after_count = len(cleaned)
    logger.info(
        "compress_memories: user=%s before=%d after=%d",
        user_id, before_count, after_count,
    )
    return {"status": "ok", "before": before_count, "after": after_count}


_TOOL_HANDLERS = {
    "save_memory":       _tool_save_memory,
    "delete_memory":     _tool_delete_memory,
    "list_memories":     _tool_list_memories,
    "compress_memories": _tool_compress_memories,
}


# ---------------------------------------------------------------------------
# 修法 B(audit_input_tokens_bloat.md #4)── tool result 字符截断
#
# 单 turn 多 round tool calling 下,prior round 的 tool result 会以
# ``{"role":"tool","content":json.dumps(result)}`` 形式附加到 messages,
# 下一 round LLM 看到全部历史 → 单次最贵 68k tokens 调用根因之一。
#
# 策略:
#   * 4000 chars 上限(中文 ~2k tokens / 英文 ~1k tokens),保留**尾部**
#     (大多数 tool 把结论 / summary 放尾部:eg list_memories 返回 newest-first
#      已逆序,daily_recommend 把 top picks 放后)
#   * 加 "[...truncated, N chars omitted from head]" 显式提示 LLM 数据被截断
#   * tool 真值不动,仅截 prompt 注入字符串
#   * DEBUG log 帮 dogfood 定位经常超长的 tool(后期可针对性优化 tool 返回)
# ---------------------------------------------------------------------------

#: 单条 tool result 进 messages 时的字符上限。4000 chars 实测覆盖:
#:   - apple_calendar.today_events:~20 events × ~150 chars/event ≈ 3000 chars
#:   - list_memories(top 30 ≈ 2000 chars)
#:   - bilibili.get_subtitles 短视频字幕(>30 min 视频会超 — 接受截断)
#:   - netease.daily_recommend(30 首歌 × ~100 chars/song ≈ 3000 chars)
#: 4000 是经验值,可按 dogfood 反馈调整(尾部保留 + 显式 marker 让 LLM 知情)。
TOOL_RESULT_MAX_CHARS: int = 4000


def truncate_tool_result(
    result: Any,
    *,
    max_chars: int = TOOL_RESULT_MAX_CHARS,
    tool_name: str = "",
) -> str:
    """Serialize ``result`` to JSON string and truncate head if over ``max_chars``。

    Truncation 策略:**保留尾部**(大多数 tool 把 conclusion / summary 放尾,
    head 是 metadata / less critical info)。截断时插入 marker 让 LLM 知道
    数据被裁过,可避免 LLM 当全量数据用。

    Args:
        result: tool 返回值(dict / list / str / 其他 json-serializable)
        max_chars: 上限字符数(默认 ``TOOL_RESULT_MAX_CHARS=4000``)
        tool_name: 仅 log 用,标识哪个 tool 触发截断(便于 dogfood 调优)

    Returns:
        str 形式,可直接作 ``messages.append({...,"content": ...})`` 的 content。
        若已是 ``str`` 类型则**不**再 json.dumps(避免 ``"raw string"`` 多一层引号)。
    """
    result_str = (
        result if isinstance(result, str)
        else json.dumps(result, ensure_ascii=False)
    )
    if len(result_str) <= max_chars:
        return result_str
    omitted = len(result_str) - max_chars
    truncated = (
        f"[...truncated, {omitted} chars omitted from head]\n"
        + result_str[-max_chars:]
    )
    logger.debug(
        "[tool_truncate] %s: %d -> %d chars (-%d)",
        tool_name or "<unnamed>", len(result_str), max_chars, omitted,
    )
    return truncated


async def _execute_tool(
    user_id: str,
    name: str,
    raw_args: str,
    character_id: Optional[int] = None,
) -> dict:
    """Parse the tool arguments and dispatch to the matching handler.

    路由顺序：
      1. memory tool（save / delete / list / compress_memories）→ 模块内 handler
      2. 其他 → ToolRegistry.call()，user_id 会话级注入，schema 中不暴露给 LLM
    任一异常都被捕获并以 {"error": "..."} 返回，不中断 tool loop。
    """
    try:
        args = json.loads(raw_args) if raw_args else {}
    except json.JSONDecodeError as exc:
        return {"error": f"invalid JSON args: {exc}"}

    # ── memory 类工具：保留原路径 ─────────────────────────────────────────
    handler = _TOOL_HANDLERS.get(name)
    if handler is not None:
        try:
            return await handler(user_id, args, character_id=character_id)
        except Exception as exc:
            logger.exception("Memory tool %s execution failed", name)
            return {"error": str(exc)}

    # ── 其他工具：经 ToolRegistry 调度 ────────────────────────────────────
    # 防止 LLM 误传会话级参数覆盖注入值
    args.pop("user_id", None)
    # v3-G chunk 4: 显式注入 character_id 到 ToolRegistry tools。
    # 旧实现只给 memory tools 透传 character_id，``character.set_activity``
    # / ``character.get_state`` 等 capability 走 ToolRegistry 路径时收不到 →
    # 报"character_id missing in context"。这里补上，与 chunk 4 fallback
    # resilience 路径保持同一注入语义。
    if character_id is not None and "character_id" not in args:
        args["character_id"] = character_id
    try:
        result = await ToolRegistry.call(name, user_id=user_id, **args)
        return {"status": "ok", "result": result}
    except KeyError:
        return {"error": f"unknown tool: {name}"}
    except TypeError as exc:
        return {"error": f"wrong arguments: {exc}"}
    except ValueError as exc:
        return {"error": f"invalid argument: {exc}"}
    except Exception as exc:
        logger.exception("Builtin tool %s execution failed", name)
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# Context assembly
# ---------------------------------------------------------------------------

async def _maybe_build_wake_call_addendum(
    user_id: str, user_text: str,
) -> Optional[str]:
    """v3-G chunk 2.6 起 stage 2 addendum 探测；chunk 4 起多 trigger 通用。

    判定条件全部为真才注入：
      1. ``proactive.enabled == True``（chunk 4：取消 mode='wake_call' 强
         耦合，让 lunch_call / bedtime_chat / long_idle 共享同一探测路径）
      2. 该 user 最近一行 assistant chat_history 的 ``proactive_trigger``
         字段非空（即任一 trigger 留下的痕迹），且对应 trigger 在
         _stage2_registry 注册了 builder。
      3. ``pending_briefings`` 有未消费、未超 TTL 的行（trigger_name 与
         上一条 assistant 的 ``proactive_trigger`` 一致）。

    命中即同步把 pending 标 ``consumed_at = now`` （consume-on-detect 语义）。

    此函数对 _build_messages 是 best-effort —— 任何异常吞成 None，让普通
    chat path 照常走。
    """
    try:
        from backend.config import config_yaml as _cfg_yaml
        proactive_cfg = _cfg_yaml.get("proactive") or {}
        if not proactive_cfg.get("enabled", False):
            return None

        from backend.database.services import (
            consume_pending_briefing,
            get_active_pending_briefing,
            get_last_assistant_turn,
        )
        # 触发模块的 import 副作用注册到 _stage2_registry
        import backend.proactive.triggers.wake_call_briefing  # noqa: F401
        try:
            import backend.proactive.triggers.lunch_call         # noqa: F401
            import backend.proactive.triggers.dinner_call        # noqa: F401
            import backend.proactive.triggers.bedtime_chat       # noqa: F401
            import backend.proactive.triggers.long_idle          # noqa: F401
        except ImportError:
            pass  # chunk 4 之前 / 部分场景没有这些 trigger
        from backend.proactive.triggers._stage2_registry import (
            build_stage2_addendum,
        )

        async with AsyncSessionLocal() as session:
            last_assistant = await get_last_assistant_turn(session, user_id)
            trigger_name = last_assistant.proactive_trigger if last_assistant else None
            if not trigger_name:
                return None

            pending = await get_active_pending_briefing(
                session, user_id, trigger_name=trigger_name,
            )
            if pending is None:
                return None

            briefing_data_json = pending.briefing_data_json
            pending_id = pending.id

            # consume-on-detect：成功取到立即标 consumed，避免重发同一条
            # 用户消息时再次注入。
            await consume_pending_briefing(session, pending_id)

        try:
            data = json.loads(briefing_data_json) if briefing_data_json else {}
        except json.JSONDecodeError:
            data = {}
        city = str(data.get("city") or "东京")

        addendum = build_stage2_addendum(
            trigger_name, user_text, briefing_data_json, city,
        )
        if addendum is None:
            logger.info(
                "[stage2] no builder for trigger=%s user=%s pending_id=%d (skipped)",
                trigger_name, user_id, pending_id,
            )
            return None
        logger.info(
            "[stage2] injected addendum for trigger=%s user=%s pending_id=%d "
            "user_text=%r",
            trigger_name, user_id, pending_id, user_text[:50],
        )
        return addendum
    except Exception:
        logger.exception("[stage2] addendum probe failed; skipping")
        return None


async def _get_active_llm_vendor() -> str:
    """Best-effort detect active LLM vendor 给 renderer 做 vendor-aware
    forbidden_phrases 注入(Layer C 模板)。

    DB 异常 / 无 active provider → ``"qwen"`` 兜底(项目默认)。
    """
    try:
        from backend.database.ai_providers import get_active_provider
        active = await get_active_provider("llm")
        if active and active.vendor_id:
            return active.vendor_id
    except Exception:
        logger.debug("[chat] _get_active_llm_vendor failed, defaulting to qwen")
    return "qwen"


def _user_content(text: str, attachments: Optional[List[dict]]) -> object:
    """2026-06-19 · 文件 + 图片输入(MVP)· 把当前 user turn 的 text +
    attachments 组装成 OpenAI 兼容 content。

    无 attachments → 返 string(老路径 · chat_history 回放 + LLM 全兼容)
    有 attachments → 返 list[block]:
        [{type:text,text}?,
         {type:text,text:'[文件 {name}]\\n{content}'}*,   # file 分支(新增)
         {type:image_url,image_url:{url}}*]              # image 分支(原有)
        - text 为空时只放 image_url / file text block(pin 1 · 空 text block 部分端点会拒)
        - image_url shape 跟 Step 0 探针 HTTP 200 验过的同款 · 不手搓变体
        - file:解 base64 → file_extract.extract_text 按 mime / 扩展兜底分派
          → 拼 "[文件 {name}]\\n{content}" 单独 text block · 抽空 / 失败仍
          标透明给 LLM(补丁 E:[抽取为空] / [抽取失败])
    """
    if not attachments:
        return text
    blocks: List[dict] = []
    if text:
        blocks.append({"type": "text", "text": text})
    # 顺序:用户文字 → 文件文本块(可读) → 图片块(visual)
    file_blocks: List[dict] = []
    image_blocks: List[dict] = []
    for a in attachments:
        if not isinstance(a, dict):
            continue
        kind = a.get("kind")
        if kind == "image":
            url = a.get("data_url")
            if isinstance(url, str) and url.startswith("data:image/"):
                image_blocks.append({
                    "type": "image_url",
                    "image_url": {"url": url},
                })
        elif kind == "file":
            url = a.get("data_url")
            mime = str(a.get("mime") or "")
            filename = str(a.get("filename") or "file")
            if not isinstance(url, str) or "," not in url:
                continue
            try:
                import base64  # noqa: PLC0415
                _, _, b64 = url.partition(",")
                raw = base64.b64decode(b64, validate=False)
            except Exception as exc:  # noqa: BLE001
                file_blocks.append({
                    "type": "text",
                    "text": f"[文件 {filename}]\n[抽取失败:{type(exc).__name__}]",
                })
                continue
            from backend.agents import file_extract as _fx  # noqa: PLC0415
            extracted, meta = _fx.extract_text(filename, mime, raw)
            if meta.get("error"):
                content_line = f"[抽取失败:{meta['error']}]"
            elif meta.get("empty") or not extracted:
                if meta.get("source") == "pdf":
                    empty_pages = meta.get("empty_pages")
                    extra = f"({empty_pages} 页未抽到文本 · 可能扫描件 / 加密)" if empty_pages else ""
                    content_line = f"[抽取为空 {extra}]"
                else:
                    content_line = "[抽取为空]"
            else:
                content_line = extracted
            file_blocks.append({
                "type": "text",
                "text": f"[文件 {filename}]\n{content_line}",
            })
    blocks.extend(file_blocks)
    blocks.extend(image_blocks)
    # 全过滤掉(异常输入)→ 退回 text(防出 empty content)
    return blocks if blocks else text


async def _build_messages(
    user_id: str,
    text: str,
    tool_result: str | None = None,
    character_id: Optional[int] = None,
    extra_system: str | None = None,
    skip_short_term: bool = False,
    turn_origin: str = "user",
    conversation_id: Optional[int] = None,
    attachments: Optional[List[dict]] = None,
) -> List[dict]:
    """Assemble the full message list to send to the LLM.

    v4 segment 1:
      Primary path → ``backend.agents.prompt.renderer.render_system_prompt`` 5-layer
      Legacy fallback → 旧 head_parts + system_parts 拼装(prompt_manager 路径,
        @deprecated 待 v4.1 删除)。

    Renderer path 在以下场景 fallthrough 到 legacy:
      * ``character_id is None``(legacy 仍依赖 yaml ``默认``)
      * ``character_personas`` 无 active variant(``RuntimeError``,可能 migration
        没跑或被人工 disable)
      * 任何 jinja / DB 异常(logged warning)

    Short-term conversation history follows as real turns, then the current
    user message as the final entry.
    """
    # ===== v4 segment 1 — renderer path (try first) =====
    if character_id is not None:
        try:
            # Gather data shared with renderer kwargs
            profile_str: Optional[str] = None
            if get_profile_enabled():
                try:
                    from backend.services.profile_regen import (
                        format_profile_for_prompt, get_profile_data,
                    )
                    profile_data = await get_profile_data(user_id)
                    formatted = format_profile_for_prompt(profile_data)
                    if formatted:
                        profile_str = formatted
                    # (2026-05-19) profile_summary fallback 已退役;
                    # profile_data 为空时不注入画像。
                except Exception:
                    logger.exception("[chat] profile gather failed (renderer path)")

            activity_str: Optional[str] = None
            try:
                from backend.services.activity_timeline import (
                    format_today_activity_for_prompt,
                )
                activity_str = await format_today_activity_for_prompt(user_id)
            except Exception as exc:
                logger.debug(
                    "[chat] activity_timeline inject skipped (renderer path): %s",
                    exc,
                )

            memory_top5: List[str] = []
            if get_long_term_enabled():
                try:
                    relevant = await search_relevant_memories(
                        user_id, query=text, top_k=5,
                    )
                    memory_top5 = [m.content for m in (relevant or [])]
                except Exception:
                    logger.exception("[chat] long-term memory recall failed (renderer path)")

            # stage2 proactive 简报检测(沿用 legacy 路径相同 sentinel 逻辑)
            stage2_addendum: Optional[str] = None
            try:
                import backend.proactive.triggers.wake_call_briefing  # noqa: F401
                try:
                    import backend.proactive.triggers.lunch_call    # noqa: F401
                    import backend.proactive.triggers.dinner_call   # noqa: F401
                    import backend.proactive.triggers.bedtime_chat  # noqa: F401
                    import backend.proactive.triggers.long_idle     # noqa: F401
                except ImportError:
                    pass
                from backend.proactive.triggers._stage2_registry import (
                    all_stage1_sentinels,
                )
                _sentinels = all_stage1_sentinels()
            except Exception:
                _sentinels = []
            _in_stage1 = bool(
                extra_system and any(s in extra_system for s in _sentinels)
            )
            if not _in_stage1:
                try:
                    stage2_addendum = await _maybe_build_wake_call_addendum(
                        user_id, text,
                    )
                except Exception:
                    logger.exception("[chat] stage2 addendum failed (renderer path)")

            # 合并 extra_system + stage2_addendum → temp_instructions(Layer D 段)
            _temp_parts: List[str] = []
            if extra_system:
                _temp_parts.append(extra_system)
            if stage2_addendum:
                _temp_parts.append(f"【proactive 简报】\n{stage2_addendum}")
            temp_instructions = "\n\n".join(_temp_parts) if _temp_parts else None

            llm_vendor = await _get_active_llm_vendor()

            # v4 segment 2 §2.1:从 character.voice_model JSON 抽 tts_language。
            # ja/en 走 layer_a.j2 双语 directive,LLM 输出 <ja>...</ja>。
            # INV-9 §5:同段抽 voice_provider 给 Layer A1 fish 子分支教 markers。
            # INV-11 Stage 0' V2'' (2026-05-25):再抽 voice_model_name 字段给
            # layer_a.j2 per-(provider, model) sub-template 路由(例如
            # 'gsv' + 'mai_v4' → V2'' GSV mai_v4 段)。
            # 2026-06-15 SPEC:tts_language 改走 resolve_tts_language 共享 ·
            # voice_model 没显式 tts_language 时按 (provider, model) 查注册表
            # 音色原生语种(mai_v4=ja 等)· 防 cid=5 绫华那种"挂日语音却落 zh
            # → directive 不注入 <ja> → LLM 出纯中文 → 静音/音色飘"链路。
            voice_provider: str = "cosyvoice"
            voice_model_name: Optional[str] = None
            try:
                async with AsyncSessionLocal() as session:
                    vm_str = (await session.execute(
                        select(Character.voice_model).where(Character.id == character_id)
                    )).scalar_one_or_none()
                if isinstance(vm_str, str) and vm_str.strip():
                    _vm = json.loads(vm_str)
                    if isinstance(_vm, dict):
                        _p = _vm.get("provider")
                        if isinstance(_p, str) and _p.strip():
                            voice_provider = _p.strip().lower()
                        _m = _vm.get("model")
                        if isinstance(_m, str) and _m.strip():
                            voice_model_name = _m.strip().lower()
            except (json.JSONDecodeError, TypeError):
                pass
            except Exception:
                logger.exception(
                    "[chat] tts_language lookup failed for character_id=%s",
                    character_id,
                )

            from backend.tts.voice_config import resolve_tts_language
            tts_language = resolve_tts_language(
                provider=voice_provider,
                model=voice_model_name,
            )

            from backend.agents.prompt import render_system_prompt
            # INV-5 §5 Phase 2:renderer 返 (stable, variable) 二元组,
            # 便于 caller 拼 messages[0] content blocks 并在 Phase 3 给
            # stable 块标 cache_control marker。
            stable_prompt, variable_prompt = await render_system_prompt(
                character_id=character_id,
                turn_origin=turn_origin,
                tool_prompt_addendum=_TOOL_PROMPT_ADDENDUM,
                user_profile=profile_str,
                today_activity=activity_str,
                long_memory_top5=memory_top5 or None,
                tool_results=tool_result,
                temp_instructions=temp_instructions,
                llm_vendor=llm_vendor,
                tts_language=tts_language,
                voice_provider=voice_provider,
                voice_model_name=voice_model_name,
            )
            logger.info(
                "[renderer] mode_origin=%s character_id=%s "
                "stable_chars=%d variable_chars=%d "
                "profile=%s activity=%s memories=%d stage2=%s tts_lang=%s",
                turn_origin, character_id,
                len(stable_prompt), len(variable_prompt),
                bool(profile_str), bool(activity_str), len(memory_top5),
                bool(stage2_addendum), tts_language,
            )

            # variable 非空 → content blocks 形态;空 → 单 string 回退
            # (避免空 block 浪费 wire byte / token,且与 pre-Phase-2 行为兼容)
            if variable_prompt:
                messages: List[dict] = [{
                    "role": "system",
                    "content": [
                        {"type": "text", "text": stable_prompt},
                        {"type": "text", "text": variable_prompt},
                    ],
                }]
            else:
                messages: List[dict] = [
                    {"role": "system", "content": stable_prompt}
                ]
            # v4-beta Stage 2:滚动摘要层独立 system 块,排在 system_prompt
            # (含人设/事实)之后、short_term 最近轮之前。空摘要(短对话期)→ 跳过,
            # 零成本零干扰。
            try:
                from backend.memory.summary import get_summary
                _sum = await get_summary(user_id, character_id, conversation_id)
                if _sum:
                    messages.append({
                        "role": "system",
                        "content": f"【过往对话摘要(滚动压缩)】\n{_sum}",
                    })
            except Exception:
                logger.exception(
                    "[chat] summary fetch failed user=%s char=%s conv=%s "
                    "— skip injection, do not block turn",
                    user_id, character_id, conversation_id,
                )
            if not skip_short_term:
                # DailyAgent Stage 1 时间地基:每条 short_term turn 前缀
                # ``[今天 HH:MM]`` / ``[昨天 HH:MM]`` / ``[M月D日 HH:MM]``。
                # turn 无 created_at(旧 in-memory entry 或 legacy 写入) →
                # 前缀为空,优雅降级,只拼原 content。
                _now_local = now_local()
                for turn in await short_term_memory.get(
                    user_id,
                    character_id=character_id,
                    conversation_id=conversation_id,
                ):
                    _prefix = format_history_time_prefix(
                        turn.get("created_at"),
                        now_local_dt=_now_local,
                    )
                    _content = (
                        f"{_prefix} {turn['content']}" if _prefix else turn["content"]
                    )
                    messages.append(
                        {"role": turn["role"], "content": _content}
                    )
            # 2026-06-19 · 当前 user turn · 有 attachments 升 list block ·
            # 无则保持 string(老路径 0 行为变化)。短期 buffer 回放仍 string。
            messages.append({
                "role": "user",
                "content": _user_content(text, attachments),
            })
            return messages

        except Exception as exc:
            logger.warning(
                "[chat] v4 renderer path failed (%s: %s), falling back to "
                "legacy @deprecated prompt_manager assembly",
                type(exc).__name__, exc,
            )
            # fallthrough to legacy

    # ===== Legacy @deprecated path (v4.1 will remove) =====
    if character_id is not None:
        # 仅 renderer 异常时打 warning(character_id is None 时是正常 fallback)
        logger.debug(
            "[chat] legacy assembly path used for character_id=%s", character_id,
        )

    # ---- 1. Persona ----
    # v3-B 补丁：把 config.yaml 里的 base_instruction (通用设定) 拼到
    # persona 之前，作为所有角色共享的输出风格约束。空串则跳过。
    # v3-D 补丁：再前置一段情感标签指令，要求 LLM 在每次回复最开头打
    # <emotion>...</emotion>，供下游 TTS 路由使用；ws.py 会剥掉标签
    # 再下发 text_chunk，前端不会看到。
    #
    # Persona 来源选择（v3-cleanup：DB persona 主源 + YAML fallback）：
    # 早期 prompt_manager 只读 characters.yaml，UI 切角色不影响 system prompt
    # —— 切到任何角色都拿 yaml '默认' 那条 ChatAgent fallback。修法：优先按
    # incoming character_id 从 DB characters.persona 拿，DB miss / 空 / 没 id
    # 才退到 prompt_manager.get_prompt（保留 LLM tool 的 switch_character
    # 路径 + 完全没角色信息时的兜底）。yaml 现在仅服务于这两种 fallback。
    db_persona: Optional[str] = None
    if character_id is not None:
        try:
            async with AsyncSessionLocal() as session:
                row = (await session.execute(
                    select(Character.persona).where(Character.id == character_id)
                )).scalar_one_or_none()
                if isinstance(row, str) and row.strip():
                    db_persona = row.strip()
        except Exception:
            logger.exception(
                "_build_messages: DB persona lookup failed for character_id=%s",
                character_id,
            )

    if db_persona is not None:
        persona_block = f"{db_persona}\n\n{BASE_INSTRUCTION}" + _TOOL_PROMPT_ADDENDUM
    else:
        prompt_data = prompt_manager.get_prompt(user_id)
        persona_block = prompt_data["system_prompt"] + _TOOL_PROMPT_ADDENDUM
    base = get_base_instruction().strip()
    emotion_inst = _build_emotion_instruction()
    thinking_inst = _build_thinking_instruction()
    motion_inst = _build_motion_instruction()

    # v3-G chunk 3b：注入"当前角色状态"段（mood / intimacy / activity / thought）+
    # state_update 标签使用说明。无 character_id 时退化成"标签说明"段，不
    # 展示具体数值。
    state_dict: Optional[dict] = None
    if character_id is not None:
        try:
            from backend.database.services import get_or_create_character_state
            async with AsyncSessionLocal() as session:
                state_row = await get_or_create_character_state(session, character_id)
            state_dict = {
                "mood": state_row.mood,
                "intimacy": state_row.intimacy,
                "thought": state_row.current_thought,
                "activity": state_row.current_activity,
            }
        except Exception:
            logger.exception(
                "_build_messages: character_state lookup failed for character_id=%s",
                character_id,
            )
    state_inst = _build_state_update_instruction(state_dict)

    # v3-F：thinking 指令紧跟 emotion 指令（两者都是输出格式约束，归一处）
    # v3-E1 step6：motion 指令也归此处，三条共同构成输出格式约束块
    # v3-G chunk 3b：state_update 也归此处
    head_parts = [emotion_inst, thinking_inst, motion_inst, state_inst]
    if base:
        head_parts.append(base)
    head_parts.append(persona_block)
    # UX-004: 过渡语行为规范紧贴 persona 之后,与 emotion/thinking/state 同层级
    # (输出格式约束块),不混进下方 profile/activity/memory recall 语义层
    head_parts.append(_TOOL_BEHAVIOR_BLOCK)
    system_parts: List[str] = ["\n\n".join(head_parts)]

    _profile_enabled   = get_profile_enabled()
    _long_term_enabled = get_long_term_enabled()

    # ---- 2. User profile (config-gated) ----
    # v3.5 chunk 11：结构化 ``users.profile_data``（JSON）注入 system prompt。
    # (2026-05-19) chunk 9 ``profile_summary`` fallback 已退役;profile_data
    # 为空时不注入用户画像。``users.profile_summary`` 列保留空列,无读写。
    if _profile_enabled:
        from backend.services.profile_regen import (
            format_profile_for_prompt,
            get_profile_data,
        )
        profile_data = await get_profile_data(user_id)
        formatted = format_profile_for_prompt(profile_data)
        if formatted:
            system_parts.append(formatted)

    # ---- 2b. Today's activity timeline (chunk 14, config-gated) ----
    # 与 profile 同位置(用户上下文层),早于 memory recall(更老的语义层)。
    # ``inject_into_chat`` 与 ``activity_timeline.enabled`` 分两个 toggle —
    # 用户可"记录但不在对话里提及"。format 函数模板化生成(无 LLM 调用),
    # 总活跃 < 60s / 关闭 / DB 异常 → silent None。
    try:
        from backend.services.activity_timeline import (
            format_today_activity_for_prompt,
        )
        activity_block = await format_today_activity_for_prompt(user_id)
        if activity_block:
            system_parts.append(activity_block)
    except Exception as exc:
        # 决不让 timeline 注入失败阻塞主对话流(对齐 chunk 8a 风格 silent)
        logger.debug("[chat] activity_timeline inject skipped: %s", exc)

    # ---- 3. Long-term memory Top-5 (config-gated) ----
    # v3.5 chunk 9 Part 3：去 character_id 隔离 —— memory 改为 user 级共享，
    # 事实跨角色统一（"我猫叫 Mochi" 跟 Momo 说一次，切八重也能召回）。
    # save_memory tool 仍写 character_id 做 audit metadata（commit 6 UI 角标
    # 显示来源角色），但检索路径**只按 user_id 过滤**。
    if _long_term_enabled:
        relevant = await search_relevant_memories(
            user_id, query=text, top_k=5,
        )
        if relevant:
            mems = [f"- {m.content}" for m in relevant]
            system_parts.append("【相关长期记忆】\n" + "\n".join(mems))

    # ---- 4. Tool result (legacy MemoryAgent path) ----
    if tool_result:
        system_parts.append(f"【工具调用结果】\n{tool_result}")

    # ---- 5. Per-turn ad-hoc instruction (e.g. v3-E1 step3 touch event) ----
    if extra_system:
        system_parts.append(f"【临时指令】\n{extra_system}")

    # ---- 6. v3-G chunk 2.6/4 proactive stage 2：自动检测 pending_briefings ----
    # 注意：proactive engine 自己（stage 1）调 ChatAgent.stream 时也会进这一
    # 函数，但 stage 1 的 user text = "[proactive trigger]" 无意义，stage 2
    # 不应在 stage 1 里注入（避免无限递归）。chunk 4：扩展到 wake_call /
    # lunch_call / dinner_call / bedtime_chat / long_idle 多 sentinel；任一
    # sentinel 命中 extra_system 都跳过 stage 2 探测。
    try:
        # Trigger imports 触发 register_stage2 副作用。失败（依赖问题）退化
        # 为只查 wake_call 的旧路径。
        import backend.proactive.triggers.wake_call_briefing  # noqa: F401
        try:
            import backend.proactive.triggers.lunch_call    # noqa: F401
            import backend.proactive.triggers.dinner_call   # noqa: F401
            import backend.proactive.triggers.bedtime_chat  # noqa: F401
            import backend.proactive.triggers.long_idle     # noqa: F401
        except ImportError:
            pass
        from backend.proactive.triggers._stage2_registry import (
            all_stage1_sentinels,
        )
        sentinels = all_stage1_sentinels()
    except Exception:
        sentinels = []
    in_stage1 = bool(extra_system and any(s in extra_system for s in sentinels))
    if not in_stage1:
        stage2_addendum = await _maybe_build_wake_call_addendum(user_id, text)
        if stage2_addendum:
            system_parts.append(f"【proactive 简报】\n{stage2_addendum}")

    system_prompt = "\n\n".join(system_parts)

    # ---- Short-term history as conversation turns ----
    # v3-G chunk 2.6: stage 1 wake call 用 skip_short_term=True，避免历史
    # 长简报 turn 污染 LLM tone（实测：8-15 字约束被历史 200 字简报 tone
    # 覆盖时输出 100+ 字）。普通 chat / stage 2 仍走全量短期记忆。
    messages: List[dict] = [{"role": "system", "content": system_prompt}]
    # v4-beta Stage 2:legacy 路径同样注入滚动摘要,独立 system 块,排在
    # system_prompt 之后、short_term 最近轮之前。与 v4 renderer 路径同契约。
    try:
        from backend.memory.summary import get_summary
        _sum = await get_summary(user_id, character_id, conversation_id)
        if _sum:
            messages.append({
                "role": "system",
                "content": f"【过往对话摘要(滚动压缩)】\n{_sum}",
            })
    except Exception:
        logger.exception(
            "[chat-legacy] summary fetch failed user=%s char=%s conv=%s "
            "— skip injection, do not block turn",
            user_id, character_id, conversation_id,
        )
    if not skip_short_term:
        # DailyAgent Stage 1 时间地基:同 renderer 路径,history 加时间前缀。
        _now_local = now_local()
        for turn in await short_term_memory.get(
            user_id,
            character_id=character_id,
            conversation_id=conversation_id,
        ):
            _prefix = format_history_time_prefix(
                turn.get("created_at"),
                now_local_dt=_now_local,
            )
            _content = (
                f"{_prefix} {turn['content']}" if _prefix else turn["content"]
            )
            messages.append({"role": turn["role"], "content": _content})

    # ---- Current user input ----
    # 2026-06-19 · 同 renderer 路径:有 attachments 升 list block,无则 string。
    messages.append({
        "role": "user",
        "content": _user_content(text, attachments),
    })
    return messages


# ---------------------------------------------------------------------------
# ChatAgent
# ---------------------------------------------------------------------------

class ChatAgent(IAgent):

    async def handle(self, message: dict) -> dict:
        """Non-streaming: return the full reply as a single dict.

        Tool calling is not used in this code path — handle() is kept for the
        legacy non-stream API surface.
        """
        payload = message.get("payload", {})
        user_id: str = payload.get("user_id", "")
        text: str = payload.get("text", "")
        context = payload.get("context") or {}
        tool_result: str | None = context.get("tool_result")
        extra_system: str | None = context.get("extra_system")
        # v4 segment 1: deterministic mode classification 依据 context.turn_origin
        # (ws.py 默认不设 → 'user';proactive/engine.py 写 trigger.name)。
        turn_origin: str = str(context.get("turn_origin") or "user")
        raw_char = payload.get("character_id")
        character_id: Optional[int] = (
            int(raw_char) if isinstance(raw_char, (int, str)) and str(raw_char).strip() else None
        )
        # Bug 1 修法:同源 conv_id 用于 short_term 过滤(audit_lost_replies.md)
        raw_conv = payload.get("conversation_id")
        conversation_id: Optional[int] = (
            int(raw_conv) if isinstance(raw_conv, (int, str)) and str(raw_conv).strip() else None
        )
        # 2026-06-19 · 图片输入(MVP)· 透传到 _build_messages
        raw_atts = payload.get("attachments") or []
        attachments: Optional[List[dict]] = (
            list(raw_atts) if isinstance(raw_atts, list) and raw_atts else None
        )

        # 2026-06-19 · 图片输入(MVP)· image-only 允许 · pin 1
        if not user_id or (not text and not attachments):
            return {
                "status": "error",
                "agent": "ChatAgent",
                "payload": {"error": "payload must contain non-empty user_id and (text or attachments)"},
            }

        try:
            messages = await _build_messages(
                user_id, text, tool_result,
                character_id=character_id,
                extra_system=extra_system,
                turn_origin=turn_origin,
                conversation_id=conversation_id,
                attachments=attachments,
            )

            reply_parts: List[str] = []
            async for chunk in stream_llm(messages):
                reply_parts.append(chunk)
            reply = "".join(reply_parts)

            return {
                "status": "success",
                "agent": "ChatAgent",
                "payload": {"text": reply},
            }

        except LLMError as exc:
            logger.error("ChatAgent LLM error for user %s: %s", user_id, exc)
            return {
                "status": "error",
                "agent": "ChatAgent",
                "payload": {"error": str(exc)},
            }
        except Exception as exc:
            logger.exception("ChatAgent unexpected error for user %s", user_id)
            return {
                "status": "error",
                "agent": "ChatAgent",
                "payload": {"error": f"Internal error: {exc}"},
            }

    async def stream(
        self, message: dict,
    ) -> AsyncGenerator[Union[str, dict], None]:
        """Streaming with unified tool calling (memory + ToolRegistry built-ins).

        Yield 类型混合(UX-004):
          * ``str``  — 一句文本,ws.py 包成 ``text_chunk`` event 给前端
          * ``dict`` — typed WS event(``tool_use_start`` / ``tool_use_done``
                       带 tool_name / duration_ms),ws.py 直接 send_json 透传
                       不经文本处理(emotion/thinking parse)

        Loops:
          1. Call acompletion(stream=True, tools=_get_all_tools()).
             —— memory tools + ToolRegistry.list_schemas() 一并暴露给 LLM。
          2. Read deltas — text deltas feed sentence buffer; tool_call deltas
             accumulate per index.
          3. When the round ends with finish_reason == "tool_calls",
             execute each tool, append assistant + tool messages, loop again.
          4. Otherwise flush remaining text and return.

        v3-G chunk 2: ``context.enable_search`` (bool) 控制本轮是否启用
        LiteLLM model-native web search（qwen → enable_search=True；deepseek
        → tools 加 web_search_preview）。proactive 简报触发用 True。普通对话
        默认 False —— 历史路径不动；config.yaml 的全局 enable_search 仍由
        前端 settings 控，但走的是 prompt-time 注入而非 LiteLLM 参数。
        """
        payload = message.get("payload", {})
        user_id: str = payload.get("user_id", "")
        text: str = payload.get("text", "")
        context = payload.get("context") or {}
        tool_result: str | None = context.get("tool_result")
        extra_system: str | None = context.get("extra_system")
        # 2026-05-29 X1: 接通 config.yaml:search.enable_search 死开关 ·
        # context 显式传 enable_search 优先(proactive trigger / 显式指令路径);
        # context 缺 key → 走 get_enable_search() 读 config.yaml(默认 true ·
        # UI 可关)。原 X1 audit §1.6 + §8 #1 死代码消费方接通 ·
        # user-turn 从此默认 True(若 config 未关)。
        enable_search: bool = bool(context.get("enable_search", get_enable_search()))
        # 同款:context 显式 enable_thinking 优先,缺则读 yaml(默 False)。
        # qwen3.x thinking model 默认开思考链 → first content token 严重滞后,
        # 关掉等于回到普通快速响应。模型非 thinking 时 client.py silent skip。
        enable_thinking: bool = bool(context.get("enable_thinking", get_enable_thinking()))
        skip_short_term: bool = bool(context.get("skip_short_term", False))
        # v4 segment 1: 见 handle() 注释,deterministic mode 依 turn_origin
        turn_origin: str = str(context.get("turn_origin") or "user")
        raw_char = payload.get("character_id")
        character_id: Optional[int] = (
            int(raw_char) if isinstance(raw_char, (int, str)) and str(raw_char).strip() else None
        )
        # Bug 1 修法:同源 conv_id 用于 short_term 过滤(audit_lost_replies.md)
        raw_conv = payload.get("conversation_id")
        conversation_id: Optional[int] = (
            int(raw_conv) if isinstance(raw_conv, (int, str)) and str(raw_conv).strip() else None
        )
        # 2026-06-19 · 图片输入(MVP)· 透传到 _build_messages
        raw_atts = payload.get("attachments") or []
        attachments: Optional[List[dict]] = (
            list(raw_atts) if isinstance(raw_atts, list) and raw_atts else None
        )

        # 2026-06-19 · image-only 允许(pin 1)
        if not user_id or (not text and not attachments):
            raise ValueError("payload must contain non-empty user_id and (text or attachments)")

        with timed("_build_messages"):
            messages = await _build_messages(
                user_id, text, tool_result,
                character_id=character_id,
                extra_system=extra_system,
                skip_short_term=skip_short_term,
                turn_origin=turn_origin,
                conversation_id=conversation_id,
                attachments=attachments,
            )

        prompt_str = json.dumps(messages, ensure_ascii=False)
        timing_logger.info(
            "[STAT] prompt_chars=%d prompt_messages=%d",
            len(prompt_str), len(messages),
        )

        max_rounds = 5  # cap tool-loop to avoid runaway
        round_idx = 0
        sentence_count = 0
        sent_buf = ""
        stream_t0 = time.perf_counter()

        while True:
            round_idx += 1
            if round_idx > max_rounds:
                logger.warning("ChatAgent: tool loop exceeded %d rounds, breaking", max_rounds)
                break

            llm_t0 = time.perf_counter()
            timing_logger.info("[TIME] LLM call start (round=%d)", round_idx)
            # bugfix-3.2.9: sanitize tool names (eg 'clipboard.summarize' →
            # 'clipboard_summarize') 防 DeepSeek/OpenAI strict schema 拒。
            # reverse_map 给后面 tool dispatch 反查回 ToolRegistry 原 key。
            # call_llm 内部还会 defensive 再跑一次 (幂等),且打 dispatcher log。
            san_tools, tool_name_rev_map = sanitize_tools_for_llm(_get_all_tools())
            # INVESTIGATION-3 第一刀 — token observation probe(纯观测,fail-silent,
            # 写一行 JSON 到 logs/token_probe.jsonl)。模块本身不读 DB 不调 LLM,
            # 任何异常 silent 吞 + debug log,绝不阻塞此 LLM 调用。
            try:
                from backend.agents._token_probe import emit_sync as _token_probe_emit
                _token_probe_emit(
                    conversation_id=conversation_id,
                    turn_n=round_idx,
                    messages=messages,
                    tools=san_tools,
                )
            except Exception:
                logger.debug("[token_probe] outer-guard skipped emit")
            try:
                wrapper = await call_llm(
                    messages,
                    stream=True,
                    tools=san_tools,
                    enable_search=enable_search,
                    enable_thinking=enable_thinking,
                    # INV-5 §5 Phase 4 step 3:让 stream 最后 chunk 含
                    # usage 字段(LiteLLM/OpenAI 行为),便于 probe 采
                    # cached_tokens / cache_creation_input_tokens 等。
                    stream_options={"include_usage": True},
                )
            except LLMError as exc:
                logger.error("ChatAgent LLM error: %s", exc)
                raise

            tool_calls_acc: Dict[int, Dict[str, Any]] = {}
            assistant_text = ""
            finish_reason: Optional[str] = None
            first_logged = False
            raw_count = 0
            last_chunk_usage: Optional[Any] = None  # INV-5 Phase 4: stream end usage

            async for chunk in wrapper:
                # LiteLLM stream end:chunk.choices 可能为 [] 但 chunk.usage 含数据
                _u = getattr(chunk, "usage", None)
                if _u is not None:
                    last_chunk_usage = _u
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                delta = choice.delta

                # Text delta — emit complete sentences as soon as boundary hits
                content = getattr(delta, "content", None)
                if content:
                    raw_count += 1
                    if not first_logged:
                        timing_logger.info(
                            "[TIME] LLM raw first chunk: %.0fms (round=%d)",
                            (time.perf_counter() - llm_t0) * 1000, round_idx,
                        )
                        first_logged = True
                    assistant_text += content
                    sent_buf += content
                    while True:
                        # v3-F：未闭合的 <thinking>...</thinking> 内不允许切句，
                        # 否则 thinking 内部的 。！？ 会把内心独白拦腰切开。
                        idx = _safe_boundary(sent_buf)
                        if idx == -1:
                            break
                        sentence = sent_buf[: idx + 1].strip()
                        sent_buf = sent_buf[idx + 1 :]
                        if sentence:
                            sentence_count += 1
                            timing_logger.info(
                                "[TIME] sentence yield #%d: %.0fms (len=%d)",
                                sentence_count,
                                (time.perf_counter() - stream_t0) * 1000,
                                len(sentence),
                            )
                            yield sentence

                # Tool-call delta — accumulate per index
                tool_deltas = getattr(delta, "tool_calls", None) or []
                for tc in tool_deltas:
                    idx = getattr(tc, "index", 0) or 0
                    entry = tool_calls_acc.setdefault(
                        idx, {"id": None, "name": "", "arguments": ""},
                    )
                    if getattr(tc, "id", None):
                        entry["id"] = tc.id
                    fn = getattr(tc, "function", None)
                    if fn is not None:
                        if getattr(fn, "name", None):
                            entry["name"] = fn.name
                        if getattr(fn, "arguments", None):
                            entry["arguments"] += fn.arguments

                fr = getattr(choice, "finish_reason", None)
                if fr:
                    finish_reason = fr

            timing_logger.info(
                "LLM round=%d raw_chunks=%d tool_calls=%d finish=%s",
                round_idx, raw_count, len(tool_calls_acc), finish_reason,
            )

            # INV-5 §5 Phase 4 step 3:stream 完成后 emit cache metrics row
            # (resp-side,按 conv_id + turn_n 与 pre-LLM emit 的 req row 配对)。
            # fail-silent,任何异常 outer-guard 吞 + debug log,不阻塞 turn。
            try:
                from backend.agents._token_probe import (
                    emit_cache_metrics_sync as _probe_cache_emit,
                )
                _probe_cache_emit(
                    conversation_id=conversation_id,
                    turn_n=round_idx,
                    usage=last_chunk_usage,
                )
            except Exception:
                logger.debug("[token_probe] cache_metrics outer-guard skipped")

            # Decide what to do next
            if tool_calls_acc:
                # Build the assistant message that requested the tool calls
                assistant_msg: dict = {
                    "role": "assistant",
                    "content": assistant_text or None,
                    "tool_calls": [
                        {
                            "id": v["id"] or f"call_{i}",
                            "type": "function",
                            "function": {
                                "name": v["name"],
                                "arguments": v["arguments"] or "{}",
                            },
                        }
                        for i, v in tool_calls_acc.items()
                    ],
                }
                messages.append(assistant_msg)

                # Execute each tool sequentially and append a tool-result message
                for i, v in tool_calls_acc.items():
                    san_name = v["name"]
                    # bugfix-3.2.9: LLM emit 的是 sanitized name (eg
                    # 'clipboard_summarize') — 反查回 original ('clipboard.summarize')
                    # 才能在 ToolRegistry / CapabilityRegistry 里找到 handler。
                    # 没改过的 name 不在 reverse_map 里 → 走 .get() fallback。
                    name = tool_name_rev_map.get(san_name, san_name)
                    raw_args = v["arguments"] or "{}"
                    logger.info(
                        "ChatAgent tool call: %s args=%s",
                        name, raw_args[:200],
                    )
                    # UX-004: emit tool_use_start before exec — frontend 据此
                    # 点亮 loading 指示器(基于 tool_name 前缀做 label mapping)。
                    # 用 original name 让前端的 label-mapping 按既有 prefix
                    # ('clipboard.', 'apple_calendar.') 工作。
                    yield {"type": "tool_use_start", "tool_name": name}
                    tool_t0 = time.perf_counter()
                    with timed(f"tool {name}"):
                        result = await _execute_tool(
                            user_id, name, raw_args, character_id=character_id,
                        )
                    duration_ms = int((time.perf_counter() - tool_t0) * 1000)
                    logger.info(
                        "ChatAgent tool result: %s -> %s (duration=%dms)",
                        name, json.dumps(result, ensure_ascii=False)[:200],
                        duration_ms,
                    )
                    # UX-004: emit tool_use_done with duration_ms — 未来 frontend
                    # 可基于慢工具(> 5s 之类)在 UI 给 "Momo 这个工具好慢哦" 反馈
                    yield {
                        "type": "tool_use_done",
                        "tool_name": name,
                        "duration_ms": duration_ms,
                    }
                    # 修法 B:tool result 截断防 multi-round input 膨胀
                    messages.append({
                        "role": "tool",
                        "tool_call_id": v["id"] or f"call_{i}",
                        "content": truncate_tool_result(result, tool_name=name),
                    })
                # Re-call LLM to let it produce the final response
                continue

            # No tool calls in this round — flush remaining buffer and finish
            remainder = sent_buf.strip()
            if remainder:
                sentence_count += 1
                timing_logger.info(
                    "[TIME] sentence yield #%d: %.0fms (len=%d, tail)",
                    sentence_count,
                    (time.perf_counter() - stream_t0) * 1000,
                    len(remainder),
                )
                yield remainder
                sent_buf = ""
            timing_logger.info("Sentence yields: %d", sentence_count)
            return
