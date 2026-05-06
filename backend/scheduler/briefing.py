"""v3-G chunk 1 — 起床简报 v0.1（最简模板拼接）。

设计取舍（v0.1 故意做最薄）：

* **文本生成**走纯模板：``"早上好，今天你有：A; B; C。"``。这是占位实
  现，便于先把 cron + delivery 链路跑通；chunk 2 升级为 ChatAgent 智能
  生成（含联网新闻 / 天气 / 个性化语气）。
* **角色 / 音色**：因为后端不持久"当前角色"概念（前端 zustand 局部状
  态），取 ``Momo (id=1)`` 作权威用户角色 —— v3-G' chunk 1c 已经把 Momo
  默认音色锁定到 cosyvoice/longyumi_v3，与用户日常听感一致。
* **delivery v0.1**：通过 ``ConnectionManager.push`` 把简报文本作 ``notify``
  事件推到前端（前端 useWebSocket.ts 已有 case 处理）；同步合成 wav 写到
  ``~/.skyler/last_briefing.wav`` 方便断点验证。**proactive 音频实时播放
  路径**（在没有 chat turn 上下文时把 audio_chunk 推到前端 + 触发
  playNextAudio queue）属 chunk 2 真实简报上线时的工作 —— 现在不上线。
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select

from backend.capabilities.calendar import today_events
from backend.config import config_yaml
from backend.database import AsyncSessionLocal
from backend.database.models import Character
from backend.tts import get_tts_engine

logger = logging.getLogger(__name__)


SKYLER_HOME      = Path("~/.skyler").expanduser()
LAST_BRIEFING_WAV = SKYLER_HOME / "last_briefing.wav"


def _get_briefing_config() -> dict:
    return config_yaml.get("briefing") or {}


def _get_timezone() -> str:
    sched_cfg = config_yaml.get("scheduler") or {}
    return str(sched_cfg.get("timezone") or "Asia/Tokyo")


# ---------------------------------------------------------------------------
# 1. 文本生成（v0.1 模板）
# ---------------------------------------------------------------------------

def _format_event_for_briefing(event: dict, tz: ZoneInfo) -> str:
    """把单个事件 dict 转成简报里说的一句。

    e.g.
    * timed event：``"上午 10 点，团队同步会"``
    * all-day：``"全天，团建活动"``
    """
    title = event.get("title") or "(无标题)"
    if event.get("all_day"):
        return f"全天 {title}"
    raw_start = event.get("start") or ""
    if not raw_start:
        return title
    # raw_start 是 RFC3339 e.g. "2026-05-07T09:00:00+09:00"
    try:
        dt = datetime.fromisoformat(raw_start)
    except ValueError:
        return f"{raw_start} {title}"
    dt_local = dt.astimezone(tz)
    hour = dt_local.hour
    minute = dt_local.minute
    period = "上午" if hour < 12 else "下午" if hour < 18 else "晚上"
    show_hour = hour if hour <= 12 else hour - 12
    if minute == 0:
        time_str = f"{period}{show_hour}点"
    else:
        time_str = f"{period}{show_hour}点{minute:02d}"
    return f"{time_str} {title}"


async def generate_morning_briefing() -> str:
    """生成简报文本。任何上游失败都吞成 friendly fallback —— cron 不允许炸。"""
    try:
        events = await today_events()
    except Exception as exc:
        logger.warning("[briefing] today_events failed: %s", exc)
        return "早上好，日历暂时连不上，但今天也是新的一天。"

    if not events:
        return "早上好，今天没有日程，可以好好休息～"

    tz = ZoneInfo(_get_timezone())
    lines = [_format_event_for_briefing(e, tz) for e in events]
    return "早上好，今天你有：" + "；".join(lines) + "。"


# ---------------------------------------------------------------------------
# 2. Momo 音色解析
# ---------------------------------------------------------------------------

async def _get_momo_voice_model() -> Optional[str]:
    """读 DB Momo 角色的 voice_model JSON 字符串。失败返 None。"""
    async with AsyncSessionLocal() as session:
        row = (await session.execute(
            select(Character).where(Character.name == "Momo")
        )).scalar_one_or_none()
    if row is None:
        return None
    return row.voice_model


# ---------------------------------------------------------------------------
# 3. delivery
# ---------------------------------------------------------------------------

async def deliver_morning_briefing() -> dict[str, Any]:
    """生成 + 推送 + 合成 wav。返回 metadata 给 test endpoint 用。

    步骤：
      1. 生成简报文本
      2. 经 ConnectionManager 把 ``notify`` 事件推给所有已注册的 WS（前端
         自动弹 toast）
      3. 用 Momo voice_model 合成 wav，写到 ``~/.skyler/last_briefing.wav``
         作离线验证
    """
    text = await generate_morning_briefing()
    logger.info("[briefing] text generated: %s", text[:100])

    # 步骤 2：推 notify。这里 import 放函数内，避免 backend.scheduler.briefing
    # 在 import time 触发 backend.routes.ws import 链。
    from backend.routes.ws import connection_manager
    user_id = str(config_yaml.get("default_user_id") or "default")
    try:
        await connection_manager.push(user_id, {"type": "notify", "content": text})
    except Exception as exc:
        logger.warning("[briefing] push notify failed: %s", exc)

    # 步骤 3：合成 wav 落盘
    voice_model = await _get_momo_voice_model()
    audio_bytes: Optional[bytes] = None
    audio_path: Optional[str] = None
    try:
        engine = get_tts_engine(voice_model)
        # emotion 走 neutral —— 起床问候不带强情感色彩；instruct-aware 音色
        # 会落 plain 路径（neutral 不在 chunk 1 实施的 instruct 白名单）。
        audio_bytes = await engine.synthesize(text, emotion="neutral")
        if audio_bytes:
            SKYLER_HOME.mkdir(parents=True, exist_ok=True)
            LAST_BRIEFING_WAV.write_bytes(audio_bytes)
            audio_path = str(LAST_BRIEFING_WAV)
            logger.info(
                "[briefing] wav saved: %s (%d bytes)",
                audio_path, len(audio_bytes),
            )
    except Exception as exc:
        logger.warning("[briefing] tts synth failed: %s", exc)

    return {
        "text": text,
        "audio_path": audio_path,
        "audio_bytes": len(audio_bytes) if audio_bytes else 0,
        "voice_model": voice_model,
    }
