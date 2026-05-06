"""v3-G chunk 0 — APScheduler-based cron / interval scheduler.

放在 ``backend/scheduler/`` 内，与既有 ``task.py`` 的 AlarmScheduler 平行：

* ``task.py`` AlarmScheduler — 30s 轮询 DB 触发到期 alarm（v2.5 起）
* ``cron.py``  cron_scheduler  — APScheduler 单例，跑 cron 表达式 / interval
  任务，给 v3-G 起的所有 capability 触发用

两个 scheduler 各自负责自己的进程内 lifecycle。lifespan 在 main.py 顺序起停。

时区：从 ``config.yaml`` 顶层 ``scheduler.timezone`` 读，缺省 Asia/Tokyo（用户日
常时区）。Beijing/Shanghai 用户可在 config.yaml 改成 Asia/Shanghai。
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from backend.config import config_yaml

logger = logging.getLogger(__name__)


def _get_timezone() -> str:
    sched_cfg = config_yaml.get("scheduler") or {}
    return str(sched_cfg.get("timezone") or "Asia/Tokyo")


# 单例。import 时立即构造，但 ``start()`` 由 lifespan 显式调用。
_scheduler: AsyncIOScheduler = AsyncIOScheduler(timezone=_get_timezone())


def schedule_cron(
    name: str,
    cron_expr: str,
    func: Callable[..., Any],
    **kwargs: Any,
) -> None:
    """注册一个 cron 任务。``name`` 唯一，重复抛 ValueError。

    cron_expr 是标准 5 段 crontab 字符串："*/15 * * * *"（每 15 分钟）。
    APScheduler 接受 6 段（带秒）也可以，按上游约定转发。
    """
    if _scheduler.get_job(name) is not None:
        raise ValueError(f"cron job {name!r} already registered")
    _scheduler.add_job(
        func,
        trigger=CronTrigger.from_crontab(cron_expr, timezone=_get_timezone()),
        id=name,
        name=name,
        kwargs=kwargs,
        replace_existing=False,
    )
    logger.info("[cron] scheduled %s with cron=%s", name, cron_expr)


def schedule_interval(
    name: str,
    seconds: int,
    func: Callable[..., Any],
    **kwargs: Any,
) -> None:
    """注册一个固定间隔触发任务。``name`` 唯一，重复抛 ValueError。"""
    if _scheduler.get_job(name) is not None:
        raise ValueError(f"interval job {name!r} already registered")
    _scheduler.add_job(
        func,
        trigger=IntervalTrigger(seconds=seconds),
        id=name,
        name=name,
        kwargs=kwargs,
        replace_existing=False,
    )
    logger.info("[cron] scheduled %s with interval=%ds", name, seconds)


def cancel_job(name: str) -> bool:
    """删除已注册任务。返回是否成功（不存在返回 False，不抛错）。"""
    if _scheduler.get_job(name) is None:
        return False
    _scheduler.remove_job(name)
    logger.info("[cron] cancelled %s", name)
    return True


def list_jobs() -> list[dict]:
    """返回当前所有注册任务的 metadata（前端调度面板备用）。"""
    out: list[dict] = []
    for job in _scheduler.get_jobs():
        out.append({
            "id": job.id,
            "name": job.name,
            "trigger": str(job.trigger),
            "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
        })
    return out


async def start() -> None:
    """启动 scheduler。幂等：已 running 则 no-op。"""
    if _scheduler.running:
        return
    _scheduler.start()
    logger.info("CronScheduler started (tz=%s)", _get_timezone())


async def shutdown() -> None:
    """关闭 scheduler。lifespan 收尾用，wait=False 不阻塞 FastAPI 收尾。"""
    if not _scheduler.running:
        return
    _scheduler.shutdown(wait=False)
    logger.info("CronScheduler shut down")


# Re-export 给 lifespan 用 —— 显式名字，避免 import 冲突 backend.scheduler.task.scheduler。
cron_scheduler = _scheduler
