"""Scan ``frontend/public/live2d/`` and return the available Live2D models.

Each character lives under ``frontend/public/live2d/<slug>/`` with a
``*.model3.json`` entry referencing the ``.moc3`` and other resources.
v3-E2 commit 3a exposes this listing as ``GET /api/live2d/models`` so the
CharacterPanel UI can offer a dropdown of validated models instead of a
free-text field.

Resolution rules
----------------
- Project root is anchored via ``Path(__file__).absolute()`` walking up two
  parents (``backend/services/live2d_scanner.py`` → repo root). Both
  ``uvicorn backend.main:app`` and the Tauri-embedded backend launch with
  different CWDs, so we never trust ``Path.cwd()``.
- **Symlink discipline**: scanner works at the **path-literal** level and
  never follows symlinks (no ``Path.resolve()``). Users routinely ``ln -s
  <external-IP-asset> frontend/public/live2d/<slug>`` to keep IP assets out
  of the repo (``.gitignore`` already excludes those slug dirs); the URL
  served by Vite + the path computed here must stay inside ``frontend/
  public/`` regardless of where the symlink target lives. ``.resolve()``
  would chase the link to its real path, breaking ``relative_to()``.
- Top-level subdirs of ``live2d/`` are considered character slugs.
- ``core/`` is the Cubism Core JS SDK runtime (whitelisted in .gitignore
  alongside ``hiyori/``); skipped here because it has no ``.model3.json``.
- Hidden directories (``.DS_Store`` parents etc.) and ``__pycache__`` are
  also skipped defensively even though they shouldn't appear under
  ``live2d/`` in practice.
- Each slug folder is scanned **one level deep** (root + immediate
  children) for ``*.model3.json``. A slug containing zero entries → an
  entry with ``pixi_compatible=False`` and a warning. Multiple entries →
  the first wins, with a warning naming the chosen file.

The moc3 version probe is intentionally **duplicated** from
``tools/check_moc3_version.py`` (only the binary header parser, ~10 lines
of code). They sit in different process roles (one-shot CLI vs runtime
HTTP service) and we don't want a runtime import dependency on a
``tools/`` package that is otherwise standalone. Future cleanup: extract
to a shared ``backend.utils.moc3`` if a third caller ever appears.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

# Pydantic 2.x 在 Python <3.12 上对 typing.TypedDict 的 schema 推断坏掉，
# 必须用 typing_extensions.TypedDict（FastAPI response_model 推断走 pydantic）。
from typing_extensions import TypedDict

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Path anchoring — never trust CWD (uvicorn / Tauri launch with diff CWDs).
# ---------------------------------------------------------------------------

# This file: <repo>/backend/services/live2d_scanner.py
# parents:    [services, backend, <repo root>]
#
# 用 .absolute() 而非 .resolve() —— 不解析 symlink，让 ``frontend/public/
# live2d/yae`` 这种指向外部 IP 资产的软链保持在 repo path 命名空间内，
# 后续 relative_to(public_root) 能算出正确的 Vite 静态 URL。详见模块顶
# "Symlink discipline" 段。
_REPO_ROOT = Path(__file__).absolute().parents[2]
_LIVE2D_DIR = _REPO_ROOT / "frontend" / "public" / "live2d"

# 子目录黑名单：core/ 是 SDK runtime（v3-E2 commit 2 .gitignore 白名单），
# __pycache__ 是 Python 副产物，"."开头的是隐藏目录。
_SKIP_DIRS: frozenset[str] = frozenset({"core", "__pycache__"})


# ---------------------------------------------------------------------------
# moc3 binary header parser — duplicated from tools/check_moc3_version.py.
# 头注释解释为什么不引入跨包依赖。
# ---------------------------------------------------------------------------

_MOC3_MAGIC = b"MOC3"
_PIXI_MAX_SUPPORTED = 4

_SDK_LABEL: dict[int, str] = {
    1: "Cubism SDK 3.0",
    2: "Cubism SDK 3.3",
    3: "Cubism SDK 4.0",
    4: "Cubism SDK 4.2",
    5: "Cubism SDK 5.0",
}


def _read_moc3_version(path: Path) -> tuple[Optional[int], Optional[str]]:
    """Return ``(version, error)``. Either ``version`` is set, or ``error``."""
    try:
        with path.open("rb") as f:
            head = f.read(5)
    except OSError as exc:
        return None, f"read error: {exc}"
    if len(head) < 5:
        return None, f"file too short ({len(head)} bytes)"
    if head[:4] != _MOC3_MAGIC:
        return None, f"bad magic: {head[:4]!r} (Cubism 2 .moc?)"
    return head[4], None


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


class Live2DModelInfo(TypedDict):
    slug: str
    model3_path: str           # /-prefixed Vite static URL
    moc3_path: str             # 同上；entry 解析失败时为空串
    moc3_version: Optional[int]
    moc3_version_label: str
    pixi_compatible: bool
    warnings: list[str]


class Live2DScanResult(TypedDict):
    scan_dir: str
    models: list[Live2DModelInfo]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_static_url(abs_path: Path) -> str:
    """``<repo>/frontend/public/live2d/hiyori/x.moc3`` → ``/live2d/hiyori/x.moc3``.

    Vite serves ``frontend/public/`` at site root; trim that prefix and
    keep the part after for the URL the browser can hit.
    """
    public_root = _REPO_ROOT / "frontend" / "public"
    rel = abs_path.relative_to(public_root)
    # Path.as_posix() 保证斜杠平台无关
    return "/" + rel.as_posix()


def _find_model3_json(slug_dir: Path) -> tuple[list[Path], list[str]]:
    """One-level-deep search inside ``slug_dir`` for ``*.model3.json``.

    Returns ``(entries, warnings)``. Empty entries list means none found —
    caller decides how to mark the slug.
    """
    warnings: list[str] = []
    # 1 层 = root + 直接子目录。Hiyori 实际 model3.json 就在 slug_dir 根；
    # 一些其他模型把入口放在 runtime/ 子目录里，扫一层兼容这两种 layout。
    candidates: list[Path] = sorted(slug_dir.glob("*.model3.json"))
    for sub in sorted(p for p in slug_dir.iterdir() if p.is_dir()):
        candidates.extend(sorted(sub.glob("*.model3.json")))
    return candidates, warnings


def _scan_slug(slug_dir: Path) -> Live2DModelInfo:
    """Build the API entry for one slug directory. Never raises."""
    slug = slug_dir.name
    warnings: list[str] = []

    entries, _ = _find_model3_json(slug_dir)
    if not entries:
        return Live2DModelInfo(
            slug=slug,
            model3_path="",
            moc3_path="",
            moc3_version=None,
            moc3_version_label="unknown",
            pixi_compatible=False,
            warnings=["no model3.json entry found"],
        )
    if len(entries) > 1:
        warnings.append(
            f"multiple model3.json found, using {entries[0].name}"
        )
    entry = entries[0]
    model3_url = _to_static_url(entry)

    # 解析 model3.json → FileReferences.Moc 拿 .moc3 路径
    moc3_path: Path
    try:
        with entry.open("r", encoding="utf-8") as f:
            data = json.load(f)
        moc_rel = data.get("FileReferences", {}).get("Moc")
        if not isinstance(moc_rel, str) or not moc_rel:
            return Live2DModelInfo(
                slug=slug,
                model3_path=model3_url,
                moc3_path="",
                moc3_version=None,
                moc3_version_label="unknown",
                pixi_compatible=False,
                warnings=warnings + ["FileReferences.Moc missing in model3.json"],
            )
        # .absolute() not .resolve() —— 不能 follow yae symlink 跳出 repo
        # path 空间，否则 _to_static_url 的 relative_to(public_root) 会炸。
        # moc_rel 一般是干净的相对文件名（"BCSZ1.1.moc3"），.absolute() 同
        # 时把可能的 ``../`` 等相对成分规整为绝对路径，又不解析 symlink。
        moc3_path = (entry.parent / moc_rel).absolute()
    except json.JSONDecodeError as exc:
        return Live2DModelInfo(
            slug=slug,
            model3_path=model3_url,
            moc3_path="",
            moc3_version=None,
            moc3_version_label="unknown",
            pixi_compatible=False,
            warnings=warnings + [f"model3.json parse error: {exc}"],
        )
    except OSError as exc:
        return Live2DModelInfo(
            slug=slug,
            model3_path=model3_url,
            moc3_path="",
            moc3_version=None,
            moc3_version_label="unknown",
            pixi_compatible=False,
            warnings=warnings + [f"model3.json read error: {exc}"],
        )

    if not moc3_path.exists():
        return Live2DModelInfo(
            slug=slug,
            model3_path=model3_url,
            moc3_path="",
            moc3_version=None,
            moc3_version_label="unknown",
            pixi_compatible=False,
            warnings=warnings + [f"moc3 file missing at {moc3_path.name}"],
        )

    version, err = _read_moc3_version(moc3_path)
    if err is not None or version is None:
        return Live2DModelInfo(
            slug=slug,
            model3_path=model3_url,
            moc3_path=_to_static_url(moc3_path),
            moc3_version=None,
            moc3_version_label="unknown",
            pixi_compatible=False,
            warnings=warnings + [f"moc3 header invalid: {err or 'no version'}"],
        )

    label = _SDK_LABEL.get(version, f"unknown SDK (v={version})")
    pixi_ok = version <= _PIXI_MAX_SUPPORTED
    if not pixi_ok:
        warnings.append(
            f"moc3 version {version} ({label}) exceeds pixi-live2d-display "
            f"max supported v{_PIXI_MAX_SUPPORTED}"
        )

    return Live2DModelInfo(
        slug=slug,
        model3_path=model3_url,
        moc3_path=_to_static_url(moc3_path),
        moc3_version=version,
        moc3_version_label=label,
        pixi_compatible=pixi_ok,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------


def scan_live2d_models() -> Live2DScanResult:
    """Enumerate ``frontend/public/live2d/<slug>/`` directories.

    Always returns; per-slug failures are surfaced via ``warnings`` rather
    than raising. ``scan_dir`` is project-relative for clarity in the
    response (absolute path leaks workstation layout to clients).
    """
    rel_scan_dir = "frontend/public/live2d"
    if not _LIVE2D_DIR.is_dir():
        logger.warning(
            "[live2d] scan dir not found at %s — returning empty list",
            _LIVE2D_DIR,
        )
        return Live2DScanResult(scan_dir=rel_scan_dir, models=[])

    models: list[Live2DModelInfo] = []
    for child in sorted(_LIVE2D_DIR.iterdir()):
        if not child.is_dir():
            continue
        if child.name in _SKIP_DIRS or child.name.startswith("."):
            continue
        try:
            info = _scan_slug(child)
        except Exception as exc:  # 防御兜底，单 slug 不能拖垮整个扫描
            logger.exception("[live2d] unexpected error scanning %s", child.name)
            info = Live2DModelInfo(
                slug=child.name,
                model3_path="",
                moc3_path="",
                moc3_version=None,
                moc3_version_label="unknown",
                pixi_compatible=False,
                warnings=[f"scanner error: {exc}"],
            )
        models.append(info)

    return Live2DScanResult(scan_dir=rel_scan_dir, models=models)
