"""TTS package.

两条调用路径并存：

* ``tts_manager`` —— 旧入口，按角色名 (str) 路由 SoVITS→Edge，被 ws.py 在
  v3-D 之前的版本使用。保留代码以备回滚。

* ``get_tts_engine(voice_model)`` —— v3-D 新入口，按 character.voice_model
  JSON 选择 provider；返回符合 ``TTSBase`` 的实例（``synthesize(text,
  emotion)``）。当前 ws.py 的主路径走这个工厂。

v3-F：所有 ``synthesize`` 调用前会经 ``preprocess_tts_text`` 剥离不读出口
的标记（``*动作*`` / ``(注释)`` / ``<emotion>`` / ``<thinking>`` 等）。

Usage::

    from backend.tts import get_tts_engine
    engine = get_tts_engine(character.voice_model)  # voice_model 可空
    audio = await engine.synthesize(sentence, emotion="开心")
"""
import logging
import re
from typing import AsyncGenerator, List, Optional, Pattern

from backend.config import get_default_voice_config, settings
from backend.tts.base import TTSBase, TTSProvider, split_sentences
from backend.tts.edge import EdgeTTSProvider
from backend.tts.sovits import SoVITSProvider
from backend.tts.voice_config import VoiceConfig, parse_voice_config
from backend.utils.text_filters import strip_all_for_tts

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# v3-F：TTS 文本预处理器
#
# LLM 输出常带不应读出的标记：动作描述 *笑了笑*、注释 (悄声)、情感 / 内心独白
# 标签等。在 synthesize 调用前用一组正则统一剥离，剥后空 / 仅标点 → 跳过合成。
#
# v3-G chunk 4 hotfix-1：``strip_all_for_tts``（text_filters.py）覆盖 emotion /
# thinking / state_update / tool_call_fallback 四道；本模块剩下的 patterns
# 只保留 motion + 动作 / 注释 / 中括号——避免重复 + 在 text_filters 加新格式
# 时不需要同步改这里。顺序：thinking 跨行最先剥（在 strip_all_for_tts 内部
# 第二步），其余无关。
# ---------------------------------------------------------------------------

# 仅保留不在 strip_all_for_tts 内的剩余模式（动作 / 注释 / 中括号 + motion 兜底）
_PREPROCESS_PATTERNS: List[Pattern[str]] = [
    re.compile(r"<motion>[^<]*</motion>", re.IGNORECASE),
    re.compile(r"\*[^*]+\*"),
    re.compile(r"\([^)]+\)"),
    re.compile(r"（[^）]+）"),
    re.compile(r"\[[^\]]+\]"),
    re.compile(r"【[^】]+】"),
]

# Python3 的 \w（str 模式默认 unicode）已覆盖汉字 / 字母 / 数字
_PRONOUNCEABLE_RE = re.compile(r"\w", re.UNICODE)

# 多余空白合并
_WS_RE = re.compile(r"[ \t]{2,}")

# bugfix-D1.1：final guard 用 —— ja/en literal tag 剥除 + 兜底未知 tag 检测。
#
# 上游 ``extract_tts_text(text, tts_language)`` 已经按 ``tts_language`` 提取
# 对应语种的 inner 文本。但当 LLM 输出含未闭合 ``<ja>「...`` 或 stream cancel
# 在 paired tag 中段截断时,fallback 路径 (text_filters.py:327) 会把带字面
# ``<ja>`` 开标签的 raw_text 原样送 TTS → cosyvoice 收到 ``"\n<ja>「...`` →
# 418 InvalidParameter。本 guard 是真正调 API 前最后一道保险。
_JA_EN_LITERAL_RE = re.compile(r"</?(?:ja|en)\b[^>]*>", re.IGNORECASE)
_ANY_TAG_LITERAL_RE = re.compile(r"<[a-z_][a-z_0-9]*[^>]*>", re.IGNORECASE)


def _tts_input_final_guard(text: str) -> Optional[str]:
    """送 TTS provider 前最后一道防线 (bugfix-D1.1)。

    上游有 4 道 strip 链 + ``extract_tts_text`` 按语种提取,理论上不该有 tag
    漏到这里;实测 LLM 输出未闭合 ``<ja>「...`` / stream cancel 截断时,
    ``extract_tts_text`` 的 fallback 分支 (text_filters.py:323-327) 会原样返
    带 ``<ja>`` 开标签的 raw_text。本 guard 兜底:

      1. 剥除字面 ``<ja>`` / ``<en>`` / ``</ja>`` / ``</en>`` (无论闭合与否)
      2. 头尾 strip + 剥多余引号
      3. 空 → 返 ``None`` (caller 跳过 synth,等下一句)
      4. 剥后仍含 ``<name>...`` 形字面 tag → 返 ``None`` (其他未知 tag 漏网)

    返 ``None`` 让 caller 走 "skip synth" 静默降级,与 ``preprocess_tts_text``
    返空串语义对齐 (``_PreprocessingEngine.synthesize`` 会 log + 跳过)。

    Args:
        text: 拟送 TTS provider 的文本 (已经过 ``preprocess_tts_text`` 主链路)。

    Returns:
        清洗后可送的纯文本 / ``None`` 表示丢弃本句。
    """
    if not text:
        return None
    cleaned = _JA_EN_LITERAL_RE.sub("", text)
    # 剥头尾常见 stray 引号 / 空白（LLM 在 paired tag 边界容易残留 ``"\n`` 等）
    cleaned = cleaned.strip().strip('"\'').strip()
    if not cleaned:
        return None
    if _ANY_TAG_LITERAL_RE.search(cleaned):
        return None
    return cleaned


def preprocess_tts_text(text: str) -> str:
    """剥离不应读出口的标记，返回交给 TTS 合成的纯文本。

    Args:
        text: LLM 原文，可能含 ``*动作*`` / ``(注释)`` / ``<emotion>`` /
              ``<thinking>`` / ``<state_update>`` / ``<tool_call>`` /
              ``<function_calls>`` / ``<invoke>`` / ```` ```json ```` 等标记。

    Returns:
        清理后的文本；如果剥离后为空或仅余标点 / 空白 → 返回 ``""``，
        调用方应跳过 ``synthesize``。

    v3-G chunk 4 hotfix-1：先经 ``strip_all_for_tts`` 干掉 LLM 标签全家
    （emotion / thinking / state_update / tool_call fallback），再走本地剩余
    pattern 列表（motion / 动作 / 注释 / 中括号）。这是第三道 strip 链路——
    chat.py 流式按段剥（第一道）+ ws.py 写库前剥（第二道）+ 这里 TTS 兜底
    （第三道）。漏一道就会被 cosyvoice 念出来。

    bugfix-D1.1：链尾追加 ``_tts_input_final_guard`` —— 兜 ``extract_tts_text``
    fallback 路径漏出的字面 ``<ja>``/``<en>`` 开标签 (LLM 未闭合 / 流式截断
    场景),拦截前 cosyvoice 收到字面 tag → 418 InvalidParameter。返 ``None``
    时本函数返 ``""``,与现有 "empty → skip synth" 契约对齐,caller 无感知。
    """
    if not text:
        return ""
    out = strip_all_for_tts(text)
    for pat in _PREPROCESS_PATTERNS:
        out = pat.sub("", out)
    # 行内多空格合并；保留换行（CosyVoice 不在意，且 split_sentences 上游已切句）
    out = _WS_RE.sub(" ", out).strip()
    if not out or not _PRONOUNCEABLE_RE.search(out):
        return ""
    guarded = _tts_input_final_guard(out)
    if guarded is None:
        logger.warning(
            "[tts] final_guard rejected (literal tag / empty after strip) raw=%r out=%r",
            text[:80], out[:80],
        )
        return ""
    return guarded


class TTSManager:
    """Orchestrates SoVITS → EdgeTTS fallback and sentence-level synthesis."""

    def __init__(self) -> None:
        self._sovits = SoVITSProvider()
        self._edge   = EdgeTTSProvider()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _sovits_enabled(self) -> bool:
        """Return True when a SoVITS API URL is configured."""
        return bool(settings.sovits_api_url.strip())

    async def _synthesize_one(self, sentence: str, character: str) -> bytes:
        """Try SoVITS; fall back to EdgeTTS on any error."""
        # v3-F：剥离动作 / 注释 / 标签后再合成；空 → 跳过该句返回 b""
        cleaned = preprocess_tts_text(sentence)
        if not cleaned:
            return b""
        if self._sovits_enabled():
            try:
                return await self._sovits.synthesize(cleaned, character)
            except Exception as exc:
                logger.warning(
                    "SoVITS failed (%s), falling back to EdgeTTS for: %r",
                    exc, cleaned,
                )
        return await self._edge.synthesize(cleaned, character)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def synthesize(self, text: str, character: str) -> bytes:
        """Split *text* into sentences, synthesise each, return concatenated audio.

        Args:
            text:      Full utterance to synthesise.
            character: Active character name (controls voice selection).

        Returns:
            Concatenated audio bytes (WAV/MP3 depending on active backend).
            Returns b"" for empty or whitespace-only input.
        """
        if not text.strip():
            return b""
        sentences = split_sentences(text)
        chunks = []
        for sentence in sentences:
            chunk = await self._synthesize_one(sentence, character)
            if chunk:
                chunks.append(chunk)
        return b"".join(chunks)

    async def stream(
        self, text: str, character: str
    ) -> AsyncGenerator[bytes, None]:
        """Yield one audio chunk per sentence as soon as it is synthesised.

        Allows the caller to begin playback before the full text is processed.

        Args:
            text:      Full utterance.
            character: Active character name.

        Yields:
            Non-empty bytes objects, one per sentence.
        """
        if not text.strip():
            return
        sentences = split_sentences(text)
        for sentence in sentences:
            chunk = await self._synthesize_one(sentence, character)
            if chunk:
                yield chunk


# Module-level singleton used throughout the application.
tts_manager = TTSManager()


# ---------------------------------------------------------------------------
# v3-D：基于 character.voice_model 的工厂
# ---------------------------------------------------------------------------


class _LegacyProviderAdapter(TTSBase):
    """把旧 ``TTSProvider`` (signature: text, character) 适配成 ``TTSBase``。

    新接口签名是 (text, emotion)，旧 provider 没有 emotion 概念 —— 直接忽略，
    用 ``character`` 字段保存原 voice ID/路径，让旧代码继续按字符串路由。
    旧 provider 抛异常时返回 None，复用新接口的"静默降级"语义。
    """

    def __init__(self, inner: TTSProvider, character: str) -> None:
        self._inner = inner
        self._character = character

    async def synthesize(
        self, text: str, emotion: str = "默认",
    ) -> Optional[bytes]:
        if not text or not text.strip():
            return None
        try:
            audio = await self._inner.synthesize(text, self._character)
            return audio or None
        except Exception as exc:
            logger.warning(
                "Legacy TTS provider failed (%s) for character=%s: %s",
                type(self._inner).__name__, self._character, exc,
            )
            return None


class _PreprocessingEngine(TTSBase):
    """v3-F：在转交给真实 engine 之前跑 ``preprocess_tts_text``。

    剥离后空文本 → 直接返回 None，跳过下游网络调用。所有 ``get_tts_engine``
    返回的实例都被这一层包住，调用方无需感知。
    """

    def __init__(self, inner: TTSBase) -> None:
        self._inner = inner

    async def synthesize(
        self, text: str, emotion: str = "默认",
    ) -> Optional[bytes]:
        cleaned = preprocess_tts_text(text)
        if not cleaned:
            logger.info("[tts] synth skipped (empty after strip) raw=%r", text[:80])
            return None
        # v3-G chunk 4 hotfix-1：日志验收点。e2e 跑场景时检查这一行，确保
        # synth_text 不带 <tool_call> / <invoke> / <function_calls> /
        # <state_update> / <emotion> / <thinking> / json 标签。
        logger.info("[tts] synth_text=%r emotion=%s", cleaned[:120], emotion)
        return await self._inner.synthesize(cleaned, emotion=emotion)


def _build_engine(voice_model: Optional[str] = None) -> TTSBase:
    """按 voice_model 构造未包装的真实 engine。"""
    default = VoiceConfig(**get_default_voice_config())
    cfg = parse_voice_config(voice_model, default)

    # bugfix-3.3.1: 真机走查 hint —— 一行明确 resolved voice 来源,免去
    # 再去翻 voice_model JSON。``source`` 不严格区分 "用户故意写了一致的
    # voice_model" 与 "走 default" (二者 cfg.voice 都等于 default.voice),
    # 但 99% 场景这正是用户想看的"per-character 有没生效"。
    source = (
        "yaml_default"
        if (not voice_model or not voice_model.strip()
            or cfg.voice == default.voice and cfg.provider == default.provider)
        else "character_db"
    )
    logger.info(
        "[TTS] synthesize voice=%s provider=%s model=%s source=%s instruct=%s",
        cfg.voice, cfg.provider, cfg.model or "<yaml-default>",
        source, cfg.instruct_supported,
    )

    if cfg.provider == "cosyvoice":
        # 延迟导入：dashscope 体积大且只在用到时才需要加载
        from backend.tts.cosyvoice import CosyVoiceTTS
        return CosyVoiceTTS(
            voice=cfg.voice,
            instruct_supported=cfg.instruct_supported,
            model=cfg.model,  # bugfix-3.4: model 透传, v3.5-plus / v3-flash 并存
        )
    if cfg.provider == "fish":
        # INV-9 §3 · Fish s2-pro provider · mode_A only references[] inline。
        # 延迟导入:fish_audio_sdk 体积适中且仅在 fish 角色用到时需要加载。
        # FishTTS 构造时读 reference_audio bytes + Fish API key + 一次性 cached。
        from backend.tts.fish import FishTTS
        return FishTTS(voice_config=cfg)
    if cfg.provider == "edge":
        return _LegacyProviderAdapter(EdgeTTSProvider(), character=cfg.voice)
    if cfg.provider == "sovits":
        # cfg.voice 此时是 model_path，原 SoVITSProvider 仍按 character 名路由 voice
        # 预设字典；保持现状，等真正接入再细化
        return _LegacyProviderAdapter(SoVITSProvider(), character=cfg.voice)

    # 未知 provider — 兜底回 CosyVoice 全局默认
    logger.warning("未知 TTS provider %r，回退 CosyVoice 默认", cfg.provider)
    from backend.tts.cosyvoice import CosyVoiceTTS
    return CosyVoiceTTS(
        voice=default.voice,
        instruct_supported=default.instruct_supported,
    )


def get_tts_engine(voice_model: Optional[str] = None) -> TTSBase:
    """根据 character.voice_model JSON 返回对应 TTS 引擎。

    Args:
        voice_model: characters.voice_model 字段。None / 空串 / 非法 JSON
                     时退化到 config.yaml 全局默认。

    Returns:
        实现 ``TTSBase`` 的实例；调用方只需 ``await engine.synthesize(text,
        emotion=...)``，永远不会抛 (失败返回 None)。返回的 engine 自动跑
        v3-F 文本预处理（剥离 ``*动作*`` / ``(注释)`` / 各种标签），剥后
        空文本会跳过实际合成直接返回 None。
    """
    return _PreprocessingEngine(_build_engine(voice_model))
