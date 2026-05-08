"""v3-G chunk 3 — 角色状态 + 剪贴板捕获路由。

* ``GET /api/characters/{id}/state``       —— 拿当前 state（chunk 3b）
* ``POST /api/characters/{id}/reset_state`` —— 重置（chunk 3b）
* ``POST /api/clipboard/captured``         —— 前端推送剪贴板变化（chunk 3a，
  备用路径；后端 NSPasteboard 后台轮询是主路径）
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import AsyncSessionLocal
from backend.database.services import (
    get_or_create_character_state,
    reset_character_state,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _serialize(state) -> dict:
    return {
        "character_id": state.character_id,
        "mood": state.mood,
        "intimacy": state.intimacy,
        "thought": state.current_thought,
        "activity": state.current_activity,
        "last_interaction_at": state.last_interaction_at.isoformat()
            if state.last_interaction_at else None,
        "updated_at": state.updated_at.isoformat() if state.updated_at else None,
    }


# ---------------------------------------------------------------------------
# 1. GET state
# ---------------------------------------------------------------------------

@router.get("/characters/{character_id}/state")
async def get_character_state(character_id: int) -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        state = await get_or_create_character_state(session, int(character_id))
    return _serialize(state)


# ---------------------------------------------------------------------------
# 2. reset_state
# ---------------------------------------------------------------------------

@router.post("/characters/{character_id}/reset_state")
async def reset_state(character_id: int) -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        state = await reset_character_state(session, int(character_id))

    # push state_update 让前端状态条立即刷新（不抛错；WS 不可达 best-effort）
    try:
        from backend.config import config_yaml
        from backend.routes.ws import connection_manager
        user_id = str(config_yaml.get("default_user_id") or "default")
        await connection_manager.push(user_id, {
            "type": "state_update",
            "character_id": int(character_id),
            "mood": state.mood,
            "intimacy": state.intimacy,
            "thought": state.current_thought,
            "activity": state.current_activity,
        })
    except Exception:
        logger.warning(
            "[reset_state] WS push failed (route success regardless)",
            exc_info=False,
        )

    return _serialize(state)


# ---------------------------------------------------------------------------
# 3. POST clipboard/captured (chunk 3a，前端备用通道)
# ---------------------------------------------------------------------------

class ClipboardCapturedBody(BaseModel):
    content: str
    content_type: Optional[str] = None  # 'url' / 'code' / 'plain_text' / 'markdown' / 'json'


# ---------------------------------------------------------------------------
# v3-G chunk 4 部分 C — heartbeat (long_idle 用)
# ---------------------------------------------------------------------------

class HeartbeatBody(BaseModel):
    user_id: Optional[str] = None


@router.post("/heartbeat")
async def heartbeat(body: HeartbeatBody) -> dict[str, Any]:
    """v3-G chunk 4：前端心跳。前端 hook 在 visibility=visible + focus 时
    每 15 秒调本路由 → ``long_idle`` trigger 用此判定"用户还在前台"。

    内存 dict ``_LAST_HEARTBEAT`` 进程内共享；重启清空。无新装依赖。
    """
    from backend.config import config_yaml as _cfg
    from backend.proactive.triggers.long_idle import record_heartbeat
    user_id = body.user_id or str(_cfg.get("default_user_id") or "default")
    record_heartbeat(user_id)
    return {"ok": True, "user_id": user_id}


@router.get("/clipboard/recent")
async def clipboard_recent(n: int = 5) -> dict[str, Any]:
    """前端 SettingsPanel 剪贴板 section 列最近 N 条 (默认 5，max 20)。"""
    from backend.integrations.clipboard import clipboard_watcher
    nn = max(1, min(int(n), 20))
    items = clipboard_watcher.get_recent(nn)
    return {"count": len(items), "items": [it.to_dict() for it in items]}


@router.post("/clipboard/clear")
async def clipboard_clear() -> dict[str, Any]:
    """前端 [全部清除] 按钮 → 清空 ringbuffer。"""
    from backend.integrations.clipboard import clipboard_watcher
    n = clipboard_watcher.clear_all()
    return {"cleared": n}


class ClipboardEnabledBody(BaseModel):
    enabled: bool


@router.get("/clipboard/enabled")
async def clipboard_get_enabled() -> dict[str, Any]:
    """v3-G chunk 4 部分 B：返回 ClipboardWatcher 当前 enabled 状态。

    runtime override only —— ClipboardWatcher.set_enabled 改的是内存 flag，
    本路由读同一份。重启回到 yaml 默认（默认 True）。
    """
    from backend.integrations.clipboard import clipboard_watcher
    return {"enabled": clipboard_watcher._enabled}  # noqa: SLF001


@router.post("/clipboard/enabled")
async def clipboard_set_enabled(body: ClipboardEnabledBody) -> dict[str, Any]:
    """v3-G chunk 4 部分 B：开 / 关 1Hz 轮询。

    enabled=False → ClipboardWatcher._poll_loop 跳过 _poll_once（ringbuffer
    已捕获条目保留，仅停新捕获）。enabled=True → 恢复 1Hz 轮询。

    **不写 config.yaml**：runtime override only。重启时回到 yaml 默认值，
    避免误入"持久关闭"状态用户找不到入口。
    """
    from backend.integrations.clipboard import clipboard_watcher
    clipboard_watcher.set_enabled(bool(body.enabled))
    logger.info("[clipboard] runtime enabled=%s (not persisted)", body.enabled)
    return {"enabled": clipboard_watcher._enabled}  # noqa: SLF001


@router.post("/clipboard/captured")
async def clipboard_captured(body: ClipboardCapturedBody) -> dict[str, Any]:
    """前端通过 Tauri 检测到剪贴板变化时调本路由（备用通道）。

    主路径是后端 NSPasteboard 1Hz 轮询（``backend.integrations.clipboard``
    的后台 task），这条路由仅在以下场景用：
      - 后端 polling 失败 / 跨平台 pyperclip 不可用
      - 前端 Tauri 想 push 比 1Hz 更敏感的捕获
    内容长度限制 100KB（避免大 base64 图片），超长截断。
    """
    text = (body.content or "")[:100_000]
    if not text.strip():
        raise HTTPException(status_code=400, detail="empty content")
    try:
        from backend.integrations.clipboard import clipboard_watcher
        clipboard_watcher.add_item(text, content_type=body.content_type)
    except Exception as exc:
        logger.exception("[clipboard/captured] add_item failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"ok": True, "size": len(text)}
