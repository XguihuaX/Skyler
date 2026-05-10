"""v3.5 chunk 5a — characters_api PATCH / POST 支持 background_path。

测试用高位 character_id (700+) + 显式 cleanup，避免污染主表。
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from backend.database import engine, init_db
from backend.database.migrations.v3_5_chunk5a_character_background import (
    run_migration,
)
from backend.routes.characters_api import router

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []

# 高位 id，避免冲突 (Momo=1, 八重=2, 已有 character_state test 用 600 段)
TEST_ID_START = 700


def check(name: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return app


async def _setup_db():
    await init_db()
    await run_migration()
    # 清掉本测试段的残留——按 id 范围 + 名字前缀 _bg_test_* 双清
    # （test_create_with_background 用 POST 让 DB 分配 id，可能落在 700+ 段外）
    async with engine.begin() as conn:
        await conn.execute(text(
            "DELETE FROM characters WHERE id >= :i AND id < :j"
        ), {"i": TEST_ID_START, "j": TEST_ID_START + 100})
        await conn.execute(text(
            "DELETE FROM characters WHERE name LIKE '_bg_test_%'"
        ))


async def _cleanup_db():
    async with engine.begin() as conn:
        await conn.execute(text(
            "DELETE FROM characters WHERE id >= :i AND id < :j"
        ), {"i": TEST_ID_START, "j": TEST_ID_START + 100})
        await conn.execute(text(
            "DELETE FROM characters WHERE name LIKE '_bg_test_%'"
        ))


# ---------------------------------------------------------------------------
# 1. POST /api/characters/create 接受 background_path
# ---------------------------------------------------------------------------

def test_create_with_background():
    print("\n[characters POST — 创建时传 background_path]")
    asyncio.get_event_loop().run_until_complete(_setup_db())
    client = TestClient(_build_app())
    r = client.post("/api/characters/create", json={
        "name": "_bg_test_create",
        "persona": "test",
        "background_path": "/backgrounds/test.mp4",
    })
    check("status 201", r.status_code == 201, f"got {r.status_code}")
    data = r.json()
    check("background_path echoed",
          data.get("background_path") == "/backgrounds/test.mp4",
          f"got {data.get('background_path')!r}")


# ---------------------------------------------------------------------------
# 2. PATCH 设置 background_path → 读回一致
# ---------------------------------------------------------------------------

def test_patch_set_background():
    print("\n[characters PATCH — set background_path]")
    asyncio.get_event_loop().run_until_complete(_setup_db())
    client = TestClient(_build_app())
    # 直接 SQL 插一行避免与 create test 串扰
    asyncio.get_event_loop().run_until_complete(_insert_test_char(TEST_ID_START + 1, "_bg_test_patch"))

    r = client.patch(f"/api/characters/{TEST_ID_START + 1}", json={
        "background_path": "/backgrounds/shrine.jpg",
    })
    check("status 200", r.status_code == 200, f"got {r.status_code}")
    check("background_path set",
          r.json().get("background_path") == "/backgrounds/shrine.jpg")

    # GET 验证持久化
    list_r = client.get("/api/characters/list")
    rows = list_r.json()
    target = next((x for x in rows if x["id"] == TEST_ID_START + 1), None)
    check("background_path persisted",
          target is not None
          and target["background_path"] == "/backgrounds/shrine.jpg")


# ---------------------------------------------------------------------------
# 3. PATCH 清除（None / 空串都视为 NULL）
# ---------------------------------------------------------------------------

def test_patch_clear_background():
    print("\n[characters PATCH — None / 空串 → 落库 NULL]")
    asyncio.get_event_loop().run_until_complete(_setup_db())
    asyncio.get_event_loop().run_until_complete(_insert_test_char(TEST_ID_START + 2, "_bg_test_clear"))
    client = TestClient(_build_app())

    # 先 set
    client.patch(f"/api/characters/{TEST_ID_START + 2}", json={
        "background_path": "/backgrounds/x.jpg",
    })

    # null 清除
    r = client.patch(f"/api/characters/{TEST_ID_START + 2}", json={
        "background_path": None,
    })
    check("None → NULL", r.json().get("background_path") is None,
          f"got {r.json().get('background_path')!r}")

    # 重 set
    client.patch(f"/api/characters/{TEST_ID_START + 2}", json={
        "background_path": "/backgrounds/x.jpg",
    })

    # 空串清除
    r = client.patch(f"/api/characters/{TEST_ID_START + 2}", json={
        "background_path": "",
    })
    check("empty string → NULL",
          r.json().get("background_path") is None,
          f"got {r.json().get('background_path')!r}")


# ---------------------------------------------------------------------------
# 4. background_path 不变（exclude_unset）
# ---------------------------------------------------------------------------

def test_patch_other_fields_dont_clear_background():
    print("\n[characters PATCH — partial update 不动 background_path]")
    asyncio.get_event_loop().run_until_complete(_setup_db())
    asyncio.get_event_loop().run_until_complete(_insert_test_char(TEST_ID_START + 3, "_bg_test_partial"))
    client = TestClient(_build_app())

    client.patch(f"/api/characters/{TEST_ID_START + 3}", json={
        "background_path": "/backgrounds/keep.mp4",
    })
    # 只改 persona
    r = client.patch(f"/api/characters/{TEST_ID_START + 3}", json={
        "persona": "new persona",
    })
    check("persona updated", r.json().get("persona") == "new persona")
    check("background_path preserved",
          r.json().get("background_path") == "/backgrounds/keep.mp4",
          f"got {r.json().get('background_path')!r}")


# ---------------------------------------------------------------------------
# 5. GET list 返回 background_path 字段
# ---------------------------------------------------------------------------

def test_list_includes_background_field():
    print("\n[characters GET list — 字段 schema 含 background_path]")
    asyncio.get_event_loop().run_until_complete(_setup_db())
    asyncio.get_event_loop().run_until_complete(_insert_test_char(TEST_ID_START + 4, "_bg_test_list"))
    client = TestClient(_build_app())

    r = client.get("/api/characters/list")
    check("status 200", r.status_code == 200)
    rows = r.json()
    target = next((x for x in rows if x["id"] == TEST_ID_START + 4), None)
    check("target row in list", target is not None)
    check("background_path key present (None default)",
          target is not None and "background_path" in target
          and target["background_path"] is None)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

async def _insert_test_char(char_id: int, name: str):
    async with engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO characters (id, name, persona) "
            "VALUES (:id, :name, :persona)"
        ), {"id": char_id, "name": name, "persona": "test"})


def main():
    try:
        test_create_with_background()
        test_patch_set_background()
        test_patch_clear_background()
        test_patch_other_fields_dont_clear_background()
        test_list_includes_background_field()
    finally:
        asyncio.get_event_loop().run_until_complete(_cleanup_db())

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
