# Skyler · 桌面感知 / 控制规划 — 最终目标 + MVP 现状

> 设计文档。`✅` = 已落地/已验证,`🔨` = 进行中,`📋` = 规划(未建)。
> 当前代码现状由真机调查确认;规划项均明确标注,不与现状混写。
> 更新:2026-06-22(MVP 已 ship · 见 §2.4)

---

## 一、最终目标(UIA Target)

### 1.1 一句话目标

让 Skyler 角色能**感知用户桌面、必要时操作桌面**——作为具身陪伴的能力。原则:**读 UI 安全、写动作须 gate**(与 filesystem 同形态)。

### 1.2 管线形态:感知 → 推理 → 动作 → 验证

分三层,常驻边界不同:

- **感知总线(push · 常驻)** — 谁也不"调用"它,它持续推、消费者订阅。
  - ✅ `ActivityWatcher` 粗信号:在哪个 app/URL、idle、时长(便宜、30s tick,已有,驱动现有主动陪伴)
  - 📋 选择性细监控(watch-list,见 Phase 3)
  - 📋 视觉事件(截图,chunk 8b)
- **Agent 消费者层**
  - ✅ 主动引擎(已有,reflex:快路径规则 + 慢路径 qwen-turbo judge)
  - 🔨 UIA 任务 agent(本次 MVP = 只读消费者)
  - 📋 未来 agents(导演 / dailyagent)
- **工具/动作层(pull · gated)** — agent 有 goal 时才 pull。
  - ✅ macos-use 读(AX,`refresh_traversal`,需 PID)
  - 📋 macos-use 写(8 个,在 dangerous_tools,Phase 2 才放)
  - ✅(框架)确认门 `dangerous_tools`(所有 agent 共享;⚠ 模型驱动写时是否真弹**未验**)

**主 agent = orchestrator**:长期把 UIA **委派**给独立 worker agent,主 agent(陪伴/人格脑)**不自己跑** perceive→reason→act 循环(避免卡对话、污染人格上下文)。MVP 因为只读≈一次工具调用,暂折在主 agent 里;多步/写时再 spin out worker。

### 1.3 两种感知模态(互补,不可互相替代)

| 模态 | 范围 | 特点 | 适合 |
|---|---|---|---|
| **AX 树** | per-app(按 PID,一次一个) | 深、结构化、精确 | "这个窗口/对话框里有什么" |
| **截图 + VLM** | whole-desktop(一张图全拍) | 广、一眼全、图像级(没那么精确) | "我桌面这几个窗口都有啥"、AX 盲区 |

- **应用枚举层**(NSWorkspace / osascript):列出在跑的 app + PID + 谁前台 = "感知有哪几个 app"。**这层是 macOS 工作区 API,不是 AX**;AX 是拿到 PID 后的深读。`ActivityWatcher` 已在用它取 frontmost。
- **AX 盲区**(截图才看得到):游戏画面 / 网页 canvas / VSCode 编辑器正文 / Skyler 自己的 Live2D 画布。

### 1.4 阶段路线

- **Phase 1(MVP · 现在)**:只读**前台一个(非 Skyler)app** 的 AX。
- **📋 Phase 1.5**:列 app(枚举层)+ 读**指定后台 app** 的 AX(枚举 + 按 PID traverse)。轻量(枚举层基本现成)。
- **📋 Phase 2**:gated **写**(点击/输入/滚动等)+ **验确认门**(模型驱动写时门必须真弹 = 放任何写前必过的安全关)+ 独立 worker agent 雏形。
- **📋 Phase 3**:**选择性常驻监控**(用户手选 watch-list 目标 → 便宜轮询 ~30s → 变化门[AX/像素 diff] → 仅变化时调 LLM/VLM judge → 主动开口,复用现有 throttle/cap)+ 完整独立 worker / 多 agent。
- **📋 正交 · chunk 8b 视觉**:截图 + VLM,补 AX 盲区 + 多窗口桌面扫。watch-list 的"截图那半"依赖它。

---

## 二、MVP 现状(做到什么程度)

### 2.1 MVP 是什么

**只读 UIA**:用户问"看看这窗口/对话框里有什么 / 帮我看看那个 X",角色读**当前前台(非 Skyler)app** 的 AX 树,据实回答——不脑补、不再装看见编故事。

### 2.2 形态/边界

- **单 agent**:主 ChatAgent 在现成的多步 agentic loop(`chat.py`,max 5 iter)里调一下就完,无独立 worker。
- **按需 / pull**:用户问才看,不常驻盯屏。
- **AX-only · 前台一个 app**。
- **工具层纯读**:macos-use 8 个写工具在 UI 关掉 → 想写也调不到(不依赖那道未验的门)。
- **能力意识在共享 `tool_addendum`** = **全 cid 通**(不是麻衣专属)。

### 2.3 build 内容(选定方案 B)

> 起因:`refresh_traversal` 要 `pid` 必填,而 9 个 tool 里没有 frontmost-PID 发现工具,LLM 从对话拿不到 PID。否决 A(让用户手输 PID,无实用性)、否决 C(`open_application_and_traverse` 是写、违反只读)。

- **`read_current_screen` capability**(`@register_capability` · `CHAT_AGENT`):
  - 解析"当前要看的 app"PID = **最近一个非 Skyler 自身**的前台 app(打字问时 Skyler 是 frontmost,literal frontmost 会读到自己 → 必须排除)。走 osascript(⚠ `NSWorkspace.frontmostApplication` 在 headless 后端有 RunLoop 缓存坑,见 hotfix-10)。
  - 拿到 PID 内部调 macos-use `refresh_traversal(pid)` → 返回 AX 摘要(够 MVP 回答即可;深挖 /tmp 文件留后)。
  - 纯读、无写副作用、不进 dangerous_tools。
- **`tool_addendum.py`**:加「屏幕读取」prose,指向 `read_current_screen`;据实答、别脑补、找不到说"没看到";只读,用户要写动作 → 如实说"屏幕写动作还没开放,目前只能读"。

### 2.4 当前状态

- ✅ **方案 B 已 ship**(commit `bf66ec3` 2026-06-21 · `read_current_screen` capability + `tool_addendum` 接入)。
- ✅ 已确认的底子(真机调查):macos-use **当前就活的**(DB override enabled,9/9 tool 注册进 ChatAgent);ChatAgent 是多步 loop;`refresh_traversal` 是唯一纯读(需 PID);`open_application_and_traverse` 等 8 个是写、在 dangerous_tools。
- 🔴 已知 bug:`screen.py` `self_frontmost` 大小写敏感(Skyler 前台时会读到自己的 AX 树)· 一行 `.lower()` fix 待 build + 验。

### 2.5 能做 / 不能做

**能**:看**前台单个 app** 的结构化 UI(按钮/输入框/菜单/对话框内容),据实回答。

**不能(边界 — 都是后续阶段)**:
- ❌ 写/操作(点击/输入/开 app/桌面控制)→ Phase 2
- ❌ 后台 app(非前台)→ Phase 1.5(枚举 + 按 PID 读)
- ❌ 多窗口桌面一眼扫 → chunk 8b 视觉
- ❌ 视觉盲区(游戏/网页 canvas/编辑器正文/Live2D 画布)→ chunk 8b 视觉
- ❌ 主动(不自己盯屏)→ Phase 3
- ❌ 多 agent(折在主 agent)→ Phase 2/3

### 2.6 注意点

- **Qwen "决定不调、直接编" quirk**(clipboard.translate / snooze 史):加了 prompt 大概率会调,但可能偶尔不调直接编。**验收必须看 backend log 确认她真调了 `read_current_screen`,不是只看答得像**。不调则上 `tool_call_resilience` 反向检测(抓"我看到屏幕里是…"伪造文本)+ 强提示。
- **AX 质量看 app**:原生 app(系统设置/Finder 对话框/计算器)树丰富;Electron/网页 app 部分;canvas/游戏读不到。

### 2.7 验收预案(commit + 重启后)

0. 前置:UI 关 macos-use 8 个写工具 + 重启 backend;首次 AX 调用授 macOS 辅助功能权限;若调用挂住 → `pkill -f mcp-server-macos-use`。
1. **语音**问"看看现在屏幕里有什么"(打字会让 Skyler 自己变前台)→ **看 log 真调了 `read_current_screen`** + 答的内容对得上真屏。
2. "帮我点一下/输入 X" → 应拒绝"写动作还没开放"。
3. 切到八重(cid=2)/荧(cid=3)再问同样的 → 也该能调能答(共享 tool_addendum)。
4. 问个 AX 读不到的(游戏/网页 canvas)→ 应如实说"没看到",别编。

### 2.8 在整体路线图的位置

- 这是 GSV 之后的一条探索;**读 MVP 本身就很 demo-able**(角色看你屏幕据实说有啥,是个好镜头,可进 demo video)。
- 写 / 常驻监控 / dailyagent 全是 **post-video**。
- **录 demo video 仍是锁定的下一个里程碑**;UIA 写 + 常驻 + dailyagent 在视频之后。
- 旁支(不在 UIA 簇内):email/MCP batch、玻璃外观自定义、角色 hub Build 3 等。

---

## 附:关键架构事实(供后续参考)

- **DB override 赢 yaml**:`mcp_client_state` / `mcp_tool_state` 对 yaml `enabled` 有优先权;enable/disable 走 UI 不走 yaml;改完 backend 必须重启。
- **能力意识落点**:`tool_addendum.py` 的 `TOOL_PROMPT_ADDENDUM`(共享层,经 `_render_layer_b` 注入每个角色)= 全 cid;`characters.yaml`/persona 才是角色专属。
- **感知两层别混**:工作区 API(NSWorkspace/osascript)= "有哪些 app + PID + 前台"(便宜);AX = "读进某 app 看 UI"(按 PID,贵)。
- **常驻 ≠ 全部精细**:常驻的是便宜粗信号;精细(AX 全树/截图)要么按需、要么只对手选目标(Phase 3),别当连续流跑。
