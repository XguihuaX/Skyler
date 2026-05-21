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
import os
import shutil
import subprocess
import sys
from typing import Any, Optional

from backend.capabilities import Consumer, TriggerMode, register_capability

logger = logging.getLogger(__name__)

IS_MACOS = sys.platform == "darwin"
_CMD_TIMEOUT = 2  # seconds


# ---------------------------------------------------------------------------
# nowplaying-cli 路径解析
# ---------------------------------------------------------------------------
#
# 后端进程 PATH 不一定包含 ``/opt/homebrew/bin``（M 系列）/``/usr/local/bin``
# （Intel）—— 经 Tauri sidecar / launchd 启动时 PATH 会被裁剪到 ``/usr/bin:
# /bin:/usr/sbin:/sbin``，``shutil.which`` 找不到 nowplaying-cli。
#
# 修：模块加载时一次性解析路径，shutil.which fail 后回退到已知 Homebrew 安装
# 目录探测；找到的绝对路径被所有 subprocess.run 调用复用，避免每次 PATH 查
# 的开销 + 跨进程环境差异。``refresh_nowplaying_bin()`` 提供运行时刷新（
# brew install 后无需重启 backend）。

_HOMEBREW_FALLBACK_PATHS = (
    "/opt/homebrew/bin/nowplaying-cli",   # Apple Silicon
    "/usr/local/bin/nowplaying-cli",      # Intel
)


def _resolve_nowplaying_bin() -> Optional[str]:
    """先 PATH 后 Homebrew 兜底；返绝对路径或 None。"""
    via_path = shutil.which("nowplaying-cli")
    if via_path:
        return via_path
    for cand in _HOMEBREW_FALLBACK_PATHS:
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    return None


_NOWPLAYING_BIN: Optional[str] = _resolve_nowplaying_bin() if IS_MACOS else None


# stderr print 保证用户可见——module 加载发生在 main.py 的 basicConfig 之前，
# logger.info 此刻会被 last-resort filter（默认 WARNING level）丢弃。
if IS_MACOS:
    if _NOWPLAYING_BIN:
        print(
            f"[media_control] nowplaying-cli resolved to: {_NOWPLAYING_BIN}",
            file=sys.stderr,
        )
        logger.info("nowplaying-cli resolved to: %s", _NOWPLAYING_BIN)
    else:
        _missing_msg = (
            "[media_control] nowplaying-cli NOT FOUND in PATH "
            f"({os.environ.get('PATH', '')!r}) "
            "or Homebrew dirs — media.* capabilities will return error. "
            "Run: brew install nowplaying-cli"
        )
        print(_missing_msg, file=sys.stderr)
        logger.warning(_missing_msg)


def get_nowplaying_bin() -> Optional[str]:
    """对外暴露，给 netease_music capability 复用同一份解析。"""
    return _NOWPLAYING_BIN


def refresh_nowplaying_bin() -> Optional[str]:
    """重新跑一次解析。``brew install nowplaying-cli`` 后调用即可，无需重启。"""
    global _NOWPLAYING_BIN
    _NOWPLAYING_BIN = _resolve_nowplaying_bin() if IS_MACOS else None
    logger.info("nowplaying-cli re-resolved: %s", _NOWPLAYING_BIN)
    return _NOWPLAYING_BIN


def _has_nowplaying_cli() -> bool:
    return IS_MACOS and _NOWPLAYING_BIN is not None


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
    if _NOWPLAYING_BIN is None:
        return -2, "", "nowplaying-cli not resolved"
    return await asyncio.to_thread(_run_sync, [_NOWPLAYING_BIN, *subcmd])


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
    if _NOWPLAYING_BIN is None:
        return {
            "status": "warn",
            "error": (
                "nowplaying-cli 未在 PATH 或 Homebrew 路径中找到。"
                "请 `brew install nowplaying-cli`（M 系列装到 /opt/homebrew/bin，"
                "Intel 在 /usr/local/bin；Skyler 自动找）"
            ),
        }
    return {"status": "healthy", "binary": _NOWPLAYING_BIN}


# ---------------------------------------------------------------------------
# 5 internal handlers (per INV-6 §2 P1.media fold, 2026-05-21):
# next_track / previous_track / play_pause / now_playing / set_volume
# 走 dispatcher `media(action=...)`,不再单独 @register_capability。
# ---------------------------------------------------------------------------


async def _handle_next_track(**_kwargs) -> dict:
    if not _has_nowplaying_cli():
        return {"ok": False, "error": "nowplaying-cli 未安装；brew install nowplaying-cli"}
    rc, _stdout, stderr = await _nowplaying("next")
    return {"ok": rc == 0, "error": stderr.strip() if rc != 0 else None}


async def _handle_previous_track(**_kwargs) -> dict:
    if not _has_nowplaying_cli():
        return {"ok": False, "error": "nowplaying-cli 未安装；brew install nowplaying-cli"}
    rc, _stdout, stderr = await _nowplaying("previous")
    return {"ok": rc == 0, "error": stderr.strip() if rc != 0 else None}


async def _handle_play_pause(**_kwargs) -> dict:
    if not _has_nowplaying_cli():
        return {"ok": False, "error": "nowplaying-cli 未安装；brew install nowplaying-cli"}
    rc, _stdout, stderr = await _nowplaying("togglePlayPause")
    return {"ok": rc == 0, "error": stderr.strip() if rc != 0 else None}


def _parse_nowplaying_get(stdout: str, fields: list[str]) -> dict:
    """``nowplaying-cli get title artist album`` 输出按行返字段，缺失行内是空。"""
    lines = stdout.splitlines()
    out: dict = {}
    for i, fld in enumerate(fields):
        val = lines[i].strip() if i < len(lines) else ""
        out[fld] = val if val and val != "null" else None
    return out


async def _handle_now_playing(**_kwargs) -> dict:
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


async def _handle_set_volume(level: Optional[int] = None, **_kwargs) -> dict:
    if not IS_MACOS:
        return {"ok": False, "error": "set_volume 仅 macOS 可用"}
    if level is None:
        return {"ok": False, "error": "level required when action=set_volume"}
    lvl = max(0, min(100, int(level)))
    rc, _stdout, stderr = await _osascript(f"set volume output volume {lvl}")
    return {"ok": rc == 0, "level": lvl, "error": stderr.strip() if rc != 0 else None}


# ---------------------------------------------------------------------------
# media dispatcher (INV-6 §2 P1.media template, 2026-05-21)
# ---------------------------------------------------------------------------

_MEDIA_ACTION_HANDLERS = {
    "next_track":     _handle_next_track,
    "previous_track": _handle_previous_track,
    "play_pause":     _handle_play_pause,
    "now_playing":    _handle_now_playing,
    "set_volume":     _handle_set_volume,
}


@register_capability(
    name="media",
    display_name="媒体控制 + 当前在播查询",
    description=(
        "macOS 系统级媒体控制 + 当前在播查询(跨来源:网易云 / Apple Music / "
        "Spotify / YouTube / Bilibili 网页等)。按 action 选具体操作:\n"
        "- next_track:下一首(用户说'下一首/切歌/换一首/不喜欢这首')\n"
        "- previous_track:上一首(用户说'上一首/刚才那首/退回去')\n"
        "- play_pause:toggle 播放/暂停(用户说'暂停/播放/继续/停一下')\n"
        "- now_playing:查当前在播歌名/歌手/专辑(用户问'在放什么/这首叫啥')\n"
        "- set_volume:调音量(用户说'音量调到 X/大声点/小声点',需 level)\n"
        "set_volume 的'大声/小声'模糊请求由你判合理 level(如 +20/-20),不反复问。"
    ),
    category="media",
    consumers=[Consumer.CHAT_AGENT],
    trigger_modes=[TriggerMode.ON_DEMAND],
    icon="play",
    health_check=health_check,
    parameters_schema={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": list(_MEDIA_ACTION_HANDLERS.keys()),
                "description": "媒体操作类型",
            },
            "level": {
                "type": "integer",
                "minimum": 0, "maximum": 100,
                "description": "仅 action=set_volume 时必填,目标音量 0-100(0=静音)",
            },
        },
        "required": ["action"],
    },
)
async def media_dispatch(action: str = "", **params: Any) -> dict:
    """Dispatcher: 按 action 路由到对应 _handle_* 函数。"""
    handler = _MEDIA_ACTION_HANDLERS.get(action)
    if handler is None:
        return {
            "ok": False,
            "error": (
                f"unknown action: {action!r}; "
                f"valid: {list(_MEDIA_ACTION_HANDLERS.keys())}"
            ),
        }
    return await handler(**params)
