"""修法 B(audit_input_tokens_bloat.md #4)── tool_result 截断 8 测试。

防 multi-round tool calling 时 prior tool result 在 messages 累积无限膨胀,
单 turn LLM input 推到 50k+ tokens。

策略验证:
  - 短 result(≤ MAX)pass-through
  - 长 result 截到 MAX,**保留尾部**(大多 tool 把 summary / conclusion 放尾)
  - 截断 marker 格式正确,let LLM 知情
  - 已是 str 输入不再多包 json.dumps 引号
  - 非 str 输入 json.dumps 后再截
  - 精确 = MAX 不截
  - DEBUG log 触发条件

Run:
    .venv/bin/python tests/test_tool_truncate.py
"""
from __future__ import annotations

import io
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Skip DB bootstrap by setting an in-memory URL; helper has no DB deps but
# import chain triggers config loading.
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from backend.agents.chat import truncate_tool_result, TOOL_RESULT_MAX_CHARS

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))


# ---------------------------------------------------------------------------
# 1. short result pass-through unchanged
# ---------------------------------------------------------------------------

def test_short_result_passes_through_unchanged():
    print("\n[1] short result(< MAX)pass-through 不变")
    payload = {"status": "ok", "events": ["A", "B"]}
    out = truncate_tool_result(payload)
    expected = json.dumps(payload, ensure_ascii=False)
    check("equals raw json.dumps", out == expected, f"got {out!r}")
    check("no truncation marker", "[...truncated" not in out)


# ---------------------------------------------------------------------------
# 2. long result truncated to max
# ---------------------------------------------------------------------------

def test_long_result_truncated_to_max():
    print("\n[2] long result(> MAX)truncated to MAX + marker")
    payload = {"data": "x" * 10000}  # raw json > 10000 chars
    out = truncate_tool_result(payload, tool_name="bigfoo")
    # marker + max chars
    check(
        f"output length == MAX + marker (~{TOOL_RESULT_MAX_CHARS} + ~45)",
        TOOL_RESULT_MAX_CHARS < len(out) < TOOL_RESULT_MAX_CHARS + 60,
        f"got len={len(out)}",
    )
    check("starts with truncation marker",
          out.startswith("[...truncated, "))
    check("marker contains 'chars omitted from head'",
          "chars omitted from head" in out)


# ---------------------------------------------------------------------------
# 3. truncation preserves tail (not head)
# ---------------------------------------------------------------------------

def test_truncation_preserves_tail():
    print("\n[3] truncation 保留尾部,丢弃头部")
    head_marker = "<<<HEAD_SHOULD_BE_GONE>>>"
    tail_marker = "<<<TAIL_SHOULD_REMAIN>>>"
    long_body = "z" * 8000
    raw = head_marker + long_body + tail_marker
    out = truncate_tool_result(raw)
    check("output does NOT contain HEAD marker",
          head_marker not in out)
    check("output DOES contain TAIL marker",
          tail_marker in out)


# ---------------------------------------------------------------------------
# 4. truncation marker format
# ---------------------------------------------------------------------------

def test_truncation_marker_format():
    print("\n[4] marker 格式 '[...truncated, N chars omitted from head]\\n'")
    body = "y" * 6000  # raw ~ 6002 with quotes after json.dumps
    out = truncate_tool_result(body, tool_name="markerfoo")
    expected_omitted = len(body) - TOOL_RESULT_MAX_CHARS  # body is str → no json.dumps wrap
    expected_marker = f"[...truncated, {expected_omitted} chars omitted from head]\n"
    check("first chars match marker template",
          out.startswith(expected_marker), f"got start={out[:80]!r}")
    # marker 后紧跟原文尾部
    check("after marker is tail of original",
          out[len(expected_marker):].startswith("y"))


# ---------------------------------------------------------------------------
# 5. non-string input gets json.dumps then truncate
# ---------------------------------------------------------------------------

def test_truncate_non_string_input_serializes_first():
    print("\n[5] non-string(dict/list)先 json.dumps 再 truncate")
    payload = {"key": "value-" + "Z" * 5000}
    out = truncate_tool_result(payload, tool_name="dictfoo")
    # 由于 json.dumps 后 > MAX,会被截断
    check("output truncated", out.startswith("[...truncated"))
    # 尾部应含原 dict 的 closing brace
    check("tail contains closing brace '}' from json",
          out.rstrip().endswith("}"), f"tail ends with: {out[-20:]!r}")


# ---------------------------------------------------------------------------
# 6. already-string input not re-wrapped in quotes
# ---------------------------------------------------------------------------

def test_truncate_handles_already_str_input():
    print("\n[6] str 输入不会被 json.dumps 多包引号")
    raw = "plain string content"
    out = truncate_tool_result(raw)
    check("short str pass-through verbatim", out == raw,
          f"got {out!r}")
    # 长 str case:也不应 json.dumps wrap(否则会有 ``\"`` 转义)
    long_raw = "p" * 8000
    out2 = truncate_tool_result(long_raw)
    check("long str: no surrounding quote in tail",
          not out2.endswith('"'), f"tail: {out2[-30:]!r}")


# ---------------------------------------------------------------------------
# 7. exact-max no truncation
# ---------------------------------------------------------------------------

def test_truncate_at_exact_max_no_truncation():
    print("\n[7] 精确 = MAX 不触发 truncate")
    raw = "a" * TOOL_RESULT_MAX_CHARS  # exact length
    out = truncate_tool_result(raw)
    check("output == input (no marker added)", out == raw)
    # 长度 = MAX 时 ``<=`` 命中 → pass-through
    check("no marker", "[...truncated" not in out)


# ---------------------------------------------------------------------------
# 8. DEBUG log triggers on truncation
# ---------------------------------------------------------------------------

def test_truncate_logs_when_triggered():
    print("\n[8] truncate 触发时打 DEBUG log,带 tool_name")
    # capture logger output from backend.agents.chat
    log_buf = io.StringIO()
    handler = logging.StreamHandler(log_buf)
    handler.setLevel(logging.DEBUG)
    log = logging.getLogger("backend.agents.chat")
    old_level = log.level
    log.setLevel(logging.DEBUG)
    log.addHandler(handler)
    try:
        truncate_tool_result("q" * 10000, tool_name="my_test_tool")
    finally:
        log.removeHandler(handler)
        log.setLevel(old_level)

    captured = log_buf.getvalue()
    check("contains [tool_truncate] tag", "[tool_truncate]" in captured)
    check("contains tool_name 'my_test_tool'", "my_test_tool" in captured)
    check("contains '-> 4000' (target size)", "-> 4000" in captured)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def main() -> int:
    test_short_result_passes_through_unchanged()
    test_long_result_truncated_to_max()
    test_truncation_preserves_tail()
    test_truncation_marker_format()
    test_truncate_non_string_input_serializes_first()
    test_truncate_handles_already_str_input()
    test_truncate_at_exact_max_no_truncation()
    test_truncate_logs_when_triggered()

    passed = sum(1 for _, ok in results if ok)
    failed = len(results) - passed
    print(f"\n{'='*60}\nResults: {passed}/{len(results)} passed, {failed} failed")
    if failed:
        print("FAILED:", ", ".join(n for n, ok in results if not ok))
        return 1
    print("ALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
