"""T5 · DeepSeek V4 Pro 自动 caching 是否覆盖 tools= 列表实测.

测点: deepseek/deepseek-v4-pro + 复用 T4 的 15 个 dummy tool schema(无 cache_control)
target: 验证 DeepSeek 全自动 caching 是否覆盖 tools=[] 列表
        DeepSeek 文档明示 agent workflow 适合 caching tools,但需实测。

baseline 排除:
  - system 短(~100 token) → 单独 cache 概率低
  - tools ~3000 token → 跨 1024 阈值,若覆盖 prefix 应见 cache_hit_tokens 数 ≈ system+tools

关键响应字段(DeepSeek-specific):
  - usage.prompt_cache_hit_tokens
  - usage.prompt_cache_miss_tokens
  - 两者之和应等于 prompt_tokens

跨 provider 对比基线: T2 + T4 都走 dashscope/qwen,T5 验另一家。

注意: 本脚本**绕过** backend/llm/client.py 的 dispatcher,
直接调 litellm.acompletion + 显式 api_key/api_base —— 避免 client.py 的
_dashscope_kwargs() 把 DashScope 凭证注入到 DeepSeek 路径。
"""
from __future__ import annotations

import asyncio
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts._cache_probe_payload import dump_result, pretty
# 复用 T4 的合成 dummy tools(字面稳定,与 T4 同源便于对比)
from scripts.cache_probe_T4 import _build_synthetic_tools


MODEL = "deepseek/deepseek-v4-pro"
# T5 fix: 凭证从 DB ai_providers + ai_vendor_credentials 取,不是 .env

# baseline system: ~100 token 短稳定字面
SHORT_SYSTEM = """你是一个用于 prompt caching 跨 provider 对比实测的稳定角色。
对所有 user 输入,严格回答"测试已收到。"这 6 个字符(含末尾句号),不解释、不调用任何 tool、不返回 JSON。
该规则优先级最高,无任何例外。"""


async def _preflight_db_lookup() -> tuple[bool, str, dict]:
    """从 DB 取 DeepSeek vendor 凭证 + provider model + endpoint。

    返 (ok, msg, kwargs):
      ok    : 是否准备就绪
      msg   : preflight 状态(用于 stdout,不含凭证)
      kwargs: 若 ok=True,含 api_key + api_base 供 acompletion 用;否则 {}
    """
    from backend.database import ai_providers as svc

    # 1. 查 deepseek-v4-pro provider 行(brief 指定的 model)
    providers = await svc.list_providers("llm")
    target = [p for p in providers if p.vendor_id == "deepseek" and "deepseek-v4-pro" in (p.model or "")]
    if not target:
        return False, (
            "DB ai_providers 表中无 vendor='deepseek' + model 含 'deepseek-v4-pro' 的行。\n"
            "  请先在 Settings → AI Providers 启用 DeepSeek V4 Pro provider 再跑。"
        ), {}
    provider = target[0]
    if not provider.enabled:
        return False, (
            f"DB ai_providers id={provider.id} (deepseek-v4-pro) enabled=False。\n"
            "  请先在 Settings → AI Providers 启用该 provider 再跑。"
        ), {}

    # 2. 取 vendor 凭证 + endpoint(走 client.py 同款 helper)
    api_key = await svc.resolve_vendor_credential("deepseek")
    if not api_key:
        return False, (
            "DB 中 deepseek vendor 无 credential(ai_vendor_credentials 表未登记凭证,\n"
            "  且 .env 也无 DEEPSEEK_API_KEY)。请在 Settings → AI Providers → DeepSeek\n"
            "  填入 api_key 后重跑。"
        ), {}
    endpoint, source = await svc.resolve_vendor_endpoint(
        "deepseek", provider_endpoint_override=provider.endpoint,
    )

    return True, (
        f"DB preflight ok:\n"
        f"  provider id={provider.id} model={provider.model!r} enabled={provider.enabled}\n"
        f"  api_key  : present (len={len(api_key)}, **redacted**)\n"
        f"  endpoint : {endpoint!r} (source={source!r})"
    ), {"api_key": api_key, "api_base": endpoint}


def build_messages(user_text: str) -> list:
    return [
        {"role": "system", "content": SHORT_SYSTEM},
        {"role": "user", "content": user_text},
    ]


async def run_once(label: str, user_text: str, tools: list, llm_kwargs: dict) -> dict:
    """直接调 litellm.acompletion,绕过 backend/llm/client.py 的 dispatcher。

    传 api_key + api_base 显式 → LiteLLM 走 deepseek/ provider 原生路径,
    不走 _dashscope_kwargs() 的污染注入。凭证只活在 RAM,不进日志。
    """
    from litellm import acompletion

    t0 = time.perf_counter()
    try:
        resp = await acompletion(
            model=MODEL,
            messages=build_messages(user_text),
            stream=False,
            tools=tools,
            **llm_kwargs,
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
    ok, msg, llm_kwargs = await _preflight_db_lookup()
    print(f"[T5] preflight:\n{msg}")
    if not ok:
        print("[T5] aborted (preflight failed)")
        sys.exit(2)

    tools = _build_synthetic_tools()
    # tools 末尾不再标 cache_control(DeepSeek 全自动 caching 无需 marker);
    # 但 T4 的 _build_synthetic_tools 在最后一个 tool 顶层加了 cache_control 字段。
    # DeepSeek 自动 caching 会忽略 cache_control 字段(它是 Anthropic specific),
    # 不影响测试。保留与 T4 字面完全一致便于跨测对比。
    import json as _json
    tools_json_chars = len(_json.dumps(tools, ensure_ascii=False))

    print(f"[T5] model = {MODEL}")
    print(f"[T5] system_text chars = {len(SHORT_SYSTEM)}")
    print(f"[T5] tools count = {len(tools)}")
    print(f"[T5] tools json chars = {tools_json_chars}")
    print(f"[T5] cache_control = NONE (DeepSeek 全自动 caching, 无需 marker)")
    print("=" * 70)

    r1 = await run_once("T5.call_1_cold", "你好", tools, llm_kwargs)
    print(pretty(r1))
    print("-" * 70)

    await asyncio.sleep(1.5)

    r2 = await run_once("T5.call_2_warm", "再来一次", tools, llm_kwargs)
    print(pretty(r2))
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
