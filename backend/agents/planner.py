# v3-C: PlannerAgent 已从主流程移除，保留文件备用。
# 如需恢复三分类路由，在 ws.py 中重新引入即可。
"""PlannerAgent: lightweight intent classifier + LLM-based task router.

Workflow
--------
1. Run a keyword-based pre-filter.
   – If the message is pure chitchat, return plans=[] without touching the LLM.
   – If task-intent keywords are found, go straight to the LLM.
   – Otherwise fall through to the LLM for ambiguous inputs.
2. Call the LLM with the planner system prompt, instructions, and few-shot
   examples, asking it to emit a JSON array of MCP-style agent calls.
3. Parse and validate the JSON; return plans=[] on any parse failure.

Message contract (in)
---------------------
{
    "agent": "PlannerAgent",
    "payload": {
        "user_id": str,
        "text":    str,
        "context": {}   # optional, unused by planner
    }
}

Message contract (out)
----------------------
{
    "status":  "success" | "error",
    "agent":   "PlannerAgent",
    "payload": {
        "plans": [          # list of MCP-style calls, may be empty
            {
                "agent":   "MemoryAgent" | "ToolAgent",
                "payload": { ... }
            }
        ],
        "intent": "chitchat" | "memory" | "tool" | "unknown",
        "error":  str       # only on error
    }
}
"""
import json
import logging
import re
from datetime import datetime, timezone, timedelta
from typing import List

from backend.agents.base import IAgent
from backend.config import get_planner_model
from backend.config.prompts import (
    PLANNER_AGENT_FEW_SHOT,
    PLANNER_AGENT_INST,
    PLANNER_AGENT_SYSPROMPT,
)
from backend.llm.client import LLMError, call_llm

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Beijing time helper
# ---------------------------------------------------------------------------

_CST = timezone(timedelta(hours=8))


def _now_cst() -> str:
    return datetime.now(_CST).strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------------------
# Lightweight intent classifier
# ---------------------------------------------------------------------------

# Keywords that strongly signal a structured task — skip chitchat bypass.
_TASK_RE = re.compile(
    r"提醒|闹钟|定时|alarm|计划|待办|todo"
    r"|记住|记得|记录|帮我记|添加记忆|删除记忆|查.*记忆|查.*记录"
    r"|偏好|喜好|personality|preference"
    r"|切换.*角色|角色.*切换|switch.*character"
    r"|清空.*记忆|清空.*聊天|clear.*short",
    re.IGNORECASE,
)

# Patterns that are unmistakably pure chitchat — bypass LLM entirely.
_CHITCHAT_RE = re.compile(
    r"^(你好|哈喽|嗨|hi|hello|hey|早上好|早安|晚安|晚上好|下午好|午安"
    r"|好的|嗯|嗯嗯|哦|哈哈|呵呵|哈|😊|👍|谢谢|感谢|再见|拜拜|bye"
    r"|好久不见|最近怎么样|你还好吗|没事|没什么|随便聊聊"
    r"|聊天|说说话|陪我说话|陪我聊天"
    r")[\s，。！？~～…]*$",
    re.IGNORECASE,
)


def _classify(text: str) -> str:
    """Return 'chitchat', 'task', or 'unknown'."""
    stripped = text.strip()
    if _TASK_RE.search(stripped):
        return "task"
    if _CHITCHAT_RE.match(stripped):
        return "chitchat"
    # Very short messages with no structural keyword are likely chitchat.
    if len(stripped) <= 4 and not _TASK_RE.search(stripped):
        return "chitchat"
    return "unknown"


# ---------------------------------------------------------------------------
# JSON extraction helpers
# ---------------------------------------------------------------------------

def _strip_fences(raw: str) -> str:
    """Remove markdown code fences if present."""
    raw = raw.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        # parts[1] is the content between first pair of fences
        raw = parts[1] if len(parts) >= 2 else raw
        if raw.startswith("json"):
            raw = raw[4:]
    return raw.strip()


_VALID_AGENTS = {"MemoryAgent", "ToolAgent"}


def _validate_plans(raw_list: list) -> List[dict]:
    """Keep only well-formed plan items."""
    valid = []
    for item in raw_list:
        if not isinstance(item, dict):
            continue
        agent = item.get("agent")
        payload = item.get("payload")
        if agent not in _VALID_AGENTS:
            logger.debug("PlannerAgent: ignoring unknown agent '%s'", agent)
            continue
        if not isinstance(payload, dict):
            logger.debug("PlannerAgent: item for '%s' has non-dict payload", agent)
            continue
        valid.append({"agent": agent, "payload": payload})
    return valid


def _parse_plans(raw: str) -> List[dict]:
    """Parse LLM output into a validated list of plan dicts.

    Returns [] on any error so that the pipeline can still proceed.
    """
    try:
        cleaned = _strip_fences(raw)
        parsed = json.loads(cleaned)
        if not isinstance(parsed, list):
            logger.warning("PlannerAgent: LLM returned non-list JSON (%s)", type(parsed))
            return []
        return _validate_plans(parsed)
    except json.JSONDecodeError as exc:
        logger.warning("PlannerAgent: JSON parse failed — %s | raw=%r", exc, raw[:200])
        return []


# ---------------------------------------------------------------------------
# PlannerAgent
# ---------------------------------------------------------------------------

class PlannerAgent(IAgent):

    async def handle(self, message: dict) -> dict:
        """Classify intent and return a list of agent call plans."""
        payload = message.get("payload", {})
        user_id: str = payload.get("user_id", "")
        text: str = payload.get("text", "")

        if not user_id or not text:
            return {
                "status": "error",
                "agent": "PlannerAgent",
                "payload": {
                    "error": "payload must contain non-empty user_id and text",
                    "plans": [],
                    "intent": "unknown",
                },
            }

        # ---- lightweight pre-filter ----
        intent = _classify(text)

        if intent == "chitchat":
            logger.debug("PlannerAgent: chitchat bypass for user %s", user_id)
            return {
                "status": "success",
                "agent": "PlannerAgent",
                "payload": {"plans": [], "intent": "chitchat"},
            }

        # ---- LLM planning ----
        user_prompt = (
            PLANNER_AGENT_INST.format(now_str=_now_cst(), user_id=user_id)
            + "\n\n"
            + PLANNER_AGENT_FEW_SHOT
            + "\n\n用户输入：" + text
        )

        planner_model = get_planner_model()
        logger.info("PlannerAgent calling LLM (model=%s)", planner_model)
        try:
            response = await call_llm(
                messages=[
                    {"role": "system", "content": PLANNER_AGENT_SYSPROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                model=planner_model or None,
                stream=False,
            )
            raw_content: str = response.choices[0].message.content or ""
            plans = _parse_plans(raw_content)

            # Derive three-class intent from the plan list
            if not plans:
                derived_intent = "chitchat"
            else:
                agents_used = {p["agent"] for p in plans}
                derived_intent = "tool" if "ToolAgent" in agents_used else "memory"

            return {
                "status": "success",
                "agent": "PlannerAgent",
                "payload": {
                    "plans": plans,
                    "intent": derived_intent,
                },
            }

        except LLMError as exc:
            logger.error("PlannerAgent LLM error for user %s: %s", user_id, exc)
            return {
                "status": "error",
                "agent": "PlannerAgent",
                "payload": {"error": str(exc), "plans": [], "intent": intent},
            }
        except Exception as exc:
            logger.exception("PlannerAgent unexpected error for user %s", user_id)
            return {
                "status": "error",
                "agent": "PlannerAgent",
                "payload": {
                    "error": f"Internal error: {exc}",
                    "plans": [],
                    "intent": intent,
                },
            }
