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
import logging
import re

logger = logging.getLogger(__name__)

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
    # 6. bugfix-1：函数调用风格 hallucinated tag —— ``<docx.create(filename="...", ...)>``
    #    LLM 把 Python 函数调用语法包进 angle bracket，既不 ``/>`` 自闭合也无
    #    paired close。前 5 条全漏（capability-as-tag 要求 attrs 前有空白；
    #    SUSPICIOUS_TAG_RE 要求闭合或 ``/>``）。
    #
    #    判别特征：``<name`` 后**紧跟** ``(...)``（容许 name 含 ``.``）。HTML
    #    正常 attr 写法是 ``<a href="...">``——name 后接空白和 attr=value，
    #    不会接 ``(``。所以这条对正常 HTML 零误伤。
    #
    #    ``\([^>]*?\)`` 非贪婪匹配第一个 ``)``，避免 ``[...]`` / nested 参数
    #    把范围撑过头。结尾 ``[^>]*?>`` 容许 ``)`` 和 ``>`` 之间还有杂质（如
    #    ``<docx.create(...)?>``）。
    re.compile(
        r"<[a-z_][a-z_0-9.]*\s*\([^>]*?\)[^>]*?>",
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
# emotion strip
#
# chunk 4 hotfix-1 之前：本函数只作 ``strip_all_for_tts`` TTS 路径兜底，
# chat.py ``_parse_emotion`` 流式按句剥已是主路径。
#
# v3.5 chunk 6b hotfix-4：实测发现入库链 ``_update_memory`` /
# ``_save_interrupted_turn`` **没调** ``strip_emotion`` —— ``<emotion>happy
# </emotion>`` 字面文本进 chat_history，由 Part 3 SUSPICIOUS_TAG_RE 兜底剥，
# 但每轮触发 ``[sanitize] suspicious tags`` warning（log 噪声）。本 commit
# 修正：入库链补 ``strip_emotion`` 作合法剥（emotion 是 Skyler 自有 meta
# tag），让 SUSPICIOUS 只兜未知格式。
#
# Regex 容错（对齐 ``_STATE_UPDATE_RE`` 形态）：
#   - 配对 ``<emotion>X</emotion>``：``[\s\S]*?`` 容许 X 含 ``<`` （比旧
#     ``[^<]*`` 更稳，匹配 ``<emotion><thinking>...</thinking></emotion>``
#     这种 LLM 乱嵌套）
#   - 自闭合 ``<emotion/>`` / ``<emotion />``（容许 attrs）
#   - 大小写不敏感
# ---------------------------------------------------------------------------

_EMOTION_BLOCK_RE = re.compile(
    r"<emotion\b[^>]*?/>"                              # 自闭合
    r"|<emotion\b[^>]*?>[\s\S]*?</emotion>",           # 配对
    re.IGNORECASE,
)


# v3.5 chunk 9 Part 0.5：motion strip helper（与 emotion / state_update 同 spirit）
#
# chunk 9 Part 0.5 audit 发现 4 个 Skyler 自有 meta tag 中 motion 漏了
# 写库前 strip：
#
#   meta tag       | TTS chain | 写库链 | 状态
#   -------------- | --------- | ------ | -------------------------------
#   <emotion>      | ✓         | ✓      | hotfix-4 已补
#   <thinking>     | ✓         | ✓      | v3-F 回归修补
#   <state_update> | ✓         | ✓      | chunk 3b 落地即补
#   <motion>       | ✗         | ✗      | **本 commit 补**
#
# motion 由 chat.py ``_parse_motion`` 流式按段 emit Live2D 触发事件给
# 前端，**剥的版本仅 emit 给 TTS**；full_reply 入库时仍含字面文本
# ``<motion>害羞</motion>``，由 chunk 9 hotfix-3 Part 3 SUSPICIOUS_TAG_RE
# 兜底剥 + 每轮 log ``[sanitize] suspicious tags hit=1`` warning（log 噪声）。
#
# 与 emotion 一致语义：配对 ``<motion>X</motion>`` + 自闭合 ``<motion/>``
# / ``<motion />``（容许 attrs），大小写不敏感。

_MOTION_BLOCK_RE = re.compile(
    r"<motion\b[^>]*?/>"                               # 自闭合
    r"|<motion\b[^>]*?>[\s\S]*?</motion>",             # 配对
    re.IGNORECASE,
)


def strip_motion(text: str) -> str:
    """删除所有 ``<motion>X</motion>`` 标签 + 自闭合变体。

    覆盖路径（与 ``strip_emotion`` 同契约）：
      * TTS preprocessor（``strip_all_for_tts``）—— 防 TTS 念出标签
      * 写库前（``_update_memory`` / ``_save_interrupted_turn``）—— 防
        chat_history 入库带字面 motion 文本，避免触发 SUSPICIOUS 兜底
        warning。

    主路径下 ``backend.agents.chat._parse_motion`` 在每句末检测 + emit
    Live2D 动作给前端；写库链这层是双保险（边界漏网：流式 cancel 截断 /
    LLM 多打一次 / 跨句 boundary 落点）。
    """
    if not text:
        return text
    return _MOTION_BLOCK_RE.sub("", text)


def strip_emotion(text: str) -> str:
    """删除所有 ``<emotion>X</emotion>`` 标签 + 自闭合变体。

    覆盖路径：
      * TTS preprocessor（``strip_all_for_tts``）—— 防 cosyvoice 念出标签
      * **写库前**（``_update_memory`` / ``_save_interrupted_turn``，
        hotfix-4 起）—— 防 chat_history 入库带 emotion 字面文本，避免触发
        Part 3 SUSPICIOUS_TAG_RE 兜底的 ``[sanitize] suspicious tags`` warning。

    主路径下 ``backend.agents.chat._parse_emotion`` 在第一句即剥并 emit
    ``emotion_tag`` 消息给前端；写库链这层是双保险（边界漏网：流式 cancel
    截断 / LLM 多打一次 / 跨句 boundary 落点）。
    """
    if not text:
        return text
    return _EMOTION_BLOCK_RE.sub("", text)


def strip_all_for_tts(text: str) -> str:
    """全套 strip：emotion + thinking + state_update + motion + tool_call fallback。

    送 cosyvoice / edge / sovits 之前所有 sentence 必须先经此函数。
    chunk 4 hotfix-1 之前 TTS preprocessor 只覆盖 emotion / thinking /
    state_update 三道；chunk 4 引入 tool_call fallback；chunk 9 Part 0.5
    补 motion——4 个 Skyler 自有 meta tag + tool_call fallback 共 5 道。

    v4 segment 2 §2.3 注:本函数**不剥** ``<ja>`` / ``<en>`` —— 这两个 tag
    是 caller-语义,只有 ``tts_language`` 已知时才知道剥哪个 / 留哪个。
    主路径走 ``extract_tts_text(text, tts_language)`` 在 caller 侧决定。
    本函数仍可对中文路径(无 ja/en tag)安全调用。
    """
    if not text:
        return text
    out = strip_emotion(text)
    out = strip_thinking(out)
    out = strip_state_update(out)
    out = strip_motion(out)
    out = strip_tool_call_fallback(out)
    return out


# ---------------------------------------------------------------------------
# v4 segment 2 — ja / en TTS 语言双轨 tag
#
# tts_language='ja' / 'en' 角色 voice 是日语 / 英语复刻 sample,中文音色差。
# Layer A 模板让 LLM 在中文正文后追加 <ja>日语翻译</ja>:
#   - 中文部分 → WS text_chunk(字幕给用户看)
#   - <ja> 内容 → TTS engine(给用户听)
# 流程:
#   1. ws.py / proactive engine 拿 sentence + character.voice_model.tts_language
#   2. extract_tts_text(sentence, tts_language) → 送 TTS 的实际文本
#   3. strip_ja_en_tags_for_subtitle(strip_all_for_tts(sentence)) → 字幕文本
# 兼容性:
#   - zh 角色(默认):extract_tts_text 等价于 strip_all_for_tts
#   - ja/en 角色没出 tag:fallback 到原文 + log warning(LLM 漏标)
# ---------------------------------------------------------------------------

_JA_TAG_RE = re.compile(r"<ja>([\s\S]*?)</ja>", re.IGNORECASE)
_EN_TAG_RE = re.compile(r"<en>([\s\S]*?)</en>", re.IGNORECASE)

# INV-9 §1 fix (Option A1) · 残留 ja/en 字面 open/close tag 检测器。
# pre-condition:调用前已用 ``_JA_TAG_RE.sub('')`` / ``_EN_TAG_RE.sub('')`` 剥完整
# 闭合块;若仍有 ``<ja|en`` 字面 → 视为半截 / stream 截断。
_PARTIAL_JA_EN_OPEN_RE = re.compile(r"</?(?:ja|en)\b", re.IGNORECASE)


def _has_unclosed_ja_en_tag(text: str) -> bool:
    """检测 text 含残留 ``<ja>`` / ``<en>`` 字面但未完整 paired closure。

    用于 ``extract_tts_text`` 兜底判半截 / stream 截断 → caller skip synth。
    内部先剥完整闭合块,残留字面 tag = 半截 marker。
    """
    if not text:
        return False
    stripped = _JA_TAG_RE.sub("", text)
    stripped = _EN_TAG_RE.sub("", stripped)
    return bool(_PARTIAL_JA_EN_OPEN_RE.search(stripped))


# Phase 2 真机验收 hotfix(2026-05-22)· Unicode script 检测器:
# tts_language=ja + 无 <ja> tag fallback 路径增强 — 区分"LLM 漏标整段中文"
# (无假名 → skip 避免送 ja voice)vs "LLM 漏标但内容确是日语"(含假名 →
# 仍 fallback send)。per PM 真机测试日志 13:39:45-51 暴露:LLM 输出
# "嗯，下午好。「うん、こんにちは。」" 中日混排,sentence stream 切成
# 两句,前句纯中文 + 无 <ja> → 旧 fallback strip_all_for_tts(raw) 整段送
# Fish ja voice → 念中文音色错乱 + 浪费 cost。
#
# 平假名 U+3040-U+309F / 片假名 U+30A0-U+30FF / 半角片假名 U+FF65-U+FF9F /
# 片假名扩展 U+31F0-U+31FF。汉字 U+4E00-U+9FFF 不算"日语 specific"(中日共享)。
def _has_japanese_kana(text: str) -> bool:
    """检测 text 是否含日语假名(平假名 / 片假名 / 半角片假名 / 片假名扩展)。

    返 True 视作"日语内容";返 False 视作"纯中文"(若有汉字)或"纯 ASCII"。
    用于 ``extract_tts_text`` fallback 路径 LLM 漏 <ja> tag 时判断:
      - has_kana=True  → fallback 送 raw(LLM 漏标但内容确是日语)
      - has_kana=False → skip(LLM 漏标中文 → 不送 ja voice + log warning)
    """
    if not text:
        return False
    for ch in text:
        cp = ord(ch)
        if 0x3040 <= cp <= 0x309F:  # 平假名
            return True
        if 0x30A0 <= cp <= 0x30FF:  # 片假名
            return True
        if 0xFF65 <= cp <= 0xFF9F:  # 半角片假名
            return True
        if 0x31F0 <= cp <= 0x31FF:  # 片假名扩展
            return True
    return False


def extract_tts_text(raw_text: str, tts_language: str) -> str:
    """按 tts_language 选实际送 TTS 的文本。

    Args:
        raw_text: LLM 输出原句(已经过 sentence 切分,可能含各种 meta tag)
        tts_language: ``'zh'`` / ``'ja'`` / ``'en'``;未知或 None → 视为 ``'zh'``

    Returns:
        送 TTS 的字符串。
          * zh / default:剥 ``<ja>/<en>`` 整段后走 ``strip_all_for_tts``;残留半截
            ``<ja|en`` 字面 → 返 ``""`` 让 caller skip synth(INV-9 §1 fix PM bug #2)
          * ja:取**所有** ``<ja>...</ja>`` 内容拼接(剥 meta tag 后);半截未闭合
            ``<ja`` → 返 ``""`` skip synth(INV-9 §1 fix PM bug #1);真无 tag(LLM
            漏标整段)→ fallback ``strip_all_for_tts(raw_text)`` + log(降级行为保留)
          * en:同 ja

    Bugfix-segment2-3:从 ``.search`` 改成 ``.findall`` —— ``merge_short_sentences``
    会把多个短意群 sentence 合并成一个 buffer,该 buffer 可含 2+ ``<ja>`` tag。

    INV-9 §1 Option A1 fix(2026-05-22):per INV-8 §1.5.2 sanitize bug audit verdict:
      - PM bug #1 "中日语一起全给 TTS":半截 ``<ja>`` 时 matches=[] 走 fallback
        ``strip_all_for_tts(raw)`` 不剥字面 + 内容混合送 TTS → 加 partial-tag detect
        skip synth
      - PM bug #2 "切 zh voice 仍带日语":``_SUSPICIOUS_TAG_WHITELIST`` 全局豁免在
        zh 路径反作用 → zh 分支显式 ``_JA_TAG_RE.sub('') + _EN_TAG_RE.sub('')`` 剥整段
    """
    if not raw_text:
        return raw_text or ""
    lang = (tts_language or "zh").lower()

    if lang == "ja":
        matches = _JA_TAG_RE.findall(raw_text)
        if matches:
            return "".join(strip_all_for_tts(m).strip() for m in matches if m)
        # INV-9 §1 fix (PM bug #1):半截 <ja> 未闭合 → skip synth(避免中日混送)
        if _has_unclosed_ja_en_tag(raw_text):
            logger.warning(
                "[tts] tts_language=ja but <ja> unclosed (半截/stream 截断), "
                "skip synth: preview=%r", raw_text[:80],
            )
            return ""
        # Phase 2 真机验收 hotfix(2026-05-22)· Unicode script 检测:
        # tts_language=ja + 无 <ja> tag → 看 raw 是否含假名
        #   - 无假名(纯中文 / 纯 ASCII)→ skip + WARNING(LLM 漏标中文 →
        #     不送 ja voice 避免音色错乱 + cost 浪费;原 fallback 行为反作用)
        #   - 含假名 → fallback 送原文(LLM 漏 tag 但内容确是日语)
        cleaned = strip_all_for_tts(raw_text)
        if not _has_japanese_kana(cleaned):
            logger.warning(
                "[tts] tts_language=ja but no <ja> tag and no kana detected; "
                "skip synth (LLM 漏标中文 → 不送 ja voice): preview=%r",
                cleaned[:80],
            )
            return ""
        logger.warning(
            "[tts] tts_language=ja but no <ja> tag; falling back to raw "
            "(含假名,LLM 漏 tag 但内容确是日语): preview=%r",
            cleaned[:80],
        )
        return cleaned

    if lang == "en":
        matches = _EN_TAG_RE.findall(raw_text)
        if matches:
            return "".join(strip_all_for_tts(m).strip() for m in matches if m)
        if _has_unclosed_ja_en_tag(raw_text):
            logger.warning(
                "[tts] tts_language=en but <en> unclosed, skip synth: preview=%r",
                raw_text[:80],
            )
            return ""
        logger.warning(
            "[tts] tts_language=en but no <en> tag found; "
            "falling back to raw sentence(LLM 漏标 en)"
        )
        return strip_all_for_tts(raw_text)

    # zh / unknown — INV-9 §1 fix (PM bug #2):
    # 切 zh voice 时 LLM 可能仍按旧 prompt 输出 <ja>/<en>(prompt 重渲染滞后 / LLM
    # round-trip 学到 ja 锚点) → 必须剥整段不留字面 + 内容。原行为靠 `strip_all_for_tts`
    # + ``_SUSPICIOUS_TAG_WHITELIST`` 白名单豁免,反致 <ja> 整段保留送 zh voice TTS。
    cleaned = _JA_TAG_RE.sub("", raw_text)
    cleaned = _EN_TAG_RE.sub("", cleaned)
    # 兜底:剥完闭合块后仍有 <ja|en 字面 → 半截 / stream 截断 → skip synth
    if _has_unclosed_ja_en_tag(cleaned):
        logger.warning(
            "[tts] tts_language=zh but <ja>/<en> tag literal remains after "
            "block strip (半截), skip synth: preview=%r", raw_text[:80],
        )
        return ""
    return strip_all_for_tts(cleaned)


# INV-9 §6 · Fish s2-pro inline [bracket] emotion markers · per-provider 双重隔离
# (Hard Req · PM lock 2026-05-22 + β inline schema final lock):
#
#   - 生成端(Layer A1 prompt fish 子分支)教 LLM 在 <ja> 内嵌入 [bracket] markers
#   - 接收端(本模块 + _PreprocessingEngine per-provider 分流)决定是否 strip:
#       provider == 'fish' → pass-through(markers 保留送 Fish SDK 原生支持)
#       provider != 'fish' → strip(markers 剥除送 cosyvoice/edge/sovits)
#   - 字幕路径(strip_ja_en_tags_for_subtitle 链尾)— 任何 provider 都剥
#     (用户字幕永远不应出现 [bracket],per INV-8 §1.5.7 Case 6 降级矩阵)
#
# 语法:Fish s2-pro 自然语言 emotion markers 形如 [sarcastic] / [soft chuckle] /
# [whisper] / [gentle] 等,15,000+ tags 不限固定集(per INV-8 §1.3.4)。
# regex 设计:匹配 [<non-bracket-content>] — 不嵌套不允许跨 ]。
_FISH_EMOTION_MARKER_RE = re.compile(r"\[[^\[\]]+\]")


def strip_fish_emotion_markers(text: str) -> str:
    """剥 Fish s2-pro inline [bracket] emotion markers。

    用于 per-provider 接收端:non-Fish provider 调用前必走此函数,避免 CosyVoice /
    Edge / SoVITS 字面念出 "left bracket sarcastic right bracket" 之类。Fish
    provider 路径**跳过**此函数(保留 markers 透传给 Fish SDK 原生处理)。

    字幕路径(``strip_ja_en_tags_for_subtitle`` 链尾)— 跨 provider 一律剥,
    用户看到的字幕永远不含 [bracket]。

    边角:空 [] / 空白 [   ] → 不匹配(_FISH_EMOTION_MARKER_RE 要求 1+ 非括号
    字符)— 这种形态本身是 LLM 错标,无情感语义,保留字面或剥都 OK;选择
    "不剥"避免误剥用户合法中括号(eg. 数学表达式 [n+1])。

    None / 空 → 原样返回(per text_filters 现 strip 函数 convention)。
    """
    if not text:
        return text
    return _FISH_EMOTION_MARKER_RE.sub("", text)


def strip_ja_en_tags_for_subtitle(text: str) -> str:
    """字幕路径用:删 ``<ja>...</ja>`` / ``<en>...</en>`` 整段,留中文正文。

    与 ``extract_tts_text`` 互补:本函数是字幕路径(去掉外语翻译,只留中文),
    ``extract_tts_text`` 是 TTS 路径(只保留外语翻译)。

    INV-9 §6 增强:链尾追加 ``strip_fish_emotion_markers`` — 字幕跨 provider
    一律剥 ``[bracket]`` markers(用户字幕不应出现 marker,per INV-8 §1.5.7
    Case 6 + Hard Req 字幕侧契约)。fish 模式下 LLM 输出形如:
        '"嗯,真好笑。"<ja>[soft chuckle]「ま、いいか。」</ja>'
    走完本函数 = '"嗯,真好笑。"'(剥 <ja>...</ja> 整段 + 兜底剥 [bracket] 残留)。

    None / 空 → 原样返回。
    """
    if not text:
        return text
    out = _JA_TAG_RE.sub("", text)
    out = _EN_TAG_RE.sub("", out)
    # INV-9 §6:字幕跨 provider 一律剥 [bracket](见上 docstring)
    out = strip_fish_emotion_markers(out)
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
#:
#: bugfix-D1：第二条 alternation（自闭合）补 group 2 capture，使 ``_strip_*``
#: callable replacement 可对自闭合分支也读到 tag 名走白名单判断。``findall``
#: 仅被 ``count_suspicious_tags`` 用 ``len(...)`` 消费，分组数变化不破坏现有契约。
SUSPICIOUS_TAG_RE = re.compile(
    r"<([a-z_][a-z_0-9.]*)[^>]*>[\s\S]*?</\1>"     # 配对 tag（\1 反向引用同名）
    r"|<([a-z_][a-z_0-9.]*)[^>]*?/>",              # 自闭合（容许 attrs）
    re.IGNORECASE,
)

#: 白名单：豁免 SUSPICIOUS 剥除的 tag 名（lower-case）。
#:
#: bugfix-D1（2026-05-15）：早期 LLM 在 ja/en TTS 角色（character_id=1 Mai）
#: 上输出完美交替 ``中文。<ja>「日语」</ja>``，几轮后退化成全中文 → "日语
#: voice 念中文"。根因：本兜底层 ``re.sub('', text)`` 一刀切，已被 ws.py
#: ``extract_tts_text`` 合法消费的 ``<ja>``/``<en>`` 也被剥走 → chat_history
#: 入库全中文 → 下一轮 LLM 看自己的 short_term 无 ja 锚点 → 模仿失败 →
#: round-trip 失锚 → 越聊越漏标。
#:
#: 修法：这两个 tag 是 caller-语义（``tts_language`` 已知时才决定剥哪个），
#: 不属于"未知 LLM 格式"范畴 —— 白名单豁免，让上游 ``extract_tts_text`` /
#: ``strip_ja_en_tags_for_subtitle`` 按语言做决定，DB 持久层保留原 marker。
#:
#: 注意：本白名单只影响 ``sanitize_suspicious_tags`` / ``count_suspicious_tags``
#: 两个**剥除** call site。``.search()`` guard（``save_memory`` reject、profile
#: 校验等）仍按原 regex 判定 —— 那些路径意图就是"任何 tag-like 文本一律拒绝"。
_SUSPICIOUS_TAG_WHITELIST = frozenset({"ja", "en"})


def _suspicious_tag_name(m: "re.Match[str]") -> str:
    """从 ``SUSPICIOUS_TAG_RE`` match 提取 tag 名（兼容两条 alternation 分支）。

    配对分支命中 → group(1)；自闭合分支命中 → group(2)。lower-case 返回。
    """
    return (m.group(1) or m.group(2) or "").lower()


def count_suspicious_tags(text: str) -> int:
    """统计可疑 tag 数（不含白名单豁免项，不修改文本）。

    给迁移 / profile_summary 输出验收判定 / 测试断言用。空 / None → 0。
    白名单（``_SUSPICIOUS_TAG_WHITELIST``）命中项不计数，与
    ``sanitize_suspicious_tags`` 实际剥除行为保持对称 —— 避免 caller 看到
    ``count > 0`` 却 sanitize 后内容不变的幻象日志。
    """
    if not text:
        return 0
    return sum(
        1 for m in SUSPICIOUS_TAG_RE.finditer(text)
        if _suspicious_tag_name(m) not in _SUSPICIOUS_TAG_WHITELIST
    )


def sanitize_suspicious_tags(text: str) -> str:
    """剥所有 ``SUSPICIOUS_TAG_RE`` 命中段（除 ``_SUSPICIOUS_TAG_WHITELIST``）。

    空 / None 原样返回。白名单内的 tag（``<ja>...</ja>`` / ``<en>...</en>``
    + 对应自闭合变体）保留原 marker，不参与剥除 —— 见
    ``_SUSPICIOUS_TAG_WHITELIST`` 文档段（bugfix-D1）。

    本函数**不 log** —— caller 负责打 warning + 调出现频。这样：
      * 迁移路径可静默清理（每行命中已合并日志）
      * ws.py 写库前路径上每命中 log 一次 [sanitize] suspicious tags warning
    """
    if not text:
        return text

    def _replace(m: "re.Match[str]") -> str:
        if _suspicious_tag_name(m) in _SUSPICIOUS_TAG_WHITELIST:
            return m.group(0)
        return ""

    return SUSPICIOUS_TAG_RE.sub(_replace, text)


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


# ---------------------------------------------------------------------------
# bugfix-1：code-block-aware 全套 sanitizer
#
# 现有 strip 链 + SUSPICIOUS 兜底已覆盖 99% case，但都不区分文本是否在
# markdown 代码段里。用户偶发会粘贴或讲解 ``<thinking>`` 等合法引用，进
# 代码段就该保留——剥掉会破坏教学/文档场景。
#
# ``sanitize_llm_output`` 流程：
#   1. 把 fenced ``` ```...``` ``` 和 inline ``` `...` ``` 用 placeholder 暂存
#      （markdown_json tool_call fallback 已被 strip_tool_call_fallback 单独
#      识别 + 剥，那条优先于这里执行——这里的 fenced 保护剩下的纯描述用法）
#   2. 跑全套 strip 链（emotion / thinking / state_update / motion / tool_call
#      fallback——含新加的 func-call regex 即 ``<docx.create(...)>``）
#   3. SUSPICIOUS_TAG_RE 兜底剥未知格式
#   4. 还原 placeholder
#
# 用途分工：
#   * ``strip_all_for_tts``：sentence 级别（流式按句剥；句子很少跨代码段）—— 走原路径
#   * ``sanitize_llm_output``：full-message 级别（写库前 / 大段回复整体清理）
# ---------------------------------------------------------------------------

#: fenced code block：``` 三个反引号包裹的整段（可跨行）``` —— 优先级最高
#: （fenced 内部允许 inline `` ` `` 字符）。先扫先存。
_FENCED_CODE_RE = re.compile(r"```[\s\S]*?```")

#: inline code：单/双反引号包裹的短段，不跨行。``\1`` 反向引用保证闭合数一致。
_INLINE_CODE_RE = re.compile(r"(`+)(?:(?!\1).)+?\1")

#: placeholder 形态：``__MOMO_CODE_BLOCK_{n}__``。下划线 + ``MOMO`` 前缀确保
#: 极小概率在 LLM 自然输出里碰撞。
_CODE_BLOCK_PLACEHOLDER = "\x00__MOMO_CODE_BLOCK_{n}__\x00"


def sanitize_llm_output(text: str) -> str:
    """Code-block-aware 全套 sanitize ——剥所有 hallucinated tag，保留代码段。

    覆盖：emotion / thinking / state_update / motion / tool_call fallback
    （含新加的 ``<docx.create(args)>`` 函数调用风格）+ SUSPICIOUS 兜底。

    用法：
      * 写库前对 full_reply 做最后一道清理时调本函数（替代手工组合的
        ``strip_motion(strip_emotion(strip_tool_call_fallback(...)))`` 链）
      * 任何展示给用户的整段文本，过一道本函数防 LLM 新格式从兜底逃逸

    与 ``strip_all_for_tts`` 区别：本函数保留 markdown 代码段（合法引用），
    ``strip_all_for_tts`` 走 sentence 级别不做代码段感知。
    """
    if not text:
        return text

    # Step 1：保护代码段
    placeholders: list[str] = []

    def _stash(match: re.Match) -> str:
        placeholders.append(match.group(0))
        return _CODE_BLOCK_PLACEHOLDER.format(n=len(placeholders) - 1)

    protected = _FENCED_CODE_RE.sub(_stash, text)
    protected = _INLINE_CODE_RE.sub(_stash, protected)

    # Step 2：全套 strip
    out = strip_emotion(protected)
    out = strip_thinking(out)
    out = strip_state_update(out)
    out = strip_motion(out)
    out = strip_tool_call_fallback(out)
    # Step 3：SUSPICIOUS 兜底（未知格式）
    out = sanitize_suspicious_tags(out)

    # Step 4：还原代码段
    for i, raw in enumerate(placeholders):
        out = out.replace(_CODE_BLOCK_PLACEHOLDER.format(n=i), raw)

    return out
