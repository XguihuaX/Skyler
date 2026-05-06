"""v3-G chunk 1.5 — MCP server 状态 + ``/mcp`` 暴露端点路由。

* ``GET  /api/mcp/server/status`` —— 是否启用、endpoint、暴露 tool 数、Bearer
* ``POST /mcp``                    —— 真正的 MCP streamable HTTP 端点；鉴权后
  转发到 mcp SDK 的 SessionManager

外部 client 状态 / 重连路由在 chunk 1.5 commit B 加进来（client 模块就绪后）。
"""
from __future__ import annotations

import hmac
import logging

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel
from starlette.types import Receive, Scope, Send

from backend.config import config_yaml
from backend.mcp import server as mcp_server

logger = logging.getLogger(__name__)
router = APIRouter()


def _server_config() -> dict:
    return config_yaml.get("mcp_server") or {}


# ---------------------------------------------------------------------------
# Server status
# ---------------------------------------------------------------------------

class MCPServerStatus(BaseModel):
    enabled: bool
    endpoint: str
    bearer_token_configured: bool
    bearer_token: str | None
    exposed_tool_count: int
    exposed_tool_names: list[str]


@router.get("/mcp/server/status", response_model=MCPServerStatus)
async def server_status() -> MCPServerStatus:
    cfg = _server_config()
    enabled = bool(cfg.get("enabled", False))
    endpoint_path = str(cfg.get("endpoint_path") or "/mcp")
    token = mcp_server.get_bearer_token()
    names = mcp_server.list_exposed_tool_names()
    return MCPServerStatus(
        enabled=enabled,
        endpoint=endpoint_path,
        bearer_token_configured=token is not None,
        bearer_token=token,
        exposed_tool_count=len(names),
        exposed_tool_names=names,
    )


# ---------------------------------------------------------------------------
# Streamable HTTP /mcp endpoint（鉴权 + ASGI 转发）
# ---------------------------------------------------------------------------

def _verify_bearer(authorization: str | None) -> None:
    expected = mcp_server.get_bearer_token()
    if expected is None:
        # 服务端未配置 token → 一律拒绝（防止裸暴露给任何调用方）
        raise HTTPException(
            status_code=503,
            detail="MCP_BEARER_TOKEN not configured on server",
        )
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing Bearer token")
    token = authorization[len("Bearer "):].strip()
    if not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="bearer token mismatch")


async def mcp_endpoint(request: Request) -> Response:
    """``POST /mcp`` 入口。鉴权 → mcp SDK SessionManager 接管 ASGI 通道。

    SessionManager.handle_request 直接接 scope/receive/send（流式 SSE 响应），
    所以这里不能用 FastAPI 普通的 ``@router.post`` body parsing 路径。
    """
    if not _server_config().get("enabled", False):
        raise HTTPException(status_code=503, detail="MCP server disabled in config")

    _verify_bearer(request.headers.get("authorization"))

    manager = mcp_server.get_session_manager()
    scope: Scope = request.scope
    receive: Receive = request.receive
    # Starlette 内部 send（稳定 attr）
    send: Send = request._send  # type: ignore[attr-defined]
    await manager.handle_request(scope, receive, send)
    return Response(status_code=200)
