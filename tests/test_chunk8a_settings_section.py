"""v3.5 chunk 8a commit 6 — SettingsPanel [活动感知] section 静态结构断言。

走 chunk 7 / UX-001 同 grep pattern（环境无 vitest）。
"""
from __future__ import annotations

import os
import re

import pytest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SECTION_SRC = os.path.join(ROOT, "frontend/src/components/ActivityAwarenessSection.tsx")
PANEL_SRC = os.path.join(ROOT, "frontend/src/components/SettingsPanel.tsx")
LIB_SRC = os.path.join(ROOT, "frontend/src/lib/activity.ts")


@pytest.fixture(scope="module")
def section() -> str:
    with open(SECTION_SRC, encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="module")
def panel() -> str:
    with open(PANEL_SRC, encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="module")
def lib() -> str:
    with open(LIB_SRC, encoding="utf-8") as f:
        return f.read()


def test_lib_exports_three_interfaces(lib: str) -> None:
    for name in (
        "ActivityStateLite",
        "ActivityStatusResponse",
        "ActivityConfigResponse",
        "ActivityConfigPatch",
    ):
        assert f"export interface {name}" in lib


def test_lib_endpoints_correct(lib: str) -> None:
    assert "/api/activity/status" in lib
    assert "/api/activity/config" in lib
    assert re.search(r"method:\s*'PATCH'", lib)


def test_section_imports_activity_lib(section: str) -> None:
    assert "from '../lib/activity'" in section
    assert "fetchActivityStatus" in section
    assert "fetchActivityConfig" in section
    assert "patchActivityConfig" in section


def test_section_has_main_toggle(section: str) -> None:
    """主开关行 + 调 patchActivityConfig({enabled: ...})."""
    assert "onPatch({ enabled: v })" in section


def test_section_has_fetch_url_toggle(section: str) -> None:
    assert "onPatch({ fetch_url_content: v })" in section


def test_section_blocklist_management(section: str) -> None:
    """黑名单 add/remove 都通过 patch 全量替换 list。"""
    # 增 / 删 apps
    assert "blocked_apps:" in section
    assert "blocked_url_patterns:" in section
    # accordion 展开折叠
    assert "ChevronDown" in section
    assert "ChevronRight" in section


def test_section_state_display(section: str) -> None:
    """当前状态：active_app / browser url / 今日 trigger / 节流分钟。"""
    assert "last_state?.active_app" in section
    assert "last_state?.browser?.url" in section
    assert "daily_triggers_today" in section
    assert "throttle_minutes" in section


def test_settings_panel_mounts_section(panel: str) -> None:
    assert "import ActivityAwarenessSection from './ActivityAwarenessSection'" in panel
    assert "<ActivityAwarenessSection" in panel


def test_section_periodic_refresh_30s(section: str) -> None:
    """useEffect setInterval 30s 拉 last_state。"""
    assert "setInterval" in section
    # 看大概 30000 毫秒
    assert re.search(r"setInterval\(.+?,\s*30000\s*\)", section, flags=re.DOTALL)
