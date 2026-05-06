"""v3-G chunk 1.5 — MCP client 接入层。

连接外部 MCP server（Anthropic 官方 / 社区现成 server），把对方的 tool **反
向注册**为 capability。注册后跟内置 capability 等价，ChatAgent 自动捕获。

支持两种 transport：

* **stdio**          —— 最常见。``command + args + env`` 启动子进程，stdin/
  stdout 双向 JSON-RPC（``mcp.client.stdio.stdio_client``）。npx 启动的
  Anthropic 官方 server 走这条
* **streamable HTTP** —— 远程 server。``url`` 直连
  （``mcp.client.streamable_http.streamablehttp_client``）

配置在 ``config.yaml`` 顶层 ``mcp_clients`` dict。每个 entry 字段：

  - description         展示用
  - transport           "stdio" | "http"
  - command / args / env (stdio)
  - url / headers       (http)
  - enabled             默认 False（用户主动开启）
  - expose_via_skyler_server  这个 client 的 tool 是否再被 Skyler MCP server
                              暴露出去。代理模式 = True；私有模式 = False
                              （比如 Brave search 不希望被多级转发，避免
                              API 配额泄露）

环境变量插值：``${HOME}`` / ``${BRAVE_API_KEY}`` 等用 ``os.path.expandvars``。

启动失败 **不阻塞** Skyler 主进程 —— 外部 server 挂了 / 命令找不到 / 网络
不通都只 log warning，client 状态置 disconnected，UI 提示用户。
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
from contextlib import AsyncExitStack
from datetime import timedelta
from typing import Any, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client

from backend.capabilities import (
    Capability,
    CapabilityRegistry,
    Consumer,
    TriggerMode,
)
from backend.config import config_yaml

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Client 状态对象
# ---------------------------------------------------------------------------

class _ClientHandle:
    """一个外部 MCP client 连接的运行时状态 + 资源句柄。"""

    def __init__(self, name: str, conf: dict) -> None:
        self.name = name
        self.conf = conf
        self.session: Optional[ClientSession] = None
        self.exit_stack: Optional[AsyncExitStack] = None
        self.tool_count: int = 0
        self.connected: bool = False
        self.last_error: Optional[str] = None

    def transport(self) -> str:
        return str(self.conf.get("transport") or "stdio")

    def expose_via_server(self) -> bool:
        return bool(self.conf.get("expose_via_skyler_server", True))

    def description(self) -> str:
        return str(self.conf.get("description") or "")

    def enabled(self) -> bool:
        return bool(self.conf.get("enabled", False))


_clients: dict[str, _ClientHandle] = {}
_lock = asyncio.Lock()


# ---------------------------------------------------------------------------
# 配置插值
# ---------------------------------------------------------------------------

def _expand_str(v: Any) -> Any:
    """递归 ``os.path.expandvars`` —— ``${HOME}`` / ``${BRAVE_API_KEY}`` 等替换。"""
    if isinstance(v, str):
        return os.path.expandvars(v)
    if isinstance(v, list):
        return [_expand_str(x) for x in v]
    if isinstance(v, dict):
        return {k: _expand_str(x) for k, x in v.items()}
    return v


# ---------------------------------------------------------------------------
# Connect / disconnect
# ---------------------------------------------------------------------------

async def _connect_one(handle: _ClientHandle) -> None:
    """启动 transport + 初始化 session + 注册 capabilities。失败抛异常。"""
    conf = _expand_str(handle.conf)
    stack = AsyncExitStack()
    try:
        transport_kind = handle.transport()
        if transport_kind == "stdio":
            command = conf.get("command")
            if not command:
                raise ValueError("stdio transport requires 'command'")
            # 尽早 fail —— 命令不存在时 stdio_client 会卡几秒
            if shutil.which(command) is None and not os.path.isabs(command):
                raise FileNotFoundError(f"command not found in PATH: {command}")
            params = StdioServerParameters(
                command=command,
                args=conf.get("args") or [],
                env={**os.environ, **(conf.get("env") or {})},
                cwd=conf.get("cwd"),
            )
            read_stream, write_stream = await stack.enter_async_context(
                stdio_client(params)
            )
        elif transport_kind == "http":
            url = conf.get("url")
            if not url:
                raise ValueError("http transport requires 'url'")
            # streamablehttp_client yields (read, write, get_session_id) tuple
            ctx = await stack.enter_async_context(
                streamablehttp_client(url, headers=conf.get("headers") or {})
            )
            read_stream, write_stream, _get_session_id = ctx
        else:
            raise ValueError(f"unknown transport: {transport_kind!r}")

        # init session（10s timeout 覆盖 npx 首次拉包等慢启动）
        session = await stack.enter_async_context(
            ClientSession(
                read_stream, write_stream,
                read_timeout_seconds=timedelta(seconds=30),
            )
        )
        await session.initialize()

        # 拉 tools 反向注册
        tools_resp = await session.list_tools()
        tools = list(tools_resp.tools)
        registered = 0
        for tool in tools:
            cap = _capability_from_external_tool(handle, session, tool)
            try:
                CapabilityRegistry().register_runtime(cap)
                registered += 1
            except ValueError:
                # 已存在（比如手动 reconnect 时上一轮没清掉），先 unregister 再注册
                CapabilityRegistry().unregister_runtime(cap.name)
                CapabilityRegistry().register_runtime(cap)
                registered += 1

        # commit handle 状态
        handle.session = session
        handle.exit_stack = stack
        handle.tool_count = registered
        handle.connected = True
        handle.last_error = None
        logger.info(
            "[mcp.client] %s connected (%s), %d tools registered",
            handle.name, transport_kind, registered,
        )
    except Exception:
        # 连接失败 → 释放已经入栈的资源
        await stack.aclose()
        raise


def _capability_from_external_tool(
    handle: _ClientHandle, session: ClientSession, tool,
) -> Capability:
    """外部 MCP tool → Capability。代理 handler 走 closure 默认参数固化 tool name。"""
    cap_name = f"ext.{handle.name}.{tool.name}"
    expose = handle.expose_via_server()

    # closure 默认参数固化 tool.name + session reference —— 避免循环里
    # 闭包共享同一个变量
    def _make_handler(_session: ClientSession, _tname: str = tool.name):
        async def _handler(**kwargs) -> Any:
            # 屏蔽 ChatAgent 注入的 user_id（外部 MCP 不知道这个概念，传过去
            # 容易 schema validation 失败）
            kwargs.pop("user_id", None)
            result = await _session.call_tool(_tname, kwargs)
            # CallToolResult.content 是 list[ContentBlock]；优先取第一个 text
            # 块直出 string；多个块 / 非 text 块退化成 list。
            blocks = list(result.content or [])
            if not blocks:
                return {"isError": result.isError, "content": None}
            simplified: list[Any] = []
            for blk in blocks:
                if hasattr(blk, "text") and getattr(blk, "type", "") == "text":
                    simplified.append(blk.text)
                else:
                    # 非 text 块（image/audio/resource 等）保留原始类型描述
                    simplified.append({
                        "type": getattr(blk, "type", "unknown"),
                        "_repr": repr(blk),
                    })
            if len(simplified) == 1 and isinstance(simplified[0], str):
                return {"isError": result.isError, "text": simplified[0]}
            return {"isError": result.isError, "content": simplified}
        return _handler

    def _make_health_check(_handle: _ClientHandle = handle):
        async def _hc() -> dict:
            if not _handle.connected:
                return {
                    "status": "warn",
                    "error": _handle.last_error or "client not connected",
                }
            return {"status": "healthy"}
        return _hc

    return Capability(
        name=cap_name,
        display_name=f"[{handle.name}] {tool.name}",
        description=tool.description or f"External MCP tool: {tool.name}",
        category="mcp_external",
        consumers=[Consumer.CHAT_AGENT],
        trigger_modes=[TriggerMode.ON_DEMAND],
        handler=_make_handler(session),
        icon="link-2",
        user_visible=True,
        health_check=_make_health_check(),
        parameters_schema=tool.inputSchema or {
            "type": "object", "properties": {}, "required": [],
        },
        metadata={
            "source_server": handle.name,
            "expose_via_server": expose,
            "external_tool_name": tool.name,
        },
    )


async def _disconnect_one(handle: _ClientHandle) -> None:
    """unregister capabilities + 释放 transport。"""
    # 清这个 client 派生的所有 capability
    prefix = f"ext.{handle.name}."
    reg = CapabilityRegistry()
    for cap_name in [c.name for c in reg.list_all() if c.name.startswith(prefix)]:
        reg.unregister_runtime(cap_name)
    # 关闭 transport
    if handle.exit_stack is not None:
        try:
            await handle.exit_stack.aclose()
        except Exception as exc:
            logger.warning("[mcp.client] %s exit_stack.aclose error: %s", handle.name, exc)
    handle.session = None
    handle.exit_stack = None
    handle.connected = False
    handle.tool_count = 0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def init_clients_from_config() -> None:
    """lifespan 启动钩子：按 config 启用所有 mcp_clients。

    单个 client 失败**不阻塞**整体 —— log warning + 标记 last_error 即可。
    """
    clients_cfg = config_yaml.get("mcp_clients") or {}
    async with _lock:
        for name, conf in clients_cfg.items():
            handle = _ClientHandle(name, conf or {})
            _clients[name] = handle
            if not handle.enabled():
                continue
            try:
                await _connect_one(handle)
            except Exception as exc:
                handle.last_error = str(exc)
                logger.warning(
                    "[mcp.client] failed to connect %s: %s", name, exc,
                )


async def shutdown_clients() -> None:
    """lifespan 关闭钩子：断开所有 client。"""
    async with _lock:
        for handle in list(_clients.values()):
            if handle.connected:
                try:
                    await _disconnect_one(handle)
                except Exception as exc:
                    logger.warning(
                        "[mcp.client] error disconnecting %s: %s", handle.name, exc,
                    )
        _clients.clear()


async def reconnect(name: str) -> None:
    """手动重连某个 client。先断开（含 unregister capability）再连接。

    Raises:
        KeyError: name 不在 config / 已注册的 clients 内
    """
    async with _lock:
        if name not in _clients:
            raise KeyError(name)
        handle = _clients[name]
        if handle.connected:
            await _disconnect_one(handle)
        try:
            await _connect_one(handle)
        except Exception as exc:
            handle.last_error = str(exc)
            raise


def list_status() -> list:
    """给 ``/api/mcp/clients/status`` 用。返回 pydantic-friendly dict 列表。"""
    out = []
    for name, handle in _clients.items():
        out.append({
            "name": name,
            "description": handle.description(),
            "enabled": handle.enabled(),
            "connected": handle.connected,
            "transport": handle.transport(),
            "tool_count": handle.tool_count,
            "expose_via_server": handle.expose_via_server(),
            "last_error": handle.last_error,
        })
    return out


def reset_for_test() -> None:
    """**测试专用**。"""
    _clients.clear()
