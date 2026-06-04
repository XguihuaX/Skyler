"""Scan **two** background asset directories and merge them with a ``source`` tag.

Bundled (default samples, read-only)
    ``frontend/public/backgrounds/`` — shipped with the app. Vite serves them
    at ``/backgrounds/<name>``. Cannot be deleted via the API.

User (writable, runtime data)
    ``<appData>/backgrounds/`` — populated by upload + delete endpoints.
    Backend FastAPI mounts the directory at ``/userdata/backgrounds/`` so the
    frontend can ``<img src="…">`` it via ``BACKEND_BASE`` prefix.

    ``<appData>`` resolves via ``platformdirs.user_data_dir`` using the Tauri
    bundle identifier ``com.skyler.momoos`` as the appname — gives the same
    path Tauri 2's ``appDataDir()`` returns by default, so dev/prod stay aligned
    even after we bundle the sidecar.

Scan rules (preserved from v3.5 chunk 5a):
    - Suffix whitelist:  image = jpg/jpeg/png/webp · video = mp4/webm.
    - Recurse one level of subdirs (so users can group: ``tokyo/rain.png``).
    - Hidden dirs (``.``-prefix) + ``__pycache__`` skipped.
    - Single-file errors swallowed + logged (no API failure cascade).
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

from platformdirs import user_data_dir
from typing_extensions import TypedDict

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Path anchoring — bundled (read-only) + user (writable)
# ---------------------------------------------------------------------------

# This file: <repo>/backend/services/backgrounds_scanner.py
_REPO_ROOT = Path(__file__).absolute().parents[2]
_BUNDLED_DIR = _REPO_ROOT / "frontend" / "public" / "backgrounds"
_PUBLIC_ROOT = _REPO_ROOT / "frontend" / "public"

# Tauri identifier from frontend/src-tauri/tauri.conf.json. Using the identifier
# as appname (appauthor=False) matches Tauri 2's default appDataDir() result:
#   macOS   → ~/Library/Application Support/com.skyler.momoos/
#   Linux   → ~/.local/share/com.skyler.momoos/
#   Windows → %APPDATA%\com.skyler.momoos\
_TAURI_IDENTIFIER = "com.skyler.momoos"


def _user_backgrounds_dir() -> Path:
    """Resolve <appData>/backgrounds/, lazy-create on first call."""
    base = Path(user_data_dir(_TAURI_IDENTIFIER, appauthor=False))
    target = base / "backgrounds"
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.warning(
            "[backgrounds] failed to create user dir %s: %s", target, exc
        )
    return target


_IMAGE_EXTS: frozenset[str] = frozenset({".jpg", ".jpeg", ".png", ".webp"})
_VIDEO_EXTS: frozenset[str] = frozenset({".mp4", ".webm"})
_ALLOWED_EXTS: frozenset[str] = _IMAGE_EXTS | _VIDEO_EXTS
_SKIP_DIRS: frozenset[str] = frozenset({"__pycache__"})


BackgroundType = Literal["image", "video"]
BackgroundSource = Literal["bundled", "user"]


class BackgroundInfo(TypedDict):
    name: str            # display name (no suffix)
    path: str            # relative URL: ``/backgrounds/x.png`` (bundled) or
                         # ``/userdata/backgrounds/x.png`` (user)
    type: BackgroundType
    size: int
    source: BackgroundSource


class BackgroundScanResult(TypedDict):
    scan_dirs: list[str]   # for diagnostics
    items: list[BackgroundInfo]


# Public so the upload/delete endpoints can use the same path resolver.
def get_user_backgrounds_dir() -> Path:
    return _user_backgrounds_dir()


def classify_extension(suffix: str) -> BackgroundType | None:
    s = suffix.lower()
    if s in _IMAGE_EXTS:
        return "image"
    if s in _VIDEO_EXTS:
        return "video"
    return None


def is_allowed_extension(suffix: str) -> bool:
    return suffix.lower() in _ALLOWED_EXTS


# ---------------------------------------------------------------------------
# URL builders
# ---------------------------------------------------------------------------


def _bundled_url(abs_path: Path) -> str:
    """``<repo>/frontend/public/backgrounds/x.mp4`` → ``/backgrounds/x.mp4``."""
    rel = abs_path.relative_to(_PUBLIC_ROOT)
    return "/" + rel.as_posix()


def _user_url(abs_path: Path, root: Path) -> str:
    """``<appData>/backgrounds/x.mp4`` → ``/userdata/backgrounds/x.mp4``."""
    rel = abs_path.relative_to(root)
    return "/userdata/backgrounds/" + rel.as_posix()


# ---------------------------------------------------------------------------
# Single-file inspection
# ---------------------------------------------------------------------------


def _scan_file(
    file_path: Path,
    *,
    source: BackgroundSource,
    url_builder,
    name_override: str | None = None,
) -> BackgroundInfo | None:
    bg_type = classify_extension(file_path.suffix)
    if bg_type is None:
        return None
    try:
        size = file_path.stat().st_size
    except OSError as exc:
        logger.warning("[backgrounds] stat failed for %s: %s", file_path, exc)
        return None
    return BackgroundInfo(
        name=name_override or file_path.stem,
        path=url_builder(file_path),
        type=bg_type,
        size=size,
        source=source,
    )


def _scan_dir(
    root: Path,
    *,
    source: BackgroundSource,
    url_builder,
) -> list[BackgroundInfo]:
    items: list[BackgroundInfo] = []
    if not root.is_dir():
        return items
    for entry in sorted(root.iterdir()):
        if entry.is_file():
            info = _scan_file(entry, source=source, url_builder=url_builder)
            if info is not None:
                items.append(info)
            continue
        if not entry.is_dir():
            continue
        if entry.name in _SKIP_DIRS or entry.name.startswith("."):
            continue
        # one level of subdir; name = "<sub>/<stem>" so collisions avoided.
        try:
            for sub in sorted(entry.iterdir()):
                if not sub.is_file():
                    continue
                info = _scan_file(
                    sub,
                    source=source,
                    url_builder=url_builder,
                    name_override=f"{entry.name}/{sub.stem}",
                )
                if info is not None:
                    items.append(info)
        except OSError as exc:
            logger.warning(
                "[backgrounds] subdir scan failed for %s: %s", entry, exc
            )
    return items


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------


def scan_backgrounds() -> BackgroundScanResult:
    """Scan bundled (read-only) + user (writable) dirs, merge, tag ``source``."""
    user_root = _user_backgrounds_dir()

    items: list[BackgroundInfo] = []
    # Bundled first → user appears after in the grid (visual: defaults left,
    # custom right). UI doesn't depend on order but consistent is nicer.
    items.extend(
        _scan_dir(_BUNDLED_DIR, source="bundled", url_builder=_bundled_url)
    )
    items.extend(
        _scan_dir(
            user_root,
            source="user",
            url_builder=lambda p: _user_url(p, user_root),
        )
    )

    return BackgroundScanResult(
        scan_dirs=[
            "frontend/public/backgrounds",
            str(user_root),
        ],
        items=items,
    )
