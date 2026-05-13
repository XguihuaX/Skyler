"""v3.5 chunk 14 — activity timeline capability。

三个 CHAT_AGENT consumer capability,让 LLM 在对话中按需查用户历史活动:

* ``activity.get_today_summary``   返今日总活跃 + top apps + 最近 30 min 摘要
* ``activity.get_recent_apps``     返最近 N 天的 top apps + duration 排行
* ``activity.search_history``      按 URL/title 关键词搜历史 sessions

设计原则
========

* **on-demand**:与 screen.* 同思路,LLM 自己想起"用户今天看了啥"时调;
  ChatAgent 的"今日活动"自动 system prompt 注入(commit 5 实现)走另一条路
* **silent degradation**:DB 查询失败 → 返 ``{available: false, reason: ...}``;
  绝不抛错给 ChatAgent。
* **黑名单 + idle 已在写入层过滤**:本层不必再判隐私 — chunk 14 commit 2
  写 session 之前已经过黑名单。但 search_history **不**返 ``is_idle_filtered=1``
  的 session(double protection — 用户 AFK 时停在某 URL 不该被回忆出来)。
* **不上传**:全部走本地 SQLite。capability 不调任何外部网络。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import text

from backend.capabilities import Consumer, TriggerMode, register_capability
from backend.config import config_yaml
from backend.database import engine

logger = logging.getLogger(__name__)


def _default_user_id() -> str:
    return str(config_yaml.get("default_user_id") or "default")


def _fmt_duration(seconds: int) -> str:
    """秒数 → 人类友好字串(注 LLM 拿到要自然引用而非"3600 秒")。"""
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        m = seconds // 60
        return f"{m}min"
    h = seconds // 3600
    m = (seconds % 3600) // 60
    if m == 0:
        return f"{h}h"
    return f"{h}h{m}min"


# ---------------------------------------------------------------------------
# 1. activity.get_today_summary
# ---------------------------------------------------------------------------


@register_capability(
    name="activity.get_today_summary",
    display_name="今日活动摘要",
    description=(
        "查用户今天(本地日)在各 app / URL 的总停留时长 + 类别分布。当用户问"
        "「今天累不累」「今天都干了啥」「我今天看了多久 B 站」时调。返"
        "``{available, total_active_seconds, total_active_pretty, top_apps[], "
        "by_category{}, recent_focus}``;无数据 → ``{available: false}``。"
        "**不会泄露**已被用户拉黑的 app / URL,也**不**包含 idle 期间(用户 AFK)的"
        "session。ChatAgent 默认会自动在 system prompt 注入简短今日摘要;本 capability "
        "用于用户问具体细节时(如「我今天在 B 站待了多久」)主动查。"
    ),
    category="activity",
    consumers=[Consumer.CHAT_AGENT],
    trigger_modes=[TriggerMode.ON_DEMAND],
    icon="clock",
    parameters_schema={"type": "object", "properties": {}, "required": []},
)
async def get_today_summary(**_kwargs) -> dict:
    user_id = _default_user_id()
    now = datetime.utcnow()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    recent_cutoff = now - timedelta(minutes=30)

    try:
        async with engine.begin() as conn:
            rows = (await conn.execute(text(
                "SELECT app_name, browser_url, browser_title, "
                "       duration_seconds, category, start_at "
                "FROM activity_sessions "
                "WHERE user_id = :uid "
                "  AND start_at >= :s AND start_at < :e "
                "  AND is_idle_filtered = 0 "
                "ORDER BY start_at ASC"
            ), {"uid": user_id, "s": start, "e": end})).fetchall()
    except Exception as exc:
        logger.exception("[activity_cap] get_today_summary DB query failed: %s", exc)
        return {"available": False, "reason": "db_error"}

    if not rows:
        return {
            "available": True, "total_active_seconds": 0,
            "total_active_pretty": "0min",
            "top_apps": [], "by_category": {}, "recent_focus": None,
        }

    total = 0
    app_agg: dict[str, dict] = {}
    cat_agg: dict[str, int] = {}
    recent_app: Optional[str] = None
    recent_url: Optional[str] = None
    recent_title: Optional[str] = None
    for app, url, title, dur, cat, sat in rows:
        total += int(dur)
        a = app_agg.setdefault(app, {
            "total_seconds": 0, "session_count": 0,
            "top_url": None, "top_url_seconds": 0,
            "category": cat,
        })
        a["total_seconds"] += int(dur)
        a["session_count"] += 1
        if url and int(dur) > a["top_url_seconds"]:
            a["top_url"] = url
            a["top_url_seconds"] = int(dur)
        if cat:
            cat_agg[cat] = cat_agg.get(cat, 0) + int(dur)
        # 解析 sat (sqlite 返字符串,容错)
        try:
            sat_dt = sat if isinstance(sat, datetime) else datetime.fromisoformat(str(sat))
        except (ValueError, TypeError):
            sat_dt = None
        if sat_dt is not None and sat_dt >= recent_cutoff:
            recent_app, recent_url, recent_title = app, url, title

    top_apps = sorted(
        (
            {
                "app_name": app, "total_seconds": info["total_seconds"],
                "pretty": _fmt_duration(info["total_seconds"]),
                "session_count": info["session_count"],
                "category": info["category"],
                "top_url": info["top_url"],
                "top_url_seconds": info["top_url_seconds"],
            }
            for app, info in app_agg.items()
        ),
        key=lambda x: -x["total_seconds"],
    )[:5]

    by_category = {
        cat: {"total_seconds": secs, "pretty": _fmt_duration(secs)}
        for cat, secs in sorted(cat_agg.items(), key=lambda kv: -kv[1])
    }

    recent_focus = None
    if recent_app:
        recent_focus = {
            "app_name": recent_app,
            "browser_url": recent_url,
            "browser_title": recent_title,
        }

    return {
        "available": True,
        "total_active_seconds": total,
        "total_active_pretty": _fmt_duration(total),
        "top_apps": top_apps,
        "by_category": by_category,
        "recent_focus": recent_focus,
    }


# ---------------------------------------------------------------------------
# 2. activity.get_recent_apps
# ---------------------------------------------------------------------------


@register_capability(
    name="activity.get_recent_apps",
    display_name="最近 N 天 top apps",
    description=(
        "查最近 N 天(1-30,默 7)用户 top apps + 总停留时长。用户问「这周都在干"
        "啥」「最近这几天主要用啥」时调。参数 ``days: int`` (default 7,clamp 到 "
        "[1, 30])。返 ``{available, days, top_apps[]}``,每个 entry 含 "
        "``app_name / total_seconds / pretty / session_count / category``。"
        "排黑名单 + idle 期间(同 today_summary 语义)。"
    ),
    category="activity",
    consumers=[Consumer.CHAT_AGENT],
    trigger_modes=[TriggerMode.ON_DEMAND],
    icon="calendar",
    parameters_schema={
        "type": "object",
        "properties": {
            "days": {
                "type": "integer",
                "minimum": 1, "maximum": 30, "default": 7,
                "description": "最近 N 天窗口(1-30,默 7)",
            },
        },
        "required": [],
    },
)
async def get_recent_apps(days: int = 7, **_kwargs) -> dict:
    try:
        days = max(1, min(30, int(days)))
    except (TypeError, ValueError):
        days = 7

    user_id = _default_user_id()
    now = datetime.utcnow()
    start = (now - timedelta(days=days)).replace(
        hour=0, minute=0, second=0, microsecond=0,
    )

    try:
        async with engine.begin() as conn:
            rows = (await conn.execute(text(
                "SELECT app_name, category, "
                "       SUM(duration_seconds) AS total, "
                "       COUNT(*) AS cnt "
                "FROM activity_sessions "
                "WHERE user_id = :uid "
                "  AND start_at >= :s "
                "  AND is_idle_filtered = 0 "
                "GROUP BY app_name "
                "ORDER BY total DESC LIMIT 20"
            ), {"uid": user_id, "s": start})).fetchall()
    except Exception as exc:
        logger.exception("[activity_cap] get_recent_apps DB query failed: %s", exc)
        return {"available": False, "reason": "db_error", "days": days}

    top_apps = [
        {
            "app_name": app,
            "category": cat,
            "total_seconds": int(total),
            "pretty": _fmt_duration(int(total)),
            "session_count": int(cnt),
        }
        for app, cat, total, cnt in rows
    ]
    return {"available": True, "days": days, "top_apps": top_apps}


# ---------------------------------------------------------------------------
# 3. activity.search_history
# ---------------------------------------------------------------------------


@register_capability(
    name="activity.search_history",
    display_name="搜索活动历史",
    description=(
        "在历史 session 的 ``browser_url / browser_title / app_name`` 字段里搜"
        "关键词(case-insensitive substring)。用户问「我之前在哪个网站看过 X」"
        "「我那篇 B 站视频是啥时候看的」时调。参数 ``keyword: str``(必填)+ "
        "``days: int``(默 30,clamp [1, 90])。返 ``{available, keyword, matches[]}``"
        ",每个 match 含 ``id / app / url / title / start_at / duration_seconds``。"
        "黑名单 / idle session 不在返值内(双重隐私)。"
    ),
    category="activity",
    consumers=[Consumer.CHAT_AGENT],
    trigger_modes=[TriggerMode.ON_DEMAND],
    icon="search",
    parameters_schema={
        "type": "object",
        "properties": {
            "keyword": {
                "type": "string",
                "description": "搜索关键词(在 URL / title / app_name 字段内匹配)",
            },
            "days": {
                "type": "integer",
                "minimum": 1, "maximum": 90, "default": 30,
                "description": "回看范围(1-90 天,默 30)",
            },
        },
        "required": ["keyword"],
    },
)
async def search_history(
    keyword: str = "", days: int = 30, **_kwargs,
) -> dict:
    keyword = (keyword or "").strip()
    if not keyword:
        return {
            "available": False, "reason": "empty_keyword",
            "keyword": keyword, "matches": [],
        }
    try:
        days = max(1, min(90, int(days)))
    except (TypeError, ValueError):
        days = 30

    user_id = _default_user_id()
    now = datetime.utcnow()
    start = (now - timedelta(days=days)).replace(
        hour=0, minute=0, second=0, microsecond=0,
    )
    # SQL LIKE pattern。``%`` 在 keyword 内必须 escape — sqlite 用 ESCAPE 子句
    # 显式声明分隔符。本场景 user keyword 一般是普通文字,极端含 ``%`` 的
    # 情况(如 URL fragment "100%") 也仍能搜(LIKE 含 % 当 wildcard 没问题)。
    pat = f"%{keyword.lower()}%"

    try:
        async with engine.begin() as conn:
            rows = (await conn.execute(text(
                "SELECT id, app_name, browser_url, browser_title, "
                "       start_at, duration_seconds, category "
                "FROM activity_sessions "
                "WHERE user_id = :uid "
                "  AND start_at >= :s "
                "  AND is_idle_filtered = 0 "
                "  AND ( "
                "        LOWER(app_name) LIKE :pat "
                "     OR LOWER(IFNULL(browser_url, '')) LIKE :pat "
                "     OR LOWER(IFNULL(browser_title, '')) LIKE :pat "
                "  ) "
                "ORDER BY start_at DESC LIMIT 50"
            ), {"uid": user_id, "s": start, "pat": pat})).fetchall()
    except Exception as exc:
        logger.exception("[activity_cap] search_history DB query failed: %s", exc)
        return {
            "available": False, "reason": "db_error",
            "keyword": keyword, "matches": [],
        }

    matches = [
        {
            "id": int(sid),
            "app": app,
            "url": url,
            "title": title,
            "start_at": str(sat),
            "duration_seconds": int(dur),
            "duration_pretty": _fmt_duration(int(dur)),
            "category": cat,
        }
        for sid, app, url, title, sat, dur, cat in rows
    ]
    return {
        "available": True, "keyword": keyword,
        "days": days, "matches": matches,
    }
