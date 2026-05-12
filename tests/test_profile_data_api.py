"""v3.5 chunk 11 — profile_data REST API endpoints。

GET / PATCH / DELETE / POST regenerate 四 endpoint 端到端 via FastAPI
TestClient。
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.database import AsyncSessionLocal, engine, Base
from backend.database.models import User
from backend.routes.users_api import router as users_router

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))


TEST_USER = "chunk11_profile_data_test"


async def _setup_user(initial_data: dict | None = None) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSessionLocal() as session:
        from sqlalchemy import select
        u = (await session.execute(
            select(User).where(User.user_id == TEST_USER)
        )).scalar_one_or_none()
        if u is None:
            u = User(user_id=TEST_USER, user_name=TEST_USER)
            session.add(u)
        u.profile_data = (
            json.dumps(initial_data, ensure_ascii=False)
            if initial_data is not None else None
        )
        await session.commit()


async def _teardown() -> None:
    async with AsyncSessionLocal() as session:
        from sqlalchemy import delete
        await session.execute(delete(User).where(User.user_id == TEST_USER))
        await session.commit()


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(users_router, prefix="/api")
    return TestClient(app)


# ---------------------------------------------------------------------------
# GET
# ---------------------------------------------------------------------------


def test_get_returns_null_when_unset():
    print("\n[GET] profile_data NULL → null")
    asyncio.run(_setup_user(None))
    r = _client().get(f"/api/users/{TEST_USER}/profile_data")
    check("status 200", r.status_code == 200)
    check("profile_data is None", r.json().get("profile_data") is None)


def test_get_returns_dict_when_set():
    print("\n[GET] profile_data 含 JSON → dict")
    seed = {
        "profession": "工程师", "current_projects": ["A"],
        "communication_style": None, "interests": [],
        "language_preferences": None, "active_hours": None,
        "recurring_topics": [],
    }
    asyncio.run(_setup_user(seed))
    r = _client().get(f"/api/users/{TEST_USER}/profile_data")
    check("status 200", r.status_code == 200)
    check("profile_data == seed", r.json().get("profile_data") == seed)


def test_get_404_when_user_missing():
    print("\n[GET] user 不存在 → 404")
    r = _client().get("/api/users/no_such_user_chunk11/profile_data")
    check("status 404", r.status_code == 404)


# ---------------------------------------------------------------------------
# PATCH
# ---------------------------------------------------------------------------


def test_patch_partial_merge_string_field():
    print("\n[PATCH] 单 string 字段 inline update → 其他字段不动")
    seed = {
        "profession": None, "current_projects": [],
        "communication_style": "旧 style", "interests": [],
        "language_preferences": None, "active_hours": None,
        "recurring_topics": [],
    }
    asyncio.run(_setup_user(seed))
    r = _client().patch(
        f"/api/users/{TEST_USER}/profile_data",
        json={"profession": "程序员"},
    )
    check("status 200", r.status_code == 200)
    out = r.json().get("profile_data") or {}
    check("profession 更新", out.get("profession") == "程序员")
    check("communication_style 保留旧值",
          out.get("communication_style") == "旧 style")


def test_patch_list_replace():
    print("\n[PATCH] list 字段整体替换")
    asyncio.run(_setup_user({
        "profession": None, "current_projects": ["A", "B"],
        "communication_style": None, "interests": [],
        "language_preferences": None, "active_hours": None,
        "recurring_topics": [],
    }))
    r = _client().patch(
        f"/api/users/{TEST_USER}/profile_data",
        json={"current_projects": ["C"]},
    )
    check("status 200", r.status_code == 200)
    out = r.json().get("profile_data") or {}
    check("list 替换为 [C]",
          out.get("current_projects") == ["C"])


def test_patch_clear_list_with_empty():
    print("\n[PATCH] 显式 [] 清空 list")
    asyncio.run(_setup_user({
        "profession": None, "current_projects": ["A"],
        "communication_style": None, "interests": [],
        "language_preferences": None, "active_hours": None,
        "recurring_topics": [],
    }))
    r = _client().patch(
        f"/api/users/{TEST_USER}/profile_data",
        json={"current_projects": []},
    )
    out = r.json().get("profile_data") or {}
    check("空 list 已清", out.get("current_projects") == [])


def test_patch_sanitizes_suspicious_input():
    print("\n[PATCH] 写入含 <netease.x> 可疑 tag → sanitize")
    asyncio.run(_setup_user(None))
    r = _client().patch(
        f"/api/users/{TEST_USER}/profile_data",
        json={"profession": "程序员 <netease.daily_recommend/>"},
    )
    check("status 200", r.status_code == 200)
    saved = (r.json().get("profile_data") or {}).get("profession") or ""
    check("可疑 tag 已剥",
          "<netease." not in saved)
    check("正文保留", "程序员" in saved)


def test_patch_rejects_extra_field():
    print("\n[PATCH] schema 外字段 → 422")
    asyncio.run(_setup_user(None))
    r = _client().patch(
        f"/api/users/{TEST_USER}/profile_data",
        json={"evil_field": "x"},
    )
    check("status 422", r.status_code == 422)


def test_patch_404_when_user_missing():
    print("\n[PATCH] user 不存在 → 404")
    r = _client().patch(
        "/api/users/no_such_user_chunk11/profile_data",
        json={"profession": "x"},
    )
    check("status 404", r.status_code == 404)


# ---------------------------------------------------------------------------
# DELETE
# ---------------------------------------------------------------------------


def test_delete_clears_profile_data():
    print("\n[DELETE] 清空 → 204 + GET 后 None")
    asyncio.run(_setup_user({
        "profession": "X", "current_projects": [],
        "communication_style": None, "interests": [],
        "language_preferences": None, "active_hours": None,
        "recurring_topics": [],
    }))
    c = _client()
    r = c.delete(f"/api/users/{TEST_USER}/profile_data")
    check("status 204", r.status_code == 204)
    g = c.get(f"/api/users/{TEST_USER}/profile_data")
    check("GET 后 profile_data is None",
          g.json().get("profile_data") is None)


def test_delete_404_when_user_missing():
    print("\n[DELETE] user 不存在 → 404")
    r = _client().delete("/api/users/no_such_user_chunk11/profile_data")
    check("status 404", r.status_code == 404)


# ---------------------------------------------------------------------------
# POST regenerate (mock _regenerate_profile_data)
# ---------------------------------------------------------------------------


def test_regen_incremental_default_mode():
    print("\n[POST regen] body 缺省 → mode=incremental")
    asyncio.run(_setup_user(None))
    captured = {}

    async def fake_regen(user_id, *, mode):
        captured["mode"] = mode
        async with AsyncSessionLocal() as session:
            from sqlalchemy import select
            u = (await session.execute(
                select(User).where(User.user_id == user_id)
            )).scalar_one_or_none()
            new = {
                "profession": "新职业", "current_projects": [],
                "communication_style": None, "interests": [],
                "language_preferences": None, "active_hours": None,
                "recurring_topics": [],
            }
            u.profile_data = json.dumps(new, ensure_ascii=False)
            await session.commit()
        return ("regenerated", new)

    with patch("backend.services.profile_regen._regenerate_profile_data",
               new=fake_regen):
        r = _client().post(
            f"/api/users/{TEST_USER}/profile_data/regenerate"
        )
    check("status 200", r.status_code == 200)
    data = r.json()
    check("status == regenerated", data.get("status") == "regenerated")
    check("mode 传 manual_incremental",
          captured.get("mode") == "manual_incremental")
    check("profile_data 返新值",
          (data.get("profile_data") or {}).get("profession") == "新职业")


def test_regen_reset_mode():
    print("\n[POST regen] {\"mode\": \"reset\"} → manual_reset")
    asyncio.run(_setup_user(None))
    captured = {}

    async def fake_regen(user_id, *, mode):
        captured["mode"] = mode
        return ("regenerated", None)

    with patch("backend.services.profile_regen._regenerate_profile_data",
               new=fake_regen):
        r = _client().post(
            f"/api/users/{TEST_USER}/profile_data/regenerate",
            json={"mode": "reset"},
        )
    check("status 200", r.status_code == 200)
    check("mode 传 manual_reset",
          captured.get("mode") == "manual_reset")


def test_regen_invalid_mode_422():
    print("\n[POST regen] 非法 mode → 422")
    asyncio.run(_setup_user(None))
    r = _client().post(
        f"/api/users/{TEST_USER}/profile_data/regenerate",
        json={"mode": "bogus"},
    )
    check("status 422", r.status_code == 422)


def test_regen_skip_returns_detail():
    print("\n[POST regen] skip 状态 → 200 + detail 非空")
    asyncio.run(_setup_user(None))

    async def fake_regen(user_id, *, mode):
        return ("skip_too_few_user_msgs", None)

    with patch("backend.services.profile_regen._regenerate_profile_data",
               new=fake_regen):
        r = _client().post(
            f"/api/users/{TEST_USER}/profile_data/regenerate"
        )
    check("status 200", r.status_code == 200)
    data = r.json()
    check("status == skip_too_few_user_msgs",
          data.get("status") == "skip_too_few_user_msgs")
    check("detail 非空", bool(data.get("detail")))


def test_regen_404_when_user_missing():
    print("\n[POST regen] user 不存在 → 404")
    r = _client().post(
        "/api/users/no_such_user_chunk11/profile_data/regenerate"
    )
    check("status 404", r.status_code == 404)


# ---------------------------------------------------------------------------
# Deprecation log on chunk 9 endpoints
# ---------------------------------------------------------------------------


def test_chunk9_legacy_endpoints_log_deprecation():
    print("\n[deprecation] chunk 9 legacy endpoints log warning")
    import backend.routes.users_api as mod
    src = open(mod.__file__, "r", encoding="utf-8").read()
    check("PATCH profile_summary 有 deprecated 警告",
          "[deprecated] PATCH /users/%s/profile_summary" in src)
    check("DELETE profile_summary 有 deprecated 警告",
          "[deprecated] DELETE /users/%s/profile_summary" in src)
    check("POST profile_summary/regenerate 有 deprecated 警告",
          "[deprecated] POST /users/%s/profile_summary/regenerate" in src)


# ---------------------------------------------------------------------------
# cleanup
# ---------------------------------------------------------------------------


def test_cleanup():
    print("\n[cleanup]")
    asyncio.run(_teardown())
    check("teardown OK", True)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main():
    test_get_returns_null_when_unset()
    test_get_returns_dict_when_set()
    test_get_404_when_user_missing()
    test_patch_partial_merge_string_field()
    test_patch_list_replace()
    test_patch_clear_list_with_empty()
    test_patch_sanitizes_suspicious_input()
    test_patch_rejects_extra_field()
    test_patch_404_when_user_missing()
    test_delete_clears_profile_data()
    test_delete_404_when_user_missing()
    test_regen_incremental_default_mode()
    test_regen_reset_mode()
    test_regen_invalid_mode_422()
    test_regen_skip_returns_detail()
    test_regen_404_when_user_missing()
    test_chunk9_legacy_endpoints_log_deprecation()
    test_cleanup()

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
