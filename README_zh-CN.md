<!-- 给用户审阅的新 README(中文版,对应 README_zh-CN.md)。
     落库前:① CC 把所有具体状态/版本/路径回代码核;② EN README.md 同步镜像;③ 截图待补。
     定位:只讲「是谁 / 能干什么 / 怎么干 + 最近更新 + 诚实定位」。细粒度状态全在 ROADMAP。 -->

# 🌸 Skyler

> 连续人格驱动的 Live2D 桌面 AI 陪伴角色系统。

![Python](https://img.shields.io/badge/Python-3.10+-blue) ![FastAPI](https://img.shields.io/badge/FastAPI-async-green) ![Tauri](https://img.shields.io/badge/Tauri-2.0-orange) ![React](https://img.shields.io/badge/React-18-61DAFB) ![Platform](https://img.shields.io/badge/platform-macOS-lightgrey)

🌐 **Languages**: [English](README.md) · **简体中文** · 项目原名 MomoOS,2026-05 改名 Skyler。

---

## Skyler 是什么?

Skyler 是一个连续人格驱动的 Live2D 桌面 AI 陪伴角色系统。

它不是给问答 AI 套上角色外观,而是围绕 Persona、状态系统、四层记忆、活动时间线和多源上下文组装,让角色持续积累状态,逐渐形成自己的节奏和生活感。

Skyler 支持全屏主面板和桌宠小窗两种形态。主面板用于完整对话、角色管理和能力配置;小窗用于低打扰陪伴、主动搭话和桌面上下文感知。Live2D 渲染、模型管理和 framing 已经接入,角色外观、音色、人格和能力可以分别配置。

当前本地代码已经接入文本、语音、图片和文件作为交互输入;语音链路覆盖 VAD、ASR、LLM streaming、TTS 和 Live2D 表演。图片和文件可以进入当轮模型上下文,但长期持久化和记忆沉淀仍在建设中。

桌面感知当前以只读 AX / UI Tree 为主,可以读取前台 app、窗口标题、可见 UI 文本、浏览器内容等结构化上下文;主动视觉感知正在建设中,后续会探索小模型常驻监视变化,并在需要时调用支持图片输入的模型理解当前窗口或局部屏幕。

DailyAgent 仍在建设中。当前 Stage 1 已接入日计划生成、当前活动 ticker 和状态写回,后续会继续完善为更完整的角色日常节奏系统。

Skyler 是 local-first,不是完全离线承诺:对话记录、角色状态、记忆、活动时间线等数据由本地 SQLite 和本地文件持有;LLM / TTS / ASR provider 可以替换,也可以接云端或自托管服务。

*(一句实话:这是我一个人做的项目,当前在 macOS Apple Silicon 上主力验证。)*

---

## 看一眼

<!-- TODO:补真实截图到 docs/assets/。一个 Live2D 视觉产品的 README 必须有图。 -->

| 浮玻璃陪伴态(桌宠) | 立绘馆 / 角色详情 |
|---|---|
| ![companion](docs/assets/companion.png) | ![gallery](docs/assets/gallery.png) |

| 主对话 + Live2D | MCP / 能力管理 |
|---|---|
| ![chat](docs/assets/chat.png) | ![mcp](docs/assets/mcp.png) |

> 项目怎么一步步长出来的(版本 × 功能演进)→ [EVOLUTION.md](docs/EVOLUTION.md)。

---

## 最近更新(2026-06)

> 完整能力状态见 [ROADMAP.md](ROADMAP.md);版本演进见 [EVOLUTION.md](docs/EVOLUTION.md)。

- **2026-06-21** · 桌面感知只读上线 —— 角色能读当前前台窗口的 UI 树(macOS 无障碍 AX)并据实回答;读屏只读,写动作能力已建但确认门未验,建议先手动关。
- **2026-06-21** · 聊天体验:深度思考 / 联网双开关 + 气泡本地时间戳 —— 聊天框 + 设置双入口,默认快(关思考),想深再开;每条气泡左下挂本地时间小字。
- **2026-06-20** · 玻璃外观自定义器 + 角色详情中心 Build 1 —— 陪伴态浮窗按壁纸自调对比度、切主题保留;立绘馆里看人格 / 心情 / 状态并就地编辑 persona。
- **2026-06-17** · 本地语音 GSV 本地化 —— 自训音色 `mai_v4` + 16 情绪从云端迁到局域网本地机,推理不出公网。

---

## 凭什么不一样

### 1. 连续人格:给角色一个持久的"自我"(核心)
这是 Skyler 真正下功夫、也最难被替代的地方。多数陪伴 chatbot 每轮重新发明自己的心情、在干嘛、今天过得怎样 —— 会漂移、自相矛盾。Skyler 把角色当成一个**有持久内在状态的存在**来设计:

- **Persona(她是谁)** —— 结构化角色卡 + 多 variant,包括身份、性格、说话风格、边界、样例和设定,不是一坨自由文本。
- **card_type(她是什么卡)** —— 社交型偏日常交流、关系和情绪表达;助手型偏任务、工具能力和行为边界。基础链路已接入,运行时策略还在继续分流。
- **持久状态(她现在如何)** —— mood / intimacy / current_thought / current_activity 维护在状态层,模型当输入读,而不是每轮临场编。
- **四层记忆 / 上下文** —— 短期窗口、对话摘要、长期语义记忆、用户画像与活动状态上下文共同进入 prompt。
- **DailyAgent Stage 1** —— 日计划生成、当前活动 ticker 和状态写回已接入;完整 FSM、多角色调度和更细的生活节奏仍在建设中。

一句话:把"追踪我是谁、在过怎样的一天"从 LLM 不可靠的临场发挥,卸到一个持久、有规则的状态与上下文层。

> *现状:结构化 Persona、card_type 基础链路、状态字段、`<state_update>`、活动时间线和 DailyAgent Stage 1 已在本地代码中接入。**正在做**:完整 FSM、多角色 DailyAgent、上下文仲裁策略、图片/文件记忆沉淀和更严格的安全边界。*

### 2. 可拆开的能力注册表
每个内建能力一行 `@register_capability` 注册;内部工具(日历 / 剪贴板 / 屏幕感知)、外部 MCP server、你自己写的 skill **完全平权**,LLM 分不出来。加新 skill 5 行代码,接任意 MCP server 一条 config。

### 3. 安全 by design(给会动手的 agent 装门)
能力注册表统一管原生能力和 MCP 工具;写 / 变更类工具进 `dangerous_tools`、调用前二次确认;桌面控制**读写分离** —— 读 UI 树安全、写动作能力已建但确认门未验,建议先手动关、验过再开。当一个 agent 能调外部工具、还能读屏 / 控桌面时,这层是必需品,不是装饰。

---

## 诚实定位

Skyler 站在两个成熟项目中间的空地:

- **[Open-LLM-VTuber](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber)** —— 打磨好、开箱即用的 VTuber 陪伴 app。想要装好就能用的成品,选它,它比 Skyler 成熟。
- **[Hermes Agent](https://github.com/NousResearch/hermes-agent)**(Nous Research)—— 服务器跑的个人 agent 平台,带自我提升 skill 循环。要纯 agent 平台,它更专。

Skyler 瞄准的是它俩中间没人占的位置:**桌面端、角色驱动、能拆到 agent 内核、所有权归你**。架构选型是顺着这块空地推出来的,不是照竞品 feature 表抄的。

**老实说 Skyler 现在还差在哪**:单人项目、仅 macOS 主力验证;只有 Mai 一个角色有完整人格;打包发布(dmg / 自动更新)还没做;长期记忆质量待真机回归。要成品体验,上面两个更稳;Skyler 的价值在那块**可塑 + 角色机制**的空地。

---

## 能干什么(概览)

> 哪些 🟢 已验 / 🟡 在做 / ⚪ 计划,细粒度见 [ROADMAP《当前能力状态》](ROADMAP.md)。这里只讲个大概。

- **双形态 UI** —— 全屏主面板 + 透明桌宠小窗;主面板负责深交互和配置,小窗负责低打扰陪伴和上下文感知。
- **交互链路** —— 文本、语音、图片、文件当轮输入;语音覆盖 VAD / ASR / LLM streaming / TTS / Live2D 表演。
- **Persona / 角色卡** —— 结构化 Persona、多 variant、card_type 基础链路;社交型 / 助手型已有基础区分,完整多角色生态仍在建设中。
- **状态与记忆** —— mood / intimacy / current_thought / current_activity;短期窗口、对话摘要、长期语义记忆、用户画像、活动上下文。
- **Activity / 主动陪伴** —— 活动时间线 + prompt 注入;主动触发雏形 + idle gate / throttle / daily cap / active conversation guard。
- **DailyAgent** —— Stage 1 已接入日计划生成、当前活动 ticker 和状态写回;完整 FSM / 多角色调度仍在建设中。
- **桌面感知** —— 只读 AX / UI Tree,读取前台 app、窗口标题、可见 UI 文本、浏览器内容等结构化上下文;截图式视觉理解仍是建设中方向。
- **Live2D** —— 渲染、待机微动、转头、眨眼呼吸、口型同步、多模型管理和 framing。
- **工具 / MCP** —— CapabilityRegistry、MCP client/server、per-tool 开关、provider 替换和 confirm gate 框架;危险工具端到端验证和凭证治理仍在加强。
- **可观测** —— 用量 / 资源 / 启动耗时监控 + 异常高亮。
- **可观测** —— 用量 / 资源 / 启动耗时监控 + 异常高亮

> 目前仅 Mai 有完整人格;第二个独立角色在搭建中(Live2D 模型就位,人格 / 音色 / 立绘后续补);其余角色空骨架。

---

## 怎么干

### 快速开始(macOS)

前置:Node 18+(推荐 22+)· Rust 1.75+ · Xcode CLT · Python 3.10+。

```bash
git clone <你的仓库地址> Skyler && cd Skyler

# 后端
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # 至少填 DASHSCOPE_API_KEY
uvicorn backend.main:app --reload   # http://127.0.0.1:8000

# 前端(另一个终端)
cd frontend && npm install && npm run tauri dev
# 首次 Rust 构建 5–15 分钟,之后很快
```

默认 LLM 是 Qwen 走 DashScope(国内不用翻墙)。换 provider 改一行 config —— 内部走 LiteLLM,DeepSeek / OpenAI / Anthropic / 本地 Ollama 都支持。

### 扩展 Skyler(四条路)

1. **加一个 skill** —— `backend/capabilities/` 下扔一个文件、装饰一个函数,重启后 LLM 就能调。
2. **接一个外部 MCP server** —— `config.yaml` 加一条,重启后自动发现 tool、反向注册成 `ext.<server>.<tool>` 能力。
3. **换 Live2D 模型** —— 资产放进 `frontend/public/live2d/<slug>/`,CharacterPanel 里绑定。仅支持 Cubism 4。
4. **换 LLM** —— 改 `config.yaml` 一个字段,LiteLLM 支持的 provider 都行。

### 架构一眼

```
用户输入(语音/文字)→ ASR(本地 whisper)
  → ChatAgent:context 装配 + LiteLLM tool calling
      ├─ 短期记忆:(用户,角色,conversation) 三级隔离
      ├─ memory tools(LLM 驱动 save/recall)
      ├─ 能力 = @register_capability → ToolRegistry(MCP 可扩展)
      └─ web search(模型内置)
  → emotion 解析 → TTS(CosyVoice/Fish/GSV)
  → 流式文字 + 按句音频(按发起 conversation 投递)
```

底座三件:**能力注册表**(装饰器 → 单例,自动导出 schema)· **双向 MCP**(client + server)· **Persona 级状态**(`character_states` + `<state_update>` 标签协议)。每块为什么这样长,见 [DESIGN_LITE.md](DESIGN_LITE.md)(设计真源)。

---

## 路线图

完整见 [ROADMAP.md](ROADMAP.md)。一句话:

- **Now** —— demo 视频 + 文档刷新 + 本地能力口径收口。
- **Next** —— DailyAgent 完整 FSM / 多角色调度、上下文仲裁策略增强、图片/文件记忆沉淀、主动视觉感知、桌面写操作确认门端到端验证。
- **Later** —— AX + 视觉模型融合、多角色协作、长期自治、Live2D AI director、打包发布 / dmg / 自动更新。

---

## License

代码当前 **All rights reserved**(无 LICENSE 文件),公开后切宽松协议(MIT / Apache 2.0)。

**Live2D 模型另算** —— 开发期附带若干第三方角色模型:官方样本 Hiyori(Live2D Free Material License)+ 数套**非商业同人模型**(含原神 / 星铁等角色,遵循各自 IP 的非商业同人使用条款)。这些资产**不在** Skyler 项目协议覆盖范围内,**仅限非商业使用**;商用需自行向各 IP 方申请授权。用户自己添加的任何资产,授权责任在用户。

---

## 往深里看

- [DESIGN_LITE.md](DESIGN_LITE.md) —— 设计真源,锚到代码
- [ROADMAP.md](ROADMAP.md) —— 当前能力状态 + 近期计划
- [EVOLUTION.md](docs/EVOLUTION.md) —— 版本 × 功能演进矩阵
- [docs/research/persona-schema-comparison.md](docs/research/persona-schema-comparison.md) —— 角色卡 schema 调研(vs SillyTavern)
- [docs/PM-CC-PROTOCOL.md](docs/PM-CC-PROTOCOL.md) —— 我和 Claude Code 怎么分工
