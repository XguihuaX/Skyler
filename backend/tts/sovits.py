"""SoVITSProvider — synthesise speech via a local GPT-SoVITS HTTP server.

Each character maps to a voice preset that contains the reference audio path
and its transcript.  The reference WAV files are looked up relative to the
SOVITS_MODEL_DIR environment variable.

Falls back to EdgeTTSProvider automatically (handled by TTSManager) whenever
the HTTP server is unreachable or returns an error.
"""
import logging
import os
from typing import Dict, Any

import httpx

from backend.tts.base import TTSProvider
from backend.config import settings

logger = logging.getLogger(__name__)

_TIMEOUT = 30.0  # seconds — SoVITS inference can be slow

# Per-character voice presets.
# refer_wav_path is a filename relative to SOVITS_MODEL_DIR.
_VOICE_PRESETS: Dict[str, Dict[str, Any]] = {
    "八重神子": {
        "refer_wav_path": "yae_miko_ref.wav",
        "prompt_text":    "神社的生意，比想象中要复杂得多呢。",
    },
    "默认": {
        "refer_wav_path": "yae_miko_ref.wav",
        "prompt_text":    "神社的生意，比想象中要复杂得多呢。",
    },
    "荧": {
        "refer_wav_path": "lumine_ref.wav",
        "prompt_text":    "旅途还很长，我们一起走吧。",
    },
    "凝光": {
        "refer_wav_path": "ningguang_ref.wav",
        "prompt_text":    "璃月的繁荣，是每一位商人共同努力的结果。",
    },
    "神里绫华": {
        "refer_wav_path": "ayaka_ref.wav",
        "prompt_text":    "樱花的季节又到了，真是令人心旷神怡。",
    },
}
_DEFAULT_PRESET_KEY = "默认"


def _build_payload(text: str, character: str) -> Dict[str, Any]:
    preset    = _VOICE_PRESETS.get(character, _VOICE_PRESETS[_DEFAULT_PRESET_KEY])
    model_dir = settings.sovits_model_dir.strip()
    refer_path = (
        os.path.join(model_dir, preset["refer_wav_path"])
        if model_dir
        else preset["refer_wav_path"]
    )
    return {
        "refer_wav_path": refer_path,
        "prompt_text":    preset["prompt_text"],
        "prompt_language": "zh",
        "text":           text,
        "text_language":  "zh",
        "cut_punc":       "，。",
        "top_k":          20,
        "top_p":          0.7,
        "temperature":    0.8,
        "speed":          1.0,
        "sample_steps":   32,
        "if_sr":          False,
        "language":       "zh",
    }


class SoVITSProvider(TTSProvider):

    async def synthesize(self, text: str, character: str) -> bytes:
        """POST *text* to the GPT-SoVITS server and return raw audio bytes.

        Args:
            text:      Text to synthesise (a single sentence works best).
            character: Active character name used to select the voice preset.

        Returns:
            Raw WAV/MP3 bytes from the SoVITS server.

        Raises:
            httpx.TimeoutException:   server did not respond in time.
            httpx.HTTPStatusError:    server returned a non-2xx status.
            httpx.RequestError:       network-level error (connection refused, etc.).
        """
        if not text.strip():
            return b""

        api_url = settings.sovits_api_url.strip()
        if not api_url:
            raise RuntimeError("SOVITS_API_URL is not configured")

        payload = _build_payload(text, character)
        logger.debug(
            "SoVITS: POST %s character=%s len=%d", api_url, character, len(text)
        )

        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(api_url, json=payload)
            resp.raise_for_status()
            return resp.content
