"""v3.5 chunk 6b — mpv 本地播放器封装（subprocess + Unix-socket JSON IPC）。

# 为何用 subprocess + IPC 而不是 python-mpv

| 方案 | python-mpv (ctypes) | subprocess + IPC（本方案） |
|---|---|---|
| 部署依赖 | ``libmpv.dylib`` 共享库 | ``/opt/homebrew/bin/mpv`` 可执行 |
| 失败模式 | 找不到 .dylib 时 import 时 ImportError | 找不到 binary 时 health_check 友好返 mpv_not_installed |
| macOS MediaRemote | 需要手动调 PyObjC API | ``--media-keys=yes`` mpv 自动注册 NowPlaying |
| Brew 一致性 | 既要 libmpv-dev 又要 brew mpv | 只要 brew install mpv |

# macOS MediaRemote 兜底（spec degrade 路径已用上）

mpv 0.34+ 在 macOS 自动注册 MPNowPlayingInfoCenter（``--input-media-keys``
默认 ``yes`` · 无需显式传），媒体键 / 通知中心 / nowplaying-cli 都看得见。
``--force-media-title`` / IPC ``set_property`` ``title`` 喂当前歌曲名给 NowPlaying。

(2026-05-31 mpv 0.41.0 incident: 历史 spawn args 含 ``--media-keys=yes`` ·
mpv 0.41 把该 flag rename 为 ``--input-media-keys`` · 老 flag 触发 fatal
``Setting commandline option --media-keys=yes failed`` · subprocess 启动即死 ·
IPC socket 不出现 · 调用方拿到 ``mpv IPC socket never appeared`` RuntimeError。
修法:删 ``--media-keys=yes`` 行 · 反正新名字默认就 yes · 老版本也走默认。)

**spec 原计划自写 PyObjC 桥接被 obviated**——mpv 原生支持，不写
backend/integrations/media_remote.py。这是更好的"degrade"路径（不需要
Skyler 进程持有 AVAudioSession / entitlement / Info.plist）。

# 生命周期

* Lazy spawn：第一次 ``play(url)`` 时启动 mpv ``--idle`` + ``--input-ipc-server``，
  之后所有命令走 socket
* 异常 / 退出：socket 断开 → 自动 respawn 下次 play 调用
* 应用退出：``shutdown()`` 发送 ``quit`` + ``terminate()`` + ``wait`` 优雅停止
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MPV_BINARY_CANDIDATES = [
    "/opt/homebrew/bin/mpv",     # Apple Silicon brew
    "/usr/local/bin/mpv",        # Intel mac brew
    "/usr/bin/mpv",              # Linux pkg
    "mpv",                       # PATH fallback
]

_SOCKET_PATH = Path(tempfile.gettempdir()) / "skyler_mpv.sock"

# IPC 命令 round-trip 默认超时
_IPC_TIMEOUT_S = 3.0


# ---------------------------------------------------------------------------
# Locate mpv binary
# ---------------------------------------------------------------------------

def find_mpv_binary() -> Optional[str]:
    """返回可执行 mpv 路径，找不到返 None。"""
    for cand in _MPV_BINARY_CANDIDATES:
        # 绝对路径直接 test
        if os.path.isabs(cand):
            if os.access(cand, os.X_OK):
                return cand
            continue
        # PATH 查找
        which = shutil.which(cand)
        if which:
            return which
    return None


# ---------------------------------------------------------------------------
# stderr tail (启动失败 diagnostic · 2026-05-31)
# ---------------------------------------------------------------------------


async def _read_stderr_tail(
    proc: asyncio.subprocess.Process,
    *,
    max_bytes: int = 400,
    timeout: float = 0.2,
) -> str:
    """Best-effort 读 mpv stderr · 启动失败时塞进 RuntimeError detail。

    spawn 失败场景 mpv 已快速 exit · stderr 短 + 已 EOF · ``read()`` 立返。
    若 stderr 无 (DEVNULL 等) 或 timeout 直接返空串 · 不抛。
    """
    if proc.stderr is None:
        return ""
    try:
        raw = await asyncio.wait_for(proc.stderr.read(max_bytes), timeout=timeout)
    except (asyncio.TimeoutError, Exception):
        return ""
    return raw.decode("utf-8", errors="replace").strip().replace("\n", " | ")[:max_bytes]


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


async def health_check() -> dict:
    """三档：mpv 装了 + 可执行 + （可选）socket alive。"""
    binary = find_mpv_binary()
    if binary is None:
        return {
            "status": "error",
            "error": "mpv_not_installed",
            "hint": "brew install mpv（macOS）或 apt install mpv（Linux）",
        }
    # 跑 mpv --version 拿版本号当 connectivity 验证
    try:
        proc = await asyncio.create_subprocess_exec(
            binary, "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=3.0)
        version_line = (out.decode("utf-8", errors="replace").splitlines() or [""])[0]
    except asyncio.TimeoutError:
        return {
            "status": "warn",
            "error": "mpv_version_timeout",
            "binary": binary,
        }
    except Exception as exc:
        return {
            "status": "warn",
            "error": "mpv_exec_failed",
            "detail": str(exc)[:200],
            "binary": binary,
        }
    return {
        "status": "healthy",
        "binary": binary,
        "version": version_line,
        "socket_alive": _player_singleton is not None and _player_singleton.is_running(),
    }


# ---------------------------------------------------------------------------
# MpvPlayer (singleton)
# ---------------------------------------------------------------------------


class MpvPlayer:
    """单实例 mpv 控制器；lazy spawn + socket IPC。

    本类**不暴露**给 capability 直接用——通过模块级 ``play_url`` /
    ``pause`` 等顶层函数走 ``_player_singleton``。
    """

    def __init__(self, binary: str) -> None:
        self._binary = binary
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._cmd_lock = asyncio.Lock()
        self._req_id = 0
        # FIFO 队列：play_next() 时 pop 第一个
        self._queue: list[dict] = []
        # 当前播放的元信息（给 health / now_playing 用）
        self._current: Optional[dict] = None

    # ── lifecycle ──────────────────────────────────────────────────────────

    def is_running(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    async def _spawn(self) -> None:
        """启动 mpv idle + IPC socket。已 running 时 no-op。"""
        if self.is_running():
            return
        # 旧 socket 文件清理（上一次崩溃可能残留）
        try:
            _SOCKET_PATH.unlink(missing_ok=True)
        except Exception:
            pass

        args = [
            self._binary,
            "--idle=yes",                  # 不退出，等 IPC 命令
            "--no-terminal",               # 不接 stdin tty
            "--no-video",                  # 纯音频
            "--audio-display=no",          # 不弹封面窗口
            f"--input-ipc-server={_SOCKET_PATH}",
            # (2026-05-31) `--media-keys=yes` 在 mpv 0.41 被 rename 为
            # `--input-media-keys` · 老 flag fatal · 新 flag 默认就 yes ·
            # 故直接不传。详见模块 docstring incident note。
            "--force-window=no",
        ]
        try:
            self._proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.DEVNULL,
                # (2026-05-31) 启动失败时 stderr 是唯一线索 · 改 PIPE 后
                # socket 未出现时 read 进 RuntimeError detail · 避免黑盒。
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(f"mpv binary missing: {exc}") from exc

        # 等 socket 出现（mpv 启动需要一小会儿；最多等 2s）
        for _ in range(40):
            if _SOCKET_PATH.exists():
                break
            await asyncio.sleep(0.05)
        else:
            stderr_tail = await _read_stderr_tail(self._proc)
            await self._kill()
            raise RuntimeError(
                "mpv IPC socket never appeared (timeout 2s)"
                + (f"; stderr={stderr_tail}" if stderr_tail else "")
            )

        # 连 socket
        self._reader, self._writer = await asyncio.open_unix_connection(
            str(_SOCKET_PATH),
        )
        logger.info("[mpv] spawned pid=%s socket=%s", self._proc.pid, _SOCKET_PATH)

    async def _kill(self) -> None:
        """硬杀（连不通 / 启动失败时清理用）。"""
        if self._proc is not None:
            try:
                self._proc.kill()
                await asyncio.wait_for(self._proc.wait(), timeout=2.0)
            except Exception:
                pass
        self._proc = None
        self._reader = None
        self._writer = None

    async def shutdown(self) -> None:
        """优雅停止 mpv（应用退出时调）。"""
        if not self.is_running():
            return
        try:
            await self._send_command(["quit"])
        except Exception:
            pass
        if self._proc is not None:
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                await self._kill()
        self._reader = None
        self._writer = None
        self._proc = None

    # ── IPC primitives ─────────────────────────────────────────────────────

    async def _send_command(self, command: list[Any]) -> dict:
        """JSON-IPC 命令：发 + 读响应。需要 socket alive。"""
        if not self.is_running():
            await self._spawn()
        assert self._writer is not None and self._reader is not None

        async with self._cmd_lock:
            self._req_id += 1
            req_id = self._req_id
            line = json.dumps({"command": command, "request_id": req_id}) + "\n"
            self._writer.write(line.encode("utf-8"))
            await self._writer.drain()

            # 读到 request_id 匹配的响应；mpv 可能先吐 events，按序读直到命中
            try:
                while True:
                    raw = await asyncio.wait_for(
                        self._reader.readline(), timeout=_IPC_TIMEOUT_S,
                    )
                    if not raw:
                        raise RuntimeError("mpv socket closed unexpectedly")
                    try:
                        msg = json.loads(raw.decode("utf-8", errors="replace"))
                    except json.JSONDecodeError:
                        continue
                    if msg.get("request_id") == req_id:
                        return msg
                    # event 消息，先记日志
                    if "event" in msg:
                        logger.debug("[mpv] event: %s", msg.get("event"))
            except asyncio.TimeoutError:
                raise RuntimeError("mpv IPC command timeout")

    # ── high-level API ─────────────────────────────────────────────────────

    async def play(self, url: str, *, meta: Optional[dict] = None) -> dict:
        """立即播放 URL。meta（title/artist/album）喂 NowPlaying。"""
        await self._spawn()
        # loadfile 替换当前 + 立即播
        await self._send_command(["loadfile", url, "replace"])
        # (2026-05-31) sticky pause 防御:singleton 此前若被 `pause()` 调过 ·
        # mpv 0.41 loadfile-replace 不重置 pause 属性 · 新文件加载完也卡 0
        # (PM 凌晨现场:playback-time 一直 0.000000 / 手动 set pause=false 立即出声)。
        # 显式置 False 是 idempotent(已 False 也无害)。empirical repro:
        # repro4 已证 pause=True 跨 loadfile 后会 sticky · 不 advance。
        await self._send_command(["set_property", "pause", False])
        if meta:
            title = meta.get("title")
            artist = meta.get("artist")
            if title:
                await self._send_command(["set_property", "force-media-title", str(title)])
                await self._send_command(["set_property", "media-title", str(title)])
            if artist:
                await self._send_command(["set_property", "metadata/by-key/artist", str(artist)])
        self._current = {"url": url, **(meta or {})}
        return {"status": "playing", **self._current}

    async def pause(self) -> dict:
        if not self.is_running():
            return {"status": "not_running"}
        await self._send_command(["set_property", "pause", True])
        return {"status": "paused"}

    async def resume(self) -> dict:
        if not self.is_running():
            return {"status": "not_running"}
        await self._send_command(["set_property", "pause", False])
        return {"status": "playing"}

    async def stop(self) -> dict:
        if not self.is_running():
            return {"status": "stopped"}
        await self._send_command(["stop"])
        self._current = None
        return {"status": "stopped"}

    def queue(self) -> list[dict]:
        return list(self._queue)

    def queue_extend(self, items: list[dict]) -> None:
        """供 play_playlist 用：批量入队。items=[{url, meta}, ...]"""
        self._queue.extend(items)

    def queue_clear(self) -> None:
        self._queue.clear()

    async def play_next(self) -> dict:
        """从队列 pop 下一首并 play。空队列返 ``{status: 'queue_empty'}``。"""
        if not self._queue:
            return {"status": "queue_empty"}
        item = self._queue.pop(0)
        return await self.play(item["url"], meta=item.get("meta"))

    def current(self) -> Optional[dict]:
        return self._current


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_player_singleton: Optional[MpvPlayer] = None


def get_player() -> MpvPlayer:
    """模块级 singleton（懒构造）。mpv 未装时 raise，调用方应先 health_check。"""
    global _player_singleton
    if _player_singleton is None:
        binary = find_mpv_binary()
        if binary is None:
            raise RuntimeError("mpv binary not found; run: brew install mpv")
        _player_singleton = MpvPlayer(binary)
    return _player_singleton


def _reset_for_test() -> None:
    """测试钩子：重置 singleton。"""
    global _player_singleton
    _player_singleton = None


async def shutdown_player() -> None:
    """应用退出 hook：优雅停 mpv。"""
    if _player_singleton is not None and _player_singleton.is_running():
        try:
            await _player_singleton.shutdown()
        except Exception as exc:
            logger.warning("[mpv] shutdown error: %s", exc)
