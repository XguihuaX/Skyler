"""UX-001 — CharacterStatePanel panel-mode top offset 回归测试。

防止未来不小心把 ``top: '48px'`` 改回 ``top: '12px'`` 让 TopBar 重新挡住。

TopBar h-10 = 40px / z-50；CharacterStatePanel z-30。任何 < TopBar 高度的
top 值都会让 panel 物理落在 TopBar 后方。
"""
from __future__ import annotations

import os
import re


SRC = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "frontend/src/components/CharacterStatePanel.tsx",
)


def _read() -> str:
    with open(SRC, encoding="utf-8") as f:
        return f.read()


def test_panel_top_offset_clears_topbar() -> None:
    """panel position 的 top 值必须 ≥ TopBar 高度 (h-10 = 40px)。"""
    src = _read()
    # 抓 `{ right: '...', top: 'Xpx' }` panel 分支
    m = re.search(r"right:\s*'16px'\s*,\s*top:\s*'(\d+)px'", src)
    assert m is not None, "panel-mode top offset block not found"
    top_px = int(m.group(1))
    assert top_px >= 40, (
        f"panel top={top_px}px < TopBar 40px → will be hidden behind TopBar; "
        f"raise to 48 (40 + 8 gap) or more"
    )


def test_widget_position_unchanged() -> None:
    """widget 模式仍然 right: 8px / bottom: 8px（无 TopBar，旧值正确）。"""
    src = _read()
    assert re.search(r"right:\s*'8px'\s*,\s*bottom:\s*'8px'", src)


def test_z_index_30_kept() -> None:
    """不动 z-index，避免浮到 TopBar 之上反而盖菜单。"""
    src = _read()
    assert re.search(r"zIndex:\s*30", src)
