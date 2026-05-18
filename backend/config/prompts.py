"""Static prompt strings used across multiple agents."""

BASE_INSTRUCTION: str = (
    "你收到的输入通常包括三部分：\n"
    "1. 【近期对话记录】：你与用户最近的几轮对话内容，可作为语境参考；\n"
    "2. 消息：用户的当前输入；\n"
    "3. 反馈：工具或其他 Agent 执行的结果，如 ToolAgent 调用工具函数后的反馈，"
    "或 MemoryAgent 的记忆内容、计划建议等。如有则结合消息进行总结表达。\n\n"
    "请你根据这些内容，自然地回复用户。"
    "语气亲切、有分寸，可以简洁，也可以适当延展，但不要啰嗦或堆砌情绪。"
)

# (2026-05-19) MEM_AGENT_PROMPT / PLANNER_AGENT_SYSPROMPT / PLANNER_AGENT_INST /
# PLANNER_AGENT_FEW_SHOT 已删 — PlannerAgent / MemoryAgent / ToolAgent 整套
# 自 v3-C 退出主流程,prompts.py 内此 4 段为孤儿 prompt(LLM 主路径见
# ``backend/agents/prompt/tool_addendum.py`` + ``backend/agents/chat.py``
# MEMORY_TOOLS)。BASE_INSTRUCTION 仍真活,被 ``chat.py`` 与
# ``prompt_manager.py`` 真消费,保留。
