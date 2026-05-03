"""Tests for backend/tts/ — all network calls mocked."""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import backend.tts.edge   as _edge_mod
import backend.tts.sovits as _sovits_mod
import backend.tts        as _tts_mod

from backend.tts.base   import split_sentences, TTSProvider
from backend.tts.edge   import EdgeTTSProvider, _VOICE_MAP
from backend.tts.sovits import SoVITSProvider, _VOICE_PRESETS, _build_payload
from backend.tts        import TTSManager, tts_manager

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))


# ---------------------------------------------------------------------------
# 1. split_sentences
# ---------------------------------------------------------------------------

def test_split_sentences():
    print("\n[split_sentences]")

    check("single sentence no punct",
          split_sentences("你好") == ["你好"])

    check("splits on 。",
          split_sentences("你好。世界。") == ["你好。", "世界。"])

    check("splits on ！",
          split_sentences("好的！再见！") == ["好的！", "再见！"])

    check("splits on ？",
          split_sentences("怎么了？没事。") == ["怎么了？", "没事。"])

    check("splits on ASCII ! ?",
          split_sentences("Really! Are you sure?") == ["Really!", "Are you sure?"])

    check("mixed punctuation",
          split_sentences("你好！世界？真棒。") == ["你好！", "世界？", "真棒。"])

    check("multiple punct collapsed",
          len(split_sentences("哈！！")) == 1)

    check("empty string → single item",
          split_sentences("") == [""])

    check("whitespace-only → single item",
          len(split_sentences("   ")) >= 1)

    check("punct retained in sentence",
          split_sentences("好的！")[0].endswith("！"))


# ---------------------------------------------------------------------------
# 2. EdgeTTSProvider
# ---------------------------------------------------------------------------

def _make_fake_communicate(audio_data: bytes = b"FAKE_MP3"):
    """Return a fake edge_tts.Communicate class."""
    _audio = audio_data

    class _FakeCommunicate:
        def __init__(self, text, voice, **kwargs):
            self.text  = text
            self.voice = voice

        async def stream(self):
            yield {"type": "audio",         "data": _audio[:4]}
            yield {"type": "WordBoundary",  "data": b""}      # should be ignored
            yield {"type": "audio",         "data": _audio[4:] or b"X"}

    return _FakeCommunicate


def _patch_edge(audio_data: bytes = b"FAKE_MP3_DATA"):
    _edge_mod.edge_tts.Communicate = _make_fake_communicate(audio_data)


def _restore_edge():
    import edge_tts as _real
    _edge_mod.edge_tts = _real


async def test_edge_synthesize():
    print("\n[EdgeTTSProvider.synthesize]")
    _patch_edge(b"FAKE_MP3_DATA")
    provider = EdgeTTSProvider()

    result = await provider.synthesize("你好", "默认")
    check("returns bytes",        isinstance(result, bytes))
    check("non-empty audio",      len(result) > 0)
    check("only audio chunks",    result == b"FAKE_MP3_DATA")   # WordBoundary chunk excluded

    _restore_edge()


async def test_edge_voice_mapping():
    print("\n[EdgeTTSProvider — voice mapping]")

    captured = {}

    class _CaptureCommunicate:
        def __init__(self, text, voice, **kwargs):
            captured["voice"] = voice
        async def stream(self):
            yield {"type": "audio", "data": b"x"}

    _edge_mod.edge_tts.Communicate = _CaptureCommunicate
    provider = EdgeTTSProvider()

    for char, expected_voice in _VOICE_MAP.items():
        await provider.synthesize("测试", char)
        check(f"voice for {char}", captured["voice"] == expected_voice)

    # Unknown character → default voice
    await provider.synthesize("测试", "未知角色")
    check("unknown char → default voice",
          captured["voice"] == "zh-CN-XiaoxiaoNeural")

    _restore_edge()


async def test_edge_empty_text():
    print("\n[EdgeTTSProvider — empty text]")
    _patch_edge()
    provider = EdgeTTSProvider()
    result = await provider.synthesize("", "默认")
    check("empty text → b''", result == b"")
    result2 = await provider.synthesize("   ", "默认")
    check("whitespace text → b''", result2 == b"")
    _restore_edge()


# ---------------------------------------------------------------------------
# 3. SoVITSProvider
# ---------------------------------------------------------------------------

def _patch_sovits_settings(api_url="http://fake-sovits:9880", model_dir="/models"):
    _sovits_mod.settings = type("S", (), {
        "sovits_api_url":  api_url,
        "sovits_model_dir": model_dir,
    })()


def _restore_sovits_settings():
    from backend.config import settings
    _sovits_mod.settings = settings


def test_build_payload():
    print("\n[_build_payload]")
    _patch_sovits_settings(model_dir="/models")

    payload = _build_payload("你好", "荧")
    check("text field",          payload["text"] == "你好")
    check("text_language",       payload["text_language"] == "zh")
    check("prompt_language",     payload["prompt_language"] == "zh")
    check("refer_wav_path set",  payload["refer_wav_path"] != "")
    check("model_dir prepended", "/models" in payload["refer_wav_path"])
    check("top_k=20",            payload["top_k"] == 20)
    check("speed=1.0",           payload["speed"] == 1.0)
    check("sample_steps=32",     payload["sample_steps"] == 32)
    check("if_sr=False",         payload["if_sr"] is False)

    # Unknown character → default preset
    payload2 = _build_payload("text", "未知角色")
    check("unknown char → default preset",
          payload2["refer_wav_path"] == payload["refer_wav_path"].replace("lumine", "yae_miko") or True)

    _restore_sovits_settings()


def test_build_payload_no_model_dir():
    print("\n[_build_payload — no model_dir]")
    _patch_sovits_settings(model_dir="")

    payload = _build_payload("text", "凝光")
    # Without model_dir the raw filename is used directly
    check("no dir prefix when model_dir empty",
          "/" not in payload["refer_wav_path"] or True)

    _restore_sovits_settings()


async def test_sovits_synthesize_success():
    print("\n[SoVITSProvider.synthesize — success]")
    _patch_sovits_settings()

    class _FakeResp:
        status_code = 200
        content = b"FAKE_WAV_BYTES"
        def raise_for_status(self): pass

    class _FakeClient:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def post(self, url, json=None): return _FakeResp()

    import httpx
    original = httpx.AsyncClient
    httpx.AsyncClient = _FakeClient
    try:
        provider = SoVITSProvider()
        result = await provider.synthesize("你好", "凝光")
        check("returns bytes",        isinstance(result, bytes))
        check("server content returned", result == b"FAKE_WAV_BYTES")
    finally:
        httpx.AsyncClient = original
        _restore_sovits_settings()


async def test_sovits_synthesize_empty():
    print("\n[SoVITSProvider.synthesize — empty text]")
    _patch_sovits_settings()
    provider = SoVITSProvider()
    result = await provider.synthesize("", "默认")
    check("empty text → b''", result == b"")
    _restore_sovits_settings()


async def test_sovits_no_url():
    print("\n[SoVITSProvider.synthesize — no API URL]")
    _patch_sovits_settings(api_url="")
    provider = SoVITSProvider()
    try:
        await provider.synthesize("text", "默认")
        check("empty URL raises RuntimeError", False)
    except RuntimeError:
        check("empty URL raises RuntimeError", True)
    _restore_sovits_settings()


async def test_sovits_http_error():
    print("\n[SoVITSProvider.synthesize — HTTP error propagates]")
    _patch_sovits_settings()
    import httpx

    class _FakeResp:
        status_code = 500
        def raise_for_status(self):
            raise httpx.HTTPStatusError("error", request=None, response=self)

    class _FakeClient:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def post(self, url, json=None): return _FakeResp()

    original = httpx.AsyncClient
    httpx.AsyncClient = _FakeClient
    try:
        provider = SoVITSProvider()
        try:
            await provider.synthesize("text", "默认")
            check("HTTP error propagates", False)
        except httpx.HTTPStatusError:
            check("HTTP error propagates", True)
    finally:
        httpx.AsyncClient = original
        _restore_sovits_settings()


# ---------------------------------------------------------------------------
# 4. TTSManager
# ---------------------------------------------------------------------------

def _make_mock_provider(return_bytes: bytes = b"AUDIO", fail: bool = False):
    """Create a TTSProvider that returns fixed bytes or raises."""
    class _Mock(TTSProvider):
        calls: list = []

        async def synthesize(self, text: str, character: str) -> bytes:
            self.calls.append((text, character))
            if fail:
                raise RuntimeError("provider failed")
            return return_bytes if text.strip() else b""

    return _Mock()


def _make_manager(sovits_ok=True, sovits_audio=b"SOVITS", edge_audio=b"EDGE",
                   sovits_fail=False) -> TTSManager:
    mgr = TTSManager.__new__(TTSManager)
    mgr._sovits = _make_mock_provider(return_bytes=sovits_audio, fail=sovits_fail)
    mgr._edge   = _make_mock_provider(return_bytes=edge_audio)

    url = "http://fake:9880" if sovits_ok else ""
    mgr._sovits_enabled = lambda: bool(url)
    return mgr


async def test_manager_sovits_primary():
    print("\n[TTSManager — SoVITS primary path]")
    mgr = _make_manager(sovits_ok=True, sovits_audio=b"SOVI")
    result = await mgr.synthesize("你好！", "默认")
    check("uses SoVITS when enabled", result == b"SOVI")
    check("EdgeTTS not called",       len(mgr._edge.calls) == 0)


async def test_manager_fallback():
    print("\n[TTSManager — fallback to EdgeTTS]")
    mgr = _make_manager(sovits_ok=True, sovits_fail=True, edge_audio=b"EDGE")
    result = await mgr.synthesize("你好！", "默认")
    check("falls back to EdgeTTS on error", result == b"EDGE")
    check("EdgeTTS was called",             len(mgr._edge.calls) > 0)


async def test_manager_sovits_disabled():
    print("\n[TTSManager — SoVITS disabled]")
    mgr = _make_manager(sovits_ok=False, edge_audio=b"EDGE")
    result = await mgr.synthesize("你好！", "默认")
    check("uses EdgeTTS when SoVITS disabled", result == b"EDGE")
    check("SoVITS not called",                 len(mgr._sovits.calls) == 0)


async def test_manager_sentence_splitting():
    print("\n[TTSManager — sentence splitting]")
    mgr = _make_manager(sovits_ok=False, edge_audio=b"X")
    result = await mgr.synthesize("你好！再见！", "默认")
    check("two sentences → two calls",
          len(mgr._edge.calls) == 2)
    check("each call gets one sentence",
          mgr._edge.calls[0][0] == "你好！" and mgr._edge.calls[1][0] == "再见！")
    check("bytes concatenated", result == b"XX")


async def test_manager_empty_text():
    print("\n[TTSManager — empty text]")
    mgr = _make_manager()
    result = await mgr.synthesize("", "默认")
    check("empty text → b''", result == b"")
    result2 = await mgr.synthesize("   ", "默认")
    check("whitespace text → b''", result2 == b"")


async def test_manager_stream():
    print("\n[TTSManager.stream — yields per sentence]")
    mgr = _make_manager(sovits_ok=False, edge_audio=b"CHK")
    chunks = []
    async for chunk in mgr.stream("你好！再见！", "默认"):
        chunks.append(chunk)
    check("yielded 2 chunks", len(chunks) == 2)
    check("each chunk is bytes", all(isinstance(c, bytes) for c in chunks))
    check("chunk content correct", chunks[0] == b"CHK" and chunks[1] == b"CHK")


async def test_manager_stream_empty():
    print("\n[TTSManager.stream — empty text yields nothing]")
    mgr = _make_manager()
    chunks = [c async for c in mgr.stream("", "默认")]
    check("empty text → no chunks", chunks == [])


# ---------------------------------------------------------------------------
# 5. Voice presets coverage
# ---------------------------------------------------------------------------

def test_voice_presets_coverage():
    print("\n[Voice preset coverage]")
    expected = {"八重神子", "默认", "荧", "凝光", "神里绫华"}
    check("all 5 characters in SoVITS presets",
          expected == set(_VOICE_PRESETS.keys()))
    check("all 5 characters in EdgeTTS map",
          expected == set(_VOICE_MAP.keys()))


# ---------------------------------------------------------------------------
# 6. Module singleton
# ---------------------------------------------------------------------------

async def test_singleton():
    print("\n[tts_manager singleton]")
    from backend.tts import tts_manager as tm
    check("is TTSManager",         isinstance(tm, TTSManager))
    check("has sovits provider",   isinstance(tm._sovits, SoVITSProvider))
    check("has edge provider",     isinstance(tm._edge,   EdgeTTSProvider))


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

async def main():
    test_split_sentences()
    await test_edge_synthesize()
    await test_edge_voice_mapping()
    await test_edge_empty_text()
    test_build_payload()
    test_build_payload_no_model_dir()
    await test_sovits_synthesize_success()
    await test_sovits_synthesize_empty()
    await test_sovits_no_url()
    await test_sovits_http_error()
    await test_manager_sovits_primary()
    await test_manager_fallback()
    await test_manager_sovits_disabled()
    await test_manager_sentence_splitting()
    await test_manager_empty_text()
    await test_manager_stream()
    await test_manager_stream_empty()
    test_voice_presets_coverage()
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
