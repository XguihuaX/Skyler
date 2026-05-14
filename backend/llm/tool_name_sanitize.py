"""Bugfix-3.2.9 — sanitize tool function names for strict LLM schemas.

OpenAI / DeepSeek 严格按 schema 校验 ``tools[*].function.name``:
要求匹配 ``^[a-zA-Z0-9_-]+$``。Qwen / Anthropic 宽松接受非法字符。

Skyler 的 capability 命名约定带 ``.``(eg ``clipboard.summarize`` /
``apple_calendar.create_event``)→ DeepSeek/OpenAI 直接拒掉:
``Invalid 'tools[N].function.name': string does not match pattern.``

本 module 提供:
  - ``sanitize_tool_name(name)``     单名转换 (`.` `:` `/` 中文 → `_`)
  - ``sanitize_tools_for_llm(tools)`` 批量转换 + 返回 reverse_map
    (sanitized → original),让 caller 把 LLM 回来的 sanitized name
    映射回 ToolRegistry 的 original key。

设计要点:
  * **纯函数**,无 I/O 副作用,易测试
  * **幂等**: 已合规 name 不变(`'foo_bar'` → `'foo_bar'`)
  * 对所有 vendor 都跑(Qwen/Anthropic 也接受 sanitized → 无回归)
"""
from __future__ import annotations

import re
from typing import Iterable

# OpenAI / DeepSeek tool name pattern: ^[a-zA-Z0-9_-]+$
# 替换为 _,后续做开头数字防护 + 空串兜底。
_INVALID = re.compile(r"[^a-zA-Z0-9_-]")


def sanitize_tool_name(name: str) -> str:
    """把任意字符串转成合规 tool name。

    规则:
      - 非 ``[a-zA-Z0-9_-]`` 字符替换为 ``_`` (包括 ``.`` ``:`` ``/`` 中文 等)
      - 开头若是数字, 前缀 ``_`` (防 schema `^[a-zA-Z_]` 风格的二级校验)
      - 空串 / 全替换光的兜成 ``_unnamed``
    """
    if not name:
        return "_unnamed"
    s = _INVALID.sub("_", name)
    if not s:
        return "_unnamed"
    if s[0].isdigit():
        s = "_" + s
    return s


def sanitize_tools_for_llm(
    tools: Iterable[dict],
) -> tuple[list[dict], dict[str, str]]:
    """批量 sanitize tool schema list 并构造 reverse map。

    Args:
        tools: OpenAI function-calling 格式的 tool schema 列表。
               每项形如 ``{"type": "function", "function": {"name": ..., ...}}``。

    Returns:
        ``(new_tools, reverse_map)``:
          - ``new_tools``: 新 list, ``function.name`` 已 sanitize (原 list 不动)
          - ``reverse_map``: ``{sanitized: original}``。仅含真正被改过的 name —
            合规 name 不进 map,caller 可用 ``map.get(name, name)`` 兜底。

    Caller 用法 (chat.py)::

        san_tools, rev = sanitize_tools_for_llm(_get_all_tools())
        ... = await call_llm(..., tools=san_tools)
        # LLM 回来 tool_call.name → 真名:
        original = rev.get(tool_call.name, tool_call.name)
        await _execute_tool(user_id, original, args, ...)
    """
    out: list[dict] = []
    reverse_map: dict[str, str] = {}
    for t in tools:
        new_t = dict(t)
        fn = new_t.get("function")
        if isinstance(fn, dict) and "name" in fn:
            new_fn = dict(fn)
            orig = new_fn["name"]
            san = sanitize_tool_name(orig)
            if san != orig:
                # 若两个不同 orig sanitize 后冲突(理论极少, 如 'foo.bar' vs
                # 'foo:bar' 都 → 'foo_bar'), 先到先得 — 后者会被静默覆盖。
                # 实际 capability 命名约定不会撞, 真撞了 dispatch 也只是错
                # 路由,不会 schema 失败。
                new_fn["name"] = san
                reverse_map[san] = orig
            new_t["function"] = new_fn
        out.append(new_t)
    return out, reverse_map
