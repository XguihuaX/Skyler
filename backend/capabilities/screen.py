"""v3.5 chunk 8a — 屏幕 / 活动感知 capability。

四个 CHAT_AGENT consumer capability，让 LLM 在用户问"你看到我在干嘛"时
按需查当前状态：

* ``screen.get_active_app``      返当前 frontmost app
* ``screen.get_browser_url``     返 Chrome / Safari active tab url + title
* ``screen.get_browser_content`` URL 公开页面正文 fetch（走黑名单 + readability）
* ``screen.get_active_document`` 当前 Word / Pages 文档路径（.docx 走
  chunk 7 docx.read 提内容）

设计原则
========

* **不自动响应**：与 chunk 3a clipboard 同原则——capability 注册让 LLM
  在用户明确询问时调；ActivityWatcher（commit 4-5）才是周期 sniff +
  trigger 决策的入口
* **silent degradation**：activity_monitor 失败 / 非 macOS → 返
  ``{app: null, available: false}`` 让 LLM 看到"我没看到任何"自然回应；
  绝不抛错给 ChatAgent
* **黑名单 + content 长度**：``get_browser_content`` 内部直接走 url_fetcher
  默认黑名单 + 默认 max_chars=5000；调用方按返回 ``status``/``reason``
  字段判断而非异常
"""
from __future__ import annotations

import logging
import os
import re
from typing import Optional

from backend.capabilities import Consumer, TriggerMode, register_capability
from backend.integrations import activity_monitor as _am
from backend.integrations import url_fetcher as _uf
from backend.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

# 2026-06-21 · 屏幕读取 MVP · macos-use refresh_traversal 在 ToolRegistry 里的
# 注册名(见 backend/mcp/client.py:473 `cap_name = f"ext.{handle.name}.{tool.name}"`)。
# macos-use server 暴露的 tool 名自带 "macos-use_" 前缀,所以双前缀是预期。
_MACOS_USE_REFRESH_TOOL = "ext.macos-use.macos-use_refresh_traversal"

# refresh_traversal 返的文本里夹的 .txt 文件路径 · 用来提 AX 摘要正文。
# 例:"AX summary written to /tmp/macos-use_20260621_120000.txt"
_TMP_PATH_RE = re.compile(r"(/[A-Za-z0-9_/.\-]+\.txt)")

# 一次注入给 LLM 的 AX 摘要上限(字符)· 超出截断 + 标 truncated=true
# 5000 字够回答 90% "屏幕上有啥" 类问题 · 完整文件留 source_path 给后续 grep 链
_MAX_AX_CHARS = 5000


# ---------------------------------------------------------------------------
# 1. screen.get_active_app
# ---------------------------------------------------------------------------


@register_capability(
    name="screen.get_active_app",
    display_name="当前活跃 app",
    description=(
        "查当前 macOS frontmost 应用名（如 'Visual Studio Code' / 'Google Chrome' / "
        "'Spotify'）。当用户问「我现在用啥」「我在哪儿」「猜猜我在做什么」时调用。"
        "非 macOS / 无活跃 app → ``{app: null, available: false}``。不要在用户没问"
        "起时主动调，那是 ActivityWatcher 的职责。"
    ),
    category="screen",
    consumers=[Consumer.CHAT_AGENT],
    trigger_modes=[TriggerMode.ON_DEMAND],
    icon="monitor",
    parameters_schema={"type": "object", "properties": {}, "required": []},
)
async def get_active_app(**_kwargs) -> dict:
    name = _am.get_active_app()
    if name is None:
        return {"app": None, "available": False}
    return {"app": name, "available": True}


# ---------------------------------------------------------------------------
# 2. screen.get_browser_url
# ---------------------------------------------------------------------------


@register_capability(
    name="screen.get_browser_url",
    display_name="浏览器当前 tab",
    description=(
        "查用户当前在看的浏览器 tab URL + 标题（Chrome / Safari）。**仅在浏览器是"
        "macOS frontmost 应用时返回**——浏览器在后台时返 ``{browser: null, "
        "available: false}``（hotfix-9：不再泄露后台 Chrome 的 active tab）。"
        "用户问「我在看啥网页」「这页是什么」时调。不要主动连续调，先走 ActivityWatcher。"
    ),
    category="screen",
    consumers=[Consumer.CHAT_AGENT],
    trigger_modes=[TriggerMode.ON_DEMAND],
    icon="globe",
    parameters_schema={"type": "object", "properties": {}, "required": []},
)
async def get_browser_url(**_kwargs) -> dict:
    info = _am.get_browser_url()
    if info is None:
        return {"browser": None, "available": False}
    browser, url, title = info
    return {"browser": browser, "url": url, "title": title, "available": True}


# ---------------------------------------------------------------------------
# 3. screen.get_browser_content
# ---------------------------------------------------------------------------


@register_capability(
    name="screen.get_browser_content",
    display_name="浏览器当前页面正文",
    description=(
        "查用户当前浏览器 active tab 的 URL，并 fetch 公开页面正文给你看。"
        "成功时返 ``{fetched: true, url, title, content}``；黑名单（银行/邮箱/社交"
        "/localhost）/ 需登录 / 超时 / 反爬 / 非 HTML → ``{fetched: false, reason: "
        "...}``。用户问「这页讲啥」「帮我总结这文章」时调；老实告诉用户没读到的原因，"
        "不要瞎编。"
    ),
    category="screen",
    consumers=[Consumer.CHAT_AGENT],
    trigger_modes=[TriggerMode.ON_DEMAND],
    icon="book-open",
    parameters_schema={
        "type": "object",
        "properties": {
            "max_chars": {
                "type": "integer", "minimum": 200, "maximum": 20000, "default": 5000,
                "description": "正文截断长度（默认 5000；超过加 …）",
            },
        },
        "required": [],
    },
)
async def get_browser_content(max_chars: int = 5000, **_kwargs) -> dict:
    # 先拿 URL（hotfix-9: frontmost-gated, 浏览器在后台时返 None）
    info = _am.get_browser_url()
    if info is None:
        return {"fetched": False, "reason": "no_browser", "browser": None}
    browser, url, title = info

    if not url or not url.lower().startswith(("http://", "https://")):
        return {"fetched": False, "reason": "invalid_url", "browser": browser,
                "url": url, "title": title}

    result = await _uf.fetch_article_content(url, max_chars=int(max_chars))
    if result is None:  # pragma: no cover - 当前 fetch 总返 dict
        return {"fetched": False, "reason": "unknown", "browser": browser,
                "url": url, "title": title}
    result["browser"] = browser
    # 用浏览器 tab 的 title 兜底 readability 抓不到的情况
    if not result.get("title"):
        result["title"] = title
    return result


# ---------------------------------------------------------------------------
# 4. screen.get_active_document
# ---------------------------------------------------------------------------


@register_capability(
    name="screen.get_active_document",
    display_name="当前文档",
    description=(
        "查 macOS 当前 frontmost 的 Word / Pages 文档路径。.docx 文档自动走 chunk 7 "
        "``docx.read`` 提内容；.pages 文档只返 path（Pages 无开放读取接口）。"
        "无活跃文档 / 非 macOS → ``{path: null, available: false}``。"
        "用户问「我现在写的这份是啥」「读一下我打开的文档」时调。"
    ),
    category="screen",
    consumers=[Consumer.CHAT_AGENT],
    trigger_modes=[TriggerMode.ON_DEMAND],
    icon="file-text",
    parameters_schema={"type": "object", "properties": {}, "required": []},
)
async def get_active_document(**_kwargs) -> dict:
    info = _am.get_active_document_path()
    if info is None:
        return {"path": None, "available": False}
    path, kind = info

    result: dict = {
        "path": path,
        "type": kind,
        "available": True,
        # filename hint：LLM 可以串调 ``docx.read`` 读 sandbox 内的 .docx（chunk 7）
        "basename": os.path.basename(path),
    }

    # 暴露"是否可走 docx.read 读内容"提示：sandbox 内 .docx 才可读，越界由
    # docx.read 自身的 safe_resolve 拦下（不在本 capability 里复杂化逻辑）。
    if kind == "word" and path.lower().endswith(".docx"):
        sandbox_root = os.path.expanduser("~/Documents/Skyler/docs")
        try:
            rel = os.path.relpath(path, sandbox_root)
            in_sandbox = not rel.startswith("..") and not os.path.isabs(rel)
        except ValueError:
            in_sandbox = False
        if in_sandbox:
            result["readable_via"] = "docx.read"
            result["sandbox_relative"] = rel
        else:
            result["readable_via"] = None
            result["note"] = (
                "Word 文档不在 docx 沙箱内（~/Documents/Skyler/docs/），"
                "需要用户主动把文件挪进去后才能调 docx.read 读内容"
            )

    return result


# ---------------------------------------------------------------------------
# 5. screen.read_current_screen (2026-06-21 · 屏幕读取 MVP)
#
# Wrapper:内部解析"非 Skyler" frontmost PID + 调 macos-use refresh_traversal
# + 直接读 .txt 内容截 5000 字返给 LLM。LLM 视角是单步调用、零参数。
#
# 设计原则:
#   - **只读**:不调任何带写动作的 macos-use tool
#   - **Skyler 自己 frontmost** → 返 self_frontmost · 让 LLM 提示用户切窗口
#     (单 frontmost 查询不假装"次 frontmost",那个 osascript 不可靠)
#   - **macos-use 未启用** → 返 macos_use_not_enabled · 让 LLM 引导去 UI 启用
#   - 全异常路径返 ``{available: False, reason, message}`` · 绝不抛
# ---------------------------------------------------------------------------


@register_capability(
    name="screen.read_current_screen",
    display_name="读当前屏幕(AX)",
    description=(
        "读用户当前在看的 macOS 窗口的 accessibility 树(AX)摘要,返回前 5000 "
        "字给你回答\"屏幕里有什么\"类问题。**无需参数** —— 内部自动找当前 "
        "frontmost 应用 PID(排除 Skyler 自己)再调 macos-use refresh_traversal。"
        "Skyler 自己在前台 → 返 ``{available: false, reason: \"self_frontmost\"}``,"
        "让用户先把目标应用切到前台。macos-use 未启用 → 返 ``{available: false, "
        "reason: \"macos_use_not_enabled\"}``,引导用户去 Capabilities → MCP "
        "Servers 启用。**只读**,绝不调写/点击/输入类工具。"
    ),
    category="screen",
    consumers=[Consumer.CHAT_AGENT],
    trigger_modes=[TriggerMode.ON_DEMAND],
    icon="scan-eye",
    parameters_schema={"type": "object", "properties": {}, "required": []},
)
async def read_current_screen(**_kwargs) -> dict:
    # 1. 拿 frontmost (name, pid)
    info = _am.get_frontmost_app_with_pid()
    if info is None:
        return {
            "available": False,
            "reason": "no_frontmost",
            "message": "没拿到当前 frontmost 应用(非 macOS / osascript 失败)",
        }
    name, pid = info

    # 2. Skyler 自己在前台 → 不假装能看到"用户身后那个"
    if name == _am.SKYLER_BUNDLE_NAME:
        return {
            "available": False,
            "reason": "self_frontmost",
            "frontmost_app": name,
            "message": (
                "Skyler 自己在前台 · 请把你想让我看的应用切到前台后再问一次 "
                "(Cmd+Tab / 点对应窗口)"
            ),
        }

    # 3. 调 macos-use refresh_traversal(pid=...)
    try:
        result = await ToolRegistry.call(_MACOS_USE_REFRESH_TOOL, pid=pid)
    except KeyError:
        return {
            "available": False,
            "reason": "macos_use_not_enabled",
            "frontmost_app": name,
            "pid": pid,
            "message": (
                "屏幕读取依赖的 macos-use MCP server 当前未启用 · 用户可在 "
                "Capabilities → MCP Servers 里启用 'macos-use'"
            ),
        }
    except Exception as exc:  # noqa: BLE001 - 兜底任何运行时错
        logger.warning(
            "[screen.read_current_screen] refresh_traversal raise: %s", exc,
        )
        return {
            "available": False,
            "reason": "traversal_error",
            "frontmost_app": name,
            "pid": pid,
            "message": f"AX 树读取失败:{exc}",
        }

    # 4. result = {"isError": bool, "text": str} | {"isError": bool, "content": list}
    if not isinstance(result, dict) or result.get("isError"):
        return {
            "available": False,
            "reason": "traversal_failed",
            "frontmost_app": name,
            "pid": pid,
            "raw": result if isinstance(result, dict) else str(result),
            "message": "macos-use refresh_traversal 返错(可能 PID 已退出或无 AX 权限)",
        }
    text_payload = result.get("text") or ""
    if not text_payload:
        return {
            "available": False,
            "reason": "empty_payload",
            "frontmost_app": name,
            "pid": pid,
            "message": "AX 摘要返回空 · 应用可能没暴露 accessibility 树",
        }

    # 5. 从返回文本里提 /tmp/xxx.txt 路径 · 读前 5000 字
    path_match = _TMP_PATH_RE.search(text_payload)
    if path_match is None:
        # 没匹到路径就直接把 server 返的 text 当摘要返(防御 · 不崩)
        return {
            "available": True,
            "frontmost_app": name,
            "pid": pid,
            "summary": text_payload[:_MAX_AX_CHARS],
            "truncated": len(text_payload) > _MAX_AX_CHARS,
            "source_path": None,
            "note": "未在 server 返回中找到 .txt 路径 · 用 text payload 直显",
        }
    source_path = path_match.group(1)
    try:
        with open(source_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read(_MAX_AX_CHARS + 1)
    except FileNotFoundError:
        return {
            "available": False,
            "reason": "ax_file_missing",
            "frontmost_app": name,
            "pid": pid,
            "source_path": source_path,
            "message": "AX 摘要 .txt 不存在(可能 /tmp 已被清)",
        }
    except OSError as exc:
        return {
            "available": False,
            "reason": "ax_file_read_error",
            "frontmost_app": name,
            "pid": pid,
            "source_path": source_path,
            "message": f"AX 摘要 .txt 读失败:{exc}",
        }

    truncated = len(content) > _MAX_AX_CHARS
    if truncated:
        content = content[:_MAX_AX_CHARS]
    return {
        "available": True,
        "frontmost_app": name,
        "pid": pid,
        "summary": content,
        "truncated": truncated,
        "source_path": source_path,
    }
