"""v3.5 chunk 6a — B 站集成层（Nemo2011/bilibili-api 社区 fork 包装）。

设计与 ``backend/integrations/netease_music.py`` 同模式：
* 一个 ``BilibiliClient`` 单例类，向上暴露 11 个方法（每个对应一个 capability）
* 健康检查三档：``library_present`` / ``cookie_configured`` / ``connectivity``
* 所有公开方法包 try/except 转 ``{"error": "<code>", "detail": "..."}`` 字典，
  绝不向 capability 层 raise（与 chunk 1 netease / chunk 7 docx 同契约）

Cookie 走 ``.env`` ``BILIBILI_SESSDATA``（与 chunk 1 NETEASE_MUSIC_U 同
模式，不走 chunk 7 ``mcp_credentials`` 表——B 站是本地 capability，不是
MCP server 子进程）。

# 字幕授权 audit 笔记（chunk 6a 实施时）

B 站 2024-2025 风控收紧 ``/x/player/v2`` 与 ``/x/player/wbi/v2`` 端点：
未携带 sessdata 时返回 ``code: 0`` 但 ``subtitles: []`` 空列表。
``bilibili-api-python`` 库直接在 ``Video.get_subtitle()`` 入口
``raise CredentialNoSessdataException``。

实施 pivot：spec 原计划 ``get_subtitles`` 走无 cookie 路径，实测不可行。
本模块把 ``get_subtitles`` 归类为 cookie-required，与其他 4 个 "自己的"
capability 并列。用户配 ``BILIBILI_SESSDATA`` 后 5 个全部可用；未配则
统一返 ``cookie_required`` 错误码。
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lazy import — 让 capability 模块在 library 缺失时仍能 import + 给清晰错误
# ---------------------------------------------------------------------------

_LIB_AVAILABLE: Optional[bool] = None
_LIB_IMPORT_ERR: Optional[str] = None


def _try_import_lib():
    """返回 (bilibili_api 模块或 None, error_str_or_None)。缓存结果。"""
    global _LIB_AVAILABLE, _LIB_IMPORT_ERR
    if _LIB_AVAILABLE is False:
        return None, _LIB_IMPORT_ERR
    try:
        import bilibili_api as _ba  # noqa: F401
        _LIB_AVAILABLE = True
        return _ba, None
    except ImportError as exc:
        _LIB_AVAILABLE = False
        _LIB_IMPORT_ERR = str(exc)
        return None, str(exc)


# ---------------------------------------------------------------------------
# Cookie / Credential
# ---------------------------------------------------------------------------

_SESSDATA_ENV = "BILIBILI_SESSDATA"


def _read_sessdata() -> Optional[str]:
    raw = os.getenv(_SESSDATA_ENV)
    if not raw or not raw.strip():
        return None
    return raw.strip()


def _build_credential() -> Optional[Any]:
    """构造 ``bilibili_api.Credential``。无 sessdata → None。"""
    ba, _ = _try_import_lib()
    if ba is None:
        return None
    sessdata = _read_sessdata()
    if sessdata is None:
        return None
    return ba.Credential(sessdata=sessdata)


# ---------------------------------------------------------------------------
# Error normalisation
# ---------------------------------------------------------------------------

# B 站常见风控 code → 友好 error key 映射
_RISK_CODES: dict[int, str] = {
    -352: "risk_control",       # 通用风控（频繁请求）
    -412: "rate_limited",       # 限流
    -403: "forbidden",
    -404: "not_found",
    -509: "rate_limited",
    62002: "video_unavailable",
}


def _normalize_error(exc: Exception) -> dict:
    """B 站 lib 抛的各种异常 → 统一 dict。"""
    ba, _ = _try_import_lib()
    name = type(exc).__name__
    msg = str(exc)

    # ResponseCodeException 带 code 字段
    code = getattr(exc, "code", None)
    if isinstance(code, int) and code in _RISK_CODES:
        return {
            "error": _RISK_CODES[code],
            "detail": msg,
            "bilibili_code": code,
        }

    if ba is not None:
        if isinstance(exc, ba.CredentialNoSessdataException) or isinstance(
            exc, ba.exceptions.CredentialNoSessdataException
        ):
            return {
                "error": "cookie_required",
                "hint": (
                    "请在 .env 配置 BILIBILI_SESSDATA（浏览器 F12 → "
                    "Application → Cookies → bilibili.com → 复制 SESSDATA 值）"
                ),
            }
        if isinstance(exc, ba.NetworkException):
            return {"error": "network_error", "detail": msg}
        if isinstance(exc, ba.ArgsException):
            return {"error": "invalid_args", "detail": msg}
    # 兜底
    return {"error": "bilibili_error", "exception": name, "detail": msg[:200]}


# ---------------------------------------------------------------------------
# Health check (3 tiers)
# ---------------------------------------------------------------------------

async def health_check() -> dict:
    """三档健康状态：library 装了 + cookie 配了 + 真能 hit B 站。

    给 ``capabilities/bilibili.py`` 的 ``@register_capability`` ``health_check``
    用，UI CapabilityPanel 显示。
    """
    ba, err = _try_import_lib()
    if ba is None:
        return {
            "status": "error",
            "error": "library_missing",
            "detail": err or "bilibili-api-python not installed",
            "fix": "pip install bilibili-api-python>=17.4",
        }

    cookie_configured = _read_sessdata() is not None

    # connectivity probe — hot videos 是最便宜的无 cookie 调用
    try:
        await ba.hot.get_hot_videos(pn=1, ps=1)
        connectivity = "ok"
    except Exception as exc:
        return {
            "status": "warn",
            "library_present": True,
            "cookie_configured": cookie_configured,
            "connectivity": "fail",
            "detail": str(exc)[:200],
        }

    return {
        "status": "healthy" if cookie_configured else "warn",
        "library_present": True,
        "cookie_configured": cookie_configured,
        "connectivity": connectivity,
        "note": (
            None if cookie_configured
            else "无 cookie 时只能用 6 个无登录 capability；配置 BILIBILI_SESSDATA "
                 "后解锁 5 个登录 capability（含字幕总结）"
        ),
    }


# ---------------------------------------------------------------------------
# Public client (11 methods)
# ---------------------------------------------------------------------------


def _require_lib():
    """Lib 缺失时返 raise 用的错误 dict；存在则返 (ba, None)。"""
    ba, err = _try_import_lib()
    if ba is None:
        return None, {
            "error": "library_missing",
            "detail": err,
            "fix": "pip install bilibili-api-python>=17.4",
        }
    return ba, None


def _require_cookie():
    """Cookie 未配返 (None, err_dict)；已配返 (credential, None)。"""
    cred = _build_credential()
    if cred is None:
        return None, {
            "error": "cookie_required",
            "hint": (
                "请在 .env 配置 BILIBILI_SESSDATA（浏览器 F12 → Application →"
                " Cookies → bilibili.com → 复制 SESSDATA 值）。详见 "
                "docs/bilibili-setup.md"
            ),
        }
    return cred, None


# ─── 无 cookie ────────────────────────────────────────────────────────────

async def search_video(
    keyword: str, page: int = 1, page_size: int = 20,
) -> dict:
    """搜视频。返回 ``{result: [...], total, page}``。"""
    ba, err = _require_lib()
    if err:
        return err
    if not keyword or not keyword.strip():
        return {"error": "missing_keyword"}
    try:
        r = await ba.search.search_by_type(
            keyword=keyword.strip(),
            search_type=ba.search.SearchObjectType.VIDEO,
            page=page,
            page_size=page_size,
        )
        # 标准化：剥掉 B 站冗余字段，只留对 LLM 有用的
        items: list[dict] = []
        for v in (r.get("result") or [])[:page_size]:
            items.append({
                "bvid": v.get("bvid"),
                "aid": v.get("aid"),
                "title": _strip_em(v.get("title")),
                "author": v.get("author"),
                "duration": v.get("duration"),
                "play": v.get("play"),
                "description": (v.get("description") or "")[:200],
                "url": f"https://www.bilibili.com/video/{v.get('bvid')}" if v.get("bvid") else None,
            })
        return {
            "result": items,
            "total": r.get("numResults", 0),
            "page": r.get("page", page),
        }
    except Exception as exc:
        return _normalize_error(exc)


async def get_video_info(bvid: Optional[str] = None, aid: Optional[int] = None) -> dict:
    """拿单个视频的元数据。bvid 或 aid 二选一。"""
    ba, err = _require_lib()
    if err:
        return err
    if not bvid and not aid:
        return {"error": "missing_bvid_or_aid"}
    try:
        v = ba.video.Video(bvid=bvid, aid=aid)
        info = await v.get_info()
        # 摘要字段
        owner = info.get("owner") or {}
        stat = info.get("stat") or {}
        return {
            "bvid": info.get("bvid"),
            "aid": info.get("aid"),
            "cid": info.get("cid"),
            "title": info.get("title"),
            "description": info.get("desc") or "",
            "duration": info.get("duration"),  # 秒
            "pubdate": info.get("pubdate"),    # unix 秒
            "owner": {
                "mid": owner.get("mid"),
                "name": owner.get("name"),
            },
            "stat": {
                "view": stat.get("view"),
                "danmaku": stat.get("danmaku"),
                "like": stat.get("like"),
                "favorite": stat.get("favorite"),
                "coin": stat.get("coin"),
                "share": stat.get("share"),
                "reply": stat.get("reply"),
            },
            "url": f"https://www.bilibili.com/video/{info.get('bvid')}",
        }
    except Exception as exc:
        return _normalize_error(exc)


async def search_user(keyword: str, page: int = 1) -> dict:
    """搜 UP 主。"""
    ba, err = _require_lib()
    if err:
        return err
    if not keyword or not keyword.strip():
        return {"error": "missing_keyword"}
    try:
        r = await ba.search.search_by_type(
            keyword=keyword.strip(),
            search_type=ba.search.SearchObjectType.USER,
            page=page,
        )
        items: list[dict] = []
        for u in r.get("result") or []:
            items.append({
                "mid": u.get("mid"),
                "name": _strip_em(u.get("uname")),
                "fans": u.get("fans"),
                "videos": u.get("videos"),
                "level": u.get("level"),
                "sign": u.get("usign") or "",
            })
        return {"result": items, "page": page}
    except Exception as exc:
        return _normalize_error(exc)


async def get_user_videos(mid: int, page: int = 1, page_size: int = 30) -> dict:
    """拿 UP 主投稿列表。"""
    ba, err = _require_lib()
    if err:
        return err
    try:
        u = ba.user.User(uid=int(mid))
        data = await u.get_videos(pn=page, ps=page_size)
        vlist = (data.get("list") or {}).get("vlist") or []
        items = [{
            "bvid": v.get("bvid"),
            "aid": v.get("aid"),
            "title": v.get("title"),
            "duration": v.get("length"),
            "play": v.get("play"),
            "created": v.get("created"),
            "url": f"https://www.bilibili.com/video/{v.get('bvid')}",
        } for v in vlist]
        return {
            "mid": int(mid),
            "page": page,
            "total": (data.get("page") or {}).get("count", 0),
            "videos": items,
        }
    except Exception as exc:
        return _normalize_error(exc)


async def hot_videos(page: int = 1, page_size: int = 20) -> dict:
    """首页热门视频。"""
    ba, err = _require_lib()
    if err:
        return err
    try:
        data = await ba.hot.get_hot_videos(pn=page, ps=page_size)
        items = []
        for v in (data.get("list") or [])[:page_size]:
            owner = v.get("owner") or {}
            stat = v.get("stat") or {}
            items.append({
                "bvid": v.get("bvid"),
                "aid": v.get("aid"),
                "title": v.get("title"),
                "owner": owner.get("name"),
                "view": stat.get("view"),
                "duration": v.get("duration"),
                "url": f"https://www.bilibili.com/video/{v.get('bvid')}",
            })
        return {"result": items, "page": page}
    except Exception as exc:
        return _normalize_error(exc)


async def get_ranking(rank_type: str = "all", day: int = 3) -> dict:
    """排行榜。rank_type: 'all' / 'rookie' / 'origin'，day: 3/7。"""
    ba, err = _require_lib()
    if err:
        return err
    try:
        rt = {
            "all":    ba.rank.RankType.All,
            "rookie": ba.rank.RankType.Rookie,
            "origin": ba.rank.RankType.Origin,
        }.get(rank_type, ba.rank.RankType.All)
        day_enum = ba.rank.RankDayType.THREE_DAY if day <= 3 else ba.rank.RankDayType.SEVEN_DAY
        try:
            data = await ba.rank.get_rank(rank_type=rt, day=day_enum)
        except TypeError:
            # 不同版本签名可能略不同，回退
            data = await ba.rank.get_rank(type_=rt)
        items = []
        for v in (data.get("list") or [])[:50]:
            items.append({
                "bvid": v.get("bvid"),
                "aid": v.get("aid"),
                "title": v.get("title"),
                "owner": (v.get("owner") or {}).get("name"),
                "view": (v.get("stat") or {}).get("view"),
                "score": v.get("score"),
                "url": f"https://www.bilibili.com/video/{v.get('bvid')}",
            })
        return {"rank_type": rank_type, "day": day, "result": items}
    except Exception as exc:
        return _normalize_error(exc)


# ─── Cookie required ─────────────────────────────────────────────────────


async def get_subtitles(bvid: Optional[str] = None, aid: Optional[int] = None) -> dict:
    """拿视频字幕（AI / UP 主上传），用于 LLM 总结视频内容。

    **需要 cookie**：B 站 2024-2025 风控收紧，字幕 API 无 sessdata 时返空。

    优先 AI 字幕（``ai-zh`` / ``ai-zh-Hant`` 等）；无 AI 字幕则取 UP 主上
    传字幕（``zh-CN`` 等）；都没有返 ``source: "none"`` + ``subtitle_text: ""``。
    """
    ba, err = _require_lib()
    if err:
        return err
    cred, cerr = _require_cookie()
    if cerr:
        return cerr
    if not bvid and not aid:
        return {"error": "missing_bvid_or_aid"}
    try:
        v = ba.video.Video(bvid=bvid, aid=aid, credential=cred)
        info = await v.get_info()
        cid = info.get("cid")
        title = info.get("title") or ""
        duration = info.get("duration") or 0
        out_bvid = info.get("bvid")
        sub_data = await v.get_subtitle(cid=cid)
        subs = (sub_data or {}).get("subtitles") or []
        if not subs:
            return {
                "bvid": out_bvid,
                "title": title,
                "subtitle_text": "",
                "source": "none",
                "duration": duration,
                "note": "该视频未提供 AI 字幕或 UP 主字幕",
            }
        chosen, source = _choose_subtitle(subs)
        if chosen is None:
            return {
                "bvid": out_bvid,
                "title": title,
                "subtitle_text": "",
                "source": "none",
                "duration": duration,
            }
        # 拉字幕 JSON
        sub_url = chosen.get("subtitle_url") or ""
        if sub_url.startswith("//"):
            sub_url = "https:" + sub_url
        text = await _fetch_subtitle_text(sub_url)
        return {
            "bvid": out_bvid,
            "title": title,
            "subtitle_text": text,
            "source": source,
            "lan": chosen.get("lan"),
            "lan_doc": chosen.get("lan_doc"),
            "duration": duration,
        }
    except Exception as exc:
        return _normalize_error(exc)


async def get_my_history(page_size: int = 20) -> dict:
    """我的观看历史。"""
    ba, err = _require_lib()
    if err:
        return err
    cred, cerr = _require_cookie()
    if cerr:
        return cerr
    try:
        data = await ba.user.get_self_history_new(credential=cred, ps=page_size)
        items = []
        for h in (data.get("list") or [])[:page_size]:
            items.append({
                "bvid": (h.get("history") or {}).get("bvid"),
                "title": h.get("title"),
                "view_at": h.get("view_at"),
                "progress": h.get("progress"),
                "duration": h.get("duration"),
                "author": (h.get("author_name") or ""),
            })
        return {"result": items, "count": len(items)}
    except Exception as exc:
        return _normalize_error(exc)


async def get_my_followings(page: int = 1, page_size: int = 20) -> dict:
    """我关注的人。"""
    ba, err = _require_lib()
    if err:
        return err
    cred, cerr = _require_cookie()
    if cerr:
        return cerr
    try:
        # 拿 self mid 先
        self_info = await ba.user.get_self_info(credential=cred)
        my_mid = self_info.get("mid")
        if not my_mid:
            return {"error": "self_info_unavailable"}
        u = ba.user.User(uid=int(my_mid), credential=cred)
        data = await u.get_followings(pn=page, ps=page_size)
        items = [{
            "mid": f.get("mid"),
            "name": f.get("uname"),
            "sign": f.get("sign") or "",
        } for f in (data.get("list") or [])]
        return {"result": items, "total": data.get("total", 0), "page": page}
    except Exception as exc:
        return _normalize_error(exc)


async def get_later_watch() -> dict:
    """稍后再看列表。"""
    ba, err = _require_lib()
    if err:
        return err
    cred, cerr = _require_cookie()
    if cerr:
        return cerr
    try:
        data = await ba.user.get_toview_list(credential=cred)
        items = [{
            "bvid": v.get("bvid"),
            "aid": v.get("aid"),
            "title": v.get("title"),
            "duration": v.get("duration"),
            "owner": (v.get("owner") or {}).get("name"),
            "add_at": v.get("add_at"),
        } for v in (data.get("list") or [])]
        return {"result": items, "count": data.get("count", len(items))}
    except Exception as exc:
        return _normalize_error(exc)


async def get_favorites() -> dict:
    """我的收藏夹列表（不含夹内视频，第一版只列夹）。"""
    ba, err = _require_lib()
    if err:
        return err
    cred, cerr = _require_cookie()
    if cerr:
        return cerr
    try:
        self_info = await ba.user.get_self_info(credential=cred)
        my_mid = self_info.get("mid")
        if not my_mid:
            return {"error": "self_info_unavailable"}
        # bilibili-api 的 FavoriteList 类需要 fid；上层"我的收藏夹列表"用
        # favorite_list.get_video_favorite_list 接口
        from bilibili_api import favorite_list as fl
        # 这个签名各版本略不同——尝试两种
        try:
            data = await fl.get_video_favorite_list(uid=int(my_mid), credential=cred)
        except AttributeError:
            data = await fl.get_video_favorite_list(uid=int(my_mid))
        flist = (data.get("list") or []) if isinstance(data, dict) else []
        items = [{
            "fid": f.get("id"),
            "title": f.get("title"),
            "media_count": f.get("media_count"),
        } for f in flist]
        return {"result": items, "count": len(items)}
    except Exception as exc:
        return _normalize_error(exc)


# ---------------------------------------------------------------------------
# Subtitle helpers
# ---------------------------------------------------------------------------

def _choose_subtitle(subs: list[dict]) -> tuple[Optional[dict], str]:
    """从 B 站 subtitle list 选最优条目。

    优先级：
      1. ai_type=1（AI 字幕）且 lan 含 'ai' 或 'zh' —— AI 中文
      2. UP 主上传的 zh / zh-CN
      3. 列表第一项
    """
    if not subs:
        return None, "none"
    ai_zh = [s for s in subs if (s.get("ai_type") or 0) >= 1 and "zh" in (s.get("lan") or "")]
    if ai_zh:
        return ai_zh[0], "ai"
    manual_zh = [s for s in subs
                 if (s.get("ai_type") or 0) == 0
                 and "zh" in (s.get("lan") or "")]
    if manual_zh:
        return manual_zh[0], "manual"
    return subs[0], "manual"


async def _fetch_subtitle_text(url: str) -> str:
    """拉 B 站字幕 JSON URL → 拼成 plain text（去时间戳 + 段间换行）。"""
    if not url:
        return ""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(url, headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://www.bilibili.com",
            })
            data = r.json()
    except Exception as exc:
        logger.warning("[bilibili] subtitle fetch failed: %s", exc)
        return ""
    body = data.get("body") or []
    parts = []
    for line in body:
        content = (line.get("content") or "").strip()
        if content:
            parts.append(content)
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Misc helpers
# ---------------------------------------------------------------------------

import re as _re

_EM_RE = _re.compile(r"<em[^>]*>|</em>")


def _strip_em(text: Optional[str]) -> str:
    """B 站搜索结果会用 ``<em class="keyword">X</em>`` 高亮关键词；剥掉。"""
    if not text:
        return ""
    return _EM_RE.sub("", text)
