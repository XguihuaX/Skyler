"""T3 · implicit cache 当前是否在白拿实测.

当前 prefix(openai/qwen3.6-max-preview),system message 是普通 string (无 content blocks,
无 cache_control marker),跑 3 次相同 system + 不同 user 短问句。看 response.usage 是否
出现 cached_tokens / prompt_tokens_details.cached_tokens 等非零字段。

Qwen implicit cache 文档明示: ≥ 256 tokens 自动识别公共前缀,无需 client marker。
若 T3 看到 cached_tokens 非零 → Skyler 当前已经在白拿 implicit cache。
若 T3 cached_tokens 全零 → 当前没在拿,explicit cache (cache_control) 才是唯一路径。
"""
from __future__ import annotations

import asyncio
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts._cache_probe_payload import SYSTEM_TEXT, dump_result, pretty


MODEL = "openai/qwen3.6-max-preview"  # 同 T1,但 payload 不含 cache_control


def build_messages(user_text: str) -> list:
    """system 是普通 string,无 content blocks,无 cache_control marker。"""
    return [
        {"role": "system", "content": SYSTEM_TEXT},
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
    print(f"[T3] model = {MODEL}")
    print(f"[T3] system_text chars = {len(SYSTEM_TEXT)}")
    print(f"[T3] cache_control marker = NONE (普通 string system, implicit cache 探针)")
    print("=" * 70)

    r1 = await run_once("T3.call_1_cold", "你好")
    print(pretty(r1))
    print("-" * 70)

    await asyncio.sleep(1.5)

    r2 = await run_once("T3.call_2_warm", "再来一次")
    print(pretty(r2))
    print("-" * 70)

    await asyncio.sleep(1.5)

    r3 = await run_once("T3.call_3_warm", "第三次")
    print(pretty(r3))
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
