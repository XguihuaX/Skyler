"""V4 voice greeting · character voice lines CRUD + random pick。

per PM dispatch(2026-05-22)· 立绘馆放大组件 onEnter random play 路径:
  - POST   /api/character/{cid}/voice_lines        · multipart upload
  - GET    /api/character/{cid}/voice_lines        · list per character
  - GET    /api/character/{cid}/voice_lines/random · 1 random(404 if empty)
  - DELETE /api/character/{cid}/voice_lines/{lid}  · del file + DB row

audio 存 ``backend/static/voice_lines/<cid>/<uuid>.<ext>``;前端通过
``/static/voice_lines/<cid>/<uuid>.<ext>`` URL 拿(per main.py StaticFiles
mount)。

格式校验:.wav / .mp3 / .ogg 白名单;5MB 大小 cap(类比 splash-art
characters_api.py upload pattern)。duration_ms 通过 mutagen 提取
(已装 per requirements)。

参考:characters_api.py upload_splash_art for multipart 上传 idiom。
"""
from __future__ import annotations

import logging
import random
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_session

logger = logging.getLogger(__name__)

router = APIRouter()

# Audio storage 根目录 — 相对 repo root(per main.py StaticFiles mount)
_VOICE_LINES_DIR = Path(__file__).resolve().parent.parent / "static" / "voice_lines"
_MAX_VOICE_SIZE: int = 5 * 1024 * 1024  # 5 MB
_ALLOWED_EXTS: set[str] = {".wav", ".mp3", ".ogg"}
# audio/* MIME -> ext 兜底
_MIME_TO_EXT: dict[str, str] = {
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/wave": ".wav",
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/ogg": ".ogg",
    "audio/vorbis": ".ogg",
}


def _resolve_ext(content_type: Optional[str], filename: Optional[str]) -> str:
    """MIME 优先 + filename 兜底 + 白名单校验。"""
    if content_type and content_type.lower() in _MIME_TO_EXT:
        return _MIME_TO_EXT[content_type.lower()]
    if filename:
        ext = Path(filename).suffix.lower()
        if ext in _ALLOWED_EXTS:
            return ext
    raise HTTPException(
        status_code=415,
        detail=f"unsupported audio format; allowed: {sorted(_ALLOWED_EXTS)}",
    )


def _extract_duration_ms(file_path: Path) -> Optional[int]:
    """提取音频时长(ms);失败返 None(不阻塞 INSERT)。

    WAV 路径:用 Python 标准 ``wave`` 读 sample_rate / channels / sampwidth
              + ``file_size`` 推算 audio_bytes / bytes_per_sec(per Fish
              s2-pro 生成 WAV header ``n_frames=INT_MAX`` bug 兜底;
              mutagen / wave.getnframes() 都会被该 bug 误导)。
    mp3/ogg/其它 · 走 mutagen(bitrate-based info.length 可信)。
    """
    ext = file_path.suffix.lower()
    file_size = file_path.stat().st_size if file_path.exists() else 0

    if ext == ".wav":
        try:
            import wave
            with wave.open(str(file_path), "rb") as w:
                sr = w.getframerate()
                ch = w.getnchannels()
                sw = w.getsampwidth()
            bytes_per_sec = sr * ch * sw
            if bytes_per_sec <= 0:
                return None
            # 减 WAV header ~44 bytes(RIFF + fmt + data chunk overhead;
            # 真实 audio bytes ≈ file_size - 44。误差 < 0.5ms 可忽略)
            audio_bytes = max(0, file_size - 44)
            return int(round(audio_bytes / bytes_per_sec * 1000))
        except Exception as exc:
            logger.warning(
                "[voice_lines] wave-based duration extract failed for %s: %s",
                file_path, exc,
            )
            return None

    # mp3 / ogg / 其它 · mutagen bitrate-based
    try:
        from mutagen import File as MutagenFile
        m = MutagenFile(str(file_path))
        if m is None or not hasattr(m, "info") or m.info is None:
            return None
        length_sec = getattr(m.info, "length", None)
        if length_sec is None:
            return None
        return int(round(length_sec * 1000))
    except Exception as exc:
        logger.warning(
            "[voice_lines] mutagen duration extract failed for %s: %s",
            file_path, exc,
        )
        return None


# Public export · seed script 等外部 caller 用同款 robust 实现
extract_audio_duration_ms = _extract_duration_ms


async def _character_exists(session: AsyncSession, character_id: int) -> bool:
    row = (await session.execute(text(
        "SELECT 1 FROM characters WHERE id = :cid"
    ), {"cid": character_id})).first()
    return row is not None


@router.post("/character/{character_id}/voice_lines")
async def upload_voice_line(
    character_id: int,
    file: UploadFile = File(...),
    text_description: Optional[str] = Form(None),
    language: Optional[str] = Form(None),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """上传单个 voice line 音频文件 + 落 DB。

    流程:
      1. character 存在性检查 → 404
      2. MIME / 扩展名校验 → 415
      3. 流式读 + 5MB 拦截 → 413
      4. 生成 UUID 文件名 → 落 backend/static/voice_lines/{cid}/<uuid>.<ext>
      5. mutagen 提取 duration_ms(失败 None,不阻塞)
      6. INSERT character_voice_lines + return record dict
    """
    if not await _character_exists(session, character_id):
        raise HTTPException(status_code=404, detail="character not found")

    target_ext = _resolve_ext(file.content_type, file.filename)

    # 流式读 + 大小校验
    data = bytearray()
    while True:
        chunk = await file.read(64 * 1024)
        if not chunk:
            break
        data.extend(chunk)
        if len(data) > _MAX_VOICE_SIZE:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"voice line exceeds {_MAX_VOICE_SIZE // (1024 * 1024)}MB limit"
                ),
            )

    # 落盘 · backend/static/voice_lines/<cid>/<uuid>.<ext>
    char_dir = _VOICE_LINES_DIR / str(character_id)
    char_dir.mkdir(parents=True, exist_ok=True)
    new_uuid = uuid.uuid4().hex
    file_name = f"{new_uuid}{target_ext}"
    target_path = char_dir / file_name
    try:
        target_path.write_bytes(bytes(data))
    except OSError as exc:
        logger.error("[voice_lines] write failed: %s", exc)
        raise HTTPException(status_code=500, detail="failed to save file") from exc

    # mutagen duration · 失败不阻塞
    duration_ms = _extract_duration_ms(target_path)

    # 相对路径(per DB 字段 spec):'<cid>/<uuid>.<ext>'
    rel_audio_path = f"{character_id}/{file_name}"

    # INSERT
    try:
        result = await session.execute(text("""
            INSERT INTO character_voice_lines
                (character_id, audio_path, text_description, language, duration_ms)
            VALUES (:cid, :path, :desc, :lang, :dur)
        """), {
            "cid": character_id,
            "path": rel_audio_path,
            "desc": text_description.strip() if text_description else None,
            "lang": language.strip() if language else None,
            "dur": duration_ms,
        })
        await session.commit()
        new_id = result.lastrowid
    except Exception as exc:
        # DB INSERT 失败 → 删 file 不留半 state
        try:
            target_path.unlink()
        except OSError:
            pass
        await session.rollback()
        logger.exception("[voice_lines] INSERT failed for cid=%s", character_id)
        raise HTTPException(status_code=500, detail="DB insert failed") from exc

    logger.info(
        "[voice_lines] uploaded cid=%s id=%s path=%s duration_ms=%s",
        character_id, new_id, rel_audio_path, duration_ms,
    )
    return {
        "id": new_id,
        "character_id": character_id,
        "audio_path": rel_audio_path,
        "audio_url": f"/static/voice_lines/{rel_audio_path}",
        "text_description": text_description,
        "language": language,
        "duration_ms": duration_ms,
    }


@router.get("/character/{character_id}/voice_lines")
async def list_voice_lines(
    character_id: int,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """List voice lines per character(空 list 仍 200 + items=[])。"""
    if not await _character_exists(session, character_id):
        raise HTTPException(status_code=404, detail="character not found")

    rows = (await session.execute(text("""
        SELECT id, character_id, audio_path, text_description, language,
               duration_ms, created_at
        FROM character_voice_lines
        WHERE character_id = :cid
        ORDER BY created_at DESC, id DESC
    """), {"cid": character_id})).mappings().all()

    items = [{
        "id": r["id"],
        "character_id": r["character_id"],
        "audio_path": r["audio_path"],
        "audio_url": f"/static/voice_lines/{r['audio_path']}",
        "text_description": r["text_description"],
        "language": r["language"],
        "duration_ms": r["duration_ms"],
        "created_at": str(r["created_at"]) if r["created_at"] else None,
    } for r in rows]
    return {"character_id": character_id, "count": len(items), "items": items}


@router.get("/character/{character_id}/voice_lines/random")
async def get_random_voice_line(
    character_id: int,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """随机返 1 条 voice line;空 list → 404。

    立绘馆放大 onEnter 触发,前端 fetch 404 / 失败时静默不播(per PM spec)。
    """
    if not await _character_exists(session, character_id):
        raise HTTPException(status_code=404, detail="character not found")

    rows = (await session.execute(text("""
        SELECT id, character_id, audio_path, text_description, language,
               duration_ms, created_at
        FROM character_voice_lines
        WHERE character_id = :cid
    """), {"cid": character_id})).mappings().all()

    if not rows:
        raise HTTPException(
            status_code=404, detail="no voice lines for this character",
        )

    pick = random.choice(rows)
    return {
        "id": pick["id"],
        "character_id": pick["character_id"],
        "audio_path": pick["audio_path"],
        "audio_url": f"/static/voice_lines/{pick['audio_path']}",
        "text_description": pick["text_description"],
        "language": pick["language"],
        "duration_ms": pick["duration_ms"],
    }


@router.delete("/character/{character_id}/voice_lines/{line_id}")
async def delete_voice_line(
    character_id: int,
    line_id: int,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """删 voice line · DELETE file + DB row。

    file unlink 失败不阻塞 DB DELETE(主路径以 DB 为准;orphan file 占磁盘
    可后续 GC,per characters_api splash_art purge 同 pattern)。
    """
    row = (await session.execute(text("""
        SELECT audio_path FROM character_voice_lines
        WHERE id = :lid AND character_id = :cid
    """), {"lid": line_id, "cid": character_id})).first()
    if row is None:
        raise HTTPException(status_code=404, detail="voice line not found")

    audio_path = row[0]
    full_path = _VOICE_LINES_DIR / audio_path

    # DB DELETE 主路径
    await session.execute(text("""
        DELETE FROM character_voice_lines
        WHERE id = :lid AND character_id = :cid
    """), {"lid": line_id, "cid": character_id})
    await session.commit()

    # file unlink · 失败 warning 不抛
    try:
        if full_path.exists():
            full_path.unlink()
    except OSError as exc:
        logger.warning("[voice_lines] failed to unlink file %s: %s", full_path, exc)

    logger.info(
        "[voice_lines] deleted cid=%s id=%s path=%s",
        character_id, line_id, audio_path,
    )
    return {"deleted_id": line_id, "audio_path": audio_path}
