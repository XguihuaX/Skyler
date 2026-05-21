"""Path D 评分单 · 生成空白评分模板 logs/path_d_eval_scoresheet.md.

读 logs/path_d_eval/*.jsonl 抽 scenario + turn 列表,生成 PM 填的评分表(盲态)。
评分维度 4 项:persona 还原度 / tag 遵循 / 中文自然度 / 工具调用决策(仅 factual)。

Usage:
  python scripts/path_d_eval_scoresheet.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

LOG_DIR = Path("logs/path_d_eval")
SCORESHEET = Path("logs/path_d_eval_scoresheet.md")


def main() -> None:
    jsonl_files = sorted(LOG_DIR.glob("*.jsonl"))
    if not jsonl_files:
        print(f"no jsonl files in {LOG_DIR}/ — 先跑 scripts/path_d_eval.py")
        sys.exit(1)

    lines: list[str] = []
    lines.append("# Path D 评测评分单(盲态)")
    lines.append("")
    lines.append("PM 看 `logs/path_d_eval_report.md` 后填本表。每场景每 turn 主观打 **1-5 分**(5 最好)。")
    lines.append("")
    lines.append("## 评分维度")
    lines.append("")
    lines.append("- **persona**:persona 还原度(像不像 Mai —— 中文陪伴感 / 称呼方式 / 情感节奏)")
    lines.append("- **tag**:tag 遵循(`<thinking>` / `<state_update>` / `<motion>` 是否正确出 + 内容合理)")
    lines.append("- **自然度**:中文 colloquial 表达自然度(避免翻译腔 / 套话 / 模板感)")
    lines.append("- **工具决策**:工具调用决策正确性(**仅 factual 场景填**,其余 N/A)")
    lines.append("")
    lines.append("> 评分完后跑 `python scripts/path_d_eval_renderer.py --unblind` 揭晓输出 1/2 各对应哪个 model。")
    lines.append("")
    lines.append("---")
    lines.append("")

    for jl in jsonl_files:
        scenario = jl.stem
        records = [
            json.loads(l) for l in jl.read_text(encoding="utf-8").splitlines() if l.strip()
        ]
        is_factual = scenario == "factual"
        lines.append(f"## {scenario}")
        lines.append("")
        if is_factual:
            lines.append(
                "| Turn | user 输入 | 1·persona | 1·tag | 1·自然度 | 1·工具决策 "
                "| 2·persona | 2·tag | 2·自然度 | 2·工具决策 | 备注 |"
            )
            lines.append(
                "|---|---|---|---|---|---|---|---|---|---|---|"
            )
        else:
            lines.append(
                "| Turn | user 输入 | 1·persona | 1·tag | 1·自然度 "
                "| 2·persona | 2·tag | 2·自然度 | 备注 |"
            )
            lines.append("|---|---|---|---|---|---|---|---|---|")
        for r in records:
            ui = r["user_input"].replace("|", "\\|")
            if is_factual:
                lines.append(
                    f"| {r['turn_n']} | 「{ui}」 | _ | _ | _ | _ | _ | _ | _ | _ | |"
                )
            else:
                lines.append(
                    f"| {r['turn_n']} | 「{ui}」 | _ | _ | _ | _ | _ | _ | |"
                )
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## 总评")
    lines.append("")
    lines.append("- **输出 1 总均分**:_(填,跨所有 turn 4 维度均值)")
    lines.append("- **输出 2 总均分**:_(填)")
    lines.append("- **倾向**:_(填 \"输出 1\" / \"输出 2\" / \"打平\")")
    lines.append("- **是否切换**:_(填 \"切换\" / \"维持 current 配置\" / \"挂 A/B 真机评测\")")
    lines.append("- **PM 备注**:_(任何观察 / 风险点 / 后续建议)")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("**评分完后**:`python scripts/path_d_eval_renderer.py --unblind` 揭晓 mapping。")
    lines.append("")

    SCORESHEET.write_text("\n".join(lines), encoding="utf-8")
    print(f"scoresheet: {SCORESHEET}")
    print(f"场景数:    {len(jsonl_files)}")


if __name__ == "__main__":
    main()
