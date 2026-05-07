"""Tests for v3-G chunk 2 MorningBriefingTrigger —— mock ChatAgent + capability
calls 验证 system prompt 含正确指令链 + WS push 序列 + 默认配置解析。
"""
import asyncio
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.proactive.triggers.morning_briefing import (
    MorningBriefingTrigger,
    _briefing_enabled,
    _resolve_cron,
    _resolve_city,
)
from backend.proactive import engine as proactive_engine

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))


# ---------------------------------------------------------------------------
# 1. 默认配置解析
# ---------------------------------------------------------------------------

async def test_default_cron_expr():
    print("\n[morning_briefing — default cron]")
    with patch.dict(
        proactive_engine.config_yaml,
        {"proactive": {"morning_briefing": {}}},
        clear=False,
    ):
        cron = _resolve_cron()
    check("default = '0 9 * * *'", cron == "0 9 * * *", f"got {cron!r}")


async def test_custom_cron_expr():
    print("\n[morning_briefing — custom cron]")
    with patch.dict(
        proactive_engine.config_yaml,
        {"proactive": {"morning_briefing": {"cron": "30 7 * * *"}}},
        clear=False,
    ):
        cron = _resolve_cron()
    check("respects custom cron", cron == "30 7 * * *", f"got {cron!r}")


async def test_default_city():
    print("\n[morning_briefing — default city]")
    with patch.dict(
        proactive_engine.config_yaml,
        {"proactive": {"morning_briefing": {}}},
        clear=False,
    ):
        city = _resolve_city()
    check("default city = 东京", city == "东京", f"got {city!r}")


async def test_briefing_enabled_gating():
    """两层 enabled 都要 true 才启用：proactive.enabled + morning_briefing.enabled。"""
    print("\n[morning_briefing — enabled gating]")
    with patch.dict(
        proactive_engine.config_yaml,
        {"proactive": {"enabled": False, "morning_briefing": {"enabled": True}}},
        clear=False,
    ):
        check("proactive.enabled=False ⇒ disabled", _briefing_enabled() is False)

    with patch.dict(
        proactive_engine.config_yaml,
        {"proactive": {"enabled": True, "morning_briefing": {"enabled": False}}},
        clear=False,
    ):
        check("morning_briefing.enabled=False ⇒ disabled", _briefing_enabled() is False)

    with patch.dict(
        proactive_engine.config_yaml,
        {"proactive": {"enabled": True, "morning_briefing": {"enabled": True}}},
        clear=False,
    ):
        check("both true ⇒ enabled", _briefing_enabled() is True)


# ---------------------------------------------------------------------------
# 2. system prompt 包含 spec 锁定的 6 条指令
# ---------------------------------------------------------------------------

async def test_system_prompt_includes_instruction_chain():
    print("\n[morning_briefing — system prompt instruction chain]")
    with patch.dict(
        proactive_engine.config_yaml,
        {"proactive": {"morning_briefing": {"city": "上海"}}},
        clear=False,
    ):
        t = MorningBriefingTrigger()
        prompt = await t.build_system_prompt(None)

    check("starts with 你正在生成今日早晨简报",
          "你正在生成今日早晨简报" in prompt)
    check("instructs time.now",     "time.now" in prompt)
    check("instructs calendar.today_events", "calendar.today_events" in prompt)
    check("instructs list_memories", "list_memories" in prompt)
    check("uses 配置的城市 上海",   "上海" in prompt, f"prompt={prompt[:200]!r}")
    check("instructs enable_search 查天气", "天气" in prompt and "enable_search" in prompt)
    check("instructs 200-300 字",    "200" in prompt and "300" in prompt)
    check("instructs 不要列表分点",  "列表" in prompt or "分点" in prompt)
    check("instructs 开放话头",      "开放话头" in prompt or "接话" in prompt)


async def test_resolve_capabilities():
    print("\n[morning_briefing — resolve_capabilities hint list]")
    t = MorningBriefingTrigger()
    caps = await t.resolve_capabilities()
    check("hint includes time.now", "time.now" in caps)
    check("hint includes calendar.today_events", "calendar.today_events" in caps)
    check("hint includes list_memories", "list_memories" in caps)


# ---------------------------------------------------------------------------
# 3. trigger metadata
# ---------------------------------------------------------------------------

async def test_trigger_metadata():
    print("\n[morning_briefing — trigger metadata]")
    t = MorningBriefingTrigger()
    check("name = 'morning_briefing'", t.name == "morning_briefing")
    check("enable_search = True", t.enable_search is True)
    check("interval/event_source None",
          t.interval_seconds is None and t.event_source is None)


# ---------------------------------------------------------------------------
# 4. 完整 WS push 序列（mock 整个 ChatAgent.stream）
# ---------------------------------------------------------------------------

async def test_full_ws_push_sequence():
    """mock ChatAgent.stream → 验证 text_chunk(proactive) → done(proactive) 序列。"""
    print("\n[morning_briefing — full WS push sequence]")
    from backend.database import AsyncSessionLocal
    from backend.database.services import create_user, get_user
    from backend.database.migrations.v3_e1_z import run_migration as _m_z
    from backend.database.migrations.v3_f import run_migration as _m_f
    from backend.database.migrations.v3_g_chunk2_proactive import (
        run_migration as _m_chunk2,
    )
    from backend.database import init_db
    await init_db(); await _m_f(); await _m_z(); await _m_chunk2()
    async with AsyncSessionLocal() as session:
        if await get_user(session, "test_briefing_seq") is None:
            await create_user(session, "test_briefing_seq", "TestSeq")

    async def fake_stream(_self, _msg):
        # 模拟简报输出：emotion + 三句
        yield "<emotion>happy</emotion>早安，今天东京晴。"
        yield "你 9 点有晨会，记得别迟到。"
        yield "想喝咖啡了吗？"

    push_calls: list = []
    from backend.routes import ws as ws_mod
    async def fake_push(uid, msg):
        push_calls.append((uid, msg))

    with patch.object(proactive_engine.ChatAgent, "stream", fake_stream), \
         patch.dict(
             proactive_engine.config_yaml,
             {"proactive": {"character_id_override": 1,
                            "morning_briefing": {"enabled": True, "city": "东京"}},
              "default_user_id": "test_briefing_seq"},
             clear=False,
         ), \
         patch("backend.proactive.engine.get_tts_enabled", return_value=False), \
         patch.object(ws_mod.connection_manager, "push", fake_push):
        result = await proactive_engine.run_trigger(
            MorningBriefingTrigger(), user_id="test_briefing_seq",
        )

    types = [m.get("type") for _u, m in push_calls]
    check("first push is emotion (parsed from 1st sentence)",
          "emotion" in types)
    check("text_chunk count = 3",
          types.count("text_chunk") == 3,
          f"types={types}")
    check("all text_chunks have proactive=true",
          all(m.get("proactive") for _u, m in push_calls if m.get("type") == "text_chunk"))
    check("all text_chunks have proactive_trigger=morning_briefing",
          all(m.get("proactive_trigger") == "morning_briefing"
              for _u, m in push_calls if m.get("type") == "text_chunk"))
    check("final type is done",
          types[-1] == "done", f"types={types}")
    check("done has proactive=true",
          push_calls[-1][1].get("proactive") is True)

    # 简报文本应包含 emotion 标签剥除后的 3 句拼接
    text = result.get("text", "")
    check("emotion tag stripped from persisted text",
          "<emotion>" not in text and "</emotion>" not in text,
          f"text={text!r}")
    check("contains 早安",  "早安" in text)
    check("contains 9 点", "9 点" in text or "9点" in text)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

async def main():
    await test_default_cron_expr()
    await test_custom_cron_expr()
    await test_default_city()
    await test_briefing_enabled_gating()
    await test_system_prompt_includes_instruction_chain()
    await test_resolve_capabilities()
    await test_trigger_metadata()
    await test_full_ws_push_sequence()

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
