"""INVESTIGATION-3 第一刀 — token observation probe (read-only).

在 ChatAgent.stream() L1647 LLM 调用前触发,**纯观测**:
  - 计算本次请求各注入源 token 数
  - 写一行 JSON 到 ``logs/token_probe.jsonl``
  - 任何异常 silent 吞 + debug log,**绝不阻塞** LLM 调用

不改业务逻辑;不读 DB;不额外调 LLM/向量;只对已组装好的 ``messages`` +
``tools`` 做字符串解析 + tokenize。

字段分解策略:
  - ``tools_schema`` ← 直接 tok(san_tools)
  - ``summary`` ← scan messages,找首个 system + content 起头 "【过往对话摘要"
  - ``short_term`` ← 求和 messages[1..-2] 中 role∈{user,assistant} 的 content token
  - ``current_text`` ← tok(messages[-1].content)
  - ``system_combined`` ← tok(messages[0].content)(Jinja 5-layer 整体)
  - ``layer_a / layer_b / layer_c / layer_d`` ← 用 layer header 标记切片 system 文本
  - ``addendum`` ← Layer B 内 "你有以下 tool 可用" 标记后段
  - ``persona / character_state`` ← Layer C 内 "[当前状态]" header 前 / 后
  - ``user_profile / activity / long_memory_top5`` ← Layer D 内 "用户画像:" /
    "今日活动:" / "长期记忆(Top 5):" sub-marker 切片
  - ``total`` ← tools + system_combined + summary + short_term + current_text

Marker 解析失败(模板措辞变化等)→ 字段=0,但行仍写出便于事后看是否有变化。
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Any, List, Optional

logger = logging.getLogger(__name__)

#: tokenizer 与项目 default_model 对齐(litellm.token_counter 内部对 Qwen 走
#: cl100k_base fallback,与上一轮 INVESTIGATION-2 测量一致)。
_PROBE_MODEL = "qwen3.6-max-preview"

#: 落盘路径相对仓库根 cwd
_PROBE_PATH_REL = os.path.join("logs", "token_probe.jsonl")


def _path() -> str:
    return os.path.join(os.getcwd(), _PROBE_PATH_REL)


def _tok(text: Any) -> int:
    """Best-effort token count via litellm.token_counter; -1 on failure."""
    if text is None or text == "":
        return 0
    if isinstance(text, (list, dict)):
        text = json.dumps(text, ensure_ascii=False)
    try:
        import litellm
        return litellm.token_counter(model=_PROBE_MODEL, text=str(text))
    except Exception:
        return -1


# Jinja 模板的层级 header(对应 backend/agents/prompt/templates/*.j2)
_LAYER_A_HEADER = "[输出格式规范"
_LAYER_B_HEADER = "[本轮模式"
_LAYER_C_HEADER = "[你的角色]"
_LAYER_D_HEADER = "[上下文信息"


def _split_system_layers(system_text: str) -> dict:
    """切 system_prompt 为 layer A/B/C/D 文本块。Marker 缺失 → 该 layer = ""。"""
    out = {"layer_a": "", "layer_b": "", "layer_c": "", "layer_d": ""}
    markers = [
        ("layer_a", _LAYER_A_HEADER),
        ("layer_b", _LAYER_B_HEADER),
        ("layer_c", _LAYER_C_HEADER),
        ("layer_d", _LAYER_D_HEADER),
    ]
    positions: List[tuple] = []
    for name, marker in markers:
        idx = system_text.find(marker)
        if idx >= 0:
            positions.append((idx, name))
    positions.sort()
    for i, (idx, name) in enumerate(positions):
        end = positions[i + 1][0] if i + 1 < len(positions) else len(system_text)
        out[name] = system_text[idx:end].strip()
    return out


def _split_layer_b(layer_b_text: str) -> dict:
    """Layer B 内切出 ``TOOL_PROMPT_ADDENDUM`` 段(用 tool_addendum.py L17 字面起头)。"""
    addendum_marker = "你有以下 tool 可用"
    idx = layer_b_text.find(addendum_marker)
    if idx >= 0:
        return {
            "addendum": layer_b_text[idx:].strip(),
            "b_directive": layer_b_text[:idx].strip(),
        }
    return {"addendum": "", "b_directive": layer_b_text}


def _split_layer_c(layer_c_text: str) -> dict:
    """Layer C 内用 ``[当前状态]`` 切 persona / character_state(C4)。"""
    state_marker = "[当前状态]"
    idx = layer_c_text.find(state_marker)
    if idx >= 0:
        return {
            "persona": layer_c_text[:idx].strip(),
            "character_state": layer_c_text[idx:].strip(),
        }
    return {"persona": layer_c_text, "character_state": ""}


def _flatten_system_content(content: Any) -> str:
    """Normalize messages[0].content to string for marker-based layer splitting.

    INV-5 §5 Phase 4 fix:Phase 2 给 messages[0].content 引入 list-of-blocks
    形态(stable / variable 双 text block)便于 Phase 3 在 stable 块标
    cache_control;但 _split_system_layers 用 ``str.find(marker)`` 切层,
    list 形态会触发 AttributeError → outer except 静默吞 → row 不写出。

    本 helper 把 list-form 拼回 string(用 ``"\\n\\n".join`` 与 renderer
    `_build_messages` 的 stable/variable 拼接同 separator,marker 字面
    位置与 pre-Phase-2 一致,切层逻辑 work 不变)。

    - str 形态(pre-Phase-2 / variable 为空 fallback 路径)→ 原样
    - list 形态 → join 内 text blocks
    - 其它(None / dict / 非预期)→ ``""``
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n\n".join(
            b.get("text", "") for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        )
    return ""


def _split_layer_d(layer_d_text: str) -> dict:
    """Layer D 内用 ``用户画像:`` / ``今日活动:`` / ``长期记忆(Top 5):`` 切。"""
    out = {"user_profile": "", "activity": "", "long_memory_top5": ""}
    sub_markers = [
        ("user_profile", "用户画像:"),
        ("activity", "今日活动:"),
        ("long_memory_top5", "长期记忆(Top 5):"),
    ]
    positions: List[tuple] = []
    for name, marker in sub_markers:
        idx = layer_d_text.find(marker)
        if idx >= 0:
            positions.append((idx, name))
    positions.sort()
    for i, (idx, name) in enumerate(positions):
        end = positions[i + 1][0] if i + 1 < len(positions) else len(layer_d_text)
        out[name] = layer_d_text[idx:end].strip()
    return out


def _extract_cache_fields(usage: Any) -> dict:
    """Pull cache-related fields from LiteLLM response.usage object.

    INV-5 §5 Phase 4 step 3 — 4 字段 schema:
      - cached_tokens             命中缓存 token 数(0 = cold,>0 = warm hit)
      - cache_creation_input_tokens  首次创建缓存 token 数(>0 = cold,0 = warm)
      - cache_type                "ephemeral" 或 None
      - is_cache_hit              boolean: cached_tokens > 0

    各 provider 字段位置(LiteLLM ModelResponse.usage.model_dump() 实测):
      - Qwen dashscope/: 全 4 字段都嵌在 prompt_tokens_details 内:
            cached_tokens / cache_creation_input_tokens / cache_type
            (本刀 Phase 4 实测; 之前 INV-5 §2.3 / §4.2 dump 表格把字段
             从 prompt_tokens_details ascii-flatten 显示让人误以为在顶层)
      - DeepSeek deepseek/: 顶层 prompt_cache_hit_tokens + 兼容字段
            prompt_tokens_details.cached_tokens (LiteLLM 1.x+ 也填上)
      - OpenAI openai/: 仅 prompt_tokens_details.cached_tokens

    取值策略:全部从 prompt_tokens_details 内部取;顶层 fallback 防御
    不同 SDK 版本字段位置变动。任何异常 / 字段缺失 → 字段填 None,
    行仍写出。
    """
    out: dict = {
        "cached_tokens": None,
        "cache_creation_input_tokens": None,
        "cache_type": None,
        "is_cache_hit": False,
    }
    if usage is None:
        return out

    def _get(obj, key):
        if obj is None:
            return None
        if isinstance(obj, dict):
            return obj.get(key)
        return getattr(obj, key, None)

    details = _get(usage, "prompt_tokens_details")

    # cached_tokens: prompt_tokens_details.cached_tokens (Qwen/OpenAI/DeepSeek)
    cached = _get(details, "cached_tokens")
    if cached is None:
        # DeepSeek 顶层 alt: prompt_cache_hit_tokens
        cached = _get(usage, "prompt_cache_hit_tokens")
    out["cached_tokens"] = cached

    # cache_creation_input_tokens: prompt_tokens_details 内 (Qwen 实测路径)
    # 顶层 fallback 防御 SDK 版本差异
    cci = _get(details, "cache_creation_input_tokens")
    if cci is None:
        cci = _get(usage, "cache_creation_input_tokens")
    out["cache_creation_input_tokens"] = cci

    # cache_type: prompt_tokens_details 内 (Qwen 实测路径)
    ct = _get(details, "cache_type")
    if ct is None:
        ct = _get(usage, "cache_type")
    out["cache_type"] = ct

    out["is_cache_hit"] = bool(cached) and cached > 0
    return out


def emit_cache_metrics_sync(
    *,
    conversation_id: Optional[int],
    turn_n: int,
    usage: Any,
) -> None:
    """Append a per-turn response-side row with cache fields only.

    INV-5 §5 Phase 4 step 3 — 配对 emit_sync 写的 request-side row;按
    (conv_id, turn_n) 锚定。Sync + fail-silent — **never** raises。

    分析 jsonl 时按 (conv_id, turn_n) 把 req / resp 两行 join 起来,合并视图
    含 prompt 各段 token 数 + cache 命中数据。
    """
    try:
        row: dict = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "conv_id": conversation_id,
            "turn_n": turn_n,
            "kind": "cache_metrics",  # 区分 req row (无 kind) / resp row
        }
        row.update(_extract_cache_fields(usage))
        # 也带上 prompt_tokens 便于快速看占比
        if usage is not None:
            for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
                if isinstance(usage, dict):
                    val = usage.get(k)
                else:
                    val = getattr(usage, k, None)
                if val is not None:
                    row[k] = val

        os.makedirs(os.path.dirname(_path()), exist_ok=True)
        with open(_path(), "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception as exc:
        logger.debug("[token_probe] cache_metrics emit failed: %s", exc)


def emit_sync(
    *,
    conversation_id: Optional[int],
    turn_n: int,
    messages: List[dict],
    tools: List[dict],
) -> None:
    """Decompose this LLM request and append one JSONL row.

    Sync + fail-silent — **never** raises or blocks the caller.
    """
    try:
        row: dict = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "conv_id": conversation_id,
            "turn_n": turn_n,
        }
        row["tools_schema"] = _tok(tools)

        # Decompose messages list (renderer path)
        system_text = ""
        summary_text = ""
        short_term_msgs: List[str] = []
        current_text = ""
        if messages:
            if messages[0].get("role") == "system":
                # Phase 2 起 content 可能是 list-of-blocks;归一化后再切层
                system_text = _flatten_system_content(
                    messages[0].get("content", "")
                )
            for m in messages[1:-1] if len(messages) > 1 else []:
                role = m.get("role")
                content = m.get("content", "") or ""
                if role == "system" and content.startswith("【过往对话摘要"):
                    summary_text = content
                elif role in ("user", "assistant"):
                    short_term_msgs.append(content)
            if messages[-1].get("role") == "user":
                current_text = messages[-1].get("content", "") or ""

        row["summary"] = _tok(summary_text)
        row["short_term"] = sum(_tok(c) for c in short_term_msgs)
        row["current_text"] = _tok(current_text)
        row["system_combined"] = _tok(system_text)

        # Sub-layer split via marker parsing on system_text
        layers = _split_system_layers(system_text)
        row["layer_a"] = _tok(layers["layer_a"])

        layer_b_parts = _split_layer_b(layers["layer_b"])
        row["addendum"] = _tok(layer_b_parts["addendum"])

        layer_c_parts = _split_layer_c(layers["layer_c"])
        row["persona"] = _tok(layer_c_parts["persona"])
        row["character_state"] = _tok(layer_c_parts["character_state"])

        layer_d_parts = _split_layer_d(layers["layer_d"])
        row["user_profile"] = _tok(layer_d_parts["user_profile"])
        row["activity"] = _tok(layer_d_parts["activity"])
        row["long_memory_top5"] = _tok(layer_d_parts["long_memory_top5"])

        # total = sum 上层独立块 token(避免 double-count system 内的 sub-layer)
        row["total"] = (
            max(row["tools_schema"], 0)
            + max(row["system_combined"], 0)
            + max(row["summary"], 0)
            + max(row["short_term"], 0)
            + max(row["current_text"], 0)
        )

        os.makedirs(os.path.dirname(_path()), exist_ok=True)
        with open(_path(), "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception as exc:
        logger.debug("[token_probe] emit failed: %s", exc)
