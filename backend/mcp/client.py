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
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client

from backend.capabilities import (
    Capability,
    CapabilityRegistry,
    Consumer,
    TriggerMode,
)
from backend.config import config_yaml
# v3.5 chunk 7：DB 驱动的 credentials + runtime enable override
from backend.mcp import credentials as _creds
# UX-001：DB 驱动的 per-tool enable override
from backend.mcp import tool_state as _tool_state

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
        # UX-001：connected server 暴露的 tool 元数据。enabled 反映 DB override
        # （未在 mcp_tool_state 表里登记的 tool 默认 enabled=True）。
        # disconnected → []。
        self.tools: list[dict] = []
        # 2026-06-15 Q4 持有者-task 字段:每个 handle 一个后台任务持有 stack ·
        # async with stack: enter → await stop_event.wait() → 退栈 · 全在同一
        # task 内,解 anyio "Attempted to exit cancel scope in a different
        # task" 报错(原 bug 场景:UI POST enable 在 request worker task 内
        # enter,DELETE / lifespan shutdown 在另一 task 调 stack.aclose)。
        #
        # 4 个字段每次 _start_holder 重置一次(holder 不复用,disable 后下次
        # enable 起新 task)。
        self.stop_event: Optional[asyncio.Event] = None
        self.ready_event: Optional[asyncio.Event] = None
        self.holder_task: Optional[asyncio.Task] = None
        self.connect_error: Optional[BaseException] = None

    def transport(self) -> str:
        return str(self.conf.get("transport") or "stdio")

    def expose_via_server(self) -> bool:
        return bool(self.conf.get("expose_via_skyler_server", True))

    def description(self) -> str:
        return str(self.conf.get("description") or "")

    def enabled(self) -> bool:
        return bool(self.conf.get("enabled", False))

    def env_required(self) -> list[str]:
        """v3.5 chunk 7：config.yaml 声明的必填凭证名列表。

        UI 用这个判断哪些 key 还没配。Capability handler 不需要——子进程
        启动前 ``_connect_one`` 自动把 DB 里所有 ``mcp_credentials`` 注入 env。
        """
        v = self.conf.get("env_required") or []
        return [str(x) for x in v] if isinstance(v, list) else []


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

async def _holder_task(handle: _ClientHandle) -> None:
    """2026-06-15 Q4 持有者-task · 每个 client handle 一个后台任务。

    生命周期(全在本 task 内执行,解 anyio 跨 task cancel scope 报错):

        1. ENTER · 原 _connect_one body:启动 transport + 建 ClientSession +
           拉 tools + 注册 CapabilityRegistry · enter 失败时把异常存
           handle.connect_error 后 ready_event.set 唤醒等待方
        2. 设置 handle 状态(connected=True) + ready_event.set 唤醒 _start_holder
        3. HOLD · await handle.stop_event.wait() —— 等外部(disable / reconnect /
           lifespan shutdown)set stop_event
        4. EXIT · 退栈前 unregister capabilities + 清 handle 状态;
           async with 自动调 stack.__aexit__ → MCP SDK 的 stdio_client /
           streamablehttp_client / ClientSession 内部 anyio task group 取消跟
           退出 cancel scope 都在 enter 那个 task 内,**不会再跨 task 报错**

    异常路径:enter 中途任一步 raise → handle.connect_error 存,ready_event
    set,异常往外冒触发 async with 退栈(stack 部分入栈也能干净 aclose,因为
    仍在同一 task 内)· holder task 自然结束。
    """
    conf = _expand_str(handle.conf)
    try:
        # 2026-06-15 batch 2 [browser_login] · auth: browser_login entry 必须
        # 先 cookie 就位 · holder 不开浏览器 · 不挂登录子进程。前端先调
        # POST /api/mcp/clients/{name}/login 扫码 · 完成后再 enable。
        from backend.mcp import browser_login as _browser_login  # noqa: PLC0415
        if _browser_login.is_browser_login_entry(conf):
            if not _browser_login.cookie_ready(conf):
                raise FileNotFoundError(
                    "browser_login 类 server 需先扫码登录:cookie 未生成 / 已过期 "
                    "· 前端面板点「登录」按钮"
                )
        async with AsyncExitStack() as stack:
            # === ENTER · 原 _connect_one body ===
            transport_kind = handle.transport()
            if transport_kind == "stdio":
                command = conf.get("command")
                if not command:
                    raise ValueError("stdio transport requires 'command'")
                # 尽早 fail —— 命令不存在时 stdio_client 会卡几秒
                if shutil.which(command) is None and not os.path.isabs(command):
                    raise FileNotFoundError(f"command not found in PATH: {command}")
                # v3.5 chunk 7：env 三层叠加（后覆前）：
                #   1. os.environ        —— PATH 等基础环境
                #   2. config.yaml env   —— 兼容 chunk 1.5 旧路径（${BRAVE_API_KEY}）
                #   3. DB credentials    —— UI 输入的 API key 等（最高优先级）
                db_env = await _creds.get_env(handle.name)
                params = StdioServerParameters(
                    command=command,
                    args=conf.get("args") or [],
                    env={**os.environ, **(conf.get("env") or {}), **db_env},
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
            elif transport_kind == "sse":
                # 2026-06-15 Q1 SSE transport · 高德 https://mcp.amap.com/sse?key=
                # 等官方 SSE server 用这条。SDK 已装 mcp.client.sse.sse_client。
                #
                # ⚠️ URL 内的 ${VAR}(eg ?key=${AMAP_MAPS_API_KEY})已经被
                # _expand_str(handle.conf) 顶部展开(见 _holder_task 开头 conf
                # = _expand_str(handle.conf))· expandvars 顺序:os.environ +
                # DB credentials 通过 env 子进程注入(stdio 用)· 但 SSE 不走
                # 子进程 · 必须把 DB credentials 提前注入 os.environ 让
                # expandvars 能命中 · 否则 ${AMAP_MAPS_API_KEY} 字面值进 URL
                # = Q3 github bug 的 URL 版。
                #
                # 注入策略:enter sse_client 之前临时 patch os.environ · enter
                # 完成后立即 restore(避免污染整进程 env)。同 _connect_one 里
                # stdio 的 DB env 注入语义 · 只是路径不同。
                url = conf.get("url")
                if not url:
                    raise ValueError("sse transport requires 'url'")
                # 临时 patch:把 DB credentials merge 进 os.environ · expandvars
                # 已经在 _expand_str(handle.conf) 跑过 · 但那时还没 patch DB ·
                # 所以这里要单独再展开一次 URL。
                db_env = await _creds.get_env(handle.name)
                if db_env:
                    saved_env: dict[str, Optional[str]] = {}
                    for k, v in db_env.items():
                        saved_env[k] = os.environ.get(k)
                        os.environ[k] = v
                    try:
                        # 重新展开(_expand_str 顶部那次没赶上 DB env)
                        url = os.path.expandvars(url)
                        headers = {
                            k: os.path.expandvars(v) if isinstance(v, str) else v
                            for k, v in (conf.get("headers") or {}).items()
                        }
                    finally:
                        # 立即 restore os.environ 防污染
                        for k, prev in saved_env.items():
                            if prev is None:
                                os.environ.pop(k, None)
                            else:
                                os.environ[k] = prev
                else:
                    headers = conf.get("headers") or {}
                # sse_client yields (read, write) tuple
                read_stream, write_stream = await stack.enter_async_context(
                    sse_client(url, headers=headers)
                )
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
            # UX-001：先一次性拉本 server 的 per-tool override（少一次 N 次 DB 查询）
            overrides = await _tool_state.list_overrides(handle.name)
            # 2026-06-15 ⑤ · seed dangerous_tools 的 require_confirmation=1
            # (幂等 · 不覆盖已有 override · 用户 UI 翻 OFF 后不会被打回 1)
            dangerous = conf.get("dangerous_tools") or []
            dangerous_names: list[str] = (
                [str(t) for t in dangerous] if isinstance(dangerous, list) else []
            )
            if dangerous_names:
                seeded = await _tool_state.seed_require_confirmation(
                    handle.name, dangerous_names,
                )
                if seeded:
                    logger.info(
                        "[mcp.client] %s seeded require_confirmation=1 for %d "
                        "dangerous tool(s): %s",
                        handle.name, seeded, dangerous_names,
                    )
            # 2026-06-15 batch 2 [自校验] · 连上真实 server 后核对 dangerous_tools:
            #   1) config 列了某 dangerous tool · 但真 tool list 里没这个名字
            #      → WARN(护栏空跑 · 多半是配置打错字 / server 升级删了 tool)
            #   2) 真 tool 名字包含写/删/发常见动词关键字、但**没**在 config
            #      dangerous_tools 里 → WARN(可能裸跑 · 漏挂确认门)
            # 关键字集合刻意宽:正常 read 类(get/list/search)不命中 · 任何
            # 写/删/发都会命中 · 漏报代价 > 误报代价。
            real_tool_names = {t.name for t in tools}
            stale_dangerous = sorted(
                set(dangerous_names) - real_tool_names
            )
            if stale_dangerous:
                logger.warning(
                    "[mcp.client] %s dangerous_tools 含 %d 个真实 tool list "
                    "里没有的名字(护栏空跑 · 检查 mcp.config.yaml 拼写): %s",
                    handle.name, len(stale_dangerous), stale_dangerous,
                )
            _RISKY_VERB_KEYWORDS = (
                "delete", "remove", "push", "create", "update",
                "merge", "send", "publish", "write",
            )
            danger_set = set(dangerous_names)
            possibly_naked = sorted(
                t.name for t in tools
                if t.name not in danger_set
                and any(kw in t.name.lower() for kw in _RISKY_VERB_KEYWORDS)
            )
            if possibly_naked:
                logger.warning(
                    "[mcp.client] %s 真 tool list 含 %d 个名字像写/删/发的 tool "
                    "但**没**在 dangerous_tools(可能裸跑 · 检查是否漏挂确认门): %s",
                    handle.name, len(possibly_naked), possibly_naked,
                )
            registered = 0
            tool_meta: list[dict] = []
            for tool in tools:
                t_enabled = overrides.get(tool.name, True)
                tool_meta.append({
                    "name": tool.name,
                    "description": getattr(tool, "description", "") or "",
                    "enabled": t_enabled,
                    # 2026-06-02 · UI 试调骨架预填用 · 原样透传 MCP server 给的
                    # JSON Schema(同 _capability_from_external_tool:277)· 缺失 → None
                    "input_schema": getattr(tool, "inputSchema", None) or None,
                })
                if not t_enabled:
                    # 用户在 UI 把这条单独关了 —— 不注册到 CapabilityRegistry，
                    # LLM 见不到，schema 不暴露。重启后 enabled 翻 True 时
                    # `set_tool_enabled` 走 register 路径补回来。
                    continue
                cap = _capability_from_external_tool(handle, session, tool)
                try:
                    CapabilityRegistry().register_runtime(cap)
                    registered += 1
                except ValueError:
                    # 已存在（比如手动 reconnect 时上一轮没清掉），先 unregister 再注册
                    CapabilityRegistry().unregister_runtime(cap.name)
                    CapabilityRegistry().register_runtime(cap)
                    registered += 1

            # commit handle 状态(connected=True 后才 set ready_event)
            handle.session = session
            handle.exit_stack = stack
            handle.tool_count = registered
            handle.tools = tool_meta
            handle.connected = True
            handle.last_error = None
            skipped = len(tools) - registered
            logger.info(
                "[mcp.client] %s connected (%s), %d/%d tools registered "
                "(%d disabled per UI override)",
                handle.name, transport_kind, registered, len(tools), skipped,
            )
            assert handle.ready_event is not None
            handle.ready_event.set()

            # === HOLD · 等外部 set stop_event ===
            assert handle.stop_event is not None
            await handle.stop_event.wait()

            # === EXIT · 退栈前 unregister capabilities ===
            # 退栈本身由 async with 调 stack.__aexit__ 自动 · 跟 enter 同 task ✓
            prefix = f"ext.{handle.name}."
            reg = CapabilityRegistry()
            for cap_name in [c.name for c in reg.list_all() if c.name.startswith(prefix)]:
                try:
                    reg.unregister_runtime(cap_name)
                except KeyError:
                    pass
            handle.connected = False
            handle.session = None
            handle.tool_count = 0
            handle.tools = []
            logger.info("[mcp.client] %s holder task exiting cleanly", handle.name)
        # async with 退出 → stack 内 transport / session 全部 aclose · cancel
        # scope 退出时在持有者 task 内 ✓ · 不再报 "different task"
        handle.exit_stack = None
    except Exception as exc:  # noqa: BLE001 · ENTER 失败或 stop_event 等待期被取消
        handle.connect_error = exc
        handle.last_error = str(exc)
        handle.connected = False
        handle.session = None
        handle.exit_stack = None
        handle.tool_count = 0
        handle.tools = []
        # ENTER 失败也要唤醒 _start_holder 让它 raise(避免无限等)
        if handle.ready_event is not None and not handle.ready_event.is_set():
            handle.ready_event.set()
        logger.warning(
            "[mcp.client] %s holder task error: %s", handle.name, exc,
        )


async def _start_holder(handle: _ClientHandle) -> None:
    """启动 holder task + 等 ENTER 完成 · ENTER 失败抛 connect_error。

    幂等性:若 holder 已存在(handle.holder_task 未 done)→ no-op。
    """
    existing = handle.holder_task
    if existing is not None and not existing.done():
        return  # 已在跑 · 别再起新 task
    # 每次 start 重置 event + error(holder 不复用 · 上一轮的 stop_event 已被 set)
    handle.stop_event = asyncio.Event()
    handle.ready_event = asyncio.Event()
    handle.connect_error = None
    handle.holder_task = asyncio.create_task(
        _holder_task(handle), name=f"mcp-holder-{handle.name}",
    )
    await handle.ready_event.wait()
    if handle.connect_error is not None:
        # ENTER 失败 · holder task 应该已结束或正在结束 · 把 error 转出给调用方
        # 也清掉 holder_task 引用 · 下次 start 重新起
        try:
            await handle.holder_task
        except Exception:  # noqa: BLE001
            pass
        handle.holder_task = None
        raise handle.connect_error


async def _stop_holder(handle: _ClientHandle) -> None:
    """set stop_event + await holder task 完成退栈 · 防资源泄漏。

    幂等性:holder_task 已 done / 已 None → no-op · 不再 await 防 InvalidState。
    """
    task = handle.holder_task
    if task is None or task.done():
        handle.holder_task = None
        return
    if handle.stop_event is not None:
        handle.stop_event.set()
    try:
        await task
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[mcp.client] %s holder task await error: %s", handle.name, exc,
        )
    handle.holder_task = None


# ---------------------------------------------------------------------------
# 向后兼容 wrapper · 老路径(mcp_api.py POST create_client 等)透明转调
# ---------------------------------------------------------------------------

async def _connect_one(handle: _ClientHandle) -> None:
    """v3.5 chunk 7 wrapper · 转 _start_holder。

    保留同签名让 mcp_api.py POST /api/mcp/clients 等老 caller 透明 · 新代码
    请直接用 _start_holder。
    """
    await _start_holder(handle)


async def _disconnect_one(handle: _ClientHandle) -> None:
    """v3.5 chunk 7 wrapper · 转 _stop_holder。

    unregister capabilities 移到 holder task 内部退栈前做(_holder_task EXIT
    段),wrapper 只负责 set stop_event + await。
    """
    await _stop_holder(handle)


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



# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def _effective_enabled(handle: "_ClientHandle") -> bool:
    """v3.5 chunk 7: DB ``mcp_client_state`` override 优先于 config.yaml ``enabled``。

    None / 缺行 → 走 config.yaml 默认（向后兼容 chunk 1.5 单一 enabled 字段）。
    """
    override = await _creds.get_enabled_override(handle.name)
    if override is None:
        return handle.enabled()
    return override


async def init_clients_from_config() -> None:
    """lifespan 启动钩子：按 config 启用所有 mcp_clients。

    单个 client 失败**不阻塞**整体 —— log warning + 标记 last_error 即可。
    v3.5 chunk 7：``mcp_client_state`` DB override 优先于 ``config.yaml``。
    """
    clients_cfg = config_yaml.get("mcp_clients") or {}
    async with _lock:
        for name, conf in clients_cfg.items():
            handle = _ClientHandle(name, conf or {})
            _clients[name] = handle
            if not await _effective_enabled(handle):
                continue
            try:
                await _connect_one(handle)
            except Exception as exc:
                handle.last_error = str(exc)
                logger.warning(
                    "[mcp.client] failed to connect %s: %s", name, exc,
                )


async def shutdown_clients() -> None:
    """lifespan 关闭钩子：断开所有 client。

    2026-06-15 Q4 持有者-task:Phase 1 并发 set 所有 holder 的 stop_event ·
    Phase 2 并发 await holder task 完成退栈 · 防泄漏。原顺序 await 在 N 个
    server 都挂等 stack.aclose 时会拉长 lifespan shutdown(N × 单次超时)。
    """
    async with _lock:
        handles = list(_clients.values())
        # Phase 1 · 并发 set stop_event(把所有 holder 都从 await 唤醒)
        for handle in handles:
            task = handle.holder_task
            if task is not None and not task.done() and handle.stop_event is not None:
                handle.stop_event.set()
        # Phase 2 · 并发 await holder task 完成退栈 · 异常不阻塞其它(防一个挂
        # 卡死整个 lifespan)
        pending = [
            handle.holder_task for handle in handles
            if handle.holder_task is not None and not handle.holder_task.done()
        ]
        if pending:
            results = await asyncio.gather(*pending, return_exceptions=True)
            for exc in results:
                if isinstance(exc, BaseException):
                    logger.warning(
                        "[mcp.client] holder task shutdown error: %s", exc,
                    )
        # 清状态(holder 内部 EXIT 段已置 connected=False 等 · 这里 belt-and-suspenders)
        for handle in handles:
            handle.holder_task = None
            handle.connected = False
            handle.session = None
            handle.exit_stack = None
            handle.tool_count = 0
            handle.tools = []
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


# ---------------------------------------------------------------------------
# v3.5 chunk 7：UI 驱动的 enable/disable（与 reconnect 区分——这俩持久化到 DB）
# ---------------------------------------------------------------------------

async def enable(name: str) -> None:
    """启用 + 持久化 enabled=True + 立即尝试连接。

    Raises:
        KeyError: name 不在 config
        Exception: 连接失败（last_error 已设；调用方应转 HTTP 500）
    """
    async with _lock:
        if name not in _clients:
            raise KeyError(name)
        handle = _clients[name]
        await _creds.set_enabled(name, True)
        if handle.connected:
            return
        try:
            await _connect_one(handle)
        except Exception as exc:
            handle.last_error = str(exc)
            raise


async def disable(name: str) -> None:
    """禁用 + 持久化 enabled=False + 立即断开（如已连接）。

    Raises:
        KeyError: name 不在 config
    """
    async with _lock:
        if name not in _clients:
            raise KeyError(name)
        handle = _clients[name]
        await _creds.set_enabled(name, False)
        if handle.connected:
            await _disconnect_one(handle)


async def set_tool_enabled(server_name: str, tool_name: str, enabled: bool) -> dict:
    """UX-001：单 tool 级 enable/disable。持久化到 ``mcp_tool_state``。

    server 已连接：
      enabled=True  且当前未注册 → register + bump tool_count
      enabled=False 且当前已注册 → unregister + decrement tool_count
    server 未连接：仅持久化 override，下次 connect 时生效。

    返回该 server 最新的 ``tools`` 列表（与 list_status 同 shape）+ ``tool_count``。

    Raises:
        KeyError: server name 不在 config
        ValueError: tool_name 不在该 server 暴露的 tool 列表里
    """
    async with _lock:
        if server_name not in _clients:
            raise KeyError(server_name)
        handle = _clients[server_name]
        # 必须先有一份 tool meta（要么 server 已连接，要么 server 关着但
        # 历史上连过一次 —— 当前实现：disconnected → tools=[]，所以 server
        # 关时不允许翻 per-tool toggle。先 enable server 再翻 tool。）
        idx = next((i for i, t in enumerate(handle.tools) if t["name"] == tool_name), None)
        if idx is None:
            raise ValueError(
                f"tool {tool_name!r} not advertised by server {server_name!r} "
                f"(connect server first to populate tool list)"
            )
        was_enabled = bool(handle.tools[idx]["enabled"])
        # 持久化 + 内存同步
        await _tool_state.set_enabled(server_name, tool_name, enabled)
        handle.tools[idx]["enabled"] = enabled
        # CapabilityRegistry diff：根据 transition 决定 register/unregister
        if handle.connected and handle.session is not None:
            cap_name = f"ext.{server_name}.{tool_name}"
            reg = CapabilityRegistry()
            if enabled and not was_enabled:
                # 需要原始 tool 对象重建 capability。从 session list_tools 再拉一次。
                tools_resp = await handle.session.list_tools()
                tool_obj = next(
                    (t for t in tools_resp.tools if t.name == tool_name), None,
                )
                if tool_obj is None:
                    logger.warning(
                        "[mcp.client] %s.%s vanished from list_tools; skipping re-register",
                        server_name, tool_name,
                    )
                else:
                    cap = _capability_from_external_tool(handle, handle.session, tool_obj)
                    try:
                        reg.register_runtime(cap)
                    except ValueError:
                        reg.unregister_runtime(cap.name)
                        reg.register_runtime(cap)
                    handle.tool_count += 1
            elif not enabled and was_enabled:
                # unregister 不存在的 cap 抛 KeyError → silent
                try:
                    reg.unregister_runtime(cap_name)
                    handle.tool_count = max(0, handle.tool_count - 1)
                except KeyError:
                    pass
        return {
            "server_name": server_name,
            "tool_name": tool_name,
            "enabled": enabled,
            "tool_count": handle.tool_count,
            "tools": list(handle.tools),
        }


async def list_status() -> list:
    """给 ``/api/mcp/clients/status`` 用。返回 pydantic-friendly dict 列表。

    v3.5 chunk 7 扩展：
      - ``enabled`` 现在反映"effective"（DB override 优先于 config.yaml）
      - ``env_required`` 列出 config 声明的必填凭证 key
      - ``missing_credentials`` 列出"必填但 DB 里还没配"的 key（UI 用来禁
         用 toggle 并提示"先配置凭证"）
    """
    out = []
    for name, handle in _clients.items():
        configured = set((await _creds.get_env(name)).keys())
        required = handle.env_required()
        missing = [k for k in required if k not in configured]
        effective_enabled = await _effective_enabled(handle)
        out.append({
            "name": name,
            "description": handle.description(),
            "enabled": effective_enabled,
            "connected": handle.connected,
            "transport": handle.transport(),
            "tool_count": handle.tool_count,
            "expose_via_server": handle.expose_via_server(),
            "last_error": handle.last_error,
            "env_required": required,
            "missing_credentials": missing,
            # UX-001：per-server tool 列表 + 单 tool enabled 状态。
            # disconnected → []；UI 用 server enabled + tools 长度做"X cap"角标。
            "tools": list(handle.tools),
        })
    return out


def reset_for_test() -> None:
    """**测试专用**。"""
    _clients.clear()
