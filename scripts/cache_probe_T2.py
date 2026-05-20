"""T2 · prefix 切换 fallback 实测.

把 model prefix 改成 dashscope/qwen3.6-max-preview 走 LiteLLM 原生 DashScope provider,
对比 T1 行为。验证:
  - client.py:24-35 _dashscope_kwargs() 注入 api_base/api_key 是否仍生效
    (原生 DashScope provider 可能不需要 api_base 覆写,会忽略;但不应当报错)
  - cache_control 是否生效

同 T1 payload(content blocks + cache_control),只换 prefix。
"""
from __future__ import annotations

import asyncio
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts._cache_probe_payload import SYSTEM_TEXT, dump_result, pretty


MODEL = "dashscope/qwen3.6-max-preview"  # LiteLLM 原生 DashScope provider prefix


def build_messages(user_text: str) -> list:
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
    print(f"[T2] model = {MODEL}")
    print(f"[T2] system_text chars = {len(SYSTEM_TEXT)}")
    print(f"[T2] cache_control marker = on last (only) text block of system")
    print(f"[T2] expect: LiteLLM 原生 DashScope provider 路径,_dashscope_kwargs() "
          f"api_base 覆写在此路径上行为待观察")
    print("=" * 70)

    r1 = await run_once("T2.call_1_cold", "你好")
    print(pretty(r1))
    print("-" * 70)

    await asyncio.sleep(1.5)

    r2 = await run_once("T2.call_2_warm", "再来一次")
    print(pretty(r2))
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
