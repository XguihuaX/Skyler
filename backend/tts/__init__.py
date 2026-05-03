"""TTS package.

两条调用路径并存：

* ``tts_manager`` —— 旧入口，按角色名 (str) 路由 SoVITS→Edge，被 ws.py 在
  v3-D 之前的版本使用。保留代码以备回滚。

* ``get_tts_engine(voice_model)`` —— v3-D 新入口，按 character.voice_model
  JSON 选择 provider；返回符合 ``TTSBase`` 的实例（``synthesize(text,
  emotion)``）。当前 ws.py 的主路径走这个工厂。

Usage::

    from backend.tts import get_tts_engine
    engine = get_tts_engine(character.voice_model)  # voice_model 可空
    audio = await engine.synthesize(sentence, emotion="开心")
"""
import logging
from typing import AsyncGenerator, Optional

from backend.config import get_default_voice_config, settings
from backend.tts.base import TTSBase, TTSProvider, split_sentences
from backend.tts.edge import EdgeTTSProvider
from backend.tts.sovits import SoVITSProvider
from backend.tts.voice_config import VoiceConfig, parse_voice_config

logger = logging.getLogger(__name__)


class TTSManager:
    """Orchestrates SoVITS → EdgeTTS fallback and sentence-level synthesis."""

    def __init__(self) -> None:
        self._sovits = SoVITSProvider()
        self._edge   = EdgeTTSProvider()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _sovits_enabled(self) -> bool:
        """Return True when a SoVITS API URL is configured."""
        return bool(settings.sovits_api_url.strip())

    async def _synthesize_one(self, sentence: str, character: str) -> bytes:
        """Try SoVITS; fall back to EdgeTTS on any error."""
        if self._sovits_enabled():
            try:
                return await self._sovits.synthesize(sentence, character)
            except Exception as exc:
                logger.warning(
                    "SoVITS failed (%s), falling back to EdgeTTS for: %r",
                    exc, sentence,
                )
        return await self._edge.synthesize(sentence, character)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def synthesize(self, text: str, character: str) -> bytes:
        """Split *text* into sentences, synthesise each, return concatenated audio.

        Args:
            text:      Full utterance to synthesise.
            character: Active character name (controls voice selection).

        Returns:
            Concatenated audio bytes (WAV/MP3 depending on active backend).
            Returns b"" for empty or whitespace-only input.
        """
        if not text.strip():
            return b""
        sentences = split_sentences(text)
        chunks = []
        for sentence in sentences:
            chunk = await self._synthesize_one(sentence, character)
            if chunk:
                chunks.append(chunk)
        return b"".join(chunks)

    async def stream(
        self, text: str, character: str
    ) -> AsyncGenerator[bytes, None]:
        """Yield one audio chunk per sentence as soon as it is synthesised.

        Allows the caller to begin playback before the full text is processed.

        Args:
            text:      Full utterance.
            character: Active character name.

        Yields:
            Non-empty bytes objects, one per sentence.
        """
        if not text.strip():
            return
        sentences = split_sentences(text)
        for sentence in sentences:
            chunk = await self._synthesize_one(sentence, character)
            if chunk:
                yield chunk


# Module-level singleton used throughout the application.
tts_manager = TTSManager()


# ---------------------------------------------------------------------------
# v3-D：基于 character.voice_model 的工厂
# ---------------------------------------------------------------------------


class _LegacyProviderAdapter(TTSBase):
    """把旧 ``TTSProvider`` (signature: text, character) 适配成 ``TTSBase``。

    新接口签名是 (text, emotion)，旧 provider 没有 emotion 概念 —— 直接忽略，
    用 ``character`` 字段保存原 voice ID/路径，让旧代码继续按字符串路由。
    旧 provider 抛异常时返回 None，复用新接口的"静默降级"语义。
    """

    def __init__(self, inner: TTSProvider, character: str) -> None:
        self._inner = inner
        self._character = character

    async def synthesize(
        self, text: str, emotion: str = "默认",
    ) -> Optional[bytes]:
        if not text or not text.strip():
            return None
        try:
            audio = await self._inner.synthesize(text, self._character)
            return audio or None
        except Exception as exc:
            logger.warning(
                "Legacy TTS provider failed (%s) for character=%s: %s",
                type(self._inner).__name__, self._character, exc,
            )
            return None


def get_tts_engine(voice_model: Optional[str] = None) -> TTSBase:
    """根据 character.voice_model JSON 返回对应 TTS 引擎。

    Args:
        voice_model: characters.voice_model 字段。None / 空串 / 非法 JSON
                     时退化到 config.yaml 全局默认。

    Returns:
        实现 ``TTSBase`` 的实例；调用方只需 ``await engine.synthesize(text,
        emotion=...)``，永远不会抛 (失败返回 None)。
    """
    default = VoiceConfig(**get_default_voice_config())
    cfg = parse_voice_config(voice_model, default)

    if cfg.provider == "cosyvoice":
        # 延迟导入：dashscope 体积大且只在用到时才需要加载
        from backend.tts.cosyvoice import CosyVoiceTTS
        return CosyVoiceTTS(
            voice=cfg.voice,
            instruct_supported=cfg.instruct_supported,
        )
    if cfg.provider == "edge":
        return _LegacyProviderAdapter(EdgeTTSProvider(), character=cfg.voice)
    if cfg.provider == "sovits":
        # cfg.voice 此时是 model_path，原 SoVITSProvider 仍按 character 名路由 voice
        # 预设字典；保持现状，等真正接入再细化
        return _LegacyProviderAdapter(SoVITSProvider(), character=cfg.voice)

    # 未知 provider — 兜底回 CosyVoice 全局默认
    logger.warning("未知 TTS provider %r，回退 CosyVoice 默认", cfg.provider)
    from backend.tts.cosyvoice import CosyVoiceTTS
    return CosyVoiceTTS(
        voice=default.voice,
        instruct_supported=default.instruct_supported,
    )
