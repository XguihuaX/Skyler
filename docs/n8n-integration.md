# n8n / 外部 Workflow 工具接入指南（v3-G chunk 0）

## 总览

MomoOS 后端在 v3-G chunk 0 起暴露一组 webhook 接收端，给 n8n / Zapier /
Make / 自建脚本之类的外部 workflow 工具一条**反向**调用通道：

```
外部工具  ──────►  POST /api/webhooks/n8n/{trigger_name}
                  Authorization: Bearer ...
                  X-Signature:    ...                          (双因子)
                  Body:           {... 任意 JSON ...}

后端    ──────►  WEBHOOK_HANDLERS[trigger_name](payload)       (异步 dispatch)
        ──────►  立即返回 {"status":"accepted","trigger":...}  (n8n 不等)
```

设计取舍：

* 不暴露 ChatAgent / Capability 给外部直接调（避免 capability 误用）
* 而是定义具名 trigger，每个 trigger 一个明确职责（"日历事件到了"、"Bilibili
  有新视频"、"早上 7 点起床问候"），由 handler 翻译成 MomoOS 内部动作
* 鉴权双层：Bearer 防误调 + HMAC SHA256 防 payload 篡改

---

## 鉴权配置

### 1. 生成两个随机密钥

```bash
openssl rand -hex 32   # → N8N_BEARER_TOKEN
openssl rand -hex 32   # → N8N_HMAC_SECRET
```

### 2. 写进项目根 `.env`

```bash
N8N_BEARER_TOKEN=<刚生成的第一串>
N8N_HMAC_SECRET=<刚生成的第二串>
```

后端 lazy 读取（首次 webhook 调用时校验）。`.env` 改完不需要重启就能生效，
但**已经在跑的请求**仍按旧值。

### 3. 把同样两个密钥复制到 n8n 工作流的 credentials

n8n 的 HTTP Request 节点配置项里：

* **Method**：POST
* **URL**：`http://localhost:8000/api/webhooks/n8n/test`（替换 trigger_name）
* **Headers**：
  - `Authorization: Bearer {{ $credentials.bearer_token }}`
  - `X-Signature: {{ $crypto.hmac("sha256", $json.body, $credentials.hmac_secret) }}`
  - `Content-Type: application/json`
* **Body**：JSON，由前面节点构造

如果 n8n 部署在另一台机器，把 `localhost` 换成 MomoOS 后端的可达地址。

---

## 签名约定（重要）

`X-Signature` 是对**原始请求 body bytes** 的 HMAC SHA256，hex 编码：

```python
signature = hmac.new(
    N8N_HMAC_SECRET.encode("utf-8"),
    raw_body_bytes,
    hashlib.sha256,
).hexdigest()
```

**注意点**：

* 签名输入是**原始 bytes**，不是 dict。如果 workflow 工具帮你 `JSON.stringify`
  之后再签，要确保发送的 body 也是同样的 stringify 结果（避免 key 排序 / 空格
  差异让签名失效）。
* 容忍 `sha256=` 前缀（GitHub-style）：`X-Signature: sha256=abc123...` 也接受
* `hmac.compare_digest` 防 timing-attack —— 调试时不要看签名匹配速度。

---

## 当前已注册的 trigger

| trigger_name | handler 行为 | 用途 |
|---|---|---|
| `test` | log + 返回 echo | 接通验证用，发什么 payload 后端就 echo 回 `text` 字段 |

新增 trigger 在 `backend/routes/webhooks_api.py` 的 `WEBHOOK_HANDLERS` dict 注册：

```python
async def handle_my_new_trigger(payload: dict) -> dict:
    # 在这里写真实业务逻辑（推 Live2D / 触发主动对话 / 写 daily_briefing）
    ...
    return {"status": "ok"}

WEBHOOK_HANDLERS["my_new_trigger"] = handle_my_new_trigger
```

handler 必须 async 且返回 dict（即使没人看返回值，方便 log）。

---

## curl 测试命令（快速验证）

把 `BEARER` / `SECRET` 替换成你 `.env` 里的真值：

```bash
BEARER="your-bearer-token-here"
SECRET="your-hmac-secret-here"
BODY='{"text":"hello from curl"}'

SIG=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "$SECRET" | awk '{print $2}')

curl -i -X POST http://localhost:8000/api/webhooks/n8n/test \
  -H "Authorization: Bearer $BEARER" \
  -H "X-Signature: $SIG" \
  -H "Content-Type: application/json" \
  -d "$BODY"
```

期望响应：

```
HTTP/1.1 200 OK
content-type: application/json

{"status":"accepted","trigger":"test"}
```

后端日志应能看到（INFO 级）：

```
[n8n webhook test] payload={'text': 'hello from curl'}
```

---

## 错误对照表

| HTTP | 含义 | 排查 |
|---|---|---|
| 200 | 已接收，handler 异步跑 | 看后端日志确认 handler 行为 |
| 400 | payload 不是合法 JSON 对象 | body 必须是 object，不能是 array / string / null |
| 401 | Bearer 或 HMAC 校验失败 | 检查 `.env` 与 n8n credentials 是否一致；检查签名是不是对**原始 body bytes**算的 |
| 404 | trigger_name 未注册 | 看 `WEBHOOK_HANDLERS` dict |
| 503 | `N8N_BEARER_TOKEN` / `N8N_HMAC_SECRET` 没在 server 配置 | 写 `.env` 后**重启**后端 |

---

## 安全提示

* webhook URL **不要**暴露到公网（Cloudflare Tunnel / Tailscale 走 zero-trust 才行）
* 即便是 localhost-only，也保留 Bearer + HMAC 双因子（防本机其他进程意外调）
* 不要把 token / secret commit 进 git——`.env` 已在 `.gitignore` 内
* 如果 token 泄露，`openssl rand -hex 32` 重新生成两组并同步到 n8n 即可，
  不需要改代码
