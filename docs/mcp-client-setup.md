# Skyler 接入外部 MCP Server 指南（v3-G chunk 1.5）

Skyler 也能当 MCP **client**，连外部 MCP server，把对方的 tool 反向注册成
内部 capability。注册后跟内置 capability 一样：ChatAgent 自动可用、能力面
板有卡片、health check 反映连接状态、可选地通过 Skyler 自己的 MCP server
再次暴露给上游 LLM 工具（代理模式）。

## 一、配置位置

`config.yaml` 顶层 `mcp_clients` dict，每个 entry = 一个外部 server。改完
**重启后端**生效。

```yaml
mcp_clients:
  <server-name>:        # 唯一，capability 命名空间会用：ext.<server-name>.<tool-name>
    description: "..."   # 展示用
    transport: stdio | http
    # stdio 用：
    command: npx
    args: ["-y", "@modelcontextprotocol/server-xxx", "..."]
    env:                  # 可选；会与现有 os.environ 合并后传给子进程
      KEY1: "value or ${ENV_VAR}"
    cwd: /path             # 可选
    # http 用：
    url: https://example.com/mcp
    headers:
      Authorization: "Bearer ..."
    # 通用：
    enabled: true | false                  # 默认 false；用户主动开
    expose_via_skyler_server: true | false # 是否再次暴露给 Skyler 自己的 MCP server
                                            # （默认 true = 代理模式；false = 私有）
```

### 环境变量插值

`${HOME}` / `${BRAVE_API_KEY}` / 任何 `${VAR}` 形式都会被 `os.path.expandvars`
替换，作用范围覆盖 `args` / `env` / `url` / `headers` / `cwd`。

未定义的 `${VAR}` 保留原文不替换 —— 调试时你能看到 "command 命令找不到"
而不是无头追踪。

---

## 二、stdio vs streamable HTTP 选择

| 场景 | 选 |
|---|---|
| Anthropic 官方 server（`@modelcontextprotocol/server-*`）| **stdio**，npx 启动 |
| 社区 npm / Python 本地 server | **stdio** |
| 远程已部署的 MCP server | **http** |
| 不确定 | **stdio** —— 99% 官方 / 社区 server 走 stdio |

stdio 模式 Skyler 会 fork 一个子进程，stdin/stdout 双向 JSON-RPC，子进程
生命周期跟 Skyler 后端绑定（后端关 → 子进程退出）。

---

## 三、`expose_via_skyler_server` 含义

* **`true`（代理模式）**：外部 server 的 tool 也会通过 Skyler 自己的 `/mcp`
  endpoint 暴露给上游 LLM 工具（Claude Desktop 等）。Claude Desktop 看到的 tool
  数 = 内置 + 外部 expose 的总和。**适合**：filesystem 这种纯本地、安全的工具。
* **`false`（私有模式）**：外部 server 的 tool 只给 Skyler ChatAgent 内部用，**不**经
  Skyler MCP server 转发出去。**适合**：Brave search 等带 API 配额 / 鉴权
  的 server —— 多级转发会让上游 LLM 直接消耗你的 API 配额，且配额泄露排查
  极难。
* 内部 capability 仍然能调外部 server 的 tool（不论 expose_via_server 何值），
  这个开关只控制"是否再次暴露"。

---

## 四、完整示例 1：Filesystem（Anthropic 官方）

读你 `~/Documents` 下文件给 Skyler / 上游 LLM 用。

```yaml
mcp_clients:
  filesystem:
    description: "本地文件读取（Anthropic 官方 server）"
    transport: stdio
    command: npx
    args: ["-y", "@modelcontextprotocol/server-filesystem", "${HOME}/Documents"]
    enabled: true
    expose_via_skyler_server: true
```

启用前：

```bash
# 验证 npx 可用
which npx
# 验证子进程跑得起来（手动测一次，Ctrl-C 退出）
npx -y @modelcontextprotocol/server-filesystem ~/Documents
```

启用后：能力面板 `mcp_external` 类目应出现 `ext.filesystem.read_file` /
`ext.filesystem.write_file` / `ext.filesystem.list_directory` 等 tools，每张卡片
徽章显示 `[ext · filesystem]`。

跟 Momo 聊"读一下 ~/Documents/notes/今天.md"应能触发 ext.filesystem.read_file。

---

## 五、完整示例 2：Brave Search（需要 API key）

```yaml
mcp_clients:
  brave-search:
    description: "Brave 搜索（需要 BRAVE_API_KEY）"
    transport: stdio
    command: npx
    args: ["-y", "@modelcontextprotocol/server-brave-search"]
    env:
      BRAVE_API_KEY: "${BRAVE_API_KEY}"
    enabled: true
    expose_via_skyler_server: false   # 关键：不代理出去，避免上游耗你配额
```

`.env` 加：

```bash
BRAVE_API_KEY=BSA...your_key_here
```

[申请 Brave Search API key](https://api.search.brave.com/) → free tier 每月 2000 次。

启用后：能力面板看到 `ext.brave-search.brave_web_search` 等。**注意**：在
Claude Desktop 的"已暴露 tools"清单里**不会**看到这条 —— 因为
`expose_via_skyler_server: false`。但 Momo 内部 ChatAgent 可以调（适合"搜
一下 X" 这种用户问句）。

---

## 六、故障排查

| 症状 | 排查 |
|---|---|
| 能力面板"外部 MCP servers"里显示红点 + "命令找不到" | `which npx` 验证；Node 没装 → `brew install node`；`command:` 写绝对路径 |
| 启动时 "API key 失败" / 子进程立刻退出 | env 变量没插值（`${BRAVE_API_KEY}` 找不到值会保持原文）；检查 `.env` 是否被读 |
| 连接超时 / "client not connected" | 子进程没 ready；点 [重连] 按钮重试；看后端日志 `[mcp.client] failed to connect` |
| "expose 给 Claude Desktop 但看不到外部 tool" | `expose_via_skyler_server` 设为 `false` 时不会派发；改 `true` 后**重启 Skyler 后端 + Claude Desktop** |
| 同名 tool 冲突（外部 server A 和 B 都有 search） | 当前用 `ext.<server-name>.<tool-name>` 命名空间隔离，不会冲突 |
| 子进程没退干净（端口占用 / 文件锁） | `pkill -f "@modelcontextprotocol/server-"` 然后重启 Skyler；这是 stdio 模式的固有风险 |

---

## 七、API endpoint

* `GET /api/mcp/clients/status` —— 列所有 client 状态（前端 panel 拉这个）
* `POST /api/mcp/clients/{name}/reconnect` —— 手动重连某个 client（panel "重连" 按钮调）

---

## 八、命名空间约定

外部 capability 命名严格遵循：

```
ext.<server-name>.<external-tool-name>
```

* `<server-name>` 来自 `config.yaml` 你写的 key
* `<external-tool-name>` 来自外部 server 自报的 `tool.name`

这样：

* 内置 capability（time.now / calendar.*）和外部不会冲突
* 不同外部 server 即使有同名 tool（两个都叫 search）也不会冲突
* 上游 LLM 看到 `ext.brave-search.search` 一眼能识别来源
