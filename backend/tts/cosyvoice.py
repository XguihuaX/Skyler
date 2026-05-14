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

v3-G' patch（撤销 chunk 1a SSML emotion 错误）—— emotion 走 instruct
--------------------------------------------------------------------
chunk 1a (de7ebe2) 误把 emotion 包成 ``<voice emotion="X">...</voice>``
SSML，但 DashScope 官方 SSML 标签**没有 emotion 属性**（合法属性只有
voice / rate / pitch / volume / effect / bgm），导致请求要么被静默忽略
要么直接返 400。已撤销 SSML 包装，回到 v3-D 起就一直在用的 **instruct
路径**——SDK 真接受的情感控制通道。

instruct 调用形态（venv 已 audit，不靠印象）：

  ``speech_synthesizer.py:140-167`` SpeechSynthesizer 构造接受
      ``instruction: str`` 字段，max 128 chars。
  ``speech_synthesizer.py:218-219`` 调用时 ``cmd["payload"]["parameters"]
      ["instruction"] = self.instruction``，进入 WebSocket payload。

我们传的字符串是自然语言指令： ``"你说话的情感是{emotion}。"``。系统音色
（含 longanhuan / longanyang）的 instruction **必须严格匹配文档列出的固定
格式**，emotion 与"是"之间**不能**有空格——曾经按"前导空格"误读文档示
例，结果 longanhuan 用不严格格式时会被服务端返 ``InvalidParameter 428``。
参考：https://help.aliyun.com/zh/model-studio/cosyvoice-voice-list 中
longanhuan 段的 Instruct 设置。emotion 用文档列出的 7 个英文枚举：
``neutral / fearful / angry / sad / surprised / happy / disgusted``。

硬约束：**只有 instruct-aware 音色支持此路径**（即 config.yaml 标
``instruct: true`` 的音色，目前只有 ``longanhuan``）。其他音色传 instruction
会被 SDK 返 400。所以 ``_blocking_synthesize`` 显式判 ``instruct_supported``
分两条路。

emotion 白名单：当前 LLM prompt（chat.py _build_emotion_instruction）只
引导 neutral/happy/sad/angry/surprised 5 词。fearful / disgusted 在
EMOTION_MAP 中只为兜底外部输入，**instruct 路径不引发**它们——避免给
没在 LLM 引导列表的情感跑实验性 instruction。
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

import dashscope
from dashscope.audio.tts_v2 import AudioFormat, SpeechSynthesizer

from backend.config import get_cosyvoice_config
from backend.tts.base import TTSBase

logger = logging.getLogger(__name__)


# v3-G' patch: instruct 路径触发的 emotion 白名单。
# - happy / sad / angry / surprised：LLM emotion-instruction 引导用，4 项
# - neutral：等价于"不指定"，按照 v3-D 起的约定不传 instruction
# - fearful / disgusted：当前 LLM prompt 未引导，加进去会派发未验证的实验
#   性 instruction，先排除；未来 prompt 加引导时同步加入此集合
_INSTRUCT_EMOTION_WHITELIST: frozenset[str] = frozenset({
    "happy",
    "sad",
    "angry",
    "surprised",
})


# bugfix-3.4: cosyvoice-v3.5-plus / v3.5-flash 系列 (含用户复刻 voice 跑这两个
# 模型) 当前不支持 ``instruction`` 参数,SDK 调用直接返 ``Engine return error
# code: 418 InvalidParameter``。这里硬性 skip instruction (即便 voice JSON 标
# ``instruct_supported=true``),走 plain text 路径保合成成功。等 DashScope 官
# 方支持 v3.5-plus instruct 后,从这个集合移除。v4.1+ backlog。
_MODELS_WITHOUT_INSTRUCT: frozenset[str] = frozenset({
    "cosyvoice-v3.5-plus",
    "cosyvoice-v3.5-flash",
})


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
        model: Optional[str] = None,
    ) -> None:
        """构造 CosyVoiceTTS。

        Args:
            voice: 音色 ID。None → yaml default_voice。
            instruct_supported: 该音色是否支持 instruct 情感引导。
            model: bugfix-3.4 — DashScope CosyVoice model 版本。None → yaml
                ``tts.cosyvoice.model``。非空时优先于 yaml — 让用户复刻 voice
                (跑 cosyvoice-v3.5-plus) 与系统 voice (跑 v3-flash) 在同一进程
                内并存,不会因 model/voice 不匹配返 418。
        """
        cfg = get_cosyvoice_config()
        self.model: str = model or cfg.get("model", "cosyvoice-v3-flash")
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

    def _blocking_synthesize(
        self, text: str, emotion_en: str,
    ) -> Optional[bytes]:
        """同步调用 DashScope；放进 to_thread 里执行。

        emotion 路由：
          - 音色 ``instruct_supported=True`` 且 emotion 在白名单 → 传
            ``instruction="你说话的情感是X。"`` 走真情感引导
          - 否则（音色不支持 / emotion 未引导 / neutral）→ plain text，emotion
            字段静默丢弃（SDK 没渠道接收，不报错）
        """
        kwargs: dict = {
            "model": self.model,
            "voice": self.voice,
            # 24kHz mono 16bit WAV — 浏览器原生可播
            "format": AudioFormat.WAV_24000HZ_MONO_16BIT,
        }
        # bugfix-3.4: v3.5-plus / v3.5-flash 模型即便 voice 标 instruct_supported
        # 也跑 instruction → 418。这里硬性 skip,走 plain text 保合成成功。
        # 等 DashScope 支持 v3.5-plus instruct 后从 _MODELS_WITHOUT_INSTRUCT 移除。
        model_blocks_instruct = self.model in _MODELS_WITHOUT_INSTRUCT
        emotion_active = (
            self.instruct_supported
            and emotion_en in _INSTRUCT_EMOTION_WHITELIST
            and not model_blocks_instruct
        )
        if emotion_active:
            # 文档严格格式："你说话的情感是{emotion}。"
            # 注意：emotion 与"是"之间**不能**有空格，否则系统音色会返
            # InvalidParameter 428（v3-G' patch 修正）。
            instruction = f"你说话的情感是{emotion_en}。"
            kwargs["instruction"] = instruction
            logger.debug(
                '[CosyVoice instruct] voice=%s emotion=%s instruction="%s"',
                self.voice, emotion_en, instruction,
            )
        elif model_blocks_instruct and emotion_en and emotion_en != "neutral":
            # 明示 log: voice 本来 instruct_supported=True 但 model 整体不支持
            logger.info(
                "[CosyVoice] model=%s 不支持 instruction, voice=%s emotion=%s "
                "→ plain text (v4.1+ DashScope 加 v3.5-plus instruct 后取消)",
                self.model, self.voice, emotion_en,
            )
        else:
            # 三种情况会落这里：音色不支持 instruct / emotion 未在白名单 /
            # emotion=neutral。前两种走 plain，emotion 字段被丢弃；neutral
            # 等价于"不指定"，与 v3-D 起约定一致。
            if emotion_en and emotion_en != "neutral":
                logger.debug(
                    "[CosyVoice plain] voice=%s does not support instruct"
                    " (or emotion %s not whitelisted), emotion ignored",
                    self.voice, emotion_en,
                )

        synthesizer = SpeechSynthesizer(**kwargs)
        audio = synthesizer.call(text)
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
