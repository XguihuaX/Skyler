"""Tests for v3-G chunk 3a clipboard capabilities (3 个 CHAT_AGENT cap)。

Mock LLM call_llm + mock clipboard_watcher.get_recent → 验证三个 capability
的契约、错误路径、index 边界。
"""
import asyncio
import os
import sys
from unittest.mock import patch, AsyncMock, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.integrations.clipboard import ClipboardItem
import backend.capabilities.clipboard as clipboard_caps

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))


def _make_item(content: str, ctype: str = "plain_text", at: float = 1000.0) -> ClipboardItem:
    return ClipboardItem(
        content=content, content_type=ctype,
        captured_at=at, captured_iso="2026-05-08T08:00:00",
    )


# ---------------------------------------------------------------------------
# 1. capabilities registered (CHAT_AGENT)
# ---------------------------------------------------------------------------

async def test_capabilities_registered():
    print("\n[clipboard caps — registered as CHAT_AGENT]")
    from backend.capabilities import CapabilityRegistry, Consumer
    reg = CapabilityRegistry()
    for name in ("clipboard.get_recent", "clipboard.summarize", "clipboard.translate"):
        cap = reg.get(name)
        check(f"{name} present", cap is not None)
        if cap:
            check(f"{name} CHAT_AGENT consumer",
                  Consumer.CHAT_AGENT in cap.consumers)


# ---------------------------------------------------------------------------
# 2. get_recent
# ---------------------------------------------------------------------------

async def test_get_recent_returns_serialized():
    print("\n[clipboard caps — get_recent returns dict items]")
    items = [
        _make_item("hello"), _make_item("https://x.com", "url"),
    ]
    with patch.object(clipboard_caps.clipboard_watcher, "get_recent", return_value=items):
        out = await clipboard_caps.get_recent(n=5)
    check("count = 2", out["count"] == 2)
    check("items is list of dict",
          isinstance(out["items"], list)
          and all(isinstance(i, dict) for i in out["items"]))
    check("items contain content_type",
          all("content_type" in i for i in out["items"]))


async def test_get_recent_clamps_n():
    print("\n[clipboard caps — get_recent forwards n]")
    captured = {}
    def fake_get_recent(n):
        captured["n"] = n
        return []
    with patch.object(clipboard_caps.clipboard_watcher, "get_recent",
                      side_effect=fake_get_recent):
        await clipboard_caps.get_recent(n=10)
    check("n forwarded to watcher", captured.get("n") == 10)


# ---------------------------------------------------------------------------
# 3. summarize
# ---------------------------------------------------------------------------

async def test_summarize_index_out_of_range():
    print("\n[clipboard caps — summarize index OOR returns error]")
    with patch.object(clipboard_caps.clipboard_watcher, "get_recent", return_value=[]):
        out = await clipboard_caps.summarize(item_index=0)
    check("error returned when empty", "error" in out)


async def test_summarize_calls_llm_returns_summary():
    print("\n[clipboard caps — summarize calls LLM, returns summary]")
    items = [_make_item("This is a long article about Python async patterns...")]
    fake_resp = MagicMock()
    fake_resp.choices = [MagicMock()]
    fake_resp.choices[0].message.content = "讲了 Python async pattern。"

    async def fake_call_llm(*a, **kw):
        return fake_resp

    # call_llm is imported lazily inside summarize; patch at the source module
    with patch.object(clipboard_caps.clipboard_watcher, "get_recent", return_value=items), \
         patch("backend.llm.client.call_llm", side_effect=fake_call_llm):
        out = await clipboard_caps.summarize(item_index=0)

    check("summary present",
          out.get("summary") == "讲了 Python async pattern。",
          f"got summary={out.get('summary')!r}")
    check("content_type passthrough",
          out.get("content_type") == "plain_text")
    check("original_length present",
          isinstance(out.get("original_length"), int))


async def test_summarize_llm_error():
    print("\n[clipboard caps — summarize handles LLM error]")
    from backend.llm.client import LLMError
    items = [_make_item("hello world")]
    async def boom(*a, **kw):
        raise LLMError("boom")
    with patch.object(clipboard_caps.clipboard_watcher, "get_recent", return_value=items), \
         patch("backend.llm.client.call_llm", side_effect=boom):
        out = await clipboard_caps.summarize(item_index=0)
    check("error string returned", "error" in out and "boom" in out["error"])


# ---------------------------------------------------------------------------
# 4. translate
# ---------------------------------------------------------------------------

async def test_translate_index_out_of_range():
    print("\n[clipboard caps — translate index OOR returns error]")
    with patch.object(clipboard_caps.clipboard_watcher, "get_recent", return_value=[]):
        out = await clipboard_caps.translate(item_index=0, target_lang="zh")
    check("error returned when empty", "error" in out)


async def test_translate_uses_target_lang():
    print("\n[clipboard caps — translate respects target_lang in prompt]")
    items = [_make_item("hello")]
    fake_resp = MagicMock()
    fake_resp.choices = [MagicMock()]
    fake_resp.choices[0].message.content = "你好"

    captured_messages = {}
    async def fake_call_llm(messages=None, **_kw):
        captured_messages["messages"] = messages
        return fake_resp

    with patch.object(clipboard_caps.clipboard_watcher, "get_recent", return_value=items), \
         patch("backend.llm.client.call_llm", side_effect=fake_call_llm):
        out = await clipboard_caps.translate(item_index=0, target_lang="zh")

    check("translation returned", out.get("translation") == "你好")
    check("target_lang in response",
          out.get("target_lang") == "zh")
    sent_prompt = captured_messages["messages"][0]["content"]
    check("prompt includes 简体中文 (zh expansion)",
          "简体中文" in sent_prompt)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

async def main():
    await test_capabilities_registered()
    await test_get_recent_returns_serialized()
    await test_get_recent_clamps_n()
    await test_summarize_index_out_of_range()
    await test_summarize_calls_llm_returns_summary()
    await test_summarize_llm_error()
    await test_translate_index_out_of_range()
    await test_translate_uses_target_lang()

    total = len(results)
    passed = sum(1 for _, ok in results if ok)
    print(f"\n{'='*40}")
    print(f"Results: {passed}/{total} passed")
    if passed < total:
        print("FAILED:", ", ".join(n for n, ok in results if not ok))
        sys.exit(1)
    else:
        print("ALL TESTS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
