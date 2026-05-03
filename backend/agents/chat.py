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
from backend.database import AsyncSessionLocal
from backend.database.models import Memory
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


async def _sentence_stream(
    token_gen: AsyncGenerator[str, None],
) -> AsyncGenerator[str, None]:
    """Buffer tokens from *token_gen* and yield complete sentences."""
    buf = ""
    async for token in token_gen:
        buf += token
        while True:
            idx = _find_boundary(buf)
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
    "\n\n你有以下 tool 可用：\n"
    "记忆类：save_memory / delete_memory / list_memories / compress_memories。\n"
    "  - 当用户透露值得记住的事（事实、偏好、承诺、计划），主动调 save_memory；\n"
    "  - 当用户要求忘掉某事，先 list_memories 找匹配再 delete_memory；\n"
    "  - 当用户要求整理记忆，调 compress_memories。\n"
    "系统类：switch_character / clear_short_term。\n"
    "  - 仅当用户明确要求切换角色时调 switch_character；\n"
    "  - 仅当用户明确要求清空当前对话上下文时调 clear_short_term。\n"
    "不要每条都问'要记下来吗'，自然判断即可。"
    "调完 tool 后用一两句简短自然的中文回应用户。"
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

async def _build_messages(
    user_id: str,
    text: str,
    tool_result: str | None = None,
    character_id: Optional[int] = None,
) -> List[dict]:
    """Assemble the full message list to send to the LLM.

    System prompt order:
      1. Character persona (from prompt_manager, per-user character)
      2. Memory-tool usage instructions
      3. User profile summary (from users table)
      4. Long-term memory Top-5 (vector search)
      5. Tool result (legacy MemoryAgent pre-call result, if any)

    Short-term conversation history follows as real turns, then the current
    user message as the final entry.
    """
    # ---- 1. Persona (per-user, from characters.yaml) ----
    # v3-B 补丁：把 config.yaml 里的 base_instruction (通用设定) 拼到
    # persona 之前，作为所有角色共享的输出风格约束。空串则跳过。
    # v3-D 补丁：再前置一段情感标签指令，要求 LLM 在每次回复最开头打
    # <emotion>...</emotion>，供下游 TTS 路由使用；ws.py 会剥掉标签
    # 再下发 text_chunk，前端不会看到。
    prompt_data = prompt_manager.get_prompt(user_id)
    persona_block = prompt_data["system_prompt"] + _TOOL_PROMPT_ADDENDUM
    base = get_base_instruction().strip()
    emotion_inst = _build_emotion_instruction()
    head_parts = [emotion_inst]
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

    system_prompt = "\n\n".join(system_parts)

    # ---- Short-term history as conversation turns ----
    messages: List[dict] = [{"role": "system", "content": system_prompt}]
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
        tool_result: str | None = (payload.get("context") or {}).get("tool_result")
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
            messages = await _build_messages(user_id, text, tool_result, character_id=character_id)

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
        """
        payload = message.get("payload", {})
        user_id: str = payload.get("user_id", "")
        text: str = payload.get("text", "")
        tool_result: str | None = (payload.get("context") or {}).get("tool_result")
        raw_char = payload.get("character_id")
        character_id: Optional[int] = (
            int(raw_char) if isinstance(raw_char, (int, str)) and str(raw_char).strip() else None
        )

        if not user_id or not text:
            raise ValueError("payload must contain non-empty user_id and text")

        with timed("_build_messages"):
            messages = await _build_messages(user_id, text, tool_result, character_id=character_id)

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
                        idx = _find_boundary(sent_buf)
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
