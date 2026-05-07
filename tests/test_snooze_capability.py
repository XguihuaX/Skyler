"""Tests for v3-G chunk 2.6 — proactive.snooze_wake_call capability。

不启 cron scheduler；直接 mock APScheduler ``add_job`` 调用 + 手动建一个
fake ``get_job`` return 拟造 next_run_time。
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))


# ---------------------------------------------------------------------------
# 1. capability registered
# ---------------------------------------------------------------------------

async def test_capability_registered():
    print("\n[snooze — capability registered]")
    # Trigger import side-effect
    import backend.proactive.snooze_capability  # noqa: F401
    from backend.capabilities import CapabilityRegistry, Consumer
    reg = CapabilityRegistry()
    cap = reg.get("proactive.snooze_wake_call")
    check("capability present", cap is not None)
    if cap:
        check("CHAT_AGENT consumer", Consumer.CHAT_AGENT in cap.consumers)
        check("user_visible False (tool surface 噪音减少)",
              cap.user_visible is False)
        params = cap.parameters_schema or {}
        props = (params.get("properties") or {})
        m = props.get("minutes") or {}
        check("minutes 5-120 range",
              m.get("minimum") == 5 and m.get("maximum") == 120)


# ---------------------------------------------------------------------------
# 2. snooze schedules a one-shot DateTrigger job (no conflict)
# ---------------------------------------------------------------------------

async def test_snooze_schedules_one_shot():
    print("\n[snooze — schedules one-shot job (no conflict)]")
    from backend.proactive.snooze_capability import (
        snooze_wake_call, WAKE_CALL_CRON_JOB_ID,
    )
    from backend.scheduler import cron as cron_module

    # Fake scheduler with no current cron job (no conflict)
    fake_sched = MagicMock()
    fake_sched.timezone = ZoneInfo("Asia/Tokyo")
    fake_sched.get_job.return_value = None  # no wake_call cron registered
    fake_sched.add_job = MagicMock()

    with patch.object(cron_module, "_scheduler", fake_sched):
        out = await snooze_wake_call(minutes=20)

    check("ok=True", out.get("ok") is True, f"got {out}")
    check("run_at present (ISO string)", isinstance(out.get("run_at"), str))
    check("job_id wake_call_snooze_*",
          isinstance(out.get("job_id"), str)
          and out["job_id"].startswith("wake_call_snooze_"))
    check("add_job called once", fake_sched.add_job.call_count == 1)

    args, kwargs = fake_sched.add_job.call_args
    from apscheduler.triggers.date import DateTrigger
    check("trigger is DateTrigger",
          isinstance(kwargs.get("trigger"), DateTrigger),
          f"got {type(kwargs.get('trigger'))}")
    # Lookup ensures the cron job id used for conflict detection
    fake_sched.get_job.assert_any_call(WAKE_CALL_CRON_JOB_ID)


# ---------------------------------------------------------------------------
# 3. conflict avoidance: skip when next regular cron is sooner
# ---------------------------------------------------------------------------

async def test_snooze_skips_when_cron_sooner():
    print("\n[snooze — skip when next regular cron run is sooner]")
    from backend.proactive.snooze_capability import snooze_wake_call
    from backend.scheduler import cron as cron_module

    tz = ZoneInfo("Asia/Tokyo")
    # 假装下次正常 cron 还有 10 分钟，但用户想 snooze 30 分钟 → 跳过
    near_future = datetime.now(tz) + timedelta(minutes=10)
    fake_job = MagicMock()
    fake_job.next_run_time = near_future
    fake_sched = MagicMock()
    fake_sched.timezone = tz
    fake_sched.get_job.return_value = fake_job
    fake_sched.add_job = MagicMock()

    with patch.object(cron_module, "_scheduler", fake_sched):
        out = await snooze_wake_call(minutes=30)

    check("ok=False (skipped)", out.get("ok") is False)
    check("message mentions cron",
          isinstance(out.get("message"), str) and "cron" in out["message"])
    check("add_job NOT called", fake_sched.add_job.call_count == 0)


# ---------------------------------------------------------------------------
# 4. minutes coercion (out of range → default)
# ---------------------------------------------------------------------------

async def test_snooze_invalid_minutes_uses_default():
    print("\n[snooze — invalid minutes coerced to default]")
    from backend.proactive.snooze_capability import snooze_wake_call
    from backend.scheduler import cron as cron_module

    fake_sched = MagicMock()
    fake_sched.timezone = ZoneInfo("Asia/Tokyo")
    fake_sched.get_job.return_value = None
    fake_sched.add_job = MagicMock()

    with patch.object(cron_module, "_scheduler", fake_sched):
        out_zero = await snooze_wake_call(minutes=0)         # below 5
        out_huge = await snooze_wake_call(minutes=99999)     # above 120
        out_bad = await snooze_wake_call(minutes="abc")     # type:ignore[arg-type]

    check("minutes=0 → ok=True (coerced to default 30)",
          out_zero.get("ok") is True)
    check("minutes=99999 → ok=True (coerced to default 30)",
          out_huge.get("ok") is True)
    check("minutes='abc' → ok=True (coerced to default 30)",
          out_bad.get("ok") is True)


# ---------------------------------------------------------------------------
# 5. handler imports without registering twice (idempotent module reload safe)
# ---------------------------------------------------------------------------

async def test_handler_returns_dict_shape():
    print("\n[snooze — handler returns shape contract]")
    from backend.proactive.snooze_capability import snooze_wake_call
    from backend.scheduler import cron as cron_module

    fake_sched = MagicMock()
    fake_sched.timezone = ZoneInfo("Asia/Tokyo")
    fake_sched.get_job.return_value = None
    fake_sched.add_job = MagicMock()

    with patch.object(cron_module, "_scheduler", fake_sched):
        out = await snooze_wake_call(minutes=15)

    for key in ("ok", "run_at", "message"):
        check(f"shape contract: '{key}' present", key in out)
    check("ok is bool", isinstance(out["ok"], bool))


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

async def main():
    await test_capability_registered()
    await test_snooze_schedules_one_shot()
    await test_snooze_skips_when_cron_sooner()
    await test_snooze_invalid_minutes_uses_default()
    await test_handler_returns_dict_shape()

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
