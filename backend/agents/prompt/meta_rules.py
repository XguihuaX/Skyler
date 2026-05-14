"""A2 meta_rules — render-only,**不进 LLM context**,Python 侧引用执行。

记录 Segment 1 的 sign-off invariant 与渲染优先级。renderer 不读这些常量,
但 test 与 future tooling(eg v4.1 ADDENDUM 重构 / sanitize 状态机扩展)
可以 import 来做静态校验。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass(frozen=True)
class MetaRules:
    priority_order: List[str] = field(default_factory=lambda: [
        "safety",       # B2 universal_constraints 第 2 条
        "layer_a1",     # 输出格式规范(tag specs)
        "layer_c",      # persona core
        "layer_d_data", # context 数据陈述
        "layer_e",      # transition / 其他低优先级附录
    ])
    strip_briefing_imperative: bool = True
    sanitize_chain_invariants: List[str] = field(default_factory=lambda: [
        "thinking_tag_extracted_before_tts",
        "state_update_parsed_into_character_states",
        "motion_routed_to_live2d",
        "emotion_tag_paired_form_preserved",   # A1 sign-off
        "TOOL_PROMPT_ADDENDUM_relocated_as_is",  # D-1 sign-off
    ])


META_RULES = MetaRules()
