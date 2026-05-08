"""Tests for v3-G chunk 4 Part C — v3-F' trigger pack
(lunch_call / dinner_call / bedtime_chat / long_idle) + heartbeat。

每个 trigger 测：
- metadata（name / cron / sentinel 唯一）
- stage 1 prompt 含 8-15 字约束
- stage 2 addendum builder 占位填充
- _enabled gate（proactive.enabled + triggers.{name}.enabled 双层）
- 注册到 _stage2_registry

long_idle 额外：
- _is_user_in_foreground 判定
- check_and_maybe_fire 三条件 gate
- record_heartbeat round-trip

heartbeat 路由测：POST /api/heartbeat。
"""
import asyncio
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


# Trigger imports activate register_stage2 副作用
import backend.proactive.triggers.wake_call_briefing  # noqa: F401, E402
import backend.proactive.triggers.lunch_call as _lunch_mod  # noqa: E402
import backend.proactive.triggers.dinner_call as _dinner_mod  # noqa: E402
import backend.proactive.triggers.bedtime_chat as _bedtime_mod  # noqa: E402
import backend.proactive.triggers.long_idle as _long_idle_mod  # noqa: E402
from backend.proactive.triggers.lunch_call import LunchCallTrigger  # noqa: E402
from backend.proactive.triggers.dinner_call import DinnerCallTrigger  # noqa: E402
from backend.proactive.triggers.bedtime_chat import BedtimeChatTrigger  # noqa: E402
from backend.proactive.triggers.long_idle import LongIdleTrigger  # noqa: E402
from backend.proactive.triggers._stage2_registry import (  # noqa: E402
    all_stage1_sentinels, build_stage2_addendum, get_stage1_sentinel,
)


# ---------------------------------------------------------------------------
# 1. 5 sentinels 都注册了，互不冲突
# ---------------------------------------------------------------------------

def test_all_sentinels_registered():
    print("\n[trigger pack — all 5 stage 1 sentinels registered]")
    sents = all_stage1_sentinels()
    expected = [
        "[wake_call_stage1_v1]",
        "[lunch_call_stage1_v1]",
        "[dinner_call_stage1_v1]",
        "[bedtime_chat_stage1_v1]",
        "[long_idle_stage1_v1]",
    ]
    for s in expected:
        check(f"{s} present", s in sents, f"got: {sents}")
    check("all 5 unique", len(set(sents)) == len(expected),
          f"sents={sents}")


# ---------------------------------------------------------------------------
# 2. metadata sanity per trigger
# ---------------------------------------------------------------------------

def _check_trigger_metadata(label: str, trigger, expected_name: str):
    check(f"{label} name = {expected_name!r}",
          trigger.name == expected_name)
    check(f"{label} enable_search False",
          trigger.enable_search is False)


def test_lunch_metadata():
    print("\n[lunch_call — metadata]")
    t_wd = LunchCallTrigger(weekend=False)
    t_we = LunchCallTrigger(weekend=True)
    _check_trigger_metadata("lunch (weekday)", t_wd, "lunch_call")
    check("weekday cron has 1-5 weekday spec",
          "1-5" in (t_wd.cron_expr or ""), f"got {t_wd.cron_expr!r}")
    check("weekend cron has 0,6 weekday spec",
          "0,6" in (t_we.cron_expr or "") or "6,0" in (t_we.cron_expr or ""),
          f"got {t_we.cron_expr!r}")


def test_dinner_metadata():
    print("\n[dinner_call — metadata]")
    t = DinnerCallTrigger()
    _check_trigger_metadata("dinner", t, "dinner_call")
    check("default cron 30 18 * * *", t.cron_expr == "30 18 * * *",
          f"got {t.cron_expr!r}")


def test_bedtime_metadata():
    print("\n[bedtime_chat — metadata]")
    t = BedtimeChatTrigger()
    _check_trigger_metadata("bedtime", t, "bedtime_chat")
    check("default cron 30 22 * * *", t.cron_expr == "30 22 * * *",
          f"got {t.cron_expr!r}")


def test_long_idle_metadata():
    print("\n[long_idle — metadata]")
    t = LongIdleTrigger()
    _check_trigger_metadata("long_idle", t, "long_idle")
    check("uses interval_seconds (not cron)",
          t.cron_expr is None and t.interval_seconds is not None)
    check("interval >=60 (5 min default)",
          (t.interval_seconds or 0) >= 60, f"got {t.interval_seconds}")


# ---------------------------------------------------------------------------
# 3. stage 1 prompt 含 8-15 字强约束
# ---------------------------------------------------------------------------

async def _check_prompt_constraints(label: str, trigger):
    prompt = await trigger.build_system_prompt(None)
    check(f"{label} prompt non-empty + len > 200",
          len(prompt) > 200, f"got len={len(prompt)}")
    check(f"{label} 8-15 字约束", "8-15" in prompt or "8 至 15" in prompt)
    check(f"{label} 严禁词条", "严禁" in prompt)
    check(f"{label} sentinel embedded",
          get_stage1_sentinel(trigger.name) in prompt)


async def test_stage1_prompts_per_trigger():
    print("\n[stage 1 prompts — per-trigger constraints]")
    await _check_prompt_constraints("lunch", LunchCallTrigger())
    await _check_prompt_constraints("dinner", DinnerCallTrigger())
    await _check_prompt_constraints("bedtime", BedtimeChatTrigger())
    await _check_prompt_constraints("long_idle", LongIdleTrigger())


# ---------------------------------------------------------------------------
# 4. stage 2 addendum builder
# ---------------------------------------------------------------------------

def test_stage2_addendum_builders():
    print("\n[stage 2 addendums — builder + placeholder fill]")
    for trig_name, scene_word in [
        ("lunch_call", "午饭呼叫"),
        ("dinner_call", "晚饭呼叫"),
        ("bedtime_chat", "睡前问候"),
        ("long_idle", "轻触你"),
    ]:
        out = build_stage2_addendum(
            trig_name, user_text="嗯嗯", briefing_data_json='{"city":"东京"}', city="东京",
        )
        check(f"{trig_name} returns string",
              isinstance(out, str) and len(out) > 200)
        check(f"{trig_name} contains scene label '{scene_word}'",
              scene_word in (out or ""), f"got first 100: {out[:100]!r}")
        check(f"{trig_name} embeds user_text",
              "嗯嗯" in (out or ""))
        check(f"{trig_name} embeds briefing_data_json",
              "东京" in (out or ""))
        check(f"{trig_name} mentions 自适应规则",
              ("简短模糊" in out) and ("好奇精神" in out))


def test_stage2_unknown_trigger_returns_none():
    print("\n[stage 2 — unknown trigger name → None]")
    out = build_stage2_addendum("nonexistent_trigger", "嗯", "{}", "东京")
    check("returns None", out is None)


# ---------------------------------------------------------------------------
# 5. _enabled gating —— proactive.enabled AND triggers.X.enabled
# ---------------------------------------------------------------------------

def test_lunch_enabled_gating():
    print("\n[lunch_call — _enabled gate]")
    # both true
    with patch.dict(_lunch_mod.config_yaml,
                    {"proactive": {"enabled": True, "triggers": {"lunch_call": {"enabled": True}}}},
                    clear=False):
        check("both True → enabled", _lunch_mod._enabled() is True)
    # proactive off
    with patch.dict(_lunch_mod.config_yaml,
                    {"proactive": {"enabled": False, "triggers": {"lunch_call": {"enabled": True}}}},
                    clear=False):
        check("proactive off → disabled", _lunch_mod._enabled() is False)
    # trigger off
    with patch.dict(_lunch_mod.config_yaml,
                    {"proactive": {"enabled": True, "triggers": {"lunch_call": {"enabled": False}}}},
                    clear=False):
        check("trigger off → disabled", _lunch_mod._enabled() is False)


def test_bedtime_default_disabled():
    """bedtime_chat / long_idle 默认 disabled。"""
    print("\n[bedtime_chat — default disabled]")
    with patch.dict(_bedtime_mod.config_yaml,
                    {"proactive": {"enabled": True, "triggers": {"bedtime_chat": {}}}},
                    clear=False):
        check("triggers.bedtime_chat 缺 enabled 字段 → False (default)",
              _bedtime_mod._enabled() is False)


def test_long_idle_default_disabled():
    print("\n[long_idle — default disabled]")
    with patch.dict(_long_idle_mod.config_yaml,
                    {"proactive": {"enabled": True, "triggers": {"long_idle": {}}}},
                    clear=False):
        check("default disabled", _long_idle_mod._enabled() is False)


# ---------------------------------------------------------------------------
# 6. long_idle heartbeat + check_and_maybe_fire
# ---------------------------------------------------------------------------

def test_record_heartbeat_round_trip():
    print("\n[long_idle — record_heartbeat → _is_user_in_foreground]")
    _long_idle_mod._LAST_HEARTBEAT.clear()
    check("no record → not in foreground",
          _long_idle_mod._is_user_in_foreground("uX") is False)
    _long_idle_mod.record_heartbeat("uX")
    check("after record → in foreground",
          _long_idle_mod._is_user_in_foreground("uX") is True)


def test_heartbeat_grace_window():
    """grace_seconds 之外的 heartbeat 视为离线。"""
    print("\n[long_idle — heartbeat grace window]")
    _long_idle_mod._LAST_HEARTBEAT["uY"] = datetime.utcnow() - timedelta(seconds=120)
    with patch.dict(_long_idle_mod.config_yaml,
                    {"proactive": {"triggers": {"long_idle": {"heartbeat_grace_seconds": 30}}}},
                    clear=False):
        check("120s ago > 30s grace → not in foreground",
              _long_idle_mod._is_user_in_foreground("uY") is False)


async def test_check_and_maybe_fire_disabled_skips():
    print("\n[long_idle — check_and_maybe_fire skips when disabled]")
    fired = {"called": False}
    async def fake_run(_t, **_): fired["called"] = True
    with patch.dict(_long_idle_mod.config_yaml,
                    {"proactive": {"enabled": True, "triggers": {"long_idle": {"enabled": False}}}},
                    clear=False), \
         patch("backend.proactive.engine.run_wake_call_trigger", fake_run):
        await _long_idle_mod.check_and_maybe_fire()
    check("disabled → run_wake_call_trigger NOT called",
          fired["called"] is False)


async def test_check_and_maybe_fire_no_heartbeat_skips():
    print("\n[long_idle — no heartbeat → skip]")
    _long_idle_mod._LAST_HEARTBEAT.clear()
    fired = {"called": False}
    async def fake_run(_t, **_): fired["called"] = True
    with patch.dict(_long_idle_mod.config_yaml,
                    {"proactive": {"enabled": True, "triggers": {"long_idle": {"enabled": True}}}},
                    clear=False), \
         patch("backend.proactive.engine.run_wake_call_trigger", fake_run):
        await _long_idle_mod.check_and_maybe_fire()
    check("no heartbeat → not fired", fired["called"] is False)


async def test_check_and_maybe_fire_recent_user_msg_skips():
    """heartbeat ok 但用户最近刚说过话（< threshold）→ skip。"""
    print("\n[long_idle — recent user msg skips]")
    from backend.database import init_db, AsyncSessionLocal
    from backend.database.services import (
        add_chat_history, create_user, get_user,
    )
    from backend.database.migrations.v3_e1_z import run_migration as m_z
    from backend.database.migrations.v3_f import run_migration as m_f
    from backend.database.migrations.v3_g_chunk2_proactive import run_migration as m_c2
    from backend.database.migrations.v3_g_chunk2_6_pending_briefing import run_migration as m_c26
    await init_db(); await m_f(); await m_z(); await m_c2(); await m_c26()
    async with AsyncSessionLocal() as session:
        if await get_user(session, "default") is None:
            await create_user(session, "default", "default")
        await add_chat_history(session, "default", "user", "刚刚说的话")

    _long_idle_mod.record_heartbeat("default")
    fired = {"called": False}
    async def fake_run(_t, **_): fired["called"] = True
    with patch.dict(_long_idle_mod.config_yaml,
                    {"proactive": {
                        "enabled": True,
                        "triggers": {"long_idle": {
                            "enabled": True,
                            "idle_threshold_minutes": 30,
                            "cooldown_minutes": 90,
                            "heartbeat_grace_seconds": 60,
                        }},
                     }, "default_user_id": "default"},
                    clear=False), \
         patch("backend.proactive.engine.run_wake_call_trigger", fake_run):
        await _long_idle_mod.check_and_maybe_fire()
    check("recent user msg → not fired", fired["called"] is False)


# ---------------------------------------------------------------------------
# 7. heartbeat HTTP route
# ---------------------------------------------------------------------------

def test_heartbeat_route():
    print("\n[heartbeat — POST /api/heartbeat]")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.routes.character_state_api import router

    _long_idle_mod._LAST_HEARTBEAT.clear()

    app = FastAPI()
    app.include_router(router, prefix="/api")
    client = TestClient(app)
    r = client.post("/api/heartbeat", json={"user_id": "test_hb"})
    check("status 200", r.status_code == 200, f"got {r.status_code}")
    check("ok=True", r.json().get("ok") is True)
    check("recorded last_heartbeat",
          "test_hb" in _long_idle_mod._LAST_HEARTBEAT)


def test_heartbeat_route_default_user():
    print("\n[heartbeat — default user_id from config]")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.routes.character_state_api import router

    app = FastAPI()
    app.include_router(router, prefix="/api")
    client = TestClient(app)
    r = client.post("/api/heartbeat", json={})
    check("status 200", r.status_code == 200)
    check("ok=True", r.json().get("ok") is True)


# ---------------------------------------------------------------------------
# 8. Stage 2 用户响应不同风格 — addendum 包含正确分支说明
# ---------------------------------------------------------------------------

def test_stage2_addendum_4_styles_per_trigger():
    print("\n[stage 2 addendum — all 4 user-style branches present]")
    out = build_stage2_addendum(
        "lunch_call", user_text="嗯", briefing_data_json="{}", city="东京",
    )
    for branch in ("简短模糊", "好奇精神", "拒绝场景", "切换话题"):
        check(f"lunch addendum has {branch} branch",
              branch in (out or ""), f"got first 200: {out[:200]!r}")


# ---------------------------------------------------------------------------
# 9. 一个 trigger 的 sentinel 不会被另一个 trigger 误识别
# ---------------------------------------------------------------------------

def test_sentinel_uniqueness():
    print("\n[sentinels — distinct strings, no aliasing]")
    sents = all_stage1_sentinels()
    for i, s in enumerate(sents):
        for j, t in enumerate(sents):
            if i != j:
                check(f"{s!r} not subset of {t!r}",
                      s not in t, f"sentinel collision detected!")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

async def main_async():
    test_all_sentinels_registered()
    test_lunch_metadata()
    test_dinner_metadata()
    test_bedtime_metadata()
    test_long_idle_metadata()
    await test_stage1_prompts_per_trigger()
    test_stage2_addendum_builders()
    test_stage2_unknown_trigger_returns_none()
    test_lunch_enabled_gating()
    test_bedtime_default_disabled()
    test_long_idle_default_disabled()
    test_record_heartbeat_round_trip()
    test_heartbeat_grace_window()
    await test_check_and_maybe_fire_disabled_skips()
    await test_check_and_maybe_fire_no_heartbeat_skips()
    await test_check_and_maybe_fire_recent_user_msg_skips()
    test_heartbeat_route()
    test_heartbeat_route_default_user()
    test_stage2_addendum_4_styles_per_trigger()
    test_sentinel_uniqueness()


def main():
    asyncio.run(main_async())
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
