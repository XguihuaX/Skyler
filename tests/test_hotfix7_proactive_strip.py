"""hotfix-7 — proactive trigger 路径 state_update / 其他 meta tag 漏出 text_chunk
push 的回归测试。

锁三件事:
1. ``_parse_state_update`` 出现在 proactive engine import + 至少 2 处 call
   site(run_trigger + run_wake_call_trigger 各一)
2. ``strip_all_for_tts`` 在每个 text_chunk push 前调（兜底防回归）
3. ``_apply_proactive_state_update`` helper 存在 + 调到 update_character_state
   + push state_update WS 事件
"""
from __future__ import annotations

import os
import re

import pytest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINE_SRC = os.path.join(ROOT, "backend/proactive/engine.py")
WS_SRC = os.path.join(ROOT, "backend/routes/ws.py")


@pytest.fixture(scope="module")
def engine() -> str:
    with open(ENGINE_SRC, encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="module")
def ws() -> str:
    with open(WS_SRC, encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------------------
# Part 1: proactive engine `_parse_state_update` 双挂点
# ---------------------------------------------------------------------------


def test_engine_imports_parse_state_update(engine: str) -> None:
    """``_parse_state_update`` 必须从 chat 模块 import。"""
    assert re.search(
        r"from backend\.agents\.chat import\s*\([^)]*_parse_state_update",
        engine, flags=re.DOTALL,
    ), "engine.py 缺 import _parse_state_update"


def test_engine_parse_state_update_called_at_least_twice(engine: str) -> None:
    """两个 stream 函数(run_trigger + run_wake_call_trigger)各一处。"""
    matches = re.findall(
        r"parsed_state,\s*sentence\s*=\s*_parse_state_update\(sentence\)",
        engine,
    )
    assert len(matches) >= 2, (
        f"_parse_state_update 仅 {len(matches)} 处 call —— 两个 proactive trigger "
        "stream 函数(run_trigger + run_wake_call_trigger)都该挂"
    )


def test_engine_apply_proactive_state_update_helper_exists(engine: str) -> None:
    assert re.search(
        r"async def _apply_proactive_state_update\(",
        engine,
    ), "缺 _apply_proactive_state_update helper"
    # helper 必须调 update_character_state
    assert "update_character_state(" in engine
    # 必须 push state_update 类型 WS 事件
    assert '"type": "state_update"' in engine


def test_engine_state_update_called_before_text_chunk_push(engine: str) -> None:
    """每个 text_chunk push 之前的 N 行内必须有 _parse_state_update 调用。

    防回归：proactive trigger 路径漏挂这个 parser 就是 hotfix-7 的根因。
    """
    # 找两个 push text_chunk 行
    push_locations = [
        m.start() for m in re.finditer(r'"type":\s*"text_chunk"', engine)
    ]
    assert len(push_locations) >= 2, "engine.py 应该有 ≥ 2 处 text_chunk push"
    for push_idx in push_locations:
        # push 之前 800 字符窗口必须出现 _parse_state_update
        window_start = max(0, push_idx - 800)
        window = engine[window_start:push_idx]
        assert "_parse_state_update" in window, (
            f"text_chunk push @ offset {push_idx} 之前 800 字符内没看到 "
            "_parse_state_update 调用 —— proactive 路径漏挂回归"
        )


# ---------------------------------------------------------------------------
# Part 2: 三处 text_chunk push 都套 strip_all_for_tts
# ---------------------------------------------------------------------------


def test_engine_imports_strip_all_for_tts(engine: str) -> None:
    assert "strip_all_for_tts" in engine
    assert re.search(
        r"from backend\.utils\.text_filters import\s+strip_all_for_tts",
        engine,
    ) or re.search(
        r"from backend\.utils\.text_filters import [^)]*strip_all_for_tts",
        engine,
    )


def test_ws_imports_strip_all_for_tts(ws: str) -> None:
    assert "strip_all_for_tts" in ws


def test_text_chunk_pushes_use_final_chunk_after_strip(engine: str, ws: str) -> None:
    """每个 ``"type": "text_chunk", "content": ...`` push 的 content 必须是
    ``final_chunk`` 变量(经 strip_all_for_tts 处理)而非 raw ``sentence``。"""
    combined = engine + "\n" + ws
    # 抓所有 text_chunk content 引用
    matches = re.findall(
        r'"type":\s*"text_chunk"\s*,\s*"content":\s*(\w+)',
        combined,
    )
    assert len(matches) >= 3, (
        f"text_chunk push 仅 {len(matches)} 处 —— 期望 ≥ 3"
        "(ws main + 2 proactive)"
    )
    for varname in matches:
        assert varname == "final_chunk", (
            f"text_chunk push 用 ``content: {varname}`` —— 应该用 "
            "``final_chunk``(经 strip_all_for_tts 兜底剥过的)"
        )


def test_engine_strip_call_count(engine: str) -> None:
    """``strip_all_for_tts(sentence)`` 在 engine 内至少 2 处(两 proactive 路径)。"""
    matches = re.findall(r"strip_all_for_tts\(sentence\)", engine)
    assert len(matches) >= 2


def test_ws_strip_call_in_text_chunk_path(ws: str) -> None:
    """ws.py 主路径 text_chunk push 之前调 strip_all_for_tts。

    用 ``payload = {"type": "text_chunk"`` 锚定真 push 行(跳过模块顶部 docstring
    协议示例里出现的 ``text_chunk`` 字符串)。
    """
    push_loc = ws.find('payload = {"type": "text_chunk"')
    assert push_loc > 0, "找不到真正的 ``payload = {\"type\": \"text_chunk\"...`` 行"
    window = ws[max(0, push_loc - 400):push_loc]
    assert "strip_all_for_tts(sentence)" in window
    assert "final_chunk" in window


# ---------------------------------------------------------------------------
# Part 3: _strip_format_tags 升级
# ---------------------------------------------------------------------------


def test_strip_format_tags_uses_strip_all_for_tts(engine: str) -> None:
    """持久化前 ``_strip_format_tags`` 改用 ``strip_all_for_tts``(完整 5 道
    strip)而不再是早期只剥 emotion/motion/thinking 三档的版本。
    """
    idx = engine.find("def _strip_format_tags")
    assert idx >= 0, "engine 找不到 _strip_format_tags 函数"
    # 拿到下一个顶层 def/async def 之前的所有行作 body
    after = engine[idx:]
    # 第一个匹配下一个顶层 def
    next_def = re.search(r"\n(?:def |async def |class )", after[10:])  # 跳过自己的 def
    body = after[: next_def.start() + 10] if next_def else after
    assert "strip_all_for_tts" in body, (
        "_strip_format_tags 函数体没看到 strip_all_for_tts —— hotfix-7 commit 1 升级丢了"
    )


# ---------------------------------------------------------------------------
# Part 4: behavior smoke (无需真启 stream，直接调 strip_all_for_tts 验语义)
# ---------------------------------------------------------------------------


def test_strip_all_for_tts_drops_state_update_tag() -> None:
    """``strip_all_for_tts('<state_update mood="happy" />早安')`` → '早安'。

    端到端验证 hotfix-7 根本依赖(commit 1 + 2 都假设这个函数能剥 state_update)。
    """
    import sys
    sys.path.insert(0, ROOT)
    from backend.utils.text_filters import strip_all_for_tts
    raw = '<state_update mood="happy" thought="新的一天" />早安呀,快起床啦~'
    out = strip_all_for_tts(raw)
    assert "<state_update" not in out
    assert "mood=" not in out
    assert "早安呀" in out


def test_strip_all_for_tts_drops_all_5_meta_tags() -> None:
    """完整剥 5 道: emotion / thinking / state_update / motion / tool_call。"""
    import sys
    sys.path.insert(0, ROOT)
    from backend.utils.text_filters import strip_all_for_tts
    raw = (
        '<emotion>happy</emotion>'
        '<thinking>内心独白</thinking>'
        '<state_update mood="happy" />'
        '<motion>害羞</motion>'
        '<tool_call>{"name":"x"}</tool_call>'
        '正文内容'
    )
    out = strip_all_for_tts(raw)
    for tag_start in ("<emotion", "<thinking", "<state_update", "<motion", "<tool_call"):
        assert tag_start not in out, f"strip_all_for_tts 漏剥 {tag_start}"
    assert "正文内容" in out
