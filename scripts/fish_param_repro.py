"""INV-9 参数 sweep part 3 · Part 1 T=0.2 复现 audit(2026-05-22)。

PM 决策:Part 1 T=0.2 听感 ≫ Part 2 T=0.20 三 runs → 不是抽样运气,需查清。

任务:重跑 Part 1 同一组 T=0.2 × 4 texts(用与 Part 1 完全相同的 voice_model
JSON 结构,含 fish_seed=42 字段),比 md5/bytes/duration 跟原 Part 1 输出。

完全一致(byte-identical)→ 服务器侧今天稳定,Part 2 听感差异原因不在
脚本(只能是抽样运气 / 模型版本切换 / 时间窗口波动等服务器侧)。

不一致 → 服务器侧已变(模型 / 路由更新等)→ 影响生产 default T 决策。

输出 INV9_repro_T02_S{1|2|3|4}.wav + INV9_repro_summary.json(含 diff matrix
vs 原 Part 1)。
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


# 与 scripts/fish_param_sweep.py 完全相同的 build_voice_model · 含 fish_seed
def build_voice_model_part1(temperature: float, top_p: float, seed: int) -> str:
    """Part 1 build_voice_model 完全复制(含 fish_seed 字段)。"""
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

TOP_P = 0.7
SEED = 42


# 原 Part 1 T=0.2 输出 md5 + bytes(从 INV9_param_sweep_summary.json 实测记录)
ORIGINAL_PART1_T02 = {
    "S1": {"md5": "9c9f0309d3d5", "bytes": 208940, "dur_sec": 2.37},
    "S2": {"md5": "26d5c0c65f06", "bytes": 573484, "dur_sec": 6.50},
    "S3": {"md5": "2ee36cc75623", "bytes": 135212, "dur_sec": 1.53},
    "S4": {"md5": "04bd7343dc39", "bytes": 442412, "dur_sec": 5.02},
}


async def one_call(name: str, voice_model_json: str, text: str) -> dict:
    from backend.tts import get_tts_engine

    engine = get_tts_engine(voice_model_json)
    t0 = time.perf_counter()
    audio = await engine.synthesize(text)
    elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)

    if audio is None:
        return {
            "name": name, "text": text, "audio_bytes": 0,
            "elapsed_ms": elapsed_ms, "md5": None,
            "md5_prefix": None, "audio_dur_sec": None,
            "error": "synth returned None",
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
        "md5_prefix": md5[:12],
        "out_path": str(out_path.relative_to(ROOT)),
        "error": None,
    }


async def main() -> int:
    print("=" * 70)
    print("INV-9 part 3 · Part 1 T=0.2 复现 audit")
    print("Re-run T=0.2 × 4 texts (与 Part 1 完全相同 voice_model 含 fish_seed=42)")
    print("Compare md5 / bytes vs 原 Part 1 INV9_param_T02_S{1-4}")
    print("=" * 70)

    # Balance start
    from fish_audio_sdk import Session
    api_key_file = ROOT / "api_key.txt"
    api_key = api_key_file.read_text(encoding="utf-8").strip() if api_key_file.exists() else ""
    if api_key:
        s = Session(api_key)
        try:
            cred = s.get_api_credit()
            pkg = s.get_package()
            print(f"\n[balance start] credit=${cred.credit} package={pkg.balance}/{pkg.total}")
        except Exception:
            pass

    results = []
    for text_id, text in TEXTS.items():
        name = f"INV9_repro_T02_{text_id}"
        print(f"\n[run] {name} · text={text!r}")
        voice_model = build_voice_model_part1(0.2, TOP_P, SEED)
        res = await one_call(name, voice_model, text)
        res["text_id"] = text_id
        results.append(res)

        if res["error"]:
            print(f"  ❌ {res['error']}")
            continue

        original = ORIGINAL_PART1_T02[text_id]
        bytes_match = res["audio_bytes"] == original["bytes"]
        md5_match = res["md5"].startswith(original["md5"])
        dur_match = res["audio_dur_sec"] == original["dur_sec"]
        print(f"  ✅ {res['elapsed_ms']}ms · {res['audio_bytes']:,}B ({res['audio_dur_sec']}s) "
              f"md5={res['md5_prefix']}...")
        print(f"  → vs original Part 1: bytes {original['bytes']:,} "
              f"({'==' if bytes_match else '≠'}) / "
              f"md5 {original['md5']}... ({'==' if md5_match else '≠'}) / "
              f"dur {original['dur_sec']}s ({'==' if dur_match else '≠'})")
        res["original_bytes"] = original["bytes"]
        res["original_md5_prefix"] = original["md5"]
        res["original_dur_sec"] = original["dur_sec"]
        res["bytes_match"] = bytes_match
        res["md5_match"] = md5_match
        res["dur_match"] = dur_match
        res["bytes_delta"] = res["audio_bytes"] - original["bytes"]
        res["dur_delta_sec"] = round(res["audio_dur_sec"] - original["dur_sec"], 2)

    # Balance end
    if api_key:
        try:
            cred = s.get_api_credit()
            pkg = s.get_package()
            print(f"\n[balance end] credit=${cred.credit} package={pkg.balance}/{pkg.total}")
        except Exception:
            pass

    # ── Diff matrix 总览 ───────────────────────────────────────────
    print("\n" + "=" * 70)
    print("Diff matrix · 复现 vs 原 Part 1")
    print("=" * 70)
    print(f"{'text':>4} | {'orig bytes':>11} | {'repro bytes':>12} | {'Δ bytes':>9} | "
          f"{'orig dur':>8} | {'repro dur':>9} | match")
    print("-" * 80)
    n_md5_match = 0
    n_byte_match = 0
    n_dur_match = 0
    for r in results:
        if r.get("error"):
            print(f"  {r.get('text_id', '?')} · 错误")
            continue
        match_str = f"md5{'✓' if r['md5_match'] else '✗'} bytes{'✓' if r['bytes_match'] else '✗'}"
        if r["md5_match"]: n_md5_match += 1
        if r["bytes_match"]: n_byte_match += 1
        if r["dur_match"]: n_dur_match += 1
        print(f"  {r['text_id']:>2} | {r['original_bytes']:>11,} | {r['audio_bytes']:>12,} | "
              f"{r['bytes_delta']:>+9,} | {r['original_dur_sec']:>7.2f}s | "
              f"{r['audio_dur_sec']:>8.2f}s | {match_str}")

    print()
    print(f"md5 match: {n_md5_match}/{len(results)}")
    print(f"bytes match: {n_byte_match}/{len(results)}")
    print(f"duration match: {n_dur_match}/{len(results)}")

    # ── Verdict ───────────────────────────────────────────────────
    if n_md5_match == len(results):
        verdict = ("byte-identical 完全 reproducible · 服务器侧今天稳定;"
                   "Part 2 听感差异在脚本逻辑(diff 已 audit:仅 fish_seed 字段差) "
                   "或抽样运气(同 T 不同 run 6.7%-27.6% 变异度 per part 2)")
    elif n_md5_match == 0:
        verdict = ("0/4 md5 match · 服务器侧 stochastic — Fish 即便 fish_seed=42 仍每次"
                   "不同(per part 1 seed NON-FUNCTIONAL 实证一致);"
                   "Part 1 vs Part 2 听感差异**是服务器侧抽样运气**,非脚本逻辑差")
    else:
        verdict = f"{n_md5_match}/{len(results)} md5 partial match · 中间状态,需进一步分析"

    print(f"\n[verdict] {verdict}")

    # ── 写 summary ─────────────────────────────────────────────────
    summary = {
        "test": "Part 1 T=0.2 复现 audit",
        "verdict": verdict,
        "n_md5_match": n_md5_match,
        "n_byte_match": n_byte_match,
        "n_dur_match": n_dur_match,
        "results": results,
        "original_part1_t02": ORIGINAL_PART1_T02,
    }
    summary_path = OUT_DIR / "INV9_repro_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\n[summary] written to {summary_path.relative_to(ROOT)}")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
