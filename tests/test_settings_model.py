"""v3-G chunk 1.7 — settings/model 切换 API 测试。

覆盖：
  - GET /api/settings/model 返回 current + available 列表
  - POST 合法 model id → 写回 config.yaml + reload + 立即生效
  - POST 非法 model id → 400
  - 持久化检查：写回后从磁盘重新 load，default_model 字段已变

测试不动真实 config.yaml——用 tmp_path + monkeypatch _CONFIG_PATH +
config_yaml dict in-place 替换。
"""
import asyncio
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import yaml
from fastapi import HTTPException

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.config import config_yaml, reload_config_yaml  # noqa: E402
import backend.routes.settings_api as settings_api  # noqa: E402

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))


_FIXTURE_YAML = """\
default_model: openai/qwen3.6-plus
default_user_id: default
available_models:
  - id: openai/qwen3.6-plus
    display_name: Qwen3.6 Plus
    description: 稳定平衡，日常推荐
    tier: stable
  - id: openai/qwen3.6-max-preview
    display_name: Qwen3.6 Max
    description: 最强能力，preview 期可能偶发不稳
    tier: preview
"""


def _isolated_config(tmp_path: Path):
    """Build a temporary config.yaml + patch settings_api._CONFIG_PATH +
    seed config_yaml dict so reload_config_yaml() picks up the fixture.
    Returns the patched config path object.
    """
    cfg = tmp_path / "config.yaml"
    cfg.write_text(_FIXTURE_YAML, encoding="utf-8")

    # Snapshot real config_yaml so we can restore after the test
    snapshot = dict(config_yaml)
    config_yaml.clear()
    config_yaml.update(yaml.safe_load(_FIXTURE_YAML))

    # Also patch backend.config.load_config_yaml to read our fixture file
    # so reload_config_yaml() doesn't pull from the project's real config.yaml
    import backend.config as bc
    real_loader = bc.load_config_yaml
    bc.load_config_yaml = lambda: yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}

    def restore():
        bc.load_config_yaml = real_loader
        config_yaml.clear()
        config_yaml.update(snapshot)

    return cfg, restore


# ---------------------------------------------------------------------------
# 1. GET /api/settings/model
# ---------------------------------------------------------------------------

async def test_get_returns_current_and_available():
    print("\n[settings/model — GET returns current + available]")
    with tempfile.TemporaryDirectory() as td:
        cfg, restore = _isolated_config(Path(td))
        try:
            with patch.object(settings_api, "_CONFIG_PATH", cfg):
                resp = await settings_api.get_model_settings()
        finally:
            restore()
    check("current = openai/qwen3.6-plus", resp.current == "openai/qwen3.6-plus")
    check("available has 2 models", len(resp.available) == 2)
    ids = [m.id for m in resp.available]
    check("plus + max-preview present", set(ids) == {
        "openai/qwen3.6-plus", "openai/qwen3.6-max-preview",
    })
    plus = next(m for m in resp.available if m.id == "openai/qwen3.6-plus")
    check("plus tier=stable", plus.tier == "stable")
    max_preview = next(m for m in resp.available if m.id == "openai/qwen3.6-max-preview")
    check("max-preview tier=preview", max_preview.tier == "preview")
    check("display_name populated", plus.display_name == "Qwen3.6 Plus")


# ---------------------------------------------------------------------------
# 2. POST valid model → switches + persists
# ---------------------------------------------------------------------------

async def test_post_valid_switches_and_persists():
    print("\n[settings/model — POST valid switches + persists to disk]")
    with tempfile.TemporaryDirectory() as td:
        cfg, restore = _isolated_config(Path(td))
        try:
            with patch.object(settings_api, "_CONFIG_PATH", cfg):
                body = settings_api.ModelUpdateBody(model="openai/qwen3.6-max-preview")
                resp = await settings_api.set_model_settings(body)
                # Re-read from disk to confirm persistence
                on_disk = yaml.safe_load(cfg.read_text(encoding="utf-8"))
        finally:
            restore()
    check("response.current updated", resp.current == "openai/qwen3.6-max-preview")
    check("disk default_model updated", on_disk["default_model"] == "openai/qwen3.6-max-preview")
    check("available preserved on disk", len(on_disk.get("available_models") or []) == 2)


# ---------------------------------------------------------------------------
# 3. POST invalid model → 400
# ---------------------------------------------------------------------------

async def test_post_invalid_returns_400():
    print("\n[settings/model — POST invalid returns 400]")
    with tempfile.TemporaryDirectory() as td:
        cfg, restore = _isolated_config(Path(td))
        try:
            raised: HTTPException | None = None
            try:
                with patch.object(settings_api, "_CONFIG_PATH", cfg):
                    body = settings_api.ModelUpdateBody(model="bogus/not-a-model")
                    await settings_api.set_model_settings(body)
            except HTTPException as exc:
                raised = exc
            on_disk_after = yaml.safe_load(cfg.read_text(encoding="utf-8"))
        finally:
            restore()
    check("HTTPException raised", raised is not None)
    if raised is not None:
        check("status_code = 400", raised.status_code == 400)
        check("detail mentions unknown", "unknown model" in str(raised.detail))
    check(
        "disk untouched after bad POST",
        on_disk_after["default_model"] == "openai/qwen3.6-plus",
    )


# ---------------------------------------------------------------------------
# 4. After switch, get_default_model() reflects new value (process state)
# ---------------------------------------------------------------------------

async def test_post_updates_in_process_state():
    print("\n[settings/model — POST updates in-process get_default_model()]")
    from backend.config import get_default_model
    with tempfile.TemporaryDirectory() as td:
        cfg, restore = _isolated_config(Path(td))
        try:
            with patch.object(settings_api, "_CONFIG_PATH", cfg):
                before = get_default_model()
                body = settings_api.ModelUpdateBody(model="openai/qwen3.6-max-preview")
                await settings_api.set_model_settings(body)
                after = get_default_model()
        finally:
            restore()
    check("before = plus", before == "openai/qwen3.6-plus")
    check("after = max-preview", after == "openai/qwen3.6-max-preview")


# ---------------------------------------------------------------------------
# 5. Empty available_models → GET still works (empty list)
# ---------------------------------------------------------------------------

async def test_get_handles_missing_available_models():
    print("\n[settings/model — GET tolerates missing available_models]")
    with tempfile.TemporaryDirectory() as td:
        cfg = Path(td) / "config.yaml"
        cfg.write_text("default_model: foo/bar\n", encoding="utf-8")

        snapshot = dict(config_yaml)
        config_yaml.clear()
        config_yaml.update({"default_model": "foo/bar"})
        try:
            with patch.object(settings_api, "_CONFIG_PATH", cfg):
                resp = await settings_api.get_model_settings()
        finally:
            config_yaml.clear()
            config_yaml.update(snapshot)
    check("current returned", resp.current == "foo/bar")
    check("available is empty list", resp.available == [])


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

async def main():
    await test_get_returns_current_and_available()
    await test_post_valid_switches_and_persists()
    await test_post_invalid_returns_400()
    await test_post_updates_in_process_state()
    await test_get_handles_missing_available_models()

    total = len(results)
    passed = sum(1 for _, ok in results if ok)
    print(f"\n{'=' * 40}")
    print(f"Results: {passed}/{total} passed")
    if passed < total:
        print("FAILED:", ", ".join(n for n, ok in results if not ok))
        sys.exit(1)
    else:
        print("ALL TESTS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
