# Apple Calendar 接入指南（v3-G chunk 1.6）

Skyler 直接走 macOS EventKit 读 / 写 Apple Calendar，**零网络 / 零 VPN /
零外部账号**。如果你的日程数据已经在 iCloud / 本地 Calendar.app（不论原始
来源是 iCloud / Google / Outlook / Exchange，只要在 macOS Calendar.app 里
看得到都行），就能用。

国内大陆用户的最佳选择 —— Google Calendar 即便挂代理也常被防火墙抖断
（chunk 1 经验），Apple Calendar 完全本地，永不挂。

---

## 一、依赖

```bash
pip install -r requirements.txt
```

`requirements.txt` 里 `pyobjc-framework-EventKit>=10.0` 仅 macOS 实际安装
（PEP 508 平台标记 `sys_platform == "darwin"`）。Linux / Windows 开发机
不会装这个包，但能正常 `pip install -r requirements.txt`，相关 capability
在非 macOS 平台 health_check 直接返黄色警告，不会阻塞主流程。

---

## 二、第一次启动（系统权限弹框）

1. 启动 Skyler 后端
2. 第一次调用任何 Apple Calendar capability 时（聊天里说"今天有什么会"
   或测试简报按钮），macOS 会弹出系统权限对话框：

   > "Skyler" wants access to your calendar.

3. 点 **允许 / OK**
4. 之后调用都直接生效，不会再弹

**重要**：这个权限框是 macOS 系统级保护机制，不是 Skyler 的 UI。你必须
亲眼看到并主动允许 —— Skyler 不会绕过 / 预先警告 / 替你点击。

如果第一次没看到权限框：
- 检查系统设置 → 隐私与安全性 → 日历 → 看 Skyler 是否在列表里
- 如果在列表里但开关是关的，手动打开
- 如果不在列表，关掉 Skyler 后端 → 重新调一次 capability，等弹框

---

## 三、iCloud 同步（让 iPhone / iPad 上的事件也可见）

如果你想 Skyler 看到 iPhone 上加的事件 / 在 Skyler 创建后能同步到 iPhone：

1. 系统设置 → 顶部你的 Apple ID → iCloud → "Show All" → **Calendars** 打开
2. 打开 Calendar.app 验证：左侧栏应能看到 "iCloud" 分组下的日历
3. 重启 Skyler 后端，再调用一次 capability

如果没开 iCloud 同步，Skyler 仍能用，但只看到 macOS 本机日历（"On My Mac"）。

---

## 四、多日历选择

macOS Calendar.app 通常有多个日历（"工作"、"个人"、"家庭"、"假期"等）。
Skyler 默认行为：

- **读事件**（today_events / upcoming_events）：拉**所有**已勾选可见的日历
- **创建事件**（create_event）：写到**系统默认日历**（Calendar.app 偏好设置 →
  默认日历）。可以在调用时显式传 `calendar_name="工作"` 写到指定日历。

让 Momo 把日程加到工作日历：

> 把"明天上午 10 点产品评审会"加到工作日历

Momo 应该调用 `apple_calendar.create_event(title="产品评审会", start_iso="...", calendar_name="工作")`。

---

## 五、跟 Google Calendar 切换

`config.yaml` 顶层：

```yaml
calendar:
  default_source: apple   # apple | google

apple_calendar:
  enabled: true

google_calendar:
  enabled: false   # 默认禁用；想用改成 true 并按 docs/google-calendar-setup.md 配 OAuth
```

`calendar.today_events` / `calendar.upcoming_events` 这两个**路由 capability**
按 `default_source` 自动选数据源 —— 改 yaml 重启就生效。`apple_calendar.*`
和 `google_calendar.*` 直接 capability 仍可独立调（高级用户场景）。

如果两个 source 都 enable + default_source=apple：Skyler 内部 ChatAgent
读事件走 Apple；用户明确说"用 Google 看一下"时 LLM 调 `google_calendar.*`。

---

## 六、故障排查

| 症状 | 排查 |
|---|---|
| 能力卡片黄色 + "Apple Calendar 仅 macOS 可用" | 你不在 macOS 上 —— 用 Google Calendar 或别用日历能力 |
| 黄色 + "pyobjc-framework-EventKit 未安装" | `.venv/bin/pip install -r requirements.txt` 重装 |
| 黄色 + "未授权访问日历" | 调一次任意 calendar capability 等弹框；或系统设置 → 隐私与安全性 → 日历 手动打开 Skyler 开关 |
| 创建事件后 Calendar.app 看不到 | 先在 Calendar.app 左侧栏看选中日历对不对；尝试 Cmd-R 刷新；iCloud 同步可能慢几秒 |
| "找不到可用日历（系统默认日历未设置？）" | 系统设置 → 通用 → 默认日历 选一个；或调用时显式传 `calendar_name` |
| 第一次没弹权限框 | 系统设置 → 隐私与安全性 → 日历 → 检查 Skyler 是否被你之前拒绝过；切换开关 |

---

## 七、scope / 权限升级路径

当前 Skyler 申请 **完整事件读写权限**（macOS 14+ 的 `requestFullAccess`）。
如果将来要加 reminders（提醒事项）能力，需要额外申请
`requestFullAccessToRemindersWithCompletion_` —— 那是另一个独立权限框。

**绝不**会申请通讯录 / 文件 / 位置等无关权限 —— Skyler 严格只在能力实际需
要时申请最小权限。

---

## 八、跟 chunk 1 Google Calendar 的关系

* chunk 1（2026-05-07）接入 Google Calendar via OAuth desktop flow
* chunk 1.6（2026-05-07）接入 Apple Calendar via EventKit
* **Google 代码保留**：`backend/integrations/google_calendar.py` + `backend/capabilities/google_calendar.*`
  (chunk 1 的 capability 现在重命名到 google_calendar 命名空间，从 LLM tool surface
  里降级；你哪天想用打开 yaml 即可)
* `calendar.today_events` / `calendar.upcoming_events` 是**统一路由层**，两个 source
  都能服务，LLM 看到的是这两个 router caps 而非 source-specific 的具体实现
