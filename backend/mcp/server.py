"""v3-G chunk 1.5 — MCP server 暴露层。

把 CapabilityRegistry 中的 capability **自动派生**成 MCP tool 暴露出去，外
部 LLM 工具（Claude Desktop / Cursor / Claude Code）可以 ``POST /mcp`` 调用
内部 capability。

派生规则
========
仅当 capability:
  1. 在 ``Consumer.CHAT_AGENT`` consumers 内（外部 LLM 等价于一个聊天
     agent，权限语义对齐）
  2. metadata 里 ``expose_via_server`` 不为 False（默认 True；外部 MCP
     反向接进来的 capability 可由 client config 决定要不要再次暴露，避免
     代理层级混乱 / API 配额泄露）

派生映射：
  cap.name              → tool.name
  cap.description       → tool.description
  cap.parameters_schema → tool.inputSchema  （None → 空 object schema）

调用路径：
  外部 client → POST /mcp → StreamableHTTPSessionManager → server.call_tool
  → CapabilityRegistry.get(name).handler(**arguments) → JSON 包成 TextContent

鉴权
====
``Authorization: Bearer <MCP_BEARER_TOKEN>`` —— 在 FastAPI 路由层做（dispatch
进 session manager 前），缺失 / 错误返 401。
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

import mcp.types as mcp_types
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

from backend.capabilities import CapabilityRegistry, Consumer

logger = logging.getLogger(__name__)


SERVER_NAME = "skyler"
SERVER_VERSION = "v3-G-chunk1.5"


def _is_exposable(cap) -> bool:
    """capability 是否要被 MCP server 暴露给外部。"""
    if Consumer.CHAT_AGENT not in cap.consumers:
        return False
    return bool(cap.metadata.get("expose_via_server", True))


def _build_tool_from_capability(cap) -> mcp_types.Tool:
    """capability metadata → mcp.types.Tool。"""
    schema = cap.parameters_schema or {
        "type": "object", "properties": {}, "required": [],
    }
    return mcp_types.Tool(
        name=cap.name,
        description=cap.description,
        inputSchema=schema,
    )


# ---------------------------------------------------------------------------
# Server 单例 + handler 注册
# ---------------------------------------------------------------------------

_server: Server = Server(SERVER_NAME)


@_server.list_tools()
async def _list_tools() -> list[mcp_types.Tool]:
    """实时从 CapabilityRegistry 派生 —— 运行时新加的外部 capability 自动出现。"""
    out: list[mcp_types.Tool] = []
    for cap in CapabilityRegistry().list_all():
        if not _is_exposable(cap):
            continue
        out.append(_build_tool_from_capability(cap))
    return out


@_server.call_tool()
async def _call_tool(
    name: str, arguments: dict[str, Any] | None,
) -> list[mcp_types.TextContent]:
    """把调用路由到 capability handler。"""
    cap = CapabilityRegistry().get(name)
    if cap is None:
        # 让 SDK 把 ValueError 转成 MCP InvalidParams JSON-RPC 错误
        raise ValueError(f"unknown tool: {name}")
    if not _is_exposable(cap):
        raise ValueError(f"tool not exposed: {name}")

    args = arguments or {}
    # ChatAgent 会注入 user_id；MCP server 调用没有 user_id 概念，按"系统调
    # 用"传 default —— 与既有 ChatAgent 路径一致，handler 都已用 **_kwargs
    # 兜住 user_id（chunk 0 / 1 验证过）。
    args.setdefault("user_id", os.environ.get("DEFAULT_USER_ID", "default"))

    try:
        result = await cap.handler(**args)
    except Exception as exc:
        logger.exception("[mcp.server] capability %s failed", name)
        raise ValueError(f"capability {name} failed: {exc}")

    # MCP 要求返回 list[TextContent | ImageContent | ...]。把任意 JSON 序
    # 列化结果包成单段 TextContent（外部 LLM 收到 JSON 字符串自己解析）。
    payload = json.dumps(result, ensure_ascii=False, default=str)
    return [mcp_types.TextContent(type="text", text=payload)]


# ---------------------------------------------------------------------------
# Streamable HTTP session manager（FastAPI 挂载用）
# ---------------------------------------------------------------------------

_session_manager: StreamableHTTPSessionManager | None = None


def get_session_manager() -> StreamableHTTPSessionManager:
    """懒加载 session manager 单例。

    ``stateless=True`` —— tool 调用是无状态请求，不需要服务端维护会话；这
    也避免长连接 + 多客户端时的 session id 冲突。
    """
    global _session_manager
    if _session_manager is None:
        _session_manager = StreamableHTTPSessionManager(
            app=_server,
            stateless=True,
            json_response=False,  # 用 SSE 流，跟 MCP 标准 transport 一致
        )
    return _session_manager


# ---------------------------------------------------------------------------
# 状态查询（/api/mcp/server/status 用）
# ---------------------------------------------------------------------------

def list_exposed_tool_names() -> list[str]:
    return [c.name for c in CapabilityRegistry().list_all() if _is_exposable(c)]


def get_bearer_token() -> str | None:
    """从 .env 读 MCP_BEARER_TOKEN。返回 None 表示未配置（auth 层应拒绝所有请求）。"""
    val = os.environ.get("MCP_BEARER_TOKEN", "").strip()
    return val or None
