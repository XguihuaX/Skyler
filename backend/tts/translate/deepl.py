"""DeepL REST API translate provider。

Config(via config.yaml · 永不入 stage):
  translate:
    provider: deepl
    timeout_ms: 1500
    deepl:
      endpoint: "https://api-free.deepl.com/v2/translate"  # free tier
      # endpoint: "https://api.deepl.com/v2/translate"     # pro tier

API key(via .env 或环境变量):
  DEEPL_API_KEY=your-key-here
"""
from __future__ import annotations

import logging

import httpx

from backend.tts.translate.base import TranslateProvider

logger = logging.getLogger(__name__)

# DeepL API 语种代码映射(ISO-639-1 内部码 → DeepL 代码)
_LANG_MAP: dict[str, str] = {
    "zh": "ZH",
    "ja": "JA",
    "en": "EN-US",  # DeepL target 需区分 EN-US / EN-GB
}

_DEFAULT_ENDPOINT = "https://api-free.deepl.com/v2/translate"


class DeepLProvider(TranslateProvider):
    def __init__(self, api_key: str, endpoint: str = _DEFAULT_ENDPOINT) -> None:
        self._api_key = api_key
        self._endpoint = endpoint or _DEFAULT_ENDPOINT

    async def translate(self, text: str, src: str, dst: str) -> str:
        src_code = _LANG_MAP.get(src.lower(), src.upper())
        dst_code = _LANG_MAP.get(dst.lower(), dst.upper())
        async with httpx.AsyncClient(trust_env=False) as client:
            resp = await client.post(
                self._endpoint,
                headers={"Authorization": f"DeepL-Auth-Key {self._api_key}"},
                json={
                    "text": [text],
                    "source_lang": src_code,
                    "target_lang": dst_code,
                },
                timeout=10.0,
            )
        resp.raise_for_status()
        data = resp.json()
        return data["translations"][0]["text"]
