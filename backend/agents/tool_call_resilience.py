"""v3-G chunk 4 部分 A — 通用 Tool Call Resilience Layer。

# 背景

Qwen3.6（DashScope OpenAI-compatible 通道）在 tool calling 时偶发把 tool
调用以**非 OpenAI function_call 协议**的形式输出到 ``delta.content`` 文本流：

* ``<tool_call>{"name": "X", "arguments": {...}}</tool_call>``    Qwen 内部 XML
* ``<function_calls><invoke name="X"><parameter name="K">V</parameter></invoke></function_calls>``  Anthropic 风格
* `````json\n{"name": "X", "arguments": ...}\n`````  Markdown JSON 块

ChatAgent 的主循环按 OpenAI 协议看 ``finish_reason='tool_calls'`` 决定执
行——这些 fallback 形式跑到 ``delta.content``，ChatAgent 完全意识不到，
capability 不会真被调，LLM 自欺已完成。chunk 2.6 footgun 4（snooze 不真触
发）+ chunk 3 footgun 7（clipboard.translate 不真翻）都是这条。**v3 封盘
前必修**。

# 设计

把 fallback 检测做成**纯函数**模块（``detect_and_execute_fallback_tool_calls``），
ws.py 在 stream 主循环结束、把 reply 写 chat_history 前调用一次：

  1. 用 3 条 regex 扫文本，按顺序匹配 + 容错 JSON parse 出 ``(name, args)``
  2. ToolRegistry 有该 name 才执行（防 LLM 编造 name）
  3. 调 ``ToolRegistry.call`` 拿结果（capability 副作用真生效）
  4. log fallback path 用于 telemetry：``[tool_resilience] fallback=...``
  5. 从原文剥掉对应 substring（防 XML 残骸进 chat_history / TTS）

返回 ``(cleaned_text, executed_list)``。caller 用 cleaned_text 持久化。

# 不做的事

* **不喂 tool result 回 LLM** 让它续写：MVP 简化。capability 副作用已生效，
  LLM 自欺"已完成"在用户视角无伤——用户会看到"好的 N 分钟后再叫你～"
  + 5 分钟后真触发 wake_call。增量价值小，下次再做。
* **不阻断主流程**：任何子步骤异常吞 + log，永远返回原文 + 已执行的部分，
  不抛错。
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Fallback patterns（按特异性顺序：最严格的先扫，markdown_json 最后兜底）
# ---------------------------------------------------------------------------

#: Qwen 内部 XML：``<tool_call>{json}</tool_call>``
_QWEN_XML_RE = re.compile(
    r"<tool_call>\s*(\{.*?\})\s*</tool_call>",
    re.DOTALL | re.IGNORECASE,
)

#: Anthropic invoke 风格——整段：
#:   ``<function_calls><invoke name="X">...</invoke></function_calls>``
_ANTHROPIC_INVOKE_BLOCK_RE = re.compile(
    r"<function_calls>\s*"
    r"<invoke\s+name\s*=\s*[\"']([^\"']+)[\"']\s*>"
    r"(.*?)"
    r"</invoke>\s*</function_calls>",
    re.DOTALL | re.IGNORECASE,
)
#: Anthropic invoke 风格——内部参数：``<parameter name="K">V</parameter>``
_ANTHROPIC_PARAM_RE = re.compile(
    r"<parameter\s+name\s*=\s*[\"']([^\"']+)[\"']\s*>(.*?)</parameter>",
    re.DOTALL | re.IGNORECASE,
)

#: Markdown JSON：```` ```json\n{"name":"X","arguments":...}\n``` ````
#: 故意宽松（最后扫，已被前两条剥掉的不会再命中）。要求 JSON 含 ``"name"``
#: 字段才算 tool 调用——防止用户单纯 paste 的 JSON 被误判。
_MARKDOWN_JSON_RE = re.compile(
    r"```json\s*(\{[^`]*?\"name\"\s*:\s*\"[^\"]+\"[^`]*?\})\s*```",
    re.DOTALL | re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

async def detect_and_execute_fallback_tool_calls(
    stream_text: str,
    *,
    user_id: str,
    character_id: Optional[int] = None,
) -> Tuple[str, list[dict]]:
    """扫 ``stream_text`` 找 fallback tool 调用，执行 + 剥离。

    Args:
        stream_text:    LLM 这一轮全部 ``delta.content`` 拼起来的文本。
        user_id:        ChatAgent 注入的会话级 user_id。
        character_id:   当前 character_id（``character.set_activity`` /
                        ``character.get_state`` 等 capability 需要）。

    Returns:
        ``(cleaned_text, executed_list)``：
        * ``cleaned_text``  剥掉所有 fallback tool call 标签的文本（写
          chat_history / TTS preprocessor 都用这版）
        * ``executed_list`` ``[{"pattern": str, "name": str, "args": dict,
          "result": Any}, ...]``，按命中顺序

    任何子步骤异常吞 + log，不抛。即便 ToolRegistry 不可用，仍返 cleaned_text
    + 部分 executed_list。
    """
    # 延迟 import 避免循环（routes.ws → agents.chat → agents.tool_call_resilience）
    from backend.tools.registry import ToolRegistry, _tools as _tool_registry_dict

    cleaned = stream_text
    executed: list[dict] = []
    seen_spans: list[tuple[int, int]] = []  # 已剥位置区间，markdown_json 兜底跳过

    # ─── 1. Qwen XML ────────────────────────────────────────────────────────
    for m in _QWEN_XML_RE.finditer(stream_text):
        span = m.span()
        try:
            payload = json.loads(m.group(1))
            name = payload.get("name")
            args = payload.get("arguments")
            if isinstance(args, str):
                # 部分模型把 arguments 二次 JSON 字符串化，再 parse 一次
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            if not isinstance(args, dict):
                args = {}
            if not name or not isinstance(name, str):
                continue
            if name not in _tool_registry_dict:
                logger.info(
                    "[tool_resilience] qwen_xml: tool %r not registered, skipping",
                    name,
                )
                continue
            try:
                result = await _call_with_context(
                    ToolRegistry, name, args, user_id=user_id, character_id=character_id,
                )
            except Exception as exc:
                logger.warning(
                    "[tool_resilience] qwen_xml exec failed name=%s: %s",
                    name, exc,
                )
                result = {"error": str(exc)}
            executed.append({
                "pattern": "qwen_xml", "name": name, "args": args, "result": result,
            })
            seen_spans.append(span)
            logger.info(
                "[tool_resilience] fallback=qwen_xml tool=%s args=%s",
                name, json.dumps(args, ensure_ascii=False)[:200],
            )
        except Exception as exc:
            logger.warning("[tool_resilience] qwen_xml parse failed: %s", exc)

    # 剥所有 qwen_xml 标签（无论是否成功执行——已是非业务文本，不该进 chat_history）
    cleaned = _QWEN_XML_RE.sub("", cleaned)

    # ─── 2. Anthropic invoke ───────────────────────────────────────────────
    for m in _ANTHROPIC_INVOKE_BLOCK_RE.finditer(stream_text):
        try:
            name = m.group(1)
            params_str = m.group(2) or ""
            args: dict[str, Any] = {}
            for pm in _ANTHROPIC_PARAM_RE.finditer(params_str):
                key = pm.group(1)
                raw_val = (pm.group(2) or "").strip()
                args[key] = _coerce_param_value(raw_val)
            if name not in _tool_registry_dict:
                logger.info(
                    "[tool_resilience] anthropic_invoke: tool %r not registered, skipping",
                    name,
                )
                continue
            try:
                result = await _call_with_context(
                    ToolRegistry, name, args, user_id=user_id, character_id=character_id,
                )
            except Exception as exc:
                logger.warning(
                    "[tool_resilience] anthropic_invoke exec failed name=%s: %s",
                    name, exc,
                )
                result = {"error": str(exc)}
            executed.append({
                "pattern": "anthropic_invoke", "name": name, "args": args, "result": result,
            })
            logger.info(
                "[tool_resilience] fallback=anthropic_invoke tool=%s args=%s",
                name, json.dumps(args, ensure_ascii=False)[:200],
            )
        except Exception as exc:
            logger.warning("[tool_resilience] anthropic_invoke parse failed: %s", exc)

    cleaned = _ANTHROPIC_INVOKE_BLOCK_RE.sub("", cleaned)

    # ─── 3. Markdown JSON 兜底（最宽松，前两条剥过的不会再命中） ────────
    for m in _MARKDOWN_JSON_RE.finditer(cleaned):
        try:
            payload = json.loads(m.group(1))
            name = payload.get("name")
            args = payload.get("arguments") or payload.get("args") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            if not isinstance(args, dict) or not name or not isinstance(name, str):
                continue
            if name not in _tool_registry_dict:
                continue
            try:
                result = await _call_with_context(
                    ToolRegistry, name, args, user_id=user_id, character_id=character_id,
                )
            except Exception as exc:
                logger.warning(
                    "[tool_resilience] markdown_json exec failed name=%s: %s",
                    name, exc,
                )
                result = {"error": str(exc)}
            executed.append({
                "pattern": "markdown_json", "name": name, "args": args, "result": result,
            })
            logger.info(
                "[tool_resilience] fallback=markdown_json tool=%s args=%s",
                name, json.dumps(args, ensure_ascii=False)[:200],
            )
        except Exception as exc:
            logger.warning("[tool_resilience] markdown_json parse failed: %s", exc)

    cleaned = _MARKDOWN_JSON_RE.sub("", cleaned)
    cleaned = cleaned.strip()
    return cleaned, executed


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

async def _call_with_context(
    registry, name: str, args: dict, *, user_id: str, character_id: Optional[int],
) -> Any:
    """``ToolRegistry.call`` 包装：注入 user_id + character_id。

    防 LLM 在 fallback 形式里**主动**传 user_id 覆盖会话级注入；character_id
    只在 args 里没有时注入，让 LLM 显式指定的优先（极少见，但合理）。
    """
    args = dict(args)
    args.pop("user_id", None)
    if character_id is not None and "character_id" not in args:
        args["character_id"] = character_id
    return await registry.call(name, user_id=user_id, **args)


def _coerce_param_value(raw: str) -> Any:
    """Anthropic ``<parameter>`` value 文本 → Python 原值。

    尝试顺序：
      1. ``"true"`` / ``"false"`` / ``"null"`` （大小写不敏感）
      2. int → float
      3. JSON parse（数组 / 嵌套对象）
      4. 否则原字符串
    """
    if raw is None:
        return None
    s = raw.strip()
    if not s:
        return ""
    low = s.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    if low == "null":
        return None
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    if s[0] in ("[", "{"):
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            pass
    return s


__all__ = [
    "detect_and_execute_fallback_tool_calls",
]
