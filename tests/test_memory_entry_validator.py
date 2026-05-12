"""v3.5 chunk 10 commit 4 — memory_entry_validator + filter pipeline。

Reject:
  * JSON parse 失败 / 顶层不是 list / 单 entry 不是 dict
  * type 不在 ALLOWED_TYPES
  * content 长度超限 / 含 SUSPICIOUS tag
  * confidence 不是 number / 不在 [0,1] / 低于阈值
  * 与现有 memory 向量相似度 > dup_threshold

Soft warn (accept + log):
  * 反推词命中 (chunk 11 同 14 词清单)
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.utils import memory_entry_validator as v

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))


VALID_ENTRY = {
    "type": "fact",
    "content": "用户的猫叫 Mochi",
    "confidence": 0.9,
}


# ---------------------------------------------------------------------------
# parse_extractor_output
# ---------------------------------------------------------------------------


def test_parse_valid_json_list():
    print("\n[parse] 合法 JSON list 返 list")
    out = v.parse_extractor_output(json.dumps([VALID_ENTRY]))
    check("非 None", out is not None)
    check("len 1", len(out) == 1)


def test_parse_markdown_fence_stripped():
    print("\n[parse] markdown fence 自动剥")
    raw = "```json\n[]\n```"
    out = v.parse_extractor_output(raw)
    check("剥 fence 后返空 list", out == [])


def test_parse_empty_returns_none():
    print("\n[parse] 空 string → None")
    check("'' → None", v.parse_extractor_output("") is None)


def test_parse_invalid_json_returns_none():
    print("\n[parse] 非合法 JSON → None")
    check("→ None", v.parse_extractor_output("not json") is None)


def test_parse_top_level_dict_with_entries_key_accepted():
    print("\n[parse] 容忍 {'entries': [...]} dict wrap")
    raw = json.dumps({"entries": [VALID_ENTRY]})
    out = v.parse_extractor_output(raw)
    check("剥 wrapper 后 list", out is not None and len(out) == 1)


def test_parse_top_level_dict_without_entries_returns_none():
    print("\n[parse] {'foo': ...} → None")
    raw = json.dumps({"foo": [VALID_ENTRY]})
    check("→ None", v.parse_extractor_output(raw) is None)


def test_parse_top_level_not_list_or_dict_returns_none():
    print("\n[parse] 顶层 string / number → None")
    check("string → None", v.parse_extractor_output('"hi"') is None)
    check("number → None", v.parse_extractor_output('123') is None)


# ---------------------------------------------------------------------------
# _validate_entry_schema
# ---------------------------------------------------------------------------


def test_entry_valid_passes():
    print("\n[schema] 合法 entry → 返 cleaned dict")
    out = v._validate_entry_schema(VALID_ENTRY, user_id="u")
    check("非 None", out is not None)
    check("type", out["type"] == "fact")
    check("content stripped", out["content"] == "用户的猫叫 Mochi")
    check("confidence", out["confidence"] == 0.9)


def test_entry_reject_non_dict():
    print("\n[schema] 非 dict → None")
    check("None → None", v._validate_entry_schema(None, user_id="u") is None)
    check("list → None", v._validate_entry_schema([], user_id="u") is None)
    check("string → None", v._validate_entry_schema("x", user_id="u") is None)


def test_entry_reject_invalid_type():
    print("\n[schema] type 不在 ALLOWED_TYPES → None")
    e = {**VALID_ENTRY, "type": "bogus"}
    check("→ None", v._validate_entry_schema(e, user_id="u") is None)


def test_entry_reject_content_too_short():
    print("\n[schema] content 太短 → None")
    e = {**VALID_ENTRY, "content": "x"}
    check("len=1 → None", v._validate_entry_schema(e, user_id="u") is None)


def test_entry_reject_content_too_long():
    print("\n[schema] content 太长 → None")
    e = {**VALID_ENTRY, "content": "a" * 250}
    check("len=250 → None", v._validate_entry_schema(e, user_id="u") is None)


def test_entry_reject_suspicious_tag():
    print("\n[schema] SUSPICIOUS tag → None")
    e = {**VALID_ENTRY, "content": "用户喜欢 <netease.daily_recommend/>"}
    check("→ None", v._validate_entry_schema(e, user_id="u") is None)


def test_entry_reject_invalid_confidence():
    print("\n[schema] confidence 不合法 → None")
    check("non-number → None",
          v._validate_entry_schema(
              {**VALID_ENTRY, "confidence": "high"}, user_id="u") is None)
    check("> 1 → None",
          v._validate_entry_schema(
              {**VALID_ENTRY, "confidence": 1.5}, user_id="u") is None)
    check("< 0 → None",
          v._validate_entry_schema(
              {**VALID_ENTRY, "confidence": -0.1}, user_id="u") is None)
    check("bool → None",
          v._validate_entry_schema(
              {**VALID_ENTRY, "confidence": True}, user_id="u") is None)


def test_entry_backinference_keyword_accepted():
    print("\n[schema] 反推词命中 → accept (fail-open)")
    e = {**VALID_ENTRY, "content": "用户细腻敏感，需要被陪伴的人"}
    out = v._validate_entry_schema(e, user_id="u")
    check("非 None（fail-open）", out is not None)


# ---------------------------------------------------------------------------
# validate_and_filter_entries (top-level pipeline)
# ---------------------------------------------------------------------------


async def test_pipeline_rejects_below_min_confidence():
    print("\n[pipeline] confidence < min → reject")
    raw = json.dumps([
        {"type": "fact", "content": "置信度低的条目一",   "confidence": 0.3},
        {"type": "fact", "content": "置信度高的条目二",   "confidence": 0.95},
    ])
    out = await v.validate_and_filter_entries(
        raw, user_id="u",
        min_confidence=0.5, dup_threshold=0.99,
        existing_contents=[],
    )
    check("剩 1 条（>= 0.5）", len(out) == 1)
    check("是高置信条目",
          out[0]["content"] == "置信度高的条目二")


async def test_pipeline_rejects_duplicates_via_cosine():
    print("\n[pipeline] 与现有 memory 相似度 > dup_threshold → reject")
    # mock _is_duplicate 直接返 True 表示重复
    async def fake_is_dup(content, existing, th):
        return content.startswith("重复")
    with patch.object(v, "_is_duplicate", new=fake_is_dup):
        raw = json.dumps([
            {"type": "fact", "content": "重复的内容样本",   "confidence": 0.9},
            {"type": "fact", "content": "新的有用内容样本", "confidence": 0.9},
        ])
        out = await v.validate_and_filter_entries(
            raw, user_id="u",
            min_confidence=0.5, dup_threshold=0.9,
            existing_contents=["something"],
        )
    check("剩 1 条", len(out) == 1)
    check("是 '新的内容样本'", out[0]["content"] == "新的有用内容样本")


async def test_pipeline_llm_judge_filter():
    print("\n[pipeline] llm_judge=False → reject")
    async def judge_say_no(content):
        return False
    with patch.object(v, "_is_duplicate",
                      new=AsyncMock(return_value=False)):
        raw = json.dumps([VALID_ENTRY])
        out = await v.validate_and_filter_entries(
            raw, user_id="u",
            min_confidence=0.5, dup_threshold=0.9,
            existing_contents=[],
            llm_judge=judge_say_no,
        )
    check("被 judge reject", out == [])


async def test_pipeline_llm_judge_exception_fail_open():
    print("\n[pipeline] llm_judge raise → fail-open accept")
    async def judge_throws(content):
        raise RuntimeError("oops")
    with patch.object(v, "_is_duplicate",
                      new=AsyncMock(return_value=False)):
        raw = json.dumps([VALID_ENTRY])
        out = await v.validate_and_filter_entries(
            raw, user_id="u",
            min_confidence=0.5, dup_threshold=0.9,
            existing_contents=[],
            llm_judge=judge_throws,
        )
    check("异常 → accept", len(out) == 1)


async def test_pipeline_intra_batch_dedup():
    print("\n[pipeline] 同 batch 内部 dedup（后续 entry 看到前面已 accept 的）")

    async def fake_is_dup(content, existing, th):
        # 模拟 "Mochi" 与已 accept 的 Mochi 类相似度 > th
        return any("Mochi" in e for e in existing) and "Mochi" in content
    with patch.object(v, "_is_duplicate", new=fake_is_dup):
        raw = json.dumps([
            {"type": "fact", "content": "用户的猫叫 Mochi",       "confidence": 0.9},
            {"type": "fact", "content": "Mochi 是用户家的猫",     "confidence": 0.9},
            {"type": "fact", "content": "完全不同的另一条内容",   "confidence": 0.9},
        ])
        out = await v.validate_and_filter_entries(
            raw, user_id="u",
            min_confidence=0.5, dup_threshold=0.9,
            existing_contents=[],
        )
    check("剩 2 条（第一条 + 不同内容）", len(out) == 2)
    check("第二条被同 batch dedup",
          all("Mochi 是用户家的猫" != e["content"] for e in out))


async def test_pipeline_returns_empty_on_parse_failure():
    print("\n[pipeline] LLM 输出 garbage → []")
    out = await v.validate_and_filter_entries(
        "not a json", user_id="u",
        min_confidence=0.5, dup_threshold=0.9,
        existing_contents=[],
    )
    check("→ []", out == [])


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


async def amain():
    await test_pipeline_rejects_below_min_confidence()
    await test_pipeline_rejects_duplicates_via_cosine()
    await test_pipeline_llm_judge_filter()
    await test_pipeline_llm_judge_exception_fail_open()
    await test_pipeline_intra_batch_dedup()
    await test_pipeline_returns_empty_on_parse_failure()


def main():
    test_parse_valid_json_list()
    test_parse_markdown_fence_stripped()
    test_parse_empty_returns_none()
    test_parse_invalid_json_returns_none()
    test_parse_top_level_dict_with_entries_key_accepted()
    test_parse_top_level_dict_without_entries_returns_none()
    test_parse_top_level_not_list_or_dict_returns_none()
    test_entry_valid_passes()
    test_entry_reject_non_dict()
    test_entry_reject_invalid_type()
    test_entry_reject_content_too_short()
    test_entry_reject_content_too_long()
    test_entry_reject_suspicious_tag()
    test_entry_reject_invalid_confidence()
    test_entry_backinference_keyword_accepted()
    asyncio.run(amain())

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
