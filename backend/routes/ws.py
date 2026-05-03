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

from backend.agents.chat import ChatAgent, _parse_emotion, _parse_thinking
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
# v3-F #3：TTS 多段并发合成
#
# - 句子从 ChatAgent.stream 出来，立即推 text_chunk 给前端，并 spawn 一个
#   asyncio.Task 做 synthesize；task 进 ordered queue。
# - 单独的 consumer task 顺序 await queue，保证音频按句序发送（前端按到达
#   顺序入播放队列）。
# - 信号量控制并发上限，避免被 cosyvoice 限流；超时返回 None 跳过。
# - emotion 整轮锁定（first sentence 决定后所有 task 共用同一 turn_emotion）。
# ---------------------------------------------------------------------------

TTS_CONCURRENCY = 3
TTS_TIMEOUT_S = 10.0
_tts_semaphore = asyncio.Semaphore(TTS_CONCURRENCY)


from typing import Awaitable, Callable

# audio_sender 接口：consumer 把成功合成的 wav bytes 交给 sender，
# 真实路径下封 base64 后 ws.send_json({"type":"audio_chunk",...})；
# 测试可以塞个直接 append 到 list 的 sender。
AudioSender = Callable[[bytes], Awaitable[None]]


async def _tts_synth_with_timeout(
    engine,  # backend.tts.base.TTSBase
    text: str,
    emotion: str,
    *,
    idx: int = 0,
    sem: asyncio.Semaphore = _tts_semaphore,
    timeout: float = TTS_TIMEOUT_S,
) -> Optional[bytes]:
    """节流 + 超时 + 异常兜底的单句合成。

    返回 None 表示本句失败 / 超时，consumer 应跳过。CancelledError 透传，
    便于打断（v3-F #4）外部 ``task.cancel()`` 立即生效。
    """
    t0 = time.perf_counter()
    async with sem:
        try:
            audio = await asyncio.wait_for(
                engine.synthesize(text, emotion=emotion),
                timeout=timeout,
            )
            timing_logger.info(
                "[TIME] TTS #%d: %.0fms len=%d",
                idx, (time.perf_counter() - t0) * 1000, len(text),
            )
            return audio
        except asyncio.TimeoutError:
            logger.warning(
                "[TTS] timeout %.1fs idx=%d sentence=%r",
                timeout, idx, text[:30],
            )
            return None
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "[TTS] error idx=%d: %s sentence=%r",
                idx, exc, text[:30],
            )
            return None


async def _tts_audio_consumer(
    queue: "asyncio.Queue[Optional[asyncio.Task[Optional[bytes]]]]",
    sender: AudioSender,
) -> None:
    """按 FIFO 顺序 await 队列里的 task；非空 audio 交给 sender。

    sender 异常 → 记录后继续（避免 producer 端阻塞）。``None`` 哨兵 → 退出。
    CancelledError 透传，外部 cancel 立即生效。
    """
    while True:
        item = await queue.get()
        if item is None:
            return
        try:
            audio = await item
        except asyncio.CancelledError:
            raise
        except Exception:
            audio = None
        if not audio:
            continue
        try:
            await sender(audio)
        except Exception as send_exc:
            logger.warning("[TTS] audio sender failed: %s", send_exc)

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
        # v3-F：内心独白每轮最多推送一次（解析到 <thinking> 后锁定）
        thinking_pushed = False
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

        # v3-F #3：TTS 并发合成 + 顺序播放
        # producer 把每句的 synth task 放进 audio_queue；consumer 按入队顺序
        # await 后 send audio_chunk。pending_tts 持引用便于异常时统一 cancel。
        audio_queue: "asyncio.Queue[Optional[asyncio.Task[Optional[bytes]]]]" = asyncio.Queue()
        pending_tts: List[asyncio.Task] = []

        async def _send_audio(audio: bytes) -> None:
            audio_b64 = base64.b64encode(audio).decode()
            await ws.send_json({"type": "audio_chunk", "content": audio_b64})

        consumer_task: Optional[asyncio.Task] = None
        try:
            with timed("ChatAgent total"):
                consumer_task = asyncio.create_task(
                    _tts_audio_consumer(audio_queue, _send_audio)
                )

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

                    # v3-F #2：剥离 <thinking>...</thinking> 内心独白；命中后单独 push
                    # 一次。chat.py 的 _safe_boundary 保证 thinking 块不会被
                    # sentence-stream 切开，所以同一句里看到完整闭合标签。
                    thinking_value, sentence = _parse_thinking(sentence)
                    if thinking_value and not thinking_pushed:
                        thinking_pushed = True
                        logger.info(
                            "[thinking] pushed (len=%d) user=%s",
                            len(thinking_value), user_id,
                        )
                        await ws.send_json({
                            "type": "thinking",
                            "value": thinking_value,
                        })

                    # 剥标签后可能为空（极端情况：句子只有标签），跳过本句
                    if not sentence.strip():
                        continue

                    reply_parts.append(sentence)
                    sentence_idx += 1

                    # 立即推送 text_chunk —— 不等 audio
                    payload = {"type": "text_chunk", "content": sentence}
                    payload_bytes = len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
                    ws_send_count += 1
                    with timed(f"WS send chunk #{sentence_idx} bytes={payload_bytes}"):
                        await ws.send_json(payload)

                    # v3-F #3：spawn TTS task 并入队；并发由 _tts_semaphore 节流，
                    # consumer 按入队顺序 await，保证 audio_chunk 顺序播放。
                    # turn_emotion 整轮一致；synthesize 内部 + _synth_one 双层
                    # try/except，永远不会抛到 producer。
                    if get_tts_enabled():
                        task = asyncio.create_task(
                            _tts_synth_with_timeout(
                                tts_engine, sentence, turn_emotion,
                                idx=sentence_idx,
                            )
                        )
                        pending_tts.append(task)
                        await audio_queue.put(task)

                # producer 结束：投递 None 哨兵让 consumer 退出
                await audio_queue.put(None)
                # 等 consumer 把所有 audio_chunk 发完，再发 done
                await consumer_task
                consumer_task = None

            timing_logger.info(
                "[TIME] Chat total: %.0fms",
                (time.perf_counter() - chat_t0) * 1000,
            )
            timing_logger.info(
                "WS text_chunk sends: %d, TTS tasks: %d",
                ws_send_count, len(pending_tts),
            )

        except Exception as exc:
            logger.exception("ChatAgent stream error for user %s", user_id)
            # 取消所有 pending TTS / consumer，避免悬挂任务
            for t in pending_tts:
                if not t.done():
                    t.cancel()
            if consumer_task is not None and not consumer_task.done():
                consumer_task.cancel()
            try:
                await ws.send_json({"type": "error", "message": str(exc)})
            except Exception:
                pass
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
