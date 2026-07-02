# Skyler · ROADMAP

> 当前路线图以本地代码为准。更细的版本演进见 [docs/EVOLUTION.md](docs/EVOLUTION.md),历史实施日志见 [IMPLEMENTATION_LOG.md](IMPLEMENTATION_LOG.md)。
>
> 状态定义:已落地 = 本地代码链路已经接通;进行中 = 有基础实现或框架,但策略 / 端到端验证 / 多角色化还没完成;规划 = 设计方向明确但不应写成当前能力。

---

## 项目定位

Skyler 是一个**连续人格驱动的 Live2D 桌面 AI 陪伴角色系统**。

它不是给问答 AI 套角色外观,而是围绕 Persona、状态系统、四层记忆、活动时间线和多源上下文组装,让角色持续积累状态,逐渐形成自己的节奏和生活感。

Local-first 的边界:对话记录、角色状态、记忆、活动时间线等数据由本地 SQLite / 本地文件持有;LLM / TTS / ASR provider 可替换,可以接云端或自托管服务,不要表述为完全离线。

---

## 已落地

### UI / 桌面形态

- 双形态 UI:全屏主面板 + 桌宠小窗。
- 主面板承载完整对话、聊天历史、角色管理、能力配置和设置浮层。
- 小窗承载低打扰陪伴、Live2D 展示、ASR 预览、VAD 状态和快速控制。
- Live2D 渲染、模型扫描 / 管理 / 上传、Cubism 4 路径、framing 缩放 / 位移控制。
- 进入动画、立绘馆、角色详情中心、玻璃外观自定义和主题系统。

### 交互链路

- 文本输入。
- 语音链路:VAD / 手动录音、ASR、LLM streaming、TTS、Live2D 表演。
- TTS provider × model × voice 分层,支持 GSV / CosyVoice / Fish 等路径。
- 图片和文件作为**当轮输入**进入模型上下文。
- 文件输入会抽取文本后进入当前 prompt;图片输入以 image block 进入当前模型调用,理解能力取决于 active model。

### Persona / 角色卡

- 结构化 Persona 表与 API:`character_personas`、active variant、内置 seed 备份、恢复默认。
- Persona 字段覆盖身份、性格、语气、样例、禁忌、关系、lore 等。
- 前端角色详情页和 Persona 编辑器已接入。
- `card_type` 基础链路已接入:社交型 / 助手型。
- 社交型偏日常交流、关系和情绪表达;助手型偏任务、工具能力和行为边界。
- Prompt 模板已消费 Persona v2 多数字段。

### 状态与记忆

- 状态层:`mood`、`intimacy`、`current_thought`、`current_activity`。
- `<state_update />` 写回协议。
- `character.get_state` capability。
- intimacy 每日衰减。
- 短期窗口:按 user / character / conversation 隔离。
- 对话摘要:长对话滚动 fold。
- 长期语义记忆:embedding 检索、遗忘曲线、tombstone 抑制删除事实回流。
- 用户画像:`users.profile_data` 结构化 JSON。
- 活动上下文:`activity_sessions` 与今日活动格式化注入。

> “四层记忆”在当前代码里应按真实来源理解为:短期窗口 / 对话摘要 / 长期语义记忆 / 用户画像与活动状态上下文,不要写成另一个不存在的独立架构。

### Activity / 主动陪伴

- 活动时间线记录 active app、browser、document、URL content 等上下文。
- 活动 session 持久化,支持跨 session 查看与清理。
- 今日活动可被格式化后注入 ChatAgent prompt。
- 主动触发雏形已接入:IDE、音乐、技术文档、长时间专注等触发。
- idle gate / throttle / daily cap / active conversation guard 已接入,避免过度打扰。

### DailyAgent Stage 1

- 日计划表 `character_daily_plans`。
- 日计划生成服务。
- 当前活动 ticker 根据当天计划写回 `current_activity`。
- 今日计划 API 和角色详情页可视化。

### 桌面感知 / Perception

- 只读 AX / UI Tree 桌面感知已落地。
- 能读取前台 app、窗口标题、可见 UI 文本、浏览器 URL / 内容等结构化上下文。
- `screen.read_current_screen` 读取当前非 Skyler 前台 app 的 AX 树。
- 当前能力是只读;适合 demo 展示“基于证据理解当前桌面上下文”。

### Capability / MCP / Provider

- CapabilityRegistry 作为统一能力注册层。
- `@register_capability` 自动导出 schema 并注入 ToolRegistry。
- MCP client 可消费外部 server tools,注册为 `ext.<server>.<tool>` capability。
- MCP server 可暴露 Skyler 自身 capability。
- per-tool 开关。
- confirm gate 框架。
- LLM provider 走 LiteLLM + DB active provider / yaml fallback。
- TTS provider registry 支持 provider / model / voice 分层。

---

## 进行中

- DailyAgent 完整 FSM / 多角色调度。
- 社交型 / 助手型运行时策略进一步分流。
- 上下文仲裁策略增强:从当前 prompt 组装顺序和 gate,演进为更明确的优先级 / 证据 / 状态仲裁。
- 写操作确认门端到端验证:确认门框架已在,但危险写操作不能宣传为已完整安全可用。
- 主动视觉感知:
  - 小模型常驻监视变化。
  - 判断是否需要进一步视觉理解。
  - 截取当前窗口或局部屏幕。
  - 调用 Qwen Plus / Flash 等支持图片输入的模型理解当前画面。
- 图片/文件持久化和记忆沉淀。
- 凭证治理和危险工具安全策略。
- 多角色 Persona 内容完善。
- 长期记忆陪伴质量真机回归。
- Live2D emotion → expression map 的角色级补全。

---

## 规划

- AX + 视觉模型融合。
- 更完整多角色协作。
- 长期自治。
- Persona-level learning。
- Live2D AI director / 更完整 expression map / 动作与表情选择策略。
- 原创贴纸 / 多模态表达通道。
- 图片生成能力。
- 记忆架构 v2 / 更强 RAG。
- 打包发布 / dmg / 自动更新。
- CI release 与 dogfood 更新链路。

---

## Demo 口径

可展示:

- 全屏主面板 + 桌宠小窗。
- Live2D、语音链路、Persona 角色系统、活动时间线、只读 AX / UI Tree、MCP 能力扩展。
- DailyAgent Stage 1 可标为“建设中 / 已接入基础链路”,不要说完整 FSM。
- 感知页应写成 Perception / 桌面感知,明确区分已落地 AX / UI Tree 和建设中的主动视觉感知。

不要夸大:

- 不要说完整 VLM 屏幕视觉系统已完成。
- 不要把用户上传图片/文件与主动截屏视觉感知混为一谈。
- 不要说写操作安全可用已经端到端验证。
- 不要说完整多角色生态、长期自治或多角色协作已完成。

---

## 近期建议顺序

1. Demo 视频与投递材料:先把已落地能力讲清楚,并诚实标注进行中能力。
2. DailyAgent:补齐完整 FSM、多角色调度和 card_type gate。
3. Perception:在 AX / UI Tree 之外,逐步接入主动视觉感知的截图判断链路。
4. Safety:验证写操作确认门、完善危险工具策略和凭证治理。
5. Persona:完善社交型 / 助手型运行时分流和多角色内容。
