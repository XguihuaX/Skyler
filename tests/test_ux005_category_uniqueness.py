"""UX-005 — capability category 单一归属 audit guard。

防回归测试:任何 provider(capability name 的首段 / ``ext.X`` 形式)**必须**
只出现在一个 ``category`` 里。若有人改 capability 元数据让 provider 横跨
多 category(如 netease 同时在 music 和 media),本测试会立刻 fail。

也顺便检查 UX-005 commit 1 决定的归属:
  * netease 13 caps 全在 music
  * xhs 1 cap 在 social
  * media 只剩 bilibili + media_control
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 触发 capability 注册副作用 — 必须 import 全部 capability 模块
import backend.capabilities.activity            # noqa: F401
import backend.capabilities.apple_calendar      # noqa: F401
import backend.capabilities.bilibili            # noqa: F401
import backend.capabilities.calendar            # noqa: F401
import backend.capabilities.character_state     # noqa: F401
import backend.capabilities.clipboard           # noqa: F401
import backend.capabilities.docx_ops            # noqa: F401
import backend.capabilities.google_calendar     # noqa: F401
import backend.capabilities.media_control       # noqa: F401
import backend.capabilities.netease_music       # noqa: F401
import backend.capabilities.netease_playback    # noqa: F401
import backend.capabilities.screen              # noqa: F401
import backend.capabilities.time_capability     # noqa: F401
import backend.capabilities.xiaohongshu         # noqa: F401
import backend.proactive.snooze_capability      # noqa: F401

from backend.capabilities.registry import CapabilityRegistry


def _extract_provider(cap_name: str) -> str:
    """对齐 frontend ``CapabilityPanel._extractProvider``:
    ``ext.X.Y`` → ``ext.X``;否则取首段。"""
    parts = cap_name.split('.')
    if parts[0] == 'ext' and len(parts) >= 2:
        return f'ext.{parts[1]}'
    return parts[0]


def _build_provider_categories() -> dict[str, set[str]]:
    pc: dict[str, set[str]] = {}
    for cap in CapabilityRegistry().list_all():
        provider = _extract_provider(cap.name)
        pc.setdefault(provider, set()).add(cap.category)
    return pc


# ===========================================================================
# Guard 1: 任意 provider 不跨 category(核心 audit invariant)
# ===========================================================================


def test_no_provider_spans_multiple_categories() -> None:
    """任何 provider 必须只在 1 个 category 内。

    若 fail,means 有人加 / 改 capability 让某个 provider 横跨多 category
    (典型:netease 同时 music+media)— 这种状态会让用户在 CapabilityPanel
    里看到同名 provider 出现多次,体感困惑。
    """
    pc = _build_provider_categories()
    duplicates = {p: sorted(cats) for p, cats in pc.items() if len(cats) > 1}
    assert duplicates == {}, (
        f"以下 provider 横跨多 category(违反 UX-005 invariant):\n"
        + "\n".join(f"  {p}: {cats}" for p, cats in duplicates.items())
    )


# ===========================================================================
# Guard 2: UX-005 commit 1 决定的 category 归属(防有人后续改回去)
# ===========================================================================


def test_netease_all_in_music() -> None:
    pc = _build_provider_categories()
    assert pc.get("netease") == {"music"}, (
        f"netease 应单一归 music(UX-005 commit 1 决定),实际:"
        f"{sorted(pc.get('netease', set()))}"
    )


def test_xhs_in_social() -> None:
    pc = _build_provider_categories()
    assert pc.get("xhs") == {"social"}, (
        f"xhs 应单一归 social(UX-005 commit 1 决定),实际:"
        f"{sorted(pc.get('xhs', set()))}"
    )


def test_media_only_has_bilibili_and_media_control() -> None:
    """media category 应只剩 bilibili 视频站 + media_control 系统控制。

    netease.local_* 已搬到 music(commit 1);xhs 已搬到 social(commit 1)。
    """
    reg = CapabilityRegistry()
    media_caps = [c for c in reg.list_all() if c.category == "media"]
    providers = {_extract_provider(c.name) for c in media_caps}
    assert providers == {"bilibili", "media"}, (
        f"media category provider 应为 {{bilibili, media}},实际:{sorted(providers)}"
    )


# ===========================================================================
# Guard 3: 期望的 category 计数下限(防意外丢失 capability)
# ===========================================================================


def test_music_category_has_at_least_13_caps() -> None:
    """music = netease 7 API + 6 local playback = 13(UX-005 commit 1 后)。"""
    reg = CapabilityRegistry()
    music_count = sum(1 for c in reg.list_all() if c.category == "music")
    assert music_count >= 13, (
        f"music category cap 数 ({music_count}) < 13,可能 netease.local_* 没改成 music"
    )


def test_social_category_present() -> None:
    """social category 在 UX-005 commit 1 新建,应至少含 xhs。"""
    reg = CapabilityRegistry()
    social_count = sum(1 for c in reg.list_all() if c.category == "social")
    assert social_count >= 1, "social category 应至少含 xhs.parse_url"
