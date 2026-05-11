"""v3.5 chunk 9 Part 2 — profile_summary REST API endpoints。

新加 3 个 endpoint:
  * PATCH  /api/users/{user_id}/profile_summary             —— 用户手动编辑
  * DELETE /api/users/{user_id}/profile_summary             —— 已存在，UI 现在暴露
  * POST   /api/users/{user_id}/profile_summary/regenerate  —— 同步 LLM 重算

测试用 FastAPI TestClient 端到端调用，mock 最底层 LLM（``_compute_profile_summary``
真路径会调真 LLM），断 status code + 返回结构。
"""
from __future__ import annotations

import asyncio
import os
import sys
from types import SimpleNamespace
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


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

TEST_USER = "chunk9_profile_test_user"


async def _setup_user(initial_summary: str | None = "初始 profile") -> None:
    """Ensure test user exists; reset profile_summary to known state."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSessionLocal() as session:
        from sqlalchemy import select
        u = (await session.execute(
            select(User).where(User.user_id == TEST_USER)
        )).scalar_one_or_none()
        if u is None:
            u = User(user_id=TEST_USER, user_name=TEST_USER,
                     profile_summary=initial_summary)
            session.add(u)
        else:
            u.profile_summary = initial_summary
        await session.commit()


async def _teardown_user() -> None:
    async with AsyncSessionLocal() as session:
        from sqlalchemy import delete
        await session.execute(delete(User).where(User.user_id == TEST_USER))
        await session.commit()


def _make_client() -> TestClient:
    app = FastAPI()
    app.include_router(users_router, prefix="/api")
    return TestClient(app)


# ---------------------------------------------------------------------------
# PATCH /users/{user_id}/profile_summary
# ---------------------------------------------------------------------------


def test_patch_summary_saves_clean_content():
    print("\n[PATCH] 写干净内容 → 200 + profile_summary 更新")
    asyncio.run(_setup_user("旧 profile"))
    client = _make_client()
    new = "用户喜欢简短回复，倾向偏感性表达，对工作话题有所抗拒。"
    r = client.patch(
        f"/api/users/{TEST_USER}/profile_summary",
        json={"summary": new},
    )
    check("status 200", r.status_code == 200)
    data = r.json()
    check("返回新 summary", data.get("profile_summary") == new)


def test_patch_summary_sanitizes_suspicious_input():
    print("\n[PATCH] 写含 <netease.x> 可疑 tag → sanitize 后保存")
    asyncio.run(_setup_user("初始"))
    client = _make_client()
    dirty = "用户喜欢 <netease.daily_recommend></netease.daily_recommend> 听歌。"
    r = client.patch(
        f"/api/users/{TEST_USER}/profile_summary",
        json={"summary": dirty},
    )
    check("status 200", r.status_code == 200)
    saved = r.json().get("profile_summary") or ""
    check("可疑 tag 已剥",
          "<netease." not in saved and "</netease." not in saved)
    check("正文保留", "用户喜欢" in saved and "听歌" in saved)


def test_patch_summary_user_not_found():
    print("\n[PATCH] 不存在 user → 404")
    client = _make_client()
    r = client.patch(
        "/api/users/nonexistent_user_chunk9/profile_summary",
        json={"summary": "x"},
    )
    check("status 404", r.status_code == 404)


# ---------------------------------------------------------------------------
# DELETE /users/{user_id}/profile_summary
# ---------------------------------------------------------------------------


def test_delete_summary_clears_to_null():
    print("\n[DELETE] 清空 profile_summary → NULL")
    asyncio.run(_setup_user("待清的 profile"))
    client = _make_client()
    r = client.delete(f"/api/users/{TEST_USER}/profile_summary")
    check("status 204", r.status_code == 204)
    # GET via /profile to verify NULL
    g = client.get(f"/api/users/{TEST_USER}/profile")
    check("GET 后 profile_summary == None",
          g.json().get("profile_summary") is None)


# ---------------------------------------------------------------------------
# POST /users/{user_id}/profile_summary/regenerate
# ---------------------------------------------------------------------------


def test_regenerate_calls_compute_returns_new_summary():
    print("\n[POST regen] mock _compute → status=regenerated + 新 summary")
    asyncio.run(_setup_user("旧 profile"))
    client = _make_client()

    async def fake_compute(user_id, *, min_user_rows=1):
        # 模拟成功：写库 + 返新 summary
        async with AsyncSessionLocal() as session:
            from sqlalchemy import select
            u = (await session.execute(
                select(User).where(User.user_id == user_id)
            )).scalar_one_or_none()
            new = "regenerate 后的全新 profile 内容用来测试。" * 3
            u.profile_summary = new
            await session.commit()
            return ("regenerated", new)

    with patch("backend.routes.ws._compute_profile_summary",
               new=fake_compute):
        r = client.post(
            f"/api/users/{TEST_USER}/profile_summary/regenerate"
        )
    check("status 200", r.status_code == 200)
    data = r.json()
    check("status field == regenerated", data.get("status") == "regenerated")
    check("profile_summary 是新的",
          (data.get("profile_summary") or "").startswith("regenerate"))


def test_regenerate_skip_too_few_rows_returns_status_and_detail():
    print("\n[POST regen] mock _compute skip → status + detail，旧 profile 保留")
    asyncio.run(_setup_user("旧 profile 被保留"))
    client = _make_client()

    async def fake_compute(user_id, *, min_user_rows=1):
        return ("skip_too_few_rows", None)

    with patch("backend.routes.ws._compute_profile_summary",
               new=fake_compute):
        r = client.post(
            f"/api/users/{TEST_USER}/profile_summary/regenerate"
        )
    check("status 200", r.status_code == 200)
    data = r.json()
    check("status field == skip_too_few_rows",
          data.get("status") == "skip_too_few_rows")
    check("detail 非空", bool(data.get("detail")))
    check("profile_summary 保留旧值",
          data.get("profile_summary") == "旧 profile 被保留")


def test_regenerate_user_not_found():
    print("\n[POST regen] 不存在 user → 404")
    client = _make_client()
    r = client.post(
        "/api/users/no_such_user_chunk9/profile_summary/regenerate"
    )
    check("status 404", r.status_code == 404)


# ---------------------------------------------------------------------------
# cleanup
# ---------------------------------------------------------------------------


def test_cleanup():
    print("\n[cleanup]")
    asyncio.run(_teardown_user())
    check("teardown OK", True)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main():
    test_patch_summary_saves_clean_content()
    test_patch_summary_sanitizes_suspicious_input()
    test_patch_summary_user_not_found()
    test_delete_summary_clears_to_null()
    test_regenerate_calls_compute_returns_new_summary()
    test_regenerate_skip_too_few_rows_returns_status_and_detail()
    test_regenerate_user_not_found()
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
