"""v3.5 chunk 7 — MCP credentials + enable/disable + API endpoints。

不真启动 npx 子进程（npm install 网络耗时 + 不稳）。client lifecycle 仅测
state 机：``init_clients_from_config`` 读 DB override + ``list_status`` 返
missing_credentials；真正 stdio_client 走 chunk 1.5 已有测试。
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from backend.database import engine, init_db
from backend.database.migrations.v3_5_chunk7_mcp_credentials import (
    run_migration,
)
from backend.mcp import credentials as creds
from backend.mcp import client as mcp_client
from backend.routes.mcp_api import router

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))


async def _setup():
    await init_db()
    await run_migration()
    # 清测试段
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM mcp_credentials WHERE server_name LIKE '_test_%'"))
        await conn.execute(text("DELETE FROM mcp_client_state WHERE server_name LIKE '_test_%'"))
    mcp_client.reset_for_test()


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return app


# ---------------------------------------------------------------------------
# 1. credentials CRUD
# ---------------------------------------------------------------------------

async def test_credentials_crud():
    print("\n[credentials — upsert / get_env / list_keys / delete via empty value]")
    await _setup()
    await creds.upsert("_test_x", "API_KEY", "secret_v1")
    env = await creds.get_env("_test_x")
    check("get_env returns dict", env == {"API_KEY": "secret_v1"}, f"got {env!r}")

    # Update
    await creds.upsert("_test_x", "API_KEY", "secret_v2")
    env = await creds.get_env("_test_x")
    check("upsert updates value", env["API_KEY"] == "secret_v2")

    # Add 2nd key
    await creds.upsert("_test_x", "URL", "https://example.com")
    keys = await creds.list_keys("_test_x")
    check("list_keys count = 2", len(keys) == 2)
    check("list_keys hides value",
          all("value" not in k for k in keys),
          f"got {keys!r}")

    # Empty value → delete
    await creds.upsert("_test_x", "URL", "")
    env = await creds.get_env("_test_x")
    check("empty value deletes key",
          "URL" not in env and "API_KEY" in env,
          f"got {env!r}")


async def test_credentials_empty_key_rejected():
    print("\n[credentials — empty key_name rejected]")
    await _setup()
    try:
        await creds.upsert("_test_x", "  ", "value")
        check("empty key raises", False)
    except ValueError:
        check("empty key raises", True)


# ---------------------------------------------------------------------------
# 2. enable override
# ---------------------------------------------------------------------------

async def test_enable_override():
    print("\n[enable override — None default → set True/False]")
    await _setup()
    check("default None", await creds.get_enabled_override("_test_y") is None)
    await creds.set_enabled("_test_y", True)
    check("after True", await creds.get_enabled_override("_test_y") is True)
    await creds.set_enabled("_test_y", False)
    check("after False", await creds.get_enabled_override("_test_y") is False)


# ---------------------------------------------------------------------------
# 3. client.list_status missing_credentials
# ---------------------------------------------------------------------------

async def test_list_status_missing_creds():
    print("\n[client.list_status — missing_credentials 反映 env_required vs DB]")
    await _setup()
    # 模拟一个 mcp client config（不真连）
    handle = mcp_client._ClientHandle("_test_notion", {
        "description": "test",
        "transport": "stdio",
        "command": "echo",  # 不会真启动，只是看 status
        "env_required": ["TEST_API_KEY", "TEST_URL"],
        "enabled": False,
    })
    mcp_client._clients["_test_notion"] = handle

    try:
        rows = await mcp_client.list_status()
        item = next((r for r in rows if r["name"] == "_test_notion"), None)
        check("item present", item is not None)
        check("env_required echoed",
              item["env_required"] == ["TEST_API_KEY", "TEST_URL"])
        check("missing = both keys",
              set(item["missing_credentials"]) == {"TEST_API_KEY", "TEST_URL"})

        # 配一个 key
        await creds.upsert("_test_notion", "TEST_API_KEY", "v")
        rows = await mcp_client.list_status()
        item = next(r for r in rows if r["name"] == "_test_notion")
        check("after partial config, missing = 1",
              item["missing_credentials"] == ["TEST_URL"])

        # 配齐
        await creds.upsert("_test_notion", "TEST_URL", "u")
        rows = await mcp_client.list_status()
        item = next(r for r in rows if r["name"] == "_test_notion")
        check("after full config, missing = []",
              item["missing_credentials"] == [])

        # cleanup
        await creds.upsert("_test_notion", "TEST_API_KEY", "")
        await creds.upsert("_test_notion", "TEST_URL", "")
    finally:
        mcp_client._clients.pop("_test_notion", None)


async def test_effective_enabled_db_override():
    print("\n[client._effective_enabled — DB override > config]")
    await _setup()
    handle = mcp_client._ClientHandle("_test_eff", {
        "description": "test",
        "transport": "stdio",
        "command": "echo",
        "enabled": False,  # config 默认 False
    })
    mcp_client._clients["_test_eff"] = handle
    try:
        check("no override → config default (False)",
              await mcp_client._effective_enabled(handle) is False)
        await creds.set_enabled("_test_eff", True)
        check("DB True overrides config False",
              await mcp_client._effective_enabled(handle) is True)
        await creds.set_enabled("_test_eff", False)
        check("DB False overrides", await mcp_client._effective_enabled(handle) is False)
    finally:
        mcp_client._clients.pop("_test_eff", None)


# ---------------------------------------------------------------------------
# 4. API endpoints
# ---------------------------------------------------------------------------

def test_credentials_endpoints():
    print("\n[API — GET/PUT /api/mcp/clients/{name}/credentials]")
    asyncio.run(_setup())
    # 注册一个 fake handle 让 status 路径返 _test_creds
    handle = mcp_client._ClientHandle("_test_creds", {
        "description": "API test",
        "transport": "stdio",
        "command": "echo",
        "env_required": ["MY_KEY"],
        "enabled": False,
    })
    mcp_client._clients["_test_creds"] = handle
    try:
        client = TestClient(_build_app())

        # PUT 设凭证
        r = client.put(
            "/api/mcp/clients/_test_creds/credentials",
            json={"credentials": {"MY_KEY": "secret"}},
        )
        check("PUT 200", r.status_code == 200, f"got {r.status_code} {r.text}")
        data = r.json()
        check("response keys", len(data["keys"]) == 1)
        check("no value in response",
              "value" not in data["keys"][0])

        # GET 列 keys
        r = client.get("/api/mcp/clients/_test_creds/credentials")
        check("GET 200", r.status_code == 200)
        check("configured=True", r.json()["keys"][0]["configured"] is True)

        # PUT 404 unknown server
        r = client.put(
            "/api/mcp/clients/_does_not_exist/credentials",
            json={"credentials": {"X": "y"}},
        )
        check("unknown server 404", r.status_code == 404,
              f"got {r.status_code}")

        # PUT 422 empty body
        r = client.put(
            "/api/mcp/clients/_test_creds/credentials",
            json={"credentials": {}},
        )
        check("empty credentials 422", r.status_code == 422)
    finally:
        mcp_client._clients.pop("_test_creds", None)
        asyncio.run(creds.upsert("_test_creds", "MY_KEY", ""))


def test_enabled_endpoint_blocks_missing_creds():
    print("\n[API — PUT /enabled 缺凭证 → 422]")
    asyncio.run(_setup())
    handle = mcp_client._ClientHandle("_test_enable", {
        "description": "test",
        "transport": "stdio",
        "command": "echo",
        "env_required": ["NEEDED_KEY"],
        "enabled": False,
    })
    mcp_client._clients["_test_enable"] = handle
    try:
        client = TestClient(_build_app())
        r = client.put(
            "/api/mcp/clients/_test_enable/enabled",
            json={"enabled": True},
        )
        check("missing creds 422", r.status_code == 422, f"got {r.status_code} {r.text}")
        check("detail mentions missing key",
              "NEEDED_KEY" in r.json().get("detail", ""))
    finally:
        mcp_client._clients.pop("_test_enable", None)


def test_disable_endpoint_works_without_creds():
    print("\n[API — PUT /enabled False 不需要凭证]")
    asyncio.run(_setup())
    handle = mcp_client._ClientHandle("_test_disable", {
        "description": "test",
        "transport": "stdio",
        "command": "echo",
        "env_required": ["KEY"],
        "enabled": False,
    })
    mcp_client._clients["_test_disable"] = handle
    try:
        client = TestClient(_build_app())
        # 即使没凭证，disable 也应 OK（safe operation）
        r = client.put(
            "/api/mcp/clients/_test_disable/enabled",
            json={"enabled": False},
        )
        check("disable without creds 200", r.status_code == 200,
              f"got {r.status_code}")
        check("enabled=False reflected",
              r.json()["enabled"] is False)
    finally:
        mcp_client._clients.pop("_test_disable", None)


# ---------------------------------------------------------------------------
# 5. config.yaml has Notion entry
# ---------------------------------------------------------------------------

def test_notion_entry_in_config():
    print("\n[config.yaml — notion entry present + 字段合法]")
    from backend.config import config_yaml
    clients = config_yaml.get("mcp_clients") or {}
    notion = clients.get("notion")
    check("notion entry present", notion is not None)
    if notion is None:
        return
    check("transport stdio", notion.get("transport") == "stdio")
    check("command npx", notion.get("command") == "npx")
    args = notion.get("args") or []
    check("args mentions @notionhq/notion-mcp-server",
          any("notionhq/notion-mcp-server" in str(a) for a in args),
          f"got {args!r}")
    check("env_required includes NOTION_API_KEY",
          "NOTION_API_KEY" in (notion.get("env_required") or []))
    check("default enabled=False",
          notion.get("enabled", True) is False)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

async def amain():
    await test_credentials_crud()
    await test_credentials_empty_key_rejected()
    await test_enable_override()
    await test_list_status_missing_creds()
    await test_effective_enabled_db_override()


def main():
    asyncio.run(amain())
    test_credentials_endpoints()
    test_enabled_endpoint_blocks_missing_creds()
    test_disable_endpoint_works_without_creds()
    test_notion_entry_in_config()

    total = len(results)
    passed = sum(1 for _, ok in results if ok)
    print(f"\n{'='*40}")
    print(f"Results: {passed}/{total} passed")
    if passed < total:
        print("FAILED:", ", ".join(n for n, ok in results if not ok))
        sys.exit(1)
    else:
        print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
