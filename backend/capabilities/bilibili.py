"""v3.5 chunk 6a — B 站 11 个 capability(2026-05-21 INV-7 §1 P1.bilibili fold)。

姿态 A 本地 capability(与 chunk 1 netease / chunk 7 docx 同架构)。
Implementation 复用 ``backend/integrations/bilibili.py`` 的 11 个 client 方法。

**fold 后形态**:11 个旧 cap `bilibili.<action>` 改为 1 个 `bilibili` dispatcher,
内部 11 个 `_handle_*` async function 复用底层 `_bili` client 实现。LLM 调用形态:
``bilibili(action="search_video", keyword="X")``。

Spec pivot:``get_subtitles`` 从无 cookie 移到 cookie(B 站 2024-2025 风控
现实),详见 ``backend/integrations/bilibili.py`` 头注释。
"""
from __future__ import annotations

from typing import Any

from backend.capabilities import Consumer, TriggerMode, register_capability
from backend.integrations import bilibili as _bili


# ---------------------------------------------------------------------------
# 11 internal handlers (per INV-7 §1 P1.bilibili fold, 2026-05-21):
# search_video / get_video_info / search_user / get_user_videos / hot_videos /
# get_ranking / get_subtitles / get_my_history / get_my_followings /
# get_later_watch / get_favorites
# 走 dispatcher `bilibili(action=...)`,不再单独 @register_capability。
# ---------------------------------------------------------------------------


async def _handle_search_video(
    keyword: str = "", page: int = 1, page_size: int = 20, **_kwargs: Any,
) -> dict:
    return await _bili.search_video(keyword=keyword, page=page, page_size=page_size)


async def _handle_get_video_info(
    bvid: str = "", aid: int = 0, **_kwargs: Any,
) -> dict:
    return await _bili.get_video_info(bvid=bvid or None, aid=aid or None)


async def _handle_search_user(
    keyword: str = "", page: int = 1, **_kwargs: Any,
) -> dict:
    return await _bili.search_user(keyword=keyword, page=page)


async def _handle_get_user_videos(
    mid: int = 0, page: int = 1, page_size: int = 30, **_kwargs: Any,
) -> dict:
    if not mid:
        return {"error": "missing_mid"}
    return await _bili.get_user_videos(mid=int(mid), page=page, page_size=page_size)


async def _handle_hot_videos(
    page: int = 1, page_size: int = 20, **_kwargs: Any,
) -> dict:
    return await _bili.hot_videos(page=page, page_size=page_size)


async def _handle_get_ranking(
    rank_type: str = "all", day: int = 3, **_kwargs: Any,
) -> dict:
    return await _bili.get_ranking(rank_type=rank_type, day=day)


async def _handle_get_subtitles(
    bvid: str = "", aid: int = 0, **_kwargs: Any,
) -> dict:
    return await _bili.get_subtitles(bvid=bvid or None, aid=aid or None)


async def _handle_get_my_history(
    page_size: int = 20, **_kwargs: Any,
) -> dict:
    return await _bili.get_my_history(page_size=page_size)


async def _handle_get_my_followings(
    page: int = 1, page_size: int = 20, **_kwargs: Any,
) -> dict:
    return await _bili.get_my_followings(page=page, page_size=page_size)


async def _handle_get_later_watch(**_kwargs: Any) -> dict:
    return await _bili.get_later_watch()


async def _handle_get_favorites(**_kwargs: Any) -> dict:
    return await _bili.get_favorites()


# ---------------------------------------------------------------------------
# bilibili dispatcher (INV-7 §1 P1.bilibili template reuse #2)
# ---------------------------------------------------------------------------

_BILIBILI_ACTION_HANDLERS = {
    "search_video":      _handle_search_video,
    "get_video_info":    _handle_get_video_info,
    "search_user":       _handle_search_user,
    "get_user_videos":   _handle_get_user_videos,
    "hot_videos":        _handle_hot_videos,
    "get_ranking":       _handle_get_ranking,
    "get_subtitles":     _handle_get_subtitles,
    "get_my_history":    _handle_get_my_history,
    "get_my_followings": _handle_get_my_followings,
    "get_later_watch":   _handle_get_later_watch,
    "get_favorites":     _handle_get_favorites,
}


@register_capability(
    name="bilibili",
    display_name="B 站操作",
    description=(
        "B 站操作集合。按 action 选具体操作:\n"
        "- search_video:搜视频(用户说'B 站搜 X / 有没有 X 视频',需 keyword)\n"
        "- get_video_info:视频元数据(标题/UP/时长/播放数/点赞/弹幕等;用户说"
        "'这视频是谁发的/多长/简介'或粘 BV 链接时**默认**调,bvid 或 aid 二选一)\n"
        "- search_user:搜 UP 主(需 keyword)\n"
        "- get_user_videos:UP 主投稿(需 mid,先 search_user 拿 mid)\n"
        "- hot_videos:首页热门(用户说'B 站现在有啥热门')\n"
        "- get_ranking:排行榜(rank_type=all/rookie/origin,day=3/7)\n"
        "- get_subtitles:视频字幕用于总结(⭐ 杀手 use case:'帮我总结这视频/讲了啥/"
        "太长不看',拿字幕后用自己话总结;bvid/aid 二选一;需 BILIBILI_SESSDATA cookie)\n"
        "- get_my_history / get_my_followings / get_later_watch / get_favorites:"
        "个人数据(需 BILIBILI_SESSDATA cookie)\n"
    ),
    category="media",
    consumers=[Consumer.CHAT_AGENT],
    trigger_modes=[TriggerMode.ON_DEMAND],
    icon="play-square",
    health_check=_bili.health_check,
    parameters_schema={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": list(_BILIBILI_ACTION_HANDLERS.keys()),
                "description": "B 站操作类型",
            },
            "keyword": {
                "type": "string",
                "description": "仅 action=search_video / search_user 必填",
            },
            "bvid": {
                "type": "string",
                "description": "仅 action=get_video_info / get_subtitles(与 aid 二选一)",
            },
            "aid": {
                "type": "integer",
                "description": "仅 action=get_video_info / get_subtitles(与 bvid 二选一)",
            },
            "mid": {
                "type": "integer",
                "description": "仅 action=get_user_videos 必填(UP 主 ID,先 search_user 拿)",
            },
            "page": {
                "type": "integer",
                "default": 1,
                "description": "页码(search/user_videos/hot/followings),默 1",
            },
            "page_size": {
                "type": "integer",
                "description": "每页条数(search 默 20/user_videos 默 30/hot 默 20/history 默 20/followings 默 20)",
            },
            "rank_type": {
                "type": "string",
                "enum": ["all", "rookie", "origin"],
                "default": "all",
                "description": "仅 action=get_ranking,综合/新人/原创(默 all)",
            },
            "day": {
                "type": "integer",
                "enum": [3, 7],
                "default": 3,
                "description": "仅 action=get_ranking,时间窗 3 或 7 天(默 3)",
            },
        },
        "required": ["action"],
    },
)
async def bilibili_dispatch(action: str = "", **params: Any) -> dict:
    """Dispatcher: 按 action 路由到对应 _handle_* 函数,含 action-specific required 校验。"""
    handler = _BILIBILI_ACTION_HANDLERS.get(action)
    if handler is None:
        return {
            "ok": False,
            "error": (
                f"unknown action: {action!r}; "
                f"valid: {list(_BILIBILI_ACTION_HANDLERS.keys())}"
            ),
        }
    # action-specific required 字段校验
    if action in ("search_video", "search_user"):
        if not params.get("keyword"):
            return {"ok": False, "error": f"keyword required when action={action}"}
    elif action == "get_user_videos":
        if not params.get("mid"):
            return {"ok": False, "error": "mid required when action=get_user_videos"}
    elif action in ("get_video_info", "get_subtitles"):
        if not params.get("bvid") and not params.get("aid"):
            return {"ok": False, "error": f"bvid or aid required when action={action}"}
    return await handler(**params)


__all__ = [
    "bilibili_dispatch",
]
