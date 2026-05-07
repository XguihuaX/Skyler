"""Tests for v3-G chunk 2 proactive engine —— 抽象基类、character 解析、
chat_history 字段写入、config 路径。

测 ChatAgent.stream 整链路属于 test_morning_briefing.py 的 mock 路径；
本文件只测 engine 自己的静态契约。
"""
import asyncio
import os
import sys
from typing import Optional
from unittest.mock import patch, AsyncMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.database.models import Character
from backend.proactive import ProactiveTrigger, run_trigger
from backend.proactive import engine as proactive_engine

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))


# ---------------------------------------------------------------------------
# 1. 抽象基类签名
# ---------------------------------------------------------------------------

class _NopTrigger(ProactiveTrigger):
    name = "nop"
    cron_expr = "0 9 * * *"
    enable_search = False

    async def build_system_prompt(self, character: Optional[Character]) -> str:
        return "do nothing"


async def test_abstract_base_class():
    print("\n[proactive — abstract base class signature]")
    t = _NopTrigger()
    check("name set", t.name == "nop")
    check("cron_expr set", t.cron_expr == "0 9 * * *")
    check("interval/event_source default None",
          t.interval_seconds is None and t.event_source is None)
    check("enable_search default False", t.enable_search is False)
    sysprompt = await t.build_system_prompt(None)
    check("build_system_prompt returns str", isinstance(sysprompt, str))
    caps = await t.resolve_capabilities()
    check("resolve_capabilities default empty", caps == [])


async def test_abstract_class_unimplemented():
    print("\n[proactive — abstract method enforcement]")
    try:
        ProactiveTrigger()  # type: ignore[abstract]
        check("can't instantiate ABC", False, "no error raised")
    except TypeError:
        check("can't instantiate ABC", True)


# ---------------------------------------------------------------------------
# 2. character 解析三档优先级
# ---------------------------------------------------------------------------

async def test_resolve_target_character_override_takes_priority():
    print("\n[proactive — character resolution: override wins]")
    with patch.dict(
        proactive_engine.config_yaml,
        {"proactive": {"character_id_override": 7}},
        clear=False,
    ):
        # 这一档不需要 DB 查询，override 设了就直接返
        cid = await proactive_engine._resolve_target_character_id("default")
    check("returns override id=7", cid == 7, f"got {cid}")


async def _ensure_db_migrated() -> None:
    """init_db + 所有 v3-G chunk 2 之前的 schema migrations，让测试 DB 完整。"""
    from backend.database import init_db
    from backend.database.migrations.v3_e1_z import run_migration as m_z
    from backend.database.migrations.v3_f import run_migration as m_f
    from backend.database.migrations.v3_g_chunk2_proactive import (
        run_migration as m_chunk2,
    )
    await init_db()
    await m_f()
    await m_z()
    await m_chunk2()


async def test_resolve_target_falls_back_to_recent_user_turn():
    """配置 override=null + DB 有最近 user turn → 该 turn 的 character_id。"""
    print("\n[proactive — character resolution: most recent user turn]")
    # 先确保数据库 + 所有相关迁移就位
    await _ensure_db_migrated()
    from backend.database import AsyncSessionLocal
    from backend.database.services import (
        add_chat_history, create_user, get_user,
    )
    from backend.database.models import Character
    from sqlalchemy import select
    async with AsyncSessionLocal() as session:
        if await get_user(session, "test_proactive") is None:
            await create_user(session, "test_proactive", "TestUser")
        # 确保两个 character 行存在
        for cid_target, name in [(1, "Momo"), (99, "TestPropose")]:
            row = (await session.execute(
                select(Character).where(Character.id == cid_target)
            )).scalar_one_or_none()
            if row is None:
                session.add(Character(id=cid_target, name=name, persona=f"persona-{name}"))
        await session.commit()

    async with AsyncSessionLocal() as session:
        # 写一行 user-side chat 与 character_id=99
        await add_chat_history(
            session, "test_proactive", "user", "hi",
            character_id=99,
        )

    with patch.dict(
        proactive_engine.config_yaml,
        {"proactive": {"character_id_override": None}},
        clear=False,
    ):
        cid = await proactive_engine._resolve_target_character_id("test_proactive")
    check("falls back to recent user turn char_id=99",
          cid == 99, f"got {cid}")


async def test_resolve_target_falls_back_to_momo():
    """没有 user turn → fallback Momo (id=1)。"""
    print("\n[proactive — character resolution: Momo fallback]")
    await _ensure_db_migrated()
    from backend.database import AsyncSessionLocal
    from backend.database.services import (
        create_user, get_user,
    )
    async with AsyncSessionLocal() as session:
        if await get_user(session, "test_lonely") is None:
            await create_user(session, "test_lonely", "LonelyUser")

    with patch.dict(
        proactive_engine.config_yaml,
        {"proactive": {"character_id_override": None}},
        clear=False,
    ):
        cid = await proactive_engine._resolve_target_character_id("test_lonely")
    # Momo 在 DB init 流程会被创建（id 由 DB 决定，可能不是 1，但 name='Momo' 行存在）
    # _resolve_target_character_id 兜底用 name='Momo' 查
    check("returns Momo id (not None)", cid is not None, f"got {cid}")


# ---------------------------------------------------------------------------
# 3. chat_history.kind / proactive_trigger 字段写入
# ---------------------------------------------------------------------------

async def test_run_trigger_writes_proactive_kind():
    """mock ChatAgent.stream 返单句，验证 chat_history 写入用 kind='proactive'。"""
    print("\n[proactive — run_trigger persists with kind='proactive']")
    await _ensure_db_migrated()
    from backend.database import AsyncSessionLocal
    from backend.database.services import create_user, get_user
    from backend.database.models import ChatHistory
    from sqlalchemy import select
    async with AsyncSessionLocal() as session:
        if await get_user(session, "test_kind") is None:
            await create_user(session, "test_kind", "KindUser")

    class _FixedTrigger(ProactiveTrigger):
        name = "test_fixed"
        enable_search = False

        async def build_system_prompt(self, character):
            return "test prompt"

    async def fake_stream(_self, _msg):
        yield "<emotion>happy</emotion>这是测试简报内容。"

    # mock ChatAgent.stream + TTS（不让 audio 真合成 / 真 push）
    with patch.object(proactive_engine.ChatAgent, "stream", fake_stream), \
         patch.dict(
             proactive_engine.config_yaml,
             {"proactive": {"character_id_override": 1}},
             clear=False,
         ), \
         patch("backend.proactive.engine.get_tts_enabled", return_value=False):

        # 也要 stub connection_manager.push 不依赖真实 WS
        from backend.routes import ws
        push_calls: list = []
        async def fake_push(uid, msg):
            push_calls.append((uid, msg))
        with patch.object(ws.connection_manager, "push", fake_push):
            result = await run_trigger(_FixedTrigger(), user_id="test_kind")

    check("run_trigger returns text", "测试简报内容" in result.get("text", ""),
          f"got text={result.get('text')!r}")
    check("returns proactive_trigger name",
          result.get("proactive_trigger") == "test_fixed",
          f"got {result.get('proactive_trigger')}")
    check("at least one text_chunk pushed with proactive=true",
          any(m.get("type") == "text_chunk" and m.get("proactive") for _u, m in push_calls),
          f"calls={[m.get('type') for _,m in push_calls]}")
    check("done pushed with proactive=true",
          any(m.get("type") == "done" and m.get("proactive") for _u, m in push_calls))

    # 验证 chat_history 行
    async with AsyncSessionLocal() as session:
        rows = list((await session.execute(
            select(ChatHistory)
            .where(ChatHistory.user_id == "test_kind")
            .where(ChatHistory.kind == "proactive")
            .order_by(ChatHistory.id.desc())
            .limit(1)
        )).scalars().all())
    check("chat_history row written", len(rows) == 1)
    if rows:
        r = rows[0]
        check("kind = 'proactive'", r.kind == "proactive")
        check("proactive_trigger = 'test_fixed'",
              r.proactive_trigger == "test_fixed")
        check("role = 'assistant'", r.role == "assistant")


# ---------------------------------------------------------------------------
# 4. config 路径
# ---------------------------------------------------------------------------

async def test_config_path_proactive():
    print("\n[proactive — config path]")
    cfg = proactive_engine._get_proactive_config()
    check("config returns dict", isinstance(cfg, dict))
    # 真实 config.yaml 应该有 proactive 节
    check("real config.yaml has proactive section",
          isinstance(proactive_engine.config_yaml.get("proactive"), dict),
          f"got {type(proactive_engine.config_yaml.get('proactive'))}")


# ---------------------------------------------------------------------------
# 5. profile_summary 跳过 proactive 行（回归）
# ---------------------------------------------------------------------------

async def test_profile_summary_excludes_proactive_rows():
    """v3-E1 Step Z.2 已实现 kinds=['normal'] 白名单 ⇒ proactive 自动排除。
    回归测试：ws._regenerate_profile_summary 调 get_chat_history 时，传 kinds 应仅含 'normal'。
    """
    print("\n[regression — profile_summary excludes proactive rows]")
    from backend.routes import ws as ws_mod

    captured: dict = {}

    async def fake_get_history(session, user_id, limit=None, kinds=None):
        captured["kinds"] = kinds
        return []  # empty → 触发 short-circuit "clear summary" 路径

    async def fake_update(session, user_id, summary):
        captured["update"] = summary

    with patch.object(ws_mod, "get_chat_history", fake_get_history), \
         patch.object(ws_mod, "update_profile_summary", fake_update):
        await ws_mod._regenerate_profile_summary("any_user")

    check("get_chat_history called with kinds=['normal']",
          captured.get("kinds") == ["normal"],
          f"got kinds={captured.get('kinds')!r}")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

async def main():
    await test_abstract_base_class()
    await test_abstract_class_unimplemented()
    await test_resolve_target_character_override_takes_priority()
    await test_resolve_target_falls_back_to_recent_user_turn()
    await test_resolve_target_falls_back_to_momo()
    await test_run_trigger_writes_proactive_kind()
    await test_config_path_proactive()
    await test_profile_summary_excludes_proactive_rows()

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
    asyncio.run(main())
