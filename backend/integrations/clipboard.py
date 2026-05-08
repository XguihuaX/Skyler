"""v3-G chunk 3a — 剪贴板助手低层 client。

设计要点
========

* **macOS 主路径**：``AppKit.NSPasteboard`` 直接读（pyobjc 已是 EventKit
  transitive 依赖，无需新装）。每次轮询比对 ``changeCount``；变化时取新内容。
* **跨平台 fallback**：``pyperclip`` ——简单 polling，无 changeCount 概念，
  比对 last_text 快路径就够用。Linux X11 / Wayland 自带 pyperclip backend
  自动检测。
* **不调 LLM**：本 module 是纯数据层，决定不在这里做翻译 / 总结。capability
  层 ``backend.capabilities.clipboard`` 才调 LLM。
* **不自动响应**：spec 关键设计原则——"用户只想 Momo 在被问到时回应，自动
  评论会烦人"。本 module 仅捕获 + 提供查询 API；何时使用由 ChatAgent
  按用户意图决定。
* **Ringbuffer + TTL**：内存最近 50 条，TTL 24h。重启即清空（**不持久化**：
  剪贴板内容隐私敏感，不进 SQLite，也不外传）。

content_type 启发式
====================

简单规则，基于 content 字符串本体：
  1. 以 ``http://`` / ``https://`` 开头 → ``url``
  2. 以 ``{`` 起且以 ``}`` 终（trim 后）→ ``json``
  3. 含 ```` ``` ```` / ``    `` 缩进 / 关键词（def / class / function / import /
     ``=>``）→ ``code``
  4. 含 markdown 标记（``# `` 行首 / ``[...](`` / ``- `` / ``> ``）→ ``markdown``
  5. 否则 → ``plain_text``

不做 ML / 模型识别——成本不值，规则糙够用。

Public API
==========

* ``clipboard_watcher`` 单例 ``ClipboardWatcher``
* ``ClipboardWatcher.add_item(content, content_type=None)`` ——手动 push
  （前端 Tauri ``POST /api/clipboard/captured`` 路径调）
* ``ClipboardWatcher.get_recent(n=5)`` ——拿最近 N 条
* ``ClipboardWatcher.start_polling()`` / ``stop_polling()``
* ``IS_MACOS`` / ``IS_PYPERCLIP_AVAILABLE`` 平台 flag
"""
from __future__ import annotations

import asyncio
import logging
import re
import sys
import time
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Deque, List, Optional

logger = logging.getLogger(__name__)

IS_MACOS = sys.platform == "darwin"

# pyperclip 是 cross-platform fallback；macOS 也可用，但 NSPasteboard 走
# changeCount 更精准（不用 last_text 比对）。
try:
    import pyperclip as _pyperclip  # noqa: F401
    IS_PYPERCLIP_AVAILABLE = True
except Exception:
    IS_PYPERCLIP_AVAILABLE = False

# AppKit/NSPasteboard 仅 macOS 有；非 macOS import 失败是正常 fallback path。
_NSPasteboard = None
if IS_MACOS:
    try:
        from AppKit import NSPasteboard  # type: ignore
        _NSPasteboard = NSPasteboard
    except Exception as exc:
        logger.warning("[clipboard] AppKit.NSPasteboard import failed: %s", exc)


# Ringbuffer 容量 + TTL —— 走代码常量（spec：如需调整再独立 chunk）
_MAX_ITEMS = 50
_TTL_SECONDS = 24 * 3600
_POLL_INTERVAL_SECONDS = 1.0


@dataclass
class ClipboardItem:
    content: str
    content_type: str       # 'url' / 'code' / 'plain_text' / 'markdown' / 'json'
    captured_at: float      # epoch seconds
    captured_iso: str       # 友好时间戳；前端直接显示

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# content_type 启发式
# ---------------------------------------------------------------------------

_URL_RE = re.compile(r"^https?://", re.IGNORECASE)
_CODE_KEYWORDS = ("def ", "class ", "function ", "import ", "const ", "let ",
                  "var ", "return ", "=>", "#include", "package ")
_MD_PATTERNS = (re.compile(r"^#{1,6}\s", re.MULTILINE),
                re.compile(r"\[.+?\]\(.+?\)"),
                re.compile(r"^\s*[-*+]\s", re.MULTILINE),
                re.compile(r"^\s*>\s", re.MULTILINE))


def detect_content_type(text: str) -> str:
    if not isinstance(text, str) or not text.strip():
        return "plain_text"
    stripped = text.strip()

    if _URL_RE.match(stripped) and "\n" not in stripped[:80]:
        return "url"

    if stripped.startswith("{") and stripped.endswith("}"):
        try:
            import json as _json
            _json.loads(stripped)
            return "json"
        except Exception:
            pass

    if "```" in text or any(kw in text for kw in _CODE_KEYWORDS):
        return "code"
    # 简单缩进启发式：连续 2 行以 4 空格 / tab 起
    indented = sum(1 for ln in text.splitlines() if ln.startswith(("    ", "\t")))
    if indented >= 2:
        return "code"

    for pat in _MD_PATTERNS:
        if pat.search(text):
            return "markdown"

    return "plain_text"


# ---------------------------------------------------------------------------
# ClipboardWatcher
# ---------------------------------------------------------------------------

class ClipboardWatcher:
    """单例。``start_polling`` 启动后台 task；``add_item`` 也可手动 push。"""

    def __init__(self) -> None:
        self._buf: Deque[ClipboardItem] = deque(maxlen=_MAX_ITEMS)
        self._last_text: Optional[str] = None
        self._last_change_count: int = -1
        self._task: Optional[asyncio.Task] = None
        self._enabled: bool = True

    # -------------------------------- write paths

    def add_item(self, content: str, content_type: Optional[str] = None) -> Optional[ClipboardItem]:
        """新增一条到 ringbuffer。重复 last_text 时跳过（去抖）。空字符串跳过。"""
        if not isinstance(content, str):
            return None
        text = content.strip()
        if not text:
            return None
        if self._last_text == text:
            return None
        self._last_text = text
        ctype = content_type if content_type in {"url", "code", "plain_text", "markdown", "json"} \
            else detect_content_type(text)
        item = ClipboardItem(
            content=text,
            content_type=ctype,
            captured_at=time.time(),
            captured_iso=datetime.now().isoformat(timespec="seconds"),
        )
        self._buf.append(item)
        logger.info(
            "[clipboard] captured: type=%s len=%d preview=%r",
            ctype, len(text), text[:30],
        )
        return item

    # -------------------------------- read paths

    def get_recent(self, n: int = 5) -> List[ClipboardItem]:
        """拿最近 n 条（最新在前）。同时清掉超 TTL 的老记录。"""
        self._evict_expired()
        n = max(1, min(int(n), _MAX_ITEMS))
        items = list(self._buf)[-n:]
        return list(reversed(items))

    def get_all(self) -> List[ClipboardItem]:
        self._evict_expired()
        return list(reversed(self._buf))

    def clear_one(self, captured_at: float) -> bool:
        """按 captured_at 删一条。前端单条删除按钮调。"""
        for i, item in enumerate(self._buf):
            if abs(item.captured_at - captured_at) < 1e-3:
                del self._buf[i]
                return True
        return False

    def clear_all(self) -> int:
        n = len(self._buf)
        self._buf.clear()
        self._last_text = None
        return n

    def _evict_expired(self) -> None:
        now = time.time()
        while self._buf and (now - self._buf[0].captured_at) > _TTL_SECONDS:
            self._buf.popleft()

    # -------------------------------- polling lifecycle

    def set_enabled(self, enabled: bool) -> None:
        """前端 [捕获剪贴板] 开关用。disabled 时停 polling，但保留已捕获条目。"""
        self._enabled = bool(enabled)

    async def _poll_loop(self) -> None:
        """1Hz 轮询。macOS 走 changeCount；其他平台 / fallback 走 last_text 比对。"""
        logger.info(
            "[clipboard] poll loop start (macos=%s, pyperclip=%s)",
            IS_MACOS, IS_PYPERCLIP_AVAILABLE,
        )
        while True:
            try:
                if self._enabled:
                    await self._poll_once()
            except asyncio.CancelledError:
                logger.info("[clipboard] poll loop cancelled")
                raise
            except Exception:
                logger.exception("[clipboard] poll iteration failed; continuing")
            await asyncio.sleep(_POLL_INTERVAL_SECONDS)

    async def _poll_once(self) -> None:
        text: Optional[str] = None
        if _NSPasteboard is not None:
            pb = _NSPasteboard.generalPasteboard()
            change_count = int(pb.changeCount())
            if change_count == self._last_change_count:
                return
            self._last_change_count = change_count
            ns_str = pb.stringForType_("public.utf8-plain-text")
            if ns_str is not None:
                text = str(ns_str)
        elif IS_PYPERCLIP_AVAILABLE:
            try:
                text = _pyperclip.paste()
            except Exception:
                return
        if text:
            await asyncio.to_thread(self.add_item, text)

    def start_polling(self) -> None:
        if self._task is not None and not self._task.done():
            return
        if _NSPasteboard is None and not IS_PYPERCLIP_AVAILABLE:
            logger.warning(
                "[clipboard] no backend available (NSPasteboard / pyperclip 都缺)；"
                "polling disabled. POST /api/clipboard/captured 路径仍可用。"
            )
            return
        loop = asyncio.get_event_loop()
        self._task = loop.create_task(self._poll_loop())
        logger.info("[clipboard] polling task spawned")

    async def stop_polling(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except (asyncio.CancelledError, Exception):
            pass
        self._task = None


# 单例
clipboard_watcher = ClipboardWatcher()


__all__ = [
    "ClipboardItem",
    "ClipboardWatcher",
    "clipboard_watcher",
    "detect_content_type",
    "IS_MACOS",
    "IS_PYPERCLIP_AVAILABLE",
]
