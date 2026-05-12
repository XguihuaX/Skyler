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


# ---------------------------------------------------------------------------
# hotfix-6: default-collapsed regression locks
# ---------------------------------------------------------------------------


def test_default_collapsed_initial_expanded_set_empty(src: str) -> None:
    """expanded 必须 useState<Set<string>>(new Set()) 初始化为空 Set。

    回归 case：曾经被改成 new Set(clients.map(...)) 之类的"默认全展开"路径。
    """
    assert re.search(
        r"useState<Set<string>>\(\s*new Set\(\s*\)\s*\)",
        src,
    ), "expanded state 不是 new Set() 初始化 — 检查是否被改成默认展开"


def test_tools_map_only_inside_isExpanded_gate(src: str) -> None:
    """整文件 ``client.tools.map`` 只能在 ToolList 内出现（被 isExpanded gate 包住）。

    防回归：曾经把 tool 列表 map 直接放在 ClientRow 顶层（line 284 badge 块附
    近），导致默认全展开 + 平铺一长串。
    """
    matches = [
        m.start() for m in re.finditer(r"client\.tools\.map\(", src)
    ]
    # 期望恰好 0 处（map 现在改 ToolList 内部用 ``client.tools.map`` 仍然是
    # ``client`` 因为是同一变量名 prop），所以 ClientRow 内不应再有 map 直接
    # 调用。允许 ToolList 内一处。
    # 简洁断言：``client.tools.map`` 出现 0 或 1 次；> 1 = 怀疑回归
    assert len(matches) <= 1, (
        f"client.tools.map 出现 {len(matches)} 次，怀疑回归（应该只在 ToolList "
        f"内部一处）。位置: {matches}"
    )


def test_toollist_component_separate(src: str) -> None:
    """ToolList 抽成独立 component（不在 ClientRow 内联），强化 gate 隔离。"""
    assert re.search(r"function ToolList\(", src), \
        "ToolList sub-component 缺失 — 是否被合并回 ClientRow？"
    # ClientRow 调 ToolList 走 ``<ToolList .../>``
    assert "<ToolList" in src


def test_isExpanded_gate_is_ternary_or_short_circuit(src: str) -> None:
    """isExpanded gate 必须是 ``isExpanded ? <ToolList .../> : null`` 或
    ``isExpanded && <ToolList .../>``。

    防回归：曾经误改成 ``true ? ...`` / 无条件渲染。
    """
    # 允许 ``isExpanded ? (\n  <ToolList`` 或 ``isExpanded && <ToolList`` 两种 JSX 风格
    assert (re.search(r"isExpanded\s*\?\s*\(?\s*<ToolList", src, flags=re.DOTALL)
            or re.search(r"isExpanded\s*&&\s*\(?\s*<ToolList", src, flags=re.DOTALL)), (
        "ClientRow 调 ToolList 时的 gate 表达式不在了 — 默认折叠可能失效"
    )


def test_toggleExpand_only_caller_of_setExpanded(src: str) -> None:
    """``setExpanded`` 必须只在 ``toggleExpand`` 函数体内调一次（不在 refresh / useEffect 里）。

    防回归：曾经在 refresh() 内偷偷 setExpanded(...) 自动展开。
    """
    occurrences = [m.start() for m in re.finditer(r"setExpanded\b", src)]
    # 一次是 useState 声明（``const [expanded, setExpanded] = useState(...)``），
    # 一次是 toggleExpand 内调用。合计 2 处。> 2 = 怀疑回归。
    assert len(occurrences) == 2, (
        f"setExpanded 出现 {len(occurrences)} 处（应该恰好 2 处：useState 声明 + "
        f"toggleExpand 调用）。多出的位置怀疑触发自动展开"
    )
