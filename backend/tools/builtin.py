"""Built-in tools available without any external MCP server.

每个 function 都是 async，接受 ToolRegistry 中登记 schema 所声明的 keyword
参数，成功返回可序列化的 dict，失败抛 ValueError / RuntimeError。

v3-C：每个工具同时导出 OpenAI function-calling schema 常量，注册时一并写入
ToolRegistry，从而被 ChatAgent 自动暴露给 LLM。schema 中刻意不暴露 user_id
等会话级参数 —— 这些由 ChatAgent._execute_tool 在执行时注入。
"""
from backend.config.prompt_manager import prompt_manager
from backend.memory.short_term import short_term_memory


async def switch_character(user_id: str, character_id: str) -> dict:
    """Switch the active character for *user_id* to *character_id*.

    Raises:
        ValueError: if *character_id* is not registered in characters.yaml.
    """
    success = prompt_manager.switch_character(user_id, character_id)
    if not success:
        raise ValueError(f"未知角色: {character_id!r}")
    return {"message": f"角色已切换为 {character_id}", "character_id": character_id}


async def clear_short_term(user_id: str) -> dict:
    """Discard all short-term conversation history for *user_id*."""
    await short_term_memory.clear(user_id)
    return {"message": "短期记忆已清空"}


# ---------------------------------------------------------------------------
# OpenAI function-calling schemas（暴露给 LLM 的形参不含 user_id）
# ---------------------------------------------------------------------------

SWITCH_CHARACTER_SCHEMA = {
    "type": "function",
    "function": {
        "name": "switch_character",
        "description": (
            "切换当前会话使用的角色。仅在用户明确表达'切换/换/变成 XX 角色'"
            "时调用，否则不要使用。调完后请用一两句简短自然的中文确认。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "character_id": {
                    "type": "string",
                    "description": (
                        "目标角色的标识，对应 characters.yaml 中已定义的"
                        "角色名（如 'Momo'、'荧'、'胡桃' 等）。"
                    ),
                },
            },
            "required": ["character_id"],
        },
    },
}

CLEAR_SHORT_TERM_SCHEMA = {
    "type": "function",
    "function": {
        "name": "clear_short_term",
        "description": (
            "清空当前用户的短期对话缓冲（仅清近端 turns，不动长期记忆/数据库）。"
            "仅在用户明确说'清空对话/重新开始/忘掉刚才的话题'等时调用。"
        ),
        "parameters": {"type": "object", "properties": {}},
    },
}
