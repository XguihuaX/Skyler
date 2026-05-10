"""Scan ``frontend/public/backgrounds/`` and return per-character background assets.

v3.5 chunk 5a — CharacterPanel 用一份"当前可用背景资产"下拉，替代裸文本框。
后缀决定类型（image / video），前端按类型分发 ``<img>`` / ``<video>``。

Resolution rules（与 ``live2d_scanner.py`` 对齐）
----------------------------------------------
- Project root 用 ``Path(__file__).absolute().parents[2]``。``uvicorn`` 与
  Tauri-embedded backend 启动 CWD 不同，永不信任 ``Path.cwd()``。
- **Symlink discipline**: 用 ``.absolute()`` 不 ``.resolve()``。用户可能
  ``ln -s <external IP asset> frontend/public/backgrounds/<file>``，URL 服
  务由 Vite 在 repo path 命名空间内做，``relative_to()`` 不能被 symlink
  解析跳出。详见 ``live2d_scanner.py`` 顶头注释。
- 递归扫一级子目录（与 live2d 不同：背景文件可以平铺也可以分组）。隐藏
  目录（``.``开头）+ ``__pycache__`` 跳过。
- 后缀白名单：``.jpg / .jpeg / .png / .webp`` → image；``.mp4 / .webm`` →
  video。其他后缀忽略（README.md / .gitkeep / 用户暂存的素材源文件等）。
- 不读文件二进制；只看 stat 拿 size。
- 单文件错误不会拖垮整个 scan —— 文件级 try/except 后吞，缺失文件不计入
  返回列表（与 live2d scanner 的 warnings 数组不同：背景缺失通常说明用户
  刚移走，没必要 UI 报警，列表少一项就够了）。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

from typing_extensions import TypedDict

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Path anchoring
# ---------------------------------------------------------------------------

# This file: <repo>/backend/services/backgrounds_scanner.py
_REPO_ROOT = Path(__file__).absolute().parents[2]
_BACKGROUNDS_DIR = _REPO_ROOT / "frontend" / "public" / "backgrounds"
_PUBLIC_ROOT = _REPO_ROOT / "frontend" / "public"

# 后缀 → 类型
_IMAGE_EXTS: frozenset[str] = frozenset({".jpg", ".jpeg", ".png", ".webp"})
_VIDEO_EXTS: frozenset[str] = frozenset({".mp4", ".webm"})

# 跳过的子目录名（与 live2d_scanner 同 pattern）
_SKIP_DIRS: frozenset[str] = frozenset({"__pycache__"})


BackgroundType = Literal["image", "video"]


class BackgroundInfo(TypedDict):
    name: str            # 不含后缀的展示名（``tokyo_rain``）
    path: str            # /-prefixed Vite static URL（``/backgrounds/tokyo_rain.mp4``）
    type: BackgroundType
    size: int            # 字节


class BackgroundScanResult(TypedDict):
    scan_dir: str        # repo-relative，避免 leak workstation 路径
    items: list[BackgroundInfo]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _classify(suffix: str) -> BackgroundType | None:
    s = suffix.lower()
    if s in _IMAGE_EXTS:
        return "image"
    if s in _VIDEO_EXTS:
        return "video"
    return None


def _to_static_url(abs_path: Path) -> str:
    """``<repo>/frontend/public/backgrounds/x.mp4`` → ``/backgrounds/x.mp4``。"""
    rel = abs_path.relative_to(_PUBLIC_ROOT)
    return "/" + rel.as_posix()


def _scan_file(file_path: Path) -> BackgroundInfo | None:
    """单文件 → BackgroundInfo。后缀不在白名单 / stat 失败 → None。"""
    bg_type = _classify(file_path.suffix)
    if bg_type is None:
        return None
    try:
        size = file_path.stat().st_size
    except OSError as exc:
        logger.warning("[backgrounds] stat failed for %s: %s", file_path, exc)
        return None
    return BackgroundInfo(
        name=file_path.stem,
        path=_to_static_url(file_path),
        type=bg_type,
        size=size,
    )


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------


def scan_backgrounds() -> BackgroundScanResult:
    """Enumerate ``frontend/public/backgrounds/`` (recursive one level).

    Always returns; per-file failures swallowed + logged. ``scan_dir`` is
    repo-relative for clarity, mirroring ``scan_live2d_models``.
    """
    rel_scan_dir = "frontend/public/backgrounds"
    if not _BACKGROUNDS_DIR.is_dir():
        logger.warning(
            "[backgrounds] scan dir not found at %s — returning empty list",
            _BACKGROUNDS_DIR,
        )
        return BackgroundScanResult(scan_dir=rel_scan_dir, items=[])

    items: list[BackgroundInfo] = []

    # 1. 根目录直接文件
    for entry in sorted(_BACKGROUNDS_DIR.iterdir()):
        if entry.is_file():
            info = _scan_file(entry)
            if info is not None:
                items.append(info)
            continue
        if not entry.is_dir():
            continue
        if entry.name in _SKIP_DIRS or entry.name.startswith("."):
            continue
        # 2. 子目录（一层深）—— 让用户分组（``tokyo/rain.mp4`` / ``shrine/night.jpg``）
        try:
            for sub in sorted(entry.iterdir()):
                if not sub.is_file():
                    continue
                info = _scan_file(sub)
                if info is not None:
                    # name 用 ``<subdir>/<stem>``，避免重名 collision
                    items.append({
                        **info,
                        "name": f"{entry.name}/{sub.stem}",
                    })
        except OSError as exc:
            logger.warning(
                "[backgrounds] subdir scan failed for %s: %s",
                entry, exc,
            )

    return BackgroundScanResult(scan_dir=rel_scan_dir, items=items)
