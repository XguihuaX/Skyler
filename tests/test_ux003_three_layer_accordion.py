"""UX-003 — CapabilityPanel 三层 accordion 全面回归断言。

锁:
1. category-level fold 状态 (Set<string>, 初始空 = 全折叠)
2. provider 自动分组规则 (_extractProvider) 边界 case
3. 多 provider category 走二层 render path,单 provider category 走 flat path
4. media → media_control display name 映射
5. ext.X provider 渲染 ``[ext]`` 角标
6. 默认全折叠 (category 折 + provider 折 + capability 折,3 层)
"""
from __future__ import annotations

import os
import re

import pytest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PANEL_SRC = os.path.join(ROOT, "frontend/src/components/CapabilityPanel.tsx")


@pytest.fixture(scope="module")
def panel_raw() -> str:
    with open(PANEL_SRC, encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="module")
def panel(panel_raw: str) -> str:
    """剥行/block 注释,代码层断言不被解释性注释里的标识符触发假阳性。"""
    s = re.sub(r"/\*.*?\*/", "", panel_raw, flags=re.DOTALL)
    s = re.sub(r"//[^\n]*", "", s)
    return s


# ---------------------------------------------------------------------------
# Part 1: category-level fold
# ---------------------------------------------------------------------------


def test_expanded_categories_state_initialized_as_empty_set(panel: str) -> None:
    """``useState<Set<string>>(new Set())`` 初始空 → 9 个 category 默认全折叠。"""
    assert re.search(
        r"const \[expandedCategories,\s*setExpandedCategories\]\s*=\s*"
        r"useState<Set<string>>\(\s*new Set\(\s*\)\s*\)",
        panel,
    ), "expandedCategories 必须初始化为 new Set() (UX-003 全折叠启动)"


def test_toggleCategory_is_only_setter_caller(panel: str) -> None:
    """``setExpandedCategories`` 只在 ``toggleCategory`` 函数体内被调一次。

    防回归: 曾经被改成在 refresh/useEffect 偷偷 setExpandedCategories 自动展开。
    """
    matches = re.findall(r"\bsetExpandedCategories\b", panel)
    # 1: useState 声明 + 1: toggleCategory 调用 = 2 处
    assert len(matches) == 2, (
        f"setExpandedCategories 出现 {len(matches)} 处 (期望 2: useState + "
        "toggleCategory)。> 2 怀疑被引入自动展开路径"
    )


def test_category_body_gated_by_catExpanded(panel: str) -> None:
    """category body 必须 ``{catExpanded && (...)}`` 短路 gate。"""
    assert re.search(r"\{catExpanded\s*&&\s*\(", panel), (
        "category body 缺 ``{catExpanded && (...)}`` gate"
    )


def test_category_header_role_button_for_keyboard_a11y(panel: str) -> None:
    """category header 用 ``role="button" tabIndex={0}`` 而非 ``<button>``
    (避免嵌套 button 非法 HTML)。
    """
    assert 'role="button"' in panel
    # 必须 Enter/Space 键盘支持
    assert "e.key === 'Enter'" in panel or 'e.key === "Enter"' in panel


# ---------------------------------------------------------------------------
# Part 2: provider-level fold
# ---------------------------------------------------------------------------


def test_expanded_providers_state_initialized_as_empty_set(panel: str) -> None:
    """``expandedProviders`` 初始空 → 多 provider category 内 provider 全折叠。"""
    assert re.search(
        r"const \[expandedProviders,\s*setExpandedProviders\]\s*=\s*"
        r"useState<Set<string>>\(\s*new Set\(\s*\)\s*\)",
        panel,
    )


def test_provider_key_uses_category_namespace(panel: str) -> None:
    """``${category}::${provider}`` 复合 key 防 namespace 撞(netease 同时
    存在 music + media)。"""
    assert "${cat}::${provider}" in panel or "`${cat}::${provider}`" in panel


def test_extract_provider_helper_exists(panel: str) -> None:
    assert re.search(r"function _extractProvider\(", panel)
    # ext.X.Y 分支必须显式处理
    assert re.search(r"parts\[0\]\s*===\s*'ext'", panel)


def test_provider_display_map_has_media_to_media_control(panel: str) -> None:
    """``PROVIDER_DISPLAY`` 含 ``media: 'media_control'``映射(用户 Q1 确认)。"""
    m = re.search(
        r"PROVIDER_DISPLAY[^{]*\{([^}]*)\}",
        panel,
        flags=re.DOTALL,
    )
    assert m, "找不到 PROVIDER_DISPLAY map"
    body = m.group(1)
    assert "'media_control'" in body or '"media_control"' in body
    assert "media:" in body


def test_grouped_by_provider_uses_useMemo(panel: str) -> None:
    """``groupedByProvider`` 必须 useMemo 缓存(每个 category 内 Map)。"""
    assert "groupedByProvider" in panel
    # useMemo + dep on grouped
    m = re.search(
        r"const groupedByProvider\s*=\s*useMemo\(",
        panel,
    )
    assert m


# ---------------------------------------------------------------------------
# Part 3: render path 分支(多 provider vs 单 provider)
# ---------------------------------------------------------------------------


def test_multi_provider_branch_renders_provider_rows(panel: str) -> None:
    """``groupedByProvider[cat].size > 1`` 分支必须存在。"""
    assert re.search(r"groupedByProvider\[cat\]\.size\s*>\s*1", panel)


def test_provider_row_renders_count_badge(panel: str) -> None:
    """provider row 必须显示 ``{provCaps.length} cap`` 计数。"""
    assert "{provCaps.length} cap" in panel


def test_ext_provider_renders_badge(panel: str) -> None:
    """provider 是 ``ext.X`` 时必须渲染 ``ext`` 角标(provider row 头部)。"""
    assert re.search(r"isExt\s*=\s*provider\.startsWith\(['\"]ext\.['\"]\)", panel)
    # 角标用 ``ext`` 文本(provider row 头部小角标,与单 capability 行的
    # ``[ext · server]`` 角标分开)
    assert re.search(r">\s*ext\s*<", panel)


def test_single_provider_branch_fallback_to_flat_list(panel: str) -> None:
    """当 ``size <= 1`` 必须 fall back 到 flat ``grouped[cat].map`` (UX-002 行为)。

    检查 ternary 的 ``: ( ... grouped[cat].map`` 结构(注释已剥),宽松匹配
    多 provider 分支结尾后 fallback 分支调 ``grouped[cat].map``。
    """
    # ternary form: `size > 1 ? ( ...A... ) : ( ...B... )` 必须出现
    # 其中 B 分支调 grouped[cat].map (flat fallback)。
    # 因为多 provider 分支也调过几次 grouped (provCaps 来自 groupedByProvider),
    # 我们只需确认 ``grouped[cat].map(`` 在源码至少 1 处出现 + ``size > 1`` 后
    # 有 ``: (`` ternary else branch。
    assert "groupedByProvider[cat].size > 1" in panel
    assert ") : (" in panel or "): (" in panel, (
        "三元运算 else 分支不存在 —— 单 provider 走 flat fallback 路径"
    )
    assert "grouped[cat].map" in panel, (
        "flat fallback 必须调 grouped[cat].map((cap) => <CapabilityRow .../>)"
    )


# ---------------------------------------------------------------------------
# Part 4: 完整默认全折叠状态(category + provider 都空 set)
# ---------------------------------------------------------------------------


def test_default_all_collapsed_three_layers(panel: str) -> None:
    """三个 state 都 useState<Set<string>>(new Set()) 初始空,3 层全折叠。

    layer 1: expandedCategories
    layer 2: expandedProviders
    layer 3: CapabilityRow 内部 expanded (UX-002 commit 1 已锁: defaultExpanded
              = false,本测试不重复)
    """
    layer1 = re.search(
        r"expandedCategories[^=]*=\s*useState<Set<string>>\(\s*new Set\(\s*\)\s*\)",
        panel,
    )
    layer2 = re.search(
        r"expandedProviders[^=]*=\s*useState<Set<string>>\(\s*new Set\(\s*\)\s*\)",
        panel,
    )
    assert layer1, "layer 1 (expandedCategories) 不是 new Set() 初始化"
    assert layer2, "layer 2 (expandedProviders) 不是 new Set() 初始化"


# ---------------------------------------------------------------------------
# Part 5: _extractProvider 端到端 behavior smoke
# ---------------------------------------------------------------------------


def test_provider_extraction_logic_handles_known_shapes(panel: str) -> None:
    """audit 实测的所有 capability name shape:
    - ``ext.filesystem.read_file`` → provider = ``ext.filesystem``
    - ``ext.brave-search.brave_web_search`` → provider = ``ext.brave-search``
    - ``apple_calendar.today_events`` → provider = ``apple_calendar``
    - ``netease.local_play_song`` → provider = ``netease``
    - ``xhs.parse_url`` → provider = ``xhs``
    - ``time.now`` → provider = ``time``

    grep 源代码确认 ``_extractProvider`` 在 split('.') 时拼回 ``ext.<X>``
    那两段。
    """
    m = re.search(
        r"function _extractProvider\(capName: string\): string \{([\s\S]*?)\n\}",
        panel,
    )
    assert m, "_extractProvider 函数体没抓到"
    body = m.group(1)
    # ext.X.Y 时返 `ext.${parts[1]}`
    assert "ext." in body and "parts[1]" in body
    # else 取 parts[0]
    assert "return parts[0]" in body
