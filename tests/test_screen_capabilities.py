"""v3.5 chunk 8a commit 2 — screen capabilities 单测。

走两条路径：

1. 直接调 handler（验业务逻辑 + activity_monitor mock）
2. 走 ``ToolRegistry.call(name, **kwargs)``（验真注册 + 真 dispatch；
   对齐 chunk 6b hotfix-2 教训：runtime call 比单元函数更能 catch 注册问题）
"""
from __future__ import annotations

import os
import sys
from unittest.mock import patch, AsyncMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 触发 capability 注册（decorator 副作用）
import backend.capabilities.screen  # noqa: F401
from backend.capabilities import screen as scr_mod  # 直接调 handler 路径
from backend.tools.registry import ToolRegistry


# ---------------------------------------------------------------------------
# 1. screen.get_active_app
# ---------------------------------------------------------------------------


async def test_get_active_app_available() -> None:
    with patch.object(scr_mod._am, "get_active_app", return_value="Visual Studio Code"):
        r = await scr_mod.get_active_app()
    assert r == {"app": "Visual Studio Code", "available": True}


async def test_get_active_app_unavailable() -> None:
    with patch.object(scr_mod._am, "get_active_app", return_value=None):
        r = await scr_mod.get_active_app()
    assert r == {"app": None, "available": False}


async def test_get_active_app_via_tool_registry() -> None:
    """走 ToolRegistry.call 路径，对齐 hotfix-2。"""
    with patch.object(scr_mod._am, "get_active_app", return_value="Chrome"):
        r = await ToolRegistry.call("screen.get_active_app")
    assert r["app"] == "Chrome"
    assert r["available"] is True


# ---------------------------------------------------------------------------
# 2. screen.get_browser_url
# ---------------------------------------------------------------------------


async def test_get_browser_url_chrome_preferred() -> None:
    with patch.object(scr_mod._am, "get_chrome_active_tab",
                      return_value=("https://github.com", "GitHub")), \
         patch.object(scr_mod._am, "get_safari_active_tab",
                      return_value=("https://apple.com", "Apple")):
        r = await scr_mod.get_browser_url()
    # Chrome 优先（Safari 不应被调）
    assert r == {
        "browser": "chrome",
        "url": "https://github.com",
        "title": "GitHub",
        "available": True,
    }


async def test_get_browser_url_safari_fallback() -> None:
    with patch.object(scr_mod._am, "get_chrome_active_tab", return_value=None), \
         patch.object(scr_mod._am, "get_safari_active_tab",
                      return_value=("https://apple.com", "Apple")):
        r = await scr_mod.get_browser_url()
    assert r["browser"] == "safari"
    assert r["url"] == "https://apple.com"


async def test_get_browser_url_none_available() -> None:
    with patch.object(scr_mod._am, "get_chrome_active_tab", return_value=None), \
         patch.object(scr_mod._am, "get_safari_active_tab", return_value=None):
        r = await scr_mod.get_browser_url()
    assert r == {"browser": None, "available": False}


async def test_get_browser_url_via_tool_registry() -> None:
    with patch.object(scr_mod._am, "get_chrome_active_tab",
                      return_value=("https://x.com", "X")), \
         patch.object(scr_mod._am, "get_safari_active_tab", return_value=None):
        r = await ToolRegistry.call("screen.get_browser_url")
    assert r["browser"] == "chrome"


# ---------------------------------------------------------------------------
# 3. screen.get_browser_content
# ---------------------------------------------------------------------------


async def test_get_browser_content_no_browser() -> None:
    with patch.object(scr_mod._am, "get_chrome_active_tab", return_value=None), \
         patch.object(scr_mod._am, "get_safari_active_tab", return_value=None):
        r = await scr_mod.get_browser_content()
    assert r == {"fetched": False, "reason": "no_browser", "browser": None}


async def test_get_browser_content_fetches_chrome_url() -> None:
    mocked = AsyncMock(return_value={
        "fetched": True,
        "url": "https://docs.python.org/3/",
        "title": "Python 3 docs",
        "content": "Welcome to the Python 3 documentation",
        "status": "ok",
    })
    with patch.object(scr_mod._am, "get_chrome_active_tab",
                      return_value=("https://docs.python.org/3/", "Python Docs")), \
         patch.object(scr_mod._uf, "fetch_article_content", mocked):
        r = await scr_mod.get_browser_content(max_chars=2000)
    assert r["fetched"] is True
    assert r["browser"] == "chrome"
    assert r["content"].startswith("Welcome to")
    # max_chars 被透传
    mocked.assert_awaited_once()
    kwargs = mocked.await_args.kwargs
    assert kwargs.get("max_chars") == 2000


async def test_get_browser_content_blocked_returns_reason() -> None:
    mocked = AsyncMock(return_value={
        "fetched": False, "url": "https://mail.google.com",
        "reason": "blocked",
    })
    with patch.object(scr_mod._am, "get_chrome_active_tab",
                      return_value=("https://mail.google.com", "Gmail")), \
         patch.object(scr_mod._uf, "fetch_article_content", mocked):
        r = await scr_mod.get_browser_content()
    assert r["fetched"] is False
    assert r["reason"] == "blocked"
    assert r["browser"] == "chrome"


async def test_get_browser_content_title_fallback() -> None:
    """fetch 返空 title → 用 browser tab 的 title 兜底。"""
    mocked = AsyncMock(return_value={
        "fetched": True, "url": "https://e.com", "title": "", "content": "body",
        "status": "ok",
    })
    with patch.object(scr_mod._am, "get_chrome_active_tab",
                      return_value=("https://e.com", "Tab Title")), \
         patch.object(scr_mod._uf, "fetch_article_content", mocked):
        r = await scr_mod.get_browser_content()
    assert r["title"] == "Tab Title"


async def test_get_browser_content_via_tool_registry() -> None:
    mocked = AsyncMock(return_value={
        "fetched": True, "url": "https://e.com", "title": "T", "content": "B",
        "status": "ok",
    })
    with patch.object(scr_mod._am, "get_chrome_active_tab",
                      return_value=("https://e.com", "T")), \
         patch.object(scr_mod._uf, "fetch_article_content", mocked):
        r = await ToolRegistry.call("screen.get_browser_content")
    assert r["fetched"] is True


# ---------------------------------------------------------------------------
# 4. screen.get_active_document
# ---------------------------------------------------------------------------


async def test_get_active_document_none() -> None:
    with patch.object(scr_mod._am, "get_active_document_path", return_value=None):
        r = await scr_mod.get_active_document()
    assert r == {"path": None, "available": False}


async def test_get_active_document_pages() -> None:
    with patch.object(scr_mod._am, "get_active_document_path",
                      return_value=("/Users/me/draft.pages", "pages")):
        r = await scr_mod.get_active_document()
    assert r["path"] == "/Users/me/draft.pages"
    assert r["type"] == "pages"
    assert r["available"] is True
    assert r["basename"] == "draft.pages"


async def test_get_active_document_docx_in_sandbox() -> None:
    sandbox = os.path.expanduser("~/Documents/Skyler/docs")
    path = os.path.join(sandbox, "report.docx")
    with patch.object(scr_mod._am, "get_active_document_path",
                      return_value=(path, "word")):
        r = await scr_mod.get_active_document()
    assert r["readable_via"] == "docx.read"
    assert r["sandbox_relative"] == "report.docx"


async def test_get_active_document_docx_out_of_sandbox() -> None:
    with patch.object(scr_mod._am, "get_active_document_path",
                      return_value=("/Users/me/elsewhere/x.docx", "word")):
        r = await scr_mod.get_active_document()
    assert r["readable_via"] is None
    assert "note" in r


async def test_get_active_document_via_tool_registry() -> None:
    with patch.object(scr_mod._am, "get_active_document_path",
                      return_value=("/Users/me/x.pages", "pages")):
        r = await ToolRegistry.call("screen.get_active_document")
    assert r["type"] == "pages"


# ---------------------------------------------------------------------------
# CapabilityRegistry registration smoke
# ---------------------------------------------------------------------------


def test_all_four_capabilities_registered() -> None:
    from backend.capabilities import CapabilityRegistry
    reg = CapabilityRegistry()
    names = {c.name for c in reg.list_all()}
    for needed in (
        "screen.get_active_app",
        "screen.get_browser_url",
        "screen.get_browser_content",
        "screen.get_active_document",
    ):
        assert needed in names, f"capability {needed} not registered"
