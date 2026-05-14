"""v4 persona engineering segment 1 — 5-layer prompt rendering framework.

Layers:
  A — output format spec(tag specs + 长度建议)+ meta_rules(render-only)
  B — mode_directive(roleplay/proactive)+ universal_constraints + tool_addendum
  C — persona(身份卡/性格/说话风格/口头禅/voice_samples/forbidden_phrases/状态)
  D — context(profile / 今日活动 / 长期记忆 / 工具结果 / 临时指令 / proactive briefing)
  + transition — variant 切换的 carry-over 防漂移提示

Entry:
  ``render_system_prompt(character_id, turn_origin, …) -> str``
"""

from backend.agents.prompt.mode import Mode, PROACTIVE_ORIGINS, determine_mode
from backend.agents.prompt.renderer import render_system_prompt

__all__ = [
    "Mode",
    "PROACTIVE_ORIGINS",
    "determine_mode",
    "render_system_prompt",
]
