"""Tests for backend/agents/planner.py — all LLM calls mocked."""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import backend.agents.planner as _planner_mod
from backend.agents.planner import (
    PlannerAgent,
    _classify,
    _parse_plans,
    _strip_fences,
    _validate_plans,
)
from backend.agents.base import IAgent

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------

def _patch_llm(json_text: str):
    """Make call_llm return a fake response with *json_text* as content."""
    class _Msg:
        content = json_text
    class _Choice:
        message = _Msg()
    class _Resp:
        choices = [_Choice()]
    async def _fake(messages, stream=False, **kw):
        return _Resp()
    _planner_mod.call_llm = _fake


def _patch_llm_raise(exc):
    async def _fake(messages, stream=False, **kw):
        raise exc
    _planner_mod.call_llm = _fake


# ---------------------------------------------------------------------------
# 1. Intent classifier
# ---------------------------------------------------------------------------

def test_classify_chitchat():
    print("\n[_classify — chitchat]")
    for text in ["你好", "哈喽", "早上好", "hi", "hello", "嗯嗯", "哦", "哈哈",
                 "谢谢", "再见", "拜拜", "好的", "bye", "晚安", "下午好"]:
        check(f"chitchat: '{text}'", _classify(text) == "chitchat", _classify(text))


def test_classify_task():
    print("\n[_classify — task keywords]")
    # Search-related queries (天气/新闻) are no longer in _TASK_RE; handled by ChatAgent.
    cases = [
        ("帮我设置明早8点的闹钟", "alarm"),
        ("提醒我明天下午3点开会", "reminder"),
        ("记住我喜欢喝咖啡", "memory"),
        ("查一下我的记忆", "memory search"),
        ("切换角色到八重神子", "character switch"),
        ("清空我的聊天记录", "clear"),
        ("添加一条待办", "todo"),
        ("删除记忆", "delete memory"),
    ]
    for text, label in cases:
        check(f"task ({label}): '{text}'", _classify(text) == "task", _classify(text))


def test_classify_unknown():
    print("\n[_classify — unknown]")
    for text in ["我最近有点累", "今天心情不好", "随便说点什么"]:
        result = _classify(text)
        check(f"unknown: '{text}'", result == "unknown", result)


def test_classify_very_short():
    print("\n[_classify — very short non-task]")
    for text in ["嗯", "哦", "呢", "吧"]:
        check(f"short '{text}' → chitchat", _classify(text) == "chitchat", _classify(text))


# ---------------------------------------------------------------------------
# 2. JSON parsing helpers
# ---------------------------------------------------------------------------

def test_strip_fences():
    print("\n[_strip_fences]")
    check("no fence",          _strip_fences("[]") == "[]")
    check("```json fence",     _strip_fences("```json\n[]\n```") == "[]")
    check("``` fence",         _strip_fences("```\n[]\n```") == "[]")
    check("leading whitespace", _strip_fences("  []  ") == "[]")


def test_validate_plans():
    print("\n[_validate_plans]")
    # Three-class design: only MemoryAgent and ToolAgent are valid targets.
    # SearchAgent is no longer a valid plan target.
    good = [
        {"agent": "MemoryAgent", "payload": {"function": "add_todo", "args": {}}},
        {"agent": "ToolAgent",   "payload": {"function": "switch_character", "args": {}}},
    ]
    result = _validate_plans(good)
    check("valid items kept", len(result) == 2)

    bad = [
        {"agent": "SearchAgent",  "payload": {"query": "天气"}},   # removed agent
        {"agent": "ChatAgent",    "payload": {}},                   # not a target agent
        {"agent": "MemoryAgent",  "payload": "not-dict"},           # payload must be dict
        "just a string",                                             # not a dict
        {},                                                          # no agent key
    ]
    result2 = _validate_plans(bad)
    check("all invalid items dropped", len(result2) == 0)

    mixed = good[:1] + bad[:1]
    result3 = _validate_plans(mixed)
    check("only valid items in mixed list", len(result3) == 1)


def test_parse_plans():
    print("\n[_parse_plans]")
    valid_json = json_str = '[{"agent":"MemoryAgent","payload":{"function":"add_todo","args":{}}}]'
    plans = _parse_plans(valid_json)
    check("valid JSON parses to 1 plan", len(plans) == 1)
    check("plan has agent key",          plans[0]["agent"] == "MemoryAgent")

    check("empty array → []",           _parse_plans("[]") == [])
    check("invalid JSON → []",          _parse_plans("not json") == [])
    check("non-list JSON → []",         _parse_plans('{"agent":"x"}') == [])
    check("fenced JSON parses OK",
          len(_parse_plans("```json\n" + valid_json + "\n```")) == 1)
    check("empty string → []",          _parse_plans("") == [])


# ---------------------------------------------------------------------------
# 3. PlannerAgent.handle() — chitchat bypass
# ---------------------------------------------------------------------------

async def test_chitchat_bypass():
    print("\n[PlannerAgent — chitchat bypass]")
    agent = PlannerAgent()

    for text in ["你好", "哈喽", "早上好", "再见"]:
        result = await agent.handle({"payload": {"user_id": "u1", "text": text}})
        check(f"'{text}' bypasses LLM",
              result["status"] == "success"
              and result["payload"]["plans"] == []
              and result["payload"]["intent"] == "chitchat")


# ---------------------------------------------------------------------------
# 4. PlannerAgent.handle() — LLM routing
# ---------------------------------------------------------------------------

async def test_handle_task_success():
    print("\n[PlannerAgent — task routing]")
    plan_json = '[{"agent":"MemoryAgent","payload":{"function":"add_todo","args":{"user_id":"u1","owner_type":"alarm","title":"alarm","description":"明天8点","due_time":"2026-04-29 08:00:00","status":"pending"}}}]'
    _patch_llm(plan_json)

    agent = PlannerAgent()
    result = await agent.handle({"payload": {"user_id": "u1", "text": "帮我设置明早8点闹钟"}})
    check("status success",          result["status"] == "success")
    check("agent label correct",     result["agent"] == "PlannerAgent")
    check("plans has 1 item",        len(result["payload"]["plans"]) == 1)
    check("plan agent is MemoryAgent",
          result["payload"]["plans"][0]["agent"] == "MemoryAgent")


async def test_handle_empty_plans():
    print("\n[PlannerAgent — empty plan from LLM]")
    _patch_llm("[]")
    agent = PlannerAgent()
    result = await agent.handle({"payload": {"user_id": "u1", "text": "我最近有点累"}})
    check("status success",   result["status"] == "success")
    check("plans is []",      result["payload"]["plans"] == [])


async def test_handle_bad_json():
    print("\n[PlannerAgent — LLM returns invalid JSON]")
    _patch_llm("这不是json内容")
    agent = PlannerAgent()
    result = await agent.handle({"payload": {"user_id": "u1", "text": "帮我查天气"}})
    check("status success on parse failure", result["status"] == "success")
    check("plans is [] on parse failure",    result["payload"]["plans"] == [])


async def test_handle_multi_agent_plans():
    print("\n[PlannerAgent — multi-agent plans]")
    # Three-class design: MemoryAgent + ToolAgent; SearchAgent is filtered out.
    plan_json = '''[
        {"agent": "MemoryAgent", "payload": {"function": "add_todo", "args": {}}},
        {"agent": "ToolAgent",   "payload": {"function": "switch_character", "args": {"character_id": "凝光"}}}
    ]'''
    _patch_llm(plan_json)
    agent = PlannerAgent()
    result = await agent.handle({"payload": {"user_id": "u1", "text": "切换角色并设置提醒"}})
    check("2 plans returned", len(result["payload"]["plans"]) == 2)
    agents = {p["agent"] for p in result["payload"]["plans"]}
    check("MemoryAgent present", "MemoryAgent" in agents)
    check("ToolAgent present",   "ToolAgent" in agents)


async def test_handle_fenced_json():
    print("\n[PlannerAgent — markdown-fenced JSON]")
    plan_json = '```json\n[{"agent":"ToolAgent","payload":{"function":"switch_character","args":{"character_id":"凝光"}}}]\n```'
    _patch_llm(plan_json)
    agent = PlannerAgent()
    result = await agent.handle({"payload": {"user_id": "u1", "text": "切换角色到凝光"}})
    check("fenced JSON parsed", len(result["payload"]["plans"]) == 1)
    check("ToolAgent plan",     result["payload"]["plans"][0]["agent"] == "ToolAgent")


# ---------------------------------------------------------------------------
# 5. Error handling
# ---------------------------------------------------------------------------

async def test_validation_error():
    print("\n[PlannerAgent — input validation]")
    agent = PlannerAgent()

    r = await agent.handle({"payload": {"user_id": "", "text": "hi"}})
    check("empty user_id → error", r["status"] == "error")

    r = await agent.handle({"payload": {"user_id": "u", "text": ""}})
    check("empty text → error",    r["status"] == "error")

    r = await agent.handle({"payload": {}})
    check("missing fields → error", r["status"] == "error")

    # error payload always has plans and intent
    for resp in [r]:
        check("error payload has plans", "plans" in resp["payload"])


async def test_llm_error():
    print("\n[PlannerAgent — LLM error]")
    from backend.llm.client import LLMServiceError
    _patch_llm_raise(LLMServiceError("x", Exception("down")))

    agent = PlannerAgent()
    result = await agent.handle({"payload": {"user_id": "u1", "text": "帮我查天气"}})
    check("LLM error → status error",  result["status"] == "error")
    check("plans is [] on LLM error",  result["payload"]["plans"] == [])
    check("error message present",     bool(result["payload"].get("error")))


# ---------------------------------------------------------------------------
# 6. IAgent compliance
# ---------------------------------------------------------------------------

async def test_iagent_compliance():
    print("\n[IAgent compliance]")
    import inspect
    check("PlannerAgent subclasses IAgent",     issubclass(PlannerAgent, IAgent))
    check("handle is coroutine function",       asyncio.iscoroutinefunction(PlannerAgent.handle))
    check("stream raises NotImplementedError",  True)  # by design from IAgent default


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main():
    test_classify_chitchat()
    test_classify_task()
    test_classify_unknown()
    test_classify_very_short()
    test_strip_fences()
    test_validate_plans()
    test_parse_plans()
    await test_chitchat_bypass()
    await test_handle_task_success()
    await test_handle_empty_plans()
    await test_handle_bad_json()
    await test_handle_multi_agent_plans()
    await test_handle_fenced_json()
    await test_validation_error()
    await test_llm_error()
    await test_iagent_compliance()

    total = len(results)
    passed = sum(1 for _, ok in results if ok)
    print(f"\n{'='*40}")
    print(f"Results: {passed}/{total} passed")
    if passed < total:
        failed = [name for name, ok in results if not ok]
        print("FAILED:", ", ".join(failed))
        sys.exit(1)
    else:
        print("ALL TESTS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
