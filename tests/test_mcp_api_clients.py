"""Tests for Stage 2.1.1 — POST/DELETE /api/mcp/clients endpoints.

Run:
    .venv/bin/python tests/test_mcp_api_clients.py

The MCP transport stack (stdio_client / streamablehttp_client) is mocked at
``_connect_one`` / ``_disconnect_one`` so tests stay hermetic (no npx, no
network). The route handlers themselves and ``_ClientHandle`` state
mutation are real.
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

# Patch DB url before any backend import
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yaml
from fastapi import HTTPException

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from backend.database import Base
import backend.database as _db_module

TEST_ENGINE = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
TEST_SESSION = sessionmaker(
    TEST_ENGINE, class_=AsyncSession, expire_on_commit=False,
)
_db_module.engine = TEST_ENGINE
_db_module.AsyncSessionLocal = TEST_SESSION

from backend.database import models  # noqa: F401

import backend.routes.mcp_api as _mcp_api
import backend.mcp.client as _mcp_client
import backend.mcp.credentials as _creds
import backend.mcp.tool_state as _tool_state


PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, cond: bool, detail: str = "") -> None:
    tag = PASS if cond else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, cond))


# ---------------------------------------------------------------------------
# Test infrastructure
# ---------------------------------------------------------------------------

async def setup_db() -> None:
    """Build tables for mcp_credentials + mcp_client_state + mcp_tool_state."""
    async with TEST_ENGINE.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Tables ORM doesn't know about — chunk 7 / UX-001 raw migrations
        from sqlalchemy import text
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS mcp_credentials (
              server_name TEXT NOT NULL,
              key_name    TEXT NOT NULL,
              value       TEXT NOT NULL,
              updated_at  TIMESTAMP,
              PRIMARY KEY (server_name, key_name)
            )
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS mcp_client_state (
              server_name TEXT PRIMARY KEY,
              enabled     INTEGER NOT NULL,
              updated_at  TIMESTAMP
            )
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS mcp_tool_state (
              server_name TEXT NOT NULL,
              tool_name   TEXT NOT NULL,
              enabled     INTEGER NOT NULL,
              updated_at  TIMESTAMP,
              PRIMARY KEY (server_name, tool_name)
            )
        """))


def install_patches(tmp_config: Path) -> dict:
    """Monkey-patch:
       - ``_CONFIG_PATH`` → tmp file
       - ``_connect_one`` → marks handle.connected=True with fake tool_count
       - ``_disconnect_one`` → no-op cleanup

    Returns dict of {orig_*: callable} for uninstall.
    """
    orig = {
        "config_path":   _mcp_api._CONFIG_PATH,
        "connect_one":   _mcp_client._connect_one,
        "disconnect_one": _mcp_client._disconnect_one,
    }
    _mcp_api._CONFIG_PATH = tmp_config

    async def fake_connect_one(handle):
        handle.connected = True
        handle.tool_count = 3  # arbitrary fake
        handle.tools = [
            {"name": "fake_tool_a", "description": "fake", "enabled": True},
            {"name": "fake_tool_b", "description": "fake", "enabled": True},
            {"name": "fake_tool_c", "description": "fake", "enabled": True},
        ]
        handle.last_error = None

    async def fake_disconnect_one(handle):
        handle.connected = False
        handle.tool_count = 0
        handle.tools = []
        handle.session = None
        handle.exit_stack = None

    _mcp_client._connect_one = fake_connect_one
    _mcp_client._disconnect_one = fake_disconnect_one
    return orig


def uninstall_patches(orig: dict) -> None:
    _mcp_api._CONFIG_PATH = orig["config_path"]
    _mcp_client._connect_one = orig["connect_one"]
    _mcp_client._disconnect_one = orig["disconnect_one"]


def reset_state() -> None:
    """Clear _clients + reset yaml between tests."""
    _mcp_client._clients.clear()


# ---------------------------------------------------------------------------
# 1. POST new stdio server
# ---------------------------------------------------------------------------

async def test_post_new_stdio() -> None:
    print("\n[test_post_new_stdio]")
    with tempfile.TemporaryDirectory() as td:
        config = Path(td) / "config.yaml"
        config.write_text("default_user_id: default\n", encoding="utf-8")
        orig = install_patches(config)
        reset_state()
        try:
            body = _mcp_api.CreateClientBody(
                name="my-fs",
                description="local filesystem",
                transport="stdio",
                command="npx",
                args=["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
                env={},
                enabled=True,
            )
            resp = await _mcp_api.create_client(body)
            check("returns 201-shape response", resp.name == "my-fs")
            check("connected=true after fake _connect_one",
                  resp.connected is True)
            check("tool_count surfaced", resp.tool_count == 3)
            check("error is None", resp.error is None)
            check("registered in _clients dict",
                  "my-fs" in _mcp_client._clients)

            # Verify yaml file contains the new entry
            with open(config, encoding="utf-8") as f:
                cfg = yaml.safe_load(f)
            entry = (cfg.get("mcp_clients") or {}).get("my-fs")
            check("yaml entry persisted", entry is not None)
            check("yaml transport correct",
                  entry and entry.get("transport") == "stdio")
            check("yaml command correct",
                  entry and entry.get("command") == "npx")
            check("yaml args list",
                  entry and entry.get("args") == [
                      "-y", "@modelcontextprotocol/server-filesystem", "/tmp",
                  ])

            # DB override row written
            override = await _creds.get_enabled_override("my-fs")
            check("DB enable override = True", override is True)
        finally:
            uninstall_patches(orig)


# ---------------------------------------------------------------------------
# 2. POST new http server
# ---------------------------------------------------------------------------

async def test_post_new_http() -> None:
    print("\n[test_post_new_http]")
    with tempfile.TemporaryDirectory() as td:
        config = Path(td) / "config.yaml"
        config.write_text("default_user_id: default\n", encoding="utf-8")
        orig = install_patches(config)
        reset_state()
        try:
            body = _mcp_api.CreateClientBody(
                name="remote-mcp",
                transport="http",
                url="https://example.com/mcp",
                enabled=True,
            )
            resp = await _mcp_api.create_client(body)
            check("response transport=http", resp.transport == "http")
            check("connected=true", resp.connected is True)

            with open(config, encoding="utf-8") as f:
                cfg = yaml.safe_load(f)
            entry = (cfg.get("mcp_clients") or {}).get("remote-mcp")
            check("yaml url persisted",
                  entry and entry.get("url") == "https://example.com/mcp")
            check("yaml has no 'command' for http entry",
                  entry and "command" not in entry)
        finally:
            uninstall_patches(orig)


# ---------------------------------------------------------------------------
# 3. POST duplicate name → 409
# ---------------------------------------------------------------------------

async def test_post_duplicate_name() -> None:
    print("\n[test_post_duplicate_name — 409 on conflict]")
    with tempfile.TemporaryDirectory() as td:
        config = Path(td) / "config.yaml"
        config.write_text("", encoding="utf-8")
        orig = install_patches(config)
        reset_state()
        try:
            body = _mcp_api.CreateClientBody(
                name="dup", transport="stdio", command="echo",
            )
            await _mcp_api.create_client(body)

            # Second POST same name
            raised_code = None
            try:
                await _mcp_api.create_client(body)
            except HTTPException as exc:
                raised_code = exc.status_code
            check("second POST raised HTTPException", raised_code is not None)
            check("status 409", raised_code == 409)
        finally:
            uninstall_patches(orig)


# ---------------------------------------------------------------------------
# 4. stdio without command → 422
# ---------------------------------------------------------------------------

async def test_post_missing_command_for_stdio() -> None:
    print("\n[test_post_missing_command_for_stdio — 422]")
    with tempfile.TemporaryDirectory() as td:
        config = Path(td) / "config.yaml"
        config.write_text("", encoding="utf-8")
        orig = install_patches(config)
        reset_state()
        try:
            body = _mcp_api.CreateClientBody(
                name="bad-stdio", transport="stdio",
                # command omitted
            )
            raised_code = None
            try:
                await _mcp_api.create_client(body)
            except HTTPException as exc:
                raised_code = exc.status_code
            check("422 on missing command", raised_code == 422)
            check("nothing leaked into _clients",
                  "bad-stdio" not in _mcp_client._clients)
        finally:
            uninstall_patches(orig)


# ---------------------------------------------------------------------------
# 5. http without url → 422
# ---------------------------------------------------------------------------

async def test_post_missing_url_for_http() -> None:
    print("\n[test_post_missing_url_for_http — 422]")
    with tempfile.TemporaryDirectory() as td:
        config = Path(td) / "config.yaml"
        config.write_text("", encoding="utf-8")
        orig = install_patches(config)
        reset_state()
        try:
            body = _mcp_api.CreateClientBody(
                name="bad-http", transport="http",
                # url omitted
            )
            raised_code = None
            try:
                await _mcp_api.create_client(body)
            except HTTPException as exc:
                raised_code = exc.status_code
            check("422 on missing url", raised_code == 422)
            check("nothing leaked into _clients",
                  "bad-http" not in _mcp_client._clients)
        finally:
            uninstall_patches(orig)


# ---------------------------------------------------------------------------
# 6. DELETE existing
# ---------------------------------------------------------------------------

async def test_delete_existing() -> None:
    print("\n[test_delete_existing]")
    with tempfile.TemporaryDirectory() as td:
        config = Path(td) / "config.yaml"
        config.write_text("", encoding="utf-8")
        orig = install_patches(config)
        reset_state()
        try:
            # Create then delete
            await _mcp_api.create_client(_mcp_api.CreateClientBody(
                name="to-delete", transport="stdio", command="echo",
            ))
            check("created in _clients", "to-delete" in _mcp_client._clients)

            # Seed some credentials + tool_state to verify cleanup
            await _creds.upsert("to-delete", "API_KEY", "secret_value")
            await _tool_state.set_enabled("to-delete", "fake_tool_a", False)

            resp = await _mcp_api.delete_client("to-delete")
            check("delete returned status=ok", resp.status == "ok")
            check("removed from _clients",
                  "to-delete" not in _mcp_client._clients)

            with open(config, encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
            check("yaml entry pruned",
                  "to-delete" not in (cfg.get("mcp_clients") or {}))

            # DB cleanup — credentials + tool_state both wiped
            creds_after = await _creds.list_keys("to-delete")
            check("credentials wiped", creds_after == [])
            overrides_after = await _tool_state.list_overrides("to-delete")
            check("tool_state wiped", overrides_after == {})
        finally:
            uninstall_patches(orig)


# ---------------------------------------------------------------------------
# 7. DELETE nonexistent → 404
# ---------------------------------------------------------------------------

async def test_delete_nonexistent() -> None:
    print("\n[test_delete_nonexistent — 404]")
    with tempfile.TemporaryDirectory() as td:
        config = Path(td) / "config.yaml"
        config.write_text("", encoding="utf-8")
        orig = install_patches(config)
        reset_state()
        try:
            raised_code = None
            try:
                await _mcp_api.delete_client("ghost")
            except HTTPException as exc:
                raised_code = exc.status_code
            check("404 on nonexistent", raised_code == 404)
        finally:
            uninstall_patches(orig)


# ---------------------------------------------------------------------------
# 8. Concurrent POST with different names — atomic helper lock works
# ---------------------------------------------------------------------------

async def test_concurrent_post_different_names() -> None:
    print("\n[test_concurrent_post_different_names — both land cleanly]")
    with tempfile.TemporaryDirectory() as td:
        config = Path(td) / "config.yaml"
        config.write_text("default_user_id: default\n", encoding="utf-8")
        orig = install_patches(config)
        reset_state()
        try:
            body_a = _mcp_api.CreateClientBody(
                name="parallel-a", transport="stdio", command="echo",
            )
            body_b = _mcp_api.CreateClientBody(
                name="parallel-b", transport="stdio", command="echo",
            )
            results_pair = await asyncio.gather(
                _mcp_api.create_client(body_a),
                _mcp_api.create_client(body_b),
            )
            check("both responses returned", len(results_pair) == 2)
            check("both names in _clients",
                  "parallel-a" in _mcp_client._clients
                  and "parallel-b" in _mcp_client._clients)

            with open(config, encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
            clients_in_yaml = (cfg.get("mcp_clients") or {})
            check("both yaml entries present (no lost write)",
                  "parallel-a" in clients_in_yaml
                  and "parallel-b" in clients_in_yaml,
                  f"yaml has: {list(clients_in_yaml.keys())}")
            check("default_user_id preserved (not stomped)",
                  cfg.get("default_user_id") == "default")
        finally:
            uninstall_patches(orig)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

async def main() -> int:
    await setup_db()
    await test_post_new_stdio()
    await test_post_new_http()
    await test_post_duplicate_name()
    await test_post_missing_command_for_stdio()
    await test_post_missing_url_for_http()
    await test_delete_existing()
    await test_delete_nonexistent()
    await test_concurrent_post_different_names()

    print(f"\n=== summary: {sum(1 for _, ok in results if ok)}/{len(results)} passed ===")
    failed = [name for name, ok in results if not ok]
    if failed:
        for f in failed:
            print(f"  FAIL: {f}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
