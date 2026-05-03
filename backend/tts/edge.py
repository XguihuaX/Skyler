"""EdgeTTS provider — fallback TTS using Microsoft Edge neural voices.

No API key or local model required; requires an internet connection.
Output format is MP3.
"""
import logging
from typing import Dict

import edge_tts

from backend.tts.base import TTSProvider

logger = logging.getLogger(__name__)

# Character → Edge-TTS voice name
_VOICE_MAP: Dict[str, str] = {
    "八重神子": "zh-CN-XiaoxiaoNeural",
    "默认":     "zh-CN-XiaoxiaoNeural",
    "荧":       "zh-CN-XiaoyiNeural",
    "凝光":     "zh-CN-YunjianNeural",
    "神里绫华": "zh-CN-XiaochenNeural",
}
_DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"


class EdgeTTSProvider(TTSProvider):

    async def synthesize(self, text: str, character: str) -> bytes:
        """Stream-synthesise *text* with the voice mapped to *character*.

        Returns:
            MP3 audio bytes.  Returns b"" for empty input.

        Raises:
            edge_tts.exceptions.NoAudioReceived: if Edge TTS returns no audio.
            Exception: propagated on network / API errors.
        """
        if not text.strip():
            return b""

        voice = _VOICE_MAP.get(character, _DEFAULT_VOICE)
        logger.debug("EdgeTTS: voice=%s character=%s len=%d", voice, character, len(text))

        communicate = edge_tts.Communicate(text, voice)
        chunks = []
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                chunks.append(chunk["data"])

        return b"".join(chunks)
