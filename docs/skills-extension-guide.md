# Extending Skyler — 给 Momo 加新能力的 3 条路径

Skyler 是「可塑型 AI 角色容器」——扩展是一等公民,不是补丁。这意味着:**用户
应该能从 UI 把别的工具 / 视觉资产装进来,不动 yaml 不改 .py**。Stage 2 之后,
90% 的扩展场景由 UI 完成,只有"深度集成 Skyler 内部状态"还需要写代码。

本指南给三条路径 + 一棵决策树 + v4.1+ 演进预告。

---

## 速览决策树

| 我的需求 | 选 |
| --- | --- |
| 装现成工具(filesystem / git / GitHub / 数据库 / Notion / Slack ...) | **A — MCP** |
| 加新角色立绘 / 切换 Live2D 模型 | **B — Live2D** |
| 深度集成 Skyler 内部(memory 操作 / character 切换 / Live2D motion 触发 / 多模态) | **C — Python** |
| 跨语言写 capability(Node / Rust / Go / Bash ...) | **A — MCP**(用对方语言写 server) |
| 不懂代码 | **A 或 B** |
| 高性能 / 低延迟 / in-process / 需要直接读写 SQLAlchemy session | **C — Python** |

如果两条路都行:**优先 A**。少一层进程、少一次重启、跨工具复用(同一个 MCP server 也能给 Claude Desktop / Cursor / Cline 用)。

---

## 路径 A:UI 装 MCP server ⭐ 推荐

**状态:✅ Stage 2.1 已 ship**(commit `1ecf9af`)

90% 用户走这条路。MCP(Model Context Protocol)是 Anthropic 主推的工具协议,
社区已有几百个现成 server,Skyler 把它们当 first-class capability 接入。

### 用户视角(纯 UI,3 分钟)

1. 打开 SettingsPanel → 滑到底部 **[扩展能力 (MCP)]** section
2. 点 **[+ 新增 server]**
3. 填:
   - **name** —— 任意标识(如 `filesystem`)
   - **transport** —— `stdio`(子进程,最常见) / `http`(远程)
   - **command** + **args** —— 启动子进程的命令(如 `npx -y @modelcontextprotocol/server-filesystem ~/Documents`)
   - **env** —— 可选,secrets **用 `${VAR_NAME}` 模板**,提交后弹出凭证 modal 让你填真实值
4. **提交** —— 后端 `POST /api/mcp/clients` 写 `config.yaml` + 立即尝试连接
5. 连接成功 → 状态徽章 🟢 `running · N tools`,LLM 立即可用

### 优点

- ❌ 不要懂 Python
- ❌ 不要重启 backend
- ✅ 跨语言:server 用什么写都行(npx / uvx / docker / 自编译二进制)
- ✅ 跨工具复用:同一个 server 也能挂到 Claude Desktop / Cursor / Cline
- ✅ secrets 不进 git——env 模板只写变量名,真实 token 存 SQLite `mcp_credentials` 表

### 上游来源

| 源 | 内容 |
| --- | --- |
| [modelcontextprotocol.io](https://modelcontextprotocol.io) | 协议文档 + Anthropic 官方 servers |
| [github.com/modelcontextprotocol/servers](https://github.com/modelcontextprotocol/servers) | 官方 server 仓库(filesystem / fetch / git / github / postgres / 等) |
| [mcp.so](https://mcp.so) | 社区索引,按场景分类 |
| [smithery.ai](https://smithery.ai) | hosted MCP server 市场 |

### 5 个值得装的现成 MCP server

| Server | 用途 | 启动 |
| --- | --- | --- |
| `@modelcontextprotocol/server-filesystem` | 读本地文件树 | `npx -y ... ~/Documents` |
| `@modelcontextprotocol/server-sequential-thinking` | LLM 自助调多步推理 | `npx -y ...` |
| `@modelcontextprotocol/server-memory` | 简易 KV 持久化记忆 | `npx -y ...` |
| `@modelcontextprotocol/server-git` | 读 git repo + log + diff | `npx -y ... --repository <path>` |
| `@modelcontextprotocol/server-fetch` | 抓任意 URL 当 LLM context | `npx -y ...` |

### 失败排查

- **连接失败** → 状态徽章 🔴 `error`,hover 看 `last_error`。常见:命令拼错、依赖未装(npx 第一次拉包 ~30s,稍等)、env 缺凭证
- **凭证缺失** → 状态徽章「需配置凭证」,点 **[配置凭证]** 输入(明文存 SQLite,与 `.env` 风险等价,ROADMAP 有 OS keyring 加密 backlog)
- **添加成功但 connect 失败** → backend 返 201 + `error`,yaml **不 rollback**;用户可点 [删除] 重添或先配凭证再重试

---

## 路径 B:UI 装 Live2D 模型

**状态:✅ Stage 2.2 已 ship**(commit `c03ae2e`)

扩展角色视觉(立绘 / 表情 / 动作)。Skyler 的角色驱动定位让 Live2D 是一等公民。

### 用户视角(纯 UI,2 分钟)

1. 打开 **CharacterPanel** → 编辑或新建角色
2. 找到 **Live2D 模型** label → 点旁边 **[+ 上传模型]**
3. 拖入 `.zip`(含 `.moc3` + `.model3.json` + 可选 textures / motions)
4. 后端验证 + 解压 → 弹 toast `已上传 <slug>(N textures / M motions)`
5. dropdown 自动选中新 slug
6. 若 zip 内含 `.motion3.json`,弹 **应用默认 motion map?** 对话框
   - 点 **[应用]** → 写到 `character.motion_map_json`,LLM 输出 `<motion>X</motion>` 标签时该角色会真触发动作
   - 点 **[跳过]** → 保留前端兜底 motionMap(`frontend/src/config/live2d.ts`),后续可手动编辑

### 限制

- ❌ **仅 Cubism 4 及以下**(SDK 4.2 / `.moc3` version ≤ 4)。Cubism 5 模型 backend 直接 422 拒收——`pixi-live2d-display` 还没支持(GitHub issue #118 跟进中)
- ❌ 单 zip ≤ 30 MB(每个文件 ≤ 10 MB,防 zip-bomb)
- ❌ slug 已存在 → 409,UI 提供改名重试 input

### 上游来源

| 源 | 内容 |
| --- | --- |
| [live2d.com/en/sample-data/](https://www.live2d.com/en/learn/sample/) | Live2D 官方 free sample(Hiyori / Haru / 等;商用授权看 Live2D 条款) |
| 商业 commission | Booth.pm / Skeb / Twitter 找画师定制 |
| 自制 | Cubism Editor(免费版可做);需要美术功底 |

### 资产结构(zip 内层)

```
mymodel/                          # zip 解压后会放 frontend/public/live2d/<slug>/
├── mymodel.moc3                  # 必备
├── mymodel.model3.json           # 必备 — entry,引用 .moc3 + textures + motions
├── mymodel.4096/
│   └── texture_00.png            # 可选,textures
├── motions/
│   ├── idle_01.motion3.json      # 可选,motion 文件 — backend 扫文件名生成 motion_map 默认值
│   └── tap_01.motion3.json
└── mymodel.physics3.json         # 可选,物理(头发 / 衣服摇摆)
```

backend `_build_motion_map()` 把每个 `.motion3.json` 文件名 stem 作为 motion entry:
`idle_01.motion3.json` → `{"idle_01": {"group": "idle_01", "index": 0}}`。这是
**默认值**(模板),Live2D 模型作者一般按 `GroupName_XX.motion3.json` 命名,
模板基本能直接用;不能用时在 character.motion_map_json 手动改。

---

## 路径 C:写 Python capability(深度集成)

**状态:🔧 需改代码 + 重启 backend**。v4.1+ backlog 计划 UI 化,但 .py
跨 framework 不兼容,优先级不高(详 ROADMAP "Skill UI" backlog 条目)。

### 何时选 C 而不是 A

| 场景 | 为什么 C |
| --- | --- |
| 需要读写 Skyler 内部 state(memory / character_state / activity_timeline 表)| MCP 是隔离子进程,拿不到主进程的 SQLAlchemy session |
| 需要在 ChatAgent.stream 流程中插钩子(motion 触发 / emotion 解析)| MCP 协议没暴露 stream 中间状态 |
| 需要 in-process 性能(单次调用 < 10ms) | MCP 子进程 IPC 单次 ~5-20ms 起步 |
| 已经有 Python 库就能跑(`python-docx` / `openpyxl` / `pdfplumber` / `pyperclip` ...) | A 也行,但 C 少一层进程,沙箱更直接 |

### 用户视角(5 分钟,但需要懂 Python)

1. `pip install <lib>`,加进 `requirements.txt`
2. 写 `backend/capabilities/<feature>.py`(模板见下)
3. `backend/main.py` 加一行 `import backend.capabilities.<feature>` 触发
   `@register_capability` decorator 副作用
4. 重启 `uvicorn` —— ChatAgent 自动看到新 capability(无需改前端)

### 最简模板

```python
"""backend/capabilities/excel_ops.py — 读 Excel 表格"""
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
        "读取 .xlsx 表格的指定 sheet 内容(默认第一个 sheet)。"
        "适用场景:用户说「读一下那个表」「看看 XX.xlsx 里写了啥」。\n\n"
        "参数:\n- filename: 文件名\n- sheet_name: sheet 名称,可选\n\n"
        "返回 ``{sheet, rows, row_count}``。"
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
    filename: str = "", sheet_name: str = "", **_kwargs: Any,
) -> dict:
    if not filename.strip():
        return {"error": "missing_filename"}
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

- [ ] handler 用 `async def`,接 `**_kwargs` 兜 ChatAgent 注入的 `user_id`
- [ ] description 走强引导风格(触发场景 + 参数说明 + 返回 schema)——
      这字段被拼进 system prompt,LLM 看 description 决定何时调
- [ ] 所有错误返 `{"error": "<code>", "detail": ...}` dict,**不 raise**
      ——让 LLM 接着说人话
- [ ] 接用户 filename 的所有路径都走 `safe_resolve`,禁绝对路径 / `..` /
      路径分隔符
- [ ] 沙箱目录:用户可见放 `~/Documents/Skyler/<feature>/`;
      内部 token / 配置放 `~/.skyler/`
- [ ] `backend/main.py` 加 `import` 触发 decorator 副作用
- [ ] 写 `tests/test_<feature>_capabilities.py` 测 happy path + 错误全路径

### 完整例子(链接 capabilities/ 实际代码)

| 文件 | 形态 | 看点 |
| --- | --- | --- |
| `backend/capabilities/time_capability.py` | 最简 capability | 1 个 handler / 单文件 |
| `backend/capabilities/clipboard.py` | 多 capability 同模块 | 3 个 handler 共享 helper |
| `backend/capabilities/docx_ops.py` | SAFE 沙箱 + path traversal 防御 | 用户 filename 安全模式 |
| `backend/capabilities/apple_calendar.py` | 系统集成 + Python 调 EventKit | macOS API 包装 |
| `backend/capabilities/netease_playback.py` | 跨进程协作(mpv IPC) | asyncio.subprocess / Lock |
| `backend/capabilities/character_state.py` | 深度内部集成 | AsyncSession + WS push |

---

## 反模式 — 不要做的事

- ❌ **为了"MCP 时髦"给只 wrap HTTP endpoint 的简单功能写 MCP server**
  ——直接 capability 内 `httpx.AsyncClient` 调用更省事(路径 C),或装个 fetch MCP 让 LLM 自己抓(路径 A)
- ❌ **给 LLM 不会主动想用的能力做 MCP**——npx 首次启动有 ~30s 拉包代价,
  装来吃灰不如不装
- ❌ **MCP 模板里 env 字段写明文 token**(`SLACK_BOT_TOKEN: "xoxb-..."`)
  ——会写进 config.yaml + git 历史。永远只写 `${VAR_NAME}` 模板,真实值
  走 UI 凭证 modal 存 DB
- ❌ **路径 C 的 capability 接用户 filename 不过 `safe_resolve`**——经典
  `../../etc/passwd` 攻击面
- ❌ **handler 抛异常**(`raise ValueError(...)`)——LLM 看到 500 error 会
  乱猜或重试,改返 `{"error": "<code>"}` 让它说人话
- ❌ **description 写裸 API doc**(`"Read xlsx file"`)——LLM 不知道何时该
  调。改写"用户说 XX 时调用"+ 触发场景列表

---

## v4.1+ 演进预告

| 项目 | 状态 | 备注 |
| --- | --- | --- |
| .py capability UI 拖入 + 一键重启 backend | v4.1+ backlog | 消除路径 C 的代码门槛;详 ROADMAP "Skill UI" 行 |
| Skyler-as-MCP-server | v4.1+ backlog | 反向暴露:让 Claude Code / Cursor / Cline 调 Skyler 的 character_state / memory / Live2D control。详 ROADMAP "Skyler-as-MCP-server" 行 |
| SKILL.md 加载(Anthropic Layer 1 skill) | v4.2+ research | 让 Momo 用跨工具 skill 知识(类似 Claude Code 的 skill 系统) |
| MCP 凭证 OS keyring 加密 | v4.x backlog | 替代当前 SQLite 明文存储 |

---

## 进阶:让 LLM 知道何时该调

- **`description` 字段是 LLM 唯一信源**——被 ChatAgent 拼进 system prompt,
  LLM 看 description 决定何时调。强引导写法("用户说 X 时调"、"适用场景:")
  比裸 API doc 更让 LLM 主动用
- **`parameters_schema` 是 JSON Schema**,LLM 按它生成参数;description
  里每个字段说明清楚比 schema enum 更靠谱
- **错误 dict 里 `error` 字段用 enum-like 短字符串**(`file_not_found` /
  `invalid_path` / `parse_failed`),LLM 会按 code 决定下一步动作
- **`save_memory` tool 故意写"仅在用户明确要求记住时调"**——日常事实由
  background MemoryExtractor 自动提取;这种约束直接写进 description LLM 就听话

---

## 候选 skill 推荐姿态对照

| Skill | 推荐路径 | 原因 |
| --- | --- | --- |
| Notion / Linear / Slack / GitHub / Stripe | **A** | 官方 / 社区 MCP server 完整;装 + 配凭证 5 分钟 |
| 本地文件树读取 | **A** | `@modelcontextprotocol/server-filesystem` 现成 |
| Web 搜索 | **A** | `@modelcontextprotocol/server-brave-search` / `tavily-mcp` 现成 |
| URL 抓取 | **A** | `@modelcontextprotocol/server-fetch` 现成 |
| Apple Calendar / Reminders / Notes | **C** | macOS EventKit / AppleScript,Python `pyobjc` / `osascript` 直接调 |
| 网易云 / Bilibili / 小红书 | **C** | 已 ship,内部 DB 状态 + 风控 header 自维护 |
| docx / xlsx / pdf 读写 | **C** | Python 库直接调,沙箱限制比 MCP 简单 |
| 屏幕截图 / 浏览器自动化 | **C** | 需要主进程权限(macOS Accessibility / Tauri 主进程) |
| OCR | **C** | `pytesseract` 直接调 |
| 角色立绘 / 新动作 | **B** | 不是 capability,是视觉资产 |
| 跨工具(Claude Code / Cursor / Cline)复用 | **A** | MCP server 本来就是跨工具协议 |

---

## 参考

- [DESIGN §零 Why these choices](../DESIGN.md) —— 战略层"可塑性"
- [DESIGN §十五之A Capability Registry](../DESIGN.md) —— 注册机制实现
- [stage-2-starting-context.md](stage-2-starting-context.md) —— Stage 2 设计 audit(三路径权衡)
- [ROADMAP.md Tech Debt & Backlog](../ROADMAP.md) —— v4.1+ 演进 backlog 全表
- [mcp-client-setup.md](mcp-client-setup.md) —— MCP 旧手动 yaml 配置参考(Stage 2.1 UI 之前的路径)
- [mcp-server-setup.md](mcp-server-setup.md) —— Skyler 作为 MCP server 配置(给未来 Skyler-as-server 用)
