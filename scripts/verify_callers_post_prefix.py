"""verify_callers_post_prefix · INV-5 §5 acceptance 补丁:8 个非主链 caller direct trigger.

Phase 4 完成报告中 caller 回归表里 #3-#10 是"inference + Phase 3 logger
间接覆盖",**未直接 trigger**。本脚本补 acceptance gap:逐个 caller 用
synthetic input 直接调一次,确认切 dashscope/ prefix 后 LiteLLM 路径
真的调通(无 401 / endpoint mismatch / unsupported param 等)。

一次性 dev-only,**不进产品调用链**。

# 测试策略

- 优先调 caller 的底层 helper(`_call_judge_llm` / `_call_summary_llm`),
  这是最接近真实业务路径的复现
- 其它无独立 helper 的 caller(裸 inline `call_llm`)直接复用 caller 的
  model 参数 + synthetic prompt 调 `call_llm`,等价于复现该 caller
  的 LLM 调用路径

# acceptance

- ✅ call_llm 不抛 → caller 行 pass
- ❌ call_llm 抛 LLMError / 任意异常 → caller 行 fail,记 traceback
- ⚠️ 不强求 cached_tokens > 0(8 caller 都是裸 user prompt,marker no-op,
  cache 预期 = 0 by design)

# 输出

stdout 打表 + 末尾 jsonl-friendly summary 行(便于贴 INV-5 §5)
"""
from __future__ import annotations

import asyncio
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ───────────────────────────────────────────────────────────────────────────
# Test cases
# ───────────────────────────────────────────────────────────────────────────


async def case_3_compress_memories() -> dict:
    """#3 chat.py:795 — `call_llm` 不传 model → DB active(dashscope/qwen3.5-plus)。"""
    from backend.llm.client import call_llm

    prompt = "请简要回复:测试输入,无需 JSON,中文 10 字以内。"
    resp = await call_llm(
        messages=[{"role": "user", "content": prompt}],
        stream=False,
    )
    text = (resp.choices[0].message.content or "").strip()
    return {"chars": len(text), "preview": text[:50],
            "model_returned": getattr(resp, "model", None)}


async def case_4_summarize_clipboard() -> dict:
    """#4 clipboard.py:107 — 同 #3 路径(无 model arg → DB active)。"""
    from backend.llm.client import call_llm

    prompt = "总结以下文本:这是测试输入。请用一句话总结。"
    resp = await call_llm(
        messages=[{"role": "user", "content": prompt}],
        stream=False,
    )
    text = (resp.choices[0].message.content or "").strip()
    return {"chars": len(text), "preview": text[:50],
            "model_returned": getattr(resp, "model", None)}


async def case_5_translate_clipboard() -> dict:
    """#5 clipboard.py:175 — 同 #3/#4 路径。"""
    from backend.llm.client import call_llm

    prompt = "翻译成英文:你好"
    resp = await call_llm(
        messages=[{"role": "user", "content": prompt}],
        stream=False,
    )
    text = (resp.choices[0].message.content or "").strip()
    return {"chars": len(text), "preview": text[:50],
            "model_returned": getattr(resp, "model", None)}


async def case_6_extractor_planner() -> dict:
    """#6 extractor.py:287 — model=get_planner_model() → dashscope/qwen-turbo。"""
    from backend.llm.client import call_llm
    from backend.config import get_planner_model

    model = get_planner_model()
    prompt = "判断 yes/no:测试输入是否包含个人事实? 仅回答 YES 或 NO。"
    resp = await call_llm(
        messages=[{"role": "user", "content": prompt}],
        model=model,
        stream=False,
    )
    text = (resp.choices[0].message.content or "").strip()
    return {"chars": len(text), "preview": text[:50],
            "model_passed": model,
            "model_returned": getattr(resp, "model", None)}


async def case_7_profile_regen() -> dict:
    """#7 profile_regen.py:285 — model=get_planner_model()。"""
    from backend.llm.client import call_llm
    from backend.config import get_planner_model

    model = get_planner_model()
    prompt = "简短回复:测试 profile regen 路径。一句话 < 30 字。"
    resp = await call_llm(
        messages=[{"role": "user", "content": prompt}],
        model=model,
        stream=False,
    )
    text = (resp.choices[0].message.content or "").strip()
    return {"chars": len(text), "preview": text[:50],
            "model_passed": model,
            "model_returned": getattr(resp, "model", None)}


async def case_8_memory_extraction() -> dict:
    """#8 memory_extraction.py:115 — model=get_planner_model()。"""
    from backend.llm.client import call_llm
    from backend.config import get_planner_model

    model = get_planner_model()
    prompt = "从以下消息提取 facts(JSON 数组):'测试输入'。返回 [] 即可。"
    resp = await call_llm(
        messages=[{"role": "user", "content": prompt}],
        model=model,
        stream=False,
    )
    text = (resp.choices[0].message.content or "").strip()
    return {"chars": len(text), "preview": text[:50],
            "model_passed": model,
            "model_returned": getattr(resp, "model", None)}


async def case_9_summary_fold_helper() -> dict:
    """#9 summary.py:191 — 直接调底层 helper `_call_summary_llm(prompt)`。

    helper 内部用 model=get_summary_model() → dashscope/qwen3.5-flash。
    返 None 视为 LLM 失败;返 str 即 pass(即便文本是 '(无显著进展)')。
    """
    from backend.memory.summary import _call_summary_llm, get_summary_model

    prompt = (
        "任务:把现有摘要和新挤出窗口的对话片段合并,重新压缩成不超过 200 token 的新摘要。\n\n"
        "现有摘要:\n(尚无)\n\n新挤出窗口的对话片段:\n[用户] 测试\n[她] 嗯,知道了。\n"
    )
    raw = await _call_summary_llm(prompt)
    if raw is None:
        raise RuntimeError("_call_summary_llm returned None (LLM error path)")
    return {"chars": len(raw), "preview": raw[:50],
            "model_passed": get_summary_model()}


async def case_10_activity_judge_helper() -> dict:
    """#10 activity_judge.py:205 — 直接调底层 helper `_call_judge_llm(prompt)`。

    helper 内部用 model=get_judge_model() → dashscope/qwen-turbo。
    返 None 视为 LLM 失败;返 str 即 pass(后续 JSON parse 可能失败但
    LLM 路径已通)。
    """
    from backend.proactive.activity_judge import _call_judge_llm, get_judge_model

    prompt = (
        "你是 AI 陪伴 Momo,正在决定是否主动找用户说话。\n"
        "当前用户状态:测试输入。\n"
        '**只返 JSON,不要其他内容**:\n'
        '{"speak": false, "reason": "测试", "topic_hint": ""}'
    )
    raw = await _call_judge_llm(prompt)
    if raw is None:
        raise RuntimeError("_call_judge_llm returned None (LLM error path)")
    return {"chars": len(raw), "preview": raw[:50],
            "model_passed": get_judge_model()}


CASES = [
    (3,  "compress_memories      (chat.py:795,    no model → DB active)", case_3_compress_memories),
    (4,  "summarize_clipboard    (clipboard:107,  no model → DB active)", case_4_summarize_clipboard),
    (5,  "translate_clipboard    (clipboard:175,  no model → DB active)", case_5_translate_clipboard),
    (6,  "extractor              (extractor:287,  planner_model)        ", case_6_extractor_planner),
    (7,  "profile_regen          (profile_regen:285, planner_model)     ", case_7_profile_regen),
    (8,  "memory_extraction      (memory_extr:115,    planner_model)    ", case_8_memory_extraction),
    (9,  "summary fold           (summary:191,    summary_model)        ", case_9_summary_fold_helper),
    (10, "activity_judge         (activity_judge:205, judge_model)      ", case_10_activity_judge_helper),
]


# ───────────────────────────────────────────────────────────────────────────
# Runner
# ───────────────────────────────────────────────────────────────────────────


async def main() -> int:
    print("=" * 100)
    print("INV-5 §5 acceptance 补丁 · 8 非主链 caller direct trigger post-prefix-switch")
    print("=" * 100)

    results: list[dict] = []
    for n, name, fn in CASES:
        t0 = time.perf_counter()
        try:
            out = await fn()
            elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
            results.append({
                "n": n, "name": name, "status": "PASS",
                "elapsed_ms": elapsed_ms,
                **out,
            })
            print(f"  ✅ #{n} {name}  pass  [{elapsed_ms:.0f}ms, {out['chars']} chars]")
            print(f"       preview: {out['preview']!r}")
        except Exception as exc:
            elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
            results.append({
                "n": n, "name": name, "status": "FAIL",
                "elapsed_ms": elapsed_ms,
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc()[:1500],
            })
            print(f"  ❌ #{n} {name}  fail  [{elapsed_ms:.0f}ms]")
            print(f"       error: {type(exc).__name__}: {exc}")

    # ── Summary ──────────────────────────────────────────────────────────
    print()
    print("=" * 100)
    print("Summary:")
    pass_n = sum(1 for r in results if r["status"] == "PASS")
    fail_n = sum(1 for r in results if r["status"] == "FAIL")
    print(f"  pass = {pass_n} / 8")
    print(f"  fail = {fail_n} / 8")
    if fail_n > 0:
        print()
        print("FAILED cases — needs PM review:")
        for r in results:
            if r["status"] == "FAIL":
                print(f"  #{r['n']} {r['name']}")
                print(f"    {r['error']}")
                print(f"    traceback (first 800 chars):")
                for ln in r["traceback"][:800].splitlines():
                    print(f"      {ln}")
    print("=" * 100)
    return 0 if fail_n == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
