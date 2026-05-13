"""v3-G chunk 1.5 — MCP server 状态 + ``/mcp`` 暴露端点路由。

* ``GET  /api/mcp/server/status`` —— 是否启用、endpoint、暴露 tool 数、Bearer
* ``POST /mcp``                    —— 真正的 MCP streamable HTTP 端点；鉴权后
  转发到 mcp SDK 的 SessionManager

外部 client 状态 / 重连路由在 chunk 1.5 commit B 加进来（client 模块就绪后）。
"""
from __future__ import annotations

import hmac
import logging
from pathlib import Path
from typing import Literal, Optional

import yaml
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from starlette.types import Receive, Scope, Send

from backend.config import config_yaml, reload_config_yaml
from backend.mcp import server as mcp_server
from backend.utils.yaml_atomic import write_config_atomic

# Stage 2.1.1: 与 backend/config/__init__.py / backend/routes/config_api.py
# 一致的 config.yaml 路径锚定。
_CONFIG_PATH = Path(__file__).parent.parent.parent / "config.yaml"

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

class MCPToolItem(BaseModel):
    """UX-001：单 tool 在 ExtensionsSection 折叠后的展开行。"""
    name: str
    description: str = ""
    enabled: bool


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
    # UX-001：connected server 已注册的 tool 列表 + 单 tool enabled override
    tools: list[MCPToolItem] = []


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
# Stage 2.1.1：POST / DELETE 新增 / 删除 MCP client entry
#
# 设计要点
#   - 写 yaml 走 ``write_config_atomic``(per-path lock + tmp + os.rename),
#     2.1.0 已落地,顺手为 2.1.2 前端 form 备好后端
#   - secrets **不写明文** 进 yaml:env dict 推荐 ``${VAR_NAME}`` 模板;
#     真实 token 仍走 ``mcp_credentials`` DB 表(``PUT /credentials``)
#   - POST 在 connect 失败时**不 rollback yaml** —— 让用户在 UI 看到失败
#     原因决定是否 DELETE 重试;比起静默清掉用户输入更友好
#   - DELETE 先 ``disable(name)``(同 PUT/enabled,防 in-flight tool call),
#     再 pop ``_clients`` + 删 yaml + 清 DB 凭证 / per-tool override
#   - DELETE 时 yaml 写失败 → 已 in-memory pop 但下次启动可能"幽灵恢复"
#     (config.yaml 还有 entry),返 500 + log warning,用户重试 DELETE 即可
# ---------------------------------------------------------------------------


class CreateClientBody(BaseModel):
    name: str = Field(..., min_length=1)
    description: Optional[str] = None
    transport: Literal["stdio", "http"]
    command: Optional[str] = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: Optional[str] = None
    enabled: bool = True
    expose_via_skyler_server: bool = True


class CreateClientResponse(BaseModel):
    name: str
    transport: str
    enabled: bool
    connected: bool
    tool_count: int
    error: Optional[str] = None


def _build_conf_dict(body: CreateClientBody) -> dict:
    """Body → yaml 写入用的 dict。与 config.yaml 现有 entry shape 对齐。"""
    conf: dict = {
        "description": body.description or "",
        "transport": body.transport,
        "enabled": body.enabled,
        "expose_via_skyler_server": body.expose_via_skyler_server,
    }
    if body.transport == "stdio":
        conf["command"] = body.command
        if body.args:
            conf["args"] = list(body.args)
        if body.env:
            conf["env"] = dict(body.env)
    else:  # http
        conf["url"] = body.url
    return conf


@router.post(
    "/mcp/clients",
    response_model=CreateClientResponse,
    status_code=201,
)
async def create_client(body: CreateClientBody) -> CreateClientResponse:
    """新增一个 MCP client entry:写 config.yaml + 注册到 ``_clients`` + 视
    ``enabled`` 决定是否立即 connect。

    Errors:
      * 409 — name 已存在(in ``_clients``)
      * 422 — stdio 缺 ``command`` / http 缺 ``url``
      * 500 — yaml 写失败(connect 失败**不**返 500,改返 200 +
        ``error`` 字段,让 UI 看到原因)
    """
    from backend.mcp import client as mcp_client
    from backend.mcp import credentials as _creds

    # 跨字段校验(Pydantic Literal 已挡 transport 取值,这里补 transport-
    # specific 必填)
    if body.transport == "stdio" and not (body.command and body.command.strip()):
        raise HTTPException(
            status_code=422, detail="stdio transport requires 'command'",
        )
    if body.transport == "http" and not (body.url and body.url.strip()):
        raise HTTPException(
            status_code=422, detail="http transport requires 'url'",
        )

    conf = _build_conf_dict(body)

    # 整个新增动作持 ``_lock`` —— 避免和并发 POST / DELETE / enable/disable
    # 抢 ``_clients`` 字典。``write_config_atomic`` 自己另有 per-path lock,
    # 不与 ``_lock`` 死锁。
    async with mcp_client._lock:
        if body.name in mcp_client._clients:
            raise HTTPException(
                status_code=409, detail=f"client {body.name!r} already exists",
            )

        def _add_entry(cfg: dict) -> None:
            clients = cfg.get("mcp_clients")
            if not isinstance(clients, dict):
                clients = {}
                cfg["mcp_clients"] = clients
            clients[body.name] = conf

        try:
            await write_config_atomic(_CONFIG_PATH, _add_entry)
        except (yaml.YAMLError, OSError) as exc:
            raise HTTPException(
                status_code=500, detail=f"config.yaml write failed: {exc}",
            )
        # 让 backend.config.config_yaml 立即对所有读侧可见(后续 init / list
        # 走的都是同一个 module-level dict)
        reload_config_yaml()

        # In-memory 注册
        handle = mcp_client._ClientHandle(body.name, conf)
        mcp_client._clients[body.name] = handle

        # enabled=True → 立即尝试连接;失败不 rollback yaml
        connect_error: Optional[str] = None
        if body.enabled:
            try:
                await _creds.set_enabled(body.name, True)
            except Exception as exc:
                logger.warning(
                    "[mcp] create %s set_enabled persist failed: %s",
                    body.name, exc,
                )
            try:
                await mcp_client._connect_one(handle)
            except Exception as exc:
                handle.last_error = str(exc)
                connect_error = str(exc)
                logger.warning(
                    "[mcp] create %s connect failed (yaml saved, user can "
                    "retry / DELETE): %s",
                    body.name, exc,
                )

    return CreateClientResponse(
        name=body.name,
        transport=body.transport,
        enabled=body.enabled,
        connected=handle.connected,
        tool_count=handle.tool_count,
        error=connect_error,
    )


class DeleteClientResponse(BaseModel):
    status: str
    name: str


@router.delete("/mcp/clients/{name}", response_model=DeleteClientResponse)
async def delete_client(name: str) -> DeleteClientResponse:
    """删一个 MCP client entry。

    流程:
      1. ``disable(name)`` —— DB enabled override 置 False + 已连接则
         ``_disconnect_one``(unregister capabilities + close transport)
      2. 从 ``_clients`` pop
      3. ``write_config_atomic`` 删 yaml entry
      4. Best-effort 清 ``mcp_tool_state`` + ``mcp_credentials`` DB 痕迹

    Errors:
      * 404 — name 不在 ``_clients``
      * 500 — yaml prune 失败(in-memory 已删,下次启动可能从 yaml 残留
        中恢复;告知用户重试 DELETE)
    """
    from backend.mcp import client as mcp_client
    from backend.mcp import credentials as _creds
    from backend.mcp import tool_state as _tool_state

    # 1. disable —— 内部用 _lock,完成后 handle.connected=False
    try:
        await mcp_client.disable(name)
    except KeyError:
        raise HTTPException(
            status_code=404, detail=f"client {name!r} not configured",
        )

    # 2. pop _clients(in_memory)+ 3. 删 yaml + 4. DB 清理。全在 _lock
    #    内,与并发 POST 互斥(同一时刻不会有 name 复活)
    yaml_error: Optional[str] = None
    async with mcp_client._lock:
        mcp_client._clients.pop(name, None)

        def _remove_entry(cfg: dict) -> None:
            clients = cfg.get("mcp_clients")
            if isinstance(clients, dict):
                clients.pop(name, None)

        try:
            await write_config_atomic(_CONFIG_PATH, _remove_entry)
            reload_config_yaml()
        except (yaml.YAMLError, OSError) as exc:
            yaml_error = str(exc)
            logger.warning(
                "[mcp] delete %s yaml prune failed: %s — ghost may "
                "reappear on restart (user should retry DELETE)",
                name, exc,
            )

        # Best-effort DB cleanup;失败不阻塞(留 row 也只是无害 stale data)
        try:
            await _tool_state.delete_for_server(name)
        except Exception as exc:
            logger.warning(
                "[mcp] delete %s tool_state cleanup failed: %s", name, exc,
            )
        try:
            await _creds.delete_all(name)
        except Exception as exc:
            logger.warning(
                "[mcp] delete %s credentials cleanup failed: %s", name, exc,
            )

    if yaml_error:
        raise HTTPException(
            status_code=500,
            detail=(
                f"client removed from memory but config.yaml prune failed: "
                f"{yaml_error}. Retry DELETE."
            ),
        )

    return DeleteClientResponse(status="ok", name=name)


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


# ---------------------------------------------------------------------------
# UX-001：per-tool enable/disable
# ---------------------------------------------------------------------------


class ToolEnabledBody(BaseModel):
    enabled: bool


class ToolEnabledResponse(BaseModel):
    server_name: str
    tool_name: str
    enabled: bool
    tool_count: int
    tools: list[MCPToolItem]


@router.put(
    "/mcp/clients/{name}/tools/{tool_name}/enabled",
    response_model=ToolEnabledResponse,
)
async def set_tool_enabled(
    name: str, tool_name: str, body: ToolEnabledBody,
) -> ToolEnabledResponse:
    """UI 单 tool toggle。

    * server 未连接 → 422（先 enable server 再翻 tool）—— server.tools 为空
      就没法知道 tool_name 合法不合法
    * tool_name 不在 server 暴露列表 → 422
    * 翻 disabled → unregister 该 ext.<server>.<tool> capability，立即对 LLM 不可见
    * 翻 enabled → re-register
    """
    from backend.mcp import client as mcp_client
    try:
        result = await mcp_client.set_tool_enabled(name, tool_name, body.enabled)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"client {name!r} not configured")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return ToolEnabledResponse(**result)


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
