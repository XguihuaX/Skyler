"""v3.5 chunk 8a — Activity API endpoints。

* ``GET   /api/activity/status``    当前 snapshot + watcher 运行状态
* ``GET   /api/activity/config``    黑名单 / 开关 / 节流 / cap 等配置
* ``PATCH /api/activity/config``    部分字段 patch（黑名单增删 / enabled
                                     toggle）。**仅 runtime 内存改动**，
                                     不写 config.yaml（与 chunk 7 mcp_client_state
                                     一致：DB / 内存做差异，文件作 default）

注：本 chunk 不引入新表（chunk 7 ``mcp_client_state`` 走 DB 是因为 server
toggle 要跨重启沿用；activity_watcher 的临时开关 + 黑名单调整定位是"当前
session 试着关 / 加一条 pattern 看效果"——重启后回 config.yaml 默认就好）。
长期想跨重启沿用的话，未来 backlog 再加 ``activity_watcher_state`` 表。
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.integrations import activity_watcher as aw
from backend.proactive import activity_judge as judge
from backend.proactive import activity_smart as smart

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# GET /api/activity/status
# ---------------------------------------------------------------------------


class ActivityStatusResponse(BaseModel):
    enabled: bool
    running: bool
    poll_interval_seconds: int
    fetch_url_content: bool
    last_state: Optional[dict] = None
    # 当前节流 / cap 摘要（让 UI 看到"接下来还能触发几次"）
    daily_triggers_today: int
    daily_cap: int
    throttle_minutes: int


@router.get("/activity/status", response_model=ActivityStatusResponse)
async def activity_status() -> ActivityStatusResponse:
    state = aw.activity_watcher.get_last_state()
    return ActivityStatusResponse(
        enabled=aw.activity_watcher.is_enabled(),
        running=aw.activity_watcher.is_running(),
        poll_interval_seconds=aw.get_poll_interval_seconds(),
        fetch_url_content=aw.get_fetch_url_content(),
        last_state=(state.to_dict() if state is not None else None),
        daily_triggers_today=smart._today_count,
        daily_cap=smart.get_max_daily_triggers(),
        throttle_minutes=smart.get_throttle_minutes(),
    )


# ---------------------------------------------------------------------------
# GET /api/activity/config
# ---------------------------------------------------------------------------


class ActivityConfigResponse(BaseModel):
    enabled: bool
    poll_interval_seconds: int
    fetch_url_content: bool
    blocked_apps: list[str]
    blocked_url_patterns: list[str]
    trigger_throttle_minutes: int
    max_daily_triggers: int
    # chunk 8a-ext 慢路径 judge 字段
    judge_enabled: bool
    judge_model: str
    judge_min_stay_minutes: int
    judge_throttle_minutes: int
    # chunk 8a-ext V2: 键鼠 idle 闸阈值(秒);0 = 关闭闸,非 macOS 自动绕过
    judge_idle_threshold_seconds: int


@router.get("/activity/config", response_model=ActivityConfigResponse)
async def activity_config() -> ActivityConfigResponse:
    return ActivityConfigResponse(
        enabled=aw.activity_watcher.is_enabled(),
        poll_interval_seconds=aw.get_poll_interval_seconds(),
        fetch_url_content=aw.get_fetch_url_content(),
        blocked_apps=aw.get_blocked_apps(),
        blocked_url_patterns=aw.get_blocked_url_patterns(),
        trigger_throttle_minutes=smart.get_throttle_minutes(),
        max_daily_triggers=smart.get_max_daily_triggers(),
        judge_enabled=judge.get_judge_enabled(),
        judge_model=judge.get_judge_model(),
        judge_min_stay_minutes=judge.get_min_stay_minutes(),
        judge_throttle_minutes=judge.get_judge_throttle_minutes(),
        judge_idle_threshold_seconds=judge.get_idle_threshold_seconds(),
    )


# ---------------------------------------------------------------------------
# PATCH /api/activity/config
# ---------------------------------------------------------------------------


class ActivityConfigPatch(BaseModel):
    enabled: Optional[bool] = None
    blocked_apps: Optional[list[str]] = None
    blocked_url_patterns: Optional[list[str]] = None
    fetch_url_content: Optional[bool] = None
    # chunk 8a-ext: 智能陪伴 judge 总开关(默认 ON,关掉后慢路径完全静默)
    judge_enabled: Optional[bool] = None
    # chunk 8a-ext V2: idle 闸阈值(秒)。值为 0 即关闸,负数被 clamp 到 0,非 macOS
    # ioreg 失败自动绕过保持 V1 行为。前端 UI 允许 [0, 1800] 区间(0..30 min)。
    judge_idle_threshold_seconds: Optional[int] = None


# ---------------------------------------------------------------------------
# GET /api/activity/permissions
# ---------------------------------------------------------------------------


class PermissionsResponse(BaseModel):
    ns_workspace_ok: bool
    applescript_ok: bool
    hint: Optional[str] = None


@router.get("/activity/permissions", response_model=PermissionsResponse)
async def activity_permissions() -> PermissionsResponse:
    result = await aw.check_macos_permissions()
    return PermissionsResponse(**result)


@router.patch("/activity/config", response_model=ActivityConfigResponse)
async def patch_activity_config(body: ActivityConfigPatch) -> ActivityConfigResponse:
    """部分字段 patch。在 ``config_yaml`` 的 ``activity_watcher`` block 上做
    in-memory 修改，让 watcher 下一拍读到（与 chunk 11 ``profile_data`` cron
    config hot reload 同语义）。

    *enabled* 翻 True 时 watcher 若未运行则 start_polling；翻 False 时
    set_enabled(False) → run_loop 内 stop_event 触发，下次启动需要再调
    start_polling。
    """
    from backend.config import config_yaml

    cfg = config_yaml.setdefault("activity_watcher", {})

    if body.enabled is not None:
        cfg["enabled"] = bool(body.enabled)
        aw.activity_watcher.set_enabled(bool(body.enabled))
        if body.enabled and not aw.activity_watcher.is_running():
            aw.activity_watcher.start_polling()

    if body.blocked_apps is not None:
        cfg["blocked_apps"] = [str(x) for x in body.blocked_apps]

    if body.blocked_url_patterns is not None:
        cfg["blocked_url_patterns"] = [str(x) for x in body.blocked_url_patterns]

    if body.fetch_url_content is not None:
        cfg["fetch_url_content"] = bool(body.fetch_url_content)

    if body.judge_enabled is not None:
        # chunk 8a-ext: 慢路径 judge 总开关。配置走独立 ``activity_judge`` 块,
        # 不在 ``activity_watcher`` block 内,与 ActivityJudge config 读取一致。
        from backend.config import config_yaml as _cfg
        _cfg.setdefault("activity_judge", {})["enabled"] = bool(body.judge_enabled)

    if body.judge_idle_threshold_seconds is not None:
        # chunk 8a-ext V2: idle 闸阈值。clamp 到 [0, 3600] 防 UI 误输入。
        # 0 = 关闸; > 0 = 静止超 N 秒 → skip judge。
        from backend.config import config_yaml as _cfg
        try:
            v = max(0, min(3600, int(body.judge_idle_threshold_seconds)))
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=400,
                detail="judge_idle_threshold_seconds 必须为整数",
            )
        _cfg.setdefault("activity_judge", {})["idle_threshold_seconds"] = v

    return await activity_config()


# ---------------------------------------------------------------------------
# v3.5 chunk 14 — Timeline endpoints
#
# /api/activity/timeline           GET   按日(默 today)/ 日数返完整 timeline +
#                                        summary_by_app + summary_by_category
# /api/activity/timeline/{id}      DELETE 删单条 session
# /api/activity/timeline?date=...  DELETE 清某日
# ---------------------------------------------------------------------------


from datetime import datetime, timedelta, timezone   # noqa: E402

from sqlalchemy import text                          # noqa: E402

from backend.database import engine                  # noqa: E402


class ActivitySessionRow(BaseModel):
    id: int
    start_at: str
    end_at: str
    duration_seconds: int
    app_name: str
    browser_url: Optional[str] = None
    browser_title: Optional[str] = None
    category: Optional[str] = None
    is_idle_filtered: bool = False


class ActivityAppSummary(BaseModel):
    app_name: str
    total_seconds: int
    session_count: int
    category: Optional[str] = None
    top_urls: list[dict]  # [{url, title, seconds}], 截 top 5


class TimelineResponse(BaseModel):
    date: str                          # YYYY-MM-DD,start of window
    days: int                          # 窗口天数(1 = 单日)
    total_active_seconds: int
    sessions: list[ActivitySessionRow]
    summary_by_app: list[ActivityAppSummary]
    summary_by_category: dict[str, int]  # category → total seconds


def _parse_date_arg(date_str: Optional[str]) -> datetime:
    """``YYYY-MM-DD`` → naive UTC midnight。``None`` → today UTC midnight。

    SQLite 里 ``start_at`` 用 ``datetime.utcnow()`` 写,因此查询窗口也用 UTC。
    """
    if not date_str:
        now = datetime.utcnow()
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(
            status_code=400, detail="date 必须是 YYYY-MM-DD 格式",
        )
    return d


def _default_user_id() -> str:
    from backend.config import config_yaml as _cfg
    return str(_cfg.get("default_user_id") or "default")


@router.get("/activity/timeline", response_model=TimelineResponse)
async def get_timeline(
    date: Optional[str] = None,
    days: int = 1,
    include_idle: bool = True,
) -> TimelineResponse:
    """返指定日期(或 N 天滚动窗口)的 timeline。

    Args:
      date:         ``YYYY-MM-DD``,默 today
      days:         窗口天数(default 1 = 单日,7 = 最近一周)。clamp [1, 90]
      include_idle: 默 True;false 时 ``is_idle_filtered=1`` 的 session 不入
                    sessions list,且 summary 计算时 exclude
    """
    if days < 1:
        days = 1
    if days > 90:
        days = 90

    start = _parse_date_arg(date)
    end = start + timedelta(days=days)
    user_id = _default_user_id()

    sql = """
        SELECT id, start_at, end_at, duration_seconds, app_name,
               browser_url, browser_title, category, is_idle_filtered
        FROM activity_sessions
        WHERE user_id = :uid
          AND start_at >= :start
          AND start_at < :end
    """
    params = {"uid": user_id, "start": start, "end": end}
    if not include_idle:
        sql += " AND is_idle_filtered = 0"
    sql += " ORDER BY start_at ASC"

    async with engine.begin() as conn:
        rows = (await conn.execute(text(sql), params)).fetchall()

    sessions: list[ActivitySessionRow] = []
    app_agg: dict[str, dict] = {}
    cat_agg: dict[str, int] = {}
    total_secs = 0

    for r in rows:
        (
            sid, sat, eat, dur, app, url, title, cat, idle_flag,
        ) = r
        sessions.append(ActivitySessionRow(
            id=int(sid),
            start_at=str(sat),
            end_at=str(eat),
            duration_seconds=int(dur),
            app_name=app,
            browser_url=url,
            browser_title=title,
            category=cat,
            is_idle_filtered=bool(idle_flag),
        ))
        total_secs += int(dur)
        a = app_agg.setdefault(app, {
            "total_seconds": 0, "session_count": 0,
            "category": cat, "urls": {},
        })
        a["total_seconds"] += int(dur)
        a["session_count"] += 1
        # category 取该 app 第一次出现的;如果不同 session 标了不同 category,
        # 后到的覆盖最近一次(实际同 app session 应同 category,这里保守)
        if cat:
            a["category"] = cat
        if url:
            u = a["urls"].setdefault(url, {"title": title or "", "seconds": 0})
            u["seconds"] += int(dur)
        if cat:
            cat_agg[cat] = cat_agg.get(cat, 0) + int(dur)

    summary_by_app: list[ActivityAppSummary] = []
    for app_name, info in sorted(
        app_agg.items(), key=lambda kv: -kv[1]["total_seconds"],
    ):
        top_urls = sorted(
            (
                {"url": u, "title": meta["title"], "seconds": meta["seconds"]}
                for u, meta in info["urls"].items()
            ),
            key=lambda x: -x["seconds"],
        )[:5]
        summary_by_app.append(ActivityAppSummary(
            app_name=app_name,
            total_seconds=info["total_seconds"],
            session_count=info["session_count"],
            category=info.get("category"),
            top_urls=top_urls,
        ))

    return TimelineResponse(
        date=start.strftime("%Y-%m-%d"),
        days=days,
        total_active_seconds=total_secs,
        sessions=sessions,
        summary_by_app=summary_by_app,
        summary_by_category=cat_agg,
    )


@router.delete("/activity/timeline/{session_id}")
async def delete_timeline_session(session_id: int) -> dict:
    """删单条 session。返 ``{deleted: bool}``。"""
    user_id = _default_user_id()
    async with engine.begin() as conn:
        res = await conn.execute(text(
            "DELETE FROM activity_sessions "
            "WHERE id = :id AND user_id = :uid"
        ), {"id": session_id, "uid": user_id})
    deleted = bool(getattr(res, "rowcount", 0))
    logger.info(
        "[activity_timeline] delete session id=%d user=%s -> %s",
        session_id, user_id, deleted,
    )
    return {"deleted": deleted}


@router.delete("/activity/timeline")
async def delete_timeline_by_date(date: Optional[str] = None) -> dict:
    """清某日所有 session(date=YYYY-MM-DD)或所有 timeline(date=None 谨慎)。"""
    user_id = _default_user_id()
    if date is None:
        # 清整张表(仅当前 user) — 高风险,要求显式 ``date=all``
        raise HTTPException(
            status_code=400,
            detail="必须传 date=YYYY-MM-DD 或 date=all 才能清空",
        )
    if date == "all":
        async with engine.begin() as conn:
            res = await conn.execute(text(
                "DELETE FROM activity_sessions WHERE user_id = :uid"
            ), {"uid": user_id})
    else:
        start = _parse_date_arg(date)
        end = start + timedelta(days=1)
        async with engine.begin() as conn:
            res = await conn.execute(text(
                "DELETE FROM activity_sessions "
                "WHERE user_id = :uid AND start_at >= :s AND start_at < :e"
            ), {"uid": user_id, "s": start, "e": end})
    n = int(getattr(res, "rowcount", 0))
    logger.info(
        "[activity_timeline] delete by date=%s user=%s -> %d row(s)",
        date, user_id, n,
    )
    return {"deleted_count": n, "date": date}
