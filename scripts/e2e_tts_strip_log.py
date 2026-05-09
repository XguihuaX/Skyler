"""End-to-end log capture for v3-G chunk 4 hotfix-1.

3 scenarios that historically had fallback tool_call patterns reach TTS:
  1. clipboard.translate fallback (Anthropic <invoke>)
  2. proactive.snooze_wake_call fallback (Qwen <tool_call>)
  3. plain chitchat with <state_update> (chunk 3b regression)

Stub the inner TTS engine to record what cleaned text it sees; assert no
fallback / state_update / emotion / thinking tag survives. Mirrors what the
cosyvoice / edge / sovits providers would receive in production.

Run::
    python scripts/e2e_tts_strip_log.py
"""
from __future__ import annotations

import asyncio
import io
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# capture [tts] log lines
_log_buf = io.StringIO()
handler = logging.StreamHandler(_log_buf)
handler.setLevel(logging.INFO)
logging.basicConfig(level=logging.INFO, force=True)
logging.getLogger().addHandler(handler)

from backend.tts import _PreprocessingEngine
from backend.tts.base import TTSBase


class _RecordingEngine(TTSBase):
    """Inner engine stub that records every (text, emotion) it receives."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def synthesize(self, text: str, emotion: str = "默认"):
        self.calls.append((text, emotion))
        # Return non-empty bytes so caller treats it as success
        return b"\x00\x00"


# Per-scenario raw LLM streams (what cosyvoice would have received pre-fix).
SCENARIOS = [
    {
        "name": "clipboard.translate (Anthropic <invoke>)",
        "raw_stream": [
            # Sentence 1 — fallback invoke buried in normal reply
            '<emotion>happy</emotion>好的~',
            # Sentence 2 — translation result delivered through fallback invoke
            '<function_calls><invoke name="clipboard.translate">'
            '<parameter name="target_lang">zh</parameter></invoke></function_calls>',
            '翻译好啦：你好世界。',
        ],
        "forbidden_substrings": [
            "<emotion>", "<function_calls>", "<invoke", "<parameter",
            "clipboard.translate", "</invoke>", "</function_calls>",
        ],
        "must_contain": ["你好世界"],
    },
    {
        "name": "proactive.snooze_wake_call (Qwen <tool_call>)",
        "raw_stream": [
            '<emotion>calm</emotion>好的~',
            # Qwen XML fallback — must not be read aloud
            '<tool_call>{"name":"proactive.snooze_wake_call",'
            '"arguments":{"minutes":5}}</tool_call>',
            '再睡 5 分钟。',
        ],
        "forbidden_substrings": [
            "<emotion>", "<tool_call>", "</tool_call>",
            "proactive.snooze_wake_call", '"name"', "minutes",
        ],
        "must_contain": ["再睡 5 分钟"],
    },
    {
        "name": "<state_update> chunk 3b regression",
        "raw_stream": [
            '<emotion>happy</emotion>'
            '<state_update mood="happy" intimacy_delta="+1" thought="觉得用户今天很努力" />'
            '嘿，辛苦啦！',
        ],
        "forbidden_substrings": [
            "<emotion>", "<state_update", "intimacy_delta", "thought=",
            "/>", "辛苦啦！</state_update>",
        ],
        "must_contain": ["嘿，辛苦啦"],
    },
]


async def run_scenario(scenario: dict, recorder: _RecordingEngine) -> tuple[bool, list[str]]:
    failures: list[str] = []
    engine = _PreprocessingEngine(recorder)
    initial_call_count = len(recorder.calls)
    for sentence in scenario["raw_stream"]:
        await engine.synthesize(sentence, emotion="happy")
    new_calls = recorder.calls[initial_call_count:]
    seen_text = " ".join(t for t, _ in new_calls)
    print(f"\n=== {scenario['name']} ===")
    print(f"  raw stream chunks: {len(scenario['raw_stream'])}")
    print(f"  TTS calls fired:    {len(new_calls)}")
    for i, (txt, emo) in enumerate(new_calls):
        print(f"  [tts] synth_text={txt!r} emotion={emo}")
    for sub in scenario["forbidden_substrings"]:
        if sub in seen_text:
            failures.append(f"FORBIDDEN substring {sub!r} reached TTS")
    for sub in scenario["must_contain"]:
        if sub not in seen_text:
            failures.append(f"MISSING expected substring {sub!r} in TTS output")
    return len(failures) == 0, failures


async def main() -> None:
    recorder = _RecordingEngine()
    overall_ok = True
    for scenario in SCENARIOS:
        ok, fails = await run_scenario(scenario, recorder)
        if ok:
            print("  → PASS")
        else:
            print("  → FAIL")
            for f in fails:
                print(f"     ! {f}")
            overall_ok = False

    print("\n" + "=" * 60)
    print("Captured [tts] log lines:")
    handler.flush()
    log_lines = [
        ln for ln in _log_buf.getvalue().splitlines()
        if "[tts]" in ln
    ]
    for ln in log_lines:
        print("  " + ln)
    if not log_lines:
        print("  (none — check logging config)")

    print("\n" + "=" * 60)
    print("Result:", "ALL SCENARIOS PASSED" if overall_ok else "FAILED")
    if not overall_ok:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
