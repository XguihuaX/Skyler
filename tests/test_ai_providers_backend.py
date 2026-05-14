"""Bugfix-3.1 — AI Providers backend tests.

Coverage:
  * test_list_vendors                       — 4 builtin seed visible
  * test_create_custom_vendor               — POST + listing含
  * test_delete_builtin_vendor_forbidden    — 403
  * test_set_vendor_credentials_encrypted   — DB row 不是明文,API 不回 value
  * test_list_providers_grouped_by_vendor   — group shape 正确
  * test_activate_requires_credential       — vendor 无 cred → 400 no_credential
  * test_activate_uses_env_fallback         — .env 有 key 时 activate 成功
  * test_dispatcher_via_vendor_credentials  — call_llm 从 DB 取 active provider + cred

Run:
    .venv/bin/python tests/test_ai_providers_backend.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

# DB / crypto key 隔离 —— 都在 backend import 前
_TMP_HOME = tempfile.mkdtemp(prefix="momoos-bugfix3-")
os.environ["HOME"] = _TMP_HOME
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

import backend.database as _db_module

TEST_ENGINE = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
TEST_SESSION = sessionmaker(
    TEST_ENGINE, class_=AsyncSession, expire_on_commit=False,
)
_db_module.engine = TEST_ENGINE
_db_module.AsyncSessionLocal = TEST_SESSION

from backend.database import ai_providers as svc
from backend.database.migrations.bugfix_3_1_ai_providers import run_migration
from backend.database.migrations.bugfix_3_2_6_endpoint_env_repair import (
    run_migration as run_migration_3_2_6,
)
from backend.database.migrations.bugfix_3_2_7_model_prefix_repair import (
    run_migration as run_migration_3_2_7,
)
from backend.utils.crypto import decrypt
from sqlalchemy import text

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, cond: bool, detail: str = "") -> None:
    tag = PASS if cond else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, cond))


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------


async def setup_db() -> None:
    # 顺序与 backend/main.py startup 保持一致:3.2.7 先于 3.1(table 不存在时 no-op),
    # 防 3.1 seed dedup 在升级路径上插入重复行。
    await run_migration_3_2_7()
    await run_migration()
    await run_migration_3_2_6()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_list_vendors():
    print("\n[1] list_vendors — 4 builtin seed visible")
    # bugfix-3.2.6: 测试环境清空所有 vendor env keys 以保证 has_credential=False
    # 是初始 invariant (真实 .env 可能含 DASHSCOPE_API_KEY → env fallback 触发)
    from backend.config import settings
    saved = (
        settings.dashscope_api_key, settings.openai_api_key,
        settings.anthropic_api_key, settings.deepseek_api_key,
    )
    settings.dashscope_api_key = ""  # type: ignore[assignment]
    settings.openai_api_key = ""  # type: ignore[assignment]
    settings.anthropic_api_key = ""  # type: ignore[assignment]
    settings.deepseek_api_key = ""  # type: ignore[assignment]
    for key in ("DASHSCOPE_API_KEY", "OPENAI_API_KEY",
                "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY"):
        os.environ.pop(key, None)
    try:
        rows = await svc.list_vendors()
        ids = {v.id for v in rows}
        check("4 builtins present",
              {"qwen", "openai", "anthropic", "deepseek"}.issubset(ids),
              f"got={ids}")
        check("all builtin kind",
              all(v.vendor_kind == "builtin" for v in rows if v.id in ids),
              f"kinds={[v.vendor_kind for v in rows]}")
        check("has_credential=False initially (DB and env both empty)",
              all(not v.has_credential for v in rows),
              f"has_cred={[v.has_credential for v in rows]}")
    finally:
        (settings.dashscope_api_key, settings.openai_api_key,
         settings.anthropic_api_key, settings.deepseek_api_key) = saved


async def test_create_custom_vendor():
    print("\n[2] create_custom_vendor")
    v = await svc.create_vendor(
        id="my-vllm", name="My vLLM",
        default_endpoint="http://localhost:8000/v1",
        credential_key_name="MY_VLLM_KEY",
    )
    check("returned vendor kind=custom", v.vendor_kind == "custom",
          f"got={v.vendor_kind}")
    fetched = await svc.get_vendor("my-vllm")
    check("readback id matches", fetched is not None and fetched.id == "my-vllm")
    rows = await svc.list_vendors()
    check("appears in list", "my-vllm" in {v.id for v in rows})


async def test_delete_builtin_vendor_forbidden():
    print("\n[3] delete_builtin_vendor_forbidden")
    result = await svc.delete_vendor("qwen")
    check("delete builtin returns 'builtin'", result == "builtin",
          f"got={result}")
    v = await svc.get_vendor("qwen")
    check("vendor still exists", v is not None)


async def test_set_vendor_credentials_encrypted():
    print("\n[4] set_vendor_credentials_encrypted")
    ok = await svc.set_vendor_credential("openai", "sk-test-abc123")
    check("upsert returned True", ok is True)
    # 查 DB raw 看是否密文
    async with TEST_ENGINE.begin() as conn:
        row = (await conn.execute(text(
            "SELECT key_value FROM ai_vendor_credentials WHERE vendor_id='openai'"
        ))).first()
    check("row exists in DB", row is not None)
    raw = row[0] if row else ""
    check("DB value is NOT plaintext",
          raw != "sk-test-abc123" and "sk-test-abc123" not in raw,
          f"got raw len={len(raw)}")
    # decrypt 回原文
    decrypted = decrypt(raw)
    check("decrypt round-trip == plaintext",
          decrypted == "sk-test-abc123",
          f"decrypted={decrypted!r}")
    # service-level getter 也返回 plaintext
    fetched = await svc.get_vendor_credential("openai")
    check("get_vendor_credential plaintext", fetched == "sk-test-abc123")
    # has_credential 变 True
    v = await svc.get_vendor("openai")
    check("has_credential=True after set",
          v is not None and v.has_credential is True)


async def test_list_providers_grouped_by_vendor():
    print("\n[5] list_providers — grouped by vendor")
    # 用 LLM seed: 应有 qwen 下 2 个, openai 下 2, anthropic 下 2, deepseek 下 1
    rows = await svc.list_providers("llm")
    by_vendor: dict = {}
    for p in rows:
        by_vendor.setdefault(p.vendor_id, []).append(p.model)
    check("qwen has 2 providers",
          len(by_vendor.get("qwen", [])) == 2,
          f"got={by_vendor.get('qwen')}")
    check("openai has 2 providers",
          len(by_vendor.get("openai", [])) == 2,
          f"got={by_vendor.get('openai')}")
    check("anthropic has 2 providers",
          len(by_vendor.get("anthropic", [])) == 2,
          f"got={by_vendor.get('anthropic')}")
    check("deepseek has 1 provider",
          len(by_vendor.get("deepseek", [])) == 1,
          f"got={by_vendor.get('deepseek')}")
    check("all builtin kind",
          all(p.provider_kind == "builtin" for p in rows))


async def test_activate_requires_credential():
    print("\n[6] activate_requires_credential")
    # 找一个 qwen 下的 provider, qwen 当前还没 set credential
    rows = await svc.list_providers("llm")
    qwen_prov = next(p for p in rows if p.vendor_id == "qwen")
    # 清掉可能的 env fallback —— 测试期 settings.dashscope_api_key 可能为空
    # (test 环境无 .env), 直接尝试 activate
    from backend.config import settings
    saved = settings.dashscope_api_key
    settings.dashscope_api_key = ""  # type: ignore[assignment]
    try:
        result = await svc.activate_provider(qwen_prov.id)
        check("no credential → returns 'no_credential'",
              result == "no_credential", f"got={result}")
        p = await svc.get_provider(qwen_prov.id)
        check("provider remains inactive",
              p is not None and p.is_active is False)
    finally:
        settings.dashscope_api_key = saved


async def test_activate_uses_env_fallback():
    print("\n[7] activate_uses_env_fallback when no DB credential")
    # 临时把 dashscope env 注入 settings 模拟 .env 已配
    from backend.config import settings
    saved = settings.dashscope_api_key
    settings.dashscope_api_key = "sk-env-fallback"  # type: ignore[assignment]
    try:
        # 确保 qwen 没 DB credential(上一 test 没设)
        await svc.clear_vendor_credential("qwen")
        rows = await svc.list_providers("llm")
        qwen_prov = next(p for p in rows if p.vendor_id == "qwen")
        result = await svc.activate_provider(qwen_prov.id)
        check("env fallback → activate ok",
              result == "ok", f"got={result}")
        active = await svc.get_active_provider("llm")
        check("active is this provider",
              active is not None and active.id == qwen_prov.id)
        # resolve_vendor_credential 应该回 .env 值
        cred = await svc.resolve_vendor_credential("qwen")
        check("resolve falls back to env",
              cred == "sk-env-fallback", f"got={cred}")
    finally:
        settings.dashscope_api_key = saved


async def test_auto_activate_on_env_credential():
    """Bugfix-3.2.5: 老用户首启平滑过渡 —— migration 跑时若 .env 有 vendor key
    且 DB 没 is_active LLM provider, 自动 activate 第一个 vendor 凭证可用的
    builtin (优先 yaml default 匹配)。"""
    print("\n[9] auto_activate_on_env_credential")
    # 准备 fresh state: deactivate 全部 LLM (sql) — 模拟首次启动 DB
    from sqlalchemy import text as sa_text
    async with TEST_ENGINE.begin() as conn:
        await conn.execute(sa_text(
            "UPDATE ai_providers SET is_active=0 WHERE type='llm'"
        ))
        # 也清掉前测留下的 DB 凭证以确保 .env 是唯一路径
        await conn.execute(sa_text("DELETE FROM ai_vendor_credentials"))
    # 模拟 .env 配 DASHSCOPE_API_KEY
    from backend.config import settings
    saved = settings.dashscope_api_key
    settings.dashscope_api_key = "sk-env-dashscope"  # type: ignore[assignment]
    try:
        # 重跑 migration → auto_activate 应该选 Qwen 的第一个 (matches yaml
        # default_model "deepseek/deepseek-chat" 默认实际无匹配, 走 seed 顺序
        # → qwen 优先)
        await run_migration()
        active = await svc.get_active_provider("llm")
        check("auto-activate happened",
              active is not None, f"got={active}")
        check("activated provider is from Qwen vendor",
              active is not None and active.vendor_id == "qwen",
              f"got vendor={None if active is None else active.vendor_id}")

        # 再跑一次 migration → 不应改变(尊重已有 active)
        first_id = active.id if active else None
        await run_migration()
        active2 = await svc.get_active_provider("llm")
        check("migration idempotent — active not changed",
              active2 is not None and active2.id == first_id,
              f"got new id={None if active2 is None else active2.id}")
    finally:
        settings.dashscope_api_key = saved


async def test_has_credential_env_fallback():
    """Bugfix-3.2.6: has_credential 检测 .env fallback。"""
    print("\n[10] has_credential reads .env fallback")
    # Clean DB creds
    async with TEST_ENGINE.begin() as conn:
        await conn.execute(text("DELETE FROM ai_vendor_credentials"))
    from backend.config import settings
    saved_dash = settings.dashscope_api_key
    saved_oai = settings.openai_api_key
    try:
        # Set only DASHSCOPE_API_KEY in env, OpenAI key empty
        settings.dashscope_api_key = "sk-env-dashscope"  # type: ignore[assignment]
        settings.openai_api_key = ""  # type: ignore[assignment]
        # Also remove from os.environ for OpenAI to guarantee no value
        os.environ.pop("OPENAI_API_KEY", None)
        rows = await svc.list_vendors()
        by_id = {v.id: v for v in rows}
        check("qwen credential_source == 'env'",
              by_id["qwen"].credential_source == "env",
              f"got={by_id['qwen'].credential_source}")
        check("qwen has_credential = True",
              by_id["qwen"].has_credential is True)
        check("openai credential_source == 'none'",
              by_id["openai"].credential_source == "none",
              f"got={by_id['openai'].credential_source}")
        check("openai has_credential = False",
              by_id["openai"].has_credential is False)
    finally:
        settings.dashscope_api_key = saved_dash
        settings.openai_api_key = saved_oai


async def test_has_credential_db_priority():
    """DB credential 优先 over .env."""
    print("\n[11] has_credential DB priority over env")
    from backend.config import settings
    saved = settings.dashscope_api_key
    try:
        settings.dashscope_api_key = "sk-env-value"  # type: ignore[assignment]
        await svc.set_vendor_credential("qwen", "sk-db-value")
        v = await svc.get_vendor("qwen")
        check("source == 'db' when both set",
              v is not None and v.credential_source == "db",
              f"got={None if v is None else v.credential_source}")
        # resolve_vendor_credential should return DB value
        resolved = await svc.resolve_vendor_credential("qwen")
        check("resolve returns DB value", resolved == "sk-db-value",
              f"got={resolved}")
    finally:
        await svc.clear_vendor_credential("qwen")
        settings.dashscope_api_key = saved


async def test_endpoint_resolution_chain():
    """Bugfix-3.2.6: endpoint 4-tier chain — provider > env > vendor.default > none."""
    print("\n[12] endpoint resolution chain")
    from backend.config import settings
    # Ensure clean env state
    saved_dbu = getattr(settings, "dashscope_base_url", "")
    os.environ.pop("DASHSCOPE_BASE_URL", None)
    os.environ.pop("DASHSCOPE_API_BASE", None)
    settings.dashscope_base_url = ""  # type: ignore[assignment]
    try:
        # 1. Pure vendor default (no override, no env)
        ep, src = await svc.resolve_vendor_endpoint("qwen")
        check("vendor default endpoint",
              ep == "https://dashscope.aliyuncs.com/compatible-mode/v1" and src == "vendor",
              f"got=({ep}, {src})")

        # 2. Env override via settings
        settings.dashscope_base_url = "https://my-custom-dashscope"  # type: ignore[assignment]
        ep, src = await svc.resolve_vendor_endpoint("qwen")
        check("env settings override",
              ep == "https://my-custom-dashscope" and src == "env",
              f"got=({ep}, {src})")
        settings.dashscope_base_url = ""  # reset

        # 3. Provider override beats env + vendor
        os.environ["DASHSCOPE_BASE_URL"] = "https://env-dashscope"
        ep, src = await svc.resolve_vendor_endpoint(
            "qwen", provider_endpoint_override="https://provider-override",
        )
        check("provider override wins",
              ep == "https://provider-override" and src == "provider",
              f"got=({ep}, {src})")

        # 4. Alias DASHSCOPE_API_BASE works when DASHSCOPE_BASE_URL missing
        os.environ.pop("DASHSCOPE_BASE_URL", None)
        os.environ["DASHSCOPE_API_BASE"] = "https://alias-base"
        ep, src = await svc.resolve_vendor_endpoint("qwen")
        check("alias DASHSCOPE_API_BASE resolves",
              ep == "https://alias-base" and src == "env",
              f"got=({ep}, {src})")
    finally:
        settings.dashscope_base_url = saved_dbu
        os.environ.pop("DASHSCOPE_BASE_URL", None)
        os.environ.pop("DASHSCOPE_API_BASE", None)


async def test_migration_repairs_inconsistent_state():
    """Bugfix-3.2.6: migration 修补 is_active=1 AND enabled=0 → enabled=1。"""
    print("\n[13] migration repairs inconsistent state")
    # Manually plant inconsistent row
    async with TEST_ENGINE.begin() as conn:
        await conn.execute(text(
            "UPDATE ai_providers SET enabled=0, is_active=1 "
            "WHERE id = (SELECT id FROM ai_providers WHERE type='llm' LIMIT 1)"
        ))
    # Verify planted
    async with TEST_ENGINE.begin() as conn:
        row = (await conn.execute(text(
            "SELECT COUNT(*) FROM ai_providers WHERE is_active=1 AND enabled=0"
        ))).first()
    check("planted inconsistent row exists",
          row is not None and row[0] >= 1, f"count={None if row is None else row[0]}")
    # Run repair
    await run_migration_3_2_6()
    async with TEST_ENGINE.begin() as conn:
        row = (await conn.execute(text(
            "SELECT COUNT(*) FROM ai_providers WHERE is_active=1 AND enabled=0"
        ))).first()
    check("after repair, no inconsistent rows",
          row is not None and row[0] == 0, f"count={None if row is None else row[0]}")


async def test_activate_sets_enabled():
    """Bugfix-3.2.6: activate_provider 强制 enabled=1, 避免自相矛盾。"""
    print("\n[14] activate_provider sets enabled=1")
    # 用 settings 模拟 .env (settings.openai_api_key)
    from backend.config import settings
    saved_oai = settings.openai_api_key
    try:
        settings.openai_api_key = "sk-env-openai"  # type: ignore[assignment]
        # plant: disabled OpenAI provider, then activate it
        rows = await svc.list_providers("llm")
        oai_prov = next(p for p in rows if p.vendor_id == "openai")
        await svc.patch_provider(oai_prov.id, enabled=False)
        # confirm disabled
        p = await svc.get_provider(oai_prov.id)
        check("provider initially disabled",
              p is not None and p.enabled is False)
        # activate should still succeed (no longer 'not_enabled') + flip enabled
        result = await svc.activate_provider(oai_prov.id)
        check("activate ok despite disabled", result == "ok", f"got={result}")
        p = await svc.get_provider(oai_prov.id)
        check("provider now enabled + active",
              p is not None and p.enabled is True and p.is_active is True,
              f"enabled={None if p is None else p.enabled} active={None if p is None else p.is_active}")
    finally:
        settings.openai_api_key = saved_oai


async def test_dispatcher_via_vendor_credentials():
    print("\n[8] dispatcher_via_vendor_credentials")
    # 给 openai vendor 设 DB credential
    await svc.set_vendor_credential("openai", "sk-openai-from-db")
    rows = await svc.list_providers("llm")
    openai_prov = next(p for p in rows if p.vendor_id == "openai")
    result = await svc.activate_provider(openai_prov.id)
    check("openai activated", result == "ok", f"got={result}")
    # 直接调 dispatcher 的 resolver
    from backend.llm.client import _resolve_db_provider_kwargs
    model, kwargs = await _resolve_db_provider_kwargs(None)
    check("dispatcher returns active provider model",
          model == openai_prov.model, f"got={model}")
    check("kwargs api_key == DB plaintext",
          kwargs.get("api_key") == "sk-openai-from-db",
          f"got={kwargs.get('api_key')}")
    check("kwargs api_base from vendor default",
          kwargs.get("api_base") == "https://api.openai.com/v1",
          f"got={kwargs.get('api_base')}")
    # caller 显式 model → DB 路径让步
    model2, kwargs2 = await _resolve_db_provider_kwargs("override/foo")
    check("explicit model override skips DB",
          model2 is None and kwargs2 == {})


async def test_seed_models_have_litellm_prefix():
    """Bugfix-3.2.7: 所有 builtin LLM provider 的 model 字段必须含 LiteLLM
    provider 前缀 ('xxx/yyy'),否则 LiteLLM acompletion 会抛
    BadRequestError('LLM Provider NOT provided')。防未来 add builtin 漏写。"""
    print("\n[15] seed_models_have_litellm_prefix")
    rows = await svc.list_providers("llm")
    bad = [(p.id, p.vendor_id, p.name, p.model)
           for p in rows
           if p.provider_kind == "builtin" and (not p.model or "/" not in p.model)]
    check(
        "all builtin LLM models have LiteLLM provider prefix",
        not bad,
        f"model 缺少 LiteLLM provider 前缀: {bad}" if bad else "",
    )


async def test_migration_repair_qwen_model_prefix():
    """Bugfix-3.2.7: 老 DB 含裸 qwen3.6-* 行 → migration 修补成 openai/qwen3.6-*。
    幂等:再跑一次不变,且不影响已带前缀的行。"""
    print("\n[16] migration_repair_qwen_model_prefix")
    # 在 ai_providers 注入裸名行(模拟老 install)
    async with TEST_ENGINE.begin() as conn:
        await conn.execute(text("""
            INSERT INTO ai_providers
                (vendor_id, type, name, model, provider_kind, enabled, is_active)
            VALUES
                ('qwen', 'llm', '_legacy_plus', 'qwen3.6-plus',
                 'builtin', 1, 0),
                ('qwen', 'llm', '_legacy_max', 'qwen3.6-max-preview',
                 'builtin', 1, 0)
        """))
    # 跑修补
    await run_migration_3_2_7()
    async with TEST_ENGINE.begin() as conn:
        bare = (await conn.execute(text(
            "SELECT COUNT(*) FROM ai_providers "
            "WHERE model IN ('qwen3.6-plus', 'qwen3.6-max-preview')"
        ))).first()
        prefixed_plus = (await conn.execute(text(
            "SELECT COUNT(*) FROM ai_providers "
            "WHERE name='_legacy_plus' AND model='openai/qwen3.6-plus'"
        ))).first()
        prefixed_max = (await conn.execute(text(
            "SELECT COUNT(*) FROM ai_providers "
            "WHERE name='_legacy_max' AND model='openai/qwen3.6-max-preview'"
        ))).first()
    check(
        "no bare qwen3.6-* model rows after repair",
        bare is not None and bare[0] == 0,
        f"remaining bare count={None if bare is None else bare[0]}",
    )
    check(
        "_legacy_plus row repaired to openai/qwen3.6-plus",
        prefixed_plus is not None and prefixed_plus[0] == 1,
        f"got count={None if prefixed_plus is None else prefixed_plus[0]}",
    )
    check(
        "_legacy_max row repaired to openai/qwen3.6-max-preview",
        prefixed_max is not None and prefixed_max[0] == 1,
        f"got count={None if prefixed_max is None else prefixed_max[0]}",
    )
    # 幂等:再跑一次不应再动行
    await run_migration_3_2_7()
    async with TEST_ENGINE.begin() as conn:
        still_prefixed = (await conn.execute(text(
            "SELECT COUNT(*) FROM ai_providers "
            "WHERE model IN ('openai/qwen3.6-plus', 'openai/qwen3.6-max-preview')"
        ))).first()
    check(
        "migration idempotent on already-prefixed rows",
        still_prefixed is not None and still_prefixed[0] >= 2,
        f"count={None if still_prefixed is None else still_prefixed[0]}",
    )


async def test_migration_repair_deepseek_model_prefix():
    """Bugfix-3.2.7: 老 DB 含裸 deepseek-chat 行 → 修补成 deepseek/deepseek-chat。"""
    print("\n[17] migration_repair_deepseek_model_prefix")
    async with TEST_ENGINE.begin() as conn:
        await conn.execute(text("""
            INSERT INTO ai_providers
                (vendor_id, type, name, model, provider_kind, enabled, is_active)
            VALUES
                ('deepseek', 'llm', '_legacy_ds', 'deepseek-chat',
                 'builtin', 1, 0)
        """))
    await run_migration_3_2_7()
    async with TEST_ENGINE.begin() as conn:
        bare = (await conn.execute(text(
            "SELECT COUNT(*) FROM ai_providers WHERE model='deepseek-chat'"
        ))).first()
        prefixed = (await conn.execute(text(
            "SELECT COUNT(*) FROM ai_providers "
            "WHERE name='_legacy_ds' AND model='deepseek/deepseek-chat'"
        ))).first()
    check(
        "no bare deepseek-chat rows after repair",
        bare is not None and bare[0] == 0,
        f"remaining count={None if bare is None else bare[0]}",
    )
    check(
        "_legacy_ds repaired to deepseek/deepseek-chat",
        prefixed is not None and prefixed[0] == 1,
        f"got count={None if prefixed is None else prefixed[0]}",
    )


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------


async def _main():
    await setup_db()
    await test_list_vendors()
    await test_create_custom_vendor()
    await test_delete_builtin_vendor_forbidden()
    await test_set_vendor_credentials_encrypted()
    await test_list_providers_grouped_by_vendor()
    await test_activate_requires_credential()
    await test_activate_uses_env_fallback()
    await test_auto_activate_on_env_credential()
    await test_has_credential_env_fallback()
    await test_has_credential_db_priority()
    await test_endpoint_resolution_chain()
    await test_migration_repairs_inconsistent_state()
    await test_activate_sets_enabled()
    await test_dispatcher_via_vendor_credentials()
    await test_seed_models_have_litellm_prefix()
    await test_migration_repair_qwen_model_prefix()
    await test_migration_repair_deepseek_model_prefix()


if __name__ == "__main__":
    asyncio.run(_main())
    passed = sum(1 for _, ok in results if ok)
    failed = len(results) - passed
    print(f"\n=== {passed} passed, {failed} failed ===")
    # cleanup tmp home
    import shutil
    shutil.rmtree(_TMP_HOME, ignore_errors=True)
    sys.exit(0 if failed == 0 else 1)
