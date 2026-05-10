"""v3.5 chunk 6a — B 站 11 个 capability。

姿态 A 本地 capability（与 chunk 1 netease / chunk 7 docx 同架构）。
Implementation 复用 ``backend/integrations/bilibili.py`` 的 11 个 client
方法；本模块只做：``@register_capability`` 装饰 + description verbatim 引
导 + handler 接 ``**_kwargs`` 兜 ``user_id``。

Spec pivot：``get_subtitles`` 从无 cookie 移到 cookie（B 站 2024-2025 风控
现实），详见 ``backend/integrations/bilibili.py`` 头注释。
"""
from __future__ import annotations

from typing import Any

from backend.capabilities import Consumer, TriggerMode, register_capability
from backend.integrations import bilibili as _bili


# ---------------------------------------------------------------------------
# 1. search_video（无 cookie）
# ---------------------------------------------------------------------------

@register_capability(
    name="bilibili.search_video",
    display_name="搜索 B 站视频",
    description=(
        "搜索 B 站视频。用户说「B 站搜一下…」「有没有相关的 B 站视频」"
        "「B 站上 X 怎么讲的」时调用。\n\n"
        "参数：\n"
        "- keyword: 搜索关键词（必填）\n"
        "- page: 页码（缺省 1）\n"
        "- page_size: 每页条数（缺省 20，max 50）\n\n"
        "返回 ``{result: [{bvid, title, author, duration, play, url}, ...], total, page}``。"
        "title 已剥除 ``<em>`` 高亮标签。"
    ),
    category="media",
    consumers=[Consumer.CHAT_AGENT],
    trigger_modes=[TriggerMode.ON_DEMAND],
    icon="search",
    health_check=_bili.health_check,
    parameters_schema={
        "type": "object",
        "properties": {
            "keyword":   {"type": "string"},
            "page":      {"type": "integer"},
            "page_size": {"type": "integer"},
        },
        "required": ["keyword"],
    },
)
async def search_video(
    keyword: str = "", page: int = 1, page_size: int = 20, **_kwargs: Any,
) -> dict:
    return await _bili.search_video(keyword=keyword, page=page, page_size=page_size)


# ---------------------------------------------------------------------------
# 2. get_video_info（无 cookie）
# ---------------------------------------------------------------------------

@register_capability(
    name="bilibili.get_video_info",
    display_name="获取 B 站视频详情",
    description=(
        "拿 B 站视频元数据（标题 / UP 主 / 描述 / 时长 / 播放数 / 点赞 / 收藏 / "
        "弹幕 / 评论 等）。用户说「这个视频是谁发的」「这视频多长」「视频简介」"
        "或粘了 B 站链接（bilibili.com/video/BVxxx / BV 开头编号）时**默认**调"
        "本 capability 拿信息。\n\n"
        "参数（二选一）：\n"
        "- bvid: BV 号（推荐，B 站新版主流）\n"
        "- aid: AV 号（兼容老链接）\n\n"
        "返回 ``{bvid, aid, cid, title, description, duration, owner: {mid, name}, "
        "stat: {view, like, favorite, ...}, url}``。"
    ),
    category="media",
    consumers=[Consumer.CHAT_AGENT],
    trigger_modes=[TriggerMode.ON_DEMAND],
    icon="info",
    health_check=_bili.health_check,
    parameters_schema={
        "type": "object",
        "properties": {
            "bvid": {"type": "string"},
            "aid":  {"type": "integer"},
        },
    },
)
async def get_video_info(
    bvid: str = "", aid: int = 0, **_kwargs: Any,
) -> dict:
    return await _bili.get_video_info(bvid=bvid or None, aid=aid or None)


# ---------------------------------------------------------------------------
# 3. search_user（无 cookie）
# ---------------------------------------------------------------------------

@register_capability(
    name="bilibili.search_user",
    display_name="搜索 B 站 UP 主",
    description=(
        "搜索 B 站 UP 主。用户说「B 站搜一下 XX UP 主」「找下 X 这个人的频道」时调用。\n\n"
        "参数：\n- keyword: UP 主关键词\n- page: 页码（缺省 1）\n\n"
        "返回 ``{result: [{mid, name, fans, videos, level, sign}, ...], page}``。"
    ),
    category="media",
    consumers=[Consumer.CHAT_AGENT],
    trigger_modes=[TriggerMode.ON_DEMAND],
    icon="user-search",
    health_check=_bili.health_check,
    parameters_schema={
        "type": "object",
        "properties": {
            "keyword": {"type": "string"},
            "page":    {"type": "integer"},
        },
        "required": ["keyword"],
    },
)
async def search_user(
    keyword: str = "", page: int = 1, **_kwargs: Any,
) -> dict:
    return await _bili.search_user(keyword=keyword, page=page)


# ---------------------------------------------------------------------------
# 4. get_user_videos（无 cookie）
# ---------------------------------------------------------------------------

@register_capability(
    name="bilibili.get_user_videos",
    display_name="获取 UP 主投稿列表",
    description=(
        "拿指定 UP 主的最近投稿视频列表。用户说「XX UP 主最近发了啥」「看看 XX "
        "的视频」（先用 search_user 拿到 mid 再调本 capability）时调用。\n\n"
        "参数：\n- mid: UP 主用户 ID（int）\n- page: 页码\n- page_size: 每页（缺省 30）\n\n"
        "返回 ``{mid, page, total, videos: [{bvid, title, duration, play, created, url}, ...]}``。"
    ),
    category="media",
    consumers=[Consumer.CHAT_AGENT],
    trigger_modes=[TriggerMode.ON_DEMAND],
    icon="list",
    health_check=_bili.health_check,
    parameters_schema={
        "type": "object",
        "properties": {
            "mid":       {"type": "integer"},
            "page":      {"type": "integer"},
            "page_size": {"type": "integer"},
        },
        "required": ["mid"],
    },
)
async def get_user_videos(
    mid: int = 0, page: int = 1, page_size: int = 30, **_kwargs: Any,
) -> dict:
    if not mid:
        return {"error": "missing_mid"}
    return await _bili.get_user_videos(mid=int(mid), page=page, page_size=page_size)


# ---------------------------------------------------------------------------
# 5. hot_videos（无 cookie）
# ---------------------------------------------------------------------------

@register_capability(
    name="bilibili.hot_videos",
    display_name="B 站首页热门",
    description=(
        "B 站首页热门视频。用户说「B 站现在有啥热门」「最近 B 站火什么」时调用。\n\n"
        "参数：\n- page: 页码\n- page_size: 每页（缺省 20）\n\n"
        "返回 ``{result: [{bvid, title, owner, view, duration, url}, ...]}``。"
    ),
    category="media",
    consumers=[Consumer.CHAT_AGENT],
    trigger_modes=[TriggerMode.ON_DEMAND],
    icon="flame",
    health_check=_bili.health_check,
    parameters_schema={
        "type": "object",
        "properties": {
            "page":      {"type": "integer"},
            "page_size": {"type": "integer"},
        },
    },
)
async def hot_videos(
    page: int = 1, page_size: int = 20, **_kwargs: Any,
) -> dict:
    return await _bili.hot_videos(page=page, page_size=page_size)


# ---------------------------------------------------------------------------
# 6. get_ranking（无 cookie）
# ---------------------------------------------------------------------------

@register_capability(
    name="bilibili.get_ranking",
    display_name="B 站排行榜",
    description=(
        "B 站排行榜（综合 / 新人 / 原创）。用户说「B 站排行榜」「这周 B 站排行」"
        "时调用。\n\n"
        "参数：\n"
        "- rank_type: 'all'（综合，默认）/ 'rookie'（新人）/ 'origin'（原创）\n"
        "- day: 时间窗，3 或 7（缺省 3）\n\n"
        "返回 ``{rank_type, day, result: [{bvid, title, owner, view, score, url}, ...]}``。"
    ),
    category="media",
    consumers=[Consumer.CHAT_AGENT],
    trigger_modes=[TriggerMode.ON_DEMAND],
    icon="bar-chart-3",
    health_check=_bili.health_check,
    parameters_schema={
        "type": "object",
        "properties": {
            "rank_type": {"type": "string", "enum": ["all", "rookie", "origin"]},
            "day":       {"type": "integer", "enum": [3, 7]},
        },
    },
)
async def get_ranking(
    rank_type: str = "all", day: int = 3, **_kwargs: Any,
) -> dict:
    return await _bili.get_ranking(rank_type=rank_type, day=day)


# ---------------------------------------------------------------------------
# 7. get_subtitles ⭐（cookie required）
# ---------------------------------------------------------------------------

@register_capability(
    name="bilibili.get_subtitles",
    display_name="获取 B 站视频字幕（用于 LLM 总结）",
    description=(
        "拿 B 站视频字幕用于内容总结。⭐ 杀手 use case：用户说「帮我总结这"
        "个 B 站视频」「这个视频讲了啥」「太长不看」「3 分钟讲完」「视频内容"
        "概括一下」时调用，拿到字幕后用你自己的话**总结**（不要原样输出字幕，"
        "字幕有时间戳 / 重复 / 口语化）。\n\n"
        "策略：优先 AI 字幕（多数视频有）；无 AI 字幕取 UP 主上传字幕；都没"
        "有返 ``source='none'`` —— 此时回话告诉用户「这个视频没有字幕，我没"
        "法看到内容」，**不要瞎编内容**。\n\n"
        "**需要 cookie**（B 站 2024-2025 风控限制）：未配 BILIBILI_SESSDATA 时"
        "返 ``cookie_required``，直接转告用户去 docs/bilibili-setup.md 配。\n\n"
        "参数（二选一）：\n- bvid / aid\n\n"
        "返回 ``{bvid, title, subtitle_text, source: 'ai'|'manual'|'none', "
        "duration, lan, lan_doc}``。"
    ),
    category="media",
    consumers=[Consumer.CHAT_AGENT],
    trigger_modes=[TriggerMode.ON_DEMAND],
    icon="file-text",
    health_check=_bili.health_check,
    parameters_schema={
        "type": "object",
        "properties": {
            "bvid": {"type": "string"},
            "aid":  {"type": "integer"},
        },
    },
)
async def get_subtitles(
    bvid: str = "", aid: int = 0, **_kwargs: Any,
) -> dict:
    return await _bili.get_subtitles(bvid=bvid or None, aid=aid or None)


# ---------------------------------------------------------------------------
# 8. get_my_history（cookie required）
# ---------------------------------------------------------------------------

@register_capability(
    name="bilibili.get_my_history",
    display_name="我的观看历史",
    description=(
        "我的 B 站观看历史。用户说「我最近在 B 站看了啥」「上次看的那个视频"
        "在哪」时调用。需要 ``BILIBILI_SESSDATA`` cookie。\n\n"
        "参数：\n- page_size: 返回条数（缺省 20）\n\n"
        "返回 ``{result: [{bvid, title, view_at, progress, duration, author}, ...]}``。"
    ),
    category="media",
    consumers=[Consumer.CHAT_AGENT],
    trigger_modes=[TriggerMode.ON_DEMAND],
    icon="history",
    health_check=_bili.health_check,
    parameters_schema={
        "type": "object",
        "properties": {"page_size": {"type": "integer"}},
    },
)
async def get_my_history(
    page_size: int = 20, **_kwargs: Any,
) -> dict:
    return await _bili.get_my_history(page_size=page_size)


# ---------------------------------------------------------------------------
# 9. get_my_followings（cookie required）
# ---------------------------------------------------------------------------

@register_capability(
    name="bilibili.get_my_followings",
    display_name="我关注的 UP 主",
    description=(
        "拿我关注的 UP 主列表。用户说「我关注了哪些 UP 主」「我有没有关注 X」时调用。"
        "需要 ``BILIBILI_SESSDATA`` cookie。\n\n"
        "参数：\n- page / page_size\n\n"
        "返回 ``{result: [{mid, name, sign}, ...], total, page}``。"
    ),
    category="media",
    consumers=[Consumer.CHAT_AGENT],
    trigger_modes=[TriggerMode.ON_DEMAND],
    icon="user-check",
    health_check=_bili.health_check,
    parameters_schema={
        "type": "object",
        "properties": {
            "page":      {"type": "integer"},
            "page_size": {"type": "integer"},
        },
    },
)
async def get_my_followings(
    page: int = 1, page_size: int = 20, **_kwargs: Any,
) -> dict:
    return await _bili.get_my_followings(page=page, page_size=page_size)


# ---------------------------------------------------------------------------
# 10. get_later_watch（cookie required）
# ---------------------------------------------------------------------------

@register_capability(
    name="bilibili.get_later_watch",
    display_name="稍后再看",
    description=(
        "拿稍后再看列表。用户说「我的稍后再看里有啥」「之前标记的 B 站视频」时调用。"
        "需要 ``BILIBILI_SESSDATA``。\n\n"
        "返回 ``{result: [{bvid, title, duration, owner, add_at}, ...], count}``。"
    ),
    category="media",
    consumers=[Consumer.CHAT_AGENT],
    trigger_modes=[TriggerMode.ON_DEMAND],
    icon="clock",
    health_check=_bili.health_check,
    parameters_schema={"type": "object", "properties": {}},
)
async def get_later_watch(**_kwargs: Any) -> dict:
    return await _bili.get_later_watch()


# ---------------------------------------------------------------------------
# 11. get_favorites（cookie required）
# ---------------------------------------------------------------------------

@register_capability(
    name="bilibili.get_favorites",
    display_name="我的收藏夹",
    description=(
        "拿我的收藏夹列表（不含夹内视频，第一版只列夹）。用户说「我有哪些 B 站收藏夹」"
        "「我的收藏」时调用。需要 ``BILIBILI_SESSDATA``。\n\n"
        "返回 ``{result: [{fid, title, media_count}, ...], count}``。"
    ),
    category="media",
    consumers=[Consumer.CHAT_AGENT],
    trigger_modes=[TriggerMode.ON_DEMAND],
    icon="star",
    health_check=_bili.health_check,
    parameters_schema={"type": "object", "properties": {}},
)
async def get_favorites(**_kwargs: Any) -> dict:
    return await _bili.get_favorites()


__all__ = [
    "search_video", "get_video_info", "search_user", "get_user_videos",
    "hot_videos", "get_ranking", "get_subtitles",
    "get_my_history", "get_my_followings", "get_later_watch", "get_favorites",
]
