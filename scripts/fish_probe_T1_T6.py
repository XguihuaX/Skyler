"""INV-8 §1.3 stage 2 · Fish Audio s2-pro 实打验证 T1-T6。

跑法:
    .venv/bin/python scripts/fish_probe_T1_T6.py

输入:
    api_key.txt           Fish API key
    tts/fish/参考音频/mai/mai5min_0033.wav   Mai reference audio (stereo 44100Hz WAV)
    tts/fish/参考音频/mai/mai5min_0033.lab   Mai reference transcript

输出:
    scripts/fish_probe_outputs/   每个 test 的合成 WAV / log

6 大类(per INV-8 §1.3.9):
  T1  基础 zero-shot synth (single 日语 sentence)
  T2  Emotion markers — 5 子项:单 marker / 多 marker 跨句 / 嵌套 / mid-sentence / cross-lang 中文 markers
  T3  Stream vs non-stream (latency baseline)
  T4  错误码触发 — 3 子项:bad reference (zero bytes) / bad key / 超长 text
  T5  Cost 实测(对比 byte 估算)
  T6  References[] audio 格式约束(stereo wav 是否 work / sample rate)

每 call 实际 cost ≈ $0.025/100 日语 chars,总 audit cost cap ~$2。
"""
from __future__ import annotations
import sys
import time
import json
from pathlib import Path
from decimal import Decimal

from fish_audio_sdk import Session, TTSRequest, ReferenceAudio, HttpCodeErr

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "scripts" / "fish_probe_outputs"
OUT_DIR.mkdir(parents=True, exist_ok=True)

API_KEY = (ROOT / "api_key.txt").read_text().strip()
REF_WAV_PATH = ROOT / "tts" / "fish" / "参考音频" / "mai" / "mai5min_0033.wav"
REF_TEXT = (ROOT / "tts" / "fish" / "参考音频" / "mai" / "mai5min_0033.lab").read_text().strip()

REF_AUDIO_BYTES = REF_WAV_PATH.read_bytes()
print(f"[setup] ref wav: {len(REF_AUDIO_BYTES):,} bytes / ref text: {REF_TEXT[:50]}...")


def _make_ref() -> ReferenceAudio:
    return ReferenceAudio(audio=REF_AUDIO_BYTES, text=REF_TEXT)


def synth(name: str, text: str, *, model: str = "s2-pro", latency: str = "normal",
          stream: bool = False, references=None, no_ref: bool = False) -> dict:
    """Single TTS call with timing + save output.

    Returns dict: {name, text, bytes_estimate, elapsed_ms, audio_bytes, output_path, error}
    """
    s = Session(API_KEY)
    text_bytes = len(text.encode("utf-8"))
    refs = [] if no_ref else (references if references is not None else [_make_ref()])

    req_kwargs = dict(
        text=text,
        references=refs,
        format="wav",
        latency=latency,
    )
    req = TTSRequest(**req_kwargs)

    t0 = time.perf_counter()
    audio_bytes = b""
    first_chunk_ms = None
    chunk_count = 0
    error = None
    try:
        for chunk in s.tts(req, backend=model):
            if first_chunk_ms is None:
                first_chunk_ms = (time.perf_counter() - t0) * 1000
            audio_bytes += chunk
            chunk_count += 1
            if not stream:
                continue
        elapsed_ms = (time.perf_counter() - t0) * 1000
    except HttpCodeErr as e:
        elapsed_ms = (time.perf_counter() - t0) * 1000
        error = f"HttpCodeErr({e.status}): {e}"
    except Exception as e:
        elapsed_ms = (time.perf_counter() - t0) * 1000
        error = f"{type(e).__name__}: {e}"

    out_path = OUT_DIR / f"{name}.wav"
    if audio_bytes and not error:
        out_path.write_bytes(audio_bytes)

    result = {
        "name": name,
        "text": text,
        "bytes_estimate": text_bytes,
        "first_chunk_ms": round(first_chunk_ms, 1) if first_chunk_ms else None,
        "elapsed_ms": round(elapsed_ms, 1),
        "audio_bytes_out": len(audio_bytes),
        "chunk_count": chunk_count,
        "output_path": str(out_path.relative_to(ROOT)) if (audio_bytes and not error) else None,
        "error": error,
    }
    return result


def main():
    s = Session(API_KEY)
    pkg0 = s.get_package()
    cred0 = s.get_api_credit()
    print(f"\n[balance@start] credit=${cred0.credit} package=Plus {pkg0.balance}/{pkg0.total} bytes (finished_at={pkg0.finished_at})")

    results = []

    # ─── T1 基础 zero-shot ──────────────────────────────────────────────
    print("\n=== T1 基础 zero-shot (Mai reference + 日语 target) ===")
    results.append(synth("T1_basic_ja",
        "こんにちは、お元気ですか?"))
    print(json.dumps(results[-1], ensure_ascii=False, indent=2))

    # ─── T2 emotion markers (5 子项) ────────────────────────────────────
    print("\n=== T2.1 single marker [sarcastic] ===")
    results.append(synth("T2_1_single_marker",
        "[sarcastic]ま、いいか。"))
    print(json.dumps(results[-1], ensure_ascii=False, indent=2))

    print("\n=== T2.2 multi marker cross-sentence ===")
    results.append(synth("T2_2_multi_marker",
        "[soft chuckle]うん、まあね。[gentle]気にしないで。"))
    print(json.dumps(results[-1], ensure_ascii=False, indent=2))

    print("\n=== T2.3 nested (paired tag form, predict NOT supported) ===")
    results.append(synth("T2_3_nested",
        "[sarcastic]やれやれ[/sarcastic]、君もか。"))
    print(json.dumps(results[-1], ensure_ascii=False, indent=2))

    print("\n=== T2.4 mid-sentence inline marker ===")
    results.append(synth("T2_4_mid_sentence",
        "ね、ねえ[whisper]ちょっと聞いて。"))
    print(json.dumps(results[-1], ensure_ascii=False, indent=2))

    print("\n=== T2.5 cross-lang Mai persona-ish ===")
    results.append(synth("T2_5_persona_mai",
        "[teasing]ま、いい子だね。[soft chuckle]"))
    print(json.dumps(results[-1], ensure_ascii=False, indent=2))

    # ─── T3 stream vs non-stream(同 text 不同 latency) ─────────────────
    print("\n=== T3.1 latency=normal ===")
    results.append(synth("T3_1_latency_normal",
        "今日は天気がいいですね。少し散歩でもしようかな。",
        latency="normal"))
    print(json.dumps(results[-1], ensure_ascii=False, indent=2))

    print("\n=== T3.2 latency=balanced ===")
    results.append(synth("T3_2_latency_balanced",
        "今日は天気がいいですね。少し散歩でもしようかな。",
        latency="balanced"))
    print(json.dumps(results[-1], ensure_ascii=False, indent=2))

    # ─── T4 错误码 ──────────────────────────────────────────────────────
    print("\n=== T4.1 bad reference (zero bytes audio) ===")
    bad_ref = ReferenceAudio(audio=b"", text="")
    results.append(synth("T4_1_bad_ref", "テスト。", references=[bad_ref]))
    print(json.dumps(results[-1], ensure_ascii=False, indent=2))

    print("\n=== T4.2 bad API key ===")
    s_bad = Session("invalid_key_xxxxxxxxxxxxxxxxxx")
    req_bad = TTSRequest(text="テスト。", references=[_make_ref()], format="wav")
    t0 = time.perf_counter()
    err = None
    try:
        for _ in s_bad.tts(req_bad, backend="s2-pro"):
            pass
    except HttpCodeErr as e:
        err = f"HttpCodeErr({e.status}): {e}"
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
    elapsed = round((time.perf_counter() - t0) * 1000, 1)
    print(json.dumps({"name": "T4_2_bad_key", "error": err, "elapsed_ms": elapsed}, ensure_ascii=False, indent=2))
    results.append({"name": "T4_2_bad_key", "error": err, "elapsed_ms": elapsed})

    print("\n=== T4.3 no reference + no reference_id (fully missing) ===")
    results.append(synth("T4_3_no_ref",
        "テスト。", no_ref=True))
    print(json.dumps(results[-1], ensure_ascii=False, indent=2))

    # ─── T5 Cost 实测(对比 byte 估算) ──────────────────────────────────
    print("\n=== T5 cost 实测 (100 日语 char ~300 bytes) ===")
    long_ja = "麻衣はそういう人だから。少しは気を遣ってあげなさい。あ、それで、昨日言ってたあれ、どうだった?私はちょっと心配だったのよ。"
    print(f"[T5] text len={len(long_ja)} char / utf8 bytes={len(long_ja.encode('utf-8'))}")
    results.append(synth("T5_cost_100ja", long_ja))
    print(json.dumps(results[-1], ensure_ascii=False, indent=2))

    # ─── T6 references[] audio 格式(stereo WAV 已成功多次,这里测 mono/sample_rate 影响) ──
    print("\n=== T6 references[] 多 sample 提质量(同一 ref 重复)===")
    multi_refs = [_make_ref(), _make_ref()]
    results.append(synth("T6_multi_ref",
        "あなたはこの話、信じる?", references=multi_refs))
    print(json.dumps(results[-1], ensure_ascii=False, indent=2))

    # ─── 末尾 balance check ─────────────────────────────────────────────
    pkg1 = s.get_package()
    cred1 = s.get_api_credit()
    print(f"\n[balance@end] credit=${cred1.credit} package=Plus {pkg1.balance}/{pkg1.total} bytes")
    print(f"[delta] credit_delta=${cred0.credit - cred1.credit}  package_delta={pkg0.balance - pkg1.balance} bytes")

    # ─── 汇总 ───────────────────────────────────────────────────────────
    summary_path = OUT_DIR / "summary.json"
    summary_path.write_text(json.dumps({
        "balance_start": {"credit": str(cred0.credit), "package": {"total": pkg0.total, "balance": pkg0.balance}},
        "balance_end":   {"credit": str(cred1.credit), "package": {"total": pkg1.total, "balance": pkg1.balance}},
        "results": results,
    }, ensure_ascii=False, indent=2))
    print(f"\n[summary] written to {summary_path.relative_to(ROOT)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
