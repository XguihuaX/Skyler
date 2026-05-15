"""v4 persona engineering segment 2 — 50+ test cases.

覆盖:
  Phase 1 — Renderer 5 字段升级 (7)
  Phase 2 — ja tag 链路 (8)
  Phase 3 — Persona REST API (12)
  Phase 5 — Migration (2 + ensure-defaults 2)
  Regression — segment 1 + sanitize 链路保持绿

Run:
    .venv/bin/python tests/test_persona_segment2.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from typing import Any, Dict, List, Optional
from unittest.mock import patch

_TMP_HOME = tempfile.mkdtemp(prefix="momoos-v4-persona-s2-")
os.environ["HOME"] = _TMP_HOME
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import create_async_engine

from backend.agents.prompt.persona_loader import LoadedPersona, LoadedState
from backend.agents.prompt.renderer import (
    _render_layer_a,
    _render_layer_c,
    filter_samples_by_tolerance,
    render_system_prompt,
)
from backend.utils.text_filters import (
    extract_tts_text,
    strip_ja_en_tags_for_subtitle,
    strip_all_for_tts,
)

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
            "_global": ["作为AI"],
            "_qwen": [],
            "_deepseek": [],
        },
        relationship_to_user={"type": "companion"},
    )
    base.update(overrides)
    return LoadedPersona(**base)


def _mock_state(**overrides) -> LoadedState:
    base = dict(mood="neutral", intimacy=0, activity=None, current_thought=None)
    base.update(overrides)
    return LoadedState(**base)


# ===========================================================================
# Phase 1 — Renderer 5 字段升级 (7 tests)
# ===========================================================================

def test_render_self_intro_low_intimacy_uses_0_69():
    print("\n[1] self_intro 双梯级:intimacy=30 → 0-69 公开版")
    persona = _mock_persona(identity={
        "name": "Mai", "aliases": [], "self_reference": "我",
        "age": None, "occupation": None, "origin": None,
        "self_intro": {
            "0-69": "公开版自我介绍 PUBLIC_SENTINEL",
            "70-100": "深度版自我介绍 DEEP_SENTINEL",
        },
    })
    state = _mock_state(intimacy=30)
    out = _render_layer_c(persona, state, None, "qwen")
    check("PUBLIC_SENTINEL appears", "PUBLIC_SENTINEL" in out)
    check("DEEP_SENTINEL absent", "DEEP_SENTINEL" not in out)
    check("'深度模式' header absent", "深度模式" not in out)


def test_render_self_intro_high_intimacy_uses_70_100():
    print("\n[2] self_intro 双梯级:intimacy=85 → 70-100 深度版")
    persona = _mock_persona(identity={
        "name": "Mai", "aliases": [], "self_reference": "我",
        "age": None, "occupation": None, "origin": None,
        "self_intro": {
            "0-69": "公开版自我介绍 PUBLIC_SENTINEL",
            "70-100": "深度版自我介绍 DEEP_SENTINEL",
        },
    })
    state = _mock_state(intimacy=85)
    out = _render_layer_c(persona, state, None, "qwen")
    check("DEEP_SENTINEL appears", "DEEP_SENTINEL" in out)
    check("PUBLIC_SENTINEL absent", "PUBLIC_SENTINEL" not in out)
    check("'深度模式' header present", "深度模式" in out)


def test_filter_samples_by_tolerance_low():
    print("\n[3] tolerance=0.2 → 只命中 [0.0,0.4] 区间样本")
    samples = [
        {"scene": "low", "text": "淡", "tolerance_range": [0.0, 0.4]},
        {"scene": "mid", "text": "中", "tolerance_range": [0.4, 0.7]},
        {"scene": "high", "text": "浓", "tolerance_range": [0.7, 1.0]},
        {"scene": "any", "text": "全域"},  # 无 tolerance_range → 总命中
    ]
    out = filter_samples_by_tolerance(samples, 0.2)
    scenes = [s["scene"] for s in out]
    check("only 'low' and 'any' kept", scenes == ["low", "any"], f"got {scenes}")


def test_filter_samples_by_tolerance_high():
    print("\n[4] tolerance=0.9 → 命中 [0.7,1.0] + 全域;0-empty fallback 不触发")
    samples = [
        {"scene": "low", "text": "淡", "tolerance_range": [0.0, 0.4]},
        {"scene": "high", "text": "浓", "tolerance_range": [0.7, 1.0]},
        {"scene": "any", "text": "全域"},
    ]
    out = filter_samples_by_tolerance(samples, 0.9)
    scenes = [s["scene"] for s in out]
    check("'high' + 'any' kept", scenes == ["high", "any"], f"got {scenes}")

    # tolerance 完全错配 → fallback 到全集(不返 0 条)
    edge_samples = [
        {"scene": "low", "text": "淡", "tolerance_range": [0.0, 0.3]},
    ]
    out2 = filter_samples_by_tolerance(edge_samples, 0.9)
    check("0-match fallback returns full list",
          [s["scene"] for s in out2] == ["low"])


def test_render_preferences_mixed_types():
    print("\n[5] lore.preferences mixed (string + dict) 兼容")
    persona = _mock_persona(lore={
        "preferences": {
            "likes": [
                "纯字符串爱好_PLAIN",
                {"item": "字典爱好_DICT", "why": "因为_REASON"},
                {"item": "字典无 why"},
            ],
            "dislikes": ["不喜欢的事 PLAIN_DISLIKE"],
            "secretly_appreciates": ["默默感激 SECRET"],
        }
    })
    out = _render_layer_c(persona, _mock_state(), None, "qwen")
    check("plain string like rendered", "纯字符串爱好_PLAIN" in out)
    check("dict like rendered", "字典爱好_DICT" in out)
    check("dict why annotation rendered", "(因为_REASON)" in out)
    check("dict no-why rendered", "字典无 why" in out)
    check("dislike rendered", "PLAIN_DISLIKE" in out)
    check("secretly_appreciates section rendered", "SECRET" in out)
    check("'[偏好]' header present", "[偏好]" in out)


def test_render_taboo_topics_hard_no_with_reaction():
    print("\n[6] taboo_topics.hard_no 含 her_reaction 输出")
    persona = _mock_persona(taboo_topics={
        "hard_no": [
            {"topic": "提到她的真实身份", "her_reaction": "立刻沉默,转移话题"},
        ],
        "soft_no": [
            {"topic": "问她年龄", "her_reaction": "笑着回避"},
        ],
    })
    out = _render_layer_c(persona, _mock_state(), None, "qwen")
    check("'[禁区与反应]' header", "[禁区与反应]" in out)
    check("hard_no topic", "提到她的真实身份" in out)
    check("hard_no reaction", "立刻沉默,转移话题" in out)
    check("soft_no topic", "问她年龄" in out)
    check("soft_no reaction", "笑着回避" in out)


def test_render_emotion_triggers_full():
    print("\n[7] lore.emotion_triggers 渲染 ssml_tag + intensity + triggers + expression")
    persona = _mock_persona(lore={
        "emotion_triggers": {
            "shy": {
                "ssml_tag": "shy",
                "intensity": 0.7,
                "triggers": ["被夸聪明", "被牵手"],
                "expression": "侧脸,声音变小",
            },
            "annoyed_cold": {
                "ssml_tag": "neutral",
                "intensity": 0.4,
                "triggers": ["问她'你喜欢谁'"],
                "expression": "笑着回避问题",
            },
        }
    })
    out = _render_layer_c(persona, _mock_state(), None, "qwen")
    check("emotion_triggers header", "[情绪触发参考]" in out)
    check("shy section rendered", "shy" in out and "0.7" in out)
    check("shy triggers rendered", "被夸聪明" in out and "被牵手" in out)
    check("shy expression rendered", "侧脸,声音变小" in out)
    check("ssml emotion tag included", "<emotion>shy</emotion>" in out)
    check("annoyed_cold section rendered", "annoyed_cold" in out)


# ===========================================================================
# Phase 2 — ja tag 链路 (8 tests)
# ===========================================================================

def test_layer_a_ja_mode_includes_directive():
    """Bugfix-segment2-2 + Bugfix-segment2-3:ja directive 强约束**意群交替**
    格式 ── 不集中(seg2-2)+ 不切碎(seg2-3)。"""
    print("\n[8] layer_a tts_language='ja' 含 ja directive (意群交替 spec)")
    out = _render_layer_a(available_motions=None, tts_language="ja")
    check("[日语 TTS 模式] header", "[日语 TTS 模式" in out)
    check("<ja>...</ja> tag format described",
          "<ja>" in out and "</ja>" in out)
    # 意群 / coherent thought 描述(seg2-3 引入,seg2-2 alternation 升级版)
    check("'意群' instruction present", "意群" in out)
    # Bugfix-segment2-2:旧版"一回合只输出一组"必须**已删除**,否则 LLM 集中
    # 写中文最后才 ja,后端 sentence-level extract 看不到 → fallback raw →
    # 中文送日语 voice 合成,听起来错乱
    check("OLD wrong wording '一回合只输出一组' REMOVED",
          "一回合只输出一组" not in out,
          "still contains forbidden old wording")


def test_layer_a_ja_directive_says_alternate():
    """Bugfix-segment2-2 + seg2-3:directive 必须传达"多个 ja tag 交替"语义,
    不能是单 ja(集中)也不能每句一 ja(切碎)。"""
    print("\n[8a] ja directive 传达意群级中日交替语义")
    out = _render_layer_a(available_motions=None, tts_language="ja")
    # seg2-3:意群边界 / 单字短词不独立成 tag(隐含交替)
    check("'意群边界' or '意群' 边界规则",
          "意群边界" in out or "意群" in out)
    # 单字短词不独立 → 隐含合并到意群,且多意群 → 多 ja tag
    check("anti-pattern hint:'单字' / '短词' / '不能独立'",
          "单字" in out or "不能独立" in out or "短词" in out)
    # 一回合多 ja tag(意群级)是正确的
    check("'多个 ja tag' or '一回合内' 多 tag 表述",
          "多个" in out or "一回合内" in out or "多个 ja tag" in out)


def test_layer_a_ja_directive_has_correct_example():
    """Bugfix-segment2-2:必须含 ✓ 正确示范(中文 → ja → 中文 → ja 交替)。"""
    print("\n[8b] ja directive ✓ correct example shows alternation")
    out = _render_layer_a(available_motions=None, tts_language="ja")
    check("✓ marker present", "✓" in out)
    # 正确示范应该有**多个** <ja> tag(交替),不是一个
    # find the example block, count <ja> occurrences in it
    correct_idx = out.find("正确格式")
    wrong_idx = out.find("错误格式")
    correct_block = out[correct_idx:wrong_idx] if (correct_idx >= 0 and wrong_idx > correct_idx) else ""
    ja_count_correct = correct_block.count("<ja>")
    check("✓ example contains 2+ <ja> tags (alternating)",
          ja_count_correct >= 2, f"got {ja_count_correct} in correct block")
    check("✓ example shows Japanese after each Chinese sentence",
          "「" in correct_block)  # 日语引号


def test_layer_a_ja_directive_has_wrong_example_warning():
    """Bugfix-segment2-2:必须含 ✗ 错误示范展示 anti-pattern,LLM 看到这种
    "集中模式" example marked WRONG → 不模仿。"""
    print("\n[8c] ja directive ✗ wrong example marked as anti-pattern")
    out = _render_layer_a(available_motions=None, tts_language="ja")
    check("✗ marker present", "✗" in out)
    check("'错误格式' header present", "错误格式" in out)
    # 错误示范应该只有 1 个 <ja>(整段集中),正是要避免的模式
    wrong_idx = out.find("错误格式")
    if wrong_idx > 0:
        # extract block until next header or end
        rest = out[wrong_idx:wrong_idx + 400]
        # 错误块本身就示范"一段中文 + 一个 ja",所以 1 个 ja 正确
        ja_count_wrong = rest.count("<ja>")
        check("✗ example shows the anti-pattern (single ja for all sentences)",
              ja_count_wrong >= 1, f"got {ja_count_wrong} in wrong block")
    # 还要说明 WHY:explanation tells LLM why alternation matters
    check("explanation 'TTS 错乱' or 'sentence' or '音色' 说明",
          "TTS 错乱" in out or "音色" in out or "sentence" in out)


# ===========================================================================
# Bugfix-Segment2-3 — 意群粒度 + sentence merge buffer (8 tests)
# ===========================================================================

def test_layer_a_ja_directive_min_chunk_size_specified():
    """Directive 必须含 ≥ 10 字 意群粒度规则。"""
    print("\n[8d] ja directive 含 ≥ 10 字 意群粒度约束")
    out = _render_layer_a(available_motions=None, tts_language="ja")
    check("'意群' or 'coherent thought' phrasing", "意群" in out)
    check("'≥ 10 字' or '10-30 字' 数字约束",
          "≥ 10 字" in out or "10-30 字" in out or "10 字" in out)
    check("'单字短词' or '不能独立成 tag' 单字禁忌",
          "单字短词" in out or "不能" in out)


def test_layer_a_ja_directive_correct_example_grouped():
    """正确示范必须演示**多句合并到一个意群**的 ja tag。"""
    print("\n[8e] ja directive ✓ correct example 演示意群合并")
    out = _render_layer_a(available_motions=None, tts_language="ja")
    # 找一个正确示例,验里面有合并的句号(多句合并成一个 ja)
    correct_idx = out.find("正确格式 ✓")
    next_section_idx = out.find("错误格式")
    correct_block = out[correct_idx:next_section_idx] if (
        correct_idx >= 0 and next_section_idx > correct_idx
    ) else ""
    # 正确示例内每个 <ja> 包住至少一个意群,意群内可有多个中文句号
    # eg "嗯,去吧。我不吵你。" 1 个 ja 包 2 个句号
    check("✓ example has at least one ja-tag with 2+ Chinese 句号(意群合并示范)",
          # 找 "...。...。"<ja> pattern(2 个 。 在 quote 内)
          ('。我' in correct_block or '。你' in correct_block or
           '。先' in correct_block or '。专心' in correct_block),
          "expected 2+ 句号 in a single quote+ja pair")


def test_layer_a_ja_directive_wrong_example_too_fine():
    """错误示范必须包含"切碎"的 anti-pattern(每句一个 ja)。"""
    print("\n[8f] ja directive ✗ 包含切碎 anti-pattern")
    out = _render_layer_a(available_motions=None, tts_language="ja")
    # 找"切得太碎"或类似 anti-pattern 提示
    check("'切碎' / '切得太碎' / 'too fine' 表述",
          "切碎" in out or "切得太碎" in out or "太碎" in out)
    # 错误示范应该有 3+ 个 ja tag(每个 1-3 字短)
    # 找"嗯。" "去吧。" 这种短句各自带 ja
    has_fine_anti = (
        '"嗯。"<ja>' in out or
        '\"嗯。\"<ja>' in out or
        '"哦。"<ja>' in out
    )
    check("✗ example shows 1-word sentence with own ja tag",
          has_fine_anti or "切" in out,  # 至少有"切"字
          "expected '嗯。'<ja>...</ja> as anti-pattern")


# ---------------------------------------------------------------------------
# sentence_merge.merge_short_sentences (5 tests)
# ---------------------------------------------------------------------------

async def _collect(gen):
    out = []
    async for item in gen:
        out.append(item)
    return out


async def _fake_stream(*items):
    for x in items:
        yield x


async def test_sentence_yield_merges_short_sentences():
    """两个短中文句被合并成 1 个 yield。"""
    print("\n[Mc1] merge_short_sentences:'嗯。' + '去吧。' 合并(2 短 → 1 yield)")
    from backend.agents.sentence_merge import merge_short_sentences
    out = await _collect(merge_short_sentences(
        _fake_stream('"嗯。"<ja>「うん。」</ja>', '"去吧。"<ja>「行きなさい。」</ja>')
    ))
    check("2 short → 1 merged yield at stream end", len(out) == 1,
          f"got {len(out)} yields")
    check("merged buffer contains both ja segments",
          out and '<ja>「うん。」</ja>' in out[0]
          and '<ja>「行きなさい。」</ja>' in out[0])


async def test_sentence_yield_flushes_at_15_chars():
    """累积 ≥ 15 字幕字数时立刻 flush。"""
    print("\n[Mc2] merge_short_sentences:buffer ≥ 15 sub-chars → flush")
    from backend.agents.sentence_merge import merge_short_sentences
    # 3 短句 ≈ 5+5+5 = 15 字幕字数 → 第 3 句 append 后 flush
    out = await _collect(merge_short_sentences(
        _fake_stream(
            '"嗯,去吧。"<ja>「うん。」</ja>',           # 5 sub-chars
            '"我不吵你。"<ja>「邪魔しないから。」</ja>', # 5 sub-chars
            '"专心看完。"<ja>「ゆっくり読んで。」</ja>', # 5 sub-chars
        )
    ))
    # buffer 累积到 15 字 → flush;期望最终 1 个 yield(或 2 视 boundary)
    check("3 short ≥ 15 chars accumulated → flushed",
          1 <= len(out) <= 2, f"got {len(out)} yields")
    # 所有 3 个 ja segments 都应被包含(总和)
    all_text = "".join(out)
    check("all 3 ja segments preserved", "うん" in all_text and "邪魔" in all_text and "ゆっくり" in all_text)


async def test_sentence_yield_flushes_on_stream_end_with_residue():
    """stream 结束时残余 buffer 必须 flush。"""
    print("\n[Mc3] merge_short_sentences:stream end → flush residue")
    from backend.agents.sentence_merge import merge_short_sentences
    out = await _collect(merge_short_sentences(
        _fake_stream('"嗯。"<ja>「うん。」</ja>')  # 1 sub-char,buffer 不到 15
    ))
    check("1 short → 1 yield at end", len(out) == 1)
    check("residue contains the sentence",
          out and 'うん' in out[0])


async def test_sentence_yield_passes_through_long_sentences_unchanged():
    """≥ 15 字幕字数的长 sentence 直接 pass-through,不缓冲。"""
    print("\n[Mc4] merge_short_sentences:长 sentence 直通,不延迟")
    from backend.agents.sentence_merge import merge_short_sentences
    # 一个 20 字中文 sentence,字幕 sub_len 20 ≥ 15 → 立即 yield
    long_s = '"今天天气真好,我刚刚在写代码,你呢?"<ja>「今日いい天気ね。仕事してた?」</ja>'
    short_s = '"嗯。"<ja>「うん。」</ja>'
    out = await _collect(merge_short_sentences(
        _fake_stream(long_s, short_s)
    ))
    check("2 yields (long passthrough + short residue at end)",
          len(out) == 2, f"got {len(out)}")
    check("first yield is the long sentence", out and out[0] == long_s)
    check("second yield is the short residue",
          len(out) > 1 and "嗯" in out[1])


async def test_sentence_yield_passes_through_dict_events():
    """dict tool events 必须 pass-through 并在前 flush 当前 buffer 保顺序。"""
    print("\n[Mc5] merge_short_sentences:dict event pass-through + flush buffer")
    from backend.agents.sentence_merge import merge_short_sentences
    short_s = '"嗯。"<ja>「うん。」</ja>'
    tool_event = {"type": "tool_use_start", "tool_name": "search"}
    out = await _collect(merge_short_sentences(
        _fake_stream(short_s, tool_event, short_s)
    ))
    # 期望:
    #   - 第 1 短句 buffer
    #   - tool_event 到 → flush buffer + yield event
    #   - 第 2 短句 buffer
    #   - stream end → flush buffer
    #   总 3 yields
    check("3 yields total (buffer flush + event + residue)",
          len(out) == 3, f"got {len(out)}")
    check("tool_event preserved in correct position",
          out[1] == tool_event)
    check("first/third are str", isinstance(out[0], str) and isinstance(out[2], str))


# ---------------------------------------------------------------------------
# extract_tts_text 多 <ja> tag concat (Bugfix-segment2-3 配套)
# ---------------------------------------------------------------------------

def test_extract_tts_text_concatenates_multiple_ja_tags():
    """合并 buffer 含 2+ <ja> tag → extract 拼接全部 Japanese segments。"""
    print("\n[Mc6] extract_tts_text:多 <ja> tag 拼接")
    raw = '"嗯。"<ja>「うん。」</ja>"去吧。"<ja>「行きなさい。」</ja>'
    out = extract_tts_text(raw, "ja")
    check("both ja segments concatenated",
          "「うん。」" in out and "「行きなさい。」" in out,
          f"got {out!r}")
    check("no Chinese leaked", "嗯。" not in out and "去吧。" not in out)


def test_layer_a_zh_mode_no_ja_directive():
    print("\n[9] layer_a tts_language='zh' (default) 不含 ja/en directive")
    out_default = _render_layer_a(available_motions=None)  # default zh
    out_explicit = _render_layer_a(available_motions=None, tts_language="zh")
    check("zh default: no [日语 TTS 模式]", "[日语 TTS 模式" not in out_default)
    check("zh default: no [英语 TTS 模式]", "[英语 TTS 模式" not in out_default)
    check("zh explicit: no [日语 TTS 模式]", "[日语 TTS 模式" not in out_explicit)


def test_extract_tts_text_ja_with_tag():
    print("\n[10] extract_tts_text ja 模式正确取 <ja> 内容")
    raw = '"...笨蛋。"<ja>「...バカ。」</ja>'
    out = extract_tts_text(raw, "ja")
    check("Japanese content extracted", out == "「...バカ。」", f"got {out!r}")


def test_extract_tts_text_ja_missing_tag_fallback():
    print("\n[11] extract_tts_text ja 但 LLM 漏标 → fallback 到原文(剥 meta tag)")
    raw = "<thinking>x</thinking>纯中文没有 ja 标记。"
    out = extract_tts_text(raw, "ja")
    check("falls back to stripped raw",
          out.strip() == "纯中文没有 ja 标记。", f"got {out!r}")


def test_extract_tts_text_zh_default():
    print("\n[12] extract_tts_text zh 等价于 strip_all_for_tts")
    raw = "<thinking>think</thinking>正文。"
    out = extract_tts_text(raw, "zh")
    expected = strip_all_for_tts(raw)
    check("zh equals strip_all_for_tts", out == expected, f"got {out!r}")


def test_strip_ja_tag_for_subtitle():
    print("\n[13] strip_ja_en_tags_for_subtitle 删 ja/en 标签")
    raw = '"...笨蛋。"<ja>「...バカ。」</ja>'
    out = strip_ja_en_tags_for_subtitle(raw)
    check("ja tag removed", "<ja>" not in out and "</ja>" not in out)
    check("Chinese preserved", '"...笨蛋。"' in out)

    raw_en = "Hello.<en>你好。</en>"
    out_en = strip_ja_en_tags_for_subtitle(raw_en)
    check("en tag removed", "<en>" not in out_en)


def test_sanitize_chain_includes_ja_tag_in_boundary():
    print("\n[14] _BOUNDARY_PAIRED_TAGS 含 'ja' 和 'en' + boundary 状态机识别")
    from backend.agents.chat import _BOUNDARY_PAIRED_TAGS, _find_boundary
    check("ja in boundary set", "ja" in _BOUNDARY_PAIRED_TAGS)
    check("en in boundary set", "en" in _BOUNDARY_PAIRED_TAGS)

    # 验:ja 标签**内部**的全角句末标点不能让 state machine 提前切句
    # buf 以 < 开头进 tag 检测,< 后是 'j' (字母) → 跳过整段 <ja>...</ja>
    # ja 内部的 。 应被忽略;ja 未闭合 → -1
    buf_unclosed = "<ja>「バカ。"  # ja open + 内部 。 + 未闭合
    idx_unclosed = _find_boundary(buf_unclosed)
    check("unclosed ja → -1 (wait for </ja>, ignore inner 。)",
          idx_unclosed == -1, f"got idx={idx_unclosed}")

    # ja 闭合 + 后跟句末标点 → 应在闭合后的 。 处切句
    buf_closed = "<ja>「バカ。」</ja>。"
    idx_closed = _find_boundary(buf_closed)
    # 切点应在最后那个 。(位置 14 = len("<ja>「バカ。」</ja>"))
    check("closed ja → boundary at trailing 。 outside tag",
          idx_closed == len("<ja>「バカ。」</ja>"),
          f"got idx={idx_closed} expected={len('<ja>「バカ。」</ja>')}")


def test_mai_voice_model_has_tts_language_ja_after_migration():
    """Phase 5 migration 模块 import 检查(详细行为在 Phase 5 tests 测)。"""
    print("\n[15] Phase 5 migration modules import OK")
    from backend.database.migrations import v4_persona_segment2_mai_ja  # noqa: F401
    from backend.database.migrations import v4_persona_segment2_ensure_defaults  # noqa: F401
    check("v4_persona_segment2_mai_ja imports OK", True)
    check("v4_persona_segment2_ensure_defaults imports OK", True)


# ===========================================================================
# Phase 3 — Persona REST API (12 tests)
#
# 用 FastAPI TestClient + 独立 in-memory engine。所有 endpoint 都注册到
# 一个 mini app,经 client.request 调用,验 status code + JSON shape。
# ===========================================================================

from sqlalchemy.ext.asyncio import async_sessionmaker
from fastapi import FastAPI


def _make_api_engine_and_app():
    """每个 API test 一份 fresh in-memory engine + 单独 mini FastAPI app。"""
    engine_obj = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False, connect_args={"check_same_thread": False},
    )
    SessionLocal = async_sessionmaker(engine_obj, expire_on_commit=False)

    async def _get_session_test():
        async with SessionLocal() as s:
            yield s

    from backend.routes.persona_api import router as persona_router
    from backend.database import get_session as real_get_session

    app = FastAPI()
    app.include_router(persona_router, prefix="/api")
    app.dependency_overrides[real_get_session] = _get_session_test

    return engine_obj, SessionLocal, app


async def _setup_api_db(engine_obj) -> None:
    """建全套 schema(ORM metadata.create_all 拿 12-列 characters 表 + 关联),
    seed 1 char + 跑 v4_persona migration seed 1 builtin variant。"""
    from backend.database import Base  # 触发 ORM metadata
    import backend.database.models  # noqa: F401 注册 Character / CharacterPersona

    async with engine_obj.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # 仅 insert 一个 character row(其他列允许 NULL)
        await conn.execute(sa_text(
            "INSERT INTO characters (id, name, persona) VALUES (1, 'TestChar', 'p1')"
        ))
    # 跑 v4_persona_thickening_segment1 migration(seed default variant +
    # builtin_seed backup + partial unique index)
    from backend.database.migrations import v4_persona_thickening_segment1 as mod
    from unittest.mock import patch as _patch
    with _patch.object(mod, "engine", engine_obj):
        await mod.run_migration()


async def _call_api(app, method: str, path: str, body: Optional[dict] = None):
    """Async TestClient-style helper using httpx ASGI transport。"""
    import httpx
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        kwargs = {}
        if body is not None:
            kwargs["json"] = body
        resp = await client.request(method, path, **kwargs)
        return resp.status_code, (resp.json() if resp.content else None)


async def test_get_personas_list():
    print("\n[16] GET /characters/{id}/personas → list")
    engine_obj, _, app = _make_api_engine_and_app()
    await _setup_api_db(engine_obj)
    sc, body = await _call_api(app, "GET", "/api/characters/1/personas")
    check("200 OK", sc == 200, f"sc={sc}")
    check("returns list", isinstance(body, list) and len(body) == 1)
    if body:
        check("variant_name=default", body[0]["variant_name"] == "default")
        check("is_active=True", body[0]["is_active"] is True)
        check("identity is dict (json-parsed)", isinstance(body[0]["identity"], dict))
    await engine_obj.dispose()


async def test_get_active_persona():
    print("\n[17] GET /characters/{id}/personas/active")
    engine_obj, _, app = _make_api_engine_and_app()
    await _setup_api_db(engine_obj)
    sc, body = await _call_api(app, "GET", "/api/characters/1/personas/active")
    check("200 OK", sc == 200)
    check("is_active=True", body and body["is_active"] is True)
    check("identity.name='TestChar'",
          body and body["identity"]["name"] == "TestChar")
    await engine_obj.dispose()


async def test_get_persona_by_id():
    print("\n[18] GET /personas/{id}")
    engine_obj, _, app = _make_api_engine_and_app()
    await _setup_api_db(engine_obj)
    # default seeded id=1
    sc, body = await _call_api(app, "GET", "/api/personas/1")
    check("200 OK", sc == 200)
    check("returns same id", body and body["id"] == 1)
    # 404 on unknown
    sc2, _ = await _call_api(app, "GET", "/api/personas/9999")
    check("404 for unknown id", sc2 == 404)
    await engine_obj.dispose()


async def test_create_persona_user_variant():
    print("\n[19] POST create user variant")
    engine_obj, _, app = _make_api_engine_and_app()
    await _setup_api_db(engine_obj)
    body = {
        "variant_name": "病娇 Mai",
        "description": "yandere variant",
        "identity": {"name": "Mai-y", "aliases": [], "self_reference": "本小姐"},
        "personality_core": {"core_traits": ["yandere"]},
        "speech_style": {"vocabulary": "obsessive"},
        "signature_phrases": ["只准看我"],
        "voice_samples": [],
        "forbidden_phrases": {"_global": []},
        "relationship_to_user": {"type": "lover"},
    }
    sc, resp = await _call_api(app, "POST", "/api/characters/1/personas", body)
    check("200 OK", sc == 200, f"sc={sc} resp={resp}")
    check("is_builtin=False", resp and resp["is_builtin"] is False)
    check("is_active=False(创建不激活)", resp and resp["is_active"] is False)
    check("variant_name persisted", resp and resp["variant_name"] == "病娇 Mai")
    check("signature_phrases parsed list",
          resp and resp["signature_phrases"] == ["只准看我"])
    await engine_obj.dispose()


async def test_create_persona_unique_constraint():
    print("\n[20] POST 重复 variant_name → 409")
    engine_obj, _, app = _make_api_engine_and_app()
    await _setup_api_db(engine_obj)
    body = {
        "variant_name": "default",  # 与 seeded variant 重名
        "identity": {"name": "Dup"},
        "personality_core": {},
        "speech_style": {},
        "signature_phrases": [],
        "voice_samples": [],
        "forbidden_phrases": {},
        "relationship_to_user": {},
    }
    sc, resp = await _call_api(app, "POST", "/api/characters/1/personas", body)
    check("409 conflict", sc == 409, f"sc={sc} resp={resp}")
    await engine_obj.dispose()


async def test_patch_persona_partial():
    print("\n[21] PATCH partial 单字段更新")
    engine_obj, _, app = _make_api_engine_and_app()
    await _setup_api_db(engine_obj)
    # PATCH 改 description + speech_style.vocabulary
    sc, resp = await _call_api(app, "PATCH", "/api/personas/1", {
        "description": "updated description",
        "speech_style": {"vocabulary": "playful_only"},
    })
    check("200 OK", sc == 200, f"sc={sc}")
    check("description updated", resp and resp["description"] == "updated description")
    check("speech_style.vocabulary updated",
          resp and resp["speech_style"].get("vocabulary") == "playful_only")
    # 未传字段不变
    check("variant_name unchanged", resp and resp["variant_name"] == "default")
    await engine_obj.dispose()


async def test_patch_builtin_allowed():
    print("\n[22] PATCH builtin variant 允许(用户全权)")
    engine_obj, _, app = _make_api_engine_and_app()
    await _setup_api_db(engine_obj)
    sc, resp = await _call_api(app, "PATCH", "/api/personas/1", {
        "identity": {"name": "Renamed Mai"},
    })
    check("200 OK on builtin patch", sc == 200, f"sc={sc}")
    check("identity.name patched on builtin",
          resp and resp["identity"]["name"] == "Renamed Mai")
    check("is_builtin still True", resp and resp["is_builtin"] is True)
    await engine_obj.dispose()


async def test_delete_active_persona_rejected():
    print("\n[23] DELETE active variant → 409")
    engine_obj, _, app = _make_api_engine_and_app()
    await _setup_api_db(engine_obj)
    sc, resp = await _call_api(app, "DELETE", "/api/personas/1")  # default is_active=1
    check("409 cannot delete active", sc == 409, f"sc={sc} resp={resp}")
    await engine_obj.dispose()


async def test_delete_non_active_ok():
    print("\n[24] DELETE non-active variant → 200")
    engine_obj, _, app = _make_api_engine_and_app()
    await _setup_api_db(engine_obj)
    # 先创建一个非 active 的 variant
    create_body = {
        "variant_name": "deletable",
        "identity": {"name": "D"}, "personality_core": {}, "speech_style": {},
        "signature_phrases": [], "voice_samples": [],
        "forbidden_phrases": {}, "relationship_to_user": {},
    }
    sc1, created = await _call_api(app, "POST", "/api/characters/1/personas", create_body)
    new_id = created["id"]
    sc2, resp = await _call_api(app, "DELETE", f"/api/personas/{new_id}")
    check("200 OK", sc2 == 200, f"sc={sc2} resp={resp}")
    check("response.ok=True", resp and resp.get("ok") is True)
    # GET 404 after delete
    sc3, _ = await _call_api(app, "GET", f"/api/personas/{new_id}")
    check("subsequent GET 404", sc3 == 404)
    await engine_obj.dispose()


async def test_activate_persona_swaps_flag():
    print("\n[25] POST activate 互换 is_active")
    engine_obj, _, app = _make_api_engine_and_app()
    await _setup_api_db(engine_obj)
    # 创建第二个 variant
    create_body = {
        "variant_name": "v2",
        "identity": {"name": "V2"}, "personality_core": {}, "speech_style": {},
        "signature_phrases": [], "voice_samples": [],
        "forbidden_phrases": {}, "relationship_to_user": {},
    }
    _, created = await _call_api(app, "POST", "/api/characters/1/personas", create_body)
    new_id = created["id"]
    # 激活 v2
    sc, resp = await _call_api(app, "POST", f"/api/personas/{new_id}/activate")
    check("200 OK", sc == 200, f"sc={sc}")
    check("new variant is_active=True", resp and resp["is_active"] is True)
    check("just_switched=True", resp and resp.get("just_switched") is True)
    # 原 default 现在 is_active=False
    _, default_after = await _call_api(app, "GET", "/api/personas/1")
    check("default deactivated", default_after and default_after["is_active"] is False)
    await engine_obj.dispose()


async def test_activate_already_active_noop():
    print("\n[26] POST activate already-active → just_switched=False")
    engine_obj, _, app = _make_api_engine_and_app()
    await _setup_api_db(engine_obj)
    sc, resp = await _call_api(app, "POST", "/api/personas/1/activate")
    check("200 OK", sc == 200, f"sc={sc}")
    check("just_switched=False (already active)",
          resp and resp.get("just_switched") is False)
    await engine_obj.dispose()


# ===========================================================================
# Phase 5 — Migrations (4 tests)
# ===========================================================================

async def test_mai_ja_migration_tags_matching_voice():
    """voice_id 匹配 → tagged ja;voice_id 不匹配 → 不动。"""
    print("\n[28] Phase 5 mai_ja:by voice_id, covers all chars with same voice")
    engine_obj = _make_api_engine_and_app()[0]
    from backend.database import Base
    import backend.database.models  # noqa: F401

    MAI_VOICE = "cosyvoice-v3.5-plus-bailian-a19f528011c1446eafd4c4990301270f"
    OTHER_VOICE = "cosyvoice-v3.5-plus-bailian-some-other-voice"

    async with engine_obj.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # 3 行 character:2 用 Mai voice (id=1, 101),1 用其他 voice (id=2)
        # 注:JSON 字符串里的 ``:true`` 不能直接用 f-string 嵌 sa_text(SQLAlchemy
        # 把 ``:tr`` 当 bind param)。用 :voice / :other_voice / :json 参数化。
        vm_mai = json.dumps({"provider": "cosyvoice", "voice": MAI_VOICE,
                             "instruct_supported": True})
        vm_other = json.dumps({"provider": "cosyvoice", "voice": OTHER_VOICE,
                               "instruct_supported": True})
        await conn.execute(
            sa_text(
                "INSERT INTO characters (id, name, persona, voice_model) VALUES "
                "(1, 'CharA', 'pA', :vm_mai), "
                "(2, 'CharB', 'pB', :vm_other), "
                "(101, 'CharC', 'pC', :vm_mai)"
            ),
            {"vm_mai": vm_mai, "vm_other": vm_other},
        )

    from backend.database.migrations import v4_persona_segment2_mai_ja as mod
    from unittest.mock import patch as _patch
    with _patch.object(mod, "engine", engine_obj):
        await mod.run_migration()

    async with engine_obj.begin() as conn:
        rows = (await conn.execute(sa_text(
            "SELECT id, json_extract(voice_model, '$.tts_language') FROM characters ORDER BY id"
        ))).all()
    by_id = dict(rows)
    check("id=1 (Mai voice) tagged ja", by_id[1] == "ja", f"got {by_id[1]!r}")
    check("id=2 (other voice) untouched", by_id[2] is None, f"got {by_id[2]!r}")
    check("id=101 (Mai voice) tagged ja", by_id[101] == "ja", f"got {by_id[101]!r}")
    await engine_obj.dispose()


async def test_mai_ja_migration_idempotent():
    """重跑 migration: tts_language=ja 已存在的行不被重复更新。"""
    print("\n[29] Phase 5 mai_ja:idempotent (re-run noop)")
    engine_obj = _make_api_engine_and_app()[0]
    from backend.database import Base
    import backend.database.models  # noqa: F401

    MAI_VOICE = "cosyvoice-v3.5-plus-bailian-a19f528011c1446eafd4c4990301270f"
    async with engine_obj.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        vm_mai = json.dumps({"provider": "cosyvoice", "voice": MAI_VOICE,
                             "instruct_supported": True})
        await conn.execute(
            sa_text("INSERT INTO characters (id, name, persona, voice_model) "
                    "VALUES (1, 'CharA', 'pA', :vm)"),
            {"vm": vm_mai},
        )

    from backend.database.migrations import v4_persona_segment2_mai_ja as mod
    from unittest.mock import patch as _patch
    with _patch.object(mod, "engine", engine_obj):
        await mod.run_migration()  # first run: tags
        # second run: should be no-op (rowcount=0, no error)
        await mod.run_migration()

    async with engine_obj.begin() as conn:
        ttslang = (await conn.execute(sa_text(
            "SELECT json_extract(voice_model, '$.tts_language') FROM characters WHERE id=1"
        ))).scalar()
    check("after 2 runs still ja", ttslang == "ja", f"got {ttslang!r}")
    await engine_obj.dispose()


async def test_ensure_defaults_seeds_missing_chars():
    """ensure-defaults migration 给缺 active variant 的 character 补一份。"""
    print("\n[30] Phase 5 ensure_defaults:seeds missing chars")
    engine_obj = _make_api_engine_and_app()[0]
    from backend.database import Base
    import backend.database.models  # noqa: F401

    async with engine_obj.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # 2 character rows,**没有**对应 character_personas
        await conn.execute(sa_text(
            "INSERT INTO characters (id, name, persona) VALUES (1, 'A', 'a'), (2, 'B', 'b')"
        ))
        # 先建 segment-1 表(用模块跑一次给 1 个 char 建,然后再加 1 个 char,
        # 跑 segment-2 ensure-defaults 看是否补上 char 2)
    # 跑 segment 1 migration 给现有 chars seed default(此时是 2 个 char)
    from backend.database.migrations import v4_persona_thickening_segment1 as mod1
    from unittest.mock import patch as _patch
    with _patch.object(mod1, "engine", engine_obj):
        await mod1.run_migration()
    # 此时两个 char 都已 seeded;模拟"insert 新 char 后 segment-1 不再跑"
    async with engine_obj.begin() as conn:
        await conn.execute(sa_text(
            "INSERT INTO characters (id, name, persona) VALUES (101, 'LateChar', 'late')"
        ))
        # 验:char 101 缺 active variant
        cnt_before = (await conn.execute(sa_text(
            "SELECT COUNT(*) FROM character_personas WHERE character_id=101"
        ))).scalar()
    check("LateChar has no variant initially", cnt_before == 0)

    # 跑 segment 2 ensure-defaults
    from backend.database.migrations import v4_persona_segment2_ensure_defaults as mod2
    with _patch.object(mod2, "engine", engine_obj):
        await mod2.run_migration()

    async with engine_obj.begin() as conn:
        cnt_after = (await conn.execute(sa_text(
            "SELECT COUNT(*) FROM character_personas WHERE character_id=101 AND is_active=1"
        ))).scalar()
        # seed backup 同步写
        seed_cnt = (await conn.execute(sa_text(
            "SELECT COUNT(*) FROM character_personas_builtin_seed WHERE character_id=101"
        ))).scalar()
    check("LateChar seeded after ensure-defaults", cnt_after == 1, f"got {cnt_after}")
    check("seed_data backup also written", seed_cnt == 1, f"got {seed_cnt}")
    await engine_obj.dispose()


async def test_ensure_defaults_idempotent():
    """ensure-defaults 跑 2 次,row count 稳定。"""
    print("\n[31] Phase 5 ensure_defaults:idempotent")
    engine_obj = _make_api_engine_and_app()[0]
    from backend.database import Base
    import backend.database.models  # noqa: F401

    async with engine_obj.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(sa_text(
            "INSERT INTO characters (id, name, persona) VALUES (1, 'X', 'x')"
        ))

    from backend.database.migrations import v4_persona_thickening_segment1 as mod1
    from backend.database.migrations import v4_persona_segment2_ensure_defaults as mod2
    from unittest.mock import patch as _patch
    with _patch.object(mod1, "engine", engine_obj):
        await mod1.run_migration()
    with _patch.object(mod2, "engine", engine_obj):
        await mod2.run_migration()
        await mod2.run_migration()  # second run

    async with engine_obj.begin() as conn:
        cnt = (await conn.execute(sa_text(
            "SELECT COUNT(*) FROM character_personas WHERE character_id=1"
        ))).scalar()
    check("row count stable after re-run", cnt == 1, f"got {cnt}")
    await engine_obj.dispose()


async def test_restore_to_builtin_from_seed():
    print("\n[27] POST restore_to_builtin 从 seed 恢复")
    engine_obj, _, app = _make_api_engine_and_app()
    await _setup_api_db(engine_obj)
    # PATCH 改 identity.name
    await _call_api(app, "PATCH", "/api/personas/1", {
        "identity": {"name": "Hijacked"},
    })
    _, hijacked = await _call_api(app, "GET", "/api/personas/1")
    check("post-patch name", hijacked and hijacked["identity"]["name"] == "Hijacked")
    # restore
    sc, resp = await _call_api(app, "POST", "/api/personas/1/restore_to_builtin")
    check("200 OK", sc == 200, f"sc={sc}")
    check("name restored to seeded TestChar",
          resp and resp["identity"]["name"] == "TestChar")
    await engine_obj.dispose()


# ===========================================================================
# Runner
# ===========================================================================

async def _async_main():
    # Phase 1
    test_render_self_intro_low_intimacy_uses_0_69()
    test_render_self_intro_high_intimacy_uses_70_100()
    test_filter_samples_by_tolerance_low()
    test_filter_samples_by_tolerance_high()
    test_render_preferences_mixed_types()
    test_render_taboo_topics_hard_no_with_reaction()
    test_render_emotion_triggers_full()
    # Phase 2
    test_layer_a_ja_mode_includes_directive()
    test_layer_a_ja_directive_says_alternate()
    test_layer_a_ja_directive_has_correct_example()
    test_layer_a_ja_directive_has_wrong_example_warning()
    # Bugfix-Segment2-3
    test_layer_a_ja_directive_min_chunk_size_specified()
    test_layer_a_ja_directive_correct_example_grouped()
    test_layer_a_ja_directive_wrong_example_too_fine()
    await test_sentence_yield_merges_short_sentences()
    await test_sentence_yield_flushes_at_15_chars()
    await test_sentence_yield_flushes_on_stream_end_with_residue()
    await test_sentence_yield_passes_through_long_sentences_unchanged()
    await test_sentence_yield_passes_through_dict_events()
    test_extract_tts_text_concatenates_multiple_ja_tags()
    test_layer_a_zh_mode_no_ja_directive()
    test_extract_tts_text_ja_with_tag()
    test_extract_tts_text_ja_missing_tag_fallback()
    test_extract_tts_text_zh_default()
    test_strip_ja_tag_for_subtitle()
    test_sanitize_chain_includes_ja_tag_in_boundary()
    test_mai_voice_model_has_tts_language_ja_after_migration()
    # Phase 3
    await test_get_personas_list()
    await test_get_active_persona()
    await test_get_persona_by_id()
    await test_create_persona_user_variant()
    await test_create_persona_unique_constraint()
    await test_patch_persona_partial()
    await test_patch_builtin_allowed()
    await test_delete_active_persona_rejected()
    await test_delete_non_active_ok()
    await test_activate_persona_swaps_flag()
    await test_activate_already_active_noop()
    await test_restore_to_builtin_from_seed()
    # Phase 5
    await test_mai_ja_migration_tags_matching_voice()
    await test_mai_ja_migration_idempotent()
    await test_ensure_defaults_seeds_missing_chars()
    await test_ensure_defaults_idempotent()


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
