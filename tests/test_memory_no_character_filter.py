"""v3.5 chunk 9 Part 3 — memory 检索去 character_id 隔离 contract 验证。

* ``backend/agents/chat.py:_build_messages`` 调 ``search_relevant_memories``
  时不传 ``character_id`` —— 让 memory 跨角色共享（事实统一）
* ``backend/routes/memory_api.py:/memory/list`` 默认（不传 character_id query
  param）返 user 级全部
* save_memory tool 仍记录 character_id（audit metadata，UI 角标用）—— 本测
  试不验证写入（已被 chunk 3a memory tools 测试覆盖）
"""
from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.agents import chat as chat_mod

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))


# ---------------------------------------------------------------------------
# 1. _build_messages 不传 character_id 到 search_relevant_memories
# ---------------------------------------------------------------------------


def test_chat_py_search_call_omits_character_id():
    print("\n[1] chat.py _build_messages → search_relevant_memories 不传 character_id")
    src = open(chat_mod.__file__, "r", encoding="utf-8").read()
    # 关键 invariant：search_relevant_memories call 不带 character_id 参数
    # （v3.5 chunk 9 Part 3 之前是 ``search_relevant_memories(..., character_id=character_id)``）
    # 我们查 src 找 search_relevant_memories 调用块
    idx = src.find("search_relevant_memories")
    check("找到 search_relevant_memories 调用点", idx > 0)
    # 取调用点附近 200 字符
    snippet = src[idx : idx + 400]
    check(
        "调用块**不含** character_id= 关键字（chunk 9 Part 3 删除）",
        "character_id=character_id" not in snippet,
        detail=f"snippet 前 120 字: {snippet[:120]!r}",
    )


# ---------------------------------------------------------------------------
# 2. /api/memory/list 默认（不传 character_id）→ 不下沉到 get_all_memories
#    的 character_id 过滤
# ---------------------------------------------------------------------------


async def test_memory_list_endpoint_default_no_character_filter():
    print("\n[2] /api/memory/list 默认不带 character_id query → user 级全部")
    from backend.routes import memory_api

    captured: dict = {}

    async def fake_get_all(session, user_id, *, active_only=True,
                          character_id=None):
        captured["character_id"] = character_id
        captured["user_id"] = user_id
        return []

    with patch.object(memory_api, "get_all_memories", new=fake_get_all):
        # 直接调 endpoint async function
        await memory_api.list_memories(
            user_id="u_test_chunk9",
            character_id=None,
            active_only=True,
            session=MagicMock(),
        )
    check("character_id passed to get_all_memories == None",
          captured.get("character_id") is None)
    check("user_id passed through",
          captured.get("user_id") == "u_test_chunk9")


async def test_memory_list_endpoint_explicit_character_id_still_works():
    print("\n[2.b] 显式传 character_id query → 仍按 character 过滤（可选筛选）")
    from backend.routes import memory_api
    captured: dict = {}

    async def fake_get_all(session, user_id, *, active_only=True,
                           character_id=None):
        captured["character_id"] = character_id
        return []

    with patch.object(memory_api, "get_all_memories", new=fake_get_all):
        await memory_api.list_memories(
            user_id="u_test_chunk9",
            character_id=42,
            active_only=True,
            session=MagicMock(),
        )
    check("explicit character_id=42 passed through",
          captured.get("character_id") == 42)


# ---------------------------------------------------------------------------
# 3. memory_api response 仍包含 character_id 字段（UI 角标用）
# ---------------------------------------------------------------------------


def test_memory_list_response_includes_character_id():
    print("\n[3] /api/memory/list response 仍含 character_id 字段（UI 角标用）")
    from backend.routes import memory_api as ma
    src = open(ma.__file__, "r", encoding="utf-8").read()
    # 在 list_memories 实现中查找 ``"character_id": m.character_id`` 投影
    check("response 投影 character_id",
          '"character_id": m.character_id' in src)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


async def amain():
    await test_memory_list_endpoint_default_no_character_filter()
    await test_memory_list_endpoint_explicit_character_id_still_works()


def main():
    test_chat_py_search_call_omits_character_id()
    asyncio.run(amain())
    test_memory_list_response_includes_character_id()

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
