"""hotfix-8 — _IDE_APPS 终端类 + macOS 中文 localized name 覆盖回归。

锁：
1. macOS Apple Terminal.app 中文 localized name ``'终端'`` 在集合里
2. 英文 ``'Terminal'`` 也在(覆盖 macOS 英文 locale + 第三方包装情形)
3. 第三方终端(iTerm2 / Alacritty / WezTerm / Warp / Kitty / Hyper)全在
4. ``_classify(app="终端")`` 命中 IDE 规则 → ``activity_ide_open``
5. ``_classify(app="Terminal")`` 同
"""
from __future__ import annotations

import os
import sys
from datetime import datetime

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.integrations.activity_watcher import ActivityChange, ActivityState
from backend.proactive import activity_smart as smart


def _app_changed(new_app: str, *, hour: int = 14) -> ActivityChange:
    ts = datetime.now().replace(
        hour=hour, minute=0, second=0, microsecond=0,
    ).timestamp()
    return ActivityChange(
        kind="app_changed",
        old=None,
        new=ActivityState(active_app=new_app, timestamp=ts),
        detail={"old_app": "Chrome", "new_app": new_app},
    )


# ---------------------------------------------------------------------------
# Set membership
# ---------------------------------------------------------------------------


def test_ide_apps_contains_chinese_terminal() -> None:
    """⭐ 中文 macOS Apple Terminal.app localizedName 必须在 _IDE_APPS。"""
    assert "终端" in smart._IDE_APPS, (
        "macOS 中文系统 NSWorkspace.frontmostApplication.localizedName 返 "
        "'终端' (Terminal.app CFBundleDisplayName 中文 localization),漏掉 "
        "会让中文 macOS 用户切到终端时永远不触发 activity_ide_open"
    )


def test_ide_apps_contains_english_terminal() -> None:
    """英文 macOS 用户 NSWorkspace 返 'Terminal' (lowercase 比较)。"""
    assert "terminal" in smart._IDE_APPS


def test_ide_apps_contains_all_third_party_terminals() -> None:
    """第三方终端类完整覆盖(iTerm2 / Alacritty / WezTerm / Warp / Kitty / Hyper)。"""
    for app in ("iterm", "iterm2", "alacritty", "wezterm", "warp", "kitty", "hyper"):
        assert app in smart._IDE_APPS, f"_IDE_APPS 缺 {app!r}"


# ---------------------------------------------------------------------------
# _classify behavior
# ---------------------------------------------------------------------------


def test_classify_chinese_terminal_triggers_ide_open() -> None:
    """⭐ 用户切到 macOS Terminal(中文系统)→ activity_ide_open 触发。"""
    label = smart._classify(_app_changed("终端"))
    assert label == "activity_ide_open"


def test_classify_english_terminal_triggers_ide_open() -> None:
    label = smart._classify(_app_changed("Terminal"))
    assert label == "activity_ide_open"


def test_classify_iterm2_triggers_ide_open() -> None:
    assert smart._classify(_app_changed("iTerm2")) == "activity_ide_open"


def test_classify_alacritty_triggers_ide_open() -> None:
    assert smart._classify(_app_changed("Alacritty")) == "activity_ide_open"


def test_classify_warp_triggers_ide_open() -> None:
    assert smart._classify(_app_changed("Warp")) == "activity_ide_open"


def test_classify_wezterm_triggers_ide_open() -> None:
    assert smart._classify(_app_changed("WezTerm")) == "activity_ide_open"


def test_classify_late_night_chinese_terminal() -> None:
    """凌晨 3 点切 ``'终端'`` → late_night_ide(更温柔 prompt)。"""
    label = smart._classify(_app_changed("终端", hour=3))
    assert label == "activity_late_night_ide"


# ---------------------------------------------------------------------------
# Negative: 非 IDE 的 app 不误命中
# ---------------------------------------------------------------------------


def test_classify_chrome_still_not_ide() -> None:
    """Chrome / Finder 等不应被新 i18n alias 误命中。"""
    assert smart._classify(_app_changed("Google Chrome")) is None
    assert smart._classify(_app_changed("Finder")) is None
    assert smart._classify(_app_changed("Safari")) is None
