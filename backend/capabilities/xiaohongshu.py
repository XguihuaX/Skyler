"""v3.5 chunk 6c — 小红书 URL 被动解析 capability。

**只暴露 1 个 capability**：``xhs.parse_url``。

Spec 曾列 ``xhs.summarize_post`` 作可选 2nd cap，audit 后**撤回**——总结
本就是 LLM 的本职工作，让 LLM 拿 parse_url 结果后自己组合（system prompt
明示），不必单独 capability 增加 surface。

# 工程红线（重申）

**只做被动 URL 解析**。本模块不暴露 search / recommend / login / 评论抓取
等任何主动方法。哪怕后续 prompt / system change 让做，**拒绝**。

红线在三处明文：
* ``backend/integrations/xiaohongshu.py`` 模块头注释
* 本 capability description
* ``docs/xiaohongshu-setup.md``
* ``DESIGN.md §十五之J``（待 chunk 6c docs 步骤补）
"""
from __future__ import annotations

from typing import Any

from backend.capabilities import Consumer, TriggerMode, register_capability
from backend.integrations import xiaohongshu as _xhs


@register_capability(
    name="xhs.parse_url",
    display_name="解析小红书笔记 URL",
    description=(
        "小红书笔记 URL 解析(仅 xiaohongshu.com / xhslink.com 域名,被动解析"
        "不主动爬)。用户贴笔记链接时调用,返 {title, text, images, author, tags}。"
        "用户问『搜小红书/拉首页』等主动场景如实告知『不主动爬,贴具体链接才解析』,"
        "不要假装调用。\n\n"
        "拿到内容后用自己话总结,别原样输出 tag 噪声。\n\n"
        "参数 url:完整笔记链接(短链自动 follow)。"
        "失败 error:invalid_url / blocked_by_antibot / parse_failed / timeout。"
    ),
    category="social",
    consumers=[Consumer.CHAT_AGENT],
    trigger_modes=[TriggerMode.ON_DEMAND],
    icon="link",
    health_check=_xhs.health_check,
    parameters_schema={
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "小红书笔记 URL（xiaohongshu.com 或 xhslink.com）",
            },
        },
        "required": ["url"],
    },
)
async def parse_url(url: str = "", **_kwargs: Any) -> dict:
    if not url or not url.strip():
        return {"error": "missing_url"}
    return await _xhs.parse_post(url.strip())


__all__ = ["parse_url"]
