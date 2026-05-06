"""v3-G chunk 0 — Capability Registry.

为后续所有 tool（Calendar / 网易云 / Bilibili / Pollinations / n8n trigger…）
提供统一的注册中枢。每个 capability 通过 ``@register_capability`` 装饰器
在 import time 注册到全局单例。

与既有 ``backend.tools.registry.ToolRegistry`` 的关系
====================================================

ToolRegistry（v3-C 引入）已经在做"name → callable + OpenAI function-calling
schema"这件事，且 ChatAgent 通过 ``ToolRegistry.list_schemas()`` 和
``ToolRegistry.call()`` 跑 LLM tool 调用闭环。**不能造平行系统**。

本 module 的策略：

* CapabilityRegistry 只负责"展示给人 + 路由元数据"那一层（display_name /
  category / icon / consumers / trigger_modes / health_check / 用户可见）
* 注册时若 ``Consumer.CHAT_AGENT`` 在 consumers，**自动**派生 OpenAI
  function-calling schema（按 capability.parameters_schema 包一层），并
  调 ``ToolRegistry.register(name, handler, schema)`` 把 handler 注入到
  ChatAgent 已有的 tool loop —— 零改 chat.py
* ChatAgent 调 tool 时仍走 ``ToolRegistry.call(name, user_id=..., **args)``，
  会透传 ``user_id`` 形参，所以 chat-agent-aware 的 capability handler
  必须能接受 ``user_id``（推荐用 ``user_id: str`` 显式参数；若 capability
  本身不需要 user_id，写 ``**_kwargs`` 兜住）

数据契约
========

``CapabilityRegistry`` 是单例 —— 进程内全局一份。运行时只读，注册阶段在
import time 完成（package ``__init__.py`` 触发各 capability module 的
import → decorator 副作用）。
"""
from __future__ import annotations

import asyncio
import inspect
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, ClassVar, Optional

from backend.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class Consumer(str, Enum):
    """谁能调用这个 capability。一个 capability 可以同时给多个 consumer。"""

    CHAT_AGENT = "chat_agent"   # ChatAgent 走 LiteLLM tool calling 主动调
    SCHEDULER  = "scheduler"     # cron / interval 定时触发
    WEBHOOK    = "webhook"       # 外部事件（n8n 等）触发


class TriggerMode(str, Enum):
    """capability 的典型触发模式 —— 主要给前端面板做 badge 展示。"""

    ON_DEMAND     = "on_demand"      # 用户 / agent 主动触发
    SCHEDULED     = "scheduled"       # cron 定时
    EVENT_DRIVEN  = "event_driven"    # 外部事件触发


@dataclass
class Capability:
    """一个 capability 的完整 metadata + handler。"""

    name: str
    display_name: str
    description: str
    category: str
    consumers: list[Consumer]
    trigger_modes: list[TriggerMode]
    handler: Callable[..., Any]
    icon: str = "circle"
    user_visible: bool = True
    health_check: Optional[Callable[[], Any]] = None
    parameters_schema: Optional[dict] = field(default=None)


class CapabilityRegistry:
    """进程级单例。capability 在 import time 注册，运行时只读。"""

    _instance: ClassVar[Optional["CapabilityRegistry"]] = None
    _capabilities: dict[str, Capability]

    def __new__(cls) -> "CapabilityRegistry":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._capabilities = {}
        return cls._instance

    def register(self, cap: Capability) -> None:
        """注册一个 capability。同名重复注册抛 ValueError。"""
        if cap.name in self._capabilities:
            raise ValueError(
                f"Capability {cap.name!r} already registered "
                f"(existing handler: {self._capabilities[cap.name].handler.__qualname__})"
            )
        self._capabilities[cap.name] = cap
        logger.debug(
            "registered capability: %s (consumers=%s, trigger_modes=%s)",
            cap.name,
            [c.value for c in cap.consumers],
            [t.value for t in cap.trigger_modes],
        )

        # CHAT_AGENT consumer → 派生 OpenAI schema 同时注册到 ToolRegistry，
        # 让 ChatAgent 的 list_schemas() 自动捕获，零改 chat.py。
        if Consumer.CHAT_AGENT in cap.consumers:
            schema = _build_openai_schema(cap)
            ToolRegistry.register(cap.name, cap.handler, schema)

    def get(self, name: str) -> Optional[Capability]:
        return self._capabilities.get(name)

    def list_all(self) -> list[Capability]:
        return list(self._capabilities.values())

    def list_for_consumer(self, consumer: Consumer) -> list[Capability]:
        return [c for c in self._capabilities.values() if consumer in c.consumers]

    def list_user_visible(self) -> list[Capability]:
        return [c for c in self._capabilities.values() if c.user_visible]

    def list_by_category(self) -> dict[str, list[Capability]]:
        out: dict[str, list[Capability]] = {}
        for cap in self._capabilities.values():
            if not cap.user_visible:
                continue
            out.setdefault(cap.category, []).append(cap)
        return out

    async def health_check_one(self, name: str) -> dict:
        """跑单个 capability 的 health_check。返回 ``{status, error?}``。"""
        cap = self.get(name)
        if cap is None:
            return {"status": "unknown", "error": f"capability {name!r} not found"}
        return await _run_health_check(cap)

    async def health_check_all(self) -> dict[str, dict]:
        """并发跑所有 capability 的 health_check。返回 ``{name: {status, error?}}``。"""
        names = [c.name for c in self._capabilities.values()]
        tasks = [_run_health_check(c) for c in self._capabilities.values()]
        results = await asyncio.gather(*tasks, return_exceptions=False)
        return dict(zip(names, results))

    def reset_for_test(self) -> None:
        """**测试专用** —— 清空注册表 + 同步清掉 ToolRegistry 里曾注入的条目。"""
        for name in list(self._capabilities.keys()):
            # ToolRegistry 没暴露 unregister，直接戳内部 dict（与 register 时
            # 的 _tools / _schemas 同模块）。仅测试路径使用。
            from backend.tools.registry import _tools, _schemas
            _tools.pop(name, None)
            _schemas.pop(name, None)
        self._capabilities.clear()


# ---------------------------------------------------------------------------
# decorator
# ---------------------------------------------------------------------------

def register_capability(
    *,
    name: str,
    display_name: str,
    description: str,
    category: str,
    consumers: list[Consumer],
    trigger_modes: list[TriggerMode],
    icon: str = "circle",
    user_visible: bool = True,
    health_check: Optional[Callable[[], Any]] = None,
    parameters_schema: Optional[dict] = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """装饰器：把被装饰函数注册成 capability。

    被装饰函数即 handler，签名必须 async 且能接受 ChatAgent 注入的
    ``user_id`` kwarg（即使 capability 本身不需要 user_id，也建议加
    ``**_kwargs`` 兜住，避免 TypeError）。
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        cap = Capability(
            name=name,
            display_name=display_name,
            description=description,
            category=category,
            consumers=consumers,
            trigger_modes=trigger_modes,
            handler=func,
            icon=icon,
            user_visible=user_visible,
            health_check=health_check,
            parameters_schema=parameters_schema,
        )
        CapabilityRegistry().register(cap)
        return func
    return decorator


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _build_openai_schema(cap: Capability) -> dict:
    """从 capability metadata 构造 OpenAI function-calling schema。"""
    parameters = cap.parameters_schema or {
        "type": "object", "properties": {}, "required": [],
    }
    return {
        "type": "function",
        "function": {
            "name": cap.name,
            "description": cap.description,
            "parameters": parameters,
        },
    }


async def _run_health_check(cap: Capability) -> dict:
    """统一执行 health_check：兼容 sync/async；任何异常都吞成 error 返回。"""
    if cap.health_check is None:
        return {"status": "unknown"}
    try:
        result = cap.health_check()
        if inspect.isawaitable(result):
            result = await result
    except Exception as exc:
        logger.warning("health_check failed for %s: %s", cap.name, exc)
        return {"status": "error", "error": str(exc)}

    # 约定 health_check 返回值：
    #   - True / "healthy" / {"status": "healthy"}     → healthy
    #   - "warn" / {"status": "warn", ...}             → warn
    #   - False / "error" / {"status": "error", ...}   → error（带 error msg 更佳）
    #   - dict 直接透传
    if isinstance(result, dict):
        return result
    if result is True or result == "healthy":
        return {"status": "healthy"}
    if result == "warn":
        return {"status": "warn"}
    if result is False or result == "error":
        return {"status": "error"}
    return {"status": "unknown"}
