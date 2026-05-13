"""Characters REST API.

Mounted at /api in main.py.  Full URL map:
  GET    /api/characters/list
  POST   /api/characters/create
  PATCH  /api/characters/{id}
  DELETE /api/characters/{id}
  POST   /api/characters/{id}/splash-art   (v4-fan chunk 1)
  DELETE /api/characters/{id}/splash-art   (v4-fan chunk 1)
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Final, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_session
from backend.database.models import Character
from backend.utils.safe_path import safe_resolve

logger = logging.getLogger(__name__)

router = APIRouter()


DEFAULT_CHARACTER_NAME = "Momo"


# ---------------------------------------------------------------------------
# v4-fan chunk 1 — splash art upload constants
# ---------------------------------------------------------------------------
# 路径锚定:与 live2d_scanner._LIVE2D_DIR 同 pattern——从本文件向上 2 层
# 到 repo root,再 ``frontend/public/splash-art/``。``Path.cwd()`` 不可信
# (uvicorn / Tauri 启动 CWD 不同)。
_REPO_ROOT: Final[Path] = Path(__file__).absolute().parents[2]
_SPLASH_ART_DIR: Path = _REPO_ROOT / "frontend" / "public" / "splash-art"

# 5 MB 上限。1024×1536 JPEG 通常 1-2 MB,PNG 3-4 MB,5 MB 给 PNG / 高分
# WebP 留余地;同时拦异常大上传(用户应在客户端做 resize,不该传 4K 原图)。
_MAX_SPLASH_SIZE: Final[int] = 5 * 1024 * 1024

# 支持的扩展名 → 规范化(.jpeg / .jpg 都接受,落盘统一 ``.jpg``)。
# 顺序:常见度优先(jpg / png / webp 三种二次元立绘最常见)。
_MIME_TO_EXT: Final[dict[str, str]] = {
    "image/jpeg": ".jpg",
    "image/png":  ".png",
    "image/webp": ".webp",
}

# 扩展名白名单(MIME 缺失时的兜底匹配)。Tauri WebView 偶尔 file.type=""
# (空字符串)而非具体 MIME,与 Live2DDropzone.tsx 同 pattern。
_EXT_WHITELIST: Final[frozenset[str]] = frozenset({".jpg", ".jpeg", ".png", ".webp"})

# 同 character.id 的旧文件(任意扩展名)cleanup 用。
_ALL_SPLASH_EXTS: Final[tuple[str, ...]] = (".jpg", ".jpeg", ".png", ".webp")


def _fmt_dt(dt: Optional[datetime]) -> Optional[str]:
    return dt.strftime("%Y-%m-%d %H:%M:%S") if dt else None


def _to_dict(c: Character) -> dict:
    return {
        "id": c.id,
        "name": c.name,
        "persona": c.persona,
        "avatar_path": c.avatar_path,
        "voice_model": c.voice_model,
        "live2d_model": c.live2d_model,
        # v3-E2: per-character map JSON 字段。NULL → 前端 resolveCharacterMaps
        # 回退到 config/live2d.ts 全局默认。
        "emotion_map_json":  c.emotion_map_json,
        "motion_map_json":   c.motion_map_json,
        "hit_area_map_json": c.hit_area_map_json,
        # v3.5 chunk 5a: per-character 背景层 URL（image / video）。NULL =
        # 用现有 fallback 链（Live2D / 静态 jpeg），CharacterView 透明处理。
        "background_path":   c.background_path,
        # v4-fan chunk 1: Fan UI 扇面卡牌底图 URL。NULL = 走前端 fallback 占位。
        "splash_art_url":    c.splash_art_url,
        "created_at": _fmt_dt(c.created_at),
    }


class CharacterCreateBody(BaseModel):
    name: str
    persona: str
    avatar_path: Optional[str] = None
    voice_model: Optional[str] = None
    live2d_model: Optional[str] = None
    # v3-E2: per-character maps（JSON 字符串），可选。Schema 不下放校验，
    # 前端 parse 失败兜底回退默认 + console.warn。
    emotion_map_json:  Optional[str] = None
    motion_map_json:   Optional[str] = None
    hit_area_map_json: Optional[str] = None
    # v3.5 chunk 5a: 可选背景资产 URL。None / 空串都视为"未配置"。
    background_path:   Optional[str] = None


class CharacterPatchBody(BaseModel):
    name: Optional[str] = None
    persona: Optional[str] = None
    avatar_path: Optional[str] = None
    voice_model: Optional[str] = None
    live2d_model: Optional[str] = None
    emotion_map_json:  Optional[str] = None
    motion_map_json:   Optional[str] = None
    hit_area_map_json: Optional[str] = None
    # v3.5 chunk 5a: PATCH 时传 None 表示清除；传字符串覆盖。
    background_path:   Optional[str] = None


@router.get("/characters/list")
async def list_characters(
    session: AsyncSession = Depends(get_session),
) -> List[dict]:
    rows = list((await session.execute(
        select(Character).order_by(Character.id.asc())
    )).scalars().all())
    return [_to_dict(c) for c in rows]


@router.post("/characters/create", status_code=201)
async def create_character(
    body: CharacterCreateBody,
    session: AsyncSession = Depends(get_session),
) -> dict:
    if not body.name.strip() or not body.persona.strip():
        raise HTTPException(status_code=422, detail="name and persona are required")
    existing = (await session.execute(
        select(Character).where(Character.name == body.name)
    )).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="character name already exists")
    c = Character(
        name=body.name,
        persona=body.persona,
        avatar_path=body.avatar_path,
        voice_model=body.voice_model,
        live2d_model=body.live2d_model,
        emotion_map_json=body.emotion_map_json,
        motion_map_json=body.motion_map_json,
        hit_area_map_json=body.hit_area_map_json,
        background_path=body.background_path,
    )
    session.add(c)
    await session.commit()
    await session.refresh(c)
    return _to_dict(c)


@router.patch("/characters/{character_id}")
async def patch_character(
    character_id: int,
    body: CharacterPatchBody,
    session: AsyncSession = Depends(get_session),
) -> dict:
    c = (await session.execute(
        select(Character).where(Character.id == character_id)
    )).scalar_one_or_none()
    if c is None:
        raise HTTPException(status_code=404, detail="character not found")
    updates = body.model_dump(exclude_unset=True)
    if "name" in updates and updates["name"]:
        c.name = updates["name"]
    if "persona" in updates and updates["persona"]:
        c.persona = updates["persona"]
    if "avatar_path" in updates:
        c.avatar_path = updates["avatar_path"]
    if "voice_model" in updates:
        c.voice_model = updates["voice_model"]
    if "live2d_model" in updates:
        c.live2d_model = updates["live2d_model"]
    if "emotion_map_json" in updates:
        c.emotion_map_json = updates["emotion_map_json"]
    if "motion_map_json" in updates:
        c.motion_map_json = updates["motion_map_json"]
    if "hit_area_map_json" in updates:
        c.hit_area_map_json = updates["hit_area_map_json"]
    if "background_path" in updates:
        # 空串等价 NULL，避免 frontend "(无)" 传空串时落库残留 ""
        bp = updates["background_path"]
        c.background_path = bp if (isinstance(bp, str) and bp.strip()) else None
    await session.commit()
    await session.refresh(c)
    return _to_dict(c)


@router.delete("/characters/{character_id}", status_code=204)
async def delete_character(
    character_id: int,
    session: AsyncSession = Depends(get_session),
) -> None:
    c = (await session.execute(
        select(Character).where(Character.id == character_id)
    )).scalar_one_or_none()
    if c is None:
        raise HTTPException(status_code=404, detail="character not found")
    if c.name == DEFAULT_CHARACTER_NAME:
        raise HTTPException(status_code=403, detail="cannot delete the default Momo character")
    await session.delete(c)
    await session.commit()


# ---------------------------------------------------------------------------
# v4-fan chunk 1 — splash art upload / delete
# ---------------------------------------------------------------------------

def _resolve_splash_ext(
    content_type: Optional[str], filename: Optional[str],
) -> str:
    """从 MIME + 文件名推断目标扩展名。

    优先 MIME(可信);Tauri WebView 偶尔 ``content_type=""`` / ``None`` →
    回退 filename 扩展名,与 Live2DDropzone.tsx 同 pattern。``.jpeg`` 落盘
    统一规范化成 ``.jpg``,避免一个角色既有 ``2.jpeg`` 又有 ``2.jpg``。

    返回:目标扩展名(``.jpg`` / ``.png`` / ``.webp``)。
    抛 HTTPException 415:都识别不出。
    """
    if content_type:
        mapped = _MIME_TO_EXT.get(content_type.lower())
        if mapped is not None:
            return mapped
    if filename:
        ext = Path(filename).suffix.lower()
        if ext in _EXT_WHITELIST:
            return ".jpg" if ext == ".jpeg" else ext
    raise HTTPException(
        status_code=415,
        detail=(
            f"unsupported splash art type: content_type={content_type!r} "
            f"filename={filename!r}; expected png / jpeg / webp"
        ),
    )


def _purge_old_splash(character_id: int) -> None:
    """删除该 character.id 下所有已有扩展名的 splash art。

    覆盖 ``2.jpg`` → ``2.png`` 这种"换格式"场景:旧文件不清会留两份在
    ``frontend/public/splash-art/`` 下,vite 仍会 serve 旧那份。即便目标
    目录不存在(首次上传)也安全 —— glob/unlink 都对缺位友好。
    """
    if not _SPLASH_ART_DIR.is_dir():
        return
    for ext in _ALL_SPLASH_EXTS:
        p = _SPLASH_ART_DIR / f"{character_id}{ext}"
        if p.exists():
            try:
                p.unlink()
            except OSError as exc:
                # 不致命:vite 会 serve 新文件;旧文件残留只占磁盘
                logger.warning(
                    "[splash_art] failed to unlink old %s: %s", p, exc,
                )


@router.post("/characters/{character_id}/splash-art")
async def upload_splash_art(
    character_id: int,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """接收单图 multipart,落到 ``frontend/public/splash-art/<id>.<ext>``。

    流程:
      1. SELECT character → 404 if missing
      2. MIME / 扩展名校验 → 415 if not png/jpeg/webp
      3. 流式读 + 5MB 大小拦截 → 413 if too large
      4. safe_resolve 验证目标路径在沙箱内
      5. purge 旧文件(任意已有扩展名)
      6. 写新文件;失败 rollback 不留半文件
      7. UPDATE characters.splash_art_url + commit
      8. 返回 ``{character_id, splash_art_url}``
    """
    # 1. character 存在性
    c = (await session.execute(
        select(Character).where(Character.id == character_id)
    )).scalar_one_or_none()
    if c is None:
        raise HTTPException(status_code=404, detail="character not found")

    # 2. 类型校验(MIME 优先,filename 兜底)
    target_ext = _resolve_splash_ext(file.content_type, file.filename)

    # 3. 流式读 + 5MB 拦截。先读完再 safe_resolve / 写盘,避免小文件场景
    #    多一次目录创建 IO。
    data = bytearray()
    while True:
        chunk = await file.read(64 * 1024)
        if not chunk:
            break
        data.extend(chunk)
        if len(data) > _MAX_SPLASH_SIZE:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"splash art exceeds {_MAX_SPLASH_SIZE // (1024 * 1024)}MB "
                    f"limit"
                ),
            )

    # 4. 沙箱目录 ensure + safe_resolve(防御 character_id 异常映射场景)
    _SPLASH_ART_DIR.mkdir(parents=True, exist_ok=True)
    target_filename = f"{character_id}{target_ext}"
    try:
        target_path = safe_resolve(
            _SPLASH_ART_DIR, target_filename, allow_subdirs=False,
        )
    except ValueError as exc:
        # int character_id 无法构造越界路径,但保留兜底以防未来字段类型改动
        raise HTTPException(status_code=422, detail=str(exc))

    # 5. cleanup 旧扩展名残留(2.jpg → 上传 2.png 时 2.jpg 必须删)
    _purge_old_splash(character_id)

    # 6. 写文件;失败 unlink + rollback DB(尚未 commit)
    try:
        target_path.write_bytes(bytes(data))
    except OSError as exc:
        # 不留半文件:OSError 可能在写途中,文件可能已部分写
        if target_path.exists():
            try:
                target_path.unlink()
            except OSError:
                pass
        logger.exception(
            "[splash_art] write failed for character_id=%d", character_id,
        )
        raise HTTPException(
            status_code=500, detail=f"failed to write splash art: {exc}",
        )

    # 7. DB update
    splash_url = f"/splash-art/{target_filename}"
    c.splash_art_url = splash_url
    await session.commit()

    logger.info(
        "[splash_art] uploaded character_id=%d size=%d ext=%s url=%s",
        character_id, len(data), target_ext, splash_url,
    )
    return {"character_id": character_id, "splash_art_url": splash_url}


@router.delete("/characters/{character_id}/splash-art")
async def delete_splash_art(
    character_id: int,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """删除该 character 的立绘:文件 unlink + DB url=NULL。

    幂等:文件 / DB 字段已为空也 200。这是"reset to fallback"语义,不是
    "deletion",所以不返 204 —— 让前端拿到 ``{deleted: true}`` 做 UI 反馈。
    """
    c = (await session.execute(
        select(Character).where(Character.id == character_id)
    )).scalar_one_or_none()
    if c is None:
        raise HTTPException(status_code=404, detail="character not found")

    _purge_old_splash(character_id)
    c.splash_art_url = None
    await session.commit()

    logger.info("[splash_art] deleted character_id=%d", character_id)
    return {"character_id": character_id, "deleted": True}
