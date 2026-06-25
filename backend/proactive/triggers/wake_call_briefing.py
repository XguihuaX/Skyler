"""v3-G chunk 2.6 — WakeCallBriefingTrigger（"邀请对话"模式）。

设计哲学（详见 DESIGN §十五之B 模式 A vs B）：

* **模式 A 单方面播报**（``MorningBriefingTrigger``）：cron → 整段内容推送
  到 WS。适合"非问也得通知"场景。
* **模式 B 邀请对话**（本 trigger）：cron → 轻触发短问候 → 等用户响应 →
  用户第一句话 trigger 真内容作为对话回复。适合大多数生活节奏 trigger。
  默认 v3-F' 走模式 B。

stage 1 / stage 2 状态机
========================

::

    cron 0 8 * * * Asia/Tokyo
       │
       ▼
    [stage 1 — engine.run_wake_call_trigger]
       ① aggregate_briefing_data → time / calendar / instruction memories / city
       ② INSERT pending_briefings (consumed_at=NULL, ttl=30min)
       ③ ChatAgent.stream "你只需 8-15 字叫醒用户" → push 短 TTS proactive=true
       ④ chat_history kind='proactive' proactive_trigger='wake_call'
       │
       ▼  (用户开始 ASR 或文字)
    [stage 2 — chat.py _build_messages 注入]
       ① 检测最近 assistant turn proactive_trigger='wake_call'
       ② 拉 active pending_briefing（未消费 + 未 TTL 过期）
       ③ system prompt 末尾追加 _WAKE_CALL_BRIEFING_ADDENDUM
          (包含用户原话 + 自适应规则 + briefing_data_json 缓存)
       ④ 标 pending consumed_at = utcnow （consume-on-detect）
       │
       ▼
    LLM 按用户响应风格自适应输出（嗯 / 精神 / 拒绝 / 切话题）
       │
       ▼
    chat_history kind='normal' （**重要**：这是真对话，profile rewrite 应看见）

**为什么是 consume-on-detect 而不是 consume-on-success**：
- 简单：不需跨模块协调（_build_messages → ws.py turn 完成后通知）
- 容错：如果 turn 失败，用户重发的下一条消息 pending 已消费 → fallback
  普通短回复，对用户更可预期（避免连续两次都触发简报内容）

cron 默认 ``0 8 * * *``（早 8 点，比 morning_briefing 早一小时——叫醒），
从 ``config.proactive.wake_call_briefing.cron`` 读。
"""
from __future__ import annotations

import logging
from typing import Optional

from backend.config import config_yaml
from backend.database.models import Character
from backend.proactive.engine import ProactiveTrigger

logger = logging.getLogger(__name__)


_DEFAULT_CRON = "0 8 * * *"
_DEFAULT_TTL_MIN = 30
_DEFAULT_SNOOZE_MIN = 30


def _wake_call_config() -> dict:
    proactive = config_yaml.get("proactive") or {}
    return proactive.get("wake_call_briefing") or {}


def _resolve_cron() -> str:
    cfg = _wake_call_config()
    expr = cfg.get("cron")
    if isinstance(expr, str) and expr.strip():
        return expr.strip()
    return _DEFAULT_CRON


def _resolve_ttl_minutes() -> int:
    cfg = _wake_call_config()
    val = cfg.get("pending_ttl_minutes")
    if isinstance(val, int) and 5 <= val <= 240:
        return val
    return _DEFAULT_TTL_MIN


def _resolve_default_snooze_minutes() -> int:
    cfg = _wake_call_config()
    val = cfg.get("default_snooze_minutes")
    if isinstance(val, int) and 5 <= val <= 120:
        return val
    return _DEFAULT_SNOOZE_MIN


def _wake_call_mode_active() -> bool:
    """``proactive.mode == 'wake_call'`` 才注册 cron。``mode`` 字段互斥决定
    哪个 trigger 上线，避免两个都注册撞车。
    """
    proactive = config_yaml.get("proactive") or {}
    if not proactive.get("enabled", False):
        return False
    return str(proactive.get("mode") or "").strip() == "wake_call"


# stage 1：让 LLM 用 character.persona 生成 8-15 字叫醒短句。
# 不需要 enable_search / 不要调任何 tool，纯 persona-based 短问候。
#
# 重要：本 prompt 故意**重复多遍**长度约束。早期实测 LLM 受短期记忆里
# 历史长简报的 tone 影响，会输出 100+ 字 wake call。多重锚定才能压住。
#: 检测 sentinel —— ChatAgent._build_messages 用此字符串识别 stage 1 prompt
#: 跳过 wake_call addendum 注入，避免 stage 1 自己又被注入 stage 2 内容。
WAKE_CALL_STAGE1_SENTINEL = "[wake_call_stage1_v1]"

# INV-13 Option G(2026-05-27)软化:原 "8-15 字硬约束 + ⚠️⚠️⚠️ 三层强调" 改
# 为 "**简短早晨叫醒**(参考 8-15 字)" 软指引。详 docs/INV-13-*.md §11.5 / §12.6。
_STAGE1_SYSTEM_PROMPT = WAKE_CALL_STAGE1_SENTINEL + """
⚠️ 本轮风格要求:**简短早晨叫醒**(参考 8-15 字 · 软指引非硬约束)。

❌ 严禁输出（无论历史对话提到了什么）：
- 任何天气信息（"今天天气""气温""带伞"等字眼一律禁止）
- 任何日程内容（"几点开会""今天有 X 事""今天日程"等一律禁止）
- 任何待办提醒（"记得做 X""别忘了 X"等一律禁止）
- 任何询问 / 闲笔 / 开放话头（"想听歌吗""今天打算做什么"等一律禁止）
- 任何叙述或铺陈语句

✅ 只输出:用人设语气 + 昵称叫醒,简短问候式。例:
- "宝,醒一醒～"
- "起床啦,懒虫～"
- "早安呀宝贝～"
- "宝宝,新的一天啦～"

本轮**只是轻触发早晨叫醒** · 想说的所有日程 / 天气 / 待办内容**留到用户回应后再说** —— 那是 stage 2 的事,与本轮无关。

直接输出叫醒话本身,不前缀,不解释,不 metadata。"""


class WakeCallBriefingTrigger(ProactiveTrigger):
    """模式 B 邀请对话：早晨轻触发短问候 + DB 缓存 → 用户响应后自适应内容。"""

    name = "wake_call"
    enable_search = False  # stage 1 只发短问候，不需 web search

    def __init__(self) -> None:
        self.cron_expr = _resolve_cron()
        self.interval_seconds = None
        self.event_source = None

    async def build_system_prompt(self, character: Optional[Character]) -> str:
        return _STAGE1_SYSTEM_PROMPT

    async def resolve_capabilities(self) -> list[str]:
        """stage 1 不需要 LLM 调任何 capability —— 短问候是纯文本生成。

        返空列表 = engine 不会注入 capability hint。stage 2 的 addendum
        在 chat.py 里独立处理，自带"调 snooze 推迟"指令。
        """
        return []


# ---------------------------------------------------------------------------
# stage 2：ChatAgent 注入到 system prompt 的 addendum 模板
#
# 由 backend.agents.chat 在 _build_messages 检测到 pending_briefing 时拼。
# 用户原文（_text_for_addendum）和缓存数据（_briefing_data_for_addendum）
# 拼到模板里。
# ---------------------------------------------------------------------------

WAKE_CALL_STAGE2_ADDENDUM = """⚠️ 上一轮你叫用户起床。用户刚刚回复了「{user_text}」。

请根据用户响应风格**自适应**输出：

- **简短模糊**（"嗯" / "早" / "嗯嗯" / "咋了"）→ 50-80 字带出今日核心日程 + 一句温度感闲笔。
- **好奇精神**（"早，今天怎么样" / "几点了" / "今天有啥事" / "天气如何"）→ 180-260 字完整简报（天气 + 日程 + 待办 + 闲笔 + 开放话头）。**临时覆盖你平时简短克制的人设约束**，简报场景需要信息密度。
- **拒绝起床**（"再睡" / "还早" / "困" / "不想起" / "再睡 N 分钟"）→ 不发简报内容，回 1 句安抚（≤25 字），并**调用 proactive.snooze_wake_call(minutes=N)** 推迟下次 wake call（用户说"再睡 X 分钟"则 minutes=X，否则用配置默认）。
- **切换话题**（用户直接问无关的事如"今天天气如何""我的日程""帮我加个会议"）→ 优先回答当前话题，**丢弃**简报内容（pending 仍被消费，避免下次再触发）。

完成本轮后**立即回到日常人设风格**，下一次回复保持简短克制（除非又是简报场景）。

【缓存的预聚合数据 briefing_data_json】
{briefing_data_json}

【对天气 / 新闻补充信息】
如果用户响应风格是"好奇精神"且需要天气 / 新闻——直接调用 enable_search 现查（缓存里没有 weather / news；这俩留给 stage 2 现查更新鲜）。其他风格不需要查。

city = {city}（搜索时拼【今日 {city} 天气】）。"""


# v3-G chunk 4 Part C：注册到 _stage2_registry 让 chat.py 多 trigger 通用查表。
def _wake_call_stage2_builder(
    user_text: str, briefing_data_json: str, city: str | None,
) -> str:
    return WAKE_CALL_STAGE2_ADDENDUM.format(
        user_text=user_text,
        briefing_data_json=briefing_data_json,
        city=city or "东京",
    )


from backend.proactive.triggers._stage2_registry import register_stage2  # noqa: E402

register_stage2("wake_call", WAKE_CALL_STAGE1_SENTINEL, _wake_call_stage2_builder)


__all__ = [
    "WakeCallBriefingTrigger",
    "WAKE_CALL_STAGE1_SENTINEL",
    "WAKE_CALL_STAGE2_ADDENDUM",
    "_resolve_cron",
    "_resolve_ttl_minutes",
    "_resolve_default_snooze_minutes",
    "_wake_call_mode_active",
]
