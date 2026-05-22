"""INV-9 参数 sweep 刀(2026-05-22)· Fish s2-pro temperature × text grid。

诊断 Mai 音色 fidelity(PM 听 INV9_smoke_basic_ja + soft_chuckle 反馈不够像 Mai)。

Grid:
  - temperature ∈ {0.2, 0.4, 0.6, 0.8} × texts ∈ {S1, S2, S3, S4}
  - 固定 top_p=0.7, fish_seed=42(SDK 不接受 seed,sweep 实证 byte-identical)
  - 16 主表 calls

Texts:
  S1 = "こんにちは、今日もよろしくお願いします。"            (基础日语对白)
  S2 = "私、桜島麻衣。桜島の桜、麻衣の衣。簡単でしょう?"     (Mai 自我介绍 canon)
  S3 = "[teasing] あら、来たのね。"                          (短 + emotion marker)
  S4 = "[soft chuckle] フン、待ってたわよ。先輩として、..."  (长 + emotion)

Seed sanity check(+3 calls):
  - T=0.4, S2, seed=42 × 3 runs
  - 期望 byte-identical(SDK 真识 seed 时)
  - 不 identical → summary 标注 "seed param non-functional"

输出:
  - WAV → scripts/fish_probe_outputs/INV9_param_T{02|04|06|08}_S{1|2|3|4}.wav
  - Seed → scripts/fish_probe_outputs/INV9_param_T04_S2_run{1|2|3}.wav
  - summary.json:每条 temp/text_id/seed/latency_ms/bytes/md5

成本:~19 × $0.025 ≈ ~$0.50

跑法:
    .venv/bin/python scripts/fish_param_sweep.py
"""
from __future__ import annotations
import asyncio
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OUT_DIR = ROOT / "scripts" / "fish_probe_outputs"
OUT_DIR.mkdir(parents=True, exist_ok=True)

REF_TEXT = (ROOT / "tts" / "fish" / "参考音频" / "mai" / "mai5min_0033.lab").read_text(encoding="utf-8").strip()


def build_voice_model(temperature: float, top_p: float, seed: int) -> str:
    return json.dumps({
        "provider": "fish",
        "voice": "mai5min_0033",
        "model": "s2-pro",
        "tts_language": "ja",
        "reference_audio_path": "tts/fish/参考音频/mai/mai5min_0033.wav",
        "reference_text": REF_TEXT,
        "fish_latency": "balanced",
        "fish_temperature": temperature,
        "fish_top_p": top_p,
        "fish_seed": seed,
    })


TEXTS = {
    "S1": "こんにちは、今日もよろしくお願いします。",
    "S2": "私、桜島麻衣。桜島の桜、麻衣の衣。簡単でしょう?",
    "S3": "[teasing] あら、来たのね。",
    "S4": "[soft chuckle] フン、待ってたわよ。先輩として、ちゃんと面倒見てあげるから。",
}

TEMPS = [0.2, 0.4, 0.6, 0.8]
TOP_P = 0.7
SEED = 42


def temp_label(t: float) -> str:
    """0.2 → 'T02';0.4 → 'T04'。"""
    return f"T{int(round(t * 10)):02d}"


async def one_call(name: str, voice_model_json: str, text: str) -> dict:
    from backend.tts import get_tts_engine

    engine = get_tts_engine(voice_model_json)
    t0 = time.perf_counter()
    audio = await engine.synthesize(text)
    elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)

    if audio is None:
        return {
            "name": name, "text": text, "audio_bytes": 0,
            "elapsed_ms": elapsed_ms, "md5": None, "error": "synth returned None",
        }

    out_path = OUT_DIR / f"{name}.wav"
    out_path.write_bytes(audio)
    md5 = hashlib.md5(audio).hexdigest()
    dur_sec = round(len(audio) / 88200, 2)  # 44.1kHz mono 16bit
    return {
        "name": name,
        "text": text,
        "audio_bytes": len(audio),
        "audio_dur_sec": dur_sec,
        "elapsed_ms": elapsed_ms,
        "md5": md5,
        "out_path": str(out_path.relative_to(ROOT)),
        "error": None,
    }


async def main() -> int:
    print("=" * 70)
    print("INV-9 参数 sweep · Fish s2-pro temperature × text grid")
    print(f"Grid: {len(TEMPS)} temps × {len(TEXTS)} texts = {len(TEMPS) * len(TEXTS)} 主表 calls")
    print(f"Fixed: top_p={TOP_P}, fish_seed={SEED}")
    print(f"Plus seed sanity check: T=0.4 S=S2 × 3 runs")
    print("=" * 70)

    summary = {
        "grid": {"temperatures": TEMPS, "texts": list(TEXTS.keys()),
                 "top_p_fixed": TOP_P, "seed_fixed": SEED},
        "texts": TEXTS,
        "calls": [],
        "seed_sanity": [],
        "notes": [],
    }

    # Pre-check:get_api_credit / package balance
    from fish_audio_sdk import Session
    from pathlib import Path as P
    api_key = (P(ROOT / "api_key.txt").read_text().strip()
               if (ROOT / "api_key.txt").exists()
               else "")
    if api_key:
        s = Session(api_key)
        try:
            cred = s.get_api_credit()
            pkg = s.get_package()
            summary["balance_start"] = {
                "credit": str(cred.credit),
                "package_balance": pkg.balance, "package_total": pkg.total,
            }
            print(f"\n[balance start] credit=${cred.credit} package={pkg.balance}/{pkg.total} bytes")
        except Exception as exc:
            print(f"[balance err] {exc}")

    # ── 主表 grid 16 calls ──────────────────────────────────────────
    print("\n## 主表 grid 16 calls(temp × text)\n")
    for temp in TEMPS:
        for text_id, text in TEXTS.items():
            name = f"INV9_param_{temp_label(temp)}_{text_id}"
            print(f"[run] {name} · T={temp} · text={text!r}")
            voice_model = build_voice_model(temp, TOP_P, SEED)
            res = await one_call(name, voice_model, text)
            res["temperature"] = temp
            res["text_id"] = text_id
            res["top_p"] = TOP_P
            res["seed"] = SEED
            summary["calls"].append(res)
            if res["error"]:
                print(f"  ❌ {res['error']}")
            else:
                print(f"  ✅ {res['elapsed_ms']}ms · {res['audio_bytes']:,}B "
                      f"({res['audio_dur_sec']}s) · md5={res['md5'][:12]}...")

    # ── Seed sanity 3 runs:T=0.4 S2 seed=42 × 3 ────────────────────
    print("\n## Seed sanity check · T=0.4 S=S2 × 3 runs(seed=42 fixed)\n")
    sanity_text = TEXTS["S2"]
    sanity_md5s = []
    for run_i in (1, 2, 3):
        name = f"INV9_param_T04_S2_run{run_i}"
        voice_model = build_voice_model(0.4, TOP_P, SEED)
        print(f"[run] {name}")
        res = await one_call(name, voice_model, sanity_text)
        res["run_idx"] = run_i
        res["temperature"] = 0.4
        res["text_id"] = "S2"
        res["top_p"] = TOP_P
        res["seed"] = SEED
        summary["seed_sanity"].append(res)
        if res["md5"]:
            sanity_md5s.append(res["md5"])
            print(f"  ✅ {res['elapsed_ms']}ms · {res['audio_bytes']:,}B "
                  f"({res['audio_dur_sec']}s) · md5={res['md5']}")
        else:
            print(f"  ❌ {res['error']}")

    # ── Seed sanity verdict ─────────────────────────────────────────
    unique_md5s = set(sanity_md5s)
    if len(unique_md5s) == 1 and len(sanity_md5s) == 3:
        verdict = ("seed param FUNCTIONAL — 3 runs byte-identical "
                   f"(md5={sanity_md5s[0][:16]}...);SDK 暗中接受 seed?")
    elif len(unique_md5s) > 1:
        verdict = (f"seed param NON-FUNCTIONAL — 3 runs 不 identical "
                   f"({len(unique_md5s)} 不同 md5);SDK TTSRequest 确不识 "
                   f"seed 字段(per fish-audio-sdk 1.3.0 introspect)")
    else:
        verdict = f"seed sanity 未完整(只有 {len(sanity_md5s)} runs 成功)"

    summary["seed_verdict"] = verdict
    print(f"\n[seed verdict] {verdict}")

    # ── Post-balance ──────────────────────────────────────────────
    if api_key:
        try:
            cred = s.get_api_credit()
            pkg = s.get_package()
            summary["balance_end"] = {
                "credit": str(cred.credit),
                "package_balance": pkg.balance, "package_total": pkg.total,
            }
            print(f"\n[balance end] credit=${cred.credit} package={pkg.balance}/{pkg.total} bytes")
        except Exception:
            pass

    # ── 写 summary.json ────────────────────────────────────────────
    summary_path = OUT_DIR / "INV9_param_sweep_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\n[summary] written to {summary_path.relative_to(ROOT)}")

    # ── 表格总览 ────────────────────────────────────────────────────
    print("\n## 主表 grid 总览 · audio_dur_sec(approx 视觉对比)\n")
    print(f"{'':>4} | " + " | ".join(f"{tid:>4}" for tid in TEXTS) + "  ·  ms 中位数")
    print("-" * 60)
    for temp in TEMPS:
        row = [f"{temp_label(temp):>4}"]
        ms_list = []
        for text_id in TEXTS:
            cell = next((c for c in summary["calls"]
                         if c["temperature"] == temp and c["text_id"] == text_id), None)
            if cell and cell.get("audio_dur_sec") is not None:
                row.append(f"{cell['audio_dur_sec']:>4.2f}")
                ms_list.append(cell["elapsed_ms"])
            else:
                row.append("  -- ")
        median_ms = int(sorted(ms_list)[len(ms_list) // 2]) if ms_list else 0
        print(" | ".join(row) + f"  ·  ~{median_ms}ms")

    ok_count = sum(1 for c in summary["calls"] if not c["error"])
    sanity_ok = sum(1 for c in summary["seed_sanity"] if not c["error"])
    total_ok = ok_count + sanity_ok
    total_calls = len(summary["calls"]) + len(summary["seed_sanity"])
    print(f"\n[result] {total_ok}/{total_calls} calls OK · {ok_count}/{len(summary['calls'])} grid · "
          f"{sanity_ok}/{len(summary['seed_sanity'])} sanity")

    return 0 if total_ok == total_calls else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
