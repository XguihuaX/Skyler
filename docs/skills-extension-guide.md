# Skyler Skill Extension Guide (v3.5 chunk 7+)

Skyler 是「个人乐高底盘」——加新能力（"skill"）有两条路径，按你的能力来源
挑一条即可：

* **姿态 A**：用 Python 库就能实现 → 写本地 capability（5 分钟模板）
* **姿态 B**：第三方 SaaS 提供官方 MCP server → config.yaml 加几行 + UI 启用

本指南给两侧的最小可行模板 + 决策树 + 候选 skill 推荐姿态对照。

---

## 决策树

```
新 skill 想接入？
  │
  ├─ Python 库能跑（docx / openpyxl / pdfplumber / pyperclip / pyautogui...）
  │      → 姿态 A
  │
  ├─ 第三方 SaaS 有官方 MCP server（Notion / Linear / Slack / GitHub / ...）
  │      → 姿态 B
  │
  ├─ 两种都行 → 姿态 A（少一层进程 + 直接 SAFE 沙箱）
  │
  └─ HTTP API 但无 MCP server → 姿态 A，handler 内直接 ``httpx`` 调用
       （不要为了 "MCP 时髦" 而单独写 MCP server）
```

### 反模式

* 不要为只 wrap 一个 HTTP endpoint 的简单功能写 MCP server——直接 capability
  内 `httpx.AsyncClient` 调用更省事
* 不要为 LLM 不会主动想用的能力做姿态 B——npx 首次启动有 30s 拉包代价
* SAFE 沙箱不能省——任何接收用户输入的 filename 都必须走 `safe_resolve`

---

## 姿态 A：本地 capability 模板

### 用户视角

「加一个能力，比如读 Excel 表格」：

1. `pip install openpyxl`，加进 `requirements.txt`
2. 写 `backend/capabilities/excel_ops.py`（模板见下）
3. `backend/main.py` 加一行 `import backend.capabilities.excel_ops`
4. 重启后端，ChatAgent 自动看到新能力（无需改前端、无需改 SettingsPanel）

### 开发者模板

```python
"""backend/capabilities/excel_ops.py — v3.5 chunk 7+ 模板"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from backend.capabilities import Consumer, TriggerMode, register_capability
from backend.config import config_yaml
from backend.utils.safe_path import ensure_sandbox_dir, safe_resolve


def _safe_dir() -> Path:
    raw = ((config_yaml.get("skills") or {}).get("excel") or {}).get(
        "safe_dir"
    ) or "~/Documents/Skyler/sheets"
    return ensure_sandbox_dir(Path(raw).expanduser(), mode=0o700)


@register_capability(
    name="excel.read_sheet",
    display_name="读取 Excel 表格",
    description=(
        "读取 .xlsx 表格的指定 sheet 内容（默认第一个 sheet）。"
        "适用场景：用户说「读一下那个表」「看看 XX.xlsx 里写了啥」。\n\n"
        "参数：\n"
        "- filename: 文件名（带或不带 .xlsx 后缀）\n"
        "- sheet_name: sheet 名称，可选；缺省读第一个\n\n"
        "返回 ``{sheet, rows: [[cell, ...], ...], row_count}``。"
    ),
    category="files",
    consumers=[Consumer.CHAT_AGENT],
    trigger_modes=[TriggerMode.ON_DEMAND],
    icon="table",
    parameters_schema={
        "type": "object",
        "properties": {
            "filename": {"type": "string"},
            "sheet_name": {"type": "string"},
        },
        "required": ["filename"],
    },
)
async def excel_read_sheet(
    filename: str = "",
    sheet_name: str = "",
    **_kwargs: Any,
) -> dict:
    if not filename.strip():
        return {"error": "missing_filename"}
    # 自动补后缀
    name = filename.strip()
    if not name.lower().endswith(".xlsx"):
        name += ".xlsx"
    try:
        target = safe_resolve(_safe_dir(), name, allow_subdirs=False)
    except ValueError as exc:
        return {"error": "invalid_path", "detail": str(exc)}
    if not target.exists():
        return {"error": "file_not_found", "filename": name}
    try:
        wb = load_workbook(target, read_only=True, data_only=True)
        ws = wb[sheet_name] if sheet_name else wb.active
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
    except Exception as exc:
        return {"error": "parse_failed", "detail": str(exc)}
    return {"sheet": ws.title, "rows": rows, "row_count": len(rows)}
```

### Checklist

* [ ] handler 用 `async def`，接 `**_kwargs` 兜 `user_id`
* [ ] description 走 chunk 1.7 verbatim 引导风格（强引导 + 触发场景 + 参数
      说明 + 返回 schema）
* [ ] 所有错误返 `{"error": "<code>", "detail": ...}` dict，**不 raise**——
      让 LLM 接着说人话
* [ ] 接用户 filename 的所有路径都走 `safe_resolve`，禁绝对路径 / `..` /
      路径分隔符
* [ ] 沙箱目录用户可见时放 `~/Documents/Skyler/<feature>/`；内部 token /
      配置放 `~/.skyler/`
* [ ] `backend/main.py` 加 `import` 触发 `@register_capability` side-effect
* [ ] 跑 `tests/test_<feature>_capabilities.py` 测 happy path + error 全路径

---

## 姿态 B：MCP server 一键启用模板

### 用户视角

「加一个 Slack 集成」：

1. 看 [modelcontextprotocol.io](https://modelcontextprotocol.io) /
   server 作者 GitHub README，拿到 npm 包名（如 `@some-org/slack-mcp-server`）
2. 编辑 `config.yaml` `mcp_clients` 段加一项（模板见下）
3. 重启后端
4. 打开前端 [Settings → 扩展能力] section → 看到「Slack」行 → 点 [配置凭证] →
   输入 token → 关 modal → toggle 启用 → 30s 内 ChatAgent 看到新 tools

### config.yaml 模板

```yaml
mcp_clients:
  # 名字随意（用于 UI 展示 + DB key）
  slack:
    description: Slack 消息读写（需要 SLACK_BOT_TOKEN，UI 配置）
    transport: stdio
    command: npx
    args:
    - -y
    - '@some-org/slack-mcp-server'
    env_required:
    - SLACK_BOT_TOKEN
    enabled: false              # 默认 false，用户在 UI 翻 ON
    expose_via_skyler_server: false  # 通常 false（不级联代理给外部 MCP client）
```

### 字段说明

| 字段 | 含义 |
|---|---|
| `transport` | `stdio`（绝大多数 npx-based server）或 `http` |
| `command` / `args` | 子进程命令；`npx` + `-y` + 包名是最常见模式 |
| `env_required` | 必填凭证 key list，**仅声明**不存值；UI 用这个判 toggle 是否 disabled |
| `enabled` | config.yaml 默认值；DB `mcp_client_state` override 优先 |
| `expose_via_skyler_server` | True 时该 server 的 tool 会被 Skyler 自己的 MCP server 再暴露给外部 MCP client（代理模式）。多数场景 False，避免 API quota 泄漏 |

### Checklist

* [ ] config.yaml 写好 entry，重启后端
* [ ] 在 SettingsPanel [扩展能力] section 看到新行；状态徽章应为「需配置凭证」
* [ ] 点 [配置凭证] → 输入 `env_required` 列出的 key → 保存
* [ ] toggle 启用 → 状态徽章变 🟢 running·N tools（30s 内；首次启动 npx 拉包慢）
* [ ] 让 LLM 调一次某个 tool 验证端到端

### 注意

* 凭证存在 SQLite `mcp_credentials` 表，**明文**。MVP 接受，与 `.env` 风险
  等价。`ROADMAP Tech Debt` 有「MCP 凭证加密」backlog
* 不要在 config.yaml 的 `env` 字段里写 `${SLACK_BOT_TOKEN}` 这种 shell 变量
  插值——chunk 7 之后推荐用 `env_required` + UI 写 DB 的路径，避免凭证泄
  漏到 git 历史里
* 启动 server 失败时 SettingsPanel 行的状态徽章变 🔴 error，hover 看
  `last_error`。常见原因：npm 包名拼错 / 凭证错误 / 网络不通

---

## 候选 skill 推荐姿态对照

| Skill | 推荐姿态 | 包 / 库 | 备注 |
|---|---|---|---|
| docx 操作 | A ✅ | `python-docx` | 已 ship（chunk 7 demo） |
| Excel 表格 | A | `openpyxl` | 模板见上 |
| PDF 文本提取 | A | `pdfplumber` / `PyMuPDF` | 沙箱限制大 PDF |
| 本地文件操作 | A 或 B | `pathlib` 或 `@modelcontextprotocol/server-filesystem` | 已配（chunk 1.5 demo） |
| Apple Notes | A | macOS `osascript` | 用 subprocess 调 AppleScript |
| Apple Reminders | A | macOS EventKit (`pyobjc`) | 与 calendar 同 pyobjc 栈 |
| Notion | B ✅ | `@notionhq/notion-mcp-server` | 已 ship（chunk 7 demo） |
| Slack | B | 社区 `@some-org/slack-mcp-server` | 多个社区实现，挑 star/活跃度高的 |
| Linear | B | `@linear/mcp-server` 等 | 官方 / 社区 server 都有 |
| GitHub | B | `@modelcontextprotocol/server-github` | 官方 MCP server |
| Stripe | B | Stripe 官方 MCP server | 商业场景 |
| Brave 搜索 | B | `@modelcontextprotocol/server-brave-search` | 已配（chunk 1.5 demo） |
| Web Scraping | A | `httpx` + `beautifulsoup4` | 直接 capability，handler 内调 |
| Pollinations 表情包 | A | `httpx` + 图床上传 | 单一 HTTP API → 姿态 A |
| OCR | A | `pytesseract` | 沙箱限输入图片 |
| 屏幕截图 | (chunk 8) | Tauri Rust 端 | v4 屏幕感知，单独大 chunk |

---

## 进阶：让 LLM 知道何时该调

* `description` 字段直接被 ChatAgent 拼进 system prompt 给 LLM 看——**强引导**
  写法（"用户说 X 时调"、"适用场景: ..."）比裸 API doc 更让 LLM 主动用
* `parameters_schema` 是 JSON Schema，LLM 按它生成参数；description 里
  每个字段都说明清楚比 schema enum 更靠谱
* 错误 dict 里 `error` 字段用 enum-like 短字符串（`file_not_found` /
  `invalid_path` / `parse_failed`），LLM 会按 code 决定下一步动作

---

## 参考

* DESIGN §十五之A、Capability Registry 架构（capability 注册机制）
* DESIGN §十五之H、Skill 集成姿态（决策树 + V1 限制）
* `backend/capabilities/time_capability.py`——最简 capability 实例
* `backend/capabilities/clipboard.py`——多 capability 同模块实例
* `backend/capabilities/docx_ops.py`——chunk 7 docx demo（SAFE 沙箱
  + path traversal 防御）
* `backend/mcp/client.py`——chunk 1.5 MCP client（subprocess + tool 反注册）
* `backend/mcp/credentials.py`——chunk 7 DB-driven credentials
