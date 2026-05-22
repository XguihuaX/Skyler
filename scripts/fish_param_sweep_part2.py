"""INV-9 参数 sweep part 2(2026-05-22)· T=0.15/0.20/0.30 narrow window + T=0.20 变异度 check。

PM 听完 part 1 19 WAV 后:T=0.2 倾向最优 → narrow 邻域多探 + T=0.2 内
变异度(seed NON-FUNCTIONAL per part 1 实证,需验同 T 同 text 多 run
音质波动)。不下探 T<0.15(PM:更低听感过死板)。

Grid:
  - T=0.20 × 4 texts × 3 runs = 12 calls(变异度 check 主目的)
  - T=0.15 × 4 texts × 1 run = 4 calls(单探)
  - T=0.30 × 4 texts × 1 run = 4 calls(单探)
  - 共 20 calls
  - 固定 top_p=0.7

Texts:reuse part 1 S1-S4
  S1 = "こんにちは、今日もよろしくお願いします。"
  S2 = "私、桜島麻衣。桜島の桜、麻衣の衣。簡単でしょう?"
  S3 = "[teasing] あら、来たのね。"
  S4 = "[soft chuckle] フン、待ってたわよ。先輩として、ちゃんと面倒見てあげるから。"

输出:
  - WAV → scripts/fish_probe_outputs/
    INV9_param2_T020_S{1-4}_run{1-3}.wav  (12)
    INV9_param2_T015_S{1-4}.wav           (4)
    INV9_param2_T030_S{1-4}.wav           (4)
  - summary → scripts/fish_probe_outputs/INV9_param_sweep_part2_summary.json

成本估:~20 × 实测 ~100 bytes ≈ ~$0.03(per part 1 实测 ~5.6% 估算)

跑法:
    .venv/bin/python scripts/fish_param_sweep_part2.py
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


def build_voice_model(temperature: float, top_p: float = 0.7) -> str:
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
    })


TEXTS = {
    "S1": "こんにちは、今日もよろしくお願いします。",
    "S2": "私、桜島麻衣。桜島の桜、麻衣の衣。簡単でしょう?",
    "S3": "[teasing] あら、来たのね。",
    "S4": "[soft chuckle] フン、待ってたわよ。先輩として、ちゃんと面倒見てあげるから。",
}

TOP_P = 0.7


def temp_label(t: float) -> str:
    """0.15 → 'T015';0.20 → 'T020';0.30 → 'T030'(3 位精度,与 part 1 'T02' 区分)。"""
    return f"T{int(round(t * 100)):03d}"


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
    dur_sec = round(len(audio) / 88200, 2)
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
    print("INV-9 参数 sweep part 2 · narrow window + T=0.20 变异度")
    print("Grid:T=0.20 × 4 texts × 3 runs (12)")
    print("    + T=0.15 × 4 texts × 1 run (4)")
    print("    + T=0.30 × 4 texts × 1 run (4)")
    print(f"Fixed: top_p={TOP_P}")
    print("=" * 70)

    summary = {
        "grid": {
            "T020_runs": 3, "T015_runs": 1, "T030_runs": 1,
            "texts": list(TEXTS.keys()),
            "top_p_fixed": TOP_P,
        },
        "texts": TEXTS,
        "calls_T020": [],     # 12 calls (3 runs × 4 texts)
        "calls_T015": [],     # 4 calls
        "calls_T030": [],     # 4 calls
        "variance_T020": {},  # per text · md5 set / bytes 范围
    }

    # Balance start
    from fish_audio_sdk import Session
    api_key_file = ROOT / "api_key.txt"
    api_key = api_key_file.read_text(encoding="utf-8").strip() if api_key_file.exists() else ""
    s_session = None
    if api_key:
        s_session = Session(api_key)
        try:
            cred = s_session.get_api_credit()
            pkg = s_session.get_package()
            summary["balance_start"] = {
                "credit": str(cred.credit),
                "package_balance": pkg.balance, "package_total": pkg.total,
            }
            print(f"\n[balance start] credit=${cred.credit} package={pkg.balance}/{pkg.total} bytes")
        except Exception as exc:
            print(f"[balance err] {exc}")

    # ── T=0.20 × 4 texts × 3 runs(变异度 check 主目的) ─────────────
    print("\n## T=0.20 × 4 texts × 3 runs(变异度 check)\n")
    for text_id, text in TEXTS.items():
        for run_i in (1, 2, 3):
            name = f"INV9_param2_T020_{text_id}_run{run_i}"
            print(f"[run] {name}")
            voice_model = build_voice_model(0.20, TOP_P)
            res = await one_call(name, voice_model, text)
            res["temperature"] = 0.20
            res["text_id"] = text_id
            res["run_idx"] = run_i
            res["top_p"] = TOP_P
            summary["calls_T020"].append(res)
            if res["error"]:
                print(f"  ❌ {res['error']}")
            else:
                print(f"  ✅ {res['elapsed_ms']}ms · {res['audio_bytes']:,}B "
                      f"({res['audio_dur_sec']}s) · md5={res['md5'][:12]}...")

    # ── T=0.15 × 4 texts × 1 run ────────────────────────────────────
    print("\n## T=0.15 × 4 texts × 1 run · 下探\n")
    for text_id, text in TEXTS.items():
        name = f"INV9_param2_T015_{text_id}"
        print(f"[run] {name}")
        voice_model = build_voice_model(0.15, TOP_P)
        res = await one_call(name, voice_model, text)
        res["temperature"] = 0.15
        res["text_id"] = text_id
        res["top_p"] = TOP_P
        summary["calls_T015"].append(res)
        if res["error"]:
            print(f"  ❌ {res['error']}")
        else:
            print(f"  ✅ {res['elapsed_ms']}ms · {res['audio_bytes']:,}B "
                  f"({res['audio_dur_sec']}s) · md5={res['md5'][:12]}...")

    # ── T=0.30 × 4 texts × 1 run ────────────────────────────────────
    print("\n## T=0.30 × 4 texts × 1 run · 上探\n")
    for text_id, text in TEXTS.items():
        name = f"INV9_param2_T030_{text_id}"
        print(f"[run] {name}")
        voice_model = build_voice_model(0.30, TOP_P)
        res = await one_call(name, voice_model, text)
        res["temperature"] = 0.30
        res["text_id"] = text_id
        res["top_p"] = TOP_P
        summary["calls_T030"].append(res)
        if res["error"]:
            print(f"  ❌ {res['error']}")
        else:
            print(f"  ✅ {res['elapsed_ms']}ms · {res['audio_bytes']:,}B "
                  f"({res['audio_dur_sec']}s) · md5={res['md5'][:12]}...")

    # ── 变异度分析 · T=0.20 同 text 3 runs ─────────────────────────
    print("\n## T=0.20 变异度分析(同 text 3 runs · bytes 范围 / md5 set 大小)\n")
    print(f"{'text':>4} | {'run1 bytes':>10} | {'run2 bytes':>10} | {'run3 bytes':>10} | "
          f"{'range':>6} | {'range/min':>8} | unique md5")
    print("-" * 90)
    for text_id in TEXTS:
        runs = [c for c in summary["calls_T020"] if c["text_id"] == text_id]
        runs.sort(key=lambda c: c["run_idx"])
        if len(runs) != 3 or any(r.get("error") for r in runs):
            print(f"  {text_id} · 不完整 / 错误")
            continue
        bts = [r["audio_bytes"] for r in runs]
        md5s = [r["md5"] for r in runs]
        rng = max(bts) - min(bts)
        rng_ratio = rng / min(bts) if min(bts) > 0 else 0
        unique = len(set(md5s))
        summary["variance_T020"][text_id] = {
            "run_bytes": bts, "byte_range": rng,
            "byte_range_ratio": round(rng_ratio, 3),
            "unique_md5_count": unique,
        }
        print(f"  {text_id} | {bts[0]:>10,} | {bts[1]:>10,} | {bts[2]:>10,} | "
              f"{rng:>6,} | {rng_ratio:>7.1%} | {unique}/3")

    # Balance end
    if s_session:
        try:
            cred = s_session.get_api_credit()
            pkg = s_session.get_package()
            summary["balance_end"] = {
                "credit": str(cred.credit),
                "package_balance": pkg.balance, "package_total": pkg.total,
            }
            print(f"\n[balance end] credit=${cred.credit} package={pkg.balance}/{pkg.total} bytes")
            # delta
            start_pkg = summary.get("balance_start", {}).get("package_balance")
            if start_pkg is not None:
                delta = start_pkg - pkg.balance
                print(f"[delta] package -{delta} bytes · cost ~${delta / 1_000_000 * 15:.4f}")
        except Exception:
            pass

    # ── 写 summary.json ────────────────────────────────────────────
    summary_path = OUT_DIR / "INV9_param_sweep_part2_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\n[summary] written to {summary_path.relative_to(ROOT)}")

    # ── 终览 · 跨 T 跨 text audio_dur ──────────────────────────────
    print("\n## 跨 T 跨 text audio_dur_sec 总览\n")
    print(f"{'temp':>5} | " + " | ".join(f"{tid:>4}" for tid in TEXTS) + "  备注")
    print("-" * 60)
    # T015 一行
    row_t015 = [f"{'T015':>5}"]
    for text_id in TEXTS:
        c = next((x for x in summary["calls_T015"] if x["text_id"] == text_id), None)
        row_t015.append(f"{c['audio_dur_sec']:>4.2f}" if c and c.get("audio_dur_sec") else "  --")
    print(" | ".join(row_t015) + "  (1 run 下探)")
    # T020 三行
    for run_i in (1, 2, 3):
        row = [f"{'T020.' + str(run_i):>5}"]
        for text_id in TEXTS:
            c = next((x for x in summary["calls_T020"]
                      if x["text_id"] == text_id and x["run_idx"] == run_i), None)
            row.append(f"{c['audio_dur_sec']:>4.2f}" if c and c.get("audio_dur_sec") else "  --")
        print(" | ".join(row) + f"  (run {run_i})")
    # T030 一行
    row_t030 = [f"{'T030':>5}"]
    for text_id in TEXTS:
        c = next((x for x in summary["calls_T030"] if x["text_id"] == text_id), None)
        row_t030.append(f"{c['audio_dur_sec']:>4.2f}" if c and c.get("audio_dur_sec") else "  --")
    print(" | ".join(row_t030) + "  (1 run 上探)")

    total_ok = (sum(1 for c in summary["calls_T020"] if not c.get("error"))
                + sum(1 for c in summary["calls_T015"] if not c.get("error"))
                + sum(1 for c in summary["calls_T030"] if not c.get("error")))
    total = (len(summary["calls_T020"]) + len(summary["calls_T015"]) +
             len(summary["calls_T030"]))
    print(f"\n[result] {total_ok}/{total} calls OK")
    return 0 if total_ok == total else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
