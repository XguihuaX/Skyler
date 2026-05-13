"""chunk 14 — activity_timeline 全套回归。

Part A: schema + migration 幂等
Part B: session writer poll handler(boundary / blacklist / short / idle)
Part C: Timeline API GET / DELETE single / DELETE by date
Part D: 3 capabilities(get_today_summary / get_recent_apps / search_history)
Part E: ChatAgent format_today_activity_for_prompt 注入(+ 与 chunk 11
        profile 注入不冲突)
Part F: 隐私(黑名单不写入 / search_history 不返 idle / 总开关 OFF 不写)
Part G: cleanup_old_sessions cron
"""
from __future__ import annotations

import asyncio  # noqa: F401
import os
import sqlite3
import sys
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.database import engine
from backend.integrations import activity_monitor as am
from backend.integrations.activity_watcher import ActivityState
from backend.services import activity_timeline as at
from backend.routes import activity_api as api


_TEST_USER = "__chunk14_test__"


@pytest.fixture(autouse=True)
async def _clean_test_rows():
    """每 test 前后清自己的 user_id 行,不踩其他测试 + 真用户数据。"""
    async with engine.begin() as conn:
        await conn.execute(text(
            "DELETE FROM activity_sessions WHERE user_id = :uid"
        ), {"uid": _TEST_USER})
    at.reset_state_for_test()
    yield
    async with engine.begin() as conn:
        await conn.execute(text(
            "DELETE FROM activity_sessions WHERE user_id = :uid"
        ), {"uid": _TEST_USER})
    at.reset_state_for_test()


async def _seed(rows: list[tuple]) -> None:
    """rows: [(offset_seconds_before_now, duration_seconds, app, url, title,
               category, is_idle_filtered), ...]"""
    now = datetime.utcnow().replace(microsecond=0)
    async with engine.begin() as conn:
        for offset, dur, app, url, title, cat, idle in rows:
            sat = now - timedelta(seconds=offset)
            eat = sat + timedelta(seconds=dur)
            await conn.execute(text(
                "INSERT INTO activity_sessions("
                "  user_id, start_at, end_at, duration_seconds,"
                "  app_name, browser_url, browser_title, category, is_idle_filtered"
                ") VALUES (:u, :s, :e, :d, :a, :url, :t, :c, :i)"
            ), {
                "u": _TEST_USER, "s": sat, "e": eat, "d": dur,
                "a": app, "url": url, "t": title, "c": cat,
                "i": 1 if idle else 0,
            })


# ===========================================================================
# Part A: schema + migration 幂等
# ===========================================================================


async def test_schema_table_and_indexes_present() -> None:
    """migration 已跑 → activity_sessions 表 + 2 index 在。"""
    async with engine.begin() as conn:
        row = (await conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='activity_sessions'"
        ))).fetchone()
        assert row is not None and row[0] == "activity_sessions"
        idx = (await conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND tbl_name='activity_sessions' ORDER BY name"
        ))).fetchall()
        idx_names = {r[0] for r in idx}
    # 必须含两个手动创建 + 可能的 sqlite_autoindex
    assert "idx_activity_sessions_user_date" in idx_names
    assert "idx_activity_sessions_app" in idx_names


async def test_migration_idempotent() -> None:
    """重复跑 migration 不破坏数据 / 不抛错。"""
    from backend.database.migrations.v3_5_chunk14_activity_sessions import (
        run_migration,
    )
    # seed 一行
    await _seed([(100, 60, "Code", None, None, "ide", 0)])
    # 再跑 migration
    await run_migration()
    # 数据仍在
    async with engine.begin() as conn:
        n = (await conn.execute(text(
            "SELECT COUNT(*) FROM activity_sessions WHERE user_id=:u"
        ), {"u": _TEST_USER})).fetchone()[0]
    assert n == 1


# ===========================================================================
# Part B: session writer poll handler
# ===========================================================================


async def test_writer_writes_session_on_tuple_change() -> None:
    """(app, url) tuple 变化 → 上一段写入。"""
    with patch.object(at, "_get_default_user_id", return_value=_TEST_USER), \
         patch.object(at, "_is_user_idle", return_value=False):
        # tick 1: VSCode
        await at.session_writer_poll_handler(
            ActivityState(active_app="Code", browser=None, timestamp=0.0)
        )
        # 模拟 60s 后
        at._prev_start_at = datetime.utcnow() - timedelta(seconds=60)
        # tick 2: Chrome with URL → 上一段(Code, 60s)应被写入
        await at.session_writer_poll_handler(ActivityState(
            active_app="Google Chrome",
            browser={"browser": "chrome", "url": "https://x.com", "title": "X"},
            timestamp=60.0,
        ))

    async with engine.begin() as conn:
        rows = (await conn.execute(text(
            "SELECT app_name, duration_seconds, category FROM activity_sessions "
            "WHERE user_id=:u ORDER BY id"
        ), {"u": _TEST_USER})).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "Code"
    assert rows[0][1] >= 30   # 至少 30s
    assert rows[0][2] == "ide"


async def test_writer_skips_short_session_below_min_seconds() -> None:
    """duration < min_session_seconds(默 30s) → 不写入。"""
    with patch.object(at, "_get_default_user_id", return_value=_TEST_USER), \
         patch.object(at, "_is_user_idle", return_value=False):
        await at.session_writer_poll_handler(ActivityState(
            active_app="Code", browser=None, timestamp=0.0
        ))
        # 模拟 5s(< 30s) 后切
        at._prev_start_at = datetime.utcnow() - timedelta(seconds=5)
        await at.session_writer_poll_handler(ActivityState(
            active_app="Spotify", browser=None, timestamp=5.0
        ))
    async with engine.begin() as conn:
        n = (await conn.execute(text(
            "SELECT COUNT(*) FROM activity_sessions WHERE user_id=:u"
        ), {"u": _TEST_USER})).fetchone()[0]
    assert n == 0


async def test_writer_skips_blacklisted_app() -> None:
    """app 在 blocked_apps → 不写入。"""
    with patch.object(at, "_get_default_user_id", return_value=_TEST_USER), \
         patch.object(at._aw, "get_blocked_apps", return_value=["1Password"]), \
         patch.object(at._aw, "get_blocked_url_patterns", return_value=[]), \
         patch.object(at, "_is_user_idle", return_value=False):
        await at.session_writer_poll_handler(ActivityState(
            active_app="1Password", browser=None, timestamp=0.0
        ))
        at._prev_start_at = datetime.utcnow() - timedelta(seconds=60)
        await at.session_writer_poll_handler(ActivityState(
            active_app="Code", browser=None, timestamp=60.0
        ))
    async with engine.begin() as conn:
        n = (await conn.execute(text(
            "SELECT COUNT(*) FROM activity_sessions "
            "WHERE user_id=:u AND app_name='1Password'"
        ), {"u": _TEST_USER})).fetchone()[0]
    assert n == 0


async def test_writer_skips_when_globally_disabled() -> None:
    """activity_timeline.enabled=false → 不写入(但游标仍更新)。"""
    with patch.object(at, "_get_default_user_id", return_value=_TEST_USER), \
         patch.object(at, "get_timeline_enabled", return_value=False), \
         patch.object(at, "_is_user_idle", return_value=False):
        await at.session_writer_poll_handler(ActivityState(
            active_app="Code", browser=None, timestamp=0.0
        ))
        at._prev_start_at = datetime.utcnow() - timedelta(seconds=60)
        await at.session_writer_poll_handler(ActivityState(
            active_app="Spotify", browser=None, timestamp=60.0
        ))
    async with engine.begin() as conn:
        n = (await conn.execute(text(
            "SELECT COUNT(*) FROM activity_sessions WHERE user_id=:u"
        ), {"u": _TEST_USER})).fetchone()[0]
    assert n == 0


async def test_writer_marks_idle_filtered() -> None:
    """idle 期间结束的 session 写时标 is_idle_filtered=1。"""
    with patch.object(at, "_get_default_user_id", return_value=_TEST_USER), \
         patch.object(at, "_is_user_idle", return_value=True):
        await at.session_writer_poll_handler(ActivityState(
            active_app="Code", browser=None, timestamp=0.0
        ))
        at._prev_start_at = datetime.utcnow() - timedelta(seconds=60)
        await at.session_writer_poll_handler(ActivityState(
            active_app="Spotify", browser=None, timestamp=60.0
        ))
    async with engine.begin() as conn:
        flag = (await conn.execute(text(
            "SELECT is_idle_filtered FROM activity_sessions WHERE user_id=:u"
        ), {"u": _TEST_USER})).fetchone()[0]
    assert flag == 1


# ===========================================================================
# Part C: Timeline API
# ===========================================================================


async def test_api_get_timeline_aggregates_correctly() -> None:
    await _seed([
        (3*3600, 3600, "Code", None, None, "ide", 0),
        (2*3600, 1200, "Google Chrome", "https://github.com", "GitHub", "browser", 0),
        (1800, 600, "Spotify", None, None, "music", 0),
    ])
    with patch.object(api, "_default_user_id", return_value=_TEST_USER):
        resp = await api.get_timeline(date=None, days=1, include_idle=True)
    assert resp.total_active_seconds == 3600 + 1200 + 600
    assert len(resp.sessions) == 3
    apps = {s.app_name for s in resp.summary_by_app}
    assert apps == {"Code", "Google Chrome", "Spotify"}
    assert resp.summary_by_category == {"ide": 3600, "browser": 1200, "music": 600}


async def test_api_include_idle_false_excludes_idle_rows() -> None:
    await _seed([
        (3600, 600, "Code", None, None, "ide", 0),
        (1800, 600, "Slack", None, None, "other", 1),    # idle
    ])
    with patch.object(api, "_default_user_id", return_value=_TEST_USER):
        resp = await api.get_timeline(date=None, days=1, include_idle=False)
    assert len(resp.sessions) == 1
    assert resp.sessions[0].app_name == "Code"


async def test_api_delete_single_session() -> None:
    await _seed([(600, 300, "Code", None, None, "ide", 0)])
    async with engine.begin() as conn:
        row_id = (await conn.execute(text(
            "SELECT id FROM activity_sessions WHERE user_id=:u"
        ), {"u": _TEST_USER})).fetchone()[0]

    with patch.object(api, "_default_user_id", return_value=_TEST_USER):
        r = await api.delete_timeline_session(int(row_id))
    assert r == {"deleted": True}

    async with engine.begin() as conn:
        n = (await conn.execute(text(
            "SELECT COUNT(*) FROM activity_sessions WHERE user_id=:u"
        ), {"u": _TEST_USER})).fetchone()[0]
    assert n == 0


async def test_api_delete_by_date_requires_explicit_param() -> None:
    """date=None 拒绝(防误删全表)。"""
    from fastapi import HTTPException
    with patch.object(api, "_default_user_id", return_value=_TEST_USER):
        with pytest.raises(HTTPException) as ei:
            await api.delete_timeline_by_date(date=None)
    assert ei.value.status_code == 400


async def test_api_delete_by_date_all() -> None:
    """date='all' 真清当前 user 全表。"""
    await _seed([
        (3600, 600, "Code", None, None, "ide", 0),
        (1800, 600, "Spotify", None, None, "music", 0),
    ])
    with patch.object(api, "_default_user_id", return_value=_TEST_USER):
        r = await api.delete_timeline_by_date(date="all")
    assert r["deleted_count"] == 2
    async with engine.begin() as conn:
        n = (await conn.execute(text(
            "SELECT COUNT(*) FROM activity_sessions WHERE user_id=:u"
        ), {"u": _TEST_USER})).fetchone()[0]
    assert n == 0


# ===========================================================================
# Part D: capabilities
# ===========================================================================


async def test_cap_get_today_summary() -> None:
    """走 ToolRegistry.call 真路径(对齐 hotfix-2 教训)。"""
    import backend.capabilities.activity  # noqa: trigger registration
    from backend.tools.registry import ToolRegistry
    from backend.capabilities import activity as cap_mod

    await _seed([
        (3*3600, 3600, "Code", None, None, "ide", 0),
        (1*3600, 600, "Spotify", None, None, "music", 0),
        (60, 60, "Slack", None, None, "other", 1),       # idle excluded
    ])

    with patch.object(cap_mod, "_default_user_id", return_value=_TEST_USER):
        r = await ToolRegistry.call("activity.get_today_summary", user_id="x")
    assert r["available"] is True
    assert r["total_active_seconds"] == 3600 + 600   # idle row excluded
    app_names = {a["app_name"] for a in r["top_apps"]}
    assert "Code" in app_names and "Spotify" in app_names
    assert "Slack" not in app_names                  # idle filtered out


async def test_cap_get_recent_apps_clamps_days() -> None:
    import backend.capabilities.activity  # noqa
    from backend.tools.registry import ToolRegistry
    from backend.capabilities import activity as cap_mod

    await _seed([(86400 * 5, 3600, "Code", None, None, "ide", 0)])
    with patch.object(cap_mod, "_default_user_id", return_value=_TEST_USER):
        r = await ToolRegistry.call("activity.get_recent_apps",
                                    user_id="x", days=7)
    assert r["available"] is True
    assert r["days"] == 7
    assert any(a["app_name"] == "Code" for a in r["top_apps"])

    # clamp negative → 1
    with patch.object(cap_mod, "_default_user_id", return_value=_TEST_USER):
        r2 = await ToolRegistry.call("activity.get_recent_apps",
                                     user_id="x", days=-5)
    assert r2["days"] == 1


async def test_cap_search_history_excludes_idle() -> None:
    """search_history 不返 is_idle_filtered=1 的行(双重隐私)。"""
    import backend.capabilities.activity  # noqa
    from backend.tools.registry import ToolRegistry
    from backend.capabilities import activity as cap_mod

    await _seed([
        (3600, 600, "Google Chrome", "https://news.example/active", "active news", "browser", 0),
        (1800, 600, "Google Chrome", "https://news.example/idle", "idle news", "browser", 1),
    ])
    with patch.object(cap_mod, "_default_user_id", return_value=_TEST_USER):
        r = await ToolRegistry.call("activity.search_history",
                                    user_id="x", keyword="news", days=7)
    assert r["available"] is True
    urls = {m["url"] for m in r["matches"]}
    assert "https://news.example/active" in urls
    assert "https://news.example/idle" not in urls


async def test_cap_search_history_empty_keyword() -> None:
    import backend.capabilities.activity  # noqa
    from backend.tools.registry import ToolRegistry
    r = await ToolRegistry.call("activity.search_history",
                                user_id="x", keyword="", days=7)
    assert r["available"] is False
    assert r["reason"] == "empty_keyword"


# ===========================================================================
# Part E: ChatAgent injection
# ===========================================================================


async def test_format_today_activity_returns_none_when_no_data() -> None:
    s = await at.format_today_activity_for_prompt(_TEST_USER)
    assert s is None


async def test_format_today_activity_returns_none_when_disabled() -> None:
    await _seed([(3600, 600, "Code", None, None, "ide", 0)])
    with patch.object(at, "get_inject_enabled", return_value=False):
        s = await at.format_today_activity_for_prompt(_TEST_USER)
    assert s is None


async def test_format_today_activity_under_threshold_returns_none() -> None:
    """总活跃 < 60s → 不污染 prompt。"""
    await _seed([(60, 30, "Code", None, None, "ide", 0)])
    s = await at.format_today_activity_for_prompt(_TEST_USER)
    assert s is None


async def test_format_today_activity_builds_prompt_block() -> None:
    await _seed([
        (3*3600, 3 * 3600, "Code", None, None, "ide", 0),
        (1*3600, 600, "Spotify", None, None, "music", 0),
    ])
    s = await at.format_today_activity_for_prompt(_TEST_USER)
    assert s is not None
    assert "## 用户今日活动" in s
    # hotfix-10 display_name 应用
    assert "VS Code" in s
    assert "3小时" in s
    assert "Spotify" in s


async def test_format_today_activity_excludes_idle() -> None:
    """idle session 不计入注入摘要(用户 AFK 时段不该被 Momo 回忆)。"""
    await _seed([
        (3600, 600, "Code", None, None, "ide", 0),
        (1800, 1800, "Spotify", None, None, "music", 1),   # idle 30 min
    ])
    s = await at.format_today_activity_for_prompt(_TEST_USER)
    assert s is not None
    assert "Spotify" not in s   # idle 行被排除


async def test_injection_coexists_with_chunk11_profile() -> None:
    """注入块独立 — 不应触碰 chunk 11 profile 注入路径(回归)。"""
    import backend.services.profile_regen as pr
    # both functions are independent;两者都不抛 + 都返非 None 输出 == 注入并存可行
    fake_profile = {
        "profession": "engineer",
        "current_projects": ["Skyler"],
        "interests": ["AI", "music"],
        "language_preferences": ["zh", "en"],
    }
    fp = pr.format_profile_for_prompt(fake_profile)
    assert fp and "engineer" in fp

    await _seed([(3*3600, 3 * 3600, "Code", None, None, "ide", 0)])
    fa = await at.format_today_activity_for_prompt(_TEST_USER)
    assert fa and "VS Code" in fa
    # 两个 block 在 system_parts 内拼接互不重复
    combined = fp + "\n\n" + fa
    assert combined.count("## 用户今日活动") == 1


# ===========================================================================
# Part F: 隐私(黑名单不写入 / search 不返 idle / 总开关 OFF 不写)
# ===========================================================================


async def test_privacy_blocked_url_pattern_not_written() -> None:
    """blocked_url_patterns 命中 → 不写入。"""
    with patch.object(at, "_get_default_user_id", return_value=_TEST_USER), \
         patch.object(at._aw, "get_blocked_apps", return_value=[]), \
         patch.object(at._aw, "get_blocked_url_patterns",
                      return_value=["*mail.google.com*"]), \
         patch.object(at, "_is_user_idle", return_value=False):
        await at.session_writer_poll_handler(ActivityState(
            active_app="Google Chrome",
            browser={"browser": "chrome",
                     "url": "https://mail.google.com/inbox", "title": "Gmail"},
            timestamp=0.0,
        ))
        at._prev_start_at = datetime.utcnow() - timedelta(seconds=60)
        await at.session_writer_poll_handler(ActivityState(
            active_app="Code", browser=None, timestamp=60.0
        ))
    async with engine.begin() as conn:
        n = (await conn.execute(text(
            "SELECT COUNT(*) FROM activity_sessions "
            "WHERE user_id=:u AND browser_url LIKE '%mail.google.com%'"
        ), {"u": _TEST_USER})).fetchone()[0]
    assert n == 0


# ===========================================================================
# Part G: cleanup cron
# ===========================================================================


async def test_cleanup_deletes_old_rows_only() -> None:
    # 40 天前 1 行 + 1 天前 1 行
    await _seed([
        (40 * 86400, 600, "Code", None, None, "ide", 0),
        (1 * 86400, 600, "Spotify", None, None, "music", 0),
    ])
    n = await at.cleanup_old_sessions()
    assert n == 1   # 只删 40 天前那条
    async with engine.begin() as conn:
        remaining = (await conn.execute(text(
            "SELECT app_name FROM activity_sessions WHERE user_id=:u"
        ), {"u": _TEST_USER})).fetchall()
    assert {r[0] for r in remaining} == {"Spotify"}


async def test_cleanup_noop_when_cleanup_days_zero() -> None:
    """cleanup_days=0 → 函数 no-op 返 0,数据保留。"""
    await _seed([(40 * 86400, 600, "Code", None, None, "ide", 0)])
    with patch.object(at, "get_cleanup_days", return_value=0):
        n = await at.cleanup_old_sessions()
    assert n == 0
    async with engine.begin() as conn:
        cnt = (await conn.execute(text(
            "SELECT COUNT(*) FROM activity_sessions WHERE user_id=:u"
        ), {"u": _TEST_USER})).fetchone()[0]
    assert cnt == 1   # 数据保留


# ===========================================================================
# Part H: hotfix-10 collaboration
# ===========================================================================


def test_categorize_handles_english_bundle_names() -> None:
    """hotfix-10 后 app_name 是英文 bundle 名,categorize 仍正确归类。"""
    # 这些都是 osascript 返的英文 bundle 名
    assert at.categorize("Code", None) == "ide"
    assert at.categorize("Terminal", None) == "ide"
    assert at.categorize("Safari", None) == "browser"
    assert at.categorize("Google Chrome", None) == "browser"
    assert at.categorize("Spotify", None) == "music"


def test_display_name_used_in_injection_not_storage() -> None:
    """hotfix-10 display_name helper:LLM-facing only,storage 用 bundle 名。"""
    assert am.get_display_name("Code") == "VS Code"
    assert am.get_display_name("Terminal") == "终端"
    # 不在 mapping 的 → 原值
    assert am.get_display_name("Spotify") == "Spotify"
