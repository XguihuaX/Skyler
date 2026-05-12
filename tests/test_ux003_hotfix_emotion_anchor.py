"""UX-003 hotfix — 情绪 UI 锚 parent 修复回归。

UX-003 commit 3 改 ``CharacterStatePanel`` panel-mode 位置 ``right: 16px →
left: 16px`` 避开右上角历史按钮。但**漏防**:``<CharacterStatePanel>`` 在
``App.tsx`` 内作 ``<Panel>`` 的 sibling 渲染,nearest positioned ancestor 是
App 外层 ``<div className="w-screen h-screen ... relative">`` → 整个视口。
``left: 16px`` 落在 viewport 左边界 = Sidebar / ConversationList 列内,挡
顶部用户按钮 / 其他左上角元素。

本 hotfix:
1. App.tsx 只在 widget mode 渲染 ``<CharacterStatePanel position="widget">``
2. Panel.tsx chat-view 容器 ``<div className="relative flex-1 h-full
   overflow-hidden">`` 内部加 ``<CharacterStatePanel position="panel">``
   → 锚到 CharacterView 实际占据的子区域

测试覆盖:
- App.tsx 不再无条件渲染 panel-mode CharacterStatePanel
- Panel.tsx import + 渲染 CharacterStatePanel
- Panel.tsx render 点确实在 chat-view ``relative`` 容器内
"""
from __future__ import annotations

import os
import re

import pytest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_SRC = os.path.join(ROOT, "frontend/src/App.tsx")
PANEL_SRC = os.path.join(ROOT, "frontend/src/modes/Panel.tsx")


@pytest.fixture(scope="module")
def app_tsx() -> str:
    with open(APP_SRC, encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="module")
def panel_tsx() -> str:
    with open(PANEL_SRC, encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------------------
# App.tsx — 只 widget mode 渲染
# ---------------------------------------------------------------------------


def test_app_only_renders_emotion_panel_for_widget_mode(app_tsx: str) -> None:
    """``App.tsx`` 内 ``<CharacterStatePanel ...>`` 必须 gated by ``mode === 'widget'``,
    不再无条件渲染 panel-mode 实例(panel-mode 实例已迁到 Panel.tsx 内部
    chat-view 容器,锚到 CharacterView 子区域而非视口)。"""
    # 抓 CharacterStatePanel JSX 出现
    matches = re.findall(r"<CharacterStatePanel\b[^/]*/>", app_tsx)
    assert len(matches) == 1, (
        f"App.tsx 内 <CharacterStatePanel> 出现 {len(matches)} 次, 期望恰好 1 处"
    )
    # 该 1 处必须有 ``position="widget"`` 字面(不能是 ``position={mode === ...}``
    # 那种条件表达式)
    assert 'position="widget"' in matches[0], (
        f"App.tsx 的 CharacterStatePanel 必须固定 position=\"widget\", 实际: {matches[0]}"
    )
    # 该 JSX 必须**被** ``mode === 'widget' && `` short-circuit 保护
    # 抓 ``mode === 'widget' && <CharacterStatePanel`` 模式
    assert re.search(
        r"mode\s*===\s*['\"]widget['\"]\s*&&\s*<CharacterStatePanel",
        app_tsx,
    ), "App.tsx 缺 ``mode === 'widget' && <CharacterStatePanel>`` short-circuit"


def test_app_no_longer_renders_panel_mode_emotion_in_app_outer(app_tsx: str) -> None:
    """App.tsx 不该再有 ``position={mode === 'widget' ? 'widget' : 'panel'}``
    ternary —— panel mode 实例移到 Panel.tsx 内。"""
    assert not re.search(
        r"<CharacterStatePanel\s+position=\{mode\s*===\s*['\"]widget['\"]\s*\?\s*['\"]widget['\"]\s*:\s*['\"]panel['\"]\}",
        app_tsx,
    ), (
        "App.tsx 仍含 ``position={mode === 'widget' ? 'widget' : 'panel'}`` —— "
        "panel-mode 实例应该迁到 Panel.tsx 内部 chat-view 容器"
    )


# ---------------------------------------------------------------------------
# Panel.tsx — chat-view 容器内渲染 panel-mode 实例
# ---------------------------------------------------------------------------


def test_panel_imports_character_state_panel(panel_tsx: str) -> None:
    assert re.search(
        r"import\s+CharacterStatePanel\s+from\s+['\"]\.\./components/CharacterStatePanel['\"]",
        panel_tsx,
    ), "Panel.tsx 缺 CharacterStatePanel import"


def test_panel_renders_character_state_panel_position_panel(panel_tsx: str) -> None:
    """Panel.tsx 必须有 ``<CharacterStatePanel position="panel" />``。"""
    assert re.search(
        r"<CharacterStatePanel\s+position=['\"]panel['\"]\s*/>",
        panel_tsx,
    ), "Panel.tsx 缺 <CharacterStatePanel position=\"panel\" />"


def test_panel_emotion_inside_relative_chatview_container(panel_tsx: str) -> None:
    """``<CharacterStatePanel position="panel">`` 必须在 ``<div className="relative
    flex-1 h-full overflow-hidden">`` chat-view 容器内 —— 确保 absolute
    positioning 锚到该容器(它是 ``position: relative`` 的 positioned ancestor)
    而非更外层。

    检查方式:抓两者位置,断言 CharacterStatePanel 在容器开头(``relative
    flex-1 h-full overflow-hidden`` 字面所在行)之后、对应闭合 ``</div>`` 之前。
    """
    container_idx = panel_tsx.find('"relative flex-1 h-full overflow-hidden"')
    assert container_idx > 0, "找不到 chat-view ``relative flex-1 h-full overflow-hidden`` 容器"
    panel_jsx_idx = panel_tsx.find(
        '<CharacterStatePanel position="panel"', container_idx,
    )
    assert panel_jsx_idx > 0, "chat-view 容器之后未找到 CharacterStatePanel"
    # CharacterStatePanel 必须出现在 ChatInput 之前(以保证它仍在容器同 div 内,
    # 不被意外移到 outer 兄弟)
    chat_input_idx = panel_tsx.find('<ChatInput />', panel_jsx_idx)
    history_idx = panel_tsx.find('<ChatHistoryDrawer', panel_jsx_idx)
    assert chat_input_idx > 0, "ChatInput 不在 CharacterStatePanel 之后(结构异常)"
    assert history_idx > 0, "ChatHistoryDrawer 不在 CharacterStatePanel 之后"


def test_panel_emotion_renders_after_character_view(panel_tsx: str) -> None:
    """渲染顺序:``<CharacterView>`` 在 ``<CharacterStatePanel>`` 之前,
    确保 z-index 层级(CharacterView z-0 < emotion z-30)正常叠放。"""
    cv_idx = panel_tsx.find("<CharacterView ")
    sp_idx = panel_tsx.find('<CharacterStatePanel position="panel"')
    assert 0 < cv_idx < sp_idx, (
        f"渲染顺序错: CharacterView idx={cv_idx}, CharacterStatePanel idx={sp_idx}"
    )
