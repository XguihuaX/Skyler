"""Central tool registry: maps names to async callables.

Built-in tools are registered at the bottom of this module so any import
of the registry automatically makes them available.  MCP tools can be
added at runtime via ToolRegistry.register().

v3-C: registry 同时存储 OpenAI function-calling schema，供 ChatAgent
统一拼接到 acompletion(tools=...) 参数。register() 的 schema 形参可选，
未提供则该工具不会被自动暴露给 LLM（只能由后端代码主动 call()）。

Usage::

    from backend.tools.registry import ToolRegistry
    result = await ToolRegistry.call("switch_character", user_id="u1", character_id="荧")
    schemas = ToolRegistry.list_schemas()  # → list[dict] for LLM tools=
"""
import inspect
import logging
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

_tools: Dict[str, Callable] = {}
_schemas: Dict[str, dict] = {}


class ToolRegistry:

    @classmethod
    def register(
        cls,
        name: str,
        func: Callable,
        schema: Optional[dict] = None,
    ) -> None:
        """Register *func* under *name*, overwriting any previous entry.

        若 *schema* 给出（OpenAI function-calling 格式），则同时登记到
        schema 表，list_schemas() 可读出供 LLM tools= 使用。
        """
        _tools[name] = func
        if schema is not None:
            _schemas[name] = schema
        logger.debug("registered tool: %s (schema=%s)", name, schema is not None)

    @classmethod
    def get(cls, name: str) -> Callable:
        """Return the callable for *name*.

        Raises:
            KeyError: if no tool with *name* is registered.
        """
        if name not in _tools:
            raise KeyError(f"Tool '{name}' not registered")
        return _tools[name]

    @classmethod
    def list_tools(cls) -> list[str]:
        """Return all registered tool names."""
        return list(_tools.keys())

    @classmethod
    def list_schemas(cls) -> list[dict]:
        """Return all registered OpenAI function-calling schemas."""
        return list(_schemas.values())

    @classmethod
    async def call(cls, tool_name: str, **kwargs: Any) -> Any:
        """Invoke the tool registered as *tool_name* with *kwargs*.

        Supports both async and sync callables.

        Raises:
            KeyError:   unknown tool name.
            TypeError:  wrong arguments for the tool.
            Exception:  any error raised by the tool itself.
        """
        func = cls.get(tool_name)
        if inspect.iscoroutinefunction(func):
            return await func(**kwargs)
        return func(**kwargs)


# ---------------------------------------------------------------------------
# Register built-in tools
# ---------------------------------------------------------------------------

from backend.tools.builtin import (  # noqa: E402
    switch_character,
    clear_short_term,
    SWITCH_CHARACTER_SCHEMA,
    CLEAR_SHORT_TERM_SCHEMA,
)

ToolRegistry.register("switch_character", switch_character, SWITCH_CHARACTER_SCHEMA)
ToolRegistry.register("clear_short_term", clear_short_term, CLEAR_SHORT_TERM_SCHEMA)
