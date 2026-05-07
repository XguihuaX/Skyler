"""v3-G chunk 2 — 通用 proactive engine。

设计要点
--------

* **trigger-agnostic**：``ProactiveTrigger`` 抽象类只承诺 metadata + 两个钩子
  （``build_system_prompt`` / ``resolve_capabilities``）；engine 不知道也不关心
  trigger 内部业务逻辑。新增 trigger 只需新建一个文件实现该抽象。
* **复用 ChatAgent**：proactive 转 ChatAgent.stream（zero-改动 chat.py），让
  persona / tool calling / emotion / motion / thinking 全套体验自动具备。
* **复用 TTS pipeline**：从 backend.routes.ws 借 ``_tts_synth_with_timeout`` +
  ``_tts_audio_consumer`` 直接复用并发合成 + 顺序播放队列，不重写。
* **WS 协议向后兼容**：text_chunk / audio_chunk / done 加 ``proactive=true`` +
  ``proactive_trigger`` 字段；老前端忽略未知字段照常工作。
* **kind='proactive' 持久化**：assistant 行写 chat_history with kind='proactive'
  + proactive_trigger=trigger.name。profile_summary 重写已通过白名单
  ``kinds=['normal']`` 自动排除（v3-E1 Step Z.2 落地，本 chunk 零改动）。
* **character 解析三档**：spec character_id_override > 最近 user turn 角色 >
  Momo (id=1)。

非目标
------

* **不做 capability 硬过滤**：``resolve_capabilities`` 返的 list 当前作 *hint*
  注入到 system prompt（"你这次触发主要会用 A/B/C"），不裁剪 ToolRegistry
  传给 LLM 的 tools[]。理由：硬裁剪要在 ChatAgent 加 per-call tool subset
  参数，但本 chunk 的 MorningBriefingTrigger 用 hint 已足够（早晨简报需要的
  capability 都属于 CHAT_AGENT 集合，多暴露几个无副作用）。Backlog：硬过
  滤场景出现时再扩展。
* **不接管语音 TTS engine 选择**：直接读 character.voice_model 字段（与正
  常 chat 同源），让简报跟用户日常听感一致。
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, List, Optional

from sqlalchemy import select

from backend.agents.chat import (
    ChatAgent,
    _parse_emotion,
    _parse_motion,
    _parse_thinking,
)
from backend.config import config_yaml, get_tts_enabled
from backend.database import AsyncSessionLocal
from backend.database.models import Character, ChatHistory, Conversation
from backend.database.services import add_chat_history
from backend.memory.short_term import short_term_memory
from backend.tts import get_tts_engine
from backend.utils.text_filters import strip_thinking

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ProactiveTrigger 抽象
# ---------------------------------------------------------------------------

class ProactiveTrigger(ABC):
    """主动触发器抽象基类。

    子类要么覆写下列 class-level 属性，要么在 ``__init__`` 里赋值。三种调度方
    式 ``cron_expr`` / ``interval_seconds`` / ``event_source`` 互斥，至少给一
    个非 None；都为 None 表示该 trigger 仅作 ``POST /api/briefing/test`` 类
    手动触发用（不走 cron 注册）。
    """

    #: 触发器唯一名字，写入 ``chat_history.proactive_trigger`` + ``cron`` 任务
    #: id，且前端 ChatHistory 渲染时按它映射 label（如 morning_briefing →
    #: "🌅（早安简报）"）。最长 64 字符 by convention，下放 DB 不强制。
    name: str = ""

    #: APScheduler crontab 表达式（5 段："0 9 * * *"）。互斥三选一。
    cron_expr: Optional[str] = None

    #: 固定间隔秒数。互斥三选一。
    interval_seconds: Optional[int] = None

    #: 外部事件源标识（如 "n8n.morning"），互斥三选一。本 chunk 仅占位，
    #: 实际接通到 webhook 路由由后续 chunk 实现。
    event_source: Optional[str] = None

    #: 是否启用 LiteLLM model-native web search（qwen → enable_search 参数；
    #: deepseek → web_search_preview tool）。早晨简报需要查天气 / 新闻 → True；
    #: 饭点 / 睡前等纯陪伴 trigger → False。
    enable_search: bool = False

    @abstractmethod
    async def build_system_prompt(self, character: Optional[Character]) -> str:
        """生成本次触发的系统提示词（注入到 ``context.extra_system``）。

        ``character`` 为目标角色 ORM（已解析；可能为 None 极端兜底）。trigger
        子类可以读 ``character.persona`` 拼自然过渡，但不要重写 persona ——
        ChatAgent 已经从 DB 拿 persona 注入到 system 头部。这里专注于"这次为
        什么主动开口" + "需要 LLM 调哪些 capability"。
        """
        raise NotImplementedError

    async def resolve_capabilities(self) -> List[str]:
        """返这次触发希望 LLM 主动调的 capability name 列表（hint 用）。

        默认返 ``[]`` ⇒ 不加 hint，LLM 看到所有 CHAT_AGENT capability，按
        ``build_system_prompt`` 里的引导自由调度。子类如有强引导诉求 override
        返个具体子集（engine 会把这些名字拼进 prompt 末尾作为 hint）。
        """
        return []


# ---------------------------------------------------------------------------
# Engine 主流程
# ---------------------------------------------------------------------------

# Trigger 运行时往 ChatAgent.stream 喂的"用户侧"占位 text。ChatAgent.stream
# 必须有非空 text，否则 raise ValueError；内容本身不会进 chat_history（engine
# 只持久化 assistant 一行，user 侧不写），仅用作 LLM 上下文里的最后一句"用
# 户暗示"。
_PROACTIVE_USER_PROMPT = "[proactive trigger]"

# build_system_prompt 末尾追加的 capability hint 模板
_CAP_HINT_TEMPLATE = (
    "\n\n本次触发推荐主动调用以下 capability："
    "{names}。其他 capability 仍可见，按需调用。"
)


def _get_proactive_config() -> dict:
    """读 ``config.yaml.proactive`` 子树，无则返 ``{}``。"""
    return config_yaml.get("proactive") or {}


async def _resolve_target_character_id(user_id: str) -> Optional[int]:
    """三档优先级解析目标 character_id。

    1. ``config.proactive.character_id_override``（int / null）
    2. 该 user 最近 ``role='user'`` 的 chat_history 行的 character_id
    3. fallback Momo (id=1)
    任一档解析到合法 id 即返回；全部 miss 返 None（调用方应再做 None-safe
    回退到 1）。
    """
    cfg = _get_proactive_config()
    override = cfg.get("character_id_override")
    if isinstance(override, int) and override > 0:
        return override

    async with AsyncSessionLocal() as session:
        row = (await session.execute(
            select(ChatHistory.character_id)
            .where(ChatHistory.user_id == user_id)
            .where(ChatHistory.role == "user")
            .where(ChatHistory.character_id.isnot(None))
            .order_by(ChatHistory.created_at.desc())
            .limit(1)
        )).scalar_one_or_none()
        if isinstance(row, int):
            return row

        # Fallback Momo
        momo = (await session.execute(
            select(Character.id).where(Character.name == "Momo")
        )).scalar_one_or_none()
        if isinstance(momo, int):
            return momo

    return None


async def _get_or_create_conversation(
    user_id: str, character_id: int,
) -> Optional[int]:
    """拉该 character 最近一个 conversation；没有就新建 title='主动陪伴'。

    返回 conversation id；DB 不可用时返 None（让 chat_history 行 conversation_id
    NULL —— 不阻塞 turn 落库）。
    """
    try:
        async with AsyncSessionLocal() as session:
            row = (await session.execute(
                select(Conversation.id)
                .where(Conversation.user_id == user_id)
                .where(Conversation.character_id == character_id)
                .order_by(Conversation.updated_at.desc())
                .limit(1)
            )).scalar_one_or_none()
            if isinstance(row, int):
                return row

            conv = Conversation(
                user_id=user_id,
                character_id=character_id,
                title="主动陪伴",
            )
            session.add(conv)
            await session.commit()
            await session.refresh(conv)
            return int(conv.id)
    except Exception:
        logger.exception(
            "[proactive] _get_or_create_conversation failed user=%s char=%s",
            user_id, character_id,
        )
        return None


async def _load_character(character_id: Optional[int]) -> Optional[Character]:
    if character_id is None:
        return None
    try:
        async with AsyncSessionLocal() as session:
            return (await session.execute(
                select(Character).where(Character.id == character_id)
            )).scalar_one_or_none()
    except Exception:
        logger.exception("[proactive] _load_character failed id=%s", character_id)
        return None


def _strip_format_tags(text: str) -> str:
    """剥离 emotion / motion / thinking 标签 —— 持久化前的最后一道清洗。"""
    text = strip_thinking(text)
    text = re.sub(r"<emotion>.*?</emotion>", "", text, flags=re.DOTALL).strip()
    text = re.sub(r"<motion>[^<]*</motion>", "", text).strip()
    return text


async def run_trigger(
    trigger: ProactiveTrigger,
    user_id: str,
) -> dict:
    """执行一次 proactive trigger 并把结果通过 WS 推到前端 + 落库。

    返回 ``{text, character_id, conversation_id, proactive_trigger,
    audio_bytes}``，给手动测试 endpoint 用。WS 不可达不致命（push 沉默
    失败），落库 + 返回值仍然可用。
    """
    # 延迟 import：避免 backend.routes.ws import 链在 module-load 时被触发
    from backend.routes import ws as _ws

    target_char_id = await _resolve_target_character_id(user_id)
    character = await _load_character(target_char_id)
    if target_char_id is None or character is None:
        # 极端兜底：硬编码 Momo id=1（init 流程已保证 Momo 存在）
        target_char_id = 1
        character = await _load_character(1)
        if character is None:
            logger.error("[proactive] no character resolvable, aborting trigger=%s", trigger.name)
            return {
                "text": "",
                "character_id": None,
                "conversation_id": None,
                "proactive_trigger": trigger.name,
                "audio_bytes": 0,
                "error": "no character resolvable",
            }

    conv_id = await _get_or_create_conversation(user_id, target_char_id)

    # ── system prompt 拼接 ──────────────────────────────────────────────
    system_prompt = await trigger.build_system_prompt(character)
    cap_hint_names = await trigger.resolve_capabilities()
    if cap_hint_names:
        system_prompt = system_prompt + _CAP_HINT_TEMPLATE.format(
            names=", ".join(cap_hint_names),
        )

    # ── ChatAgent message ───────────────────────────────────────────────
    chat_msg = {
        "agent": "ChatAgent",
        "payload": {
            "user_id": user_id,
            "text": _PROACTIVE_USER_PROMPT,
            "character_id": target_char_id,
            "context": {
                "extra_system": system_prompt,
                "enable_search": bool(trigger.enable_search),
            },
        },
    }

    # ── TTS engine ──────────────────────────────────────────────────────
    voice_model: Optional[str] = character.voice_model
    tts_engine = get_tts_engine(voice_model)
    tts_enabled = get_tts_enabled()

    # ── WS push helpers ─────────────────────────────────────────────────
    connection_manager = _ws.connection_manager
    proactive_meta = {
        "proactive": True,
        "proactive_trigger": trigger.name,
    }

    async def _push(msg: dict) -> None:
        try:
            await connection_manager.push(user_id, msg)
        except Exception as exc:
            logger.warning("[proactive] push failed: %s", exc)

    async def _send_audio(audio: bytes) -> None:
        b64 = base64.b64encode(audio).decode()
        await _push({
            "type": "audio_chunk",
            "content": b64,
            **proactive_meta,
        })

    # ── ChatAgent stream + concurrent TTS ──────────────────────────────
    chat_agent = ChatAgent()
    audio_queue: "asyncio.Queue[Optional[asyncio.Task[Optional[bytes]]]]" = asyncio.Queue()
    pending_tts: List[asyncio.Task] = []
    consumer: Optional[asyncio.Task] = None
    if tts_enabled:
        consumer = asyncio.create_task(_ws._tts_audio_consumer(audio_queue, _send_audio))

    reply_parts: List[str] = []
    turn_emotion = "默认"
    emotion_resolved = False
    thinking_pushed = False
    audio_total_bytes = 0

    try:
        async for sentence in chat_agent.stream(chat_msg):
            # 第一句锁 emotion + 推送 emotion 事件（与 ws.py 主路径同结构）
            if not emotion_resolved:
                parsed_emotion, sentence = _parse_emotion(sentence)
                turn_emotion = parsed_emotion
                emotion_resolved = True
                if parsed_emotion and parsed_emotion != "默认":
                    await _push({
                        "type": "emotion",
                        "value": parsed_emotion,
                        **proactive_meta,
                    })

            # thinking 每轮一次
            thinking_value, sentence = _parse_thinking(sentence)
            if thinking_value and not thinking_pushed:
                thinking_pushed = True
                await _push({
                    "type": "thinking",
                    "value": thinking_value,
                    **proactive_meta,
                })

            # motion per-segment
            parsed_motion, sentence = _parse_motion(sentence)
            if parsed_motion:
                await _push({
                    "type": "motion",
                    "value": parsed_motion,
                    **proactive_meta,
                })

            if not sentence.strip():
                continue

            reply_parts.append(sentence)

            # text_chunk 立即推
            await _push({
                "type": "text_chunk",
                "content": sentence,
                **proactive_meta,
            })

            # TTS 并发合成 + 顺序入队（复用 ws.py 的 helper + semaphore）
            if tts_enabled and consumer is not None:
                task = asyncio.create_task(
                    _ws._tts_synth_with_timeout(
                        tts_engine, sentence, turn_emotion,
                        idx=len(reply_parts),
                    )
                )
                pending_tts.append(task)
                await audio_queue.put(task)

        # producer 收尾
        if tts_enabled and consumer is not None:
            await audio_queue.put(None)
            await consumer

    except Exception as exc:
        logger.exception("[proactive] ChatAgent stream failed trigger=%s", trigger.name)
        await _push({
            "type": "error",
            "message": f"proactive trigger {trigger.name} failed: {exc}",
            **proactive_meta,
        })
    finally:
        if consumer is not None and not consumer.done():
            consumer.cancel()
        for t in pending_tts:
            if not t.done():
                t.cancel()

    # done
    await _push({
        "type": "done",
        **proactive_meta,
    })

    # ── 持久化 assistant 行 ────────────────────────────────────────────
    full_reply = _strip_format_tags("".join(reply_parts))
    if full_reply:
        # short-term memory：必须 add，否则用户 VAD 续聊时 ChatAgent 上下文里
        # 看不到这条简报 turn，"把 X 改到下午"等指代会断（spec 验收硬指标）。
        try:
            await short_term_memory.add(user_id, "assistant", full_reply)
        except Exception:
            logger.exception("[proactive] short_term add failed trigger=%s", trigger.name)

        try:
            async with AsyncSessionLocal() as session:
                await add_chat_history(
                    session,
                    user_id=user_id,
                    role="assistant",
                    content=full_reply,
                    conversation_id=conv_id,
                    character_id=target_char_id,
                    kind="proactive",
                    proactive_trigger=trigger.name,
                )
                if conv_id is not None:
                    conv = (await session.execute(
                        select(Conversation).where(Conversation.id == conv_id)
                    )).scalar_one_or_none()
                    if conv is not None:
                        conv.updated_at = datetime.utcnow()
                        await session.commit()
        except Exception:
            logger.exception(
                "[proactive] persist assistant row failed trigger=%s",
                trigger.name,
            )

    logger.info(
        "[proactive] trigger=%s user=%s char=%s len=%d sentences=%d audio=%d",
        trigger.name, user_id, target_char_id,
        len(full_reply), len(reply_parts), audio_total_bytes,
    )

    return {
        "text": full_reply,
        "character_id": target_char_id,
        "conversation_id": conv_id,
        "proactive_trigger": trigger.name,
        # audio 在流式 push 中已经发完；保留 0 占位让 frontend 旧接口不炸
        "audio_bytes": audio_total_bytes,
    }


__all__ = ["ProactiveTrigger", "run_trigger"]
