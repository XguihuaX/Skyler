"""2026-06-15 ⑤ — MCP tool 调用前确认门 · runtime 拦截。

设计 (per PM SPEC):
  - prompt 不动:LLM 在 layered prompt 仍看到工具 schema · 调用时才被拦
  - capability handler 包裹:check `tool_state.is_confirmation_required` ·
    True → push WS event 'mcp_tool_confirm_request' → await asyncio.Event ·
    accept 继续 · reject / 超时 → 抛 ToolConfirmationRejected · capability
    handler 捕获后返"已取消"给 LLM 当 tool-result
  - WS protocol(ws.py 路由响应):
      → 服务端 push:{"type": "mcp_tool_confirm_request",
                      "request_id": "<uuid>", "cap_name": "ext.xhs.publish_note",
                      "server_name": "xhs", "tool_name": "publish_note",
                      "args_preview": "..."}
      ← 客户端回:{"type": "mcp_tool_confirm_response",
                  "request_id": "<uuid>", "accept": true}
  - 超时:asyncio.wait_for(120s) → DENY → "确认超时,已取消"
  - args_preview:仅 modal 展示(每 value 截 ~200 字 / 整体 ~600 字封顶) ·
    accept 后真 call_tool 用完整 args

模块状态:
  _pending_confirms: dict[request_id, _PendingConfirm]
  _push_callback: ws.py 注册的 push 函数 · None = WS 未就绪(降级 deny)

线程安全:asyncio 单 event loop · 字典操作不需锁。Event 跨 task 用 set/wait
跟 Q4 持有者-task 同 anyio 友好。
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public exception · _make_handler 抓它返"已取消"给 LLM
# ---------------------------------------------------------------------------


class ToolConfirmationRejected(Exception):
    """用户 reject 或确认超时 · LLM 看到的 tool-result = "用户已取消该操作" 或类似。

    故意继承 Exception(非 CancelledError)· asyncio.CancelledError 会被
    capability handler 上游再 raise 中断主对话 task;我们要的是干净返
    user-friendly 字符串给 LLM 看 · 不中断对话。
    """


# ---------------------------------------------------------------------------
# Pending state + WS push 钩子
# ---------------------------------------------------------------------------


@dataclass
class _PendingConfirm:
    request_id: str
    cap_name: str
    server_name: str
    tool_name: str
    args_preview: str
    event: asyncio.Event = field(default_factory=asyncio.Event)
    accept: bool = False  # 仅 event.set() 之后读


_pending_confirms: dict[str, _PendingConfirm] = {}

# ws.py 启动时注册 · None = WS 未连接 · 降级 DENY(safer default)
_PushCallback = Callable[[dict[str, Any]], Awaitable[None]]
_push_callback: Optional[_PushCallback] = None


def register_push_callback(callback: Optional[_PushCallback]) -> None:
    """ws.py 启动时调:注册 push 函数(`ws.send_json` wrapper)· None = 解绑。

    多 WS 连接场景(罕见 · Skyler 单用户)· 后注册的覆盖先注册的 · 简单单 callback。
    """
    global _push_callback
    _push_callback = callback


# ---------------------------------------------------------------------------
# Public API · client.py _make_handler 调用
# ---------------------------------------------------------------------------


_DEFAULT_TIMEOUT_SECONDS = 120
_ARGS_PREVIEW_VALUE_LIMIT = 200
_ARGS_PREVIEW_TOTAL_LIMIT = 600


def _build_args_preview(args: dict[str, Any]) -> str:
    """每 value 截 ~200 字 · 整体 ~600 字封顶 · 仅 modal 显示用。

    复杂 type(list / dict)走 repr 截字 · 不递归 · 避免无穷大对象消耗。
    """
    parts: list[str] = []
    for k, v in args.items():
        s = v if isinstance(v, str) else repr(v)
        if len(s) > _ARGS_PREVIEW_VALUE_LIMIT:
            s = s[:_ARGS_PREVIEW_VALUE_LIMIT] + "…(截断)"
        parts.append(f"{k}: {s}")
    full = "\n".join(parts)
    if len(full) > _ARGS_PREVIEW_TOTAL_LIMIT:
        full = full[:_ARGS_PREVIEW_TOTAL_LIMIT] + "\n…(整体截断)"
    return full


async def request_confirmation(
    *,
    cap_name: str,
    server_name: str,
    tool_name: str,
    args: dict[str, Any],
    timeout: float = _DEFAULT_TIMEOUT_SECONDS,
) -> None:
    """Push WS confirm event + await response · reject / 超时 → raise。

    Args:
        cap_name:    ext.<server>.<tool> · 跟 CapabilityRegistry 一致
        server_name / tool_name: 模板显示用
        args:        真实 tool call kwargs · 用于生成 preview · 不在 WS 传完整 args
        timeout:     秒 · 默认 120s · 超时按 DENY

    Raises:
        ToolConfirmationRejected: 用户 reject / 超时 / WS 未连接(降级 deny)
    """
    if _push_callback is None:
        # WS 未连 = 降级 DENY · 安全侧(没人看到 modal 时不能默认放行写/删操作)
        logger.warning(
            "[mcp.confirm_gate] no WS push callback registered · DENY "
            "%s tool=%s",
            cap_name, tool_name,
        )
        raise ToolConfirmationRejected(
            "WS 未连接 · 无法弹确认窗 · 已取消该操作"
        )

    request_id = uuid.uuid4().hex
    pending = _PendingConfirm(
        request_id=request_id,
        cap_name=cap_name,
        server_name=server_name,
        tool_name=tool_name,
        args_preview=_build_args_preview(args),
    )
    _pending_confirms[request_id] = pending

    try:
        try:
            await _push_callback({
                "type": "mcp_tool_confirm_request",
                "request_id": request_id,
                "cap_name": cap_name,
                "server_name": server_name,
                "tool_name": tool_name,
                "args_preview": pending.args_preview,
            })
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[mcp.confirm_gate] WS push failed for %s tool=%s: %s · DENY",
                cap_name, tool_name, exc,
            )
            raise ToolConfirmationRejected(
                "确认事件推送失败 · 已取消该操作"
            )

        logger.info(
            "[mcp.confirm_gate] awaiting confirm %s tool=%s (request_id=%s)",
            cap_name, tool_name, request_id[:8],
        )
        try:
            await asyncio.wait_for(pending.event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning(
                "[mcp.confirm_gate] timeout %.0fs · DENY %s tool=%s",
                timeout, cap_name, tool_name,
            )
            raise ToolConfirmationRejected(
                f"确认超时({int(timeout)}s)· 已取消该操作"
            )

        if not pending.accept:
            logger.info(
                "[mcp.confirm_gate] user REJECT %s tool=%s",
                cap_name, tool_name,
            )
            raise ToolConfirmationRejected("用户已取消该操作")

        logger.info(
            "[mcp.confirm_gate] user ACCEPT %s tool=%s · proceeding",
            cap_name, tool_name,
        )
    finally:
        _pending_confirms.pop(request_id, None)


def resolve_confirmation(request_id: str, accept: bool) -> bool:
    """ws.py 收到 'mcp_tool_confirm_response' 时调:set event 唤醒 caller。

    Returns:
        True 命中并 resolved · False request_id 未知(过期 / 重复)
    """
    pending = _pending_confirms.get(request_id)
    if pending is None:
        logger.warning(
            "[mcp.confirm_gate] unknown request_id=%s in response (accept=%s)",
            request_id[:8] if request_id else "?", accept,
        )
        return False
    pending.accept = bool(accept)
    pending.event.set()
    return True


def deny_all_pending() -> int:
    """2026-06-15 batch 2 [confirm 边界] · WS 断开时调:把所有挂起 confirm
    全判 DENY · 防孤儿 task 永远 await 死。

    request_confirmation 的 caller 看 `accept=False` 后抛 ToolConfirmationRejected ·
    handler 接到正常返"已取消"给 LLM · LLM 继续对话。

    Returns:
        被 deny 的 pending 数。
    """
    pending_list = list(_pending_confirms.values())
    for p in pending_list:
        p.accept = False
        p.event.set()
    if pending_list:
        logger.warning(
            "[mcp.confirm_gate] WS disconnect · denied %d pending confirm(s)",
            len(pending_list),
        )
    return len(pending_list)
