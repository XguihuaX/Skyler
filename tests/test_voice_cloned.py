"""Bugfix-3.3.1 — Voice cloned + preview + migration + priority tests.

Coverage:
  * test_migration_seed_cloned_voices_idempotent
        — 跑两次结果一致, 已 cloned 的不动
  * test_migration_skips_already_cloned
        — 角色 voice_model 已是 cloned voice 时跳过
  * test_migration_overwrites_null_or_system
        — voice_model 为 NULL 或系统 longxxx 时覆盖
  * test_get_cloned_voices_api (mock DashScope)
        — SDK list_voices 返回的 list 被 normalize 成 ClonedVoice list
  * test_get_cloned_voices_cache_skips_dashscope
        — 第二次同样调用 hit cache, 不打 DashScope
  * test_preview_voice_endpoint (mock)
        — POST /tts/voice/preview 返回 base64 audio
  * test_voice_usage_reverse_index
        — 读 characters.voice_model JSON 反向 voice → chars[]
  * test_character_voice_model_priority_through_parse
        — parse_voice_config + character voice > yaml default

Run:
    .venv/bin/python tests/test_voice_cloned.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

# DB / crypto key 隔离, 在 backend import 前
_TMP_HOME = tempfile.mkdtemp(prefix="momoos-bugfix331-")
os.environ["HOME"] = _TMP_HOME
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text

import backend.database as _db_module

TEST_ENGINE = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
TEST_SESSION = sessionmaker(
    TEST_ENGINE, class_=AsyncSession, expire_on_commit=False,
)
_db_module.engine = TEST_ENGINE
_db_module.AsyncSessionLocal = TEST_SESSION

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, cond: bool, detail: str = "") -> None:
    tag = PASS if cond else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, cond))


# ---------------------------------------------------------------------------
# Setup: minimal characters table + 7 rows mimicking real DB
# ---------------------------------------------------------------------------


async def setup_db() -> None:
    async with TEST_ENGINE.begin() as conn:
        await conn.execute(text("""
            CREATE TABLE characters (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                voice_model TEXT
            )
        """))
        # 角色 id 2/3/5 → 复刻 voice (NULL voice_model 初态)
        # 角色 id 1 (Momo) → 已配 longanhuan 系统 voice
        # 角色 id 99/100 → 其他无关角色 (不在 cloned list 内)
        # NOTE: sqlalchemy text() 把 ":word" 当 bind parameter, 这里 voice_model
        # JSON 含 ``"instruct_supported":true`` → 必须用 bind param 喂进去
        momo_vm = json.dumps({
            "provider": "cosyvoice", "voice": "longanhuan",
            "instruct_supported": True,
        })
        await conn.execute(text(
            "INSERT INTO characters (id, name, voice_model) VALUES "
            "(1, 'Momo', :vm), "
            "(2, '八重神子', NULL), "
            "(3, '荧', NULL), "
            "(4, '凝光', NULL), "
            "(5, '神里绫华', NULL), "
            "(99, '路过猫娘', NULL), "
            "(100, '祥子-test', NULL)"
        ), {"vm": momo_vm})


# ---------------------------------------------------------------------------
# Migration tests
# ---------------------------------------------------------------------------


async def test_migration_seed_cloned_voices_idempotent():
    """跑 1 次 → 3 chars 被填; 跑 2 次 → 不动 (skip already_cloned)。"""
    print("\n[1] migration_seed_cloned_voices_idempotent")
    from backend.database.migrations.bugfix_3_3_1_seed_cloned_voices import (
        run_migration,
    )
    await run_migration()
    async with TEST_ENGINE.begin() as conn:
        rows = (await conn.execute(text(
            "SELECT id, voice_model FROM characters WHERE id IN (2,3,5)"
        ))).fetchall()
    by_id = {r[0]: r[1] for r in rows}
    check("char 2 → has voice_model",
          by_id.get(2) is not None and "cosyvoice-v3.5-plus-bailian-" in by_id[2],
          f"got={by_id.get(2)}")
    check("char 3 → has voice_model",
          by_id.get(3) is not None and "cosyvoice-v3.5-plus-bailian-" in by_id[3])
    check("char 5 → has voice_model",
          by_id.get(5) is not None and "cosyvoice-v3.5-plus-bailian-" in by_id[5])
    # Run again — should be skip-all
    await run_migration()
    async with TEST_ENGINE.begin() as conn:
        rows2 = (await conn.execute(text(
            "SELECT id, voice_model FROM characters WHERE id IN (2,3,5)"
        ))).fetchall()
    by_id2 = {r[0]: r[1] for r in rows2}
    check("idempotent (char 2 same after 2nd run)",
          by_id.get(2) == by_id2.get(2))
    check("idempotent (char 3 same)", by_id.get(3) == by_id2.get(3))
    check("idempotent (char 5 same)", by_id.get(5) == by_id2.get(5))


async def test_migration_does_not_touch_unrelated_chars():
    """char 1 (Momo, 系统 voice) / 4 / 99 / 100 不动。"""
    print("\n[2] migration_does_not_touch_unrelated")
    async with TEST_ENGINE.begin() as conn:
        rows = (await conn.execute(text(
            "SELECT id, voice_model FROM characters "
            "WHERE id IN (1, 4, 99, 100) ORDER BY id"
        ))).fetchall()
    by_id = {r[0]: r[1] for r in rows}
    check("char 1 (Momo) longanhuan 保留",
          by_id.get(1) is not None and "longanhuan" in by_id[1],
          f"got={by_id.get(1)}")
    check("char 4 voice_model still NULL", by_id.get(4) is None)
    check("char 99 voice_model still NULL", by_id.get(99) is None)
    check("char 100 voice_model still NULL", by_id.get(100) is None)


async def test_migration_overwrites_non_cloned_only():
    """已是 cloned voice → 不覆盖; 系统 voice → 覆盖? 实际策略:
    只跳过 voice 字段以 'cosyvoice-v3.5-plus-bailian-' 开头的 (即已复刻)。
    系统 voice (longxxx) 会被覆盖成复刻 voice。这里测试该策略。"""
    print("\n[3] migration_overwrites_system_voice_not_cloned")
    # plant: char 2 = system voice (会被覆盖); char 3 = 已复刻 voice (跳过)
    sys_vm = json.dumps({
        "provider": "cosyvoice", "voice": "longanhuan",
        "instruct_supported": True,
    })
    manual_cloned_vm = json.dumps({
        "provider": "cosyvoice",
        "voice": "cosyvoice-v3.5-plus-bailian-USER-MANUAL",
    })
    async with TEST_ENGINE.begin() as conn:
        await conn.execute(
            text("UPDATE characters SET voice_model = :vm WHERE id = 2"),
            {"vm": sys_vm},
        )
        await conn.execute(
            text("UPDATE characters SET voice_model = :vm WHERE id = 3"),
            {"vm": manual_cloned_vm},
        )
    from backend.database.migrations.bugfix_3_3_1_seed_cloned_voices import (
        run_migration,
    )
    await run_migration()
    async with TEST_ENGINE.begin() as conn:
        rows = (await conn.execute(text(
            "SELECT id, voice_model FROM characters WHERE id IN (2, 3)"
        ))).fetchall()
    by_id = {r[0]: r[1] for r in rows}
    # char 2 系统 voice → 被覆盖
    check("char 2 系统 voice → 覆盖成 official cloned voice",
          by_id.get(2) is not None
          and "cosyvoice-v3.5-plus-bailian-a61ea44f8a9648b3920b7ef98280d226" in by_id[2],
          f"got={by_id.get(2)}")
    # char 3 user 自填 cloned voice → 不动
    check("char 3 用户手填 cloned voice → 保留不动",
          by_id.get(3) is not None
          and "USER-MANUAL" in by_id[3],
          f"got={by_id.get(3)}")


# ---------------------------------------------------------------------------
# API endpoint tests (mock DashScope SDK)
# ---------------------------------------------------------------------------


async def test_get_cloned_voices_api_mock():
    """mock DashScope VoiceEnrollmentService.list_voices,
    确认 endpoint shape + normalize 正确。"""
    print("\n[4] get_cloned_voices_api (mock DashScope)")
    # mock SDK 返回的 list
    fake_voices = [
        {"voice_id": "cosyvoice-v3.5-plus-bailian-aaaaa", "status": "OK",
         "gmtCreate": "2025-11-01 10:00:00",
         "gmtModified": "2025-11-02 10:00:00"},
        {"id": "cosyvoice-v3.5-plus-bailian-bbbbb", "status": "PENDING",
         "create_time": "2025-11-03 11:00:00"},
    ]
    # ensure cache is fresh-test (clear)
    import backend.routes.tts_api as tts_api
    tts_api._cached_voices = None
    tts_api._cached_at = 0.0
    # mock _blocking_list_cloned_voices
    with patch.object(tts_api, "_blocking_list_cloned_voices", return_value=fake_voices):
        resp = await tts_api.list_cloned_voices(force=True)
    check("response.voices len matches", len(resp.voices) == 2,
          f"got len={len(resp.voices)}")
    check("first voice_id 正确 (alias 'voice_id')",
          resp.voices[0].voice_id == "cosyvoice-v3.5-plus-bailian-aaaaa",
          f"got={resp.voices[0].voice_id}")
    check("second voice_id 正确 (alias 'id')",
          resp.voices[1].voice_id == "cosyvoice-v3.5-plus-bailian-bbbbb",
          f"got={resp.voices[1].voice_id}")
    check("create_time normalized (gmtCreate alias)",
          resp.voices[0].create_time == "2025-11-01 10:00:00",
          f"got={resp.voices[0].create_time}")
    check("status passthrough", resp.voices[0].status == "OK")
    check("cached False on force=True", resp.cached is False)


async def test_get_cloned_voices_cache():
    """第二次同样调用 hit cache (cached=True), 不打 DashScope。"""
    print("\n[5] get_cloned_voices_cache_skips_dashscope")
    import backend.routes.tts_api as tts_api
    fake_voices = [{"id": "cosyvoice-v3.5-plus-bailian-c1", "status": "OK"}]
    tts_api._cached_voices = None
    tts_api._cached_at = 0.0
    call_count = {"n": 0}

    def fake_block():
        call_count["n"] += 1
        return fake_voices

    with patch.object(tts_api, "_blocking_list_cloned_voices", side_effect=fake_block):
        # First call — cache miss
        r1 = await tts_api.list_cloned_voices(force=False)
        # Second call — cache hit
        r2 = await tts_api.list_cloned_voices(force=False)
    check("DashScope called only once", call_count["n"] == 1,
          f"got count={call_count['n']}")
    check("first call cached=False", r1.cached is False)
    check("second call cached=True", r2.cached is True)


async def test_preview_voice_endpoint_mock():
    """POST /tts/voice/preview 返回 base64 audio (mock DashScope synth)。"""
    print("\n[6] preview_voice_endpoint_mock")
    import backend.routes.tts_api as tts_api
    from backend.routes.tts_api import preview_voice, VoicePreviewBody
    fake_audio = b"FAKEWAV" * 100  # 700 bytes
    with patch.object(tts_api, "_blocking_preview", return_value=fake_audio):
        resp = await preview_voice(VoicePreviewBody(
            voice="cosyvoice-v3.5-plus-bailian-xxx", text="你好",
        ))
    check("audio_b64 non-empty", bool(resp.audio_b64),
          f"got len={len(resp.audio_b64)}")
    # decode roundtrip
    import base64
    decoded = base64.b64decode(resp.audio_b64)
    check("base64 round-trip == original bytes", decoded == fake_audio)
    check("voice echoed back",
          resp.voice == "cosyvoice-v3.5-plus-bailian-xxx")
    check("format declared wav-24khz", resp.format == "wav-24khz-16bit-mono")


# ---------------------------------------------------------------------------
# Voice usage reverse index
# ---------------------------------------------------------------------------


async def test_voice_usage_reverse_index():
    """GET /tts/voices/usage 读 characters.voice_model JSON 算反向。"""
    print("\n[7] voice_usage_reverse_index")
    from backend.routes.tts_api import voice_usage
    resp = await voice_usage()
    by_voice = {e.voice: e.characters for e in resp.by_voice}
    # 经过 migration 后, char 2/3/5 → 3 个不同 cloned voice
    # 但 test 3 已把 char 3 的 voice 改成 USER-MANUAL
    check("char 2 cloned voice 反查",
          "cosyvoice-v3.5-plus-bailian-a61ea44f8a9648b3920b7ef98280d226" in by_voice,
          f"keys={list(by_voice.keys())}")
    chars_for_char2 = by_voice.get(
        "cosyvoice-v3.5-plus-bailian-a61ea44f8a9648b3920b7ef98280d226"
    )
    check("char 2 → 八重神子",
          chars_for_char2 is not None
          and any(c["id"] == 2 and c["name"] == "八重神子" for c in chars_for_char2))
    # Momo (id=1) → longanhuan 系统 voice 也得反查到
    check("longanhuan 反查 → Momo",
          "longanhuan" in by_voice and any(c["id"] == 1 for c in by_voice["longanhuan"]))


# ---------------------------------------------------------------------------
# Voice priority: parse_voice_config + character voice > yaml default
# ---------------------------------------------------------------------------


def test_character_voice_priority_through_parse():
    """parse_voice_config 收 character.voice_model JSON,优先级正确。"""
    print("\n[8] character_voice_priority_through_parse")
    from backend.tts.voice_config import VoiceConfig, parse_voice_config
    yaml_default = VoiceConfig(
        provider="cosyvoice", voice="longyumi_v3", instruct_supported=False,
    )
    # case 1: voice_model=None → use yaml default
    cfg = parse_voice_config(None, yaml_default)
    check("None voice_model → yaml default",
          cfg.voice == "longyumi_v3" and cfg.provider == "cosyvoice")
    # case 2: 空 JSON {} → yaml default (parse_voice_config 退化)
    cfg = parse_voice_config("{}", yaml_default)
    check("空 {} → yaml default", cfg.voice == "longyumi_v3")
    # case 3: cloned voice → override
    char_vm = json.dumps({
        "provider": "cosyvoice",
        "voice": "cosyvoice-v3.5-plus-bailian-aaaa",
        "instruct_supported": True,
    })
    cfg = parse_voice_config(char_vm, yaml_default)
    check("cloned voice → 覆盖 yaml default",
          cfg.voice == "cosyvoice-v3.5-plus-bailian-aaaa",
          f"got={cfg.voice}")
    check("instruct_supported True 传递", cfg.instruct_supported is True)
    # case 4: 不合法 JSON → fallback
    cfg = parse_voice_config("{broken json}", yaml_default)
    check("不合法 JSON → fallback to default", cfg.voice == "longyumi_v3")


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------


async def _main():
    await setup_db()
    await test_migration_seed_cloned_voices_idempotent()
    await test_migration_does_not_touch_unrelated_chars()
    await test_migration_overwrites_non_cloned_only()
    await test_get_cloned_voices_api_mock()
    await test_get_cloned_voices_cache()
    await test_preview_voice_endpoint_mock()
    await test_voice_usage_reverse_index()
    test_character_voice_priority_through_parse()


if __name__ == "__main__":
    asyncio.run(_main())
    passed = sum(1 for _, ok in results if ok)
    failed = len(results) - passed
    print(f"\n=== {passed} passed, {failed} failed ===")
    import shutil
    shutil.rmtree(_TMP_HOME, ignore_errors=True)
    sys.exit(0 if failed == 0 else 1)
