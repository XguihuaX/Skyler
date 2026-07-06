# Skyler

连续人格驱动的 Live2D 桌面 AI 陪伴角色系统。

Skyler 不是给问答 AI 套一个角色外观。这个项目主要在探索一件事：桌面上的 Live2D 角色，能不能把 Persona、运行时状态、近期活动、语音表达和工具能力放进同一套系统里，而不是每轮对话都从零开始。

语言： [English](README.md) / **简体中文**

## Demo

> 完整 demo 视频会在最终渲染后补到这里。

后续建议放：

```md
[![Skyler Demo](docs/assets/demo-placeholder.png)](https://github.com/XguihuaX/Skyler/releases)
```

## 目前已经做到什么

- **双形态桌面 UI**：全屏主面板 + 透明桌宠小窗。
- **Live2D 运行层**：模型加载、渲染、framing、待机动作、口型同步和多模型管理。
- **交互输入**：文本、语音、图片和文件都可以作为当轮输入进入模型。
- **语音链路**：Silero VAD、ASR、LLM streaming、TTS 和 Live2D 表达钩子。情绪 TTS 已接入；Live2D motion 规划还没做完。
- **角色系统**：结构化 Persona、active variant、`card_type`、社交卡 / 助手卡元数据和 `CharacterState`。
- **状态与记忆上下文**：mood、intimacy、current_thought、current_activity、短期窗口、对话摘要、长期语义记忆、用户画像和活动上下文。
- **活动上下文**：前台 app、浏览器标题 / URL、文档路径和 activity session 会写入本地，并可以整理后注入 prompt。
- **桌面感知**：当前按需读取前台 app 的只读 AX / UI Tree 摘要，不默认持续读取所有窗口。
- **能力扩展层**：`CapabilityRegistry`、内建 capability、MCP client / server、API provider 配置、per-tool 开关和 confirm gate 框架。

## 正在做

- DailyAgent Stage 1 之后的完整形态。Stage 1 已经接了日计划生成、当前活动 ticker 和状态写回；完整 FSM 和多角色调度还没完成。
- 社交卡和助手卡的运行时策略分流。
- 上下文仲裁：当 persona、记忆、活动、屏幕上下文和工具结果互相冲突时，决定哪些证据优先。
- Window Roster / Watchlist / 目标 PID 按需深读，用来完善分层桌面感知。
- 危险工具和写操作确认门的端到端验证。
- 图片 / 文件输入的长期持久化和记忆沉淀。
- 打包发布、release 流程和自动更新。

## 还没有完成

- 持续 VLM 屏幕监控。
- 完整多角色协作。
- 长期自治。
- Live2D AI director / 动作库规划。
- Anime 资产生成或 ComfyUI 工作流接入。

## local-first 的边界

对话记录、角色状态、记忆和活动数据保存在本地 SQLite 或本地文件里。LLM、ASR、TTS provider 可以配置成云端或自托管服务。Skyler 是 local-first，但目前不能说成完全离线应用。

## 快速开始

当前主要在 macOS Apple Silicon 上验证。

前置依赖：

- Node 18+ / npm
- Rust toolchain 和 Xcode Command Line Tools
- Python 3.10+

```bash
git clone <repo-url> Skyler
cd Skyler

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env

uvicorn backend.main:app --reload
```

另开一个终端：

```bash
cd frontend
npm install
npm run tauri dev
```

provider key、本地模型地址和私有配置都应放在本地配置文件里，不要提交。

## 文档

- [ROADMAP.md](ROADMAP.md)：当前状态、进行中工作和后续方向。
- [DESIGN_LITE.md](DESIGN_LITE.md)：精简技术设计和代码口径。
- [docs/demo-positioning.md](docs/demo-positioning.md)：demo 讲法和能力边界。
- [docs/EVOLUTION.md](docs/EVOLUTION.md)：较早的版本 / 功能演进记录。

## 当前限制

这是一个单人项目。主要验证环境是 macOS Apple Silicon。有些能力已经接了基础链路，但还没到产品级稳定，例如 DailyAgent、危险工具确认、主动感知和打包发布。

## License

项目还没有确定开源协议。在正式添加 LICENSE 文件前，请按 all rights reserved 处理。

Live2D 模型和角色素材不等于代码协议的一部分。复用或分发前需要分别确认每个模型 / 素材自己的授权。
