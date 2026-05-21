"""v3-H chunk 1 — 网易云 capability (上层)。

调底层 ``backend.integrations.netease_music`` client + ``open`` 唤起本地
网易云 App。共 7 个 capability，全部 CHAT_AGENT consumer：

* ``netease.daily_recommend``       —— 今日推荐（直接放）
* ``netease.personal_fm``           —— 私人 FM / 心动模式
* ``netease.play_song``             —— 按关键词搜歌并播
* ``netease.play_playlist``         —— 列出用户歌单（让 LLM 模糊匹配，**不**直接播）
* ``netease.play_playlist_by_id``   —— 按 ID 播放歌单（接 play_playlist 第二步）
* ``netease.like_current``          —— 红心当前在播（与 media.now_playing 配合）
* ``netease.search``                —— 搜歌不播放（信息查询用）

播放路径：拿到 song/playlist id → orpheus:// URL → ``open <url>`` 唤起 App。
description 里写明触发场景，强引导 LLM 在合适时机调用（chunk 1.7 verbatim 模式）。
"""
from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
from typing import Optional

from backend.capabilities import Consumer, TriggerMode, register_capability
from backend.capabilities.media_control import get_nowplaying_bin
from backend.integrations import netease_music as nm

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _open_url(url: str) -> bool:
    """``open <url>`` 唤起 macOS 默认 handler（网易云 App for orpheus://）。

    非 macOS 环境 / open 缺失 → 返回 False（capability 层包成 ``opened=False``
    + 错误提示）；正常返 True。timeout=4s。
    """
    if shutil.which("open") is None:
        return False
    try:
        proc = await asyncio.to_thread(
            subprocess.run, ["open", url],
            capture_output=True, text=True, timeout=4,
        )
    except subprocess.TimeoutExpired:
        logger.warning("[netease] open %s timed out", url)
        return False
    return proc.returncode == 0


# v3-H chunk 1 patch — autoplay 兜底
#
# 上一版 patch 把 URL 改成 ``orpheus://{kind}/<id>/play`` 期望网易云 App
# 自动播放，用户实测发现仍只跳转不开播。Audit 网易云 macOS App 包：
#   * 无 .sdef 文件、Info.plist 无 ``OSAScriptingDefinition`` ⇒ **没有 AppleScript
#     scripting dictionary**。``tell application "NeteaseMusic" to play`` 这条
#     命令会被 osascript 拒绝（"doesn't understand"）—— 本路径不可行。
#   * 中文名 ``"网易云音乐"`` 不被 AppleScript 解析（``running`` 返 false）；
#     只有 CFBundleName ``"NeteaseMusic"`` 可解析，但仅 activate / running 等
#     NSWorkspace 通用命令可用。
#
# 改用 ``nowplaying-cli play``：
#   * 路由经 macOS MediaRemote framework（系统级，跨来源）—— 跟 media.* 同条路径
#   * **idempotent**：已在播则 no-op，不会"toggle 错"
#   * 不抢焦点、不弹 Accessibility / Automation 权限框
#   * timeout=2s；缺失 / 失败一律 log warning 不抛
#
# personalFM URL Scheme 自带 autoplay 语义（验证后仍工作），不走兜底。
_NCM_PLAY_DELAY_SEC = 1.5  # 等 NCM App 启动 + 加载 UI + 注册 MediaRemote 源


async def _trigger_ncm_play() -> bool:
    """``open`` 唤起 NCM 后调用，触发自动播放。

    复用 media_control 已解析的 ``nowplaying-cli`` 绝对路径（Tauri sidecar /
    launchd 等场景下后端 PATH 不一定有 /opt/homebrew/bin，DRY 一份解析逻辑）。

    Best-effort：任何步骤失败都 log warning 后返 False，不抛异常——主流程
    （open URL）已经成功，"没自动播"是退化体验，不应让 capability 整体失败。
    """
    bin_path = get_nowplaying_bin()
    if bin_path is None:
        logger.warning(
            "[netease] nowplaying-cli 未解析到绝对路径；无法触发自动播放。"
            "请 `brew install nowplaying-cli`，或调 media_control.refresh_nowplaying_bin()",
        )
        return False
    await asyncio.sleep(_NCM_PLAY_DELAY_SEC)
    try:
        proc = await asyncio.to_thread(
            subprocess.run, [bin_path, "play"],
            capture_output=True, text=True, timeout=2,
        )
    except subprocess.TimeoutExpired:
        logger.warning("[netease] nowplaying-cli play timed out")
        return False
    if proc.returncode != 0:
        logger.warning(
            "[netease] nowplaying-cli play rc=%d stderr=%s",
            proc.returncode, (proc.stderr or "").strip(),
        )
        return False
    return True


def _client() -> nm.NeteaseClient:
    return nm.get_client()


# ---------------------------------------------------------------------------
# v3.5 chunk 6b hotfix-1：场景类 capability fall through 到 mpv
# ---------------------------------------------------------------------------
#
# 背景：chunk 6b 只改了显式 ``netease.play_*`` 为 ``local_play_*``，**没动**
# 场景类（daily_recommend / personal_fm / play_song(keyword) /
# play_playlist_by_id）。这些仍走 URL Scheme + ``_trigger_ncm_play`` 兜底，
# 用户实测 NCM 客户端跳转后**不自动播放指定歌曲**（只接管系统媒体键），
# capability 却返 ``autoplay: true`` 误导 LLM 回话"已在播放"。
#
# 修法：把"播单曲 / 播单首+其余入队"抽成共享 helper，按 mpv 健康检查
# 三档分支：
#   * mpv healthy + cookie OK → 走 chunk 6b mpv 真闭环，``autoplay=True``
#     诚实（mpv 真在放）
#   * mpv 缺 / cookie 缺 / song_url 失败 → fallback URL Scheme 唤起 NCM，
#     但 ``autoplay=False`` + ``hint`` 字段提示用户「需要 brew install mpv
#     才能自动播放指定歌曲」
#
# 不改 chunk 6b 已 push 的 mpv 路径（``netease.local_*``），只在 chunk 1
# capability 内部 fall through 进去。capability 名 + 返回 schema 向后兼容
# （opened/autoplay/songs 字段保留）。

from backend.integrations import mpv_player as _mpv  # v3.5 chunk 6b


async def _mpv_available_and_cookie_ok() -> bool:
    """组合检查：mpv binary + cookie，两侧任一失败返 False。

    用于场景 capability 在调真实播放前的预检；返 False 时立即走 URL
    Scheme fallback，不会触发 mpv subprocess spawn。
    """
    if not _client().has_credentials:
        return False
    h = await _mpv.health_check()
    return h.get("status") == "healthy"


async def _try_mpv_play_single(song_id: int, *, title: str = "", artist: str = "") -> dict:
    """单曲 mpv 播放（song_id → song_url → mpv.play）。

    成功：``{played: True, is_trial: bool, song_id, url}``
    失败：``{played: False, reason: 'url_unavailable' | 'mpv_error', detail}``
    调用方据此决定整体 capability 返 ``autoplay=True/False``。
    """
    try:
        info = await asyncio.to_thread(_client().get_song_url, int(song_id))
    except Exception as exc:
        return {"played": False, "reason": "netease_api_error", "detail": str(exc)[:120]}
    url = info.get("url") or ""
    if not url:
        return {"played": False, "reason": "url_unavailable", "song_id": int(song_id)}
    try:
        await _mpv.get_player().play(url, meta={
            "title": title or f"NCM {song_id}",
            "artist": artist or "网易云音乐",
        })
    except Exception as exc:
        return {"played": False, "reason": "mpv_error", "detail": str(exc)[:120]}
    return {
        "played": True,
        "is_trial": bool(info.get("is_trial")),
        "song_id": int(song_id),
        "url": url[:80],
    }


async def _try_mpv_play_song_queue(songs: list[dict]) -> dict:
    """播放 song 列表第一首 + 其余入 mpv 队列。``songs`` 必须含 ``id``。

    成功：``{played: True, queued: int, first_song_id, is_trial}``
    失败：``{played: False, reason, detail}``（不入任何队列）
    """
    if not songs:
        return {"played": False, "reason": "empty_song_list"}
    first = songs[0]
    sid = first.get("id") or first.get("song_id")
    if not sid:
        return {"played": False, "reason": "first_song_missing_id"}
    title = first.get("name") or first.get("title") or ""
    artist = _join_artist_names(first.get("ar") or first.get("artists"))
    player = _mpv.get_player()
    player.queue_clear()
    res = await _try_mpv_play_single(int(sid), title=title, artist=artist)
    if not res.get("played"):
        return res
    queued = 1
    # 后续 best-effort 入队（单曲失败跳过；与 local_play_playlist 同 pattern）
    for t in songs[1:]:
        tid = t.get("id") or t.get("song_id")
        if not tid:
            continue
        try:
            info = await asyncio.to_thread(_client().get_song_url, int(tid))
            u = info.get("url") or ""
            if not u:
                continue
            t_title = t.get("name") or t.get("title") or f"NCM {tid}"
            t_artist = _join_artist_names(t.get("ar") or t.get("artists")) or "网易云音乐"
            player.queue_extend([{
                "url": u,
                "meta": {"title": t_title, "artist": t_artist},
            }])
            queued += 1
        except Exception as exc:
            logger.warning("[netease scene] queue extend skip id=%s: %s", tid, exc)
    return {
        "played": True,
        "queued": queued,
        "first_song_id": int(sid),
        "is_trial": res.get("is_trial", False),
    }


def _join_artist_names(items) -> str:
    """提取并 join 艺人名 —— 兼容 raw NCM dict 形态 (``[{name: ...}]``，
    weapi 原始字段) 与集成层 ``_normalize_song`` 已转好的字符串列表
    (``[str]``，``daily_recommend / personal_fm / search / playlist_detail``
    出口形态)。

    hotfix-1 写死 ``a.get("name")`` 假设永远是 dict，runtime 拿到 normalize
    后的字符串列表立刻 ``AttributeError: 'str' object has no attribute
    'get'``。本 helper 用 isinstance 分流，单元测试覆盖两种 shape。
    """
    names: list[str] = []
    for a in items or []:
        if isinstance(a, dict):
            n = a.get("name") or ""
        elif isinstance(a, str):
            n = a
        else:
            continue
        if n:
            names.append(n)
    return ", ".join(names)


def _mpv_unavailable_hint() -> str:
    return (
        "未自动播放指定歌曲：需要 mpv 才能 Skyler 内嵌自解码自动播放。"
        "macOS: ``brew install mpv``；Linux: ``apt install mpv``。"
        "装好后 Skyler 会优先用 mpv，无需重启。NCM 客户端已唤起（仅作 fallback，"
        "用户需手动点播放）。详见 docs/netease-playback-setup.md"
    )



# ---------------------------------------------------------------------------
# 7 internal handlers (per INV-7 §2 P1.netease fold, 2026-05-21):
# daily_recommend / personal_fm / play_song / play_playlist /
# play_playlist_by_id / like_current / search
# 走 dispatcher `netease_web(action=...)`,不再单独 @register_capability。
# ---------------------------------------------------------------------------


async def _handle_daily_recommend(**_kwargs) -> dict:
    songs = await asyncio.to_thread(_client().daily_recommend)
    if not songs:
        return {"opened": False, "autoplay": False, "songs": [],
                "error": "日推为空（账号未登录或当日数据缺失）"}
    first = songs[0]

    if await _mpv_available_and_cookie_ok():
        res = await _try_mpv_play_song_queue(songs[:30])
        if res.get("played"):
            return {
                "opened": True,
                "autoplay": True,
                "backend": "mpv",
                "first_song": first,
                "songs": songs[:5],
                "queued": res.get("queued"),
                "is_trial": res.get("is_trial", False),
            }
        logger.warning(
            "[netease daily_recommend] mpv play failed (%s), falling back to URL Scheme",
            res.get("reason"),
        )

    url = nm.NeteaseClient.play_url_scheme("song", int(first["id"]))
    opened = await _open_url(url)
    return {
        "opened": opened,
        "autoplay": False,
        "backend": "url_scheme",
        "first_song": first,
        "songs": songs[:5],
        "hint": _mpv_unavailable_hint(),
    }


async def _handle_personal_fm(**_kwargs) -> dict:
    songs = await asyncio.to_thread(_client().personal_fm)

    if await _mpv_available_and_cookie_ok():
        res = await _try_mpv_play_song_queue(songs[:10])
        if res.get("played"):
            return {
                "opened": True,
                "autoplay": True,
                "backend": "mpv",
                "songs": songs[:5],
                "queued": res.get("queued"),
                "is_trial": res.get("is_trial", False),
            }
        logger.warning(
            "[netease personal_fm] mpv play failed (%s), falling back",
            res.get("reason"),
        )

    opened = await _open_url("orpheus://personalFM")
    if not opened and songs:
        opened = await _open_url(
            nm.NeteaseClient.play_url_scheme("song", int(songs[0]["id"]))
        )
    return {
        "opened": opened,
        "autoplay": False,
        "backend": "url_scheme_fm",
        "songs": songs[:5],
        "note": (
            "唤起了 NCM 客户端 personalFM 模式。NCM 客户端原生支持 FM "
            "autoplay，开后即播。Skyler 自身未触发播放（装 mpv 后默认走 "
            "Skyler 内嵌路径）。"
        ),
    }


async def _handle_play_song(keyword: str = "", **_kwargs) -> dict:
    if not keyword:
        return {"opened": False, "autoplay": False, "error": "missing_keyword"}
    songs = await asyncio.to_thread(_client().search, keyword, "song", 5)
    if not songs:
        return {"opened": False, "autoplay": False, "song": None,
                "error": f"网易云没搜到「{keyword}」"}
    song = songs[0]

    if await _mpv_available_and_cookie_ok():
        title = song.get("name") or ""
        artist = _join_artist_names(song.get("ar") or song.get("artists"))
        res = await _try_mpv_play_single(int(song["id"]), title=title, artist=artist)
        if res.get("played"):
            return {
                "opened": True,
                "autoplay": True,
                "backend": "mpv",
                "song": song,
                "alternatives": songs[1:],
                "is_trial": res.get("is_trial", False),
            }
        logger.warning(
            "[netease play_song(keyword)] mpv play failed (%s), falling back",
            res.get("reason"),
        )

    url = nm.NeteaseClient.play_url_scheme("song", int(song["id"]))
    opened = await _open_url(url)
    return {
        "opened": opened,
        "autoplay": False,
        "backend": "url_scheme",
        "song": song,
        "alternatives": songs[1:],
        "hint": _mpv_unavailable_hint(),
    }


async def _handle_play_playlist(**_kwargs) -> dict:
    playlists = await asyncio.to_thread(_client().my_playlists, 100)
    return {
        "playlists": playlists,
        "next_step": (
            "从上面挑最匹配用户描述的那个,调 netease_web action=play_playlist_by_id "
            "传 playlist_id;不要凭空生成 id。"
        ),
    }


async def _handle_play_playlist_by_id(playlist_id: int = 0, **_kwargs) -> dict:
    if not playlist_id:
        return {"opened": False, "autoplay": False, "error": "missing_playlist_id"}
    pid = int(playlist_id)

    if await _mpv_available_and_cookie_ok():
        try:
            detail = await asyncio.to_thread(_client().playlist_detail, pid)
        except Exception as exc:
            logger.warning(
                "[netease play_playlist_by_id] playlist_detail failed (%s), falling back",
                str(exc)[:120],
            )
        else:
            tracks = detail.get("tracks") or []
            if tracks:
                res = await _try_mpv_play_song_queue(tracks[:50])
                if res.get("played"):
                    return {
                        "opened": True,
                        "autoplay": True,
                        "backend": "mpv",
                        "playlist_id": pid,
                        "queued": res.get("queued"),
                        "first_song_id": res.get("first_song_id"),
                        "is_trial": res.get("is_trial", False),
                    }
                logger.warning(
                    "[netease play_playlist_by_id] mpv queue play failed (%s), falling back",
                    res.get("reason"),
                )

    url = nm.NeteaseClient.play_url_scheme("playlist", pid)
    opened = await _open_url(url)
    return {
        "opened": opened,
        "autoplay": False,
        "backend": "url_scheme",
        "playlist_id": pid,
        "url": url,
        "hint": _mpv_unavailable_hint(),
    }


async def _handle_like_current(title: str = "", artist: Optional[str] = None, **_kwargs) -> dict:
    if not title:
        return {"liked": False, "error": "missing_title"}
    keyword = f"{title} {artist}".strip() if artist else title
    candidates = await asyncio.to_thread(_client().search, keyword, "song", 5)
    if not candidates:
        return {"liked": False, "error": f"网易云没搜到「{keyword}」（不是网易云资源？）"}
    song = candidates[0]
    ok = await asyncio.to_thread(_client().like_song, int(song["id"]), True)
    return {"liked": bool(ok), "song": song}


async def _handle_search(
    keyword: str = "",
    search_type: str = "song",
    limit: int = 10,
    **_kwargs,
) -> dict:
    if not keyword:
        return {"keyword": "", "type": search_type, "results": [], "error": "missing_keyword"}
    results = await asyncio.to_thread(
        _client().search, keyword, search_type, max(1, min(30, int(limit))),
    )
    return {"keyword": keyword, "type": search_type, "results": results}


# ---------------------------------------------------------------------------
# netease_web dispatcher (INV-7 §2 P1.netease template reuse #3 · web path)
# ---------------------------------------------------------------------------

_NETEASE_WEB_ACTION_HANDLERS = {
    "daily_recommend":     _handle_daily_recommend,
    "personal_fm":         _handle_personal_fm,
    "play_song":           _handle_play_song,
    "play_playlist":       _handle_play_playlist,
    "play_playlist_by_id": _handle_play_playlist_by_id,
    "like_current":        _handle_like_current,
    "search":              _handle_search,
}


@register_capability(
    name="netease_web",
    display_name="网易云 Web API(NCM 客户端 + mpv-first)",
    description=(
        "网易云 web API 路径(mpv 装好 → 内嵌 mpv 自动播 autoplay=true;"
        "否则唤起 NCM 客户端 URL Scheme,autoplay=false)。按 action 选:\n"
        "- daily_recommend:今日推荐 30 首,直接放(用户说『放日推/听今天推荐』)\n"
        "- personal_fm:私人 FM / 心动模式(用户说『随便放点/私人电台』)\n"
        "- play_song:按关键词搜并放(用户说『放某某歌/来一首 X』,需 keyword)\n"
        "- play_playlist:列用户歌单(让你模糊匹配,**不直接播**;两步流程第一步)\n"
        "- play_playlist_by_id:按 ID 放歌单(接 play_playlist 第二步,需 playlist_id)\n"
        "- like_current:红心当前在播(需 media action=now_playing 拿 title/artist 后调本;需 title)\n"
        "- search:搜歌不播(用户问『有没有 X / 歌手是谁』,需 keyword;可指 search_type)\n\n"
        "**何时用 netease_local**(本 cap 的对偶):用户已知 song_id/playlist_id 且想真自动播放时;"
        "本 web cap 的 mpv-first 自动 fallback 已覆盖多数场景,不必手切 local。"
    ),
    category="music",
    consumers=[Consumer.CHAT_AGENT],
    trigger_modes=[TriggerMode.ON_DEMAND],
    icon="music",
    health_check=nm.health_check,
    parameters_schema={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": list(_NETEASE_WEB_ACTION_HANDLERS.keys()),
                "description": "网易云 web API 操作类型",
            },
            "keyword": {
                "type": "string",
                "description": "仅 action=play_song / search 必填,搜索关键词",
            },
            "playlist_id": {
                "type": "integer",
                "description": "仅 action=play_playlist_by_id 必填,歌单 ID(先调 action=play_playlist 拿)",
            },
            "title": {
                "type": "string",
                "description": "仅 action=like_current 必填,歌名(来自 media action=now_playing)",
            },
            "artist": {
                "type": "string",
                "description": "仅 action=like_current 可选,歌手",
            },
            "search_type": {
                "type": "string",
                "enum": ["song", "album", "artist", "playlist"],
                "default": "song",
                "description": "仅 action=search 可选,搜索类型(默 song)",
            },
            "limit": {
                "type": "integer",
                "default": 10,
                "minimum": 1, "maximum": 30,
                "description": "仅 action=search 可选,返回条数(默 10)",
            },
        },
        "required": ["action"],
    },
)
async def netease_web_dispatch(action: str = "", **params) -> dict:
    """Dispatcher: 按 action 路由到 _handle_*,含 3 类必填校验。"""
    handler = _NETEASE_WEB_ACTION_HANDLERS.get(action)
    if handler is None:
        return {
            "ok": False,
            "error": (
                f"unknown action: {action!r}; "
                f"valid: {list(_NETEASE_WEB_ACTION_HANDLERS.keys())}"
            ),
        }
    # action-specific required 字段校验
    if action in ("play_song", "search"):
        if not params.get("keyword"):
            return {"ok": False, "error": f"keyword required when action={action}"}
    elif action == "play_playlist_by_id":
        if not params.get("playlist_id"):
            return {"ok": False, "error": "playlist_id required when action=play_playlist_by_id"}
    elif action == "like_current":
        if not params.get("title"):
            return {"ok": False, "error": "title required when action=like_current"}
    return await handler(**params)


__all__ = [
    "netease_web_dispatch",
]
