"""v4 persona engineering segment 1 — 31 test cases.

覆盖:
  Schema/Migration (5):
    1. test_migration_creates_tables
    2. test_migration_seeds_7_default_variants
    3. test_migration_idempotent
    4. test_active_persona_unique_per_char
    5. test_builtin_seed_backup_matches_active
  Mode (3):
    6. test_determine_mode_proactive_origins
    7. test_determine_mode_user_defaults_roleplay
    8. test_determine_mode_unknown_origin_defaults_roleplay
  Layer A (3):
    9. test_render_layer_a_includes_tag_specs
   10. test_render_layer_a_emotion_paired_tag_form
   11. test_render_layer_a_density_constraint_text_present
  Layer B (3):
   12. test_render_layer_b_mode_directive_roleplay
   13. test_render_layer_b_mode_directive_proactive
   14. test_render_layer_b_tool_addendum_inline
  Layer C (8):
   15. test_render_layer_c_identity_card
   16. test_render_layer_c_includes_voice_samples
   17. test_render_layer_c_excludes_empty_voice_samples
   18. test_render_layer_c_forbidden_phrases_qwen_subset
   19. test_render_layer_c_forbidden_phrases_deepseek_subset
   20. test_render_layer_c_state_runtime_present
   21. test_render_layer_c_thought_sanitize_dirty
   22. test_render_layer_c_anchor_phrase_present
  Layer D (4):
   23. test_render_layer_d_basic_context
   24. test_render_layer_d_briefing_schema_invalid_skipped
   25. test_render_layer_d_briefing_imperative_stripped
   26. test_render_layer_d_no_briefing_in_roleplay
  Transition (2):
   27. test_render_transition_only_when_switched
   28. test_render_transition_includes_variant_name
  Sanitize invariant (2):
   29. test_renderer_output_does_not_break_sanitize_invariants
   30. test_emotion_tag_paired_form_preserved_in_output
  Renderer integration (1):
   31. test_render_full_prompt_smoke

Run:
    .venv/bin/python tests/test_persona_segment1.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from unittest.mock import patch

_TMP_HOME = tempfile.mkdtemp(prefix="momoos-v4-persona-s1-")
os.environ["HOME"] = _TMP_HOME
# 单独 schema DB(in-memory)给 Schema/Migration 测试用,renderer 测试 mock 掉
# loader 不碰 DB。
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from backend.agents.prompt.briefing_sanitize import (
    ProactiveBriefing,
    sanitize_briefing_field,
    validate_and_sanitize_briefing,
)
from backend.agents.prompt.mode import Mode, PROACTIVE_ORIGINS, determine_mode
from backend.agents.prompt.persona_loader import LoadedPersona, LoadedState
from backend.agents.prompt.renderer import (
    _render_layer_a,
    _render_layer_b,
    _render_layer_c,
    _render_layer_d,
    _render_transition,
    render_system_prompt,
    sanitize_thought,
)

# ---------------------------------------------------------------------------
# Test runner harness — 与项目其他 unit test 同 style(手动 PASS/FAIL)
# ---------------------------------------------------------------------------

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))


# ---------------------------------------------------------------------------
# Mock fixtures
# ---------------------------------------------------------------------------

def _mock_persona(**overrides) -> LoadedPersona:
    base = dict(
        character_id=1,
        variant_name="default",
        identity={
            "name": "TestChar", "aliases": [], "self_reference": "我",
            "age": None, "occupation": None, "origin": None,
        },
        personality_core={
            "core_traits": [], "contrasts": [], "energy_level": "medium",
            "default_emotion": "calm",
        },
        speech_style={
            "vocabulary": "neutral", "sentence_rhythm": "medium",
            "user_address": "你", "emoji_habit": "rare",
            "punctuation_quirk": "standard", "cliche_tolerance": 0.5,
        },
        signature_phrases=[],
        voice_samples=[],
        forbidden_phrases={
            "_global": ["作为AI", "作为一个助手"],
            "_qwen": ["总的来说"],
            "_deepseek": ["请允许我"],
        },
        relationship_to_user={"type": "companion", "intimacy_progression": "linear"},
    )
    base.update(overrides)
    return LoadedPersona(**base)


def _mock_state(**overrides) -> LoadedState:
    base = dict(mood="neutral", intimacy=0, activity=None, current_thought=None)
    base.update(overrides)
    return LoadedState(**base)


# ---------------------------------------------------------------------------
# 1-5: Schema / Migration
# ---------------------------------------------------------------------------

# 同 bugfix-4 测试范本:用单独的 in-memory engine 跑 migration 验 schema,
# 避开主 momoos.db。migration 函数本身用 ``backend.database.engine`` 全局
# (production DB),这里 monkey-patch 那个 engine。

from backend.database import migrations as _migrations_pkg  # noqa: E402


def _make_test_engine():
    """每个 schema test 一个 fresh in-memory engine."""
    return create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False, connect_args={"check_same_thread": False},
    )


async def _setup_characters_table(conn) -> None:
    """migration 假设 characters 表已存在,这里 mock 出来给 schema test 用。"""
    await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS characters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            persona TEXT NOT NULL
        )
    """))
    # seed 3 行模拟 characters 表(包含 Momo id=1 触发 yaml ``默认`` key 映射)
    await conn.execute(text(
        "INSERT INTO characters (id, name, persona) VALUES "
        "(1, 'Momo', 'momo persona'), "
        "(2, '八重神子', 'yae persona'), "
        "(99, 'TestChar99', 'test 99')"
    ))


async def _run_schema_migration_on(engine_obj) -> None:
    """对 patch 后的 engine 跑 v4 migration。"""
    from backend.database.migrations import v4_persona_thickening_segment1 as mod
    with patch.object(mod, "engine", engine_obj):
        async with engine_obj.begin() as conn:
            await _setup_characters_table(conn)
        await mod.run_migration()


async def test_migration_creates_tables():
    print("\n[1] migration creates tables")
    engine_obj = _make_test_engine()
    await _run_schema_migration_on(engine_obj)
    async with engine_obj.begin() as conn:
        cp = (await conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='character_personas'"
        ))).first()
        seed = (await conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='character_personas_builtin_seed'"
        ))).first()
        idx = (await conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name='idx_persona_active_per_char'"
        ))).first()
    check("character_personas table exists", cp is not None)
    check("character_personas_builtin_seed table exists", seed is not None)
    check("partial unique index exists", idx is not None)
    await engine_obj.dispose()


async def test_migration_seeds_7_default_variants():
    """Mock 3 row characters → 3 default variants seeded."""
    print("\n[2] migration seeds default variant per character")
    engine_obj = _make_test_engine()
    await _run_schema_migration_on(engine_obj)
    async with engine_obj.begin() as conn:
        rows = (await conn.execute(text(
            "SELECT character_id, variant_name, is_active, is_builtin "
            "FROM character_personas ORDER BY character_id"
        ))).all()
    check("3 variants seeded (mock characters table had 3 rows)", len(rows) == 3,
          f"got {len(rows)}")
    check("all variant_name = 'default'",
          all(r[1] == "default" for r in rows))
    check("all is_active=1", all(r[2] == 1 for r in rows))
    check("all is_builtin=1", all(r[3] == 1 for r in rows))
    await engine_obj.dispose()


async def test_migration_idempotent():
    print("\n[3] migration idempotent (run twice)")
    engine_obj = _make_test_engine()
    await _run_schema_migration_on(engine_obj)
    # second run on same engine
    from backend.database.migrations import v4_persona_thickening_segment1 as mod
    with patch.object(mod, "engine", engine_obj):
        await mod.run_migration()
    async with engine_obj.begin() as conn:
        n = (await conn.execute(text(
            "SELECT COUNT(*) FROM character_personas"
        ))).scalar()
    check("row count stable after 2 runs", n == 3, f"got {n}")
    await engine_obj.dispose()


async def test_active_persona_unique_per_char():
    """partial UNIQUE INDEX 应阻止同 character 双 is_active=1。"""
    print("\n[4] active variant unique per character (partial UNIQUE INDEX)")
    engine_obj = _make_test_engine()
    await _run_schema_migration_on(engine_obj)
    async with engine_obj.begin() as conn:
        # insert another variant for character_id=1 with is_active=1 — 必须 raise
        from sqlalchemy.exc import IntegrityError
        ok = False
        try:
            await conn.execute(text(
                "INSERT INTO character_personas "
                "(character_id, variant_name, is_active, is_builtin, "
                " identity, personality_core, speech_style, signature_phrases, "
                " voice_samples, forbidden_phrases, relationship_to_user) "
                "VALUES (1, 'second', 1, 0, '{}', '{}', '{}', '[]', '[]', '{}', '{}')"
            ))
        except IntegrityError:
            ok = True
    check("INSERT second is_active=1 raises IntegrityError", ok)
    await engine_obj.dispose()


async def test_builtin_seed_backup_matches_active():
    """character_personas_builtin_seed 的 seed_data JSON 应与 active variant
    的 7 字段内容等价(每个字段在 active row 里是 JSON-in-TEXT)。"""
    print("\n[5] builtin_seed table backup matches active variant")
    engine_obj = _make_test_engine()
    await _run_schema_migration_on(engine_obj)
    async with engine_obj.begin() as conn:
        active = (await conn.execute(text(
            "SELECT identity, personality_core, speech_style, signature_phrases, "
            "voice_samples, forbidden_phrases, relationship_to_user "
            "FROM character_personas WHERE character_id=1 AND is_active=1"
        ))).first()
        seed = (await conn.execute(text(
            "SELECT seed_data FROM character_personas_builtin_seed "
            "WHERE character_id=1 AND variant_name='default'"
        ))).first()
    check("active row found", active is not None)
    check("seed backup row found", seed is not None)
    seed_dict = json.loads(seed[0])
    keys = ("identity", "personality_core", "speech_style", "signature_phrases",
            "voice_samples", "forbidden_phrases", "relationship_to_user")
    for i, k in enumerate(keys):
        check(f"seed[{k}] == json.loads(active.{k})",
              seed_dict[k] == json.loads(active[i]))
    await engine_obj.dispose()


# ---------------------------------------------------------------------------
# 6-8: Mode determination
# ---------------------------------------------------------------------------

def test_determine_mode_proactive_origins():
    print("\n[6] determine_mode for known PROACTIVE_ORIGINS")
    for origin in PROACTIVE_ORIGINS:
        check(f"  {origin} → PROACTIVE", determine_mode(origin) == Mode.PROACTIVE)


def test_determine_mode_user_defaults_roleplay():
    print("\n[7] determine_mode 'user' → ROLEPLAY")
    check("user → ROLEPLAY", determine_mode("user") == Mode.ROLEPLAY)


def test_determine_mode_unknown_origin_defaults_roleplay():
    print("\n[8] unknown origin / None / '' → ROLEPLAY")
    check("unknown_string → ROLEPLAY",
          determine_mode("xyz_unknown") == Mode.ROLEPLAY)
    check("'' → ROLEPLAY", determine_mode("") == Mode.ROLEPLAY)


# ---------------------------------------------------------------------------
# 9-11: Layer A
# ---------------------------------------------------------------------------

def test_render_layer_a_includes_tag_specs():
    print("\n[9] layer_a 含 4 个 tag spec")
    out = _render_layer_a(["挥手", "害羞"])
    for tag in ("<thinking>", "<state_update", "<motion>", "<emotion>"):
        check(f"contains {tag!r}", tag in out)


def test_render_layer_a_emotion_paired_tag_form():
    """A1 sign-off: <emotion>X</emotion> paired-tag,不能出现 attribute 风格。"""
    print("\n[10] layer_a emotion uses paired-tag form (A1 sign-off)")
    out = _render_layer_a([])
    check("<emotion>...</emotion> appears", "<emotion>" in out and "</emotion>" in out)
    check("no attribute-style emotion=\"...\"", 'emotion="' not in out)
    check("no attribute-style emotion=xxx", "emotion=xxx" not in out and "emotion=hap" not in out)


def test_render_layer_a_density_constraint_text_present():
    print("\n[11] layer_a 含密度约束文本")
    out = _render_layer_a([])
    check("density constraint phrase", "密度约束" in out)
    check("3-5 回合约束", "3-5" in out or "3 - 5" in out)


# ---------------------------------------------------------------------------
# 12-14: Layer B
# ---------------------------------------------------------------------------

def test_render_layer_b_mode_directive_roleplay():
    print("\n[12] layer_b roleplay directive")
    out = _render_layer_b(Mode.ROLEPLAY, "ADDENDUM_X")
    check("contains roleplay header", "[本轮模式: roleplay]" in out)
    check("contains roleplay body", "日常陪伴对话" in out)
    check("no proactive body", "信息倾倒" not in out)


def test_render_layer_b_mode_directive_proactive():
    print("\n[13] layer_b proactive directive")
    out = _render_layer_b(Mode.PROACTIVE, "ADDENDUM_X")
    check("contains proactive header", "[本轮模式: proactive]" in out)
    check("contains proactive body", "signature_phrases 开场" in out)
    check("no roleplay body", "日常陪伴对话,请深度入戏" not in out)


def test_render_layer_b_tool_addendum_inline():
    print("\n[14] layer_b 嵌入 tool_addendum 原样")
    out = _render_layer_b(Mode.ROLEPLAY, "TOOLS_SENTINEL_QWERTYZ")
    check("tool_addendum injected", "TOOLS_SENTINEL_QWERTYZ" in out)


# ---------------------------------------------------------------------------
# 15-22: Layer C
# ---------------------------------------------------------------------------

def test_render_layer_c_identity_card():
    print("\n[15] layer_c 身份卡")
    persona = _mock_persona(identity={
        "name": "Momo", "aliases": ["小桃"], "self_reference": "本喵",
        "age": 22, "occupation": "AI 桌面助手", "origin": "v3-C 启用",
    })
    out = _render_layer_c(persona, _mock_state(), None, "qwen")
    check("name rendered", "Momo" in out)
    check("aliases rendered", "小桃" in out)
    check("age rendered", "22 岁" in out)
    check("occupation rendered", "AI 桌面助手" in out)
    check("origin rendered", "v3-C 启用" in out)
    check("self_reference rendered", "本喵" in out)


def test_render_layer_c_includes_voice_samples():
    print("\n[16] layer_c voice_samples 渲染")
    persona = _mock_persona(voice_samples=[
        {"scene": "起床问候", "text": "嗯…起床啦"},
        {"scene": "睡前", "text": "晚安,做个好梦"},
    ])
    out = _render_layer_c(persona, _mock_state(), None, "qwen")
    check("scene-1 rendered", "[起床问候]" in out and "嗯…起床啦" in out)
    check("scene-2 rendered", "[睡前]" in out and "晚安,做个好梦" in out)


def test_render_layer_c_excludes_empty_voice_samples():
    print("\n[17] layer_c 空 voice_samples 不渲染整段")
    persona = _mock_persona(voice_samples=[])
    out = _render_layer_c(persona, _mock_state(), None, "qwen")
    check("'真实样本' header absent", "真实样本" not in out)


def test_render_layer_c_forbidden_phrases_qwen_subset():
    print("\n[18] qwen forbidden_phrases 包含 _qwen 子集")
    persona = _mock_persona(forbidden_phrases={
        "_global": ["作为AI"],
        "_qwen": ["总的来说", "综上所述"],
        "_deepseek": ["请允许我"],
    })
    out_qwen = _render_layer_c(persona, _mock_state(), None, "qwen")
    check("qwen path: _qwen 短语出现", "总的来说" in out_qwen and "综上所述" in out_qwen)
    check("qwen path: _deepseek 短语不出现", "请允许我" not in out_qwen)
    check("qwen path: _global 仍出现", "作为AI" in out_qwen)


def test_render_layer_c_forbidden_phrases_deepseek_subset():
    print("\n[19] deepseek forbidden_phrases 包含 _deepseek 子集")
    persona = _mock_persona(forbidden_phrases={
        "_global": ["作为AI"],
        "_qwen": ["总的来说"],
        "_deepseek": ["请允许我", "我会尽力"],
    })
    out = _render_layer_c(persona, _mock_state(), None, "deepseek")
    check("deepseek path: _deepseek 短语出现",
          "请允许我" in out and "我会尽力" in out)
    check("deepseek path: _qwen 短语不出现", "总的来说" not in out)


def test_render_layer_c_state_runtime_present():
    print("\n[20] layer_c [当前状态] 段渲染 mood/intimacy/activity/thought")
    persona = _mock_persona()
    state = _mock_state(mood="happy", intimacy=42, activity="烤面包",
                       current_thought="心情不错")
    out = _render_layer_c(persona, state, "心情不错", "qwen")
    check("[当前状态] header", "[当前状态]" in out)
    check("mood happy", "happy" in out)
    check("intimacy 42/100", "42/100" in out)
    check("activity 烤面包", "烤面包" in out)
    check("thought 心情不错", "心情不错" in out)


def test_render_layer_c_thought_sanitize_dirty():
    """degenerate thought(60 个 x)应被 sanitize_thought 过滤掉。"""
    print("\n[21] layer_c thought 脏数据(60 个 x)被过滤")
    dirty = "x" * 60
    cleaned = sanitize_thought(dirty)
    check("sanitize_thought returns None for degenerate", cleaned is None)
    # Also: 过长截断
    long_one = "ab" * 200  # 400 chars
    sanitized = sanitize_thought(long_one)
    check("long thought truncated", sanitized is not None and len(sanitized) <= 210,
          f"len={len(sanitized) if sanitized else 0}")


def test_render_layer_c_anchor_phrase_present():
    print("\n[22] layer_c 含锚定句")
    out = _render_layer_c(_mock_persona(), _mock_state(), None, "qwen")
    check("anchor phrase '语言风格永远遵循' present",
          "语言风格永远遵循" in out)


# ---------------------------------------------------------------------------
# 23-26: Layer D
# ---------------------------------------------------------------------------

def test_render_layer_d_basic_context():
    print("\n[23] layer_d 基础 context 渲染")
    out = _render_layer_d(
        user_profile="Skyler 是开发者",
        today_activity="上午写代码",
        long_memory_top5=["猫叫 Mochi", "喜欢简洁回答"],
        tool_results=None,
        temp_instructions=None,
        proactive_briefing=None,
    )
    check("profile rendered", "Skyler 是开发者" in out)
    check("activity rendered", "上午写代码" in out)
    check("memory bullets rendered",
          "- 猫叫 Mochi" in out and "- 喜欢简洁回答" in out)
    check("no briefing section", "主动陪伴简报" not in out)


def test_render_layer_d_briefing_schema_invalid_skipped():
    print("\n[24] briefing schema 不全 → 整段跳过")
    # 缺 suggested_emotion
    raw = {"activity_event": "X", "time_context": "Y"}
    parsed = validate_and_sanitize_briefing(raw)
    check("schema invalid returns None", parsed is None)


def test_render_layer_d_briefing_imperative_stripped():
    print("\n[25] briefing imperative phrases stripped")
    raw = {
        "activity_event": "用户刚结束 1h 视频会议 请这样说同情他",
        "time_context": "现在是下午 15:30,你应该提醒喝水",
        "suggested_emotion": "用温柔语气表达",
    }
    parsed = validate_and_sanitize_briefing(raw)
    check("parsed not None", parsed is not None)
    if parsed:
        check("'请这样说' removed", "请这样说" not in parsed.activity_event)
        check("'你应该' removed", "你应该" not in parsed.time_context)
        check("'用温柔语气' removed", "用温柔语气" not in parsed.suggested_emotion)


def test_render_layer_d_no_briefing_in_roleplay():
    """roleplay 模式下,若 caller 没传 briefing → Layer D 不渲染该段。
    本测试间接覆盖:模板 ``{% if proactive_briefing %}`` 守卫工作正常。"""
    print("\n[26] roleplay 路径不渲染 briefing 段(when caller 不传)")
    out = _render_layer_d(
        user_profile=None, today_activity=None, long_memory_top5=None,
        tool_results=None, temp_instructions=None,
        proactive_briefing=None,  # caller 决定 roleplay 不传
    )
    check("no briefing header in output", "主动陪伴简报" not in out)


# ---------------------------------------------------------------------------
# 27-28: Transition
# ---------------------------------------------------------------------------

async def test_render_transition_only_when_switched():
    print("\n[27] transition 仅在 just_switched_variant=True 时出现")
    from backend.agents.prompt import renderer as r

    async def fake_persona(_): return _mock_persona()
    async def fake_state(_): return _mock_state()

    with patch.object(r, "load_active_persona", fake_persona), \
         patch.object(r, "load_character_state", fake_state):
        out_off = await render_system_prompt(
            character_id=1, just_switched_variant=False,
        )
        out_on = await render_system_prompt(
            character_id=1, just_switched_variant=True,
        )
    check("off: no transition marker", "刚切换为" not in out_off)
    check("on: transition marker present", "刚切换为" in out_on)


def test_render_transition_includes_variant_name():
    print("\n[28] transition 含 variant_name")
    out = _render_transition("user_custom_warm")
    check("variant_name interpolated", "user_custom_warm" in out)


# ---------------------------------------------------------------------------
# 29-30: Sanitize invariant
# ---------------------------------------------------------------------------

def test_renderer_output_does_not_break_sanitize_invariants():
    """Layer A 描述 emotion / thinking / state_update / motion 4 个 tag,
    应该与 chat.py 的 _BOUNDARY_PAIRED_TAGS / _EMOTION_RE / SUSPICIOUS_TAG_RE
    完全兼容。验:layer_a 输出**不含**会让 sanitize 链误剥的污染字符。"""
    print("\n[29] renderer output 不破 sanitize chain")
    from backend.agents.chat import _BOUNDARY_PAIRED_TAGS, _EMOTION_RE
    out = _render_layer_a(["挥手"])
    # 关键 tag name 都在 paired-tag 名单内
    for tagname in ("thinking", "emotion", "state_update", "motion"):
        check(f"{tagname} in _BOUNDARY_PAIRED_TAGS",
              tagname in _BOUNDARY_PAIRED_TAGS)
    # _EMOTION_RE 仍是 paired-tag pattern,不是 attribute(A1 sign-off)
    check("_EMOTION_RE pattern uses paired form",
          "<emotion>" in _EMOTION_RE.pattern and "</emotion>" in _EMOTION_RE.pattern)
    # layer_a 描述的 emotion 用 paired form
    check("layer_a uses <emotion>...</emotion> paired form",
          "<emotion>" in out and "</emotion>" in out)


def test_emotion_tag_paired_form_preserved_in_output():
    """A1 sign-off:渲染的 prompt 永远不引导 LLM 用 attribute 风格 emotion。"""
    print("\n[30] emotion paired-tag form preserved")
    out = _render_layer_a([])
    # 不应该出现 ``emotion="happy"`` 这种 attribute 风格教学
    check("no 'emotion=\"' attribute pattern",
          'emotion="happy"' not in out and 'emotion="x"' not in out)
    check("paired form is 'taught'",
          "<emotion>" in out and "</emotion>" in out)


# ---------------------------------------------------------------------------
# 31: Renderer integration smoke
# ---------------------------------------------------------------------------

async def test_render_full_prompt_smoke():
    """完整 4 层 + 数据 + mode 切换 smoke test。"""
    print("\n[31] full renderer smoke (mock persona, mode toggle)")
    from backend.agents.prompt import renderer as r

    async def fake_persona(cid):
        return _mock_persona(
            identity={
                "name": "MockMomo", "aliases": [], "self_reference": "我",
                "age": None, "occupation": None, "origin": None,
            },
            signature_phrases=["啊…早安"],
            voice_samples=[{"scene": "early", "text": "嗯…"}],
        )

    async def fake_state(cid):
        return _mock_state(mood="curious", intimacy=30, activity="读书")

    with patch.object(r, "load_active_persona", fake_persona), \
         patch.object(r, "load_character_state", fake_state):
        out = await render_system_prompt(
            character_id=1,
            turn_origin="user",
            tool_prompt_addendum="ADDENDUM_PAYLOAD_XYZ",
            user_profile="profile X",
            today_activity="activity Y",
            long_memory_top5=["memo Z"],
            llm_vendor="qwen",
        )

    check("Layer A present", "[输出格式规范" in out)
    check("Layer B roleplay header present", "[本轮模式: roleplay]" in out)
    check("Layer B tool_addendum present", "ADDENDUM_PAYLOAD_XYZ" in out)
    check("Layer C identity present", "MockMomo" in out)
    check("Layer C signature_phrase present", "啊…早安" in out)
    check("Layer C voice_sample present", "[early]" in out)
    check("Layer C state present", "curious" in out and "30/100" in out)
    check("Layer D profile present", "profile X" in out)
    check("Layer D activity present", "activity Y" in out)
    check("Layer D memory present", "memo Z" in out)
    check("anchor phrase present", "语言风格永远遵循" in out)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

async def _async_main():
    await test_migration_creates_tables()
    await test_migration_seeds_7_default_variants()
    await test_migration_idempotent()
    await test_active_persona_unique_per_char()
    await test_builtin_seed_backup_matches_active()

    test_determine_mode_proactive_origins()
    test_determine_mode_user_defaults_roleplay()
    test_determine_mode_unknown_origin_defaults_roleplay()

    test_render_layer_a_includes_tag_specs()
    test_render_layer_a_emotion_paired_tag_form()
    test_render_layer_a_density_constraint_text_present()

    test_render_layer_b_mode_directive_roleplay()
    test_render_layer_b_mode_directive_proactive()
    test_render_layer_b_tool_addendum_inline()

    test_render_layer_c_identity_card()
    test_render_layer_c_includes_voice_samples()
    test_render_layer_c_excludes_empty_voice_samples()
    test_render_layer_c_forbidden_phrases_qwen_subset()
    test_render_layer_c_forbidden_phrases_deepseek_subset()
    test_render_layer_c_state_runtime_present()
    test_render_layer_c_thought_sanitize_dirty()
    test_render_layer_c_anchor_phrase_present()

    test_render_layer_d_basic_context()
    test_render_layer_d_briefing_schema_invalid_skipped()
    test_render_layer_d_briefing_imperative_stripped()
    test_render_layer_d_no_briefing_in_roleplay()

    await test_render_transition_only_when_switched()
    test_render_transition_includes_variant_name()

    test_renderer_output_does_not_break_sanitize_invariants()
    test_emotion_tag_paired_form_preserved_in_output()

    await test_render_full_prompt_smoke()


def main() -> int:
    asyncio.run(_async_main())
    passed = sum(1 for _, ok in results if ok)
    failed = len(results) - passed
    print(f"\n{'='*60}\nResults: {passed}/{len(results)} passed, {failed} failed")
    if failed:
        print("FAILED:", ", ".join(n for n, ok in results if not ok))
        return 1
    print("ALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
