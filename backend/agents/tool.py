# v3-C: 已被 ChatAgent 统一接管，保留文件备用。
"""ToolAgent: dispatches tool calls through ToolRegistry.

Message contract (in)
---------------------
{
    "agent": "ToolAgent",
    "payload": {
        "function": str,   # registered tool name
        "args": { ... }    # kwargs forwarded to the tool
    }
}

Message contract (out)
----------------------
{
    "status":  "success" | "error",
    "agent":   "ToolAgent",
    "payload": {
        "result": <serialisable data>,   # on success
        "error":  str                    # on error only
    }
}
"""
import logging
from typing import Any

from backend.agents.base import IAgent
from backend.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


def _ok(result: Any) -> dict:
    return {"status": "success", "agent": "ToolAgent", "payload": {"result": result}}


def _err(msg: str) -> dict:
    return {"status": "error", "agent": "ToolAgent", "payload": {"error": msg}}


class ToolAgent(IAgent):

    async def handle(self, message: dict) -> dict:
        """Dispatch payload.function to the matching registered tool."""
        payload = message.get("payload", {})
        function: str = payload.get("function", "")
        args: dict = payload.get("args", {}) or {}

        if not function:
            return _err("payload.function is required")

        try:
            result = await ToolRegistry.call(function, **args)  # tool_name positional
            return _ok(result)
        except KeyError as exc:
            return _err(f"unknown tool: {exc}")
        except TypeError as exc:
            return _err(f"wrong arguments: {exc}")
        except ValueError as exc:
            return _err(f"invalid argument: {exc}")
        except Exception as exc:
            logger.exception("ToolAgent error in %s", function)
            return _err(f"internal error: {exc}")
