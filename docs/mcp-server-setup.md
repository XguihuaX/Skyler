# Skyler 作 MCP Server 接入指南（v3-G chunk 1.5）

Skyler 把内部所有 capability 自动派生成 MCP tool 暴露给外部 LLM 工具
（Claude Desktop / Cursor / Claude Code 等）。本文教你怎么连接。

## 一、获取 endpoint + Bearer token

### 启动后

打开 Skyler → 设置 → 能力面板 → 顶部"MCP server 已启用"banner：

* **Endpoint**：`http://localhost:8000/mcp`
* **Bearer token**：banner 上点 [👁] 显示完整值，[📋] 一键复制 `Bearer xxx`

如果 banner 显示"⚠️ 未配置 MCP_BEARER_TOKEN"，需要在项目根 `.env` 写一个：

```bash
echo "MCP_BEARER_TOKEN=$(openssl rand -hex 32)" >> .env
```

然后重启后端。

### Banner 不可见？

config.yaml 里 `mcp_server.enabled` 必须为 `true`。默认开启。

---

## 二、Claude Desktop 配置

### macOS 路径

`~/Library/Application Support/Claude/claude_desktop_config.json`

### 配置示例

```json
{
  "mcpServers": {
    "skyler": {
      "type": "streamableHttp",
      "url": "http://localhost:8000/mcp",
      "headers": {
        "Authorization": "Bearer YOUR_TOKEN_HERE"
      }
    }
  }
}
```

把 `YOUR_TOKEN_HERE` 换成你 `.env` 里的 `MCP_BEARER_TOKEN` 真值。

保存后**完全退出 Claude Desktop**（菜单 → Quit，不是关窗口）再重新打开。

### 验证

在 Claude Desktop 对话里试问：

> "用 skyler 看看现在几点"

应触发 `time.now` capability。如果触发，Claude Desktop 工具栏会有一个 "🔧
Used X tools" 提示。

---

## 三、Cursor 配置

### 路径

`~/.cursor/mcp.json` 或在 IDE 里 Settings → MCP → Edit JSON。

### 配置示例

```json
{
  "mcpServers": {
    "skyler": {
      "type": "http",
      "url": "http://localhost:8000/mcp",
      "headers": {
        "Authorization": "Bearer YOUR_TOKEN_HERE"
      }
    }
  }
}
```

Cursor 不同版本对 streamable HTTP 支持有差异。如果版本太旧只支持 stdio，先升级 Cursor。

---

## 四、Claude Code (CLI) 配置

```bash
claude mcp add --transport http --header "Authorization: Bearer YOUR_TOKEN" skyler http://localhost:8000/mcp
```

---

## 五、用 mcp inspector 测试

[mcp-inspector](https://github.com/modelcontextprotocol/inspector) 是官方调试工具：

```bash
npx @modelcontextprotocol/inspector http://localhost:8000/mcp
```

启动后在浏览器打开 inspector UI，"Headers" 面板加：

```
Authorization: Bearer YOUR_TOKEN
```

点 "Connect" → 应能看到当前所有暴露的 tool 列表。点任一 tool → 填参数 → 调用 → 看响应。

---

## 六、当前暴露的 tools

来源：所有 `Consumer.CHAT_AGENT` 且 `metadata.expose_via_server` 不为 False 的 capability。
默认包含：

| name | 说明 |
|---|---|
| `time.now` | 获取当前时间（v3-G chunk 0） |
| `calendar.today_events` | 今天 Google Calendar 事件（v3-G chunk 1） |
| `calendar.upcoming_events` | 未来 N 天 Google Calendar 事件 |

接入外部 MCP server（chunk 1.5 client 模式）后，对方的 tool 也会反向暴露
出去 —— 除非在 `mcp_clients.<name>.expose_via_skyler_server` 设为 `false`。
完整可暴露 tool 列表见 banner 旁的"N tools 已暴露"和 inspector 输出。

---

## 七、安全

* **绝不**把 `MCP_BEARER_TOKEN` commit 进 git；`.env` 已在 `.gitignore` 内
* **绝不**让 `localhost:8000/mcp` 暴露到公网；如果要远程访问，走 Cloudflare
  Tunnel / Tailscale 等 zero-trust 网关，**不要**改 0.0.0.0 或 reverse proxy
* token 泄露时立即 `openssl rand -hex 32` 重新生成，写回 `.env` 并重启后端，
  同步更新所有外部客户端配置

## 八、错误对照

| HTTP / 现象 | 含义 | 排查 |
|---|---|---|
| 401 missing Bearer token | 客户端没带 Authorization 头 | 检查客户端 `headers` 配置 |
| 401 bearer token mismatch | token 不一致 | 重新复制 banner 上的 token |
| 503 MCP_BEARER_TOKEN not configured | 后端 .env 没有 token | `openssl rand -hex 32 >> .env` 后重启 |
| 503 MCP server disabled in config | config.yaml `mcp_server.enabled: false` | 改成 `true` |
| Claude Desktop 看不到 skyler 工具 | 配置没生效 / 后端未启 | 完全退出 Claude Desktop 重启；确认 Skyler 后端在跑；inspector 先验证 |
