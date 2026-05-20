"""T1 · 当前 prefix(openai/qwen3.6-max-preview) + content blocks + cache_control 实测.

判定:
  (a) 报错 (unsupported parameter)
  (b) silently strip 不报错但 cached_tokens 全零
  (c) pass-through 给 DashScope endpoint,第 2 次调用 cached_tokens 非零

跑两次相同 system(content blocks 形态,末尾 cache_control: ephemeral),不同 user 短问句,
对比 prompt_tokens / cached_tokens / cache_creation_input_tokens 等字段。

一次性 dev-only,不进产品调用链。
"""
from __future__ import annotations

import asyncio
import sys
import time
import traceback
from pathlib import Path

# 让脚本能 import backend.*
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts._cache_probe_payload import SYSTEM_TEXT, dump_result, pretty


MODEL = "openai/qwen3.6-max-preview"  # 当前 Skyler default_model prefix


def build_messages(user_text: str) -> list:
    """system 是 content blocks 形态,末尾 block 标 cache_control:ephemeral."""
    return [
        {
            "role": "system",
            "content": [
                {
                    "type": "text",
                    "text": SYSTEM_TEXT,
                    "cache_control": {"type": "ephemeral"},
                },
            ],
        },
        {"role": "user", "content": user_text},
    ]


async def run_once(label: str, user_text: str) -> dict:
    from backend.llm.client import call_llm

    t0 = time.perf_counter()
    try:
        resp = await call_llm(
            messages=build_messages(user_text),
            model=MODEL,
            stream=False,
        )
    except Exception as exc:
        return {
            "label": label,
            "error": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc()[:2000],
            "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1),
        }
    return dump_result(label, resp, (time.perf_counter() - t0) * 1000)


async def main() -> None:
    print(f"[T1] model = {MODEL}")
    print(f"[T1] system_text chars = {len(SYSTEM_TEXT)}")
    print(f"[T1] cache_control marker = on last (only) text block of system")
    print("=" * 70)

    r1 = await run_once("T1.call_1_cold", "你好")
    print(pretty(r1))
    print("-" * 70)

    # 间隔 1.5 秒,模拟连续两次请求(Qwen explicit cache TTL 5min,1.5s 足够稳)
    await asyncio.sleep(1.5)

    r2 = await run_once("T1.call_2_warm", "再来一次")
    print(pretty(r2))
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
