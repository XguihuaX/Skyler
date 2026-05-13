# 🌸 Skyler

> 一个可塑型 AI 角色容器 —— 自带你的 LLM、自带你的 Live2D 模型、自带你的 MCP 工具。Agent 内核给你打好地基,剩下的拼成什么样,自己塑造。

![Python](https://img.shields.io/badge/Python-3.10+-blue) ![FastAPI](https://img.shields.io/badge/FastAPI-async-green) ![Tauri](https://img.shields.io/badge/Tauri-2.0-orange) ![React](https://img.shields.io/badge/React-18-61DAFB) ![Platform](https://img.shields.io/badge/platform-macOS-lightgrey) ![Status](https://img.shields.io/badge/v4--alpha-✅%20shipped-success)

> **最新**:v4-alpha (2026 年 5 月) —— Activity Timeline + tool 调用过渡 UX + Live2D 透着可见的历史抽屉。完整路线见 [ROADMAP](ROADMAP.md)。
>
> *项目原名 MomoOS,2026-05 改名 Skyler。*

🌐 **Languages**: [English](README.md) · **简体中文**

---

## Skyler 是什么?

Skyler 是一个带 Live2D 角色界面的桌面 AI agent。跟那种打包好的 VTuber app 不一样,Skyler 是个**给你拿来改的容器** —— 内核(MOMOOS)、能力注册表、主动陪伴层 —— 这些是底座;但每一个 capability、每一个外部集成、每一个角色资产,都是你能拆下来换的。

你要是动过这个念头 —— "我能不能有一个真正属于我自己的 AI 陪伴,本地跑、用我喜欢的角色、调我自己注册的工具" —— Skyler 就是给你这种人写的。

角色不是装饰。Persona 级状态(心情 / 最近的想法 / 跟你的亲密度)跨 session 持久化;agent 能调你注册的任何 tool 和你接的任何 MCP server;立绘会响应它说的话和你在屏幕上做的事。这些层没有一个是锁死的。

---

## 这是给谁的?

Skyler 是给**有动手能力的二次元半技术宅**写的:

- 你能跑命令行,也能写一点 Python
- 你在意数据所有权(本地跑 SQLite、本地跑 sentence-transformers,没有云依赖)
- 你喜欢"角色驱动的 AI"这个想法,不喜欢冷冰冰的 chatbot
- 你宁可拿到一个能扩展的框架,也不想要一个磨得很光滑但改不动的 app

要是你想要开箱即用的 VTuber 体验,去看 [Open-LLM-VTuber](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber)。
要是你想要服务器跑的个人 agent 平台,去看 [Hermes Agent](https://github.com/NousResearch/hermes-agent)。

**Skyler 站在它俩之间** —— 一个桌面、角色化、真正属于你自己的 agent。

---

## Skyler 凭什么不一样

### 1. 能力注册表是可拆开的

每个内建 capability 都是一行 `@register_capability` 装饰器注册的。内部 tool(日历 / 剪贴板 / 屏幕感知)、外部 MCP server(filesystem / brave-search / Notion)、你自己写的 skill,**完全是平权的** —— LLM agent 分不出来,也不应该分得出来。

加一个新 skill 5 行代码就够。接一个外部 MCP server 一条 config 就行。除了装饰器和 JSON schema,没有别的 plugin API 要学。

### 2. 双向 MCP

Skyler 既是 MCP **client**(消费 filesystem / brave-search / Notion 等任何 MCP server),也是 MCP **server**(把自己的能力注册表、角色状态、记忆暴露给 Claude Desktop / Cursor / Claude Code 等任何 MCP client)。

你的 AI 角色变成 MCP 生态里的一个节点,而不是一座孤岛。

### 3. Persona 级状态机

大多数 agent 框架只跟踪任务状态。Skyler 还跟踪**角色状态** —— LLM 驱动地累积心情、注意力、当前在做什么、最近的想法、跟你的亲密度。状态不是写死在 prompt 里的,它会随交互演化。

这就是 Momo 感觉像个具体的人而不是通用工具的原因。也是我们长期路线图里最重要那一条的基础:**persona-level learning**(角色跟你一起成长,不只是变得更能干)。

---

## 对比

|  | Skyler | Open-LLM-VTuber | Hermes Agent |
|---|---|---|---|
| 形态 | 桌面 + Live2D | 桌面 + Live2D | CLI + messaging gateway |
| 可改造性 | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐⭐⭐ |
| 角色系统 | ⭐⭐⭐⭐ persona + 状态机 | ⭐⭐⭐ Live2D + persona | ❌ |
| 主动陪伴 | ⭐⭐⭐⭐ broadcast + trigger pack | ❌ 只被动 | ⭐⭐⭐ cron |
| MCP 集成 | ✅ 双向 | ✅ 只 client | ✅ workspace |
| 自我提升 skill 学习 | ❌ 路线图远期 | ❌ | ⭐⭐⭐⭐⭐ |
| 跨平台 messaging gateway | ❌ 路线图中期 | ❌ | ⭐⭐⭐⭐⭐ |
| 训练数据导出 | ❌ 路线图远期 | ❌ | ⭐⭐⭐⭐⭐ |
| 本地优先 / 无云依赖 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |

诚实说,右边三行 Hermes 现在比 Skyler 强。这些是真实差距,不假装看不见。中间四行是 Skyler 真正下功夫的地方。

---

## 快速开始

### 前置(macOS)

| 工具 | 最低版本 | 安装 |
|---|---|---|
| Node.js | 18+(推荐 22+)| `brew install node` |
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
# 编辑 .env,至少:
#   DASHSCOPE_API_KEY=sk-xxx
#   DATABASE_URL=sqlite+aiosqlite:///./skyler.db

uvicorn backend.main:app --reload
# 后端跑在 http://127.0.0.1:8000

# ── 前端(另一个终端)──────────────────────────────────
cd frontend
npm install
npm run tauri dev
# 首次 Rust 构建 5–15 分钟,之后启动很快
```

默认 LLM 是 Qwen 走 DashScope(国内不用翻墙)。换 provider 改 `config.yaml` —— Skyler 内部走 LiteLLM,DeepSeek / OpenAI / Anthropic / 本地 Ollama 都是改一行的事。

---

## Live2D 资产管理

Skyler 默认带 Live2D 官方免费样品模型 **Hiyori**。想换自己的角色,四步:

1. **资产放进 `frontend/public/live2d/<slug>/`** —— slug 用小写英文(例如 `yae-miko`、`momo-v2`),后面在 CharacterPanel 里 `live2d_model` 字段填的就是这个名字。
2. **目录里必须有一个 `*.model3.json` 入口文件**,还要有 `*.moc3`、`textures/`,至少一个 motion。完整 checklist 看 [`frontend/public/live2d/README.md`](frontend/public/live2d/README.md)。
3. **接通前先验 moc3 版本**:
   ```bash
   python -m tools.check_moc3_version frontend/public/live2d/<slug>/
   ```
   pixi-live2d-display 不支持 Cubism 5,version ≥ 5 或塞了 Cubism 2 的 `.moc` 都会让脚本退出码非零。
4. **CharacterPanel 里绑定** —— 打开角色编辑器,把 `live2d_model` 字段填成你的 slug,重进对话就生效。

**IP / license 隔离** —— `.gitignore` 默认 ignore `frontend/public/live2d/` 下除 `hiyori/` 以外所有子目录。你扔进去的第三方 / 委托资产不会被 track,也不会被 push 出去。这是有意的:Skyler 项目的 license 没法覆盖不属于你的资产。自制 / 已清理 license 的模型想入库时,在 `.gitignore` 末尾追加 `!frontend/public/live2d/<slug>/`。

**免责声明** —— Skyler 自己的代码用宽松 license,但**不为用户添加的任何 Live2D 资产 license 背书**。资产怎么来的、有没有授权、能不能传播,完全是用户自己的责任。

### 实操示例:从 BCSZ1.1 dump 接入八重神子

具体例子 —— Cubism 4 的八重神子资产在 `<某路径>/BCSZ1.1/`。Skyler 的 character id=2 已经叫「八重神子」,`motion_map_json` / `hit_area_map_json` 也已经由 `v3_e2_yae_maps` 迁移填好。让她渲染只差资产入位:

```bash
# 选项 A:复制资产到 slug 目录
cp -r "<某路径>/BCSZ1.1" frontend/public/live2d/yae

# 选项 B:软链接(省盘 + 改源更方便)
ln -s "<某路径>/BCSZ1.1" frontend/public/live2d/yae
```

任一种方式,`frontend/public/live2d/yae/` 都被 .gitignore 排除 —— 资产留本地,进 git 的只有"character id=2 指向 slug `yae`"这条数据迁移。验证之后刷新 UI:

```bash
python -m tools.check_moc3_version frontend/public/live2d/yae/
# 期望:[OK] version=3 (Cubism SDK 4.0)
```

打开 CharacterPanel,切到八重神子,立绘换成 BCSZ1.1。点击模型 Skyler 会播 `Start` motion(八重的初见配音),而不是 Hiyori 的 `Tap` 随机一条 —— 这就是 per-character `motion_map_json` 生效的视觉信号。

> **注意:模型 motion3.json 中引用的配音 wav 默认禁用。** 部分模型(八重 BCSZ1.1 含 6 段配音)会在 motion 自带 wav;Skyler 所有语音输出统一走 LLM + TTS pipeline,让 motion 自动播 wav 会跟 TTS 重叠。当前在 SDK config 层全局关闭。未来 per-character 开关已在 ROADMAP backlog —— 鼠标点击触发的 motion 可以播原声 wav 保留演出价值,LLM 标签触发的不播让 TTS 独占。

---

## 特性

下面列的是 Skyler 当前能做的事。每一层都是设计成可以拆开来换的,没有锁死的。

### 🎙 输入与输出
- **语音输入**两种模式:
  - **手动模式** —— 点击开始录音,再点击发送
  - **VAD 模式** —— 点击激活后,Web Audio API 自动检测语音;1.5 秒静音自动发送;60 秒空闲回 sleep
- **ASR 实时回显** —— 通过 `asr_result` WebSocket 消息把识别结果即时显示在输入框上方,并写入聊天历史
- **流式输出** —— 文字和音频按句到达
- **TTS** —— CosyVoice(DashScope,默认)→ Edge-TTS 后备;每角色独立 `voice_model` 配置;SoVITS 计划中
- **assistant 说话时自动静音 mic**(防回声 loop)
- **Tool 调用过渡** —— agent 调 tool 时先冒一句过渡话("让我看看…"),输入框同时显示对应 loading pill("查日历…"),你不会卡在 30 秒沉默里不知道是不是卡死了。chunk 14 producer/consumer + chunk 6b TTS pipeline 已实现 sentence-by-sentence streaming,经 chunk 15 实测验证体感流畅

### 🧠 记忆 & 人格(三层结构)
- **第 1 层 短期** —— `chat_history` 表,按 conversation_id 组织,ChatAgent 每轮取最近 N 行;也是第 2 层 worker 的唯一输入源
- **第 2 层 长期事实记忆** —— `memory` 表,**入库主路径改成 server-side worker**(`MemoryExtractor`,每 5 min batch 提取 + 10 道 quality filter + entry_type 四分类 + extraction_source 四态来源标签)。`save_memory` tool 降级为"用户明确说要记"的显式入口。检索按**遗忘曲线** `score = relevance * (1+log(1+ac)) / (1+age*decay)` + threshold gate + 跨角色共享
- **第 3 层 用户画像** —— `users.profile_data` JSON schema(profession / current_projects / interests / recurring_topics / communication_style / active_hours / language_preferences),validator 严格 hard-reject 反推词;legacy `profile_summary` 自由段保留作 fallback;每日 cron 自动重生
- **活动时间线** —— 跟 `chat_history` 平行的第二条 timeline,持久化你每天的 app/URL session(已过滤 idle 时长)。Momo 能在对话里自然引用今天的活动("看你 VS Code 待了 3 小时,跟昨天那个项目吧?")。默认保留 30 天。
- **记忆查看抽屉** —— entry_type tab(事实 / 偏好 / 事件 / 承诺)+ extraction_source 角标(自动提取 / 你说要记 / 手动 / 旧)+ confidence 显示
- **记忆开关** —— 长期记忆 / 用户画像 / 屏幕感知 / web search / 活动时间线 全在 Settings 可单独 toggle

### 🤖 Multi-Agent Intelligence
- **ChatAgent direct flow** —— LiteLLM tool calling 在一个 LLM round-trip 里同时驱动 memory + 内建工具 + MCP 工具(不需要单独 planner)
- **真 MCP 工具接入** —— 可扩展 `ToolRegistry`,双向(Skyler 既是 client 又是 server)
- **LiteLLM 统一 LLM 层** —— DeepSeek / Qwen / OpenAI / Claude(config 切换)
- **Web 搜索** —— 模型内置(Qwen Max / DeepSeek),`enable_search` 开关

### 🎭 多角色对话
- **每角色独立** —— 每个角色有自己的 conversations 和 memory;用户画像跨角色共享(一份对你的印象)
- **对话列表** —— 可折叠侧栏,改名 / 删除;删对话触发画像 recompute
- **角色切换器** —— TopBar 下拉,完整 CRUD 走 `CharacterManagerDrawer`(Momo / `id=1` 是系统默认,不能删)
- **每角色音色** —— `character.voice_model` JSON: `{provider, voice, instruct_supported}`;空值 fallback 到全局默认

### 🎨 UI:8 套主题

Settings → UI 风格切换:

| 主题 | 调性 |
|---|---|
| 🌫️ 莫兰迪 | 暖色极简奶油 |
| 🌆 黄昏 *(默认)* | 梦幻紫色暮色 |
| 🌊 玻璃 | glassmorphism 冷色 |
| 🌸 水彩 | 粉色 |
| 🌌 极光 | 深海绿青 |
| 🌷 樱花 | 樱花夜 |
| 🌃 赛博 | 赛博绛红 |
| 💜 薰衣草 | 薰衣草雾 |

所有组件走 `var(--color-*)`(styles/themes.css),没有硬编码 Tailwind 色值。状态存 `localStorage`,首次渲染 `data-theme` 上 mount 防闪烁。

`lucide-react` 图标全组件覆盖。

### 🔔 主动陪伴
- **Trigger pack** —— wake_call / lunch_call / dinner_call / bedtime_chat / long_idle / morning_briefing —— Momo 在该出现的时候才出现,不是每个 polling 都说话
- **活动触发** —— `ide_open` / `music_playing` / `long_focus` / `url_tech_doc` / `late_night_ide` —— 上下文快路径分类,加 LLM 慢路径判官应对模糊场景(停留 5+ min、多重 throttle、daily cap、idle 闸 —— 人离开电脑就闭嘴)
- **邀请对话模式** —— 主动不只是推送;trigger 可以先冒一句短招呼等你回应,再走完整对话

### 🛠 工具生态
- **日历** —— Apple EventKit(默认,零网络)+ Google Calendar(可选)
- **音乐** —— 网易云(内建 mpv 自解码,也支持 URL Scheme fallback)+ macOS 媒体控制(next/prev/play_pause/now_playing/volume,Apple Music / Spotify / YouTube 通吃)
- **B 站** —— 11 个 capability(search / video info / subtitles 给 AI 总结 / etc.)
- **小红书** —— 只做 URL 被动解析(红线锁在代码层:不暴露 search / recommend / feed)
- **Docx** —— 读 / 写 / append,沙盒在 `~/Documents/Skyler/docs/`
- **Notion** —— 通过官方 `@notionhq/notion-mcp-server` MCP 接入
- **剪贴板助手** —— 最近 50 条 ring buffer(24h TTL,从不写 SQLite),`get_recent` / `summarize` / `translate`
- **屏幕感知** —— active app + 浏览器 URL + 页面正文(19 条黑名单守银行 / 邮箱 / 社交 / localhost)
- **以及自定义 skill** —— 见 [扩展 Skyler](#扩展-skyler)

---

## 架构

Skyler 的架构不是凑出来的。每个大决策 —— 能力注册表、双向 MCP、persona 级 `character_states`、活动时间线 —— 都是定位决定的直接结果。一个"可改的角色框架"必须有平权的扩展机制、生态参与、人格持久化。想知道为什么一块东西长这样,见 [DESIGN.md](DESIGN.md)。

```
用户输入(语音 / 文字)
  ├─ [VAD 模式]  Web Audio API 检测语音 → MediaRecorder
  │              静音 > 1.5s → 停 → 发音频
  ├─ [手动]      用户点击 → MediaRecorder 开始/结束 → 发
  └─ [文字]      直接打字发送

  → ASR        faster-whisper(后端)→ asr_result 推前端
  → ChatAgent  context 装配 + LiteLLM tool calling
                ├─ memory tools:save / delete / list / compress(LLM 驱动)
                ├─ 内建工具:ToolRegistry(MCP 可扩展)
                ├─ capabilities:@register_capability 自动入 ToolRegistry
                └─ web search:模型内置(Qwen Max / DeepSeek)
  → emotion    首句解析 <emotion>X</emotion> → 锁定本轮 emotion
  → TTS        get_tts_engine(voice_model) → CosyVoice / Edge / SoVITS
  → 输出:      流式文字 chunk + 按句音频 chunk + asr_result 预览

能力注册表:
  @register_capability 装饰器 → CapabilityRegistry 单例
    ├─ Consumer.CHAT_AGENT  → 自动导出 OpenAI schema → ToolRegistry → ChatAgent
    ├─ Consumer.SCHEDULER   → APScheduler cron / interval triggers
    └─ Consumer.WEBHOOK     → /api/webhooks/n8n/{trigger}(Bearer + HMAC 认证)
  GET /api/capabilities → frontend CapabilityPanel(按 category 卡片 + 健康点)

双层集成:
  backend/integrations/<service>.py     低层 client(OAuth、retry、健康检查)
  backend/capabilities/<service>.py     每个 action 5 行 @register_capability

双向 MCP:
  ┌─────────────────────────────────────────────────────────────────┐
  │  CapabilityRegistry  ←  装饰器  | 运行时  | aggregator           │
  │                                                                  │
  │  来源 1:@register_capability(内建:time / calendar)            │
  │  来源 2:MCP client(消费外部 server,如 filesystem / brave / Notion) │
  │  Skyler-as-server:POST /mcp 把注册表暴露给                      │
  │            Claude Desktop / Cursor / Claude Code(Bearer 认证)  │
  └─────────────────────────────────────────────────────────────────┘

Persona 级状态:
  character_states 表  ← mood / intimacy / current_thought / current_activity
  <state_update> LLM 标签协议(跟 <emotion> 平行)
  每日 intimacy_decay cron
  用户画像跨角色共享(对你的一份印象)

活动时间线:
  ActivityWatcher(30s 轮询)
    → (app, url, idle 标志)元组变化 → session 边界
    → SessionWriter 持久化到 activity_sessions 表
    → ChatAgent system-prompt 注入("用户今天 X 用了 Y 小时")
    → 5 道隐私闸(黑名单 / 写入层 dedup / idle 过滤 / 显式删除 / 全本地)
```

---

## 技术栈

- **后端**:Python 3.10 / FastAPI / SQLAlchemy(异步)/ APScheduler / LiteLLM / faster-whisper / sentence-transformers / pyobjc(macOS-only 部分)
- **前端**:Tauri 2 / React 18 / TypeScript / Vite / Tailwind / Zustand / lucide-react / pixi-live2d-display(Cubism 3 + 4)
- **TTS**:CosyVoice(DashScope)默认 / Edge-TTS 后备 / SoVITS 计划中
- **ASR**:faster-whisper(本地)
- **LLM**:LiteLLM(Qwen / DeepSeek / OpenAI / Claude / 本地 Ollama —— config 切换)
- **DB**:SQLite + Alembic 迁移
- **MCP**:stdio + streamable HTTP,双向
- **Embeddings**:sentence-transformers(paraphrase-multilingual)
- **平台**:macOS Apple Silicon 主力;Linux/Windows 部分支持

---

## 扩展 Skyler

Skyler 是设计成给你扩展的。四条扩展路径覆盖常见 case。

### 1. 加一个 skill(内建 capability)

`backend/capabilities/` 下扔一个文件,装饰一个函数,重启后 LLM 就能调:

```python
# backend/capabilities/weather.py
from backend.capabilities.registry import register_capability, Consumer

@register_capability(
    name="weather.current",
    description="查指定城市的当前天气。用户问天气时调用。",
    consumers=[Consumer.CHAT_AGENT],
    parameters={
        "type": "object",
        "properties": {
            "city": {"type": "string", "description": "城市名,如 '东京'"}
        },
        "required": ["city"],
    },
)
async def get_current_weather(city: str) -> dict:
    # 调你喜欢的 API,返 JSON 可序列化 dict
    return {"city": city, "temp_c": 18, "condition": "多云"}
```

就这样。不用专门注册,不用 plugin manifest。装饰器 + JSON schema 就是契约。

完整 pattern(错误处理、健康检查、多 consumer)见 [docs/skills-extension-guide.md](docs/skills-extension-guide.md)。

### 2. 接一个外部 MCP server

在 `config.yaml` 加一条:

```yaml
mcp_clients:
  - name: filesystem
    command: npx
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/Users/me/Documents"]
    enabled: true
    expose_via_skyler_server: false   # 不要再暴露给 Claude Desktop
```

重启后 MCP client 连上,发现 tool,反向注册成 `ext.filesystem.<tool>` capability。ChatAgent 自动认。

任何 MCP server 都行:brave-search、Notion(`@notionhq/notion-mcp-server`)、Anthropic 的参考 server,或者你自己写的。见 [docs/mcp-client-setup.md](docs/mcp-client-setup.md)。

### 3. 换 Live2D 模型

见上面 [Live2D 资产管理](#live2d-资产管理)章节。前端 `live2d_scanner` 自动发现 `frontend/public/live2d/<slug>/<slug>.model3.json`。Motion map 和 emotion 绑定是 per-character 的;见 [docs/live2d-setup.md](docs/live2d-setup.md)。

### 4. 换 LLM provider

Skyler 内部走 LiteLLM,所以 LiteLLM 支持的 provider 都是改 `config.yaml` 的事:

```yaml
llm:
  provider: openai          # 或 'anthropic' / 'deepseek' / 'ollama' / etc.
  model: gpt-4o
  api_key_env: OPENAI_API_KEY
```

本地 Ollama 模型、私有部署、自定义 endpoint —— 全部一个 config 字段。不动代码。

---

## Skyler 不是什么

- Skyler **不是**开箱即用的 VTuber app。想要包装好的直播 / 角色 UX,去用 [Open-LLM-VTuber](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber)。
- Skyler **不**做自我提升的 skill 学习。Skill 不会用着用着自己变好。这事 [Hermes Agent](https://github.com/NousResearch/hermes-agent) 做得很到位。我们长期路线图上有这事,叫 *persona-level learning*(角色成长,不只是 skill 库变厚)。
- Skyler **不**带 messaging gateway(Telegram / Discord 等)。中期路线图项。当前是桌面 only。
- Skyler **不**导出你的对话数据作为训练数据。长期路线图项,会作为"用你跟角色的对话训练你自己的小模型"功能。
- Skyler **不**跟 LangChain / AutoGen 这种通用 agent 框架比。Skyler 专门是*角色驱动的桌面 agent*。要是不想要角色这一层,就不该用 Skyler。

诚实列这些,是因为差距真实存在。这些也就是路线图。

---

## 路线图

完整路线见 [ROADMAP.md](ROADMAP.md),按四条支柱组织:

- **当前重点**:把可改性真正做到顺手(skill 文档、Live2D 替换指南、plugin registry 雏形)
- **中期**:补上面诚实列的缺口(messaging gateway、训练数据导出、capability marketplace)
- **远期**:persona-level learning(`character_states` 真的能成长)
- **长期愿景**:在桌面端建立一个小而忠诚的可塑型 AI 角色容器爱好者生态

---

## 先前的工作

Skyler 站在两个项目定义出来的空地中间:

- **[Open-LLM-VTuber](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber)** —— 打磨好的 VTuber 陪伴体验。想要一个开箱即用的 app,选它。
- **[Hermes Agent](https://github.com/NousResearch/hermes-agent)**(Nous Research 出品)—— 服务器跑的个人 agent 平台,带自我提升 skill 循环。

它俩在各自方向上都做得很好。Skyler 瞄准的是它俩中间的空地 —— 桌面、角色驱动、能拆到 agent 内核、所有权归你。架构选型是顺着这个空地推出来的,不是按竞品 feature 表抄出来的。

它们当前在哪些事上比 Skyler 强,见上面 [对比](#对比)表 —— 老老实实列出来,让你选对工具。

---

## 项目状态

v4-alpha 在 2026 年 5 月发布。Activity timeline + tool 调用过渡 UX + Live2D 透着可见的历史抽屉都已上线。完整实施日志(每个 chunk、hotfix、UX 迭代)在 [ROADMAP.md](ROADMAP.md) —— 那是真实的历史。当前重点是让 Skyler 的可改性对下一个贡献者(而不只是原作者)真的顺手。

---

## 许可证

目前 **All rights reserved**(无 LICENSE 文件)。仓库公开后会切换到宽松许可证(MIT 或 Apache 2.0)—— 注意:之后捆绑的 Live2D 模型有 Live2D Inc. 自己的许可证,**不在** Skyler 项目许可证覆盖范围内。

### Live2D 模型许可

Skyler 当前开发期使用 Live2D 官方样本模型 **Hiyori**(位于 `frontend/public/live2d/hiyori/`),由 illustrator Kani Biimu 创作。该模型遵循 **Live2D Free Material License Agreement**,开发/学习/小规模商用 OK;中大型企业商用需向 Live2D Inc. 申请书面授权。

后续版本会替换为自有/购买的模型,届时 Skyler 项目本身的 license 不覆盖该模型,模型遵循各自原始 license。

---

## 贡献

私有开发期间不接受外部贡献。等公开后见。
