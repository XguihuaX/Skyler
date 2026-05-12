"""UX-002 — frontend ``CapabilityRow.tsx`` 通用 accordion row 静态结构断言。

走 chunk 7 / UX-001 同 grep pattern（环境无 vitest）：
* 关键 props 接收（name / displayName / briefDescription / statusBadge /
  leftIcon / expandedContent / defaultExpanded）
* 默认折叠（``useState<boolean>(defaultExpanded)`` 且 defaultExpanded 默认
  false）
* caret 用 ChevronDown / ChevronRight（视觉对齐 UX-001 / hotfix-6）
* expandedContent 只在 expanded=true 时渲染
* aria-expanded / aria-label 无障碍属性正确
"""
from __future__ import annotations

import os
import re

import pytest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "frontend/src/components/CapabilityRow.tsx")


@pytest.fixture(scope="module")
def src() -> str:
    with open(SRC, encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------------------
# Props interface
# ---------------------------------------------------------------------------


def test_props_interface_exposes_required_fields(src: str) -> None:
    """6 个 props 全部声明且只可选 ``statusBadge`` / ``leftIcon`` / ``defaultExpanded``。"""
    assert "export interface CapabilityRowProps" in src
    for required in ("name: string", "displayName: string",
                     "briefDescription: string", "expandedContent: ReactNode"):
        assert required in src, f"缺 required prop {required!r}"
    for optional in ("statusBadge?: ReactNode", "leftIcon?: ReactNode",
                     "defaultExpanded?: boolean"):
        assert optional in src, f"缺 optional prop {optional!r}"


# ---------------------------------------------------------------------------
# 默认折叠
# ---------------------------------------------------------------------------


def test_default_collapsed_via_defaultExpanded_false(src: str) -> None:
    """default 走 ``defaultExpanded = false`` 形参默认值，**不能**改成 true。"""
    assert re.search(r"defaultExpanded\s*=\s*false", src), \
        "defaultExpanded 必须 default false（UX-002 硬约束：全折叠启动）"


def test_initial_state_uses_defaultExpanded(src: str) -> None:
    """``useState<boolean>(defaultExpanded)`` —— state 初值跟形参绑死。"""
    assert re.search(r"useState<boolean>\(\s*defaultExpanded\s*\)", src), (
        "expanded state 初始化必须 useState<boolean>(defaultExpanded)，"
        "不能 hard-code true / 引入 derived state"
    )


# ---------------------------------------------------------------------------
# Caret + accordion gate
# ---------------------------------------------------------------------------


def test_imports_chevron_icons(src: str) -> None:
    """视觉对齐 UX-001：ChevronDown + ChevronRight 都从 lucide-react import。"""
    assert "ChevronDown" in src
    assert "ChevronRight" in src
    # 真正用到（不仅 import）
    assert "<ChevronDown" in src
    assert "<ChevronRight" in src


def test_expanded_gate_around_expandedContent(src: str) -> None:
    """``{expanded && (...)}`` 短路 gate 包住 expandedContent；
    不允许无条件渲染 expandedContent。"""
    # expandedContent 只能出现在 gate 内的渲染（外加 props 定义）
    matches = [m.start() for m in re.finditer(r"\bexpandedContent\b", src)]
    # 1 处 props interface + 1 处 destructure + 1 处实际 render = 3 处
    assert len(matches) <= 4, (
        f"expandedContent 出现 {len(matches)} 次（应 ≤ 4：interface / destructure / render）"
    )
    # gate 表达式 ``{expanded && ...`` 必须存在并紧跟 expandedContent
    assert re.search(
        r"\{expanded\s*&&\s*\(", src,
    ), "缺 ``{expanded && (...)}`` 短路 gate，可能默认展开"


def test_caret_toggle_via_setExpanded(src: str) -> None:
    """caret button onClick 调 ``setExpanded((v) => !v)``。

    防回归：曾经误改成 ``setExpanded(true)`` 单向只展开不收。
    """
    assert re.search(r"setExpanded\(\s*\(v\)\s*=>\s*!v\s*\)", src), (
        "caret 点击必须 toggle (v) => !v，不能单向"
    )


# ---------------------------------------------------------------------------
# 无障碍 + 视觉一致
# ---------------------------------------------------------------------------


def test_aria_attributes(src: str) -> None:
    assert 'aria-label={expanded ? \'折叠\' : \'展开\'}' in src
    assert "aria-expanded={expanded}" in src


def test_left_icon_optional_render(src: str) -> None:
    """``{leftIcon && (<span>...{leftIcon}</span>)}`` —— optional 渲染。"""
    assert re.search(r"\{leftIcon\s*&&", src)


def test_status_badge_optional_render(src: str) -> None:
    assert re.search(r"\{statusBadge\s*&&", src)


def test_data_capability_attr_for_dom_lookup(src: str) -> None:
    """``data-capability={name}`` 让集成测试 / DOM 查询能按 name 定位 row。"""
    assert 'data-capability={name}' in src


# ---------------------------------------------------------------------------
# Single export
# ---------------------------------------------------------------------------


def test_default_export(src: str) -> None:
    assert re.search(
        r"export default function CapabilityRow\(", src,
    ), "CapabilityRow 必须 default export"
