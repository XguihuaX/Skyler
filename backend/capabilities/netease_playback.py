"""v3.5 chunk 6b — 网易云 mpv 本地自解码播放 capability。

(2026-05-21 INV-7 §2 P1.netease fold) 6 个旧 cap `netease.local_*` 折叠为
单一 `netease_local` dispatcher,LLM 调用形态:
  netease_local(action="play_song", song_id=N)
  netease_local(action="play_playlist", playlist_id=N, limit=50)
  netease_local(action="pause" | "resume" | "stop" | "next_in_queue")

与 chunk 1 ``netease_web`` web URL Scheme 路径并列。两套并存:
* netease_web 路径:NCM 客户端有歌词 / 动画 / 完整曲库,URL Scheme 不可靠
* netease_local 路径:mpv 自解码,自动播放真闭环,无歌词 / 动画,会员歌曲走
  试听片段

chunk 1 ``netease_web.like_current`` 仍 work:能从 mpv state 拿当前 song_id
(前提是本 chunk capability 启动的播放)。
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
# Health:mpv health + NCM cookie 双重
# ---------------------------------------------------------------------------

async def _combined_health() -> dict:
    mpv_h = await _mpv.health_check()
    nem_h = await _nem.health_check()
    if mpv_h.get("status") == "error":
        return mpv_h
    if nem_h.get("status") == "error":
        return nem_h
    overall = "healthy"
    if mpv_h.get("status") != "healthy" or nem_h.get("status") != "healthy":
        overall = "warn"
    return {
        "status": overall,
        "mpv": mpv_h,
        "netease": nem_h,
    }


# ---------------------------------------------------------------------------
# 6 internal handlers (per INV-7 §2 P1.netease fold, 2026-05-21):
# play_song / play_playlist / pause / resume / stop / next_in_queue
# 走 dispatcher `netease_local(action=...)`,不再单独 @register_capability。
# ---------------------------------------------------------------------------


async def _handle_play_song(song_id: int = 0, **_kwargs: Any) -> dict:
    if not song_id:
        return {"error": "missing_song_id"}
    mpv_h = await _mpv.health_check()
    if mpv_h.get("status") == "error":
        return mpv_h
    if not _nem.get_client().has_credentials:
        return {
            "error": "cookie_required",
            "hint": "请在 .env 配置 NETEASE_MUSIC_U（详见 docs/netease-music-setup.md）",
        }
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
    try:
        await _mpv.get_player().play(url, meta={
            "title": f"NCM {song_id}",
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


async def _handle_play_playlist(
    playlist_id: int = 0, limit: int = 50, **_kwargs: Any,
) -> dict:
    if not playlist_id:
        return {"error": "missing_playlist_id"}
    mpv_h = await _mpv.health_check()
    if mpv_h.get("status") == "error":
        return mpv_h
    if not _nem.get_client().has_credentials:
        return {
            "error": "cookie_required",
            "hint": "请在 .env 配置 NETEASE_MUSIC_U",
        }
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
    player = _mpv.get_player()
    player.queue_clear()
    first_song = tracks[0]
    first_id = first_song.get("id") or first_song.get("song_id")
    if not first_id:
        return {"error": "playlist_track_no_id"}
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


async def _handle_pause(**_kwargs: Any) -> dict:
    try:
        return await _mpv.get_player().pause()
    except Exception as exc:
        return {"error": "mpv_command_failed", "detail": str(exc)[:200]}


async def _handle_resume(**_kwargs: Any) -> dict:
    try:
        return await _mpv.get_player().resume()
    except Exception as exc:
        return {"error": "mpv_command_failed", "detail": str(exc)[:200]}


async def _handle_stop(**_kwargs: Any) -> dict:
    try:
        player = _mpv.get_player()
        player.queue_clear()
        return await player.stop()
    except Exception as exc:
        return {"error": "mpv_command_failed", "detail": str(exc)[:200]}


async def _handle_next_in_queue(**_kwargs: Any) -> dict:
    try:
        return await _mpv.get_player().play_next()
    except Exception as exc:
        return {"error": "mpv_command_failed", "detail": str(exc)[:200]}


# ---------------------------------------------------------------------------
# netease_local dispatcher (INV-7 §2 P1.netease template reuse #3 · local path)
# ---------------------------------------------------------------------------

_NETEASE_LOCAL_ACTION_HANDLERS = {
    "play_song":     _handle_play_song,
    "play_playlist": _handle_play_playlist,
    "pause":         _handle_pause,
    "resume":        _handle_resume,
    "stop":          _handle_stop,
    "next_in_queue": _handle_next_in_queue,
}


@register_capability(
    name="netease_local",
    display_name="网易云本地播放(mpv)",
    description=(
        "网易云本地 mpv 自解码播放(自动播放闭环,不依赖 NCM 客户端)。"
        "按 action 选具体操作:\n"
        "- play_song:放单曲(用户说『放 X / 来一首 Y』,先 netease_web "
        "action=search 拿 song_id 再调本 cap;需 song_id)\n"
        "- play_playlist:放歌单全曲(先 netease_web action=play_playlist "
        "拿 playlist_id 再调本 cap;需 playlist_id,limit 默 50)\n"
        "- pause:暂停 mpv(保留进度,可 resume)\n"
        "- resume:恢复暂停的 mpv 播放\n"
        "- stop:停止 mpv 播放 + 清队列(不可 resume)\n"
        "- next_in_queue:切到 play_playlist 入队的下一首\n\n"
        "VIP/付费下架返试听片段 ~30s(is_trial=True),如实告诉用户。"
    ),
    category="music",
    consumers=[Consumer.CHAT_AGENT],
    trigger_modes=[TriggerMode.ON_DEMAND],
    icon="play",
    health_check=_combined_health,
    parameters_schema={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": list(_NETEASE_LOCAL_ACTION_HANDLERS.keys()),
                "description": "本地 mpv 播放操作类型",
            },
            "song_id": {
                "type": "integer",
                "description": "仅 action=play_song 必填,NCM 歌曲 ID",
            },
            "playlist_id": {
                "type": "integer",
                "description": "仅 action=play_playlist 必填,NCM 歌单 ID",
            },
            "limit": {
                "type": "integer",
                "default": 50,
                "description": "仅 action=play_playlist 可选,最多入队曲数(默 50)",
            },
        },
        "required": ["action"],
    },
)
async def netease_local_dispatch(action: str = "", **params: Any) -> dict:
    """Dispatcher: 按 action 路由到 _handle_*,含 2 类必填校验。"""
    handler = _NETEASE_LOCAL_ACTION_HANDLERS.get(action)
    if handler is None:
        return {
            "ok": False,
            "error": (
                f"unknown action: {action!r}; "
                f"valid: {list(_NETEASE_LOCAL_ACTION_HANDLERS.keys())}"
            ),
        }
    if action == "play_song":
        if not params.get("song_id"):
            return {"ok": False, "error": "song_id required when action=play_song"}
    elif action == "play_playlist":
        if not params.get("playlist_id"):
            return {"ok": False, "error": "playlist_id required when action=play_playlist"}
    return await handler(**params)


__all__ = [
    "netease_local_dispatch",
]
