"""WebSocket endpoint: full conversation pipeline.

v3-C 流程精简
-------------
receive (text | voice)
  └─ [voice] whisper_asr.transcribe_b64 → 写 chat_history → 推 asr_result
  └─ ChatAgent.stream()              ← 直接走，不再经 PlannerAgent
        tool calling（memory + builtin 统一）→ text_chunk → TTS → audio_chunk
  └─ send done
  └─ asyncio.create_task(_update_memory)   ← background, never blocks the reply

PlannerAgent / MemoryAgent / ToolAgent 仍保留在 backend/agents/ 下作为
软禁用代码，未在该路径被引用。如需恢复三分类路由，重新引入即可。

Wire format
-----------
Client → server:
  {"type": "text",  "content": "...", "user_id": "xxx"}
  {"type": "voice", "audio":   "<b64>", "user_id": "xxx"}

Server → client (streaming):
  {"type": "text_chunk",  "content": "..."}
  {"type": "audio_chunk", "content": "<b64>"}
  {"type": "done"}
  {"type": "error", "message": "..."}
"""
import asyncio
import base64
import json
import logging
import time
from typing import List

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from datetime import datetime
from typing import Optional, Tuple

from sqlalchemy import select

from backend.agents.chat import ChatAgent, _parse_emotion
from backend.asr.whisper import whisper_asr
from backend.config import config_yaml, get_planner_model, get_tts_enabled
from backend.config.prompt_manager import prompt_manager
from backend.database import AsyncSessionLocal
from backend.database.models import Character, Conversation
from backend.database.services import (
    add_chat_history,
    get_chat_history,
    get_profile_summary,
    update_profile_summary,
)
from backend.llm.client import LLMError, call_llm
from backend.memory.short_term import short_term_memory
from backend.tts import get_tts_engine, tts_manager  # noqa: F401  (manager 保留作为旧路径)
from backend.utils.timer import timed

timing_logger = logging.getLogger("momoos.timing")

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# ConnectionManager — push notifications from background tasks to frontend
# ---------------------------------------------------------------------------

class ConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[str, WebSocket] = {}

    def register(self, user_id: str, ws: WebSocket) -> None:
        self._connections[user_id] = ws

    def unregister(self, user_id: str) -> None:
        self._connections.pop(user_id, None)

    async def push(self, user_id: str, message: dict) -> None:
        ws = self._connections.get(user_id)
        if ws:
            await ws.send_json(message)


connection_manager = ConnectionManager()


# ---------------------------------------------------------------------------
# Module-level agent singleton (one shared across all WS connections)
#
# v3-C: PlannerAgent / MemoryAgent / ToolAgent 已退出主流程，意图识别 + tool
# 调度全部由 ChatAgent 通过 LiteLLM tool calling 完成。
# ---------------------------------------------------------------------------

_chat_agent = ChatAgent()

# ---------------------------------------------------------------------------
# profile_summary background regeneration (V2.5-D)
#
# Incremental update: each pass folds the most recent ~50 turns into the
# previous summary instead of rewriting from scratch, so stable traits stick
# while short-term observations refresh. Triggered both by the per-turn
# counter and by conversation deletion (so wiping all turns clears the
# summary too).
#
# IMPORTANT: PROFILE_SUMMARY_TURN_THRESHOLD is set to 5 for live testing; flip
# back to 50 once the end-to-end run is verified.
# ---------------------------------------------------------------------------

PROFILE_SUMMARY_TURN_THRESHOLD = 5
PROFILE_SUMMARY_HISTORY_LIMIT = 100   # pull last 100 chat_history rows = ~50 rounds
PROFILE_SUMMARY_MIN_ROWS = 20         # below this, skip — not enough signal
PROFILE_SUMMARY_MIN_OUTPUT_LEN = 50   # reject obviously-truncated LLM output
turn_count_per_user: dict[str, int] = {}


def _format_chat_history(rows: list) -> str:
    """Render chat_history rows as ``[role]: content`` lines, oldest-first."""
    return "\n".join(f"[{r.role}]: {r.content}" for r in rows)


def _build_profile_prompt(old_summary: Optional[str], history_text: str) -> str:
    """Build the incremental profile-update prompt fed to the planner LLM."""
    return f"""下面是用户与 Momo 最近的对话记录。请基于这些对话和已有的印象，更新你（Momo）对这个用户形成的整体印象。

当前印象（如有）：
{old_summary or "(暂无，第一次形成)"}

最近对话：
{history_text}

输出规则：
- 保留旧印象中的稳定特征（性格、职业、长期偏好、沟通风格）
- 调整最近的短期观察（情绪倾向、近期话题、状态变化）
- 不要罗列具体事实（"用户住北京"这种事实归记忆库管，不写进印象）
- 多用形容词描述这个人是怎样的，少用名词列他做了什么
- 300-500 字，3-7 句中文
- 直接输出印象段，不要加引号、标题、前后说明

新印象："""


async def _regenerate_profile_summary(user_id: str) -> None:
    """Refresh users.profile_summary from the latest chat_history.

    Behaviour:
      * 0 rows  → clear the column (user wiped everything).
      * <20 rows → skip (not enough signal yet).
      * otherwise → call planner LLM with incremental prompt + old summary.

    Always tolerant: any exception is logged at error level; the per-user
    counter is reset in ``finally`` so a failure never wedges future passes.
    """
    try:
        async with AsyncSessionLocal() as session:
            rows = await get_chat_history(
                session, user_id, limit=PROFILE_SUMMARY_HISTORY_LIMIT,
            )

        # 1. Empty history → clear the summary outright.
        if len(rows) == 0:
            async with AsyncSessionLocal() as session:
                await update_profile_summary(session, user_id, None)
            logger.info(
                "[profile_summary] cleared for user=%s (no chat history)",
                user_id,
            )
            return

        # 2. Too little signal — skip without touching the column.
        if len(rows) < PROFILE_SUMMARY_MIN_ROWS:
            logger.info(
                "[profile_summary] skip user=%s (only %d rows, need >= %d)",
                user_id, len(rows), PROFILE_SUMMARY_MIN_ROWS,
            )
            return

        # 3. Fold the new turns into the existing summary.
        async with AsyncSessionLocal() as session:
            old_summary = await get_profile_summary(session, user_id)

        prompt = _build_profile_prompt(old_summary, _format_chat_history(rows))

        try:
            response = await call_llm(
                messages=[{"role": "user", "content": prompt}],
                model=get_planner_model(),
                stream=False,
            )
            new_summary = (response.choices[0].message.content or "").strip()
        except LLMError as exc:
            logger.error(
                "[profile_summary] LLM call failed for user=%s: %s",
                user_id, exc,
            )
            return

        if not new_summary or len(new_summary) < PROFILE_SUMMARY_MIN_OUTPUT_LEN:
            logger.error(
                "[profile_summary] empty/too-short LLM output for user=%s: %r",
                user_id, new_summary,
            )
            return

        async with AsyncSessionLocal() as session:
            await update_profile_summary(session, user_id, new_summary)
        logger.info(
            "[profile_summary] regenerated for user=%s len=%d",
            user_id, len(new_summary),
        )
    except Exception as exc:
        logger.error(
            "[profile_summary] unexpected error for user=%s: %s",
            user_id, exc,
        )
    finally:
        # Reset the counter regardless of success/failure so transient errors
        # don't leave a user permanently stuck above threshold.
        turn_count_per_user[user_id] = 0


def _bump_turn_and_maybe_regenerate(user_id: str) -> None:
    """Increment per-user turn counter; spawn background task at threshold."""
    n = turn_count_per_user.get(user_id, 0) + 1
    if n >= PROFILE_SUMMARY_TURN_THRESHOLD:
        # Counter is reset inside _regenerate_profile_summary's finally block,
        # so we don't pre-zero here — that would race with concurrent turns.
        asyncio.create_task(_regenerate_profile_summary(user_id))
    else:
        turn_count_per_user[user_id] = n


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _default_user_id() -> str:
    return config_yaml.get("default_user_id", "default")


async def _resolve_conv_char(
    user_id: str,
    incoming_conv: Optional[int],
    incoming_char: Optional[int],
) -> Tuple[Optional[int], Optional[int]]:
    """Backwards-compatible resolution for v2 frontends that don't send IDs.

    - character_id: use incoming if provided, else look up Momo by name.
    - conversation_id: use incoming if provided, else pick the user's
      most-recently-updated conversation.
    Returns (conv_id_or_None, char_id_or_None). Either may be None if the
    DB has no matching row (eg. fresh install before migration ran).
    """
    async with AsyncSessionLocal() as session:
        char_id = incoming_char
        if char_id is None:
            row = (await session.execute(
                select(Character.id).where(Character.name == "Momo")
            )).scalar_one_or_none()
            if row is not None:
                char_id = int(row)

        conv_id = incoming_conv
        if conv_id is None:
            row = (await session.execute(
                select(Conversation.id)
                .where(Conversation.user_id == user_id)
                .order_by(Conversation.updated_at.desc())
                .limit(1)
            )).scalar_one_or_none()
            if row is not None:
                conv_id = int(row)
    return conv_id, char_id


async def _bump_conversation_updated_at(conv_id: int) -> None:
    """Set conversations.updated_at = utcnow() for the given conversation."""
    async with AsyncSessionLocal() as session:
        c = (await session.execute(
            select(Conversation).where(Conversation.id == conv_id)
        )).scalar_one_or_none()
        if c is not None:
            c.updated_at = datetime.utcnow()
            await session.commit()


async def _update_memory(
    user_id: str,
    user_text: str,
    reply: str,
    conversation_id: Optional[int] = None,
    character_id: Optional[int] = None,
    skip_user_history: bool = False,
) -> None:
    """Persist the conversation turn to short-term buffer and chat_history.

    Long-term memory is produced by the LLM via the save_memory tool
    (see backend/agents/chat.py). conversations.updated_at is bumped so the
    sidebar list shows the freshly-active conversation at the top.

    V2.5-C2a: skip_user_history=True when the user-side row was already
    persisted earlier in the turn (e.g. ASR transcript was written before the
    pipeline started, so we only need the assistant row here).
    """
    try:
        await short_term_memory.add(user_id, "user",      user_text)
        await short_term_memory.add(user_id, "assistant", reply)

        async with AsyncSessionLocal() as session:
            if not skip_user_history:
                await add_chat_history(
                    session, user_id, "user", user_text,
                    conversation_id=conversation_id,
                    character_id=character_id,
                )
            await add_chat_history(
                session, user_id, "assistant", reply,
                conversation_id=conversation_id,
                character_id=character_id,
            )

        if conversation_id is not None:
            await _bump_conversation_updated_at(conversation_id)

        _bump_turn_and_maybe_regenerate(user_id)
    except Exception:
        logger.exception("_update_memory failed for user %s", user_id)


# ---------------------------------------------------------------------------
# Per-message pipeline
# ---------------------------------------------------------------------------

async def _handle_message(ws: WebSocket, data: dict) -> None:
    user_id  = (data.get("user_id") or "").strip() or _default_user_id()
    msg_type = data.get("type", "text")

    # V2.5-C: conversation_id / character_id are optional for back-compat.
    # If absent we fall back to the user's most-recent conversation + Momo.
    raw_conv = data.get("conversation_id")
    raw_char = data.get("character_id")
    incoming_conv: Optional[int] = int(raw_conv) if raw_conv is not None else None
    incoming_char: Optional[int] = int(raw_char) if raw_char is not None else None
    conv_id, char_id = await _resolve_conv_char(user_id, incoming_conv, incoming_char)

    user_history_already_written = False

    with timed("Total turn"):
        # ── 1. Resolve text ─────────────────────────────────────────────────
        if msg_type == "voice":
            b64_audio = data.get("audio", "")
            if not b64_audio:
                await ws.send_json({"type": "error", "message": "Missing audio field"})
                return
            try:
                with timed("ASR"):
                    text = await whisper_asr.transcribe_b64(b64_audio)
            except Exception as exc:
                logger.warning("ASR failed: %s", exc)
                await ws.send_json({"type": "error", "message": f"ASR failed: {exc}"})
                return

            # Persist the user-side transcript immediately so it's reachable
            # from chat_history / chatMessages, then push asr_result with the
            # row id so the frontend can mirror it into its in-memory list.
            asr_message_id: Optional[int] = None
            if text.strip():
                try:
                    async with AsyncSessionLocal() as session:
                        row = await add_chat_history(
                            session, user_id, "user", text,
                            conversation_id=conv_id,
                            character_id=char_id,
                        )
                        asr_message_id = row.id
                    user_history_already_written = True
                except Exception:
                    logger.exception("ASR chat_history persist failed for user %s", user_id)
            await ws.send_json({
                "type": "asr_result",
                "content": text,
                "message_id": asr_message_id,
            })
        else:
            text = (data.get("content") or "").strip()

        if not text:
            await ws.send_json({"type": "error", "message": "Empty input"})
            return

        # ── 2. ChatAgent stream + TTS ────────────────────────────────────────
        # v3-C：直接走 ChatAgent，意图识别 / 记忆 tool / 内置工具调度全部
        # 由 LiteLLM tool calling 在 ChatAgent.stream() 内统一处理。
        # v3-D：TTS 路由从静态 character-name 改为按 character.voice_model
        #        JSON。voice_model 为空时 get_tts_engine 会用全局默认。
        character = prompt_manager.get_current_character(user_id)

        # 读取当前 character 的 voice_model（可能为 None / 空串 / 合法 JSON）
        voice_model: Optional[str] = None
        if char_id is not None:
            try:
                async with AsyncSessionLocal() as session:
                    row = (await session.execute(
                        select(Character.voice_model).where(Character.id == char_id)
                    )).scalar_one_or_none()
                    voice_model = row if isinstance(row, str) else None
            except Exception:
                logger.exception(
                    "Failed to load character.voice_model for id=%s", char_id,
                )

        tts_engine = get_tts_engine(voice_model)
        # 同一轮对话用同一情感（由第一句的 <emotion> 标签决定）
        turn_emotion = "默认"
        emotion_resolved = False
        logger.info(
            "[TTS] turn start user=%s char_id=%s voice_model=%s engine=%s",
            user_id, char_id,
            (voice_model or "<default>")[:80],
            type(tts_engine).__name__,
        )

        chat_msg = {
            "agent": "ChatAgent",
            "payload": {
                "user_id":      user_id,
                "text":         text,
                "character_id": char_id,
            },
        }

        reply_parts: List[str] = []
        chat_t0 = time.perf_counter()
        first_chunk_logged = False
        sentence_idx = 0
        ws_send_count = 0
        try:
            with timed("ChatAgent total"):
                async for sentence in _chat_agent.stream(chat_msg):
                    if not first_chunk_logged:
                        timing_logger.info(
                            "[TIME] Chat first chunk: %.0fms",
                            (time.perf_counter() - chat_t0) * 1000,
                        )
                        first_chunk_logged = True

                    # v3-D：第一句剥离 <emotion> 标签，整轮情感锁定下来
                    if not emotion_resolved:
                        parsed_emotion, sentence = _parse_emotion(sentence)
                        turn_emotion = parsed_emotion
                        emotion_resolved = True
                        logger.info(
                            "[TTS] emotion=%s (parsed from first chunk)",
                            turn_emotion,
                        )

                    # 剥标签后可能为空（极端情况：第一句只有标签），跳过本句
                    if not sentence.strip():
                        continue

                    reply_parts.append(sentence)
                    sentence_idx += 1

                    # Send text immediately — per-send timer to spot WS push backpressure.
                    payload = {"type": "text_chunk", "content": sentence}
                    payload_bytes = len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
                    ws_send_count += 1
                    with timed(f"WS send chunk #{sentence_idx} bytes={payload_bytes}"):
                        await ws.send_json(payload)

                    # TTS — best-effort, never blocks text delivery.
                    # engine.synthesize 内部已 try/except，失败返回 None。
                    if get_tts_enabled():
                        try:
                            with timed(f"TTS sentence #{sentence_idx}"):
                                audio_bytes = await tts_engine.synthesize(
                                    sentence, emotion=turn_emotion,
                                )
                            if audio_bytes:
                                audio_b64 = base64.b64encode(audio_bytes).decode()
                                await ws.send_json({"type": "audio_chunk", "content": audio_b64})
                        except Exception as tts_exc:
                            logger.warning(
                                "TTS skipped for sentence (%s): %s",
                                sentence[:20], tts_exc,
                            )

            timing_logger.info(
                "[TIME] Chat total: %.0fms",
                (time.perf_counter() - chat_t0) * 1000,
            )
            timing_logger.info("WS text_chunk sends: %d", ws_send_count)

        except Exception as exc:
            logger.exception("ChatAgent stream error for user %s", user_id)
            await ws.send_json({"type": "error", "message": str(exc)})
            return

        await ws.send_json({"type": "done"})

        # ── 3. Background memory update ─────────────────────────────────────
        full_reply = "".join(reply_parts)
        asyncio.create_task(_update_memory(
            user_id, text, full_reply,
            conversation_id=conv_id,
            character_id=char_id,
            skip_user_history=user_history_already_written,
        ))


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """Stream-based conversation endpoint.

    Clients send one JSON message per turn; the server streams back
    text_chunk / audio_chunk frames and closes with a done frame.
    The connection stays open for multiple turns.
    """
    await websocket.accept()
    user_id = _default_user_id()
    connection_manager.register(user_id, websocket)
    logger.info("WebSocket connection opened")
    try:
        while True:
            data: dict = await websocket.receive_json()
            try:
                await _handle_message(websocket, data)
            except WebSocketDisconnect:
                raise                        # propagate to outer handler
            except Exception as exc:
                logger.exception("Unhandled error in _handle_message")
                try:
                    await websocket.send_json({"type": "error", "message": str(exc)})
                except Exception:
                    pass
    except WebSocketDisconnect:
        logger.info("WebSocket connection closed")
    finally:
        connection_manager.unregister(user_id)
