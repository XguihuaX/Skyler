"""qwen-mt 机器翻译 provider(DashScope · OpenAI 兼容端点)。

A2 翻译层默认 provider。复用全项目 LLM 已用的 DashScope 凭证
(settings.dashscope_api_key + dashscope_base_url),不新增凭证。

调用形态(官方 · OpenAI 兼容 /compatible-mode/v1/chat/completions):
  POST {base_url}/chat/completions
  body = {
    "model": "qwen-mt-turbo",
    "messages": [{"role": "user", "content": <待翻译文本>}],
    "translation_options": {"source_lang": "Chinese", "target_lang": "Japanese"},
  }
  ↑ translation_options 平铺在 body 顶层(OpenAI SDK 里走 extra_body · 裸 HTTP 直接放 body)。
  qwen-mt 是**机器翻译专用模型**,非通用 LLM · 实时调用(非 Batch)。

lang 码:qwen-mt 用**英文语种全名(首字母大写)**,非 ISO 码。
  zh → Chinese · ja → Japanese · en → English

兜底(防 httpx 未捕获异常重演):
  - key 空 → 直接 raise(不发请求)· 上层 translate_for_tts 捕获 → None → skip + warning
  - HTTP 4xx/5xx / 超时 / 非预期结构 → raise · 同上兜底
"""
from __future__ import annotations

import logging

import httpx

from backend.tts.translate.base import TranslateProvider

logger = logging.getLogger(__name__)

# qwen-mt 语种代码:ISO-639-1 内部码 → qwen-mt 英文语种全名
_LANG_MAP: dict[str, str] = {
    "zh": "Chinese",
    "ja": "Japanese",
    "en": "English",
}

_DEFAULT_MODEL = "qwen-mt-turbo"


class QwenMTProvider(TranslateProvider):
    """DashScope qwen-mt-turbo 翻译 provider · 实时调用。"""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str = _DEFAULT_MODEL,
    ) -> None:
        self._api_key = api_key
        # base_url 形如 https://dashscope.aliyuncs.com/compatible-mode/v1
        self._base_url = (base_url or "").rstrip("/")
        self._model = model or _DEFAULT_MODEL

    async def translate(self, text: str, src: str, dst: str) -> str:
        # 兜底①:key 空 → 不发请求,直接 raise(上层捕获 → None 兜底)
        if not self._api_key:
            raise RuntimeError(
                "qwen-mt: dashscope_api_key empty · skip request (fallback None)"
            )
        if not self._base_url:
            raise RuntimeError(
                "qwen-mt: dashscope_base_url empty · skip request (fallback None)"
            )

        src_code = _LANG_MAP.get(src.lower(), src)
        dst_code = _LANG_MAP.get(dst.lower(), dst)

        url = f"{self._base_url}/chat/completions"
        body = {
            "model": self._model,
            "messages": [{"role": "user", "content": text}],
            "translation_options": {
                "source_lang": src_code,
                "target_lang": dst_code,
            },
        }
        # trust_env=False:绕过 shell HTTP(S)_PROXY · 与 gsv.py / deepl.py 同款
        async with httpx.AsyncClient(trust_env=False) as client:
            resp = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
                timeout=10.0,  # 硬上限;真实超时由 translate_for_tts 的 asyncio.wait_for 控
            )
        # 兜底②:4xx/5xx → raise_for_status 抛 · 上层捕获兜底
        resp.raise_for_status()
        data = resp.json()
        # 兜底③:结构不符(无 choices / content)→ KeyError/IndexError 抛 · 上层兜底
        return data["choices"][0]["message"]["content"]
