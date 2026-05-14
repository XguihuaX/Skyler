"""Bugfix-4 — tts_call_log 聚合查询。

GET /api/observability/tts/usage 走这里。三档 range:
- today   : 当天 00:00 至今
- month   : 当月 1 号 至今
- recent  : 不分时间, 最近 N 条 (调度走 list_recent_calls)
"""
from __future__ import annotations

import logging
from datetime import datetime, time as dtime, timezone
from typing import Optional

from sqlalchemy import text

from backend.database import engine

logger = logging.getLogger(__name__)


def _today_start_iso() -> str:
    """本地 (server 时区) 当天 00:00 的 ISO 字符串 (SQLite CURRENT_TIMESTAMP 是 UTC)。

    简化:用 UTC 当天 00:00。dogfood 单用户场景时区差 8h 不至于让 today 错位
    一整天 (用户在 8h 内不会有上千 TTS call)。需要严格本地时区时改 timezone-aware。
    """
    today = datetime.now(timezone.utc).date()
    return datetime.combine(today, dtime.min, tzinfo=timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def _month_start_iso() -> str:
    now = datetime.now(timezone.utc)
    return now.replace(
        day=1, hour=0, minute=0, second=0, microsecond=0,
    ).strftime("%Y-%m-%d %H:%M:%S")


async def aggregate_usage(range_: str = "today") -> dict:
    """聚合 tts_call_log 用量,返回 dict::

        {
          "range": "today",
          "total_calls": int,
          "total_chars": int,
          "total_cost_yuan": float,
          "by_source": {
              "chat":     {"calls": int, "chars": int, "cost": float},
              "proactive": {...},
              ...
          },
          "avg_chars_per_call": int | None,
          "anomaly_calls": [...]   # input_chars > 500
        }
    """
    where_clause = ""
    params: dict = {}
    if range_ == "today":
        where_clause = "WHERE timestamp >= :since"
        params["since"] = _today_start_iso()
    elif range_ == "month":
        where_clause = "WHERE timestamp >= :since"
        params["since"] = _month_start_iso()
    # else: 不加 WHERE = 全量

    async with engine.begin() as conn:
        # 1. 总计 + per-source 聚合
        rows = (await conn.execute(text(f"""
            SELECT
                source,
                COUNT(*)       AS calls,
                SUM(input_chars) AS chars,
                SUM(cost_estimate) AS cost
            FROM tts_call_log
            {where_clause}
            GROUP BY source
        """), params)).fetchall()

        # 2. 异常 calls (input_chars > 500) — 一般 emotion tag 漏的征兆
        anomaly_rows = (await conn.execute(text(f"""
            SELECT id, timestamp, source, character_id, voice, input_chars,
                   input_preview, success, error_message
            FROM tts_call_log
            {where_clause}
            {'AND' if where_clause else 'WHERE'} input_chars > 500
            ORDER BY input_chars DESC
            LIMIT 10
        """), params)).fetchall()

    total_calls = sum(r[1] or 0 for r in rows)
    total_chars = sum(r[2] or 0 for r in rows)
    total_cost = sum(r[3] or 0.0 for r in rows)
    by_source: dict[str, dict] = {}
    for r in rows:
        by_source[r[0] or "unknown"] = {
            "calls": int(r[1] or 0),
            "chars": int(r[2] or 0),
            "cost": round(float(r[3] or 0.0), 4),
        }

    avg_chars = int(total_chars / total_calls) if total_calls > 0 else None

    anomalies = [
        {
            "id": r[0],
            "timestamp": r[1],
            "source": r[2],
            "character_id": r[3],
            "voice": r[4],
            "input_chars": r[5],
            "input_preview": r[6],
            "success": bool(r[7]),
            "error_message": r[8],
        }
        for r in anomaly_rows
    ]

    return {
        "range": range_,
        "total_calls": int(total_calls),
        "total_chars": int(total_chars),
        "total_cost_yuan": round(float(total_cost), 4),
        "by_source": by_source,
        "avg_chars_per_call": avg_chars,
        "anomaly_calls": anomalies,
    }


async def list_recent_calls(limit: int = 20) -> list[dict]:
    """最近 N 条 TTS call。前端 [详细记录] modal 用。"""
    limit = max(1, min(limit, 200))
    async with engine.begin() as conn:
        rows = (await conn.execute(text(
            "SELECT id, timestamp, source, character_id, voice, model, "
            "input_chars, input_preview, cost_estimate, success, error_message "
            "FROM tts_call_log ORDER BY id DESC LIMIT :n"
        ), {"n": limit})).fetchall()
    return [
        {
            "id": r[0], "timestamp": r[1], "source": r[2],
            "character_id": r[3], "voice": r[4], "model": r[5],
            "input_chars": r[6], "input_preview": r[7],
            "cost_estimate": r[8], "success": bool(r[9]),
            "error_message": r[10],
        }
        for r in rows
    ]
