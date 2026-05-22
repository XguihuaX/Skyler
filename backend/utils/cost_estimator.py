"""INV-9 §7 · Fish s2-pro cost estimator + per-user cap aggregation。

per INV-8 §1.3.6 决策 5 重写 + Phase 2 §7 收尾刀 PM lock(2026-05-22):
  - 本地累计 char × language → bytes × cost rate → 估 cost
  - per-user daily/monthly cost cap 由 ``profile_data`` JSON 字段控制
  - 触达 cap 或 API 失败 fallback CosyVoice + WS toast event

cost 模型:
  Fish s2-pro $15 / 1M UTF-8 bytes(per INV-8 §1.3 stage 1 docs + INV-8
  §1.3.10 stage 2 实证)。日语 1 char ≈ 3 bytes UTF-8 → Mai 日语 100 字
  回复 ≈ $0.0045/turn(per INV-9 中插 sweep 实测校准:估算原偏高 5x,
  实际 ~5.6% baseline)。

default cap(PM 2026-05-22 lock):per-user $1/day + $20/month。$1/day ≈
220+ turns 余裕(per Step 5 + Part 1/2 实测 ~$0.028/19 calls = $0.0015/call)。

聚合策略:
  - tts_call_log 现 schema 无 user_id 列(per momoos.db PRAGMA);
    本实现按单用户 default 场景:SUM(cost_estimate) WHERE model='s2-pro'
    AND timestamp >= window_start;聚合**不分 user**(单用户场景准确,
    多用户场景偏保守 — 因为 cap 共享会更早触达)
  - multi-user 精确 per-user 聚合需 tts_call_log 加 user_id 列,留 v4.1+
    backlog(per INV-8 §1.收口.2 Q7 single-user 假设)
"""
from __future__ import annotations
import json
import logging
from datetime import datetime, time as dtime
from typing import Optional, Tuple

from sqlalchemy import text

from backend.database import engine

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────
# Cost rates · per INV-8 §1.3.6 + INV-9 中插 sweep 校准
# ─────────────────────────────────────────────────────────────────────────

# Fish s2-pro: $15 per 1M UTF-8 bytes
FISH_S2_PRO_COST_PER_M_BYTES_USD: float = 15.0

# Default caps · PM Phase 2 §7 lock(per Step 5 + Part 1/2 实测 $0.0015/call,
# $1/day ≈ 660 turns 余裕,远高于原估 40 turns 估算偏高 ~5x)
DEFAULT_DAILY_CAP_USD: float = 1.0
DEFAULT_MONTHLY_CAP_USD: float = 20.0

# 近似 UTF-8 bytes/char(per INV-8 §1.3.6):
#   ja / zh ≈ 3 bytes/char(多字节 CJK)
#   en ≈ 1 byte/char
_BYTES_PER_CHAR: dict[str, int] = {"ja": 3, "zh": 3, "en": 1}


# ─────────────────────────────────────────────────────────────────────────
# Estimation functions(pure · 不依赖 DB)
# ─────────────────────────────────────────────────────────────────────────


def estimate_fish_cost_for_text(text_input: Optional[str]) -> float:
    """精确估算 Fish s2-pro cost · 按真实 UTF-8 bytes。

    适用 caller 持有完整 text 的场景(synth 调用前 / log INSERT 前)。
    """
    if not text_input:
        return 0.0
    bytes_count = len(text_input.encode("utf-8"))
    return round(bytes_count / 1_000_000 * FISH_S2_PRO_COST_PER_M_BYTES_USD, 6)


def estimate_fish_cost_for_chars(input_chars: int, lang: str = "ja") -> float:
    """近似估算 · input_chars × bytes/char × rate。

    适用 log 聚合 / 历史数据估算(`tts_call_log.input_preview` 截 200 字符
    不够精确,但 input_chars 总数完整)。Mai 主路径 lang='ja' (3 bytes/char)。
    """
    if input_chars <= 0:
        return 0.0
    bpc = _BYTES_PER_CHAR.get((lang or "ja").lower(), 3)
    return round(input_chars * bpc / 1_000_000 * FISH_S2_PRO_COST_PER_M_BYTES_USD, 6)


# ─────────────────────────────────────────────────────────────────────────
# Cap reading · profile_data JSON
# ─────────────────────────────────────────────────────────────────────────


def get_user_cost_caps(profile_data: Optional[dict]) -> Tuple[float, float]:
    """从 profile_data JSON 读 (daily_cap_usd, monthly_cap_usd);缺字段返 default。

    profile_data JSON 字段:
      - fish_daily_cost_cap_usd: float(默 DEFAULT_DAILY_CAP_USD = 1.0)
      - fish_monthly_cost_cap_usd: float(默 DEFAULT_MONTHLY_CAP_USD = 20.0)
    """
    if not profile_data or not isinstance(profile_data, dict):
        return (DEFAULT_DAILY_CAP_USD, DEFAULT_MONTHLY_CAP_USD)

    daily_raw = profile_data.get("fish_daily_cost_cap_usd")
    monthly_raw = profile_data.get("fish_monthly_cost_cap_usd")

    try:
        daily = float(daily_raw) if daily_raw is not None else DEFAULT_DAILY_CAP_USD
    except (TypeError, ValueError):
        daily = DEFAULT_DAILY_CAP_USD
    try:
        monthly = float(monthly_raw) if monthly_raw is not None else DEFAULT_MONTHLY_CAP_USD
    except (TypeError, ValueError):
        monthly = DEFAULT_MONTHLY_CAP_USD

    return (daily, monthly)


# ─────────────────────────────────────────────────────────────────────────
# DB aggregation · tts_call_log
# ─────────────────────────────────────────────────────────────────────────


async def _sum_fish_cost_since(window_start: datetime) -> float:
    """SUM(cost_estimate) WHERE model='s2-pro' AND timestamp >= window_start。

    聚合不分 user(per docstring 顶部 single-user assumption)。
    无 row → 返 0.0。任何 DB 异常 → 返 0.0 + log(让 cap check 默认放行,
    避免 DB 抖动导致 fish 路径全断)。
    """
    try:
        async with engine.begin() as conn:
            row = (await conn.execute(text("""
                SELECT COALESCE(SUM(cost_estimate), 0.0) FROM tts_call_log
                WHERE model = :model AND timestamp >= :start
            """), {"model": "s2-pro", "start": window_start})).first()
            return float(row[0]) if row else 0.0
    except Exception as exc:
        logger.warning(
            "[cost_estimator] aggregate query failed (silent 0.0): %s", exc,
        )
        return 0.0


async def get_today_fish_cost_usd() -> float:
    """Today's cumulative fish s2-pro cost in USD(从 utc 当日 00:00 起)。"""
    today_start = datetime.combine(datetime.utcnow().date(), dtime.min)
    return await _sum_fish_cost_since(today_start)


async def get_month_fish_cost_usd() -> float:
    """Month's cumulative fish s2-pro cost in USD(从 utc 当月 1 日 00:00 起)。"""
    now = datetime.utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return await _sum_fish_cost_since(month_start)


# ─────────────────────────────────────────────────────────────────────────
# Cap check · 主入口(ws.py / chat.py 调 fish 前调用)
# ─────────────────────────────────────────────────────────────────────────


async def check_fish_cost_cap_exceeded(user_id: str) -> dict:
    """检查 user 的 fish cost 是否超 daily / monthly cap。

    Args:
        user_id: 用户 ID(default 单用户场景);多用户场景待 v4.1+ tts_call_log
                 加 user_id 列后改聚合 query。

    Returns:
        ``{
            "exceeded": bool,                # 是否触达任一 cap
            "reason": "daily" | "monthly" | None,
            "today_cost": float,             # USD
            "month_cost": float,
            "daily_cap": float,
            "monthly_cap": float,
        }``

        DB 异常 → ``exceeded=False`` 默认放行(避免 DB 抖动 fish 路径全断)。
    """
    # 读 user.profile_data
    profile_data: Optional[dict] = None
    try:
        from backend.database import AsyncSessionLocal
        from backend.database.models import User
        from sqlalchemy import select
        async with AsyncSessionLocal() as session:
            u = (await session.execute(
                select(User).where(User.user_id == user_id)
            )).scalar_one_or_none()
        if u and u.profile_data:
            try:
                profile_data = json.loads(u.profile_data)
            except (json.JSONDecodeError, TypeError):
                profile_data = None
    except Exception as exc:
        logger.warning(
            "[cost_estimator] profile_data read failed for user=%s (silent default): %s",
            user_id, exc,
        )
        profile_data = None

    daily_cap, monthly_cap = get_user_cost_caps(profile_data)

    today_cost = await get_today_fish_cost_usd()
    month_cost = await get_month_fish_cost_usd()

    reason: Optional[str] = None
    if today_cost >= daily_cap:
        reason = "daily"
    elif month_cost >= monthly_cap:
        reason = "monthly"

    return {
        "exceeded": reason is not None,
        "reason": reason,
        "today_cost": round(today_cost, 6),
        "month_cost": round(month_cost, 6),
        "daily_cap": daily_cap,
        "monthly_cap": monthly_cap,
    }
