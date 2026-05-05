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
  {"type": "text",      "content": "...", "user_id": "xxx"}
  {"type": "voice",     "audio":   "<b64>", "user_id": "xxx"}
  {"type": "interrupt"}                                        # v3-F #4
  {"type": "touch",     "user_id": "xxx",                       # v3-E1 step3
                        "conversation_id": int|None,
                        "character_id":    int|None}
    # 用户点 Live2D canvas → 注入 system 指令走正常 chat 流程，
    # user 占位符 "[touch]" 入 chat_history。

Server → client (streaming):
  {"type": "asr_result",  "content": "...", "message_id": int|None}
  {"type": "text_chunk",  "content": "..."}
  {"type": "audio_chunk", "content": "<b64>"}
  {"type": "thinking",    "value":   "..."}                    # v3-F
  {"type": "done",        "interrupted": bool}                 # v3-F #4
  {"type": "notify" / "alarm", ...}                            # 来自后台任务
  {"type": "error",       "message": "..."}
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

from backend.agents.chat import ChatAgent, _parse_emotion, _parse_motion, _parse_thinking
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
from backend.utils.text_filters import strip_thinking
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


# v3-E1 step3：触摸事件占位 + 临时 system 指令
# user content 存 [touch] 而不是空串，方便在 chat_history viewer 里识别这一轮
# 是怎么开始的；指令文本通过 chat_msg.payload.context.extra_system 注入到
# system prompt（_build_messages 第 5 段）。
TOUCH_USER_CONTENT = "[touch]"
TOUCH_INSTRUCTION = (
    "用户刚刚轻轻碰了一下你。请用一两句话自然反应一下，"
    "符合你当前的人设和情绪。"
)


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
            # v3-E1 Step Z.2：白名单只取 'normal' 行 —— touch / proactive 触发的
            # 对话 user 占位（[touch]）+ AI 主动回复一句不应作为画像样本。
            # 用白名单而非黑名单：未来新增 kind 时默认排除，不会沉默污染画像。
            rows = await get_chat_history(
                session, user_id,
                limit=PROFILE_SUMMARY_HISTORY_LIMIT,
                kinds=["normal"],
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
    kind: str = "normal",
) -> None:
    """Persist the conversation turn to short-term buffer and chat_history.

    Long-term memory is produced by the LLM via the save_memory tool
    (see backend/agents/chat.py). conversations.updated_at is bumped so the
    sidebar list shows the freshly-active conversation at the top.

    V2.5-C2a: skip_user_history=True when the user-side row was already
    persisted earlier in the turn (e.g. ASR transcript was written before the
    pipeline started, so we only need the assistant row here).

    v3-E1 Step Z.2: ``kind`` 同时打在 user 和 assistant 两行上 —— 一对
    （[touch] + AI 回应）逻辑上是同源的，profile_summary 用整对过滤。
    """
    # v3-F 回归修：流式按句剥 thinking（chat.py _parse_thinking）有边界漏网，
    # 写库前再剥一道，确保 short_term + chat_history 都不带 <thinking> 标签。
    reply = strip_thinking(reply)
    try:
        await short_term_memory.add(user_id, "user",      user_text)
        await short_term_memory.add(user_id, "assistant", reply)

        async with AsyncSessionLocal() as session:
            if not skip_user_history:
                await add_chat_history(
                    session, user_id, "user", user_text,
                    conversation_id=conversation_id,
                    character_id=character_id,
                    kind=kind,
                )
            await add_chat_history(
                session, user_id, "assistant", reply,
                conversation_id=conversation_id,
                character_id=character_id,
                kind=kind,
            )

        if conversation_id is not None:
            await _bump_conversation_updated_at(conversation_id)

        _bump_turn_and_maybe_regenerate(user_id)
    except Exception:
        logger.exception("_update_memory failed for user %s", user_id)


# ---------------------------------------------------------------------------
# v3-F #4：语音打断 —— per-connection turn state + 中断收尾
# ---------------------------------------------------------------------------


class _TurnState:
    """Per-WebSocket-connection 的当前 turn 状态。

    interrupt 收到时需要：
      - 取消正在运行的 ``current_turn``（_handle_message_safe wrapping task）
      - 取消所有 in-flight TTS task（``pending_tts``）
      - 把已生成的 ``reply_parts`` 写入 chat_history with ``interrupted_at``

    每收到一个新 user 消息时由 ``reset_for_new_turn`` 清零。``current_turn``
    本身由端点循环管理。
    """

    def __init__(self) -> None:
        self.current_turn: Optional[asyncio.Task] = None
        self.pending_tts: List[asyncio.Task] = []
        self.reply_parts: List[str] = []
        self.user_text: str = ""
        self.conv_id: Optional[int] = None
        self.char_id: Optional[int] = None
        self.user_history_already_written: bool = False
        # Set True 当端点收到 interrupt → 让 _handle_message_safe 走 interrupted 收尾
        self.interrupted: bool = False
        # v3-E1 Step Z.2：本轮 kind ('normal' / 'touch' / 'proactive')。
        # 让 _save_interrupted_turn 也能给 partial reply 打上正确 kind。
        self.kind: str = "normal"

    def reset_for_new_turn(self) -> None:
        # 不动 current_turn —— 由调用方（端点）保证已 cancel + await
        self.pending_tts = []
        self.reply_parts = []
        self.user_text = ""
        self.conv_id = None
        self.char_id = None
        self.user_history_already_written = False
        self.interrupted = False
        self.kind = "normal"


async def _save_interrupted_turn(state: "_TurnState", user_id: str) -> None:
    """打断收尾：partial reply 写 chat_history 并标 interrupted_at。

    与 ``_update_memory`` 区别：
      * assistant 行带 ``interrupted_at = utcnow()``
      * 不调 ``_bump_turn_and_maybe_regenerate``（被打断的轮不代表用户画像）
      * reply 为空 → 只保留 user 行（如未写过），不写空 assistant 行
    """
    if not state.user_text:
        return  # nothing to record

    # v3-F 回归修：被打断时 reply_parts 可能在 thinking 块内部被 cancel，
    # 残留半个标签 —— strip_thinking 只剥完整对，半截开标签会留下。
    # 前端渲染层有兜底正则再扫一次，最差只是多保留一段没意义的字符串。
    full_reply = strip_thinking("".join(state.reply_parts)).strip()
    interrupted_at = datetime.utcnow()

    try:
        # short-term：被打断的也算一轮（让 LLM 下轮知道说到哪儿了）
        await short_term_memory.add(user_id, "user", state.user_text)
        if full_reply:
            await short_term_memory.add(user_id, "assistant", full_reply)

        async with AsyncSessionLocal() as session:
            if not state.user_history_already_written:
                await add_chat_history(
                    session, user_id, "user", state.user_text,
                    conversation_id=state.conv_id,
                    character_id=state.char_id,
                    kind=state.kind,
                )
            if full_reply:
                await add_chat_history(
                    session, user_id, "assistant", full_reply,
                    conversation_id=state.conv_id,
                    character_id=state.char_id,
                    interrupted_at=interrupted_at,
                    kind=state.kind,
                )

        if state.conv_id is not None:
            await _bump_conversation_updated_at(state.conv_id)

        logger.info(
            "[interrupt] saved partial reply user=%s reply_len=%d at=%s",
            user_id, len(full_reply), interrupted_at.isoformat(),
        )
    except Exception:
        logger.exception(
            "_save_interrupted_turn failed for user %s", user_id,
        )


def _request_interrupt(state: "_TurnState") -> None:
    """同步触发打断：cancel current_turn + 全部 pending TTS。

    不 await。``_handle_message_safe`` 的 CancelledError 兜底负责 DB 收尾 +
    送 done 给前端。pending_tts 单独 cancel —— 它们是独立 task，不是
    current_turn 的子，不会因 turn cancel 自动停。
    """
    state.interrupted = True
    if state.current_turn is not None and not state.current_turn.done():
        state.current_turn.cancel()
    for t in list(state.pending_tts):
        if not t.done():
            t.cancel()


# ---------------------------------------------------------------------------
# Per-message pipeline
# ---------------------------------------------------------------------------

async def _handle_message(
    ws: WebSocket, data: dict, state: "_TurnState",
) -> None:
    user_id  = (data.get("user_id") or "").strip() or _default_user_id()
    msg_type = data.get("type", "text")

    # V2.5-C: conversation_id / character_id are optional for back-compat.
    # If absent we fall back to the user's most-recent conversation + Momo.
    raw_conv = data.get("conversation_id")
    raw_char = data.get("character_id")
    incoming_conv: Optional[int] = int(raw_conv) if raw_conv is not None else None
    incoming_char: Optional[int] = int(raw_char) if raw_char is not None else None
    conv_id, char_id = await _resolve_conv_char(user_id, incoming_conv, incoming_char)

    # 把可见信息写入 state，让打断收尾能找到 conv / char / user_text
    state.conv_id = conv_id
    state.char_id = char_id

    # v3-E1 Step Z.2：本轮 kind。touch 事件 = 'touch'；其他全 'normal'。
    # v3-F' 接通后 proactive 触发路径在那里设 'proactive'。
    turn_kind = "touch" if msg_type == "touch" else "normal"
    state.kind = turn_kind

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
                    state.user_history_already_written = True
                except Exception:
                    logger.exception("ASR chat_history persist failed for user %s", user_id)
            await ws.send_json({
                "type": "asr_result",
                "content": text,
                "message_id": asr_message_id,
            })
        elif msg_type == "touch":
            # v3-E1 step3：用户点 Live2D canvas 触发主动对话
            # user content 用占位符存进 chat_history，instruction 通过
            # context.extra_system 进 system prompt，让 LLM 自然回应一句。
            text = TOUCH_USER_CONTENT
        else:
            text = (data.get("content") or "").strip()

        if not text:
            await ws.send_json({"type": "error", "message": "Empty input"})
            return

        # 让打断收尾能拿到这一轮的 user 文本
        state.user_text = text

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

        # v3-E1 step3：touch 事件注入临时 system 指令
        if msg_type == "touch":
            chat_msg["payload"]["context"] = {
                "extra_system": TOUCH_INSTRUCTION,
            }

        # reply_parts 用 state 提供的 list —— 打断收尾从同一个 list 读已生成内容
        reply_parts: List[str] = state.reply_parts
        chat_t0 = time.perf_counter()
        first_chunk_logged = False
        sentence_idx = 0
        ws_send_count = 0

        # v3-F #3：TTS 并发合成 + 顺序播放
        # producer 把每句的 synth task 放进 audio_queue；consumer 按入队顺序
        # await 后 send audio_chunk。pending_tts 也写到 state，让打断 handler
        # 能从外部 cancel 它们。
        audio_queue: "asyncio.Queue[Optional[asyncio.Task[Optional[bytes]]]]" = asyncio.Queue()
        pending_tts: List[asyncio.Task] = state.pending_tts

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
                        # v3-E1 step5：把 emotion 推给前端，per-turn 一次性事件，
                        # 风格跟 v3-F thinking push 平行。"默认" 是 _parse_emotion
                        # 的 miss 兜底（LLM 没打 <emotion> 标签），此时不推 →
                        # 前端 currentEmotion 保持 null，Live2DCanvas 监听点
                        # 不触发（中性消息不应该改表情）。
                        if parsed_emotion and parsed_emotion != "默认":
                            logger.info(
                                "[emotion] pushed value=%s user=%s",
                                parsed_emotion, user_id,
                            )
                            await ws.send_json({
                                "type": "emotion",
                                "value": parsed_emotion,
                            })

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

                    # v3-E1 step6：每段独立解析 motion 标签 —— 与 emotion（整轮
                    # 一次锁定）不同，motion 每段都可能命中，命中即 push 让前端
                    # Live2DCanvas useEffect 触发 model.motion()。NORMAL 优先级
                    # 跟触摸 Tap 同级（先到先服务）。同段多个标签只用第一个，
                    # _parse_motion 已把所有 motion 标签从 sentence 剥除，避免
                    # 残留进 text_chunk / chat_history。
                    parsed_motion, sentence = _parse_motion(sentence)
                    if parsed_motion:
                        logger.info(
                            "[motion] pushed value=%s user=%s",
                            parsed_motion, user_id,
                        )
                        await ws.send_json({
                            "type": "motion",
                            "value": parsed_motion,
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

        except asyncio.CancelledError:
            # v3-F #4：被打断 —— consumer 与 pending TTS 在 finally 统一 cancel；
            # 重新抛出由 _handle_message_safe 捕获后做 DB 收尾 + send done。
            raise
        except Exception as exc:
            logger.exception("ChatAgent stream error for user %s", user_id)
            try:
                await ws.send_json({"type": "error", "message": str(exc)})
            except Exception:
                pass
            return
        finally:
            # 无论正常完成 / 异常 / 打断，都把 consumer 与 pending TTS 收掉，
            # 避免悬挂 task。正常完成时 consumer 已 await 过；done 后再 cancel
            # idempotent。
            if consumer_task is not None and not consumer_task.done():
                consumer_task.cancel()
            for t in pending_tts:
                if not t.done():
                    t.cancel()

        await ws.send_json({"type": "done"})

        # ── 3. Background memory update ─────────────────────────────────────
        full_reply = "".join(reply_parts)
        asyncio.create_task(_update_memory(
            user_id, text, full_reply,
            conversation_id=conv_id,
            character_id=char_id,
            skip_user_history=user_history_already_written,
            kind=turn_kind,
        ))


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------


async def _handle_message_safe(
    ws: WebSocket, data: dict, state: "_TurnState", user_id: str,
) -> None:
    """``_handle_message`` 的安全包装，专为被外部 cancel 设计。

    打断路径：``_request_interrupt`` 调 ``state.current_turn.cancel()`` →
    CancelledError 在 ``_handle_message`` 的下一个 await 抛出 → 经 finally
    取消所有 TTS task 后传到这里 → 把 partial reply 写 DB 标
    ``interrupted_at`` → 发 ``{"type":"done","interrupted":true}``。

    成功路径：``_handle_message`` 自己发 ``done``。这里只负责异常分流。
    """
    try:
        await _handle_message(ws, data, state)
    except asyncio.CancelledError:
        # 把当前 task 的 cancellation 状态清掉，让后面 cleanup 的 await 不被
        # 二次 cancel（Python 3.11+ 才有 uncancel；3.10 及以下 task.cancel
        # 本来就只触发一次 CancelledError，无需特殊处理）
        try:
            asyncio.current_task().uncancel()  # type: ignore[union-attr]
        except (AttributeError, RuntimeError):
            pass

        try:
            await _save_interrupted_turn(state, user_id)
        except Exception:
            logger.exception(
                "save interrupted turn failed for user=%s", user_id,
            )
        try:
            await ws.send_json({"type": "done", "interrupted": True})
        except Exception:
            pass
        # 不再 re-raise —— turn 至此安全收尾
    except WebSocketDisconnect:
        # 端点循环会在下次 receive_json 时再触发
        pass
    except Exception as exc:
        logger.exception("Unhandled error in _handle_message")
        try:
            await ws.send_json({"type": "error", "message": str(exc)})
        except Exception:
            pass


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """Stream-based conversation endpoint.

    Clients send one JSON message per turn; the server streams back
    text_chunk / audio_chunk frames and closes with a done frame.
    The connection stays open for multiple turns.

    v3-F #4: turn 在独立 task 内运行，main loop 维持空闲以便随时接收
    ``{"type":"interrupt"}``。收到 interrupt 时 cancel 当前 turn task +
    所有 pending TTS task。``_handle_message_safe`` 兜底做 DB 收尾。
    """
    await websocket.accept()
    user_id = _default_user_id()
    connection_manager.register(user_id, websocket)
    state = _TurnState()
    logger.info("WebSocket connection opened")
    try:
        while True:
            data: dict = await websocket.receive_json()
            msg_type = data.get("type")

            # ── interrupt：异步触发，不 await turn 结束 ─────────────────────
            if msg_type == "interrupt":
                logger.info("[interrupt] received user=%s", user_id)
                _request_interrupt(state)
                continue

            # ── 新一轮：若上一轮还没结束（比如客户端没等 done 直接发了下条）
            #    保险起见先 cancel 上一轮，避免两个 turn 抢 ws 写入。
            if state.current_turn is not None and not state.current_turn.done():
                logger.warning(
                    "[ws] new turn arrived while previous still running, cancelling"
                )
                state.current_turn.cancel()
                try:
                    await state.current_turn
                except (asyncio.CancelledError, Exception):
                    pass

            state.reset_for_new_turn()
            state.current_turn = asyncio.create_task(
                _handle_message_safe(websocket, data, state, user_id)
            )
            # 不 await —— 让 receive_json 继续监听 interrupt
    except WebSocketDisconnect:
        logger.info("WebSocket connection closed")
    finally:
        # 连接关闭时把还在跑的 turn / TTS 收掉
        if state.current_turn is not None and not state.current_turn.done():
            state.current_turn.cancel()
        for t in list(state.pending_tts):
            if not t.done():
                t.cancel()
        connection_manager.unregister(user_id)
