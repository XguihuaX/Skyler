"""v3.5 chunk 11 — cron profile_daily_regenerate + 50-turn 删除 验证。"""
from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.services import profile_regen as pr

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))


# ---------------------------------------------------------------------------
# 1. profile_daily_regenerate 跑全 user
# ---------------------------------------------------------------------------


async def test_daily_iterates_all_users():
    print("\n[cron] profile_daily_regenerate 跑全 user + 各自 try/except")
    seen_users: list[str] = []

    async def fake_regen(user_id, *, mode):
        seen_users.append(user_id)
        return ("regenerated", {"profession": "X"})

    # Mock DB user list
    class FakeRow:
        def __init__(self, uid): self._uid = uid
        def __getitem__(self, i): return self._uid

    class FakeResult:
        def __init__(self, rows): self._rows = rows
        def all(self): return self._rows

    class FakeSession:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def execute(self, q): return FakeResult([("u1",), ("u2",), ("u3",)])

    def make_session():
        return FakeSession()

    with patch.object(pr, "AsyncSessionLocal", side_effect=make_session), \
         patch.object(pr, "_regenerate_profile_data", new=fake_regen):
        await pr.profile_daily_regenerate()
    check("跑过 3 个 user", sorted(seen_users) == ["u1", "u2", "u3"])


async def test_daily_one_user_failure_does_not_block_others():
    print("\n[cron] 一个 user 抛 → 其他继续")
    visited: list[str] = []

    async def fake_regen(user_id, *, mode):
        visited.append(user_id)
        if user_id == "u2":
            raise RuntimeError("boom")
        return ("regenerated", {})

    class FakeResult:
        def all(self): return [("u1",), ("u2",), ("u3",)]

    class FakeSession:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def execute(self, q): return FakeResult()

    with patch.object(pr, "AsyncSessionLocal", side_effect=lambda: FakeSession()), \
         patch.object(pr, "_regenerate_profile_data", new=fake_regen):
        await pr.profile_daily_regenerate()
    check("3 user 都 visited", sorted(visited) == ["u1", "u2", "u3"])


# ---------------------------------------------------------------------------
# 2. 50-turn 计数器已删除（grep ws.py 验证）
# ---------------------------------------------------------------------------


def test_50_turn_counter_removed():
    print("\n[remove] ws.py turn_count 计数器 / threshold / bump 函数都已删")
    import backend.routes.ws as ws_mod
    src = open(ws_mod.__file__, "r", encoding="utf-8").read()
    check("turn_count_per_user 变量定义已删",
          "turn_count_per_user: dict[str, int]" not in src)
    check("PROFILE_SUMMARY_TURN_THRESHOLD 常量已删",
          "PROFILE_SUMMARY_TURN_THRESHOLD = " not in src)
    check("def _bump_turn_and_maybe_regenerate 函数定义已删",
          "def _bump_turn_and_maybe_regenerate" not in src)
    check("_bump_turn_and_maybe_regenerate(user_id) 调用已删",
          "_bump_turn_and_maybe_regenerate(user_id)" not in src)


def test_module_does_not_export_turn_count():
    print("\n[remove] backend.routes.ws 不再有 turn_count_per_user 属性")
    import backend.routes.ws as ws_mod
    check("hasattr turn_count_per_user is False",
          not hasattr(ws_mod, "turn_count_per_user"))
    check("hasattr _bump_turn_and_maybe_regenerate is False",
          not hasattr(ws_mod, "_bump_turn_and_maybe_regenerate"))


# ---------------------------------------------------------------------------
# 3. main.py 注册 cron
# ---------------------------------------------------------------------------


def test_main_py_registers_profile_cron():
    print("\n[main] main.py 注册 profile_daily_regenerate")
    import backend.main as main_mod
    src = open(main_mod.__file__, "r", encoding="utf-8").read()
    check("schedule_cron('profile_daily_regenerate', ...) 调用存在",
          "profile_daily_regenerate" in src
          and 'cron_scheduler.schedule_cron' in src)
    check("log 行 '[cron] profile_daily_regenerate registered:' 存在",
          "[cron] profile_daily_regenerate registered:" in src)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


async def amain():
    await test_daily_iterates_all_users()
    await test_daily_one_user_failure_does_not_block_others()


def main():
    asyncio.run(amain())
    test_50_turn_counter_removed()
    test_module_does_not_export_turn_count()
    test_main_py_registers_profile_cron()

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
