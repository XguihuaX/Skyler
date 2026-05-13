# Stage 2 C MVP — Skill / MCP / Live2D 管理 UI · Starting Context

前置:`README.md` / `DESIGN.md §零 / §一 / §十九` / `ROADMAP.md §Now`。
Stage 2 目标:用户**纯前端**管理三类资源,不动 yaml / 不改 .py。

本 audit 只盘点现状(§1-§4)+ 分析改造影响面(§5-§6),不修改源代码。


---

## 1. Skill / Capability 注册机制现状

### 1.1 装饰器

`backend/capabilities/registry.py:196-233`:

```python
def register_capability(
    *, name: str, display_name: str, description: str, category: str,
    consumers: list[Consumer], trigger_modes: list[TriggerMode],
    icon: str = "circle", user_visible: bool = True,
    health_check: Optional[Callable[[], Any]] = None,
    parameters_schema: Optional[dict] = None,
    metadata: Optional[dict] = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def decorator(func):
        cap = Capability(name=name, ..., handler=func, metadata=dict(metadata or {}))
        CapabilityRegistry().register(cap)
        return func
    return decorator
```

### 1.2 capabilities/ 目录 + 数量

`backend/capabilities/`(13 模块):

* `time_capability.py`(1 cap)、`apple_calendar.py`(4)、`google_calendar.py`(2)
* `calendar.py`(2 路由层)、`netease_music.py`(7)、`netease_playback.py`(6)
* `media_control.py`(5)、`clipboard.py`(3)、`character_state.py`(3)
* `docx_ops.py`(3)、`bilibili.py`(11)、`xiaohongshu.py`(1)
* `screen.py`(4)、`activity.py`(3)

合计 **55 个内置 capability**(`backend/capabilities/registry.py:58` + 4 个
proactive trigger 注册经 stage2_registry 不进 ChatAgent tool surface)。
加上 `tools/builtin.py:14,26` 2 个 builtin tool(`switch_character` /
`clear_short_term`),ChatAgent 默认能见 **57**。`memory tools` 4 个走
`_TOOL_HANDLERS` 独立 dict(`backend/agents/chat.py:911-916`),不经
ToolRegistry。

### 1.3 启动注册流程

`backend/main.py:117-134`:

```python
# 触发 capability decorator 副作用注册到 CapabilityRegistry + ToolRegistry。
# 必须在 FastAPI app 构造前 import。新增 capability 时把 import 加到这里。
import backend.capabilities.time_capability    # noqa: F401, E402
import backend.capabilities.apple_calendar    # noqa: F401, E402  v3-G chunk 1.6
import backend.capabilities.google_calendar   # noqa: F401, E402
... (12 个 import,顺序敏感:apple/google 必须在 calendar 路由层前)
```

顺序:
1. Python import 触发 `@register_capability` decorator
2. `CapabilityRegistry().register(cap)` `registry.py:100-118`
3. 若 `Consumer.CHAT_AGENT` 在 consumers → 自动 mirror 到 `ToolRegistry.register(name, handler, schema)` `registry.py:116-118`

### 1.4 ToolRegistry vs CapabilityRegistry

* **CapabilityRegistry**(`backend/capabilities/registry.py:96-189`):进程
  级单例,持 metadata(display_name / category / icon / health_check)+
  handler。给前端"能力面板"列表用。
* **ToolRegistry**(`backend/tools/registry.py:27-81`):name → callable +
  OpenAI function-calling schema dict 双表。给 ChatAgent 跑 LLM tool loop
  用(`backend/agents/chat.py:1394-1397` `_get_all_tools()`)。
* **关系**:CapabilityRegistry 是 superset,只要 `Consumer.CHAT_AGENT`
  consumer 在列表里就自动 mirror 到 ToolRegistry。
* **不可造平行系统**(`registry.py:11-32` 模块头明示)——所有 LLM 可见
  tool 必须经 CapabilityRegistry 入口。

### 1.5 完整通路时序图(`.py` → LLM 调用)

```
import time:
  ├─ Python import backend.capabilities.foo                 (main.py:117-134)
  ├─ @register_capability(name="foo.bar", ...) decorator 触发
  ├─ CapabilityRegistry().register(cap)                     (registry.py:100)
  │   └─ cap 入 _capabilities dict
  │   └─ Consumer.CHAT_AGENT in cap.consumers
  │       → schema = _build_openai_schema(cap)              (registry.py:240-252)
  │       → ToolRegistry.register(name, handler, schema)    (registry.py:118)

runtime (per turn):
  ├─ ChatAgent.stream() — call_llm(tools=_get_all_tools())  (chat.py:1394-1397)
  │   └─ _get_all_tools = MEMORY_TOOLS + ToolRegistry.list_schemas()
  ├─ LLM 返回 finish_reason='tool_calls' + tool_calls_acc
  ├─ yield {"type":"tool_use_start", "tool_name":name}      (chat.py:1501)
  ├─ await _execute_tool(user_id, name, raw_args, ...)      (chat.py:1504)
  │   └─ if name in _TOOL_HANDLERS: await handler(...)       (memory 类)
  │   └─ else: await ToolRegistry.call(name, **args)         (其他)
  │       └─ inspect.iscoroutinefunction → await func(**kwargs)
  └─ yield {"type":"tool_use_done", ...}                    (chat.py:1515)
```

### 1.6 运行时加载支持

**当前不支持热加载**。grep:

* `grep -rn "importlib" backend/` → 0 hit
* `grep -rn "hot.?reload\|reload_capability" backend/` → 0 hit

加新 capability 现状(`docs/skills-extension-guide.md:47`,`134`):
1. 把 .py 放进 `backend/capabilities/`
2. `backend/main.py` 加一行 `import backend.capabilities.xxx`
3. 重启 backend

唯一已有的"运行时注册"是
`CapabilityRegistry.register_runtime()`(`registry.py:175-189`)——但**仅
被 MCP client 调用**(`backend/mcp/client.py:221-286` `_capability_from_external_tool`),
没有暴露给"从磁盘扫 .py 加载" 路径。

### 1.7 "重启需要重启什么"

* **uvicorn** —— 必须重启,因为 Python 已 import 的模块用 `import` 二次执行
  不会真重载,装饰器不会再触发
* **frontend (Tauri webview)** —— 不需要重启;`yarn tauri dev` HMR 不受
  backend 重启影响;但前端 `useWebSocket.ts:381-391` reconnect 逻辑会自
  动断开重连 + 用户感受到~1-2 s 短暂"已断开"标记
* **Tauri 主进程** —— 不需要;backend 是独立的 uvicorn 子进程(开发模式),
  Tauri 不直接 spawn 它(`frontend/src-tauri/tauri.conf.json:8-10`
  `beforeDevCommand: "npm run dev"`,没有 backend sidecar)
* **生产 macOS .app** —— Tauri 没有 `externalBin` / sidecar 配置;backend
  目前是用户**手动**跑 `uvicorn`,这意味着 Stage 2 的"一键重启 backend"
  在生产打包之前**没有自然 hook 可用**——见 §5 风险

---

## 2. MCP server 配置现状

### 2.1 config.yaml 段 schema

`config.yaml:132-153` 顶层 `mcp_clients` dict:

```yaml
mcp_clients:
  filesystem:
    description: 本地文件读取（Anthropic 官方 server）
    transport: stdio                              # "stdio" | "http"
    command: npx
    args:
      - -y
      - '@modelcontextprotocol/server-filesystem'
      - ${HOME}/Documents
    enabled: false
    expose_via_skyler_server: true
  brave-search:
    description: Brave 搜索（需要 BRAVE_API_KEY）
    transport: stdio
    command: npx
    args: [-y, '@modelcontextprotocol/server-brave-search']
    env:
      BRAVE_API_KEY: ${BRAVE_API_KEY}
    enabled: false
    expose_via_skyler_server: false
```

字段说明在 `backend/mcp/client.py:14-29`:`transport / command / args /
env`(stdio)或 `url / headers`(http)、`enabled`、
`expose_via_skyler_server`、可选 `env_required` 列表。

### 2.2 启动时初始化

`backend/main.py:631-658`:

```python
# ── 9. v3-G chunk 1.5 — MCP clients：连接外部 server 反向注册 capability
from backend.mcp import client as mcp_client_module
mcp_cfg = config_yaml.get("mcp_server") or {}
server_enabled = bool(mcp_cfg.get("enabled", False))
if server_enabled:
    async with mcp_server.get_session_manager().run():
        await mcp_client_module.init_clients_from_config()  # ← 这里
        try:
            yield
        finally:
            await mcp_client_module.shutdown_clients()
else:
    await mcp_client_module.init_clients_from_config()
```

`init_clients_from_config`(`backend/mcp/client.py:323-342`)遍历
`config_yaml.get("mcp_clients")`,逐个 `_connect_one`。失败 log warning
不阻塞主流程。

### 2.3 运行时 reload 支持

* **`reload_config_yaml()`**(`backend/config/__init__.py:53-63`):**已存在**。
  从磁盘重读 + 原位 mutate 全局 dict,所有 `from backend.config import
  config_yaml` 的引用立即可见新值。
* **MCP client 手动重连**(`backend/mcp/client.py:359-375`):`async def
  reconnect(name)` 断开 + 重连单个 client。**不重读 config.yaml**——
  conf 是 client_handle 构造时锁定的。要让"加新 server 后立即生效",**
  需要新建 _ClientHandle + _clients[name] = handle + connect**——目前
  没有这样的"动态注册新 server"API。
* **`enable(name)` / `disable(name)`**(`client.py:382-415`):仅对**已在
  config 里**的 server 切换。DB `mcp_credentials.enabled` override 持久
  化(`backend/mcp/credentials.py:105`)。

### 2.4 mcp_client_state / mcp_tool_state

* **`mcp_credentials` 表**(chunk 7 migration `main.py:204`):server-level
  `enabled` override + 凭证存储(明文,`docs/mcp-client-setup.md` /
  ROADMAP §Tech Debt 标 backlog 升级 OS keyring)。
* **`mcp_tool_state` 表**(UX-001 migration `main.py:230`):per-tool
  enable/disable。未登记的 tool 默认 enabled。`backend/mcp/tool_state.py`
  69 行。
* **`mcp_client_state`**(chunk 7 hotfix 历史名,后已合到 `mcp_credentials`
  表):`backend/mcp/credentials.py:105-120` `set_enabled` 写的就是这里。

### 2.5 既有 endpoint

`backend/routes/mcp_api.py`:

| Method | Path | 用途 | 行号 |
| --- | --- | --- | --- |
| GET    | `/api/mcp/clients/status` | 列所有 client + tools | `73` |
| POST   | `/api/mcp/clients/{name}/reconnect` | 手动重连 | `85` |
| PUT    | `/api/mcp/clients/{name}/enabled` | server 级 toggle | `115` |
| PUT    | `/api/mcp/clients/{name}/tools/{tool}/enabled` | tool 级 toggle | `245` |
| GET    | `/api/mcp/clients/{name}/credentials` | 列凭证 key 状态 | `179` |
| PUT    | `/api/mcp/clients/{name}/credentials` | 写凭证 | `197` |
| GET    | `/api/mcp/server/status` | Skyler MCP server 自身 | `270` |

**缺口**:**没有** `POST /api/mcp/clients`(新增 server entry 到 config.yaml)
和 `DELETE /api/mcp/clients/{name}`。Stage 2 要补这两条。

---

## 3. Live2D 模型管理现状

### 3.1 资产目录

```
frontend/public/live2d/
├── core/                   # Cubism Web SDK runtime(.gitignore 白名单跳过扫描)
├── hiyori/                 # 默认内置模型
│   ├── hiyori_pro_t11.model3.json
│   ├── *.moc3              # entry 指向
│   ├── *.motion3.json      # 多个 group(Flick/FlickDown/...)
│   ├── motion/             # 部分模型用子目录
│   └── hiyori_pro_t11.2048/ # textures
├── yae/                    # 八重(Yae Miko)模型,符号链接指向外部 IP 资产
│   └── textures/
```

`backend/services/live2d_scanner.py:65-66` 锚定 repo root,**不解析
symlink**(`.absolute()` 而非 `.resolve()`),让用户用 `ln -s
<外部IP资产> frontend/public/live2d/<slug>` 跳过 git track。

### 3.2 .moc3 → Live2DCanvas 完整 4 步

| 步骤 | 现状(手动) | 文件:行号 |
| --- | --- | --- |
| 1. 放资产 | 把模型整目录扔进 `frontend/public/live2d/<slug>/` | `live2d_scanner.py:14-31` |
| 2. 后端识别 | `GET /api/live2d/models` 自动扫 + 验 moc3 版本(≤4 兼容 pixi-live2d-display)| `live2d_api.py:16-24` |
| 3. character 关联 | `PATCH /api/characters/{id}` 写 `live2d_model=<slug>` | `characters_api.py:70` |
| 4. 前端解析 | `resolveLive2dModelUrl(slug, models)` 先走 scanner store,miss 走 `live2dModelEntry` hardcode | `frontend/src/config/live2d.ts:37-66` |

`live2d_scanner.py:141-153` `_find_model3_json` 一层深度搜 `*.model3.json`
(slug_dir 根 + 一级子目录,覆盖 Hiyori 的 root layout + 其他模型的
`runtime/` 子目录布局)。

### 3.3 emotion_map / motion_map / hit_area_map

存储分两层:

**全局默认**`frontend/src/config/live2d.ts`:
* `emotionMap: Record<string, string> = {}`(行 104)—— v3-E1 Hiyori 没
  .exp3.json,空表
* `motionMap: Record<string, MotionEntry>`(行 134-162)—— 当前硬编码
  Hiyori 的 Flick/FlickDown/FlickUp/Flick@Body 4 组,23 个中文 key

**per-character 覆盖**`characters` 表(`backend/database/models.py:49-60`):
```python
live2d_model      = Column(Text, nullable=True)  # slug
emotion_map_json  = Column(Text, nullable=True)  # JSON string
motion_map_json   = Column(Text, nullable=True)
hit_area_map_json = Column(Text, nullable=True)
background_path   = Column(Text, nullable=True)
```

API 完整支持 CRUD(`backend/routes/characters_api.py:30-115`):
* GET `/api/characters/list` 返所有字段
* POST `/api/characters/create` 接所有字段
* PATCH `/api/characters/{id}` 接所有字段
* DELETE `/api/characters/{id}`

前端 `CharacterPanel.tsx:932-944` 已有"`live2d_model` 文本框 + 与 scanner
对照 warning"。**当前没有**:
* `.moc3` 拖入上传
* 自动 motionMap 默认值生成(从 .motion3.json 文件名推 group/index)
* per-character emotion/motion/hit_area_map_json 的图形化编辑器

---

## 4. 已有 frontend UI 现状

### 4.1 CapabilityPanel

`frontend/src/components/CapabilityPanel.tsx`(911 行,大型 panel)。

主要 hooks(`395-423`):
```typescript
const [items, setItems] = useState<CapabilityDTO[]>([]);
const [googleStatus, setGoogleStatus] = useState<GoogleStatusResponse | null>(null);
const loadAll = useCallback(async () => {
  const data = await fetchCapabilities();
  setItems(data.capabilities);
}, []);
```

* 数据源:`fetchCapabilities()` `frontend/src/lib/capabilities.ts:41-45`
  → `GET /api/capabilities`
* **当前没有"toggle 单个 capability"功能**——`CapabilityDTO` 也没
  `enabled` 字段。**只有内置 capability 的 health_check refresh**。
* "Category accordion + Provider toggle" 是 UX-005 的 google 集成开关,
  跟"打开 / 关闭 capability"语义不同(`530`,`545`)。

### 4.2 ExtensionsSection (MCP 管理 UI)

`frontend/src/components/ExtensionsSection.tsx`(693 行)——MCP client 管理
**已 work**。

功能(实测从 SettingsPanel 底部进):
* 列所有 MCP server + tool(`refresh()` 行 56-67)
* server toggle(`onToggle` 行 73-90 调 `setMCPClientEnabled`)
* per-tool toggle(`toolToggling` state + `setMCPToolEnabled`)
* `[配置凭证]` modal(`credModalFor` state + `setMCPCredentials`)

**当前没有的**:
* 表单加新 server entry(写 config.yaml)
* 删除 server entry
* 测试连接按钮(目前只有 `reconnect`)

### 4.3 CharacterPanel(Live2D 切换部分)

`frontend/src/components/CharacterPanel.tsx`(1231 行)。

Live2D 相关 state + form(`109-124`,`408-410`):
```typescript
live2d_model: string;
background_path: string;
// (form 也有 emotion_map_json / motion_map_json / hit_area_map_json)
```

实现(`932-944`):
* 文本框输入 slug,与 `live2dModels`(`GET /api/live2d/models`)对照
* slug 不在扫描结果里 → 黄字 warning
* 没有上传 / dropzone

`emotion_map_json` / `motion_map_json` / `hit_area_map_json` 字段在 form
有,但**没**对应 textarea(grep `motion_map_json` 没看到 UI 输入框
——只有 form data 字段定义和 PATCH 提交时透传)。

### 4.4 Dropzone / FileUpload 现状

`grep -rn "Dropzone\|FileDrop\|onDrop\|react-dropzone" frontend/src/` →
**0 hit**。

`grep -rn "input.*type.*file" frontend/src/` 也没;现有 UI 全部基于
文本框 + 选项 dropdown,**无任何文件上传 / 拖拽组件可直接复用**。
Stage 2 需要从 0 引入一个 minimal dropzone(20 行可写 + 不必拉
`react-dropzone` 依赖,HTML5 `ondragover`/`ondrop` 原生 API 足够)。

---

## 5. Stage 2 改造影响面

### 5.1 Skill 拖入 .py 新增

**改造点**:

| 项 | 新增 | 复用 / 已有 |
| --- | --- | --- |
| **后端 endpoint** | `POST /api/skills/upload` 接 multipart .py | 文件路径走 `backend/utils/safe_path.py` `safe_resolve`(`docx_ops.py:133` 同 pattern) |
| **验证** | 静态 `ast.parse` 看是否含 `@register_capability` decorator;ban `import subprocess` / `os.system` / `__import__` 之类(可选) | — |
| **写入** | 复制到 `backend/capabilities/<name>.py` | — |
| **生效** | 改 `backend/main.py:117-134` 加 import?还是 `importlib.import_module`?| — |
| **重启** | `POST /api/skills/restart` 触发 uvicorn 重启 | **没有 hook**(§1.7 详) |
| **前端 UI** | dropzone + 列表 + per-capability `enabled` toggle | `lib/capabilities.ts` API client + `CapabilityPanel.tsx` 列表渲染 |
| **toggle 持久化** | 新表 `capability_state(name TEXT PK, enabled BOOLEAN)`? | 同 `mcp_tool_state` pattern(`backend/mcp/tool_state.py:69`)|

**核心风险**:

1. **"一键重启 backend" 没有自然 hook**——开发模式:用户手动跑
   uvicorn,backend 不能自杀重生(os.execv 可行但不优雅);Tauri 没
   sidecar 配置(`tauri.conf.json` 仅 `beforeDevCommand`)。
   * 选项 A:`importlib.import_module("backend.capabilities." + name)`
     运行时加载(免重启),依赖 decorator side-effect。**风险**:
     已有同名 capability 再注册时 `registry.register` 抛 `ValueError`
     (`registry.py:101-105`);`_TOOL_HANDLERS` 不动则 ToolRegistry 上层
     也不重复挂。可以接,但需要先扩 `unregister_capability` 配对。
   * 选项 B:暴露 `POST /api/skills/restart` 调 `os.execv(sys.executable,
     [sys.executable, "-m", "uvicorn", ...])` —— **暴力但确实有效**。
     `--reload` flag 启动下 uvicorn 监 .py 变化自动 reload,但用户跑
     `uvicorn backend.main:app` 不带 `--reload` 时无效。
   * 选项 C:加 Tauri sidecar(`externalBin`)让 Tauri 启动 backend +
     用 Tauri Rust 命令重启子进程 —— **架构改动大**,留 v4.1。

2. **.py 验证策略**:用户自由放 .py 是巨大攻击面。MVP 阶段先
   **strong warning + 用户自己承担风险**(类似 Skill 安装 = 装 Python
   包,本质相同);未来可加 AST 白名单。

3. **`capability_state` 表设计**:per-capability `enabled` override 需
   要和 `mcp_tool_state` 区分(MCP tool ≠ 内置 capability);共表还是分
   表是设计选择(详 §7 Q1)。

### 5.2 MCP 表单新增 server

**改造点**:

| 项 | 新增 | 复用 |
| --- | --- | --- |
| **后端 endpoint** | `POST /api/mcp/clients` 接 form data | `backend/routes/config_api.py:176-209` write-back pattern(load → mutate → safe_dump) |
| **endpoint** | `DELETE /api/mcp/clients/{name}` | 同上 |
| **写入 config.yaml** | yaml.safe_dump 重写 | `config_api.py:193-200` |
| **生效** | new `_ClientHandle` + `_clients[name]=handle` + `_connect_one(handle)` | `backend/mcp/client.py:323-342` `init_clients_from_config` 重用 |
| **前端 UI** | 加 server 表单(name / description / transport / command / args / env / `enabled` checkbox)| `ExtensionsSection.tsx` 现有列表 + toggle UI |

**核心风险**:

1. **config.yaml 写并发**(`backend/routes/config_api.py:176-209` 已展示
   pattern,但**不原子**)——load → mutate → dump 不带 .tmp + rename。
   并发写丢更新风险存在。改造时**强烈建议**:用 `os.rename(tmp,
   final)` 原子 swap + `asyncio.Lock` 串行化。
2. **reload MCP 不影响 in-flight tool call**:`init_clients_from_config`
   只是把新 entry 加进 `_clients` dict,不动已建立的 session。但 MVP 不
   会"删一个正在用的 server"(用户场景:加新 server > 删旧 server)。
   保留风险。
3. **secrets 不写 yaml**:env 段 `${BRAVE_API_KEY}` 是模板,实际 token
   存 `mcp_credentials` 表(`backend/mcp/credentials.py:38`)。MVP 加新
   server 时要先写 yaml 把"形状"建立,再让用户在 UI 单独填凭证(
   `ExtensionsSection.tsx` `credModalFor` modal 现成)。

### 5.3 Live2D 拖入新增

**改造点**:

| 项 | 新增 | 复用 |
| --- | --- | --- |
| **后端 endpoint** | `POST /api/live2d/upload` 接 zip / 多文件 multipart | `live2d_scanner.py:130-138` `_to_static_url` |
| **验证** | 必须找到 .model3.json + .moc3 + ver ≤ 4 | `live2d_scanner.py:90-101` `_read_moc3_version` |
| **复制到 assets** | 解压到 `frontend/public/live2d/<slug>/` | — |
| **生效** | scanner 下次 `GET /api/live2d/models` 自动看到 | `live2d_scanner.py` 已是 read-fresh,**无需手动 invalidate** |
| **motionMap 默认值** | 扫 .motion3.json 文件名 → `{group: <basename>, index: 0}` | 当前 hardcode 在 `frontend/src/config/live2d.ts:134-162`,需要新增 endpoint 写到 `characters.motion_map_json` |
| **前端 UI** | dropzone + 验证 toast + 自动填 `live2d_model` slug | `CharacterPanel.tsx:932-944` 现有文本框 + dropdown |

**核心风险**:

1. **Multi-file vs zip**:`.moc3` + `.model3.json` + `.motion3.json`×N +
   textures/×N → 一次拖入需要保留目录结构。**用 zip 上传**最简(浏览器
   原生 File API 支持 ZIP 拖入,后端 `zipfile.ZipFile` 解压);单文件流
   会让"哪个 .moc3 配哪个 .json"难判定。
2. **Symlink 不参与上传**——`yae/` 这种外部 IP 资产符号链接是手动
   配置,UI 上传场景必然是"用户买来的合法 model package 整个上传到 repo
   内部"。不冲突。
3. **moc3 ver=5(Cubism 5)**:`live2d_scanner.py:79` `_PIXI_MAX_SUPPORTED
   = 4`,Cubism 5 走不通 pixi-live2d-display。UI 应在 upload 时验证 +
   拒绝 ver=5,给清晰错误而不是默默接受让 CharacterCanvas 黑屏。
4. **路径越界**:zip 内含 `../../etc/passwd` 这类经典攻击。**必须**用
   `backend/utils/safe_path.py` `safe_resolve` 把每个解压成员限定在
   `frontend/public/live2d/<slug>/` 内。

---

## 6. 实施路径建议

基于 §1-§5 复杂度,**推荐顺序**:

1. **Stage 2.1 — MCP 表单新增 server**(风险最低,2-3 d)
   * 复用最多既有 infra(`ExtensionsSection.tsx` 完整 UI + `mcp_api.py`
     完整 endpoint 集 + `config_api.py` write-back pattern)
   * 不引入"重启 / 热加载"难题(MCP client 本来就是运行时连接,reload
     语义清晰)
   * 拿这个 sub-stage 试水 config.yaml 写并发模式(atomic rename +
     asyncio.Lock),后两个 sub-stage 都能复用
2. **Stage 2.2 — Live2D 拖入新增**(中风险,3-4 d)
   * `live2d_scanner` 已 read-fresh,加 upload endpoint 无 reload 难题
   * **不依赖 Stage 2.1**(写的不是 yaml 而是文件系统),可与 2.1 并行
   * zip handling + safe_path 验证是主复杂度
   * motionMap 默认值生成可作为 "nice to have",first iteration 让用户
     手填 `motion_map_json`
3. **Stage 2.3 — Skill 拖入 .py + 一键重启**(高风险,5-7 d)
   * 唯一卡在 §1.7 "重启 hook" 选择 —— 推荐 MVP 走"选项 A:importlib
     + 配对 unregister"(不依赖 process manager,纯 Python 内可控)
   * `capability_state` toggle 表设计先做 schema 决定(详 §7 Q1)
   * 先做 toggle UI(不需要 upload),验证 toggle pipeline 稳定后再做
     upload —— 把两个独立改动**串行**而非并行,避免回归面叠加

**并行 vs 串行建议**:2.1 + 2.2 可独立并行(无代码冲突,改不同
endpoint + 不同 frontend section);2.3 留最后,因为它最碰核心
`registry.py` + `main.py` import 链。

**配套 contributing guide**:沿用 `docs/skills-extension-guide.md` 现
有 200 行结构,删除"加 import 到 main.py + 重启"段落,改为"拖入 UI
即生效"+ "走 UI 装 / 走代码装两条路径都支持"。

---

## 7. Audit 中未解明的问题

### Q1. `capability_state` toggle 表设计

* 选项 A:复用 `mcp_tool_state`(`backend/mcp/tool_state.py:69`)语义
  扩展 —— `mcp_tool_state(server_name, tool_name, enabled)` 改成
  `tool_state(source TEXT, name TEXT, enabled BOOLEAN)`,source ∈
  {builtin, mcp_external}。
* 选项 B:新表 `capability_state(name TEXT PK, enabled BOOLEAN)`,
  独立于 MCP。
* **待顾问拍板**:存储是否合并?语义合并(都是"override 默认 enabled")
  还是分表(MCP 与内置生命周期不同)?

### Q2. 重启 hook 选哪个?

§5.1 提了 A/B/C 三选项。**重要决策**:Stage 2 MVP 是只支持开发模式
(用户手动跑 uvicorn,backend 不能自杀重生)还是承诺生产可用?
* 如果 MVP 只覆盖开发模式 → 选项 A(importlib + unregister 配对)
* 如果要生产可用 → 走选项 C(Tauri sidecar)→ 但这是 stage 2 之外的
  打包改造,工程量 >> 1 d

### Q3. 验证策略 — `.py` upload 是否做静态扫描?

ban `import subprocess` / `os.system` 等是入门级 ACL,但很容易绕(`__import__`
/ `eval`)。MVP 真实选择:
* 选项 A:**完全不验证 + 用户承担风险**——类比 `pip install`,
  本地 Python 跑任何代码就是自食其果
* 选项 B:AST `import` 白名单 + log 警告 — 安全感增加但是误判风险
* 选项 C:用沙箱 subprocess pre-flight 跑 import 试一遍,看 decorator
  是否真触发 + 抛错就拒收
* **建议 MVP = 选项 A** + UI strong-warning 文字("拖入的 .py 会直接
  跑在 backend 进程,只接受你信任来源的文件")。Stage 2 后续再考虑 B/C。

### Q4. config.yaml 写并发是否在本 stage 内统一治理?

`backend/routes/config_api.py:176-209` 已经在做 base_instruction
write-back,但**不原子**。Stage 2.1 加 MCP server 时改成 atomic
是机会,顺手把 `set_base_instruction_endpoint` 一并修复?还是 scope
内只新加 endpoint,旧 endpoint 留 backlog?
* 建议:**顺手修**,反正 helper 就那 15 行(load + mutate + tmp dump
  + os.rename + reload),抽出来都用。

### Q5. 前端 dropzone 自建还是拉 `react-dropzone`?

`grep` 已确认 0 hit 现有。20 行 HTML5 `dragover` / `drop` 原生 API
足够 + 0 依赖增加。但 `react-dropzone` 帮 accessibility / keyboard
nav 多。
* 建议:**自建**,保持依赖精简(README §零 "Skyler 是 hackable
  framework" 的依赖红线)。

### Q6. Live2D zip 上传 vs 单文件 multi-select

`<input type="file" multiple webkitdirectory>` 也是浏览器原生支持的
"整目录上传",但只在 Chromium 系工作(Tauri 用 wry/WebKit,跨平台
表现需要实测)。
* 建议:**zip 上传**为主 + 单文件 multi-select 作 fallback。zip 解
  压完整目录结构成熟可靠,单文件流要前端拼路径。

### Q7. Stage 2 完成后 `docs/skills-extension-guide.md` 是删除还是改写?

现有文档讲"姿态 A 本地 capability + 姿态 B 外部 MCP server"两条
路。Stage 2 UI 上线后,**两条路都还在**(高级用户仍可写 .py / 改
yaml);UI 是 superset。建议:**改写**——保留两个姿态的描述,
增加 § "UI 直接装" 作 fast path,引导新用户走 UI、高级用户走代码。
不要删除——`.py` 写法仍是 skill 开发的最完整方式(测试 / 复杂逻辑
等场景 UI 装不优雅)。

---

Audit 完成时间:2026-05-14
git commit hash:`87928ea`
(`87928ea45ae14dc67f5cdbd478d40e482b0a2e29`)
