"""INV-9 §4 · FishTTS 直调 smoke(纯 provider 层,绕过 chat stack)。

per PM Phase 2 第 2 commit 要求:用 mai5min_0033.wav reference 跑通 Mai
普通日语对白一次,验证 FishTTS.synthesize() 接口端到端通(get_tts_engine
工厂 → VoiceConfig → FishTTS → SDK → audio bytes → log_tts_call)。

输出 WAV → scripts/fish_probe_outputs/(已 .gitignore;PM 听感验证)。

跑法:
    .venv/bin/python scripts/fish_provider_smoke.py
"""
from __future__ import annotations
import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OUT_DIR = ROOT / "scripts" / "fish_probe_outputs"
OUT_DIR.mkdir(parents=True, exist_ok=True)

REF_TEXT_FILE = ROOT / "tts" / "fish" / "参考音频" / "mai" / "mai5min_0033.lab"

# 模拟 DB 里 cid=101 (樱岛麻衣) 改 fish provider 后的 voice_model JSON
voice_model_json = json.dumps({
    "provider": "fish",
    "voice": "mai5min_0033",
    "model": "s2-pro",
    "tts_language": "ja",
    "reference_audio_path": "tts/fish/参考音频/mai/mai5min_0033.wav",
    "reference_text": REF_TEXT_FILE.read_text(encoding="utf-8").strip(),
    "fish_latency": "balanced",
})


async def main() -> int:
    # 通过 get_tts_engine 工厂(per ws.py:733 生产路径)
    from backend.tts import get_tts_engine

    print("[smoke] 构造 FishTTS via get_tts_engine(voice_model_json)...")
    engine = get_tts_engine(voice_model_json)
    print(f"[smoke] engine class = {type(engine).__name__}")
    # 工厂返 _PreprocessingEngine 包装 FishTTS;inner 才是 FishTTS
    inner = getattr(engine, "_inner", None)
    print(f"[smoke] _inner class = {type(inner).__name__ if inner else 'N/A'}")

    # 单句 Mai 日语对白(无 [bracket] markers — 本 commit 不含 §5/§6 双重隔离)
    text = "こんにちは、今日もよろしくお願いします。"
    print(f"\n[smoke] synth text = {text!r}")
    t0 = time.perf_counter()
    audio = await engine.synthesize(text, emotion="默认")
    elapsed_ms = (time.perf_counter() - t0) * 1000

    if audio is None:
        print(f"[smoke] ❌ synth returned None (after {elapsed_ms:.1f}ms)")
        return 1

    out_path = OUT_DIR / "INV9_smoke_basic_ja.wav"
    out_path.write_bytes(audio)
    # 44.1kHz mono 16bit WAV → 88.2 KB/sec audio
    audio_duration_sec = len(audio) / 88200
    print(f"[smoke] ✅ synth OK in {elapsed_ms:.1f}ms")
    print(f"[smoke]    audio bytes = {len(audio):,}")
    print(f"[smoke]    audio dur ≈ {audio_duration_sec:.2f}s (44.1kHz mono)")
    print(f"[smoke]    out = {out_path.relative_to(ROOT)}")

    # 第二句 · 含 inline [bracket] marker(per §1.3 stage 2 + 决策 4 β schema)
    # 仅测 SDK 是否字面接受 marker;声学语义听感由 PM 听 WAV 判
    text_with_marker = "[soft chuckle]ま、いいか。気にしないで。"
    print(f"\n[smoke] synth text with marker = {text_with_marker!r}")
    t0 = time.perf_counter()
    audio2 = await engine.synthesize(text_with_marker, emotion="默认")
    elapsed_ms = (time.perf_counter() - t0) * 1000

    if audio2 is None:
        print(f"[smoke] ❌ marker synth returned None (after {elapsed_ms:.1f}ms)")
        return 1
    out_path2 = OUT_DIR / "INV9_smoke_with_marker.wav"
    out_path2.write_bytes(audio2)
    print(f"[smoke] ✅ marker synth OK in {elapsed_ms:.1f}ms")
    print(f"[smoke]    audio bytes = {len(audio2):,} dur ≈ {len(audio2)/88200:.2f}s")
    print(f"[smoke]    out = {out_path2.relative_to(ROOT)}")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
