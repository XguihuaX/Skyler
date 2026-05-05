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
    ssml: bool
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
        ssml=bool(raw.get("ssml", False)),
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
