"""共享文本过滤工具。

当前只有一个用途：在持久化前剥离 ``<thinking>...</thinking>`` 内心独白
块。v3-F 引入 thinking 标签时只做了 TTS 预处理（不读出来）+ 流式按句剥离
（chat.py 的 ``_parse_thinking``），但写库前没补一道。结果某些边界情况下
（流式 sentence 拼接、被打断截断、跨句边界）原始标签会进入 chat_history，
让前端气泡和未来 profile_summary 重写都看到 LLM 的内心独白。

这里提供独立的、最简单的"丢弃"语义：拿到一段文本，无论里面有没有
thinking、有没有闭合，都返回剥干净的版本（含末尾紧贴的空白）。

设计上跟 chat.py 的 ``_THINKING_RE`` 平行而不复用：
- chat.py 的版本配合 ``_THINKING_OPEN_RE`` / ``_THINKING_CLOSE_RE`` 用于流式
  sentence 边界守护（不能切在未闭合标签里），跟"是否完整闭合"强相关。
- 这里只做"看到完整对就剥"的简单语义，未闭合的开标签留下不动 —— 因为这
  种情况要么是流式中途看到的部分，要么是 reply_parts 被 cancel 截断；前者
  不应该进这里，后者宁可保留半截标签也比丢弃后续内容好（前端层会兜底再
  剥一次，渲染时不会暴露）。
"""
import re

_THINKING_BLOCK_RE = re.compile(
    r"<thinking>[\s\S]*?</thinking>\s*",
    re.IGNORECASE,
)


def strip_thinking(text: str) -> str:
    """删除文本中所有完整的 ``<thinking>...</thinking>`` 块。

    Args:
        text: 原始文本，可能含 0 到 N 个 thinking 块。

    Returns:
        剥干净的文本。无完整块匹配时原样返回。``\\s*`` 顺手吃掉块后紧贴的
        换行 / 空格，避免回复正文前面挂个空行。
    """
    if not text:
        return text
    return _THINKING_BLOCK_RE.sub("", text)


# v3-G chunk 3b：``<state_update mood="..." intimacy_delta="..." thought="..." />``
# 自闭合标签，紧贴 ``<emotion>`` 之后由 LLM 可选输出。chat.py 按段剥离 + ws.py
# 写库前再剥 + TTS preprocessor（本函数）第三道双保险，避免标签漏进朗读。
#
# Regex 容错：
#  - 标准自闭合 ``<state_update ... />``
#  - 容错带文本闭合 ``<state_update ...>...</state_update>``
#  - 大小写不敏感（_re.IGNORECASE）
_STATE_UPDATE_RE = re.compile(
    r"<state_update\b[^>]*?/>"            # 标准自闭合
    r"|<state_update\b[^>]*?>[\s\S]*?</state_update>",  # 容错变体
    re.IGNORECASE,
)


def strip_state_update(text: str) -> str:
    """删除所有 ``<state_update ... />`` 标签（自闭合 + 容错变体）。

    Args:
        text: 原始文本。

    Returns:
        剥干净的文本（含尾随空白合并）。空 / None 原样返回。
    """
    if not text:
        return text
    return _STATE_UPDATE_RE.sub("", text)
