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

    return await activity_config()
