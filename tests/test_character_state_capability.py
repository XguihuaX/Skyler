"""Tests for v3-G chunk 3b character_state capability + DB CRUD + decay。"""
import asyncio
import os
import sys
from unittest.mock import patch, AsyncMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Trigger @register_capability decorator side-effects so registry has the
# character.* capabilities visible to test_capabilities_registered.
import backend.capabilities.character_state  # noqa: F401, E402

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
    from backend.database.migrations.v3_g_chunk2_6_pending_briefing import run_migration as m_c26
    from backend.database.migrations.v3_g_chunk3_character_states import run_migration as m_c3
    await init_db()
    await m_f(); await m_z(); await m_c2(); await m_c26(); await m_c3()


# ---------------------------------------------------------------------------
# 1. capability registration metadata
# ---------------------------------------------------------------------------

async def test_capabilities_registered():
    print("\n[character_state — capability metadata]")
    from backend.capabilities import CapabilityRegistry, Consumer
    reg = CapabilityRegistry()

    cap_get = reg.get("character.get_state")
    check("character.get_state present", cap_get is not None)
    if cap_get:
        check("get_state CHAT_AGENT", Consumer.CHAT_AGENT in cap_get.consumers)

    cap_set = reg.get("character.set_activity")
    check("character.set_activity present", cap_set is not None)
    if cap_set:
        check("set_activity CHAT_AGENT", Consumer.CHAT_AGENT in cap_set.consumers)

    cap_decay = reg.get("character.intimacy_decay")
    check("character.intimacy_decay present", cap_decay is not None)
    if cap_decay:
        check("decay SCHEDULER consumer", Consumer.SCHEDULER in cap_decay.consumers)
        check("decay NOT CHAT_AGENT (避免 LLM 调)",
              Consumer.CHAT_AGENT not in cap_decay.consumers)
        check("decay user_visible False",
              cap_decay.user_visible is False)


# ---------------------------------------------------------------------------
# 2. get_or_create_character_state DB CRUD
# ---------------------------------------------------------------------------

async def test_get_or_create_creates_default():
    print("\n[character_state — get_or_create creates default row]")
    await _setup_db()
    from backend.database import AsyncSessionLocal
    from backend.database.services import get_or_create_character_state

    async with AsyncSessionLocal() as session:
        state = await get_or_create_character_state(session, character_id=1)

    check("mood neutral default", state.mood == "neutral")
    check("intimacy 0 default", state.intimacy == 0)
    check("thought None", state.current_thought is None)
    check("activity None", state.current_activity is None)
    check("last_interaction_at set", state.last_interaction_at is not None)

    # 第二次调用：返同一行
    async with AsyncSessionLocal() as session:
        state2 = await get_or_create_character_state(session, character_id=1)
    check("idempotent (same row id)", state2.id == state.id)


# ---------------------------------------------------------------------------
# 3. update_character_state happy path + clamping
# ---------------------------------------------------------------------------

async def test_update_state_mood_intimacy_thought():
    print("\n[character_state — update_state mood + delta + thought + activity]")
    await _setup_db()
    from backend.database import AsyncSessionLocal
    from backend.database.services import (
        reset_character_state, update_character_state,
    )

    # Reset to ensure fresh state (DB file persists across test runs)
    async with AsyncSessionLocal() as session:
        await reset_character_state(session, character_id=300)
        state = await update_character_state(
            session, character_id=300,
            mood="happy",
            intimacy_delta=2,
            thought="觉得用户今天很努力",
            activity="在看书",
        )
    check("mood happy", state.mood == "happy")
    check("intimacy +2 from 0 → 2", state.intimacy == 2)
    check("thought set", state.current_thought == "觉得用户今天很努力")
    check("activity set", state.current_activity == "在看书")


async def test_update_state_intimacy_clamped_per_turn():
    """单轮 LLM 用 ``intimacy_delta=+5`` 应被 clamp 到 +2。"""
    print("\n[character_state — intimacy_delta clamped to ±2 per turn]")
    await _setup_db()
    from backend.database import AsyncSessionLocal
    from backend.database.services import (
        reset_character_state, update_character_state,
    )

    async with AsyncSessionLocal() as session:
        await reset_character_state(session, character_id=301)
        state = await update_character_state(
            session, character_id=301, intimacy_delta=99,
        )
    check("delta=99 clamped to +2",
          state.intimacy == 2, f"got intimacy={state.intimacy}")

    async with AsyncSessionLocal() as session:
        state2 = await update_character_state(
            session, character_id=301, intimacy_delta=-99,
        )
    check("delta=-99 from 2 clamped to -2 → 0",
          state2.intimacy == 0, f"got intimacy={state2.intimacy}")


async def test_update_state_intimacy_floor_zero():
    print("\n[character_state — intimacy floor at 0]")
    await _setup_db()
    from backend.database import AsyncSessionLocal
    from backend.database.services import update_character_state

    from backend.database.services import reset_character_state
    async with AsyncSessionLocal() as session:
        await reset_character_state(session, character_id=302)
        # 起点 0；再来一次 -2 应仍为 0，不为 -2
        state = await update_character_state(
            session, character_id=302, intimacy_delta=-2,
        )
    check("0 - 2 stays at 0",
          state.intimacy == 0, f"got intimacy={state.intimacy}")


async def test_update_state_invalid_mood_silent_skip():
    print("\n[character_state — invalid mood silently skipped]")
    await _setup_db()
    from backend.database import AsyncSessionLocal
    from backend.database.services import update_character_state

    from backend.database.services import reset_character_state
    async with AsyncSessionLocal() as session:
        await reset_character_state(session, character_id=303)
        # initial mood neutral
        state = await update_character_state(
            session, character_id=303, mood="evil_mood",
        )
    check("invalid mood ⇒ stays neutral",
          state.mood == "neutral", f"got mood={state.mood}")


async def test_update_state_thought_truncated():
    print("\n[character_state — thought / activity truncated to 60 chars]")
    await _setup_db()
    from backend.database import AsyncSessionLocal
    from backend.database.services import update_character_state

    long_thought = "x" * 100
    async with AsyncSessionLocal() as session:
        state = await update_character_state(
            session, character_id=304, thought=long_thought,
        )
    check("thought truncated to 60",
          len(state.current_thought) == 60, f"got len={len(state.current_thought)}")


# ---------------------------------------------------------------------------
# 4. get_state capability handler
# ---------------------------------------------------------------------------

async def test_get_state_capability_returns_dict():
    print("\n[character_state — get_state capability handler]")
    await _setup_db()
    from backend.capabilities.character_state import get_state

    out = await get_state(character_id=305)
    check("dict shape", isinstance(out, dict))
    check("character_id echoed", out.get("character_id") == 305)
    check("mood field present", "mood" in out)
    check("intimacy field present", "intimacy" in out)


async def test_get_state_missing_character_id():
    print("\n[character_state — get_state without character_id]")
    from backend.capabilities.character_state import get_state
    out = await get_state(character_id=None)
    check("error returned", "error" in out)


# ---------------------------------------------------------------------------
# 5. set_activity capability + WS push best-effort
# ---------------------------------------------------------------------------

async def test_set_activity_updates_db():
    print("\n[character_state — set_activity DB update + WS push]")
    await _setup_db()
    from backend.capabilities.character_state import set_activity
    from backend.routes import ws as ws_mod

    push_calls: list = []
    async def fake_push(uid, msg):
        push_calls.append((uid, msg))

    with patch.object(ws_mod.connection_manager, "push", fake_push):
        out = await set_activity(
            activity="在烤面包",
            thought="想做点新的尝试",
            character_id=306,
            user_id="default",
        )

    check("ok=True", out.get("ok") is True)
    check("state.activity persisted",
          out["state"].get("activity") == "在烤面包")
    check("WS state_update push happened",
          any(m.get("type") == "state_update" for _u, m in push_calls))


async def test_set_activity_empty_rejected():
    print("\n[character_state — set_activity rejects empty]")
    from backend.capabilities.character_state import set_activity
    out = await set_activity(activity="", character_id=307)
    check("error returned", "error" in out)


# ---------------------------------------------------------------------------
# 6. intimacy_decay
# ---------------------------------------------------------------------------

async def test_intimacy_decay_minus_one():
    print("\n[character_state — intimacy_decay -1 floor 0]")
    await _setup_db()
    from backend.database import AsyncSessionLocal
    from backend.database.services import (
        get_or_create_character_state, update_character_state,
    )
    from backend.capabilities.character_state import intimacy_decay

    # Set up: 1 character with intimacy=5
    async with AsyncSessionLocal() as session:
        await update_character_state(session, character_id=400, intimacy_delta=2)
        await update_character_state(session, character_id=400, intimacy_delta=2)
        await update_character_state(session, character_id=400, intimacy_delta=1)
        state_before = await get_or_create_character_state(session, 400)
    intimacy_before = state_before.intimacy

    # decay 一次：每个 character intimacy -1
    out = await intimacy_decay()
    check("returned dict shape",
          "decayed_count" in out and "total_chars" in out)

    async with AsyncSessionLocal() as session:
        state_after = await get_or_create_character_state(session, 400)
    check("intimacy decreased by 1 (or by 0 if was 0)",
          state_after.intimacy == max(0, intimacy_before - 1),
          f"before={intimacy_before} after={state_after.intimacy}")


# ---------------------------------------------------------------------------
# 7. reset_character_state
# ---------------------------------------------------------------------------

async def test_reset_character_state():
    print("\n[character_state — reset_character_state]")
    await _setup_db()
    from backend.database import AsyncSessionLocal
    from backend.database.services import (
        reset_character_state, update_character_state,
    )

    async with AsyncSessionLocal() as session:
        await update_character_state(
            session, character_id=500,
            mood="happy", intimacy_delta=2, thought="x", activity="y",
        )
        state = await reset_character_state(session, character_id=500)
    check("mood reset to neutral", state.mood == "neutral")
    check("intimacy reset to 0", state.intimacy == 0)
    check("thought reset None", state.current_thought is None)
    check("activity reset None", state.current_activity is None)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

async def main():
    await test_capabilities_registered()
    await test_get_or_create_creates_default()
    await test_update_state_mood_intimacy_thought()
    await test_update_state_intimacy_clamped_per_turn()
    await test_update_state_intimacy_floor_zero()
    await test_update_state_invalid_mood_silent_skip()
    await test_update_state_thought_truncated()
    await test_get_state_capability_returns_dict()
    await test_get_state_missing_character_id()
    await test_set_activity_updates_db()
    await test_set_activity_empty_rejected()
    await test_intimacy_decay_minus_one()
    await test_reset_character_state()

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
