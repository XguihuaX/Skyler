"""TTS 抽象接口 + 句子切分工具。

两套抽象并存：

* ``TTSProvider`` —— 旧接口 ``synthesize(text, character)``，仍服务于
  ``backend.tts.tts_manager`` 的 SoVITS→Edge 自动切换路径。

* ``TTSBase`` —— v3-D 引入的新接口 ``synthesize(text, emotion)``，由
  ``backend.tts.get_tts_engine`` 工厂返回的 CosyVoice 实例使用。
  适配器会把旧 Provider 也包装成 TTSBase 形态。
"""
import re
from abc import ABC, abstractmethod
from typing import List, Optional

# Splits after a sentence-ending punctuation mark, keeping the mark attached
# to its sentence so TTS models get proper prosody cues.
# "你好！世界？" → ["你好！", "世界？"]
_SENT_RE   = re.compile(r'(?<=[。！？!?])')
# Matches strings that contain nothing but punctuation and whitespace
# (produced by consecutive marks like "！！" → ["！！", ""])
_PUNCT_ONLY = re.compile(r'^[。！？!?\s]+$')


def split_sentences(text: str) -> List[str]:
    """Split *text* into sentences on 。！？!? boundaries.

    Each sentence retains its trailing punctuation.
    Returns the original text as a single-item list when no boundary is found.
    """
    parts = [p.strip() for p in _SENT_RE.split(text) if p.strip()]
    # Drop punctuation-only fragments produced by consecutive marks (e.g. "！！")
    parts = [p for p in parts if not _PUNCT_ONLY.match(p)]
    return parts if parts else [text.strip()]


class TTSProvider(ABC):
    @abstractmethod
    async def synthesize(self, text: str, character: str) -> bytes:
        """Synthesise *text* for the given *character* and return audio bytes.

        Implementations should return WAV or MP3 bytes.
        Raises on unrecoverable errors; callers handle fallback.
        """
        ...


class TTSBase(ABC):
    """v3-D 新接口：以情感词驱动合成。

    返回 None 表示本句合成失败，调用方应静默跳过、不影响文字输出。
    实现方应自行 try/except 网络/SDK 异常。
    """

    @abstractmethod
    async def synthesize(
        self, text: str, emotion: str = "默认",
    ) -> Optional[bytes]:
        """合成 *text*，可选 *emotion* (中文情感词，由实现方做映射)。"""
        ...
