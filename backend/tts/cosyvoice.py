"""CosyVoice (DashScope) TTS 实现。

走与 LLM 同一个 DASHSCOPE_API_KEY，无需额外申请。
返回 WAV 字节（24kHz mono 16bit），失败时返回 None，由调用方静默降级。

实现要点
--------
* DashScope SDK 的 ``SpeechSynthesizer.call()`` 是阻塞接口，所以放进
  ``asyncio.to_thread`` 不堵事件循环。
* 真实参数名是 ``instruction`` 而非 spec 草稿里的 ``instruct_text``，
  ``format`` 用 ``AudioFormat`` 枚举（采样率随枚举值带入）。
* ``instruct_supported=False`` 时不传 ``instruction``，避免 longyumi_v3
  这类不支持引导的音色返回 400。

v3-G' chunk 1：emotion 真生效（走 SSML）
----------------------------------------
之前 ``emotion`` 字段被 SDK 静默忽略（不通过 instruction 也不通过 SSML
的话 SDK 没渠道接收）。改造为：emotion 命中非 neutral 时把文本包成
``<voice emotion="X">…</voice>`` 再调 ``call()``。

DashScope SDK 在 ``speech_synthesizer.py:740-744``（venv 已 audit）每次
``call()`` 内部强制 ``additional_params["enable_ssml"] = True``，所以**不
需要**手动配 enable_ssml；只要文本是合法 SSML 片段，SDK 走 SSML 解析路径
即生效。

XML 转义用 ``xml.sax.saxutils.escape`` —— 正文里带 ``&`` / ``<`` / ``>``
不转的话 SSML 解析器会炸，整段返回 400。

适用音色：v3-flash 系列（longyumi_v3 / longfeifei_v3 / longanqin_v3 /
longanhuan）已 audit 全支持 SSML。详见 config.yaml ``tts.available_voices``
+ ROADMAP v3-G' 章节音色目录。
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional
from xml.sax.saxutils import escape as xml_escape

import dashscope
from dashscope.audio.tts_v2 import AudioFormat, SpeechSynthesizer

from backend.config import get_cosyvoice_config
from backend.tts.base import TTSBase

logger = logging.getLogger(__name__)


# 中文情感词 → CosyVoice 英文情感值。语义见 _normalise_emotion 注释：
# - 命中本表 → 返回映射的英文值
# - 未命中（已是英文枚举如 "happy"，或未知中文如 "困惑"）→ 透传不变
# - 空串 / None → "neutral" 兜底
# 透传策略允许 LLM 直接输出英文枚举跳过映射；未知值由下游 SDK 报错，
# 由 synthesize() 的 try/except 吞掉返回 None，上层静默降级。
EMOTION_MAP: dict[str, str] = {
    "开心": "happy", "高兴": "happy", "快乐": "happy",
    "悲伤": "sad",   "难过": "sad",   "伤心": "sad",
    "愤怒": "angry", "生气": "angry",
    "惊讶": "surprised", "惊喜": "surprised",
    "恐惧": "fearful", "害怕": "fearful",
    "厌恶": "disgusted",
    "平静": "neutral", "默认": "neutral",
}


def _normalise_emotion(raw: str) -> str:
    """中文/英文情感词 → CosyVoice 接受的英文枚举。"""
    if not raw:
        return "neutral"
    if raw in EMOTION_MAP:
        return EMOTION_MAP[raw]
    # 已是英文枚举或未知值 — 直接透传，下游若不识别会返回错误，被 try 兜住
    return raw


class CosyVoiceTTS(TTSBase):
    """单角色一实例；voice 与 instruct_supported 在构造时锁定。"""

    def __init__(
        self,
        voice: Optional[str] = None,
        instruct_supported: bool = False,
    ) -> None:
        cfg = get_cosyvoice_config()
        self.model: str = cfg.get("model", "cosyvoice-v3-flash")
        self.voice: str = voice or cfg.get("default_voice", "longyumi_v3")
        self.instruct_supported: bool = bool(instruct_supported)
        # 模块级单例配置 API key — DashScope SDK 通过模块属性读取
        api_key = os.environ.get("DASHSCOPE_API_KEY", "")
        if api_key:
            dashscope.api_key = api_key
        else:
            logger.warning(
                "DASHSCOPE_API_KEY 未设置，CosyVoice 调用将失败"
            )

    def _wrap_ssml(self, text: str, emotion_en: str) -> str:
        """把正文包成 ``<voice emotion="X">…</voice>``。

        - emotion ∈ {"", "neutral"} → 直接返回原 text，避免无意义 SSML overhead
        - 其他 → ``<voice emotion="happy">escaped text</voice>``

        DashScope SDK 在 ``call()`` 内部已强制 enable_ssml；plain text 仍按
        plain 处理，包含 ``<voice>`` 标签的就走 SSML 路径。
        """
        if not emotion_en or emotion_en == "neutral":
            return text
        return f'<voice emotion="{emotion_en}">{xml_escape(text)}</voice>'

    def _blocking_synthesize(
        self, text: str, emotion_en: str,
    ) -> Optional[bytes]:
        """同步调用 DashScope；放进 to_thread 里执行。"""
        kwargs: dict = {
            "model": self.model,
            "voice": self.voice,
            # 24kHz mono 16bit WAV — 浏览器原生可播
            "format": AudioFormat.WAV_24000HZ_MONO_16BIT,
        }
        # instruct-supported 音色（如 longanhuan）：SSML emotion + 自然语言
        # instruction 双管齐下；instruct 不支持时 (longyumi_v3 / longfeifei_v3
        # / longanqin_v3) 仅用 SSML，避免 SDK 返 400。
        if self.instruct_supported and emotion_en and emotion_en != "neutral":
            kwargs["instruction"] = f"你说话的情感是{emotion_en}。"

        # v3-G' chunk 1：把文本包成 <voice emotion="X">…</voice>，
        # SDK 内部 enable_ssml=true 让真情感生效。
        wrapped = self._wrap_ssml(text, emotion_en)
        if wrapped is not text:
            logger.debug(
                "[CosyVoice SSML] voice=%s emotion=%s wrapped=%r",
                self.voice, emotion_en, wrapped[:120],
            )

        synthesizer = SpeechSynthesizer(**kwargs)
        audio = synthesizer.call(wrapped)
        # SDK 在失败时返回 None / 空 bytes
        if not audio:
            logger.error(
                "CosyVoice 返回空音频 voice=%s len=%d text=%r",
                self.voice, len(text), text[:30],
            )
            return None
        return audio

    async def synthesize(
        self, text: str, emotion: str = "默认",
    ) -> Optional[bytes]:
        """合成单句；任何异常都吞掉，返回 None 由上层静默跳过。"""
        if not text or not text.strip():
            return None
        emotion_en = _normalise_emotion(emotion)
        try:
            return await asyncio.to_thread(
                self._blocking_synthesize, text, emotion_en,
            )
        except Exception as exc:
            logger.error(
                "CosyVoice 合成失败 voice=%s emotion=%s err=%s",
                self.voice, emotion_en, exc,
            )
            return None
