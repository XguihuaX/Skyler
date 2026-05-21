"""INV-9 §2+§3+§4 unit test · TTS 抽象层 + Fish provider。

覆盖:
  - VoiceConfig 4 新字段(tts_language / reference_audio_path /
    reference_text / fish_latency)默认值 + 显式赋值
  - parse_voice_config fish 分支 raise(缺 reference_audio_path / reference_text)
  - parse_voice_config fish 分支 OK(全字段提供)
  - parse_voice_config 其它 provider(cosyvoice / edge / sovits)backward compat
  - _build_engine 工厂按 cfg.provider 分流(cosyvoice / fish;不 boot 真 SDK)

不覆盖(留独立脚本):
  - FishTTS 真 API 调用 → scripts/fish_provider_smoke.py 直调
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.tts.voice_config import VoiceConfig, parse_voice_config  # noqa: E402

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))


# ----- default for parse_voice_config (yaml fallback baseline) -----
DEFAULT = VoiceConfig(
    provider="cosyvoice",
    voice="longyumi_v3",
    instruct_supported=False,
)


# ---------------------------------------------------------------------------
# 1. VoiceConfig dataclass 4 新字段
# ---------------------------------------------------------------------------
def test_voice_config_new_fields_defaults():
    print("\n[1.1] VoiceConfig 4 新字段默认值")
    cfg = VoiceConfig(provider="cosyvoice", voice="longyumi_v3")
    check("tts_language 默认 'zh'", cfg.tts_language == "zh")
    check("reference_audio_path 默认 None", cfg.reference_audio_path is None)
    check("reference_text 默认 None", cfg.reference_text is None)
    check("fish_latency 默认 'balanced'", cfg.fish_latency == "balanced")


def test_voice_config_explicit_fields():
    print("\n[1.2] VoiceConfig 显式赋值 4 字段")
    cfg = VoiceConfig(
        provider="fish",
        voice="mai5min_0033",
        model="s2-pro",
        tts_language="ja",
        reference_audio_path="tts/fish/参考音频/mai/mai5min_0033.wav",
        reference_text="自分の方が可愛いって自覚あるくせに...",
        fish_latency="balanced",
    )
    check("tts_language='ja'", cfg.tts_language == "ja")
    check("reference_audio_path 写入",
          cfg.reference_audio_path == "tts/fish/参考音频/mai/mai5min_0033.wav")
    check("reference_text 写入", cfg.reference_text.startswith("自分"))
    check("fish_latency='balanced'", cfg.fish_latency == "balanced")


# ---------------------------------------------------------------------------
# 2. parse_voice_config · fish 分支 raise(缺 ref 字段)
# ---------------------------------------------------------------------------
def test_parse_fish_missing_ref_audio_path_raises():
    print("\n[2.1] parse fish 缺 reference_audio_path → ValueError")
    bad = json.dumps({
        "provider": "fish",
        "voice": "mai",
        "reference_text": "self transcript",
    })
    raised = False
    try:
        parse_voice_config(bad, DEFAULT)
    except ValueError as exc:
        raised = "reference_audio_path" in str(exc)
    check("raise ValueError 含 'reference_audio_path'", raised)


def test_parse_fish_missing_ref_text_raises():
    print("\n[2.2] parse fish 缺 reference_text → ValueError")
    bad = json.dumps({
        "provider": "fish",
        "voice": "mai",
        "reference_audio_path": "tts/fish/参考音频/mai/mai5min_0033.wav",
    })
    raised = False
    try:
        parse_voice_config(bad, DEFAULT)
    except ValueError as exc:
        raised = "reference_text" in str(exc)
    check("raise ValueError 含 'reference_text'", raised)


def test_parse_fish_empty_ref_audio_path_raises():
    print("\n[2.3] parse fish reference_audio_path 空串 → ValueError")
    bad = json.dumps({
        "provider": "fish",
        "voice": "mai",
        "reference_audio_path": "  ",
        "reference_text": "x",
    })
    raised = False
    try:
        parse_voice_config(bad, DEFAULT)
    except ValueError:
        raised = True
    check("raise ValueError", raised)


def test_parse_fish_empty_ref_text_raises():
    print("\n[2.4] parse fish reference_text 空串 → ValueError")
    bad = json.dumps({
        "provider": "fish",
        "voice": "mai",
        "reference_audio_path": "tts/fish/参考音频/mai/mai5min_0033.wav",
        "reference_text": "   ",
    })
    raised = False
    try:
        parse_voice_config(bad, DEFAULT)
    except ValueError:
        raised = True
    check("raise ValueError", raised)


# ---------------------------------------------------------------------------
# 3. parse_voice_config · fish 分支 OK(全字段)
# ---------------------------------------------------------------------------
def test_parse_fish_full_ok():
    print("\n[3] parse fish 全字段 → 正常 VoiceConfig")
    good = json.dumps({
        "provider": "fish",
        "voice": "mai5min_0033",
        "model": "s2-pro",
        "tts_language": "ja",
        "reference_audio_path": "tts/fish/参考音频/mai/mai5min_0033.wav",
        "reference_text": "自分の方が可愛いって自覚あるくせに、別の誰か...",
        "fish_latency": "balanced",
    })
    cfg = parse_voice_config(good, DEFAULT)
    check("provider == 'fish'", cfg.provider == "fish")
    check("voice == 'mai5min_0033'", cfg.voice == "mai5min_0033")
    check("model == 's2-pro'", cfg.model == "s2-pro")
    check("tts_language == 'ja'", cfg.tts_language == "ja")
    check("reference_audio_path 写入",
          cfg.reference_audio_path == "tts/fish/参考音频/mai/mai5min_0033.wav")
    check("reference_text 含日语 prefix",
          cfg.reference_text.startswith("自分"))
    check("fish_latency == 'balanced'", cfg.fish_latency == "balanced")


def test_parse_fish_latency_default_when_omitted():
    print("\n[3.1] parse fish 省略 fish_latency → 默 'balanced'")
    good = json.dumps({
        "provider": "fish",
        "voice": "mai",
        "reference_audio_path": "tts/fish/参考音频/mai/mai5min_0033.wav",
        "reference_text": "x",
    })
    cfg = parse_voice_config(good, DEFAULT)
    check("fish_latency 默 'balanced'", cfg.fish_latency == "balanced")


# ---------------------------------------------------------------------------
# 4. 其它 provider backward compat
# ---------------------------------------------------------------------------
def test_parse_cosyvoice_unchanged():
    print("\n[4.1] parse cosyvoice · 现 cid=1 Mai voice_model · backward compat")
    cid1 = json.dumps({
        "provider": "cosyvoice",
        "voice": "longyumi_v3",
        "instruct_supported": False,
        "tts_language": "zh",
    })
    cfg = parse_voice_config(cid1, DEFAULT)
    check("provider 'cosyvoice'", cfg.provider == "cosyvoice")
    check("voice 'longyumi_v3'", cfg.voice == "longyumi_v3")
    check("tts_language 'zh'", cfg.tts_language == "zh")
    check("reference_audio_path None(非 fish)",
          cfg.reference_audio_path is None)


def test_parse_cosyvoice_v35_plus_unchanged():
    print("\n[4.2] parse cid=2 八重神子 · cosyvoice-v3.5-plus · backward compat")
    cid2 = json.dumps({
        "provider": "cosyvoice",
        "model": "cosyvoice-v3.5-plus",
        "voice": "cosyvoice-v3.5-plus-bailian-xxx",
        "instruct_supported": True,
        "ssml_supported": True,  # 死字段,backward compat
    })
    cfg = parse_voice_config(cid2, DEFAULT)
    check("provider 'cosyvoice'", cfg.provider == "cosyvoice")
    check("model 'cosyvoice-v3.5-plus'",
          cfg.model == "cosyvoice-v3.5-plus")
    check("instruct_supported True", cfg.instruct_supported is True)


def test_parse_empty_returns_default():
    print("\n[4.3] parse 空串 / None → default backward compat")
    check("None → default", parse_voice_config(None, DEFAULT) is DEFAULT)
    check("'' → default", parse_voice_config("", DEFAULT) is DEFAULT)
    check("'   ' → default",
          parse_voice_config("   ", DEFAULT) is DEFAULT)


def test_parse_invalid_json_returns_default():
    print("\n[4.4] parse 非法 JSON → default(不抛)")
    cfg = parse_voice_config("not-json", DEFAULT)
    check("非法 JSON 不抛 + 返 default", cfg is DEFAULT)


# ---------------------------------------------------------------------------
# 5. _build_engine 工厂分流(per provider 返不同 engine 类)
# ---------------------------------------------------------------------------
def test_build_engine_cosyvoice():
    print("\n[5.1] _build_engine cosyvoice → CosyVoiceTTS 实例")
    from backend.tts import _build_engine
    cfg_json = json.dumps({
        "provider": "cosyvoice",
        "voice": "longyumi_v3",
        "instruct_supported": False,
    })
    engine = _build_engine(cfg_json)
    cls = type(engine).__name__
    check(f"engine class = CosyVoiceTTS(got {cls})",
          cls == "CosyVoiceTTS")


def test_build_engine_fish():
    print("\n[5.2] _build_engine fish → FishTTS 实例(全字段)")
    from backend.tts import _build_engine
    cfg_json = json.dumps({
        "provider": "fish",
        "voice": "mai5min_0033",
        "model": "s2-pro",
        "tts_language": "ja",
        "reference_audio_path": "tts/fish/参考音频/mai/mai5min_0033.wav",
        "reference_text": "自分の方が可愛いって自覚あるくせに、別の誰かのことを可愛いとか言ってる女がサクタは好きなの?",
        "fish_latency": "balanced",
    })
    engine = _build_engine(cfg_json)
    cls = type(engine).__name__
    check(f"engine class = FishTTS(got {cls})", cls == "FishTTS")
    # 验证 cached 字段
    check("FishTTS.backend == 's2-pro'", getattr(engine, "backend", None) == "s2-pro")
    check("FishTTS.latency == 'balanced'",
          getattr(engine, "latency", None) == "balanced")
    check("FishTTS._ref_audio_bytes 非空",
          len(getattr(engine, "_ref_audio_bytes", b"")) > 0)


def test_build_engine_fish_missing_ref_raises():
    print("\n[5.3] _build_engine fish 缺 ref → ValueError(parse 阶段 raise)")
    from backend.tts import _build_engine
    bad = json.dumps({
        "provider": "fish",
        "voice": "mai",
        "reference_text": "x",
        # missing reference_audio_path
    })
    raised = False
    try:
        _build_engine(bad)
    except ValueError:
        raised = True
    check("缺 ref_audio_path → ValueError 抛", raised)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main():
    test_voice_config_new_fields_defaults()
    test_voice_config_explicit_fields()
    test_parse_fish_missing_ref_audio_path_raises()
    test_parse_fish_missing_ref_text_raises()
    test_parse_fish_empty_ref_audio_path_raises()
    test_parse_fish_empty_ref_text_raises()
    test_parse_fish_full_ok()
    test_parse_fish_latency_default_when_omitted()
    test_parse_cosyvoice_unchanged()
    test_parse_cosyvoice_v35_plus_unchanged()
    test_parse_empty_returns_default()
    test_parse_invalid_json_returns_default()
    test_build_engine_cosyvoice()
    test_build_engine_fish()
    test_build_engine_fish_missing_ref_raises()

    total = len(results)
    passed = sum(1 for _, ok in results if ok)
    print(f"\n{'='*60}")
    print(f"Results: {passed}/{total} passed")
    if passed < total:
        print("FAILED:", ", ".join(n for n, ok in results if not ok))
        sys.exit(1)
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
