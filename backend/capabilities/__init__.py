"""Capability Registry — public surface.

使用：

    from backend.capabilities import (
        Capability, CapabilityRegistry,
        Consumer, TriggerMode, register_capability,
    )

注意：本 ``__init__`` 故意**不**直接 import 各 capability module（time_capability
等），避免引入循环 import 风险。各 capability 在 ``backend/main.py`` 显式
import，触发 decorator 副作用 → 注册到 CapabilityRegistry + ToolRegistry。
"""
from backend.capabilities.registry import (
    Capability,
    CapabilityRegistry,
    Consumer,
    TriggerMode,
    register_capability,
)

__all__ = [
    "Capability",
    "CapabilityRegistry",
    "Consumer",
    "TriggerMode",
    "register_capability",
]
