"""Tests for v3-G chunk 2.6 — WakeCallBriefingTrigger 双阶段流水线。

mock LLM + capability —— 不打真实网络。验证 stage 1 push 短问候 + 写
pending；stage 2 ChatAgent._build_messages 检测 + 注入 addendum + 消费
pending；mode 互斥；TTL 边界。
"""
import asyncio
import json
import os
import sys
from datetime import datetime, timedelta
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))


async def _setup_db() -> None:
    from backend.database import init_db
    from backend.database.migrations.v3_e1_z import run_migration as m_z
    from backend.database.migrations.v3_f import run_migration as m_f
    from backend.database.migrations.v3_g_chunk2_proactive import run_migration as m_c2
    from backend.database.migrations.v3_g_chunk2_6_pending_briefing import (
        run_migration as m_c26,
    )
    await init_db()
    await m_f(); await m_z(); await m_c2(); await m_c26()


async def _ensure_user(uid: str) -> None:
    from backend.database import AsyncSessionLocal
    from backend.database.services import create_user, get_user
    async with AsyncSessionLocal() as session:
        if await get_user(session, uid) is None:
            await create_user(session, uid, f"User-{uid}")


# ---------------------------------------------------------------------------
# 1. WakeCallBriefingTrigger metadata
# ---------------------------------------------------------------------------

async def test_trigger_metadata():
    print("\n[wake_call — trigger metadata]")
    from backend.proactive.triggers.wake_call_briefing import (
        WakeCallBriefingTrigger,
    )
    t = WakeCallBriefingTrigger()
    check("name = 'wake_call'", t.name == "wake_call")
    check("enable_search = False", t.enable_search is False)
    check("interval/event_source None",
          t.interval_seconds is None and t.event_source is None)
    check("cron_expr default '0 8 * * *'", t.cron_expr == "0 8 * * *")


async def test_stage1_system_prompt_constraints():
    print("\n[wake_call — stage 1 system prompt 8-15 字 constraint]")
    from backend.proactive.triggers.wake_call_briefing import (
        WakeCallBriefingTrigger,
    )
    t = WakeCallBriefingTrigger()
    prompt = await t.build_system_prompt(None)
    check("instructs 8-15 chars", "8-15" in prompt or "8 到 15" in prompt or "8 至 15" in prompt)
    check("forbids listing today's events",
          "严禁" in prompt or "禁止" in prompt or "不要" in prompt)
    check("explicitly bans 日程 / 待办 keywords in output",
          "日程" in prompt and ("待办" in prompt or "提醒" in prompt or "今天有" in prompt))


# ---------------------------------------------------------------------------
# 2. mode mutex helpers
# ---------------------------------------------------------------------------

async def test_mode_mutex_helper():
    print("\n[wake_call — _wake_call_mode_active checks proactive.mode]")
    from backend.proactive.triggers.wake_call_briefing import _wake_call_mode_active
    from backend.config import config_yaml

    with patch.dict(config_yaml,
                    {"proactive": {"enabled": True, "mode": "wake_call"}},
                    clear=False):
        check("mode=wake_call ⇒ active", _wake_call_mode_active() is True)
    with patch.dict(config_yaml,
                    {"proactive": {"enabled": True, "mode": "morning_briefing"}},
                    clear=False):
        check("mode=morning_briefing ⇒ inactive", _wake_call_mode_active() is False)
    with patch.dict(config_yaml,
                    {"proactive": {"enabled": True, "mode": "off"}},
                    clear=False):
        check("mode=off ⇒ inactive", _wake_call_mode_active() is False)
    with patch.dict(config_yaml,
                    {"proactive": {"enabled": False, "mode": "wake_call"}},
                    clear=False):
        check("enabled=False ⇒ inactive", _wake_call_mode_active() is False)


# ---------------------------------------------------------------------------
# 3. aggregate_briefing_data
# ---------------------------------------------------------------------------

async def test_aggregate_briefing_data():
    print("\n[wake_call — aggregate_briefing_data shape]")
    await _setup_db()
    await _ensure_user("agg_user")

    from backend.proactive.engine import aggregate_briefing_data

    async def fake_today_events(**_kw):
        return [{"title": "晨会", "start": "2026-05-08T09:00:00+09:00", "all_day": False}]

    with patch("backend.capabilities.calendar.today_events", fake_today_events):
        data = await aggregate_briefing_data("agg_user", character_id=1)

    check("has 'time' key", "time" in data and isinstance(data["time"], dict))
    check("has 'calendar_events' list", isinstance(data.get("calendar_events"), list))
    check("calendar_events contains mocked event",
          len(data["calendar_events"]) >= 1
          and any(e.get("title") == "晨会" for e in data["calendar_events"]))
    check("has 'instruction_memories' list",
          isinstance(data.get("instruction_memories"), list))
    check("has 'city' string", isinstance(data.get("city"), str) and data["city"])


# ---------------------------------------------------------------------------
# 4. run_wake_call_trigger: stage 1 push short greeting + write pending
# ---------------------------------------------------------------------------

async def test_run_wake_call_stage1_pushes_short_and_writes_pending():
    print("\n[wake_call — stage 1 pushes short greeting + writes pending]")
    await _setup_db()
    await _ensure_user("wc_user1")

    from backend.proactive.engine import run_wake_call_trigger
    from backend.proactive.triggers.wake_call_briefing import WakeCallBriefingTrigger
    from backend.proactive import engine as proactive_engine

    async def fake_stream(_self, _msg):
        # 模拟 8-15 字短问候，带 emotion 标签
        yield "<emotion>happy</emotion>起床啦，宝～"

    push_calls: list = []
    from backend.routes import ws as ws_mod
    async def fake_push(uid, msg):
        push_calls.append((uid, msg))

    with patch.object(proactive_engine.ChatAgent, "stream", fake_stream), \
         patch.dict(proactive_engine.config_yaml,
                    {"proactive": {
                        "character_id_override": 1,
                        "wake_call_briefing": {"pending_ttl_minutes": 30},
                    }}, clear=False), \
         patch("backend.proactive.engine.get_tts_enabled", return_value=False), \
         patch.object(ws_mod.connection_manager, "push", fake_push), \
         patch("backend.capabilities.calendar.today_events",
               lambda **_: _empty_events()):
        result = await run_wake_call_trigger(
            WakeCallBriefingTrigger(), user_id="wc_user1",
        )

    check("returns text", "起床啦" in result.get("text", ""))
    check("returns pending_id (int)", isinstance(result.get("pending_id"), int))
    check("returns proactive_trigger='wake_call'",
          result.get("proactive_trigger") == "wake_call")

    types = [m.get("type") for _u, m in push_calls]
    check("push contains text_chunk(s)", "text_chunk" in types)
    check("push contains done", types.count("done") == 1)
    check("all proactive=true on text_chunk",
          all(m.get("proactive") for _u, m in push_calls
              if m.get("type") == "text_chunk"))
    check("all proactive_trigger=wake_call",
          all(m.get("proactive_trigger") == "wake_call"
              for _u, m in push_calls if m.get("type") == "text_chunk"))


async def _empty_events():
    return []


# ---------------------------------------------------------------------------
# 5. stage 2: _build_messages detects pending + injects addendum + consumes
# ---------------------------------------------------------------------------

async def test_stage2_detection_and_injection():
    print("\n[wake_call — stage 2 detects + injects + consumes]")
    await _setup_db()
    await _ensure_user("wc_stage2_user")

    from backend.config import config_yaml
    from backend.database import AsyncSessionLocal
    from backend.database.models import PendingBriefing
    from backend.database.services import (
        add_chat_history, add_pending_briefing,
    )
    from backend.agents.chat import _maybe_build_wake_call_addendum
    from sqlalchemy import select

    # Setup: 上一行 assistant chat_history kind=proactive trigger=wake_call
    async with AsyncSessionLocal() as session:
        await add_chat_history(
            session, "wc_stage2_user", "assistant", "起床啦～",
            kind="proactive", proactive_trigger="wake_call",
            character_id=1, conversation_id=1,
        )
        pending = await add_pending_briefing(
            session, user_id="wc_stage2_user", trigger_name="wake_call",
            briefing_data_json=json.dumps({"city": "东京", "calendar_events": []}),
            character_id=1, conversation_id=1, ttl_minutes=30,
        )
        pending_id = pending.id

    # Run probe under mode='wake_call'
    with patch.dict(config_yaml, {"proactive": {"mode": "wake_call"}}, clear=False):
        addendum = await _maybe_build_wake_call_addendum(
            "wc_stage2_user", "嗯嗯",
        )

    check("addendum returned (not None)", addendum is not None)
    if addendum:
        check("addendum mentions user_text", "嗯嗯" in addendum)
        check("addendum has stage 2 instructions",
              "简短模糊" in addendum and "好奇精神" in addendum and "拒绝起床" in addendum)
        check("addendum mentions snooze tool",
              "proactive.snooze_wake_call" in addendum or "snooze" in addendum.lower())
        check("addendum embeds briefing_data_json",
              "东京" in addendum)

    # 验证 pending 已被消费
    async with AsyncSessionLocal() as session:
        fetched = (await session.execute(
            select(PendingBriefing).where(PendingBriefing.id == pending_id)
        )).scalar_one_or_none()
    check("pending consumed_at populated",
          fetched is not None and fetched.consumed_at is not None)

    # 第二次调用：pending 已 consumed → 应返 None
    with patch.dict(config_yaml, {"proactive": {"mode": "wake_call"}}, clear=False):
        addendum2 = await _maybe_build_wake_call_addendum(
            "wc_stage2_user", "嗯嗯",
        )
    check("second probe returns None (idempotent)", addendum2 is None)


async def test_stage2_skips_when_no_wake_call_in_history():
    print("\n[wake_call — stage 2 skips when last assistant turn != wake_call]")
    await _setup_db()
    await _ensure_user("wc_skip_user")

    from backend.config import config_yaml
    from backend.database import AsyncSessionLocal
    from backend.database.services import add_chat_history, add_pending_briefing
    from backend.agents.chat import _maybe_build_wake_call_addendum

    async with AsyncSessionLocal() as session:
        # 上一条 assistant turn 不是 wake_call —— 普通聊天回复
        await add_chat_history(
            session, "wc_skip_user", "assistant", "今天天气不错呢",
            kind="normal", character_id=1, conversation_id=1,
        )
        await add_pending_briefing(
            session, user_id="wc_skip_user", trigger_name="wake_call",
            briefing_data_json="{}", character_id=1, conversation_id=1,
        )

    with patch.dict(config_yaml, {"proactive": {"mode": "wake_call"}}, clear=False):
        out = await _maybe_build_wake_call_addendum("wc_skip_user", "嗯")
    check("returns None (last assistant != wake_call)", out is None)


async def test_stage2_skips_when_mode_not_wake_call():
    print("\n[wake_call — stage 2 skips when proactive.mode != wake_call]")
    await _setup_db()
    await _ensure_user("wc_mode_user")

    from backend.config import config_yaml
    from backend.database import AsyncSessionLocal
    from backend.database.services import add_chat_history, add_pending_briefing
    from backend.agents.chat import _maybe_build_wake_call_addendum

    async with AsyncSessionLocal() as session:
        await add_chat_history(
            session, "wc_mode_user", "assistant", "起床啦～",
            kind="proactive", proactive_trigger="wake_call",
            character_id=1, conversation_id=1,
        )
        await add_pending_briefing(
            session, user_id="wc_mode_user", trigger_name="wake_call",
            briefing_data_json="{}", character_id=1, conversation_id=1,
        )

    with patch.dict(config_yaml,
                    {"proactive": {"mode": "morning_briefing"}}, clear=False):
        out = await _maybe_build_wake_call_addendum("wc_mode_user", "嗯")
    check("mode!=wake_call ⇒ returns None", out is None)


async def test_stage2_skips_when_pending_expired():
    print("\n[wake_call — stage 2 skips when pending TTL expired]")
    await _setup_db()
    await _ensure_user("wc_ttl_user")

    from backend.config import config_yaml
    from backend.database import AsyncSessionLocal, engine
    from backend.database.services import add_chat_history, add_pending_briefing
    from backend.agents.chat import _maybe_build_wake_call_addendum
    from sqlalchemy import text as sa_text

    async with AsyncSessionLocal() as session:
        await add_chat_history(
            session, "wc_ttl_user", "assistant", "起床啦～",
            kind="proactive", proactive_trigger="wake_call",
            character_id=1, conversation_id=1,
        )
        pending = await add_pending_briefing(
            session, user_id="wc_ttl_user", trigger_name="wake_call",
            briefing_data_json="{}", character_id=1, conversation_id=1,
            ttl_minutes=30,
        )
        pid = pending.id

    # Hack: 把 pending.created_at 改成 1 小时前，模拟 TTL 超时
    one_hour_ago = datetime.utcnow() - timedelta(hours=1)
    async with engine.begin() as conn:
        await conn.execute(
            sa_text("UPDATE pending_briefings SET created_at = :ts WHERE id = :i"),
            {"ts": one_hour_ago, "i": pid},
        )

    with patch.dict(config_yaml, {"proactive": {"mode": "wake_call"}}, clear=False):
        out = await _maybe_build_wake_call_addendum("wc_ttl_user", "嗯")
    check("expired pending ⇒ returns None", out is None)


# ---------------------------------------------------------------------------
# 6. _build_messages 自身集成（带 stage 1 prompt 时跳过 wake_call 探测）
# ---------------------------------------------------------------------------

async def test_build_messages_skips_addendum_during_stage1():
    """stage 1 自己调 ChatAgent.stream 时，extra_system 含"用 8-15 个字
    叫用户起床" → _build_messages 不应再注入 wake_call addendum（避免无限
    递归 / 重复 prompt）。
    """
    print("\n[wake_call — _build_messages skips addendum during stage 1]")
    await _setup_db()
    await _ensure_user("wc_recursion_user")

    from backend.config import config_yaml
    from backend.database import AsyncSessionLocal
    from backend.database.services import add_chat_history, add_pending_briefing
    from backend.agents.chat import _build_messages

    async with AsyncSessionLocal() as session:
        await add_chat_history(
            session, "wc_recursion_user", "assistant", "之前那条 wake call",
            kind="proactive", proactive_trigger="wake_call",
            character_id=1, conversation_id=1,
        )
        await add_pending_briefing(
            session, user_id="wc_recursion_user", trigger_name="wake_call",
            briefing_data_json="{}", character_id=1, conversation_id=1,
        )

    from backend.proactive.triggers.wake_call_briefing import (
        WAKE_CALL_STAGE1_SENTINEL,
    )
    stage1_prompt = WAKE_CALL_STAGE1_SENTINEL + "\n8-15 字叫醒用户。"

    with patch.dict(config_yaml, {"proactive": {"mode": "wake_call"}}, clear=False):
        msgs = await _build_messages(
            user_id="wc_recursion_user",
            text="[proactive trigger]",
            character_id=1,
            extra_system=stage1_prompt,
        )

    sys_prompt = next((m["content"] for m in msgs if m["role"] == "system"), "")
    check("stage 1 sentinel present in system prompt",
          WAKE_CALL_STAGE1_SENTINEL in sys_prompt)
    check("wake_call addendum NOT injected during stage 1",
          "wake_call 简报" not in sys_prompt and "简短模糊" not in sys_prompt)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

async def main():
    await test_trigger_metadata()
    await test_stage1_system_prompt_constraints()
    await test_mode_mutex_helper()
    await test_aggregate_briefing_data()
    await test_run_wake_call_stage1_pushes_short_and_writes_pending()
    await test_stage2_detection_and_injection()
    await test_stage2_skips_when_no_wake_call_in_history()
    await test_stage2_skips_when_mode_not_wake_call()
    await test_stage2_skips_when_pending_expired()
    await test_build_messages_skips_addendum_during_stage1()

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
