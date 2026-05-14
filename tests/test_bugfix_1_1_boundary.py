"""Bugfix-1.1 — sentence boundary 在 <state_update thought="...。"/> attribute
值内误切句的 regression。

根因：``_find_boundary`` 旧实现按字符扫到 ``。`` 立即返回 idx —— 不感知
当前位置是否在 ``<tag...>`` 内。当 LLM 输出 ``<state_update thought="...粗
心了，赶紧补救。" />`` 时，thought 属性里的全角 ``。`` 触发切句，留下半截
unclosed ``<state_update mood="..."`` 进 sentence A，下游所有 strip 都要求
闭合 ``/>`` 或 ``</tag>`` —— 全漏 → 字面文本进 FE text_chunk + TTS。

修法：``_find_boundary`` 用 state machine 跟踪 ``<tagname...>`` 范围，标签
内的句末标点跳过。

本 test 跑 sentence_stream（完整链路）+ _find_boundary（unit），双重覆盖。
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.agents.chat import _find_boundary, _sentence_stream

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results: list = []


def check(name: str, condition: bool, detail: str = "") -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}" + (f" — {detail}" if detail else ""))
    results.append((name, condition))


async def _token_gen(*tokens):
    for t in tokens:
        yield t


async def _collect(agen):
    out = []
    async for s in agen:
        out.append(s)
    return out


# ---------------------------------------------------------------------------
# 1. 核心 regression：state_update thought 内的 。 不再误切句
# ---------------------------------------------------------------------------


async def test_state_update_with_full_width_period_in_thought():
    """**核心 bug case**：用户真机看到的 sample。"""
    print("\n[regression] state_update thought 含全角 。")
    sample = (
        '<state_update mood="sad" intimacy_delta="0" '
        'thought="哎呀，刚才光顾着聊天，居然忘了真正调用工具保存文件，'
        '太粗心了，赶紧补救。" />我帮你补救一下。'
    )
    # _find_boundary 应该跳过 thought 内的 。，找到 "补救一下。" 的最后那个
    idx = _find_boundary(sample)
    check(
        "boundary 在 /> 之后",
        idx > sample.index("/>"),
        f"got idx={idx}, /> at {sample.index('/>')}",
    )
    ch_at_idx = sample[idx] if idx >= 0 else "n/a"
    check(
        "boundary char 是末尾 。",
        idx != -1 and sample[idx] == "。",
        f"got idx={idx}, ch={ch_at_idx!r}",
    )


async def test_state_update_paired_form_with_period():
    """容错配对版 ``<state_update>thought</state_update>``。"""
    print("\n[regression] state_update 配对版含 。")
    sample = '<state_update>很难过。真的。</state_update>正文。'
    idx = _find_boundary(sample)
    check(
        "boundary 在 </state_update> 之后",
        idx > sample.index("</state_update>"),
        f"got idx={idx}",
    )


async def test_sentence_stream_no_unclosed_tag_leak():
    """端到端 sentence_stream：state_update 应整段进同一句，不被劈半。"""
    print("\n[regression] sentence_stream 不劈 state_update")
    sample = (
        '<emotion>sad</emotion>'
        '<state_update mood="sad" thought="太粗心了，赶紧补救。" />'
        '我帮你补救一下。'
    )
    sents = await _collect(_sentence_stream(_token_gen(sample)))
    # state_update 必须完整在某一句里（不能被劈半）
    joined = "".join(sents)
    check("flat join 等于原始", joined.replace(" ", "") == sample.replace(" ", "").strip() or joined == sample.strip(), f"got={sents}")
    # 不应有任何句子含 unclosed state_update（即 <state_update 但无对应 /> 或 </state_update>）
    for s in sents:
        if "<state_update" in s.lower():
            check(
                f"完整闭合 in sentence",
                "/>" in s or "</state_update>" in s.lower(),
                f"sentence={s!r}",
            )


# ---------------------------------------------------------------------------
# 2. 不能 regress：原 9 个 _find_boundary 测试 + 边缘 case
# ---------------------------------------------------------------------------


async def test_existing_boundary_regression():
    """v3-F 原 9 个 boundary case 全保留。"""
    print("\n[regression] 原 9 个 boundary case")
    check("Chinese period",          _find_boundary("你好。") == 2)
    check("Chinese exclaim",         _find_boundary("真棒！") == 2)
    check("Chinese question",        _find_boundary("怎么了？") == 3)
    check("ASCII exclaim",           _find_boundary("Wow!") == 3)
    check("ASCII question",          _find_boundary("OK?") == 2)
    check("Period + space",          _find_boundary("Hi. there") == 2)
    check("Period at end no space",  _find_boundary("3.14") == -1)
    check("No boundary",             _find_boundary("hello world") == -1)
    check("Empty string",            _find_boundary("") == -1)


async def test_math_lt_gt_not_eaten():
    """数学 ``2 < 3`` ``5 > 4`` 不应被误判为 tag。"""
    print("\n[negative] 数学 < > 不被吞")
    # < 后是空格，不进 in_tag
    check("'2 < 3 真好。' 切在 。", _find_boundary("2 < 3 真好。") == len("2 < 3 真好"))
    # 不进 in_tag → 句末 。 正常返回
    check("'5 > 4。' 切在 。", _find_boundary("5 > 4。") == len("5 > 4"))


async def test_heart_emoji_lt_three_not_eaten():
    """``<3`` heart emoji（数字开头）不应触发 in_tag。"""
    print("\n[negative] <3 emoticon 不被吞")
    check("'<3 真的！' 切在 ！", _find_boundary("<3 真的！") == len("<3 真的"))


async def test_state_update_at_end_no_reply_text():
    """``<state_update .../>`` 在 buffer 末尾、无后续正文 → 没有 boundary（等下个 chunk）。"""
    print("\n[edge] state_update 在末尾无正文")
    sample = '<state_update mood="sad" thought="哎呀。" />'
    # /> 之后没有任何字符 → 没有 sentence end，返回 -1
    idx = _find_boundary(sample)
    check("没有 boundary", idx == -1, f"got idx={idx}")


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------


async def _main():
    await test_state_update_with_full_width_period_in_thought()
    await test_state_update_paired_form_with_period()
    await test_sentence_stream_no_unclosed_tag_leak()
    await test_existing_boundary_regression()
    await test_math_lt_gt_not_eaten()
    await test_heart_emoji_lt_three_not_eaten()
    await test_state_update_at_end_no_reply_text()


if __name__ == "__main__":
    asyncio.run(_main())
    passed = sum(1 for _, ok in results if ok)
    failed = len(results) - passed
    print(f"\n=== {passed} passed, {failed} failed ===")
    sys.exit(0 if failed == 0 else 1)
