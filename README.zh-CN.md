# 🌸 Skyler

> 一个本地优先的 AI 桌面伴侣 —— 外面是 Galgame 风格看板娘，里面是全栈生活&工具型 agent。

![Python](https://img.shields.io/badge/Python-3.10+-blue) ![FastAPI](https://img.shields.io/badge/FastAPI-async-green) ![Tauri](https://img.shields.io/badge/Tauri-2.0-orange) ![React](https://img.shields.io/badge/React-18-61DAFB) ![Platform](https://img.shields.io/badge/platform-macOS-lightgrey) ![Status](https://img.shields.io/badge/status-v3--WIP-yellow)

> **状态（2026-05）**：v3 ✅ + v3.5 chunk 5 ✅ + chunk 7 ✅ + chunk 6 (a/b/c) ✅ 全部完成。媒体接入收尾：chunk 6b mpv 子进程 + Unix socket JSON IPC 自解码（6 个 ``netease.local_*`` capability，NCM 自动播放真闭环——通过 mpv 0.34+ 原生 macOS NowPlaying 注册，不需要 PyObjC 桥）；chunk 6c 小红书 URL 被动解析（单 ``xhs.parse_url``，模块层不暴露 search/recommend/fetch_homepage 等主动方法——红线锁在代码层而非仅 policy）。51+ capabilities、6 proactive triggers、950+ 测试 / 0 回归、5 套抽象——CapabilityRegistry / ProactiveTrigger ABC / 双向 MCP / SAFE path util / mpv-IPC wrapper。接下来：chunk 8 v4 屏幕感知（VLM 抽象 + Tauri 截图 + 隐私黑名单）。
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

### 🌸 角色存在感（v3-E1 主线完成，2026-05）
- 🎭 **Live2D 看板娘**（Hiyori 样本模型，Cubism 4）—— 渲染 + idle / focus / breath，Galgame 满铺布局
- 👄 **口型同步** —— Web Audio AnalyserNode → `ParamMouthOpenY`，跨多段 TTS 共享 AudioContext
- 👆 **触摸响应** —— 点击看板娘 → Tap motion + AI 主动回复（special turn 注入）
- 🎬 **LLM 驱动动作** —— `<motion>X</motion>` 标签驱动 16 个中文动作词 → Hiyori 4 个 `Flick*` motion group（语义实测对齐：放松甩手 / 害羞收敛 / 加油应援 / 撒娇俏皮）
- 😊 **Emotion 数据流** —— `<emotion>X</emotion>` 解析 → WS push → store；视觉绑定 deferred 到 v3-E3（Hiyori 没有 `.exp3.json`）
- 🧠 **内心独白** —— `<thinking>X</thinking>` 让 LLM 思考但 TTS 不读、不持久化
- v2.7 基线：emotion 标签驱动 TTS 多音色；未绑 Live2D 时回退静态角色图

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

## Live2D 资产管理

Skyler 默认带 Live2D 官方免费样品模型 **Hiyori**。想加新角色按这四步走：

1. **资产放进 `frontend/public/live2d/<slug>/`** —— slug 用小写英文（例如
   `yae-miko`、`momo-v2`），后面在 CharacterPanel 里 `live2d_model` 字段
   填的就是这个名字。
2. **目录里必须有一个 `*.model3.json` 入口文件**，还要有 `*.moc3`、
   `textures/`，至少一个 motion。完整 checklist 看
   [`frontend/public/live2d/README.md`](frontend/public/live2d/README.md)。
3. **接通前先验 moc3 版本**：
   ```bash
   python -m tools.check_moc3_version frontend/public/live2d/<slug>/
   ```
   pixi-live2d-display 不支持 Cubism 5，version ≥ 5 或者塞进来一个 Cubism 2
   的 `.moc` 都会让脚本退出码非零。
4. **CharacterPanel 里绑定** —— 打开角色编辑器，把 `live2d_model` 字段填
   成你的 slug，重进对话就生效。

**IP / license 隔离** —— `.gitignore` 默认 ignore `frontend/public/live2d/`
下除 `hiyori/` 以外所有子目录。你扔进去的第三方 / 委托资产不会被 track，
更不会被 push 出去。这是有意的：Skyler 项目的 license 没法覆盖不属于你的
资产。自制 / 已清理 license 的模型想入库时，在 `.gitignore` 末尾追加
`!frontend/public/live2d/<slug>/`。

**免责声明** —— Skyler 自己的代码是 MIT，但**不为用户添加的任何 Live2D
资产 license 背书**。资产怎么来的、有没有授权、能不能传播，完全是用户
自己的责任。

### 实操示例：从 BCSZ1.1 dump 接入八重神子

具体例子 —— Cubism 4 的八重神子资产在 `<某路径>/BCSZ1.1/`。Skyler 的
character id=2 已经叫「八重神子」，`motion_map_json` / `hit_area_map_json`
也已经由 `v3_e2_yae_maps` 迁移填好。让她渲染只差资产入位：

```bash
# 选项 A：复制资产到 slug 目录
cp -r "<某路径>/BCSZ1.1" frontend/public/live2d/yae

# 选项 B：软链接（省盘 + 改源更方便）
ln -s "<某路径>/BCSZ1.1" frontend/public/live2d/yae
```

任一种方式，`frontend/public/live2d/yae/` 都被 .gitignore 排除 —— 资产
留本地，进 git 的只有"character id=2 指向 slug `yae`"这条数据迁移。验证
之后刷新 UI：

```bash
python -m tools.check_moc3_version frontend/public/live2d/yae/
# 期望：[OK] version=3 (Cubism SDK 4.0)
```

打开 CharacterPanel，切到八重神子，立绘换成 BCSZ1.1。点击模型 Skyler
会播 `Start` motion（八重的初见配音），而不是 Hiyori 的 `Tap` 随机一条
—— 这就是 per-character `motion_map_json` 生效的视觉信号。

> **注意：模型 motion3.json 中引用的配音 wav 默认禁用。** 部分模型（八重
> BCSZ1.1 含 6 段配音）会在 motion 自带 wav；Skyler 所有语音输出统一走
> LLM + TTS pipeline，让 motion 自动播 wav 会跟 TTS 重叠。当前在 SDK
> config 层全局关闭。未来 per-character 开关已在 ROADMAP backlog —— 鼠标
> 点击触发的 motion 可以播原声 wav 保留演出价值，LLM 标签触发的不播让
> TTS 独占。

---

## 路线图

完整路线图见 [**ROADMAP.md**](ROADMAP.md)。

**TL;DR —— 接下来要做的事：**

- **v3 收尾（第 1 梯队，1–3 周）**：
  - ✅ **v3-E1 完成**（8 commit + Step Z cleanup）：Hiyori Live2D —— 渲染、idle、触摸 Tap、口型同步、emotion 数据流、LLM 驱动 motion
  - ✅ **v3-E2 完成**（9 commit）：runtime 抽象层 + per-character `*_map_json` + 资产扫描 API + 下拉 + 八重神子 BCSZ1.1 接入 + emotion 视觉绑定路径接通 + Momo persona 还原
  - **v3-E3**：纯运营任务 —— 找一个有 `.exp3.json` 的模型，填该角色 `emotion_map_json`，美术调参
  - **v3-F'**：主动对话 + 时间感知（饭点 / 睡前 / 长时无互动触发）
  - ✅ **v3-G' 完成**（5 commit + patch）：CharacterPanel 两级下拉 voice picker（provider → voice）、6 个 cosyvoice 音色目录、emotion 通过 SDK `instruction` 字段在 instruct-supported 音色（longanhuan）上真生效。chunk 1a 的 SSML 方案事后证明是错的——DashScope SSML 标签没 emotion 属性——已撤回，回到 v3-D 起就有的 instruct 自然语言指令路径作为唯一通道。
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
| v3-D：emotion 系统 | ✅ 完成（前端数据流接入 v3-E1 Step 5；视觉绑定 v3-E3）|
| v3-E1：Live2D 接入（用 Hiyori 走通） | ✅ 完成（8 commit + Step Z cleanup，2026-05）|
| v3-E2：多模型 Live2D（runtime 抽象层 + per-character maps + 八重 BCSZ1.1）| ✅ 完成（9 commit，2026-05-06）|
| v3-E3：emotion 视觉绑定 | 🚧 代码路径已接通，等有 `.exp3.json` 的模型 |
| v3-F：语音体验飞跃（打断 + 并发 + 预处理 + 内心独白） | ✅ 完成 |
| v3-F'：主动对话 + 时间感知 | 📋 计划中 |
| v3-G：生活 & 工具层（剪贴板 / 简报 / cron / 成长系统） | 📋 计划中 |
| v3-G'：TTS UI + cosyvoice instruct emotion | ✅ 完成（5 commit + patch，2026-05-06）—— SSML 路径撤回，instruct 路径正典 |
| v3.5 chunk 5：视觉跃迁包（角色背景层 + Tauri 启动 splash video） | ✅ 完成（2026-05-11，4 commit）|
| v3.5 chunk 6a：B 站接入（11 capability + AI 字幕总结） | ✅ 完成（2026-05-11，4 commit）—— ``bilibili-api-python>=17.4`` 社区 fork 包 ``backend/integrations/bilibili.py`` (11 方法 + 三档健康检查 + 风控 code 映射) + ``backend/capabilities/bilibili.py`` (11 个 ``@register_capability``)；6 无 cookie + 5 cookie capability；``get_subtitles`` ⭐ 杀手 use case（B 站 2024-2025 风控收紧字幕 API，spec pivot 移到 cookie 组）；红线：投币 / 三连 / 评论 / 弹幕 / 下载；104 新测试 / 0 回归（704/704 across 22 suites）；详见 ``docs/bilibili-setup.md`` |
| v3.5 chunk 6b：网易云 mpv 自解码（6 个 ``local_*`` capability） | ✅ 完成（2026-05-11，5 commit）—— ``NeteaseClient.get_song_url`` 补 weapi POST + ``backend/integrations/mpv_player.py`` subprocess + Unix socket JSON IPC（不走 python-mpv ctypes，避免 libmpv 共享库部署）+ 6 个 ``netease.local_*``；MediaRemote spec degrade 升级——mpv 0.34+ 原生 macOS NowPlaying 注册（``--media-keys=yes``），不需 PyObjC 桥（节省 ~200 行 + 无 entitlement 需求）；VIP 试听透传 ``is_trial=True``；与 chunk 1 NCM URL Scheme 并存（``local_`` 前缀避免 namespace 冲突）；56 新测试；详见 ``docs/netease-playback-setup.md`` |
| v3.5 chunk 6c：小红书 URL 被动解析（红线锁在代码层） | ✅ 完成（2026-05-11，5 commit）—— 单一 ``xhs.parse_url`` capability；``backend/integrations/xiaohongshu.py`` **不暴露** search/recommend/fetch_homepage/list_followings 等任何主动方法（红线在模块层 enforce，不只是 policy）；域名白名单 + follow_redirects + 浏览器 UA 伪装；数据源 ``__INITIAL_STATE__`` → og:meta → parse_failed；反爬识别 412/418 → ``blocked_by_antibot``；system prompt 引导 LLM 主动搜索类问题如实告诉用户无能力**不要瞎编**；52 新测试（含 4 条红线 enforcement 断言）；详见 ``docs/xiaohongshu-setup.md`` |
| v3.5 chunk 7：Skill 集成 demo（姿态 A docx capability + 姿态 B Notion MCP server） | ✅ 完成（2026-05-11，5 commit）—— 姿态 A docx 3 capability + ``backend/utils/safe_path.py`` 集中防御；姿态 B 扩展 chunk 1.5 ``backend/mcp/client.py``（``enable``/``disable``/DB env 注入）+ ``mcp_credentials`` / ``mcp_client_state`` 双表 + ``ExtensionsSection.tsx`` UI + ``@notionhq/notion-mcp-server`` 官方包；65 新测试 / 0 回归（556/556 across 16 suites）。新加 skill 参 ``docs/skills-extension-guide.md`` |
| v3.5 chunk 8：v4 屏幕感知（VLM 抽象 + Tauri 截图 + 像素差预过滤 + 隐私黑名单） | 📋 计划中 |
| v4：屏幕感知 | 📋 计划中 |
| v5-D / T1 / T2：autodl + GPT-SoVITS + 自定义 voice 训练 | 📋 长期 |
| v6+：多设备 / 云端部署 | 📋 长期 |

---

## 许可证

目前 **All rights reserved**（无 LICENSE 文件）。仓库公开后会切换到宽松许可证（MIT 或 Apache 2.0）—— 注意：之后捆绑的 Live2D 模型有 Live2D Inc. 自己的许可证，**不在** Skyler 项目许可证覆盖范围内。

### Live2D 模型许可

Skyler 当前开发期使用 Live2D 官方样本模型 **Hiyori**（位于 `frontend/public/live2d/hiyori/`），由 illustrator Kani Biimu 创作。该模型遵循 **Live2D Free Material License Agreement**，开发/学习/小规模商用 OK；中大型企业商用需向 Live2D Inc. 申请书面授权。

v3-E2 阶段会替换为自有/购买的模型，届时 Skyler 项目本身的 license 不覆盖该模型，模型遵循各自原始 license。

---

## 贡献

私有开发期间不接受外部贡献。等公开后见。
