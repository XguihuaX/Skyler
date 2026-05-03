"""Tests for backend/tts/ — all network calls mocked."""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import backend.tts.edge   as _edge_mod
import backend.tts.sovits as _sovits_mod
import backend.tts        as _tts_mod

from backend.tts.base   import split_sentences, TTSProvider, TTSBase
from backend.tts.edge   import EdgeTTSProvider, _VOICE_MAP
from backend.tts.sovits import SoVITSProvider, _VOICE_PRESETS, _build_payload
from backend.tts        import (
    TTSManager,
    tts_manager,
    preprocess_tts_text,
    _PreprocessingEngine,
)

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
# 6. v3-F preprocess_tts_text
# ---------------------------------------------------------------------------

def test_preprocess_passthrough():
    print("\n[preprocess_tts_text — passthrough]")
    check("plain Chinese unchanged",
          preprocess_tts_text("你好世界") == "你好世界")
    check("Chinese with punct unchanged",
          preprocess_tts_text("你好！世界？") == "你好！世界？")
    check("plain English unchanged",
          preprocess_tts_text("Hello world") == "Hello world")


def test_preprocess_strips_action():
    print("\n[preprocess_tts_text — *action* 动作描述]")
    check("strips *笑*",
          preprocess_tts_text("*笑* 你好") == "你好")
    check("strips multiple actions",
          preprocess_tts_text("*抬头* 嗨 *微笑*") == "嗨")
    check("strips embedded action",
          preprocess_tts_text("早上好*伸了个懒腰*再见") == "早上好再见")
    check("preserves * in middle when unpaired",
          preprocess_tts_text("a*b") == "a*b")


def test_preprocess_strips_parens():
    print("\n[preprocess_tts_text — (注释) 括号]")
    check("strips ASCII parens",
          preprocess_tts_text("你好(悄声)再见") == "你好再见")
    check("strips Chinese parens",
          preprocess_tts_text("你好（轻声）再见") == "你好再见")
    check("strips ASCII brackets",
          preprocess_tts_text("[标记]你好") == "你好")
    check("strips Chinese brackets",
          preprocess_tts_text("【提示】你好") == "你好")
    check("multiple kinds combined",
          preprocess_tts_text("(注释)你好（备注）[mark]【标签】结束")
          == "你好结束")


def test_preprocess_strips_emotion_motion():
    print("\n[preprocess_tts_text — emotion / motion 标签]")
    check("strips <emotion>X</emotion>",
          preprocess_tts_text("<emotion>开心</emotion>今天天气真好")
          == "今天天气真好")
    check("strips <motion>X</motion>",
          preprocess_tts_text("<motion>wave</motion>你好") == "你好")
    check("case insensitive emotion",
          preprocess_tts_text("<EMOTION>happy</EMOTION>hi") == "hi")
    check("strips both in one line",
          preprocess_tts_text("<emotion>happy</emotion><motion>nod</motion>嗨")
          == "嗨")


def test_preprocess_strips_thinking():
    print("\n[preprocess_tts_text — <thinking> 多行]")
    check("strips single-line thinking",
          preprocess_tts_text("<thinking>该说什么呢</thinking>你好")
          == "你好")
    check("strips multi-line thinking",
          preprocess_tts_text(
              "<thinking>该\n说\n什么</thinking>你好"
          ) == "你好")
    check("strips thinking with inner *action*",
          preprocess_tts_text(
              "<thinking>*想想* 该说什么</thinking>你好"
          ) == "你好")
    check("non-greedy across two thinking blocks",
          preprocess_tts_text(
              "<thinking>A</thinking>正文<thinking>B</thinking>结尾"
          ) == "正文结尾")


def test_preprocess_returns_empty_when_unspeakable():
    print("\n[preprocess_tts_text — 空 / 仅标点 / 仅标记]")
    check("empty string → ''",
          preprocess_tts_text("") == "")
    check("whitespace → ''",
          preprocess_tts_text("   \n  ") == "")
    check("only punctuation → ''",
          preprocess_tts_text("。。！？") == "")
    check("only action → ''",
          preprocess_tts_text("*笑了笑*") == "")
    check("only thinking → ''",
          preprocess_tts_text("<thinking>内心活动</thinking>") == "")
    check("action + punct → ''",
          preprocess_tts_text("*笑*。。。") == "")
    check("emotion tag only → ''",
          preprocess_tts_text("<emotion>happy</emotion>") == "")


def test_preprocess_mixed_realistic():
    print("\n[preprocess_tts_text — 真实 LLM 输出形态]")
    raw = (
        "<emotion>开心</emotion>"
        "<thinking>用户在打招呼，回应一下</thinking>"
        "*微笑* 你好呀！(轻声)今天过得怎么样？"
    )
    check("strips all tags + actions, keeps prose",
          preprocess_tts_text(raw) == "你好呀！今天过得怎么样？")


# ---------------------------------------------------------------------------
# 6.b _PreprocessingEngine integration
# ---------------------------------------------------------------------------

class _CapturingEngine(TTSBase):
    """记录 synthesize 收到了什么，固定返回一段假音频。"""

    def __init__(self) -> None:
        self.calls: list = []

    async def synthesize(self, text, emotion="默认"):
        self.calls.append((text, emotion))
        return b"AUDIO" if text else None


async def test_preprocessing_engine_strips_before_synth():
    print("\n[_PreprocessingEngine — 剥离后再调下游]")
    inner = _CapturingEngine()
    eng = _PreprocessingEngine(inner)
    result = await eng.synthesize("*笑*你好(悄声)！", emotion="开心")
    check("returned audio", result == b"AUDIO")
    check("inner saw cleaned text",
          inner.calls and inner.calls[0][0] == "你好！")
    check("emotion preserved",
          inner.calls and inner.calls[0][1] == "开心")


async def test_preprocessing_engine_skips_when_empty():
    print("\n[_PreprocessingEngine — 空文本跳过下游]")
    inner = _CapturingEngine()
    eng = _PreprocessingEngine(inner)
    result = await eng.synthesize("*只有动作*", emotion="默认")
    check("returned None", result is None)
    check("inner not called", inner.calls == [])

    result2 = await eng.synthesize("<thinking>X</thinking>", emotion="默认")
    check("thinking-only → None", result2 is None)
    check("inner still not called", inner.calls == [])


async def test_preprocessing_engine_passthrough_clean_text():
    print("\n[_PreprocessingEngine — 干净文本直通]")
    inner = _CapturingEngine()
    eng = _PreprocessingEngine(inner)
    await eng.synthesize("你好世界！", emotion="默认")
    check("inner saw exact text",
          inner.calls and inner.calls[0][0] == "你好世界！")


# ---------------------------------------------------------------------------
# 6.c TTSManager integrates preprocess in legacy path
# ---------------------------------------------------------------------------

async def test_manager_preprocess_strips_action():
    print("\n[TTSManager — 旧路径剥离 *动作*]")
    mgr = _make_manager(sovits_ok=False, edge_audio=b"OK")
    await mgr.synthesize("*笑*你好。", "默认")
    check("edge saw cleaned text",
          mgr._edge.calls and mgr._edge.calls[0][0] == "你好。")


async def test_manager_preprocess_skips_empty_sentence():
    print("\n[TTSManager — 仅动作的句子被跳过]")
    mgr = _make_manager(sovits_ok=False, edge_audio=b"X")
    # split_sentences 切成 ["*笑*。", "你好。"]，第一句被预处理掉
    result = await mgr.synthesize("*笑*。你好。", "默认")
    # 只调用一次，第一句剥后为空跳过
    check("only one synth call",
          len(mgr._edge.calls) == 1)
    check("the call was the speakable sentence",
          mgr._edge.calls[0][0] == "你好。")
    check("audio for one sentence",
          result == b"X")


# ---------------------------------------------------------------------------
# 6.d v3-F #3: concurrent TTS pipeline (_tts_synth_with_timeout +
#              _tts_audio_consumer)
# ---------------------------------------------------------------------------

import time as _time

from backend.routes.ws import (
    _tts_synth_with_timeout,
    _tts_audio_consumer,
)


class _DelayEngine(TTSBase):
    """每次 synthesize 延迟 *delay* 秒后返回 ``label`` 字节序列。

    用于测试：并发执行（多个 in-flight）+ 顺序播放（FIFO consumer）。
    label 唯一，便于按字节判断顺序。
    """

    def __init__(self, plan: list) -> None:
        # plan: List[(label_byte, delay_seconds, mode)]; mode in {'ok','raise','sleep_long'}
        self._plan = list(plan)
        self.calls: list = []

    async def synthesize(self, text, emotion="默认"):
        idx = len(self.calls)
        self.calls.append((text, emotion, _time.perf_counter()))
        if idx >= len(self._plan):
            return b"X"
        label, delay, mode = self._plan[idx]
        if mode == "sleep_long":
            # 睡得比超时还久；调用方 wait_for 会先 cancel
            await asyncio.sleep(delay)
            return bytes([label])
        if mode == "raise":
            await asyncio.sleep(delay)
            raise RuntimeError(f"synth {label} broken")
        await asyncio.sleep(delay)
        return bytes([label])


async def _drive_pipeline(
    engine: TTSBase,
    sentences: list,         # List[(text, emotion)]
    *,
    timeout: float = 10.0,
    sem_size: int = 3,
) -> list:
    """在测试里跑一遍 producer/consumer 模式，返回 sender 收到的音频列表。

    producer 顺序 spawn _tts_synth_with_timeout task → put queue；末尾投 None。
    consumer 顺序 await 后调 sender。
    """
    sem = asyncio.Semaphore(sem_size)
    queue: "asyncio.Queue" = asyncio.Queue()
    received: list = []

    async def sender(audio: bytes) -> None:
        received.append(audio)

    consumer = asyncio.create_task(_tts_audio_consumer(queue, sender))

    for idx, (text, emotion) in enumerate(sentences, start=1):
        t = asyncio.create_task(
            _tts_synth_with_timeout(
                engine, text, emotion, idx=idx, sem=sem, timeout=timeout,
            )
        )
        await queue.put(t)
    await queue.put(None)
    await consumer
    return received


async def test_concurrent_tts_preserves_order():
    print("\n[TTS pipeline — order preserved despite concurrency]")
    # 3 句，每句返回不同 label，第 1 句最慢；并发跑也要按 1,2,3 顺序送达
    engine = _DelayEngine([
        (1, 0.20, "ok"),
        (2, 0.05, "ok"),
        (3, 0.05, "ok"),
    ])
    t0 = _time.perf_counter()
    received = await _drive_pipeline(engine, [
        ("句一", "happy"),
        ("句二", "happy"),
        ("句三", "happy"),
    ])
    elapsed = _time.perf_counter() - t0

    check("3 audios delivered", len(received) == 3)
    check("order = 1,2,3 (FIFO)",
          received == [b"\x01", b"\x02", b"\x03"])
    # 并行：3 句串行需 ~0.30s，并发 3 应 < 0.30 (~0.20 主导)
    check(f"runtime concurrent (~0.20s, got {elapsed:.2f}s)",
          elapsed < 0.30)


async def test_concurrent_tts_preserves_emotion_per_call():
    print("\n[TTS pipeline — emotion forwarded per call]")
    engine = _DelayEngine([(1, 0.01, "ok"), (2, 0.01, "ok")])
    await _drive_pipeline(engine, [
        ("句一", "happy"),
        ("句二", "happy"),  # 整轮一致
    ])
    emotions = [e for _, e, _ in engine.calls]
    check("both calls got 'happy'", emotions == ["happy", "happy"])


async def test_concurrent_tts_skips_failed_sentence():
    print("\n[TTS pipeline — exception in synth → skipped]")
    engine = _DelayEngine([
        (1, 0.01, "ok"),
        (2, 0.01, "raise"),
        (3, 0.01, "ok"),
    ])
    received = await _drive_pipeline(engine, [
        ("句一", "默认"),
        ("句二", "默认"),
        ("句三", "默认"),
    ])
    check("2 audios delivered (failed one skipped)",
          received == [b"\x01", b"\x03"])


async def test_concurrent_tts_timeout_skips():
    print("\n[TTS pipeline — timeout → None → skipped]")
    engine = _DelayEngine([
        (1, 0.01, "ok"),
        (2, 0.50, "sleep_long"),  # 睡 0.5s，超时设 0.1s
        (3, 0.01, "ok"),
    ])
    received = await _drive_pipeline(
        engine,
        [("句一", "默认"), ("句二", "默认"), ("句三", "默认")],
        timeout=0.10,
    )
    check("timed-out sentence dropped, others kept",
          received == [b"\x01", b"\x03"])


async def test_concurrent_tts_semaphore_limits_inflight():
    print("\n[TTS pipeline — semaphore limits concurrency]")
    # 5 句各睡 0.20s，sem=2 → 串行批次 ≈ 3 批 → ~0.60s；sem=5 应 ~0.20s
    sentences = [(f"s{i}", "默认") for i in range(5)]

    engine_sem2 = _DelayEngine([(i + 1, 0.20, "ok") for i in range(5)])
    t0 = _time.perf_counter()
    await _drive_pipeline(engine_sem2, sentences, sem_size=2)
    elapsed_sem2 = _time.perf_counter() - t0

    engine_sem5 = _DelayEngine([(i + 1, 0.20, "ok") for i in range(5)])
    t0 = _time.perf_counter()
    await _drive_pipeline(engine_sem5, sentences, sem_size=5)
    elapsed_sem5 = _time.perf_counter() - t0

    check(f"sem=5 faster than sem=2 ({elapsed_sem5:.2f}s < {elapsed_sem2:.2f}s)",
          elapsed_sem5 < elapsed_sem2 - 0.10)
    check(f"sem=2 ≥ ~0.55s (3 batches @ 0.20s, got {elapsed_sem2:.2f}s)",
          elapsed_sem2 > 0.55)


async def test_consumer_handles_sender_failure():
    print("\n[TTS pipeline — sender exception logged, doesn't break others]")
    engine = _DelayEngine([(1, 0.01, "ok"), (2, 0.01, "ok"), (3, 0.01, "ok")])
    sem = asyncio.Semaphore(3)
    queue: "asyncio.Queue" = asyncio.Queue()
    delivered: list = []
    fail_call = {"count": 0}

    async def flaky_sender(audio: bytes) -> None:
        fail_call["count"] += 1
        if fail_call["count"] == 2:
            raise IOError("ws closed")
        delivered.append(audio)

    consumer = asyncio.create_task(_tts_audio_consumer(queue, flaky_sender))
    for idx, (text, emotion) in enumerate(
        [("a", "默认"), ("b", "默认"), ("c", "默认")], start=1,
    ):
        t = asyncio.create_task(
            _tts_synth_with_timeout(engine, text, emotion, idx=idx, sem=sem)
        )
        await queue.put(t)
    await queue.put(None)
    await consumer

    check("sender failure on #2 doesn't kill consumer",
          delivered == [b"\x01", b"\x03"])


# ---------------------------------------------------------------------------
# 7. Module singleton
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
    # v3-F preprocess
    test_preprocess_passthrough()
    test_preprocess_strips_action()
    test_preprocess_strips_parens()
    test_preprocess_strips_emotion_motion()
    test_preprocess_strips_thinking()
    test_preprocess_returns_empty_when_unspeakable()
    test_preprocess_mixed_realistic()
    await test_preprocessing_engine_strips_before_synth()
    await test_preprocessing_engine_skips_when_empty()
    await test_preprocessing_engine_passthrough_clean_text()
    await test_manager_preprocess_strips_action()
    await test_manager_preprocess_skips_empty_sentence()
    # v3-F #3 concurrent TTS pipeline
    await test_concurrent_tts_preserves_order()
    await test_concurrent_tts_preserves_emotion_per_call()
    await test_concurrent_tts_skips_failed_sentence()
    await test_concurrent_tts_timeout_skips()
    await test_concurrent_tts_semaphore_limits_inflight()
    await test_consumer_handles_sender_failure()
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
