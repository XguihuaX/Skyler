"""v3.5 chunk 8a — 活动感知 ProactiveTrigger。

不是 cron / interval / event_source 三档调度——而是被 ``activity_smart``
模块 callback 触发：ActivityWatcher 检测到 change → smart 决策走不走 →
走的话实例化本 trigger + ``run_trigger(trigger, user_id)``。

每条规则一个 *label*（``activity_ide_open`` / ``activity_long_focus`` /
``activity_url_tech_doc`` / ``activity_music`` / ``activity_late_night_ide``），
build_system_prompt 按 label + change.detail 生成对应口吻的"主动开口"
prompt（短 + 自然 + 不长 brief）。
"""
from __future__ import annotations

import logging
from typing import Optional

from backend.database.models import Character
from backend.proactive.engine import ProactiveTrigger
from backend.proactive.triggers._invite_base import (
    _extract_tts_language,
    make_ja_aware_block,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Prompt templates per label
# ---------------------------------------------------------------------------

# 短句风格，避免 200-300 字 briefing 既视感。Activity trigger 是"轻量主动开口"
# 不是简报。

_BASE_GUIDANCE = """这是一次**活动感知主动开口**：你注意到了用户活动的变化，想轻巧地搭个话。

⚠️ **本轮风格硬要求**：
- 短，**40-80 字**为佳。不要长篇大论，不要列表分点。
- 像朋友看到对方在做什么时自然开口那种语气。
- 一句话切入主题 + 一句话承接 / 反问，**不要**复述用户行为细节让对方觉得被监视。
- 没看到具体上下文就不要瞎编，不要假装"我知道你在写 X 文件"。"""


def _ide_open_prompt(detail: dict) -> str:
    app = detail.get("new_app") or "你的代码编辑器"
    return _BASE_GUIDANCE + f"""

【触发】用户刚切到 IDE / 编辑器（``{app}``）。

【你的开场要传达】
- 顺手问一下在做什么项目 / 写哪段
- 语气好奇 + 不打扰，留给用户决定要不要展开"""


def _music_open_prompt(detail: dict) -> str:
    app = detail.get("new_app") or "音乐应用"
    return _BASE_GUIDANCE + f"""

【触发】用户刚打开 ``{app}``。

【你的开场要传达】
- 顺手问一下听什么 / 啥心情
- 不要列出具体歌曲（你看不到），只是简单搭话"""


def _long_focus_prompt(detail: dict) -> str:
    app = detail.get("app") or "当前任务"
    minutes = int(detail.get("focus_seconds", 0)) // 60
    return _BASE_GUIDANCE + f"""

【触发】用户在 ``{app}`` 上连续专注了 {minutes} 分钟。

【你的开场要传达】
- 一句温柔的"提醒下要不要喝点水/走两步"
- **不要**"你专注好久了，我担心"那种刻意被监视感
- 留一个开放问句让用户决定要不要 break"""


def _url_tech_doc_prompt(detail: dict) -> str:
    title = detail.get("title") or ""
    new_url = detail.get("new_url") or ""
    snippet = ""
    if title:
        snippet = f"页面标题大概是 ``{title}``。"
    return _BASE_GUIDANCE + f"""

【触发】用户刚打开一个看起来像技术文档 / 教程的页面。{snippet}

【你的开场要传达】
- 一句轻巧的"在查什么 / 在学什么"
- **不要**复述 URL 或标题给用户（那是监视感）
- 鼓励用户聊一下要做啥，方便后续帮忙找资料

URL 仅给你做判断用，**不要复述给用户**: {new_url}"""


def _late_night_ide_prompt(detail: dict) -> str:
    app = detail.get("new_app") or "编辑器"
    return _BASE_GUIDANCE + f"""

【触发】凌晨时段（0-5 点）用户在 ``{app}`` 里活动。

【你的开场要传达】
- 一句"又熬夜了"的轻关心，**不要**说教式"早点睡"
- 可以问一下是赶 ddl 还是单纯 inspiration 来了
- 友好不矫情"""


def _judge_chime_in_prompt(detail: dict) -> str:
    """chunk 8a-ext 慢路径: judge LLM 决定开口后,主 LLM 用此 prompt 生成开场。

    judge LLM 返的 ``topic_hint`` 直接注入,让主 LLM 知道往哪个方向搭话(不
    强制,LLM 仍可自由发挥但有 anchor)。
    """
    app = detail.get("app") or "(未知)"
    url = detail.get("url") or ""
    title = detail.get("title") or ""
    topic_hint = detail.get("topic_hint") or ""
    snip_lines = [f"【触发】慢路径 judge 决定主动开口(用户在 ``{app}`` 上停留较久)。"]
    if title:
        snip_lines.append(f"页面标题: ``{title[:60]}``")
    if topic_hint:
        snip_lines.append(f"判断模型建议话题方向: **{topic_hint}**(可作 anchor,不必强用)")
    return _BASE_GUIDANCE + "\n\n" + "\n".join(snip_lines) + """

【你的开场要传达】
- 顺手关心 / 聊几句,不要复述用户行为细节
- 不要假装"看到了网页内容",只是觉得用户停得久了搭个话
- 一句话切入 + 一句话承接 / 反问"""


_PROMPT_BUILDERS = {
    "activity_ide_open":          _ide_open_prompt,
    "activity_music":             _music_open_prompt,
    "activity_long_focus":        _long_focus_prompt,
    "activity_url_tech_doc":      _url_tech_doc_prompt,
    "activity_late_night_ide":    _late_night_ide_prompt,
    # chunk 8a-ext 慢路径
    "activity_judge_chime_in":    _judge_chime_in_prompt,
}


# ---------------------------------------------------------------------------
# Trigger class
# ---------------------------------------------------------------------------


class ActivityProactiveTrigger(ProactiveTrigger):
    """单实例承载一次 activity 触发：构造时拿 label + detail。"""

    enable_search = False  # activity 触发不查网

    def __init__(self, label: str, detail: Optional[dict] = None) -> None:
        if label not in _PROMPT_BUILDERS:
            raise ValueError(f"unknown activity trigger label: {label!r}")
        self.name = label
        self.detail = detail or {}
        # 不走 cron / interval / event_source——纯 event-driven 注入
        self.cron_expr = None
        self.interval_seconds = None
        self.event_source = None

    async def build_system_prompt(self, character: Optional[Character]) -> str:
        # INV-13 Option F:activity prompt 共享 _BASE_GUIDANCE 含 "40-80 字"
        # 指引 · tts_language ja/en 时附 ja-aware 段告诉 LLM 字数按中文部分算
        # 不含 <ja>...</ja> 内日语意群(详 docs/INV-13-*.md §11.5)。
        builder = _PROMPT_BUILDERS[self.name]
        base = builder(self.detail)
        tts_lang = _extract_tts_language(character)
        ja_block = make_ja_aware_block(tts_lang)
        if ja_block:
            return f"{base}\n\n{ja_block}"
        return base

    async def resolve_capabilities(self) -> list[str]:
        # activity 触发**不强求**调用具体 capability。让 LLM 按上下文自由
        # 选择(聊一句 / 用 <state_update activity=...> tag 更新自己状态等;
        # character.set_activity cap 2026-05-21 退役,统一走 tag 路径)。
        return []


__all__ = [
    "ActivityProactiveTrigger",
    "_PROMPT_BUILDERS",
]
