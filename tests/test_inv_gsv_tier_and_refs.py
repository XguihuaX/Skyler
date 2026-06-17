"""INV (2026-06-11) · GSV thin reference + tts_models_cache + list_refs /
upload_ref_local + emotion_coverage 集成测试。

跑法:
    cd <repo>
    .venv/bin/python tests/test_inv_gsv_tier_and_refs.py

依赖真实 momoos.db(已跑过 inv_tts_models_table_and_seed)+ tts/gsv/mai_v4/
实际 16 .lab。失败 PRINT 红 + sys.exit(1)。

覆盖:
  T1 三 tier: DB voice_model 完整 spread(模拟旧数据)→ DB 第一档赢
  T2 三 tier: thin reference(模拟阶段 ② 迁移后)→ tts_models_cache spec 第二档赢
  T3 三 tier: thin reference + cache 清空(模拟 cache 加载失败)→ tts_models.json fallback
  T4 emotion 集合 = lab_cache.keys() 动态派生(集合外 fallback default)
  T5 list_refs / upload_ref_local 模块级 helper
  T6 cache-fail → json-fallback + WARNING(_FELL_BACK_TO_JSON 翻 True)
"""
from __future__ import annotations

import json
import os
import sys
import shutil
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"

results: list[tuple[str, bool]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    tag = PASS if cond else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, cond))


def test_three_tier_cache_loaded():
    print("\n[T1+T2 · 三 tier · cache loaded]")
    from backend.tts.tts_models_cache import reload_gsv_models_cache
    from backend.tts.gsv import GSVTTS
    from backend.tts.voice_config import VoiceConfig

    reload_gsv_models_cache()
    cfg = VoiceConfig(provider="gsv", voice="", tts_language="ja")

    # T1 · DB spread 完整 → 字段以 DB 副本赢(per-char override 语义)
    spread_vm = json.dumps({
        "provider": "gsv",
        "model": "mai_v4",
        "tts_language": "ja",
        "server_url": "http://10.0.0.1:9880",   # 故意改 IP · 跟 _DEFAULT 不同
        "gpt_weights": "spread/GPT.ckpt",
        "sovits_weights": "spread/SoVITS.pth",
        "emotion_bank_dir": "tts/gsv/mai_v4",
        "remote_emotion_bank_dir": "/spread/bank/",
        "default_emotion": "温柔",
        "inference_params": {"top_k": 99},
    })
    e1 = GSVTTS(voice_config=cfg, voice_model_json=spread_vm)
    check("T1 server_url DB 赢", e1.server_url == "http://10.0.0.1:9880")
    check("T1 gpt_weights DB 赢", e1.gpt_weights == "spread/GPT.ckpt")
    check("T1 remote_emotion_bank DB 赢", e1.remote_emotion_bank == "/spread/bank/")
    check("T1 default_emotion DB 赢", e1.default_emotion == "温柔")
    check("T1 inference_params DB top_k 赢", e1.inference_params.get("top_k") == 99)
    # spec 提供的字段未覆盖时仍透传(merge)
    check("T1 inference_params spec 补足", e1.inference_params.get("temperature") == 1.0)

    # T2 · thin reference(模拟迁移后)→ spec 赢
    thin_vm = json.dumps({"provider": "gsv", "model": "mai_v4", "tts_language": "ja"})
    e2 = GSVTTS(voice_config=cfg, voice_model_json=thin_vm)
    check("T2 server_url spec→default(无全局)", "106.75" in e2.server_url)
    check("T2 gpt_weights spec 赢", "mai_v4-e15" in e2.gpt_weights)
    check("T2 sovits_weights spec 赢", "mai_v4_e5_s1380" in e2.sovits_weights)
    # 2026-06-14 · wav_remote_dir 已迁本地(D:/.../reference_audio/mai_v4/)·
    # 期望从旧 /mai_emotion_bank/ 更到当前真值 /mai_v4/(见 inv_tts_models_table_
    # and_seed::_NEW_LOCAL_REMOTE)。后端 _DEFAULT 兜底仍是旧公网值 → T3 不变。
    check("T2 remote_emotion_bank spec 赢", e2.remote_emotion_bank.endswith("/mai_v4/"))
    check("T2 default_emotion spec 赢", e2.default_emotion == "日常")
    check("T2 inference_params spec top_k 赢", e2.inference_params.get("top_k") == 15)


def test_three_tier_cache_empty():
    print("\n[T3 · 三 tier · cache 空 → _DEFAULT 兜底]")
    from backend.tts import tts_models_cache as tmc
    from backend.tts.gsv import GSVTTS
    from backend.tts.voice_config import VoiceConfig

    saved_cache = tmc._GSV_MODELS_CACHE
    tmc._GSV_MODELS_CACHE = {}
    try:
        cfg = VoiceConfig(provider="gsv", voice="", tts_language="ja")
        vm = json.dumps({"provider": "gsv", "model": "mai_v4", "tts_language": "ja"})
        e = GSVTTS(voice_config=cfg, voice_model_json=vm)
        check("T3 cache 空时 gpt_weights 走 _DEFAULT", "mai_v4-e15" in e.gpt_weights)
        check("T3 cache 空时 remote_bank 走 _DEFAULT", "/workspace/GSVI/" in e.remote_emotion_bank)
        check("T3 cache 空时 default_emotion 走 _DEFAULT", e.default_emotion == "日常")
    finally:
        tmc._GSV_MODELS_CACHE = saved_cache


def test_emotion_dynamic_set():
    print("\n[T4 · emotion 动态集合 · lab_cache.keys()]")
    from backend.tts.tts_models_cache import reload_gsv_models_cache
    from backend.tts.gsv import GSVTTS
    from backend.tts.voice_config import VoiceConfig

    reload_gsv_models_cache()
    cfg = VoiceConfig(provider="gsv", voice="", tts_language="ja")
    vm = json.dumps({"provider": "gsv", "model": "mai_v4", "tts_language": "ja"})
    e = GSVTTS(voice_config=cfg, voice_model_json=vm)

    # 16 集合(顺序无关)
    expected = {
        "日常", "温柔", "傲娇", "吃醋", "严厉", "慌乱", "害羞", "调皮",
        "安慰", "伤感", "真挚", "幸福", "感谢", "放松", "叙事", "感动",
    }
    actual = set(e._lab_cache.keys())
    check(f"T4 16 个 .lab 全在 cache(actual={len(actual)})", actual == expected)
    # 集合内/外路由
    check("T4 集合内 '日常' 路由原样", e._resolve_ref_wav("日常") == "日常")
    check("T4 集合外 '平静' 回 default", e._resolve_ref_wav("平静") == "日常")
    check("T4 集合外 '开心' 回 default", e._resolve_ref_wav("开心") == "日常")
    check("T4 '默认' → default", e._resolve_ref_wav("默认") == "日常")


def test_list_refs_and_upload_local():
    print("\n[T5 · list_refs / upload_ref_local 模块级 helper]")
    from backend.tts.gsv import list_refs, upload_ref_local

    # 真实读 tts/gsv/mai_v4
    repo_root = Path(__file__).resolve().parent.parent
    bank = repo_root / "tts" / "gsv" / "mai_v4"
    refs = list_refs(str(bank))
    check(f"T5 list_refs 命中 16 行 actual={len(refs)}", len(refs) == 16)
    names = {r["name"] for r in refs}
    check("T5 '日常' 在", "日常" in names)
    check("T5 '真挚' 在", "真挚" in names)
    check("T5 row 含 lab_size + lab_preview",
          all("lab_size" in r and "lab_preview" in r for r in refs))

    # upload_ref_local: 写到 tmpdir · 不污染 repo
    with tempfile.TemporaryDirectory() as tmp:
        target = upload_ref_local(tmp, "test_emotion", "ja prompt text 测试")
        check("T5 upload_ref_local 返路径存在", target.exists())
        check("T5 upload_ref_local 内容写入",
              target.read_text(encoding="utf-8") == "ja prompt text 测试")
        # 安全:path traversal 拒绝
        try:
            upload_ref_local(tmp, "../escape", "x")
            check("T5 path traversal 阻断", False, "ValueError not raised")
        except ValueError:
            check("T5 path traversal 阻断", True)
        try:
            upload_ref_local(tmp, "a/b", "x")
            check("T5 slash in emotion 阻断", False)
        except ValueError:
            check("T5 slash in emotion 阻断", True)

    # upload_ref_remote 是 stub
    from backend.tts.gsv import upload_ref_remote
    try:
        upload_ref_remote("http://x", "/x/", "e", b"")
        check("T5 upload_ref_remote stub raises NotImplementedError", False)
    except NotImplementedError:
        check("T5 upload_ref_remote stub raises NotImplementedError", True)


def test_cache_fallback_to_json():
    print("\n[T6 · cache DB 失败 → tts_models.json fallback + WARNING]")
    from backend.tts import tts_models_cache as tmc

    # 重定向 _DB_PATH 到不存在路径 → reload 触发 fallback
    saved_path = tmc._DB_PATH
    tmc._DB_PATH = Path("/nonexistent/momoos.db")
    try:
        n = tmc.reload_gsv_models_cache()
        check("T6 fallback 后 cache 非空(json gsv 段)", n >= 1)
        check("T6 _FELL_BACK_TO_JSON 翻 True", tmc.fell_back_to_json() is True)
        spec = tmc.get_gsv_model_spec("mai_v4")
        check("T6 mai_v4 spec 从 json 拿到", spec.get("id") == "mai_v4")
        check("T6 spec 含 gpt_weights", "gpt_weights" in spec)
    finally:
        tmc._DB_PATH = saved_path
        tmc.reload_gsv_models_cache()  # 复原 DB cache


if __name__ == "__main__":
    test_three_tier_cache_loaded()
    test_three_tier_cache_empty()
    test_emotion_dynamic_set()
    test_list_refs_and_upload_local()
    test_cache_fallback_to_json()

    passed = sum(1 for _, ok in results if ok)
    failed = sum(1 for _, ok in results if not ok)
    print(f"\n{passed} passed · {failed} failed")
    sys.exit(0 if failed == 0 else 1)
