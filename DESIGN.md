# Skyler 技术设计文档 v3-WIP（2026-05）

> 本文档是给 Claude Code 使用的开发蓝图。每次开启新会话时，将本文档粘贴进去作为上下文。
>
> **改名提示**：项目原名 MomoOS，2026-05 重命名为 **Skyler**。代码内 localStorage key（`momoos.mode` / `momoos.theme` / `momoos.convListCollapsed`）暂未跟改，保留为代码现实；后续做 v3 收尾 commit 时统一重命名 + 加 fallback 读取（旧 key → 新 key），不破坏用户既有状态。
>
> **当前状态**：v2.7 全部完成 + v3-A/B/C/D 进行中（约 v3 整体 60%）。详见 §十六 阶段性进度。

---

## 一、项目定位

Skyler 是一个**本地运行的 AI Agent 桌面伴侣**，定位是**双重身份**：

- 🎭 **Galgame 风格情感伴侣外观** —— Live2D 看板娘、persona 驱动对话、emotion 驱动 TTS 多音色、角色状态面板
- 🛠️ **生活 & 工具型 agent 内核** —— 长期记忆、MCP 工具生态、自然语言定时任务、屏幕感知、剪贴板助手、每日简报

外观是 Galgame 看板娘（情感面）→ 内核是能记忆、能执行任务、能定时主动、能看屏幕的全栈 agent（工具面）。和纯陪伴向的 Open-LLM-VTuber、纯远程工具向的 Hermes Agent **都不同** —— Skyler 的目标是这两者的合一。

技术能力：
- 语音（手动 / VAD 自动检测）+ 文字多模态输入
- ASR 识别结果实时回显到前端 + 进入 chat 历史
- 流式文字 + 分句 TTS 输出（CosyVoice 默认 / Edge 后备 / SoVITS 占位）
- ChatAgent + LLM tool calling 自主管理记忆（save / delete / list / compress）
- 双层记忆系统（memory 事实条目 + profile_summary 整体印象）
- ChatGPT 模式多对话 + 多角色（每角色独立 conversations / memory）
- 后端主动推送（闹钟、长任务完成、后台事件、屏幕感知评论）
- Tauri 2 桌面应用（透明看板娘 + 完整面板双模式，Galgame 风布局）
- emotion 标签（`<emotion>X</emotion>`）解析驱动 TTS 多音色（v3-D 后端就绪）
- 8 套 UI 主题切换（v3-A 完成）
- 屏幕感知（v4 规划，主动 + 被动模式，VLM 云端分析）
- 单用户本地应用，无需登录认证（多设备访问推迟到 v6+，见 §二十 跨平台策略）

**借鉴来源**：Open-LLM-VTuber（avatar UX）+ Hermes Agent（skill 累积型工具 agent）。完整借鉴清单见 §十九。

---

## 二、目录结构

```
Skyler/
├── backend/
│   ├── main.py                       # FastAPI app + lifespan 预加载模型 + 迁移
│   ├── config/
│   │   ├── __init__.py               # config_yaml + reload_config_yaml() + get_*() getters
│   │   ├── characters.yaml
│   │   ├── prompt_manager.py
│   │   └── prompts.py
│   ├── agents/
│   │   ├── base.py
│   │   ├── registry.py
│   │   ├── planner.py                # qwen-turbo 意图三分类
│   │   ├── chat.py                   # ChatAgent + 4 个 memory tool（save/delete/list/compress）
│   │   ├── memory.py
│   │   └── tool.py
│   ├── memory/
│   │   ├── short_term.py
│   │   └── long_term.py              # sentence-transformers + 向量检索（按 character_id）
│   ├── database/
│   │   ├── __init__.py
│   │   ├── models.py
│   │   ├── services.py
│   │   └── migrations/
│   │       ├── __init__.py
│   │       └── v2_5_b.py             # 幂等迁移：加 conversations/characters，扩 chat_history/memory
│   ├── tts/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── sovits.py
│   │   └── edge.py
│   ├── asr/
│   │   └── whisper.py                # faster-whisper + run_in_executor
│   ├── llm/
│   │   └── client.py                 # LiteLLM wrapper（DashScope OpenAI 兼容端点）
│   ├── vlm/                          # v4：视觉大模型客户端
│   │   └── client.py
│   ├── screen/                       # v4：屏幕感知模块
│   │   ├── analyzer.py
│   │   └── filter.py
│   ├── tools/
│   │   ├── registry.py
│   │   └── builtin.py
│   ├── routes/
│   │   ├── ws.py                     # WebSocket + ConnectionManager + profile_summary 触发
│   │   ├── memory_api.py             # memory CRUD + character_id filter
│   │   ├── conversations_api.py      # conversations CRUD + messages 拉取
│   │   ├── characters_api.py         # characters CRUD
│   │   ├── users_api.py              # users profile + profile_summary reset
│   │   ├── health_api.py             # /api/health 模型就绪状态
│   │   └── config_api.py             # GET /api/config + POST /reload
│   ├── scheduler/
│   │   └── task.py
│   └── utils/
│       ├── logger.py
│       └── timer.py                  # @contextmanager timed("xxx") 仪表化
│
├── frontend/
│   ├── src/
│   │   ├── App.tsx                   # 启动 health 轮询 + fetchConfig + fetchCharacters + fetchConversations
│   │   ├── modes/
│   │   │   ├── Widget.tsx
│   │   │   └── Panel.tsx             # 三栏布局：Sidebar + ConversationList + 主区
│   │   ├── components/
│   │   │   ├── CharacterView.tsx     # 满铺背景，draggable=false
│   │   │   ├── CharacterDialogueBubble.tsx  # 浮动 Momo 气泡（仅最后一条 assistant）
│   │   │   ├── ChatHistory.tsx       # 滚动消息列表
│   │   │   ├── ChatHistoryDrawer.tsx # 右侧滑入完整历史
│   │   │   ├── ConversationList.tsx  # 左侧对话列表（折叠 0/240px）
│   │   │   ├── CharacterSwitcher.tsx # TopBar 角色切换 dropdown
│   │   │   ├── CharacterManagerDrawer.tsx  # 角色 CRUD
│   │   │   ├── MemoryManagerDrawer.tsx     # 记忆 view + delete + filter
│   │   │   ├── ChatInput.tsx
│   │   │   ├── ControlBar.tsx
│   │   │   ├── VadBar.tsx
│   │   │   ├── StatusBadge.tsx
│   │   │   ├── AsrPreview.tsx
│   │   │   ├── ConnectionDot.tsx
│   │   │   ├── TopBar.tsx            # 全局 drag region + switcher + 三按钮
│   │   │   ├── Sidebar.tsx           # 💬 ⚙ + ConnectionDot
│   │   │   ├── SettingsPanel.tsx     # 多区块（Memory / ASR-VAD / TTS / 记忆 / 基础信息 / 角色）
│   │   │   └── NotificationToast.tsx
│   │   ├── hooks/
│   │   │   ├── useWebSocket.ts       # 重连 / 消息分发 / 流式 chatMessages 累加
│   │   │   └── useAudio.ts           # VAD 状态机 + 反馈防护
│   │   ├── lib/
│   │   │   ├── window.ts             # setConfigField + applyModeWindowProps
│   │   │   ├── config.ts             # fetchConfig + fetchHealth
│   │   │   └── api/
│   │   │       ├── conversations.ts
│   │   │       └── characters.ts
│   │   ├── store/
│   │   │   └── index.ts              # Zustand：mode/characters/conversations/chatMessages 等
│   │   ├── contexts/
│   │   │   └── appApi.ts
│   │   └── assets/
│   │       └── character.jpeg
│   └── src-tauri/
│       ├── tauri.conf.json
│       ├── capabilities/default.json # 含 core:window:allow-start-dragging
│       └── src/main.rs               # write_config_field 命令
│
├── .env / .env.example
├── config.yaml
├── requirements.txt
└── README.md
```

---

## 三、数据库 Schema（SQLite，v2.7 当前）

```sql
CREATE TABLE users (
    user_id         TEXT PRIMARY KEY,
    user_name       TEXT NOT NULL,
    profile_summary TEXT,                       -- LLM 增量重写的整体印象（300-500 字）
    nickname        TEXT,                       -- v2.5-B 加：用户希望被怎么称呼
    language        TEXT DEFAULT 'zh-CN',       -- v2.5-B 加：语言偏好
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE characters (                       -- v2.5-B 新增
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL UNIQUE,
    persona         TEXT NOT NULL,              -- system prompt for this character
    avatar_path     TEXT,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);
-- 默认行：Momo (id=1)，不可删除

CREATE TABLE conversations (                    -- v2.5-B 新增
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         TEXT NOT NULL REFERENCES users(user_id),
    character_id    INTEGER NOT NULL REFERENCES characters(id),
    title           TEXT NOT NULL DEFAULT '新对话',
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP   -- 每收到一轮消息更新
);

CREATE TABLE memory (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         TEXT NOT NULL REFERENCES users(user_id),
    role            TEXT CHECK(role IN ('user','system')) NOT NULL,
    type            TEXT CHECK(type IN ('fact','instruction','emotion','activity','daily')) NOT NULL,
    content         TEXT NOT NULL,
    embedding       BLOB,
    expires_at      DATETIME,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    character_id    INTEGER REFERENCES characters(id)    -- v2.5-D 加：按角色隔离
);

CREATE TABLE chat_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         TEXT NOT NULL REFERENCES users(user_id),
    role            TEXT CHECK(role IN ('user','assistant')) NOT NULL,
    content         TEXT NOT NULL,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    conversation_id INTEGER REFERENCES conversations(id),  -- v2.5-B 加：删 conv 级联
    character_id    INTEGER REFERENCES characters(id)      -- v2.5-D 加：按角色隔离
);

CREATE TABLE todos (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         TEXT NOT NULL REFERENCES users(user_id),
    owner_type      TEXT CHECK(owner_type IN ('alarm','agent','schedule')) NOT NULL,
    title           TEXT NOT NULL,
    description     TEXT,
    due_time        DATETIME NOT NULL,
    status          TEXT CHECK(status IN ('pending','completed','failed','multiple')) DEFAULT 'pending',
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- v2.5-B 移除：personality 表（用户画像层并入 profile_summary 单字段）
```

**迁移脚本**：`backend/database/migrations/v2_5_b.py`，幂等执行。lifespan 启动时 backfill 旧 chat_history / memory 行的 character_id NULL → Momo (id=1)。

---

## 四、核心接口设计

### 4.1 IAgent 抽象接口

```python
from abc import ABC, abstractmethod
from typing import AsyncGenerator

class IAgent(ABC):
    @abstractmethod
    async def handle(self, message: dict) -> dict: ...

    async def stream(self, message: dict) -> AsyncGenerator[str, None]:
        raise NotImplementedError
        yield
```

### 4.2 消息格式

```python
# 输入
{ "agent": "PlannerAgent", "payload": { "user_id": "xxx", "text": "...", "context": {} } }

# 输出
{ "status": "success"|"error", "agent": "ChatAgent",
  "payload": { "text": "...", "audio": "base64（可选）",
               "tool_result": {}, "memory_ops": [] } }
```

### 4.3 WebSocket 协议（v2.7）

```
客户端 → 服务端：
{ "type": "text",  "content": "你好",      "user_id": "xxx",
  "conversation_id": 5,  "character_id": 1 }            ← 后两个可选
{ "type": "voice", "audio": "<base64>",  "user_id": "xxx",
  "conversation_id": 5,  "character_id": 1 }
{ "type": "screen", "image": "<base64>", "user_id": "xxx", "trigger": "active|passive" }   ← v4

注：缺省 conversation_id → 后端用该 user 最新对话；缺省 character_id → 用 Momo (1)。

服务端 → 客户端（流式回复）：
{ "type": "text_chunk",  "content": "你好" }
{ "type": "audio_chunk", "content": "<base64>" }
{ "type": "done" }
{ "type": "error", "message": "..." }

服务端 → 客户端（主动推送）：
{ "type": "notify",     "content": "任务完成！" }
{ "type": "alarm",      "content": "该起床了～", "todo_id": 42 }
{ "type": "asr_result", "content": "识别出的文字", "message_id": 123 }   ← message_id 用于前端进 chatMessages
{ "type": "screen_comment", "content": "你这段代码漏了分号", "image_id": "xxx" }   ← v4
```

### 4.4 REST 接口（v2.7 完整列表，main.py 通过 prefix="/api" 挂载）

```
# 健康 / 配置
GET    /api/health                                      → 模型就绪状态
GET    /api/config                                      → 白名单 JSON
POST   /api/config/reload                               → 重读 config.yaml

# 记忆（按 character_id 隔离）
GET    /api/memory/list?user_id=&character_id=
POST   /api/memory/add
PATCH  /api/memory/{id}
DELETE /api/memory/{id}

# 对话
GET    /api/conversations/list?user_id=&character_id=
POST   /api/conversations/create
PATCH  /api/conversations/{id}                          → 改 title
DELETE /api/conversations/{id}                          → 级联清 chat_history + 触发 profile_summary regen
GET    /api/conversations/{id}/messages?limit=&before_id=  → 分页拉历史

# 角色
GET    /api/characters/list
POST   /api/characters/create
PATCH  /api/characters/{id}
DELETE /api/characters/{id}                             → Momo 拒删（403）

# 用户
GET    /api/users/{user_id}/profile                     → { user_id, user_name, nickname, language, profile_summary }
PATCH  /api/users/{user_id}/profile                     → 改 nickname / language
DELETE /api/users/{user_id}/profile_summary             → 清空印象
```

GET /api/config 响应（敏感字段如 API keys / database_url / sovits / whisper / planner_model / screen.* 不暴露）：

```json
{
  "default_model": "openai/qwen-plus",
  "default_user_id": "default",
  "memory":  { "long_term_enabled": true, "profile_enabled": true },
  "search":  { "enable_search": true },
  "cache":   { "profile_ttl_seconds": 300 },
  "tts":     { "enabled": true }
}
```

GET /api/health 响应：

```json
{
  "status": "ready" | "warming",
  "models": { "embedding": "ready", "whisper": "ready", "llm": "ready" }
}
```

---

## 五、记忆系统设计（v2.7 双层模型）

### 5.1 两层结构

```
memory 表（事实记忆）
  - LLM 在对话中通过 4 个 tool 自主管理：
    · save_memory(content, type)       — 用户透露值得记的事
    · delete_memory(memory_id)         — 用户要求忘掉
    · list_memories()                  — 列出当前所有
    · compress_memories()              — 去重/合并/精简
  - 用户 不手动添加（按用户偏好），可在 SettingsPanel 看到 + 单条删 + 全部清空
  - 按 character_id 隔离（每个角色独立"她记得的事"）
  - 写入时同步生成 embedding (paraphrase-multilingual-MiniLM-L12-v2)
  - 检索：当前输入做 query，cosine top-5 注入 ChatAgent prompt（按 character_id 过滤）

profile_summary（整体印象）— users 字段
  - 一段 300-500 字的描述性段落，例：
    "Skyler 是个对设计有强烈直觉的程序员，对话直接、爱用反问。最近常聊
     Skyler 项目，会主动指出过度工程。心情起伏不大，深夜更活跃。"
  - 增量式重写（不是从零生成）：
    prompt 里同时塞「旧印象 + 最近 50 round chat_history」→ LLM 输出新印象覆盖
    保留旧的稳定特征，调整最近的短期观察
  - 触发条件：
    a. 每 50 轮 assistant 回复（in-memory turn_count_per_user 计数器）
    b. DELETE /api/conversations/{id}（基于剩余 chat_history 重算）
  - 数据保护：
    · chat_history 行数 < 20（< 10 round）→ 跳过更新
    · chat_history 行数 = 0（删光所有对话）→ profile_summary 设 NULL
  - user 级（不按 character 隔离，跨角色共享对你的整体感觉）
  - 不在 UI 显示（按用户偏好），用户可在对话里问 Momo 由其自然回答
  - 实现：backend/routes/ws.py _regenerate_profile_summary，asyncio.create_task 后台跑
  - 调用模型用 get_planner_model()（qwen-turbo）控成本

短期记忆
  - chat_history 表，按 conversation_id 组织
  - 永久保留，仅在 DELETE /api/conversations/{id} 时级联删除该对话的行
  - ChatHistoryDrawer 分页拉取（limit=50, before_id 滚动加载）
  - ChatAgent 每次组装 context 时取该 conversation 最近 N 行
```

### 5.2 Context 组装顺序（ChatAgent _build_messages）

```
1. character.persona（system prompt，按 currentCharacterId 取）
2. users.profile_summary（永远注入，如有）
3. memory 向量检索 Top-5（按 user_id + character_id 过滤）
4. 工具调用结果（如 ChatAgent 同一轮内调过 tool）
5. [v4] 最近一次屏幕分析摘要（如有）
6. 当前 conversation 最近 N 轮 chat_history（按 conversation_id）
7. 用户当前输入
```

### 5.3 save_memory tool description（收紧版，避免乱存）

```
当用户透露值得长期记住的事时调用。判断标准：这条事实在未来 1 周以上的对话中是否仍有用？

应保存：
- 稳定事实（住址、职业、家人、宠物名字）
- 长期偏好（喜欢/讨厌某物，每日习惯）
- 承诺/计划（deadline、约会、未来安排）
- 反复出现的模式（用户多次提及才显著的特征）

不保存：
- 日常打招呼、单次提问
- 当下情绪、天气、时间感叹（"今天好累"除非反复出现）
- chitchat 本身
```

---

## 六、TTS 分层设计

```
使用顺序：GPT-SoVITS → Edge-TTS（自动降级）
分句流式：按句号/问号/感叹号切割，逐句生成逐句推送
TTS 失败不影响文字输出，文字和音频独立推送
全局开关：config.yaml tts.enabled=false 时，ChatAgent 跳过整个 TTS 调用链路，只推 text_chunk
```

v3 计划：character.voice_model 字段，每角色独立 TTS（SoVITS 模型路径或 Edge voice id），不设则用全局默认。

---

## 七、LLM 调用封装

```python
# backend/llm/client.py
# DashScope 走 OpenAI 兼容端点（更稳，路由到中国区，无需翻墙）
# config.yaml 用 openai/ 前缀 + DASHSCOPE_API_BASE 指向 compatible-mode/v1
```

`config.yaml`：
```yaml
default_model: "openai/qwen-plus"      # 走 DashScope 兼容端点
planner_model: "openai/qwen-turbo"     # 三分类用便宜模型
default_user_id: "default"

memory:
  long_term_enabled: true
  profile_enabled: true

search:
  enable_search: true

tts:
  enabled: true

cache:
  profile_ttl_seconds: 300

# v4 配置
screen:
  enabled: false
  mode: "passive"
  vlm_model: "qwen/qwen-vl-max"
  capture_interval_sec: 30
  pixel_diff_threshold: 0.1
  blocklist:
    - "1Password"
    - "Banking app"
```

`.env`（关键变量）：
```
DASHSCOPE_API_KEY=sk-xxx
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
DASHSCOPE_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
HF_HUB_OFFLINE=1
TRANSFORMERS_OFFLINE=1
WHISPER_MODEL=small
WHISPER_DEVICE=cpu
DATABASE_URL=sqlite+aiosqlite:///./skyler.db
SOVITS_API_URL=
```

### 7.5 v2 / v2.5 前端架构硬决策（不可改）

| 决策点 | 内容 |
|---|---|
| **平台范围** | 仅 macOS，不写跨平台条件分支。Windows 兼容延期 |
| **Widget/Panel 架构** | 单 Tauri window 切 mode，由 zustand `mode: "widget" \| "panel"` 控制。**禁止两个独立 window 方案** |
| **窗口属性切换** | Tauri 2 JS API 动态切（lib/window.ts applyModeWindowProps）。Widget = 350×500/decorations:false/alwaysOnTop:true，Panel = 1100×750/decorations:false（自定义 TopBar）/alwaysOnTop:false |
| **启动模式** | 默认 Panel；localStorage 'momoos.mode' 持久化用户上次选择 |
| **全局 drag strip** | App.tsx 顶层 fixed top-0 h-6 z-9999 data-tauri-drag-region（仅 widget 模式渲染）。Panel 模式由 TopBar 自带 drag region |
| **Character 防拖** | CharacterView img: draggable=false + WebkitUserDrag none + onDragStart preventDefault |
| **UI 风格参考** | 强制对齐 [Open-LLM-VTuber-Web](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber-Web)。v3 加 4 套配色切换（莫兰迪 / 暮色梦幻 / 玻璃拟态 / 水彩二次元）+ lucide-react 图标库 |
| **多对话 + 多角色** | ChatGPT 模式：每角色独立 conversations / memory；profile_summary user 级共享 |
| **Tauri 2 capabilities** | 前端调 setSize/setDecorations/setAlwaysOnTop/start-dragging 等必须在 capabilities/default.json 显式授权 |
| **配置写回** | Tauri Rust write_config_field（serde_yaml） + POST /api/config/reload |
| **包管理** | 前端固定 npm；Tailwind 锁 v3.4 |
| **网络** | DashScope 走 OpenAI 兼容端点 + 中国区直连。VPN 路由会拖慢/失败，部署到 autodl 后无此问题 |

### 7.6 红线（v3 才能动）

- Live2D 渲染（CharacterView 仍是静态 .jpeg）
- emotion 标签解析（`<emotion>` 不剥离不解析）
- 屏幕感知截图 / VLM 分析 / screen_comment 推送
- 系统操作 agent（mouse/keyboard 控制）
- 真实打断逻辑（ChatInput 🚫 按钮仍是占位）
- UI 风格切换器（4 配色 + 图标库引入）
- character.voice_model 字段（每角色独立 TTS）

---

## 八、WebSocket 全链路流程（v2.7）

```
收到消息（text / voice / screen）
  → resolve conversation_id + character_id（缺省时 latest conv + Momo）
  → [voice] ASR (run_in_executor) → 写 chat_history(role=user) → 推送 asr_result {message_id}
  → [screen] 直接走 VLM 分析路径（v4）
  → PlannerAgent (qwen-turbo) → 三分类
      chitchat → 直接 ChatAgent
      memory / tool → asyncio.gather 并行
  → ChatAgent → _build_messages（按 character_id 过滤记忆）
  → acompletion(stream=True, tools=MEMORY_TOOLS)
  → 主循环：
      · 累积 delta.tool_calls 到完整 tool 调用
      · 一轮结束执行 tool → 把 tool result 加回 messages → 重新 acompletion（最多 5 轮）
      · 流式 yield text token → _sentence_stream 切句 → ws.send_json(text_chunk)
  → done
  → 后台异步：
      · 写 assistant 回复到 chat_history
      · turn_count_per_user[user_id] += 1
      · if >= 50 → asyncio.create_task(_regenerate_profile_summary)
  → conversations.updated_at 更新

DELETE /api/conversations/{id}：
  → 级联删该 conversation 所有 chat_history 行
  → asyncio.create_task(_regenerate_profile_summary)（基于剩余历史重算）
```

---

## 九、VAD 语音模式设计

### 9.1 两种录音模式

| 模式 | 触发方式 | 录音控制 |
|------|---------|---------|
| 手动模式（默认） | 点击麦克风按钮开始，再点停止并发送 | MediaRecorder 手动 start/stop |
| VAD 模式 | 点击激活监听，自动检测语音 | Web Audio API 分贝检测驱动 |

### 9.2 VAD 状态机

```
sleep（休眠）
  ↓ 用户点击麦克风
active（监听中）
  ↓ 分贝 ≥ 阈值
recording（录音中）
  ↓ 静音持续 ≥ 1.5s
→ MediaRecorder.stop() → base64 → WebSocket → 回到 active
  ↓ active 状态下 60s 无新录音
sleep（休眠）
```

### 9.3 VAD 参数（Settings 面板可调，存 localStorage）

| 参数 | 默认值 | 说明 |
|------|--------|------|
| 录音模式 | 手动 | 手动 / VAD 切换 |
| 语音检测阈值 | 65 | 分贝阈值（1–100） |
| 静音超时 | 1.5s | 持续静音多久后停止录音 |
| Momo 说话时静音 | 开 | TTS 播放时关麦，防反馈 |

---

## 十、前端 UI 设计（v2.7 当前）

### 10.1 UI 风格

参考 [Open-LLM-VTuber-Web](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber-Web)，深色主题 + 半透明叠加。

v2.7 仍是 slate-900 / 700 / 100 风格。v3 计划加 4 套配色切换器：
- A. 莫兰迪奶油（warm minimal）
- B. 暮色梦幻（dusk dreamy）
- C. 玻璃拟态（glassmorphism）
- D. 水彩二次元（pixiv style）

### 10.2 Widget 模式（350×500，透明 always-on-top）

```
┌─ 全局 drag strip 24px (z-9999) ─┐
│  [状态徽章] idle                 │
│                                  │
│   [角色立绘满铺]                 │
│                                  │
│  ┌──────────────────────────┐   │
│  │ ASR 回显文字 (5s 淡出)   │   │
│  └──────────────────────────┘   │
│  ══ VAD 波形条 ══                │
│  [⚙] [🎤] [⌨] [●]               │
└──────────────────────────────────┘
```

- hover 显隐控件（StatusBadge / AsrPreview / VadBar / ControlBar / ConnectionDot）
- 角色立绘 satisfies draggable=false，img 不可拖出窗口

### 10.3 Panel 模式（1100×750，Galgame 风布局）

```
┌─ TopBar (h-10) ──────────── [Switcher ▾] [⌃] [_] [×] ─┐
├──────┬────────────┬──────────────────────────────────┤
│      │            │                                   │
│ Side │ Conv List  │   Character 满铺背景              │
│ bar  │ 0 / 240px  │                                   │
│      │ + 折叠 24  │   ┌──────────────────────────┐    │
│ 💬   │            │   │ 浮动 Momo 气泡            │    │
│ ⚙    │ + 新对话   │   │ 仅显当前 assistant 一句   │    │
│      │ ─ 对话 1   │   │ 流式累加                  │    │
│      │ - 对话 2   │   └──────────────────────────┘    │
│      │            │                          [📜 历史] │
│  ●   │            │   [ChatInput 浮于底部]            │
└──────┴────────────┴───────────────────────────────────┘

点 📜 → ChatHistoryDrawer 从右侧滑入（60% 宽，半透明覆盖）
```

主要组件：
- TopBar：含 data-tauri-drag-region 拖动区 + CharacterSwitcher dropdown + Widget 切换/最小化/关闭按钮
- Sidebar：💬 chat / ⚙ settings 两个图标 + 底部 ConnectionDot
- ConversationList：可折叠 0/240px，localStorage 持久化（'momoos.convListCollapsed'）。每条显示 title + 相对时间 + hover 删除/重命名
- 24px 折叠按钮：◀ / ▶ 切换 ConversationList 宽度
- CharacterView：满铺 z-0 背景，img draggable=false
- CharacterDialogueBubble：absolute bottom-24 浮动，订阅 chatMessages 找最后一条 assistant
- ChatHistoryDrawer：always-mounted，open=true 时 translate-x-0 滑入；ESC + 点空白 + × 关闭
- 所有 drawer 顶部 pt-10 让位 TopBar

### 10.4 AI 状态标签

| 状态 | 含义 |
|------|------|
| `idle` | 空闲 |
| `listening` | VAD 检测说话 / 手动录音 |
| `thinking` | 等待 LLM 响应 |
| `speaking` | TTS 播放中 |
| `interrupted` | 被打断 |

### 10.5 Settings 面板结构（v2.7 当前）

```
Settings
├── Memory（开关层）
│   ├── 长期记忆        [toggle]   → memory.long_term_enabled
│   ├── 用户画像        [toggle]   → memory.profile_enabled
│   └── 联网搜索        [toggle]   → search.enable_search
├── ASR / VAD（localStorage 纯前端）
│   ├── 录音模式        [手动 | VAD]
│   ├── 语音检测阈值    [slider 1–100, default 65]
│   ├── 静音超时        [slider 0.5–3.0s, default 1.5]
│   └── Momo 说话时静音  [toggle]
├── TTS
│   └── 启用 TTS        [toggle]   → tts.enabled
├── 记忆（数据层）
│   ├── 当前 N 条       [摘要]
│   └── [管理]          → MemoryManagerDrawer (type filter + 滚动 + 单删 + 全清)
├── 基础信息
│   ├── 称呼 (nickname) [text input]
│   └── 语言 (language) [select]
├── 角色
│   ├── 当前 N 个角色   [摘要]
│   └── [管理]          → CharacterManagerDrawer (CRUD，Momo 不可删)
└── Screen Awareness (v4)
    ├── 启用屏幕感知    [toggle]
    ├── 模式            [主动 | 被动]
    ├── 截图间隔        [slider]
    ├── 变化阈值        [slider]
    └── 隐私黑名单      [应用列表]

v3 计划加：
├── UI 风格            [A/B/C/D 四选一 segmented control]
└── ...
```

### 10.6 Settings 同步机制

```typescript
// frontend/src/lib/window.ts
import { invoke } from '@tauri-apps/api/core';

export async function setConfigField(keyPath: string, value: unknown): Promise<void> {
  await invoke('write_config_field', { keyPath, value });
  await fetch('http://127.0.0.1:8000/api/config/reload', { method: 'POST' });
}
```

后端 reload 函数：模块级 `reload_config_yaml()`。所有读配置走 `get_default_model()` / `get_planner_model()` / `get_tts_enabled()` 等 getter。

---

## 十一、设置开关

| 开关 | 位置 | 关闭后效果 |
|------|------|-----------|
| long_term_enabled | config.memory | 跳过 embedding 生成、向量检索 |
| profile_enabled | config.memory | 跳过 profile_summary 注入 |
| enable_search | config.search | ChatAgent 不传联网参数给模型 |
| tts.enabled | config.tts | ChatAgent 跳过 TTS 调用，只推 text_chunk |
| 录音模式 / VAD 参数 | localStorage | Web Audio API 参数 |
| screen.enabled / mode | config.screen | 关闭屏幕感知（v4） |
| mode | localStorage 'momoos.mode' | 启动默认 Panel，记住用户上次选择 |
| convListCollapsed | localStorage | 折叠状态持久化 |

短期记忆永远开启，不提供关闭开关。

---

## 十二、主动推送（ConnectionManager）

```python
class ConnectionManager:
    def __init__(self):
        self._connections: dict[str, WebSocket] = {}

    def register(self, user_id: str, ws: WebSocket) -> None:
        self._connections[user_id] = ws

    def unregister(self, user_id: str) -> None:
        self._connections.pop(user_id, None)

    async def push(self, user_id: str, message: dict) -> None:
        ws = self._connections.get(user_id)
        if ws:
            await ws.send_json(message)

connection_manager = ConnectionManager()
```

用法：
```python
# ASR 推送（v2.5 起带 message_id）
await connection_manager.push(user_id, {
    "type": "asr_result", "content": transcribed_text, "message_id": row_id
})

# 闹钟
await connection_manager.push(user_id, {
    "type": "alarm", "content": f"提醒：{todo.title}", "todo_id": todo.id
})

# 屏幕感知评论（v4）
await connection_manager.push(user_id, {
    "type": "screen_comment", "content": "这段代码漏了分号"
})
```

---

## 十三、屏幕感知设计（v4）

### 13.1 双模式

```
主动模式（active）
  用户语音/快捷键触发 → Tauri 截图 → 压缩 → ws.send({type:"screen"})
  → 后端 VLM 分析 → 注入 ChatAgent context → 正常回复链路

被动模式（passive）
  Tauri 后台定时截图（默认 30s 一次）
  → 前端先做像素差对比（上一张 vs 当前）
  → 差异 < 阈值 → 丢弃
  → 差异 ≥ 阈值 → ws.send({type:"screen", trigger:"passive"})
  → 后端 VLM 分析 → connection_manager.push({type:"screen_comment"})
```

### 13.2 隐私保护

- **黑名单机制**：`config.screen.blocklist` 配置应用名/窗口标题，截图前检查命中则跳过
- **本地预过滤**：像素差对比在前端完成
- **Settings 一键关闭**：`screen.enabled=false`

### 13.3 像素差预过滤算法

```typescript
function pixelDiff(img1: ImageData, img2: ImageData): number {
  const small1 = downscale(img1, 64, 64);
  const small2 = downscale(img2, 64, 64);
  let diff = 0;
  for (let i = 0; i < small1.data.length; i += 4) {
    const dr = Math.abs(small1.data[i] - small2.data[i]);
    const dg = Math.abs(small1.data[i+1] - small2.data[i+1]);
    const db = Math.abs(small1.data[i+2] - small2.data[i+2]);
    if (dr + dg + db > 30) diff++;
  }
  return diff / (small1.width * small1.height);
}
```

### 13.4 系统操作扩展（v4 后续）

mac 上需要请求 Accessibility 权限。技术栈：
- Tauri Rust 端调用 `enigo` crate 模拟键鼠
- 截图获取像素 → VLM 分析 → 输出操作指令 → enigo 执行
- 操作前必须经用户确认

---

## 十四、情绪系统（v3）

**情绪标签**：ChatAgent 在正文前输出 `<emotion>开心</emotion>`，前端解析后剥离正文正常显示。

**TTS 情绪驱动**：
- 方案 A（SoVITS）：每个角色多套参考音频，按情绪标签选择
- 方案 B（CosyVoice2）：文本内插入情绪指令

**Live2D 联动**：前端收到 `<emotion>` 标签后触发对应表情动作。

---

## 十五、MCP 工具扩展

```
短期：tools/builtin.py 直接添加内置函数
中期：tools/mcp_bridge.py 启动时连接本地 MCP server，批量注册
长期：config.yaml 配置 mcp_servers 列表，启动时自动发现注册
```

**v2.5 已有的 4 个内置 memory tool**（在 ChatAgent 内通过 LiteLLM tool calling）：
- save_memory(content, type)
- delete_memory(memory_id)
- list_memories()
- compress_memories()

---

## 十六、开发进度

### ✅ 阶段一：骨架搭建
### ✅ 阶段二：后端核心 (v1)
### ✅ 阶段三：前端 v2 (模块 1–9 全部完成)

模块清单：
1. ✅ 后端补充：GET /api/config + POST /api/config/reload
2. ✅ Tauri 初始化：透明窗口 + capabilities 配齐
3. ✅ Widget 模式 6 组件 + hover 显隐
4. ✅ Panel 模式 + Widget↔Panel 切换
5. ✅ useWebSocket：重连 + 消息分发 + audio 队列
6. ✅ useAudio：手动 + VAD 状态机 + 反馈防护
7. ✅ ASR 回显：AsrPreview 5 秒淡出
8. ✅ 记忆面板（v2.5 已删除独立 view，改进 SettingsPanel 区块）
9. ✅ 设置面板：Memory 三 toggle + ASR/VAD + TTS

### ✅ 阶段四：v2.5 (A–E 全部完成)

- **v2.5-A**：后端性能 — lifespan 预加载 + asyncio.to_thread + /api/health + timing 仪表化 + planner 换 qwen-turbo + chat.py 改用 getter + add_memory 错误 log
- **v2.5-B**：Schema 迁移 — 加 conversations / characters；chat_history + memory 加列；users 加 nickname/language；删 personality；4 个 memory tool；隐式 summarizer 替代 maybe_summarize
- **v2.5-C1**：前端三栏 — Sidebar + ConversationList + 折叠按钮 + 主区；GET /conversations/{id}/messages；ws 协议加 conversation_id / character_id
- **v2.5-C2a**：Galgame 风 — Character 满铺 + CharacterDialogueBubble + ChatHistoryDrawer；删 SubtitleBar from Panel；删 MemoryPanel；Sidebar 简化 💬⚙
- **v2.5-C2b**：SettingsPanel 重构（记忆 + 基础信息）+ ASR 进 ChatHistory + profile_summary 50 轮 task + save_memory 描述收紧 + 死代码清理 + 抽屉滑入动画
- **v2.5-C2 小补丁**：拖动权限 + 立绘防拖 + 全局 drag strip + 抽屉 X 位置 + 改名"记忆" + MemoryManagerDrawer
- **v2.5-D**：多角色 — CharacterSwitcher（TopBar dropdown）+ CharacterManagerDrawer（CRUD）+ 全链路 character_id 透传 + lifespan backfill
- **v2.5-E**：启动模式 localStorage 持久化（默认 Panel）+ profile_summary 增量重写 + 删对话触发 + 数据保护门槛

### 🚧 阶段五：v3（Presence + 工具型能力 + UI 重做）—— 进行中（约 60%）

#### v3-A：UI 风格切换器 + 图标库 ✅ 已完成（**超 DESIGN 范围**：4 套 → 实际 8 套）
- [x] **8 套主题** — `morandi` / `dusk`(默认) / `glass` / `watercolor` + bonus `aurora` / `sakura` / `cyber` / `lavender`
- [x] `frontend/src/styles/themes.css` 全套 CSS variables，`index.css` 已 import
- [x] store `theme` 状态 + `setTheme` + localStorage 持久化（`momoos.theme`，rebrand 时重命名）
- [x] `App.tsx` mount 应用 `data-theme` 防首屏闪烁
- [x] `SettingsPanel.tsx` 4×2 grid 主题预览选择器（base + accent 双色斜切渐变）
- [x] **246 处 `var(--color-*)` 引用**深度迁移
- [x] `lucide-react ^1.14.0` 已装，11 个组件迁移完成

#### v3-B：character.voice_model 字段 ✅ 已完成
- [x] `backend/database/migrations/v3_b.py` —— 幂等加 `characters.voice_model TEXT`
- [x] `backend/tts/voice_config.py` —— JSON parser，存 `{provider, voice, instruct_supported}`，失败兜底默认
- [x] `backend/tts/__init__.py` 新工厂 `get_tts_engine(voice_model)`，按 JSON 路由 cosyvoice / edge / sovits
- [x] `backend/tts/cosyvoice.py` —— DashScope CosyVoice 全新实现（24kHz mono 16bit WAV，asyncio.to_thread）
- [x] `_LegacyProviderAdapter` —— 把旧 `TTSProvider(text, character)` 适配到新 `TTSBase(text, emotion)`
- [x] `CharacterPanel.tsx` 已有 voice_model 输入框
- [x] `config.yaml` `tts.provider: cosyvoice` + cosyvoice 配置块

#### v3-C：PlannerAgent 简化 ✅ 已完成
- [x] `planner.py` 头注释「v3-C: PlannerAgent 已从主流程移除，保留文件备用」
- [x] `ws.py` 主流程改为直接走 `ChatAgent.stream()`，意图识别 + tool 调度全由 LiteLLM tool calling 完成
- [x] PlannerAgent / MemoryAgent / ToolAgent 文件保留作回滚备份
- [x] `planner_model` 配置仍用于 profile_summary 增量重写（不同用途，合理保留）

#### v3-D：emotion 系统 ⚠️ 后端 100% / 前端等 Live2D
- [x] `chat.py` `_EMOTION_RE` 正则 + `_parse_emotion()` + `_build_emotion_instruction()` 注入 system prompt
- [x] `ws.py` 第一句剥离 `<emotion>` 标签锁定整轮 `turn_emotion`，后续句子复用
- [x] `engine.synthesize(sentence, emotion=turn_emotion)` 整链路通
- [x] `cosyvoice.py` 中文情感词 → 英文枚举 EMOTION_MAP，instruct_supported=True 时插 `instruction` 参数
- [x] `config.yaml` `tts.emotions` 列表给 LLM 选择
- [ ] **前端推送 emotion 给 Live2D 控制器** —— 等 Live2D 接入后补 `ws send_json({"type": "emotion", "value": X})` + 前端 store `currentEmotion` 状态

#### v3-E：Live2D 接入 + 前端 emotion 联动 📋 计划中
- [ ] **SDK 选型**：`pixi-live2d-display` + Cubism 5 Web SDK（开源）
- [ ] **CharacterView.tsx** —— 从 `<img>` 换成 `<canvas>` + Live2D runtime；保持 Galgame 满铺布局不变
- [ ] **idle 动画** —— Cubism 模型自带的 idle motion 自动循环
- [ ] **口型同步** —— `useAudio.ts` 扩展 audio amplitude 取样钩子，驱动 ParamMouthOpenY
- [ ] **emotion → 表情切换** —— store 加 `currentEmotion` 状态，CharacterView 订阅 → Live2D `setExpression(emotionMap[X])`
- [ ] **触摸响应**（OLV #6 借鉴）—— Live2D `hitTest` 不同 hit area 触发不同 motion + AI 回应
- [ ] **motionMap**（OLV #8 借鉴）—— 说话时同步 Live2D motion，`<motion>X</motion>` 标签注入 system prompt（emotion 系统的扩展）
- [ ] **`characters.live2d_model` 字段** —— 复用 v3-B 模式加列，存模型路径
- [ ] **资产**：你需要自己找一个 Cubism 5 .moc3 / .model3.json 模型（许可证另购或用免费样本）

#### v3-F：语音体验飞跃 📋 计划中（OLV 借鉴）
- [ ] **语音打断**（OLV #1）—— ChatInput 🚫 按钮接通；用户开始说话 → 立即 cancel LLM stream → 立即 stop TTS playback → 已说出部分写入 chat_history 标「被打断」
  - DESIGN §7.6 红线第一条；`status: 'interrupted'` 状态 store 已就绪，差最后接通
- [ ] **TTS 多段并发合成**（OLV #2）—— 当前是 sentence-by-sentence 串行，改为并发合成 + 顺序播放，砍首句到末句的等待时间
- [ ] **TTS 预处理器**（OLV #3）—— 正则剥离 `*动作*` / `(注释)` / `[标记]` 不让 TTS 读出来；同时也要不读 `<emotion>` 残留（虽然 `_parse_emotion` 应该已剥离）
- [ ] **AI 内心独白**（OLV #5）—— `<thinking>X</thinking>` 标签解析，不读出但前端显示在 status 区或独立 thoughts 抽屉

#### v3-G：生活 & 工具型能力 📋 计划中（Hermes 借鉴 + DESIGN 原计划）
- [ ] **剪贴板助手** —— Tauri clipboard API 监听变化，AI 可主动评论 / 翻译 / 总结复制内容
- [ ] **每日简报** —— 自然语言定时任务（"每天早上 9 点说今天日程"）通过 ConnectionManager.push() 主动播报
- [ ] **智能提醒** —— 比 alarm 更软的提醒，结合 profile_summary 上下文
- [ ] **自然语言 cron 调度**（Hermes #3 借鉴）—— 扩展现有 scheduler，支持自然语言定义任意定时任务（不只是 alarm）
- [ ] **角色状态面板 / 成长系统**（OLV v1.4 + DESIGN 计划合并）—— 当前心情 / 亲密度 / 当前思绪 / 当前正在做什么；与 profile_summary 联动；详见 §十八

### 📋 阶段六：v4 屏幕感知 + 视觉能力（OLV #4 借鉴）

1. **后端**：vlm/client.py + screen/analyzer.py + filter.py
2. **Tauri**：screen capture API + 像素差对比 + 全局热键监听
3. **前端**：Settings 面板加 Screen Awareness 开关 + 黑名单管理
4. **WebSocket**：增加 `screen` 上行 + `screen_comment` 下行
5. **黑名单**：截图前检查活动窗口（应用名 / 窗口标题 / Bundle ID）
6. **主动模式**：hotkey / 语音命令触发单次截图 → VLM
7. **被动模式**：定时截图 + 像素差预过滤 → VLM 仅在画面真有变化时调用 → AI 主动评论
8. **AI 用自己的浏览器**（OLV #4 后半，可选）—— 内嵌 webview 让 AI 能访问网页查信息（区别于 web_search 工具的纯文本结果）

### 📋 阶段七：v5 部署到 autodl + 持久化执行

部署到国内云服务器（autodl / Modal / 自有 VPS）后：
- 后端 → DashScope 国内直连，秒回
- 前端 Mac → 后端通过 SSH tunnel 或 HTTPS
- 用户本地 VPN 状态不再影响 LLM 调用
- **GPT-SoVITS 本地推理服务器**（你长期 TTS 路线）—— 在 GPU 服务器上起 SoVITS 推理服务，桌面端通过 HTTP 调用，避开桌面端 GPU 跨平台问题
- **子 agent 隔离**（Hermes #4 借鉴）—— 长任务（屏幕分析、批量记忆压缩、自主信息收集）跑在独立子 agent context，不阻塞主对话

### 📋 阶段八：v6+ 多设备访问（高代价）

⚠️ **这个阶段会让项目从「桌面应用」跃迁到「小型 SaaS」**，工作量约等于把整个项目再写半遍。详见 §二十 跨平台策略。

- [ ] Windows 客户端（Tauri 已支持，但屏幕监视 / 全局热键 / 系统通知 全部需要重新做）
- [ ] 用户认证 + WebSocket 鉴权 + TLS
- [ ] 数据库迁移到 Postgres（SQLite 不支持多客户端并发写）
- [ ] 多端状态同步 + 冲突解决
- [ ] 移动端（远期）
- [ ] **Hermes 风格的 skill 自我累积系统**（Hermes #1 借鉴，长期愿景）—— 让 Skyler 用得越久越懂用户的工作模式，自动总结出可复用的 "skills"

详细执行清单见 **ROADMAP.md**。

---

## 十七、每次启动 CC 会话的 Prompt 模板

```
你接管 Skyler 项目的开发。

【项目背景】
Skyler 是本地运行的 AI Agent 桌面伴侣（原名 MomoOS，2026-05 改名）。
定位：Galgame 风格情感伴侣外观 + 生活&工具型 agent 内核。
技术栈：FastAPI + WebSocket（后端） + React 18 + Vite + Tauri 2（前端） + SQLite + SQLAlchemy async。
完整背景：仓库根 README.md / DESIGN.md / ROADMAP.md。

【当前状态】
v2.7 + v3-A/B/C/D 完成，v3 整体约 60%。
v3-A: 8 套主题 + lucide-react ✅
v3-B: character.voice_model + CosyVoice ✅
v3-C: PlannerAgent 简化 ✅
v3-D: emotion 后端 ✅（前端等 Live2D）
下一阶段：v3-E（Live2D + emotion 联动）/ v3-F（语音体验）/ v3-G（生活工具层）。

【UI 参考】
Open-LLM-VTuber-Web（avatar UX）
Hermes Agent（skill 累积 / cron 调度 / 子 agent 隔离设计借鉴）

【当前任务】
[填写当前模块名称]
[填写具体需求]

【约束条件】
- 所有 LLM 调用走 LiteLLM，model 从 config.yaml 读
- 所有 IO async/await
- API Key 从 .env 读，禁硬编码
- SQLite + SQLAlchemy async
- TypeScript 严格、Tailwind v3.4，**所有颜色用 var(--color-*) 不硬编码 Tailwind 色板**
- 每个函数有类型注解
- 配置写回走 Tauri write_config_field + POST /api/config/reload
- VAD 纯前端实现
- ASR 通过 ws asr_result 回显（含 message_id 进 chatMessages）
- ChatAgent 用 LiteLLM tool calling 管理 memory（4 个 tool）
- profile_summary 增量重写 + 50 轮 / 删对话触发 + 数据门槛保护
- emotion 标签必须保留 v3-D 后端流程（chat.py `_parse_emotion` + ws.py `turn_emotion`）
- 所有新组件用 lucide-react 图标，禁 Unicode emoji
- CC 输出必须中文
- **Git 工作流**：每完成一个独立模块自动 git add + commit（conventional commits: feat/fix/docs/refactor:）+ push origin main。重要架构决策同步更新 DESIGN.md 和 ROADMAP.md
- DB schema 变化必须写幂等迁移到 backend/database/migrations/，命名 v3_X.py（X 是子阶段字母）

【设计文档】
[粘贴本文档]
```

---

## 十八、环境配置

### .env / .env.example
```
# LLM
DASHSCOPE_API_KEY=
DEEPSEEK_API_KEY=
OPENAI_API_KEY=
ANTHROPIC_API_KEY=

# DashScope OpenAI 兼容端点（推荐，避免 LiteLLM 默认走海外）
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
DASHSCOPE_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1

# 模型缓存离线模式（避免 sentence-transformers 网络检查阻塞）
HF_HUB_OFFLINE=1
TRANSFORMERS_OFFLINE=1

# TTS
SOVITS_API_URL=http://127.0.0.1:9880
SOVITS_MODEL_DIR=

# ASR
WHISPER_MODEL=small
WHISPER_DEVICE=cpu

# DB
DATABASE_URL=sqlite+aiosqlite:///./skyler.db
```

### 依赖清单（requirements.txt 核心）
```
fastapi
uvicorn[standard]
websockets
sqlalchemy[asyncio]
aiosqlite
litellm
httpx
faster-whisper
edge-tts
python-dotenv
pydantic
pydantic-settings
sentence-transformers
numpy
pillow              # v4：图像处理
```

---

## 十九、Open-LLM-VTuber & Hermes Agent 借鉴清单

Skyler 的功能选型借鉴自两个开源项目。本节明确**借鉴了什么、为什么不借鉴某些**，避免后续设计漂移。

### 19.1 Open-LLM-VTuber（avatar UX 参考）

**已采纳并集成进路线图**：

| 特性 | Skyler 对应阶段 | 备注 |
|---|---|---|
| 语音打断（停止生成 token + 停止播放） | v3-F | DESIGN §7.6 红线第一条 |
| TTS 多段并发合成 + 优先播首句 | v3-F | 当前 sentence-by-sentence 串行 |
| TTS 预处理器（剥离 `*动作*` / `(注释)` 不读出） | v3-F | 极低成本，高收益 |
| 视觉能力（屏幕共享 + 相机 + AI 浏览器） | v4 | 与 DESIGN §13 屏幕感知合并 |
| AI 主动说话 + 内心独白（`<thinking>` 标签） | v3-F + v3-G | 增加角色立体感 |
| Live2D 触摸响应 | v3-E | 不同 hit area 触发不同 motion |
| motionMap（说话同步动作） | v3-E | emotion 系统的扩展 |
| MCP 协议接入 | v3-G / v4 | DESIGN §15 已有规划 |
| 多并发 session + 多设备访问 | v6+ | **代价极高**，见 §二十 |
| Character Status Panel（v1.4 路线图） | v3-G 成长系统 | 与下方 19.3 成长系统合并 |

**未采纳**：

| 特性 | 不采纳原因 |
|---|---|
| 群聊（多角色同时在场对话） | 与单角色 Galgame 看板娘定位冲突 |
| Bilibili 弹幕客户端 | 直播场景，与桌面伴侣定位无关 |
| Letta / MemGPT 长期记忆 | Skyler 的 SQLite + sentence-transformers 已够用，引入 Letta 增加运维复杂度且经常变 API |

### 19.2 Hermes Agent（生活 & 工具型 agent 参考）

Hermes 定位是"住在你服务器上的远程持久 agent"，与 Skyler 桌面伴侣定位**不同**，但有几条核心设计可直接借鉴。

**已采纳并集成进路线图**：

| 特性 | Skyler 对应阶段 | 备注 |
|---|---|---|
| 自我提升 skill 累积循环 | v6+ 长期愿景 | 与 profile_summary 联动深化"对你的了解" |
| 自然语言 cron 调度 | v3-G | 扩展现有 alarm 系统为通用任务调度 |
| 子 agent 隔离（长任务独立 context） | v5 | 屏幕分析 / 批量记忆压缩这类长任务用 |
| 多执行 backend（local / Docker / SSH / Modal） | v5 autodl 部署 | 远程 GPU 推理需要 |
| Persona 编辑器（SOUL.md 风格） | 已部分完成 | `characters.persona` + CharacterManagerDrawer |

**未采纳**：

| 特性 | 不采纳原因 |
|---|---|
| 16+ messaging gateway（Telegram / Discord / WhatsApp / Signal 等） | Skyler 是桌面应用，不是远程 agent；用户跟 Skyler 互动入口是桌面看板娘而非 IM |

### 19.3 成长系统设计（v3-G）

DESIGN 原版只写了名字没展开。结合 OLV v1.4 的 Character Status Panel 计划，定为以下形式：

**核心：角色状态面板** —— UI 区域显示当前心情 / 亲密度 / 当前思绪 / 当前正在做什么。

**数据来源**：
- 心情：当前 turn 的 `<emotion>` 标签 + 最近 N 轮平均情绪
- 亲密度：累计互动 turn 数 + 连续打卡天数 + 重要事件触发
- 当前思绪：ChatAgent 回复时输出的 `<thinking>X</thinking>` 标签内容
- 当前正在做什么：默认 "陪着你"；后台执行任务时显示具体内容（与子 agent 隔离结合）

**互动反馈**：
- 亲密度阈值解锁称呼变化、对话语气微调（注入 system prompt）
- 纪念日（首次见面 / N 天打卡）触发特殊主动消息
- profile_summary 与亲密度联动 —— 越熟越深的"对你的整体印象"

**实现位置**：
- 后端：`backend/database/models.py` 加 `relationship` 表（character_id × user_id × intimacy / streak / first_met / last_active）
- 后端：迁移脚本 `v3_g.py` 幂等加表
- 前端：新组件 `CharacterStatusPanel.tsx`，Panel 内某处展示
- ChatAgent：每 turn 末尾更新 relationship 表

---

## 二十、跨平台策略

**核心结论**：跨平台难度不由项目大小决定，而由"接触系统底层"的功能数量决定。

### 20.1 难度按功能分层

| 功能类别 | 跨平台代价 | 例子 |
|---|---|---|
| 🟢 **零代价** | React + FastAPI 内的一切 | LLM 调用、记忆系统、对话 UI、配色主题、任意业务逻辑 |
| 🟡 **中代价** | Tauri 2 已封装但需配置 | 透明窗口、always-on-top、系统通知、文件路径、打包分发 |
| 🔴 **高代价** | 各 OS 接口完全不同 | 屏幕截图、全局热键、麦克风、本地 GPU 推理 |
| 🔴🔴 **极高代价** | 部分平台几乎做不了 | 系统操作 agent（鼠标键盘控制），Linux Wayland 下截图 / 热键 |

### 20.2 Skyler 各功能的跨平台关键点

| 功能 | macOS | Windows | Linux |
|---|---|---|---|
| Tauri 透明窗口 + 点击穿透 | ✅ | ✅ | ⚠️ Wayland 有问题 |
| 麦克风访问 | ✅ + Info.plist 权限声明 | ✅ WASAPI | ⚠️ PulseAudio / PipeWire 各家不同 |
| **屏幕截图（v4）** | ScreenCaptureKit + 屏幕录制权限弹窗 | GDI / DWM | ⚠️ Wayland 几乎做不了，X11 OK |
| **全局热键（v4 主动模式）** | Accessibility 权限 | RegisterHotKey 直接能用 | ⚠️ Wayland GG |
| 本地 GPU 推理（GPT-SoVITS） | Metal / MPS | CUDA | CUDA / ROCm 一塌糊涂 |
| 系统通知 | NotificationCenter | Toast | libnotify |
| 文件路径 | `~/Library/Application Support` | `%APPDATA%` | `~/.config` |
| 打包分发 | 签名 + 公证（$99/年） | 签名昂贵但不强制 | .deb / .rpm / .AppImage 各打 |

### 20.3 战略

1. **v3 阶段坚持 macOS-only** —— README 大方写明，不假装支持
2. **v4 屏幕感知设计时主动模式优先** —— hotkey 触发可控，不像被动模式要持续后台监听，Windows 接入时只需做单次截图，避开持续监听难题
3. **Wayland 大概率不支持** —— 如果要 Linux 支持，明确 X11 only
4. **GPT-SoVITS 本地推理放到服务器部署模式（v5 autodl）** —— GPU 推理只在 Linux 服务器上，桌面端 HTTP 调用，自然绕开桌面 GPU 跨平台问题
5. **多设备访问推迟到 v6+** —— 这是从"桌面应用"到"小型 SaaS"的跃迁（用户认证 / WS 鉴权 / TLS / Postgres / 多端同步 / 冲突解决 / 部署运维），工作量等于把项目再写半遍
6. **localStorage 持久化保留 fallback** —— 跨设备时这些状态不能用，需要后端持久化方案

---

*文档版本：v3-WIP | 最后更新：2026-05-04*

变更日志：
- **v3-WIP（2026-05-04，Skyler 改名 + v3-A/B/C/D 完成）**：项目 MomoOS → Skyler；v3 拆 A-G 七个子阶段；A/B/C/D 完成（8 套主题 + lucide / character.voice_model + CosyVoice / PlannerAgent 简化 / emotion 后端）；E/F/G 计划写明（Live2D / 语音体验 / 生活工具层）；新增 §十九 OLV/Hermes 借鉴清单 + §二十 跨平台策略
- **v2.7（2026-05）**：v2.5 全模块完成 — schema 加 conversations/characters/character_id/conversation_id 列；删 personality 表；4 个 memory tool（save/delete/list/compress）通过 LiteLLM tool calling；隐式 summarizer 替代每 20 轮显式总结；前端 ChatGPT 模式重构 — 三栏布局 + 折叠侧栏 + Galgame 风（Character 满铺 + 浮动气泡 + 历史抽屉）+ 多角色切换；Sidebar 简化 💬⚙；SettingsPanel 重构（含记忆/基础信息/角色三新区块）；profile_summary 增量重写 + 50 轮 / 删对话触发 + 数据门槛保护；启动模式 localStorage 持久化（默认 Panel）；config.yaml 改用 openai/qwen-plus + DashScope 兼容端点；后端 lifespan 预加载 + asyncio.to_thread + /api/health。
- v2.6（2026-05）：补全 GET /api/config 白名单 JSON；修正 reload 函数为 reload_config_yaml() / get_*() 风格；新增 tts.enabled 全局开关；Tauri 2 write_config_field 命令实现。
- v2.5（2026-04）：v4 屏幕感知模块设计，初版前端 v2 模块清单。
