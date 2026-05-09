"""v3-G chunk 4 hotfix-1：TTS strip 链路覆盖 chunk 4 fallback 标签。

覆盖点：
  1. strip_tool_call_fallback：4 种 pattern 各自正解
  2. strip_all_for_tts：emotion / thinking / state_update / tool_call 全套
  3. has_partial_open_tag：流式 buffer 末尾未闭合标签检测
  4. preprocess_tts_text：第三道链路兜底（TTS 入口）
  5. 全是标签的 sentence 经 preprocess_tts_text 返回空字符串（caller 跳过）
  6. 多标签同时存在 strip 顺序无关
  7. 流式中 partial tag 边界："今天我很开心 <tool_ca" + "ll>{...}</tool_call> 真的"

无外部依赖；run::

    python tests/test_tts_strip_fallback.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.utils.text_filters import (
    has_partial_open_tag,
    strip_all_for_tts,
    strip_emotion,
    strip_state_update,
    strip_thinking,
    strip_tool_call_fallback,
)
from backend.tts import preprocess_tts_text

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))


# ---------------------------------------------------------------------------
# 1. strip_tool_call_fallback：4 种 pattern
# ---------------------------------------------------------------------------

def test_strip_qwen_xml():
    print("\n[strip_tool_call_fallback — Qwen <tool_call>]")
    text = '前文。<tool_call>{"name":"clipboard.translate","arguments":{}}</tool_call>后文。'
    out = strip_tool_call_fallback(text)
    check("tag removed", "<tool_call>" not in out and "</tool_call>" not in out)
    check("payload removed", "clipboard.translate" not in out, f"got {out!r}")
    check("surrounding text preserved", "前文。" in out and "后文。" in out)


def test_strip_anthropic_function_calls_block():
    print("\n[strip_tool_call_fallback — Anthropic <function_calls>]")
    text = (
        '好的~<function_calls><invoke name="proactive.snooze_wake_call">'
        '<parameter name="minutes">5</parameter></invoke></function_calls>稍后再叫。'
    )
    out = strip_tool_call_fallback(text)
    check("function_calls block removed",
          "<function_calls>" not in out and "</function_calls>" not in out)
    check("invoke removed", "<invoke" not in out)
    check("parameter removed", "<parameter" not in out and "minutes" not in out)
    check("surrounding text preserved", "好的~" in out and "稍后再叫。" in out,
          f"got {out!r}")


def test_strip_lone_invoke_block():
    print("\n[strip_tool_call_fallback — lone <invoke>]")
    text = '<invoke name="time.now">无参</invoke>现在的时间。'
    out = strip_tool_call_fallback(text)
    check("invoke block removed", "<invoke" not in out and "time.now" not in out)
    check("trailing text preserved", "现在的时间。" in out, f"got {out!r}")


def test_strip_markdown_json():
    print("\n[strip_tool_call_fallback — markdown json]")
    text = (
        '前面文本。```json\n{"name": "clipboard.translate", '
        '"arguments": {"target_lang": "zh"}}\n```后面文本。'
    )
    out = strip_tool_call_fallback(text)
    check("json block removed", '"name"' not in out and "clipboard.translate" not in out)
    check("```json marker removed", "```json" not in out and "```" not in out,
          f"got {out!r}")
    check("surrounding text preserved", "前面文本。" in out and "后面文本。" in out)


def test_strip_markdown_json_without_name_keeps_block():
    print("\n[strip_tool_call_fallback — markdown json without 'name' key]")
    # 用户单纯 paste 的非 tool_call json 不应被误删（与 tool_call_resilience 同语义）
    text = '前。```json\n{"foo": "bar"}\n```后。'
    out = strip_tool_call_fallback(text)
    check("non-tool json kept", "foo" in out and "bar" in out, f"got {out!r}")


def test_strip_no_tag_idempotent():
    print("\n[strip_tool_call_fallback — no tag idempotent]")
    text = "今天天气真好。"
    check("unchanged", strip_tool_call_fallback(text) == text)


def test_strip_empty_safe():
    print("\n[strip_tool_call_fallback — empty / None]")
    check("empty string", strip_tool_call_fallback("") == "")
    check("None safe", strip_tool_call_fallback(None) is None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 2. strip_all_for_tts：四道全套
# ---------------------------------------------------------------------------

def test_strip_all_emotion_thinking_state_toolcall():
    print("\n[strip_all_for_tts — 全套四道]")
    text = (
        '<emotion>happy</emotion>'
        '<thinking>用户好开心</thinking>'
        '<state_update mood="happy" intimacy_delta="+1" />'
        '今天真好~'
        '<tool_call>{"name":"x","arguments":{}}</tool_call>'
        '再见。'
    )
    out = strip_all_for_tts(text)
    check("emotion stripped", "<emotion>" not in out)
    check("thinking stripped", "<thinking>" not in out)
    check("state_update stripped", "<state_update" not in out)
    check("tool_call stripped", "<tool_call>" not in out)
    check("正文保留", "今天真好" in out and "再见" in out, f"got {out!r}")


def test_strip_all_order_independent():
    print("\n[strip_all_for_tts — 多标签顺序无关]")
    # 同一文本里多种标签交错，函数应都剥掉
    text = (
        'A<tool_call>{"name":"x"}</tool_call>'
        'B<emotion>happy</emotion>'
        'C<thinking>think</thinking>'
        'D<state_update mood="happy" />'
        'E'
    )
    out = strip_all_for_tts(text)
    check("all 4 stripped",
          "<tool_call" not in out and "<emotion" not in out
          and "<thinking" not in out and "<state_update" not in out,
          f"got {out!r}")
    check("normal letters preserved", all(c in out for c in "ABCDE"))


def test_strip_all_empty():
    print("\n[strip_all_for_tts — 空 / None]")
    check("empty", strip_all_for_tts("") == "")
    check("None", strip_all_for_tts(None) is None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 3. has_partial_open_tag
# ---------------------------------------------------------------------------

def test_partial_open_tag_typing():
    print("\n[has_partial_open_tag — open tag still being typed]")
    # 标签本体未结束（``>`` 还没来）→ 应等下一 chunk
    check("partial <tool_ca", has_partial_open_tag("今天好开心。<tool_ca"))
    check("partial <tool_call", has_partial_open_tag("今天好开心。<tool_call"))
    check("partial <function_calls", has_partial_open_tag("好的~<function_calls"))
    check("partial <invoke", has_partial_open_tag('好的~<invoke name="x"'))
    check("partial <emotion", has_partial_open_tag("<emotion"))
    check("partial <thinking", has_partial_open_tag("<thinking"))
    check("partial <state_update", has_partial_open_tag("<state_update mood"))
    check("partial markdown json", has_partial_open_tag('好的~```json\n{"name'))


def test_partial_open_tag_block_unclosed():
    print("\n[has_partial_open_tag — block opened but not yet closed]")
    # 开标签完整（``>`` 已来）但块内容未关闭 —— 块内可能有 ``。`` 误触发 boundary
    check("<tool_call> open block",
          has_partial_open_tag('今天。<tool_call>{"name":"x","arg":"我开心。"}'))
    check("<function_calls> open block",
          has_partial_open_tag('好的~<function_calls><invoke name="y">'))
    check("<invoke> open block",
          has_partial_open_tag('好的~<invoke name="z"><parameter'))


def test_partial_open_tag_closed():
    print("\n[has_partial_open_tag — closed tag returns False]")
    # 完整闭合 → 应正常允许切句
    check("closed tool_call",
          not has_partial_open_tag(
              '今天。<tool_call>{"name":"x","arguments":{}}</tool_call>真的。'
          ))
    check("closed function_calls",
          not has_partial_open_tag(
              '好的~<function_calls><invoke name="x"></invoke></function_calls>稍等。'
          ))
    check("plain text without tags", not has_partial_open_tag("今天天气真好。"))
    check("empty", not has_partial_open_tag(""))
    check("None safe", not has_partial_open_tag(None))  # type: ignore[arg-type]


def test_partial_streaming_concat():
    print("\n[has_partial_open_tag — streaming concat scenario]")
    # 用户场景："今天我很开心 <tool_ca" + "ll>{...}</tool_call> 真的"
    chunk1 = "今天我很开心。<tool_ca"
    chunk2 = 'll>{"name":"x","arguments":{}}</tool_call>真的。'
    check("chunk1 → partial detected", has_partial_open_tag(chunk1))
    full = chunk1 + chunk2
    check("after concat → partial false (block closed)",
          not has_partial_open_tag(full),
          f"got {has_partial_open_tag(full)!r}")
    # 经 strip_all_for_tts 后两个 chunk 串起来的最终 sentence 应干净
    cleaned = strip_all_for_tts(full)
    check("after strip — no fallback tag",
          "<tool_call>" not in cleaned and "name" not in cleaned,
          f"got {cleaned!r}")
    check("正文保留", "今天我很开心" in cleaned and "真的" in cleaned)


# ---------------------------------------------------------------------------
# 4. preprocess_tts_text：第三道链路（TTS 入口）
# ---------------------------------------------------------------------------

def test_preprocess_strips_chunk4_fallback():
    print("\n[preprocess_tts_text — chunk 4 fallback strip]")
    text = (
        '<emotion>happy</emotion>好的~'
        '<tool_call>{"name":"x","arguments":{}}</tool_call>'
        '稍后叫你。'
    )
    out = preprocess_tts_text(text)
    check("emotion gone", "<emotion>" not in out)
    check("tool_call gone", "<tool_call>" not in out)
    check("正文保留", "好的" in out and "稍后叫你" in out, f"got {out!r}")


def test_preprocess_all_tags_returns_empty():
    print("\n[preprocess_tts_text — sentence is all tags → empty]")
    # 全是 fallback tool_call 标签 —— TTS caller 应该跳过
    text = '<tool_call>{"name":"clipboard.translate","arguments":{}}</tool_call>'
    out = preprocess_tts_text(text)
    check("returns empty string", out == "", f"got {out!r}")


def test_preprocess_empty_after_invoke_strip():
    print("\n[preprocess_tts_text — function_calls only → empty]")
    text = (
        '<function_calls><invoke name="proactive.snooze_wake_call">'
        '<parameter name="minutes">5</parameter></invoke></function_calls>'
    )
    out = preprocess_tts_text(text)
    check("returns empty string", out == "", f"got {out!r}")


def test_preprocess_state_update_still_stripped():
    print("\n[preprocess_tts_text — state_update 第三道兜底]")
    text = '<state_update mood="happy" intimacy_delta="+1" />嘿，辛苦啦！'
    out = preprocess_tts_text(text)
    check("state_update gone", "<state_update" not in out)
    check("正文保留", "嘿，辛苦啦！" in out, f"got {out!r}")


def test_preprocess_multi_pattern_combo():
    print("\n[preprocess_tts_text — emotion+thinking+state+tool_call+motion+action]")
    text = (
        '<emotion>happy</emotion>'
        '<thinking>想了想</thinking>'
        '<state_update mood="happy" />'
        '*笑了笑*嗨~<motion>害羞</motion>'
        '(悄声)今天天气真好~'
        '<tool_call>{"name":"x","arguments":{}}</tool_call>'
    )
    out = preprocess_tts_text(text)
    check("all tags removed",
          all(t not in out for t in [
              "<emotion", "<thinking", "<state_update", "<motion",
              "<tool_call", "*笑了笑*", "(悄声)",
          ]),
          f"got {out!r}")
    check("正文保留", "嗨" in out and "今天天气真好" in out)


# ---------------------------------------------------------------------------
# 5. 单独 strip_emotion / strip_thinking / strip_state_update 旧 case 不破
# ---------------------------------------------------------------------------

def test_existing_strip_thinking_unchanged():
    print("\n[regression — strip_thinking 旧 case 仍通过]")
    text = "<thinking>独白</thinking>正文。"
    out = strip_thinking(text)
    check("strip_thinking still works", out == "正文。", f"got {out!r}")


def test_existing_strip_state_update_unchanged():
    print("\n[regression — strip_state_update 旧 case 仍通过]")
    text = '<state_update mood="happy" />正文。'
    out = strip_state_update(text)
    check("strip_state_update still works", out == "正文。", f"got {out!r}")


def test_strip_emotion_self_consistent():
    print("\n[strip_emotion — 单独调]")
    text = "<emotion>happy</emotion>嗨~"
    out = strip_emotion(text)
    check("emotion stripped", out == "嗨~", f"got {out!r}")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> None:
    test_strip_qwen_xml()
    test_strip_anthropic_function_calls_block()
    test_strip_lone_invoke_block()
    test_strip_markdown_json()
    test_strip_markdown_json_without_name_keeps_block()
    test_strip_no_tag_idempotent()
    test_strip_empty_safe()

    test_strip_all_emotion_thinking_state_toolcall()
    test_strip_all_order_independent()
    test_strip_all_empty()

    test_partial_open_tag_typing()
    test_partial_open_tag_block_unclosed()
    test_partial_open_tag_closed()
    test_partial_streaming_concat()

    test_preprocess_strips_chunk4_fallback()
    test_preprocess_all_tags_returns_empty()
    test_preprocess_empty_after_invoke_strip()
    test_preprocess_state_update_still_stripped()
    test_preprocess_multi_pattern_combo()

    test_existing_strip_thinking_unchanged()
    test_existing_strip_state_update_unchanged()
    test_strip_emotion_self_consistent()

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
    main()
