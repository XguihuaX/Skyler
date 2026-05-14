"""D6 — proactive briefing schema 校验 + 指令性短语剥除。

三层防御:
  1. **schema 校验**:必填 3 字段(activity_event / time_context /
     suggested_emotion),任一缺失 → 返回 None,Layer D6 段不输出。
  2. **指令性短语 strip**:对每个字段 sub 掉 ``请这样说`` / ``你应该`` 等
     directive pattern。briefing 是"数据陈述,不是台词"(Layer D6 模板首行)
     —— 防止 stage1 cron 给 stage2 的简报里夹带 imperative,污染 persona
     speech_style。
  3. **空白裁剪**:strip 后再 strip 空白,避免变成 "  " 还能在模板里渲染
     出空行段落。
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProactiveBriefing:
    activity_event: str
    time_context: str
    suggested_emotion: str


# 指令性短语黑名单。``.{1,5}``/``.{1,10}`` 防止 greedy 吃整段;仅匹配紧贴
# 关键词的小尾巴。LLM 写 briefing 时若说 ``建议用温柔语气`` / ``记得提醒他喝水``
# 这种就会被 strip,只留事实 ``建议用`` / ``记得`` 后面的小尾巴会被一同删除。
IMPERATIVE_PATTERNS = [
    r"请这样说",
    r"你应该",
    r"用.{1,5}语气",
    r"记得.{1,10}",
    r"务必.{1,10}",
    r"必须.{1,10}",
]

_IMPERATIVE_RE_LIST = [re.compile(p) for p in IMPERATIVE_PATTERNS]


def sanitize_briefing_field(text: str) -> str:
    """删指令性短语,留事实陈述。空 / None → 空串。"""
    if not text:
        return ""
    for cre in _IMPERATIVE_RE_LIST:
        text = cre.sub("", text)
    return text.strip()


def validate_and_sanitize_briefing(
    raw: Optional[dict],
) -> Optional[ProactiveBriefing]:
    """schema 校验 + sanitize。None / schema 不符 → None,Layer D6 不渲染。"""
    if not raw or not isinstance(raw, dict):
        return None
    required = ("activity_event", "time_context", "suggested_emotion")
    if not all(k in raw and raw[k] for k in required):
        logger.warning(
            "[briefing] schema invalid, dropping; got keys=%s",
            list(raw.keys()),
        )
        return None
    activity_event = sanitize_briefing_field(str(raw["activity_event"]))
    time_context = sanitize_briefing_field(str(raw["time_context"]))
    suggested_emotion = sanitize_briefing_field(str(raw["suggested_emotion"]))
    if not (activity_event and time_context and suggested_emotion):
        # sanitize 之后字段空了 —— 等于全是 imperative,丢弃
        logger.warning("[briefing] all fields empty after sanitize, dropping")
        return None
    return ProactiveBriefing(
        activity_event=activity_event,
        time_context=time_context,
        suggested_emotion=suggested_emotion,
    )
