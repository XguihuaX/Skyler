"""v3-G chunk 2 — MorningBriefingTrigger 早晨智能简报。

用 ChatAgent + 联网搜索 + capability 调度生成 200-300 字自然口语早晨问候，
覆盖：天气一句 / 日程概述 / 待办提醒 / 温度感闲笔 / 开放话头结尾。

cron 默认 ``0 9 * * *``（Asia/Tokyo），从 ``config.yaml.proactive.morning_briefing.cron``
读，启停从同段 ``enabled`` 读。

city 解析（v0.1）：先看 ``config.proactive.morning_briefing.city``，没有
fallback "东京"。未来可从 user.profile_summary / instruction memory 抽。
"""
from __future__ import annotations

import logging
from typing import Optional

from backend.config import config_yaml
from backend.database.models import Character
from backend.proactive.engine import ProactiveTrigger

logger = logging.getLogger(__name__)


_DEFAULT_CRON = "0 9 * * *"
_DEFAULT_CITY = "东京"

_SYSTEM_PROMPT_TEMPLATE = """你正在生成今日早晨简报。这是一次**特殊**的主动开口：

⚠️ **重要：本轮回复必须 200-300 字**。这是早晨简报的硬性要求，**临时覆盖**你平时"简短克制 通常不超过3句话"的人设约束。简报短了用户拿不到信息密度，长了又啰嗦——目标 200-300 字这个区间。

执行步骤（按顺序调用 tool）：
1. 调 time.now 拿当前时间 / 星期 / 是否周末。
2. 调 calendar.today_events 拿今日日程。
3. 调 list_memories 拿用户最近指令类记忆作为「待办」（type='instruction' 优先）。
4. 用 enable_search 查【今日 {city} 天气】和【今日综合要闻最热 1-2 条】。
5. 把这些信息用你自己的语气编织成 **200-300 字** 自然口语早晨问候。不要列表分点，要像跟人面对面说话一样自然铺开。

回复内容必须包含（缺一不可）：
- 天气一句（具体温度 / 阴晴 / 是否需要带伞）
- 今日日程概述（如几点有什么事，几件大事）
- 至少一个待办提醒（来自 list_memories 的 instruction 类记忆，或日程里的待办性事项）
- 一句温度感闲笔（季节回响 / 城市风物 / profile_summary 里反映的用户状态）
- 一个开放话头结尾，让用户能直接接话（如"今天打算先做哪件？" / "想喝点什么？"）

格式要求：
- **不要**说"早安简报开始"或"以下是今天的简报"之类的标题语；直接进入问候本身。
- 第一句就是叫名字 + 早安（如"宝，早安～"）。
- **写完后默数一遍字数**：少于 200 字就再补两句温度感闲笔；超过 300 字就剪掉次要内容。
"""


def _briefing_config() -> dict:
    proactive = config_yaml.get("proactive") or {}
    return proactive.get("morning_briefing") or {}


def _resolve_city() -> str:
    cfg = _briefing_config()
    city = cfg.get("city")
    if isinstance(city, str) and city.strip():
        return city.strip()
    return _DEFAULT_CITY


def _resolve_cron() -> str:
    cfg = _briefing_config()
    expr = cfg.get("cron")
    if isinstance(expr, str) and expr.strip():
        return expr.strip()
    return _DEFAULT_CRON


def _briefing_enabled() -> bool:
    """``proactive.enabled`` AND ``proactive.morning_briefing.enabled`` 都为 True 才开。"""
    proactive = config_yaml.get("proactive") or {}
    if not proactive.get("enabled", False):
        return False
    cfg = proactive.get("morning_briefing") or {}
    return bool(cfg.get("enabled", False))


class MorningBriefingTrigger(ProactiveTrigger):
    """早晨简报：每天 9 点（默认）拉起一段智能问候。"""

    name = "morning_briefing"
    enable_search = True

    def __init__(self) -> None:
        # cron_expr 在 init 时从 config 解析，让 hot-reload 后下次实例化生效
        self.cron_expr = _resolve_cron()
        self.interval_seconds = None
        self.event_source = None

    async def build_system_prompt(self, character: Optional[Character]) -> str:
        """注入 spec 锁定的 6 条指令链 + 当前 city。

        ``character`` 不直接出现在 prompt 里 —— ChatAgent 已经把 persona
        放在 system 头部，trigger 这里只补"为什么要主动开口 + 要怎么做"。
        """
        return _SYSTEM_PROMPT_TEMPLATE.format(city=_resolve_city())

    async def resolve_capabilities(self) -> list[str]:
        """返这次触发希望 LLM 主动调用的 capability hint。

        engine 把这个列表拼到 system prompt 末尾作为提示，但不裁剪 ToolRegistry
        传给 LLM 的 tools[]（其他 capability 仍可见）。
        """
        return [
            "time.now",
            "calendar.today_events",
            "list_memories",
        ]


__all__ = [
    "MorningBriefingTrigger",
    "_briefing_enabled",
    "_resolve_cron",
    "_resolve_city",
]
