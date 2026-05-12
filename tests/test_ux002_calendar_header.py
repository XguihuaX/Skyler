"""UX-002 commit 3 — calendar Google OAuth footer + 测试简报按钮 已归位到
category header（脱离单 CapabilityDetail 卡片）。
"""
from __future__ import annotations

import os
import re

import pytest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "frontend/src/components/CapabilityPanel.tsx")


@pytest.fixture(scope="module")
def src_raw() -> str:
    with open(SRC, encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="module")
def src(src_raw: str) -> str:
    """剥掉行/block 注释（同 test_ux002_capability_panel 思路），让"代码层面"
    断言不被解释性注释里出现的标识符触发假阳性。"""
    s = re.sub(r"/\*.*?\*/", "", src_raw, flags=re.DOTALL)
    s = re.sub(r"//[^\n]*", "", s)
    return s


def test_calendar_google_auth_badge_component_exists(src: str) -> None:
    """``CalendarGoogleAuthBadge`` 抽成独立 component 挂在 category header。"""
    assert re.search(r"function CalendarGoogleAuthBadge\(", src), \
        "缺 CalendarGoogleAuthBadge component"


def test_capability_detail_no_longer_has_google_props(src: str) -> None:
    """``CapabilityDetail`` 不再接受 googleStatus / onGoogleAuth / onGoogleRevoke /
    googleBusy props（已搬到 category header 级）。"""
    # 抓 CardProps interface 定义那段
    m = re.search(r"interface CardProps\s*\{([^}]*)\}", src, flags=re.DOTALL)
    assert m, "缺 CardProps interface"
    body = m.group(1)
    for name in ("googleStatus", "onGoogleAuth", "onGoogleRevoke", "googleBusy"):
        assert name not in body, (
            f"CardProps 仍含 {name!r} —— 应该已搬到 category header"
        )


def test_capability_detail_signature_only_cap_and_onRefresh(src: str) -> None:
    """``function CapabilityDetail({cap, onRefresh}: CardProps)`` —— 严格两参。"""
    assert re.search(
        r"function CapabilityDetail\(\s*\{\s*cap,\s*onRefresh,?\s*\}\s*:\s*CardProps\)",
        src,
    ), "CapabilityDetail 签名不是 {cap, onRefresh} only —— 检查 google* 是否真删了"


def test_google_oauth_block_no_longer_inside_capability_detail(src: str) -> None:
    """``isCalendar`` 变量 / ``onGoogleAuth && void onGoogleAuth()`` 这类 calendar
    专属调用**只**在 CalendarGoogleAuthBadge 内出现。"""
    # isCalendar 变量已经不存在（之前在 CapabilityDetail 内 ``const isCalendar = ...``）
    assert "const isCalendar" not in src, \
        "CapabilityDetail 内 isCalendar 计算仍在 —— 没真删"


def test_calendar_header_uses_badge(src: str) -> None:
    """``{cat === 'calendar' && ...}`` 块内出现 ``<CalendarGoogleAuthBadge``。"""
    # 找 cat === 'calendar' 那个分支
    idx = src.find("cat === 'calendar'")
    assert idx > 0
    # 在 idx 之后 1000 字符内必须出现 CalendarGoogleAuthBadge
    chunk = src[idx:idx + 2000]
    assert "<CalendarGoogleAuthBadge" in chunk, (
        "calendar category header 块未挂 CalendarGoogleAuthBadge"
    )


def test_capability_row_expanded_content_no_google_props(src: str) -> None:
    """``<CapabilityDetail cap=... onRefresh=...>`` —— 不传 google* 参数（已搬走）。"""
    # 抓 <CapabilityDetail 那段
    m = re.search(
        r"<CapabilityDetail\s+([^/]+)/>",
        src,
    )
    assert m, "缺 <CapabilityDetail .../>"
    props = m.group(1)
    for name in ("googleStatus", "onGoogleAuth", "onGoogleRevoke", "googleBusy"):
        assert name not in props, (
            f"<CapabilityDetail .../> 仍传 {name!r} props"
        )


def test_test_briefing_button_still_in_category_header(src: str) -> None:
    """测试简报按钮保留在 category header（不能搬到 CapabilityDetail 里）。"""
    # 测试按钮的关键字符
    assert "测试今日简报" in src or "测试今日簡報" in src or "🧪" in src
    # 必须在 cat === 'calendar' 块附近
    idx = src.find("cat === 'calendar'")
    assert idx > 0
    chunk = src[idx:idx + 3000]
    assert "测试今日简报" in chunk
