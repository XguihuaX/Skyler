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
from dataclasses import dataclass
from typing import List

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from datetime import datetime
from typing import Optional, Tuple

from sqlalchemy import select

from backend.agents.chat import (
    ChatAgent,
    _parse_emotion,
    _parse_motion,
    _parse_state_update,
    _parse_thinking,
)
from backend.asr.whisper import whisper_asr
from backend.config import config_yaml, get_planner_model, get_tts_enabled
from backend.config.prompt_manager import prompt_manager
from backend.database import AsyncSessionLocal
from backend.database.models import Character, Conversation
from backend.database.services import (
    add_chat_history,
    get_chat_history,
)
from backend.llm.client import LLMError, call_llm
from backend.memory.short_term import short_term_memory
from backend.tts import get_tts_engine, tts_manager  # noqa: F401  (manager 保留作为旧路径)
from backend.utils.text_filters import (
    SUSPICIOUS_TAG_RE,
    count_suspicious_tags,
    extract_tts_text,
    sanitize_suspicious_tags,
    strip_all_for_tts,
    strip_emotion,
    strip_ja_en_tags_for_subtitle,
    strip_motion,
    strip_state_update,
    strip_thinking,
    strip_tool_call_fallback,
)
from backend.utils.timer import timed

timing_logger = logging.getLogger("momoos.timing")

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# ConnectionManager — push notifications from background tasks to frontend
# + per-connection (character_id, conversation_id) tracking(绑定语义 Rule B)
# ---------------------------------------------------------------------------
#
# Rule B(proactive 投递校验)需要 backend 在 push 前回答"用户**此刻 UI 上**
# 是哪个 character / conversation"。原 ``ConnectionManager`` 只存 WebSocket
# 句柄,无 char/conv 维度。本版本加 ``set_current`` / ``get_current``:
#   * 每次 WS 收到 user 帧(``type='text'/'voice'/'touch'/'character_switch'``)
#     在 ``_handle_message`` 入口调 ``set_current(uid, char_id, conv_id)``
#     —— 把最新意图 snapshot 进 connection state。
#   * ``run_trigger`` 在 LLM 调用前 + 持久化前两次调 ``get_current(uid)``,
#     若 char_id 与触发时的 ``target_char_id`` 不符 → 静默丢弃(debug log,
#     不投递不持久化)。
#
# ``character_switch`` 是新的 WS 帧 type:前端切角色时通知 backend 更新
# state,backend 不触发 LLM,仅更新连接状态 + ack。
# ---------------------------------------------------------------------------


@dataclass
class _ConnState:
    ws: WebSocket
    char_id: Optional[int] = None
    conv_id: Optional[int] = None


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[str, _ConnState] = {}

    def register(self, user_id: str, ws: WebSocket) -> None:
        self._connections[user_id] = _ConnState(ws=ws)

    def unregister(self, user_id: str) -> None:
        self._connections.pop(user_id, None)

    def set_current(
        self, user_id: str,
        char_id: Optional[int], conv_id: Optional[int],
    ) -> None:
        """Snapshot the user's current (character, conversation) for this conn。

        路径 7 / Rule B:在每一次 WS user 帧入口调用 —— text/voice/touch/
        character_switch 都视为"用户明确表达当前 UI 状态"的事件。
        若用户尚未注册(``register`` 未调过),no-op(下次 register 时为空,
        必须收到第一帧才被填充)。
        """
        st = self._connections.get(user_id)
        if st is None:
            return
        st.char_id = char_id
        st.conv_id = conv_id

    def get_current(
        self, user_id: str,
    ) -> Optional[tuple[Optional[int], Optional[int]]]:
        """Return ``(char_id, conv_id)`` snapshot for the user's connection。

        无连接 / 连接已 unregister → ``None``。
        连接在但未收到 user 帧(char/conv 仍 None)→ ``(None, None)``。
        """
        st = self._connections.get(user_id)
        if st is None:
            return None
        return (st.char_id, st.conv_id)

    async def push(self, user_id: str, message: dict) -> None:
        st = self._connections.get(user_id)
        if st is not None:
            await st.ws.send_json(message)


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
TTS_TIMEOUT_S = 30.0  # INV-11 Stage 1 (2026-05-25): 10s → 30s · GSV CPU 模式 ~50s 会 timeout 早 fallback stub(比 user 静默等 90s 强);GPU 模式 ~5s 6x buffer 充足。per-voice_provider 细分 timeout 留 v4.1。
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

# (2026-05-19) profile_summary 段全退役 — chunk 11 profile_data 接管;
# 此处 _compute_profile_summary / _regenerate_profile_summary / 配套常量
# 与 helpers 已删。delete_conversation 路径不再触发任何 profile 重生。


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


async def _apply_and_push_state_update(
    ws: WebSocket,
    user_id: str,
    character_id: int,
    parsed: dict,
) -> None:
    """v3-G chunk 3b 帮手：把解析到的 ``<state_update>`` 应用到 DB +
    push WS ``state_update`` 事件让前端状态条刷新。

    任何子步骤失败都吞 + log，不阻塞主对话流。``parsed`` 来自
    ``_parse_state_update``，含 mood / intimacy_delta / thought（可能为 None）。
    services.update_character_state 已校验 enum / clamp delta / 截断长度。
    """
    try:
        from backend.database.services import update_character_state
        async with AsyncSessionLocal() as session:
            new_state = await update_character_state(
                session, character_id,
                mood=parsed.get("mood"),
                intimacy_delta=parsed.get("intimacy_delta"),
                thought=parsed.get("thought"),
                activity=parsed.get("activity"),
            )
        await ws.send_json({
            "type": "state_update",
            "character_id": int(character_id),
            "mood": new_state.mood,
            "intimacy": new_state.intimacy,
            "thought": new_state.current_thought,
            "activity": new_state.current_activity,
        })
        logger.info(
            "[state_update] user=%s char=%s applied %s → mood=%s intimacy=%d",
            user_id, character_id, parsed,
            new_state.mood, new_state.intimacy,
        )
    except Exception:
        logger.exception(
            "[state_update] apply/push failed user=%s char=%s parsed=%s",
            user_id, character_id, parsed,
        )


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
    # v3-G chunk 3b 同 pattern：流式 _parse_state_update 只在 first sentence
    # 跑（与 emotion 同段），后续 sentence 残留的 <state_update> 走 ws-side
    # strip 兜底。chunk 2.6 footgun 教训：双保险 + TTS preprocessor 第三道。
    # v3-G chunk 4 hotfix-1：tool_call_resilience 已 strip 过 full_reply，但
    # 当 reply 直接来自 partial 路径或绕过 resilience 调用时这里再 strip 一道。
    # v3.5 chunk 6b hotfix-4：补 strip_emotion（chunk 4 契约第 2 道入库前必须
    # 完整覆盖 Skyler 自有 meta tag：emotion / state_update / thinking）；之前
    # 漏 emotion 致每轮 SUSPICIOUS 兜底报 warning，治标不治本。emotion 放在
    # 链尾 SUSPICIOUS 之前，让合法 tag 走合法路径剥，SUSPICIOUS 只兜未知格式。
    # v3.5 chunk 9 Part 0.5：补 strip_motion（同样漏在写库链，触发 SUSPICIOUS
    # 兜底每轮 warning），让 4 个 Skyler 自有 meta tag 全部走合法 strip 路径。
    reply = strip_motion(strip_emotion(
        strip_tool_call_fallback(strip_state_update(strip_thinking(reply)))
    ))
    # v3.5 chunk 6b hotfix-3：通用 unknown-tag sanitize 末尾兜底。
    # **只对 assistant 行** —— 用户消息原样保留（HTML / code snippet 等）。
    # 命中即 log warning + strip，让维护者看到 LLM 模式变化。
    if reply:
        _suspicious_n = count_suspicious_tags(reply)
        if _suspicious_n > 0:
            logger.warning(
                "[sanitize] suspicious tags hit=%d user=%s preview=%r",
                _suspicious_n, user_id, reply[:200],
            )
            reply = sanitize_suspicious_tags(reply).strip()
    try:
        await short_term_memory.add(
            user_id, "user", user_text,
            character_id=character_id, conversation_id=conversation_id,
        )
        await short_term_memory.add(
            user_id, "assistant", reply,
            character_id=character_id, conversation_id=conversation_id,
        )

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

        # v3.5 chunk 11：删除 N-turn 计数器触发（``_bump_turn_and_maybe_regenerate``
        # 整体移除）。结构化 ``profile_data`` 由 cron job
        # ``profile_daily_regenerate`` 每天 23:55 主动重生，节奏更稳。
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
      * （chunk 11 起 ``_update_memory`` 也不再 bump turn count，但被打断
        的轮逻辑上仍不应触发 profile 重生 —— 此 invariant 现在由 cron 替代）
      * reply 为空 → 只保留 user 行（如未写过），不写空 assistant 行
    """
    if not state.user_text:
        return  # nothing to record

    # v3-F 回归修：被打断时 reply_parts 可能在 thinking 块内部被 cancel，
    # 残留半个标签 —— strip_thinking 只剥完整对，半截开标签会留下。
    # 前端渲染层有兜底正则再扫一次，最差只是多保留一段没意义的字符串。
    # v3-G chunk 3b：同步剥 <state_update>。
    # v3-G chunk 4 hotfix-1：同步剥 fallback tool_call 标签（中断时 reply_parts
    # 已是逐句 strip 过的，但保留双保险——主路径写库前同样 3 道全过）。
    # v3.5 chunk 6b hotfix-4：补 strip_emotion（与 _update_memory 同契约）。
    # v3.5 chunk 9 Part 0.5：补 strip_motion（4 个 Skyler 自有 meta tag 同契约）。
    # v3.5 chunk 6b hotfix-3：末尾再过一道通用 unknown-tag sanitize。
    full_reply = strip_motion(strip_emotion(strip_tool_call_fallback(
        strip_state_update(strip_thinking("".join(state.reply_parts)))
    ))).strip()
    if full_reply:
        _suspicious_n = count_suspicious_tags(full_reply)
        if _suspicious_n > 0:
            logger.warning(
                "[sanitize] suspicious tags (interrupted) hit=%d user=%s preview=%r",
                _suspicious_n, user_id, full_reply[:200],
            )
            full_reply = sanitize_suspicious_tags(full_reply).strip()
    interrupted_at = datetime.utcnow()

    try:
        # short-term：被打断的也算一轮（让 LLM 下轮知道说到哪儿了）
        await short_term_memory.add(
            user_id, "user", state.user_text,
            character_id=state.char_id, conversation_id=state.conv_id,
        )
        if full_reply:
            await short_term_memory.add(
                user_id, "assistant", full_reply,
                character_id=state.char_id, conversation_id=state.conv_id,
            )

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

    # 路径 7 / Rule B(绑定语义)— ``character_switch`` 是新 WS 帧 type:
    # 前端切角色时通知 backend 当前 UI 状态,不触发 LLM,仅更新连接状态。
    # 必须在 _resolve_conv_char 之前处理(避免反查 chat_history 干扰)。
    if msg_type == "character_switch":
        connection_manager.set_current(user_id, incoming_char, incoming_conv)
        logger.info(
            "[character_switch] user=%s char=%s conv=%s",
            user_id, incoming_char, incoming_conv,
        )
        try:
            await ws.send_json({
                "type": "character_switch_ack",
                "character_id": incoming_char,
                "conversation_id": incoming_conv,
            })
        except Exception:
            logger.exception("[character_switch] ack failed")
        return

    conv_id, char_id = await _resolve_conv_char(user_id, incoming_conv, incoming_char)

    # Rule B:每次 user 帧入口同步更新 ConnectionManager —— proactive gate
    # 投递前以这个 snapshot 为"用户当前 UI 角色 / 对话"的 source of truth。
    connection_manager.set_current(user_id, char_id, conv_id)

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
            # Bug 2 修法:asr_result(用户语音转写)也带 conv_id 让前端按
            # currentConv filter(防 in-flight 语音 turn 切走后 user 气泡冒到新 conv)
            await ws.send_json({
                "type": "asr_result",
                "content": text,
                "message_id": asr_message_id,
                "conversation_id": state.conv_id,
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

        # v3-G chunk 3b：任何 user message 入 turn → 更新角色 last_interaction_at。
        # 不在这里改 mood / intimacy（那靠 LLM <state_update> 标签）。失败 best-effort，
        # 不阻塞主对话流。
        if char_id is not None and msg_type != "touch":
            try:
                from backend.database.services import update_character_state
                async with AsyncSessionLocal() as session:
                    await update_character_state(
                        session, char_id, bump_last_interaction=True,
                    )
            except Exception:
                logger.exception(
                    "[state] bump last_interaction_at failed char=%s", char_id,
                )

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

        # INV-9 §7 · Fish cost cap check(per 决策 5 实施)
        # voice_model 是 fish provider → 调 fish 前 check daily/monthly cap;
        # 触达 → fallback CosyVoice yaml default(voice_model = None)+ push
        # WS event 'tts_cost_cap_exceeded' 给前端 toast 提示用户。
        # 默认 cap $1/day · $20/month(profile_data JSON 覆盖,详 cost_estimator.py)
        if voice_model:
            try:
                _vm_for_cap = json.loads(voice_model)
                if (isinstance(_vm_for_cap, dict)
                        and _vm_for_cap.get("provider") == "fish"):
                    from backend.utils.cost_estimator import check_fish_cost_cap_exceeded
                    cap_status = await check_fish_cost_cap_exceeded(user_id)
                    if cap_status["exceeded"]:
                        logger.warning(
                            "[tts] fish cost cap '%s' exceeded for user=%s "
                            "today=$%.4f / cap=$%.4f · month=$%.4f / cap=$%.4f "
                            "→ fallback CosyVoice yaml default",
                            cap_status["reason"], user_id,
                            cap_status["today_cost"], cap_status["daily_cap"],
                            cap_status["month_cost"], cap_status["monthly_cap"],
                        )
                        # Fallback:voice_model=None 让 get_tts_engine 走 yaml
                        # default(CosyVoice longyumi_v3),tts_language 回退 zh
                        voice_model = None
                        # Push WS event 前端 NotificationToast(per useWebSocket
                        # case 'tts_cost_cap_exceeded' → pushNotification)
                        try:
                            await ws.send_json({
                                "type": "tts_cost_cap_exceeded",
                                "reason": cap_status["reason"],
                                "today_cost": cap_status["today_cost"],
                                "month_cost": cap_status["month_cost"],
                                "daily_cap": cap_status["daily_cap"],
                                "monthly_cap": cap_status["monthly_cap"],
                            })
                        except Exception:
                            logger.exception(
                                "[tts] failed to send tts_cost_cap_exceeded WS event",
                            )
            except (json.JSONDecodeError, TypeError):
                pass
            except Exception:
                logger.exception(
                    "[tts] cost cap check failed (silent fallthrough · 默认放行)"
                )

        tts_engine = get_tts_engine(voice_model)
        # v4 segment 2 §2.5:解析 voice_model.tts_language,日语 / 英语 voice
        # 角色需要在 sentence 层走 extract_tts_text(ja/en 分离),否则 TTS 拿到
        # 中文正文音色合成会很差(Mai 复刻日语 sample 念中文不自然)。
        tts_language = "zh"
        if voice_model:
            try:
                _vm_obj = json.loads(voice_model)
                tts_language = (_vm_obj or {}).get("tts_language", "zh") or "zh"
            except (json.JSONDecodeError, TypeError):
                tts_language = "zh"
        # bugfix-4: 设 TTS context — 主聊天 source='chat',让 tts_call_log 能
        # 区分用量来源 (chat / proactive / activity / preview)。ContextVar 在
        # asyncio task 内 propagate, _tts_synth_with_timeout / engine.synthesize
        # 都看到这个值。
        from backend.observability.tts_log import set_tts_call_context
        set_tts_call_context(source="chat", character_id=char_id, user_id=user_id)
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
                # Bug 1 修法:ChatAgent 用此 conv_id 过滤 short_term,确保同
                # character 不同 conversation 的历史不串(audit_lost_replies.md)。
                "conversation_id": conv_id,
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
            # Bug 2 修法:chunks 附 conv_id snapshot,前端按 currentConversationId
            # filter 防 in-flight turn 切走后的 audio 串到新 conv 播放。
            await ws.send_json({
                "type": "audio_chunk",
                "content": audio_b64,
                "conversation_id": state.conv_id,
            })

        consumer_task: Optional[asyncio.Task] = None
        try:
            with timed("ChatAgent total"):
                consumer_task = asyncio.create_task(
                    _tts_audio_consumer(audio_queue, _send_audio)
                )

                # Bugfix-segment2-3:ja/en 模式 wrap merge_short_sentences,
                # 把 <10 字短意群 sentence 合并到下一句一起 yield。zh 模式 不
                # 包,保留原逐句流式体验。
                _agent_stream = _chat_agent.stream(chat_msg)
                if tts_language in ("ja", "en"):
                    from backend.agents.sentence_merge import merge_short_sentences
                    _agent_stream = merge_short_sentences(_agent_stream)
                async for sentence in _agent_stream:
                    # UX-004: chat.py 现在 yield Union[str, dict] —— dict 是 typed
                    # WS event(tool_use_start / tool_use_done),直接透传不经文本
                    # 处理(emotion/thinking parse + TTS 等都不适用)。
                    if isinstance(sentence, dict):
                        logger.info(
                            "[ws] forwarding tool event %s user=%s tool=%s",
                            sentence.get("type"), user_id,
                            sentence.get("tool_name"),
                        )
                        await ws.send_json(sentence)
                        continue

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

                        # v3-G chunk 3b：第一句同时解析 <state_update> 标签。
                        # 与 emotion 同段（紧贴 <emotion> 之后）；解析后剥离
                        # 不进 chat_history、不进 TTS。命中即写 DB + push WS
                        # state_update 事件让前端状态条立即刷新。
                        parsed_state, sentence = _parse_state_update(sentence)
                        if parsed_state and char_id is not None:
                            await _apply_and_push_state_update(
                                ws, user_id, char_id, parsed_state,
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
                        # Bug 2 修法:chunks 带 conv_id 让前端按 currentConv filter。
                        await ws.send_json({
                            "type": "thinking",
                            "value": thinking_value,
                            "conversation_id": state.conv_id,
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

                    # v3-G chunk 4 hotfix-1：剥 fallback tool_call 标签
                    # （<tool_call> / <function_calls> / <invoke> / json 块）。
                    # tool_call_resilience 在 stream 结束后整体扫 full_reply 真
                    # 执行 + 剥；此处需要在每句送 TTS / text_chunk 之前先剥，
                    # 否则 cosyvoice 把 XML 念出来 + 前端短暂看到 XML。chat.py
                    # _safe_boundary 已用 has_partial_open_tag 阻止半截 XML 越界，
                    # 这里只可能命中完整闭合块。
                    sentence = strip_tool_call_fallback(sentence)

                    # 剥标签后可能为空（极端情况：句子只有标签），跳过本句
                    if not sentence.strip():
                        logger.info(
                            "[chat] sentence skipped (all-tag after strip) user=%s",
                            user_id,
                        )
                        continue

                    reply_parts.append(sentence)
                    sentence_idx += 1

                    # 立即推送 text_chunk —— 不等 audio
                    # hotfix-7 commit 2：最后一道 ``strip_all_for_tts`` 兜底,
                    # 防回归 + 给未来新 LLM 标签格式留缓冲。正常路径 sentence
                    # 已被 _parse_emotion / _parse_state_update / _parse_thinking
                    # / _parse_motion / _parse_tool_call_fallback 5 道剥过,本
                    # 行通常 no-op;但任一 parser 漏点 / LLM 新格式时这里兜底。
                    #
                    # v4 segment 2 §2.5:字幕路径走 strip_ja_en_tags_for_subtitle
                    # 删 <ja>...</ja> / <en>...</en> 翻译,只留中文正文给用户看。
                    final_chunk = strip_ja_en_tags_for_subtitle(
                        strip_all_for_tts(sentence)
                    )
                    if not final_chunk.strip():
                        continue  # 全是 meta tag → 不 push
                    payload = {
                        "type": "text_chunk",
                        "content": final_chunk,
                        # Bug 2 修法:chunks 带 conv_id 让前端按 currentConv filter。
                        "conversation_id": state.conv_id,
                    }
                    payload_bytes = len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
                    ws_send_count += 1
                    with timed(f"WS send chunk #{sentence_idx} bytes={payload_bytes}"):
                        await ws.send_json(payload)

                    # v3-F #3：spawn TTS task 并入队；并发由 _tts_semaphore 节流，
                    # consumer 按入队顺序 await，保证 audio_chunk 顺序播放。
                    # turn_emotion 整轮一致；synthesize 内部 + _synth_one 双层
                    # try/except，永远不会抛到 producer。
                    #
                    # v4 segment 2 §2.5:TTS 路径走 extract_tts_text(sentence,
                    # tts_language) ── ja/en 角色取翻译送 TTS,中文角色等价 no-op。
                    if get_tts_enabled():
                        tts_text = extract_tts_text(sentence, tts_language)
                        if not tts_text or not tts_text.strip():
                            # ja/en 角色但 LLM 漏标 + 原文剥光 → 跳过 TTS
                            continue
                        task = asyncio.create_task(
                            _tts_synth_with_timeout(
                                tts_engine, tts_text, turn_emotion,
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

        # ── 3a. v3-G chunk 4: tool_call_resilience —— Qwen 偶发把 tool 调用
        # 以非 OpenAI 协议形式（<tool_call>JSON</tool_call> / Anthropic
        # invoke / markdown json）写到 delta.content 里 → ChatAgent 主循环
        # 看不见，capability 不真触发。本 chunk 引入兜底层：stream 结束后扫
        # full_reply 找这些 fallback 形式 + 真执行 + 剥 XML 残骸。chunk 2.6
        # snooze + chunk 3 clipboard.translate 实测 quirk 由此真解。
        full_reply = "".join(reply_parts)
        try:
            from backend.agents.tool_call_resilience import (
                detect_and_execute_fallback_tool_calls,
            )
            cleaned_reply, fallback_executed = await detect_and_execute_fallback_tool_calls(
                full_reply, user_id=user_id, character_id=char_id,
            )
            if fallback_executed:
                logger.info(
                    "[chat] tool_call_resilience caught %d fallback call(s): %s",
                    len(fallback_executed),
                    [f"{e['pattern']}/{e['name']}" for e in fallback_executed],
                )
                full_reply = cleaned_reply
        except Exception:
            logger.exception("[tool_resilience] layer crashed; using raw reply")

        # Bug 2 修法:done 也带 conv_id 让前端按 currentConv filter
        await ws.send_json({"type": "done", "conversation_id": state.conv_id})

        # ── 3b. Background memory update ────────────────────────────────────
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
            # Bug 2 修法:interrupted done 也带 conv_id
            await ws.send_json({
                "type": "done",
                "interrupted": True,
                "conversation_id": state.conv_id,
            })
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

            # ── Bug 2 修法(audit_lost_replies.md):character_switch 是纯状态
            #    同步,不应触发对旧 turn 的 cancel。在 endpoint loop 直接处理:
            #    更新 ConnectionManager + ack,**让 in-flight turn 继续跑完**,
            #    跑完按 9039d75 snapshot 投递回原 conv → Rule A "不丢" 兑现。
            #    与 interrupt 共享同一"提前处理 + continue 跳 task 调度"模式。
            if msg_type == "character_switch":
                raw_char = data.get("character_id")
                raw_conv = data.get("conversation_id")
                new_char: Optional[int] = (
                    int(raw_char) if raw_char is not None else None
                )
                new_conv: Optional[int] = (
                    int(raw_conv) if raw_conv is not None else None
                )
                connection_manager.set_current(user_id, new_char, new_conv)
                logger.info(
                    "[character_switch] user=%s char=%s conv=%s "
                    "(in-flight turn preserved)", user_id, new_char, new_conv,
                )
                try:
                    await websocket.send_json({
                        "type": "character_switch_ack",
                        "character_id": new_char,
                        "conversation_id": new_conv,
                    })
                except Exception:
                    logger.exception("[character_switch] ack failed")
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
