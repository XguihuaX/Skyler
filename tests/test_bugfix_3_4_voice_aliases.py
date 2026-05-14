"""Bugfix-3.4 — voice_aliases + v3.5-plus skip-instruct + parse model field tests.

Coverage:
  * test_v35_plus_skips_instruction
        — CosyVoiceTTS(model=cosyvoice-v3.5-plus, instruct_supported=True) +
          emotion 在白名单 → 不发 instruction (skip), plain text
  * test_v3_plus_keeps_instruction
        — CosyVoiceTTS(model=cosyvoice-v3-plus, instruct_supported=True) +
          emotion='happy' → 发 instruction
  * test_v3_flash_default_keeps_instruction
        — 默认 yaml model cosyvoice-v3-flash + instruct → 发 instruction
  * test_parse_voice_config_reads_model_field
        — voice_model JSON 含 model 字段 → VoiceConfig.model = 该值
  * test_parse_voice_config_model_falls_back_to_none
        — 不含 model 字段 → cfg.model is None (caller 用 yaml fallback)
  * test_voice_aliases_crud
        — list / get / set / delete + idempotent
  * test_migration_seed_aliases_from_characters
        — characters 绑了 cloned voice → seed 出 '<name> voice' alias
  * test_migration_does_not_overwrite_user_alias
        — 用户已自定义 alias → migration 不覆盖
  * test_alias_fallback_chain
        — resolveVoiceName-like 逻辑:alias > fallback > 截断 raw

Run:
    .venv/bin/python tests/test_bugfix_3_4_voice_aliases.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from unittest.mock import patch, MagicMock

# Isolate DB / HOME
_TMP_HOME = tempfile.mkdtemp(prefix="momoos-bugfix34-")
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
# v3.5-plus skip instruction
# ---------------------------------------------------------------------------


def test_v35_plus_skips_instruction():
    """Bugfix-3.4: model=cosyvoice-v3.5-plus 即便 instruct_supported=True 也跳过
    instruction → plain text 调用,防 418。"""
    print("\n[1] v35_plus_skips_instruction")
    from backend.tts.cosyvoice import CosyVoiceTTS
    # 用 patch.object 在 CosyVoiceTTS 内部 SpeechSynthesizer 上拦截 — 我们关心
    # 的是构造 SpeechSynthesizer 时的 kwargs 含不含 'instruction'。
    captured = {}

    class FakeSpeechSynthesizer:
        def __init__(self, **kwargs):
            captured.update(kwargs)
        def call(self, text):
            return b"FAKEWAV"

    with patch("backend.tts.cosyvoice.SpeechSynthesizer", FakeSpeechSynthesizer):
        tts = CosyVoiceTTS(
            voice="cosyvoice-v3.5-plus-bailian-xxxxx",
            instruct_supported=True,
            model="cosyvoice-v3.5-plus",
        )
        audio = tts._blocking_synthesize("你好", "happy")
    check("audio not None (skip instruction ≠ skip synth)", audio == b"FAKEWAV")
    check("model 正确传入 v3.5-plus",
          captured.get("model") == "cosyvoice-v3.5-plus",
          f"got={captured.get('model')}")
    check("voice 正确传入",
          captured.get("voice") == "cosyvoice-v3.5-plus-bailian-xxxxx")
    check("instruction kwarg 未传 (v3.5-plus skip)",
          "instruction" not in captured,
          f"captured keys={list(captured.keys())}")


def test_v3_plus_keeps_instruction():
    """Bugfix-3.4 regression: 旧模型 cosyvoice-v3-plus + 白名单 emotion → 仍传
    instruction (跟 bugfix-3.4 之前一致, 没回归)。"""
    print("\n[2] v3_plus_keeps_instruction")
    from backend.tts.cosyvoice import CosyVoiceTTS
    captured = {}

    class FakeSpeechSynthesizer:
        def __init__(self, **kwargs):
            captured.update(kwargs)
        def call(self, text):
            return b"FAKEWAV"

    with patch("backend.tts.cosyvoice.SpeechSynthesizer", FakeSpeechSynthesizer):
        tts = CosyVoiceTTS(
            voice="longanhuan",
            instruct_supported=True,
            model="cosyvoice-v3-plus",  # 老 model, 仍支持 instruction
        )
        tts._blocking_synthesize("你好", "happy")
    check("model 正确传入 v3-plus",
          captured.get("model") == "cosyvoice-v3-plus")
    check("instruction kwarg 已传 (v3-plus 走 instruct)",
          "instruction" in captured,
          f"captured keys={list(captured.keys())}")
    check("instruction 格式 = '你说话的情感是happy。'",
          captured.get("instruction") == "你说话的情感是happy。",
          f"got={captured.get('instruction')!r}")


def test_v3_flash_default_keeps_instruction():
    """yaml default cosyvoice-v3-flash + instruct=True + 白名单 emotion → 传
    instruction (跟旧 default 行为一致)。"""
    print("\n[3] v3_flash_default_keeps_instruction")
    from backend.tts.cosyvoice import CosyVoiceTTS
    captured = {}

    class FakeSpeechSynthesizer:
        def __init__(self, **kwargs):
            captured.update(kwargs)
        def call(self, text):
            return b"FAKEWAV"

    with patch("backend.tts.cosyvoice.SpeechSynthesizer", FakeSpeechSynthesizer):
        # model 不传 → 走 yaml default
        tts = CosyVoiceTTS(voice="longanhuan", instruct_supported=True)
        tts._blocking_synthesize("你好", "sad")
    check("model = yaml default cosyvoice-v3-flash",
          captured.get("model") == "cosyvoice-v3-flash",
          f"got={captured.get('model')}")
    check("instruction kwarg 已传 (v3-flash 走 instruct)",
          "instruction" in captured)


def test_no_emotion_no_instruction():
    """emotion='neutral' → 即便 instruct_supported / model 支持也不传 instruction。"""
    print("\n[4] no_emotion_no_instruction")
    from backend.tts.cosyvoice import CosyVoiceTTS
    captured = {}

    class FakeSpeechSynthesizer:
        def __init__(self, **kwargs):
            captured.update(kwargs)
        def call(self, text):
            return b"FAKEWAV"

    with patch("backend.tts.cosyvoice.SpeechSynthesizer", FakeSpeechSynthesizer):
        tts = CosyVoiceTTS(voice="longanhuan", instruct_supported=True,
                           model="cosyvoice-v3-plus")
        tts._blocking_synthesize("你好", "neutral")
    check("neutral emotion → 不传 instruction",
          "instruction" not in captured,
          f"got keys={list(captured.keys())}")


# ---------------------------------------------------------------------------
# parse_voice_config reads model field
# ---------------------------------------------------------------------------


def test_parse_voice_config_reads_model_field():
    """Bugfix-3.4: parse_voice_config 解析 voice_model JSON 的 model 字段。"""
    print("\n[5] parse_voice_config_reads_model_field")
    from backend.tts.voice_config import VoiceConfig, parse_voice_config
    default = VoiceConfig(provider="cosyvoice", voice="longyumi_v3")
    vm = json.dumps({
        "provider": "cosyvoice",
        "model": "cosyvoice-v3.5-plus",
        "voice": "cosyvoice-v3.5-plus-bailian-aaaa",
        "instruct_supported": True,
    })
    cfg = parse_voice_config(vm, default)
    check("cfg.model = 'cosyvoice-v3.5-plus'",
          cfg.model == "cosyvoice-v3.5-plus", f"got={cfg.model}")
    check("cfg.voice 正确", cfg.voice == "cosyvoice-v3.5-plus-bailian-aaaa")
    check("instruct_supported 透传", cfg.instruct_supported is True)


def test_parse_voice_config_model_falls_back_to_none():
    """voice_model JSON 无 model 字段 → cfg.model is None (caller 走 yaml fallback)。"""
    print("\n[6] parse_voice_config_model_none_fallback")
    from backend.tts.voice_config import VoiceConfig, parse_voice_config
    default = VoiceConfig(provider="cosyvoice", voice="longyumi_v3")
    # 旧 voice_model (没 model 字段)
    vm = json.dumps({"provider": "cosyvoice", "voice": "longwan_v3"})
    cfg = parse_voice_config(vm, default)
    check("cfg.model is None (无 model 字段)",
          cfg.model is None, f"got={cfg.model!r}")
    # 空字符串 model → 同样 None
    vm = json.dumps({"provider": "cosyvoice", "voice": "longwan_v3", "model": ""})
    cfg = parse_voice_config(vm, default)
    check("cfg.model is None (空字符串)",
          cfg.model is None, f"got={cfg.model!r}")


# ---------------------------------------------------------------------------
# voice_aliases CRUD + migration
# ---------------------------------------------------------------------------


async def setup_db_for_aliases() -> None:
    """Create characters table + voice_aliases table 模拟真实 DB 形状。"""
    async with TEST_ENGINE.begin() as conn:
        await conn.execute(text("""
            CREATE TABLE characters (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                voice_model TEXT
            )
        """))
        cloned_vm_a = json.dumps({
            "provider": "cosyvoice", "model": "cosyvoice-v3.5-plus",
            "voice": "cosyvoice-v3.5-plus-bailian-a61ea44f",
            "instruct_supported": True,
        })
        cloned_vm_b = json.dumps({
            "provider": "cosyvoice", "model": "cosyvoice-v3.5-plus",
            "voice": "cosyvoice-v3.5-plus-bailian-ec2676aa",
            "instruct_supported": True,
        })
        await conn.execute(text(
            "INSERT INTO characters (id, name, voice_model) VALUES "
            "(1, 'Momo', NULL), "
            "(2, '八重神子', :vm_a), "
            "(3, '荧', :vm_b), "
            "(4, '无 voice 角色', NULL)"
        ), {"vm_a": cloned_vm_a, "vm_b": cloned_vm_b})


async def test_voice_aliases_crud():
    """Bugfix-3.4: list / get / set / delete + 空 displayname = delete。"""
    print("\n[7] voice_aliases_crud")
    from backend.database import voice_aliases as svc
    # set
    await svc.set_alias("cosyvoice-v3.5-plus-bailian-c1", "测试 voice 1")
    check("set + list 包含 c1",
          (await svc.list_aliases()).get("cosyvoice-v3.5-plus-bailian-c1")
              == "测试 voice 1")
    # get
    check("get_alias 返回 plaintext",
          await svc.get_alias("cosyvoice-v3.5-plus-bailian-c1") == "测试 voice 1")
    # update (upsert)
    await svc.set_alias("cosyvoice-v3.5-plus-bailian-c1", "测试 voice 1 (改)")
    check("upsert 覆盖",
          await svc.get_alias("cosyvoice-v3.5-plus-bailian-c1")
              == "测试 voice 1 (改)")
    # 空 display_name → 等价 delete
    await svc.set_alias("cosyvoice-v3.5-plus-bailian-c1", "  ")
    check("空 display_name → delete",
          await svc.get_alias("cosyvoice-v3.5-plus-bailian-c1") is None)
    # 显式 delete
    await svc.set_alias("cosyvoice-v3.5-plus-bailian-c2", "another")
    n = await svc.delete_alias("cosyvoice-v3.5-plus-bailian-c2")
    check("delete returns rowcount=1", n == 1, f"got={n}")
    check("delete 后 get → None",
          await svc.get_alias("cosyvoice-v3.5-plus-bailian-c2") is None)
    # delete 不存在的 → 0
    n2 = await svc.delete_alias("nonexistent")
    check("delete nonexistent rowcount=0", n2 == 0, f"got={n2}")


async def test_migration_seed_aliases_from_characters():
    """Bugfix-3.4: migration 从 characters.voice_model 反查给 cloned voice
    auto-seed '<name> voice' alias。"""
    print("\n[8] migration_seed_aliases_from_characters")
    # 清空 voice_aliases 后跑 migration
    async with TEST_ENGINE.begin() as conn:
        await conn.execute(text("DELETE FROM voice_aliases"))
    from backend.database.migrations.bugfix_3_4_voice_aliases import (
        run_migration,
    )
    await run_migration()
    from backend.database import voice_aliases as svc
    aliases = await svc.list_aliases()
    check("八重神子 voice seeded",
          aliases.get("cosyvoice-v3.5-plus-bailian-a61ea44f") == "八重神子 voice",
          f"got={aliases.get('cosyvoice-v3.5-plus-bailian-a61ea44f')}")
    check("荧 voice seeded",
          aliases.get("cosyvoice-v3.5-plus-bailian-ec2676aa") == "荧 voice")
    # Momo (id=1, voice_model NULL) + 无 voice 角色 (id=4) 不在 aliases 内
    check("Momo (NULL voice_model) 无 seed",
          not any(a == "Momo voice" for a in aliases.values()),
          f"all aliases={list(aliases.values())}")


async def test_migration_does_not_overwrite_user_alias():
    """Bugfix-3.4: 用户已设 alias → migration 用 INSERT OR IGNORE 不覆盖。"""
    print("\n[9] migration_does_not_overwrite_user_alias")
    from backend.database import voice_aliases as svc
    # 用户自定义
    await svc.set_alias("cosyvoice-v3.5-plus-bailian-a61ea44f", "我的八重")
    # 跑 migration
    from backend.database.migrations.bugfix_3_4_voice_aliases import (
        run_migration,
    )
    await run_migration()
    check("user alias 不被 migration 覆盖",
          await svc.get_alias("cosyvoice-v3.5-plus-bailian-a61ea44f") == "我的八重")


# ---------------------------------------------------------------------------
# Fallback chain
# ---------------------------------------------------------------------------


def test_alias_fallback_chain():
    """resolve_display_name_sync: alias > fallback > 截断 raw voice_id."""
    print("\n[10] alias_fallback_chain")
    from backend.database.voice_aliases import resolve_display_name_sync
    aliases = {
        "cosyvoice-v3.5-plus-bailian-a61ea44f": "八重神子 voice",
    }
    check("alias 存在 → 返回 alias",
          resolve_display_name_sync(
              "cosyvoice-v3.5-plus-bailian-a61ea44f", aliases, "fallback-not-used",
          ) == "八重神子 voice")
    check("alias 不存在 + fallback 给 → 返回 fallback",
          resolve_display_name_sync(
              "cosyvoice-v3.5-plus-bailian-c9", aliases, "用户提供 fallback",
          ) == "用户提供 fallback")
    # voice_id[:24] + "…" — count carefully: "cosyvoice-v3.5-plus-bail" 是前 24 char
    check("alias 不存在 + 无 fallback + 长 id → 截断",
          resolve_display_name_sync(
              "cosyvoice-v3.5-plus-bailian-c9999999999999", aliases,
          ) == "cosyvoice-v3.5-plus-bail…",
          f"got={resolve_display_name_sync('cosyvoice-v3.5-plus-bailian-c9999999999999', aliases)!r}")
    check("alias 不存在 + 无 fallback + 短 id → 原样",
          resolve_display_name_sync("longanhuan", aliases) == "longanhuan")


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------


async def _main():
    # voice config / synth 路径 (no DB)
    test_v35_plus_skips_instruction()
    test_v3_plus_keeps_instruction()
    test_v3_flash_default_keeps_instruction()
    test_no_emotion_no_instruction()
    test_parse_voice_config_reads_model_field()
    test_parse_voice_config_model_falls_back_to_none()
    test_alias_fallback_chain()
    # DB 路径
    await setup_db_for_aliases()
    # 先跑 migration 创 voice_aliases 表 + 自动 seed
    from backend.database.migrations.bugfix_3_4_voice_aliases import run_migration
    await run_migration()
    await test_voice_aliases_crud()
    await test_migration_seed_aliases_from_characters()
    await test_migration_does_not_overwrite_user_alias()


if __name__ == "__main__":
    asyncio.run(_main())
    passed = sum(1 for _, ok in results if ok)
    failed = len(results) - passed
    print(f"\n=== {passed} passed, {failed} failed ===")
    import shutil
    shutil.rmtree(_TMP_HOME, ignore_errors=True)
    sys.exit(0 if failed == 0 else 1)
