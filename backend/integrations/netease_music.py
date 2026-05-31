"""v3-H chunk 1 — 网易云音乐内置接入（web API + orpheus URL scheme）。

**架构选择**：weapi 加密路径（AES-128-CBC + RSA-1024 to encrypt secret_key）。
理由：

  - weapi 是覆盖最完整、最稳定的内部 API；7 个目标 capability 全部能走通
  - 公开 GET endpoint 只能覆盖 search / playlist_detail / my_playlists 三个
    （daily_recommend / personal_fm / like_song / playlist write 都需要 weapi）
  - 加密参数公开已久（jixunmoe/netease-cloud-music-api、Binaryify/NeteaseCloudMusicApi
    等都用同一个 RSA modulus 与 AES preset），不是逆向破解
  - 体积代价：pycryptodome 一个新 dep（~3MB BSD/PD），已加到 requirements.txt

**播放路径**：拿到歌曲/歌单 ID 后，**不**自己下载流——拼成 ``orpheus://...``
URL scheme，由调用层 ``subprocess.run(["open", url])`` 唤起本地网易云 App
播放。这样不绕过付费/版权校验，也无需处理音频流。

**风控**：headers 完整模拟 Chrome（UA / Referer / Origin），cookie 来自
``settings.netease_music_u``（用户从 Chrome F12 抓 ``MUSIC_U`` cookie 写入
``.env``）。频率仅个人单用户场景，不做 scraping，不批量。

**异常路径**：cookie 缺失 / 失效 / 网络异常一律降级 warn，不阻塞主流程。
"""
from __future__ import annotations

import base64
import json
import logging
import random
import string
from typing import Any, Optional

import requests
from Crypto.Cipher import AES

from backend.config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# weapi 加密常量（公开值；与 jixunmoe / Binaryify 实现一致）
# ---------------------------------------------------------------------------

_AES_PRESET = b"0CoJUm6Qyw8W8jud"
_AES_IV     = b"0102030405060708"
_RSA_MODULUS = int(
    "00e0b509f6259df8642dbc35662901477df22677ec152b5ff68ace615bb7b725"
    "152b3ab17a876aea8a5aa76d2e417629ec4ee341f56135fccf695280104e0312"
    "ecbda92557c93870114af6c9d05c4f7f0c3685b7a46bee255932575cce10b424"
    "d813cfe4875d3e82047b97ddef52741d546b8e289dc6935b3ece0462db0a22b8e7",
    16,
)
_RSA_E = 0x010001


def _aes_encrypt(text: bytes, key: bytes) -> bytes:
    pad = 16 - len(text) % 16
    text = text + bytes([pad]) * pad
    cipher = AES.new(key, AES.MODE_CBC, _AES_IV)
    return base64.b64encode(cipher.encrypt(text))


def _rsa_encrypt_secret(secret: bytes) -> str:
    # 网易云的 RSA "encryption"：把 secret 倒序左 0-pad 到 128 字节，
    # 当作大整数做 modular pow，输出 256 字符 hex
    text = secret[::-1].rjust(128, b"\x00")
    n = int.from_bytes(text, "big")
    encrypted = pow(n, _RSA_E, _RSA_MODULUS)
    return f"{encrypted:0256x}"


def weapi_encrypt(payload: dict) -> dict:
    """把 ``payload`` 编成 weapi POST body：{"params": ..., "encSecKey": ...}。"""
    text = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    secret = "".join(
        random.choices(string.ascii_letters + string.digits, k=16)
    ).encode("utf-8")
    params = _aes_encrypt(_aes_encrypt(text, _AES_PRESET), secret).decode("ascii")
    enc_sec_key = _rsa_encrypt_secret(secret)
    return {"params": params, "encSecKey": enc_sec_key}


# ---------------------------------------------------------------------------
# 风控 headers（模拟 Chrome）
# ---------------------------------------------------------------------------

_BASE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://music.163.com/",
    "Origin":  "https://music.163.com",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "X-Requested-With": "XMLHttpRequest",
}

_BASE_URL  = "https://music.163.com"
_DEFAULT_TIMEOUT = 8


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------

class NeteaseAPIError(RuntimeError):
    """网易云 API 调用失败（HTTP 非 2xx / cookie 失效 / 业务 code != 200）。"""


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class NeteaseClient:
    """同步 client；外层 capability 用 ``asyncio.to_thread`` 包装。

    所有 weapi POST 都自动注入 cookie + csrf_token。``MUSIC_U`` 没配置时
    保留对象可用，但调用业务接口会抛 NeteaseAPIError——上层 health_check
    应先看 ``has_credentials`` 决定是否降级 warn。
    """

    def __init__(self, music_u: Optional[str] = None) -> None:
        self._music_u = (music_u if music_u is not None else settings.netease_music_u) or ""
        self._user_id: Optional[int] = None  # 懒查；首次需要时 fetch

    @property
    def has_credentials(self) -> bool:
        return bool(self._music_u)

    # -- low-level ----------------------------------------------------------

    def _cookies(self) -> dict:
        if not self._music_u:
            return {}
        # 加上 __remember_me 让风控更像登录态
        return {
            "MUSIC_U": self._music_u,
            "__remember_me": "true",
            "os": "pc",
            "appver": "2.9.7",
        }

    def _weapi_post(self, path: str, payload: dict) -> dict:
        if not self._music_u:
            raise NeteaseAPIError("未配置 NETEASE_MUSIC_U cookie；无法调用网易云 API")
        url = f"{_BASE_URL}/weapi{path}"
        body = weapi_encrypt({**payload, "csrf_token": ""})
        try:
            resp = requests.post(
                url,
                data=body,
                headers=_BASE_HEADERS,
                cookies=self._cookies(),
                timeout=_DEFAULT_TIMEOUT,
            )
        except requests.RequestException as exc:
            raise NeteaseAPIError(f"网络异常：{exc}") from exc
        # 2026-05-30 Patch B: HTTP non-200 时 log 完整 body(不截断)·
        # 抛错文字仍截短防爆。下次 NCM rotation 时 log 里直接看完整 server 解释。
        if resp.status_code != 200:
            try:
                full_body = resp.text
            except Exception:
                full_body = "<decode-failed>"
            logger.warning(
                "[netease] weapi HTTP %s path=%s body_len=%d body=%r",
                resp.status_code, path, len(full_body), full_body,
            )
            raise NeteaseAPIError(f"HTTP {resp.status_code}: {full_body[:200]}")
        # 2026-05-30 Patch B: resp.json() 失败时 ·
        #   1. 先去 UTF-8 BOM 重试 json.loads(text.lstrip('﻿'))
        #   2. log raw bytes hex 前 100 字节(诊断 BOM / 编码 / chunked 错位)
        #   3. 仍失败抛 · log 行已含 hex 供 PM 诊断
        try:
            data = resp.json()
        except ValueError as exc:
            txt = resp.text or ""
            stripped = txt.lstrip("﻿")
            try:
                data = json.loads(stripped)
                logger.info(
                    "[netease] BOM-stripped JSON parse succeeded · path=%s "
                    "(原 ValueError=%s)", path, exc,
                )
            except ValueError:
                raw_bytes = resp.content[:100] if resp.content else b""
                logger.warning(
                    "[netease] resp.json failed · path=%s · content-type=%r "
                    "· body_len=%d · raw_hex=%s · body=%r",
                    path,
                    resp.headers.get("Content-Type"),
                    len(txt),
                    raw_bytes.hex(),
                    txt[:300],
                )
                raise NeteaseAPIError(f"返回非 JSON：{txt[:200]}") from exc
        # 2026-05-30 Patch B 回归补丁: `resp.json()` / `json.loads(stripped)`
        # 返非 dict (eg JSON string 字面量 / null / list / number) 时早抛 ·
        # 比让 data.get("code") AttributeError 信息可读。
        if not isinstance(data, dict):
            txt_preview = (resp.text or "")[:300]
            logger.warning(
                "[netease] non-dict JSON response · path=%s · type=%s · body=%r",
                path, type(data).__name__, txt_preview,
            )
            raise NeteaseAPIError(
                f"响应不是 JSON object · type={type(data).__name__}: {txt_preview[:200]}"
            )
        code = data.get("code")
        if code == 301 or code == 401:
            raise NeteaseAPIError("cookie 失效或账号未登录，请重新抓 MUSIC_U")
        if code != 200:
            # Patch B: msg 字段(NCM 新版常用)优先于 message(老版) · 提高真错可见度
            raise NeteaseAPIError(
                f"API code={code}: {data.get('message') or data.get('msg') or data}"
            )
        return data

    # -- helpers ------------------------------------------------------------

    def _ensure_user_id(self) -> int:
        if self._user_id is not None:
            return self._user_id
        data = self._weapi_post("/w/nuser/account/get", {})
        profile = (data.get("profile") or {}) if isinstance(data, dict) else {}
        uid = profile.get("userId")
        if not isinstance(uid, int):
            raise NeteaseAPIError("无法从 account/get 拿 userId（cookie 可能失效）")
        self._user_id = uid
        return uid

    @staticmethod
    def _normalize_song(song: dict) -> dict:
        """统一字段，跨接口（搜索结果 / 歌单详情 / personal_fm）都能 normalize。"""
        artists_field = song.get("ar") or song.get("artists") or []
        artists = [a.get("name") for a in artists_field if isinstance(a, dict) and a.get("name")]
        album_field = song.get("al") or song.get("album") or {}
        return {
            "id":      song.get("id"),
            "name":    song.get("name") or "",
            "artists": artists,
            "album":   (album_field.get("name") if isinstance(album_field, dict) else "") or "",
        }

    # -- public API ---------------------------------------------------------

    def daily_recommend(self) -> list[dict]:
        """今日推荐歌曲（每日 30 首）。"""
        data = self._weapi_post("/v2/discovery/recommend/songs", {})
        # 2026-05-30 Patch B 回归补丁: 防 NCM 返 {code:200, data:<非 dict>}
        # 风控/异常响应 · 让函数返 [] 而非 AttributeError。
        inner = data.get("data")
        if not isinstance(inner, dict):
            logger.warning(
                "[netease] daily_recommend: data['data'] not dict · type=%s · returning []",
                type(inner).__name__,
            )
            return []
        raw_list = inner.get("dailySongs") or []
        return [self._normalize_song(s) for s in raw_list if isinstance(s, dict)]

    def personal_fm(self) -> list[dict]:
        """私人 FM / 心动模式当前批次（一次返多首，App 自己按顺序播）。"""
        data = self._weapi_post("/v1/radio/get", {})
        # 2026-05-30 Patch B 回归补丁: 同款防御
        raw_list = data.get("data")
        if not isinstance(raw_list, list):
            logger.warning(
                "[netease] personal_fm: data['data'] not list · type=%s · returning []",
                type(raw_list).__name__,
            )
            return []
        return [self._normalize_song(s) for s in raw_list if isinstance(s, dict)]

    def my_playlists(self, limit: int = 100) -> list[dict]:
        """用户所有歌单（含红心，红心通常是第一项 specialType=5）。"""
        uid = self._ensure_user_id()
        data = self._weapi_post(
            "/user/playlist", {"uid": uid, "limit": limit, "offset": 0},
        )
        # 2026-05-30 Patch B 回归补丁: data["playlist"] 必须是 list
        raw = data.get("playlist")
        if not isinstance(raw, list):
            logger.warning(
                "[netease] my_playlists: data['playlist'] not list · type=%s · returning []",
                type(raw).__name__,
            )
            return []
        out: list[dict] = []
        for p in raw:
            if not isinstance(p, dict):
                continue
            out.append({
                "id":          p.get("id"),
                "name":        p.get("name") or "",
                "track_count": p.get("trackCount") or 0,
                "is_liked":    p.get("specialType") == 5,
            })
        return out

    def playlist_detail(self, playlist_id: int) -> dict:
        data = self._weapi_post(
            "/v6/playlist/detail", {"id": int(playlist_id), "n": 1000, "s": 0},
        )
        # 2026-05-30 Patch B 回归补丁: data["playlist"] 必须是 dict
        pl = data.get("playlist")
        if not isinstance(pl, dict):
            logger.warning(
                "[netease] playlist_detail(%s): data['playlist'] not dict · type=%s · returning empty",
                playlist_id, type(pl).__name__,
            )
            return {"id": int(playlist_id), "name": "", "tracks": []}
        tracks = pl.get("tracks") if isinstance(pl.get("tracks"), list) else []
        return {
            "id":     pl.get("id"),
            "name":   pl.get("name") or "",
            "tracks": [self._normalize_song(t) for t in tracks if isinstance(t, dict)],
        }

    def search(self, keyword: str, search_type: str = "song", limit: int = 20) -> list[dict]:
        """搜索；type 支持 song / album / artist / playlist。"""
        type_map = {"song": 1, "album": 10, "artist": 100, "playlist": 1000}
        t = type_map.get(search_type, 1)
        data = self._weapi_post(
            "/cloudsearch/get/web",
            {"s": keyword, "type": t, "offset": 0, "limit": limit, "total": True},
        )
        # 2026-05-30 Patch B 回归补丁: NCM 风控时 data["result"] 可能返
        # 非空字符串(eg "frequent_visit" / "need_login") 不是 dict ·
        # 原 `data.get("result") or {}` 短路保留 str · 下面 result.get(...)
        # AttributeError。改 isinstance 检查 · 非 dict 视为空 search 结果 + log。
        result = data.get("result")
        if not isinstance(result, dict):
            logger.warning(
                "[netease] search: data['result'] not dict · type=%s · value=%r · returning []",
                type(result).__name__, result if isinstance(result, (str, int, float, bool)) else "(non-primitive)",
            )
            return []
        if t == 1:
            songs = result.get("songs") or []
            return [self._normalize_song(s) for s in songs if isinstance(s, dict)]
        if t == 10:
            return [{
                "id":   a.get("id"),
                "name": a.get("name") or "",
                "artist": (a.get("artist") or {}).get("name") or "",
            } for a in result.get("albums") or [] if isinstance(a, dict)]
        if t == 100:
            return [{
                "id": a.get("id"), "name": a.get("name") or "",
            } for a in result.get("artists") or [] if isinstance(a, dict)]
        if t == 1000:
            return [{
                "id":   p.get("id"),
                "name": p.get("name") or "",
                "track_count": p.get("trackCount") or 0,
            } for p in result.get("playlists") or [] if isinstance(p, dict)]
        return []

    def like_song(self, song_id: int, like: bool = True) -> bool:
        """加 / 取消红心。"""
        data = self._weapi_post(
            "/song/like",
            {"trackId": int(song_id), "like": bool(like), "time": 25},
        )
        return data.get("code") == 200

    def add_to_playlist(self, playlist_id: int, song_id: int) -> bool:
        """添加歌曲到指定歌单（op=add；删除走 op=del，本 chunk 不暴露）。"""
        data = self._weapi_post(
            "/playlist/manipulate/tracks",
            {
                "op":         "add",
                "pid":        int(playlist_id),
                "trackIds":   json.dumps([int(song_id)]),
                "imme":       "true",
            },
        )
        return data.get("code") == 200

    # -- URL scheme ---------------------------------------------------------

    # v3.5 chunk 6b：返回可直接喂 mpv 的 song 播放 URL。
    # 走 /song/enhance/player/url/v1（NCM web 网页播放器同款 endpoint），
    # br 默认 320kbps（webdav 上限；VIP / 大会员 trial 时 br 会被自动 clamp）。
    # 试听片段（VIP / 付费下架歌曲）API 返 freeTrialInfo 字段 + url 仍有效但
    # 只有前 ~30s。is_trial 由上层 normalize 后透传给 capability，让 LLM 提示用户。
    #
    # 2026-05-30 Patch A trial #1: 旧 payload {ids, br:320000} → 全 400(`参数错误`)。
    # 2024 NCM rotation 后 `/song/enhance/player/url/v1` 老 br 字段被淘汰 ·
    # 改用 `level` 字符串(standard/higher/exhigh/lossless/hires) + `encodeType`。
    # 第 1 轮 trial: level=exhigh + encodeType=flac (320kbps 等价档 + 无损 flac)。
    # 仍 400 时 PM 真机反馈 · CC 下一轮降到 level=standard / encodeType=mp3 · 或切
    # 端点 /v2。br 参数保留作 caller 兼容(映射到 level)。
    _BR_TO_LEVEL = {
        320000: "exhigh",
        192000: "higher",
        128000: "standard",
        999000: "lossless",
    }

    def get_song_url(self, song_id: int, br: int = 320000) -> dict:
        """拿 song 直链播放 URL（用于 mpv 本地播放）。

        返回 ``{url, br, type, size, is_trial, song_id}``。URL 失效（VIP 下架 /
        地区限制）时 ``url`` 会是空字符串或 None —— 调用方需检查后做 fallback。
        """
        sid = int(song_id)
        # Patch A trial #1: 旧 {ids, br} → 新 {ids, level, encodeType}
        level = self._BR_TO_LEVEL.get(int(br), "exhigh")
        payload = {
            "ids": json.dumps([sid]),
            "level": level,
            "encodeType": "flac",
        }
        data = self._weapi_post("/song/enhance/player/url/v1", payload)
        items = data.get("data") or []
        if not items:
            return {
                "song_id": sid,
                "url": "",
                "is_trial": False,
                "note": "no data returned",
            }
        item = items[0] or {}
        free_trial = item.get("freeTrialInfo") or item.get("freeTimeTrialPrivilege")
        return {
            "song_id": sid,
            "url": item.get("url") or "",
            "br": item.get("br"),
            "type": item.get("type"),
            "size": item.get("size"),
            "is_trial": bool(free_trial),
            "expires_at_hint": item.get("expi"),
        }

    @staticmethod
    def play_url_scheme(kind: str, item_id: int) -> str:
        """拼装 ``orpheus://`` URL scheme。

        autoplay 语义（社区共识，多个 NCM-launcher 整合一致）：

        * ``orpheus://{song,playlist,album}/<id>``        —— 导航到该页，**不**自动播放
        * ``orpheus://{song,playlist,album}/<id>/play``   —— 导航 + 立即播放（推荐）
        * ``orpheus://artist/<id>``                       —— 仅导航（艺人页没有"播放整页"语义）
        * ``orpheus://personalFM``                        —— 直接进 FM 模式，本身即触发播放

        本 chunk 1 patch 把 song/playlist/album 默认走 /play 后缀（chunk 1 验证后
        发现仅导航不播放，需用户手动点播放键）。
        """
        if kind not in {"song", "playlist", "album", "artist"}:
            raise ValueError(f"unsupported kind: {kind!r}")
        if kind == "artist":
            return f"orpheus://artist/{int(item_id)}"
        return f"orpheus://{kind}/{int(item_id)}/play"


# ---------------------------------------------------------------------------
# Module-level singleton + health
# ---------------------------------------------------------------------------

_client: Optional[NeteaseClient] = None


def get_client() -> NeteaseClient:
    global _client
    if _client is None:
        _client = NeteaseClient()
    return _client


def _reset_client_cache() -> None:
    global _client
    _client = None


async def health_check() -> dict:
    """三档：

    * ``warn``    —— 未配 cookie / 网络异常 / cookie 失效
    * ``healthy`` —— 已配 cookie 且 account/get 能拿到 user_id
    """
    client = get_client()
    if not client.has_credentials:
        return {
            "status": "warn",
            "error": (
                "未配置 NETEASE_MUSIC_U cookie。Chrome 登录 music.163.com "
                "→ F12 → Application → Cookies 复制 MUSIC_U 写入 .env，"
                "详见 docs/netease-music-setup.md"
            ),
        }
    import asyncio
    try:
        uid = await asyncio.to_thread(client._ensure_user_id)
    except NeteaseAPIError as exc:
        return {"status": "warn", "error": f"网易云 cookie 校验失败：{exc}"}
    except Exception as exc:
        return {"status": "warn", "error": f"网易云健康检查异常：{exc}"}
    return {"status": "healthy", "error": None, "user_id": uid}
