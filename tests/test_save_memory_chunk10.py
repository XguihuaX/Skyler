"""v3.5 chunk 10 commit 5 — save_memory tool 降级 + quality filter + 标记。

* 显式入口仍可用，但 description 收紧到"用户明确说要记"
* 写入前 SUSPICIOUS / 长度 / 重复 quality filter
* 通过 filter 才入库，标 extraction_source='llm_save_memory'
"""
from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import delete, select, text

from backend.database import AsyncSessionLocal, Base, engine
from backend.database.models import Memory, User

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))


TEST_USER = "chunk10_save_memory_test"


async def _setup() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSessionLocal() as session:
        await session.execute(delete(Memory).where(Memory.user_id == TEST_USER))
        u = (await session.execute(
            select(User).where(User.user_id == TEST_USER)
        )).scalar_one_or_none()
        if u is None:
            session.add(User(user_id=TEST_USER, user_name=TEST_USER))
        await session.commit()


async def _teardown() -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(delete(Memory).where(Memory.user_id == TEST_USER))
        await session.execute(delete(User).where(User.user_id == TEST_USER))
        await session.commit()


# ---------------------------------------------------------------------------
# Description contract
# ---------------------------------------------------------------------------


def test_save_memory_description_tightened():
    print("\n[desc] save_memory description 收紧到'用户明确说要记'")
    import backend.agents.chat as chat_mod
    src = open(chat_mod.__file__, "r", encoding="utf-8").read()
    check("description 含 '请记住'", "请记住 X" in src)
    check("description 提及 chunk 10 worker",
          "chunk 10" in src and "background worker" in src)
    check("description 含 '不要主动'", "不要主动" in src)


def test_tool_prompt_addendum_updated():
    print("\n[addendum] _TOOL_PROMPT_ADDENDUM 提示 worker 替代")
    import backend.agents.chat as chat_mod
    src = open(chat_mod.__file__, "r", encoding="utf-8").read()
    check("含 'worker 每 5 分钟自动提取'",
          "chunk 10" in src
          and ("worker 每 5 分钟" in src or "5 分钟自动" in src))


# ---------------------------------------------------------------------------
# Behavior
# ---------------------------------------------------------------------------


async def test_save_memory_happy_path_marks_extraction_source():
    print("\n[behavior] 合法 content → 入库 + extraction_source='llm_save_memory'")
    await _setup()
    from backend.agents.chat import _tool_save_memory
    out = await _tool_save_memory(
        TEST_USER, {"content": "用户最喜欢的早餐是麦片"}, character_id=None,
    )
    check("status == ok", out.get("status") == "ok")
    check("extraction_source returned",
          out.get("extraction_source") == "llm_save_memory")
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(Memory).where(Memory.user_id == TEST_USER)
        )).scalars().all()
    check("入库 1 条", len(rows) == 1)
    if rows:
        check("DB extraction_source = 'llm_save_memory'",
              rows[0].extraction_source == "llm_save_memory")


async def test_save_memory_too_short_rejected():
    print("\n[behavior] content < 5 字 → reject 不入库")
    await _setup()
    from backend.agents.chat import _tool_save_memory
    out = await _tool_save_memory(
        TEST_USER, {"content": "短"}, character_id=None,
    )
    check("error returned",
          out.get("status") == "error"
          and out.get("error") == "content_length_out_of_range")
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(Memory).where(Memory.user_id == TEST_USER)
        )).scalars().all()
    check("不入库", len(rows) == 0)


async def test_save_memory_suspicious_rejected():
    print("\n[behavior] content 含 SUSPICIOUS tag → reject")
    await _setup()
    from backend.agents.chat import _tool_save_memory
    out = await _tool_save_memory(
        TEST_USER,
        {"content": "用户喜欢 <netease.daily_recommend/> 的推荐"},
        character_id=None,
    )
    check("status == error", out.get("status") == "error")
    check("error == suspicious_tag_detected",
          out.get("error") == "suspicious_tag_detected")
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(Memory).where(Memory.user_id == TEST_USER)
        )).scalars().all()
    check("不入库", len(rows) == 0)


async def test_save_memory_duplicate_rejected():
    print("\n[behavior] 与现有 memory 相似度 > dup_threshold → reject")
    await _setup()
    from backend.agents.chat import _tool_save_memory

    # 先存一条
    out1 = await _tool_save_memory(
        TEST_USER, {"content": "用户的猫叫 Mochi，三岁了，毛是橘色"},
        character_id=None,
    )
    check("first save ok", out1.get("status") == "ok")

    # mock cosine 永远 > dup_threshold
    with patch("backend.memory.long_term._cosine",
               return_value=0.99):
        out2 = await _tool_save_memory(
            TEST_USER, {"content": "用户家的猫名字叫 Mochi，三岁的橘猫"},
            character_id=None,
        )
    check("status == duplicate", out2.get("status") == "duplicate")
    check("existing_memory_id 返回",
          out2.get("existing_memory_id") is not None)
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(Memory).where(Memory.user_id == TEST_USER)
        )).scalars().all()
    check("仍只 1 条", len(rows) == 1)


async def test_save_memory_empty_content_rejected():
    print("\n[behavior] 空 content → error")
    await _setup()
    from backend.agents.chat import _tool_save_memory
    out = await _tool_save_memory(
        TEST_USER, {"content": "   "}, character_id=None,
    )
    check("error: content is required",
          out.get("status") == "error"
          and "content" in (out.get("error") or ""))


async def test_cleanup():
    print("\n[cleanup]")
    await _teardown()
    check("teardown OK", True)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


async def amain():
    await test_save_memory_happy_path_marks_extraction_source()
    await test_save_memory_too_short_rejected()
    await test_save_memory_suspicious_rejected()
    await test_save_memory_duplicate_rejected()
    await test_save_memory_empty_content_rejected()
    await test_cleanup()


def main():
    test_save_memory_description_tightened()
    test_tool_prompt_addendum_updated()
    asyncio.run(amain())

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
