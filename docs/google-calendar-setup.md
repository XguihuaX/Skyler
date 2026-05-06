# Google Calendar 接入指南（v3-G chunk 1）

Skyler 通过 Google Calendar API 拉取你的日程，给 ChatAgent 提供"今日有什么会"
能力，给起床简报提供素材。所有调用是**只读**（scope `calendar.readonly`），
不会写入 / 删除 / 修改你的日历。

---

## 一、Google Cloud Console 创建 OAuth client

### 1. 登录 [Google Cloud Console](https://console.cloud.google.com/)

需要一个 Google 账号。如果你身处国内大陆，**强烈建议挂代理**——不光是
Console 本身需要，后续 Skyler 调 Calendar API 也走 Google 国际网络。

### 2. 创建一个新 project

- 顶部下拉 → "New Project"
- 名字随便（"skyler-personal" 之类）
- 创建后切换到这个 project

### 3. 启用 Google Calendar API

- 左侧菜单 "APIs & Services" → "Library"
- 搜索 "Google Calendar API"
- 点 "Enable"

### 4. 配置 OAuth consent screen

- 左侧 "APIs & Services" → "OAuth consent screen"
- User Type 选 "External"（个人 Google 账号必须选这个）
- 填 app name（"Skyler"）+ 你的邮箱即可
- Scopes 这一步可以跳过（OAuth flow 自己会带 scope）
- Test users：**把你自己的 Google 邮箱加进去**——否则 OAuth flow 会拒绝

### 5. 创建 OAuth client credentials

- 左侧 "APIs & Services" → "Credentials"
- "Create Credentials" → "OAuth client ID"
- Application type 选 **"Desktop app"**（不是 Web！Skyler 是本地 desktop 应用）
- 名字随便（"skyler-desktop"）
- 创建完成后在 client 列表里点下载图标 → 得到一个 JSON 文件，
  通常叫 `client_secret_xxxxx.apps.googleusercontent.com.json`

### 6. 把这个 JSON 放到 Skyler 能找到的位置

```bash
mkdir -p ~/.skyler
mv ~/Downloads/client_secret_*.json ~/.skyler/google_credentials.json
```

文件路径 **必须**是 `~/.skyler/google_credentials.json`，不是别的名字。

---

## 二、第一次连接 Google 账号

1. 启动 Skyler（前端 + 后端）
2. 切换到设置 → "能力 — Momo 能做什么" 面板
3. 找到 `calendar.today_events` / `calendar.upcoming_events` 卡片
   - 状态会是黄色"注意"，提示"未授权，请连接 Google 账号"
4. 点卡片底部的 **[连接 Google]** 按钮
5. **Skyler 后端**会启动一个临时本地 HTTP server 并自动打开浏览器到 Google
   授权页面
6. 在浏览器选你刚才在 OAuth consent 加进 Test users 的那个 Google 账号
7. 看到一个"Google hasn't verified this app"警告 → "Advanced" → "Go to
   skyler-personal (unsafe)" → "Continue"——这个警告对个人 desktop OAuth
   client 是正常的（Google 不为每个个人 app 做认证）
8. 同意 calendar 只读 scope
9. 浏览器跳到一个 "The authentication flow has completed" 页面，可以关掉
10. Skyler 卡片状态会变成绿色"健康"——授权完成，token 保存在
    `~/.skyler/google_token.json`

---

## 三、国内访问注意事项

* Google Calendar API 端点 `googleapis.com` 在国内被墙，调用必须走代理：
  系统级代理（V2Ray / Clash 等设置到 HTTP_PROXY / HTTPS_PROXY 环境变量）
  对 Skyler 后端有效。
* 网络不稳定时 Skyler 会**自动重试 3 次**（指数退避 1 → 2 → 4 → 8 秒），仍失败
  时 Capability 健康状态会显示黄色"网络异常"——不会刷成红色 error，因为
  这是国内常态而非真的故障。
* Calendar API 每天有 quota，但个人使用远远摸不到上限（百万级 read），
  不需要担心。

---

## 四、撤销 / 重新授权

* 点能力卡片底部 **[重新授权]** 按钮，会先删 `~/.skyler/google_token.json`
  再重启 OAuth flow。
* 在 Google 账号里也可以单独 revoke：
  https://myaccount.google.com/permissions —— 找到 Skyler，撤销访问权限。
  下次 Skyler 调 API 时 refresh 会失败，能力卡片自动回到"未授权"状态。

---

## 五、调试

后端日志（`uvicorn` 输出 / `logger` INFO+）里搜 `google_calendar`：

* `[google_calendar] OAuth completed, token saved to ...` —— 首次授权成功
* `[google_calendar] token.json parse failed` —— token 文件损坏，删掉重新授权
* `[google_calendar] token refresh failed (likely revoked)` —— 你在 Google
  侧 revoke 了；点重新授权
* `[google_calendar] token refresh network err` —— 代理 / 网络问题，本次跳过

---

## 六、scope 升级路径

当前 scope 仅 `calendar.readonly`。未来要加：

* 创建 / 修改事件 → `calendar.events`
* 多日历访问 → `calendar`（无 readonly 后缀，全权限）

加 scope 时**必须**先 revoke 当前 token（同上"撤销"步骤），再重新 OAuth flow，
否则 Google API 调新 scope 会返 403 insufficient scope。
