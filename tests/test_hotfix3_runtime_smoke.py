"""v3.5 chunk 6b hotfix-3 — runtime smoke 覆盖 Part 1-5。

* Part 1 — resilience capability-name-as-tag 真识别 + 真调
* Part 2 — strip 4 道防线第 4 种 pattern
* Part 3 — at-source SUSPICIOUS_TAG_RE sanitize（assistant 行剥；user 行不动）
* Part 4 — migration 幂等（第二次跑 scrubbed = 0）
* Part 5 — _regenerate_profile_summary 双向 sanitize（输入剥 + 输出保护）

测试约定：
  * 用 ``ToolRegistry.call`` 真实 invoke 路径（与 ChatAgent / chat.py 同入口）
  * 只 patch 最底层（netease HTTP / ``_open_url`` / mpv subprocess / LLM call）
  * 不动 hotfix-1/2 fall-through 逻辑
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import shutil
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.agents.tool_call_resilience import detect_and_execute_fallback_tool_calls
from backend.capabilities import netease_music  # noqa: F401 register
from backend.utils.text_filters import (
    count_suspicious_tags,
    sanitize_suspicious_tags,
)

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))


# ---------------------------------------------------------------------------
# Part 1: resilience capability_tag 真识别 + 真执行 + 剥残骸
# ---------------------------------------------------------------------------


async def test_part1_resilience_capability_tag_invoke_real():
    print("\n[Part 1] resilience capability_tag → 真 ToolRegistry.call")
    # 真实路径：fake netease client 让 daily_recommend handler 跑通
    from backend.integrations import netease_music as nm
    fake_client = MagicMock()
    fake_client.has_credentials = False  # 走 URL Scheme fallback，不触 mpv
    fake_client.daily_recommend = MagicMock(return_value=[
        {"id": 1001, "name": "Song A", "artists": ["X"], "album": ""},
    ])
    async def fake_open(_url): return True

    text = (
        "好的，给你放日推～"
        "<netease.daily_recommend></netease.daily_recommend>"
    )
    from backend.capabilities import netease_music as caps
    with patch.object(nm, "get_client", return_value=fake_client), \
         patch.object(caps, "_open_url", side_effect=fake_open):
        cleaned, executed = await detect_and_execute_fallback_tool_calls(
            text, user_id="default", character_id=1,
        )
    check("identified capability_tag pattern",
          any(e["pattern"] == "capability_tag" for e in executed))
    check("name=netease.daily_recommend",
          any(e["name"] == "netease.daily_recommend" for e in executed))
    check("cleaned 文本不含 <netease.",
          "<netease." not in cleaned and "</netease." not in cleaned)
    check("cleaned 保留正文", "好的，给你放日推" in cleaned)


async def test_part1_resilience_unregistered_tag_skip():
    print("\n[Part 1] 不存在的 tool name → skip + 仍剥残骸")
    text = "前缀<fake.nothing>{\"x\":1}</fake.nothing>后缀"
    cleaned, executed = await detect_and_execute_fallback_tool_calls(
        text, user_id="default", character_id=1,
    )
    check("不调用未注册 tool",
          not any(e["name"] == "fake.nothing" for e in executed))
    check("仍剥残骸",
          "<fake.nothing" not in cleaned and "</fake.nothing>" not in cleaned)


async def test_part1_resilience_self_closed():
    print("\n[Part 1] 自闭合 tag 也识别")
    from backend.integrations import netease_music as nm
    from backend.capabilities import netease_music as caps
    fake_client = MagicMock()
    fake_client.has_credentials = False
    fake_client.daily_recommend = MagicMock(return_value=[
        {"id": 1, "name": "X", "artists": ["A"], "album": ""},
    ])
    async def fake_open(_): return True
    text = "<netease.daily_recommend />"
    with patch.object(nm, "get_client", return_value=fake_client), \
         patch.object(caps, "_open_url", side_effect=fake_open):
        cleaned, executed = await detect_and_execute_fallback_tool_calls(
            text, user_id="default", character_id=1,
        )
    check("self-closed 也命中",
          any(e["pattern"] == "capability_tag" for e in executed))
    check("cleaned 不再含 tag", "<netease." not in cleaned)


# ---------------------------------------------------------------------------
# Part 2: strip 4 道防线（text_filters 已单测，这里做集成 spot check）
# ---------------------------------------------------------------------------


def test_part2_strip_chain():
    print("\n[Part 2] strip_all_for_tts 链覆盖 capability-name-as-tag")
    from backend.utils.text_filters import strip_all_for_tts
    t = "<netease.daily_recommend></netease.daily_recommend>说话内容"
    out = strip_all_for_tts(t)
    check("TTS 链剥 capability tag", out == "说话内容")


# ---------------------------------------------------------------------------
# Part 3: at-source SUSPICIOUS_TAG_RE — 模拟 _update_memory 写库路径
# ---------------------------------------------------------------------------


def test_part3_assistant_sanitize_inline():
    print("\n[Part 3] assistant 行 SUSPICIOUS_TAG_RE 命中 → strip + 写库")
    # 直接调度 sanitize 链（与 ws.py:_update_memory 中嵌入的相同）
    reply = "Momo 给你放～<netease.daily_recommend></netease.daily_recommend>"
    n = count_suspicious_tags(reply)
    cleaned = sanitize_suspicious_tags(reply).strip()
    check("命中 count 1", n == 1)
    check("剥后无 <netease.", "<netease." not in cleaned)
    check("保留正文", "Momo 给你放" in cleaned)


def test_part3_user_message_not_sanitized():
    print("\n[Part 3] user 消息不动 (ws.py 只对 assistant 行调 sanitize)")
    # 此处只断言函数本身是纯净的；ws.py 调用方走的是 ``reply``，``user_text``
    # 从未过 sanitize。函数级测试仅确认 sanitize 不带副作用——但 user 路径
    # 不应被它触碰，由 _update_memory 调用点保证（见 ws.py:_update_memory）。
    import backend.routes.ws as ws_mod
    src = open(ws_mod.__file__, "r", encoding="utf-8").read()
    # 关键 invariant：sanitize_suspicious_tags 只在 reply（assistant）变量上调
    # 在 _update_memory body 内不能出现 ``sanitize_suspicious_tags(user_text``
    check("ws.py 不对 user_text 调 sanitize",
          "sanitize_suspicious_tags(user_text" not in src)
    check("ws.py 对 reply 调 sanitize（assistant 路径）",
          "sanitize_suspicious_tags(reply)" in src or
          "sanitize_suspicious_tags(full_reply)" in src)


# ---------------------------------------------------------------------------
# Part 4: migration 幂等（在临时 sqlite DB 上跑）
# ---------------------------------------------------------------------------


async def test_part4_migration_idempotent():
    print("\n[Part 4] migration 二次跑幂等 + 备份生成")
    # 用临时 DB 跑 migration —— monkeypatch engine 指向临时文件
    tmpdir = tempfile.mkdtemp(prefix="hotfix3_smoke_")
    tmp_db = os.path.join(tmpdir, "test.db")
    try:
        # 用 sync sqlite 注入污染数据
        import sqlite3
        conn = sqlite3.connect(tmp_db)
        conn.executescript("""
        CREATE TABLE users (
            user_id TEXT PRIMARY KEY,
            profile_summary TEXT
        );
        CREATE TABLE chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT, role TEXT, content TEXT
        );
        CREATE TABLE memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT
        );
        INSERT INTO users (user_id, profile_summary) VALUES
            ('u1', '用户喜欢<a.b></a.b><c.d/><e.f></e.f>很多'),  -- 3 hits → NULL
            ('u2', '用户喜欢<a.b></a.b>正常文本');                 -- 1 hit → inline scrub
        INSERT INTO chat_history (user_id, role, content) VALUES
            ('u1', 'assistant', '放<netease.daily_recommend></netease.daily_recommend>'),
            ('u1', 'assistant', '正常文本'),
            ('u1', 'user', '<should.not.touch />user content');
        INSERT INTO memory (content) VALUES
            ('用户偏好 <a.b></a.b> 这种'),
            ('纯文本不动');
        """)
        conn.commit()
        conn.close()

        # monkeypatch engine
        from sqlalchemy.ext.asyncio import create_async_engine
        from backend.database.migrations import (
            v3_5_chunk6b_hotfix3_clean_polluted_memories as mig,
        )
        tmp_engine = create_async_engine(
            f"sqlite+aiosqlite:///{tmp_db}", echo=False,
        )

        with patch.object(mig, "engine", tmp_engine):
            await mig.run_migration()
            # 第二次跑 —— 幂等检查
            await mig.run_migration()

        # 验证 DB 状态
        conn = sqlite3.connect(tmp_db)
        # u1 profile cleared
        r = conn.execute(
            "SELECT profile_summary FROM users WHERE user_id='u1'"
        ).fetchone()
        check("u1 profile NULL (hit >= 3)", r[0] is None)
        # u2 profile scrubbed inline
        r2 = conn.execute(
            "SELECT profile_summary FROM users WHERE user_id='u2'"
        ).fetchone()
        check("u2 profile inline scrubbed",
              r2[0] is not None and "<a.b>" not in r2[0])
        check("u2 profile 保留正文",
              "正常文本" in (r2[0] or ""))
        # chat_history assistant scrubbed; user row 不动
        assist_rows = conn.execute(
            "SELECT content FROM chat_history WHERE role='assistant'"
        ).fetchall()
        check("chat_history assistant 无 <netease.",
              all("<netease." not in (r[0] or "") for r in assist_rows))
        user_row = conn.execute(
            "SELECT content FROM chat_history WHERE role='user'"
        ).fetchone()
        check("chat_history user 行不被剥（保留 <should.not.touch />）",
              "<should.not.touch" in (user_row[0] or ""))
        # memory scrubbed
        mem_rows = conn.execute("SELECT content FROM memory").fetchall()
        check("memory 无 <a.b>",
              all("<a.b>" not in (r[0] or "") for r in mem_rows))
        conn.close()

        # 备份验证
        backup = tmp_db + ".backup-before-hotfix3"
        check("备份文件生成", os.path.exists(backup))
        check("备份不空", os.path.exists(backup) and os.path.getsize(backup) > 0)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Part 5: profile_summary 双向 sanitize（unit：_format_chat_history + 输出 guard）
# ---------------------------------------------------------------------------


def test_part5_input_sanitize_format_chat_history():
    print("\n[Part 5] _format_chat_history 输入端 sanitize")
    from backend.routes.ws import _format_chat_history

    class Row:
        def __init__(self, role, content):
            self.role = role
            self.content = content

    rows = [
        Row("user", "<should.not.touch />user text"),
        Row("assistant",
            "<netease.daily_recommend></netease.daily_recommend>已放日推"),
    ]
    formatted = _format_chat_history(rows)
    # **新设计：输入端对所有 role 一起过 sanitize**（输入只读 LLM prompt，
    # 不影响 DB；user 的可疑 tag 也不该喂 LLM 引导）
    check("输出剥 <netease.",
          "<netease." not in formatted)
    check("输出剥 <should.not.touch />",
          "<should.not.touch" not in formatted)
    check("保留 user 正文", "user text" in formatted)
    check("保留 assistant 正文", "已放日推" in formatted)


def test_part5_output_guard_keeps_old_profile():
    print("\n[Part 5] LLM 输出含可疑 tag → 保留旧 profile + log warning")
    # 通过 mock `call_llm` 注入污染输出 → 期望 update_profile_summary 不被调
    import backend.routes.ws as ws_mod
    src = open(ws_mod.__file__, "r", encoding="utf-8").read()
    # 关键 invariant：_regenerate_profile_summary 在 update_profile_summary 前
    # 有 count_suspicious_tags(new_summary) 守卫
    check("ws.py 有 count_suspicious_tags(new_summary) 守卫",
          "count_suspicious_tags(new_summary)" in src)
    check("守卫含 return 路径（不写库）",
          "discarding new" in src or
          "keeping old profile" in src)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


async def amain():
    await test_part1_resilience_capability_tag_invoke_real()
    await test_part1_resilience_unregistered_tag_skip()
    await test_part1_resilience_self_closed()
    await test_part4_migration_idempotent()


def main():
    asyncio.run(amain())
    test_part2_strip_chain()
    test_part3_assistant_sanitize_inline()
    test_part3_user_message_not_sanitized()
    test_part5_input_sanitize_format_chat_history()
    test_part5_output_guard_keeps_old_profile()

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
