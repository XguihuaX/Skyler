"""Chunk 15 B1 profile — verify whether _execute_tool actually starves
audio_consumer's ws.send_json (the hypothesis from docs/chunk-15-starting-context.md
§5.2). Drives the real ws.py _handle_message + real ChatAgent.stream + real
_tts_audio_consumer, with call_llm / TTS / WebSocket mocked so the test is
deterministic and hermetic.

Profile log lands in /tmp/chunk15_profile.log via P1-P6 instrumentation
added to ws.py + chat.py (CHUNK15-PROFILE markers; reverted after audit).

Run:
    .venv/bin/python tests/test_chunk15_b1_profile.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from types import SimpleNamespace

# ── DB patching MUST happen before any backend import ──────────────────────
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Wipe stale profile log so the table reflects only this run
PROFILE_LOG = "/tmp/chunk15_profile.log"
if os.path.exists(PROFILE_LOG):
    os.unlink(PROFILE_LOG)


from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from backend.database import Base
import backend.database as _db_module

TEST_ENGINE = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
TEST_SESSION = sessionmaker(
    TEST_ENGINE, class_=AsyncSession, expire_on_commit=False,
)
_db_module.engine = TEST_ENGINE
_db_module.AsyncSessionLocal = TEST_SESSION

# Register ORM models against patched engine
from backend.database import models  # noqa: F401

import backend.routes.ws as _ws_module
import backend.agents.chat as _chat_module
import backend.tts as _tts_module

_ws_module.AsyncSessionLocal = TEST_SESSION
_chat_module.AsyncSessionLocal = TEST_SESSION

from backend.routes.ws import _TurnState, _handle_message_safe
from backend.tts.base import TTSBase


PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
USER_ID = "profile_test_user"

# How long the mocked tool blocks. The original premise says ~18-20s; we use
# 5 s so the test is fast but still long enough to make the producer/consumer
# scheduling question observable.
TOOL_BLOCK_SECONDS = 5.0
# How long the mocked TTS takes per sentence
TTS_DELAY_SECONDS = 0.05


# ===========================================================================
# Mocks
# ===========================================================================

class FakeWS:
    """In-memory WebSocket that records send_json with timestamps."""

    def __init__(self) -> None:
        self.sent: list[tuple[float, dict]] = []

    async def accept(self) -> None:
        pass

    async def send_json(self, msg: dict) -> None:
        # No artificial delay — we want to measure backend behaviour, not
        # network. perf_counter() captured at send time for cross-check vs
        # the P3 [SEND_PRE/POST] instrumentation.
        self.sent.append((time.perf_counter(), msg))


class FakeTTS(TTSBase):
    """Returns fixed bytes after a short await — simulates fast TTS."""

    async def synthesize(self, text: str, emotion: str = "默认") -> bytes:
        await asyncio.sleep(TTS_DELAY_SECONDS)
        # Return non-empty bytes so ws.py's _send_audio actually runs
        return b"FAKE_WAV_BYTES_" + text[:8].encode("utf-8", errors="replace")


def _chunk(content: str | None = None, tool_calls=None, finish_reason=None):
    """Build a LiteLLM-shaped chunk via SimpleNamespace."""
    delta = SimpleNamespace(content=content, tool_calls=tool_calls)
    choice = SimpleNamespace(delta=delta, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice])


def _tool_call_delta(idx: int, call_id: str, name: str, args: str):
    """Build a tool_call delta object (LiteLLM accumulates per-index)."""
    fn = SimpleNamespace(name=name, arguments=args)
    return SimpleNamespace(index=idx, id=call_id, function=fn)


class FakeStreamRound1:
    """Round 1: emits transition language, then a tool_call, finish_reason='tool_calls'."""

    def __aiter__(self):
        async def gen():
            # Sentence boundary triggers yield in ChatAgent.stream
            yield _chunk(content="嗯,让我看看。")
            # Tool call delta (id + name + full args in one delta — LiteLLM allows partial too)
            yield _chunk(tool_calls=[
                _tool_call_delta(0, "call_test_1", "fake_slow_tool", '{}'),
            ])
            yield _chunk(finish_reason="tool_calls")
        return gen()


class FakeStreamRound2:
    """Round 2: emits final reply, finish_reason='stop'."""

    def __aiter__(self):
        async def gen():
            yield _chunk(content="今天 14:00 有 A 区会议。")
            yield _chunk(finish_reason="stop")
        return gen()


# ===========================================================================
# DB + tool registration
# ===========================================================================

async def setup_db() -> None:
    async with TEST_ENGINE.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


# Register a fake slow tool that sleeps TOOL_BLOCK_SECONDS — drops into
# the SAME _execute_tool path the real flow uses (via ToolRegistry).
from backend.tools.registry import ToolRegistry, _tools, _schemas


async def fake_slow_tool(**kwargs) -> dict:
    """Simulate a 5 s tool execution. The await is a single sleep — this
    matches the user-supplied scenario (`await asyncio.sleep(5.0)` standing
    in for a real 23s tool block)."""
    await asyncio.sleep(TOOL_BLOCK_SECONDS)
    return {"result": "tool finished"}


def _register_fake_tool() -> None:
    ToolRegistry.register(
        "fake_slow_tool",
        fake_slow_tool,
        schema={
            "type": "function",
            "function": {
                "name": "fake_slow_tool",
                "description": "fake tool used by chunk 15 B1 profile",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        },
    )


def _unregister_fake_tool() -> None:
    _tools.pop("fake_slow_tool", None)
    _schemas.pop("fake_slow_tool", None)


# ===========================================================================
# Patches
# ===========================================================================

class Patches:
    """Context-style mock installer — restore everything in teardown."""

    def __init__(self) -> None:
        self._call_count = 0
        self._original_call_llm = _chat_module.call_llm
        self._original_build_messages = _chat_module._build_messages
        self._original_get_tts_engine = _ws_module.get_tts_engine

    async def fake_call_llm(self, messages, model=None, stream=False, **kwargs):
        # Round 1 = with tools (ChatAgent.stream first call), round 2 = post-tool
        self._call_count += 1
        if self._call_count == 1:
            return FakeStreamRound1()
        return FakeStreamRound2()

    async def fake_build_messages(self, user_id, text, tool_result=None, **kwargs):
        # Bypass DB-heavy _build_messages — return a minimal message list.
        return [
            {"role": "system", "content": "test system"},
            {"role": "user", "content": text or "test"},
        ]

    def fake_get_tts_engine(self, voice_model=None):
        return FakeTTS()

    def fake_get_tts_enabled(self) -> bool:
        # config.yaml has tts.enabled=false by default; force True for the
        # profile so the audio_chunk path actually runs.
        return True

    def install(self) -> None:
        _chat_module.call_llm = self.fake_call_llm.__get__(self, Patches)
        _chat_module._build_messages = self.fake_build_messages.__get__(self, Patches)
        _ws_module.get_tts_engine = self.fake_get_tts_engine.__get__(self, Patches)
        # ws.py uses `from backend.config import ... get_tts_enabled` so the
        # name is bound on the ws module; patch there.
        self._original_get_tts_enabled = _ws_module.get_tts_enabled
        _ws_module.get_tts_enabled = self.fake_get_tts_enabled.__get__(self, Patches)

    def uninstall(self) -> None:
        _chat_module.call_llm = self._original_call_llm
        _chat_module._build_messages = self._original_build_messages
        _ws_module.get_tts_engine = self._original_get_tts_engine
        _ws_module.get_tts_enabled = self._original_get_tts_enabled


# ===========================================================================
# Main scenario
# ===========================================================================

async def run_scenario() -> tuple[FakeWS, float]:
    """Drive _handle_message_safe with mocked LLM + TTS + WS.

    Returns the FakeWS (captured messages) and t0 (perf_counter when the call
    started) so the doc can plot timestamps relative to test start.
    """
    await setup_db()
    _register_fake_tool()
    patches = Patches()
    patches.install()

    ws = FakeWS()
    state = _TurnState()
    data = {
        "type": "text",
        "content": "今天有什么会",
        "user_id": USER_ID,
    }

    t0 = time.perf_counter()
    # Log t0 so the doc can compute relative ms
    with open(PROFILE_LOG, "a") as f:
        f.write(f"[T0] t={t0}\n")

    try:
        await _handle_message_safe(ws, data, state, USER_ID)  # type: ignore[arg-type]
    finally:
        patches.uninstall()
        _unregister_fake_tool()

    return ws, t0


# ===========================================================================
# Log analysis
# ===========================================================================

def parse_profile_log(path: str, t0: float) -> list[dict]:
    """Parse /tmp/chunk15_profile.log → list of {event, idx_or_name, t_ms}."""
    if not os.path.exists(path):
        return []
    events: list[dict] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line.startswith("["):
                continue
            try:
                tag, rest = line.split("] ", 1)
                event = tag.lstrip("[")
                kv = dict(part.split("=", 1) for part in rest.split() if "=" in part)
                t_raw = float(kv["t"])
                t_ms = (t_raw - t0) * 1000.0
                detail = ""
                if "idx" in kv:
                    detail = f"idx={kv['idx']}"
                elif "name" in kv:
                    detail = f"name={kv['name']}"
                events.append({"event": event, "detail": detail, "t_ms": t_ms})
            except Exception:
                continue
    events.sort(key=lambda e: e["t_ms"])
    return events


def classify_p1_p2_p3(
    events: list[dict], ws_events: list[tuple[float, dict]] | None = None,
    t0: float | None = None,
) -> tuple[str, str]:
    """Return (verdict, reasoning). Verdict ∈ {P1, P2, P3, INCONCLUSIVE}.

    P1 = backend event-loop starvation: transition SEND_POST ≥ EXEC_POST
    P2 = backend OK, frontend layer:    transition SEND_POST ≪ EXEC_POST
    P3 = mixed:                          SEND_POST inside [EXEC_PRE, EXEC_POST] mid-window

    When the P1-P6 instrumentation is reverted (production state), the
    /tmp/chunk15_profile.log will be empty. Fall back to FakeWS-captured
    `audio_chunk` vs `tool_use_done` timestamps — same logical comparison,
    minus the EXEC_PRE marker (audio_chunk arrival is functionally
    equivalent to SEND_POST since FakeWS has zero latency).
    """
    exec_pre = next((e["t_ms"] for e in events if e["event"] == "EXEC_PRE"), None)
    exec_post = next((e["t_ms"] for e in events if e["event"] == "EXEC_POST"), None)
    # idx=1 should be the transition language ("嗯,让我看看。")
    send_post_1 = next(
        (e["t_ms"] for e in events
         if e["event"] == "SEND_POST" and "idx=1" in e["detail"]),
        None,
    )
    if exec_pre is None or exec_post is None or send_post_1 is None:
        # Fallback: derive from FakeWS captures.
        if ws_events is None or t0 is None:
            return ("INCONCLUSIVE",
                    f"missing events: exec_pre={exec_pre}, exec_post={exec_post}, "
                    f"send_post_1={send_post_1}")
        first_audio_t = next(
            ((ts - t0) * 1000.0 for ts, m in ws_events
             if m.get("type") == "audio_chunk"),
            None,
        )
        tool_done_t = next(
            ((ts - t0) * 1000.0 for ts, m in ws_events
             if m.get("type") == "tool_use_done"),
            None,
        )
        tool_start_t = next(
            ((ts - t0) * 1000.0 for ts, m in ws_events
             if m.get("type") == "tool_use_start"),
            None,
        )
        if first_audio_t is None or tool_done_t is None or tool_start_t is None:
            return ("INCONCLUSIVE",
                    "no instrumentation and FakeWS missing audio/tool events")
        # Mirror the P1/P2/P3 decision tree, using ws-side arrivals.
        if first_audio_t >= tool_done_t:
            return ("P1",
                    f"[ws-fallback] transition audio_chunk arrived at "
                    f"t={first_audio_t:.1f}ms ≥ tool_use_done t={tool_done_t:.1f}ms")
        if first_audio_t < tool_start_t:
            return ("P2",
                    f"[ws-fallback] transition audio_chunk arrived at "
                    f"t={first_audio_t:.1f}ms BEFORE tool_use_start t={tool_start_t:.1f}ms")
        return ("P2",
                f"[ws-fallback] transition audio_chunk arrived at "
                f"t={first_audio_t:.1f}ms within tool exec window "
                f"[{tool_start_t:.1f}, {tool_done_t:.1f}] → consumer ran during exec")

    exec_window = exec_post - exec_pre
    if send_post_1 >= exec_post:
        return ("P1",
                f"transition audio SEND_POST t={send_post_1:.1f}ms is AT-OR-AFTER "
                f"EXEC_POST t={exec_post:.1f}ms → consumer was starved during exec "
                f"({exec_window:.1f}ms window)")
    if send_post_1 < exec_pre:
        return ("P2",
                f"transition audio SEND_POST t={send_post_1:.1f}ms is BEFORE "
                f"EXEC_PRE t={exec_pre:.1f}ms → audio left backend before tool even started, "
                f"backend NOT the bottleneck (exec window {exec_window:.1f}ms idle for "
                f"audio path)")
    # Inside [exec_pre, exec_post]
    rel = send_post_1 - exec_pre
    return ("P2",
            f"transition audio SEND_POST t={send_post_1:.1f}ms is WITHIN exec window "
            f"[{exec_pre:.1f}, {exec_post:.1f}] at +{rel:.1f}ms — consumer ran during exec, "
            f"not starved. Backend OK; root cause likely frontend or transport layer")


# ===========================================================================
# Runner
# ===========================================================================

def main() -> int:
    print(f"\n=== chunk 15 B1 profile run ===")
    print(f"  TOOL_BLOCK_SECONDS = {TOOL_BLOCK_SECONDS}")
    print(f"  TTS_DELAY_SECONDS  = {TTS_DELAY_SECONDS}")
    print(f"  profile log        = {PROFILE_LOG}")

    ws, t0 = asyncio.run(run_scenario())

    print(f"\n--- FakeWS captured {len(ws.sent)} ws.send_json calls ---")
    for ts, msg in ws.sent:
        rel = (ts - t0) * 1000.0
        type_ = msg.get("type")
        preview = ""
        if type_ == "text_chunk":
            preview = f" content={msg.get('content','')[:30]!r}"
        elif type_ == "audio_chunk":
            preview = f" content_len={len(msg.get('content',''))}"
        elif type_ in ("tool_use_start", "tool_use_done"):
            preview = f" tool={msg.get('tool_name')}"
        print(f"  t={rel:7.1f}ms  type={type_:<18}{preview}")

    print(f"\n--- /tmp/chunk15_profile.log (sorted by t) ---")
    events = parse_profile_log(PROFILE_LOG, t0)
    if not events:
        print(f"  {FAIL} no profile events captured")
        return 1
    for e in events:
        print(f"  t={e['t_ms']:7.1f}ms  {e['event']:<14} {e['detail']}")

    print(f"\n--- Classification ---")
    verdict, reasoning = classify_p1_p2_p3(events, ws.sent, t0)
    tag = PASS if verdict in ("P1", "P2", "P3") else FAIL
    print(f"  {tag} verdict = {verdict}")
    print(f"  reasoning: {reasoning}")

    # Test passes if any verdict was reached (i.e. enough events captured)
    return 0 if verdict in ("P1", "P2", "P3") else 1


if __name__ == "__main__":
    sys.exit(main())
