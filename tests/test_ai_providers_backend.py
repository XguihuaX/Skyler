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
    await run_migration()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_list_vendors():
    print("\n[1] list_vendors — 4 builtin seed visible")
    rows = await svc.list_vendors()
    ids = {v.id for v in rows}
    check("4 builtins present",
          {"qwen", "openai", "anthropic", "deepseek"}.issubset(ids),
          f"got={ids}")
    check("all builtin kind",
          all(v.vendor_kind == "builtin" for v in rows if v.id in ids),
          f"kinds={[v.vendor_kind for v in rows]}")
    check("has_credential=False initially",
          all(not v.has_credential for v in rows),
          f"has_cred={[v.has_credential for v in rows]}")


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
    await test_dispatcher_via_vendor_credentials()


if __name__ == "__main__":
    asyncio.run(_main())
    passed = sum(1 for _, ok in results if ok)
    failed = len(results) - passed
    print(f"\n=== {passed} passed, {failed} failed ===")
    # cleanup tmp home
    import shutil
    shutil.rmtree(_TMP_HOME, ignore_errors=True)
    sys.exit(0 if failed == 0 else 1)
