"""Tests for v3-G chunk 3b ``<state_update>`` 标签解析 + TTS strip + clamping。"""
import os
import sys
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.agents.chat import _parse_state_update, _build_state_update_instruction
from backend.utils.text_filters import strip_state_update

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))


# ---------------------------------------------------------------------------
# 1. parse self-closing
# ---------------------------------------------------------------------------

async def test_parse_self_closing_full():
    print("\n[state_update — self-closing full attrs]")
    text = '<state_update mood="happy" intimacy_delta="+1" thought="觉得用户努力" />正文…'
    parsed, stripped = _parse_state_update(text)
    check("parsed not None", parsed is not None)
    check("mood happy", parsed["mood"] == "happy")
    check("intimacy_delta +1 → 1", parsed["intimacy_delta"] == 1)
    check("thought captured", parsed["thought"] == "觉得用户努力")
    check("tag stripped", stripped == "正文…", f"got {stripped!r}")


async def test_parse_negative_delta():
    print("\n[state_update — negative intimacy_delta]")
    text = '<state_update mood="sad" intimacy_delta="-2" />伤心。'
    parsed, _ = _parse_state_update(text)
    check("intimacy_delta -2", parsed["intimacy_delta"] == -2)
    check("mood sad", parsed["mood"] == "sad")


async def test_parse_partial_attrs():
    print("\n[state_update — only mood, no delta no thought]")
    text = '<state_update mood="curious" />嗯？'
    parsed, _ = _parse_state_update(text)
    check("mood parsed", parsed["mood"] == "curious")
    check("intimacy_delta None", parsed["intimacy_delta"] is None)
    check("thought None", parsed["thought"] is None)


async def test_parse_no_tag_returns_none():
    print("\n[state_update — no tag → (None, text)]")
    text = "我没有打标签。"
    parsed, stripped = _parse_state_update(text)
    check("parsed None", parsed is None)
    check("text unchanged", stripped == text)


async def test_parse_closing_variant():
    print("\n[state_update — closing variant <state_update>...</state_update>]")
    text = '<state_update mood="excited" intimacy_delta="+1">忽略此中文</state_update>正文。'
    parsed, stripped = _parse_state_update(text)
    check("mood parsed", parsed["mood"] == "excited")
    check("inner content also stripped",
          "忽略此中文" not in stripped, f"got {stripped!r}")


async def test_parse_invalid_delta():
    print("\n[state_update — non-numeric delta → None]")
    text = '<state_update mood="happy" intimacy_delta="abc" />嗯。'
    parsed, _ = _parse_state_update(text)
    check("mood still parsed", parsed["mood"] == "happy")
    check("delta None on parse failure", parsed["intimacy_delta"] is None)


async def test_parse_single_quotes():
    print("\n[state_update — single-quoted attrs]")
    text = "<state_update mood='happy' intimacy_delta='+1' />剩余"
    parsed, _ = _parse_state_update(text)
    check("single quotes parsed", parsed["mood"] == "happy" and parsed["intimacy_delta"] == 1)


async def test_parse_multiple_tags_first_wins():
    print("\n[state_update — multiple tags, first wins, all stripped]")
    text = (
        '<state_update mood="happy" /><state_update mood="sad" />正文'
    )
    parsed, stripped = _parse_state_update(text)
    check("first mood wins", parsed["mood"] == "happy")
    check("all tags stripped",
          "<state_update" not in stripped, f"got {stripped!r}")


async def test_parse_activity_attr():
    print("\n[state_update — activity attr (extra)]")
    text = '<state_update mood="calm" activity="在烤面包" />嗯。'
    parsed, _ = _parse_state_update(text)
    check("activity captured", parsed.get("activity") == "在烤面包")


# ---------------------------------------------------------------------------
# 2. strip_state_update (TTS preprocessor / persistence-side)
# ---------------------------------------------------------------------------

async def test_strip_self_closing():
    print("\n[strip_state_update — self-closing]")
    text = '<state_update mood="happy" intimacy_delta="+1" />剩余正文。'
    out = strip_state_update(text)
    check("tag removed", out == "剩余正文。", f"got {out!r}")


async def test_strip_with_inner_content():
    print("\n[strip_state_update — closing variant]")
    text = '<state_update mood="x">inner</state_update>剩余'
    out = strip_state_update(text)
    check("entire tag + inner removed",
          "<state_update" not in out and "inner" not in out,
          f"got {out!r}")


async def test_strip_no_tag():
    print("\n[strip_state_update — no tag idempotent]")
    text = "今天天气不错。"
    out = strip_state_update(text)
    check("unchanged", out == text)


async def test_strip_empty_input():
    print("\n[strip_state_update — empty / None safe]")
    check("empty string", strip_state_update("") == "")
    check("None safe", strip_state_update(None) is None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 3. clamping in services.update_character_state
# ---------------------------------------------------------------------------

async def test_intimacy_delta_clamping():
    print("\n[services — intimacy_delta clamped to [-2, +2]]")
    # 不需要 DB —— 直接测 clamp 函数
    from backend.database.services import (
        _clamp_intimacy, INTIMACY_DELTA_PER_TURN_MAX, INTIMACY_MAX, INTIMACY_MIN,
    )
    check("INTIMACY_DELTA_PER_TURN_MAX = 2", INTIMACY_DELTA_PER_TURN_MAX == 2)
    check("INTIMACY_MAX = 100", INTIMACY_MAX == 100)
    check("INTIMACY_MIN = 0", INTIMACY_MIN == 0)
    check("clamp 150 → 100", _clamp_intimacy(150) == 100)
    check("clamp -5 → 0", _clamp_intimacy(-5) == 0)
    check("clamp 50 → 50", _clamp_intimacy(50) == 50)


async def test_mood_normalize():
    print("\n[services — mood normalize]")
    from backend.database.services import _normalize_mood, VALID_MOODS
    for m in VALID_MOODS:
        check(f"valid: {m}", _normalize_mood(m) == m)
    check("upper cased OK", _normalize_mood("HAPPY") == "happy")
    check("invalid → None", _normalize_mood("evil") is None)
    check("None → None", _normalize_mood(None) is None)
    check("empty → None", _normalize_mood("   ") is None)


# ---------------------------------------------------------------------------
# 4. _build_state_update_instruction
# ---------------------------------------------------------------------------

async def test_build_instruction_no_state():
    print("\n[chat — _build_state_update_instruction without state]")
    out = _build_state_update_instruction(None)
    check("returns string", isinstance(out, str) and len(out) > 0)
    check("instructs about <state_update> tag", "<state_update" in out)
    check("does NOT show concrete values",
          "/100" not in out and "心情：" not in out)


async def test_build_instruction_with_state():
    print("\n[chat — _build_state_update_instruction with state]")
    out = _build_state_update_instruction({
        "mood": "happy", "intimacy": 42,
        "thought": "在想用户的项目", "activity": "在看书",
    })
    check("contains 当前状态 header", "[你的当前状态]" in out)
    check("shows mood happy", "happy" in out)
    check("shows intimacy 42/100", "42/100" in out)
    check("shows thought", "在想用户的项目" in out)
    check("shows activity", "在看书" in out)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

async def main():
    await test_parse_self_closing_full()
    await test_parse_negative_delta()
    await test_parse_partial_attrs()
    await test_parse_no_tag_returns_none()
    await test_parse_closing_variant()
    await test_parse_invalid_delta()
    await test_parse_single_quotes()
    await test_parse_multiple_tags_first_wins()
    await test_parse_activity_attr()
    await test_strip_self_closing()
    await test_strip_with_inner_content()
    await test_strip_no_tag()
    await test_strip_empty_input()
    await test_intimacy_delta_clamping()
    await test_mood_normalize()
    await test_build_instruction_no_state()
    await test_build_instruction_with_state()

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
