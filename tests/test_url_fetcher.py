"""v3.5 chunk 8a commit 3 — url_fetcher 单元测试。

不联网。用 httpx MockTransport 喂预设响应跑完整路径：成功 / blocked /
timeout / 401 / 412 / 非 HTML / max_chars 截断 / readability 提取。
"""
from __future__ import annotations

import os
import sys
from unittest.mock import patch

import httpx
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.integrations import url_fetcher as uf


# ---------------------------------------------------------------------------
# is_url_blocked
# ---------------------------------------------------------------------------


def test_is_url_blocked_matches_default_patterns() -> None:
    assert uf.is_url_blocked(
        "https://mail.google.com/u/0/#inbox",
        uf.DEFAULT_BLOCKED_PATTERNS,
    )
    assert uf.is_url_blocked(
        "http://localhost:8000/api/test",
        uf.DEFAULT_BLOCKED_PATTERNS,
    )
    assert uf.is_url_blocked(
        "https://x.com/skyler",
        uf.DEFAULT_BLOCKED_PATTERNS,
    )
    assert not uf.is_url_blocked(
        "https://github.com/skyler/skyler",
        uf.DEFAULT_BLOCKED_PATTERNS,
    )


def test_is_url_blocked_custom_pattern() -> None:
    assert uf.is_url_blocked(
        "https://internal.corp/secret",
        ["*internal.corp*"],
    )


# ---------------------------------------------------------------------------
# fetch_article_content with MockTransport
# ---------------------------------------------------------------------------


_REAL_ASYNCCLIENT = httpx.AsyncClient  # 保留原始 ref 防 patch 递归


def _client_factory(handler):
    """Return a constructor that the patched httpx.AsyncClient name binds to.

    Inside fetch_article_content the code does ``httpx.AsyncClient(timeout=...,
    follow_redirects=..., ...)``；我们让 patched constructor 忽略业务参数，
    直接交 MockTransport handler 接管。
    """
    def _ctor(*_args, **_kwargs):
        return _REAL_ASYNCCLIENT(transport=httpx.MockTransport(handler))
    return _ctor


async def test_fetch_invalid_url() -> None:
    r = await uf.fetch_article_content("not-a-url")
    assert r == {"fetched": False, "url": "not-a-url", "reason": "invalid_url"}


async def test_fetch_blocked_pattern_skips_request() -> None:
    """blocked URL 不应发请求；返 reason='blocked'。"""
    called = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        called["n"] += 1
        return httpx.Response(200, text="x")

    with patch("backend.integrations.url_fetcher.httpx.AsyncClient",
               _client_factory(handler)):
        r = await uf.fetch_article_content("https://mail.google.com/inbox")
    assert r["fetched"] is False
    assert r["reason"] == "blocked"
    assert called["n"] == 0


async def test_fetch_ok_extracts_title_and_content() -> None:
    html = """
    <!DOCTYPE html><html><head><title>My Article</title></head>
    <body><article>
      <h1>Welcome</h1>
      <p>This is a long enough paragraph for readability to keep it intact and
      that will be extracted out clean.</p>
      <p>Second paragraph with even more substantive content. Lorem ipsum dolor
      sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt
      ut labore et dolore magna aliqua.</p>
    </article></body></html>
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text=html,
            headers={"content-type": "text/html; charset=utf-8"},
        )

    with patch("backend.integrations.url_fetcher.httpx.AsyncClient",
               _client_factory(handler)):
        r = await uf.fetch_article_content(
            "https://example.com/a", blocked_patterns=[],
        )
    assert r["fetched"] is True
    assert r["status"] == "ok"
    assert r["url"] == "https://example.com/a"
    assert "Welcome" in r["content"] or "long enough paragraph" in r["content"]
    # Title 抓到（readability short_title 或 _extract_title_from_html）
    assert r["title"]


async def test_fetch_max_chars_truncates() -> None:
    long_text = "<html><body><article><p>" + ("ABCDE " * 2000) + "</p></article></body></html>"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=long_text,
                              headers={"content-type": "text/html"})

    with patch("backend.integrations.url_fetcher.httpx.AsyncClient",
               _client_factory(handler)):
        r = await uf.fetch_article_content(
            "https://example.com/long", blocked_patterns=[], max_chars=100,
        )
    assert r["fetched"] is True
    # max_chars=100 + 末尾追加 "…" → ≤ 101
    assert len(r["content"]) <= 101
    assert r["content"].endswith("…")


async def test_fetch_timeout_returns_reason() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("boom", request=request)

    with patch("backend.integrations.url_fetcher.httpx.AsyncClient",
               _client_factory(handler)):
        r = await uf.fetch_article_content(
            "https://example.com/slow", blocked_patterns=[],
        )
    assert r == {"fetched": False, "url": "https://example.com/slow",
                 "reason": "timeout"}


async def test_fetch_request_error_returns_reason() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    with patch("backend.integrations.url_fetcher.httpx.AsyncClient",
               _client_factory(handler)):
        r = await uf.fetch_article_content(
            "https://example.com/", blocked_patterns=[],
        )
    assert r["fetched"] is False
    assert r["reason"] == "request_error"


async def test_fetch_401_login_required() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="<html>nope</html>",
                              headers={"content-type": "text/html"})

    with patch("backend.integrations.url_fetcher.httpx.AsyncClient",
               _client_factory(handler)):
        r = await uf.fetch_article_content(
            "https://example.com/", blocked_patterns=[],
        )
    assert r["fetched"] is False
    assert r["reason"] == "login_required"
    assert r["http_status"] == 401


async def test_fetch_429_antibot() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="rate limited",
                              headers={"content-type": "text/html"})

    with patch("backend.integrations.url_fetcher.httpx.AsyncClient",
               _client_factory(handler)):
        r = await uf.fetch_article_content(
            "https://example.com/", blocked_patterns=[],
        )
    assert r["fetched"] is False
    assert r["reason"] == "blocked_by_antibot"
    assert r["http_status"] == 429


async def test_fetch_non_html_skipped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"pdf bytes",
                              headers={"content-type": "application/pdf"})

    with patch("backend.integrations.url_fetcher.httpx.AsyncClient",
               _client_factory(handler)):
        r = await uf.fetch_article_content(
            "https://example.com/doc.pdf", blocked_patterns=[],
        )
    assert r["fetched"] is False
    assert r["reason"] == "non_html"


async def test_fetch_empty_body_returns_reason() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html><body></body></html>",
                              headers={"content-type": "text/html"})

    with patch("backend.integrations.url_fetcher.httpx.AsyncClient",
               _client_factory(handler)):
        r = await uf.fetch_article_content(
            "https://example.com/", blocked_patterns=[],
        )
    assert r["fetched"] is False
    assert r["reason"] == "empty_body"


# ---------------------------------------------------------------------------
# Title extraction fallback
# ---------------------------------------------------------------------------


def test_extract_title_basic() -> None:
    assert uf._extract_title_from_html(
        "<html><head><title>Hello World</title></head></html>"
    ) == "Hello World"
    # 大小写 / 含属性
    assert uf._extract_title_from_html(
        '<html><head><Title lang="en">X &amp; Y</Title></head>'
    ) == "X & Y"
    # 无 title
    assert uf._extract_title_from_html("<html></html>") is None
