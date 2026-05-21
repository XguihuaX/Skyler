"""INV-9 §5+§6 · per-provider [bracket] markers e2e smoke(LLM 端 → 端 verify)。

per PM Phase 2 第 3 commit smoke 要求:
  - 集成:模拟 LLM 带 marker 输出,fish 路径(保留)+ cosyvoice 路径(剥除)
    端到端 verify
  - 字幕层:strip_ja_en_tags_for_subtitle 输出永远不含 [bracket]
  - WAV 输出保留作 PM 听感验证

fish 路径走真 SDK 合成(per Mai canon range 5 markers);cosyvoice 路径用
mock inner engine(无 DASHSCOPE_API_KEY 依赖,仅 verify markers 剥除路径)。
"""
from __future__ import annotations
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OUT_DIR = ROOT / "scripts" / "fish_probe_outputs"
OUT_DIR.mkdir(parents=True, exist_ok=True)

REF_TEXT = (ROOT / "tts" / "fish" / "参考音频" / "mai" / "mai5min_0033.lab").read_text(encoding="utf-8").strip()

fish_voice_model = json.dumps({
    "provider": "fish",
    "voice": "mai5min_0033",
    "model": "s2-pro",
    "tts_language": "ja",
    "reference_audio_path": "tts/fish/参考音频/mai/mai5min_0033.wav",
    "reference_text": REF_TEXT,
    "fish_latency": "balanced",
})


# Mai canon range 5 markers · 模拟 LLM 输出 raw(含 <ja> wrap + emotion marker)
MAI_CANON_CASES = [
    ("composed",
     '"我看你今天没什么精神。"<ja>[composed]「君、今日は元気がないね。」</ja>'),
    ("sarcastic",
     '"哦,真厉害啊。"<ja>[sarcastic]「あら、すごいじゃない。」</ja>'),
    ("teasing",
     '"看,又被我猜中了。"<ja>[teasing]「ほら、また当たったでしょ。」</ja>'),
    ("gentle",
     '"别太勉强自己。"<ja>[gentle]「あんまり無理しないでね。」</ja>'),
    ("soft chuckle",
     '"哎,真拿你没办法。"<ja>[soft chuckle]「やれやれ、君って人は。」</ja>'),
]


class _CaptureTTS:
    """Mock TTSBase — 记录收到 text 不真合成。"""
    def __init__(self) -> None:
        self.received: Optional[str] = None

    async def synthesize(self, text: str, emotion: str = "默认"):
        self.received = text
        return None  # 不返 audio,这是 mock


async def main() -> int:
    from backend.tts import get_tts_engine, _PreprocessingEngine
    from backend.utils.text_filters import (
        extract_tts_text, strip_ja_en_tags_for_subtitle,
    )

    print("=" * 70)
    print("INV-9 §5+§6 · per-provider [bracket] markers e2e smoke")
    print("=" * 70)

    # ───────────────────────────────────────────────────────────
    # Part 1 · fish 路径 5 markers 真合成
    # ───────────────────────────────────────────────────────────
    print("\n## Part 1 · fish 路径 5 markers 真合成 (Mai canon range)")
    engine = get_tts_engine(fish_voice_model)
    print(f"engine class = {type(engine).__name__} / "
          f"inner = {type(getattr(engine, '_inner', None)).__name__}")

    fish_ok = 0
    for marker_name, llm_raw in MAI_CANON_CASES:
        # 模拟 ws.py:935-959 路径:extract_tts_text → engine.synthesize
        tts_text = extract_tts_text(llm_raw, "ja")
        subtitle = strip_ja_en_tags_for_subtitle(llm_raw)

        # 校验:tts_text 含 marker,subtitle 不含 marker
        marker_in_tts = f"[{marker_name}]" in tts_text
        marker_in_subtitle = "[" in subtitle

        print(f"\n[{marker_name}]")
        print(f"  raw       : {llm_raw!r}")
        print(f"  tts_text  : {tts_text!r}")
        print(f"  subtitle  : {subtitle!r}")
        print(f"  marker in tts:      {'✓' if marker_in_tts else '✗'}")
        print(f"  subtitle no bracket: {'✓' if not marker_in_subtitle else '✗'}")

        t0 = time.perf_counter()
        audio = await engine.synthesize(tts_text)
        elapsed = (time.perf_counter() - t0) * 1000

        if audio:
            out_path = OUT_DIR / f"INV9_e2e_fish_{marker_name.replace(' ', '_')}.wav"
            out_path.write_bytes(audio)
            dur = len(audio) / 88200
            print(f"  ✅ synth OK {elapsed:.0f}ms / audio {len(audio):,}B "
                  f"≈ {dur:.2f}s → {out_path.name}")
            fish_ok += 1
        else:
            print(f"  ❌ synth returned None ({elapsed:.0f}ms)")

    print(f"\n[Part 1 summary] fish 路径 {fish_ok}/{len(MAI_CANON_CASES)} OK")

    # ───────────────────────────────────────────────────────────
    # Part 2 · cosyvoice 路径(mock inner)markers 剥除验证
    # ───────────────────────────────────────────────────────────
    print("\n## Part 2 · cosyvoice 路径(mock inner)· markers 剥除 verify")
    cosy_pass = 0
    cosy_total = 0
    for marker_name, llm_raw in MAI_CANON_CASES:
        tts_text = extract_tts_text(llm_raw, "ja")
        # 直接构造 _PreprocessingEngine provider='cosyvoice' + mock inner
        mock_inner = _CaptureTTS()
        cosy_engine = _PreprocessingEngine(mock_inner, provider="cosyvoice")
        await cosy_engine.synthesize(tts_text)

        marker_in_inner_received = (
            mock_inner.received and f"[{marker_name}]" in mock_inner.received
        )
        cosy_total += 1
        if not marker_in_inner_received:
            cosy_pass += 1
            print(f"  [{marker_name}] ✓ cosyvoice 路径剥除 markers · inner 收到 "
                  f"{mock_inner.received!r}")
        else:
            print(f"  [{marker_name}] ✗ cosyvoice 路径泄漏 markers!inner 收到 "
                  f"{mock_inner.received!r}")

    print(f"\n[Part 2 summary] cosyvoice 路径剥除 {cosy_pass}/{cosy_total} OK")

    # ───────────────────────────────────────────────────────────
    # Part 3 · subtitle 字幕层跨 provider 一律剥
    # ───────────────────────────────────────────────────────────
    print("\n## Part 3 · subtitle 字幕层 · 跨 provider 一律剥 [bracket]")
    subtitle_pass = 0
    subtitle_total = 0
    for marker_name, llm_raw in MAI_CANON_CASES:
        subtitle = strip_ja_en_tags_for_subtitle(llm_raw)
        subtitle_total += 1
        if "[" not in subtitle and "]" not in subtitle:
            subtitle_pass += 1
            print(f"  [{marker_name}] ✓ subtitle 无 [bracket] · {subtitle!r}")
        else:
            print(f"  [{marker_name}] ✗ subtitle 含 [bracket]!{subtitle!r}")

    print(f"\n[Part 3 summary] subtitle 剥 {subtitle_pass}/{subtitle_total} OK")

    # ───────────────────────────────────────────────────────────
    # 总结
    # ───────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    total_ok = (fish_ok == len(MAI_CANON_CASES) and
                cosy_pass == cosy_total and
                subtitle_pass == subtitle_total)
    print(f"e2e smoke: fish {fish_ok}/{len(MAI_CANON_CASES)} "
          f"+ cosyvoice {cosy_pass}/{cosy_total} "
          f"+ subtitle {subtitle_pass}/{subtitle_total} = "
          f"{'✅ ALL PASS' if total_ok else '❌ FAIL'}")
    return 0 if total_ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
