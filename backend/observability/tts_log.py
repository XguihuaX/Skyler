"""Bugfix-4 — TTS call log instrumentation。

设计要点
--------
ContextVar 模式:caller (ws.py / proactive / activity_smart / preview) 在调
``engine.synthesize(...)`` 之前 ``set_tts_call_context(source='chat', ...)``,
``CosyVoiceTTS.synthesize`` 在合成完后从 ContextVar 读 source 写 log。

为啥 ContextVar 而不是 kwarg
---------------------------
TTSBase.synthesize 现在签名是 ``(text, emotion)``,改成 ``(text, emotion, *,
source, character_id)`` 涉及 3 个子类 + Preprocessing 包装 + 历史 caller。
ContextVar 在 asyncio 下 task-local + 上游 caller 一行 set,下游 transparent
读;TTSBase 接口不破坏,Edge/SoVITS 子类未来要埋点也走同一通道。

字段
----
``TTSCallContext``:
  - source       'chat' | 'proactive' | 'activity_smart' | 'preview' | 'unknown'
  - character_id Optional[int] (for chat / proactive)
  - user_id      Optional[str] (审计辅助;不直接进表为隐私考虑)

成本估算
--------
CosyVoice 单价随 model 不同。当前 yaml default ``cosyvoice-v3-flash``:
~¥0.0007/char。复刻 ``cosyvoice-v3.5-plus``: ~¥0.001/char。本模块用 dict
``_COST_PER_CHAR`` 维护;未知 model 用 0.0007 fallback。**估算非精确账单**。
"""
from __future__ import annotations

import asyncio
import contextvars
import logging
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import text

from backend.database import engine

logger = logging.getLogger(__name__)


@dataclass
class TTSCallContext:
    source: str = "unknown"
    character_id: Optional[int] = None
    user_id: Optional[str] = None


# task-local context. caller set / synth 读。
_tts_call_ctx: contextvars.ContextVar[Optional[TTSCallContext]] = (
    contextvars.ContextVar("tts_call_context", default=None)
)


def set_tts_call_context(
    source: str,
    character_id: Optional[int] = None,
    user_id: Optional[str] = None,
) -> contextvars.Token:
    """Caller 在 synth 前 set;返回 Token 可 ``reset`` 回老值 (一般不需要,
    task 结束 ContextVar 自动 GC)。"""
    return _tts_call_ctx.set(
        TTSCallContext(source=source, character_id=character_id, user_id=user_id)
    )


def get_tts_call_context() -> TTSCallContext:
    """Synth 内部读;若 caller 没 set,返回 default ``source='unknown'``。"""
    ctx = _tts_call_ctx.get()
    return ctx if ctx is not None else TTSCallContext()


# Model → 单价 (¥/char)。先存常见的 4 个;未知 model 走 fallback。
_COST_PER_CHAR: dict[str, float] = {
    "cosyvoice-v3-flash":  0.00007,   # DashScope 实时 TTS 报价
    "cosyvoice-v3-plus":   0.0007,
    "cosyvoice-v3.5-plus": 0.001,
    "cosyvoice-v3.5-flash": 0.0007,
}
_COST_FALLBACK = 0.0007

# INV-9 §7 · Fish s2-pro / s1 / v1.6 走 byte-based 估算(per INV-8 §1.3.6
# + cost_estimator.py):$15 / 1M UTF-8 bytes;不在 _COST_PER_CHAR 表。
_FISH_MODEL_PREFIXES: tuple[str, ...] = ("s2-pro", "s1", "v1.6")


def estimate_cost(
    input_chars: int,
    model: Optional[str],
    raw_text: Optional[str] = None,
) -> float:
    """估算 TTS cost in USD。

    INV-9 §7:fish 模型(s2-pro / s1 / v1.6)走 byte-based 估算(per
    ``backend.utils.cost_estimator``);其它 cosyvoice / sovits / edge 走
    per-char rate(原行为)。

    Args:
        input_chars: text 长度(总 chars)。
        model: TTS 模型 name(如 's2-pro' / 'cosyvoice-v3-flash')。
        raw_text: INV-9 §7 新增。fish 路径若提供则用真实 UTF-8 bytes 计费;
                 否则用 input_chars × 3(日语近似 3 bytes/char 兜底)。
                 caller 传完整 text 时此参数精确;truncate 后传偏低估。
    """
    if model in _FISH_MODEL_PREFIXES:
        # 延迟 import 避免循环(observability 依赖 utils.cost_estimator,
        # cost_estimator 依赖 backend.database;启动序列容差)
        from backend.utils.cost_estimator import (
            estimate_fish_cost_for_chars,
            estimate_fish_cost_for_text,
        )
        if raw_text:
            return estimate_fish_cost_for_text(raw_text)
        return estimate_fish_cost_for_chars(input_chars, lang="ja")
    rate = _COST_PER_CHAR.get(model or "", _COST_FALLBACK)
    return round(input_chars * rate, 4)


_PREVIEW_MAX_LEN = 200


async def log_tts_call(
    *,
    success: bool,
    voice: str,
    model: Optional[str],
    input_chars: int,
    input_preview: str,
    error_message: Optional[str] = None,
) -> None:
    """INSERT one row into tts_call_log。永不抛 (log layer 不该影响合成路径)。

    INV-9 §7:cost = estimate_cost(input_chars, model, raw_text=input_preview)
    fish 模型走 byte-based 精确估算(per backend.utils.cost_estimator);
    raw_text 用 input_preview 作 full text 候选(caller 多数传完整 text,
    在 log_tts_call 内部才截 200 chars 给 preview 列)。
    """
    ctx = get_tts_call_context()
    # INV-9 §7:fish 路径 raw_text 传 full text(caller fish.py / cosyvoice.py
    # 调 log_tts_call(input_preview=text) 传完整 text;此处用 input_preview 作
    # raw_text 给 estimate_cost 算精确 UTF-8 bytes;truncate 给 preview 列在下方)
    cost = estimate_cost(input_chars, model, raw_text=input_preview)
    preview = (input_preview or "")[:_PREVIEW_MAX_LEN]
    try:
        async with engine.begin() as conn:
            await conn.execute(text("""
                INSERT INTO tts_call_log
                    (source, character_id, voice, model, input_chars,
                     input_preview, cost_estimate, success, error_message)
                VALUES (:s, :cid, :v, :m, :ic, :ip, :ce, :ok, :err)
            """), {
                "s": ctx.source,
                "cid": ctx.character_id,
                "v": voice,
                "m": model,
                "ic": input_chars,
                "ip": preview,
                "ce": cost,
                "ok": 1 if success else 0,
                "err": error_message,
            })
    except Exception as exc:
        # log table 写失败不影响 TTS 主路径;真出错也只是少一条记录
        logger.warning(
            "[tts.log] insert failed (silently dropped): %s",
            exc,
        )


def log_tts_call_sync(**kwargs) -> None:
    """同步入口:在 sync code (eg CosyVoiceTTS._blocking_synthesize 内) 用。
    schedule async insert 到 event loop 上, sync 调用方 fire-and-forget。"""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(log_tts_call(**kwargs))
        else:
            # 极少见 — 测试环境同步路径无 loop, 直接同步 run
            asyncio.run(log_tts_call(**kwargs))
    except Exception as exc:
        logger.warning("[tts.log] sync wrapper failed: %s", exc)
