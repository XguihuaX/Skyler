"""v3-H chunk 1 — macOS 媒体控制 capability。

包装 ``nowplaying-cli``（``brew install nowplaying-cli``）+ ``osascript``
音量控制，给 ChatAgent 5 个跨来源（网易云 / Apple Music / Spotify /
YouTube / Bilibili 网页 …）的播放控制 + "现在在放什么"查询。

跨平台优雅降级（chunk 1.6 IS_MACOS pattern）：
* 非 macOS：所有 capability 仍注册（让前端能力面板看得见），调用即返"仅 macOS 可用"
* macOS 但 nowplaying-cli 缺失：health_check 返 warn 提示 ``brew install nowplaying-cli``
* macOS 已装：正常工作

subprocess.run 全部带 timeout=2s，避免 LLM 调用阻塞 event loop（虽然已用
asyncio.to_thread 隔离，但仍要短超时让用户能感知"卡了"）。
"""
from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
import sys
from typing import Any

from backend.capabilities import Consumer, TriggerMode, register_capability

logger = logging.getLogger(__name__)

IS_MACOS = sys.platform == "darwin"
_CMD_TIMEOUT = 2  # seconds


def _has_nowplaying_cli() -> bool:
    return IS_MACOS and shutil.which("nowplaying-cli") is not None


def _run_sync(cmd: list[str]) -> tuple[int, str, str]:
    """subprocess wrapper —— 返 (returncode, stdout, stderr)。

    超时返 (-1, "", "timeout")；FileNotFoundError 返 (-2, "", "<msg>")。
    """
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=_CMD_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except FileNotFoundError as exc:
        return -2, "", str(exc)
    return proc.returncode, proc.stdout or "", proc.stderr or ""


async def _nowplaying(*subcmd: str) -> tuple[int, str, str]:
    return await asyncio.to_thread(_run_sync, ["nowplaying-cli", *subcmd])


async def _osascript(script: str) -> tuple[int, str, str]:
    return await asyncio.to_thread(_run_sync, ["osascript", "-e", script])


# ---------------------------------------------------------------------------
# health_check
# ---------------------------------------------------------------------------

async def health_check() -> dict:
    if not IS_MACOS:
        return {
            "status": "warn",
            "error": f"媒体控制仅 macOS 可用（当前平台 {sys.platform}）",
        }
    if not _has_nowplaying_cli():
        return {
            "status": "warn",
            "error": (
                "nowplaying-cli 未安装。请 `brew install nowplaying-cli` "
                "（GitHub: kirtan-shah/nowplaying-cli）"
            ),
        }
    return {"status": "healthy"}


# ---------------------------------------------------------------------------
# 1. next_track
# ---------------------------------------------------------------------------

@register_capability(
    name="media.next_track",
    display_name="下一首",
    description=(
        "切到下一首歌（系统级——不限来源：网易云 / Apple Music / Spotify / "
        "YouTube / Bilibili 网页都能切）。当用户说\"下一首 / 切歌 / 换一首 / "
        "不喜欢这首\"时调用。"
    ),
    category="media",
    consumers=[Consumer.CHAT_AGENT],
    trigger_modes=[TriggerMode.ON_DEMAND],
    icon="skip-forward",
    parameters_schema={"type": "object", "properties": {}, "required": []},
    health_check=health_check,
)
async def next_track(**_kwargs) -> dict:
    if not _has_nowplaying_cli():
        return {"ok": False, "error": "nowplaying-cli 未安装；brew install nowplaying-cli"}
    rc, _stdout, stderr = await _nowplaying("next")
    return {"ok": rc == 0, "error": stderr.strip() if rc != 0 else None}


# ---------------------------------------------------------------------------
# 2. previous_track
# ---------------------------------------------------------------------------

@register_capability(
    name="media.previous_track",
    display_name="上一首",
    description=(
        "回到上一首。当用户说\"上一首 / 刚才那首 / 退回去\"时调用。同样跨来源。"
    ),
    category="media",
    consumers=[Consumer.CHAT_AGENT],
    trigger_modes=[TriggerMode.ON_DEMAND],
    icon="skip-back",
    parameters_schema={"type": "object", "properties": {}, "required": []},
    health_check=health_check,
)
async def previous_track(**_kwargs) -> dict:
    if not _has_nowplaying_cli():
        return {"ok": False, "error": "nowplaying-cli 未安装；brew install nowplaying-cli"}
    rc, _stdout, stderr = await _nowplaying("previous")
    return {"ok": rc == 0, "error": stderr.strip() if rc != 0 else None}


# ---------------------------------------------------------------------------
# 3. play_pause
# ---------------------------------------------------------------------------

@register_capability(
    name="media.play_pause",
    display_name="播放 / 暂停",
    description=(
        "切换播放 / 暂停状态（toggle）。当用户说\"暂停 / 播放 / 继续 / 停一下"
        " / 接着放\"时调用。toggle 语义——已播则停、已停则播。跨来源。"
    ),
    category="media",
    consumers=[Consumer.CHAT_AGENT],
    trigger_modes=[TriggerMode.ON_DEMAND],
    icon="play-pause",
    parameters_schema={"type": "object", "properties": {}, "required": []},
    health_check=health_check,
)
async def play_pause(**_kwargs) -> dict:
    if not _has_nowplaying_cli():
        return {"ok": False, "error": "nowplaying-cli 未安装；brew install nowplaying-cli"}
    rc, _stdout, stderr = await _nowplaying("togglePlayPause")
    return {"ok": rc == 0, "error": stderr.strip() if rc != 0 else None}


# ---------------------------------------------------------------------------
# 4. now_playing
# ---------------------------------------------------------------------------

def _parse_nowplaying_get(stdout: str, fields: list[str]) -> dict:
    """``nowplaying-cli get title artist album`` 输出按行返字段，缺失行内是空。"""
    lines = stdout.splitlines()
    out: dict = {}
    for i, fld in enumerate(fields):
        val = lines[i].strip() if i < len(lines) else ""
        out[fld] = val if val and val != "null" else None
    return out


@register_capability(
    name="media.now_playing",
    display_name="当前在播",
    description=(
        "查当前系统在播什么歌（歌名 / 歌手 / 专辑），跨来源（网易云 / Apple "
        "Music / Spotify / YouTube / Bilibili 网页都行）。当用户问\"现在在"
        "放什么 / 这首叫啥 / 谁唱的 / 这是什么歌\"时调用。返回 dict，没在"
        "播放则字段为 null。常配合 netease.like_current 给当前网易云歌曲加红心。"
    ),
    category="media",
    consumers=[Consumer.CHAT_AGENT],
    trigger_modes=[TriggerMode.ON_DEMAND],
    icon="music",
    parameters_schema={"type": "object", "properties": {}, "required": []},
    health_check=health_check,
)
async def now_playing(**_kwargs) -> dict:
    if not _has_nowplaying_cli():
        return {
            "title": None, "artist": None, "album": None,
            "playing": False,
            "error": "nowplaying-cli 未安装；brew install nowplaying-cli",
        }
    rc, stdout, stderr = await _nowplaying("get", "title", "artist", "album")
    if rc != 0:
        return {
            "title": None, "artist": None, "album": None,
            "playing": False,
            "error": stderr.strip() or f"rc={rc}",
        }
    info = _parse_nowplaying_get(stdout, ["title", "artist", "album"])
    info["playing"] = bool(info.get("title"))
    return info


# ---------------------------------------------------------------------------
# 5. set_volume
# ---------------------------------------------------------------------------

@register_capability(
    name="media.set_volume",
    display_name="设置系统音量",
    description=(
        "设置 macOS 系统输出音量（0-100）。当用户说\"音量调到 X / 大声点 / "
        "小声点 / 静音\"时调用。\"大声/小声\"模糊请求建议先 now_playing 拿"
        "上下文然后给一个合理数（如 +20 / -20）；这一档由 LLM 自己决定。"
    ),
    category="media",
    consumers=[Consumer.CHAT_AGENT],
    trigger_modes=[TriggerMode.ON_DEMAND],
    icon="volume",
    parameters_schema={
        "type": "object",
        "properties": {
            "level": {
                "type": "integer", "minimum": 0, "maximum": 100,
                "description": "目标音量 0-100；0 等价于静音",
            },
        },
        "required": ["level"],
    },
    health_check=health_check,
)
async def set_volume(level: int, **_kwargs) -> dict:
    if not IS_MACOS:
        return {"ok": False, "error": "set_volume 仅 macOS 可用"}
    lvl = max(0, min(100, int(level)))
    rc, _stdout, stderr = await _osascript(f"set volume output volume {lvl}")
    return {"ok": rc == 0, "level": lvl, "error": stderr.strip() if rc != 0 else None}
