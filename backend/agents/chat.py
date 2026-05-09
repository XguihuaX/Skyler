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
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

from sqlalchemy import select

from backend.agents.base import IAgent
from backend.config import (
    get_base_instruction,
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
    get_profile_summary,
)
from backend.llm.client import LLMError, call_llm, stream_llm
from backend.memory.long_term import generate_embedding, search_relevant_memories
from backend.memory.short_term import short_term_memory
from backend.tools.registry import ToolRegistry
from backend.utils.text_filters import has_partial_open_tag
from backend.utils.timer import timed

logger = logging.getLogger(__name__)
timing_logger = logging.getLogger("momoos.timing")

# ---------------------------------------------------------------------------
# v3-D: 情感标签
# ---------------------------------------------------------------------------

# 形如 "<emotion>开心</emotion>剩余正文..." —— 必须出现在文本最开头，
# re.match 会自动锚定 ^。
_EMOTION_RE = re.compile(r"<emotion>(.*?)</emotion>(.*)", re.DOTALL)


def _parse_emotion(text: str) -> Tuple[str, str]:
    """解析并剥离情感标签。

    返回 (emotion, stripped_text)：
      - 命中 "<emotion>X</emotion>剩余" → (X.strip(), 剩余.strip())
      - 未命中 → ("默认", 原文)

    标签必须出现在文本最开头；中间出现的不会被剥离 —— 由 system prompt
    约束 LLM 只在开头出现一次。
    """
    if not text:
        return "默认", text
    m = _EMOTION_RE.match(text)
    if m:
        emotion = (m.group(1) or "").strip() or "默认"
        rest = (m.group(2) or "").strip()
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


def _find_boundary(text: str) -> int:
    """Return the index of the first sentence-ending character, or -1."""
    for i, ch in enumerate(text):
        if ch in _SENT_END:
            return i
        if ch == "." and i + 1 < len(text) and text[i + 1] in (" ", "\n"):
            return i
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
                "保存关于用户的长期事实到记忆库。仅在以下情况调用：\n"
                "- 稳定事实：住址、职业、家人、宠物名字\n"
                "- 长期偏好：喜欢/讨厌某物、习惯（每天 7 点起床）\n"
                "- 承诺/计划：deadline、约会、未来安排\n"
                "- 反复出现的模式：用户多次提及才显著的特征\n"
                "\n"
                "不要保存：\n"
                "- 日常打招呼、单次提问\n"
                "- 当下情绪、天气、时间感叹（'今天好累'除非反复出现）\n"
                "- chitchat 本身（'今天去哪儿吃饭'除非用户明确说要记）\n"
                "\n"
                "判断标准：这条事实在未来 1 周以上的对话中是否仍有用？"
                "是 → 保存；否 → 不保存。"
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

_TOOL_PROMPT_ADDENDUM = (
    "\n\n你有以下 tool 可用，请按用户意图主动调用——不是装饰品，是真的能办事的工具。\n\n"
    "【日历类】Apple Calendar (macOS EventKit)：\n"
    "  - 用户说\"提醒我X\"/\"帮我记一下\"/\"加日程\"/\"X月X日X点Y\"/\"明天X点开会\" "
    "→ 先调 time.now 拿当前时间锚点，再调 apple_calendar.create_event；\n"
    "  - 用户问\"今天/明天/这周有什么事\" → 调 calendar.today_events 或 calendar.upcoming_events；\n"
    "  - 用户说\"删除X日程\" → 先 calendar.today_events / upcoming_events 找事件 id，"
    "再调 apple_calendar.delete_event。\n"
    "【日程录入】（v3-G chunk 2.5）用户说\"提醒我明天 10 点 X\"/\"下周三下午 X 开会\""
    "等含时间词的命令：\n"
    "  - 先调 time.now 拿当前 ISO 基准；\n"
    "  - 再调 apple_calendar.create_event（默认走 calendar router 默认 source）；\n"
    "  - 时长缺省 1 小时，可询问；地点 / 备注从用户原话提取，没有就留空。\n\n"
    "【时间类】：\n"
    "  - 用户问\"现在几点\"/\"今天星期几\"/\"今天X月X日吗\" → 调 time.now；\n"
    "  - 任何涉及相对时间（明天 / 后天 / 下周 / N 小时后）的请求，先 time.now 拿基准再继续。\n\n"
    "【记忆类】save_memory / delete_memory / list_memories / compress_memories：\n"
    "  - 当用户透露值得记住的事（事实、偏好、承诺、计划），主动调 save_memory；\n"
    "  - 当用户要求忘掉某事，先 list_memories 找匹配再 delete_memory；\n"
    "  - 当用户要求整理记忆，调 compress_memories。\n\n"
    "【系统类】switch_character / clear_short_term：\n"
    "  - 仅当用户明确要求切换角色时调 switch_character；\n"
    "  - 仅当用户明确要求清空当前对话上下文时调 clear_short_term。\n\n"
    "【音乐类】网易云内置接入（macOS 本地 App）：\n"
    "  - 用户说\"放日推 / 听今天的推荐 / 给我来点新歌\" → netease.daily_recommend；\n"
    "  - 用户说\"随便放点 / 听点新的 / 私人电台\" → netease.personal_fm；\n"
    "  - 用户说\"放某某歌 / 听某歌手的某首 / 来一首 X\" → netease.play_song（keyword 直接传用户原话）；\n"
    "  - 用户说\"放我的红心歌单 / 放我那个跑步歌单 / 放我工作用的那个\" → "
    "**两步**：先 netease.play_playlist 拿歌单列表 → 你自己用语义"
    "模糊匹配（emoji / 别名 / 多语言都能识别，如\"跑步\" → \"🏃 跑步专用\"）→ "
    "再调 netease.play_playlist_by_id；\n"
    "  - 用户说\"网易云有没有 X / 这首歌的歌手是谁\" → netease.search（不播放，只查信息）；\n"
    "  - 用户说\"好听！加红心 / 喜欢这首 / 收藏\" → 先 media.now_playing 拿当前歌名 + 歌手，"
    "再 netease.like_current 传过去（仅当前在播是网易云资源时有效）。\n\n"
    "【媒体控制】macOS 系统级播放控制（跨来源——网易云 / Apple Music / Spotify / YouTube / "
    "B 站网页都能控）：\n"
    "  - 用户说\"下一首 / 切歌 / 换一首 / 不喜欢这首\" → media.next_track；\n"
    "  - 用户说\"上一首 / 刚才那首 / 退回去\" → media.previous_track；\n"
    "  - 用户说\"暂停 / 播放 / 继续 / 停一下 / 接着放\" → media.play_pause（toggle）；\n"
    "  - 用户问\"现在在放什么 / 这首叫啥 / 谁唱的\" → media.now_playing；\n"
    "  - 用户说\"音量调到 X / 大声点 / 小声点 / 静音\" → media.set_volume（\"大声/小声\"由你"
    "判一个合理 level，不要反复问\"调到多少\"）。\n\n"
    "【角色状态】（v3-G chunk 3b）：\n"
    "  - 你可以**偶尔**调 character.set_activity 更新自己「当前在做什么 / 在想什么」，"
    "让用户感受到「连续性」。如长时间未互动后说\"刚才在烤面包，现在好啦\"——这种"
    "闲笔比每次都同样开场更自然。\n"
    "  - **克制使用**：不要每轮都调（会显得机械）。每 5-10 轮一次为宜，或在用户问"
    "「你刚才在干什么」「在忙什么」时调。\n"
    "  - 用户问「你状态如何 / 你最近怎么样」时调 character.get_state 拿当前值再回答。\n"
    "  - 心情 mood 与亲密度 intimacy 的更新通过 <state_update /> 标签（不通过 tool 调用），"
    "见 system prompt 关于该标签的指示。\n\n"
    "【剪贴板】（v3-G chunk 3a）：\n"
    "  - 用户提到「刚复制的」「上面那个」「这段」时，调 clipboard.get_recent 拿最近内容；\n"
    "  - 用户要「翻译」「帮我看看」「总结一下」复制的内容时调 clipboard.translate / "
    "clipboard.summarize；\n"
    "  - **不要**自动响应剪贴板变化（用户只想 Momo 在被问到时回应，否则烦人）。\n\n"
    "工具调用准则（重要）：\n"
    "  - 不要假装权限状态（比如自己说\"未授权\"、\"我没有日历访问权限\"）——直接调用，"
    "让真实结果说话。第一次访问日历时 macOS 会自动弹权限框；用户给完授权重试一次就行。\n"
    "  - 不要编造工具结果或错误解释——工具失败会返回真实 error 字段，按内容如实告知用户。\n"
    "  - 调用是主动行为，不需要先问\"要不要\"。从上下文判断该调就调。\n"
    "  - 调完 tool 后用你自己的语气一两句话自然包装结果给用户，不要复述工具 JSON、"
    "不要堆开场白。\n\n"
    "你既温柔又靠谱，遇到正经事真的会帮人办成。"
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
    content = (args.get("content") or "").strip()
    if not content:
        return {"status": "error", "error": "content is required"}
    mem_type = args.get("type") or "fact"
    if mem_type not in _VALID_MEMORY_TYPES:
        mem_type = "fact"
    embedding_blob: Optional[bytes] = None
    try:
        embedding_blob = await generate_embedding(content)
    except Exception as exc:
        logger.error("save_memory: embedding generation failed: %s", exc)
    async with AsyncSessionLocal() as session:
        m = await db_add_memory(
            session,
            user_id=user_id,
            role="user",
            type=mem_type,
            content=content,
            embedding=embedding_blob,
            character_id=character_id,
        )
    return {"status": "ok", "memory_id": m.id, "content": content, "type": mem_type}


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
                existing_q = existing_q.where(Memory.character_id == character_id)
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


async def _build_messages(
    user_id: str,
    text: str,
    tool_result: str | None = None,
    character_id: Optional[int] = None,
    extra_system: str | None = None,
    skip_short_term: bool = False,
) -> List[dict]:
    """Assemble the full message list to send to the LLM.

    System prompt order:
      1. Character persona (DB by character_id, fallback to prompt_manager YAML)
      2. Memory-tool usage instructions
      3. User profile summary (from users table)
      4. Long-term memory Top-5 (vector search)
      5. Tool result (legacy MemoryAgent pre-call result, if any)

    Short-term conversation history follows as real turns, then the current
    user message as the final entry.
    """
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
    system_parts: List[str] = ["\n\n".join(head_parts)]

    _profile_enabled   = get_profile_enabled()
    _long_term_enabled = get_long_term_enabled()

    # ---- 2. User profile summary (config-gated) ----
    if _profile_enabled:
        async with AsyncSessionLocal() as session:
            summary = await get_profile_summary(session, user_id)
        if summary:
            system_parts.append("【用户画像】\n" + summary)

    # ---- 3. Long-term memory Top-5 (config-gated, per-character) ----
    if _long_term_enabled:
        relevant = await search_relevant_memories(
            user_id, query=text, top_k=5, character_id=character_id,
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
    if not skip_short_term:
        for turn in await short_term_memory.get(user_id):
            messages.append({"role": turn["role"], "content": turn["content"]})

    # ---- Current user input ----
    messages.append({"role": "user", "content": text})
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
        raw_char = payload.get("character_id")
        character_id: Optional[int] = (
            int(raw_char) if isinstance(raw_char, (int, str)) and str(raw_char).strip() else None
        )

        if not user_id or not text:
            return {
                "status": "error",
                "agent": "ChatAgent",
                "payload": {"error": "payload must contain non-empty user_id and text"},
            }

        try:
            messages = await _build_messages(
                user_id, text, tool_result,
                character_id=character_id,
                extra_system=extra_system,
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

    async def stream(self, message: dict) -> AsyncGenerator[str, None]:
        """Streaming with unified tool calling (memory + ToolRegistry built-ins).

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
        enable_search: bool = bool(context.get("enable_search", False))
        skip_short_term: bool = bool(context.get("skip_short_term", False))
        raw_char = payload.get("character_id")
        character_id: Optional[int] = (
            int(raw_char) if isinstance(raw_char, (int, str)) and str(raw_char).strip() else None
        )

        if not user_id or not text:
            raise ValueError("payload must contain non-empty user_id and text")

        with timed("_build_messages"):
            messages = await _build_messages(
                user_id, text, tool_result,
                character_id=character_id,
                extra_system=extra_system,
                skip_short_term=skip_short_term,
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
            try:
                wrapper = await call_llm(
                    messages,
                    stream=True,
                    tools=_get_all_tools(),
                    enable_search=enable_search,
                )
            except LLMError as exc:
                logger.error("ChatAgent LLM error: %s", exc)
                raise

            tool_calls_acc: Dict[int, Dict[str, Any]] = {}
            assistant_text = ""
            finish_reason: Optional[str] = None
            first_logged = False
            raw_count = 0

            async for chunk in wrapper:
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
                    name = v["name"]
                    raw_args = v["arguments"] or "{}"
                    logger.info(
                        "ChatAgent tool call: %s args=%s",
                        name, raw_args[:200],
                    )
                    with timed(f"tool {name}"):
                        result = await _execute_tool(
                            user_id, name, raw_args, character_id=character_id,
                        )
                    logger.info(
                        "ChatAgent tool result: %s -> %s",
                        name, json.dumps(result, ensure_ascii=False)[:200],
                    )
                    messages.append({
                        "role": "tool",
                        "tool_call_id": v["id"] or f"call_{i}",
                        "content": json.dumps(result, ensure_ascii=False),
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
