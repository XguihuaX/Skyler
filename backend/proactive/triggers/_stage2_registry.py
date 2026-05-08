"""v3-G chunk 4 部分 C — proactive stage 2 addendum 总注册表。

chunk 2.6 wake_call 一个 trigger 时 chat.py 直接 hardcode 一个
``WAKE_CALL_STAGE2_ADDENDUM``。chunk 4 加 4 个新 trigger（lunch_call /
dinner_call / bedtime_chat / long_idle），每个 stage 2 内容侧重点不同：
餐前关心吃啥、睡前回顾今日、长时不说话轻触你。本模块把"trigger name →
(stage 1 SENTINEL, stage 2 addendum builder)"统一注册到一个 dict，
``chat.py`` 按 ``last_assistant.proactive_trigger`` 查表分发。

设计契约
========

每个 trigger 模块对外暴露：

* ``STAGE1_SENTINEL: str`` —— 嵌入 stage 1 prompt 头部的稳定哨兵字符串，
  ``chat._build_messages`` 用它识别"我现在正在 stage 1 内部"，跳过 stage 2
  探测避免无限递归（chunk 2.6 教训）。
* ``build_stage2_addendum(user_text: str, briefing_data_json: str,
  city: str | None) -> str`` —— stage 2 命中时 chat.py 用此函数生成
  prompt 末尾追加段。

注册时机
========

每个 trigger 模块 import 时 ``register_stage2(trigger_name, builder)``，
chat.py 按 ``proactive_trigger`` 查 ``_STAGE2_BUILDERS``。空 → 退回原有
wake_call 行为（向后兼容）。
"""
from __future__ import annotations

from typing import Callable, Dict, Optional

# trigger.name → (sentinel, builder)
_STAGE1_SENTINELS: Dict[str, str] = {}
_STAGE2_BUILDERS: Dict[str, Callable[[str, str, Optional[str]], str]] = {}


def register_stage2(
    trigger_name: str,
    sentinel: str,
    builder: Callable[[str, str, Optional[str]], str],
) -> None:
    """注册 trigger 的 stage 1 sentinel + stage 2 addendum builder。"""
    _STAGE1_SENTINELS[trigger_name] = sentinel
    _STAGE2_BUILDERS[trigger_name] = builder


def get_stage1_sentinel(trigger_name: str) -> Optional[str]:
    return _STAGE1_SENTINELS.get(trigger_name)


def all_stage1_sentinels() -> list[str]:
    """chat._build_messages 用全集做 sentinel detection（任一命中即跳过 stage 2）。"""
    return list(_STAGE1_SENTINELS.values())


def build_stage2_addendum(
    trigger_name: str,
    user_text: str,
    briefing_data_json: str,
    city: Optional[str] = None,
) -> Optional[str]:
    """按 trigger_name 查 builder 生成 addendum；无注册返 None。"""
    builder = _STAGE2_BUILDERS.get(trigger_name)
    if builder is None:
        return None
    try:
        return builder(user_text, briefing_data_json, city)
    except Exception:
        return None


__all__ = [
    "register_stage2",
    "get_stage1_sentinel",
    "all_stage1_sentinels",
    "build_stage2_addendum",
]
