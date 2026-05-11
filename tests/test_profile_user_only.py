"""v3.5 chunk 9 Part 1 — profile_summary 输入只读 user 消息 unit。

断 LLM 自循环：旧逻辑把 user + assistant 都喂 LLM 重写 profile，导致角色
回应被当作"用户特征"反推 → in-context learning 自循环。本测试验证：

  1. ``_filter_user_messages`` 只留 ``role='user'`` 行
  2. ``_format_user_history`` 不带 ``[role]:`` 前缀（输入已无 assistant，
     不需角色标签）
  3. ``_format_user_history`` 仍跑 SUSPICIOUS_TAG_RE 清理（用户粘贴 HTML
     防御）
  4. ``_build_profile_prompt`` 文案明确禁止反推角色回应
  5. ``_compute_profile_summary`` 在 LLM mock 输出含可疑 tag 时保留旧
     profile
"""
from __future__ import annotations

import asyncio
import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.routes import ws as ws_mod

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))


# ---------------------------------------------------------------------------
# 1. _filter_user_messages
# ---------------------------------------------------------------------------


def test_filter_user_messages_drops_assistant():
    print("\n[1] _filter_user_messages 只留 user 行")
    rows = [
        SimpleNamespace(role="user", content="今天好累"),
        SimpleNamespace(role="assistant", content="<emotion>sad</emotion>抱抱"),
        SimpleNamespace(role="user", content="工作压力大"),
        SimpleNamespace(role="assistant", content="慢慢来"),
    ]
    out = ws_mod._filter_user_messages(rows)
    check("剩 2 条", len(out) == 2)
    check("两条都 role=user", all(r.role == "user" for r in out))
    check("内容顺序保留",
          out[0].content == "今天好累" and out[1].content == "工作压力大")


def test_filter_user_messages_empty():
    print("\n[1.b] 全 assistant → 返空")
    rows = [
        SimpleNamespace(role="assistant", content="hi"),
        SimpleNamespace(role="assistant", content="hello"),
    ]
    check("空 list", ws_mod._filter_user_messages(rows) == [])


def test_filter_user_messages_handles_no_role_attr():
    print("\n[1.c] row 无 role 字段 → 不视为 user")
    rows = [SimpleNamespace(content="x")]
    check("无 role 行被丢", ws_mod._filter_user_messages(rows) == [])


# ---------------------------------------------------------------------------
# 2. _format_user_history
# ---------------------------------------------------------------------------


def test_format_user_history_no_role_prefix():
    print("\n[2] _format_user_history 不带 [role]: 前缀")
    rows = [
        SimpleNamespace(role="user", content="今天好累"),
        SimpleNamespace(role="user", content="想喝咖啡"),
    ]
    out = ws_mod._format_user_history(rows)
    check("无 [user]: 前缀", "[user]:" not in out and "[assistant]:" not in out)
    check("行以 '- ' 开头", out.startswith("- "))
    check("两条都在",
          "今天好累" in out and "想喝咖啡" in out)


def test_format_user_history_sanitizes_suspicious():
    print("\n[2.b] _format_user_history 用户粘贴可疑 tag → 走 sanitize")
    rows = [
        SimpleNamespace(
            role="user",
            content="昨天我看到 <netease.daily_recommend></netease.daily_recommend> 的代码",
        ),
    ]
    out = ws_mod._format_user_history(rows)
    check("可疑 tag 已剥",
          "<netease." not in out and "</netease." not in out)
    check("正文保留", "昨天我看到" in out)


def test_format_user_history_empty_content_skipped():
    print("\n[2.c] empty content 行不打印")
    rows = [
        SimpleNamespace(role="user", content=""),
        SimpleNamespace(role="user", content="实际内容"),
    ]
    out = ws_mod._format_user_history(rows)
    check("只有一行实际内容", out.strip() == "- 实际内容")


# ---------------------------------------------------------------------------
# 3. _build_profile_prompt 文案
# ---------------------------------------------------------------------------


def test_prompt_text_warns_against_inferring_from_assistant():
    print("\n[3] prompt 文案明确禁止基于角色回应反推")
    p = ws_mod._build_profile_prompt(None, "- 用户消息 A\n- 用户消息 B")
    check("含'用户主动表达'", "主动表达" in p or "自己说过的话" in p)
    check("含'不要基于角色回应'", "不要基于角色" in p or "不要基于" in p)
    check("含'Momo' / '八重' 示例", "Momo" in p or "八重" in p)


def test_prompt_with_old_summary_includes_it():
    print("\n[3.b] 旧 summary 注入到 prompt")
    p = ws_mod._build_profile_prompt("老印象段。", "- 用户消息")
    check("旧 summary 文本可见", "老印象段" in p)


# ---------------------------------------------------------------------------
# 4. _compute_profile_summary（mock LLM 路径）
# ---------------------------------------------------------------------------


async def test_compute_skips_when_too_few_user_rows():
    print("\n[4] _compute_profile_summary skip_too_few_rows")
    # mock get_chat_history: 仅 3 行 user（< default 10）
    fake_rows = [
        SimpleNamespace(role="user", content="x"),
        SimpleNamespace(role="user", content="y"),
        SimpleNamespace(role="assistant", content="z"),
    ]
    with patch.object(
        ws_mod, "get_chat_history",
        AsyncMock(return_value=fake_rows),
    ):
        status, summary = await ws_mod._compute_profile_summary("u1")
    check("status == skip_too_few_rows", status == "skip_too_few_rows")
    check("summary None", summary is None)


async def test_compute_clears_on_empty_history():
    print("\n[4.b] _compute_profile_summary clears NULL on zero rows")
    with patch.object(ws_mod, "get_chat_history",
                      AsyncMock(return_value=[])), \
         patch.object(ws_mod, "update_profile_summary",
                      AsyncMock()) as up:
        status, summary = await ws_mod._compute_profile_summary("u2")
    check("status == cleared", status == "cleared")
    check("summary None", summary is None)
    check("update_profile_summary called with None",
          up.call_args is not None and up.call_args.args[2] is None)


async def test_compute_returns_new_summary_on_success():
    print("\n[4.c] _compute 成功路径返新 summary + status=regenerated")
    fake_rows = [
        SimpleNamespace(role="user", content=f"用户消息 {i}") for i in range(12)
    ] + [SimpleNamespace(role="assistant", content="不应出现") for _ in range(5)]

    fake_response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(
            content="这是一段足够长的新画像内容用来通过 MIN_OUTPUT_LEN 校验。" * 3,
        ))]
    )

    with patch.object(ws_mod, "get_chat_history",
                      AsyncMock(return_value=fake_rows)), \
         patch.object(ws_mod, "get_profile_summary",
                      AsyncMock(return_value=None)), \
         patch.object(ws_mod, "update_profile_summary", AsyncMock()), \
         patch.object(ws_mod, "call_llm",
                      AsyncMock(return_value=fake_response)) as call_llm_mock:
        status, summary = await ws_mod._compute_profile_summary("u3")

    check("status == regenerated", status == "regenerated")
    check("summary 非空", summary is not None and len(summary) > 0)

    # 关键：assistant 内容 NOT 喂给 LLM
    sent_prompt = call_llm_mock.call_args.kwargs["messages"][0]["content"]
    check("assistant 内容未喂 LLM",
          "不应出现" not in sent_prompt)
    check("user 内容已喂 LLM",
          "用户消息 0" in sent_prompt and "用户消息 11" in sent_prompt)


async def test_compute_suspicious_llm_output_keeps_old_profile():
    print("\n[4.d] _compute LLM 输出含可疑 tag → 保留旧 + skip_llm_suspicious")
    fake_rows = [
        SimpleNamespace(role="user", content=f"用户消息 {i}") for i in range(12)
    ]
    fake_response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(
            content="这是新画像 <netease.daily_recommend/> 包含可疑 tag" + "x" * 100,
        ))]
    )
    with patch.object(ws_mod, "get_chat_history",
                      AsyncMock(return_value=fake_rows)), \
         patch.object(ws_mod, "get_profile_summary",
                      AsyncMock(return_value="旧 profile")), \
         patch.object(ws_mod, "update_profile_summary", AsyncMock()) as up, \
         patch.object(ws_mod, "call_llm",
                      AsyncMock(return_value=fake_response)):
        status, summary = await ws_mod._compute_profile_summary("u4")
    check("status == skip_llm_suspicious", status == "skip_llm_suspicious")
    check("update_profile_summary NOT called",
          up.call_args is None)


async def test_compute_min_user_rows_override():
    print("\n[4.e] endpoint 路径用 min_user_rows=1，少量数据也可触发")
    fake_rows = [
        SimpleNamespace(role="user", content="仅一条用户消息也够"),
    ]
    fake_response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(
            content="基于一条消息形成的画像内容长度足够通过 MIN_OUTPUT_LEN 校验。" * 2,
        ))]
    )
    with patch.object(ws_mod, "get_chat_history",
                      AsyncMock(return_value=fake_rows)), \
         patch.object(ws_mod, "get_profile_summary",
                      AsyncMock(return_value=None)), \
         patch.object(ws_mod, "update_profile_summary", AsyncMock()), \
         patch.object(ws_mod, "call_llm",
                      AsyncMock(return_value=fake_response)):
        status, summary = await ws_mod._compute_profile_summary(
            "u5", min_user_rows=1,
        )
    check("min_user_rows=1 路径 status == regenerated",
          status == "regenerated")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


async def amain():
    await test_compute_skips_when_too_few_user_rows()
    await test_compute_clears_on_empty_history()
    await test_compute_returns_new_summary_on_success()
    await test_compute_suspicious_llm_output_keeps_old_profile()
    await test_compute_min_user_rows_override()


def main():
    test_filter_user_messages_drops_assistant()
    test_filter_user_messages_empty()
    test_filter_user_messages_handles_no_role_attr()
    test_format_user_history_no_role_prefix()
    test_format_user_history_sanitizes_suspicious()
    test_format_user_history_empty_content_skipped()
    test_prompt_text_warns_against_inferring_from_assistant()
    test_prompt_with_old_summary_includes_it()
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
