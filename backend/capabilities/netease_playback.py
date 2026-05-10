"""v3.5 chunk 6b — 网易云 mpv 本地自解码播放 capability。

6 个 capability:
  - netease.play_song(song_id)
  - netease.play_playlist(playlist_id)
  - netease.pause
  - netease.resume
  - netease.stop
  - netease.next_in_queue

与 chunk 1 ``netease.*`` 数据查询 capability 并列（chunk 1 那些走 NCM 客户
端 URL Scheme 启动播放；本 chunk 走 mpv 子进程自解码播放）。两套并存：
* chunk 1 路径：NCM 客户端有歌词 / 动画 / 完整曲库，但 URL Scheme 不可
  靠（chunk 1 partial 已封存）
* chunk 6b 路径：mpv 自解码，自动播放真闭环，无歌词 / 动画，会员歌曲走
  试听片段

chunk 1 ``netease.like_current`` 仍 work：现在能从 mpv state 拿当前 song_id
（前提是本 chunk capability 启动的播放）。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from backend.capabilities import Consumer, TriggerMode, register_capability
from backend.integrations import mpv_player as _mpv
from backend.integrations import netease_music as _nem

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Health：mpv health + NCM cookie 双重
# ---------------------------------------------------------------------------

async def _combined_health() -> dict:
    mpv_h = await _mpv.health_check()
    nem_h = await _nem.health_check()
    if mpv_h.get("status") == "error":
        return mpv_h
    if nem_h.get("status") == "error":
        return nem_h
    # 两侧任一 warn 都退化整体 warn，给 UI 完整 detail
    overall = "healthy"
    if mpv_h.get("status") != "healthy" or nem_h.get("status") != "healthy":
        overall = "warn"
    return {
        "status": overall,
        "mpv": mpv_h,
        "netease": nem_h,
    }


# ---------------------------------------------------------------------------
# 1. play_song
# ---------------------------------------------------------------------------

@register_capability(
    name="netease.local_play_song",
    display_name="播放网易云单曲",
    description=(
        "本地 mpv 自解码播放网易云单曲。用户说「放 X 这首歌」「来一首 Y」"
        "「听一下 Z」时（先用 netease.search 拿 song_id 再调本 capability）"
        "触发。**自动播放真闭环**——不依赖 NCM 客户端是否打开。\n\n"
        "VIP / 付费下架歌曲返试听片段（~30s），返回字段 ``is_trial=True``，"
        "如实告诉用户「这是试听片段」。\n\n"
        "参数：\n- song_id: NCM 歌曲 ID（必填）\n\n"
        "返回 ``{status, url, is_trial, song_id}``；URL 失效 → ``{error: 'url_unavailable'}``。"
    ),
    category="media",
    consumers=[Consumer.CHAT_AGENT],
    trigger_modes=[TriggerMode.ON_DEMAND],
    icon="play",
    health_check=_combined_health,
    parameters_schema={
        "type": "object",
        "properties": {"song_id": {"type": "integer"}},
        "required": ["song_id"],
    },
)
async def play_song(song_id: int = 0, **_kwargs: Any) -> dict:
    if not song_id:
        return {"error": "missing_song_id"}
    mpv_h = await _mpv.health_check()
    if mpv_h.get("status") == "error":
        return mpv_h  # mpv_not_installed + hint
    if not _nem.get_client().has_credentials():
        return {
            "error": "cookie_required",
            "hint": "请在 .env 配置 NETEASE_MUSIC_U（详见 docs/netease-music-setup.md）",
        }
    # 拿 song/url
    try:
        info = await asyncio.to_thread(
            _nem.get_client().get_song_url, int(song_id),
        )
    except Exception as exc:
        return {"error": "netease_api_error", "detail": str(exc)[:200]}
    url = info.get("url") or ""
    if not url:
        return {
            "error": "url_unavailable",
            "song_id": int(song_id),
            "detail": "VIP 下架 / 地区限制 / 已下线",
        }
    # 喂 mpv 播
    try:
        await _mpv.get_player().play(url, meta={
            "title": f"NCM {song_id}",  # capability 层没拿 song name，由 LLM 自填
            "artist": "网易云音乐",
        })
    except Exception as exc:
        return {"error": "mpv_play_failed", "detail": str(exc)[:200]}
    return {
        "status": "playing",
        "song_id": int(song_id),
        "url": url[:80] + "..." if len(url) > 80 else url,
        "is_trial": info.get("is_trial", False),
        "br": info.get("br"),
        "note": "试听片段（~30s）" if info.get("is_trial") else None,
    }


# ---------------------------------------------------------------------------
# 2. play_playlist
# ---------------------------------------------------------------------------

@register_capability(
    name="netease.local_play_playlist",
    display_name="播放网易云歌单",
    description=(
        "本地 mpv 播放网易云歌单全曲。用户说「放 X 歌单」「听一下我的 Y 歌单」"
        "时调用（先用 netease.my_playlists 或 netease.search 拿 playlist_id 再调）。\n\n"
        "实施：拿歌单全曲 → 第一首立刻 play + 其余入 mpv 内部队列。后续"
        "调 netease.next_in_queue 切下一首；stop 清队列。\n\n"
        "参数：\n- playlist_id: 歌单 ID\n- limit: 最多入队曲数（缺省 50）\n\n"
        "返回 ``{status, playlist_id, queued, first_song_id}``。"
    ),
    category="media",
    consumers=[Consumer.CHAT_AGENT],
    trigger_modes=[TriggerMode.ON_DEMAND],
    icon="list-music",
    health_check=_combined_health,
    parameters_schema={
        "type": "object",
        "properties": {
            "playlist_id": {"type": "integer"},
            "limit": {"type": "integer"},
        },
        "required": ["playlist_id"],
    },
)
async def play_playlist(
    playlist_id: int = 0, limit: int = 50, **_kwargs: Any,
) -> dict:
    if not playlist_id:
        return {"error": "missing_playlist_id"}
    mpv_h = await _mpv.health_check()
    if mpv_h.get("status") == "error":
        return mpv_h
    if not _nem.get_client().has_credentials():
        return {
            "error": "cookie_required",
            "hint": "请在 .env 配置 NETEASE_MUSIC_U",
        }
    # 拿歌单详情
    try:
        detail = await asyncio.to_thread(
            _nem.get_client().playlist_detail, int(playlist_id),
        )
    except Exception as exc:
        return {"error": "netease_api_error", "detail": str(exc)[:200]}
    tracks = detail.get("tracks") or []
    if not tracks:
        return {"error": "empty_playlist", "playlist_id": int(playlist_id)}
    tracks = tracks[: int(limit)]
    # 拿第一首 URL + 余下批量 URL（playlist 多首串行拿 song/url；并发不是必须，
    # NCM API 实测 weapi 串行 50 首 ~3s 在可接受范围内）
    player = _mpv.get_player()
    player.queue_clear()
    first_song = tracks[0]
    first_id = first_song.get("id") or first_song.get("song_id")
    if not first_id:
        return {"error": "playlist_track_no_id"}
    # 第一首立即 play
    try:
        first_info = await asyncio.to_thread(
            _nem.get_client().get_song_url, int(first_id),
        )
        first_url = first_info.get("url") or ""
        if not first_url:
            return {"error": "first_track_unavailable", "song_id": first_id}
        await player.play(first_url, meta={
            "title": first_song.get("name") or f"NCM {first_id}",
            "artist": ", ".join(
                a.get("name", "") for a in (first_song.get("ar") or [])
            ) or "网易云音乐",
        })
    except Exception as exc:
        return {"error": "mpv_play_failed", "detail": str(exc)[:200]}

    # 后续入队（best-effort：单曲拉 URL 失败跳过）
    queued = 1
    for t in tracks[1:]:
        sid = t.get("id") or t.get("song_id")
        if not sid:
            continue
        try:
            info = await asyncio.to_thread(
                _nem.get_client().get_song_url, int(sid),
            )
            u = info.get("url") or ""
            if not u:
                continue
            player.queue_extend([{
                "url": u,
                "meta": {
                    "title": t.get("name") or f"NCM {sid}",
                    "artist": ", ".join(
                        a.get("name", "") for a in (t.get("ar") or [])
                    ) or "网易云音乐",
                },
            }])
            queued += 1
        except Exception as exc:
            logger.warning("[netease_playback] skip track %s: %s", sid, exc)
    return {
        "status": "playing",
        "playlist_id": int(playlist_id),
        "queued": queued,
        "first_song_id": int(first_id),
    }


# ---------------------------------------------------------------------------
# 3-6. transport controls
# ---------------------------------------------------------------------------

@register_capability(
    name="netease.local_pause",
    display_name="暂停 mpv 播放",
    description=(
        "暂停当前 mpv 播放（保留进度，可 resume）。用户说「暂停 / 停一下"
        " / 等等」时调用。仅作用于 mpv（chunk 6b）。NCM 客户端 / Apple "
        "Music / Spotify 走 chunk 1 ``media.play_pause``（跨来源系统媒体键）。"
    ),
    category="media",
    consumers=[Consumer.CHAT_AGENT],
    trigger_modes=[TriggerMode.ON_DEMAND],
    icon="pause",
    health_check=_combined_health,
    parameters_schema={"type": "object", "properties": {}},
)
async def pause(**_kwargs: Any) -> dict:
    try:
        return await _mpv.get_player().pause()
    except Exception as exc:
        return {"error": "mpv_command_failed", "detail": str(exc)[:200]}


@register_capability(
    name="netease.local_resume",
    display_name="恢复 mpv 播放",
    description=(
        "恢复暂停的 mpv 播放。用户说「继续 / 接着放 / 恢复播放」时调用。"
    ),
    category="media",
    consumers=[Consumer.CHAT_AGENT],
    trigger_modes=[TriggerMode.ON_DEMAND],
    icon="play",
    health_check=_combined_health,
    parameters_schema={"type": "object", "properties": {}},
)
async def resume(**_kwargs: Any) -> dict:
    try:
        return await _mpv.get_player().resume()
    except Exception as exc:
        return {"error": "mpv_command_failed", "detail": str(exc)[:200]}


@register_capability(
    name="netease.local_stop",
    display_name="停止 mpv 播放 + 清队列",
    description=(
        "停止 mpv 播放并清空播放队列。用户说「停止 / 关掉音乐 / 别放了」时调用。"
        "区别于 ``pause``：stop 清队列，不可 resume；后续重新 play_song / "
        "play_playlist。"
    ),
    category="media",
    consumers=[Consumer.CHAT_AGENT],
    trigger_modes=[TriggerMode.ON_DEMAND],
    icon="square",
    health_check=_combined_health,
    parameters_schema={"type": "object", "properties": {}},
)
async def stop(**_kwargs: Any) -> dict:
    try:
        player = _mpv.get_player()
        player.queue_clear()
        return await player.stop()
    except Exception as exc:
        return {"error": "mpv_command_failed", "detail": str(exc)[:200]}


@register_capability(
    name="netease.local_next_in_queue",
    display_name="播放队列下一首",
    description=(
        "切到 play_playlist 入队的下一首。用户说「下一首 / 切歌（在 mpv "
        "播歌单时）」时调用。区别于 chunk 1 ``media.next_track``——后者"
        "走系统媒体键转发给 NCM/Apple Music 等前端 app；本 capability 只"
        "在 mpv 自解码模式下用。\n\n队列空时返 ``{status: 'queue_empty'}``。"
    ),
    category="media",
    consumers=[Consumer.CHAT_AGENT],
    trigger_modes=[TriggerMode.ON_DEMAND],
    icon="skip-forward",
    health_check=_combined_health,
    parameters_schema={"type": "object", "properties": {}},
)
async def next_in_queue(**_kwargs: Any) -> dict:
    try:
        return await _mpv.get_player().play_next()
    except Exception as exc:
        return {"error": "mpv_command_failed", "detail": str(exc)[:200]}


__all__ = [
    "play_song", "play_playlist",
    "pause", "resume", "stop", "next_in_queue",
]
