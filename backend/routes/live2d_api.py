"""Live2D models REST API.

Mounted at /api in main.py.  Full URL map:
  GET  /api/live2d/models
  POST /api/live2d/upload   (Stage 2.2.0)

v3-E2 commit 3a — 让 CharacterPanel UI 拿到一份"当前已 ship 的 Live2D 角色
列表 + pixi 兼容性"，替代之前裸文本框输入。

Stage 2.2.0 — zip 上传:用户从前端拖入完整 model package(.zip),后端
验证 + safe_path 解压 + 自动生成 motionMap 默认值,前端不再需要手动
``ln -s`` 到 ``frontend/public/live2d/``。
"""
from __future__ import annotations

import logging
import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from pydantic import BaseModel

from backend.services import live2d_scanner
from backend.services.live2d_scanner import (
    Live2DScanResult, scan_live2d_models, _PIXI_MAX_SUPPORTED, _read_moc3_version,
)
from backend.utils.safe_path import safe_resolve

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/live2d/models")
async def list_live2d_models() -> Live2DScanResult:
    """Return the currently-shipping Live2D character roster.

    扫描 ``frontend/public/live2d/<slug>/``，每条结果带 pixi-live2d-display
    兼容判定 + warnings。单 slug 的解析失败不会让整个 API fail —— 错误以
    ``warnings`` 数组返回，``pixi_compatible=False``。
    """
    return scan_live2d_models()


# ---------------------------------------------------------------------------
# Stage 2.2.0 — POST /api/live2d/upload
# ---------------------------------------------------------------------------

# Slug 命名规则:小写字母 / 数字 / 连字符 / 下划线,2-40 字符。与 vite static
# url 友好(避免 URL 转义)+ 与 character.live2d_model 字段长度兼容。
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,39}$")

# 单 zip 大小上限:30 MB。Hiyori (含 textures) ~2 MB;商业精品模型一般
# 10-20 MB。30 MB 给 4K texture 留余地,同时拦异常大上传。
_MAX_ZIP_SIZE = 30 * 1024 * 1024

# zip 内单成员解压后大小上限:防 zip bomb。10 MB / 成员够大多数 texture。
_MAX_MEMBER_SIZE = 10 * 1024 * 1024


class MotionEntry(BaseModel):
    group: str
    index: int


class UploadResponse(BaseModel):
    slug: str
    moc3_version: int
    moc3_version_label: str
    textures_count: int
    motions_count: int
    motion_map: dict[str, MotionEntry]
    model_path: str   # vite static url, e.g. ``/live2d/<slug>/foo.model3.json``


def _infer_slug_from_moc3(name: str) -> str:
    """从 .moc3 文件 stem 推断 slug。

    ``hiyori_pro_t11.moc3`` → ``hiyori_pro_t11``。先 lower-case,然后把
    非法字符替换成 ``_``,再 squeeze 重复 ``_``,头尾 strip。失败 → 空串
    (上层拒绝)。
    """
    stem = Path(name).stem.lower()
    cleaned = re.sub(r"[^a-z0-9_-]+", "_", stem)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_-")
    return cleaned


def _validate_slug(slug: str) -> None:
    """Slug 必须匹配 ``_SLUG_RE``;否则抛 422。"""
    if not _SLUG_RE.match(slug):
        raise HTTPException(
            status_code=422,
            detail=(
                f"invalid slug {slug!r}: must be 2-40 chars of "
                f"[a-z0-9_-], starting with [a-z0-9]"
            ),
        )


def _build_motion_map(motion_filenames: list[str]) -> dict[str, MotionEntry]:
    """从 ``.motion3.json`` 文件名列表生成默认 motionMap。

    每个 motion file → ``{stem: {group: stem, index: 0}}``。stem 已含
    所有可识别 group 信息(模型作者通常按 ``GroupName_01.motion3.json``
    命名)。重名 stem 合并到同一 entry(用户后续可在前端 motion_map_json
    自定义覆盖)。
    """
    out: dict[str, MotionEntry] = {}
    for name in motion_filenames:
        stem = Path(name).name
        # 去掉 .motion3.json 双后缀(``.motion3`` + ``.json``)
        if stem.lower().endswith(".motion3.json"):
            stem = stem[: -len(".motion3.json")]
        else:
            stem = Path(stem).stem
        if not stem or stem in out:
            continue
        out[stem] = MotionEntry(group=stem, index=0)
    return out


@router.post(
    "/live2d/upload",
    response_model=UploadResponse,
)
async def upload_live2d_model(
    file: UploadFile = File(...),
    slug: Optional[str] = Query(default=None, description="可选;不指定从 .moc3 stem 推断"),
) -> UploadResponse:
    """接收 .zip 模型 package,验证 + 解压到 ``frontend/public/live2d/<slug>/``。

    流程:
      1. 落 tmpfile + 30MB 大小上限
      2. ``zipfile.ZipFile`` 校验完整性 + 列文件
      3. 强制要求 1 个 .moc3 + 1 个 .model3.json(其他可选)
      4. ``safe_resolve(allow_subdirs=True)`` 校验每个成员路径(防 ``..``)
      5. ``_read_moc3_version`` 读 magic + version byte;ver=5 → 422
      6. slug 推断 / 验证 + 409 已存在检查
      7. 解压到目标 slug 目录(保留 zip 内目录结构)
      8. 扫 .motion3.json 文件名生成 motion_map 默认值
    """
    # 1. 落 tmpfile —— 流式读以拦截大文件
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(
            status_code=422, detail="upload must be a .zip file",
        )

    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
        tmp_path = Path(tmp.name)
        total = 0
        while True:
            chunk = await file.read(64 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > _MAX_ZIP_SIZE:
                tmp.close()
                tmp_path.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=422,
                    detail=f"zip exceeds {_MAX_ZIP_SIZE // (1024 * 1024)}MB limit",
                )
            tmp.write(chunk)

    try:
        return await _process_zip(tmp_path, slug)
    finally:
        tmp_path.unlink(missing_ok=True)


async def _process_zip(
    zip_path: Path, requested_slug: Optional[str],
) -> UploadResponse:
    """zip 校验 + 解压主流程。`upload_live2d_model` 已做大小限制 + 落盘。"""
    # 2. 打开 zip + 列文件
    try:
        zf = zipfile.ZipFile(zip_path, "r")
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=422, detail=f"invalid zip file: {exc}")

    with zf:
        # 用 namelist() 而非 infolist() —— 只关心文件名,简洁
        all_names = [n for n in zf.namelist() if not n.endswith("/")]

        # 3. 必备文件存在性
        moc3_names = [n for n in all_names if n.lower().endswith(".moc3")]
        model3_names = [
            n for n in all_names if n.lower().endswith(".model3.json")
        ]
        if len(moc3_names) == 0:
            raise HTTPException(
                status_code=422,
                detail="zip must contain exactly one .moc3 file (found 0)",
            )
        if len(moc3_names) > 1:
            raise HTTPException(
                status_code=422,
                detail=f"zip must contain exactly one .moc3 file (found "
                f"{len(moc3_names)}: {moc3_names!r})",
            )
        if len(model3_names) == 0:
            raise HTTPException(
                status_code=422,
                detail="zip must contain at least one .model3.json file",
            )

        moc3_name = moc3_names[0]
        model3_name = model3_names[0]
        motion_names = [
            n for n in all_names if n.lower().endswith(".motion3.json")
        ]
        texture_names = [
            n for n in all_names if n.lower().endswith((".png", ".jpg", ".jpeg"))
        ]

        # 4. slug 推断 + 验证
        final_slug = (requested_slug or "").strip().lower() or _infer_slug_from_moc3(moc3_name)
        if not final_slug:
            raise HTTPException(
                status_code=422,
                detail=f"cannot infer slug from .moc3 name {moc3_name!r}; "
                f"specify ?slug=...",
            )
        _validate_slug(final_slug)

        # 5. 检查目标目录不存在(409)+ 用 safe_resolve 验证 slug 自身合法
        live2d_dir = live2d_scanner._LIVE2D_DIR
        try:
            target_slug_dir = safe_resolve(live2d_dir, final_slug, allow_subdirs=False)
        except ValueError as exc:
            # 不应该发生(slug 已过 _SLUG_RE),保留兜底
            raise HTTPException(status_code=422, detail=str(exc))
        if target_slug_dir.exists():
            raise HTTPException(
                status_code=409,
                detail=f"model slug {final_slug!r} already exists; "
                f"rename or delete the existing model first",
            )

        # 6. 校验每个 zip member 路径不越界 + 提前读 .moc3 头检查版本
        for member in all_names:
            try:
                # allow_subdirs=True —— 允许 zip 内嵌套目录(textures/、motion/ 等)
                safe_resolve(target_slug_dir.parent, f"{final_slug}/{member}",
                             allow_subdirs=True)
            except ValueError as exc:
                raise HTTPException(
                    status_code=422,
                    detail=f"zip member {member!r} escapes sandbox: {exc}",
                )
            # 拦 zip-bomb:单成员解压后大小过大
            info = zf.getinfo(member)
            if info.file_size > _MAX_MEMBER_SIZE:
                raise HTTPException(
                    status_code=422,
                    detail=f"zip member {member!r} exceeds per-file limit "
                    f"({info.file_size} > {_MAX_MEMBER_SIZE})",
                )

        # 7. 读 .moc3 头到内存,校验 magic + version
        moc3_data = zf.read(moc3_name)
        if len(moc3_data) < 5:
            raise HTTPException(
                status_code=422,
                detail=f"{moc3_name!r} too short to be a valid .moc3",
            )
        if moc3_data[:4] != b"MOC3":
            raise HTTPException(
                status_code=422,
                detail=f"{moc3_name!r} has bad magic (not Cubism 3+ .moc3)",
            )
        moc3_version = moc3_data[4]
        if moc3_version > _PIXI_MAX_SUPPORTED:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Cubism SDK {moc3_version}.x not supported "
                    f"(pixi-live2d-display max = SDK {_PIXI_MAX_SUPPORTED}.x). "
                    f"Use a Cubism 4.2 or earlier model."
                ),
            )

        # 8. 解压!到 target_slug_dir。先建目录再 extractall。
        try:
            target_slug_dir.mkdir(parents=True, exist_ok=False)
            try:
                zf.extractall(target_slug_dir)
            except Exception:
                # 解压中途失败 → 整目录 rollback
                shutil.rmtree(target_slug_dir, ignore_errors=True)
                raise
        except FileExistsError:
            # 应该已被前面的 if target_slug_dir.exists() 拦住
            raise HTTPException(
                status_code=409,
                detail=f"slug {final_slug!r} already exists (race)",
            )
        except Exception as exc:
            logger.exception("[live2d.upload] extract failed for %s", final_slug)
            raise HTTPException(
                status_code=500, detail=f"extract failed: {exc}",
            )

    # 9. moc3 version 标签
    label_map: dict[int, str] = {
        1: "Cubism SDK 3.0", 2: "Cubism SDK 3.3",
        3: "Cubism SDK 4.0", 4: "Cubism SDK 4.2",
    }
    version_label = label_map.get(int(moc3_version), f"Cubism SDK ver={moc3_version}")

    # 10. 生成 motion_map 默认值
    motion_map = _build_motion_map(motion_names)

    # 11. Vite static url:``/live2d/<slug>/<zip_entry_relative_path>``。
    #     直接拼比 ``live2d_scanner._to_static_url(abs_path)`` 简单——后者会
    #     要求 abs_path 必须在 repo 的 ``frontend/public/`` 下,跟测试隔离
    #     目录不兼容。本路径只依赖 slug + zip entry name,与 scanner 一致
    #     (scanner 算法等价于 ``/live2d/<slug>/<rel>``)。
    posix_member = Path(model3_name).as_posix()
    model_path = f"/live2d/{final_slug}/{posix_member}"

    logger.info(
        "[live2d.upload] slug=%s moc3_ver=%d textures=%d motions=%d",
        final_slug, moc3_version, len(texture_names), len(motion_names),
    )
    return UploadResponse(
        slug=final_slug,
        moc3_version=int(moc3_version),
        moc3_version_label=version_label,
        textures_count=len(texture_names),
        motions_count=len(motion_names),
        motion_map=motion_map,
        model_path=model_path,
    )


# Suppress unused-import warning for _read_moc3_version: kept as
# explicit re-export in case future tests want to monkey-patch it via this
# module. The current upload path does its own inline magic check (above)
# so the failure-line numbers stay localized.
_ = _read_moc3_version
