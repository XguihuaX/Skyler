"""v3.5 chunk 10 commit 4 — extractor end-to-end (mock LLM → DB)。

验证 _extract_batch → _process_user_turns → prompt → mock LLM →
validator → save_worker_entries 全链路：
  * 通过 filter 的 entries 真入 memory 表
  * extraction_source='worker' / entry_type 字段写正确
  * source_turn_id 链回最后一条 turn
  * type 列被映射到 chunk 2 五分类
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import delete, select, text

from backend.database import AsyncSessionLocal, Base, engine
from backend.database.models import ChatHistory, Memory, User
from backend.memory import extractor as ex_mod
from backend.prompts import memory_extraction as me

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))


TEST_USER = "chunk10_e2e"


async def _setup() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSessionLocal() as session:
        await session.execute(delete(Memory).where(Memory.user_id == TEST_USER))
        await session.execute(delete(ChatHistory).where(
            ChatHistory.user_id == TEST_USER))
        u = (await session.execute(
            select(User).where(User.user_id == TEST_USER)
        )).scalar_one_or_none()
        if u is None:
            session.add(User(user_id=TEST_USER, user_name=TEST_USER))
        await session.commit()
    async with engine.begin() as conn:
        await conn.execute(text(
            "DELETE FROM memory_extractor_state WHERE user_id = :u"
        ), {"u": TEST_USER})


async def _teardown() -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(delete(Memory).where(Memory.user_id == TEST_USER))
        await session.execute(delete(ChatHistory).where(
            ChatHistory.user_id == TEST_USER))
        await session.execute(delete(User).where(User.user_id == TEST_USER))
        await session.commit()
    async with engine.begin() as conn:
        await conn.execute(text(
            "DELETE FROM memory_extractor_state WHERE user_id = :u"
        ), {"u": TEST_USER})


def _fake_llm_response(content: str):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


async def test_e2e_extractor_saves_entries_to_db():
    print("\n[e2e] mock LLM 输出 2 条合法 entries → 入库 + 字段填齐")
    await _setup()

    # 准备 chat history
    async with AsyncSessionLocal() as session:
        for content in [
            "我的猫叫 Mochi，三岁了",
            "我每周一到五早上 7 点起床",
            "周五前要交项目",
        ]:
            session.add(ChatHistory(
                user_id=TEST_USER, role="user",
                content=content, kind="normal",
            ))
        await session.commit()

    llm_output = json.dumps([
        {"type": "fact",       "content": "用户的猫叫 Mochi，三岁了",  "confidence": 0.95},
        {"type": "preference", "content": "用户工作日早上 7 点起床",   "confidence": 0.9},
        {"type": "commitment", "content": "用户周五前要交项目",        "confidence": 0.85},
    ])

    # Mock LLM call
    async def fake_llm(prompt):
        return llm_output

    with patch.object(me, "call_llm",
                      AsyncMock(return_value=_fake_llm_response(llm_output))):
        ex = ex_mod.MemoryExtractor()
        await ex._extract_batch()

    # Verify DB rows
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(Memory).where(Memory.user_id == TEST_USER)
        )).scalars().all()
    check("入库 3 条", len(rows) == 3)

    by_content = {r.content: r for r in rows}
    cat = by_content.get("用户的猫叫 Mochi，三岁了")
    check("cat row 存在", cat is not None)
    if cat:
        check("extraction_source = 'worker'",
              cat.extraction_source == "worker")
        check("entry_type = 'fact'", cat.entry_type == "fact")
        check("legacy type = 'fact'", cat.type == "fact")
        check("confidence ≈ 0.95",
              cat.confidence is not None and abs(cat.confidence - 0.95) < 0.01)
        check("extracted_at non-null", cat.extracted_at is not None)
        check("source_turn_id non-null", cat.source_turn_id is not None)

    # 验证 entry_type → legacy type mapping
    pref = by_content.get("用户工作日早上 7 点起床")
    if pref:
        check("preference → legacy type 'instruction'",
              pref.type == "instruction")
    com = by_content.get("用户周五前要交项目")
    if com:
        check("commitment → legacy type 'activity'",
              com.type == "activity")

    # state pointer 推进
    last = await ex_mod.get_last_processed_turn_id(TEST_USER)
    check("state pointer > 0", last > 0)


async def test_e2e_extractor_filters_low_confidence():
    print("\n[e2e] confidence 0.3 entry → reject 不入库")
    await _setup()
    async with AsyncSessionLocal() as session:
        session.add(ChatHistory(
            user_id=TEST_USER, role="user",
            content="msg", kind="normal",
        ))
        await session.commit()

    llm_output = json.dumps([
        {"type": "fact", "content": "低置信度的事实陈述", "confidence": 0.3},
    ])
    with patch.object(me, "call_llm",
                      AsyncMock(return_value=_fake_llm_response(llm_output))):
        ex = ex_mod.MemoryExtractor()
        await ex._extract_batch()

    async with AsyncSessionLocal() as session:
        n = (await session.execute(
            select(Memory).where(Memory.user_id == TEST_USER)
        )).scalars().all()
    check("不入库", len(n) == 0)


async def test_e2e_extractor_filters_suspicious_tag():
    print("\n[e2e] content 含 <netease.x> → SUSPICIOUS reject")
    await _setup()
    async with AsyncSessionLocal() as session:
        session.add(ChatHistory(
            user_id=TEST_USER, role="user",
            content="msg", kind="normal",
        ))
        await session.commit()

    llm_output = json.dumps([
        {"type": "fact",
         "content": "可疑的 <netease.daily_recommend/> 标签内容",
         "confidence": 0.9},
    ])
    with patch.object(me, "call_llm",
                      AsyncMock(return_value=_fake_llm_response(llm_output))):
        ex = ex_mod.MemoryExtractor()
        await ex._extract_batch()

    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(Memory).where(Memory.user_id == TEST_USER)
        )).scalars().all()
    check("SUSPICIOUS 被 reject", len(rows) == 0)


async def test_e2e_extractor_llm_returns_none_safe():
    print("\n[e2e] LLM 抛异常 → 无入库 + state pointer 仍推进（避免 stuck）")
    await _setup()
    async with AsyncSessionLocal() as session:
        session.add(ChatHistory(
            user_id=TEST_USER, role="user",
            content="msg", kind="normal",
        ))
        await session.commit()

    with patch.object(me, "call_llm",
                      AsyncMock(side_effect=RuntimeError("fail"))):
        ex = ex_mod.MemoryExtractor()
        await ex._extract_batch()

    async with AsyncSessionLocal() as session:
        n = (await session.execute(
            select(Memory).where(Memory.user_id == TEST_USER)
        )).scalars().all()
    check("无入库", len(n) == 0)
    last = await ex_mod.get_last_processed_turn_id(TEST_USER)
    check("state pointer 仍推进（不 stuck 在同一条）", last > 0)


async def test_cleanup():
    print("\n[cleanup]")
    await _teardown()
    check("teardown OK", True)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


async def amain():
    await test_e2e_extractor_saves_entries_to_db()
    await test_e2e_extractor_filters_low_confidence()
    await test_e2e_extractor_filters_suspicious_tag()
    await test_e2e_extractor_llm_returns_none_safe()
    await test_cleanup()


def main():
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
