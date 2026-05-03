"""角色 voice_model 字段的 JSON 解析。

每个 character.voice_model 存一段 JSON 字符串，决定该角色用哪个 TTS provider /
音色 / 是否支持 instruct。空串或 NULL 时，调用方应传入 default 兜底。

JSON 结构（与 backend/tts/__init__.py 的 get_tts_engine 配套使用）：

    CosyVoice:
        {"provider": "cosyvoice", "voice": "longyumi_v3",
         "instruct_supported": false}

    Edge-TTS:
        {"provider": "edge", "voice": "zh-CN-XiaoxiaoNeural",
         "instruct_supported": false}

    SoVITS（占位，未真正接通）:
        {"provider": "sovits", "model_path": "/path/to/model.pth",
         "instruct_supported": true}
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class VoiceConfig:
    """单角色的 TTS 配置。

    Attributes:
        provider:           cosyvoice / edge / sovits
        voice:              音色 ID (cosyvoice / edge) 或模型路径 (sovits)
        instruct_supported: 该音色是否支持 instruct/情感引导。
                            False 时即便上层传了 emotion 也会被忽略。
    """
    provider: str
    voice: str
    instruct_supported: bool = False


def parse_voice_config(
    voice_model: Optional[str], default: VoiceConfig,
) -> VoiceConfig:
    """解析 character.voice_model JSON，失败时返回 default。

    Args:
        voice_model: characters.voice_model 字段值，可能为 None / 空串 / JSON。
        default:     兜底配置（来自 config.yaml 的全局默认）。

    Returns:
        合法的 VoiceConfig；任何异常（None / 空串 / JSON 不合法 / 字段缺失）
        都退化到 default，不抛出。
    """
    if not voice_model or not voice_model.strip():
        return default
    try:
        data = json.loads(voice_model)
        if not isinstance(data, dict):
            logger.warning(
                "voice_model 不是 JSON object，回退默认: %r", voice_model[:60]
            )
            return default
        provider = data.get("provider") or default.provider
        # sovits 用 model_path 作为 voice 字段语义
        if provider == "sovits":
            voice = data.get("model_path") or data.get("voice") or default.voice
        else:
            voice = data.get("voice") or default.voice
        return VoiceConfig(
            provider=provider,
            voice=voice,
            instruct_supported=bool(data.get("instruct_supported", False)),
        )
    except (json.JSONDecodeError, TypeError) as exc:
        logger.warning(
            "voice_model JSON 解析失败 (%s): %r", exc, voice_model[:60]
        )
        return default
