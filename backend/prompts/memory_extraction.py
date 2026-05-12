"""v3.5 chunk 10 — memory entry 提取 prompt + LLM 调用。

LLM 严格按以下契约输出：

  * 顶层是 **JSON array**（可以为空 ``[]``）
  * 每个 entry 是 dict，含 ``type`` / ``content`` / ``confidence``
  * ``type`` ∈ ``{"fact", "preference", "event", "commitment"}``
  * ``content`` 5-200 中文字符
  * ``confidence`` ∈ [0, 1]
  * **绝不写反推性描述**（chunk 11 14 反推词清单 + chunk 9 治标教训）

模型用 ``get_planner_model()``（qwen-turbo），与 chunk 11 profile 重生
同 LLM。``commit 4`` 接 validator + filter；本 commit 只负责 build
prompt + call LLM + 返 raw string，validator 是下游。

# Markdown fence 容错

LLM 偶发输出 ``\`\`\`json\n[...]\n\`\`\``，validator 端 strip。
"""
from __future__ import annotations

import logging
from typing import Optional

from backend.config import get_planner_model
from backend.llm.client import LLMError, call_llm

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

# 反推性描述清单（与 chunk 11 profile_validator._BACKINFERENCE_KEYWORDS
# 同源，**复制到 prompt 文案**让 LLM 主动避开。validator 会做最终把关
# soft warn 但不 reject）。
_AVOID_KEYWORDS_HINT = (
    "感觉 / 情绪 / 印象 / 陪伴 / 亲密 / 需要被 / 渴望 / 温柔 / "
    "细腻 / 敏感 / 脆弱 / 依赖 / 孤独 / 情感"
)


def build_extraction_prompt(turns: list) -> str:
    """Build LLM prompt 输入。

    Args:
        turns: ``list[ChatTurn]``（或任何有 ``id`` / ``content`` 属性的对象）。
               worker 调用方负责传 ``role='user' kind='normal'`` 过滤后的 turn。

    Returns:
        ready-for ``call_llm`` 的 prompt string。
    """
    msgs_lines: list[str] = []
    for t in turns:
        tid = getattr(t, "id", "?")
        content = (getattr(t, "content", "") or "").strip()
        if not content:
            continue
        # 用 turn id 让 LLM 知道哪条对话产出哪条 entry（虽然当前 schema
        # 不严格 mapping，未来引入 source_turn_id 时直接接 prompt 输出）
        msgs_lines.append(f"[turn={tid}] {content}")
    msgs_block = "\n".join(msgs_lines) if msgs_lines else "(空)"

    return f"""任务：从以下用户最近说过的话中，提取**值得长期记住**的事实条目。

判断标准（严格）：
- 稳定事实（住址 / 职业 / 家人 / 宠物名 / 工作单位）
- 长期偏好（喜欢 / 讨厌某事物，反复出现的每日习惯）
- 承诺 / 计划（deadline / 未来安排 / 约定要做的事）
- 反复出现的话题模式（用户多次提及才显著）

不提取：
- 日常打招呼、单次提问、闲聊问句
- 当下情绪（"今天好累" 单次出现不算）
- 时间感叹、天气评论
- 系统命令 / 工具调用 / 临时请求

输出规则：
1. 输出必须是**合法 JSON 列表**（可以为空 ``[]``）。
2. 每个 entry 严格按 schema：
       {{
         "type":       "fact" | "preference" | "event" | "commitment",
         "content":    "<5-200 中文字符的事实陈述>",
         "confidence": <0-1 浮点>
       }}
3. **绝不写反推性描述**（{_AVOID_KEYWORDS_HINT} 等温度感词）。
4. ``content`` 用第三人称客观陈述（"用户的猫叫 Mochi"，不是"我猫叫
   Mochi"）。
5. ``confidence`` 自评：0.9+ 反复出现 / 用户明确说；0.6-0.9 单次但具
   体；< 0.6 不输出（自我过滤）。
6. 只输出 JSON 数组，不要 markdown 围栏 / 不要解释 / 不要前缀。

输入（role=user only，新增 turn 按时间升序）：
{msgs_block}"""


# ---------------------------------------------------------------------------
# LLM caller
# ---------------------------------------------------------------------------


async def call_extraction_llm(prompt: str) -> Optional[str]:
    """单次调用 qwen-turbo 拿 raw string。失败 → None + log。

    任何 LLM 异常都返 None，worker 内部按"无新 entries"处理；不抛。
    """
    try:
        response = await call_llm(
            messages=[{"role": "user", "content": prompt}],
            model=get_planner_model(),
            stream=False,
        )
        raw = (response.choices[0].message.content or "").strip()
        return raw
    except LLMError as exc:
        logger.error("[extractor_prompt] LLM call failed: %s", exc)
        return None
    except Exception as exc:
        logger.exception(
            "[extractor_prompt] unexpected LLM error: %s", exc,
        )
        return None


__all__ = [
    "build_extraction_prompt",
    "call_extraction_llm",
]
