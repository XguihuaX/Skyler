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


# ---------------------------------------------------------------------------
# External MCP clients status / reconnect
# ---------------------------------------------------------------------------

class MCPClientStatusItem(BaseModel):
    name: str
    description: str
    enabled: bool
    connected: bool
    transport: str
    tool_count: int
    expose_via_server: bool
    last_error: str | None
    # v3.5 chunk 7：UI 凭证配置驱动
    env_required: list[str] = []
    missing_credentials: list[str] = []


class MCPClientsStatusResponse(BaseModel):
    clients: list[MCPClientStatusItem]


@router.get("/mcp/clients/status", response_model=MCPClientsStatusResponse)
async def clients_status() -> MCPClientsStatusResponse:
    from backend.mcp import client as mcp_client
    rows = await mcp_client.list_status()
    return MCPClientsStatusResponse(clients=rows)


class ReconnectResponse(BaseModel):
    status: str
    detail: str | None = None


@router.post("/mcp/clients/{name}/reconnect", response_model=ReconnectResponse)
async def reconnect_client(name: str) -> ReconnectResponse:
    from backend.mcp import client as mcp_client
    try:
        await mcp_client.reconnect(name)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"client {name!r} not configured")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"reconnect failed: {exc}")
    return ReconnectResponse(status="ok", detail=f"reconnected {name}")


# ---------------------------------------------------------------------------
# v3.5 chunk 7：UI 驱动的 enable/disable + 凭证 CRUD
# ---------------------------------------------------------------------------


class EnabledBody(BaseModel):
    enabled: bool


class EnabledResponse(BaseModel):
    status: str
    name: str
    enabled: bool
    connected: bool
    tool_count: int
    detail: str | None = None


@router.put("/mcp/clients/{name}/enabled", response_model=EnabledResponse)
async def set_client_enabled(name: str, body: EnabledBody) -> EnabledResponse:
    """UI toggle 启用 / 禁用 MCP client。持久化到 DB ``mcp_client_state``。

    启用前 server 需要凭证（``env_required`` non-empty）但 DB 还没配齐 →
    422 + 列出缺哪些 key，UI 提示用户先配凭证。
    """
    from backend.mcp import client as mcp_client
    if body.enabled:
        # 预检：必填凭证齐了再 enable，避免拉起子进程立即 401
        status_list = await mcp_client.list_status()
        item = next((s for s in status_list if s["name"] == name), None)
        if item is None:
            raise HTTPException(status_code=404, detail=f"client {name!r} not configured")
        missing = item.get("missing_credentials") or []
        if missing:
            raise HTTPException(
                status_code=422,
                detail=f"missing credentials: {', '.join(missing)}",
            )
        try:
            await mcp_client.enable(name)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"client {name!r} not configured")
        except Exception as exc:
            # 已 persist enabled=True，但连接失败 → 返 500，前端可读 last_error
            raise HTTPException(status_code=500, detail=f"enable failed: {exc}")
    else:
        try:
            await mcp_client.disable(name)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"client {name!r} not configured")

    # 重读 status 给前端最新值
    rows = await mcp_client.list_status()
    item = next((s for s in rows if s["name"] == name), None)
    if item is None:
        raise HTTPException(status_code=404, detail=f"client {name!r} disappeared")
    return EnabledResponse(
        status="ok",
        name=name,
        enabled=item["enabled"],
        connected=item["connected"],
        tool_count=item["tool_count"],
        detail=item.get("last_error"),
    )


class CredentialsBody(BaseModel):
    # ``credentials`` = {KEY_NAME: value}; 空 value 视为删除该 key
    credentials: dict[str, str]


class CredentialsListItem(BaseModel):
    key_name: str
    configured: bool
    updated_at: str | None = None


class CredentialsListResponse(BaseModel):
    server_name: str
    keys: list[CredentialsListItem]


@router.get(
    "/mcp/clients/{name}/credentials",
    response_model=CredentialsListResponse,
)
async def list_client_credentials(name: str) -> CredentialsListResponse:
    """List configured credential **key names** (NOT values) for the server.

    Frontend uses this to render "API key configured ✓" badges without
    receiving secrets.
    """
    from backend.mcp import credentials as creds
    keys = await creds.list_keys(name)
    return CredentialsListResponse(
        server_name=name,
        keys=[CredentialsListItem(**k) for k in keys],
    )


@router.put(
    "/mcp/clients/{name}/credentials",
    response_model=CredentialsListResponse,
)
async def set_client_credentials(
    name: str, body: CredentialsBody,
) -> CredentialsListResponse:
    """Upsert one or more credentials. Empty value → delete that key.

    Body shape: ``{"credentials": {"NOTION_API_KEY": "secret_xxx"}}``。
    """
    from backend.mcp import credentials as creds
    from backend.mcp import client as mcp_client
    # 校验 name 存在（防止 LLM / curl 写入 typo server）
    status_list = await mcp_client.list_status()
    if not any(s["name"] == name for s in status_list):
        raise HTTPException(status_code=404, detail=f"client {name!r} not configured")
    if not body.credentials:
        raise HTTPException(status_code=422, detail="credentials dict is empty")
    for key, val in body.credentials.items():
        try:
            await creds.upsert(name, key, val or "")
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
    keys = await creds.list_keys(name)
    return CredentialsListResponse(
        server_name=name,
        keys=[CredentialsListItem(**k) for k in keys],
    )


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
