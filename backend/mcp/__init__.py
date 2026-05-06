"""v3-G chunk 1.5 — MCP 双向集成。

* ``backend/mcp/server.py``  把 CapabilityRegistry → MCP server 暴露给外部
  LLM 工具（Claude Desktop / Cursor / Claude Code 等）
* ``backend/mcp/client.py``  连接外部 MCP server，把对方的 tool 反向注册
  为 capability（统一抽象 → ChatAgent 自动可用）

两层共用同一份 CapabilityRegistry —— 这是统一抽象的关键。
"""
