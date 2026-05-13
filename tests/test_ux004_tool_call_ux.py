"""UX-004 — tool 调用过渡语 + WS event 回归。

Part A: ``_TOOL_BEHAVIOR_BLOCK`` 注入到 system prompt
Part B: ChatAgent.stream() yield 类型 ``Union[str, dict]`` — tool_use_start
        / tool_use_done 在 _execute_tool 前后正确 emit
Part C: 注入位置不冲突 chunk 11 profile / chunk 14 activity / memory recall
"""
from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.agents.chat import (
    ChatAgent,
    _TOOL_BEHAVIOR_BLOCK,
    _build_messages,
)


# ===========================================================================
# Part A: prompt 注入
# ===========================================================================


async def test_tool_behavior_block_constant_format() -> None:
    """常量字符串本身的形状检查 — 防有人改坏 prompt 内容。"""
    block = _TOOL_BEHAVIOR_BLOCK
    # heading
    assert "【工具调用行为】" in block
    # 关键概念短语
    assert "过渡语" in block
    assert "6-15 字" in block
    # 至少 3 个示例
    for ex in ('"嗯,让我看看"', '"等我查一下"', '"稍等,我看看日历"'):
        assert ex in block, f"prompt 示例丢失:{ex}"
    # 边界(绝对避免)
    assert "silent" in block.lower() or "silent" in block
    assert "绝对避免" in block


async def test_system_prompt_contains_tool_behavior_block() -> None:
    msgs = await _build_messages(
        "default", "今天日历有什么", None,
        character_id=None, extra_system=None, skip_short_term=True,
    )
    assert len(msgs) >= 1 and msgs[0]["role"] == "system"
    sys_prompt = msgs[0]["content"]
    assert "【工具调用行为】" in sys_prompt
    # 块内容真注入(不是空 heading)
    assert "等我查一下" in sys_prompt


async def test_tool_behavior_injected_before_profile_section() -> None:
    """注入顺序:persona 之后,profile(``已知用户：``)/ activity
    (``## 用户今日活动``)/ memory recall(``【相关长期记忆】``)之前。

    head_parts 是输出格式约束层;profile/activity/memory 是语义上下文层。
    """
    msgs = await _build_messages(
        "default", "今天怎么样", None,
        character_id=None, extra_system=None, skip_short_term=True,
    )
    sys_prompt = msgs[0]["content"]
    tool_idx = sys_prompt.find("【工具调用行为】")
    assert tool_idx > 0, "tool behavior block missing"

    # profile (chunk 11) 应在 tool_behavior 之后
    profile_idx = sys_prompt.find("已知用户")
    if profile_idx >= 0:
        assert tool_idx < profile_idx, (
            f"工具调用行为({tool_idx}) 必须在 profile({profile_idx}) 之前"
        )

    # activity (chunk 14) 应在 tool_behavior 之后(如果今日有数据)
    activity_idx = sys_prompt.find("## 用户今日活动")
    if activity_idx >= 0:
        assert tool_idx < activity_idx, (
            f"工具调用行为({tool_idx}) 必须在 activity({activity_idx}) 之前"
        )

    # long-term memory recall 应在 tool_behavior 之后
    memory_idx = sys_prompt.find("【相关长期记忆】")
    if memory_idx >= 0:
        assert tool_idx < memory_idx


# ===========================================================================
# Part B: ChatAgent.stream() yield typed events
# ===========================================================================


async def test_chat_agent_yields_tool_events_around_exec() -> None:
    """mock LiteLLM 流强制 emit tool_call → 验 stream() yield 顺序:
    ``tool_use_start dict → tool_use_done dict → ... 最终 text``。

    用 fake stream + fake _execute_tool 绕开真 LLM / 真 capability。
    """
    agent = ChatAgent()

    # Fake LiteLLM stream — 第 1 轮 emit tool_call,第 2 轮 emit 文本 + finish
    # 用 acompletion 返回的 wrapper.stream 接口替身
    from types import SimpleNamespace as NS

    # Round 1: 一个 tool_call delta + finish_reason="tool_calls"
    round1 = [
        NS(choices=[NS(delta=NS(
            content=None,
            tool_calls=[NS(
                index=0,
                id="call_1",
                function=NS(name="calendar.today_events", arguments="{}"),
            )],
        ), finish_reason=None)]),
        NS(choices=[NS(delta=NS(content=None, tool_calls=None),
                       finish_reason="tool_calls")]),
    ]
    # Round 2: 文本 chunks + finish_reason="stop"
    round2 = [
        NS(choices=[NS(delta=NS(content="今天有 2 个日程。",
                                 tool_calls=None), finish_reason=None)]),
        NS(choices=[NS(delta=NS(content=None, tool_calls=None),
                       finish_reason="stop")]),
    ]
    rounds = [round1, round2]

    class _FakeStream:
        def __init__(self, chunks):
            self._chunks = chunks
            self._it = iter(chunks)
        def __aiter__(self):
            return self
        async def __anext__(self):
            try:
                return next(self._it)
            except StopIteration:
                raise StopAsyncIteration

    async def _fake_acompletion(*args, **kwargs):
        return _FakeStream(rounds.pop(0))

    async def _fake_execute_tool(user_id, name, raw_args, **kw):
        return {"available": True, "events": []}

    yielded: list = []
    with patch("backend.agents.chat.call_llm", side_effect=_fake_acompletion), \
         patch("backend.agents.chat._execute_tool", side_effect=_fake_execute_tool), \
         patch("backend.agents.chat._build_messages",
               AsyncMock(return_value=[{"role": "system", "content": "x"}])):
        async for item in agent.stream({
            "payload": {"user_id": "default", "text": "今天日历有什么",
                        "context": {}},
        }):
            yielded.append(item)

    # 第一个 yield 是 dict(tool_use_start),第二个是 dict(tool_use_done),
    # 之后是文本 chunks(可能 1 个或多个)
    dict_items = [x for x in yielded if isinstance(x, dict)]
    assert len(dict_items) == 2, f"expected 2 tool events, got {len(dict_items)}: {dict_items}"
    assert dict_items[0]["type"] == "tool_use_start"
    assert dict_items[0]["tool_name"] == "calendar.today_events"
    assert dict_items[1]["type"] == "tool_use_done"
    assert dict_items[1]["tool_name"] == "calendar.today_events"
    assert "duration_ms" in dict_items[1]
    assert isinstance(dict_items[1]["duration_ms"], int)
    assert dict_items[1]["duration_ms"] >= 0

    # tool_use_start 必须在 tool_use_done 之前 yield
    start_pos = next(i for i, x in enumerate(yielded)
                      if isinstance(x, dict) and x.get("type") == "tool_use_start")
    done_pos = next(i for i, x in enumerate(yielded)
                     if isinstance(x, dict) and x.get("type") == "tool_use_done")
    assert start_pos < done_pos


async def test_chat_agent_yields_no_tool_events_when_no_tool_call() -> None:
    """LLM 单轮直接出文本(无 tool_call)→ 不应 emit 任何 dict event。"""
    agent = ChatAgent()
    from types import SimpleNamespace as NS

    rounds = [[
        NS(choices=[NS(delta=NS(content="你好。", tool_calls=None),
                       finish_reason="stop")]),
    ]]

    class _FakeStream:
        def __init__(self, chunks):
            self._it = iter(chunks)
        def __aiter__(self):
            return self
        async def __anext__(self):
            try:
                return next(self._it)
            except StopIteration:
                raise StopAsyncIteration

    async def _fake_acompletion(*args, **kwargs):
        return _FakeStream(rounds.pop(0))

    yielded: list = []
    with patch("backend.agents.chat.call_llm", side_effect=_fake_acompletion), \
         patch("backend.agents.chat._build_messages",
               AsyncMock(return_value=[{"role": "system", "content": "x"}])):
        async for item in agent.stream({
            "payload": {"user_id": "default", "text": "你好",
                        "context": {}},
        }):
            yielded.append(item)

    dict_items = [x for x in yielded if isinstance(x, dict)]
    assert dict_items == []
