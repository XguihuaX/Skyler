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

    Best-effort：任何步骤失败都 log warning 后返 False，不抛异常——主流程
    （open URL）已经成功，"没自动播"是退化体验，不应让 capability 整体失败。
    """
    if shutil.which("nowplaying-cli") is None:
        logger.warning(
            "[netease] nowplaying-cli 未安装；无法触发自动播放。"
            "请 `brew install nowplaying-cli`",
        )
        return False
    await asyncio.sleep(_NCM_PLAY_DELAY_SEC)
    try:
        proc = await asyncio.to_thread(
            subprocess.run, ["nowplaying-cli", "play"],
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
# 1. 今日推荐
# ---------------------------------------------------------------------------

@register_capability(
    name="netease.daily_recommend",
    display_name="网易云日推",
    description=(
        "拉取网易云今日推荐歌单（30 首）并立刻在本地网易云 App 开始播放。"
        "当用户说\"放日推 / 听今天的推荐 / 给我来点新歌\"时调用，**不**需要"
        "用户给关键词，纯个性化推荐。返回 ``opened`` 与首批 ``songs``。"
    ),
    category="music",
    consumers=[Consumer.CHAT_AGENT],
    trigger_modes=[TriggerMode.ON_DEMAND],
    icon="music",
    parameters_schema={"type": "object", "properties": {}, "required": []},
    health_check=nm.health_check,
)
async def daily_recommend(**_kwargs) -> dict:
    songs = await asyncio.to_thread(_client().daily_recommend)
    if not songs:
        return {"opened": False, "songs": [], "error": "日推为空（账号未登录或当日数据缺失）"}
    # 唤起第一首即开播日推队列（网易云 App 自动接管后续 29 首）
    first = songs[0]
    url = nm.NeteaseClient.play_url_scheme("song", int(first["id"]))
    opened = await _open_url(url)
    autoplay = await _trigger_ncm_play() if opened else False
    return {"opened": opened, "autoplay": autoplay, "first_song": first, "songs": songs[:5]}


# ---------------------------------------------------------------------------
# 2. 私人 FM
# ---------------------------------------------------------------------------

@register_capability(
    name="netease.personal_fm",
    display_name="网易云私人 FM",
    description=(
        "开启网易云私人 FM / 心动模式（无限流推荐，越听越懂你）。当用户说"
        "\"随便放点 / 听点新的 / 私人电台\"等无明确目标的请求时调用。"
        "App 接管后续逻辑——调用方拿到首批信息即可，不需要持续轮询。"
    ),
    category="music",
    consumers=[Consumer.CHAT_AGENT],
    trigger_modes=[TriggerMode.ON_DEMAND],
    icon="radio",
    parameters_schema={"type": "object", "properties": {}, "required": []},
    health_check=nm.health_check,
)
async def personal_fm(**_kwargs) -> dict:
    songs = await asyncio.to_thread(_client().personal_fm)
    # orpheus://personalFM 直接进入私人 FM 模式（社区 canonical 形式；
    # 进入 FM 即触发播放，不需要 /play 后缀，详见 play_url_scheme docstring）
    opened = await _open_url("orpheus://personalFM")
    if not opened and songs:
        opened = await _open_url(nm.NeteaseClient.play_url_scheme("song", int(songs[0]["id"])))
    return {"opened": opened, "songs": songs[:5]}


# ---------------------------------------------------------------------------
# 3. 按关键词放一首歌
# ---------------------------------------------------------------------------

@register_capability(
    name="netease.play_song",
    display_name="按名字放一首歌",
    description=(
        "搜索关键词并播放第一个匹配结果。当用户说\"放某某歌 / 听某歌手的某"
        "某 / 来一首 X\"时调用。keyword 可以是\"歌名\" / \"歌名 歌手\" / "
        "\"歌手 歌名\"任一形式（网易云搜索引擎自己解析）。"
    ),
    category="music",
    consumers=[Consumer.CHAT_AGENT],
    trigger_modes=[TriggerMode.ON_DEMAND],
    icon="music",
    parameters_schema={
        "type": "object",
        "properties": {
            "keyword": {
                "type": "string",
                "description": "搜索词，如 '夜空中最亮的星' / '逃跑计划 夜空' / 'Yesterday Beatles'",
            },
        },
        "required": ["keyword"],
    },
    health_check=nm.health_check,
)
async def play_song(keyword: str, **_kwargs) -> dict:
    songs = await asyncio.to_thread(_client().search, keyword, "song", 5)
    if not songs:
        return {"opened": False, "song": None, "error": f"网易云没搜到「{keyword}」"}
    song = songs[0]
    url = nm.NeteaseClient.play_url_scheme("song", int(song["id"]))
    opened = await _open_url(url)
    autoplay = await _trigger_ncm_play() if opened else False
    return {"opened": opened, "autoplay": autoplay, "song": song, "alternatives": songs[1:]}


# ---------------------------------------------------------------------------
# 4. 列出用户歌单（不直接播；让 LLM 模糊匹配）
# ---------------------------------------------------------------------------

@register_capability(
    name="netease.play_playlist",
    display_name="放某个歌单（先列歌单让 LLM 选）",
    description=(
        "**两步流程的第一步**：列出用户所有自建/收藏歌单（含 emoji / 别名 / "
        "多语言名）。当用户说\"放我的红心歌单 / 放我那个跑步歌单 / 放我工作"
        "用的那个\"时调用。本 capability **不直接播放**——返回完整歌单列"
        "表后，LLM 用语义自己挑最匹配的（如\"跑步\" → \"🏃 跑步专用\"），再"
        "调 ``netease.play_playlist_by_id`` 完成第二步。is_liked=true 标的是"
        "红心歌单。"
    ),
    category="music",
    consumers=[Consumer.CHAT_AGENT],
    trigger_modes=[TriggerMode.ON_DEMAND],
    icon="list",
    parameters_schema={"type": "object", "properties": {}, "required": []},
    health_check=nm.health_check,
)
async def play_playlist(**_kwargs) -> dict:
    playlists = await asyncio.to_thread(_client().my_playlists, 100)
    return {
        "playlists": playlists,
        "next_step": (
            "从上面挑最匹配用户描述的那个，调 netease.play_playlist_by_id "
            "传 playlist_id；不要凭空生成 id。"
        ),
    }


# ---------------------------------------------------------------------------
# 5. 按 ID 播放歌单（接 play_playlist 第二步）
# ---------------------------------------------------------------------------

@register_capability(
    name="netease.play_playlist_by_id",
    display_name="按 ID 播放歌单",
    description=(
        "唤起本地网易云 App 播放指定 ID 的歌单。**调用前必须先**用 "
        "netease.play_playlist 拿到歌单列表 + 用语义模糊匹配挑出 id；"
        "不要凭空生成 playlist_id。"
    ),
    category="music",
    consumers=[Consumer.CHAT_AGENT],
    trigger_modes=[TriggerMode.ON_DEMAND],
    icon="play",
    parameters_schema={
        "type": "object",
        "properties": {
            "playlist_id": {
                "type": "integer",
                "description": "歌单 ID（来自 netease.play_playlist 返回的 id 字段）",
            },
        },
        "required": ["playlist_id"],
    },
    health_check=nm.health_check,
)
async def play_playlist_by_id(playlist_id: int, **_kwargs) -> dict:
    pid = int(playlist_id)
    url = nm.NeteaseClient.play_url_scheme("playlist", pid)
    opened = await _open_url(url)
    autoplay = await _trigger_ncm_play() if opened else False
    return {"opened": opened, "autoplay": autoplay, "playlist_id": pid, "url": url}


# ---------------------------------------------------------------------------
# 6. 红心当前在播
# ---------------------------------------------------------------------------

@register_capability(
    name="netease.like_current",
    display_name="给当前在播加红心",
    description=(
        "给当前正在播放的歌曲加红心（收藏）。**两步流程**：先调 "
        "media.now_playing 拿到当前歌名 + 歌手 → 在本接口里再 search 一次"
        "拿到准确 song id → 调 like。当用户说\"加红心 / 喜欢这首 / 收藏\""
        "时调用。需要本机正在播的就是网易云的歌；播 Apple Music / Spotify "
        "时调本接口会找不到对应 song id。"
    ),
    category="music",
    consumers=[Consumer.CHAT_AGENT],
    trigger_modes=[TriggerMode.ON_DEMAND],
    icon="heart",
    parameters_schema={
        "type": "object",
        "properties": {
            "title":  {"type": "string", "description": "歌名（来自 media.now_playing）"},
            "artist": {"type": "string", "description": "歌手（来自 media.now_playing，可选）"},
        },
        "required": ["title"],
    },
    health_check=nm.health_check,
)
async def like_current(title: str, artist: Optional[str] = None, **_kwargs) -> dict:
    keyword = f"{title} {artist}".strip() if artist else title
    candidates = await asyncio.to_thread(_client().search, keyword, "song", 5)
    if not candidates:
        return {"liked": False, "error": f"网易云没搜到「{keyword}」（不是网易云资源？）"}
    song = candidates[0]
    ok = await asyncio.to_thread(_client().like_song, int(song["id"]), True)
    return {"liked": bool(ok), "song": song}


# ---------------------------------------------------------------------------
# 7. 搜歌（不播放）
# ---------------------------------------------------------------------------

@register_capability(
    name="netease.search",
    display_name="搜网易云（不播放）",
    description=(
        "在网易云搜索关键词；**不播放**，仅返结果。当用户问\"网易云有没有"
        "X / 这首歌的歌手是谁 / 这张专辑里都有什么\"时调用。"
        "search_type 默认 song；可选 album / artist / playlist。"
    ),
    category="music",
    consumers=[Consumer.CHAT_AGENT],
    trigger_modes=[TriggerMode.ON_DEMAND],
    icon="search",
    parameters_schema={
        "type": "object",
        "properties": {
            "keyword": {"type": "string", "description": "搜索关键词"},
            "search_type": {
                "type": "string",
                "enum": ["song", "album", "artist", "playlist"],
                "default": "song",
            },
            "limit": {"type": "integer", "default": 10, "minimum": 1, "maximum": 30},
        },
        "required": ["keyword"],
    },
    health_check=nm.health_check,
)
async def search(
    keyword: str,
    search_type: str = "song",
    limit: int = 10,
    **_kwargs,
) -> dict:
    results = await asyncio.to_thread(
        _client().search, keyword, search_type, max(1, min(30, int(limit))),
    )
    return {"keyword": keyword, "type": search_type, "results": results}
