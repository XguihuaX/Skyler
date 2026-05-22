"""INV-12 Stage 2 · backend/routes/fish_config.py + voice_config L1 merge logic 测试。

per PM Q5 lock · 3 层 fallback semantic + 配对约束。

策略:用 FastAPI TestClient · 现 momoos.db · cid=4 凝光 dogfood(voice_model 空,
不破 cid=101 INV-9 §7 a6af74b lock)+ cleanup user_*  字段;synthesize 走
get_tts_engine mock 避免真 Fish API cost。

跑法:
    .venv/bin/python tests/test_fish_config.py
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import struct
import sys
import wave
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from backend.main import app  # noqa: E402
from backend.tts.voice_config import VoiceConfig, parse_voice_config  # noqa: E402
from sqlalchemy import text as sql_text  # noqa: E402

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []
client = TestClient(app)

TEST_CID = 4  # 凝光 voice_model 空 · safe dogfood


def check(name: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))


def _make_minimal_wav(duration_sec: float = 0.3, sr: int = 8000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        n = int(sr * duration_sec)
        w.writeframes(struct.pack("<%dh" % n, *([0] * n)))
    return buf.getvalue()


def _cleanup_test_cid() -> None:
    """Reset cid=TEST_CID voice_model + del user audio files。"""
    from backend.database import engine as db_engine

    async def _run():
        async with db_engine.begin() as conn:
            row = (await conn.execute(sql_text(
                "SELECT voice_model FROM characters WHERE id = :cid"
            ), {"cid": TEST_CID})).first()
            if row and row[0]:
                try:
                    vm = json.loads(row[0])
                except (json.JSONDecodeError, TypeError):
                    vm = {}
                # 删 user audio file(if 存在)
                u_audio = vm.get("user_reference_audio_path")
                if isinstance(u_audio, str) and u_audio.strip():
                    p = Path(__file__).resolve().parent.parent / u_audio
                    try:
                        if p.exists():
                            p.unlink()
                    except OSError:
                        pass
            # 重置 voice_model 为空 string(原 dogfood 状态)
            await conn.execute(sql_text(
                "UPDATE characters SET voice_model = '' WHERE id = :cid"
            ), {"cid": TEST_CID})

    asyncio.run(_run())


# ─────────────────────────────────────────────────────────────────────
# 1. VoiceConfig dataclass 4 新字段 + parse backward compat
# ─────────────────────────────────────────────────────────────────────
def test_voice_config_new_user_fields_defaults():
    print("\n[1.1] VoiceConfig 4 新 user_* 字段默认值")
    c = VoiceConfig(provider="cosyvoice", voice="longyumi_v3")
    check("user_reference_audio_path 默 None", c.user_reference_audio_path is None)
    check("user_reference_text 默 None", c.user_reference_text is None)
    check("user_fish_temperature 默 None", c.user_fish_temperature is None)
    check("user_fish_top_p 默 None", c.user_fish_top_p is None)


def test_parse_backward_compat_no_user_fields():
    """老 voice_model JSON(无 user_* 字段)parse 不破。"""
    print("\n[1.2] parse_voice_config 老 voice_model(无 user_*)backward compat")
    default = VoiceConfig(provider="cosyvoice", voice="longyumi_v3")
    legacy_json = json.dumps({
        "provider": "fish", "voice": "mai5min_0033", "model": "s2-pro",
        "tts_language": "ja",
        "reference_audio_path": "tts/fish/参考音频/mai/mai5min_0033.wav",
        "reference_text": "自分の方が...",
        "fish_temperature": 0.2,
    })
    cfg = parse_voice_config(legacy_json, default)
    check("provider='fish' 解析", cfg.provider == "fish")
    check("fish_temperature L2 default = 0.2", cfg.fish_temperature == 0.2)
    check("user_reference_audio_path None", cfg.user_reference_audio_path is None)
    check("user_fish_temperature None", cfg.user_fish_temperature is None)


def test_parse_with_user_override_fields():
    print("\n[1.3] parse_voice_config 含 user_override · 4 字段 parse OK")
    default = VoiceConfig(provider="cosyvoice", voice="longyumi_v3")
    vm_json = json.dumps({
        "provider": "fish", "voice": "mai5min_0033", "model": "s2-pro",
        "reference_audio_path": "tts/fish/参考音频/mai/mai5min_0033.wav",
        "reference_text": "default text",
        "fish_temperature": 0.2,
        "user_reference_audio_path": "backend/static/fish_references/4/abc.wav",
        "user_reference_text": "user override text",
        "user_fish_temperature": 0.5,
        "user_fish_top_p": 0.8,
    })
    cfg = parse_voice_config(vm_json, default)
    check("user_reference_audio_path 解析",
          cfg.user_reference_audio_path == "backend/static/fish_references/4/abc.wav")
    check("user_reference_text 解析", cfg.user_reference_text == "user override text")
    check("user_fish_temperature 解析", cfg.user_fish_temperature == 0.5)
    check("user_fish_top_p 解析", cfg.user_fish_top_p == 0.8)


# ─────────────────────────────────────────────────────────────────────
# 2. FishTTS merge logic · 3 层 fallback + 配对约束
# ─────────────────────────────────────────────────────────────────────
def _make_fish_voice_config(
    *, user_audio=None, user_text=None, user_temp=None, user_top_p=None,
    default_audio="tts/fish/参考音频/mai/mai5min_0033.wav",
    default_text="default 文本",
    default_temp=0.2, default_top_p=None,
) -> VoiceConfig:
    return VoiceConfig(
        provider="fish", voice="mai5min_0033", model="s2-pro",
        tts_language="ja",
        reference_audio_path=default_audio,
        reference_text=default_text,
        fish_temperature=default_temp,
        fish_top_p=default_top_p,
        user_reference_audio_path=user_audio,
        user_reference_text=user_text,
        user_fish_temperature=user_temp,
        user_fish_top_p=user_top_p,
    )


def test_fish_merge_l2_default_only():
    print("\n[2.1] FishTTS merge L2 default only(无 user_override · cid=101 现状)")
    from backend.tts.fish import FishTTS
    cfg = _make_fish_voice_config()
    engine = FishTTS(voice_config=cfg)
    check("_ref_text == L2 default", engine._ref_text == "default 文本")
    check("temperature L2 = 0.2", engine.temperature == 0.2)
    check("top_p L2 None", engine.top_p is None)


def test_fish_merge_l1_user_override_paired():
    print("\n[2.2] FishTTS merge L1 user_override · audio+text paired 完整 → L1 生效")
    from backend.tts.fish import FishTTS
    cfg = _make_fish_voice_config(
        user_audio="tts/fish/参考音频/mai/mai5min_0033.wav",  # 用同款现存 file
        user_text="user 上传的 reference text",
        user_temp=0.5,
    )
    engine = FishTTS(voice_config=cfg)
    check("_ref_text == L1 user_text",
          engine._ref_text == "user 上传的 reference text")
    check("temperature L1 = 0.5", engine.temperature == 0.5)
    check("top_p 未设 L1 → L2 default None", engine.top_p is None)


def test_fish_merge_pairing_violation_audio_only():
    print("\n[2.3] 配对约束违反 · 只 user_audio 无 user_text → 全回退 L2")
    from backend.tts.fish import FishTTS
    cfg = _make_fish_voice_config(
        user_audio="tts/fish/参考音频/mai/mai5min_0033.wav",
        # user_text=None → 配对违反
    )
    engine = FishTTS(voice_config=cfg)
    check("_ref_text 回退 L2 default", engine._ref_text == "default 文本")


def test_fish_merge_pairing_violation_text_only():
    print("\n[2.4] 配对约束违反 · 只 user_text 无 user_audio → 全回退 L2")
    from backend.tts.fish import FishTTS
    cfg = _make_fish_voice_config(
        user_text="孤立 user text 无 audio",
    )
    engine = FishTTS(voice_config=cfg)
    check("_ref_text 回退 L2 default", engine._ref_text == "default 文本")


def test_fish_merge_independent_temperature():
    print("\n[2.5] 独立参数 · 仅 user_fish_temperature 设 + audio/text 不配 → "
          "temp L1 但 audio/text L2 default")
    from backend.tts.fish import FishTTS
    cfg = _make_fish_voice_config(
        user_temp=0.7,  # 独立设
        # user_audio / user_text 不设 → 配对自然满足(都 None)→ ref 走 L2
    )
    engine = FishTTS(voice_config=cfg)
    check("temperature L1 = 0.7", engine.temperature == 0.7)
    check("ref 走 L2 default", engine._ref_text == "default 文本")


# ─────────────────────────────────────────────────────────────────────
# 3. API endpoints · 404 + cleanup + GET 空配置
# ─────────────────────────────────────────────────────────────────────
def test_404_unknown_character():
    print("\n[3.1] GET /api/characters/99999/fish_config → 404")
    resp = client.get("/api/characters/99999/fish_config")
    check("404 unknown cid", resp.status_code == 404)


def test_get_empty_config():
    _cleanup_test_cid()
    print("\n[3.2] GET cid=4 凝光 voice_model 空 · effective 全 None")
    resp = client.get(f"/api/characters/{TEST_CID}/fish_config")
    check("status 200", resp.status_code == 200)
    body = resp.json() if resp.status_code == 200 else {}
    eff = body.get("effective", {})
    check("effective.reference_audio_path None", eff.get("reference_audio_path") is None)
    check("effective.reference_text None", eff.get("reference_text") is None)
    check("user_override_active False", body.get("user_override_active") is False)


# ─────────────────────────────────────────────────────────────────────
# 4. POST upload · happy + 配对约束 + 415/413
# ─────────────────────────────────────────────────────────────────────
def test_post_upload_happy():
    _cleanup_test_cid()
    print("\n[4.1] POST upload happy · voice_model JSON 写回 user_* 4 字段")
    wav = _make_minimal_wav(0.3)
    resp = client.post(
        f"/api/characters/{TEST_CID}/fish_config",
        files={"file": ("test.wav", wav, "audio/wav")},
        data={
            "reference_text": "test reference text",
            "fish_temperature": "0.3",
            "fish_top_p": "0.7",
        },
    )
    check("status 200", resp.status_code == 200,
          detail=f"got {resp.status_code} body={resp.text[:200]}")
    if resp.status_code != 200:
        return
    body = resp.json()
    check("user_override.user_reference_text == 'test reference text'",
          body["user_override"]["user_reference_text"] == "test reference text")
    check("user_override.user_fish_temperature == 0.3",
          body["user_override"]["user_fish_temperature"] == 0.3)
    check("user_override_active == True", body["user_override_active"] is True)
    # effective audio path 来自 user_override
    eff_audio = body["effective"]["reference_audio_path"]
    check("effective.reference_audio_path 在 fish_references mount 下",
          eff_audio and "fish_references" in eff_audio)


def test_post_missing_required_field():
    print("\n[4.2] POST 缺 reference_text → 422")
    wav = _make_minimal_wav(0.3)
    resp = client.post(
        f"/api/characters/{TEST_CID}/fish_config",
        files={"file": ("test.wav", wav, "audio/wav")},
        data={"fish_temperature": "0.3", "fish_top_p": "0.7"},
        # missing reference_text
    )
    check("422 缺 reference_text", resp.status_code == 422,
          detail=f"got {resp.status_code}")


def test_post_first_time_no_file():
    _cleanup_test_cid()
    print("\n[4.3] POST 首次配置无 file → 400(必须上传)")
    resp = client.post(
        f"/api/characters/{TEST_CID}/fish_config",
        data={
            "reference_text": "x",
            "fish_temperature": "0.3",
            "fish_top_p": "0.7",
        },
    )
    check("400 首次无 file", resp.status_code == 400,
          detail=f"got {resp.status_code}")


def test_post_415_invalid_format():
    print("\n[4.4] POST 非 audio 格式 → 415")
    resp = client.post(
        f"/api/characters/{TEST_CID}/fish_config",
        files={"file": ("bad.txt", b"hello", "text/plain")},
        data={
            "reference_text": "x", "fish_temperature": "0.3", "fish_top_p": "0.7",
        },
    )
    check("415 text/plain", resp.status_code == 415,
          detail=f"got {resp.status_code}")


def test_post_413_too_large():
    print("\n[4.5] POST > 5MB → 413")
    big = b"\x00" * (5 * 1024 * 1024 + 100)
    resp = client.post(
        f"/api/characters/{TEST_CID}/fish_config",
        files={"file": ("big.wav", big, "audio/wav")},
        data={
            "reference_text": "x", "fish_temperature": "0.3", "fish_top_p": "0.7",
        },
    )
    check("413 > 5MB", resp.status_code == 413, detail=f"got {resp.status_code}")


# ─────────────────────────────────────────────────────────────────────
# 5. DELETE · 4 user_* 清后 effective fallback L2
# ─────────────────────────────────────────────────────────────────────
def test_delete_clears_user_override():
    """先 POST upload 占 user_*,再 DELETE 验全清 + effective fallback L2。"""
    _cleanup_test_cid()
    print("\n[5] DELETE · 清 4 user_* 后 effective fallback L2")
    wav = _make_minimal_wav(0.3)
    resp = client.post(
        f"/api/characters/{TEST_CID}/fish_config",
        files={"file": ("test.wav", wav, "audio/wav")},
        data={
            "reference_text": "test", "fish_temperature": "0.5", "fish_top_p": "0.9",
        },
    )
    assert resp.status_code == 200, f"setup POST failed: {resp.text}"

    # DELETE
    resp = client.delete(f"/api/characters/{TEST_CID}/fish_config")
    check("DELETE status 200", resp.status_code == 200,
          detail=f"got {resp.status_code}")
    body = resp.json()
    check("cleared_keys 含 4 user_*",
          set(body["cleared_keys"]) == set([
              "user_reference_audio_path", "user_reference_text",
              "user_fish_temperature", "user_fish_top_p",
          ]),
          detail=f"got {body['cleared_keys']}")
    check("effective.fish_temperature None(cid=4 L2 default 空)",
          body["effective"]["fish_temperature"] is None)
    check("user_override_active False", body["user_override_active"] is False)


# ─────────────────────────────────────────────────────────────────────
# 6. synthesize endpoint · 走 mock 避免真 Fish API call
# ─────────────────────────────────────────────────────────────────────
def test_synthesize_text_empty():
    print("\n[6.1] POST synthesize text 空 → 400")
    resp = client.post(
        f"/api/characters/{TEST_CID}/fish_config/synthesize",
        json={"text": ""},
    )
    check("空 text → 400", resp.status_code == 400)


def test_synthesize_no_voice_model():
    _cleanup_test_cid()
    print("\n[6.2] POST synthesize cid=4 voice_model 空 → 400")
    resp = client.post(
        f"/api/characters/{TEST_CID}/fish_config/synthesize",
        json={"text": "テスト"},
    )
    check("voice_model 空 → 400", resp.status_code == 400,
          detail=f"got {resp.status_code}")


def test_synthesize_non_fish_provider():
    """cosyvoice provider 走 preview endpoint → 400(only fish supported)。"""
    _cleanup_test_cid()
    print("\n[6.3] POST synthesize cid=4 设 cosyvoice voice_model → 400 non-fish")
    from backend.database import engine as db_engine

    async def _setup():
        async with db_engine.begin() as conn:
            cosyvoice_json = json.dumps({
                "provider": "cosyvoice", "voice": "longyumi_v3",
                "instruct_supported": False,
            })
            await conn.execute(sql_text(
                "UPDATE characters SET voice_model = :vm WHERE id = :cid"
            ), {"vm": cosyvoice_json, "cid": TEST_CID})
    asyncio.run(_setup())

    resp = client.post(
        f"/api/characters/{TEST_CID}/fish_config/synthesize",
        json={"text": "测试"},
    )
    check("non-fish 400", resp.status_code == 400,
          detail=f"got {resp.status_code} body={resp.text[:100]}")

    _cleanup_test_cid()


# ─────────────────────────────────────────────────────────────────────
# main
# ─────────────────────────────────────────────────────────────────────
def main():
    try:
        test_voice_config_new_user_fields_defaults()
        test_parse_backward_compat_no_user_fields()
        test_parse_with_user_override_fields()
        test_fish_merge_l2_default_only()
        test_fish_merge_l1_user_override_paired()
        test_fish_merge_pairing_violation_audio_only()
        test_fish_merge_pairing_violation_text_only()
        test_fish_merge_independent_temperature()
        test_404_unknown_character()
        test_get_empty_config()
        test_post_upload_happy()
        test_post_missing_required_field()
        test_post_first_time_no_file()
        test_post_415_invalid_format()
        test_post_413_too_large()
        test_delete_clears_user_override()
        test_synthesize_text_empty()
        test_synthesize_no_voice_model()
        test_synthesize_non_fish_provider()
    finally:
        _cleanup_test_cid()

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
