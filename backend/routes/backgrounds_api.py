"""Backgrounds asset REST API.

Mounted at /api in main.py.  Full URL map:
  GET    /api/backgrounds              — scan bundled + user dirs (with source tag)
  POST   /api/backgrounds/upload       — multipart upload to user dir
  DELETE /api/backgrounds/{name}       — delete user file (bundled rejected)

v3.5 chunk 5a (legacy: per-character bg dropdown — retired in Round 5 step 1).
2026-06-04 · Round 5 step 2 — add upload/delete + source='bundled'|'user' tag.
Bundled assets are read-only ship samples; user assets land in
``<appData>/backgrounds/`` via platformdirs (see backgrounds_scanner.py).
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from backend.services.backgrounds_scanner import (
    BackgroundScanResult,
    classify_extension,
    get_user_backgrounds_dir,
    is_allowed_extension,
    scan_backgrounds,
)

logger = logging.getLogger(__name__)

router = APIRouter()


class _UploadTooLarge(Exception):
    """Sentinel raised when streamed bytes exceed _MAX_UPLOAD_BYTES."""


# Reject filesystem-unsafe characters in display names. NUL, path separators,
# Windows-reserved chars, control chars 0x00-0x1F. Apply *before* concatenating
# extension so users can't sneak ".." traversal via the display name field.
_UNSAFE_RE = re.compile(r'[\x00-\x1f<>:"/\\|?*]')
_MAX_NAME_LEN = 100

# Round 5 step 2 hotfix (2026-06-04) · Upload size cap.
# 200 MB 选值:JPG/PNG 壁纸通常 < 10 MB · 1080p H264 短视频 ~20-100 MB ·
# 几分钟视频可达 200 MB · 4K 短视频可超 · 壁纸场景不需要 4K,200 MB 既能装
# 正常视频又能挡住手滑误传超大 / 极端攻击。改阈值改这一个常量。
_MAX_UPLOAD_BYTES = 200 * 1024 * 1024
_MAX_UPLOAD_MB = _MAX_UPLOAD_BYTES // (1024 * 1024)


def _sanitize_name(raw: str) -> str:
    cleaned = _UNSAFE_RE.sub("", raw).strip().strip(".")
    if len(cleaned) > _MAX_NAME_LEN:
        cleaned = cleaned[:_MAX_NAME_LEN]
    return cleaned


def _next_unique(target_dir: Path, stem: str, ext: str) -> Path:
    """Return a path in ``target_dir`` that doesn't exist yet.

    First tries ``<stem><ext>``; if taken, appends ``-1``, ``-2``, …, mirroring
    macOS Finder's duplicate-name convention.
    """
    candidate = target_dir / f"{stem}{ext}"
    if not candidate.exists():
        return candidate
    counter = 1
    while True:
        candidate = target_dir / f"{stem}-{counter}{ext}"
        if not candidate.exists():
            return candidate
        counter += 1


@router.get("/backgrounds")
async def list_backgrounds() -> BackgroundScanResult:
    """Return bundled + user backgrounds with ``source`` tags."""
    return scan_backgrounds()


@router.post("/backgrounds/upload")
async def upload_background(
    file: UploadFile = File(...),
    name: str = Form(""),
) -> dict:
    """Upload a single image/video to the user backgrounds dir.

    Body (multipart/form-data):
        file:  the asset (suffix must pass whitelist)
        name:  display name (optional) — falls back to original filename stem.
               Sanitized + length-clamped + duplicate-suffixed before saving.

    Returns the new file's ``BackgroundInfo`` shape (so frontend can prepend
    to its list without a second scan, though we keep refresh free).
    """
    # 1. Validate suffix from the *uploaded* filename (trust client only for
    #    the type discriminator; whitelist gate makes spoofing harmless).
    if not file.filename:
        raise HTTPException(status_code=400, detail="filename missing")
    ext = Path(file.filename).suffix
    if not is_allowed_extension(ext):
        raise HTTPException(
            status_code=400,
            detail=f"unsupported file type: {ext or '(no extension)'}",
        )

    # 2. Resolve display name: form field → sanitize → fallback to original stem.
    proposed_stem = _sanitize_name(name) if name else ""
    if not proposed_stem:
        proposed_stem = _sanitize_name(Path(file.filename).stem)
    if not proposed_stem:
        proposed_stem = "background"

    # 3. Place in user dir with collision suffix.
    user_dir = get_user_backgrounds_dir()
    target = _next_unique(user_dir, proposed_stem, ext.lower())

    # 4. Stream bytes with running size cap. FastAPI UploadFile is a spool;
    #    copying in 1 MiB chunks so big videos don't peak memory. Hitting the
    #    cap → abort + delete half-written file so disk doesn't leak partials.
    written = 0
    try:
        with target.open("wb") as fh:
            while True:
                chunk = await file.read(1024 * 1024)  # 1 MiB
                if not chunk:
                    break
                written += len(chunk)
                if written > _MAX_UPLOAD_BYTES:
                    raise _UploadTooLarge()
                fh.write(chunk)
    except _UploadTooLarge:
        try:
            target.unlink(missing_ok=True)
        except OSError:
            pass
        raise HTTPException(
            status_code=413,
            detail=f"文件超过 {_MAX_UPLOAD_MB} MB 上限",
        )
    except OSError as exc:
        # cleanup half-written file
        try:
            target.unlink(missing_ok=True)
        except OSError:
            pass
        logger.exception("[backgrounds] upload write failed for %s", target)
        raise HTTPException(status_code=500, detail=f"write failed: {exc}")

    bg_type = classify_extension(ext)
    return {
        "name": target.stem,
        "path": f"/userdata/backgrounds/{target.name}",
        "type": bg_type,
        "size": target.stat().st_size,
        "source": "user",
    }


@router.delete("/backgrounds/{name}")
async def delete_background(name: str) -> dict:
    """Delete one user-uploaded background by filename (with extension).

    Bundled assets are never deletable via this API — they're shipped with
    the app. Path traversal blocked: ``name`` must not contain path separators
    or ``..``, and the resolved path must stay inside ``user_dir``.
    """
    # Round 5 step 2 hotfix (2026-06-04) · Precise filename validation.
    # 原本 ``if ".." in name`` 把任何含连续两点的合法文件名(如 ``foo..bar.png``)
    # 全部误杀 — 实测复现 400 invalid filename。Path traversal 的真正风险是
    # name 作为 *单一 path component* 等于 ``..`` 或 ``.``,或包含 path
    # separator / NUL byte。下面 is_relative_to 仍兜底防 symlink 逃逸。
    if name in ("", ".", ".."):
        raise HTTPException(status_code=400, detail="invalid filename")
    if "/" in name or "\\" in name or "\x00" in name:
        raise HTTPException(status_code=400, detail="invalid filename")

    user_dir = get_user_backgrounds_dir()
    target = (user_dir / name).resolve()

    # Confined-path check: resolved target must stay inside user_dir.
    if not target.is_relative_to(user_dir.resolve()):
        raise HTTPException(status_code=400, detail="path escape rejected")

    if not target.is_file():
        raise HTTPException(status_code=404, detail="not found")

    try:
        target.unlink()
    except OSError as exc:
        logger.exception("[backgrounds] delete failed for %s", target)
        raise HTTPException(status_code=500, detail=f"delete failed: {exc}")

    return {"ok": True, "deleted": name}
