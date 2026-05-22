"""INV-12 Stage 2(2026-05-23)· Fish TTS 配置管理(user_override 层)。

per PM Q5 lock · 3 层 fallback semantic:
  L1 user_override = voice_model JSON 内 user_* 字段(本 endpoints 操作)
  L2 角色 default  = voice_model JSON 顶层(cid=101 INV-9 §7 a6af74b lock)
  L3 yaml global   = parse_voice_config(default) 兜底

per PM Q5 配对约束:user_reference_audio_path + user_reference_text 同时
存在或同时 None;违反 → FishTTS merge 时 log warning + 全回退 L2(in fish.py)。
本 endpoints 在 POST/DELETE 层也 enforce 配对(避免脏数据入 DB)。

4 endpoints:
  POST   /api/characters/{cid}/fish_config        · multipart upload + 4 字段 save
  GET    /api/characters/{cid}/fish_config        · effective merge + user_* 原值
  POST   /api/characters/{cid}/fish_config/synthesize · 试听(binary audio response)
  DELETE /api/characters/{cid}/fish_config        · 清 4 user_* 字段

audio 存 ``backend/static/fish_references/<cid>/<uuid>.<ext>``(独立 mount,
跟 ``/static/voice_lines/`` 并列 per INV-10 范式);格式 .wav/.mp3/.ogg ≤ 5MB。
"""
from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_session

logger = logging.getLogger(__name__)

router = APIRouter()

# Audio storage 根目录 — 跟 voice_lines 独立 mount(per Stage 1 §1.4)
_FISH_REF_DIR = Path(__file__).resolve().parent.parent / "static" / "fish_references"
_MAX_SIZE: int = 5 * 1024 * 1024  # 5 MB
_ALLOWED_EXTS: set[str] = {".wav", ".mp3", ".ogg"}
_MIME_TO_EXT: dict[str, str] = {
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/wave": ".wav",
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/ogg": ".ogg",
    "audio/vorbis": ".ogg",
}

# 4 user_override 字段(写入 voice_model JSON)
_USER_OVERRIDE_KEYS: tuple[str, ...] = (
    "user_reference_audio_path",
    "user_reference_text",
    "user_fish_temperature",
    "user_fish_top_p",
)


def _resolve_ext(content_type: Optional[str], filename: Optional[str]) -> str:
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


async def _load_character_voice_model(
    session: AsyncSession, character_id: int,
) -> tuple[bool, dict]:
    """Load characters.voice_model JSON · (exists, parsed_dict_or_empty)。"""
    row = (await session.execute(text(
        "SELECT voice_model FROM characters WHERE id = :cid"
    ), {"cid": character_id})).first()
    if row is None:
        return False, {}
    raw = row[0]
    if not raw or not raw.strip():
        return True, {}
    try:
        parsed = json.loads(raw)
        return True, (parsed if isinstance(parsed, dict) else {})
    except (json.JSONDecodeError, TypeError):
        return True, {}


async def _save_character_voice_model(
    session: AsyncSession, character_id: int, vm_dict: dict,
) -> None:
    """Write voice_model JSON back to characters table。"""
    new_json = json.dumps(vm_dict, ensure_ascii=False)
    await session.execute(text(
        "UPDATE characters SET voice_model = :vm WHERE id = :cid"
    ), {"vm": new_json, "cid": character_id})
    await session.commit()


def _build_effective_voice_config(vm: dict) -> dict:
    """Return effective fish config(merged L1 user_override > L2 default)+ raw layers。

    返结构:
      {
        "effective": {audio_path, reference_text, temperature, top_p},
                     (merge 后实际用的值;temperature/top_p None = SDK default)
        "default":   {audio_path, reference_text, temperature, top_p}, (L2)
        "user_override": {user_*  字段原值},                            (L1)
        "user_override_active": bool,  (L1 配对完整且 ref override 生效)
      }
    """
    u_audio = vm.get("user_reference_audio_path")
    u_text = vm.get("user_reference_text")
    # 用 bool() wrap 防 Python short-circuit 返 truthy string 而非 bool
    audio_paired = bool(
        isinstance(u_audio, str) and u_audio.strip()
        and isinstance(u_text, str) and u_text.strip()
    )

    d_audio = vm.get("reference_audio_path")
    d_text = vm.get("reference_text")
    d_temp = vm.get("fish_temperature")
    d_top_p = vm.get("fish_top_p")
    u_temp = vm.get("user_fish_temperature")
    u_top_p = vm.get("user_fish_top_p")

    return {
        "effective": {
            "reference_audio_path": u_audio if audio_paired else d_audio,
            "reference_text": u_text if audio_paired else d_text,
            "fish_temperature": u_temp if u_temp is not None else d_temp,
            "fish_top_p": u_top_p if u_top_p is not None else d_top_p,
        },
        "default": {
            "reference_audio_path": d_audio,
            "reference_text": d_text,
            "fish_temperature": d_temp,
            "fish_top_p": d_top_p,
        },
        "user_override": {
            "user_reference_audio_path": u_audio,
            "user_reference_text": u_text,
            "user_fish_temperature": u_temp,
            "user_fish_top_p": u_top_p,
        },
        "user_override_active": audio_paired,
    }


# ─────────────────────────────────────────────────────────────────────────
# POST /api/characters/{cid}/fish_config · upload + save user_override 全 4 字段
# ─────────────────────────────────────────────────────────────────────────


@router.post("/characters/{character_id}/fish_config")
async def upload_fish_config(
    character_id: int,
    file: Optional[UploadFile] = File(None),
    reference_text: str = Form(...),
    fish_temperature: float = Form(...),
    fish_top_p: float = Form(...),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """上传 reference audio + save 4 user_override 字段(POST = "保存"主流程)。

    per PM Q5 配对约束 + 字段一起 lock:
      - reference_text / fish_temperature / fish_top_p 必填(strict 4 一起 save)
      - file 可选 · 不传时若 user 已有 audio → 沿用 user_reference_audio_path
                  · 不传 + 无现 user audio → 400(首次配置必须上传 audio)
      - 写完后 user_reference_audio_path + user_reference_text 必同时存在
        (配对约束自动满足 · 因 text 必填)

    流程:
      1. character 存在 → 404
      2. file 提供时:415/413 validation + UUID 落 backend/static/fish_references/
      3. file 未提供 + 无现 user audio → 400
      4. JSON merge user_* 4 字段 → UPDATE voice_model
      5. 返 effective + user_override snapshot
    """
    vm_exists, vm = await _load_character_voice_model(session, character_id)
    if not vm_exists:
        raise HTTPException(status_code=404, detail="character not found")

    # ── file handling ─────────────────────────────────────────────────
    new_audio_rel_path: Optional[str] = None
    if file is not None and file.filename:
        ext = _resolve_ext(file.content_type, file.filename)
        data = bytearray()
        while True:
            chunk = await file.read(64 * 1024)
            if not chunk:
                break
            data.extend(chunk)
            if len(data) > _MAX_SIZE:
                raise HTTPException(
                    status_code=413,
                    detail=f"audio exceeds {_MAX_SIZE // (1024 * 1024)}MB limit",
                )
        char_dir = _FISH_REF_DIR / str(character_id)
        char_dir.mkdir(parents=True, exist_ok=True)
        target_filename = f"{uuid.uuid4().hex}{ext}"
        target_path = char_dir / target_filename
        try:
            target_path.write_bytes(bytes(data))
        except OSError as exc:
            logger.error("[fish_config] write failed: %s", exc)
            raise HTTPException(
                status_code=500, detail="failed to save file",
            ) from exc
        # 相对 backend/static/fish_references/ 的路径 = '<cid>/<uuid>.<ext>'
        new_audio_rel_path = f"{character_id}/{target_filename}"

    # 沿用现 user_reference_audio_path(if file 未提供 + 之前已上传过)
    effective_user_audio_path = new_audio_rel_path or vm.get(
        "user_reference_audio_path",
    )
    if not effective_user_audio_path:
        raise HTTPException(
            status_code=400,
            detail=("first-time fish_config setup requires audio file; "
                    "subsequent param-only updates may omit file"),
        )

    # ── voice_model JSON merge update(L1 user_override 全 4 字段)──────
    # 注:fish_config audio_path 用相对 fish_references mount 路径(`<cid>/<uuid>.<ext>`),
    # 跟 L2 reference_audio_path(相对 repo root)分开 mount;FishTTS 读时
    # _resolve_reference_path 兼容两种 path(后续 fish.py 改造前先用 absolute path)
    vm["user_reference_audio_path"] = _FISH_REF_DIR.relative_to(
        Path(__file__).resolve().parent.parent.parent,
    ).as_posix() + "/" + effective_user_audio_path
    vm["user_reference_text"] = reference_text.strip()
    vm["user_fish_temperature"] = float(fish_temperature)
    vm["user_fish_top_p"] = float(fish_top_p)
    await _save_character_voice_model(session, character_id, vm)

    logger.info(
        "[fish_config] saved cid=%s user_audio=%s temp=%s top_p=%s",
        character_id, vm["user_reference_audio_path"],
        vm["user_fish_temperature"], vm["user_fish_top_p"],
    )

    result = _build_effective_voice_config(vm)
    return {"character_id": character_id, **result}


# ─────────────────────────────────────────────────────────────────────────
# GET /api/characters/{cid}/fish_config · 当前 effective + user_* 原值
# ─────────────────────────────────────────────────────────────────────────


@router.get("/characters/{character_id}/fish_config")
async def get_fish_config(
    character_id: int,
    session: AsyncSession = Depends(get_session),
) -> dict:
    vm_exists, vm = await _load_character_voice_model(session, character_id)
    if not vm_exists:
        raise HTTPException(status_code=404, detail="character not found")
    result = _build_effective_voice_config(vm)
    # 补 audio_url(if user_override_active)给前端 preview
    eff_audio = result["effective"]["reference_audio_path"]
    audio_url = None
    if vm.get("user_reference_audio_path"):
        # user_reference_audio_path 已含 fish_references mount prefix · 抽 mount 之后部分
        u_path = vm["user_reference_audio_path"]
        mount_prefix = _FISH_REF_DIR.relative_to(
            Path(__file__).resolve().parent.parent.parent,
        ).as_posix() + "/"
        if u_path.startswith(mount_prefix):
            audio_url = "/static/fish_references/" + u_path[len(mount_prefix):]
    return {
        "character_id": character_id,
        **result,
        "audio_url": audio_url,
    }


# ─────────────────────────────────────────────────────────────────────────
# POST /api/characters/{cid}/fish_config/synthesize · 试听(binary audio)
# ─────────────────────────────────────────────────────────────────────────


@router.post("/characters/{character_id}/fish_config/synthesize")
async def synthesize_fish_preview(
    character_id: int,
    payload: dict,
    session: AsyncSession = Depends(get_session),
) -> Response:
    """试听 · body {"text": str} → audio binary(Content-Type: audio/wav)。

    用当前 character voice_model JSON(含 user_override merge)调 FishTTS 合成
    一次 · 返 binary。Frontend `new Audio(URL.createObjectURL(blob))` 直接播。
    """
    text_input = (payload or {}).get("text", "")
    if not isinstance(text_input, str) or not text_input.strip():
        raise HTTPException(status_code=400, detail="text required")

    # Load voice_model + 走 get_tts_engine 工厂(FishTTS 自动 merge L1>L2)
    row = (await session.execute(text(
        "SELECT voice_model FROM characters WHERE id = :cid"
    ), {"cid": character_id})).first()
    if row is None:
        raise HTTPException(status_code=404, detail="character not found")
    voice_model_str = row[0]
    if not voice_model_str or not voice_model_str.strip():
        raise HTTPException(
            status_code=400,
            detail="character has no voice_model configured",
        )

    # 构 FishTTS engine + synth · 走 get_tts_engine 让 _PreprocessingEngine
    # 包装确保 sanitize chain + per-provider strip 一致(per INV-9 §6)
    try:
        from backend.tts import get_tts_engine
        engine = get_tts_engine(voice_model_str)
        # check provider · 非 fish 不支持此 preview endpoint
        # (_PreprocessingEngine._provider 露出 lowercase string)
        if getattr(engine, "_provider", "").lower() != "fish":
            raise HTTPException(
                status_code=400,
                detail=("character not configured with fish provider; "
                        "preview only available for fish"),
            )
        # 设 TTS log context · source 'preview' 区分 chat / proactive
        from backend.observability.tts_log import set_tts_call_context
        set_tts_call_context(
            source="preview", character_id=character_id, user_id=None,
        )
        audio = await engine.synthesize(text_input, emotion="默认")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("[fish_config] preview synth failed cid=%s", character_id)
        raise HTTPException(status_code=500, detail=f"synth failed: {exc}") from exc

    if not audio:
        raise HTTPException(
            status_code=500, detail="synth returned no audio (check logs)",
        )

    return Response(content=audio, media_type="audio/wav")


# ─────────────────────────────────────────────────────────────────────────
# DELETE /api/characters/{cid}/fish_config · 清 4 user_* 字段
# ─────────────────────────────────────────────────────────────────────────


@router.delete("/characters/{character_id}/fish_config")
async def delete_fish_config(
    character_id: int,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """清 4 user_override 字段(L1 全 null)→ effective fallback L2 default。

    audio file 也 unlink(若存在 + 在 fish_references mount 下);unlink 失败
    warning 不抛(per voice_lines DELETE 范式)。
    """
    vm_exists, vm = await _load_character_voice_model(session, character_id)
    if not vm_exists:
        raise HTTPException(status_code=404, detail="character not found")

    # unlink audio file(if user_reference_audio_path 已 set)
    u_audio = vm.get("user_reference_audio_path")
    if isinstance(u_audio, str) and u_audio.strip():
        # u_audio 形如 "backend/static/fish_references/<cid>/<uuid>.<ext>"
        # 解析回 absolute path 删
        try:
            repo_root = Path(__file__).resolve().parent.parent.parent
            full_path = repo_root / u_audio
            if full_path.exists() and _FISH_REF_DIR in full_path.parents:
                full_path.unlink()
                logger.info("[fish_config] unlink %s", full_path)
        except OSError as exc:
            logger.warning("[fish_config] unlink failed: %s", exc)

    # 清 4 user_* 字段
    cleared = []
    for k in _USER_OVERRIDE_KEYS:
        if k in vm:
            del vm[k]
            cleared.append(k)
    await _save_character_voice_model(session, character_id, vm)

    logger.info("[fish_config] cleared cid=%s keys=%s", character_id, cleared)
    return {
        "character_id": character_id,
        "cleared_keys": cleared,
        **_build_effective_voice_config(vm),
    }
