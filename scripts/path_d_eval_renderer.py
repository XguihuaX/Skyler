"""Path D 报告 renderer · 读 logs/path_d_eval/*.jsonl → logs/path_d_eval_report.md.

匿名化: 每场景独立随机化把 qwen/deepseek 分配为 "输出 1" / "输出 2",
mapping 持久化到 logs/path_d_eval_mapping.json,确保 renderer 可重跑得到同一份
匿名化报告(PM 评分中途若想换字号 / 调样式可重跑而不打乱)。

PM 评分完后跑 `python scripts/path_d_eval_renderer.py --unblind` 在 report 末尾
揭晓 mapping。`--reroll` 强制重新随机化(慎用 — 会让旧评分对应错乱)。

Usage:
  python scripts/path_d_eval_renderer.py            # 首次渲染(生成 mapping)/ 再次渲染(复用 mapping)
  python scripts/path_d_eval_renderer.py --unblind  # 末尾揭晓(评分完后用)
  python scripts/path_d_eval_renderer.py --reroll   # 强制重新随机化
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

LOG_DIR = Path("logs/path_d_eval")
REPORT = Path("logs/path_d_eval_report.md")
MAPPING = Path("logs/path_d_eval_mapping.json")


def _load_mapping() -> dict:
    if MAPPING.exists():
        return json.loads(MAPPING.read_text(encoding="utf-8"))
    return {}


def _save_mapping(m: dict) -> None:
    MAPPING.write_text(
        json.dumps(m, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )


def _format_tokens(t: dict) -> str:
    """One-line token summary, cross-provider 兼容(Qwen vs DeepSeek 字段不同)."""
    if not t:
        return "(no usage)"
    out: list = []
    flat_keys = [
        "prompt_tokens", "completion_tokens", "total_tokens",
        "cached_tokens",                                       # 旧 OpenAI 字段
        "prompt_cache_hit_tokens", "prompt_cache_miss_tokens",  # DeepSeek
    ]
    for k in flat_keys:
        if k in t and t[k] is not None:
            out.append(f"{k}={t[k]}")
    # nested(LiteLLM 新版本 / OpenAI 新字段)
    details = t.get("prompt_tokens_details") or {}
    if isinstance(details, dict) and details.get("cached_tokens") is not None:
        out.append(f"prompt_details.cached={details['cached_tokens']}")
    return " · ".join(out) if out else f"(usage={t!r})"


def main() -> None:
    parser = argparse.ArgumentParser(description="Path D report renderer (anonymized)")
    parser.add_argument(
        "--reroll", action="store_true",
        help="重新随机化 mapping(慎用,会让旧评分对应错乱)",
    )
    parser.add_argument(
        "--unblind", action="store_true",
        help="末尾揭晓 mapping(PM 评分完后用)",
    )
    args = parser.parse_args()

    if args.reroll and MAPPING.exists():
        MAPPING.unlink()

    mapping = _load_mapping()
    jsonl_files = sorted(LOG_DIR.glob("*.jsonl"))
    if not jsonl_files:
        print(f"no jsonl files in {LOG_DIR}/ — 先跑 scripts/path_d_eval.py")
        sys.exit(1)

    rng = random.Random()  # 不固定 seed — mapping 缺时真随机一次,后续 reuse

    lines: list[str] = []
    lines.append("# Path D 评测报告(盲测)")
    lines.append("")
    lines.append("> 两 model(Qwen Plus `openai/qwen3.6-plus` vs DeepSeek V4 Pro `deepseek/deepseek-v4-pro`)")
    lines.append("> 在 Mai cid=1 system prompt(vendor-aware,各自 forbidden_phrases 段)+ 真实 tools schema 下,")
    lines.append("> 同 user 输入 + 各自 chat_history 推进,**输出 1 / 输出 2 已每场景独立随机化**。")
    lines.append(">")
    lines.append("> 阅读路径:看完每个 turn 两栏输出 → 在 `logs/path_d_eval_scoresheet.md` 主观打 1-5 分;")
    lines.append("> 评分完后跑 `python scripts/path_d_eval_renderer.py --unblind` 揭晓。")
    lines.append("")
    lines.append("---")
    lines.append("")

    total_records = 0
    for jl in jsonl_files:
        scenario = jl.stem
        if scenario not in mapping:
            mapping[scenario] = rng.choice(["qwen", "deepseek"])
        out1_is = mapping[scenario]

        lines.append(f"## 场景:{scenario}")
        lines.append("")

        records = [
            json.loads(l) for l in jl.read_text(encoding="utf-8").splitlines() if l.strip()
        ]
        total_records += len(records)

        for r in records:
            if out1_is == "qwen":
                out1, out2 = r["qwen_plus_output"], r["deepseek_v4pro_output"]
                tok1, tok2 = r.get("qwen_tokens", {}), r.get("deepseek_tokens", {})
                ms1, ms2 = r.get("qwen_elapsed_ms"), r.get("deepseek_elapsed_ms")
                err1, err2 = r.get("qwen_error"), r.get("deepseek_error")
            else:
                out1, out2 = r["deepseek_v4pro_output"], r["qwen_plus_output"]
                tok1, tok2 = r.get("deepseek_tokens", {}), r.get("qwen_tokens", {})
                ms1, ms2 = r.get("deepseek_elapsed_ms"), r.get("qwen_elapsed_ms")
                err1, err2 = r.get("deepseek_error"), r.get("qwen_error")

            lines.append(f"### Turn {r['turn_n']} · user: 「{r['user_input']}」")
            lines.append("")

            lines.append("**输出 1:**")
            lines.append("")
            if err1:
                lines.append(f"⚠️ ERROR: `{err1}`")
            else:
                lines.append("```")
                lines.append(out1 or "(空回复)")
                lines.append("```")
            lines.append("")
            lines.append(f"_tokens: {_format_tokens(tok1)} · elapsed={ms1}ms_")
            lines.append("")

            lines.append("**输出 2:**")
            lines.append("")
            if err2:
                lines.append(f"⚠️ ERROR: `{err2}`")
            else:
                lines.append("```")
                lines.append(out2 or "(空回复)")
                lines.append("```")
            lines.append("")
            lines.append(f"_tokens: {_format_tokens(tok2)} · elapsed={ms2}ms_")
            lines.append("")

            lines.append("---")
            lines.append("")

    if args.unblind:
        lines.append("## 🔓 揭晓 · mapping")
        lines.append("")
        for s, v in mapping.items():
            other = "deepseek" if v == "qwen" else "qwen"
            lines.append(f"- **{s}**:输出 1 = `{v}` · 输出 2 = `{other}`")
        lines.append("")

    _save_mapping(mapping)
    REPORT.write_text("\n".join(lines), encoding="utf-8")

    print(f"report:   {REPORT}")
    print(f"mapping:  {MAPPING}  ({'已揭晓在 report 末尾' if args.unblind else '盲态 — 评分完后 --unblind'})")
    print(f"渲染:     {len(jsonl_files)} 场景 / {total_records} 轮")


if __name__ == "__main__":
    main()
