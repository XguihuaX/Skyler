# 🌸 Skyler

> 一个本地优先的 AI 桌面伴侣 —— 外面是 Galgame 风格看板娘，里面是全栈生活&工具型 agent。

![Python](https://img.shields.io/badge/Python-3.10+-blue) ![FastAPI](https://img.shields.io/badge/FastAPI-async-green) ![Tauri](https://img.shields.io/badge/Tauri-2.0-orange) ![React](https://img.shields.io/badge/React-18-61DAFB) ![Platform](https://img.shields.io/badge/platform-macOS-lightgrey) ![Status](https://img.shields.io/badge/status-v3--WIP-yellow)

> **状态（2026-05）**：v2.7 后端 + UI 完整 · v3-A/B/C/D 进行中（约 v3 整体 60%）· 接下来做 Live2D、语音打断、屏幕感知、生活工具层。
>
> *项目原名 MomoOS，2026-05 重命名为 Skyler。*

🌐 **Languages**: [English](README.md) · **简体中文**

---

## Skyler 是什么？

Skyler 是一个**本地优先的 AI 伴侣**，以透明、置顶的看板娘形式住在你的 Mac 桌面。她不只是回应你 —— 她记得你分享的一切，理解你的习惯，需要的时候主动找你。

**双重身份**：

- 🎭 **Galgame 风格情感伴侣外观** —— Live2D 看板娘、persona 驱动对话、emotion 驱动 TTS 多音色、角色状态面板
- 🛠️ **生活&工具型 agent 内核** —— 长期记忆、MCP 工具生态、自然语言定时任务、屏幕感知、剪贴板助手、每日简报

两种交互模式，一个伴侣：
- **Widget 模式** —— 透明、置顶的浮动看板娘，快速语音交互
- **Panel 模式** —— 完整窗口，包含聊天历史、记忆查看器、角色管理、设置

灵感大量借鉴自 [Open-LLM-VTuber](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber)（看板娘 UX）和 [Hermes Agent](https://github.com/NousResearch/hermes-agent)（skill 累积型工具 agent）。详见 [§借鉴来源](#借鉴来源)。

---

## 特性

### 🎙 输入与输出
- **语音输入**两种模式：
  - **手动模式** —— 点击开始录音，再点击发送
  - **VAD 模式** —— 点击激活后，Web Audio API 自动检测语音；1.5 秒静音自动发送；60 秒空闲回 sleep
- **ASR 实时回显** —— 通过 `asr_result` WebSocket 消息把识别结果即时显示在输入框上方，并写入聊天历史
- **流式输出** —— 文字和音频按句到达
- **TTS** —— CosyVoice（DashScope，默认）→ Edge-TTS 后备；每角色独立 `voice_model` 配置；SoVITS 计划中
- **AI 说话时自动静音麦克风**（防反馈循环）

### 🧠 记忆与人格
- **短期记忆** —— 最近 20 轮，每次都注入
- **长期记忆** —— SQLite + sentence-transformers 向量检索，每轮 Top-5 相关记忆，按 character 隔离
- **4 个记忆 tool**（LiteLLM tool calling）—— `save_memory` / `delete_memory` / `list_memories` / `compress_memories`，LLM 自主决定记什么
- **两层用户画像** —— 记忆条目（事实）+ 自由文本 `profile_summary`，每 50 轮或删对话时增量重写
- **记忆查看抽屉** —— 浏览/添加/编辑/删除，类型彩色标签（fact / instruction / emotion / activity / daily）
- **记忆开关** —— 长期记忆、画像、网络搜索都能在 Settings 里切

### 🤖 多 agent 智能（v3-C 简化版）
- **ChatAgent 直走流程** —— LiteLLM tool calling 单轮搞定记忆 + 内置工具，PlannerAgent 在 v3-C 退出主流程
- **真实 MCP 工具集成** —— 可扩展的 ToolRegistry
- **LiteLLM 统一 LLM** —— DeepSeek / Qwen / OpenAI / Claude（config 可切换）
- **网络搜索** —— 模型原生搜索（Qwen Max / DeepSeek），通过 `enable_search` 开关

### 🎭 ChatGPT 模式多对话 + 多角色
- **每角色隔离** —— 每个角色独立 conversations + memory；`profile_summary` 跨角色共享（一份对你的整体印象）
- **对话列表** —— 可折叠侧栏，对话改名/删除；删对话触发 `profile_summary` 重算
- **角色切换器** —— TopBar 下拉，CharacterManagerDrawer 完整 CRUD（Momo / id=1 是系统默认，不能删）
- **每角色独立音色** —— `character.voice_model` JSON：`{provider, voice, instruct_supported}`；空就回退全局默认

### 🎨 UI：8 套主题系统（v3-A）
Settings → UI 风格 可切换：

| 主题 | 风格 |
|---|---|
| 🌫️ 莫兰迪 | 暖色奶油极简 |
| 🌆 暮色 *(默认)* | 紫色暮光梦幻 |
| 🌊 玻璃 | 玻璃拟态清冷 |
| 🌸 水彩 | pixiv 粉色二次元 |
| 🌌 极光 | 深海青绿 |
| 🌷 樱花 | 樱花夜 |
| 🌃 赛博 | 赛博猩红 |
| 💜 薰衣草 | 雾色薰衣草 |

所有组件用 `var(--color-*)` 引自 `styles/themes.css`（无硬编码 Tailwind 色板）。`localStorage` 持久化。`data-theme` 在 mount 时应用，防首屏闪烁。

`lucide-react` 图标库覆盖全部 11 个组件（无 Unicode emoji 残留）。

### 🔔 主动陪伴
- **闹钟与提醒系统** —— 自然语言日程，触发时角色风格播报
- **Todo 管理** —— agent 创建和用户创建的任务都存 SQLite
- **主动推送** —— 后端通过持久 WebSocket 随时主动发送（`notify` / `alarm` / 未来的 `screen_comment`）

### 🌸 角色存在感
- v2.7：静态角色图 + Galgame 布局（角色满铺 + 浮动对话气泡 + 历史抽屉）
- v3 进行中：emotion 标签系统（`<emotion>...</emotion>`）从 LLM 解析，驱动 TTS 多音色
- v3 接下来：Live2D Cubism 5 看板娘 + idle 动画、表情同步、口型同步、触摸响应

### 🪟 界面
- **双 UI 模式** —— 透明浮动 widget + 完整面板（Tauri 2）
- **Widget ↔ Panel 切换** —— 单窗口动态 resize（Tauri JS API），跨启动持久化
- **设置面板** —— 4 区块（记忆 / 基础信息 / 角色 / UI 风格）
- **Widget 模式鼠标点击穿透**

### 👁 屏幕感知 *(v4，规划中)*
- **主动模式** —— 语音命令或热键触发截图，VLM 分析
- **被动模式** —— 定时截图 + 像素差预过滤，画面真有变化时才送 VLM，主动评论通过 `screen_comment` push
- **隐私黑名单** —— 忽略指定的应用/窗口
- VLM 走云端（GPT-4o / Qwen-VL / Claude）—— 不占本地 GPU

---

## 架构

```
用户输入（语音/文字）
  ├─ [VAD 模式]  Web Audio API 检测语音 → MediaRecorder
  │              静音 > 1.5s → 停止 → 发送
  ├─ [手动模式]  用户点击 → MediaRecorder 起停 → 发送
  └─ [文字]      输入并发送

  → ASR        faster-whisper（后端）→ asr_result 推到前端
  → ChatAgent  context 组装 + LiteLLM tool calling
                ├─ memory tools：save / delete / list / compress（LLM 驱动）
                ├─ 内置工具：ToolRegistry（MCP 可扩展）
                └─ 网络搜索：模型原生（Qwen Max / DeepSeek）
  → emotion    第一句解析 <emotion>X</emotion> → 锁定整轮情感
  → TTS        get_tts_engine(voice_model) → CosyVoice / Edge / SoVITS
  → 输出：     流式文字 + 分句音频 + asr_result 回显

VAD 状态机：
  sleep ─ 点击 ─→ active ─ 语音 ─→ recording ─ 静音 1.5s ─→ 发送 → active
  active ─ 60s 空闲 ─→ sleep

后端 → 前端（主动）：
  闹钟 / 任务完成 / 事件 / 屏幕评论
    → ConnectionManager.push() → WebSocket → 前端 toast/notify
```

---

## 技术栈

| 层 | 技术 |
|-------|-----------|
| 前端 | React 18 + Vite + TypeScript + Zustand + Tailwind CSS v3.4 |
| 图标 | lucide-react |
| 主题 | CSS variables（8 套主题在 `styles/themes.css`）|
| 桌面壳 | Tauri 2（透明窗口、置顶、点击穿透、自定义 drag region）|
| 后端 | FastAPI + WebSocket（async streaming）+ SQLAlchemy async（aiosqlite）|
| LLM | LiteLLM —— DashScope（Qwen）/ DeepSeek / OpenAI / Claude（config 可切换）|
| TTS | CosyVoice v3-flash（默认）/ Edge-TTS（后备）/ SoVITS（占位）|
| ASR | faster-whisper（本地，CPU/GPU）|
| 记忆 | SQLite + sentence-transformers（本地向量检索，无 GPU 需求）|
| VLM *(v4)* | OpenAI / Qwen-VL / Claude vision API（云端）|
| 工具协议 | MCP（Model Context Protocol）|

**跨平台说明**：当前仅 macOS。Windows 支持推迟到 v6+ —— 见 [DESIGN.md §二十 跨平台策略](DESIGN.md) 解释为什么这件事没看起来那么简单。

---

## 快速开始

### 前置要求（macOS）

| 工具 | 最低版本 | 安装 |
|---|---|---|
| Node.js | 18+（推荐 22+）| `brew install node` |
| Rust 工具链 | 1.75+ | `curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \| sh` |
| Xcode Command Line Tools | 最新 | `xcode-select --install` |
| Python | 3.10+ | `brew install python@3.10` |

### 安装

```bash
git clone <你的仓库地址> Skyler
cd Skyler

# ── 后端 ──────────────────────────────────────────────
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# 编辑 .env，至少：
#   DASHSCOPE_API_KEY=sk-xxx
#   DATABASE_URL=sqlite+aiosqlite:///./skyler.db

uvicorn backend.main:app --reload
# 后端跑在 http://127.0.0.1:8000

# ── 前端（另一个终端）──────────────────────────────────
cd frontend
npm install
npm run tauri dev
# 首次 Rust 构建 5–15 分钟，之后启动很快
```

桌面会出现一个透明浮动 Widget。点击 ⚙ 打开完整 Panel。

---

## 路线图

完整路线图见 [**ROADMAP.md**](ROADMAP.md)。

**TL;DR —— 接下来要做的事：**

- **v3 收尾（第 1 梯队，1–3 周）**：
  - **v3-E1**：用 Live2D 官方样本 **Hiyori** 走通整个 Live2D 集成（验证 SDK + emotion + 触摸 + 口型同步管道）
  - **v3-E2**：换上目标 Cubism 模型（资产替换，不动代码）
  - **v3-F**：语音打断、TTS 多段并发、TTS 预处理器（剥离 `*动作*` 等不读出）、`<thinking>` 内心独白
  - **v3-G'**：TTS UI 升级 —— 裸 JSON 文本框换成 per-character provider + voice 两级下拉（**只显示真实可用选项**）
- **v3-G + v4（第 2 梯队，1–2 个月）**：剪贴板助手、每日简报、自然语言 cron、角色状态面板 + 成长系统；屏幕感知（主动 + 被动 + VLM）；AI 用自己的浏览器
- **v5（第 3 梯队，长期）**：
  - **v5-D**：autodl 部署 + 子 agent 隔离
  - **v5-T1**：GPT-SoVITS 后端接通（`SoVITSProvider` 真实现，多情感参考音频路由）
  - **v5-T2**：训练自定义 voice（CosyVoice fine-tune + GPT-SoVITS 角色专属模型）
- **v6+**：多设备访问（Windows 客户端）、Hermes 风格 skill 累积

---

## 借鉴来源

Skyler 站在两个项目的肩膀上：

### [Open-LLM-VTuber](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber)
看板娘 / 伴侣 UX 参考。借鉴的概念：
- 语音打断（用户说话立即停止生成 token）
- TTS 多段并发合成 + 优先播首句
- TTS 预处理器（剥离 `*动作*` / `(注释)` 不读出来）
- 视觉能力（相机 + 屏幕共享 + AI 自己控制浏览器）
- AI 主动说话 + 可见的内心独白（`thinking` 标签）
- Live2D 触摸响应
- motionMap（说话时同步动作）
- MCP 协议接入
- Letta 长期记忆方案 *（考虑过，未采纳 —— 现有 SQLite + 向量已经够用）*
- 多设备访问（推迟 —— 见 §跨平台策略）
- *未采纳：群聊、Bilibili 弹幕直播客户端（与单角色 Galgame 定位冲突）*

### [Hermes Agent](https://github.com/NousResearch/hermes-agent)（Nous Research 出品）
生活 & 工具型 agent 参考。借鉴的概念：
- 自我提升 skill 循环（skills 从经验累积，使用中改进）
- 自然语言 cron 调度（扩展 Skyler 现有 alarm 系统为通用任务调度）
- 子 agent 隔离（长任务跑在独立 context，不阻塞主对话）
- 多执行 backend（local / Docker / SSH / Modal 风格 serverless）—— autodl 部署相关
- Persona 编辑器（`SOUL.md` 风格）—— 已部分通过 `characters.persona` 实现
- *未采纳：messaging gateway（Telegram/Discord 等）—— Skyler 是桌面应用而非远程 agent*

---

## 项目状态

| 组件 | 状态 |
|---|---|
| 后端（FastAPI + agents + memory + TTS + ASR）| ✅ v2.7 完整 |
| 前端（Tauri + React + 8 套主题 + Galgame UI）| ✅ v2.7 完整 |
| v3-A：8 套主题 + lucide-react | ✅ 完成 |
| v3-B：`character.voice_model` + CosyVoice | ✅ 完成 |
| v3-C：PlannerAgent 简化 | ✅ 完成 |
| v3-D：emotion 系统（后端）| ✅ 完成（前端等 Live2D）|
| v3-E1：Live2D 接入（用 Hiyori 走通） | 📋 下一步要做 |
| v3-E2：换目标模型 | 📋 E1 之后 |
| v3-F：语音体验飞跃（打断 + 并发 + 预处理 + 内心独白） | 📋 计划中 |
| v3-G：生活 & 工具层（剪贴板 / 简报 / cron / 成长系统） | 📋 计划中 |
| v3-G'：TTS 配置 UI 升级（per-character 两级下拉） | 📋 计划中 |
| v4：屏幕感知 | 📋 计划中 |
| v5-D / T1 / T2：autodl + GPT-SoVITS + 自定义 voice 训练 | 📋 长期 |
| v6+：多设备 / 云端部署 | 📋 长期 |

---

## 许可证

目前 **All rights reserved**（无 LICENSE 文件）。仓库公开后会切换到宽松许可证（MIT 或 Apache 2.0）—— 注意：之后捆绑的 Live2D 模型有 Live2D Inc. 自己的许可证，**不在** Skyler 项目许可证覆盖范围内。

---

## 贡献

私有开发期间不接受外部贡献。等公开后见。
