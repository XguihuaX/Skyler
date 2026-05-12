"""v3.5 chunk 8a commit 8 — Activity API + lifespan registration 单测。

走真 FastAPI TestClient 路径，不真启 lifespan。Mock activity_monitor 让
snapshot 返预设值，验：

* GET /api/activity/status         字段齐 + 含 last_state
* GET /api/activity/config          反映 config + smart 节流默认
* PATCH /api/activity/config        部分字段 patch + enabled toggle
"""
from __future__ import annotations

import os
import sys
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.config import config_yaml
from backend.integrations import activity_watcher as aw
from backend.proactive import activity_smart as smart
from backend.routes.activity_api import router


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return app


def test_get_status_basic_shape():
    aw.reset_for_test()
    smart.reset_state_for_test()
    # ensure default config block present
    config_yaml.setdefault("activity_watcher", {}).update({"enabled": False})
    client = TestClient(_build_app())
    r = client.get("/api/activity/status")
    assert r.status_code == 200
    body = r.json()
    for key in (
        "enabled", "running", "poll_interval_seconds", "fetch_url_content",
        "last_state", "daily_triggers_today", "daily_cap", "throttle_minutes",
    ):
        assert key in body, f"missing {key} in status response"
    assert body["enabled"] is False
    assert body["running"] is False
    assert body["last_state"] is None
    assert body["daily_triggers_today"] == 0


def test_get_config_returns_defaults():
    config_yaml.setdefault("activity_watcher", {}).update({
        "enabled": True,
        "poll_interval_seconds": 45,
        "fetch_url_content": False,
        "blocked_apps": ["1Password"],
        "blocked_url_patterns": ["*chase.com*"],
        "trigger_throttle_minutes": 60,
        "max_daily_triggers": 3,
    })
    client = TestClient(_build_app())
    r = client.get("/api/activity/config")
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is True
    assert body["poll_interval_seconds"] == 45
    assert body["fetch_url_content"] is False
    assert body["blocked_apps"] == ["1Password"]
    assert body["blocked_url_patterns"] == ["*chase.com*"]
    assert body["trigger_throttle_minutes"] == 60
    assert body["max_daily_triggers"] == 3


def test_patch_blocked_apps_appends():
    config_yaml.setdefault("activity_watcher", {}).update({
        "enabled": False,
        "blocked_apps": ["1Password"],
        "blocked_url_patterns": ["*chase.com*"],
    })
    client = TestClient(_build_app())
    r = client.patch(
        "/api/activity/config",
        json={"blocked_apps": ["1Password", "Bitwarden"]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["blocked_apps"] == ["1Password", "Bitwarden"]


def test_patch_enabled_toggles_watcher():
    """PATCH enabled=True should also call activity_watcher.set_enabled + start."""
    aw.reset_for_test()
    config_yaml.setdefault("activity_watcher", {}).update({"enabled": False})

    started = {"v": False}
    real_set_enabled = aw.activity_watcher.set_enabled
    real_start = aw.activity_watcher.start_polling

    def mock_set_enabled(v):
        real_set_enabled(v)

    def mock_start():
        started["v"] = True
        # 不真起 task

    aw.activity_watcher.set_enabled = mock_set_enabled  # type: ignore
    aw.activity_watcher.start_polling = mock_start       # type: ignore
    try:
        client = TestClient(_build_app())
        r = client.patch("/api/activity/config", json={"enabled": True})
    finally:
        aw.activity_watcher.set_enabled = real_set_enabled
        aw.activity_watcher.start_polling = real_start
    assert r.status_code == 200
    assert started["v"] is True
    assert r.json()["enabled"] is True


def test_patch_fetch_url_content_only():
    config_yaml.setdefault("activity_watcher", {}).update({
        "enabled": False,
        "fetch_url_content": True,
    })
    client = TestClient(_build_app())
    r = client.patch(
        "/api/activity/config", json={"fetch_url_content": False},
    )
    assert r.status_code == 200
    assert r.json()["fetch_url_content"] is False


def test_status_includes_last_state_when_set():
    """模拟 watcher 跑过一拍后 last_state 不为 None。"""
    from backend.integrations.activity_watcher import ActivityState
    aw.activity_watcher._last_state = ActivityState(
        active_app="VSCode",
        browser={"browser": "chrome", "url": "https://github.com/a", "title": "A"},
        document=None, url_content=None, timestamp=1234567890.0,
    )
    try:
        client = TestClient(_build_app())
        r = client.get("/api/activity/status")
    finally:
        aw.activity_watcher._last_state = None
    assert r.status_code == 200
    ls = r.json()["last_state"]
    assert ls is not None
    assert ls["active_app"] == "VSCode"
    assert ls["browser"]["url"] == "https://github.com/a"


def test_main_py_registers_activity_router():
    """grep main.py 源码确认 activity_router 在 include_router 列表里。"""
    main_py = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "backend/main.py",
    )
    with open(main_py, encoding="utf-8") as f:
        src = f.read()
    assert "activity_api import router as activity_router" in src
    assert "include_router(activity_router" in src
    # 启停 hook 也在
    assert "activity_watcher.register_change_listener(activity_smart_handler)" in src
    assert "activity_watcher.start_polling()" in src
    assert "await activity_watcher.stop_polling()" in src
