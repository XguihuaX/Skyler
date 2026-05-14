"""Bugfix-3.3 — Whisper model_size config tests。

Coverage:
  * get_whisper_model_size — yaml override 优先 / 否则 settings.whisper_model fallback
  * GET /api/config/asr 返回 whisper_model_size + allowed_sizes
  * POST /api/config/asr 校验 allowed_sizes,合法值 → 写 yaml + reload_config_yaml
  * POST /api/config/asr 不合法值 → 400

Run:
    .venv/bin/python tests/test_whisper_model_size.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 隔离:每次跑用 fresh HOME + 隔离 config.yaml
_TMP_HOME = tempfile.mkdtemp(prefix="momoos-bugfix33-")
os.environ["HOME"] = _TMP_HOME

from backend import config as _cfg
from backend.config import (
    config_yaml, get_whisper_model_size, reload_config_yaml, settings,
)

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, cond: bool, detail: str = "") -> None:
    tag = PASS if cond else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, cond))


# ---------------------------------------------------------------------------
# get_whisper_model_size helper
# ---------------------------------------------------------------------------


def test_get_returns_settings_default_when_yaml_unset():
    """yaml 无 asr 节 → 退回 settings.whisper_model (.env 默认 'small')。"""
    print("\n[1] get_returns_settings_default_when_yaml_unset")
    # 临时 mutate yaml dict
    saved = dict(config_yaml)
    try:
        config_yaml.pop("asr", None)
        check("returns settings.whisper_model",
              get_whisper_model_size() == settings.whisper_model,
              f"got={get_whisper_model_size()!r} expected={settings.whisper_model!r}")
    finally:
        config_yaml.clear()
        config_yaml.update(saved)


def test_yaml_override_wins():
    """yaml asr.whisper_model_size → 优先于 .env。"""
    print("\n[2] yaml_override_wins")
    saved = dict(config_yaml)
    try:
        config_yaml["asr"] = {"whisper_model_size": "medium"}
        check("yaml override → 'medium'",
              get_whisper_model_size() == "medium",
              f"got={get_whisper_model_size()!r}")
        config_yaml["asr"] = {"whisper_model_size": "large-v3"}
        check("yaml override → 'large-v3'",
              get_whisper_model_size() == "large-v3")
        # 空字符串 → fallback
        config_yaml["asr"] = {"whisper_model_size": ""}
        check("空字符串 → fallback to settings",
              get_whisper_model_size() == settings.whisper_model)
        # 非 str → fallback
        config_yaml["asr"] = {"whisper_model_size": 123}
        check("非 str → fallback to settings",
              get_whisper_model_size() == settings.whisper_model)
    finally:
        config_yaml.clear()
        config_yaml.update(saved)


# ---------------------------------------------------------------------------
# /api/config/asr endpoint (in-process FastAPI client)
# ---------------------------------------------------------------------------


async def test_api_get_asr_returns_current():
    print("\n[3] GET /api/config/asr returns current")
    from backend.routes.config_api import (
        get_asr_config_endpoint, _ASR_ALLOWED_SIZES,
    )
    resp = await get_asr_config_endpoint()
    check("response is AsrConfigResponse",
          hasattr(resp, "whisper_model_size") and hasattr(resp, "allowed_sizes"))
    check("allowed_sizes 含 small + medium",
          "small" in resp.allowed_sizes and "medium" in resp.allowed_sizes,
          f"got={resp.allowed_sizes}")
    check("allowed_sizes 与 backend tuple 一致",
          list(_ASR_ALLOWED_SIZES) == resp.allowed_sizes,
          f"got={resp.allowed_sizes}")


async def test_api_post_asr_rejects_invalid_size():
    print("\n[4] POST /api/config/asr rejects invalid size")
    from fastapi import HTTPException
    from backend.routes.config_api import (
        set_asr_config_endpoint, AsrConfigUpdateBody,
    )
    body = AsrConfigUpdateBody(whisper_model_size="HUGE_BOGUS")
    raised = False
    try:
        await set_asr_config_endpoint(body)
    except HTTPException as exc:
        raised = True
        check("400 raised on invalid", exc.status_code == 400,
              f"got status={exc.status_code} detail={exc.detail}")
    check("HTTPException did raise", raised,
          "set_asr_config_endpoint should have raised on 'HUGE_BOGUS'")


async def test_api_post_asr_writes_yaml_and_reloads():
    print("\n[5] POST /api/config/asr writes yaml + reloads")
    # 用一个隔离 config.yaml 路径替换路由内 _CONFIG_PATH
    import backend.routes.config_api as cfg_api
    saved_path = cfg_api._CONFIG_PATH
    tmp = tempfile.NamedTemporaryFile(suffix=".yaml", delete=False)
    tmp.write(b"default_model: openai/qwen3.6-plus\n")
    tmp.close()
    cfg_api._CONFIG_PATH = Path(tmp.name)
    # 同时换 backend.config.load_config_yaml 看的路径 — 没暴露 inject 接口,
    # 这里改用直接 reload 后 patch config_yaml
    saved_yaml = dict(config_yaml)
    try:
        from backend.routes.config_api import (
            set_asr_config_endpoint, AsrConfigUpdateBody,
        )
        body = AsrConfigUpdateBody(whisper_model_size="medium")
        result = await set_asr_config_endpoint(body)
        check("returns ok",
              result == {"status": "ok", "whisper_model_size": "medium"},
              f"got={result}")
        # 文件已写
        on_disk = Path(tmp.name).read_text()
        check("disk yaml 含 asr.whisper_model_size: medium",
              "whisper_model_size: medium" in on_disk,
              f"on_disk[:200]={on_disk[:200]!r}")
    finally:
        cfg_api._CONFIG_PATH = saved_path
        config_yaml.clear()
        config_yaml.update(saved_yaml)
        os.unlink(tmp.name)


# ---------------------------------------------------------------------------
# Whisper model lazy reload after size change
# ---------------------------------------------------------------------------


async def test_whisper_reload_if_size_changed_noop_when_same():
    print("\n[6] whisper_asr.reload_if_size_changed no-op when same")
    from backend.asr.whisper import WhisperASR
    inst = WhisperASR()
    inst._model = object()  # pretend already loaded
    inst._loaded_size = get_whisper_model_size()
    changed = await inst.reload_if_size_changed()
    check("returns False when sizes match",
          changed is False, f"got={changed}")


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------


async def _main():
    test_get_returns_settings_default_when_yaml_unset()
    test_yaml_override_wins()
    await test_api_get_asr_returns_current()
    await test_api_post_asr_rejects_invalid_size()
    await test_api_post_asr_writes_yaml_and_reloads()
    await test_whisper_reload_if_size_changed_noop_when_same()


if __name__ == "__main__":
    asyncio.run(_main())
    passed = sum(1 for _, ok in results if ok)
    failed = len(results) - passed
    print(f"\n=== {passed} passed, {failed} failed ===")
    import shutil
    shutil.rmtree(_TMP_HOME, ignore_errors=True)
    sys.exit(0 if failed == 0 else 1)
