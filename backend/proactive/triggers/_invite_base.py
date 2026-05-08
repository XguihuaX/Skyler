"""v3-G chunk 4 部分 C — 模式 B "邀请对话" trigger 共享基础。

WakeCallBriefingTrigger 是 v3-F' "邀请对话"模式 B 的首个实现（chunk 2.6）。
chunk 4 加 4 个同模式 trigger（lunch_call / dinner_call / bedtime_chat /
long_idle），逻辑结构 99% 相同，只在 stage 1 短句 prompt + stage 2
addendum 内容上有差别。

本模块抽出共享部分：

* ``InviteTriggerBase`` —— 复用 stage 1 8-15 字短句 prompt 骨架，子类只
  需 override ``GREETING_HINT``（提示 LLM 这次叫什么风格的招呼）+
  ``trigger.name``。
* ``make_stage1_prompt(sentinel, hint)`` —— 共享强约束 prompt 文本。
* ``make_stage2_addendum_template(scene)`` —— 共享 stage 2 addendum 骨架，
  各 trigger 只需提供 ``scene`` 简述。

设计选择：不是 ABC 继承，是 **静态拼接 + 注册** —— trigger 子类只持配置 +
prompt 字符串，行为通过 engine.run_wake_call_trigger 执行。这样新 trigger
只需 ~30 行（不需要懂 engine 内部）。
"""
from __future__ import annotations

from typing import Optional

from backend.database.models import Character
from backend.proactive.engine import ProactiveTrigger


def make_stage1_prompt(sentinel: str, scene_label: str, examples: str) -> str:
    """生成 stage 1 强约束短句 prompt。

    Args:
        sentinel: 嵌入 prompt 头部的稳定 sentinel 字符串（防 stage 2 递归
            注入；登记到 _stage2_registry）。
        scene_label: 场景描述短词，如"叫吃午饭"/"叫吃晚饭"/"睡前问候"/"轻触你"。
        examples: 示例短句多行字符串。

    返回：含 ⚠️⚠️⚠️ 三层强调 + 严禁 / 只输出 / 例子结构的 prompt。chunk 2.6
    + chunk 3 教训：弱"可选"提示 LLM 多数轮跳过；必须强约束 + 重复才稳定
    输出 8-15 字短句。
    """
    return sentinel + f"""
⚠️⚠️⚠️ 关键约束：本轮你**只能输出一句 8-15 个字（含标点不超过 18）的短问候**，场景：{scene_label}。

❌ 严禁输出（无论历史对话提到了什么）：
- 任何天气信息（"今天天气""气温""带伞"等字眼一律禁止）
- 任何日程内容（"几点开会""今天有 X 事""今天日程"等一律禁止）
- 任何待办提醒（"记得做 X""别忘了 X"等一律禁止）
- 任何询问 / 闲笔 / 开放话头（"想听歌吗""今天打算做什么"等一律禁止）
- 任何叙述或铺陈语句

✅ 只输出：用人设语气 + 昵称喊用户，**8-15 字**。例：
{examples}

无论你的短期对话历史里有多长的过往简报，**这一轮**都只允许 8-15 字。想说的所有内容**留到用户回应后再说**——那是 stage 2 的事，与本轮无关。

直接输出短问候本身，不前缀，不解释，不 metadata。"""


def make_stage2_addendum_template(scene_label: str, scene_focus: str) -> str:
    """生成 stage 2 addendum 模板。

    Args:
        scene_label: 场景中文短词（如"午饭呼叫"）
        scene_focus: 场景关注点描述（如"用户的胃口 / 餐食偏好 / 是否在外就餐"）

    返回：包含 ``{user_text}`` ``{briefing_data_json}`` ``{city}`` 三个占位的
    模板字符串，由 chat.py 在命中 stage 2 时 ``.format`` 填充。
    """
    return f"""⚠️ 上一轮你给用户发了一句轻触发短问候（{scene_label} 场景）。用户刚刚回复了「{{user_text}}」。

请根据用户响应风格**自适应**输出，重点关注：{scene_focus}。

- **简短模糊**（"嗯" / "在" / "嗯嗯" / "咋了"）→ 50-80 字温和回应 + 一句开放话头。
- **好奇精神**（用户主动问场景相关："吃啥好""今天怎么样""你呢"等）→ 150-220 字完整回应（结合 briefing_data_json 里的可用上下文 + 一段闲笔 + 开放话头）。**临时覆盖你平时简短克制的人设约束**，本场景需要信息密度。
- **拒绝场景**（"不饿" / "已经吃了" / "不想睡" / "别烦" 等）→ ≤25 字温柔退出，不要硬塞内容。
- **切换话题**（用户直接问无关的事如要查天气、加日程、记忆）→ 优先回答当前话题，**丢弃**本轮场景内容（pending 仍被消费，避免下次再触发）。

完成本轮后**立即回到日常人设风格**，下一次回复保持简短克制（除非又是场景化触发）。

【缓存的预聚合数据 briefing_data_json】
{{briefing_data_json}}

【对天气 / 新闻补充信息】
如果用户响应风格是"好奇精神"且需要天气 / 新闻——直接调用 enable_search 现查（缓存里没有 weather / news）。

city = {{city}}（搜索时拼【今日 {{city}} 天气】）。"""


class InviteTriggerBase(ProactiveTrigger):
    """模式 B 邀请对话 trigger 共享基类。

    子类必须设：
    * ``name`` （trigger.name + chat_history.proactive_trigger 字段值）
    * ``cron_expr``（``"30 12 * * *"`` 等）—— 或 ``interval_seconds`` /
      ``event_source`` 三选一
    * ``_STAGE1_PROMPT`` （by 子类调 ``make_stage1_prompt`` 生成）

    可选 override：
    * ``enable_search``（默认 False，stage 1 只发短句不需）
    """

    enable_search = False
    _STAGE1_PROMPT: str = ""  # 子类必填

    async def build_system_prompt(self, character: Optional[Character]) -> str:
        return self._STAGE1_PROMPT

    async def resolve_capabilities(self) -> list[str]:
        return []  # stage 1 不需要工具


__all__ = [
    "InviteTriggerBase",
    "make_stage1_prompt",
    "make_stage2_addendum_template",
]
