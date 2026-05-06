"""Tests for backend.integrations.google_calendar — v3-G chunk 1.

不能跑真实 Google API（CI 没 credentials，国内访问也不可靠），全部 mock
``googleapiclient.discovery.build``。
"""
import asyncio
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 把 SKYLER_HOME / TOKEN_PATH / CREDENTIALS_PATH 换到 tmpdir，避免污染真实
# ~/.skyler。必须在 import google_calendar 之前 patch。
_TMP_HOME = Path(tempfile.mkdtemp(prefix="skyler-test-"))

import backend.integrations.google_calendar as gc

gc.SKYLER_HOME = _TMP_HOME
gc.CREDENTIALS_PATH = _TMP_HOME / "google_credentials.json"
gc.TOKEN_PATH = _TMP_HOME / "google_token.json"

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))


def _reset_state():
    """每个 test case 跑前清掉 tmp files 和 service cache。"""
    for f in (gc.CREDENTIALS_PATH, gc.TOKEN_PATH):
        if f.exists():
            f.unlink()
    gc._reset_service_cache()


# ---------------------------------------------------------------------------
# 1. credentials presence
# ---------------------------------------------------------------------------

async def test_credentials_presence():
    print("\n[google_calendar — credentials presence]")
    _reset_state()
    check("no credentials → False", not gc.is_credentials_present())

    gc.CREDENTIALS_PATH.write_text("{}")
    check("credentials file present → True", gc.is_credentials_present())

    _reset_state()


# ---------------------------------------------------------------------------
# 2. is_authorized — no token / bad token / valid token
# ---------------------------------------------------------------------------

async def test_authorized_states():
    print("\n[google_calendar — authorized states]")
    _reset_state()
    check("no token → not authorized", not gc.is_authorized())

    gc.TOKEN_PATH.write_text("not valid json")
    check("invalid token file → not authorized", not gc.is_authorized())
    _reset_state()

    fake_creds = MagicMock()
    fake_creds.valid = True
    fake_creds.expired = False
    with patch.object(
        gc.Credentials, "from_authorized_user_file", return_value=fake_creds,
    ):
        gc.TOKEN_PATH.write_text("{}")
        check("valid creds → authorized", gc.is_authorized())
    _reset_state()


# ---------------------------------------------------------------------------
# 3. health_check 三档
# ---------------------------------------------------------------------------

async def test_health_check_no_credentials():
    print("\n[google_calendar — health: no credentials]")
    _reset_state()
    h = await gc.health_check()
    check("no credentials → warn", h["status"] == "warn")
    check("no credentials → has error msg", "credentials" in (h.get("error") or ""))


async def test_health_check_unauthorized():
    print("\n[google_calendar — health: unauthorized]")
    _reset_state()
    gc.CREDENTIALS_PATH.write_text("{}")
    h = await gc.health_check()
    check("credentials but no token → warn", h["status"] == "warn")
    check("warn message includes 未授权", "未授权" in (h.get("error") or ""))
    _reset_state()


async def test_health_check_authorized_ok():
    print("\n[google_calendar — health: authorized + API ok]")
    _reset_state()
    gc.CREDENTIALS_PATH.write_text("{}")

    fake_creds = MagicMock(); fake_creds.valid = True; fake_creds.expired = False
    fake_events = MagicMock()
    fake_events.list().execute.return_value = {"items": []}
    fake_service = MagicMock()
    fake_service.events.return_value = fake_events

    with patch.object(gc.Credentials, "from_authorized_user_file", return_value=fake_creds), \
         patch.object(gc, "build", return_value=fake_service):
        gc.TOKEN_PATH.write_text("{}")
        h = await gc.health_check()
    check("authorized + API ok → healthy", h["status"] == "healthy", f"got {h}")
    _reset_state()


async def test_health_check_network_error_is_warn_not_error():
    print("\n[google_calendar — health: network err → warn (国内常态)]")
    _reset_state()
    gc.CREDENTIALS_PATH.write_text("{}")

    fake_creds = MagicMock(); fake_creds.valid = True; fake_creds.expired = False

    def _network_boom(*a, **k):
        raise OSError("DNS resolution failed (proxy down)")

    with patch.object(gc.Credentials, "from_authorized_user_file", return_value=fake_creds), \
         patch.object(gc, "build", side_effect=_network_boom):
        gc.TOKEN_PATH.write_text("{}")
        h = await gc.health_check()
    # 关键：网络异常**不能**是 error，必须降级 warn（国内常态）
    check("network err → warn (not error)", h["status"] == "warn", f"got {h}")
    _reset_state()


# ---------------------------------------------------------------------------
# 4. list_events_in_range — normalisation + retry on transient
# ---------------------------------------------------------------------------

async def test_list_events_normalises_payload():
    print("\n[google_calendar — list_events normalisation]")
    _reset_state()
    gc.CREDENTIALS_PATH.write_text("{}")

    fake_creds = MagicMock(); fake_creds.valid = True; fake_creds.expired = False
    raw_items = [
        {
            "id": "evt1",
            "summary": "晨会",
            "start": {"dateTime": "2026-05-07T09:00:00+09:00"},
            "end":   {"dateTime": "2026-05-07T10:00:00+09:00"},
            "location": "Zoom",
        },
        {
            # all-day 事件 — 用 date 字段
            "id": "evt2",
            "start": {"date": "2026-05-07"},
            "end":   {"date": "2026-05-08"},
            # 故意省略 summary，期望兜底 (无标题)
        },
    ]
    fake_events = MagicMock()
    fake_events.list().execute.return_value = {"items": raw_items}
    fake_service = MagicMock()
    fake_service.events.return_value = fake_events

    with patch.object(gc.Credentials, "from_authorized_user_file", return_value=fake_creds), \
         patch.object(gc, "build", return_value=fake_service):
        gc.TOKEN_PATH.write_text("{}")
        now = datetime.now(timezone.utc)
        events = await gc.list_events_in_range(now, now + timedelta(days=1))

    check("returns 2 events", len(events) == 2)
    check("event 1 title", events[0]["title"] == "晨会")
    check("event 1 not all_day", events[0]["all_day"] is False)
    check("event 2 fallback title", events[1]["title"] == "(无标题)")
    check("event 2 all_day flag", events[1]["all_day"] is True)
    _reset_state()


async def test_list_events_retries_on_transient_error():
    print("\n[google_calendar — retry on transient OSError]")
    _reset_state()
    gc.CREDENTIALS_PATH.write_text("{}")

    fake_creds = MagicMock(); fake_creds.valid = True; fake_creds.expired = False
    fake_events = MagicMock()
    # 头两次抛 OSError，第三次成功
    call_count = {"n": 0}
    def _execute_side_effect():
        call_count["n"] += 1
        if call_count["n"] < 3:
            raise OSError("transient")
        return {"items": []}
    fake_events.list().execute.side_effect = _execute_side_effect
    fake_service = MagicMock()
    fake_service.events.return_value = fake_events

    with patch.object(gc.Credentials, "from_authorized_user_file", return_value=fake_creds), \
         patch.object(gc, "build", return_value=fake_service):
        gc.TOKEN_PATH.write_text("{}")
        now = datetime.now(timezone.utc)
        events = await gc.list_events_in_range(now, now + timedelta(hours=1))

    check("recovered after retries", events == [])
    check("execute called 3x (2 retries)", call_count["n"] == 3, f"called {call_count['n']}x")
    _reset_state()


# ---------------------------------------------------------------------------
# 5. revoke_token
# ---------------------------------------------------------------------------

async def test_revoke_token():
    print("\n[google_calendar — revoke_token]")
    _reset_state()
    check("revoke when absent → False", gc.revoke_token() is False)

    gc.TOKEN_PATH.write_text("{}")
    check("revoke when present → True", gc.revoke_token() is True)
    check("token file removed after revoke", not gc.TOKEN_PATH.exists())
    _reset_state()


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

async def main():
    await test_credentials_presence()
    await test_authorized_states()
    await test_health_check_no_credentials()
    await test_health_check_unauthorized()
    await test_health_check_authorized_ok()
    await test_health_check_network_error_is_warn_not_error()
    await test_list_events_normalises_payload()
    await test_list_events_retries_on_transient_error()
    await test_revoke_token()

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
