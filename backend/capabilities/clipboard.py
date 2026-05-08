"""v3-G chunk 3a — 剪贴板 capability。

3 个 capability，全 CHAT_AGENT consumer：
* ``clipboard.get_recent(n=5)``        —— 拿最近 N 条剪贴板（默认 5，max 20）
* ``clipboard.summarize(item_index=0)`` —— LLM 对某条总结
* ``clipboard.translate(item_index=0, target_lang='zh')`` —— LLM 翻译

设计原则
========

* **不自动响应**：spec 关键设计——"用户只想 Momo 在被问到时回应"。capability
  注册让 ChatAgent 在用户提到"刚复制的 / 上面那个"时调；不在剪贴板变化时
  push 提醒。
* ``summarize`` / ``translate`` 走 LLM（``call_llm`` 非流式 + 紧 token 限制）：
  capability 层先拿 item 内容，然后短 prompt 调 LLM 拿结果。失败返 ``error``
  字段，ChatAgent 兜底告诉用户。
"""
from __future__ import annotations

import logging
from typing import Optional

from backend.capabilities import Consumer, TriggerMode, register_capability
from backend.integrations.clipboard import clipboard_watcher

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. clipboard.get_recent
# ---------------------------------------------------------------------------

@register_capability(
    name="clipboard.get_recent",
    display_name="拿最近剪贴板",
    description=(
        "拿最近 N 条剪贴板内容（最新在前）。当用户提到「刚复制的」「上面"
        "那个」「这段」「我刚才复制了什么」时调用。返回 list；每项含 content / "
        "content_type（url / code / plain_text / markdown / json）/ captured_at。"
        "**不要主动调**——只在用户明确提到剪贴板时调。"
    ),
    category="clipboard",
    consumers=[Consumer.CHAT_AGENT],
    trigger_modes=[TriggerMode.ON_DEMAND],
    icon="clipboard",
    parameters_schema={
        "type": "object",
        "properties": {
            "n": {
                "type": "integer", "minimum": 1, "maximum": 20, "default": 5,
                "description": "拿最近 N 条（默认 5，最多 20）",
            },
        },
        "required": [],
    },
)
async def get_recent(n: int = 5, **_kwargs) -> dict:
    items = clipboard_watcher.get_recent(int(n))
    return {
        "count": len(items),
        "items": [it.to_dict() for it in items],
    }


# ---------------------------------------------------------------------------
# 2. clipboard.summarize
# ---------------------------------------------------------------------------

@register_capability(
    name="clipboard.summarize",
    display_name="总结剪贴板某条",
    description=(
        "对最近剪贴板第 item_index 条（默认 0 = 最新）做简洁总结。当用户说"
        "「帮我总结一下刚复制的」「这段说的什么」时调用。返回 ``{summary, "
        "content_type, original_length}``。"
    ),
    category="clipboard",
    consumers=[Consumer.CHAT_AGENT],
    trigger_modes=[TriggerMode.ON_DEMAND],
    icon="file-text",
    parameters_schema={
        "type": "object",
        "properties": {
            "item_index": {
                "type": "integer", "minimum": 0, "default": 0,
                "description": "0 = 最新一条，1 = 倒数第二条…",
            },
        },
        "required": [],
    },
)
async def summarize(item_index: int = 0, **_kwargs) -> dict:
    items = clipboard_watcher.get_recent(20)
    idx = int(item_index)
    if not items or idx >= len(items) or idx < 0:
        return {"error": f"item_index={idx} out of range (have {len(items)} items)"}
    item = items[idx]

    from backend.llm.client import LLMError, call_llm
    prompt = (
        "下面是用户剪贴板里的一段内容。请用 1-2 句话简洁总结主旨；"
        "如果是 url 你就描述这是什么链接；如果是代码就说做什么的；"
        "不要罗列细节。\n\n"
        f"内容（{item.content_type}）：\n```\n{item.content[:4000]}\n```"
    )
    try:
        resp = await call_llm(
            messages=[{"role": "user", "content": prompt}],
            stream=False,
        )
        summary = (resp.choices[0].message.content or "").strip()
    except LLMError as exc:
        return {"error": f"LLM error: {exc}", "content_type": item.content_type}
    return {
        "summary": summary,
        "content_type": item.content_type,
        "original_length": len(item.content),
    }


# ---------------------------------------------------------------------------
# 3. clipboard.translate
# ---------------------------------------------------------------------------

@register_capability(
    name="clipboard.translate",
    display_name="翻译剪贴板某条",
    description=(
        "翻译最近剪贴板第 item_index 条（默认 0 = 最新）。当用户说「翻译"
        "刚复制的」「帮我翻译这段」时调用。target_lang 默认 'zh'（中文），"
        "也可传 'en' / 'ja' 等。返回 ``{translation, source_preview, target_lang}``。"
    ),
    category="clipboard",
    consumers=[Consumer.CHAT_AGENT],
    trigger_modes=[TriggerMode.ON_DEMAND],
    icon="globe",
    parameters_schema={
        "type": "object",
        "properties": {
            "item_index": {
                "type": "integer", "minimum": 0, "default": 0,
                "description": "0 = 最新一条",
            },
            "target_lang": {
                "type": "string", "default": "zh",
                "description": "目标语言代码（zh / en / ja / ko / ...）",
            },
        },
        "required": [],
    },
)
async def translate(
    item_index: int = 0,
    target_lang: str = "zh",
    **_kwargs,
) -> dict:
    items = clipboard_watcher.get_recent(20)
    idx = int(item_index)
    if not items or idx >= len(items) or idx < 0:
        return {"error": f"item_index={idx} out of range (have {len(items)} items)"}
    item = items[idx]
    lang = (target_lang or "zh").strip().lower() or "zh"

    from backend.llm.client import LLMError, call_llm
    lang_human = {
        "zh": "简体中文", "en": "英文", "ja": "日文", "ko": "韩文",
        "fr": "法文", "de": "德文", "es": "西班牙文", "ru": "俄文",
    }.get(lang, lang)
    prompt = (
        f"把下面这段内容翻译成 {lang_human}。**只输出译文**，不加解释、"
        f"不加引号、不要前缀。如果已经是 {lang_human} 就原样返回。\n\n"
        f"原文：\n```\n{item.content[:4000]}\n```"
    )
    try:
        resp = await call_llm(
            messages=[{"role": "user", "content": prompt}],
            stream=False,
        )
        translation = (resp.choices[0].message.content or "").strip()
    except LLMError as exc:
        return {"error": f"LLM error: {exc}", "target_lang": lang}
    return {
        "translation": translation,
        "source_preview": item.content[:100],
        "content_type": item.content_type,
        "target_lang": lang,
    }


__all__ = ["get_recent", "summarize", "translate"]
