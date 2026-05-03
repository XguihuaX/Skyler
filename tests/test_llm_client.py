"""Tests for backend/llm/client.py — fully mocked, no real API calls."""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import litellm.exceptions as llm_exc
import backend.llm.client as _client_mod
from backend.llm.client import (
    call_llm, stream_llm,
    LLMError, LLMAuthError, LLMRateLimitError,
    LLMContextError, LLMServiceError, LLMBadRequestError,
)

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []

def check(name: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))


# ---------------------------------------------------------------------------
# Fake response objects
# ---------------------------------------------------------------------------

class _FakeMsg:
    def __init__(self, text: str) -> None:
        self.content = text

class _FakeChoice:
    def __init__(self, text: str) -> None:
        self.message = _FakeMsg(text)

class _FakeResponse:
    def __init__(self, text: str = "hello") -> None:
        self.choices = [_FakeChoice(text)]

class _FakeDelta:
    def __init__(self, content) -> None:
        self.content = content

class _FakeStreamChoice:
    def __init__(self, content) -> None:
        self.delta = _FakeDelta(content)

class _FakeStreamChunk:
    def __init__(self, content) -> None:
        self.choices = [_FakeStreamChoice(content)]

class _FakeStream:
    """Async iterator over a fixed list of chunks."""
    def __init__(self, chunks) -> None:
        self._chunks = iter(chunks)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._chunks)
        except StopIteration:
            raise StopAsyncIteration


def _patch(mock_fn):
    """Replace acompletion in the client module's own namespace."""
    _client_mod.acompletion = mock_fn

def _mock_return(value):
    async def _m(model, messages, stream=False, **kwargs):
        return value
    return _m

def _mock_raise(exc):
    async def _m(model, messages, stream=False, **kwargs):
        raise exc
    return _m


# ---------------------------------------------------------------------------
# Non-stream tests
# ---------------------------------------------------------------------------

async def test_non_stream_returns_response():
    print("\n[call_llm — non-stream]")
    _patch(_mock_return(_FakeResponse("world")))
    resp = await call_llm([{"role": "user", "content": "hi"}])
    check("returns response object", resp is not None)
    check("response has choices", hasattr(resp, "choices"))
    check("content accessible", resp.choices[0].message.content == "world")


async def test_model_override():
    print("\n[call_llm — model override]")
    captured = {}
    async def _m(model, messages, stream=False, **kwargs):
        captured["model"] = model
        return _FakeResponse()
    _patch(_m)
    await call_llm([{"role": "user", "content": "x"}], model="openai/gpt-4o")
    check("custom model forwarded", captured["model"] == "openai/gpt-4o")


async def test_default_model_used():
    print("\n[call_llm — default model]")
    captured = {}
    async def _m(model, messages, stream=False, **kwargs):
        captured["model"] = model
        return _FakeResponse()
    _patch(_m)
    from backend.config import DEFAULT_MODEL
    await call_llm([{"role": "user", "content": "x"}])
    check("default model used when none given", captured["model"] == DEFAULT_MODEL)


async def test_kwargs_forwarded():
    print("\n[call_llm — kwargs forwarding]")
    captured = {}
    async def _m(model, messages, stream=False, **kwargs):
        captured.update(kwargs)
        return _FakeResponse()
    _patch(_m)
    await call_llm([{"role": "user", "content": "x"}], temperature=0.3, max_tokens=50)
    check("temperature forwarded", captured.get("temperature") == 0.3)
    check("max_tokens forwarded", captured.get("max_tokens") == 50)


# ---------------------------------------------------------------------------
# Stream tests
# ---------------------------------------------------------------------------

async def test_stream_returns_wrapper():
    print("\n[call_llm — stream=True]")
    fake_stream = _FakeStream([_FakeStreamChunk("he"), _FakeStreamChunk("llo")])
    _patch(_mock_return(fake_stream))
    result = await call_llm([{"role": "user", "content": "x"}], stream=True)
    check("stream=True returns stream wrapper", result is fake_stream)


async def test_stream_llm_yields_chunks():
    print("\n[stream_llm — chunk filtering]")
    chunks = [
        _FakeStreamChunk("он"),
        _FakeStreamChunk(None),    # None delta → skip
        _FakeStreamChunk(""),     # empty string → skip
        _FakeStreamChunk("лайн"),
    ]
    _patch(_mock_return(_FakeStream(chunks)))
    collected = []
    async for tok in stream_llm([{"role": "user", "content": "x"}]):
        collected.append(tok)
    check("yields non-empty chunks only", collected == ["он", "лайн"])
    check("None delta skipped", None not in collected)
    check("empty-string delta skipped", "" not in collected)


async def test_stream_llm_concatenated():
    print("\n[stream_llm — full output]")
    chunks = [_FakeStreamChunk(c) for c in ["Hello", ", ", "world", "!"]]
    _patch(_mock_return(_FakeStream(chunks)))
    out = "".join([tok async for tok in stream_llm([{"role": "user", "content": "x"}])])
    check("concatenated output correct", out == "Hello, world!")


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

async def _assert_raises(exc_cls, litellm_exc):
    _patch(_mock_raise(litellm_exc))
    try:
        await call_llm([{"role": "user", "content": "x"}])
        return False, "no exception raised"
    except exc_cls:
        return True, ""
    except Exception as e:
        return False, f"wrong exception: {type(e).__name__}: {e}"


async def test_error_mapping():
    print("\n[error handling]")

    ok, d = await _assert_raises(
        LLMAuthError,
        llm_exc.AuthenticationError("bad key", llm_provider="x", model="x", response=None),
    )
    check("AuthenticationError → LLMAuthError", ok, d)

    ok, d = await _assert_raises(
        LLMRateLimitError,
        llm_exc.RateLimitError("rate", llm_provider="x", model="x", response=None),
    )
    check("RateLimitError → LLMRateLimitError", ok, d)

    ok, d = await _assert_raises(
        LLMContextError,
        llm_exc.ContextWindowExceededError("ctx", llm_provider="x", model="x", response=None),
    )
    check("ContextWindowExceededError → LLMContextError", ok, d)

    ok, d = await _assert_raises(
        LLMServiceError,
        llm_exc.ServiceUnavailableError("svc", llm_provider="x", model="x", response=None),
    )
    check("ServiceUnavailableError → LLMServiceError", ok, d)

    ok, d = await _assert_raises(
        LLMServiceError,
        llm_exc.APIConnectionError("conn", llm_provider="x", model="x"),
    )
    check("APIConnectionError → LLMServiceError", ok, d)

    ok, d = await _assert_raises(
        LLMBadRequestError,
        llm_exc.BadRequestError("bad", llm_provider="x", model="x", response=None),
    )
    check("BadRequestError → LLMBadRequestError", ok, d)

    _patch(_mock_raise(RuntimeError("mystery")))
    try:
        await call_llm([{"role": "user", "content": "x"}])
        check("unknown exception → LLMError", False, "no exception")
    except LLMError:
        check("unknown exception → LLMError", True)
    except Exception as e:
        check("unknown exception → LLMError", False, f"got {type(e).__name__}")

    check("LLMAuthError subclasses LLMError", issubclass(LLMAuthError, LLMError))
    check("LLMRateLimitError subclasses LLMError", issubclass(LLMRateLimitError, LLMError))
    check("LLMContextError subclasses LLMError", issubclass(LLMContextError, LLMError))
    check("LLMServiceError subclasses LLMError", issubclass(LLMServiceError, LLMError))
    check("LLMBadRequestError subclasses LLMError", issubclass(LLMBadRequestError, LLMError))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main():
    await test_non_stream_returns_response()
    await test_model_override()
    await test_default_model_used()
    await test_kwargs_forwarded()
    await test_stream_returns_wrapper()
    await test_stream_llm_yields_chunks()
    await test_stream_llm_concatenated()
    await test_error_mapping()

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
