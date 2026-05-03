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

from backend.config import settings

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="whisper")


def _compute_type(device: str) -> str:
    """Choose a compute type suited to the target device."""
    return "float16" if device == "cuda" else "int8"


class WhisperASR:

    def __init__(self) -> None:
        self._model: Optional[WhisperModel] = None
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
        """Initialise the WhisperModel if not already loaded (thread-safe)."""
        if self._model is not None:
            return
        async with self._get_lock():
            if self._model is not None:   # re-check after acquiring lock
                return
            model_size = settings.whisper_model
            device     = settings.whisper_device
            compute    = _compute_type(device)
            logger.info(
                "Loading WhisperModel '%s' on %s (compute_type=%s)",
                model_size, device, compute,
            )
            loop = asyncio.get_event_loop()
            self._model = await loop.run_in_executor(
                _executor,
                lambda: WhisperModel(model_size, device=device, compute_type=compute),
            )
            logger.info("WhisperModel ready")

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
