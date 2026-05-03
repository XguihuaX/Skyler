"""Tests for backend/agents/chat.py — all external I/O mocked."""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

# Bootstrap in-memory DB before any app imports touch the real engine.
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
import backend.database as _db_mod

_TEST_ENGINE = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
_TEST_SESSION = sessionmaker(_TEST_ENGINE, class_=AsyncSession, expire_on_commit=False)
_db_mod.engine = _TEST_ENGINE
_db_mod.AsyncSessionLocal = _TEST_SESSION

from backend.database import Base
from backend.database import models as _models  # noqa — registers ORM

# Import chat module AFTER DB patch so its module-level references pick up
# the patched AsyncSessionLocal.
import backend.agents.chat as _chat_mod
from backend.agents.chat import ChatAgent, _sentence_stream, _find_boundary

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))


async def _collect(agen) -> list:
    return [x async for x in agen]


async def _token_gen(*tokens):
    for t in tokens:
        yield t


# ---------------------------------------------------------------------------
# Mock factories — always patch names in _chat_mod's own namespace
# ---------------------------------------------------------------------------

def _patch_stream_llm(text: str):
    """Replace stream_llm in chat module to yield chars of *text*."""
    async def _gen(messages, model=None, **kw):
        for ch in text:
            yield ch
    _chat_mod.stream_llm = _gen


def _patch_search(mems: list):
    """Replace search_relevant_memories in chat module."""
    async def _search(user_id, query, top_k=5):
        return mems
    _chat_mod.search_relevant_memories = _search


# ---------------------------------------------------------------------------
# DB setup
# ---------------------------------------------------------------------------

async def setup():
    async with _TEST_ENGINE.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with _TEST_SESSION() as s:
        from backend.database.services import create_user, upsert_personality
        await create_user(s, "chat_user", "Tester")
        await upsert_personality(s, "chat_user", "personality", "openness", "high")
        await upsert_personality(s, "chat_user", "preference", "music", "jazz")


# ---------------------------------------------------------------------------
# 1. Sentence boundary finder
# ---------------------------------------------------------------------------

async def test_find_boundary():
    print("\n[_find_boundary]")
    check("Chinese period",          _find_boundary("你好。") == 2)
    check("Chinese exclaim",         _find_boundary("真棒！") == 2)
    check("Chinese question",        _find_boundary("怎么了？") == 3)
    check("ASCII exclaim",           _find_boundary("Wow!") == 3)
    check("ASCII question",          _find_boundary("OK?") == 2)
    check("Period + space",          _find_boundary("Hi. there") == 2)
    check("Period at end no space",  _find_boundary("3.14") == -1)
    check("No boundary",             _find_boundary("hello world") == -1)
    check("Empty string",            _find_boundary("") == -1)


# ---------------------------------------------------------------------------
# 2. Sentence stream splitter
# ---------------------------------------------------------------------------

async def test_sentence_stream():
    print("\n[_sentence_stream]")

    sents = await _collect(_sentence_stream(_token_gen("你", "好。", "再", "见。")))
    check("two Chinese sentences",          sents == ["你好。", "再见。"], str(sents))

    sents = await _collect(_sentence_stream(_token_gen("真的吗？", "当然！")))
    check("question + exclaim",             sents == ["真的吗？", "当然！"], str(sents))

    sents = await _collect(_sentence_stream(_token_gen("hello")))
    check("trailing no-punct flushed",      sents == ["hello"], str(sents))

    sents = await _collect(_sentence_stream(_token_gen()))
    check("empty stream yields nothing",    sents == [], str(sents))

    sents = await _collect(_sentence_stream(_token_gen("第一句。第二句！第三句？")))
    check("multiple in one token",          len(sents) == 3, str(sents))

    sents = await _collect(_sentence_stream(_token_gen("ok。", "  ")))
    check("whitespace remainder discarded", sents == ["ok。"], str(sents))

    sents = await _collect(_sentence_stream(_token_gen("你", "好", "！", "再见。")))
    check("split across tokens",            sents == ["你好！", "再见。"], str(sents))


# ---------------------------------------------------------------------------
# 3. Context assembly (_build_messages)
# ---------------------------------------------------------------------------

async def test_build_messages_full():
    print("\n[_build_messages — full context]")

    class _FakeMem:
        content = "用户喜欢爵士乐"

    _patch_search([_FakeMem()])

    from backend.memory.short_term import short_term_memory
    await short_term_memory.clear("chat_user")
    await short_term_memory.add("chat_user", "user", "上次我说了什么？")
    await short_term_memory.add("chat_user", "assistant", "你说喜欢猫。")

    from backend.agents.chat import _build_messages
    msgs = await _build_messages("chat_user", "我今天想听音乐", tool_result="已找到：Miles Davis")

    check("first message is system",          msgs[0]["role"] == "system")
    sys_content = msgs[0]["content"]
    check("persona in system prompt",         "ChatAgent" in sys_content or "Momo" in sys_content or len(sys_content) > 50)
    check("personality injected",             "openness" in sys_content or "jazz" in sys_content)
    check("long-term memory injected",        "爵士" in sys_content)
    check("tool result injected",             "Miles Davis" in sys_content)

    roles = [m["role"] for m in msgs[1:]]
    check("short-term user turn present",     "user" in roles)
    check("short-term assistant turn present","assistant" in roles)
    check("last msg is current input",        msgs[-1] == {"role": "user", "content": "我今天想听音乐"})
    check("assistant turn before current",    msgs[-2]["content"] == "你说喜欢猫。")


async def test_build_messages_empty():
    print("\n[_build_messages — empty long-term + no tool]")
    _patch_search([])

    from backend.memory.short_term import short_term_memory
    await short_term_memory.clear("chat_user")

    from backend.agents.chat import _build_messages
    msgs = await _build_messages("chat_user", "hi", tool_result=None)
    sys_content = msgs[0]["content"]
    check("tool section absent",   "【工具调用结果】" not in sys_content)
    check("memory section absent", "长期记忆" not in sys_content)


# ---------------------------------------------------------------------------
# 4. ChatAgent.handle() — non-streaming
# ---------------------------------------------------------------------------

async def test_handle_success():
    print("\n[ChatAgent.handle — success]")
    _patch_stream_llm("你好！这是测试。")
    _patch_search([])

    agent = ChatAgent()
    result = await agent.handle({
        "payload": {"user_id": "chat_user", "text": "hello", "context": {}}
    })
    check("status success",      result["status"] == "success")
    check("agent label correct", result["agent"] == "ChatAgent")
    check("full text returned",  result["payload"]["text"] == "你好！这是测试。")


async def test_handle_validation():
    print("\n[ChatAgent.handle — validation]")
    agent = ChatAgent()

    r = await agent.handle({"payload": {"user_id": "", "text": "hi"}})
    check("empty user_id → error", r["status"] == "error")

    r = await agent.handle({"payload": {"user_id": "u", "text": ""}})
    check("empty text → error", r["status"] == "error")

    r = await agent.handle({"payload": {}})
    check("missing fields → error", r["status"] == "error")


async def test_handle_llm_error():
    print("\n[ChatAgent.handle — LLM error handling]")
    from backend.llm.client import LLMServiceError

    async def _error_stream(messages, model=None, **kw):
        raise LLMServiceError("x", Exception("down"))
        yield  # make it an async generator

    _chat_mod.stream_llm = _error_stream
    _patch_search([])

    agent = ChatAgent()
    result = await agent.handle({"payload": {"user_id": "chat_user", "text": "hi"}})
    check("LLM error → status error",  result["status"] == "error")
    check("error message in payload",  bool(result["payload"].get("error")))


# ---------------------------------------------------------------------------
# 5. ChatAgent.stream() — streaming sentences
# ---------------------------------------------------------------------------

async def test_stream_sentences():
    print("\n[ChatAgent.stream — sentence splitting]")

    async def _fake_stream(messages, model=None, **kw):
        for token in ["你好", "！", "我是", "Momo", "。", "很高兴见到你！"]:
            yield token
    _chat_mod.stream_llm = _fake_stream
    _patch_search([])

    from backend.memory.short_term import short_term_memory
    await short_term_memory.clear("chat_user")

    agent = ChatAgent()
    sentences = await _collect(agent.stream({
        "payload": {"user_id": "chat_user", "text": "你好"}
    }))
    check("yields multiple sentences",  len(sentences) >= 2,        str(sentences))
    check("first sentence correct",     sentences[0] == "你好！",    str(sentences))
    check("second sentence correct",    sentences[1] == "我是Momo。", str(sentences))
    check("trailing sentence yielded",  "很高兴见到你！" in sentences, str(sentences))


async def test_stream_validation_error():
    print("\n[ChatAgent.stream — validation error]")
    agent = ChatAgent()
    try:
        await _collect(agent.stream({"payload": {"user_id": "", "text": "hi"}}))
        check("empty user_id raises ValueError", False)
    except ValueError:
        check("empty user_id raises ValueError", True)


# ---------------------------------------------------------------------------
# 6. IAgent compliance
# ---------------------------------------------------------------------------

async def test_iagent_compliance():
    print("\n[IAgent compliance]")
    import inspect
    from backend.agents.base import IAgent
    check("ChatAgent subclasses IAgent",        issubclass(ChatAgent, IAgent))
    check("handle is coroutine function",       asyncio.iscoroutinefunction(ChatAgent.handle))
    check("stream is async generator function", inspect.isasyncgenfunction(ChatAgent.stream))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main():
    await setup()
    await test_find_boundary()
    await test_sentence_stream()
    await test_build_messages_full()
    await test_build_messages_empty()
    await test_handle_success()
    await test_handle_validation()
    await test_handle_llm_error()
    await test_stream_sentences()
    await test_stream_validation_error()
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
