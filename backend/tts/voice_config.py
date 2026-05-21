"""角色 voice_model 字段的 JSON 解析。

每个 character.voice_model 存一段 JSON 字符串，决定该角色用哪个 TTS provider /
音色 / 是否支持 instruct。空串或 NULL 时，调用方应传入 default 兜底。

JSON 结构（与 backend/tts/__init__.py 的 get_tts_engine 配套使用）：

    CosyVoice:
        {"provider": "cosyvoice", "voice": "longyumi_v3",
         "instruct_supported": false, "tts_language": "zh"}

    Edge-TTS:
        {"provider": "edge", "voice": "zh-CN-XiaoxiaoNeural",
         "instruct_supported": false}

    SoVITS（占位，未真正接通）:
        {"provider": "sovits", "model_path": "/path/to/model.pth",
         "instruct_supported": true}

    Fish s2-pro (INV-9 §2 · mode_A only · references[] inline 强制 reference):
        {"provider": "fish", "voice": "mai5min_0033",
         "model": "s2-pro", "tts_language": "ja",
         "reference_audio_path": "tts/fish/参考音频/mai/mai5min_0033.wav",
         "reference_text": "<reference 录音的 transcript>",
         "fish_latency": "balanced"}
        ↑ fish provider 必填 reference_audio_path + reference_text,缺则
          parse_voice_config raise ValueError(per Step 5 决策 1 mode_A only)。
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
        provider:           cosyvoice / edge / sovits / fish
        voice:              音色 ID (cosyvoice / edge) 或模型路径 (sovits) 或
                            voice 别名 (fish,例如 'mai5min_0033';不进 Fish API,
                            仅用于 log / tts_call_log 区分)
        instruct_supported: 该音色是否支持 instruct/情感引导。
                            False 时即便上层传了 emotion 也会被忽略。
        model:              bugfix-3.4: TTS provider 的 model 版本。None →
                            走全局 yaml 默认 (yaml::tts.cosyvoice.model)。
                            非空时优先于 yaml — 让 cosyvoice-v3.5-plus 复刻
                            voice 与 cosyvoice-v3-flash 系统 voice 同 DB 表
                            和谐共存。fish provider 用此字段标 backend
                            ('s2-pro' / 's1' / 'v1.6';本轮 lock 's2-pro')。

    INV-9 §2 新增字段(per INV-8 §1.5.8):

        tts_language:           'zh' (默) / 'ja' / 'en' — 决定 Layer A1 ja/en
                                directive 是否注入 + extract_tts_text 路径。
        reference_audio_path:   fish provider mode_A only 必填,wav 文件路径
                                (relative to repo root or absolute);缺则
                                parse_voice_config raise。
        reference_text:         reference audio 的 transcript;fish 必填。
        fish_latency:           "low" / "normal" / "balanced" (默 balanced,
                                per Step 5 stage 2 实测 ~593ms TTFA);仅 fish
                                provider 使用。
    """
    provider: str
    voice: str
    instruct_supported: bool = False
    model: Optional[str] = None
    # INV-9 §2 新增:
    tts_language: str = "zh"
    reference_audio_path: Optional[str] = None
    reference_text: Optional[str] = None
    fish_latency: str = "balanced"


def parse_voice_config(
    voice_model: Optional[str], default: VoiceConfig,
) -> VoiceConfig:
    """解析 character.voice_model JSON，失败时返回 default。

    Args:
        voice_model: characters.voice_model 字段值，可能为 None / 空串 / JSON。
        default:     兜底配置（来自 config.yaml 的全局默认）。

    Returns:
        合法的 VoiceConfig；JSON 不合法 / 字段缺失退化到 default 不抛。

    Raises:
        ValueError: provider='fish' 但缺 reference_audio_path 或 reference_text
                    (INV-9 §2 · Step 5 决策 1 mode_A only lock — 不静默 fallback)。
    """
    if not voice_model or not voice_model.strip():
        return default
    try:
        data = json.loads(voice_model)
    except (json.JSONDecodeError, TypeError) as exc:
        logger.warning(
            "voice_model JSON 解析失败 (%s): %r", exc, voice_model[:60]
        )
        return default

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
    # bugfix-3.4: model 字段从 voice_model JSON 透传出来 (None = yaml fallback)
    raw_model = data.get("model")
    model = raw_model.strip() if isinstance(raw_model, str) and raw_model.strip() else None

    # INV-9 §2 新增字段
    tts_language_raw = data.get("tts_language") or "zh"
    tts_language = tts_language_raw.lower() if isinstance(tts_language_raw, str) else "zh"
    reference_audio_path = data.get("reference_audio_path")
    reference_text = data.get("reference_text")
    fish_latency_raw = data.get("fish_latency") or "balanced"
    fish_latency = fish_latency_raw.lower() if isinstance(fish_latency_raw, str) else "balanced"

    # INV-9 §2 · fish mode_A only validation (per Step 5 决策 1 lock):
    # 不静默 fallback — 缺 ref 字段直接 raise,让上游(get_tts_engine /
    # _build_engine)失败立即报错,避免 fish 角色配错沉默走 default voice。
    if provider == "fish":
        if not (isinstance(reference_audio_path, str) and reference_audio_path.strip()):
            raise ValueError(
                "voice_config: provider='fish' requires reference_audio_path "
                f"(mode_A only · INV-9 §2 lock); got {reference_audio_path!r}"
            )
        if not (isinstance(reference_text, str) and reference_text.strip()):
            raise ValueError(
                "voice_config: provider='fish' requires reference_text "
                f"(mode_A only · INV-9 §2 lock); got {reference_text!r}"
            )

    return VoiceConfig(
        provider=provider,
        voice=voice,
        instruct_supported=bool(data.get("instruct_supported", False)),
        model=model,
        tts_language=tts_language,
        reference_audio_path=(reference_audio_path.strip()
                              if isinstance(reference_audio_path, str)
                              and reference_audio_path.strip()
                              else None),
        reference_text=(reference_text.strip()
                        if isinstance(reference_text, str)
                        and reference_text.strip()
                        else None),
        fish_latency=fish_latency,
    )
