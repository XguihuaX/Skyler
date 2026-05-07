"""v3-G chunk 2.6 — ``proactive.snooze_wake_call`` capability。

让 LLM 在 stage 2 检测到用户拒绝起床时调用，把下次 wake call 推迟 N 分钟。

关键设计
========

* **APScheduler 原生 DateTrigger**：用 ``add_job(trigger=DateTrigger(...))``
  注册一次性 job，run_date=now+minutes。**不**改 cron 配置，不污染主
  cron job state。
* **冲突避免**：算 snooze 时间若超过下一次正常 wake_call cron，则跳过
  snooze（避免重复叫早 / 用户睡过头反而被叫两次）。
* **ID 唯一性**：snooze job id = ``f"wake_call_snooze_{epoch_ms}"``，避免
  并发 snooze 命名冲突。
* **缺省值**从 ``config.proactive.wake_call_briefing.default_snooze_minutes``
  读，不从 LLM 传入推断。LLM 显式 minutes=N 优先。
* **range 限制**：5-120 min。LLM 传 1 min 没有意义（连两次叫醒之间至少要
  喘口气），传 240 min 跨 4 小时基本是错（用户 8 点叫早不会延到 12 点）。
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Any

from apscheduler.triggers.date import DateTrigger

from backend.capabilities import Consumer, TriggerMode, register_capability
from backend.scheduler import cron as cron_module

logger = logging.getLogger(__name__)

# wake_call 的 cron job id（main.py 注册时使用）。本 module 用它查"下次正
# 常 cron 触发时间"做冲突避免。
WAKE_CALL_CRON_JOB_ID = "wake_call_cron"


def _now_aware() -> datetime:
    """APScheduler 内部 timezone-aware；我们这里用 scheduler 的 timezone。"""
    return datetime.now(cron_module._scheduler.timezone)


@register_capability(
    name="proactive.snooze_wake_call",
    display_name="推迟早晨叫醒",
    description=(
        "推迟下次「叫醒」简报触发 N 分钟。当用户在 wake_call 早晨叫醒后"
        "明确表示拒绝起床（'再睡' / '还早' / '困' / '不想起' / '再睡 X 分钟'）"
        "时主动调用。minutes 参数：用户说'再睡 X 分钟'则 minutes=X，没明说"
        "用 config 默认（一般 30）。范围 5-120。\n\n"
        "调用前不需要询问'要推迟多久' —— 从用户原话推断或用默认即可。"
        "不要在用户没明确拒绝起床时调用（如'今天天气如何'是切换话题，"
        "不是拒绝，应直接回答天气，**不**调本 capability）。\n\n"
        "返回 ``{ok, run_at, message}``：``run_at`` 是即将触发的 ISO 时间；"
        "``ok=false`` 一般是 snooze 时间超过了下一次正常 cron（用户已经"
        "睡过头，下次正常叫醒就够了，不需要重复）。"
    ),
    category="system",
    consumers=[Consumer.CHAT_AGENT],
    trigger_modes=[TriggerMode.ON_DEMAND],
    icon="alarm-snooze",
    user_visible=False,  # tool surface 噪音减少：用户不需在面板看到这个
    parameters_schema={
        "type": "object",
        "properties": {
            "minutes": {
                "type": "integer",
                "minimum": 5,
                "maximum": 120,
                "description": "推迟分钟数。用户说'再睡 X 分钟'传 X，否则用 30 默认。",
            },
        },
        "required": [],
    },
)
async def snooze_wake_call(minutes: int = 0, **_kwargs) -> dict[str, Any]:
    # 解析 minutes：LLM 没传 / 传 0 / 传非法 → 用 config 默认
    from backend.proactive.triggers.wake_call_briefing import (
        _resolve_default_snooze_minutes,
    )
    if not isinstance(minutes, int) or minutes < 5 or minutes > 120:
        minutes = _resolve_default_snooze_minutes()

    snooze_at = _now_aware() + timedelta(minutes=minutes)

    # 冲突避免：snooze 时间晚于下一次正常 cron → 跳过
    next_cron_run = None
    job = cron_module._scheduler.get_job(WAKE_CALL_CRON_JOB_ID)
    if job is not None and job.next_run_time is not None:
        next_cron_run = job.next_run_time
        if snooze_at >= next_cron_run:
            logger.info(
                "[snooze] skipped: snooze_at=%s >= next regular cron=%s",
                snooze_at.isoformat(), next_cron_run.isoformat(),
            )
            return {
                "ok": False,
                "run_at": None,
                "message": (
                    f"snooze 时间（{snooze_at.isoformat()}）超过了下一次正常 cron"
                    f"（{next_cron_run.isoformat()}）—— 跳过 snooze，用户睡到下"
                    f"次正常叫醒即可。"
                ),
            }

    # 注册 one-shot DateTrigger job
    job_id = f"wake_call_snooze_{int(time.time() * 1000)}"
    try:
        cron_module._scheduler.add_job(
            _run_snooze_handler,
            trigger=DateTrigger(run_date=snooze_at, timezone=cron_module._scheduler.timezone),
            id=job_id,
            name=f"wake_call snooze ({minutes}min)",
            replace_existing=False,
        )
    except Exception as exc:
        logger.exception("[snooze] add_job failed")
        return {"ok": False, "run_at": None, "message": f"调度失败：{exc}"}

    logger.info(
        "[snooze] registered job=%s run_at=%s (%d min later)",
        job_id, snooze_at.isoformat(), minutes,
    )
    return {
        "ok": True,
        "run_at": snooze_at.isoformat(),
        "message": f"好的，{minutes} 分钟后再叫你～",
        "job_id": job_id,
    }


async def _run_snooze_handler() -> None:
    """one-shot snooze 触发时调本函数 —— 复用 deliver_wake_call_briefing
    路径，等价于 cron 又跑了一次。**不**记 chat_history 一行 "snooze 已
    触发" 之类，让用户感受跟正常 cron 触发一致。
    """
    from backend.scheduler.briefing import deliver_wake_call_briefing
    logger.info("[snooze] firing wake_call (snoozed cycle)")
    await deliver_wake_call_briefing()


__all__ = ["snooze_wake_call", "WAKE_CALL_CRON_JOB_ID"]
