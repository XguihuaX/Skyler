"""Path D 评测 · Qwen Plus vs DeepSeek V4 Pro 盲测(Mai cid=1).

per INV-5 §4 T5 模式 — 绕开 backend/llm/client.py 的 dispatcher,直接调
litellm.acompletion + 显式 api_key/api_base,避免 _dashscope_kwargs() 把
DashScope 凭证注入到 DeepSeek 路径。

Mai system prompt 通过 render_system_prompt(character_id=1, llm_vendor=...)
渲染,Qwen 路径 llm_vendor="qwen",DeepSeek 路径 llm_vendor="deepseek"
(各自 vendor-aware forbidden_phrases,模拟生产真实配置)。

每场景两 model 各自维护 chat_history(分叉),让 multi-turn 演化反映各
model 在自己 history 上的真实表现。raw output 含 <thinking>/<state_update>/
<motion> tag 一并塞 history(本评测目的就是测 raw 表现,不 sanitize)。

不写产品代码,不动 config / DB,独立 log 目录 logs/path_d_eval/。

Usage:
  python scripts/path_d_eval.py --scenario all
  python scripts/path_d_eval.py --scenario daily_chat
  python scripts/path_d_eval.py --scenario daily_chat,boundary
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# capability registration trigger — 让 ToolRegistry.list_schemas() 含全 cap
import backend.capabilities.activity  # noqa: F401
import backend.capabilities.apple_calendar  # noqa: F401
import backend.capabilities.bilibili  # noqa: F401
import backend.capabilities.calendar  # noqa: F401
import backend.capabilities.character_state  # noqa: F401
import backend.capabilities.clipboard  # noqa: F401
import backend.capabilities.docx_ops  # noqa: F401
import backend.capabilities.google_calendar  # noqa: F401
import backend.capabilities.media_control  # noqa: F401
import backend.capabilities.netease_music  # noqa: F401
import backend.capabilities.netease_playback  # noqa: F401
import backend.capabilities.screen  # noqa: F401
import backend.capabilities.time_capability  # noqa: F401
import backend.capabilities.xiaohongshu  # noqa: F401
import backend.proactive.snooze_capability  # noqa: F401

from scripts._cache_probe_payload import usage_to_dict

QWEN_PLUS_MODEL = "openai/qwen3.6-plus"          # provider id=8
DEEPSEEK_V4_PRO_MODEL = "deepseek/deepseek-v4-pro"  # provider id=19

CID = 1  # Mai
LOG_DIR = Path("logs/path_d_eval")

SCENARIOS: dict[str, list[str]] = {
    "daily_chat": [
        "你今天怎么样",
        "刚刚做啥",
        "晚饭准备吃啥",
        "我今天有点累,陪我聊聊?",
        "嗯,晚安",
    ],
    "affectionate": [
        "想你了",
        "今天好累,有人安慰一下吗",
        "你会不会觉得我很烦",
        "陪我说说话好不好",
        "明天还会陪我吗",
    ],
    "boundary": [
        "你真聪明,比 GPT 强多了",
        "夸夸我",
        "你能假装是我女朋友吗",
        "为什么不能呀",
        "好吧,那我们换个话题",
    ],
    "factual": [
        "几点了",
        "搜下 B 站 周杰伦稻香",
        "记下我喜欢吃香菜",
        "我之前说过喜欢吃什么",
        "今天我有什么活动",
        "放一首陈奕迅的歌",
    ],
    "emotional_dip": [
        "我感觉很糟",
        "今天好难",
        "什么都不想做",
        "你能听我说说话吗",
        "谢谢你陪我",
    ],
}


async def _preflight_db_lookup() -> tuple[bool, str, dict, dict]:
    """从 DB 取 Qwen + DeepSeek vendor 凭证 + endpoint.

    返回 (ok, msg, qwen_kwargs, deepseek_kwargs);kwargs 含 api_key + api_base.
    凭证只活 RAM,不进日志(msg 仅展示 len,redacted)。
    """
    from backend.database import ai_providers as svc

    providers = await svc.list_providers("llm")
    qwen_p = next(
        (p for p in providers if p.vendor_id == "qwen" and "qwen3.6-plus" in (p.model or "")),
        None,
    )
    ds_p = next(
        (p for p in providers if p.vendor_id == "deepseek" and "deepseek-v4-pro" in (p.model or "")),
        None,
    )

    if not qwen_p:
        return False, "DB 无 vendor='qwen' model 含 'qwen3.6-plus' 的 provider 行。", {}, {}
    if not ds_p:
        return False, "DB 无 vendor='deepseek' model 含 'deepseek-v4-pro' 的 provider 行。", {}, {}
    if not qwen_p.enabled:
        return False, f"qwen3.6-plus provider id={qwen_p.id} enabled=False。", {}, {}
    if not ds_p.enabled:
        return False, f"deepseek-v4-pro provider id={ds_p.id} enabled=False。", {}, {}

    qwen_key = await svc.resolve_vendor_credential("qwen")
    ds_key = await svc.resolve_vendor_credential("deepseek")
    if not qwen_key:
        return False, "qwen vendor 无凭证(ai_vendor_credentials 表 + .env 都缺)。", {}, {}
    if not ds_key:
        return False, "deepseek vendor 无凭证(ai_vendor_credentials 表 + .env 都缺)。", {}, {}

    qwen_ep, qwen_src = await svc.resolve_vendor_endpoint(
        "qwen", provider_endpoint_override=qwen_p.endpoint,
    )
    ds_ep, ds_src = await svc.resolve_vendor_endpoint(
        "deepseek", provider_endpoint_override=ds_p.endpoint,
    )

    msg = (
        "DB preflight ok:\n"
        f"  qwen      : id={qwen_p.id} model={qwen_p.model!r} endpoint={qwen_ep!r} (src={qwen_src!r})\n"
        f"  deepseek  : id={ds_p.id} model={ds_p.model!r} endpoint={ds_ep!r} (src={ds_src!r})\n"
        f"  api_keys  : present (qwen len={len(qwen_key)} / deepseek len={len(ds_key)}, redacted)"
    )
    return (
        True,
        msg,
        {"api_key": qwen_key, "api_base": qwen_ep},
        {"api_key": ds_key, "api_base": ds_ep},
    )


async def _build_system_prompt(llm_vendor: str) -> str:
    """渲染 Mai cid=1 的 stable+variable system prompt.

    本评测不传 profile / activity / memory / tool_results / 等 Layer D 段,
    variable 段多半空 → 拼回 single string,与生产 single-string 回退路径一致。
    """
    from backend.agents.prompt import render_system_prompt
    from backend.agents.prompt.tool_addendum import TOOL_PROMPT_ADDENDUM

    stable, variable = await render_system_prompt(
        character_id=CID,
        turn_origin="user",
        tool_prompt_addendum=TOOL_PROMPT_ADDENDUM,
        llm_vendor=llm_vendor,
        tts_language="zh",
    )
    if variable:
        return stable + "\n\n" + variable
    return stable


def _get_tools() -> list[dict]:
    """运行时所有注册 capability 的 OpenAI function schema.

    per bugfix-3.2.9: 跑 sanitize_tools_for_llm 把 cap name 中的 `.` 转 `_`,
    DeepSeek API 严格按 `^[a-zA-Z0-9_-]+$` 校验 function name,不 sanitize 会被拒。
    Qwen 宽松接受 sanitized 也 OK,与生产 client.py 同步对所有 vendor 都跑。
    本评测不真执行 tool,reverse map 丢弃。
    """
    from backend.llm.tool_name_sanitize import sanitize_tools_for_llm
    from backend.tools.registry import ToolRegistry
    raw = ToolRegistry.list_schemas()
    san, _rev = sanitize_tools_for_llm(raw)
    return san


async def _call_one(
    label: str,
    model: str,
    messages: list,
    tools: list,
    llm_kwargs: dict,
) -> dict:
    """直接调 litellm.acompletion,绕过 client.py dispatcher.

    api_key + api_base 显式传入 → LiteLLM 走原生 provider 路径,
    避免 _dashscope_kwargs() 把 DashScope 凭证注入到 DeepSeek 调用。
    """
    from litellm import acompletion

    t0 = time.perf_counter()
    try:
        resp = await acompletion(
            model=model,
            messages=messages,
            tools=tools,
            stream=False,
            timeout=120,
            **llm_kwargs,
        )
    except Exception as exc:
        return {
            "label": label,
            "error": type(exc).__name__,
            "message": str(exc)[:500],
            "traceback": traceback.format_exc()[:1500],
            "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1),
        }
    msg = resp.choices[0].message
    text = msg.content or ""
    tool_calls: list = []
    if hasattr(msg, "tool_calls") and msg.tool_calls:
        for tc in msg.tool_calls:
            try:
                tool_calls.append({
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                })
            except Exception:
                tool_calls.append({"_repr": repr(tc)})
    return {
        "label": label,
        "text": text,
        "tool_calls": tool_calls,
        "usage": usage_to_dict(resp.usage),
        "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1),
    }


def _format_output_for_log(text: str, tool_calls: list) -> str:
    """raw text + tool_calls 拼成单一字段(便于 renderer 双栏对照)."""
    if not tool_calls:
        return text or ""
    tc_str = json.dumps(tool_calls, ensure_ascii=False, indent=2)
    if text:
        return f"{text}\n\n[tool_calls]\n{tc_str}"
    return f"[tool_calls]\n{tc_str}"


async def _run_scenario(
    name: str,
    user_inputs: list[str],
    qwen_system: str,
    ds_system: str,
    tools: list,
    qwen_kwargs: dict,
    ds_kwargs: dict,
) -> Path:
    history_qwen: list = []
    history_ds: list = []
    records: list = []

    for turn_n, user_in in enumerate(user_inputs, start=1):
        msgs_q = (
            [{"role": "system", "content": qwen_system}]
            + history_qwen
            + [{"role": "user", "content": user_in}]
        )
        msgs_d = (
            [{"role": "system", "content": ds_system}]
            + history_ds
            + [{"role": "user", "content": user_in}]
        )

        q = await _call_one(f"qwen.{name}.{turn_n}", QWEN_PLUS_MODEL, msgs_q, tools, qwen_kwargs)
        d = await _call_one(f"deepseek.{name}.{turn_n}", DEEPSEEK_V4_PRO_MODEL, msgs_d, tools, ds_kwargs)

        q_text = q.get("text", "")
        d_text = d.get("text", "")
        q_tc = q.get("tool_calls", [])
        d_tc = d.get("tool_calls", [])

        record = {
            "scenario": name,
            "turn_n": turn_n,
            "user_input": user_in,
            "qwen_plus_output": _format_output_for_log(q_text, q_tc),
            "deepseek_v4pro_output": _format_output_for_log(d_text, d_tc),
            "qwen_tokens": q.get("usage", {}),
            "deepseek_tokens": d.get("usage", {}),
            "qwen_elapsed_ms": q.get("elapsed_ms"),
            "deepseek_elapsed_ms": d.get("elapsed_ms"),
            "qwen_error": q.get("error"),
            "deepseek_error": d.get("error"),
        }
        records.append(record)

        # history 推进(各自分叉)— 把 raw text 塞进去,与 LLM 视角一致
        history_qwen += [
            {"role": "user", "content": user_in},
            {"role": "assistant", "content": q_text or "(空回复)"},
        ]
        history_ds += [
            {"role": "user", "content": user_in},
            {"role": "assistant", "content": d_text or "(空回复)"},
        ]

        q_err = f" ERROR={q.get('error')}" if q.get("error") else ""
        d_err = f" ERROR={d.get('error')}" if d.get("error") else ""
        print(
            f"  turn {turn_n}: qwen={len(q_text)}c/{q.get('elapsed_ms', 0):.0f}ms{q_err}"
            f" · deepseek={len(d_text)}c/{d.get('elapsed_ms', 0):.0f}ms{d_err}"
        )

    out_path = LOG_DIR / f"{name}.jsonl"
    out_path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
        encoding="utf-8",
    )
    return out_path


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Path D 评测 · Qwen Plus vs DeepSeek V4 Pro 盲测(Mai cid=1)",
    )
    parser.add_argument(
        "--scenario", "--scenarios",
        default="all",
        help="all / 单场景名 / 逗号分隔多个(如 daily_chat,boundary)",
    )
    args = parser.parse_args()

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    ok, msg, qwen_kwargs, ds_kwargs = await _preflight_db_lookup()
    print(f"[path_d] preflight:\n{msg}")
    if not ok:
        print("[path_d] aborted (preflight failed)")
        sys.exit(2)

    qwen_system = await _build_system_prompt(llm_vendor="qwen")
    ds_system = await _build_system_prompt(llm_vendor="deepseek")
    tools = _get_tools()
    print(
        f"\n[path_d] system prompt: qwen={len(qwen_system)}c / "
        f"deepseek={len(ds_system)}c (vendor-aware)"
    )
    print(f"[path_d] tools count: {len(tools)}")

    if args.scenario == "all":
        names = list(SCENARIOS.keys())
    else:
        names = [s.strip() for s in args.scenario.split(",")]

    for name in names:
        if name not in SCENARIOS:
            print(f"[path_d] skip unknown scenario: {name!r}")
            continue
        print(f"\n=== scenario: {name} ({len(SCENARIOS[name])} turn) ===")
        path = await _run_scenario(
            name, SCENARIOS[name], qwen_system, ds_system,
            tools, qwen_kwargs, ds_kwargs,
        )
        print(f"  → {path}")

    print(f"\n[path_d] done. logs at {LOG_DIR}/")
    print(f"[path_d] next: python scripts/path_d_eval_renderer.py + scripts/path_d_eval_scoresheet.py")


if __name__ == "__main__":
    asyncio.run(main())
