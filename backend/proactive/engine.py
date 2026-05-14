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
    _parse_state_update,
    _parse_thinking,
)
from backend.config import config_yaml, get_tts_enabled
from backend.database import AsyncSessionLocal
from backend.database.models import Character, ChatHistory, Conversation
from backend.database.services import (
    add_chat_history,
    add_pending_briefing,
    get_all_memories,
)
from backend.memory.short_term import short_term_memory
from backend.tts import get_tts_engine
from backend.utils.text_filters import (
    extract_tts_text,
    strip_all_for_tts,
    strip_ja_en_tags_for_subtitle,
    strip_thinking,
)

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


async def _apply_proactive_state_update(
    push_fn,
    user_id: str,
    character_id: int,
    parsed: dict,
    proactive_meta: dict,
) -> None:
    """hotfix-7：proactive 路径的 state_update apply + push 双保险。

    ``push_fn(msg: dict)`` 用各 trigger 流程自带的 ``_push`` helper（包了
    connection_manager.push）。功能等价 ws.py main 路径 ``_apply_and_push_
    state_update``，但参数 shape 不一样（主路径直收 ``ws: WebSocket``）。

    与主路径同模板：任一子步骤失败 silent + log，不阻塞 stream。
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
        await push_fn({
            "type": "state_update",
            "character_id": int(character_id),
            "mood": new_state.mood,
            "intimacy": new_state.intimacy,
            "thought": new_state.current_thought,
            "activity": new_state.current_activity,
            **proactive_meta,
        })
        logger.info(
            "[state_update] proactive user=%s char=%s applied %s → mood=%s intimacy=%d",
            user_id, character_id, parsed,
            new_state.mood, new_state.intimacy,
        )
    except Exception:
        logger.exception(
            "[state_update] proactive apply/push failed user=%s char=%s parsed=%s",
            user_id, character_id, parsed,
        )


def _strip_format_tags(text: str) -> str:
    """剥离全套 Skyler meta tag —— 持久化前的最后一道清洗。

    hotfix-7：之前只剥 emotion / motion / thinking 三档，漏 state_update +
    tool_call fallback。某些边界（流式 cancel 截断 / LLM 多打一次 / 跨句
    boundary 落点）会让 state_update 字面文本进 chat_history。改用
    ``strip_all_for_tts`` 走 5 道完整 strip 链路（emotion / thinking /
    state_update / motion / tool_call fallback），写库前与 TTS 路径同一兜底。
    """
    return strip_all_for_tts(text).strip()


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
                # v4 segment 1: turn_origin 让 renderer 选 Mode.PROACTIVE
                # 走 layer_b.j2 PROACTIVE directive(signature_phrases 开场
                # / briefing 是 context 不是台词 / 单条 < 50 字)。trigger.name
                # 在 PROACTIVE_ORIGINS 名单内 → PROACTIVE,否则 fallback ROLEPLAY。
                "turn_origin": trigger.name,
            },
        },
    }

    # ── TTS engine ──────────────────────────────────────────────────────
    voice_model: Optional[str] = character.voice_model
    tts_engine = get_tts_engine(voice_model)
    # v4 segment 2 §2.5:解析 voice_model.tts_language(ja/en/zh)给 extract_tts_text
    tts_language = "zh"
    if voice_model:
        try:
            _vm_obj = json.loads(voice_model)
            tts_language = (_vm_obj or {}).get("tts_language", "zh") or "zh"
        except (json.JSONDecodeError, TypeError):
            tts_language = "zh"
    tts_enabled = get_tts_enabled()

    # bugfix-4: 设 TTS source — activity_smart 单独标记,其他 proactive trigger
    # (wake_call / morning_briefing / lunch_call / dinner_call / bedtime_chat /
    # long_idle) 都归到 'proactive'。UI 用量 panel 按这两个 bucket 显示。
    from backend.observability.tts_log import set_tts_call_context
    _tts_source = "activity_smart" if "activity" in trigger.name else "proactive"
    set_tts_call_context(
        source=_tts_source, character_id=target_char_id, user_id=user_id,
    )

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

            # hotfix-7：state_update tag per-segment 剥离 + apply。chunk 3b
            # ws.py 主路径已挂 _parse_state_update + _apply_and_push_state_update；
            # proactive 路径漏挂导致 ``<state_update mood="..." />`` 字面字符串
            # 进入 text_chunk push。修法：在 text_chunk push 之前剥并 apply，
            # 与主路径同语义。
            parsed_state, sentence = _parse_state_update(sentence)
            if parsed_state and target_char_id is not None:
                await _apply_proactive_state_update(
                    _push, user_id, target_char_id, parsed_state, proactive_meta,
                )

            if not sentence.strip():
                continue

            reply_parts.append(sentence)

            # text_chunk 立即推
            # hotfix-7 commit 2：最后一道 strip_all_for_tts 兜底,与 ws.py
            # 主路径同语义。防回归 + 给未来新 LLM 标签留缓冲。
            # v4 segment 2 §2.5:字幕路径剥 ja/en 翻译,只留中文给用户看。
            final_chunk = strip_ja_en_tags_for_subtitle(
                strip_all_for_tts(sentence)
            )
            if not final_chunk.strip():
                continue
            await _push({
                "type": "text_chunk",
                "content": final_chunk,
                **proactive_meta,
            })

            # TTS 并发合成 + 顺序入队（复用 ws.py 的 helper + semaphore）
            # v4 segment 2 §2.5:TTS 路径走 extract_tts_text 选 ja/en 翻译。
            if tts_enabled and consumer is not None:
                tts_text = extract_tts_text(sentence, tts_language)
                if not tts_text or not tts_text.strip():
                    continue
                task = asyncio.create_task(
                    _ws._tts_synth_with_timeout(
                        tts_engine, tts_text, turn_emotion,
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


# ---------------------------------------------------------------------------
# v3-G chunk 2.6 — wake_call_briefing 双阶段流水线
# ---------------------------------------------------------------------------

# stage 1 wake call 短问候缓冲值（chat_history kind='proactive', trigger='wake_call'）
_WAKE_CALL_TRIGGER_NAME = "wake_call"


async def aggregate_briefing_data(
    user_id: str,
    character_id: int,
) -> dict:
    """聚合早晨简报需要的本地数据（不调 LLM）。

    这一层在 wake_call **stage 1** 跑——用户还没响应时就把"今日有什么"先
    存好；用户响应后 ChatAgent stage 2 看到这些预聚合数据即可生成内容
    （weather / news 留给 LLM 在 stage 2 用 ``enable_search`` 现查，缓存
    更新鲜）。

    morning_briefing **不**调本函数 —— 它走 ChatAgent 自己 tool calling
    的"边生成边聚合"路径，不需要预聚合。

    返回 dict（写入 ``pending_briefings.briefing_data_json``）::

        {
          "time":            {iso, weekday, is_weekend, human},
          "calendar_events": [...],       # 来自 calendar.today_events 路由
          "instruction_memories": [...],   # type='instruction' 的活记忆
          "city":            "东京",        # 给 stage 2 LLM enable_search 的 hint
        }

    任一子项失败都吞成空集合或 None —— 聚合失败不应阻塞 wake call 短问
    候的发出（用户至少先听到"起床啦"）。
    """
    out: dict = {}

    # time —— 直接调 capability handler（不走 ToolRegistry，省一层）
    try:
        from backend.capabilities.time_capability import get_current_time
        out["time"] = await get_current_time()
    except Exception:
        logger.exception("[wake_call.aggregate] time.now failed")
        out["time"] = None

    # calendar.today_events —— calendar router 决定 source
    try:
        from backend.capabilities.calendar import today_events
        out["calendar_events"] = await today_events()
    except Exception:
        logger.exception("[wake_call.aggregate] calendar.today_events failed")
        out["calendar_events"] = []

    # instruction memories —— 直接 services 查，避免 LLM tool 多一轮
    try:
        async with AsyncSessionLocal() as session:
            mems = await get_all_memories(
                session, user_id,
                active_only=True,
                character_id=character_id,
            )
        out["instruction_memories"] = [
            {"id": m.id, "type": m.type, "content": m.content}
            for m in mems if m.type == "instruction"
        ]
    except Exception:
        logger.exception("[wake_call.aggregate] list_memories failed")
        out["instruction_memories"] = []

    # city —— 从 wake_call_briefing 配置读，stage 2 LLM 用作 enable_search hint
    proactive_cfg = config_yaml.get("proactive") or {}
    wake_cfg = proactive_cfg.get("wake_call_briefing") or {}
    out["city"] = str(wake_cfg.get("city") or "东京")

    return out


async def run_wake_call_trigger(
    trigger: "ProactiveTrigger",
    user_id: str,
) -> dict:
    """**Stage 1** of wake_call_briefing pipeline。

    流程：
      1. 解析 target character (override > recent user turn > Momo)
      2. 拉/建 conversation
      3. ``aggregate_briefing_data`` 拿结构化数据
      4. 写 ``pending_briefings`` 一行（ttl 从 config 读）
      5. ChatAgent.stream 生成 8-15 字短 wake call 推 WS（带
         proactive=true + proactive_trigger='wake_call'）
      6. 写 chat_history kind='proactive' + proactive_trigger='wake_call'
         + add 到 short_term

    用户后续任何 user turn 进 ChatAgent._build_messages 时，stage 2 触发
    （在 chat.py 内）。本函数只做 stage 1，不等 stage 2。

    返回 ``{text, character_id, conversation_id, pending_id, ...}`` 给手动
    测试 endpoint 用。
    """
    from backend.routes import ws as _ws

    target_char_id = await _resolve_target_character_id(user_id)
    character = await _load_character(target_char_id)
    if target_char_id is None or character is None:
        target_char_id = 1
        character = await _load_character(1)
        if character is None:
            logger.error("[wake_call] no character resolvable, aborting")
            return {"text": "", "character_id": None, "conversation_id": None,
                    "proactive_trigger": _WAKE_CALL_TRIGGER_NAME, "audio_bytes": 0,
                    "pending_id": None, "error": "no character resolvable"}

    conv_id = await _get_or_create_conversation(user_id, target_char_id)
    if conv_id is None:
        # 极端兜底：DB 不可写时仍 push 短问候（pending 写不进去也无所谓——
        # stage 2 拿不到 pending 时会降级当普通对话回复）
        logger.warning("[wake_call] conversation unresolved, proceeding without pending")

    # ── Aggregate stage（先聚合再 push，让 short greeting 后用户首次回应
    # 时 pending 一定已存在）──────────────────────────────────────────
    briefing_data = await aggregate_briefing_data(user_id, target_char_id)

    proactive_cfg = config_yaml.get("proactive") or {}
    wake_cfg = proactive_cfg.get("wake_call_briefing") or {}
    ttl_minutes = int(wake_cfg.get("pending_ttl_minutes") or 30)

    pending_id: Optional[int] = None
    if conv_id is not None:
        try:
            async with AsyncSessionLocal() as session:
                row = await add_pending_briefing(
                    session,
                    user_id=user_id,
                    trigger_name=_WAKE_CALL_TRIGGER_NAME,
                    briefing_data_json=json.dumps(briefing_data, ensure_ascii=False),
                    character_id=target_char_id,
                    conversation_id=conv_id,
                    ttl_minutes=ttl_minutes,
                )
                pending_id = int(row.id)
            logger.info(
                "[wake_call] pending_briefing #%d written for user=%s ttl=%dmin",
                pending_id, user_id, ttl_minutes,
            )
        except Exception:
            logger.exception("[wake_call] write pending_briefings failed")

    # ── Push stage：用 ChatAgent.stream 生成 8-15 字短问候 ───────────────
    # 复用 run_trigger 的核心逻辑：trigger.build_system_prompt 返"叫醒短句"
    # 提示，engine 走同一份 streaming + TTS 路径。trigger.name 写
    # 'wake_call' 让前端按 trigger 映射 toast / 灰字前缀。
    system_prompt = await trigger.build_system_prompt(character)

    chat_msg = {
        "agent": "ChatAgent",
        "payload": {
            "user_id": user_id,
            "text": _PROACTIVE_USER_PROMPT,
            "character_id": target_char_id,
            "context": {
                "extra_system": system_prompt,
                "enable_search": False,  # 短问候不需要 web search
                # 关键：跳过 short_term 历史。否则历史里的长简报 turn 会
                # 污染 LLM tone，stage 1 输出从 8-15 字漂移到 100+ 字。
                "skip_short_term": True,
                # v4 segment 1: wake_call trigger.name 在 PROACTIVE_ORIGINS 内
                # → renderer Mode.PROACTIVE。
                "turn_origin": trigger.name,
            },
        },
    }

    voice_model: Optional[str] = character.voice_model
    tts_engine = get_tts_engine(voice_model)
    # v4 segment 2 §2.5:解析 voice_model.tts_language(ja/en/zh)给 extract_tts_text
    tts_language = "zh"
    if voice_model:
        try:
            _vm_obj = json.loads(voice_model)
            tts_language = (_vm_obj or {}).get("tts_language", "zh") or "zh"
        except (json.JSONDecodeError, TypeError):
            tts_language = "zh"
    tts_enabled = get_tts_enabled()

    # bugfix-4: 同 upper proactive path — 设 TTS source for log
    from backend.observability.tts_log import set_tts_call_context
    _tts_source = "activity_smart" if "activity" in trigger.name else "proactive"
    set_tts_call_context(
        source=_tts_source, character_id=target_char_id, user_id=user_id,
    )

    connection_manager = _ws.connection_manager
    proactive_meta = {
        "proactive": True,
        "proactive_trigger": trigger.name,
    }

    async def _push(msg: dict) -> None:
        try:
            await connection_manager.push(user_id, msg)
        except Exception as exc:
            logger.warning("[wake_call] push failed: %s", exc)

    async def _send_audio(audio: bytes) -> None:
        b64 = base64.b64encode(audio).decode()
        await _push({"type": "audio_chunk", "content": b64, **proactive_meta})

    chat_agent = ChatAgent()
    audio_queue: "asyncio.Queue[Optional[asyncio.Task[Optional[bytes]]]]" = asyncio.Queue()
    pending_tts: List[asyncio.Task] = []
    consumer: Optional[asyncio.Task] = None
    if tts_enabled:
        consumer = asyncio.create_task(_ws._tts_audio_consumer(audio_queue, _send_audio))

    reply_parts: List[str] = []
    turn_emotion = "默认"
    emotion_resolved = False

    try:
        async for sentence in chat_agent.stream(chat_msg):
            if not emotion_resolved:
                parsed_emotion, sentence = _parse_emotion(sentence)
                turn_emotion = parsed_emotion
                emotion_resolved = True
                if parsed_emotion and parsed_emotion != "默认":
                    await _push({"type": "emotion", "value": parsed_emotion, **proactive_meta})

            _thinking, sentence = _parse_thinking(sentence)
            parsed_motion, sentence = _parse_motion(sentence)
            if parsed_motion:
                await _push({"type": "motion", "value": parsed_motion, **proactive_meta})

            # hotfix-7：state_update tag per-segment 剥离 + apply（同 run_trigger）。
            parsed_state, sentence = _parse_state_update(sentence)
            if parsed_state and target_char_id is not None:
                await _apply_proactive_state_update(
                    _push, user_id, target_char_id, parsed_state, proactive_meta,
                )

            if not sentence.strip():
                continue
            reply_parts.append(sentence)
            # hotfix-7 commit 2：text_chunk 最后一道 strip 兜底（同 run_trigger）。
            # v4 segment 2 §2.5:字幕剥 ja/en,TTS 走 extract_tts_text。
            final_chunk = strip_ja_en_tags_for_subtitle(
                strip_all_for_tts(sentence)
            )
            if not final_chunk.strip():
                continue
            await _push({"type": "text_chunk", "content": final_chunk, **proactive_meta})

            if tts_enabled and consumer is not None:
                tts_text = extract_tts_text(sentence, tts_language)
                if not tts_text or not tts_text.strip():
                    continue
                task = asyncio.create_task(
                    _ws._tts_synth_with_timeout(
                        tts_engine, tts_text, turn_emotion,
                        idx=len(reply_parts),
                    )
                )
                pending_tts.append(task)
                await audio_queue.put(task)

        if tts_enabled and consumer is not None:
            await audio_queue.put(None)
            await consumer

    except Exception:
        logger.exception("[wake_call] ChatAgent stream failed")
        await _push({"type": "error", "message": "wake_call stream failed", **proactive_meta})
    finally:
        if consumer is not None and not consumer.done():
            consumer.cancel()
        for t in pending_tts:
            if not t.done():
                t.cancel()

    await _push({"type": "done", **proactive_meta})

    # 持久化：与 morning_briefing 同样的双写（chat_history + short_term）
    full_reply = _strip_format_tags("".join(reply_parts))
    if full_reply:
        try:
            await short_term_memory.add(user_id, "assistant", full_reply)
        except Exception:
            logger.exception("[wake_call] short_term add failed")

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
            logger.exception("[wake_call] persist assistant row failed")

    logger.info(
        "[wake_call] stage 1 done user=%s char=%s greeting_len=%d pending_id=%s",
        user_id, target_char_id, len(full_reply), pending_id,
    )

    return {
        "text": full_reply,
        "character_id": target_char_id,
        "conversation_id": conv_id,
        "proactive_trigger": trigger.name,
        "audio_bytes": 0,
        "pending_id": pending_id,
    }


__all__ = [
    "ProactiveTrigger",
    "run_trigger",
    "run_wake_call_trigger",
    "aggregate_briefing_data",
]
