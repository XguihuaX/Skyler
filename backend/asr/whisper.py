"""WhisperASR: lazy-loading faster-whisper wrapper with async interface.

The WhisperModel is initialised once on the first transcription call.
All CPU-bound work runs in a dedicated single-threaded executor so the
asyncio event loop stays unblocked.

Configuration (read from .env via Settings)
-------------------------------------------
WHISPER_MODEL   — model size: "tiny" | "base" | "small" | "medium" | "large-v3"
                  Default: "small"
WHISPER_DEVICE  — "cpu" | "cuda" | "auto"
                  Default: "cpu"
"""
import asyncio
import base64
import io
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from faster_whisper import WhisperModel

from backend.config import get_whisper_model_size, settings

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="whisper")


def _compute_type(device: str) -> str:
    """Choose a compute type suited to the target device."""
    return "float16" if device == "cuda" else "int8"


class WhisperASR:

    def __init__(self) -> None:
        self._model: Optional[WhisperModel] = None
        self._loaded_size: Optional[str] = None  # bugfix-3.3: 记录已加载 size
        self._lock: Optional[asyncio.Lock] = None

    def _get_lock(self) -> asyncio.Lock:
        """Return the per-instance lock, creating it bound to the running loop."""
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    # ------------------------------------------------------------------
    # Model lifecycle
    # ------------------------------------------------------------------

    async def load_model(self) -> None:
        """Initialise the WhisperModel if not already loaded (thread-safe)。

        bugfix-3.3: model_size 走 ``get_whisper_model_size()`` 读 yaml override
        (UI 写回 ``asr.whisper_model_size``)。若 yaml 改了 size 跟当前已加载的
        不同 → 触发 reload (旧 model 引用置 None 让 GC 回收)。
        """
        desired_size = get_whisper_model_size()
        if self._model is not None and self._loaded_size == desired_size:
            return
        async with self._get_lock():
            # re-check after acquiring lock — 跟 desired_size 比对决定是否 reload
            if self._model is not None and self._loaded_size == desired_size:
                return
            device     = settings.whisper_device
            compute    = _compute_type(device)
            action = "Reloading" if self._model is not None else "Loading"
            logger.info(
                "%s WhisperModel '%s' on %s (compute_type=%s)",
                action, desired_size, device, compute,
            )
            # drop old model ref so faster-whisper / GPU mem can be freed by GC
            self._model = None
            loop = asyncio.get_event_loop()
            self._model = await loop.run_in_executor(
                _executor,
                lambda: WhisperModel(desired_size, device=device, compute_type=compute),
            )
            self._loaded_size = desired_size
            logger.info("WhisperModel '%s' ready", desired_size)

    async def reload_if_size_changed(self) -> bool:
        """Bugfix-3.3: 暴露给 API endpoint 用 — yaml 改 size 后调用,
        若 desired != loaded → load_model 触发 reload。返回是否真的 reload。"""
        desired = get_whisper_model_size()
        if self._model is not None and self._loaded_size == desired:
            return False
        await self.load_model()
        return True

    # ------------------------------------------------------------------
    # Transcription
    # ------------------------------------------------------------------

    async def transcribe(
        self,
        audio_bytes: bytes,
        language: Optional[str] = None,
    ) -> str:
        """Transcribe raw audio bytes and return the recognised text.

        Args:
            audio_bytes: Raw audio data in any format supported by ffmpeg
                         (WAV, MP3, WebM, OGG, …).
            language:    BCP-47 language code hint (e.g. "zh", "en").
                         Pass None to let Whisper auto-detect.

        Returns:
            Concatenated transcription text, stripped of leading/trailing
            whitespace.  Returns an empty string for silent input.
        """
        await self.load_model()

        audio_io = io.BytesIO(audio_bytes)
        model    = self._model

        def _run() -> str:
            segments, _ = model.transcribe(
                audio_io,
                language=language,
                beam_size=5,
                vad_filter=True,      # strip silence
            )
            return "".join(seg.text for seg in segments).strip()

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(_executor, _run)

    async def transcribe_b64(
        self,
        b64_audio: str,
        language: Optional[str] = None,
    ) -> str:
        """Decode a base-64 encoded audio string and transcribe it.

        Args:
            b64_audio: Standard base-64 encoded audio data (the raw bytes of
                       any ffmpeg-supported audio file).
            language:  Optional BCP-47 language hint.

        Raises:
            ValueError: if *b64_audio* is not valid base-64.

        Returns:
            Recognised text string.
        """
        try:
            audio_bytes = base64.b64decode(b64_audio, validate=True)
        except Exception as exc:
            raise ValueError(f"Invalid base64 audio data: {exc}") from exc
        return await self.transcribe(audio_bytes, language=language)


# Module-level singleton — shared across the application lifetime.
whisper_asr = WhisperASR()
