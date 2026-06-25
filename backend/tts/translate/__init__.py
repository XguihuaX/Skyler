"""TTS 翻译层 — 把 LLM 输出按 voice tts_language 转成目标语种送合成。

A2 架构:LLM 按 character.response_language 输出(默 'zh'),翻译层负责
源语种 → 目标语种(tts_language)。
  translate_for_tts(text, dst, char_id, src) → str | None
    None = 翻译失败/超时,caller 应跳过该句 TTS 并推 system_warning 事件。

Config(config.yaml · 永不入 stage):
  translate:
    provider: qwen-mt      # 默认;复用 DashScope 凭证 · deepl 为备选
    timeout_ms: 1500       # 每句翻译超时阈值
    deepl:                 # provider=deepl 时才用
      endpoint: "https://api-free.deepl.com/v2/translate"

凭证(.env · 永不入 stage):
  qwen-mt → DASHSCOPE_API_KEY + DASHSCOPE_BASE_URL(已驱动全项目 LLM · 复用)
  deepl   → DEEPL_API_KEY(备选 · 需单独申请)
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def _get_provider():
    """按 config.yaml translate.provider 选 provider · 默认 qwen-mt。

    qwen-mt 复用 DashScope 凭证(全项目 LLM 已用)· deepl 为备选。
    未知 provider 名 → 回落 qwen-mt(不 raise · 避免配错全静音)。
    """
    from backend.config import get_settings, load_config_yaml

    cfg = load_config_yaml().get("translate") or {}
    provider_name = str(cfg.get("provider") or "qwen-mt").strip().lower()
    settings = get_settings()

    if provider_name == "deepl":
        from backend.tts.translate.deepl import DeepLProvider
        deepl_cfg = cfg.get("deepl") or {}
        return DeepLProvider(
            api_key=settings.deepl_api_key,
            endpoint=deepl_cfg.get("endpoint", ""),
        )

    # 默认 qwen-mt(含未知 provider 名回落)
    from backend.tts.translate.qwen_mt import QwenMTProvider
    qwen_cfg = cfg.get("qwen_mt") or {}
    return QwenMTProvider(
        api_key=settings.dashscope_api_key,
        base_url=settings.dashscope_base_url,
        model=qwen_cfg.get("model", "qwen-mt-turbo"),
    )


async def translate_for_tts(
    text: str,
    dst: str,
    char_id: Optional[int] = None,
    src: str = "zh",
) -> Optional[str]:
    """翻译 text 到 dst 语种,供 TTS 合成用。

    Args:
        text:    源语言文本(已经过 strip_all_for_tts 清洗)。
        dst:     目标语种 'ja' / 'en'。
        char_id: 日志用,无强制要求。
        src:     源语种(默 'zh';由 caller 传 character.response_language)。

    Returns:
        翻译后文本,或 None(失败/超时)。None 时 caller 应 skip synth。
    """
    if not text or not text.strip():
        return None

    from backend.config import load_config_yaml
    cfg = load_config_yaml().get("translate") or {}
    timeout_ms = int(cfg.get("timeout_ms", 1500))

    provider = _get_provider()
    try:
        result = await asyncio.wait_for(
            provider.translate(text, src=src, dst=dst),
            timeout=timeout_ms / 1000,
        )
        return result or None
    except asyncio.TimeoutError:
        logger.warning(
            "[translate] timeout after %dms dst=%s char_id=%s preview=%r",
            timeout_ms, dst, char_id, text[:60],
        )
        return None
    except Exception:
        logger.exception(
            "[translate] failed dst=%s char_id=%s preview=%r",
            dst, char_id, text[:60],
        )
        return None
