"""UX-002 — CapabilityPanel.tsx 重构后结构断言。

* 所有 capability 通过 ``<CapabilityRow .../>`` 渲染（不再直接 ``<CapabilityCard>``）
* MCP banner / clients section 已删（重复 SettingsPanel.ExtensionsSection）
* category-level capability 计数 badge（``{N} cap`` 字面）
* 默认全折叠（``CapabilityRow defaultExpanded`` 不传 → 用 prop 默认 false）
"""
from __future__ import annotations

import os
import re

import pytest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PANEL_SRC = os.path.join(ROOT, "frontend/src/components/CapabilityPanel.tsx")
ROW_SRC = os.path.join(ROOT, "frontend/src/components/CapabilityRow.tsx")


@pytest.fixture(scope="module")
def panel_raw() -> str:
    """Whole file (含注释)。"""
    with open(PANEL_SRC, encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="module")
def panel(panel_raw: str) -> str:
    """**剥掉行注释 + block 注释**的 panel 源，断言"代码层面"是否引用名字。

    必要因为本 commit 把不少 ``MCPServerBanner`` / ``mcpServerStatus`` /
    ``fetchMcpClientsStatus`` 等名字写进**解释性注释**作为"为什么删"的标
    记，这些注释里出现这些标识符不算违规。
    """
    # 删 /* ... */ block 注释（含跨行）
    src = re.sub(r"/\*.*?\*/", "", panel_raw, flags=re.DOTALL)
    # 删 // ... 行注释
    src = re.sub(r"//[^\n]*", "", src)
    return src


# ---------------------------------------------------------------------------
# 删 MCP banner / clients section
# ---------------------------------------------------------------------------


def test_mcp_server_banner_removed(panel: str) -> None:
    """``MCPServerBanner`` 函数定义 + JSX 使用应**全部**消失。"""
    assert "function MCPServerBanner" not in panel
    assert "<MCPServerBanner" not in panel


def test_mcp_clients_section_removed(panel: str) -> None:
    assert "function MCPClientsSection" not in panel
    assert "<MCPClientsSection" not in panel


def test_mcp_state_callbacks_removed(panel: str) -> None:
    """`mcpServerStatus` / `mcpClients` state 移除。"""
    assert "mcpServerStatus" not in panel
    assert "mcpClients" not in panel
    assert "mcpReconnectingId" not in panel
    assert "refreshMcpServerStatus" not in panel
    assert "refreshMcpClients" not in panel
    assert "onReconnectClient" not in panel


def test_mcp_imports_removed(panel: str) -> None:
    """`fetchMcpClientsStatus` / `fetchMcpServerStatus` / `reconnectMcpClient` 等 import 已删。"""
    assert "fetchMcpClientsStatus" not in panel
    assert "fetchMcpServerStatus" not in panel
    assert "reconnectMcpClient" not in panel
    assert "MCPClientStatusItem" not in panel
    assert "MCPServerStatus" not in panel


# ---------------------------------------------------------------------------
# CapabilityRow 使用
# ---------------------------------------------------------------------------


def test_capability_row_imported(panel: str) -> None:
    assert "import CapabilityRow from './CapabilityRow'" in panel


def test_capability_row_used_in_map(panel: str) -> None:
    """category.map 内每行 capability 通过 ``<CapabilityRow ...>`` 渲染。"""
    assert "<CapabilityRow" in panel
    # name / displayName / briefDescription / leftIcon / statusBadge / expandedContent 都传
    assert re.search(r"name=\{cap\.name\}", panel)
    assert re.search(r"displayName=\{cap\.display_name\}", panel)
    assert re.search(r"briefDescription=\{_briefDesc\(cap\.description\)\}", panel)
    assert "leftIcon={<CapabilityIcon" in panel
    assert "statusBadge={" in panel
    assert "expandedContent={" in panel
    # CapabilityDetail 是 expandedContent 的内容（CapabilityCard 已 rename）
    assert "<CapabilityDetail" in panel


def test_capability_card_renamed_to_detail(panel: str) -> None:
    """``CapabilityCard`` 被 rename 成 ``CapabilityDetail``（body-only，不再 render header）。"""
    assert "function CapabilityCard" not in panel
    assert "function CapabilityDetail" in panel
    # CapabilityDetail 不再有 ``<CapabilityIcon`` 内联（icon 由 CapabilityRow.leftIcon 渲染）
    # 检查 CapabilityIcon 在 panel 内只用一处（CapabilityRow leftIcon slot 里）
    matches = re.findall(r"<CapabilityIcon\s", panel)
    assert len(matches) == 1, (
        f"<CapabilityIcon 出现 {len(matches)} 次（应该 == 1：仅 leftIcon slot）"
    )


# ---------------------------------------------------------------------------
# Category badge + briefDesc helper
# ---------------------------------------------------------------------------


def test_category_count_badge_rendered(panel: str) -> None:
    """category header 显示 ``{N} cap`` 计数 badge。"""
    assert "{grouped[cat].length} cap" in panel


def test_brief_desc_helper_exists(panel: str) -> None:
    """``_briefDesc`` 工具函数把长 description 截到 ~50 字符。"""
    assert re.search(r"function _briefDesc\(", panel)
    # 截断长度合理（不能截得太短）
    assert re.search(r"limit\s*=\s*5\d", panel) or re.search(r"50", panel)


# ---------------------------------------------------------------------------
# 默认折叠（commit 1 锁的 prop default false 被这里继承）
# ---------------------------------------------------------------------------


def test_no_default_expanded_override(panel: str) -> None:
    """CapabilityPanel 用 ``<CapabilityRow .../>`` 时**不传** defaultExpanded ——
    依赖 commit 1 锁的 default false 实现"全折叠"。

    防回归：曾经被改成 ``<CapabilityRow defaultExpanded={true} />`` 让某 category
    默认展开。
    """
    assert "defaultExpanded" not in panel, (
        "CapabilityPanel 引入了 defaultExpanded prop 传递 —— UX-002 硬约束 default 全折叠，"
        "不能在 panel 里 override"
    )
