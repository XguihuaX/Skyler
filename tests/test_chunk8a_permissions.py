"""v3.5 chunk 8a commit 7 — 权限自检 + Info.plist + 前端 modal grep。"""
from __future__ import annotations

import json
import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.integrations import activity_watcher as aw


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------------------
# Backend check_macos_permissions
# ---------------------------------------------------------------------------


async def test_check_permissions_all_ok() -> None:
    with patch.object(aw._am, "get_active_app", return_value="Chrome"), \
         patch.object(aw._am, "_run_osascript", return_value="ok"):
        r = await aw.check_macos_permissions()
    assert r["ns_workspace_ok"] is True
    assert r["applescript_ok"] is True
    assert r["hint"] is None


async def test_check_permissions_applescript_missing() -> None:
    with patch.object(aw._am, "get_active_app", return_value="Chrome"), \
         patch.object(aw._am, "_run_osascript", return_value=None):
        r = await aw.check_macos_permissions()
    assert r["ns_workspace_ok"] is True
    assert r["applescript_ok"] is False
    assert r["hint"]
    assert "自动化" in r["hint"]


async def test_check_permissions_non_macos() -> None:
    with patch.object(aw._am, "get_active_app", return_value=None), \
         patch.object(aw._am, "_run_osascript", return_value=None):
        r = await aw.check_macos_permissions()
    assert r["ns_workspace_ok"] is False
    assert r["applescript_ok"] is False
    assert "NSWorkspace" in (r["hint"] or "")


# ---------------------------------------------------------------------------
# GET /api/activity/permissions
# ---------------------------------------------------------------------------


def test_permissions_endpoint_shape() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.routes.activity_api import router
    app = FastAPI()
    app.include_router(router, prefix="/api")
    with patch.object(aw._am, "get_active_app", return_value="Chrome"), \
         patch.object(aw._am, "_run_osascript", return_value="ok"):
        client = TestClient(app)
        r = client.get("/api/activity/permissions")
    assert r.status_code == 200
    body = r.json()
    assert "ns_workspace_ok" in body
    assert "applescript_ok" in body
    assert "hint" in body


# ---------------------------------------------------------------------------
# Tauri Info.plist NSAppleEventsUsageDescription
# ---------------------------------------------------------------------------


def test_tauri_conf_has_apple_events_usage_description() -> None:
    """两种合法形态都接受：

    1. ``infoPlist`` 是 dict（chunk 8a commit 7 原始形态）—— 字段在 dict 里
    2. ``infoPlist`` 是 string 路径（hotfix-6 之后用户提取到外部 Info.plist）
       —— 读外部 plist 文件验证字段
    """
    path = os.path.join(ROOT, "frontend/src-tauri/tauri.conf.json")
    with open(path, encoding="utf-8") as f:
        conf = json.load(f)
    info = conf.get("bundle", {}).get("macOS", {}).get("infoPlist")
    desc: str | None = None
    if isinstance(info, dict):
        desc = info.get("NSAppleEventsUsageDescription")
    elif isinstance(info, str):
        # 路径相对 src-tauri/ 解析
        plist_path = os.path.join(ROOT, "frontend/src-tauri", info)
        assert os.path.exists(plist_path), f"infoPlist path {info} 不存在"
        with open(plist_path, encoding="utf-8") as f:
            plist_src = f.read()
        # 简单 XML 文本扫描足够（不引 plistlib，避免 Python 版本差异）
        assert "<key>NSAppleEventsUsageDescription</key>" in plist_src, \
            f"{info} 缺 NSAppleEventsUsageDescription 字段"
        # 抓 string 内容
        import re
        m = re.search(
            r"<key>NSAppleEventsUsageDescription</key>\s*<string>(.*?)</string>",
            plist_src, flags=re.DOTALL,
        )
        if m:
            desc = m.group(1)
    assert desc is not None and len(desc) > 0, "NSAppleEventsUsageDescription 字段为空"
    # 必须含"Skyler"等关键词，对用户友好
    assert "Skyler" in desc


# ---------------------------------------------------------------------------
# Frontend grep
# ---------------------------------------------------------------------------


def test_useWebSocket_handles_activity_permission_missing() -> None:
    path = os.path.join(ROOT, "frontend/src/hooks/useWebSocket.ts")
    with open(path, encoding="utf-8") as f:
        src = f.read()
    assert "activity_permission_missing" in src
    assert "setActivityPermissionHint" in src


def test_store_exposes_activity_permission_state() -> None:
    path = os.path.join(ROOT, "frontend/src/store/index.ts")
    with open(path, encoding="utf-8") as f:
        src = f.read()
    assert "activityPermissionHint" in src
    assert "setActivityPermissionHint" in src


def test_modal_component_renders_systemprefs_link() -> None:
    path = os.path.join(ROOT, "frontend/src/components/ActivityPermissionModal.tsx")
    with open(path, encoding="utf-8") as f:
        src = f.read()
    # 跳转 macOS 隐私设置自动化页的 URI scheme
    assert "x-apple.systempreferences" in src
    assert "Privacy_Automation" in src
    assert "打开系统设置" in src
    # 关闭路径 setActivityPermissionHint(null)
    assert "setActivityPermissionHint(null)" in src or "setHint(null)" in src


def test_app_tsx_mounts_modal() -> None:
    path = os.path.join(ROOT, "frontend/src/App.tsx")
    with open(path, encoding="utf-8") as f:
        src = f.read()
    assert "ActivityPermissionModal" in src
    assert "<ActivityPermissionModal" in src


def test_main_py_does_permission_check() -> None:
    path = os.path.join(ROOT, "backend/main.py")
    with open(path, encoding="utf-8") as f:
        src = f.read()
    assert "check_macos_permissions" in src
    assert "activity_permission_missing" in src
