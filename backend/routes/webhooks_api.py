"""v3-G chunk 0 — n8n / 外部 workflow 工具的 webhook receiver。

设计要点
========

* **Bearer token + HMAC SHA256 双因子鉴权**。Bearer token 防误调（共享密码），
  HMAC 防 payload 被中间人篡改。两者都在 ``.env`` 配置：
  - ``N8N_BEARER_TOKEN``
  - ``N8N_HMAC_SECRET``

* **签名约定**：``X-Signature: <hex(hmac_sha256(raw_body, secret))>``。注意
  签名是对**原始 body bytes**算的，不是 dict 序列化结果，避免 JSON 重新
  排序导致签名失效。``hmac.compare_digest`` 防 timing attack。

* **handler 路由**：``WEBHOOK_HANDLERS`` dict 把 ``trigger_name`` 映射到
  async handler。后续接 Calendar / 简报 / 主动对话推送时往这里加。

* **响应模式**：handler 用 ``asyncio.create_task`` 异步执行，路由立即返回
  ack —— n8n 默认 30s 超时，handler 长任务会触发重试，先 ack 再干活更稳。
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import os
from typing import Any, Awaitable, Callable

from fastapi import APIRouter, Header, HTTPException, Request

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Handlers — 按 trigger_name 路由
# ---------------------------------------------------------------------------

async def handle_test(payload: dict) -> dict:
    """示例 handler。仅 log + 回 echo。

    后续真实场景：
    - 推 Live2D 表情 / motion
    - 触发 ChatAgent 主动说话（v3-F' 接通后）
    - 写入 daily_briefing 队列
    """
    logger.info("[n8n webhook test] payload=%s", payload)
    return {"status": "ok", "echo": payload.get("text", "")}


WEBHOOK_HANDLERS: dict[str, Callable[[dict], Awaitable[dict]]] = {
    "test": handle_test,
}


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def _get_secret(env_name: str) -> str:
    """从 env 取密钥，缺失抛 500（防止"未配置"沦为静默放行）。"""
    val = os.environ.get(env_name, "").strip()
    if not val:
        # 用 503 而非 500 暗示运维：服务待配置
        raise HTTPException(
            status_code=503,
            detail=f"{env_name} not configured on server",
        )
    return val


def _verify_bearer(authorization: str) -> None:
    expected = _get_secret("N8N_BEARER_TOKEN")
    prefix = "Bearer "
    if not authorization.startswith(prefix):
        raise HTTPException(status_code=401, detail="invalid Authorization header")
    token = authorization[len(prefix):].strip()
    if not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="bearer token mismatch")


def _verify_hmac(raw_body: bytes, signature_hex: str) -> None:
    secret = _get_secret("N8N_HMAC_SECRET")
    expected = hmac.new(
        secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    # 容忍 sha256= 前缀（n8n 不少模板默认带）
    actual = signature_hex.removeprefix("sha256=").strip()
    if not hmac.compare_digest(actual, expected):
        raise HTTPException(status_code=401, detail="signature mismatch")


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

@router.post("/webhooks/n8n/{trigger_name}")
async def n8n_webhook(
    trigger_name: str,
    request: Request,
    x_signature: str = Header(..., alias="X-Signature"),
    authorization: str = Header(...),
) -> dict[str, Any]:
    """接收 n8n / 兼容 workflow 工具触发。

    流程：
      1. Bearer 校验
      2. 读 raw body → HMAC 校验
      3. 路由到 ``WEBHOOK_HANDLERS[trigger_name]``
      4. ``create_task`` 跑 handler，立即返回 ack
    """
    _verify_bearer(authorization)

    raw = await request.body()
    _verify_hmac(raw, x_signature)

    handler = WEBHOOK_HANDLERS.get(trigger_name)
    if handler is None:
        raise HTTPException(
            status_code=404,
            detail=f"unknown trigger: {trigger_name}",
        )

    # 解 JSON 出来给 handler 用。空 body 给 {} 兜底。
    import json
    try:
        payload = json.loads(raw) if raw else {}
        if not isinstance(payload, dict):
            raise ValueError("payload must be a JSON object")
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"invalid JSON: {exc}")

    # 异步跑，不阻塞 n8n（默认 30s 超时）
    asyncio.create_task(_run_handler_safely(trigger_name, handler, payload))

    return {"status": "accepted", "trigger": trigger_name}


async def _run_handler_safely(
    trigger_name: str,
    handler: Callable[[dict], Awaitable[dict]],
    payload: dict,
) -> None:
    """tail-call wrapper：异常都吞成 log，避免 task 失败静默挂掉。"""
    try:
        result = await handler(payload)
        logger.debug("[webhook %s] handler ok: %s", trigger_name, result)
    except Exception:
        logger.exception("[webhook %s] handler failed", trigger_name)
