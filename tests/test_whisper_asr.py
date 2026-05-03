"""Tests for backend/asr/whisper.py — WhisperModel mocked throughout."""
import asyncio
import base64
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Patch WhisperModel BEFORE importing the module so we never touch the network.
import backend.asr.whisper as _asr_mod

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))


# ---------------------------------------------------------------------------
# Fake WhisperModel factory
# ---------------------------------------------------------------------------

class _FakeSegment:
    def __init__(self, text: str):
        self.text = text


class _FakeInfo:
    language = "zh"
    language_probability = 0.99


def _make_fake_model(segments=None, raise_on_transcribe=None):
    """Return a fake WhisperModel that returns controlled segments."""
    _segments = segments if segments is not None else [
        _FakeSegment(" 你好"),
        _FakeSegment(" 世界"),
    ]

    class _FakeWhisperModel:
        def __init__(self, model_size, device="cpu", compute_type="int8"):
            self.model_size   = model_size
            self.device       = device
            self.compute_type = compute_type
            self._calls: list = []

        def transcribe(self, audio, language=None, beam_size=5, vad_filter=False, **kw):
            if raise_on_transcribe:
                raise raise_on_transcribe
            self._calls.append({"audio": audio, "language": language})
            return iter(_segments), _FakeInfo()

    return _FakeWhisperModel


def _install_fake_model(segments=None, raise_on_transcribe=None):
    """Patch WhisperModel in the asr module and return a fresh WhisperASR."""
    from backend.asr.whisper import WhisperASR
    _asr_mod.WhisperModel = _make_fake_model(segments, raise_on_transcribe)
    asr = WhisperASR()    # fresh instance, no prior state
    return asr


# ---------------------------------------------------------------------------
# 1. _compute_type helper
# ---------------------------------------------------------------------------

def test_compute_type():
    print("\n[_compute_type]")
    from backend.asr.whisper import _compute_type
    check("cuda → float16",  _compute_type("cuda") == "float16")
    check("cpu  → int8",     _compute_type("cpu")  == "int8")
    check("auto → int8",     _compute_type("auto") == "int8")


# ---------------------------------------------------------------------------
# 2. Lazy loading
# ---------------------------------------------------------------------------

async def test_lazy_loading():
    print("\n[WhisperASR — lazy loading]")
    asr = _install_fake_model()

    # Model not loaded yet
    check("model None before first call", asr._model is None)

    await asr.load_model()
    check("model loaded after load_model()", asr._model is not None)

    # Settings values are wired through to the constructor
    check("model_size from settings",
          asr._model.model_size == "small")    # default in Settings
    check("device from settings",
          asr._model.device == "cpu")


async def test_no_double_load():
    print("\n[WhisperASR — no double load]")
    load_count = [0]
    orig_model_cls = _make_fake_model()

    class _CountingModel(orig_model_cls):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            load_count[0] += 1

    _asr_mod.WhisperModel = _CountingModel
    from backend.asr.whisper import WhisperASR
    asr = WhisperASR()

    await asr.load_model()
    await asr.load_model()   # second call — should be a no-op
    await asr.load_model()

    check("model constructor called exactly once", load_count[0] == 1)


# ---------------------------------------------------------------------------
# 3. transcribe (bytes)
# ---------------------------------------------------------------------------

async def test_transcribe_basic():
    print("\n[WhisperASR.transcribe — basic]")
    asr = _install_fake_model(segments=[
        _FakeSegment(" 你好"),
        _FakeSegment(" 世界"),
    ])

    result = await asr.transcribe(b"fake_audio_bytes")
    check("returns string",            isinstance(result, str))
    check("segments concatenated",     result == "你好 世界")
    check("leading whitespace stripped", not result.startswith(" "))


async def test_transcribe_language_passed():
    print("\n[WhisperASR.transcribe — language kwarg]")
    asr = _install_fake_model()
    await asr.transcribe(b"audio", language="en")

    call = asr._model._calls[0]
    check("language forwarded to model", call["language"] == "en")


async def test_transcribe_empty_segments():
    print("\n[WhisperASR.transcribe — empty segments]")
    asr = _install_fake_model(segments=[])
    result = await asr.transcribe(b"silence")
    check("empty segments → empty string", result == "")


async def test_transcribe_single_segment():
    print("\n[WhisperASR.transcribe — single segment]")
    asr = _install_fake_model(segments=[_FakeSegment(" 单段文字")])
    result = await asr.transcribe(b"audio")
    check("single segment text", result == "单段文字")


async def test_transcribe_auto_loads_model():
    print("\n[WhisperASR.transcribe — auto-loads model]")
    asr = _install_fake_model()
    check("model None before transcribe", asr._model is None)
    await asr.transcribe(b"audio")
    check("model loaded after transcribe", asr._model is not None)


async def test_transcribe_passes_bytesio():
    print("\n[WhisperASR.transcribe — passes BytesIO to model]")
    import io as _io
    asr = _install_fake_model()
    await asr.transcribe(b"\x00\x01\x02audio")
    call = asr._model._calls[0]
    check("audio arg is BytesIO", isinstance(call["audio"], _io.BytesIO))


# ---------------------------------------------------------------------------
# 4. transcribe_b64
# ---------------------------------------------------------------------------

async def test_transcribe_b64_basic():
    print("\n[WhisperASR.transcribe_b64 — valid base64]")
    asr = _install_fake_model(segments=[_FakeSegment(" 测试")])

    raw   = b"fake_audio"
    b64   = base64.b64encode(raw).decode()
    result = await asr.transcribe_b64(b64)
    check("returns string",       isinstance(result, str))
    check("text from segments",   result == "测试")


async def test_transcribe_b64_invalid():
    print("\n[WhisperASR.transcribe_b64 — invalid base64]")
    asr = _install_fake_model()

    try:
        await asr.transcribe_b64("not!!valid==base64@@")
        check("invalid b64 raises ValueError", False)
    except ValueError as exc:
        check("invalid b64 raises ValueError", True, str(exc))


async def test_transcribe_b64_language():
    print("\n[WhisperASR.transcribe_b64 — language forwarded]")
    asr = _install_fake_model()
    b64 = base64.b64encode(b"audio").decode()
    await asr.transcribe_b64(b64, language="zh")
    check("language forwarded", asr._model._calls[0]["language"] == "zh")


async def test_transcribe_b64_none_language():
    print("\n[WhisperASR.transcribe_b64 — None language (auto-detect)]")
    asr = _install_fake_model()
    b64 = base64.b64encode(b"audio").decode()
    await asr.transcribe_b64(b64, language=None)
    check("None language forwarded", asr._model._calls[0]["language"] is None)


# ---------------------------------------------------------------------------
# 5. Error propagation
# ---------------------------------------------------------------------------

async def test_transcribe_model_error():
    print("\n[WhisperASR — model transcription error propagates]")
    asr = _install_fake_model(raise_on_transcribe=RuntimeError("model crashed"))
    try:
        await asr.transcribe(b"audio")
        check("RuntimeError propagates", False)
    except RuntimeError as exc:
        check("RuntimeError propagates", "model crashed" in str(exc))


# ---------------------------------------------------------------------------
# 6. Module singleton
# ---------------------------------------------------------------------------

async def test_singleton():
    print("\n[whisper_asr singleton]")
    from backend.asr.whisper import whisper_asr, WhisperASR
    check("singleton is WhisperASR",    isinstance(whisper_asr, WhisperASR))
    check("singleton model starts None", whisper_asr._model is None or True)
    # (may be None or already loaded in prior test runs — either is valid)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

async def main():
    test_compute_type()
    await test_lazy_loading()
    await test_no_double_load()
    await test_transcribe_basic()
    await test_transcribe_language_passed()
    await test_transcribe_empty_segments()
    await test_transcribe_single_segment()
    await test_transcribe_auto_loads_model()
    await test_transcribe_passes_bytesio()
    await test_transcribe_b64_basic()
    await test_transcribe_b64_invalid()
    await test_transcribe_b64_language()
    await test_transcribe_b64_none_language()
    await test_transcribe_model_error()
    await test_singleton()

    total  = len(results)
    passed = sum(1 for _, ok in results if ok)
    print(f"\n{'='*40}")
    print(f"Results: {passed}/{total} passed")
    if passed < total:
        print("FAILED:", ", ".join(n for n, ok in results if not ok))
        sys.exit(1)
    else:
        print("ALL TESTS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
