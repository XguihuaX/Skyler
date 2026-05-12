"""v3.5 chunk 8a — 公开 URL 内容 fetch + 黑名单 + readability 正文提取。

设计原则
========

* 单次 GET，timeout 5s，max_redirects 3，read body ≤ 1MB。**不爬站点**、
  不跟随 RSS、不 prefetch 相关页。等同浏览器手动打开一次的网络足迹。
* User-Agent 公开声明 ``Skyler/1.0 (activity-aware companion)``——服务器
  方便识别 + 屏蔽（与隐藏 UA 相比对站点诚实）
* 黑名单 fnmatch glob 命中 → 跳过 fetch + log "blocked"。默认列表覆盖银行、
  邮箱、社交、localhost，避免后台 ActivityWatcher 误抓登录后内容
* readability-lxml 提正文 + ``html.unescape``；提失败 fallback 到 ``response.
  text`` 截前 ``max_chars``
* 全函数失败 → log warning + 返 dict ``{status: "blocked"|"timeout"|...}``
  或 None；**不抛错给上层 capability / watcher**（与 chunk 6c xiaohongshu /
  chunk 3a clipboard 一致）

Public API
==========

* ``async fetch_article_content(url, *, max_chars=5000) -> Optional[dict]``
* ``is_url_blocked(url, patterns) -> bool``
"""
from __future__ import annotations

import fnmatch
import html
import logging
import re
from typing import Iterable, Optional
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 黑名单（默认值；config.activity_watcher.blocked_url_patterns 可覆盖）
# ---------------------------------------------------------------------------

DEFAULT_BLOCKED_PATTERNS: list[str] = [
    # 银行 / 金融
    "*chase.com*",
    "*bankofamerica.com*",
    "*wellsfargo.com*",
    "*paypal.com*",
    # 邮箱
    "*mail.google.com*",
    "*outlook.live.com*",
    "*outlook.office.com*",
    "*mail.yahoo.com*",
    "*mail.qq.com*",
    "*mail.163.com*",
    # 社交（登录后内容隐私敏感）
    "*facebook.com/*",
    "*instagram.com/*",
    "*twitter.com/*",
    "*x.com/*",
    "*linkedin.com/feed*",
    # 本地 dev / 局域网
    "*localhost*",
    "127.0.0.1*",
    "192.168.*",
    "10.0.*",
]


# ---------------------------------------------------------------------------
# 限额
# ---------------------------------------------------------------------------

_REQUEST_TIMEOUT_SECONDS = 5.0
_MAX_BYTES = 1 * 1024 * 1024  # 1 MB
_MAX_REDIRECTS = 3
_USER_AGENT = "Skyler/1.0 (activity-aware companion)"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def is_url_blocked(url: str, patterns: Iterable[str]) -> bool:
    """fnmatch glob 命中即 blocked。配置传 ``DEFAULT_BLOCKED_PATTERNS`` 兜底。

    匹配在**整 URL** 上（含 scheme + path），而不是仅 host —— 让 patterns
    可以更精确（``*linkedin.com/feed*`` 只挡 feed 不挡 profile 页）。
    """
    for pat in patterns:
        if fnmatch.fnmatch(url, pat):
            return True
    return False


_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


def _extract_title_from_html(body: str) -> Optional[str]:
    """简单正则抓 ``<title>``，失败返 None。给 readability fail 时兜底用。"""
    m = _TITLE_RE.search(body)
    if not m:
        return None
    return html.unescape(m.group(1).strip()) or None


def _extract_readability(html_body: str, base_url: str) -> Optional[tuple[str, str]]:
    """readability-lxml → (title, plain_text)；提取失败返 None。"""
    try:
        from readability import Document  # type: ignore
    except Exception as exc:  # pragma: no cover - 包装好就有
        logger.warning("[url_fetcher] readability import failed: %s", exc)
        return None
    try:
        doc = Document(html_body)
        title = (doc.short_title() or "").strip() or None
        # readability summary 仍带 HTML 标签 + 空白；再用一遍 lxml clean 取纯文本
        summary_html = doc.summary(html_partial=True)
        # 简单 strip tags：不引入新依赖；与 chunk 6c xiaohongshu 同 pragmatic
        text = re.sub(r"<[^>]+>", " ", summary_html)
        text = html.unescape(text)
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            return None
        if title is None:
            title = _extract_title_from_html(html_body) or ""
        return title, text
    except Exception as exc:
        logger.debug("[url_fetcher] readability failed on %s: %s", base_url, exc)
        return None


# ---------------------------------------------------------------------------
# fetch_article_content
# ---------------------------------------------------------------------------


async def fetch_article_content(
    url: str,
    *,
    blocked_patterns: Optional[Iterable[str]] = None,
    max_chars: int = 5000,
) -> Optional[dict]:
    """公开 URL → ``{url, title, content, status: "ok"}``，或 blocked / 失败时
    返 ``{fetched: false, reason: ...}``。

    所有失败路径都返 dict 而不是 None —— 让 capability 层稳定地把"我没读到"
    + 具体原因传给 LLM，便于 LLM 选择"承认看不到"还是"反问用户"。
    """
    if not url or not url.lower().startswith(("http://", "https://")):
        return {"fetched": False, "url": url, "reason": "invalid_url"}

    patterns = list(blocked_patterns) if blocked_patterns is not None \
        else DEFAULT_BLOCKED_PATTERNS

    if is_url_blocked(url, patterns):
        logger.info("[url_fetcher] blocked by pattern: %s",
                    urlparse(url).hostname or url)
        return {"fetched": False, "url": url, "reason": "blocked"}

    try:
        async with httpx.AsyncClient(
            timeout=_REQUEST_TIMEOUT_SECONDS,
            follow_redirects=True,
            max_redirects=_MAX_REDIRECTS,
            headers={
                "User-Agent": _USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,*/*;q=0.5",
            },
        ) as client:
            resp = await client.get(url)
    except httpx.TimeoutException:
        logger.warning("[url_fetcher] timeout: %s", url)
        return {"fetched": False, "url": url, "reason": "timeout"}
    except httpx.RequestError as exc:
        logger.warning("[url_fetcher] request error %s: %s", url, exc)
        return {"fetched": False, "url": url, "reason": "request_error"}
    except Exception as exc:  # pragma: no cover - 防御性
        logger.warning("[url_fetcher] unexpected %s: %s", url, exc)
        return {"fetched": False, "url": url, "reason": "unexpected_error"}

    if resp.status_code in (401, 403):
        return {"fetched": False, "url": url, "reason": "login_required",
                "http_status": resp.status_code}
    if resp.status_code in (412, 418, 429):
        return {"fetched": False, "url": url, "reason": "blocked_by_antibot",
                "http_status": resp.status_code}
    if resp.status_code >= 400:
        return {"fetched": False, "url": url, "reason": "http_error",
                "http_status": resp.status_code}

    # Content-Type 必须是 text/* 或 application/xhtml+xml；图片 / pdf / 视频跳过
    ctype = resp.headers.get("content-type", "").lower()
    if "html" not in ctype and "text/" not in ctype and "xhtml" not in ctype:
        return {"fetched": False, "url": url, "reason": "non_html",
                "content_type": ctype}

    # body size 上限
    body = resp.text or ""
    if len(body.encode("utf-8", errors="ignore")) > _MAX_BYTES:
        body = body[: _MAX_BYTES]  # 字符截断比字节截断稍宽松，OK

    extracted = _extract_readability(body, url)
    if extracted is None:
        # 退到 plain title + body 截断
        title = _extract_title_from_html(body) or ""
        text = re.sub(r"<[^>]+>", " ", body)
        text = html.unescape(text)
        text = re.sub(r"\s+", " ", text).strip()
    else:
        title, text = extracted

    if not text:
        return {"fetched": False, "url": url, "reason": "empty_body"}

    if max_chars > 0 and len(text) > max_chars:
        text = text[:max_chars].rstrip() + "…"

    return {
        "fetched": True,
        "url": url,
        "title": title or "",
        "content": text,
        "status": "ok",
    }
