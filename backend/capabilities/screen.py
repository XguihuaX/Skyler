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
from typing import Optional

from backend.capabilities import Consumer, TriggerMode, register_capability
from backend.integrations import activity_monitor as _am
from backend.integrations import url_fetcher as _uf

logger = logging.getLogger(__name__)


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
