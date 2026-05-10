"""v3.5 chunk 6c — 小红书 URL 被动解析（**绝不主动爬**）。

# 工程红线

* ✅ 用户主动贴 URL → 拉单次 HTML → 解析 og:meta + ``__INITIAL_STATE__``
* ❌ 主动搜索 / 推荐流 / 账号自动化 / 评论抓取（**坚决拒绝**实施）

红线在 system prompt + DESIGN + setup doc 三处明文。本模块工程层面**不
暴露**搜索 / 推荐相关方法——没有 search() 方法就没法被 LLM 调到这条路。

# 反爬现实

Audit 2025 web search 结论：小红书有较强 anti-bot 栈（datacenter IP 数分钟
被 ban / per-IP 10-20 req/min 限流 / 私有 API 需要签名）。

本模块策略：
* **不**走签名 API；只拉公开 HTML
* 浏览器 UA + Referer + Accept-Language 伪装
* follow_redirects=True（xhslink 短链 → 完整 URL）
* 单次低频请求，不轮询，不批量
* 失败优雅返 dict 错误码，不爆栈

**用户场景**：从 Skyler 本地启动（用户家庭 residential IP），低频被动
解析。这是 anti-bot 最宽松的场景。如真被 ban，friendly error 提示用户
"小红书暂时拒绝访问，过几分钟再试"。

# 字段解析策略

note 详情页两条数据源：
1. ``<meta property="og:title|og:description|og:image">`` —— 基础元数据，
   anti-bot 即便挡掉 API 也通常留 og 给爬虫友好
2. ``window.__INITIAL_STATE__ = {...}`` —— 完整笔记内容（title + desc +
   image list + author info + tags）；JSON 序列化时 ``undefined`` 不合法，
   解析前替换为 ``null``

策略：先尝试 ``__INITIAL_STATE__``（最完整）；解析失败 fall back og;
都不行 → ``{error: 'parse_failed'}`` 让 LLM 告诉用户。
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# 浏览器 UA（Safari macOS 同 chunk 6a B 站策略）
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/17.0 Safari/605.1.15"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://www.xiaohongshu.com/",
}

_TIMEOUT_S = 12

# 接受的 host
_ALLOWED_HOSTS = ("xiaohongshu.com", "xhslink.com")


# ---------------------------------------------------------------------------
# Regex extractors
# ---------------------------------------------------------------------------

_INITIAL_STATE_RE = re.compile(
    r"window\.__INITIAL_STATE__\s*=\s*({.*?})\s*</script>",
    re.DOTALL,
)
_OG_META_RE = re.compile(
    r'<meta[^>]+property=["\']og:([^"\']+)["\'][^>]+content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
_TWITTER_IMAGE_RE = re.compile(
    r'<meta[^>]+(?:name|property)=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# URL validation
# ---------------------------------------------------------------------------

def _is_allowed_url(url: str) -> bool:
    """限制 host 在白名单内（防 SSRF + 防误传非 xhs URL 触发本 capability）。"""
    if not url or not isinstance(url, str):
        return False
    if not (url.startswith("https://") or url.startswith("http://")):
        return False
    # 简单 hostname 提取
    try:
        host = url.split("://", 1)[1].split("/", 1)[0].lower()
    except (IndexError, ValueError):
        return False
    return any(host == h or host.endswith("." + h) for h in _ALLOWED_HOSTS)


# ---------------------------------------------------------------------------
# Initial-state JSON parsing
# ---------------------------------------------------------------------------

def _parse_initial_state(raw_json: str) -> Optional[dict]:
    """``window.__INITIAL_STATE__`` 值字符串 → dict，失败返 None。

    xhs JSON 序列化时 undefined 不替换 → 不合法 JSON。``json.loads`` 前
    把 ``undefined`` → ``null``；不动其他 token。
    """
    cleaned = raw_json.replace("undefined", "null")
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # 部分页面 __INITIAL_STATE__ 后面还有 trailing 字符；截到最后一个 '}'
        last_brace = cleaned.rfind("}")
        if last_brace > 0:
            try:
                return json.loads(cleaned[: last_brace + 1])
            except json.JSONDecodeError:
                return None
        return None


def _extract_note_from_initial_state(state: dict) -> Optional[dict]:
    """从 ``__INITIAL_STATE__`` 找到当前笔记的 dict。

    页面结构猜测顺序（按观察到的版本差异降序）：
      * ``state["note"]["noteDetailMap"][<id>]["note"]``
      * ``state["note"]["note"]``
      * ``state["noteData"]["data"]["noteInfo"]``

    找到任何含 ``title`` / ``desc`` / ``imageList`` 的子 dict 即返。
    """
    if not isinstance(state, dict):
        return None

    # 候选路径
    candidates: list[Any] = []
    note = state.get("note")
    if isinstance(note, dict):
        ndm = note.get("noteDetailMap") or {}
        if isinstance(ndm, dict):
            for v in ndm.values():
                if isinstance(v, dict):
                    inner = v.get("note") or v
                    candidates.append(inner)
        if note.get("note"):
            candidates.append(note["note"])
        candidates.append(note)

    nd = state.get("noteData")
    if isinstance(nd, dict):
        data = nd.get("data") or {}
        if isinstance(data, dict):
            candidates.append(data.get("noteInfo"))

    for c in candidates:
        if isinstance(c, dict) and any(
            k in c for k in ("title", "desc", "imageList", "ipLocation")
        ):
            return c
    return None


def _extract_og_meta(html: str) -> dict:
    """``<meta property="og:*">`` + twitter:image fallback → dict。"""
    out: dict[str, str] = {}
    for m in _OG_META_RE.finditer(html):
        out[m.group(1).lower()] = m.group(2)
    if "image" not in out:
        ti = _TWITTER_IMAGE_RE.search(html)
        if ti:
            out["image"] = ti.group(1)
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def parse_post(url: str) -> dict:
    """拉 URL HTML + 解析笔记元数据。返回归一化 dict 或 error dict。

    成功返回 ``{title, text, images: [...], author, tags, url, source}``，
    ``source ∈ {'initial_state', 'og_meta', 'unknown'}``。
    """
    if not _is_allowed_url(url):
        return {
            "error": "invalid_url",
            "hint": "仅支持 xiaohongshu.com / xhslink.com 域名",
        }
    try:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT_S,
            follow_redirects=True,
            headers=_HEADERS,
        ) as client:
            resp = await client.get(url)
    except httpx.TimeoutException:
        return {"error": "timeout", "url": url}
    except httpx.HTTPError as exc:
        return {"error": "network_error", "detail": str(exc)[:200]}

    if resp.status_code in (403, 412, 418):
        return {
            "error": "blocked_by_antibot",
            "status": resp.status_code,
            "hint": (
                "小红书暂时拒绝了请求（反爬限流）。可能原因：短时间内查询过多、"
                "网络出口被识别为非常用 IP。等几分钟再试，或换网络环境。"
            ),
        }
    if resp.status_code != 200:
        return {
            "error": "http_error",
            "status": resp.status_code,
            "url": str(resp.url),
        }
    html = resp.text
    final_url = str(resp.url)

    # 1. 优先 __INITIAL_STATE__
    m = _INITIAL_STATE_RE.search(html)
    if m:
        state = _parse_initial_state(m.group(1))
        note = _extract_note_from_initial_state(state) if state else None
        if note:
            return _normalize_note(note, final_url, source="initial_state")

    # 2. og:meta fallback
    og = _extract_og_meta(html)
    if og.get("title") or og.get("description"):
        return {
            "title": og.get("title") or "",
            "text": og.get("description") or "",
            "images": [og["image"]] if og.get("image") else [],
            "author": "",
            "tags": [],
            "url": final_url,
            "source": "og_meta",
            "note": "完整笔记内容未能解析；仅返回页面 og meta（缩略版）。",
        }

    # 3. 都没有 → parse_failed
    return {
        "error": "parse_failed",
        "url": final_url,
        "detail": (
            "页面无 __INITIAL_STATE__ 也无 og meta。可能是私人笔记 / 笔记已删除 / "
            "反爬走了不同模板。让用户检查链接是否仍可访问。"
        ),
    }


def _normalize_note(note: dict, url: str, *, source: str) -> dict:
    """``__INITIAL_STATE__`` 内笔记 dict → 归一化 capability 返回 schema。"""
    title = note.get("title") or ""
    text = note.get("desc") or note.get("content") or ""

    images: list[str] = []
    image_list = note.get("imageList") or note.get("images") or []
    if isinstance(image_list, list):
        for img in image_list:
            if isinstance(img, dict):
                u = img.get("urlDefault") or img.get("url") or img.get("urlPre")
                if u:
                    images.append(u)
            elif isinstance(img, str):
                images.append(img)

    user = note.get("user") or note.get("userInfo") or {}
    author = ""
    if isinstance(user, dict):
        author = user.get("nickname") or user.get("nickName") or user.get("name") or ""

    tags: list[str] = []
    tl = note.get("tagList") or note.get("tags") or []
    if isinstance(tl, list):
        for t in tl:
            if isinstance(t, dict):
                name = t.get("name")
                if name:
                    tags.append(str(name))
            elif isinstance(t, str):
                tags.append(t)

    return {
        "title": title,
        "text": text,
        "images": images,
        "author": author,
        "tags": tags,
        "url": url,
        "source": source,
    }


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

async def health_check() -> dict:
    """连通性 probe —— 拉首页确认能 reach。

    Anti-bot 不可避免地是 best-effort；本 probe 失败不代表 capability 一定
    不能用（短链 / 详情页响应模式可能不同），UI 显示 warn 即可。
    """
    try:
        async with httpx.AsyncClient(
            timeout=8,
            follow_redirects=True,
            headers=_HEADERS,
        ) as c:
            r = await c.get("https://www.xiaohongshu.com/explore")
    except Exception as exc:
        return {
            "status": "warn",
            "connectivity": "fail",
            "detail": str(exc)[:200],
        }
    if r.status_code in (403, 412, 418):
        return {
            "status": "warn",
            "connectivity": "blocked",
            "http_status": r.status_code,
            "hint": "当前 IP 被反爬识别；用户贴具体笔记 URL 时仍可能成功",
        }
    if r.status_code != 200:
        return {
            "status": "warn",
            "connectivity": "non_200",
            "http_status": r.status_code,
        }
    return {
        "status": "healthy",
        "connectivity": "ok",
        "note": (
            "被动 URL 解析模式；仅在用户贴具体笔记 URL 时调用。"
            "不实现搜索 / 推荐流 / 账号自动化（红线，详见 docs/xiaohongshu-setup.md）"
        ),
    }
