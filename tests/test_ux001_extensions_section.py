"""UX-001 — frontend ``ExtensionsSection.tsx`` accordion + per-tool toggle 静态结构断言。

走 chunk 7 test_mcp_chunk7.py 同 grep pattern：不跑真实渲染（无 vitest），
只在源文件里断言 UX-001 关键元素都出现。
"""
from __future__ import annotations

import os
import re

import pytest


SRC = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "frontend/src/components/ExtensionsSection.tsx",
)
LIB = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "frontend/src/lib/mcp_clients.ts",
)


@pytest.fixture(scope="module")
def src() -> str:
    with open(SRC, encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="module")
def lib() -> str:
    with open(LIB, encoding="utf-8") as f:
        return f.read()


def test_imports_chevron_icons(src: str) -> None:
    """accordion caret 需要 ChevronDown + ChevronRight。"""
    assert "ChevronDown" in src
    assert "ChevronRight" in src


def test_imports_setMCPToolEnabled_api(src: str) -> None:
    assert "setMCPToolEnabled" in src
    assert "MCPToolStatus" in src


def test_lib_exports_mcptool_status_types(lib: str) -> None:
    assert "export interface MCPToolStatus" in lib
    assert "export interface MCPToolEnabledResponse" in lib
    # MCPClientStatus 加 tools 字段
    assert re.search(r"tools:\s*MCPToolStatus\[\]", lib)


def test_lib_set_tool_enabled_uses_correct_route(lib: str) -> None:
    """``PUT /api/mcp/clients/{name}/tools/{tool}/enabled`` 路径串拼接验证。"""
    assert "/tools/" in lib
    assert "/enabled" in lib
    assert "encodeURIComponent(serverName)" in lib
    assert "encodeURIComponent(toolName)" in lib


def test_state_for_expand_and_tool_toggle(src: str) -> None:
    assert "useState<Set<string>>" in src
    assert "toolToggling" in src
    assert "toggleExpand" in src


def test_clientrow_accepts_new_props(src: str) -> None:
    assert "isExpanded:" in src
    assert "onExpand:" in src
    assert "onToolToggle:" in src


def test_toolrow_component_exists(src: str) -> None:
    """单 tool 行 component。"""
    assert re.search(r"function ToolRow\(", src)
    # 必须有 server.enabled gating（server 关 → tool toggle disabled）
    assert "server.enabled" in src
    assert re.search(r"value=\{tool\.enabled && server\.enabled\}", src)


def test_tool_count_badge_rendered(src: str) -> None:
    """``tool_count/total cap`` 角标在 ClientRow 头部出现。"""
    assert "tool_count" in src
    assert " cap" in src  # "X/Y cap" 字面


def test_disabled_server_disables_tool_toggle(src: str) -> None:
    """server 未启用 → ToolRow toggle disabled 表达式（react render-time gate）。"""
    # 关键表达：disabled={!client.enabled || ...}
    assert re.search(r"!client\.enabled\s*\|\|", src)


def test_optimistic_update_pattern(src: str) -> None:
    """乐观更新：setClients prev → map → 修改对应 tool.enabled。"""
    assert "setClients((prev)" in src
    assert "tool.name" in src
