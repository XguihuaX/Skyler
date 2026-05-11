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


# ---------------------------------------------------------------------------
# v3-G chunk 4 hotfix-1：tool_call fallback 标签 strip + partial 检测
#
# chunk 4 引入 ``tool_call_resilience``：流结束后扫 full_reply 里 Qwen / Anthropic
# fallback 形式的 tool 调用，真执行 + 剥 XML 残骸。本来只关心 chat_history /
# 前端 message 不带 XML —— 但流式 TTS 在每句出来时已把句子（含 XML）送进
# cosyvoice 念出来，post-process strip 已无意义。
#
# 修法：把 chunk 4 的 fallback pattern 加到 TTS preprocessor 第三道 strip 链路
# （``preprocess_tts_text`` 调 ``strip_tool_call_fallback``），并在流式
# sentence boundary 检测器（chat.py ``_safe_boundary``）里用
# ``has_partial_open_tag`` 决定是否跨 chunk 等待——同 thinking 待闭合一样。
#
# 工程契约（v3 封盘后）：任何未来新加 LLM 标签输出格式都必须同步加入下面
# ``_TOOL_CALL_FALLBACK_STRIP_PATTERNS`` 或对应 strip 函数 + ``_PARTIAL_OPEN_TAG_RE``。
# 漏一个 → TTS 立刻念出标签内容，链路闭环坏掉。
# ---------------------------------------------------------------------------

_TOOL_CALL_FALLBACK_STRIP_PATTERNS = [
    # 1. Qwen 内部 XML
    re.compile(r"<tool_call\b[^>]*>[\s\S]*?</tool_call>", re.IGNORECASE),
    # 2. Anthropic 风格整段
    re.compile(
        r"<function_calls\b[^>]*>[\s\S]*?</function_calls>", re.IGNORECASE,
    ),
    # 3. Anthropic 风格 invoke 单段（``function_calls`` 包不全时的兜底；
    #    匹配 attr 必须有 ``name="..."`` 防误删合法 ``<invoke>`` 文本）
    re.compile(
        r"<invoke\s+name\s*=\s*[\"'][^\"']+[\"'][^>]*>[\s\S]*?</invoke>",
        re.IGNORECASE,
    ),
    # 4. Markdown JSON：要求 JSON 含 ``"name"`` 字段才算 tool 调用——防止
    #    用户单纯 paste 的 JSON 被误删（与 tool_call_resilience.py 同语义）
    re.compile(
        r"```json\s*(\{[^`]*?\"name\"\s*:\s*\"[^\"]+\"[^`]*?\})\s*```",
        re.IGNORECASE,
    ),
    # 5. v3.5 chunk 6b hotfix-3：capability-name-as-tag。
    #    Qwen 偶发把 capability 名当 XML 标签输出（``<netease.daily_recommend />`` /
    #    ``<netease.daily_recommend>{...}</netease.daily_recommend>``）。tag name
    #    含 ``.`` 才匹配，防误删 HTML ``<div>`` 等普通标签。``\1`` 反向引用
    #    保 open/close tag 一致。
    re.compile(
        r"<([a-z_][a-z_0-9]*\.[a-z_][a-z_0-9]*)(?:\s+[^>]*?)?(?:\s*/>|>[\s\S]*?</\1>)",
        re.IGNORECASE,
    ),
]


def strip_tool_call_fallback(text: str) -> str:
    """删除 chunk 4 fallback 形式的 tool 调用标签。

    覆盖 4 种 pattern：``<tool_call>...</tool_call>`` /
    ``<function_calls>...</function_calls>`` / ``<invoke name="...">...</invoke>`` /
    `````json {"name":...} `````。
    与 ``backend.agents.tool_call_resilience`` 的 detect 模块语义平行——
    那里负责执行 + 剥；这里只负责 strip（TTS 路径不应执行 capability，
    只是不该被念出来）。

    Args:
        text: 原始文本。

    Returns:
        剥干净的文本。空 / None 原样返回。
    """
    if not text:
        return text
    out = text
    for pat in _TOOL_CALL_FALLBACK_STRIP_PATTERNS:
        out = pat.sub("", out)
    return out


# ---------------------------------------------------------------------------
# emotion strip（防御性补：chat.py 已在第一句解析 + 剥，这里只是 TTS 兜底）
# ---------------------------------------------------------------------------

_EMOTION_BLOCK_RE = re.compile(r"<emotion>[^<]*</emotion>", re.IGNORECASE)


def strip_emotion(text: str) -> str:
    """删除所有 ``<emotion>X</emotion>`` 标签。

    主路径下 ``backend.agents.chat._parse_emotion`` 在第一句即剥；本函数仅
    作为 ``strip_all_for_tts`` 的成员防御边界漏网（截断、模型乱打多次等）。
    """
    if not text:
        return text
    return _EMOTION_BLOCK_RE.sub("", text)


def strip_all_for_tts(text: str) -> str:
    """全套 strip：emotion + thinking + state_update + tool_call fallback。

    送 cosyvoice / edge / sovits 之前所有 sentence 必须先经此函数。
    chunk 4 hotfix-1 之前 TTS preprocessor 只覆盖 emotion / thinking /
    state_update 三道；chunk 4 引入 tool_call fallback 后这里成第六道
    strip——少一道就会被念出来。
    """
    if not text:
        return text
    out = strip_emotion(text)
    out = strip_thinking(out)
    out = strip_state_update(out)
    out = strip_tool_call_fallback(out)
    return out


# ---------------------------------------------------------------------------
# 流式 partial-tag 检测：buffer 末尾有未闭合标签时不允许切句
#
# 两类场景：
#   1. 开标签本身还没打完（``<tool_ca`` / ``<emotion`` 等），即 ``[^>]*$``
#      没看到结束 ``>``——下一个 chunk 才会带来 ``ll>``。
#   2. 开标签完整但块内容未闭合（``<tool_call>{"name"...`` 还没 ``</tool_call>``）。
#      此时若 sentence boundary 落在 JSON 中间，会把半截 XML 送 TTS。
#
# 第一类用 ``_PARTIAL_OPEN_TAG_RE`` 单条扫；第二类用 open / close pair 表，
# 任何 open 未匹配到对应 close → 等下一 chunk。``thinking`` 在 chat.py 已
# 单独处理（保留以避免双重 false 触发），但加进表也是 idempotent。
# ---------------------------------------------------------------------------

# 流式中标签往往是逐字符到达：``<tool_ca`` → ``<tool_call`` → ``<tool_call>``。
# 用 ``<[a-zA-Z][^>]*$`` 兜底所有"以 ``<`` + 字母开头的部分尚未结束的标签"
# —— 比按名字白名单 (``<(?:tool_call|...)``) 更稳，新增标签不必同步改这里。
# ``<3``/``<=`` 等数学符号 / emoticon 因不以字母开头不会被误判。
_PARTIAL_OPEN_TAG_RE = re.compile(
    r'<[a-zA-Z][^>]*$'
    r'|```json\s*\{[^`]*$',
    re.DOTALL,
)

# (open_re, close_re) pairs —— open 命中且后面没 close 就视为 buffer 内有
# 未闭合块。``state_update`` 是自闭合（``... />``），不放在这里——它的
# ``[^>]*$`` 部分被 partial open re 兜住已足够。
_OPEN_BLOCK_PAIRS = [
    (
        re.compile(r"<tool_call\b[^>]*>", re.IGNORECASE),
        re.compile(r"</tool_call>", re.IGNORECASE),
    ),
    (
        re.compile(r"<function_calls\b[^>]*>", re.IGNORECASE),
        re.compile(r"</function_calls>", re.IGNORECASE),
    ),
    (
        re.compile(r"<invoke\b[^>]*>", re.IGNORECASE),
        re.compile(r"</invoke>", re.IGNORECASE),
    ),
]

# v3.5 chunk 6b hotfix-3：capability-name-as-tag（``<netease.daily_recommend>``）
# 流式 partial 检测专用。``_OPEN_BLOCK_PAIRS`` 那种 open_re/close_re 写
# 死的 pair 不适用——这里 open 与 close 必须同 tag name 反向引用，逐
# match scan 才能判断。
_CAPABILITY_OPEN_TAG_RE = re.compile(
    # 负 lookbehind ``(?<!/)`` 排除自闭合 ``<x.y />`` —— 自闭合不需要 close tag。
    r"<([a-z_][a-z_0-9]*\.[a-z_][a-z_0-9]*)(?:\s+[^>]*?)?(?<!/)>",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# v3.5 chunk 6b hotfix-3：通用 unknown-tag sanitize（白名单思路）
#
# 黑名单 strip（emotion/thinking/state_update/tool_call/capability_tag）只能
# 覆盖已知模式 —— 未来 LLM 还会发明新格式（实测：``<netease.daily_recommend>``
# 字面文本两次"放日推"测试都中招）。
#
# 本规则反过来：**任何**形如 ``<name>...</name>`` 或 ``<name />`` 的低置信
# XML 都算可疑（assistant 回复正常文本不该出现这类标签），命中即剥。
#
# 仅在 ``role=assistant`` 写库前 + ``_save_interrupted_turn`` partial reply
# 写库前 + ``_regenerate_profile_summary`` 双向应用，不动 ``role=user``
# （用户可能正经发 HTML / code snippet）。
#
# 命中即 log warning（telemetry），让维护者看到 LLM 行为变化 + 调出新模式
# 时能补回黑名单规则。
# ---------------------------------------------------------------------------

#: 任何 ``<name>...</name>``（以字母 / 下划线开头，可含 ``.`` 与 digits / _ 后续字符）
#: 或对应自闭合 ``<name />``。用 ``\1`` 反向引用确保开闭 tag 同名。
#:
#: 设计取舍：
#:   * tag name 必须以字母/下划线开头 → ``<3`` ``<=`` 等 emoticon / 运算符不命中。
#:   * 容许 ``.`` 让 capability-name-as-tag 一并被兜住。
#:   * 不要求 ``.`` —— 这样 ``<tool_call>`` ``<emotion>`` 等也会被命中
#:     （即便已被前面 strip 链清掉，这里再剥一道是双保险）。
SUSPICIOUS_TAG_RE = re.compile(
    r"<([a-z_][a-z_0-9.]*)[^>]*>[\s\S]*?</\1>"     # 配对 tag（\1 反向引用同名）
    r"|<[a-z_][a-z_0-9.]*[^>]*?/>",                # 自闭合（容许 attrs）
    re.IGNORECASE,
)


def count_suspicious_tags(text: str) -> int:
    """统计可疑 tag 数（不修改文本）。

    给迁移 / profile_summary 输出验收判定 / 测试断言用。空 / None → 0。
    """
    if not text:
        return 0
    return len(SUSPICIOUS_TAG_RE.findall(text))


def sanitize_suspicious_tags(text: str) -> str:
    """剥所有 ``SUSPICIOUS_TAG_RE`` 命中段。空 / None 原样返回。

    本函数**不 log** —— caller 负责打 warning + 调出现频。这样：
      * 迁移路径可静默清理（每行命中已合并日志）
      * ws.py 写库前路径上每命中 log 一次 [sanitize] suspicious tags warning
    """
    if not text:
        return text
    return SUSPICIOUS_TAG_RE.sub("", text)


def has_partial_open_tag(text: str) -> bool:
    """流式分句时用：buffer 末尾是否有未闭合标签起始。

    True → 调用方应跳过本次 sentence 切分，等下一个 chunk 把结尾闭合标签
    带进来。False → 可正常 ``_find_boundary``。

    覆盖：
      - 开标签本体未结束（``<tool_call`` 没 ``>``）
      - 开标签完整但块内容未关闭（``<tool_call>{"...`` 没 ``</tool_call>``）

    chat.py 的 ``_safe_boundary`` 已对 ``<thinking>`` 单独做过同语义检查；
    本函数把所有 chunk 4 fallback 标签也覆盖到，避免标签内的 ``。/！/？``
    被当成句号切开。
    """
    if not text:
        return False
    if _PARTIAL_OPEN_TAG_RE.search(text):
        return True
    for open_re, close_re in _OPEN_BLOCK_PAIRS:
        for om in open_re.finditer(text):
            if not close_re.search(text, om.end()):
                return True
    # v3.5 chunk 6b hotfix-3：capability-name-as-tag open 后未闭合
    for om in _CAPABILITY_OPEN_TAG_RE.finditer(text):
        tag_name = om.group(1)
        # 同名 close tag 必须出现在 open 之后
        close_re = re.compile(rf"</{re.escape(tag_name)}>", re.IGNORECASE)
        if not close_re.search(text, om.end()):
            return True
    return False
