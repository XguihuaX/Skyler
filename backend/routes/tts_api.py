"""TTS REST API.

Mounted at /api in main.py.  Full URL map:
  GET  /api/tts/voices

v3-G' chunk 1 — 让 CharacterPanel 拿到一份"当前可用 TTS provider + 音色"
清单，替代之前 voice_model 字段裸 JSON 文本框。后端从 ``config.yaml``
``tts.available_voices`` 读，加新音色不动代码。
"""
from typing import List, Optional

from fastapi import APIRouter
from typing_extensions import TypedDict

from backend.config import get_available_voices

router = APIRouter()


# ---------------------------------------------------------------------------
# Response types — TypedDict + typing_extensions 是为对 pydantic schema 推断
# 友好（参见 services/live2d_scanner.py 同模式注释）。
# ---------------------------------------------------------------------------


class VoiceInfo(TypedDict):
    id: str
    label: str
    # v3-G' patch：emotion 控制现在走 instruct 自然语言指令，不走 SSML
    # （DashScope SSML 没有 emotion 属性）。``ssml`` 字段在 chunk 1a 误用
    # 后撤销；未来若启用 SSML rate/pitch/volume/effect/bgm 等真实属性，
    # 重新加回此字段并落实到 cosyvoice.py 调用路径。
    instruct: Optional[bool]
    traits: str


class TtsProvider(TypedDict):
    id: str
    label: str
    voices: List[VoiceInfo]


class TtsVoicesResponse(TypedDict):
    providers: List[TtsProvider]


# Provider id → 显示 label（前端两级下拉第一级显示用）
_PROVIDER_LABELS: dict[str, str] = {
    "cosyvoice": "CosyVoice",
    "edge": "Edge-TTS",
    "sovits": "GPT-SoVITS",
}


def _coerce_voice(raw: dict) -> VoiceInfo:
    """把 yaml 行规整成 VoiceInfo，缺字段用合理默认。"""
    raw_instruct = raw.get("instruct")
    if raw_instruct is None:
        instruct: Optional[bool] = None
    else:
        instruct = bool(raw_instruct)
    return VoiceInfo(
        id=str(raw.get("id", "")),
        label=str(raw.get("label", raw.get("id", ""))),
        instruct=instruct,
        traits=str(raw.get("traits", "")),
    )


@router.get("/tts/voices")
async def list_tts_voices() -> TtsVoicesResponse:
    """Return providers + voices currently available to CharacterPanel.

    Reads ``config.yaml`` ``tts.available_voices`` on every call (no cache)
    so editing the file + ``POST /api/config/reload`` reflects immediately
    without restart. Empty / malformed entries silently dropped.
    """
    raw = get_available_voices()
    providers: List[TtsProvider] = []
    for provider_id, voice_list in raw.items():
        if not isinstance(voice_list, list):
            continue
        voices: List[VoiceInfo] = []
        for entry in voice_list:
            if not isinstance(entry, dict):
                continue
            voice = _coerce_voice(entry)
            if not voice["id"]:
                continue
            voices.append(voice)
        if not voices:
            continue
        providers.append(TtsProvider(
            id=provider_id,
            label=_PROVIDER_LABELS.get(provider_id, provider_id),
            voices=voices,
        ))
    return TtsVoicesResponse(providers=providers)


# ---------------------------------------------------------------------------
# Bugfix-3.3.1 — Cloned (DashScope 控制台复刻) voice 管理 + 试听 + 用量反查
# ---------------------------------------------------------------------------

import asyncio
import base64
import json
import logging
import time as _time
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

from backend.database import engine

logger = logging.getLogger(__name__)


class ClonedVoice(BaseModel):
    voice_id: str
    create_time: Optional[str] = None
    update_time: Optional[str] = None
    status: Optional[str] = None


class ClonedVoicesResponse(BaseModel):
    voices: List[ClonedVoice]
    cached: bool = False  # True 表示走的内存缓存,未打 DashScope


class VoicePreviewBody(BaseModel):
    voice: str = Field(..., min_length=1)
    text: str = Field(default="你好,我是测试音色。", max_length=200)


class VoicePreviewResponse(BaseModel):
    audio_b64: str
    voice: str
    format: str = "wav-24khz-16bit-mono"


class VoiceUsageEntry(BaseModel):
    voice: str
    characters: List[dict]   # [{id, name}]


class VoiceUsageResponse(BaseModel):
    by_voice: List[VoiceUsageEntry]


# 5 分钟缓存复刻 voice 列表 — 避免每次 UI 刷新都打 DashScope HTTP
_CACHE_TTL_SECONDS = 300
_cached_voices: Optional[List[dict]] = None
_cached_at: float = 0.0


def _cache_fresh() -> bool:
    return (
        _cached_voices is not None
        and _time.monotonic() - _cached_at < _CACHE_TTL_SECONDS
    )


def _ensure_dashscope_key() -> None:
    """同步设置 DashScope 全局 api_key。无凭证 → 400 HTTPException。

    Note: SDK 是模块级 global state, 不好接 async DB resolve;走 .env / settings
    路径即可 (复刻 voice 是高级用户场景, DASHSCOPE_API_KEY 通常已配)。
    """
    import dashscope
    import os
    from backend.config import settings
    key = settings.dashscope_api_key or os.environ.get("DASHSCOPE_API_KEY", "")
    if not key:
        raise HTTPException(
            status_code=400,
            detail=(
                "DASHSCOPE_API_KEY 未配置 — 先在 AI Providers / Qwen vendor "
                "下配凭证, 或写 .env 文件"
            ),
        )
    dashscope.api_key = key


def _blocking_list_cloned_voices() -> List[dict]:
    """同步调 VoiceEnrollmentService.list_voices。page_size=100 覆盖正常用户。"""
    from dashscope.audio.tts_v2 import VoiceEnrollmentService
    _ensure_dashscope_key()
    svc = VoiceEnrollmentService()
    raw = svc.list_voices(page_index=0, page_size=100)
    if not isinstance(raw, list):
        logger.warning(
            "[tts.voices.cloned] DashScope returned non-list: %r", type(raw)
        )
        return []
    return raw


def _blocking_preview(voice: str, sample_text: str) -> bytes:
    """同步 CosyVoice 合成,返回 WAV bytes。"""
    from dashscope.audio.tts_v2 import AudioFormat, SpeechSynthesizer
    from backend.config import get_cosyvoice_config
    _ensure_dashscope_key()
    cfg = get_cosyvoice_config()
    model = cfg.get("model", "cosyvoice-v3-flash")
    synth = SpeechSynthesizer(
        model=model, voice=voice,
        format=AudioFormat.WAV_24000HZ_MONO_16BIT,
    )
    audio = synth.call(sample_text)
    if not audio:
        raise RuntimeError(f"voice={voice} 返回空音频 — voice_id 不存在或过期")
    return audio


def _normalize_voice_dict(d: dict) -> dict:
    """SDK 返回字段名 ('id'/'voice_id', 'gmtCreate'/'create_time') 归一化。"""
    if not isinstance(d, dict):
        return {"voice_id": str(d)}
    voice_id = d.get("voice_id") or d.get("id") or ""
    return {
        "voice_id": voice_id,
        "create_time": d.get("create_time") or d.get("gmtCreate"),
        "update_time": d.get("update_time") or d.get("gmtModified"),
        "status": d.get("status"),
    }


@router.get("/tts/voices/cloned", response_model=ClonedVoicesResponse)
async def list_cloned_voices(force: bool = False) -> Any:
    """拉用户在 DashScope 控制台复刻的所有 cosyvoice voice。

    Args:
        force: ``true`` 跳过缓存强拉。UI 的 [刷新] 按钮加 ``?force=1``。
    """
    global _cached_voices, _cached_at
    if not force and _cache_fresh() and _cached_voices is not None:
        return ClonedVoicesResponse(
            voices=[ClonedVoice(**_normalize_voice_dict(v))
                    for v in _cached_voices],
            cached=True,
        )
    try:
        raw = await asyncio.to_thread(_blocking_list_cloned_voices)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("[tts.voices.cloned] DashScope list_voices failed")
        raise HTTPException(
            status_code=502,
            detail=f"DashScope list_voices failed: {exc}",
        ) from exc
    _cached_voices = raw
    _cached_at = _time.monotonic()
    return ClonedVoicesResponse(
        voices=[ClonedVoice(**_normalize_voice_dict(v)) for v in raw],
        cached=False,
    )


@router.post("/tts/voice/preview", response_model=VoicePreviewResponse)
async def preview_voice(body: VoicePreviewBody) -> Any:
    """合成一段 ``body.text`` 试听 (默认 '你好,我是测试音色。')。返回 base64 wav。"""
    try:
        audio = await asyncio.to_thread(
            _blocking_preview, body.voice, body.text,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("[tts.voice.preview] failed voice=%s", body.voice)
        raise HTTPException(
            status_code=502,
            detail=f"voice preview failed: {exc}",
        ) from exc
    b64 = base64.b64encode(audio).decode("ascii")
    return VoicePreviewResponse(audio_b64=b64, voice=body.voice)


@router.get("/tts/voices/usage", response_model=VoiceUsageResponse)
async def voice_usage() -> Any:
    """反向 ``{voice_id: [character...]}``,前端 voice gallery 显示
    "已用于角色: 八重神子, 神里绫华"。读 characters.voice_model JSON 实时算。"""
    by_voice: dict[str, List[dict]] = {}
    async with engine.begin() as conn:
        rows = (await conn.execute(text(
            "SELECT id, name, voice_model FROM characters "
            "WHERE voice_model IS NOT NULL"
        ))).fetchall()
    for row in rows:
        cid, cname, vm_str = row[0], row[1], row[2]
        if not vm_str:
            continue
        try:
            vm = json.loads(vm_str)
        except json.JSONDecodeError:
            continue
        if not isinstance(vm, dict):
            continue
        voice = vm.get("voice")
        if not isinstance(voice, str) or not voice:
            continue
        by_voice.setdefault(voice, []).append({"id": cid, "name": cname})
    return VoiceUsageResponse(
        by_voice=[VoiceUsageEntry(voice=v, characters=chars)
                  for v, chars in sorted(by_voice.items())],
    )
