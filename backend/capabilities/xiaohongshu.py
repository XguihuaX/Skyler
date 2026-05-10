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
        "**只做被动 URL 解析**。用户主动贴小红书笔记链接（xiaohongshu.com / "
        "xhslink.com 域名）时调用，返回 title / text / images / author / tags。"
        "**没有**主动搜索 / 推荐流 / 抓评论 / 账号自动化 capability——如果"
        "用户问「帮我搜小红书 X」「拉一下小红书首页」，**如实告诉用户**："
        "「Skyler 不主动爬小红书；你贴具体笔记链接给我就能解析」，**不要瞎编**"
        "结果或假装调了什么 capability。\n\n"
        "拿到内容后用你自己的话总结 / 翻译 / 回答用户问题——不要原样输出 "
        "tags 列表 / 完整 text（小红书笔记常有大量 emoji / 标签噪声）。\n\n"
        "参数：\n- url: 笔记链接（短链 xhslink.com 也支持，自动 follow redirect）\n\n"
        "返回 ``{title, text, images, author, tags, url, source}``；error 字段："
        "``invalid_url`` / ``blocked_by_antibot``（反爬限流） / ``parse_failed``"
        " / ``timeout`` / ``http_error``。"
    ),
    category="media",
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
