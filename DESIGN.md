# Skyler 技术设计文档 v4-alpha(2026-05)

> 本文档是给 Claude Code 使用的开发蓝图。每次开启新会话时,将本文档粘贴进去作为上下文。
>
> **改名提示**:项目原名 MomoOS,2026-05 重命名为 **Skyler**。代码内 localStorage key(`momoos.mode` / `momoos.theme` / `momoos.convListCollapsed`)暂未跟改,保留为代码现实;后续做 v4 收尾 commit 时统一重命名 + 加 fallback 读取(旧 key → 新 key),不破坏用户既有状态。
>
> **当前状态(2026-05-13)**:v4-alpha shipped。chunk 14 activity timeline、UX-004 v1 tool-call transition、UX-005 capability 单一归属、UX-007 Momo bubble fade,以及 hotfix-3 ~ hotfix-10 已上线。**65+ capabilities, 11 proactive triggers, 7 architectural abstractions, 950+ 测试**。剩 chunk 8b 完整屏幕感知 + chunk 12/13/15 + 长期路线见 [ROADMAP.md](ROADMAP.md) 四支柱组织。

---

## 零、为什么是这些选择(Why these choices)

Skyler 的核心架构决策 —— Capability Registry / 双向 MCP / persona 级状态机 / 活动时间线 —— 不是"觉得这样优雅"。每个都是 §一 定位决定的直接结果。这一章先把"为什么"摆出来,后面章节具体说"怎么做"时不再重复 motivate。

### 0.1 为什么 Capability Registry(`@register_capability`)

定位是"可塑型角色容器" → 扩展是核心 → 扩展机制必须低摩擦。

替代方案被否的原因:
- ❌ 写死的 tool 列表 + if/else 分发:每加一个 skill 改一处 agent 代码,违背"接口简易"
- ❌ Plugin manifest + 加载器(LangChain 风格):学习成本高,违背"易扩展"
- ❌ 完全靠 MCP server 把所有 skill 外置:MCP server 启动慢、跨进程 overhead、调试痛苦,日常内建 skill 不该承担这个成本

→ **`@register_capability` 装饰器 + JSON schema** 是唯一契约。一个 Python 函数装饰一行就是 LLM 可调的 tool。`Consumer` enum(`CHAT_AGENT / SCHEDULER / WEBHOOK`)允许同一个 capability 被不同子系统消费。整套 plugin API 就这一个装饰器和一个 enum。

详见 §十五之A Capability Registry 架构。

### 0.2 为什么双向 MCP(client + server)

定位是"所有权归你 + 生态参与"。

只做 MCP client:Skyler 只能消费,不能贡献。社区写的 skill 无法被 Claude Desktop / Cursor / Claude Code 复用,Skyler 变成孤岛。

只做 MCP server:Skyler 只能贡献,不能消费。filesystem / brave-search / Notion 等社区已经写好的 server 无法直接接入,等于重新发明轮子。

→ **双向**:Skyler 既是 client(消费外部 server)也是 server(把 capability 注册表 + 角色状态 + 记忆暴露给任何 MCP client,带 Bearer 认证)。你的 AI 角色变成 MCP 生态里的一个节点,不是孤岛。

详见 §十五 MCP 工具扩展。

### 0.3 为什么 persona 级 `character_states`

定位是"角色化 + 长期使用"。

替代方案被否的原因:
- ❌ 状态全靠 prompt 注入,每轮 reset:角色没有"自己",每天都是新的相遇 —— 这是 ChatGPT 模式,不是陪伴
- ❌ 写死的状态机(`if mood == happy: ...`):僵硬,违背"角色 LLM 驱动演化"

→ **DB 表持久化 + LLM 驱动**:`character_states` 表跟踪 mood / intimacy / current_thought / current_activity / available;LLM 通过 `<state_update>` 标签更新(跟 `<emotion>` 平行);每日 intimacy_decay cron 模拟"不联系就疏远"的真实感。

这是 Skyler 长期 vision *persona-level learning*(角色跟用户一起成长)的基础设施 —— 没有持久化的状态机就没有"成长"。

详见 §十五之C 角色状态系统 + [ROADMAP.md](ROADMAP.md) "Later" 支柱。

### 0.4 为什么活动时间线(chunk 14)是顶层 first-class system

定位是"陪伴感"。陪伴的关键不是回应快,是**记住**。

不只记用户说了什么(`chat_history`),还记用户今天**在做什么**(`activity_sessions`)。Momo 能说"看你 VS Code 待了 3 小时,跟昨天那个项目吧?",是因为活动时间线是跟 `chat_history` 平行的**第二条 timeline**,不是塞在 chat_history 里的 metadata。

5 道隐私闸(黑名单 / 写入层 dedup / idle 过滤 / 显式删除 / 全本地)是"本地优先"原则在数据层的具体体现 —— 角色知道用户今天做了什么,但数据不离开本机。

详见 §十五之T Activity Timeline 系统。

### 0.5 为什么主动陪伴 = trigger pack + activity 双路径

定位是"角色化主动性",但有边界 —— 角色应该在该出现时出现,不该是每个 polling 都说话(那叫 spam,不叫陪伴)。

两条路径:
- **Trigger pack**(时间驱动):wake_call / lunch_call / dinner_call / bedtime_chat / long_idle / morning_briefing —— 时间窗 + cooldown + daily cap,人设性事件
- **Activity-based**(上下文驱动):`ide_open` / `music_playing` / `long_focus` / `late_night_ide` —— 快路径分类 + LLM 慢路径判官 + idle 闸(人离开电脑就闭嘴)

两条路径都共用同一套 throttle / cooldown / 静默时段闸,保证 daily cap 跨 trigger source 全局有效。

详见 §十五之B Proactive Engine + §十五之L Activity-based Trigger + §十五之Q Judge 慢路径。

---

## 一、项目定位

Skyler 是一个**可塑型 AI 角色容器**(hackable AI companion framework)—— 桌面端、角色驱动、能拆到 agent 内核、所有权归用户。

### 1.1 北极星

每一层都是设计成可以拆开来换的:capability(`@register_capability`)、Live2D 模型 / motion / emotion 绑定、TTS provider、LLM provider(LiteLLM)、MCP server(双向)、persona / 状态机。Skyler 本体提供 agent 内核(MOMOOS)、能力注册表、主动陪伴层、UI shell;剩下的拼成什么样,由用户塑造。

> "我能不能有一个真正属于我自己的 AI 陪伴,本地跑、用我喜欢的角色、调我自己注册的工具" —— Skyler 是给这种人写的。

### 1.2 目标用户

有动手能力的二次元半技术宅(hackers who want an AI character of their own):

- 能跑命令行,能写一点 Python
- 在意数据所有权(本地 SQLite、本地 sentence-transformers 嵌入,无强制云依赖)
- 喜欢"角色驱动的 AI"概念,反感冷冰冰的通用 chatbot
- 宁可拿到能扩展的框架,不要磨光但改不动的 app

### 1.3 三角坐标(产品空间)

|  | 形态 | 角色驱动 | 可改造性 |
|---|---|---|---|
| Open-LLM-VTuber | 桌面 + Live2D | ⭐⭐⭐ Live2D + persona | ⭐⭐(磨光的 app) |
| Hermes Agent | CLI + messaging gateway | ❌(任务驱动)| ⭐⭐⭐⭐⭐(框架性质) |
| **Skyler** | **桌面 + Live2D** | **⭐⭐⭐⭐ persona + 状态机** | **⭐⭐⭐⭐⭐(框架性质)** |

Skyler 站在 OLV(强角色)和 Hermes(强可改)中间的空地。架构选型是顺着这个空地推出来的,不是按竞品 feature 表抄出来的。详见 §十九。

### 1.4 六大支柱

按"通用扩展能力 vs Skyler 独有"分两组:

**通用扩展能力**(任何"长期使用 + 自己改造"的桌面 AI 都需要):
1. **可扩展** —— Capability Registry / 双向 MCP / 多 LLM provider(LiteLLM)/ 多 TTS provider(CosyVoice / Edge / SoVITS)/ 多 Live2D 模型(runtime 抽象层)
2. **易扩展** —— 5 行装饰器加 skill / 1 行 config 接外部 MCP / 替 Live2D 4 步走完(`docs/live2d-setup.md`)
3. **接口简易** —— `@register_capability` 是唯一 plugin 契约;没有别的 plugin manifest / 加载器 API 要学

**Skyler 独有**(定位决定的):
4. **本地优先** —— SQLite / sentence-transformers / Apple EventKit / faster-whisper 都本地;cloud LLM 是可选不强制(可以全切 local Ollama)
5. **角色化** —— persona 级 `character_states`(mood / intimacy / current_thought / activity)持久化跨 session,LLM 驱动演化,不是写死规则
6. **主动性** —— 不只是被叫才动;trigger pack(wake_call / lunch_call / 长 idle)+ activity-based(IDE / 音乐 / 长 focus / 深夜)让角色在该出现时主动出现

每条支柱对应的具体架构决策见 §零 + §五 + §十五各子节。

### 1.5 技术能力清单(v4-alpha 当前)

- 语音(手动 / VAD)+ 文字多模态输入
- ASR 实时回显 + 进入 chat 历史
- 流式文字 + 分句 TTS(CosyVoice 默认 / Edge 后备 / SoVITS 长期)
- ChatAgent + LLM tool calling 自主管理 memory + 内建 capability + 外部 MCP
- 三层记忆系统(short-term `chat_history` / long-term facts `memory` + server-side worker / structured `users.profile_data`)
- 活动时间线(chunk 14 起)—— 30s 轮询 app/URL session + ChatAgent system prompt 注入 + 5 道隐私闸
- 每角色独立 conversations / memory;用户画像 *跨角色* 共享(一份对用户的印象)
- 后端主动推送(闹钟 / 长任务完成 / 屏幕活动 trigger / persona 内省)
- Tauri 2 桌面应用(透明 widget + 完整 panel 双模式)
- emotion 标签(`<emotion>X</emotion>`)解析驱动 TTS 多音色
- 角色状态系统(`character_states`)+ `<state_update>` LLM 标签协议
- 双向 MCP(consumer + provider,Bearer 认证)
- 8 套 UI 主题(`var(--color-*)` 走 CSS variables)
- 屏幕感知(active app + 浏览器 URL + 页面正文,19 条隐私黑名单)
- Tool 调用过渡语 + frontend loading pill(UX-004 v1 起,audio streaming v2 留 chunk 15)
- Capability Registry 双层集成(integrations 低层 + capabilities 装饰器层)
- 单用户本地应用,无登录认证(多设备访问长期 roadmap,见 §二十)

剩余路线 + 北极星支柱 + tech debt 见 [ROADMAP.md](ROADMAP.md)。

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

## 五、记忆系统设计（v3.5 chunk 9 + 10 + 11 完成后的三层模型）

> **演进史**：v2.7 双层（memory + profile_summary 自由段）→ chunk 9 加遗忘曲线 +
> 跨角色共享 → chunk 11 用结构化 ``profile_data`` 治本"用户画像污染"，把
> ``profile_summary`` 降级为 fallback → chunk 10 把 memory 写入从 LLM tool 主路径
> 改成 server-side worker 主路径 + 显式入口降级 + 6 列结构化字段。三层合并定型如下。

### 5.1 三层结构

```
─── Layer 1：短期记忆 ──────────────────────────────────────────────────
chat_history 表
  - 按 conversation_id 组织；永久保留，仅 DELETE /api/conversations/{id}
    级联删除该对话的行
  - ChatAgent 每次取该 conversation 最近 N 轮注入 prompt
  - ChatHistoryDrawer 分页拉取（limit=50, before_id 滚动）
  - 是 Layer 2 worker 的**唯一输入源**（kind='normal' + role='user' 子集）

─── Layer 2：长期事实记忆（memory 表）─────────────────────────────────
入库路径有三条：
  · server-side MemoryExtractor worker（chunk 10 主路径，下详）
  · save_memory tool（chunk 10 commit 5 起降级为显式入口，"请记住 X" 才触发）
  · 用户在 MemoryManagerDrawer 手动添加（extraction_source='manual'）

字段结构（chunk 10 commit 1 加列）：
  content / type / character_id / created_at        老字段（chunk 2 + 9）
  access_count / last_accessed_at                   chunk 9 遗忘曲线
  extracted_at / source_turn_id / confidence /
  entry_type / quality_score / extraction_source    chunk 10 结构化

跨角色策略（chunk 9 commit 4 改）：
  - 检索**不按 character_id 隔离**——所有角色共享用户长期事实
  - UI 角标显示"由 X 记"区分原始来源
  - 仍保留 character_id 字段不删（向后兼容 + 未来 per-character override）

入库时同步生成 embedding (paraphrase-multilingual-MiniLM-L12-v2)，best-effort。

──── 检索（search_relevant_memories）───────────────────────────────────
  1. 短输入门：len(query.strip()) < 10 → 直接返 [] (chunk 9 perf)
  2. encode query（LRU + TTL cache, chunk 9 perf）
  3. SQL 取该 user 全部 memory 行
  4. 每条算 score（chunk 9 遗忘曲线）：

       score = relevance * (1 + log(1 + access_count))
                         / (1 + age_days * decay)

       relevance    cosine 相似度
       access_count 累计被 top-k 召回次数（log 渐进防爆款霸榜）
       age_days     now - (last_accessed_at OR created_at).days
       decay        config.memory.forgetting_curve.age_decay_factor（默认 0.01）

     forgetting_curve.enabled=false → 退回纯 relevance
  5. score < threshold（默认 0.3）的行不进 top-k（仍在 DB，UI 可见）
  6. top-5 返回；同时异步 bump access_count + last_accessed_at（best-effort）

──── MemoryExtractor worker（chunk 10 主路径）─────────────────────────
backend/memory/extractor.py，单例 asyncio task，lifespan 拉起 / 关停
（backend/main.py 6b''；config.memory.extractor.enabled=false 整段静默跳过）

每 interval_seconds（默认 300s）跑一轮 _extract_batch：
  for user_id in active users:
    1. read last_processed_turn_id from memory_extractor_state(user_id)
    2. fetch chat_history where role='user' kind='normal'
                         and id > last_processed_turn_id
                         limit batch_size (默认 50)
    3. build_extraction_prompt(turns)   → JSON list 契约
                                          type ∈ {fact,preference,event,commitment}
                                          content 5-200 字符 第三人称
                                          confidence 0-1
                                          14 反推词清单 prompt 主动避开
    4. call_extraction_llm(prompt)      → planner_model (qwen-turbo)
                                          LLMError / Exception → None 静默
    5. validate_and_filter_entries() —— 10 道闸：
       hard reject  ─ JSON parse 失败
                    ─ type 不在四分类
                    ─ content 长度 < 5 或 > 200
                    ─ SUSPICIOUS_TAG_RE 命中（chunk 6b hotfix-3 复用）
                    ─ confidence < min_confidence (默认 0.5)
                    ─ 与现有 memory 向量 sim > dup_threshold (默认 0.9)
                    ─ intra-batch dedup（本批已 accept 的也比对）
                    ─ (可选) llm_judge YES/NO，默认关
       soft warn   ─ 反推词命中（log 警告但 accept，让 UI 编辑）
    6. _save_worker_entries() —— INSERT memory 行：
       extraction_source='worker', confidence, source_turn_id, extracted_at,
       entry_type（chunk 10 四分类），同时填 legacy type（_TYPE_LEGACY_MAP）：
         fact       → fact
         preference → instruction
         event      → activity
         commitment → activity
       embedding best-effort，失败入库 NULL
    7. update_last_processed_turn_id(user_id, max_turn_id)
       任一子步骤异常都吞 + log，state pointer 仍推进（避免 stuck loop）

──── save_memory tool（chunk 10 commit 5 起降级）────────────────────────
description 收紧到 4 个明确触发信号（"请记住 / 以后 / 别忘了 / 你要记住"），
明文禁令"日常对话事实由 chunk 10 server-side worker 每 5 分钟自动提取，不要
主动调"。_TOOL_PROMPT_ADDENDUM 记忆类段同步。

内部 _tool_save_memory 复用 worker 同 quality filter：
  · 长度 5-200
  · SUSPICIOUS_TAG_RE 不命中
  · cosine 重复检测（命中返 status='duplicate' + existing_memory_id，不抛错）
  · raw SQL INSERT extraction_source='llm_save_memory' + extracted_at + embedding

──── extraction_source 四态 + UI 角标 ──────────────────────────────────
  worker            server-side 自动提取 → "自动提取"
  llm_save_memory   LLM 显式调 save_memory → "你说要记"
  manual            用户在 drawer 手动添加 → "手动"
  legacy            chunk 10 之前入库 → "旧"
MemoryManagerDrawer tab 切换从老 type（chunk 2 五分类）改成 entry_type
（chunk 10 四分类：全部 / 事实 / 偏好 / 事件 / 承诺）；legacy entries
（entry_type=NULL）仅在"全部" tab 显示。

─── Layer 3：用户画像（profile_data + profile_summary fallback）─────────
users.profile_data —— JSON 字段（chunk 11 主路径）
  ```json
  {
    "profession": null | "string",
    "current_projects": [ "string", ... ],
    "communication_style": null | "string",
    "interests": [ "string", ... ],
    "language_preferences": null | "string",
    "active_hours": null | "string",
    "recurring_topics": [ "string", ... ]
  }
  ```
  - schema 严格（backend/utils/profile_validator.py）：JSON parse + 类型校验 +
    SUSPICIOUS_TAG + 14 反推词清单（"温柔/陪伴/亲密/敏感"等）→ hard reject
    违规输出，注入用机械模板而非裸 LLM 文本
  - 重生逻辑（_regenerate_profile_data，4 模式）：
      manual_reset      用户在 UI 点"重新生成"
      conversation_del  DELETE /api/conversations/{id}
      cron_daily        每日 cron（取代 v2.7 50-turn 计数器，chunk 11 commit 5）
      first_seed        历史空时初次播种
  - 调用模型 get_planner_model()（qwen-turbo），prompt 严格 JSON output 契约
  - 数据保护：chat_history < 10 round 跳；删光所有对话 → profile_data 设 {}

users.profile_summary —— 自然语言段（v2.7 引入，chunk 11 后降级）
  - 现行注入优先级：profile_data 非空 → 模板化注入；NULL → fallback 到
    profile_summary 自由段
  - N 个版本后真删（README Known Problems #11，migration DROP COLUMN +
    chunk 9 /profile_summary/* endpoints 删除）

跨角色：user 级共享（不按 character_id 隔离）
不在主 UI 显示，但 SettingsPanel 有"用户档案" section（chunk 11 commit 7，
字段级编辑 + 双按钮 [重新生成] / [清空]）
```

### 5.2 Context 组装顺序（ChatAgent _build_messages，chunk 11 起）

```
1. character.persona（system prompt，按 currentCharacterId 取）
2. users.profile_data 模板化（chunk 11 format_profile_for_prompt），如有；
   profile_data NULL 或 {} → fallback users.profile_summary 自由段
3. memory 向量检索 Top-5（user_id 共享，遗忘曲线 score 阈值过滤）
4. 工具调用结果（如同一轮内调过 tool）
5. [v4] 最近一次屏幕分析摘要（如有）
6. 当前 conversation 最近 N 轮 chat_history（按 conversation_id）
7. 用户当前输入
```

短输入（< 10 字）跳过 step 3 memory 检索（chunk 9 perf optimization）。

### 5.3 save_memory tool description（chunk 10 降级后）

```
仅当用户明确说"请记住 X"/"以后 X"/"别忘了 Y"/"你要记住 Z" 时调用。

日常对话事实的提取走 backend/memory/extractor.py 的 server-side worker，
每 5 分钟批量提取，不需要本 tool。

本 tool 也复用 worker 同 quality filter（content 5-200 字符 + SUSPICIOUS_TAG
+ cosine 重复检测），写入时打 extraction_source='llm_save_memory' 标签让
UI 角标区分入口来源。
```

### 5.4 Config 速查（chunk 9 + 10 + 11 后）

```yaml
memory:
  long_term_enabled: true
  profile_enabled: true
  embedding:                              # chunk 9 perf
    device: auto                          # auto / cpu / mps
    short_input_threshold: 10
    cache_size: 100
    cache_ttl_seconds: 300
  forgetting_curve:                       # chunk 9
    enabled: true
    threshold: 0.3
    age_decay_factor: 0.01                # 100 天约半权
  extractor:                              # chunk 10
    enabled: true
    interval_seconds: 300                 # 5 分钟一批
    batch_size: 50
    min_confidence: 0.5
    dup_threshold: 0.9
    llm_judge_enabled: false              # 第 5 道 filter 默认关，开启可再降召回率
```

### 5.5 Schema 速查（chunk 9 + 10 + 11 后）

```sql
-- memory 表（chunk 10 commit 1 加 6 列；chunk 9 commit 7 加 2 列）
CREATE TABLE memory (
  id INTEGER PRIMARY KEY,
  user_id TEXT NOT NULL,
  character_id INTEGER,                   -- 检索不再按此隔离（chunk 9）
  type TEXT,                              -- 五分类 fact/instruction/emotion/activity/daily
  content TEXT NOT NULL,
  embedding BLOB,
  created_at TIMESTAMP,
  -- chunk 9
  access_count INTEGER DEFAULT 0,
  last_accessed_at TIMESTAMP,
  -- chunk 10
  extracted_at TIMESTAMP,
  source_turn_id INTEGER,                 -- 触发提取的 chat_history.id
  confidence REAL,                        -- LLM 自评 0-1
  quality_score REAL,                     -- 预留，未来引入
  entry_type TEXT,                        -- 四分类 fact/preference/event/commitment
  extraction_source TEXT NOT NULL DEFAULT 'legacy'
);

-- chunk 10 commit 1
CREATE TABLE memory_extractor_state (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT NOT NULL UNIQUE,
  last_processed_turn_id INTEGER NOT NULL DEFAULT 0,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- users.profile_data（chunk 11 commit 1）
ALTER TABLE users ADD COLUMN profile_data TEXT;  -- JSON
-- profile_summary 列保留作 fallback（README Known Problems #11）
```

---

## 六、TTS 分层设计

### 6.1 当前调用链（v3-B 完成后）

```
ws.py 主流程：
  ChatAgent.stream() yields sentence
    → _parse_emotion(sentence) 第一句锁定 turn_emotion
    → engine = get_tts_engine(character.voice_model)
    → engine.synthesize(sentence, emotion=turn_emotion)
    → 失败返回 None，静默跳过该句（不影响后续文字推送）
  全局开关：config.yaml tts.enabled=false → ws.py 跳过整个 TTS 链路
```

`get_tts_engine()` 是工厂函数，按 `voice_model` JSON 的 `provider` 字段路由到对应 TTSBase 实现。

### 6.2 voice_model JSON Schema（架构层 / 跨 provider）

`character.voice_model` 字段是 TEXT，存任意 JSON。**不存等于沿用全局默认**（config.yaml 里的 cosyvoice longyumi_v3）。前端**不在 Settings 暴露全局 TTS 选项**（避免认知负担）—— **TTS 配置只在 CharacterPanel 上 per-character 提供**。

#### CosyVoice（v3-B 默认 / 已接通）

```jsonc
// 标准音色
{
  "provider": "cosyvoice",
  "voice": "longyumi_v3",
  "instruct_supported": false
}

// fine-tune 音色（v5-T2 训练之后）
{
  "provider": "cosyvoice",
  "voice": "myvoice-xyz123",      // DashScope 训练后返回的 voice ID
  "instruct_supported": true       // fine-tune 通常支持 instruct
}
```

#### Edge-TTS（fallback / 已接通）

```jsonc
{
  "provider": "edge",
  "voice": "zh-CN-XiaoxiaoNeural",
  "instruct_supported": false
}
```

#### GPT-SoVITS（v5-T1 接通 / 多情感参考音频）

SoVITS 的核心特点：**一个角色 = 一对模型 + N 个情感参考音频**。合成时根据当前 turn 的 `emotion` 动态选择对应参考。

```jsonc
{
  "provider": "sovits",
  "name": "Skyler-v1",                                   // 显示标签

  "gpt_path":    "/Users/me/.skyler/voices/skyler-v1.ckpt",
  "sovits_path": "/Users/me/.skyler/voices/skyler-v1.pth",

  "ref_audios": {                                         // 情感 → 参考音频
    "neutral":   "/Users/me/.skyler/voices/refs/neutral.wav",
    "happy":     "/Users/me/.skyler/voices/refs/happy.wav",
    "sad":       "/Users/me/.skyler/voices/refs/sad.wav",
    "angry":     "/Users/me/.skyler/voices/refs/angry.wav",
    "surprised": "/Users/me/.skyler/voices/refs/surprised.wav"
  },
  "default_emotion": "neutral",                          // ref_audios 找不到当前 emotion 时兜底
  "instruct_supported": true
}
```

`SoVITSProvider.synthesize(text, emotion)` 实现：
1. lookup `ref_audios[emotion]`，找不到用 `ref_audios[default_emotion]`
2. 拼参数调本地 SoVITS 推理服务器（`settings.sovits_api_url`）
3. 服务器返回 WAV bytes，原样返回

### 6.3 路径管理

- 绝对路径以 `/` 开头 → 直接用
- 相对路径 → 相对 `~/.skyler/voices/`（v5 阶段定义）
- DashScope voice ID（CosyVoice 系列）不是路径，存原 ID 字符串
- 路径不存在 / 文件读取失败 → log 错误，TTS 返回 None，前端只见文字

### 6.4 前端 CharacterPanel TTS 配置 UI（v3-G' 计划）

**当前现状**：`voice_model` 字段是裸 JSON 文本框，对用户不友好。
**目标设计**：根据 `provider` 下拉动态渲染表单。

```
TTS Provider:  [CosyVoice ▼]
   └─ Voice:   [longyumi_v3 ▼]
      ☐ instruct supported (fine-tune 才打开)
```

**关键约束：UI 下拉只显示真实可用的选项**。当前阶段：

| Provider | 状态 | 当前可选 voices |
|---|---|---|
| CosyVoice | ✅ 后端已接通 | `longyumi_v3` （仅此一项） |
| Edge | ✅ 后端可用，但默认不暴露给用户 | （省略，作为内部 fallback） |
| GPT-SoVITS | 📋 v5-T1 接通后才出现 | （阶段未到） |

也就是说当前 UI 形态：
- Provider 下拉只有 `CosyVoice` 一个选项
- Voice 下拉只有 `longyumi_v3` 一个选项
- 仍然要做下拉而不是固定显示，因为这套架构是为未来扩展准备的 —— v5-T1 接通 SoVITS 后下拉自动多一个 provider，v5-T2 训练完 fine-tune 后 voice 列表自动多几项

**实现要点**：

1. 后端新增 `GET /api/tts/voices` 返回所有可用 voice 列表，按 provider 分组：
   ```jsonc
   {
     "providers": [
       {
         "id": "cosyvoice",
         "label": "CosyVoice",
         "voices": [
           {"id": "longyumi_v3", "label": "龙裕米 v3", "instruct_supported": false}
         ]
       }
       // 未来：sovits provider + 多 voice 自动加进来
     ]
   }
   ```
2. 数据来源：config.yaml 列出每个 provider 的可用 voices；后端启动时扫描 + 缓存
3. CharacterPanel 调这个接口拉真实数据，根据 provider 选择切换二级下拉
4. 用户选择后写回 `character.voice_model` JSON（按 6.2 schema）

这样**架构稳定，UI 自动跟随后端能力变化**，不需要前端硬编码 voice 列表。

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

**架构分离**（v3-E1 Step 5 决策）：

emotion 数据流（解析 → push → store → 监听点）是**模型无关**的基础设施，本仓库已就位：
- 后端 `_parse_emotion`（`backend/agents/chat.py`）解析 `<emotion>X</emotion>` 标签
- 后端 ws.py 在每轮第一个 chunk 命中后 `send_json({"type":"emotion","value":<英文枚举>})`
- 前端 `useWebSocket` 收到后写 `store.currentEmotion`
- 前端 `Live2DCanvas` useEffect 订阅 `currentEmotion` 作为绑定 hook 入口

emotion 视觉绑定（监听点 → Live2D 参数 / expression）是**模型相关**的配置层，由 `frontend/src/config/live2d.ts` 的 `emotionMap` 控制：

- 自带 `.exp3.json` 的模型：`emotionMap[key] = { type: 'expression', name: 'F01' }`，监听点调 `model.expression()`
- 无 expression 的模型（如 Hiyori）：`emotionMap[key] = { type: 'params', params: [{id, value}, ...] }`，监听点遍历调 `setParameterValueById`

v3-E1 Step 5 emotionMap 留空，Live2DCanvas 监听点仅 `console.log` 占位。待 v3-E2 换上目标模型（Hiyori 是临时模型，没有 expression 文件，调参对临时模型无意义）后填充 emotionMap，监听点改成调用对应绑定 —— **代码改动只在 emotionMap 一个文件 + 监听点 useEffect 内部**，数据流不动。

---

## 十四之A、Live2D 架构（v3-E1 + v3-E2 完成后定型）

经过 v3-E1 主线（8 commit）+ v3-E2 多模型（9 commit）走完后，Live2D 架构按"模型无关层 / 模型相关层 / 运行时层"三段式分离。任何后续模型替换、emotion / motion 扩展都按这个分层来。

### 模型无关层（核心 pipeline，跨模型 / 跨 SDK 不变）

不论使用哪个 Live2D 模型（Hiyori / 八重神子 / 自制 Momo / ...）或哪个 SDK（pixi-live2d-display / 未来的 Cubism 5 fork / Cubism 2 runtime），以下数据流都保持不变：

- **后端 `chat.py` 解析 LLM 输出标签**：
  - `<emotion>X</emotion>` —— per-turn 一次锁定（`re.match` 锚定开头）
  - `<motion>X</motion>` —— per-segment 多次触发（每段独立解析）
  - `<thinking>X</thinking>` —— 内心独白（剥离不显示给 TTS / 不持久化）
- **`ws.py` push 给前端**：`{"type": "emotion"|"motion"|"thinking", "value": ...}`
- **前端 store**：`currentEmotion` / `currentMotion` / `currentThinking`，新轮自动 clear
- **`Live2DCanvas` useEffect 监听**：currentEmotion → `runtime.setExpression`；currentMotion → `runtime.startMotion`

### 模型相关层（per-character 配置，DB 字段）

每个 character 行有三个 JSON 字段（v3-E2 chunk 4 加列 `0397b72`）：

- **`emotion_map_json`** —— `Record<string, string>`，emotion 词 → Live2D expression 名
- **`motion_map_json`** —— `Record<string, MotionEntry>`，logical motion 名 → `{group, index}`
- **`hit_area_map_json`** —— `Record<string, string>`，hit area Name → motion group

NULL / 空 / parse 失败 → 前端 `resolveCharacterMaps` 回退到 `frontend/src/config/live2d.ts` 全局默认（v3-E1 给 Hiyori ship 的 `motionMap` 16 个中文键 → Flick* group）。

`motion_map_json` 的特殊键：``"Tap"`` 是"点击 Live2DCanvas 即时反馈"的 logical motion。Hiyori 默认 motionMap 没这个键 → `handleTouch` 走 v3-E1 写死的 `'Tap'` group + random[0,1] 回退；八重的 `motion_map_json` 注册了 ``"Tap": {group: "Start"}`` → 走 per-character override。

### 运行时层（SDK 抽象，v3-E2 chunk 5 引入）

`frontend/src/lib/live2d/runtime.ts` 定义 `Live2DRuntime` 接口（6 方法签名严格 type，无 any）：

```typescript
interface Live2DRuntime {
  loadModel(container, modelUrl): Promise<ModelHandle>;
  unloadModel(handle): void;
  setMouthOpen(handle, value: number): void;        // 0~1, lip sync
  startMotion(handle, group, index): boolean;
  setExpression(handle, name): boolean;             // v3-E3 视觉绑定通道
  hitTest(handle, x, y): string | null;             // hit-area 路由预留
}
```

实现：

- **`PixiCubism4Runtime`**（`frontend/src/lib/live2d/runtimes/pixiCubism4.ts`）—— 包 pixi-live2d-display + Cubism 4 Core，moc3 ver ≤ 4
- **`getRuntime(hint?)` 工厂**（`registry.ts`）—— 当前只返回 `new PixiCubism4Runtime()`；moc3 ver > 4 输出 console.warn
- **`Live2DCanvas` 组件 0 直接 import pixi.js / pixi-live2d-display**

未来 Cubism 5 fork 接通 → 加 `PixiCubism5Runtime` + 改 `getRuntime` 分支；组件层 0 改动。

### 模型限制速查表

| 模型 | moc3 ver | .exp3.json | hit areas | 接入状态 |
|---|---|---|---|---|
| **Hiyori**（v3-E1 默认） | 3 (SDK 4.0) | ❌ | 0 | ✅ 全功能（除 emotion 视觉）|
| **八重神子 BCSZ1.1**（v3-E2 chunk 6）| 3 (SDK 4.0) | ❌ | 8 | ✅ 渲染 + idle + 触摸 + motion + lip sync；hit-area 路由 backlog |
| 加藤惠（外部资产）| - | ✅ 6 个 | - | ❌ Cubism 2 `.moc`，pixi-live2d-display 不支持 |

emotion 视觉绑定（`runtime.setExpression`）的代码路径在 v3-E2 chunk 7 已就绪。等有 `.exp3.json` 的模型接入后立刻激活，组件 / runtime 不需要改。

### Motion sound policy

模型 motion3.json 可能引用配音 wav（八重 BCSZ1.1 的 6 个"早上好 / 中午好 / 不变 / 无聊 / 夜晚 / 初见" motion 都带）。pixi-live2d-display 默认看到 `Sound` 字段会自动播这个 wav。Skyler 的语音输出统一由 LLM + TTS pipeline 驱动，motion-bundled sound 与 TTS 同时跑会出现双 audio 流重叠。

**v3-E2 patch 决定**：通过 pixi-live2d-display 模块级 `config.sound = false` 全局禁用 motion-bundled sound（设置点见 `frontend/src/lib/live2d/runtimes/pixiCubism4.ts` 顶层）。模型自带 wav 不再播放，所有声音走 TTS。

公开 `model.motion(group, idx, priority)` 在本版 pixi-live2d-display 没有 `audio` 第 4 参数（types/index.d.ts:1692），无法 per-call 关闭，只能走全局 flag。

未来路径：per-character toggle —— 鼠标点击触发的 motion 允许播原声 wav（保八重等模型的演出价值），LLM 标签触发的 motion 不播（让 TTS 独占）。需要 `Live2DRuntime.startMotion` 接口加 `playSound?: boolean` + 区分调用路径。详见 ROADMAP backlog "Motion-bundled sound per-character toggle"。

---

## 十四之B、Tech Debt

### characters 双源真相（v3-G 后期 / v4 处理）

**当前现状（v3-E1 角色修复 `ba2efd2` 后）**：

DB `characters` 表负责 UI 切角色 + per-character 隔离（chat_history / memory / voice_model / live2d_model + v3-E2 加的 `*_map_json`）；`config/characters.yaml` 负责 prompt_manager + `switch_character` LLM tool。`_build_messages` 优先从 DB 拿 persona，失败 / 没 character_id 才回 YAML —— 这是**方案 B**。

**张力点**：UI 切角色走 DB id 命中先；LLM tool 切角色改 prompt_manager state 但前端仍带原 character_id，DB persona 仍命中先 —— LLM tool 路径事实上失效。

**方案 C 彻底统一**：

- 删 `characters.yaml`
- DB 是单一真相源
- migration 把 YAML 默认 / Momo 等条目灌进 DB
- `switch_character` LLM tool 按 name 查 DB
- prompt_manager 改成 DB-backed

### Cubism 5 切换路径（远期，pixi-live2d-display issue #118 自 2023-10 未修复）

`Live2DRuntime` 抽象层 + `RuntimeRegistry` 工厂已经预埋切换点。三种走向：

1. **优先**：等 pixi-live2d-display 社区合并 Cubism 5 fork（GitHub PR 跟踪中），加 `PixiCubism5Runtime` + 改 `getRuntime(hint)` 按 `hint.moc3_version >= 5` 分支
2. **备选**：直接接官方 Cubism Web SDK 5（不用 pixi 桥），写 `Cubism5Runtime` 实现接口
3. **保底**：Cubism Editor 用 4.x 兼容选项重新导出 .moc3，永远停在 ver ≤ 4

抽象层让任一选择都不动 `Live2DCanvas` 组件代码。

### API helper 文件 ≥ 5 时迁移到 `src/api/`

当前 API 调用集中在 `frontend/src/lib/config.ts`（fetchCharacters / fetchMessages / ...），v3-E2 加了 `frontend/src/lib/live2d.ts`（fetchLive2DModels）。继续往 `lib/` 加，到 5 个左右就该升级目录结构 —— 拆成 `src/api/{characters,conversations,live2d,...}.ts`，每个 domain 一个文件。当前 2 个文件不值得拆。

### `themes.css` 加 success / error / warning 语义色 token

v3-E2 commit 3b CharacterPanel 兼容性 badge 用 `var(--color-accent)` 做绿色 OK badge，用 `var(--color-bg-elevated)` + border + AlertTriangle 图标做警告 badge —— 因为 themes.css 没有专门的 success / error / warning 色。目前可控，但未来 toast 系统 / 表单验证错误提示等场景出现时统一加：

```css
--color-success: ...;
--color-success-bg: ...;
--color-error: ...;
--color-error-bg: ...;
--color-warning: ...;
--color-warning-bg: ...;
```

8 套主题都要加，工作量约 1 小时。

### Live2D hit-area 路由真接通

v3-E2 chunk 6 给八重 (id=2) 的 `hit_area_map_json` 写好了 8 个 HitAreas → Tap* group 的契约，但 `Live2DCanvas.handleTouch` 仍走 canvas 整体点击。接通需要：

1. `handleTouch` 拿到 PIXI 局部坐标（`event.clientX/Y - rect` + 模型 scale 反向计算）
2. 调 `runtime.hitTest(handle, x, y)` 拿 hit area 名
3. 在 `maps.hitAreaMap` 里查到 motion group → `runtime.startMotion`

工作量约半天。当前点击全 canvas 触发"Tap" logical motion 已经能用，hit-area 是 nice-to-have。

### 加藤惠 Cubism 4 重制版搜寻（个人 backlog）

现有加藤惠资产（`/Users/liujunhong/Desktop/program/加藤惠live2d/`）是 Cubism 2 `.moc` + `.mtn` + `.exp.json`，`tools/check_moc3_version.py` 报 magic 不匹配 FAIL。要么找一个 Cubism 4 重制版（社区 / nizima / BOOTH），要么放弃这套资产。**6 个 expression 文件**对 v3-E3 emotion 视觉绑定本来很有价值，但格式锁死无解。

详见 ROADMAP §技术债 / v3-E2 backlog。

---

## 十四之C、Architectural Decisions

### 网易云音乐自动播放——封存

**决策**：v3-H chunk 1 已实现 weapi client + 12 capability（数据查询 + 媒体控制），但自动播放链路（orpheus URL Scheme + nowplaying-cli）在测试环境不稳定，封存待重新设计。

**架构遗产**：
- weapi 加密层、cookie 配置、capability 抽象全部保留
- 任何后续音乐方案（自解码 / 客户端 hook / 第三方播放器）都可复用

---

## 十五之B、Proactive Engine 架构（v3-G chunk 2 起）

通用主动陪伴流水线。基础假设：每条主动消息走的都是同一条管道（拉上下文 →
ChatAgent 流式生成 → WS push → DB 持久化），区别只在"什么时候触发 + 触发时
塞什么 system prompt"。这两件事抽到 ``ProactiveTrigger``，引擎本身 trigger-
agnostic。

### 设计哲学：模式 A vs 模式 B（v3-F' 设计哲学序言）

proactive trigger 分两类，交互哲学根本不同：

* **模式 A 单方面播报**：cron → 整段内容推送。
  适合"非问也得通知"场景：重要日历前 5 分钟提醒、闹钟、紧急 webhook。
  代表：``MorningBriefingTrigger`` —— cron 9 点直接播 200-300 字完整简报。
* **模式 B 邀请对话**：cron → 轻触发短问候 → 等用户响应 → 用户第一句话
  trigger 真内容作为对话回复。
  适合大多数生活节奏 trigger：早晨 / 饭点 / 睡前。用户决定要不要听 / 听
  多少 / 切到别的话题。
  代表：``WakeCallBriefingTrigger`` —— cron 8 点 8-15 字短问候，用户回
  ``"嗯"`` / ``"早，今天怎么样"`` / ``"再睡 5 分钟"`` 决定 stage 2 内容。

**默认 v3-F' 所有生活节奏 trigger 走模式 B**。理由：模式 A 是骚扰，模式 B
是陪伴。只有用户已经付费"必须听到"的内容（日程提醒、闹钟）才走 A。

``config.proactive.mode`` 三选一互斥（``wake_call`` / ``morning_briefing``
/ ``off``）决定哪个 trigger 注册到 cron_scheduler，避免两个都跑撞车（用户
8 点叫醒 + 9 点简报会被叫两次）。

### 流水线

```
   trigger (cron/interval/event)
            │
            ▼
   ProactiveTrigger.build_system_prompt(character) ─┐
   ProactiveTrigger.resolve_capabilities()         │  (聚合阶段)
            │                                       │
            ▼                                       │
   resolve target character_id ◀───────────────────┤
   (override > recent user turn > Momo fallback)   │
            │                                       │
            ▼                                       │
   get_or_create conversation                       │
            │                                       │
            ▼                                       │
   ChatAgent.stream(payload)                        │
   payload = {                                      │
       text:     "[proactive trigger]",            │
       context.extra_system: build_system_prompt,   │
       context.enable_search: trigger.enable_search,│
       character_id: target_char_id,                │
   }                                                │
            │                                       │
            ▼                                       │
   sentence stream → 并发 TTS task queue           │  (生成 + 传输)
            │                                       │
            ▼                                       │
   ConnectionManager.push                           │
       text_chunk   {proactive: true, ...}         │
       audio_chunk  {proactive: true}              │
       emotion / motion / thinking (per-turn)       │
       done         {proactive: true}              │
            │                                       │
            ▼                                       │
   add_chat_history(                               │  (持久化)
       role='assistant',                           │
       kind='proactive',                           │
       proactive_trigger=trigger.name,              │
   )                                                │
            ▼
   profile_summary 重写：kinds=['normal'] 白名单 ⇒ 自动排除（v3-E1 Step Z.2 已落地）
```

### ProactiveTrigger 抽象（``backend/proactive/engine.py``）

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| ``name`` | str | ✓ | 触发器唯一名字。写入 ``chat_history.proactive_trigger`` + cron job id；前端按它映射 toast / 灰字前缀 label |
| ``cron_expr`` | str \| None | 三选一 | APScheduler crontab 表达式（5 段） |
| ``interval_seconds`` | int \| None | 三选一 | 固定间隔触发 |
| ``event_source`` | str \| None | 三选一 | 外部事件源标识（webhook 等，本 chunk 占位） |
| ``enable_search`` | bool | — | 是否启用 LiteLLM model-native web search |
| ``build_system_prompt(character)`` | async ⇒ str | ✓ | 注入到 ``context.extra_system`` 的本次触发系统提示 |
| ``resolve_capabilities()`` | async ⇒ list[str] | — | 推荐 LLM 调的 capability hint（hint 用，不裁剪 ToolRegistry） |

### 模式 B (wake_call) 状态机（chunk 2.6 起）

模式 B 是个跨 turn / 跨进程的状态机，比模式 A 复杂。状态主要靠
``pending_briefings`` 表持久化。

```
   cron 0 8 * * * Asia/Tokyo
      │
      ▼
   ┌──────────────────────────────────────────────────────────────┐
   │ Stage 1 — engine.run_wake_call_trigger                       │
   │  ① aggregate_briefing_data(user_id, char_id)                │
   │     → time + calendar.today_events + list_memories(instruction) + city
   │     (weather / news 不缓存，留给 stage 2 现查更新鲜)           │
   │  ② INSERT pending_briefings (consumed_at=NULL, ttl=30min)   │
   │  ③ ChatAgent.stream(extra_system=8-15字叫醒, skip_short_term)│
   │     → push 短 TTS 带 proactive=true, proactive_trigger=wake_call
   │  ④ chat_history kind='proactive' proactive_trigger='wake_call'
   │  ⑤ short_term_memory.add (engine 双写契约)                   │
   └──────────────────────────────────────────────────────────────┘
      │
      ▼  (用户开始 ASR 或文字 — 任意 turn)
   ┌──────────────────────────────────────────────────────────────┐
   │ Stage 2 — chat.py _build_messages 自动注入                    │
   │  ① 读 last_assistant_turn → 必须 proactive_trigger='wake_call'│
   │  ② get_active_pending_briefing → 未消费 + 未 TTL 过期         │
   │  ③ system prompt 末尾追加 _WAKE_CALL_STAGE2_ADDENDUM         │
   │     (含用户原话 + 自适应规则 + briefing_data_json 缓存)       │
   │  ④ consume_pending_briefing (consumed_at = utcnow，          │
   │     consume-on-detect 语义)                                  │
   └──────────────────────────────────────────────────────────────┘
      │
      ▼
   LLM 按用户响应风格自适应输出（4 类）：
      - 简短模糊（嗯/早/嗯嗯）  → 50-80 字精简简报
      - 好奇精神（早，今天怎么样）→ 180-260 字完整简报 + enable_search 查天气/新闻
      - 拒绝起床（再睡/还早/困）→ ≤25 字安抚 + 调 proactive.snooze_wake_call(minutes=N)
      - 切换话题（直接问别的）  → 优先回应当前话题，丢弃简报内容
      │
      ▼
   chat_history kind='normal' (assistant 简报回复 — **故意 normal**)
      ⚠️ 关键：profile_summary 重写白名单 kinds=['normal'] 应该看见这条
         真对话，所以不能标 'proactive'。
```

**为什么是 consume-on-detect 而不是 consume-on-success**：
- 简单：不需跨模块协调（_build_messages → ws.py turn 完成后通知）
- 容错：如果 turn 失败，用户重发的下一条消息 pending 已消费 → fallback
  普通短回复，对用户更可预期（避免连续两次都触发简报内容）

**stage 1 必须 skip_short_term**：早期实测 LLM 受短期记忆里历史长简报
的 tone 影响，会输出 100+ 字 wake call。``payload.context.skip_short_term``
让 ``_build_messages`` 跳过 ``short_term_memory.get(user_id)`` 历史拼接，
LLM 仅在 system prompt + persona 上下文里生成 8-15 字叫醒。stage 2 仍走
全量短期记忆（用户响应需要历史 context）。

**避免无限递归**：``_build_messages`` 自己也跑 stage 2 探测。如果 stage 1
通过 ChatAgent.stream 又进 _build_messages，会重复注入 addendum。哨兵
``WAKE_CALL_STAGE1_SENTINEL`` 嵌在 stage 1 的 extra_system 开头，
_build_messages 检测到则跳过 addendum 探测。

### Snooze 子系统（chunk 2.6 起）

``proactive.snooze_wake_call(minutes)`` capability：

* APScheduler ``DateTrigger`` 注册一次性 job（``run_date=now+minutes``），
  **不**改 cron 主配置 —— job_id 用 ``wake_call_snooze_<epoch_ms>`` 避免
  并发命名冲突
* **冲突避免**：算 snooze 时间若超过下一次正常 wake_call cron
  （``cron_scheduler.get_job(WAKE_CALL_CRON_JOB_ID).next_run_time``），跳过
  snooze（避免重复叫早）
* **range 限制** 5-120 min；LLM 越界值或非 int → 用
  ``config.proactive.wake_call_briefing.default_snooze_minutes``（默认 30）
* ``user_visible=False`` —— 不在 UI 能力面板出现（减少 tool surface 噪音）

### v3-F' = engine 的 trigger pack

``v3-F'`` 主动对话路线（饭点 / 睡前 / 长闲 / 心情主动检查）在本 chunk 落地
后**不再是 engine 工程**，而是写若干个 ``ProactiveTrigger`` 子类。每个 trigger
按本节签名写 ~50 行（一个 cron / interval + 一段 system prompt + 推荐
capability hint），engine 自动接通完整 ChatAgent pipeline。

| v3-F' trigger 候选 | 调度 | system prompt 关注点 |
|---|---|---|
| ``meal_lunch`` / ``meal_dinner`` | cron 12:00 / 18:00 | 关心吃了什么，调 ``list_memories`` 拿口味偏好 |
| ``evening_wind_down`` | cron 22:00 | 一天总结 + 睡前关心，调 ``calendar.today_events`` 复盘 |
| ``long_idle`` | interval 30min（条件：last user turn > 2h） | 主动开口，话题源自 profile_summary |

工程量 = 每个 trigger 大约半天到一天。engine 本身零改动。

### 协议字段（向后兼容）

```json
{ "type": "text_chunk",  "content": "...",
  "proactive": true, "proactive_trigger": "morning_briefing" }
{ "type": "audio_chunk", "content": "<base64>",
  "proactive": true, "proactive_trigger": "morning_briefing" }
{ "type": "done",        "proactive": true, "proactive_trigger": "morning_briefing" }
```

老前端对未知字段静默忽略。

### 已知限制 / Backlog

* ``resolve_capabilities`` 当前只作 prompt-time hint，不真正裁剪传给 LLM 的
  ``tools[]``。LLM 仍可见所有 CHAT_AGENT consumer capability —— 为多调几个
  capability 的轻负担换 chat.py 零改动。后续若强裁剪场景出现（如 trust /
  cost 隔离），再扩展 ChatAgent 接受 per-call ``tool_subset``。
* 多 trigger 同时触发的 audio / emotion 状态隔离尚未验证（chunk 2.6 起
  ``mode`` 字段互斥决定哪个 trigger 上 cron，避免实测撞车；并发场景延后
  到 v3-F' 多 trigger 同时上线时再做）。
* **Qwen3.6 模型 snooze tool call 不稳定**（chunk 2.6 实测）：用户说"再睡 5
  分钟"时，Qwen 有时把 ``proactive.snooze_wake_call`` 调用以 Anthropic XML
  格式发到 text content，而非 OpenAI function_call delta。能力路径已验证
  正确（mock test 19/19 过 + 单独调 snooze capability 注册一次性 job 工
  作），但端到端 LLM 真调用率与模型相关。Backlog：在 prompt addendum 加更
  强烈的 "MUST call tool by function-calling, NOT text" 引导；或测试切到
  Qwen Max / Claude 看是否更稳定。
* **pending_briefings 后台清扫**：consumed / 过期行不自动删，靠表逐渐增
  长。一年后估算几千行 ⇒ 索引仍快。后续可加 daily cleanup job 删 30 天
  前的行；本 chunk 不做。
* **wake_call 用户多人场景**：当前 ``user_id`` 用 ``config.default_user_id``
  写死。多用户后端时需扩展为 per-user trigger 注册。

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

## 十五之A、Capability Registry 架构（v3-G chunk 0 起）

v3-G chunk 0 引入的统一注册中枢。在原有 v3-C 的 ``ToolRegistry``（仅承载
LLM tool calling 的 name → callable + OpenAI schema）之上加一层**富 metadata**
（display_name / category / icon / consumers / trigger_modes / health_check），
让前端"能力面板" + 后端 cron 调度 + 外部 webhook 三个消费者各看自己关心的字段。

### 三个消费者 + 注册流程

```
                                   ┌────────────────────────────┐
                                   │   @register_capability     │
                                   │   (decorator @ import time)│
                                   └────────────┬───────────────┘
                                                │
                                                ▼
                              ┌────────────────────────────────┐
                              │   CapabilityRegistry           │
                              │   (单例 dict[name, Capability])│
                              └────┬───────────┬───────────────┘
                                   │           │
                                   │           │  if Consumer.CHAT_AGENT in consumers
                                   │           │  → 派生 OpenAI schema → 同步 ToolRegistry.register
                                   │           │  → ChatAgent _get_all_tools() 自然捕获，零改 chat.py
                                   │           ▼
                                   │       ┌─────────────────┐
                                   │       │  ToolRegistry   │  (v3-C 起就有)
                                   │       └────────┬────────┘
                                   │                │
                                   │                ▼
                                   │            ChatAgent ── LiteLLM tool calling
                                   │
       ┌───────────────────────────┼─────────────────────────────┐
       │                           │                             │
       ▼                           ▼                             ▼
  Consumer.SCHEDULER          Consumer.WEBHOOK          GET /api/capabilities
  ↓                           ↓                         ↓
  cron_scheduler              n8n 等外部触发            前端 CapabilityPanel
  (APScheduler 单例)          (Bearer + HMAC)           (按 category 卡片)
  cron_expr / interval        WEBHOOK_HANDLERS          + health_check 状态点
  schedule_cron()             dict 路由
```

### 核心数据契约

```python
# backend/capabilities/registry.py
class Consumer(str, Enum):
    CHAT_AGENT = "chat_agent"     # ChatAgent 主动 LLM tool calling
    SCHEDULER  = "scheduler"       # cron / interval 定时
    WEBHOOK    = "webhook"          # n8n / 外部事件触发

class TriggerMode(str, Enum):
    ON_DEMAND     = "on_demand"
    SCHEDULED     = "scheduled"
    EVENT_DRIVEN  = "event_driven"

@dataclass
class Capability:
    name: str                              # 唯一 ID, e.g. "time.now"
    display_name: str                      # 中文展示
    description: str                       # 给 ChatAgent 看的 LLM-tool desc
    category: str                          # system / calendar / music / media / creative
    consumers: list[Consumer]
    trigger_modes: list[TriggerMode]
    handler: Callable                      # async；必须接受 user_id 或 **_kwargs
    icon: str = "circle"                   # lucide-react 图标名
    user_visible: bool = True
    health_check: Optional[Callable] = None
    parameters_schema: Optional[dict] = None  # JSON Schema for tool calling
```

### 路由原则（哪些 tool 给谁）

| capability 类型 | consumers 应包含 | 例子 |
|---|---|---|
| 用户问答型（"现在几点 / 帮我搜一下 / 切换角色"） | `CHAT_AGENT` | `time.now` / 网易云 search / 切换角色 |
| 定时任务型（"每天早上 9 点 / 每 15 分钟检查一次"） | `SCHEDULER` | 每日简报 / 健康提醒 / 角色亲密度衰减 |
| 外部事件型（"日历事件触发 / 微信消息触发 / Bilibili 新视频"） | `WEBHOOK` | n8n trigger 派发 |
| 跨界（既能 LLM 主动调，也能 cron 触发） | 多个 | `time.now` 既给 ChatAgent 又给 SCHEDULER 拿权威时间 |

**约定**：

* CHAT_AGENT consumer 必须配 `parameters_schema`（哪怕是空 object schema），
  让 LLM 知道怎么调；非 CHAT_AGENT consumer 可省。
* CHAT_AGENT-aware capability handler **必须**接受 `user_id` kwarg（ChatAgent
  一定注入）。capability 本身不需要时用 `**_kwargs` 兜住。
* `health_check` 是可选的；返回 ``{"status": "healthy"|"warn"|"error", "error"?}``，
  也支持简短形态（True / "warn" / 抛异常）。

### n8n / 外部 webhook 集成

* 通道：``POST /api/webhooks/n8n/{trigger_name}``
* 鉴权：双因子 = Bearer token + HMAC SHA256 over **raw body bytes**
* trigger_name 注册在 ``backend/routes/webhooks_api.py`` 的 ``WEBHOOK_HANDLERS`` dict
* handler 异步 dispatch 立即 ack，避免 n8n 30s 超时
* 详细对接（curl 验证 / n8n credentials 配置）见 ``docs/n8n-integration.md``

### scheduler 双轨

* ``backend/scheduler/task.py`` AlarmScheduler —— 30s 轮询 DB 触发到期 alarm（v2.5 起）
* ``backend/scheduler/cron.py`` cron_scheduler —— APScheduler 单例，cron / interval 任务
* ``backend/scheduler/briefing.py`` —— 起床简报 cron 任务（v3-G chunk 1 起）

两套 scheduler 各自 lifecycle，main.py lifespan 顺序起停。timezone 共用
``config.yaml`` 顶层 ``scheduler.timezone``（缺省 Asia/Tokyo）。

### 两层架构：integrations vs capabilities（v3-G chunk 1 起）

接入第三方服务时严格走两层：

```
backend/integrations/<service>.py        ──┐
  - OAuth flow / token refresh             │  底层 client：认证 + 重试 + 健康检查
  - API call wrappers                      │  **不带** @register_capability
  - tenacity 重试                          │  纯 Python module，可独立 mock 测
  - health_check() 函数                   ──┘
        ▲
        │ 被调用
        │
backend/capabilities/<service>.py        ──┐
  @register_capability(...)                │  上层 capability：5 行装饰器即接入
  async def some_action(**_kwargs):        │  category / consumers / trigger_modes
      return await client.some_call(...)   │  parameters_schema / icon / health_check
                                          ──┘
```

**第一次落地**（v3-G chunk 1）：``backend/integrations/google_calendar.py`` 是底
层 client；``backend/capabilities/calendar.py`` 注册 ``calendar.today_events`` /
``calendar.upcoming_events`` 两个 capability，handler 仅 1-3 行，调底层 list_events_in_range。

**好处**：

* 底层 client 改实现（换 SDK、加重试策略、调 scope）不动 capability metadata
* capability 增减 / 改 description 不动 client
* 单元测试在 integrations 层 mock SDK；capability 层只测 metadata 注册和参数 clamping
* 后续接入 网易云 / Bilibili / Pollinations 都按这个 pattern：先底层 client，再装饰器

### Google Calendar OAuth flow

```
1. 用户在 Google Cloud Console 下载 OAuth desktop client.json
2. 手工放到 ~/.skyler/google_credentials.json
3. 前端能力面板点 [连接 Google] → POST /api/integrations/google/auth
4. 后端 asyncio.to_thread(run_oauth_flow):
   - InstalledAppFlow.from_client_secrets_file(...)
   - flow.run_local_server(port=0)        ← 启动本地 HTTP server，浏览器自动打开
   - 用户在 Google 页面同意
   - Google redirect 到本地 server，flow 拿到 token
   - _save_credentials() 写 ~/.skyler/google_token.json
5. 之后所有 list_events_in_range 调用：
   - _load_credentials() 读 token.json，过期就 refresh，仍失败返 None
   - googleapiclient.discovery.build("calendar", "v3", credentials=creds)
6. 健康检查：测试拉 next 24h 事件；网络/API 错都降级成 warn（国内常态）
```

scope 升级（如未来要加创建事件能力）必须先 revoke 当前 token，再重新 OAuth flow，
否则 Google API 会返 403 insufficient scope。

### 日历多数据源架构（v3-G chunk 1.6 起）

接入 Apple Calendar 后日历能力变成**双源**。设计原则：用户视角统一，工程实
现路由层瘦：

```
                LLM tool surface (CHAT_AGENT)
        ┌──────────────────────────────────────────────┐
        │   calendar.today_events    (router)          │  ← LLM 通常调这两个
        │   calendar.upcoming_events (router)          │
        │                                              │
        │   apple_calendar.today_events                │  ← Apple 直接，给"用 Apple 看"
        │   apple_calendar.upcoming_events             │     这种明确意图
        │   apple_calendar.create_event                │  ← Apple 写（chunk 2.5 入口）
        │   apple_calendar.delete_event                │
        │                                              │
        │   google_calendar.* 不在 LLM 视野            │  ← 高级用户路径
        │     （仅 user_visible + SCHEDULER consumer） │
        └──────────────────────────────────────────────┘
                            │
                            │  router resolves
                            ▼
                  config.yaml calendar.default_source
                            │
                  ┌─────────┴─────────┐
                  │                   │
                  ▼                   ▼
       apple_calendar.today_events  google_calendar.today_events
       (实际 capability handler)    (chunk 1 的 OAuth 路径)
                  │                   │
                  ▼                   ▼
       backend/integrations/        backend/integrations/
       apple_calendar.py            google_calendar.py
       (EventKit pyobjc)            (Google API + tenacity 重试)
```

**改 source 切换**：仅改 `config.yaml.calendar.default_source: apple|google`
重启即生效。简报模块（`from backend.capabilities.calendar import today_events`）
不知道路由存在，自动跟随。

**chunk 1 → chunk 1.6 的 namespace rename**（无破坏性）：

* `backend/capabilities/calendar.py`（chunk 1，直接调 Google）
  → `backend/capabilities/google_calendar.py`（chunk 1.6 git mv 保 history）
* `calendar.today_events` / `calendar.upcoming_events`（chunk 1 cap name）
  → `google_calendar.today_events` / `google_calendar.upcoming_events`（chunk 1.6 重命名）
* 新建 `backend/capabilities/calendar.py`（chunk 1.6 router），占用旧的 `calendar.*` 名字

**为什么不全合并到 calendar.* 一个 cap**：四个原因——

1. 高级用户场景："用 Google 看一下" / "对比 Apple 和 Google" 需要直接 cap
2. SCHEDULER 任务可以锁定 source（"我的简报永远走 Apple"）
3. 健康面板要显示每个 source 独立状态（一个挂了另一个还能用，UI 要看得到）
4. 路由层不带读写副作用，纯 dispatch + 错误兜底，逻辑简单容易测

### MCP 双向架构（v3-G chunk 1.5 起）

CapabilityRegistry 是统一抽象核心，三种来源 + 三种消费者形成完整的 MCP 双
向网格：

```
                            ┌──────────────────────────────────────────────┐
                            │           CapabilityRegistry                 │
                            │   单例 dict[str, Capability]                  │
                            │   metadata: source_server / expose_via_server│
                            └────┬────────────────┬───────────────────┬────┘
                                 │                │                   │
        ┌────────────────────────┘                │                   └─────────────────────────────────┐
        │  来源 1：import-time                    │  来源 2：runtime               来源 3：聚合（无新数据）  │
        │  @register_capability                   │  register_runtime               list_for_consumer       │
        │  decorator @ python import              │  外部 MCP server 派生           CHAT_AGENT 子集          │
        │  内置 capability                        │  ext.<server>.<tool>           + expose_via_server 过滤  │
        │  (time.now / calendar.* / …)            │  (filesystem / brave-search …)                          │
        ▼                                         ▼                                                         ▼
                                  ┌──────────────────────────────────────────┐
                                  │             ToolRegistry                 │
                                  │  ChatAgent.acompletion(tools=...)        │
                                  └──────────────────────────────────────────┘
                                                  ▲
                                                  │ ChatAgent 主动 LLM tool calling
                                                  │
                                  ┌──────────────────────────────────────────┐
                                  │             ChatAgent                    │
                                  └──────────────────────────────────────────┘

  消费者 1：内部 ChatAgent（已有 chunk 0）
  消费者 2：外部 MCP server (POST /mcp)  ← Skyler 自身 server.py 暴露 ←─ 按 expose_via_server 过滤
  消费者 3：APScheduler / Webhook（chunk 0 已有）

  外部 LLM 工具 (Claude Desktop / Cursor / Claude Code) → POST /mcp + Bearer →
  Skyler.MCP server.list_tools() → 派生 list[Tool] → 返还给上游 LLM 看见的 tools
  上游调 → POST /mcp → Skyler.MCP server.call_tool() → 路由到 capability.handler

  Skyler 内部 ChatAgent 调外部 MCP server tool：
  ChatAgent → ToolRegistry.call("ext.fs.read_file", ...) → capability.handler （即 closure）
  → ClientSession.call_tool("read_file", args) → JSON-RPC over stdio → 子进程响应
```

**为什么"统一抽象"很关键**：

* 加新能力的成本极低 —— 不论来源是 Python 函数、外部 MCP server、还是其他 SDK 内置工具，写一份 capability metadata 即可被 ChatAgent / Scheduler / 外部 LLM 三方同时看见
* 命名空间隔离：内置 = `category.action`（time.now / calendar.today_events），外部 = `ext.<server>.<tool>`，永不撞名
* 暴露策略集中在 `metadata.expose_via_server` 一个字段 —— 默认全暴露，需要时候按 server 关掉（防 API 配额泄露 / 防代理混乱）
* health check / category / icon 等 UI 元数据不改 capability handler 接口

---

## 十五之C、角色状态系统（v3-G chunk 3b 起）

### 设计目标

让 Momo 有"被记得"的累积感：跟用户聊得多了 mood / intimacy 会变；长期不
聊会自然冷淡；下次聊天 prompt 里能看到当下的状态、保持人设一致性。

### mood vs emotion —— 两套独立不冲突

| 概念 | 来源 | 时间尺度 | 持久性 | 用途 |
|---|---|---|---|---|
| **emotion** (chunk D) | LLM `<emotion>` 标签，per-turn 第一句锁定 | 瞬时（这一句） | 内存 | TTS 语调 / Live2D 表情 |
| **mood** (chunk 3b)   | LLM `<state_update mood>` 标签 | 跨 turn 累积 | DB | 状态条显示 / 后续 system prompt 注入 |

emotion 切换无成本（LLM 任意一句可换）；mood 切换是"今天整体心情"的反映，
LLM 主动决定（当用户表达情绪 / 分享好消息时）。两者在同一句 LLM 输出里
都能出现：``<emotion>happy</emotion><state_update mood="happy" intimacy_delta="+1" />正文…``

### `<state_update>` 标签协议

```
<state_update mood="happy" intimacy_delta="+1" thought="觉得用户今天很努力" />
```

可用属性（全部可选）：

| 属性 | 类型 | 含义 | 写入校验 |
|---|---|---|---|
| ``mood`` | enum | happy / sad / curious / calm / excited / tired / neutral 七选一 | 不在 enum 内 → 静默忽略（不抛错，避免 LLM 拼错时整轮挂掉） |
| ``intimacy_delta`` | int | 本轮想要变动的亲密度 | clamp 到 [-2, +2] per turn（防 LLM 滥用 +99 一次刷高），叠加后再 clamp [0, 100] |
| ``thought`` | str | 当下心境短句 | 截断到 60 字 |
| ``activity`` | str | 当下在做什么短句 | 截断到 60 字（一般走 ``character.set_activity`` capability，标签也兼容） |

**剥离策略（chunk 2.6 footgun 教训：必须 3 道）**：
1. 流式按段 ``_parse_state_update``（chat.py，与 emotion 同段） 主路径
2. 写 chat_history 前 ``strip_state_update``（ws.py ``_update_memory`` /
   ``_save_interrupted_turn``） 兜底
3. TTS preprocessor 过滤（``backend/tts/__init__.py preprocess_tts_text``
   → ``utils/text_filters.strip_all_for_tts``） 第三道

**chunk 4 hotfix-1 扩展（v3-G 封盘后契约）**：
第三道 TTS preprocessor 现覆盖 **6 种**输出格式：
``<emotion>`` / ``<thinking>`` / ``<state_update>`` / ``<tool_call>`` /
``<function_calls><invoke>`` / ```` ```json {"name":...} ```` 。
``backend/utils/text_filters.py`` 提供 ``strip_all_for_tts``、``strip_tool_call_fallback``
和 ``has_partial_open_tag``：

* ``strip_all_for_tts(text)``——TTS 入口前必经；emotion → thinking →
  state_update → tool_call_fallback 四道顺序剥；缺一道 cosyvoice 念出来。
* ``has_partial_open_tag(buf)``——流式分句使用：``chat.py _safe_boundary``
  在 buffer 末尾有 ``<tool_call>`` / ``<function_calls>`` / ``<invoke>`` 等
  未闭合块时返 -1，等下一 chunk 把闭合带进来。否则块内 ``。/！/？`` 会被
  误当成句号切句，半截 XML 进 TTS。
* ``ws.py`` 流式分句出来后调用 ``strip_tool_call_fallback`` 再送 text_chunk +
  TTS（防 tool_call_resilience 还没运行就被念）。

**硬约束（v3 封盘后工程契约）**：
任何**未来新加 LLM 标签输出格式**（同时被 TTS 路径接触的）必须同步加入：
1. ``backend/utils/text_filters.py`` 的 ``_TOOL_CALL_FALLBACK_STRIP_PATTERNS``
   或对应 ``strip_*`` 函数（让 TTS 第三道兜底剥）；
2. ``has_partial_open_tag`` 覆盖（让流式分句不切坏）；
3. chat.py ``_parse_*`` 流式按段剥（主路径）+ ws.py 写库前 strip 兜底
   （持久化路径）。
漏一项 = TTS 立刻念出标签 / 半截 XML 进 chat_history / 流式中切坏块。

### Capability 表面

| name | consumer | 写 mood/intimacy 权限 | 用途 |
|---|---|---|---|
| ``character.get_state`` | CHAT_AGENT | 只读 | 用户问「你最近怎么样」时 LLM 调；返当前 state |
| ``character.set_activity`` | CHAT_AGENT | 只能写 activity / thought | LLM 主动闲笔（"刚才在烤面包"），prompt 强引导每 5-10 轮一次 |
| ``character.intimacy_decay`` | SCHEDULER 仅 | -1 / day | cron 0 0 * * * 自动跑；不是 CHAT_AGENT consumer，LLM 看不见也不能调 |

**没有** ``update_mood`` / ``update_intimacy`` 显式 capability —— 这俩故意走
``<state_update>`` 标签解析路径，避免 LLM 滥用工具刷高自己亲密度。

### 衰减规则

* **每天 0:00**（Asia/Tokyo），所有 ``character_states`` 行 intimacy -1，
  下界 0。让长期不互动的关系慢慢冷淡。
* **重新互动**靠 ``<state_update intimacy_delta="+1">`` 慢慢回升；正常聊天
  每天大概 +3 ~ +5（多轮触发）。
* **不衰减 mood**：mood 是"当下整体心情"，不该自动漂；只 LLM 显式 update
  或 ``reset_state``。

### chat_history 双写契约（chunk 2 + chunk 3b 延伸）

| 数据 | 写入路径 | 持久化位置 |
|---|---|---|
| 一般对话 turn (user/assistant) | ws.py ``_update_memory`` | chat_history kind='normal' + short_term |
| touch turn | 同上 | chat_history kind='touch' + short_term |
| proactive turn (chunk 2) | 同上 | chat_history kind='proactive' + proactive_trigger + short_term |
| **mood / intimacy 变化** (chunk 3b) | ws.py ``_apply_and_push_state_update`` | character_states 表 + WS state_update push |
| **last_interaction_at**（任何 user message） | ``update_character_state(bump_last_interaction=True)`` | character_states 表 |

state 变化 **不**进 chat_history（避免污染 profile_summary 用户画像）。

### 已知限制 / Backlog

* **LLM 标签发出率**与模型相关：实测 Qwen3.6-plus 在简单 chitchat 场景偶尔
  跳过 ``<state_update>``。chunk 3b 已通过强化 prompt（"必须输出 / 触发规
  则四条 / 只有中性 chitchat 可省略"）显著提升发出率，但仍非 100%。架构
  正确性靠单元测试 + 直接 API 测试验证；端到端真实率与模型变体相关，
  backlog：测试切到 Claude / Qwen Max 看是否更稳定。
* **mood drift 自动化**：当前 mood 只靠 LLM 显式更新；未来可考虑"超过 N 小
  时未互动 → mood drift to tired"之类自动规则。本 chunk 不做。
* **状态历史曲线**：spec 提到 ``CharacterStateDrawer.tsx`` 心情 7 天曲线，
  需要 ``character_state_history`` 表。**MVP 不做**，第二迭代 backlog。
* **多 user 场景**：当前 ``character_state.user_id`` 字段不存在，所有用户
  共享同一 character 的 state。多用户后端时需扩展。

---

## 十五之D、剪贴板助手（v3-G chunk 3a 起）

### 设计目标

让 Momo 能响应"刚才复制的那个东西"——翻译、总结、摘要。**不做**自动响
应剪贴板变化（自动评论会烦人 + 隐私敏感）。

### 数据流

```
   用户复制（任意 app）
      │
      ▼
   后端 NSPasteboard polling 1Hz       ← 主路径 (macOS)
   (changeCount 比对 → 取 stringForType)
      │
      ▼
   ClipboardWatcher.add_item()         ← 单例
   (last_text 去抖 + content_type 启发式)
      │
      ▼
   ringbuffer (deque maxlen=50)        ← 内存，重启清空
   (TTL 24h 自动 evict)
      │
      ├──► clipboard.get_recent / .summarize / .translate 容器
      │     (CHAT_AGENT capability，LLM 按用户意图按需调)
      │
      └──► GET /api/clipboard/recent
            (前端 SettingsPanel section 5s 轮询展示)
```

**备用路径**：``POST /api/clipboard/captured`` 让前端 Tauri 直接 push 上来
（本 chunk 占位；macOS NSPasteboard 后端轮询是默认主路径，无需 Tauri Rust
改动）。

### 平台支持矩阵

| 平台 | 主路径 | 后路径 |
|---|---|---|
| macOS Apple Silicon | ✅ ``AppKit.NSPasteboard`` (pyobjc transitive 已含) | pyperclip |
| macOS Intel | ✅ NSPasteboard | pyperclip |
| Linux X11 / Wayland | ❌ NSPasteboard 不可用 | ✅ pyperclip 自动 backend |
| Windows | ❌ NSPasteboard 不可用 | ✅ pyperclip win32 backend |

非 macOS 时 ``IS_MACOS=False``，``_NSPasteboard=None``，自动 fallback pyperclip。
两个都缺 → polling 不启，路由仍可用（前端 push 兜底）。

### content_type 启发式

简单规则、零模型成本：
1. ``http://`` / ``https://`` 前缀 → ``url``
2. ``{...}`` 包裹 + ``json.loads`` 通过 → ``json``
3. ``\`\`\``` 代码块 / 关键字（def / class / function / import / =>）→ ``code``
4. 连续 2 行缩进 → ``code``
5. markdown 标记（``# ``/``[X](Y)``/``- ``/``> ``）→ ``markdown``
6. 否则 → ``plain_text``

不做 ML 识别——成本不值，规则够 capability 用（``code`` 让 summarize 知道
这是代码块，``url`` 让 LLM 知道这是链接）。

### 不自动评论的设计原则

spec 关键：用户复制东西 ≠ 用户想要 Momo 回应。自动评论**绝对不做**，理
由：
1. 频率失控：用户日常复制几十次，自动评论变骚扰
2. 隐私失控：用户复制密码 / 私人内容时不想被看到
3. 上下文失控：复制 ≠ 想聊它

正确路径：用户**主动**说"刚复制的那个翻译一下"→ LLM 调 ``clipboard.translate``。
prompt 引导明确写"不要主动调，只在用户明确提到剪贴板时调"。

### 隐私契约

* **仅本地内存** ringbuffer，**不写 SQLite**
* 重启清空（TTL 24h 也是上界，用户操作系统 idle 都 evict）
* 不外传：capability 调 LLM 时**只传该条 item.content** 给 LLM，不混入历
  史 chat_history
* 前端 SettingsPanel section 显示"🔒 剪贴板内容仅本地内存，重启清空，
  不外传"明示用户

### 已知限制 / Backlog

* **frontend-driven Tauri clipboard plugin** 路径：spec 提到 ``tauri-plugin-
  clipboard-manager`` / ``arboard`` crate；本 chunk 走 backend NSPasteboard
  轮询主路径，Tauri 集成 backlog（需要 Cargo dep + Rust handler + frontend
  listen + POST 调 ``/api/clipboard/captured``）。后端轮询在 macOS 上工作
  良好（pyobjc transitive 已含），不阻塞 v3-G 封盘。
* **大型 base64 图片 / 文件**：捕获后会撑大 ringbuffer 50 条限额；route 端
  截断到 100KB，但 NSPasteboard 直接读时无截断。后续可加大小过滤。
* **set_enabled HTTP 路由**：当前 ``ClipboardWatcher.set_enabled`` 仅 Python
  内可调；前端 [捕获剪贴板] toggle 暂只写 localStorage，没接通到后端。
  backlog 加 ``POST /api/clipboard/enabled`` 让前端 toggle 真生效。

---

## 十五之E、Tool Call Resilience Layer（v3-G chunk 4 Part A 起）

### 背景

Qwen3.6（DashScope OpenAI-compatible 通道）在 tool calling 时偶发把 tool
调用以**非 OpenAI function_call 协议**的形式输出到 ``delta.content`` 文本
流。chunk 2.6 footgun 4（snooze 不真触发）+ chunk 3 footgun 7（``clipboard.
translate`` 不真翻）都是这条路径。

### 三种 fallback 形式

| 形态 | 模式 | 来源 |
|---|---|---|
| Qwen XML | ``<tool_call>{"name":"X","arguments":{...}}</tool_call>`` | Qwen 内部协议 |
| Anthropic invoke | ``<function_calls><invoke name="X"><parameter name="K">V</parameter></invoke></function_calls>`` | LLM 训练数据混入 Anthropic 风格 |
| Markdown JSON | ``\`\`\`json\n{"name": "X", "arguments": ...}\n\`\`\`` | 通用兜底（最宽松，最后扫） |

### 处理路径

```
   ChatAgent.stream() 主循环 (OpenAI function_call) → reply_parts
      │
      ▼
   ws.py turn pipeline 终点（done 之前）：
   detect_and_execute_fallback_tool_calls(full_reply, user_id, character_id)
      │
      ├─ 三条 regex 顺序扫（qwen_xml → anthropic → markdown_json）
      │
      ├─ 容错 JSON parse（双重编码 / 引号混合 / 类型 coerce）
      │
      ├─ ToolRegistry._tools 检查 name 存在才调（防 LLM 编造 name）
      │
      ├─ 注入 user_id（会话级，LLM 不能 override）
      ├─ 注入 character_id（缺失时；显式指定优先）
      │
      ▼
   await ToolRegistry.call(name, **args)  （capability 副作用真生效）
      │
      ▼
   剥离全部 fallback XML 残骸 → cleaned_text
      │
      ▼
   chat_history 写 cleaned_text（无 XML / 不污染下游 profile_summary）
```

### 不做的事 / Backlog

* **不喂 tool result 回 LLM 让它续写**：MVP 简化。capability 副作用已生
  效，LLM 自欺"已完成"在用户视角无伤——用户看到"好的 5 分钟后再叫你"
  + 5 分钟后真触发 wake_call。
* **不阻断主流程**：任何子步骤异常吞 + log，永远返回原文 + 已执行的部分
  ，不抛错。
* **未来可选切模型测试**：Qwen Max / Claude 等模型形态变异率不同，按需测
  试 + 记录 per-model 兜底率到 telemetry。

### `_execute_tool` 的 character_id 注入修

chunk 4 同步修复一个 chunk 3 latent bug：``_execute_tool`` 走 ToolRegistry
路径时之前不传 ``character_id``，导致 ``character.set_activity`` /
``character.get_state`` 等需要 character_id 的 capability 报错。chunk 4 在
ToolRegistry.call 调用前显式注入 ``args["character_id"] = character_id``
（与 fallback resilience 路径保持同一注入语义，对称契约）。

---

## 十五之F、v3-F' Trigger Pack 设计（v3-G chunk 4 Part C 起）

### 模式 B 邀请对话哲学的多 trigger 复用证明

chunk 2.6 落地 ``WakeCallBriefingTrigger`` 时定型了"模式 B 邀请对话"流水
线。chunk 4 加 4 个新 trigger（lunch_call / dinner_call / bedtime_chat /
long_idle），**每个都是 WakeCallBriefingTrigger 的克隆 + 改 prompt**，
没有新 engine 工作——这是 chunk 2.6 抽象设计的复利兑现。

### 共享基础

* ``backend/proactive/triggers/_invite_base.py`` ——
  ``InviteTriggerBase``（``ProactiveTrigger`` 子类）+ ``make_stage1_prompt
  (sentinel, scene_label, examples)`` + ``make_stage2_addendum_template
  (scene_label, scene_focus)``。
* ``backend/proactive/triggers/_stage2_registry.py`` —— trigger.name →
  (sentinel, addendum_builder) 全注册表。chat.py 按 ``last_assistant.
  proactive_trigger`` 分发到对应 builder。

### Trigger Pack 完整表

| trigger | 模式 | 调度方式 | stage 1 例子 | stage 2 关注点 |
|---|---|---|---|---|
| ``wake_call`` | B 邀请 | cron 默认 ``0 8 * * *`` | "宝，醒一醒～" | 自适应早晨简报内容 |
| ``lunch_call`` | B 邀请 | cron 工作日 ``0 12 * * 1-5`` + 周末 ``30 11 * * 0,6`` | "嘿，饿了吗？" | 胃口 / 餐食偏好 / 简单做饭 |
| ``dinner_call`` | B 邀请 | cron 默认 ``30 18 * * *`` | "忙完了？要吃啥？" | 疲惫程度 / 餐食 / 外卖 |
| ``bedtime_chat`` | B 邀请 | cron 默认 ``30 22 * * *``（default OFF）| "今天累不累？" | 今日 review / 明日预告 / 安抚 |
| ``long_idle`` | B 邀请 | interval ``5 min`` 检查 + 三条件（default OFF）| "嘿，还在吗？" | 用户当下状态 / 简短陪伴 |
| ``morning_briefing`` | A 单方面 | cron 默认 ``0 9 * * *`` | （直接整段播报）| 完整 200-300 字简报 |

### long_idle 三条件 gate

interval 5 分钟跑一次 ``check_and_maybe_fire``，**全为真**才发短问候：

1. **用户消息 idle 超阈值**：最近一行 ``role='user'`` chat_history >
   ``idle_threshold_minutes``（默认 30 分钟）
2. **没有最近的 proactive turn**：任何 ``kind='proactive'`` 行 created_at >
   ``cooldown_minutes``（默认 90 分钟）—— 避免连续主动打扰
3. **前端 heartbeat 显示用户在前台**：``last_heartbeat`` 距 now ≤
   ``heartbeat_grace_seconds``（默认 30s）

### Heartbeat 协议

* 前端 ``useWebSocket`` 在 ``visibility=visible + focus`` 时每 15s POST
  ``/api/heartbeat``，``visibilitychange`` / ``blur`` / ``focus`` 事件
  绑定 start/stop loop。
* 后端 ``backend/proactive/triggers/long_idle.py`` 维护内存
  ``_LAST_HEARTBEAT: dict[user_id, datetime]``，进程内共享。重启清空。

### chunk 0 抽象的复利证明

| chunk | 新增 capability 数 | 改 chat.py 的次数 |
|---|---|---|
| chunk 0 (基础) | 1 (time.now) | 0 |
| chunk 1 (calendar) | 2 | 0 |
| chunk 1.5 (MCP) | runtime 注册 N 个 | 0 |
| chunk 1.6 (apple) | 4 + 2 | 0 |
| chunk 1.7 (model picker) | 0 | 0 |
| chunk 2 (proactive engine) | 0（engine 走 ChatAgent.stream）| 0（生 ``extra_system`` / ``enable_search``）|
| chunk 2.6 (wake_call) | 1 (snooze)| 1（``_maybe_build_wake_call_addendum`` + sentinel detection）|
| chunk 3a (clipboard) | 3 | 0 |
| chunk 3b (character_state) | 3 | 1（``<state_update>`` parser + system prompt 注入）|
| chunk 4 (resilience + 4 triggers) | 0 | 1（resilience hook + sentinel registry generalize） |
| **累计** | **30+ capability + 5 trigger** | **3 次（全部最小化、向后兼容）** |

chunk 0 的 ``CapabilityRegistry`` + ``ToolRegistry`` 双层抽象 + chunk 2 的
``ProactiveTrigger`` 抽象，让 v3 后期所有"新功能"都退化成"加文件 + 写
prompt"。最后一次 chat.py 改动是 chunk 4 的 stage 2 sentinel registry
generalize（从 hardcode 一个 wake_call sentinel → 任意数量）—— 这是
*抽象巩固*，不是新增功能。

### Backlog / 后续

* **frontend SettingsPanel 4 trigger toggle**：当前 4 个新 trigger 通过
  ``config.yaml`` 编辑 enabled。前端 ``[主动陪伴]`` section 升级成 sub-
  section [其他主动场景] + 4 个 toggle + 各自 cron 输入是 chunk 4 deferred
  scope（per-trigger config 路由 + frontend 切换 UI）。short term 用户改
  yaml 重启即可生效。
* **per-trigger aggregate function 真实接通**：当前 4 trigger 的 stage 1
  aggregate 复用 ``aggregate_briefing_data``（time + calendar + instruction
  memories + city）。spec 提到 lunch / dinner 应聚合"最近 3 天饮食 memory"
  / bedtime "今日 chat_history kind='normal' 摘要 + 明日 calendar"。这些
  per-trigger aggregator 在 v3-F' Phase 2 / chunk 5 单独做。stage 2 prompt
  已经引导 LLM 现查（``enable_search``）+ 已聚合数据均可用。

---

## 十五之G、视觉跃迁包（v3.5 chunk 5 起）

v3 封盘后视觉感升一档。两块独立但同 cc-task 上：

### 5a 角色背景层（per-character + 多媒体）

**核心抽象**：``character.background_path`` TEXT NULL。空 → CharacterView
按原 fallback 链（Live2D → 静态 jpeg），与 chunk 5 前完全一致。配置 →
按后缀分发。

**后缀白名单**（前后端两侧同一表，schema 不下放）：

| 后缀 | 类型 | 前端 |
|---|---|---|
| ``.jpg`` / ``.jpeg`` / ``.png`` / ``.webp`` | image | ``<img>`` |
| ``.mp4`` / ``.webm`` | video | ``<video autoplay loop muted playsinline>`` |

其他后缀（README.md / .gitkeep / 用户暂存的 .psd 源等）一律忽略。

**z-index 层序**（CharacterView 渲染管线）：

```
[ background_path 层 (z-0) ]  ← <img> / <video>，autoFit cover
[ Live2D canvas (z-10) ]      ← 模型立绘 / lipsync / 表情
[ panel overlay (z-上层) ]    ← 半透明覆盖 + dialogue bubble
```

**关键设计**：背景层 + Live2D 共存（chunk 5 之前 fallback 是排他）；背
景层 onError 触发 ``bgFailed`` state → 静默回退到原 fallback，永不抛错
中断渲染。切角色时 useEffect 重置 ``bgFailed``，避免上一角色失败影响
下一角色。

**Scanner 架构**（backend/services/backgrounds_scanner.py）：

* 与 ``live2d_scanner`` 完全对称：``.absolute()`` 不 ``.resolve()``（IP
  资产 symlink 不跳出 repo path 命名空间）；递归一层子目录支持 ``tokyo/
  rain.mp4`` 分组；单文件错误吞，不让整个 scan fail。
* 返回 ``{ scan_dir, items: [{ name, path, type, size }] }`` —— TypedDict
  schema 后端 single source of truth，前端 ``lib/backgrounds.ts`` 接口
  drift 时 build error。

**IP 隔离**（``.gitignore``）：

```
frontend/public/backgrounds/*
!frontend/public/backgrounds/.gitkeep
!frontend/public/backgrounds/README.md
```

同 ``live2d/`` 的 IP 隔离 pattern 复用。第三方 / 委托作品丢进来不进 git
历史。

### 5b 启动入场 splash video

**设计哲学**：Skyler 工程**不集成** video 生成 API（Grok / Sora 离线生
成后用户自己丢文件）。只播放，文件不存在则 silent skip。

**``SplashOverlay`` 生命周期**：

```
mount
  ├─ localStorage momoos.splashEnabled === 'false' → 立即 onFinished
  └─ fetch HEAD /splash/intro.mp4
       ├─ 200 → render <video> 全屏
       │      └─ onEnded / click / keydown / onError → fade 300ms → onFinished
       └─ 404 / network err / Tauri 协议限制 → silent skip → 立即 onFinished
```

App.tsx 主视图 opacity 由 ``splashDone`` 控制，fade-in 300ms。silent-skip
时 splashDone 在 mount 同 tick 翻 true，主视图无感。

**Tauri 兼容**：fetch HEAD 在 dev (Vite HTTP) 和 prod (Tauri webview) 都
可工作；万一某 Tauri 配置拦截 HEAD，``<video onError>`` 会兜底，仍然
silent skip。双保险无单点失败。

**约束**：固定文件名 ``intro.mp4`` 硬编码（不扫描）。webm 在 macOS Tauri
webview 上 codec 支持不稳（VP9/AV1 视系统），spec 只走 mp4。

**Settings 持久化**：``momoos.splashEnabled`` 纯 localStorage，与
``LS_RECORDING_MODE`` 同 pattern。boot-time 不依赖后端连上即可生效。

### 工程契约延续

* 新增 LLM 标签需要同步加入 ``strip_all_for_tts``（chunk 4 hotfix-1）这条
  契约不适用本 chunk（无新标签）。
* 新增 frontend 资产类目（继 live2d / backgrounds / splash 之后），如果
  涉及 IP，记得复用 ``.gitignore`` 白名单 pattern：``目录/*`` 全屏蔽 +
  ``!目录/README.md`` + ``!目录/.gitkeep`` 占位。

---

## 十五之H、Skill 集成姿态（v3.5 chunk 7 起）

兑现「个人乐高底盘」承诺——演示两条独立姿态，未来加任何 skill 选其一即可，
不必每次重新设计架构。

### 姿态 A：本地 capability（docx demo）

**何时选 A**：能力本身用 Python 库就能跑（python-docx / openpyxl /
pdfplumber / pyperclip / pyautogui / ...）。直接用 Skyler 内置 capability
基础设施。

**架构**（与 chunk 0 capability_registry / chunk 1 calendar 完全对齐）：

```
LLM tool call (ChatAgent)
  ↓ ToolRegistry.call(name, **kwargs)
  ↓ async handler(**_kwargs)        ← @register_capability
  ↓ safe_resolve(SAFE_DIR, filename) ← backend/utils/safe_path.py
  ↓ python-docx / 其他库
  ↓ return {result_dict} or {error: "<code>"}
```

**SAFE 沙箱契约**：

* 沙箱根目录用户可见（``~/Documents/Skyler/<feature>/``）——用户直接 Finder
  打开方便；与 google_calendar 的 ``~/.skyler/``（隐藏 dotdir，纯内部 token
  存储）区分定位
* ``ensure_sandbox_dir(base, mode=0o700)`` 集中实现 mkdir + chmod
* ``safe_resolve(base, user_path, allow_subdirs=False)`` 集中实现 path
  traversal 防御：``.resolve()`` + ``.relative_to(base)`` + 文件名 stem
  校验（不允许 ``/`` / ``\`` / ``..`` / 绝对路径）
* config.yaml ``skills.<feature>.safe_dir`` 可覆盖默认（dev / 测试 / 多
  user 场景）

**chunk 7 docx demo**：3 capability（create / read / append）@
``~/Documents/Skyler/docs/``。filename auto-补 .docx 后缀；不支持图片 /
表格 / 公式（V1 简化）。

### 姿态 B：MCP server 一键启用（Notion demo）

**何时选 B**：第三方 SaaS 自己提供 MCP server（Notion / Linear / Slack /
GitHub / Sentry / Stripe ...）。复用 chunk 1.5 bidirectional MCP client，
零新 client 代码。

**架构**（chunk 1.5 + chunk 7 增量）：

```
config.yaml mcp_clients.<name>          ← server 元数据
  ↓ init_clients_from_config()           ← chunk 1.5
  ↓ _effective_enabled = DB override > config default ← chunk 7
  ↓ _connect_one (env = os ∪ config ∪ DB credentials)
  ↓ stdio_client(npx subprocess) | streamable_http
  ↓ ClientSession.list_tools()
  ↓ Capability per tool → CapabilityRegistry.register_runtime
  ↓ ChatAgent 见到 ext.<server>.<tool> 与本地 capability 等价调用
```

**chunk 7 增量**（不重建 client，扩展现有架构）：

* 表 ``mcp_credentials (server_name, key_name, value, updated_at)``——
  UI 输入的 API key 写 DB，启动子进程时注入 env（不污染 .env）
* 表 ``mcp_client_state (server_name, enabled, updated_at)``——UI toggle
  持久化覆盖 config.yaml ``enabled`` 默认
* ``backend/mcp/credentials.py`` async CRUD
* ``backend/mcp/client.py`` 扩展：``_effective_enabled`` / ``enable(name)`` /
  ``disable(name)`` + ``list_status`` 返 ``env_required`` /
  ``missing_credentials``
* ``backend/routes/mcp_api.py`` 扩展：``PUT .../enabled`` /
  ``PUT .../credentials`` / ``GET .../credentials``（不返 value，只列
  key + configured 状态）
* ``ExtensionsSection.tsx`` —— SettingsPanel 新 section，列 server + toggle +
  状态徽章 + [配置凭证] modal

**chunk 7 Notion demo**：``@notionhq/notion-mcp-server``（官方 npm 包
makenotion/notion-mcp-server）；env_required ``NOTION_API_KEY``；
``expose_via_skyler_server=False``（不级联代理到外部）。

**UX-001 增量**（2026-05-12，per-tool 级 override）：

* 表 ``mcp_tool_state (server_name, tool_name, enabled, updated_at)``——
  与 chunk 7 ``mcp_client_state`` 完全平行，区别是粒度落到单个 capability
  （即 ``ext.<server>.<tool>``）。只存差异：表里没行 = enabled=True。
* ``backend/mcp/tool_state.py`` 4 个 async API（is_enabled / list_overrides
  / set_enabled / delete_for_server）。
* ``backend/mcp/client.py`` ``_ClientHandle`` 加 ``tools: list[dict]``，
  ``_connect_one`` 拉 ``list_tools`` 后用 ``list_overrides`` 一次性查 DB，
  enabled=False 的 tool **不 register CapabilityRegistry**（LLM 不可见）
  + 仍记录到 ``handle.tools`` 让 UI 渲染。
* ``set_tool_enabled`` 公开 API + ``PUT /api/mcp/clients/{name}/tools/
  {tool_name}/enabled`` 路由 ——
  False→True：拉 session.list_tools 找原 tool 对象 → register_runtime；
  True→False：unregister_runtime ``ext.<server>.<tool>``。
* ``list_status()`` 返回每行加 ``tools`` 字段。
* ``ExtensionsSection.tsx`` 改 accordion：每 server 默认折叠成单行 +
  ``X/Y cap`` 角标；点 caret 展开看 capability 列表 + 单 cap toggle。
  server 关时 tool 行 visible 但 toggle 禁用（``disabled={!client.enabled
  || ...}``），状态条 ``value={tool.enabled && server.enabled}`` 让"server
  关 = 全部 cap 视觉上关闭"在 render-time 表达，per-tool override 仍持久
  在 DB 里，重新启用 server 时记得用户上次的偏好。

UX-001 没改 ``mcp_credentials`` / ``mcp_client_state`` schema —— chunk 7
原生功能不动，只在其上 layered per-tool 一级。

### 决策树

```
新 skill 想接入？
  ├─ 用 Python 库就能完成 → 姿态 A
  │      （docx / Excel / PDF / 本地文件 / Apple Notes 通过 osascript ...）
  ├─ 有官方 MCP server → 姿态 B
  │      （Notion / Linear / Slack / GitHub / Stripe ...）
  └─ 两种都行 → A（少一层进程 + 直接 SAFE 沙箱）
```

**反模式**：

* 不要为只 wrap 一个 HTTP API 的简单功能写 MCP server（直接 capability
  handler 一个 ``httpx`` 调用更省事）
* 不要为 LLM 不会主动想用的能力做姿态 B（启动 npx 子进程有 30s 首次拉包
  代价 + 占系统资源）

### V1 限制 / Backlog

* **凭证明文存储**——MVP；``ROADMAP Tech Debt`` 加「MCP 凭证加密（OS
  keyring or master password）」backlog
* **MCP server 市场 / 一键安装**——目前只列 config.yaml 已配置的 server，
  不做发现 + 自动注册。用户加新 server 需手动改 config.yaml
* **server 崩溃自动重启**——用户 toggle 即可，无 supervisor 循环
* **凭证多 user 场景**——目前 single-user，``mcp_credentials`` 无 user_id
  列；多 user 后端时需扩展

---

## 十五之I、B 站接入（v3.5 chunk 6a 起）

### 姿态选择

姿态 A 本地 capability（与 chunk 1 netease / chunk 7 docx 同架构）：

* ``backend/integrations/bilibili.py`` —— 包 ``bilibili-api-python``（Nemo2011
  社区 fork，v17.4.1 / 2025-12 stable）的 11 个 async 方法
* ``backend/capabilities/bilibili.py`` —— 11 个 ``@register_capability``，
  description 走 chunk 1.7 verbatim 强引导

**为何不走姿态 B（MCP server）**：B 站官方没有 MCP server，社区也没成熟实
现；自己包一层本地 capability 控制力更强（错误归一化 / 风控映射 / 字幕选
优策略都可定制）。

### 11 capability 全景

| Capability | Cookie | 用途 |
|---|---|---|
| ``bilibili.search_video`` | 否 | 关键词搜视频 |
| ``bilibili.get_video_info`` | 否 | BV/AV 号 → 元数据（看到 URL 默认调）|
| ``bilibili.search_user`` | 否 | 搜 UP 主 |
| ``bilibili.get_user_videos`` | 否 | UP 主投稿列表 |
| ``bilibili.hot_videos`` | 否 | 首页热门 |
| ``bilibili.get_ranking`` | 否 | 排行榜 |
| ``bilibili.get_subtitles`` ⭐ | **是** | 拿字幕 → LLM 总结（杀手 use case） |
| ``bilibili.get_my_history`` | **是** | 我的观看历史 |
| ``bilibili.get_my_followings`` | **是** | 我关注的人 |
| ``bilibili.get_later_watch`` | **是** | 稍后再看 |
| ``bilibili.get_favorites`` | **是** | 我的收藏夹 |

### 字幕策略 + 风控 audit

**Spec pivot**：原计划 ``get_subtitles`` 无 cookie。Audit 实测 B 站 2024-2025
风控收紧：

* 库 ``Video.get_subtitle()`` 直接 ``raise CredentialNoSessdataException``
* 绕过库直接 hit ``/x/player/v2`` 公开端点也返 ``subtitles: []`` 空列表
  （无登录态时字幕被风控隐藏）

实施方案：``get_subtitles`` 归类为 cookie-required。未配 SESSDATA 时返
``cookie_required`` + ``hint`` 引导用户去 ``docs/bilibili-setup.md``。

**字幕选优算法**（``_choose_subtitle``）：

1. AI 字幕（``ai_type == 1`` 且 ``lan`` 含 ``zh``）—— 多数 B 站视频都有，
   质量足够 LLM 总结
2. UP 主上传中文字幕（``ai_type == 0`` 且 ``lan`` 含 ``zh``）
3. 列表第一项 fallback
4. 都没有 → ``source: 'none'`` + ``subtitle_text: ''``，让 LLM 自己回话
   "这个视频没字幕"，**不允许瞎编内容**（system prompt 强引导）

### 风控 code → 友好 error 映射

| B 站 code | error key | 触发场景 |
|---|---|---|
| -352 | ``risk_control`` | 通用风控（频繁请求） |
| -412, -509 | ``rate_limited`` | 限流 |
| -403 | ``forbidden`` | 权限拒 |
| -404, 62002 | ``not_found`` / ``video_unavailable`` | 视频删除 / 被封 |

### 健康检查三档

``health_check()`` 返 ``{status, library_present, cookie_configured,
connectivity, ...}``：

* **healthy**：lib 装了 + cookie 配了 + connectivity ok
* **warn**：lib 装了 + (cookie 未配 OR connectivity fail) —— 仍能用部分
  capability，UI 黄色徽章 + 引导
* **error**：lib 没装 —— UI 红色徽章 + ``fix: pip install ...``

### Cookie 走 .env vs DB（与 chunk 7 区分）

| 来源 | 凭证存哪 | 适用 |
|---|---|---|
| chunk 7 MCP server | DB ``mcp_credentials`` 表，UI 输入 | 子进程，UI 可视化管理多个 server |
| chunk 6a B 站 / chunk 1 网易云 | ``.env`` 环境变量 | 本地 capability，单用户单 cookie，重启偶尔重新粘 |

未来若需要 UI 管理 B 站 / 网易云 cookie 也走 DB，可以新加
``capability_credentials`` 表复用同 pattern；当前 MVP 不做。

### 红线（chunk 6a 工程约定）

不实现以下写 / 自动化操作（社区礼仪 + 风控敏感 + 用户授权范围明确）：

* 投币 / 一键三连 / 点赞 / 收藏
* 自动评论 / 弹幕发送
* 视频下载 / 录屏
* 关注 / 取关 / 私信
* 直播弹幕监听 / 自动应援

未来用户明确同意后可单独 chunk 加，但默认拒绝。

---

## 十五之J、网易云本地 mpv 自解码（v3.5 chunk 6b 起）

### 背景

v3-H chunk 1 上线 NCM URL Scheme 启动播放路径（``netease.play_song``
等），autoplay 不可靠（NCM 客户端响应 URL Scheme 的 ``/play`` 后缀语义
在多个版本间漂移）—— chunk 1 partial 状态封存。

chunk 6b 替换路径：**Skyler 自己拿 song/url + mpv 本地播放**，自动播放真
闭环。

### 双路径并存

| 维度 | chunk 1 ``netease.play_song(keyword)`` | chunk 6b ``netease.local_play_song(song_id)`` |
|---|---|---|
| 触发 | 搜关键词 + 启动 NCM | 拿 ID 直接 mpv 播 |
| 自动播放 | ⚠️ 不可靠（NCM URL Scheme） | ✅ 真闭环 |
| 歌词 / 动画 | ✅ NCM 客户端 | ❌ 无 |
| 控制 | 媒体键 → NCM | 媒体键 → mpv |
| LLM 默认 | 仅当用户明确要 NCM 时 | **首选**（system prompt 强引导） |

### 架构

```
LLM → netease.local_play_song(song_id)
  ↓
NeteaseClient.get_song_url(song_id)   ← chunk 6b 新加
  ↓ weapi POST /song/enhance/player/url/v1
  ↓
url + is_trial flag
  ↓
MpvPlayer.play(url, meta=...)
  ↓ subprocess mpv --idle --input-ipc-server=<socket> --media-keys=yes
  ↓ JSON IPC: loadfile, set_property force-media-title, etc.
  ↓
macOS NowPlaying Center 自动获取 mpv metadata（mpv 0.34+ 原生支持）
  ↓
系统通知中心 / Touch Bar / 媒体键 / nowplaying-cli 全部能看到
```

### MediaRemote degrade 升级

**Spec 原计划** ``backend/integrations/media_remote.py`` 用 PyObjC 桥接
``MPNowPlayingInfoCenter`` / ``MPRemoteCommandCenter``。

**Audit 后取消**：

* mpv 0.34+ 原生注册 NowPlaying（``--media-keys=yes``），Skyler 不需要
  自写 PyObjC 桥
* 节省 ~200 行 PyObjC 代码
* 不需要 Skyler 进程持有 AVAudioSession / Info.plist / entitlement
* 兼容 unsigned dev 模式 Python 进程

实际是**升级**（不是 degrade）—— 比 spec 设想的方案更简洁稳健。

### 错误码

| code | 触发 |
|---|---|
| ``mpv_not_installed`` | binary 不在 PATH，提示 ``brew install mpv`` |
| ``mpv_exec_failed`` | binary 在但跑不起来（Gatekeeper 首次拦截） |
| ``cookie_required`` | NETEASE_MUSIC_U 没配 |
| ``url_unavailable`` | VIP 下架 / 地区限制 / 已下线 |
| ``netease_api_error`` | NCM API 限流 / cookie 失效 |
| ``mpv_play_failed`` | mpv loadfile 失败（解码错 / 网络中断） |
| ``mpv_command_failed`` | IPC 命令超时 / socket 断 |

### 试听片段 (VIP)

VIP 付费下架歌曲 NCM 返试听 URL (~30s)。capability 返 ``is_trial=True``
+ ``note: "试听片段（~30s）"``，LLM 如实告诉用户，不假装是完整版。

### mpv-default 策略（chunk 6b hotfix-1 补齐）

chunk 6b 落地后还有 4 个**场景类** capability（不是显式 ``play_*``，是
LLM 凭语义触发的「日推 / 私人 FM / 关键词点播 / 按 ID 播歌单」）走的还是
chunk 1 的 URL Scheme 路径。这些 capability 当时返 ``autoplay: true`` ——
但 NCM 客户端响应 ``orpheus://song/<id>/play`` **只接管系统媒体键**，不
真的开播指定歌曲。LLM 拿到 ``autoplay: true`` 后回话「已经在放啦」 ⇒
**假成功**。

hotfix-1 把这 4 个 capability 统一改成 mpv-first fall-through：

| 路径 | 触发条件 | ``backend`` | ``autoplay`` | 额外字段 |
|---|---|---|---|---|
| mpv 真闭环 | mpv 健康 + ``MUSIC_U`` cookie OK + song URL 可拿 | ``"mpv"`` | ``true`` | ``queued`` / ``is_trial`` |
| URL Scheme fallback | 其余任何条件不满足 | ``"url_scheme"`` | ``false`` | ``hint`` 引导装 mpv |
| 特殊：personalFM | URL Scheme fallback 时唤起 ``orpheus://personalFM`` | ``"url_scheme_fm"`` | ``false`` | ``note`` 说明 NCM 自带 FM autoplay |

**核心契约**：``autoplay`` 字段从此**只表 Skyler 自身状态**（mpv 是否真
在播），不试图代表 NCM 客户端的状态。NCM 客户端能否真播由 client 自己
决定，Skyler 无法可靠观测——所以诚实置 false，让 LLM 转告用户「需要装
mpv 才能真自动播」。

**helper 抽出**（``backend/capabilities/netease_music.py`` 顶部）：

* ``_mpv_available_and_cookie_ok()`` —— 复用 ``mpv_player.health_check``
  + ``NeteaseClient.has_credentials``，两侧任一失败短路返 False
* ``_try_mpv_play_single(song_id, title, artist)`` —— get_song_url + mpv.play
  原子动作，返 ``{played, is_trial, ...}``
* ``_try_mpv_play_song_queue(songs)`` —— 第一首立 play + 其余 best-effort
  入队（与 ``netease.local_play_playlist`` 同 pattern）
* ``_mpv_unavailable_hint()`` —— 友好引导文案

**audit 副产物**：全 backend 0 个 ``music://`` scheme 引用。用户曾报告
「让 Momo 播日推开了 Mac 自带音乐」—— **非代码 bug**：macOS 默认 app
handler 在 NCM 客户端未注册 orpheus URL Scheme 时，会按用户偏好回退到
默认音频 app。这是装机/系统设置问题，不是 Skyler 实现错。

---

## 十五之K、小红书 URL 被动解析（v3.5 chunk 6c 起）

### 工程红线（三处明文）

| ✅ 做 | ❌ 拒绝 |
|---|---|
| 用户主动贴 URL → 拉单次 HTML | 主动搜索 / 推荐流 |
| follow xhslink 短链 | 账号自动化 / login |
| og:meta + ``__INITIAL_STATE__`` 解析 | 评论抓取 |
| 域名白名单（仅 xiaohongshu.com / xhslink.com） | 批量爬虫 / 高频 |
| 反爬识别 + 友好 error | 弹幕 / 私信 / 点赞 |

**工程层面**：``backend/integrations/xiaohongshu.py`` **不暴露** search /
recommend / fetch_homepage / list_followings 等方法。无主动调用路径 ⇒
即便 prompt injection 也调不到。

### 哲学

小红书 anti-bot 强，主动爬有合规 + 反爬礼仪问题。Skyler 是个人陪伴助
手，不是数据采集工具。如未来确实想接搜索类功能：另起 chunk + 用户明确
同意 + 走 MCP server 隔离子进程（合规风险落在外部 server，Skyler 边界清晰）。

### 数据源策略

```
HTTP 200 →
  ├─ 优先 window.__INITIAL_STATE__（完整 title + desc + images + tags + author）
  │   * undefined → null 修正（xhs JSON 不合标）
  │   * 解析失败 fallback 截到最后一个 }
  │   * 试 noteDetailMap / note.note / noteData.data.noteInfo 多条路径
  ├─ fallback og:title + og:description + og:image（缩略版）
  └─ 都没 → parse_failed
```

### 错误码

| code | 触发 |
|---|---|
| ``invalid_url`` | 非 xiaohongshu.com / xhslink.com 域名 |
| ``blocked_by_antibot`` | 412 / 418 / 403 反爬限流 |
| ``parse_failed`` | 200 OK 但无元数据（私人 / 已删 / 模板变） |
| ``timeout`` | 12s 网络超时 |
| ``http_error`` | 其他 5xx |
| ``network_error`` | DNS / 连接断 |
| ``missing_url`` | 调用时未传 url |

### 杀手用例

LLM 看到用户贴小红书 URL → 调 ``xhs.parse_url`` → 拿到 title/text/images
后**用自己的话**总结 / 翻译 / 回答用户问题。**不**原样输出 tag 列表 /
emoji 噪声 / 完整 text（system prompt 强引导）。

LLM 看到用户问主动搜索类问题 → **如实告诉用户**「Skyler 不主动爬小红书；
你贴具体笔记链接给我就能解析」，**不要瞎编**（system prompt + capability
description 双重红线明文）。

---

## 十五之L、Activity-based Proactive Trigger（v3.5 chunk 8a 起）

### 设计目标

cron trigger（chunk 2 / 2.6 / 4 Part C）按"时间"主动开口（早安 / 饭点 /
睡前）。chunk 8a 引入按"活动"主动开口：

* 切到 IDE → "在做什么项目"
* 切到音乐 app → "听啥呢"
* 打开技术文档 URL → "在查什么"
* 90 分钟同 app 不切 → 温柔提醒喝水
* 凌晨 IDE active → 一句"又熬夜了"轻关心

与 cron trigger 并存——本系列**不替代**早安 / 饭点的时间触发，而是**补
充**一类按上下文判定的轻量主动开口。

### 与 cron trigger 的区别

| 维度 | cron trigger | activity trigger |
|------|-------------|-----------------|
| 调度 | APScheduler crontab | event-driven listener |
| 字数 | 200-300 字简报 / 8-15 字 wake call | 40-80 字短句 |
| 触发数据源 | 时间 / weather / calendar | active app / URL / 文档 / 时长 |
| 节流 | cron 表达式本身 | 同 label N min + 一天 cap |
| 黑名单 | 无 | apps + URL pattern 列表 |
| trigger label | morning_briefing / wake_call / lunch_call / ... | activity_ide_open / activity_music / activity_url_tech_doc / activity_long_focus / activity_late_night_ide |

### ActivityWatcher 工作流

```
config.activity_watcher.enabled=true
    ↓ lifespan 6c'
activity_watcher.start_polling()
    ↓ asyncio.create_task(run_loop)
run_loop（每 poll_interval_seconds，默认 30s）:
    ↓ snapshot()                ← NSWorkspace + osascript（Chrome / Safari / Word / Pages）
    ↓ 黑名单 app/URL 字段置 None
    ↓ _detect_changes(last_state, new_state)   ← 5 类 change（app/url/doc/focus_long/dwell_long）
    ↓ 若 url_changed → _maybe_fetch_url_content   ← url_fetcher + readability
    ↓ listeners 串行 dispatch（异常吞 + 不阻塞下个 listener）
    ↓ last_state = new_state
    ↓ await stop_event.wait(timeout=interval)   ← 可被 stop_polling 立即唤醒
```

### 4 道闸节流（``backend/proactive/activity_smart.py``）

ActivityWatcher 的 listener fn ``activity_smart_handler``：

1. **_classify(change)**   规则表 → trigger label 或 None（None 不触发）
2. **active-conversation guard**   最近 5 min 有 ``role='user' kind='normal'``
   的 chat_history → skip（用户正在跟 Momo 聊，别打断）
3. **throttle**   同 label 距上次 < ``trigger_throttle_minutes`` (默 30) → skip
4. **daily cap**   当天 activity trigger 次数 >= ``max_daily_triggers`` (默 5)
   → skip。跨午夜自动 reset

四道全过 → ``ActivityProactiveTrigger(label, detail)`` + 调
``proactive.engine.run_trigger`` 复用 ChatAgent / WS 推送 / TTS 流水线。

### 规则集（v1 范围）

| change.kind | 条件 | label |
|------------|------|-------|
| app_changed | new_app ∈ _IDE_APPS 且本地 0-5 点 | activity_late_night_ide |
| app_changed | new_app ∈ _IDE_APPS | activity_ide_open |
| app_changed | new_app ∈ _MUSIC_APPS | activity_music |
| url_changed | new_url 命中 _TECH_DOC_URL_PATTERNS | activity_url_tech_doc |
| app_focus_long | （同 app 持续 > 90 min 跨阈值首拍） | activity_long_focus |

``url_dwell_long`` / ``doc_changed`` 暂不出 trigger（v1 保守）。

### 隐私边界

* **黑名单一票**：blocked_apps / blocked_url_patterns 命中 → snapshot 直接
  把字段置 None。listener 完全看不到敏感场景（与 chunk 6c xiaohongshu 红线
  "主动方法不存在" 同思路：把保护推到数据源头）
* **URL 内容抓取可独立关**：``fetch_url_content=false`` → Momo 知道你在哪个
  URL 但不抓正文（"看不到内容"的诚实状态）
* **不爬站点**：url_fetcher 单次 GET + 5s timeout + 1MB body cap + 3 redirects，
  等同浏览器手动开一次的网络足迹
* **不持久化 activity state**：``activity_watcher`` in-memory 跟踪 last_state；
  重启清空。``activity_watcher_state`` 跨重启持久化先 backlog
* **本地处理**：NSWorkspace / AppleScript 全本地；url_fetcher 走 httpx 直连
  公开 URL（与 chunk 6b 网易云 / chunk 6c 小红书同等"用户浏览器能看到 = Skyler
  能看到"）

### 真接通点

* config: ``activity_watcher`` 全段（commit 9）
* code: ``backend.integrations.activity_monitor`` / ``url_fetcher`` /
  ``activity_watcher``（commits 1 / 3 / 4）
* capabilities: ``backend.capabilities.screen`` 4 cap（commit 2）
* listener: ``backend.proactive.activity_smart.activity_smart_handler``（commit 5）
* trigger class: ``backend.proactive.triggers.activity.ActivityProactiveTrigger``
* API: ``GET/PATCH /api/activity/{status,config,permissions}``（commits 7-8）
* frontend: ``ActivityAwarenessSection`` + ``ActivityPermissionModal``（commits 6-7）
* Info.plist: ``NSAppleEventsUsageDescription``（commit 7）

### 已知 V1 限制

* 浏览器只覆盖原生 Chrome + Safari，**不**覆盖 Brave / Arc / Chromium fork
  / Firefox（不同 AppleScript dict）—— backlog
* 截屏 + OCR 留 chunk 8b（"完整屏幕感知"），本 chunk 只做 URL / app metadata
* Windows / Linux 平台 activity_monitor 全函数返 None（参 README Known Problems）
* per-tool toggle 不细到"对某类 activity 仅在 weekday 触发"等高级节流；只
  按 label 节流 + daily cap

### hotfix-9 修复:get_browser_url frontmost gate(2026-05-13)

chunk 8a spec 漏洞:``get_chrome_active_tab`` / ``get_safari_active_tab``
的 AppleScript 形如 ``tell application "Google Chrome" to get URL of
active tab of front window`` — 只查"Chrome 进程有没有 window",**不**查
"Chrome 是不是 frontmost macOS app"。

#### 用户报告场景

> 早上看 bilibili 招聘页 → 切到 VSCode 写代码,Chrome 还在后台
> → 5 min 后 Momo 主动开口:"看到你在看招聘信息,要不要聊聊?"
> → 我根本不在看招聘啊!

backend log:``app='momoos' url=https://jobs.bilibili.com/social/positions/26333``
—— frontmost ≠ Chrome,但 URL 仍报 Chrome 的 active tab。

#### Root cause

``ActivityWatcher.snapshot()`` 在 chunk 8a commit 4 直接调两个 raw primitive
拼 ``state.browser``,**不**与 ``get_active_app()`` 交叉验证:

```python
chrome = _am.get_chrome_active_tab()  # 即使 Chrome 在后台也返 active tab
safari = _am.get_safari_active_tab() if chrome is None else None
if chrome is not None: browser_dict = {browser: "chrome", url, title}
```

下游链式 cascading:
1. ``state.browser.url`` 有值 → ``_detect_changes`` 觉得 URL 没变(还是 bilibili)
2. ``_url_dwell_start`` 不重置,继续累积
3. ``get_current_stay_info`` URL 优先 → 返 ``key=url:bilibili, duration=300s+``
4. chunk 8a-ext judge 看到"用户在 bilibili 停 5+ min"调 qwen-turbo → speak=true
5. Momo fire ``activity_judge_chime_in`` 主动聊招聘 → 用户错愕

#### 修法选型(audit)

| 方案 | 优点 | 缺点 |
|------|------|------|
| AppleScript 内嵌 ``frontmost of (process X of system events)`` | 一次 osascript 调用 | 需要 Accessibility 权限(NSAppleEvents 之外又一道弹窗),UX 不友好 |
| activity_monitor 层 wrapper + ``NSWorkspace.frontmostApplication`` | 零额外权限,与 chunk 8a get_active_app 同源 | 多一次 NSWorkspace 调用(~微秒级) |

**选方案 2** — frontmost 判断在 activity_monitor 层包一个 ``get_browser_url()``
wrapper,内部先 call ``get_active_app()`` 拿 localizedName,在
``_BROWSER_APPS`` frozenset 命中才路由到对应 AppleScript;否则返 None。

#### 实现

``backend/integrations/activity_monitor.py``:

```python
_BROWSER_APPS = frozenset({
    # Chromium 系 + WebKit + Gecko,中英文 alias 覆盖(hotfix-8 i18n 教训)
    "google chrome", "chrome", "google chrome 浏览器",
    "chromium", "microsoft edge", "edge", "brave browser", "brave",
    "arc", "vivaldi", "opera", "opera gx",
    "safari", "safari 浏览器", "safari technology preview",
    "firefox", "firefox 浏览器", "firefox developer edition", ...
})

def get_browser_url() -> Optional[Tuple[str, str, str]]:
    active = get_active_app()
    if active is None: return None
    if active.strip().lower() not in _BROWSER_APPS: return None
    al = active.lower()
    if "chrome" in al or "chromium" in al: ... → ("chrome", url, title)
    if "safari" in al: ...                  → ("safari", url, title)
    return None   # 识别但无 AppleScript impl(Firefox/Edge/Arc 等)
```

raw primitives ``get_chrome_active_tab`` / ``get_safari_active_tab`` **保留**
不变 —— 让既有 9 个单元测试 + 内部调用点不破。``get_browser_url`` 是高层
语义("用户当前在看什么 URL")的唯一入口。

#### 上游调用点统一接入(commit 1+2)

* ``backend.integrations.activity_watcher.snapshot()`` — 切到 ``get_browser_url()``
* ``backend.capabilities.screen.get_browser_url`` (LLM capability) — 切到 wrapper
* ``backend.capabilities.screen.get_browser_content`` — 同切;LLM 通过这两个
  capability 问"用户看什么 URL"时获得 frontmost 语义,与 ActivityWatcher 一致

#### stay_key 逻辑**不变**

``get_current_stay_info`` 既有 "URL 优先,无 URL fallback app" 是对的。
hotfix-9 修的是"什么时候有 URL"的上游 gate。一旦 ``snapshot.browser=None``
(非浏览器 frontmost),``_detect_changes`` 看 ``new_url=None vs old_url=
bilibili`` → ``_url_dwell_start = 0``(重置),``get_current_stay_info``
自然 fallback 到 ``app:VSCode``。切回 Chrome 时 ``_url_dwell_start = now``
(重新打点),不带过来旧累积 — 行为与"用户视觉感受"一致。

#### 跨平台 + 多浏览器

| 平台 / 浏览器 | get_browser_url 行为 |
|--------------|---------------------|
| macOS Chrome frontmost | ``("chrome", url, title)`` |
| macOS Safari frontmost | ``("safari", url, title)`` |
| macOS Chrome 后台(VSCode frontmost) | ``None`` — hotfix-9 修复主案 |
| macOS Firefox/Edge/Arc/Brave frontmost | ``None`` — 识别但无 AppleScript impl,与 hotfix-9 前用户体验一致(走 app:Firefox stay) |
| 非 macOS | ``None`` — get_active_app 短路 |
| 中文 macOS 终端 frontmost | ``None`` — "终端"不在 _BROWSER_APPS |

#### 测试

* ``tests/test_activity_monitor.py`` +9 case — Chrome/Safari frontmost / VSCode
  frontmost / momoos frontmost / 终端 frontmost / get_active_app=None /
  Chrome frontmost 无 window / Firefox(识别但无 impl)/ 大小写空格归一化
* ``tests/test_screen_capabilities.py`` 8 case 改 mock ``get_browser_url`` wrapper
  (旧的 chrome/safari 双 mock 简化为单 mock)
* ``tests/test_activity_watcher.py`` +3 case — snapshot 非浏览器 frontmost →
  browser=None / _detect_changes 重置 url_dwell / 端到端三步走(Chrome→VSCode
  →Chrome)stay_key 切换正确

137 PASS 跨 7 个 chunk 8a / 8a-ext 相关文件 / 0 regression。

#### 验收 5 条对照

1. Chrome 在 bilibili tab → log ``app='Google Chrome' url=...bilibili`` ✓
2. 切到 Skyler/IDE → log ``app='momoos' url=—``(URL 空)✓ — hotfix-9 核心
3. 切回 Chrome → URL 重新出现 ✓ —(``_url_dwell_start = now`` 重新打点)
4. stay_timer 在切 frontmost 时正确重置(browser→non-browser:url→app key)✓
5. 0 regression on chunk 8a + 8a-ext V1+V2 + UX + hotfix-3-8 ✓ — 137 PASS

---

## 十五之M、CapabilityPanel accordion + category 计数（UX-002 起）

### 设计目标

UX-001 + hotfix-6 把 SettingsPanel 底部 ``ExtensionsSection`` MCP servers 区改
成 accordion 单行折叠后，**剩余主体** —— ``CapabilityPanel.tsx`` 内 67
capability 仍按 category 平铺成大卡片（每卡 ~180 行 markup：icon / 名 /
description / 谁能调 / 触发 / Google OAuth footer / refresh），导致 Settings
Panel 整体高度 N 屏。UX-002 把这部分也 accordion 化，目标 ~1-2 屏。

### 抽象层

新组件 ``frontend/src/components/CapabilityRow.tsx`` —— **单层 accordion row**，
与 UX-001 ``ClientRow``/``ToolList`` 平行但**不复用**（后者 MCP-specific 双层
server-tool 关系）。Props：

```
name              capability 唯一标识符（key + data-capability 属性）
displayName       显示名
briefDescription  折叠态小灰字（caller 自己 trim，CapabilityPanel 走 _briefDesc
                  ~50 字符 + 标点边界截断）
statusBadge?      折叠态右侧 ReactNode（健康灯 / 文字 / ext 角标，caller 填）
leftIcon?         折叠态最左侧 icon（CapabilityIcon 等）
expandedContent   展开态完整 body（caller 填——description / 谁能调 / 触发 /
                  error / refresh）
defaultExpanded?  default **false**（UX-002 硬约束：全折叠启动）
```

实现要点：

* ``useState<boolean>(defaultExpanded)`` —— 无 derived state
* ``{expanded && (<div>...{expandedContent}</div>)}`` —— 短路 gate（防回归
  到默认全展开）
* aria-expanded + aria-label='折叠'/'展开' + data-capability={name} 无障碍 +
  DOM lookup 友好

### CapabilityPanel 重构

* **删 MCP banner / 外部 clients section**（243 行）—— 跟 SettingsPanel 底部
  ``ExtensionsSection`` (UX-001 + hotfix-6) 信息重复。``mcp_external`` category
  的 capability（filesystem ×14 + brave-search ×2）仍在 capability 主列表里
  显示，每行 ``[ext · source_server]`` 角标区分
* **``CapabilityCard`` rename → ``CapabilityDetail``**：body-only，不再渲染
  icon/name/health header（已由 CapabilityRow 折叠态承担）
* category header 加 ``{N} cap`` 计数 badge
* **calendar 特殊 UI 归位到 category-level**：新组件
  ``CalendarGoogleAuthBadge`` 挂在 calendar header 右侧（紧邻 ``[测试简报]``
  按钮）。``CardProps`` 砍掉 ``googleStatus`` / ``onGoogleAuth`` /
  ``onGoogleRevoke`` / ``googleBusy`` 4 props，``CapabilityDetail`` 签名
  收紧到 ``{cap, onRefresh}: CardProps`` 两参

### Layout 示意

```
CALENDAR  [8 cap]       [Google: 已授权 · user@…]  [重新授权]  🧪 [测试简报]
 ▶ today_events (apple)                                    ● 健康
 ▶ today_events (google)                                   ● 健康
 ▶ upcoming_events (apple)                                 ● 健康
 …

MEDIA     [23 cap]
 ▶ bilibili.search_video                                   ● 健康
 …

MCP_EXTERNAL  [16 cap]
 ▶ ext.filesystem.read_file      [ext · filesystem]        ● 健康
 …
```

每行点 caret 展开 → 看 description 整段 + 谁能调 / 触发 badge + error 文字
（如有）+ [刷新状态] 按钮。

### 不动的

* SettingsPanel 自己的 8 个 ``<Section title=...>`` 块（Memory / TTS / 角色状态
  / 主动陪伴 / 剪贴板 / 基础信息 / ASR-VAD / 启动）—— 配置项不应折叠
* SettingsPanel 底部 ``<ExtensionsSection>``（UX-001 + hotfix-6 已 accordion）
* 后端任何代码（``/api/capabilities`` 响应 schema 不变）

### 兼容 + 防回归

* 测试 fixture ``panel``/``src``：**剥掉行 + block 注释**后再 grep —— 让
  "删 ``MCPServerBanner``" 这类解释性注释里出现的标识符不触发假阳性
* commit 1 ``test_no_default_expanded_override`` 测试断言 CapabilityPanel **不传**
  ``defaultExpanded`` —— 依赖 commit 1 锁的 default false 实现"全折叠"
* commit 2 ``test_capability_icon_only_once`` 测试断言 ``<CapabilityIcon`` 在
  panel 内只出现 1 处（CapabilityRow leftIcon slot），防 CapabilityDetail 又
  内联 icon 导致折叠态 + 展开态都显示

---

## 十五之N、strip 工程契约延续 + frontend error normalize（hotfix-7 起）

### strip 第 5 道 — WS send_text_chunk 兜底

hotfix-1 起 ``backend/utils/text_filters.py`` 顶部就已声明:

> 工程契约(v3 封盘后):任何未来新加 LLM 标签输出格式都必须同步加入
> ``_TOOL_CALL_FALLBACK_STRIP_PATTERNS`` 或对应 strip 函数 +
> ``_PARTIAL_OPEN_TAG_RE``。漏一个 → TTS 立刻念出标签内容,链路闭环坏掉。

实测教训(hotfix-7):chunk 3b 落地 ``<state_update>`` tag 时,主路径
``ws.py`` 挂了 ``_parse_state_update``,但 **proactive engine 的两个 stream
函数(``run_trigger`` + ``run_wake_call_trigger``)漏挂**。结果 wake_call /
morning_briefing / lunch_call / dinner_call / activity-based 5 个 trigger
触发时 raw ``<state_update mood="..." />`` 字面字符串以 text_chunk push 进
前端 widget。

修法分两层:

1. **根因**: 两个 stream 函数都补 ``_parse_state_update`` + ``_apply_
   proactive_state_update`` helper(与 ws.py ``_apply_and_push_state_update``
   同语义,push 通道走 ``connection_manager.push``)
2. **防回归**(契约的"第 5 道"): 每个 ``text_chunk`` push 之前**统一**
   调 ``strip_all_for_tts(sentence)`` 兜底:

   - ws.py 主路径 line 1000
   - engine.py ``run_trigger`` text_chunk push
   - engine.py ``run_wake_call_trigger`` text_chunk push

   正常路径下 sentence 已被 5 道 parser(emotion / state_update / thinking /
   motion / tool_call fallback)剥过,本兜底 idempotent no-op。任一 parser
   漏点 / LLM 新格式时,chunk 不会带 raw 标签出 WS;空 chunk 跳过 push。

3. **持久化路径** ``_strip_format_tags`` 同样升级到 ``strip_all_for_tts``
   (原只覆盖 emotion / motion / thinking 三档,漏 state_update +
   tool_call fallback,导致 chat_history 入库后被 chunk 9 hotfix-3
   ``SUSPICIOUS_TAG_RE`` 兜底剥 + 每轮 log warning 噪声)。

### 工程契约升级版

任何新增 LLM 标签输出格式必须:

1. 加 strip 函数(``strip_X``)+ 加入 ``strip_all_for_tts`` 串联调用链
2. 加 ``_parse_X`` parser 在 ``backend/agents/chat.py``
3. **两条路径都挂 parser**:
   - ``backend/routes/ws.py`` 主路径(``_handle_message_safe`` 的 stream loop)
   - ``backend/proactive/engine.py`` 两个 stream 函数(``run_trigger`` +
     ``run_wake_call_trigger``)
4. 加 ``_PARTIAL_OPEN_TAG_RE`` 容错(防流式 sentence boundary 落在标签里)
5. 测试覆盖防回归(参 ``tests/test_hotfix7_proactive_strip.py`` 12 条断言:
   每个 text_chunk push 之前 800 字符窗口内必须出现 parser call)

### Frontend error normalize 契约

Tauri ``invoke()`` 在 Rust 端返 ``Result<T, String>`` Err 时,JS reject 收
到的是**plain string** —— **不是** ``Error`` 对象。前端 catch 用
``(e as Error).message`` 取消息 → 字符串上无属性 → 返 ``undefined`` →
toast 显示 ``undefined``。

hotfix-7 定型约定:

* ``frontend/src/lib/window.ts`` 所有 ``invoke`` 调用必须用 try/catch 包,
  ``typeof e === 'string'`` 分流后 ``throw new Error(...)`` 重新抛
* 调用方失败路径用 ``extractErrorMessage(e: unknown)`` 兜底
  (``SettingsPanel.tsx`` 已落地),三档处理 string / Error / object
* HTTP 失败(fetch 非 2xx)的 error 必须带 status + body 摘要,不只是
  ``HTTP 500``

类似契约可推广到任何 ``invoke`` 包装层(``invokeBridge`` / 等)。

---

## 十五之O、macOS app name i18n + config.yaml 幂等契约（hotfix-8 起）

### macOS NSWorkspace localizedName i18n

``backend/integrations/activity_monitor.get_active_app()`` 调
``NSWorkspace.sharedWorkspace().frontmostApplication().localizedName()``。
该 API 在**中文 locale macOS** 上对带 ``Contents/Resources/zh-Hans.lproj/
InfoPlist.strings`` 的 bundle 返**本地化字符串** ——

* Apple Terminal.app → ``'终端'``(实测中文 macOS)
* Apple Xcode → ``'Xcode'``(无 zh lproj 翻译)
* VSCode / Cursor / JetBrains / Sublime / Atom / Nova / 第三方编辑器 →
  英文(无 zh lproj)

**契约**:任何 app-name set(``_IDE_APPS`` / ``_MUSIC_APPS`` / 等)在
扩展时只对 **Apple 自家原生 app**(Terminal / Xcode / Music / Pages /
Numbers / iMessage / etc.)需要 audit + 加中文 alias。第三方 app 不需要,
因为它们的 bundle 不带 zh lproj。

实测 audit table 见 README Known Problems hotfix-8 closure 条目 + 
``tests/test_hotfix8_ide_i18n.py`` 13 条断言。

### config.yaml 幂等契约

cc-task spec 描述的"restore user's runtime tweaks" / "merge config"等
post-commit 操作必须**幂等**:

1. **检测后追加**:``cat >> file << EOF`` 前先 ``grep "^<key>:" file``,
   存在则 skip(不重复 append)
2. **声明式合并**:用 ``yq merge --inplace --type-deep`` 或类似工具替代
   shell heredoc 拼接(yq 会合并同 key 而非追加)
3. **strict YAML 测试**:本地 + CI 测试期间用自实现 ``StrictLoader``
   (mimic serde_yaml) 检测 duplicate key,而非默认 permissive
   ``yaml.safe_load``(silently 取最后一个,掩盖 bug)
4. **CC harness restore 流程审计**:每次 docs commit 末尾 restore 用户
   tweaks 时,先 ``git stash`` + apply 而不是从 tmp snapshot 重新 append

hotfix-8 实测教训:chunk 8a commit 9 restore 脚本对一个**已经含**
activity_watcher block 的快照又 ``cat >> EOF`` 第二次追加,工作树出现
两个 bit-identical block。Python ``yaml.safe_load`` permissive 没暴露,
Rust ``serde_yaml`` strict 在 Tauri ``write_config_field`` 调用时报
``parse yaml: duplicate entry with key "activity_watcher"``,导致所有
config 写入 toggle 全失败。**hotfix-7 error normalize 暴露了真因**,
hotfix-8 修了实例 + 加 ``.gitignore`` ``config.yaml.backup-before-*``
pattern + README Known Problems #16 backlog 留 root-cause 修法。

---

## 十五之P、三层 accordion + 情绪 UI 左上角(UX-003 起)

### 设计目标

UX-002 把 CapabilityPanel 67 capability 改成单行 accordion 后,Settings 高度
从 N 屏缩到 ~2 屏。但 9 个 category title 仍**固定显示** + 多 provider
category(media 23 cap / mcp_external 16 / calendar 8)展开后仍是 flat 长
列表。UX-003 全栈 accordion:

```
默认状态(全折叠):
▶ CALENDAR     [8 cap]                 [Google: 已授权] [测试简报]
▶ CHARACTER    [2 cap]
▶ CLIPBOARD    [3 cap]
▶ FILES        [3 cap]
▶ MCP_EXTERNAL [16 cap]
▶ MEDIA        [23 cap]
▶ MUSIC        [7 cap]
▶ SCREEN       [4 cap]
▶ SYSTEM       [1 cap]
                                       ← Settings 整体 1 屏内可见
```

```
点开 MEDIA(多 provider category)→ 三层:
▼ MEDIA        [23 cap]
   ▶ bilibili         [11 cap]
   ▶ media_control     [5 cap]
   ▶ netease           [6 cap]
   ▶ xhs               [1 cap]
                                       ← provider 子分组
```

```
再点 ▶ netease → 看到 capability list:
   ▼ netease           [6 cap]
      ▶ local_play_song      播放网易云单曲
      ▶ local_play_playlist  播放网易云歌单
      ▶ local_pause          暂停 mpv 播放
      ...                                ← 单行 UX-002 accordion
```

### Provider 自动分组规则

```ts
function _extractProvider(capName: string): string {
  const parts = capName.split('.');
  if (parts[0] === 'ext' && parts.length >= 2) {
    return `ext.${parts[1]}`;  // ext.<server>.<tool> → ext.<server>
  }
  return parts[0];              // 否则取首段
}
```

audit 实测覆盖完整 67 cap:
* ``ext.brave-search.brave_web_search`` → ``ext.brave-search`` (``-`` 不被
  ``.`` 误切)
* ``apple_calendar.today_events`` → ``apple_calendar``
* ``netease.local_play_song`` → ``netease``
* ``xhs.parse_url`` → ``xhs`` (独占 1 cap 也渲染 provider row,规则一致性)

### 多/单 provider category 分支

| Category | Provider 数 | render 路径 |
|---|---:|---|
| calendar | 3 (apple_calendar / google_calendar / calendar 路由) | **三层** |
| mcp_external | 2 (ext.filesystem / ext.brave-search) | **三层** |
| media | 4 (bilibili / netease / media → media_control / xhs) | **三层** |
| system / character / clipboard / files / music / screen | 1 | 二层(直接 flat capability list,与 UX-002 行为一致) |

### Provider display 映射

```ts
const PROVIDER_DISPLAY: Record<string, string> = {
  media: 'media_control',  // category=media 内 ``media.X`` cap 显示成 ``media_control``
};
```

理由:capability 命名 ``media.next_track`` / ``media.play_pause`` 等,实际
对应 ``backend/capabilities/media_control.py``(macOS NowPlaying-cli 包装)。
UI 显示 ``media_control`` 与 backend 语义一致 + 跟 category title ``MEDIA``
区分,避免视觉撞名。

``ext.X`` provider key 显示时去掉 ``ext.`` 前缀(``ext.filesystem`` 显示
为 ``filesystem [ext]`` + 加 ``ext`` 角标)。

### State 设计

```ts
// 3 个独立 Set state,每个 layer 默认空 = 全折叠
const [expandedCategories, setExpandedCategories] = useState<Set<string>>(new Set());
const [expandedProviders, setExpandedProviders] = useState<Set<string>>(new Set());
//                                                     ^^^ key = `${cat}::${provider}`
//                                                     防 namespace 撞(netease 在 music + media)
// CapabilityRow.expanded 由 CapabilityRow 内部 useState 管,defaultExpanded
// = false(UX-002 commit 1 锁)
```

### Header 嵌套 button 避坑

calendar category header 内嵌 ``[测试简报]`` + ``[Google OAuth 连接/重新授权]``
按钮。如果整个 header 用 ``<button>`` 包,会形成 nested-button(HTML 非法
+ a11y 反模式)。改用 ``<div role="button" tabIndex={0}>`` + Enter/Space
键盘事件 + ``aria-expanded`` / ``aria-label`` 无障碍。子按钮外面包一层
``onClick={(e) => e.stopPropagation()}`` 阻止误翻 fold。

### 情绪 UI 位置(UX-001 commit 3 → UX-003 commit 3)

UX-001 commit 3 修过 ``CharacterStatePanel`` panel-mode 位置(``top: 12px →
48px`` 避开 TopBar)。UX-003 commit 3 再改 ``right: 16px → left: 16px``——
原因:

* Panel mode CharacterView 区域右上角有 ``<button className="absolute top-4
  right-4 z-30">[ScrollText] 历史</button>``(modes/Panel.tsx:62-73)
* 情绪条 ``right: 16px / top: 48px`` 紧邻历史按钮下方,视觉重叠 + hover
  互相覆盖
* 左上角实测**完全空闲**:CharacterView 是 ``absolute inset-0 z-0`` 满铺
  背景,无其他 positioned 元素;TopBar 在 ``relative z-50`` 占顶 0-40px,
  情绪条 top: 48px 在它之下
* z-index 30 维持(不需要浮到 TopBar 之上反向遮 CharacterSwitcher dropdown)

Widget 模式无 TopBar / 无历史按钮 → 沿用 ``right: 8px / bottom: 8px`` 不动。

### 防回归测试覆盖

15 个 grep-style 断言锁定 layer 1/2/3 state 初始化 + provider extraction
规则 + 多/单 provider 分支 + 嵌套 button 避坑 + display map + ext 角标
+ ``setExpandedCategories`` 仅在 ``toggleCategory`` 调用(防回归自动展开)。

---

## 十五之Q、智能陪伴 judge 慢路径(chunk 8a-ext 起)

### 设计目标

chunk 8a 快路径(``activity_smart._classify``)只覆盖硬编码白名单:IDE /
音乐 app / 技术文档 URL / long_focus / late_night_ide。用户看招聘页 /
Twitter / 普通网页 / 普通 app 时 Momo 不主动说话 — 陪伴感不够。

简单粗暴"任何停留就主动说话" → 会变骚扰。chunk 8a-ext 加**慢路径 LLM
judge**:用户停同一 app/URL 5+ min → 调 qwen-turbo 判断"现在主动说话是
开心还是烦",yes 才走 fire trigger。

### 快慢路径并存

| 路径 | 触发 | 决策 | 用例 |
|------|------|------|------|
| 快路径(chunk 8a) | ``register_change_listener`` (app/url change) | 硬编码 ``_classify`` 白名单 | 切 IDE / 音乐 app / 技术文档 URL |
| 慢路径(chunk 8a-ext) | ``register_poll_listener`` (每 poll) | qwen-turbo LLM judge | 用户停某 page 5+ min |

两路共享 ``_last_fire_per_label`` 节流 + ``_today_count`` daily_cap 计数器。
快路径命中 → 不再 judge(快路径 fire 已用 1 个 cap,且 fire_throttle 也会
挡同 label 30 min 内重 fire)。

### 三重门防 LLM 滥用

1. **min_stay_minutes**(默 5)— ``maybe_judge`` 内 ``duration < min_stay``
   直接返 None,不调 LLM
2. **judge throttle**(默 10 min)— 同 stay_key ``_last_judged_per_key`` dict
   节流,10 min 内重复 stay 不重判
3. **fire_throttle**(共享快路径 30 min)— ``activity_judge_chime_in`` label
   30 min 内已 fire → 不调 judge LLM(即便 judge 想 yes 也 fire 不出,何必
   白调)
4. **daily_cap**(共享 5/天)— ``_today_count >= cap`` → 不调 judge LLM

典型场景:用户在某 page 30 min,judge 实际调用次数 = max(1, 30/10) = 3 次
LLM(每次 qwen-turbo 几百 tokens ≈ 几分钱)。

### LLM 输出契约

JSON object,markdown fence 容错(``\`\`\`json {...} \`\`\``):

```json
{
  "speak": true | false,
  "reason": "<10 字内>",
  "topic_hint": "<10-20 字 Momo 该提话题方向,可空>"
}
```

容错:
* ``"speak": "true"`` 字符串 / ``"speak": 1`` 数字 → bool 转
* reason / topic_hint 截 40 / 80 字防 LLM 乱讲被注入下游 prompt
* parse 失败 → silent None (worker 不阻塞 watcher 主 loop)
* LLM 异常(超时/网络) → silent None + 记账 throttle 防 retry storm

### 判断准则(prompt 内)

* 私密(银行/邮箱/密码管理器)→ false
* IDE 专注 → false (快路径覆盖)
* 娱乐/社交/视频 > 10 min → 沉浸,倾向 false
* 找资料/学习/公开网页 → 倾向 true
* 求职/查日程/看新闻 → 倾向 true
* 今日 cap >= 0.8 → 严格 false
* 距上次说话 < 5 min → false
* 不确定 → 倾向 false(沉默 > 骚扰)

### topic_hint 注入

judge 返 ``topic_hint`` 后,``ActivityProactiveTrigger("activity_judge_chime_in",
detail={..., topic_hint})`` 实例化。``triggers/activity.py:_judge_chime_in_prompt``
把 ``topic_hint`` 作为 anchor 注入主 LLM (ChatAgent) 的 system prompt:

> 判断模型建议话题方向: **{topic_hint}**(可作 anchor,不必强用)

主 LLM 仍按 ``_BASE_GUIDANCE`` 40-80 字硬要求生成开场,不强制使用
topic_hint(LLM 有自由度避免变成机械)。

### State

```python
# activity_judge.py
_last_judged_per_key: dict[str, float] = {}    # stay_key → 上次 judge 时间
# activity_smart.py(共享)
_last_fire_per_label: dict[str, float]         # 包括 activity_judge_chime_in
_today_count: int                              # 共享 daily_cap counter
```

### Settings toggle

``config.activity_judge.enabled: true``(默 ON)。SettingsPanel
[活动感知] section 加二级 toggle"智能陪伴 — qwen-turbo 判断(5 分钟停留
触发)",PATCH ``/api/activity/config`` body ``judge_enabled: bool``。

关闭后 ``judge_poll_handler`` 在 ``get_judge_enabled()`` 返 False 时 silent
return — 快路径完全不受影响。

### 文件清单

* ``backend/proactive/activity_judge.py``(new, 337 行)— Config / Decision
  dataclass / Prompt / LLM call / parse / throttle / maybe_judge
* ``backend/proactive/activity_smart.py``(+177 行)— ``judge_poll_handler``
  + ``_minutes_since_last_user_turn`` + ``_JUDGE_LABEL`` 常量
* ``backend/proactive/triggers/activity.py``(+30 行)— ``_judge_chime_in_prompt``
  builder + ``_PROMPT_BUILDERS`` 加 ``activity_judge_chime_in`` label
* ``backend/integrations/activity_watcher.py``(+71 行)— ``_PollListenerFn``
  type + ``register_poll_listener`` / ``clear_listeners`` extend +
  ``get_current_stay_info`` getter + run_loop poll dispatch
* ``backend/main.py``(+5 行)— lifespan ``register_poll_listener(judge_poll_handler)``
* ``backend/routes/activity_api.py``(+18 行)— config response/patch 加 4
  judge 字段
* ``frontend/src/lib/activity.ts``(+5 行)— interface 加字段
* ``frontend/src/components/ActivityAwarenessSection.tsx``(+15 行)— 二级
  toggle UI
* ``config.yaml``(+17 行)— 新 ``activity_judge:`` block

---

## 十五之R、用户活跃度 idle 闸(chunk 8a-ext V2)

### 设计目标

chunk 8a-ext V1 上线后真机回归发现两类"自言自语":

1. 用户开 Chrome 看完文档后**离开电脑去开会**,Chrome window 仍 frontmost、URL
   未变 — V1 stay 计时持续累积,5 min 后 judge 调 qwen-turbo → fire chime_in
   → Momo 对着空椅子说话(还浪费 cap)
2. 用户**晚上锁屏睡觉**但 macOS 应用未真切换 — 同样 misfire

V1 三重门 + daily_cap 防得了"骚扰"(短时间多说),防不了"人不在"(长时间静止
但前台不变)。chunk 8a-ext V2 加第 4 道闸 — **键鼠 idle 检测**。

### macOS 路径选型

| 方案 | 依赖 | 启动开销 | 评估 |
|------|------|---------|------|
| ``Quartz.CGEventSourceSecondsSinceLastEventType`` | ``pyobjc-framework-Quartz`` 新 pip | 一次 import | 准但需新依赖 |
| ``ioreg -c IOHIDSystem`` subprocess + ``HIDIdleTime`` 正则 | 零新依赖(macOS 自带 + ``subprocess`` 已用) | 每次 fork ~30ms | **选这条** |

decided: 选 **B**。chunk 8a 已建立 ``subprocess.run(osascript)`` 范式
(timeout / capture_output / check=False / silent None fallback);idle 检测
只在 judge 慢路径每 ``poll_interval`` (默 30s) 跑一次 + 已过 min_stay 5 min
闸,30ms fork 开销可接受。零新 pip 包尤其重要 — Tauri bundle 体积已经
顶到 macOS DMG 上传配额。

### 实现

``backend/integrations/activity_monitor.py:get_idle_seconds()``:

```python
res = subprocess.run(["ioreg", "-c", "IOHIDSystem"],
                     capture_output=True, text=True, timeout=2.0, check=False)
m = re.search(r'"HIDIdleTime"\s*=\s*(\d+)', res.stdout)
return int(m.group(1)) / 1e9  # ns → s
```

跨平台 graceful:非 macOS / ``shutil.which("ioreg") is None`` / ``TimeoutExpired``
/ subprocess 异常 / ``returncode != 0`` / 正则 no match → **全部返 None**。
调用方按 None 视为"无法检测,假定活跃",维持 V1 行为。

### Idle 闸位置 — 闸顺序

``maybe_judge`` 闸列(自上而下):

```
1. judge_enabled?       → False return None
2. stay_info valid?     → False return None
3. duration >= min_stay → 否 return None      ← V1
4. throttle 闸          → 命中 return None     ← V1
5. _record_judged(key)  ← 提前记账防 retry storm
6. ★ idle 闸 (V2 新加)  → idle > threshold return None
7. _build_judge_prompt + _call_judge_llm + _parse_judge_output
```

放在 **5 之后、6 之前** 有意:

* LLM 没跑 → 不烧 token / 不调网络
* 记账已写 → idle skip 也吃 throttle 配额(防 idle 闸打开关闭间反复 retry)
* 顺序在 throttle/min_stay 之后 → 不增加便宜闸的 subprocess 调用

### 为什么不放更前

idle 是**最贵**的闸(每次 fork ioreg 子进程)。throttle / min_stay 用 dict
查询和数值比较 → 纳秒级,该先挡的先挡。短停 (< 5 min) 直接不查 idle —
也几乎不会有"短停 5 min 内人就离开"的真实场景。

### Config + UI

``config.yaml`` ``activity_judge.idle_threshold_seconds: 300``(默 5 min)。
* 0 = 关闸(老 V1 行为,适合不爱被打扰的用户禁用 idle 检测让 judge 总跑)
* 负数 ``max(0, ...)`` clamp 到 0
* 非整数 / 缺失 → fallback 300

``SettingsPanel [活动感知]`` 在智能陪伴 toggle 之下条件渲染一个 ``<input
type="number" min=0 max=3600 step=30>`` — 仅 ``judge_enabled=true`` 时显示
(judge 关时 idle 闸无意义,不暴露给用户避 UI 噪音)。blur/Enter 触发
PATCH ``/api/activity/config``  ``judge_idle_threshold_seconds: int``,
backend clamp 到 [0, 3600] 防 UI 误输入。

### Audit 决定:阈值默认 300s 而不是 120/180

* < 120s:用户喝水 / 看手机 / 思考时键鼠静止 30-90s 很常见,过短会
  误判活跃用户为离开
* 300s:apple iOS auto-lock 默认 30/60/180/300s 链,普通办公屏保
  也常设 300s
* > 600s:长时间静止显然离开,但 V1 throttle 闸 (10 min/key) 已经
  挡住大部分多余调用,不必再卡

### 跨平台行为表

| 平台 | get_idle_seconds | 闸行为 |
|------|-----------------|--------|
| macOS ioreg 正常 | float(秒数) | idle > threshold → skip |
| macOS ioreg 缺失/失败 | None | 不挡(假定活跃,V1 行为) |
| Linux | None(IS_MACOS=False 短路) | 不挡(V1 行为) |
| Windows(未来 PR) | None | 不挡;后续可挂 ``GetLastInputInfo`` |

### 测试

``tests/test_chunk8a_ext_v2_idle.py``(新,21 case):
* Part A get_idle_seconds 8 case — 正常 / 长 idle / 非 macOS / ioreg 缺失 /
  timeout / 异常 / 非零 returncode / 正则不匹配
* Part B get_idle_threshold_seconds 5 case — default / custom / 0 / 负数 /
  非整数
* Part C maybe_judge 5 case — idle 100<300 / 600>300 / None / 异常 / 0 阈值
* Part D 闸顺序 3 case — record 之后 / min_stay 之前不查 / disabled 之前不查

V1 30 case + V2 21 case = **51 PASS, 0 regression**(``--asyncio-mode=auto``)。

### 文件清单

* ``backend/integrations/activity_monitor.py``(+70 行)— ``get_idle_seconds``
  + ``_HID_IDLE_RE`` + ``_IOREG_TIMEOUT_SECONDS``
* ``backend/proactive/activity_judge.py``(+27 行)— ``get_idle_threshold_seconds``
  getter + ``maybe_judge`` 内 idle 闸
* ``backend/routes/activity_api.py``(+19 行)— ``judge_idle_threshold_seconds``
  字段 GET/PATCH 双向
* ``frontend/src/lib/activity.ts``(+3 行)— 字段类型
* ``frontend/src/components/ActivityAwarenessSection.tsx``(+55 行)— idleDraft
  state + commitIdle handler + conditional number input row
* ``config.yaml``(+7 行)— ``idle_threshold_seconds: 300`` + 注释
* ``tests/test_chunk8a_ext_v2_idle.py``(new,291 行,21 case)

---

## 十五之S、get_active_app 走 osascript 修 headless 缓存(hotfix-10)

### Bug

``backend/integrations/activity_monitor.get_active_app()`` 自 chunk 8a 起
用 ``AppKit.NSWorkspace.sharedWorkspace().frontmostApplication().localizedName()``。
看似稳:**fresh** Python 进程里第一次调用确实拿到当前 frontmost。但
**long-running headless** 进程里它**只返进程启动那一拍的 frontmost**,
之后用户切多少次 app 都不更新。

实测证据(chunk 14 实施期间用户报告):
* backend daemon 启动时 Terminal frontmost
* 用户后续切 Safari / Chrome / IDE / etc
* backend log tick=2 ~ tick=27 持续 30+ 分钟全是 ``app='终端' url=—``
* 用户 CLI ``from backend.integrations import activity_monitor;
  activity_monitor.get_active_app()`` 在同一长跑进程也返 ``'终端'``

### Root cause

NSWorkspace.frontmostApplication 不是同步查询 — 它通过 **distributed
notifications** 接收"frontmost 变化"事件并维护内部缓存。dispatch 这些
事件需要 ``NSRunLoop`` 在主线程跑。headless Python 进程(daemon / 子进程
/ 任何非 GUI 应用)**没有 NSRunLoop**,事件永远不被 deliver → 内部缓存
永远是初始值。

经典 macOS pyobjc 坑。同类型 bug 在 ``NSNotificationCenter`` /
``NSDistributedNotificationCenter`` 类 API 都会出现。

### 修法 — osascript 子进程,不依赖 RunLoop

```python
res = subprocess.run(
    ["osascript", "-e", "POSIX path of (path to frontmost application)"],
    capture_output=True, text=True, timeout=2.0, check=False,
)
path = res.stdout.strip().rstrip("/")       # /Applications/Safari.app/
name = os.path.basename(path)               # Safari.app
if name.endswith(".app"): name = name[:-4]  # Safari
```

每次 fork osascript 子进程,**自己**起完整 AppleScript 环境查 frontmost,
返完即退。延迟 30-80ms,与 chunk 8a-ext V2 ``ioreg HIDIdleTime`` / chunk
8a Chrome/Safari tab AppleScript 同 pattern,**零新依赖**(``subprocess`` /
``shutil`` 已用)。

### 副作用 — 返英文 bundle 名

NSWorkspace.localizedName 给中文 macOS 用户 Apple 原生 bundle 返中文:
``"终端"``(Terminal)/ ``"Safari浏览器"``(Safari)/ ``"代码"``(Code,极少
数本地化版)。osascript ``POSIX path of`` 永远返 ``/Applications/X.app/``,
basename **永远是英文 bundle 名**:``Terminal`` / ``Safari`` / ``Code``。

下游兼容性验证(audit 前已逐个 grep 确认):

| 下游 | 是否兼容英文 bundle 名 |
|------|----------------------|
| ``_IDE_APPS`` (activity_smart) | ✅ 已含 ``'code'`` / ``'terminal'`` / ``'cursor'`` lowercase 英文 keys |
| ``_BROWSER_APPS`` (activity_monitor) | ✅ 已含 ``'safari'`` / ``'google chrome'`` / ``'firefox'`` 等 |
| ``_MUSIC_APPS`` (activity_smart) | ✅ 已含 ``'spotify'`` / ``'apple music'`` 等 |
| chunk 14 ``categorize()`` | ✅ 复用 _IDE_APPS / _BROWSER_APPS / _MUSIC_APPS |
| chunk 14 ``activity_sessions.app_name`` 列 | ✅ 跨 locale 稳定的英文名(优于中文) |
| ``stay_key = f"app:{app}"`` | ✅ 英文名跨 locale 一致,throttle 字典 key 稳定 |

hotfix-6/8 加的中文别名(``"终端"`` / ``"google chrome 浏览器"`` / 等)
post-fix 转为 dead code,但**不删** — backward compat + 历史文档价值
(任何旧 DB 行仍能用)。

### Audit 副产物 bug — pre-hotfix-10 Safari 中文 macOS 已挂

``_BROWSER_APPS`` 含 ``"safari 浏览器"`` (带空格)。但 macOS NSWorkspace
真实返 ``"Safari浏览器"`` (**无**空格)。所以中文 macOS Safari 用户在
hotfix-10 **之前**:
* ``get_active_app()`` 返 ``"Safari浏览器"``
* ``get_browser_url()`` lookup ``"safari浏览器".lower()`` ∉ ``_BROWSER_APPS``
* 返 None → snapshot.browser=None → 永远走 app stay,**不**记录 URL

hotfix-10 incidentally 通过 osascript 英文 bundle 名绕过这条 bug。

### LLM-facing display name(hotfix-10 commit 2)

DB / stay_key / lookup 一律英文 bundle 名,但 chunk 14 ``format_today_
activity_for_prompt`` 注入主对话的文本看到 ``Code 3小时`` / ``Terminal
1小时``:
* ``Code`` 太技术,LLM 容易解析为"代码"概念词
* ``Terminal`` 比 ``终端`` 对中文 macOS 用户疏远

加 ``activity_monitor._APP_DISPLAY_NAMES`` 字典 + ``get_display_name()``
helper:

```python
_APP_DISPLAY_NAMES = {
    "Code": "VS Code",
    "Code - Insiders": "VS Code Insiders",
    "Terminal": "终端",
}
```

**仅 ``format_today_activity_for_prompt`` 用** — storage / stay_key / DB /
capability return **决不**走 mapping。未列表里的 bundle 名直接返原值
(Spotify / Slack / Notion / Safari 等国际化品牌名英文阅读体验 OK)。

扩展原则:**只**加"用户明显期待中文展示"的 entry,不要扩成通用 i18n 字典。
未来若用户群分化,前端可在 UI 层做更全 mapping,backend 保持稳态。

### 跨平台 graceful

| 平台 / 情景 | get_active_app 行为 |
|------------|---------------------|
| macOS osascript 正常 | 英文 bundle name |
| macOS osascript 缺失 | None |
| macOS osascript TimeoutExpired (2s) | None + warning log |
| macOS osascript 非零 returncode(用户未授权)| None + debug log |
| macOS osascript exit 0 但 stdout 空 | None |
| 非 macOS | None(``IS_MACOS`` 短路) |

所有 None 路径与 chunk 8a / 8a-ext silent fallback 风格一致 — 决不抛错
阻塞 ActivityWatcher / ChatAgent。

### 测试

* ``tests/test_activity_monitor.py`` -3 旧 NSWorkspace case +9 新 osascript
  case +3 get_display_name case
* ``tests/test_chunk8a_ext_judge.py`` 顺手修 V2 idle gate latent flake —
  ``test_maybe_judge_calls_llm_when_eligible`` 没 mock get_idle_seconds,
  host idle > 300s 时偶发失败(V2 commit 加闸时漏 mock,留为后台 latent)

138 PASS 跨 6 个 chunk 8a/8a-ext 测试文件 / 0 regression。

### 文件清单

* ``backend/integrations/activity_monitor.py``(-23 行旧 NSWorkspace impl
  +73 行 osascript impl + 47 行 _APP_DISPLAY_NAMES 块)
* ``backend/services/activity_timeline.py``(+3 行 — format 函数过
  get_display_name)
* ``tests/test_activity_monitor.py``(-22 行 +103 行,12 new tests)
* ``tests/test_chunk8a_ext_judge.py``(+6 行,2 tests 加 idle mock 修 flake)

---

## 十五之T、Activity Timeline 系统(chunk 14 起)

### 设计目标

chunk 8a + 8a-ext + V2 + hotfix-9/10 让 Momo 知道**"用户现在在 X app/URL"**
(实时)并能基于实时 stay 触发 chime in。但**Momo 不记得"用户今天都做了什么"**:
* 用户早上 B 站看 2 小时 → 切 IDE 写代码 3 小时 → 晚上 Momo 不知道
* 用户跟 Momo 聊天时,Momo 没法说"你今天 B 站看了多久,看什么呢"

chunk 14 加 **activity_timeline 系统**:跟 ``chat_history`` 平行的第二条
timeline,持久化记录用户每天 app/URL 活动 sessions;Momo 在主对话中能引用
今日活动(``## 用户今日活动`` system prompt 块),也能通过 capability 主动
查指定日期 / 关键词。

### 三层架构

```
                                    ┌─────────────────────────────────┐
                                    │ NSWorkspace / osascript / ioreg │
                                    │ (hotfix-10 + 8a-ext V2)         │
                                    └─────────────────────────────────┘
                                                 │ frontmost app / URL / idle
                                                 ▼
┌──────────────────────────────────────────────────────────────────┐
│ ActivityWatcher (chunk 8a)                                       │
│   * snapshot() 每 30s sniff state                                │
│   * register_change_listener  → 即时 chime in (chunk 8a fast)    │
│   * register_poll_listener    → maybe_judge (chunk 8a-ext slow)  │
│                                 → session_writer_poll_handler ★  │
└──────────────────────────────────────────────────────────────────┘
                                                 │
                            ┌────────────────────┼─────────────────────┐
                            ▼                    ▼                     ▼
                  fire activity_*           judge_chime_in       activity_sessions
                  trigger (chunk 8a)        (chunk 8a-ext)       DB row (chunk 14)
                                                                       │
                                                                       ▼
                            ┌──────────────────────────────────────────────┐
                            │ /api/activity/timeline GET / DELETE          │
                            │ ToolRegistry: activity.{today_summary,       │
                            │   recent_apps, search_history}               │
                            │ ChatAgent _build_messages 注入 system prompt │
                            │ SettingsPanel ActivityTimelineDrawer         │
                            │ 每日 23:59 cleanup_old_sessions cron         │
                            └──────────────────────────────────────────────┘
```

三层职责清晰分离:
* **chunk 8a / 8a-ext**: 实时感知 + 当下决策(chime in)
* **chunk 14**: 持久化记录 + 历史查询 + LLM 上下文注入
* 共享 ActivityWatcher poll listener hook + 同一 ``blocked_apps`` /
  ``blocked_url_patterns`` 黑名单 + 同一 ``idle_threshold_seconds``

### Session boundary 检测 — poll-listener + 独立游标

audit 期间评估过两种 hook:

| 方案 | 优点 | 缺点 |
|------|------|------|
| ``register_change_listener`` 监听 url_changed / app_changed | 事件驱动,精准 | ``_detect_changes`` 在 listener 触发**前**就 reset ``_url_dwell_start`` / ``_app_focus_start`` → duration 信息丢失;long_dwell / long_focus latching(timer = ``-1.0``)污染 duration 计算 |
| ``register_poll_listener`` + 独立游标 ★ | 完全解耦 watcher 内部 timer 状态;长稳;30s 颗粒度天然匹配 ``min_session_seconds=30`` 短 session 过滤 | 每 30s 才查,sub-poll 切换看不到(可接受 — 这种切换本就是噪音不该写入) |

选**方案 2**。``backend/services/activity_timeline.py`` 维护模块级
``_prev_app`` / ``_prev_url`` / ``_prev_title`` / ``_prev_start_at`` /
``_prev_idle``,每 poll 比对 ``(active_app, browser_url)`` 元组,变化 →
写一行 ``activity_sessions``,游标重置。

### 五道闸过滤

session 写入前依次过:

1. **元组未变** → no-op(stay 还在进行,只更新 idle 标记)
2. **duration < min_session_seconds**(默 30s)→ 静默 debug log skip
3. **黑名单**(chunk 8a ``blocked_apps`` / ``blocked_url_patterns`` +
   ``url_fetcher.is_url_blocked``)→ INFO log skip
4. **总开关 ``activity_timeline.enabled=false``** → debug log skip(游标
   仍更新,关掉再打开不留空洞)
5. **DB INSERT 异常** → ``logger.exception`` 不抛 — 决不阻塞 watcher poll loop

idle 标记 ``is_idle_filtered``: 复用 chunk 8a-ext V2 ``get_idle_seconds`` +
``get_idle_threshold_seconds``(默 300s)。idle 期间结束的 session **仍**
写入(timeline UI 显示完整记录),但 ``is_idle_filtered=1`` —
capability summary 计算 + chat 注入路径 exclude。

### Schema

``activity_sessions``(commit 1 migration):

```sql
CREATE TABLE activity_sessions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT NOT NULL DEFAULT 'default',
  start_at DATETIME NOT NULL,
  end_at DATETIME NOT NULL,
  duration_seconds INTEGER NOT NULL,
  app_name TEXT NOT NULL,            -- hotfix-10 英文 bundle 名
  browser_url TEXT,                  -- NULL when非浏览器 frontmost
  browser_title TEXT,
  category TEXT,                     -- backend categorize() 推断
  is_idle_filtered INTEGER NOT NULL DEFAULT 0,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_activity_sessions_user_date ON activity_sessions(user_id, start_at);
CREATE INDEX idx_activity_sessions_app       ON activity_sessions(app_name);
```

backup 模板对齐 chunk 6b hotfix-3:跑前 ``shutil.copyfile momoos.db
.backup-before-chunk14``,二次跑跳过(幂等)。

### categorize() 规则

7 分类(优先级 URL > app,理由:用户开 Chrome 看 youtube 应分 video 而非
plain browser):

| category | URL host 子串 / app 集合 |
|----------|--------------------------|
| video | youtube.com / bilibili.com/video / netflix / twitch / iqiyi / ... |
| social | twitter / x.com / facebook / instagram / weibo / reddit / xiaohongshu |
| tech_doc | docs.python.org / mdn / fastapi / docs.rs / vuejs / ... |
| ide | _IDE_APPS(code / cursor / pycharm / xcode / vim / 终端 / ...) |
| browser | _BROWSER_APPS(safari / chrome / firefox / edge / arc / ...) |
| music | _MUSIC_APPS(spotify / apple music / 网易云音乐 / ...) |
| other | fallback |

复用 chunk 8a-ext ``_IDE_APPS`` / ``_MUSIC_APPS`` / ``_TECH_DOC_URL_PATTERNS``
+ hotfix-9 ``_BROWSER_APPS`` —— 同一 app 在 chime-in 决策路径和 timeline
归类路径**必须**归同一 category,不能裂缝。

### API endpoints(commit 3)

* ``GET /api/activity/timeline?date=YYYY-MM-DD&days=N&include_idle=bool``
  - days clamp [1, 90]
  - 返 sessions[] + summary_by_app[top_urls top5] + summary_by_category{}
* ``DELETE /api/activity/timeline/{id}`` — 单条
* ``DELETE /api/activity/timeline?date=YYYY-MM-DD`` — 整日
  - ``date=all`` 显式语义清当前 user 全表
  - ``date=None`` 拒绝 → 400(防误删)

### Capability(commit 4)

3 个 ``@register_capability`` 装饰自动入 ToolRegistry,Consumer.CHAT_AGENT,
让 LLM 主动查:

* ``activity.get_today_summary`` — top 5 apps + by_category + recent_focus
  (最近 30 min 内最后一段 stay)
* ``activity.get_recent_apps(days=7)`` — top 20 apps GROUP BY 聚合,clamp [1,30]
* ``activity.search_history(keyword, days=30)`` — LIKE 搜 app_name / URL /
  title,clamp [1, 90],返 top 50 matches。**双重隐私**: ``is_idle_filtered=1``
  显式排除(用户 AFK 时段的 stay 不该被回忆出来),且黑名单已在写入层过滤

silent degradation: DB 异常 → ``{available: false, reason: db_error}``,
绝不抛错给 ChatAgent(与 screen.* 同思路)。

### ChatAgent 注入(commit 5)

``backend/services/activity_timeline.format_today_activity_for_prompt(user_id)``
机械模板生成 ~200 字 prompt 块,**零 LLM 调用**(对齐 chunk 11
``format_profile_for_prompt`` 原则):

```
## 用户今日活动
今天已活跃 5小时15分钟。

主要花在:
- VS Code 3小时
- Google Chrome 2小时5分钟(主要看 jobs.bilibili.com B 站 - 社招岗位列表 1小时35分钟)
- Spotify 10分钟

最近 30 分钟主要在: Spotify
```

要点:
* hotfix-10 ``_APP_DISPLAY_NAMES``:``Code → "VS Code"`` / ``Terminal →
  "终端"`` LLM 友好(storage 仍英文 bundle 名)
* top URL host 简化(``https://x.com/path`` → ``x.com``)+ title 截 30 字
  防 prompt 膨胀
* ``is_idle_filtered=1`` 排除(AFK 时段不该被 Momo 提)
* 总活跃 < 60s → 返 None(刚启动 / 短时使用,信息无价值,不污染 prompt)
* 总开关 ``inject_into_chat: true`` 与 ``enabled`` 解耦 — 用户可"记录但
  不在对话被引用"
* 注入位置: ``_build_messages`` 在 chunk 11 profile 注入(line 1126-1139)
  之后、long-term memory recall(line 1141)之前。理由:
  - profile = "你是谁"(用户身份层)
  - **activity = "你今天做了什么"(用户上下文层)**  ← 新插入
  - memory recall = "我们以前聊过什么"(语义召回层)
* try/except 包外层 — 决不让 timeline 注入失败阻塞主对话流

### Frontend(commit 6)

``frontend/src/lib/activity_timeline.ts``: TS 客户端,字段对齐 backend
pydantic model。formatLocalTime helper: backend 写 UTC naive,前端按
user-local 显示。

``frontend/src/components/ActivityTimelineDrawer.tsx`` (487 行): 视觉与
MemoryManagerDrawer 完全对齐(右滑 60% 宽 + backdrop-blur + Escape 关 +
点左侧空白关)。功能:
* 日期 picker + 前后天 + [跳到今天]
* 总活跃时长 header
* [包含 idle session] checkbox + [刷新] + [清空本日]
* category 分布横条(7 色 + tooltip)+ legend
* 按 app 聚合 accordion list(开/合 + 内层 sessions 行 + idle 角标 + 单
  条 hover 删除按钮)
* 每 app 末尾显示 top URL host + 时长

SettingsPanel 加新 ``ActivityTimelineSection`` (放 ``ActivityAwareness
Section`` 之后): 标题"活动记录"+ 单卡片 [查看] 按钮(与 MemorySection
[管理] 视觉一致)。**特意不重复**总开关 / 黑名单 / idle 阈值 — 这些已在
上方 ``ActivityAwarenessSection``。

### Cleanup cron(commit 7)

每日 ``cleanup_cron``(默 23:59)触发 ``cleanup_old_sessions()``:
```python
DELETE FROM activity_sessions WHERE start_at < (now - cleanup_days)
```

* cleanup_days 默 30,0 = no-op(用户显式永久保留)
* 注册位置:main.py lifespan 6b'''(profile_daily_regenerate 之后,
  MemoryExtractor worker 之前),与现有 cron 注册风格一致

### Privacy 边界(累积)

| 层 | 措施 |
|----|------|
| 数据源 | chunk 8a snapshot 黑名单字段直接置 None,listener 完全看不到敏感场景 |
| 写入层 | chunk 14 commit 2 写 session 前**再过一次**黑名单 defensive |
| 查询层 | capability search_history 显式 ``is_idle_filtered=0`` 双重排除 idle 时段 |
| UI 层 | drawer [清空本日] + 单条删除;``date=None`` API 强制拒绝防误删 |
| 数据保留 | cron 默 30 天后自动清理 |
| 网络 | 全本地 SQLite,**不上传** |

### 文件清单

* ``backend/database/migrations/v3_5_chunk14_activity_sessions.py``(new, 127 行)
* ``backend/services/activity_timeline.py``(new, 488 行 — session writer +
  inject formatter + cleanup_old_sessions)
* ``backend/routes/activity_api.py``(+205 行 — 3 endpoint)
* ``backend/capabilities/activity.py``(new, 264 行 — 3 cap)
* ``backend/agents/chat.py``(+13 行 — _build_messages 注入)
* ``backend/main.py``(+22 行 — migration + 2 listener register + cleanup cron)
* ``backend/integrations/activity_monitor.py``(+47 行 — hotfix-10 _APP_DISPLAY_NAMES)
* ``config.yaml``(+5 行 — activity_timeline block)
* ``frontend/src/lib/activity_timeline.ts``(new, 109 行)
* ``frontend/src/components/ActivityTimelineDrawer.tsx``(new, 487 行)
* ``frontend/src/components/SettingsPanel.tsx``(+76 行 — section + drawer mount)
* ``tests/test_chunk14_activity_timeline.py``(new, 523 行,27 case)

163 PASS 跨 chunk 8a / 8a-ext / chunk 14 共 7 个测试文件 / 0 regression。

---

## 十五之U、Capability category 单一归属 + 剪贴板 accordion(UX-005 起)

### 设计目标

UX-005 治理 UX-003 三层 accordion 之后两个用户实测体感问题:

1. **media/music 重叠**:netease provider 跨 ``music``(NCM API 7 caps)
   + ``media``(本地 mpv 播放 6 caps)两个 category。CapabilityPanel 渲染
   后用户看见"网易云"在 music tab 和 media tab 各出现一次,体感困惑
   ("Momo 到底能不能控制它?")。
2. **剪贴板预览列表始终展开**:SettingsPanel "剪贴板" section 5 条预览
   list 默认全展开 + 5s 轮询持续刷新,**占用 panel 大量视觉空间**。

### audit-first 发现

完整扫描 15 个 capability 文件 / 57 个 cap。**唯一**跨 category provider 是
netease:

| Provider | Backend file | Category 改前 | Cap 数 |
|----------|--------------|---------------|--------|
| netease | netease_music.py | music | 7 |
| netease | netease_playback.py | media | 6 |

**audit 副发现 — spec 提到的"spotify / apple_music"在 backend 不存在**:
它们只是 ``backend/proactive/activity_smart.py:_MUSIC_APPS`` frozenset
里给 chime-in detection 用的字符串(``"spotify"`` / ``"apple music"``),
**不是** capability。用户当时报的 music tab "spotify/apple_music 重复"是
误解 — 当前 music tab 只有 netease 一个 provider,真正的混乱是 netease
横跨 music+media 两 category。

### 归属规则决定(audit 报告 → 用户确认)

候选 3 方案,用户选 **Choice A — 全归 music**:

* netease_playback.py 6 caps:``category=media`` → ``category=music``
* netease_music.py 7 caps 已是 music,不动
* 结果:music = netease 单 provider 13 caps;media = bilibili + media_control

**副决策 — xhs 新建 social category**: xhs 1 cap(被动 URL 解析)语义是
社交内容站,跟 bilibili 视频站性质不同。用户主动要求加 social category,
未来 Twitter / Facebook / Instagram 等都归 social。

### 归属变化对比

| Category | 改前 | 改后 |
|----------|------|------|
| music | netease 7 | **netease 13**(API + local 合并) |
| media | bilibili 12 + media_control 5 + **netease 6** + **xhs 1** | bilibili 12 + media_control 5 = **17 -1 = 16** |
| social | (不存在) | **xhs 1**(新建) |

(media 总数变化:24 → 16,-8 caps 搬出去到 music/social)

### 三层 accordion 视觉不变

``_extractProvider`` / ``PROVIDER_DISPLAY`` / ``ProviderGroupRow`` 全部
**不动** — 它们对具体 category 数 unagnostic,只对 provider key 做 grouping。
唯一改的是 ``CapabilityPanel.tsx`` 顶部的 audit 注释列表(reflect 新 single/
multi provider count)。

### 剪贴板 accordion 折叠

audit decision:backend ``_MAX_ITEMS=50`` deque + API ``n=5/max=20``,规模
**不到** chunk 14 ActivityTimelineDrawer 那种"几百条历史 + 搜索筛选"
量级。直接 accordion 折叠就够,**不需要**独立 Drawer。

实现:``SettingsPanel.tsx ClipboardSection`` 加 ``listExpanded`` state
(默 false),header 改 ``<button>`` chevron ``▸/▾`` + ``📋 最近 N 条``
显示计数,展开后 header 行内显示 ``[↻ 刷新]`` + ``[全部清除]``(``role=
"button" + tabIndex + stopPropagation`` UX-003 教训,防 click 冒泡触发
外层 toggle + 避免 HTML 嵌套 ``<button>`` 非法结构),预览列表 + 空状态
文案搬到 ``{listExpanded && ...}`` 内层。5s 轮询不变。

### Audit guard 防回归(commit 3)

``tests/test_ux005_category_uniqueness.py`` 6 case 锁两个 invariant:
* **任意 provider 不跨多 category**: 任何人改 capability 元数据让 provider
  再回到跨 category 状态(典型:netease 同时 music+media)立刻 fail
* UX-005 commit 1 决定的具体归属(netease={music} / xhs={social} / media
  provider 集合 == {bilibili, media})
* category 计数下限(music >= 13 / social >= 1,防意外删 capability)

### 文件清单

* ``backend/capabilities/netease_playback.py``(6 处 ``category="media"``
  → ``"music"``,replace_all 一次性改)
* ``backend/capabilities/xiaohongshu.py``(1 处 ``category="media"`` →
  ``"social"``)
* ``frontend/src/components/CapabilityPanel.tsx``(+1 行 -1 行 audit 注释)
* ``frontend/src/components/SettingsPanel.tsx``(+103 行 -65 行,
  ClipboardSection accordion 折叠化)
* ``tests/test_ux005_category_uniqueness.py``(new,130 行,6 case)

209 PASS 跨 chunk 8a / 8a-ext / chunk 14 / UX-005 + bilibili/netease/
clipboard/ux002 共 12 测试文件 / 0 regression。

---

## 十五之V、tool 调用过渡语 + frontend loading state(UX-004 起)

### 设计目标

audit 报告核心 finding:tool 调用链 (``chat.py`` LiteLLM stream 累积
``tool_calls_acc`` → ``_execute_tool`` → 二次 LLM call) 对前端**完全静默**。
用户问"今天日历有什么",从问完到最终回复中间 5-30 秒**没有任何反馈** —
体感"app 卡死"。

UX-004 两层叠加给"问完不沉默"反馈:

1. **Prompt 引导**: 在 system prompt 加 ``【工具调用行为】`` 块,要求 LLM
   在 tool_call 前先输出 6-15 字过渡语("嗯,让我看看" / "等我查一下")。
   预期 70-95% 跟随率(LLM 偶尔仍 silent)。
2. **Frontend loading state**: backend 新 emit ``tool_use_start`` /
   ``tool_use_done`` WS event,frontend 据此点亮 ``ChatInput`` 内 loading
   pill(``Loader2 animate-spin`` + ``animate-pulse``),tool_name 走前缀
   mapping 显示具体文案(``查日历…`` / ``查歌单…`` / etc)。

A 与 B 互补:LLM 遵守 prompt 时形成"语言 + 视觉"双重反馈,LLM 不遵守时
B 兜底保证视觉始终有反馈。

### audit-first 4 决策点(用户已确认)

| Q | Choice | 理由 |
|---|--------|------|
| 过渡语 TTS? | **A 只文字不 TTS** | TTS 当前 full-utterance queued,Choice B(过渡语单独 TTS interleave)需 sentence-by-sentence streaming 架构改,留 chunk 15 / UX-006 |
| Character-specific 过渡语? | **v1 统一默认** | 八重 / 未来角色靠 persona 自然变体;``tool_transition_examples`` 字段留给 chunk 12 persona 加厚 |
| Label mapping 来源? | **frontend 前缀 map** | 与 backend ``_extractProvider`` 对齐;新加 capability 只加 1 行 entry |
| WS event 几个? | **2 个** | tool_use_start(带 tool_name)+ tool_use_done(带 tool_name + duration_ms)。duration_ms 留给未来 "Momo 这个工具好慢哦" feedback |

### Backend 实现

#### chat.py — yield 协议扩展

``ChatAgent.stream()`` 之前 yield ``str``(句子),改为 yield
``Union[str, dict]``。dict 是 typed WS event,ws.py 直接 ``send_json``
透传,不经文本处理(emotion/thinking parse / TTS)。

Tool exec loop(chat.py:1447-1466)前后:

```python
yield {"type": "tool_use_start", "tool_name": name}
tool_t0 = time.perf_counter()
result = await _execute_tool(...)
duration_ms = int((time.perf_counter() - tool_t0) * 1000)
yield {"type": "tool_use_done", "tool_name": name, "duration_ms": duration_ms}
```

audit 4 方案对比后选 **dict-yield**(改动小 / 无 callback 耦合 / 无新依赖);
其他方案(on_event callback / contextvar / sentinel string)各有缺点详见
commit 1 message。

#### ws.py — 早路由分支

``async for sentence in _chat_agent.stream(chat_msg):`` loop 顶部加:

```python
if isinstance(sentence, dict):
    await ws.send_json(sentence)
    continue
```

permanent INFO log ``[ws] forwarding tool event %s user=%s tool=%s`` 标记
排查友好。

#### chat.py — _TOOL_BEHAVIOR_BLOCK 注入

```python
_TOOL_BEHAVIOR_BLOCK = "【工具调用行为】\n..."  # 17 行 prompt

# in _build_messages:
head_parts.append(persona_block)
head_parts.append(_TOOL_BEHAVIOR_BLOCK)    # ← UX-004 新加
system_parts: List[str] = ["\n\n".join(head_parts)]
```

注入位置选 head_parts 末尾(persona 之后):与 emotion/thinking/motion/state/
BASE_INSTRUCTION/persona 同层级(输出格式约束),**不**混入下方 profile/
activity/memory recall(语义上下文层)。注入顺序断言由
``test_tool_behavior_injected_before_profile_section`` 锁定。

### Frontend 实现

#### Store 新字段

```ts
currentToolName: string | null;        // 当前 LLM 正在调的 tool
setCurrentToolName: (v: string | null) => void;
```

紧贴 ``currentThinking`` 旁边(同 turn-scoped transient 语义)。多 tool 并行
只显示最近 set 的(用户关注当下卡顿点,不需要 list 多个)。

#### useWebSocket.ts — handler

```ts
case 'tool_use_start': s.setCurrentToolName(msg.tool_name); break;
case 'tool_use_done':  s.setCurrentToolName(null);          break;
```

新一轮发送(line 494)``setCurrentToolName(null)`` belt-and-suspenders 清
残留,防 backend 路径异常未 emit done。

#### lib/tool_labels.ts — 前缀 mapping

```ts
const TOOL_LABEL_TABLE: ToolLabelEntry[] = [
  { prefix: 'activity.',        label: '查今天的活动…' },
  { prefix: 'apple_calendar.',  label: '查日历…' },
  { prefix: 'netease.',         label: '查歌单…' },
  { prefix: 'bilibili.',        label: '看视频信息…' },
  { prefix: 'media.',           label: '控制播放…' },
  { prefix: 'xhs.',             label: '解析小红书…' },
  { prefix: 'screen.',          label: '看屏幕…' },
  { prefix: 'clipboard.',       label: '看剪贴板…' },
  // ... ext.X 也覆盖
];
// fallback: '查询中…'
```

#### ChatInput.tsx — loading pill

紧贴 thinking pill 之后:

```tsx
{currentToolName && (
  <div className="animate-pulse ..." style={{ border: '1px dashed ...' }}>
    <Loader2 size={12} className="animate-spin" />
    <span>{toolLoadingLabel(currentToolName)}</span>
  </div>
)}
```

视觉中等(dashed border + secondary text color),不抢 thinking pill
accent 焦点。``title={``tool: ${currentToolName}``}`` 给开发者调试。

### TTS 决策(Choice A 落实)

过渡语**只走文字流**(``text_chunk``)。最终 TTS 仍是完整回复 full-utterance,
跟 UX-004 之前架构一致。``audio_chunk`` 路径不改动。

**用户体感**:屏幕上看见过渡语"等我查一下" + loading pill"查日历…" 同时
出现,然后等几秒,最终回复"今天有 2 个日程,上午 10 点开会" 文字流出 +
TTS 朗读。不听见 Momo 真说"等我查一下",但视觉上已经知道她在做事。

### Tech debt 记录(用户额外约束)

1. **TTS pre-tool segment 支持**: Choice B 的"过渡语真 TTS 出声" 需要拆
   audio pipeline,留 **chunk 15 / UX-006**。settings 加 toggle / sentence
   boundary detector / per-segment TTS task queue 等。
2. **Character-specific 过渡语**: ``tool_transition_examples`` 字段加 DB
   Character schema / characters.yaml,prompt build 时拼接角色专属例子。
   留 **chunk 12 persona 加厚** 同期实施。

### 验收对照(commit 5 完成时)

| 指标 | 状态 |
|------|------|
| Backend emit tool_use_start / done | ✅ commit 1 |
| Prompt 含 ``【工具调用行为】`` 块 | ✅ commit 2 |
| Frontend loading pill 显示 + 文案 mapping | ✅ commit 3 |
| LLM 跟随率(预期 70-95%) | ⏳ user GUI 验收测 3-5 句 tool 问题统计 |
| TTS 不出过渡语(Choice A 落实) | ✅ commit 2(过渡语只走 text_chunk 不喂 TTS pipeline) |
| 0 regression on chunk 0-14 + UX-001/002/003/005 | ✅ 5 new tests pass |

### 文件清单

* ``backend/agents/chat.py``(+37 行 ``_TOOL_BEHAVIOR_BLOCK`` 常量 +2 个
  tool event yield,Union 类型签名)
* ``backend/routes/ws.py``(+10 行 dict 早路由分支)
* ``frontend/src/store/index.ts``(+11 行 currentToolName 字段)
* ``frontend/src/hooks/useWebSocket.ts``(+18 行 2 case + 新轮清残)
* ``frontend/src/lib/tool_labels.ts``(new, 62 行 mapping table)
* ``frontend/src/components/ChatInput.tsx``(+24 行 loading pill UI)
* ``tests/test_ux004_tool_call_ux.py``(new, 215 行 / 5 case)

---

## 十五之W、Momo 消息 1 min 淡化 + ChatHistoryDrawer 半透明 overlay(UX-007 起)

### 设计目标

两个交叠的视觉焦点问题:
1. Momo 消息堆积在主聊天区不断累积,旧消息长时间挡 Live2D 视觉焦点
2. 打开 ChatHistoryDrawer 时整个面板挡 Live2D,陪伴感丢失

UX-007 哲学:**Live2D 始终是视觉主体**。新消息 1 min 高亮供阅读;之后逐步
让位给角色立绘 / 表情。打开历史抽屉时仍保留 Live2D 在背景柔化可见。

### audit-first 关键发现

| 项目 | 状态 |
|------|------|
| 主区 Momo 渲染组件 | ``CharacterDialogueBubble.tsx`` 倒序找最后 assistant 消息 |
| 消息 timestamp | ``ChatMessage.ts: number`` 是 ``performance.now()``-based 单调时钟 |
| TTS state | **全局 ``status: AiStatus``,无 per-message identity** ← 关键设计权衡 |
| proactive 渲染 | 走同一 store + 同一 bubble,统一淡化规则 |
| loading pill | 在 ``ChatInput.tsx``,不在 bubble,免疫淡化 |
| ChatHistoryDrawer click-catcher | line 30-36,**当前透明无 bg** ← scrim 加这里 |
| Dark mode | 纯 CSS 变量 + color-mix,无 Tailwind ``dark:`` |

### 最小改动原则(用户决策)

- ✅ Momo 消息发出 1 min 后开始渐进淡化(主聊天区)
- ✅ ChatHistoryDrawer 弹出时整体半透明 overlay
- ❌ **不**加用户气泡(维持当前行为)
- ❌ **不**重写 ChatHistoryDrawer 内容结构,只改容器视觉
- ❌ **不**重写主聊天区组件结构

### 淡化曲线

``frontend/src/lib/fadeCurve.ts`` 纯函数 ``fadeForAge(ageMs)``:

```
age (since send)  opacity     scale    备注
0 - 60s            100%        100%     焦点期 — 用户读
60 - 120s          100%→60%    100%     主要淡化区间(线性插值)
120 - 300s         60%→30%     100%→92% 缩小给 Live2D 让位
300s+              25%(固定)   92%      最小可读不挡焦点
```

边界 case(NaN / 负 age)兜底 ``{1, 1}``。

### 三道 100% 例外

bubble 渲染时三个条件任一成立 → 强制 opacity=1 / scale=1:

1. **TTS 正在播** (``status === 'speaking'``):TTS 是 full-utterance per
   turn,该消息就是当前播放的(audit 发现 store 无 per-message TTS
   identity,这两条件同时成立 = 该消息即播放中)
2. **鼠标 hover**:用户主动想读 → 临时恢复,移开重回淡化值
3. **streaming 中**:age 极小,自然落 60s 焦点期(``fadeForAge`` 内置兜底)

### useInterval 5s tick 设计

``useEffect`` 每 5s 调 ``setNowTick`` 强制 re-render 让 fade 重算。

权衡:
* **5s 颗粒度** 而非 1s / 100ms:0.1% opacity 变化用户看不见;5s 足以让
  60→120s 淡化过渡看起来平滑(transition-opacity 200ms 本身覆盖突变)
* **不用 requestAnimationFrame**:60fps 重算无意义,只增 CPU
* **不在 first 60s skip tick**:tick 极便宜(单 setInterval),逻辑统一不分支

### transformOrigin: bottom center

``transform: scale(0.92)`` 在 5min+ 时把 bubble 缩小。``transformOrigin``
默 ``center`` 会让 bubble 向中心收缩(顶部下移)→ 推动 Live2D 头部
焦点。设 ``bottom center`` 后,scale 从底部缩,**bubble 顶部位置不变**,
Live2D 头部视觉焦点稳定。

### ChatHistoryDrawer 两层视觉调整

1. **Click-catcher(line 30-36 div)加 scrim**:
   - ``background: rgba(0, 0, 0, 0.4)``(40% 黑半透,主题无关 — system
     modal scrim 行为对齐)
   - ``backdrop-filter: blur(8px)`` + ``-webkit-backdrop-filter`` Safari
     prefix
   - Live2D 在左 40% 透着柔化可见,被适度变暗 — 视觉焦点自然转向右侧
     消息列表
2. **Drawer panel surface 85% → 95%**:
   - 用户专门来看历史,要文字稳定可读
   - ``backdrop-blur-lg`` 保留 — Live2D 大幅运动时 panel 边缘不突兀
   - 5% 仍半透是给与 Live2D 焦点之间留一丝"光透感"(完全 100% 不透显得
     生硬)

### 性能注意

* backdrop-filter blur(8px) 在 click-catcher 覆盖 ~40% 视口 — Tauri WebView
  GPU 加速正常,实测 Live2D 帧率不掉
* drawer panel 已有 ``backdrop-blur-lg``,不动
* 若未来用户报告掉帧,移除 click-catcher ``backdropFilter`` 行(scrim 单
  ``rgba(0,0,0,0.4)`` 仍生效)即可降级

### 文件清单

* ``frontend/src/lib/fadeCurve.ts``(new, 38 行 纯函数)
* ``frontend/src/components/CharacterDialogueBubble.tsx``(+50 行
  -3 行,age tick + hover + TTS 例外 + scale transform)
* ``frontend/src/components/ChatHistoryDrawer.tsx``(+14 行 -3 行,
  scrim + blur + drawer surface bump)

实测:
* fadeForAge 8 case 全 ✓(0s/30s/60s/90s/120s/180s/300s/600s,阶段
  切换边界连续无跳跃)
* tsc --noEmit PASS 两 commit
* 0 regression on chunk 0-14 + UX-001/002/003/004/005

### 与 chunk 14 / UX-004 协同

* loading pill (UX-004) 在 ChatInput 不在 bubble,**不受**淡化影响 —
  tool 执行 30s 内 loading pill 一直可见
* proactive chime(activity_judge_chime_in 等)→ 走同一 bubble → 跟普通
  Momo 消息一样按 age 淡化(用户决策:它们也是 Momo 主动说,语义一致)
* 历史抽屉 panel 内 ChatHistory 组件 **不**应用 fadeForAge(用户专门来
  看历史,要求清晰可读)

### Tech debt 记录

* per-message TTS state — 若未来要更精确(如 TTS 队列里的下一条不淡化),
  store 加 ``currentSpeakingMessageId`` 字段。当前近似规则 99% 场景够用
* 用户气泡渲染 — 现版本 UX-007 不加,跟用户决策一致;若未来加,本套
  fade 规则可移植但应**不**淡化(用户消息常是 reference point)

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

#### v3-D：emotion 系统 ✅ 完成（前端数据流接入 v3-E1 Step 5；视觉绑定 v3-E3）
- [x] `chat.py` `_EMOTION_RE` 正则 + `_parse_emotion()` + `_build_emotion_instruction()` 注入 system prompt
- [x] `ws.py` 第一句剥离 `<emotion>` 标签锁定整轮 `turn_emotion`，后续句子复用
- [x] `engine.synthesize(sentence, emotion=turn_emotion)` 整链路通
- [x] `cosyvoice.py` 中文情感词 → 英文枚举 EMOTION_MAP，instruct_supported=True 时插 `instruction` 参数
- [x] `config.yaml` `tts.emotions` 列表给 LLM 选择
- [ ] **前端推送 emotion 给 Live2D 控制器** —— 等 Live2D 接入后补 `ws send_json({"type": "emotion", "value": X})` + 前端 store `currentEmotion` 状态

#### v3-E1：Live2D 接入（**用 Hiyori 官方样本模型走通流程**）✅ 主线完成（8 commit；Step Z 4 条 cleanup 剩余）

**核心思路**：先用 Live2D 官方免费样本模型 **Hiyori** 把整个 SDK 集成 + 前后端管道打通。模型本身是不是最终目标不重要，重点是 SDK 接通后切换模型只是**资产替换、不动代码**。

- [ ] **SDK 选型**：`pixi-live2d-display` + Cubism 4 Core（pixi-live2d-display 不支持 Cubism 5，详见下注）
- [ ] **下载 Hiyori** —— Live2D 官方免费样本，注意 Live2D Free Material License Agreement 条款，开发期 OK，商用受限
- [ ] **CharacterView.tsx 改造** —— 从 `<img src={...} />` 换成 `<canvas>` + PIXI Application；保持 Galgame 满铺布局不变
- [ ] **idle 动画** —— 调用 Hiyori 自带 idle motion 自动循环
- [ ] **口型同步** —— `useAudio.ts` 扩展 `useAudioAmplitude()` hook 用 AnalyserNode 取样振幅；CharacterView 订阅 → `model.internalModel.coreModel.setParameterValueById('ParamMouthOpenY', value)`
- [ ] **emotion → 表情切换** —— ws.py 当前 `_parse_emotion` 之后**新增 send_json `{"type": "emotion", "value": "happy"}`**；前端 useWebSocket 加 case `'emotion'` → store `setCurrentEmotion`；CharacterView useEffect 订阅 → `model.expression(emotionMap[X])`
- [ ] **触摸响应**（OLV #6）—— canvas onClick → 转 PIXI 局部坐标 → `model.hitTest(x, y)`；hit area "Head" / "Body" / "Cheek" 触发不同 motion + 后端 special prompt
- [ ] **motionMap**（OLV #8）—— system prompt 加 `<motion>X</motion>` 输出指令；ws.py push 给前端；前端触发 `model.motion(X)`
- [ ] **DB 字段**：迁移 `v3_e.py` 给 `characters` 加 `live2d_model TEXT`（存模型路径或模型 ID）；CharacterPanel 加输入框

**关键约束（pixi-live2d-display 限制）**：

pixi-live2d-display 及其所有维护中的 fork（advanced / lipsyncpatch / mulmotion）只支持 Cubism 4 Core，**不支持 Cubism 5 Core**。GitHub issue #118 自 2023-10 开放至今未修复。

→ Skyler 在 Live2D 渲染层锁死在 Cubism 4 时代的 moc3 ver ≤ 4 模型。Hiyori 是 Cubism 4 格式（moc3 ver 3），完美兼容。

→ v3-E2 选购/委托模型时**必须**确认是 Cubism 4 兼容格式。Cubism 5 编辑器制作的模型可以接受，但需以"4.x 兼容"选项重新导出 .moc3。

→ 看板娘场景（眨眼 + idle + 嘴动 + emotion + motion）完全不需要 Cubism 5 新特性（增强 blend shape / offscreen 绘制 / 新 blend mode）。这个限制对实际功能 0 影响。

#### v3-E2：多模型 Live2D 接入 ✅ 完成（9 commit，2026-05-06）

主线交付（commit 范围 `1831836` → `d01f3b4`）：
- `tools/check_moc3_version.py`（moc3 + .moc 二进制头校验，pixi 兼容性判定）
- 资产路径规范化 `frontend/public/live2d/<slug>/` + `.gitignore` IP 隔离 + `frontend/public/live2d/README.md` 资产管理文档
- `GET /api/live2d/models` 扫描 API + `Live2DScanner` 单 slug 容错 + CharacterPanel 兼容性 badge 下拉
- DB schema：`characters.{emotion,motion,hit_area}_map_json` 三字段（迁移幂等）
- `Live2DRuntime` 接口（loadModel / unloadModel / setMouthOpen / startMotion / setExpression / hitTest）+ `PixiCubism4Runtime` 实现 + `getRuntime()` 工厂
- `Live2DCanvas` 重写：0 直接 import pixi.js，全走 runtime；`resolveCharacterMaps` 单字段独立 fallback
- 八重神子 (id=2) 接入 BCSZ1.1：`live2d_model='yae'` + 17 entry motion_map + 8 entry hit_area_map + emotion_map=`{}`
- emotion 视觉绑定接通：`runtime.setExpression(handle, name)` 走代码路径，等有 `.exp3.json` 的模型即激活
- Momo (id=1) persona 还原成 ChatAgent 原文（双指纹幂等）

详见 §十四之A Live2D 架构 + ROADMAP §v3-E2。

#### v3-F：语音体验飞跃 📋 计划中（OLV 借鉴）
- [ ] **语音打断**（OLV #1）—— ChatInput 🚫 按钮接通；用户开始说话 → 立即 cancel LLM stream → 立即 stop TTS playback → 已说出部分写入 chat_history 标「被打断」
  - DESIGN §7.6 红线第一条；`status: 'interrupted'` 状态 store 已就绪，差最后接通
- [ ] **TTS 多段并发合成**（OLV #2）—— 当前是 sentence-by-sentence 串行，改为并发合成 + 顺序播放，砍首句到末句的等待时间
- [ ] **TTS 预处理器**（OLV #3）—— 正则剥离 `*动作*` / `(注释)` / `[标记]` 不让 TTS 读出来；同时也要不读 `<emotion>` / `<motion>` / `<thinking>` 残留（双保险）
- [ ] **AI 内心独白**（OLV #5）—— `<thinking>X</thinking>` 标签解析，不读出但前端显示在 status 区或独立 thoughts 抽屉

#### v3-G chunk 1.6 ✅ 完成（2026-05-07）—— Apple Calendar 接入 + 日历多源路由
- [x] **`backend/integrations/apple_calendar.py`** —— pyobjc-framework-EventKit；macOS 14+ `requestFullAccessToEventsWithCompletion_` + 旧版 fallback；`threading.Event` 桥接 Cocoa callback 到 `asyncio.to_thread`；list/create/delete events；health_check 三档（非 macOS / EventKit 缺失 / macOS<12 / 未授权 → 全 warn）
- [x] **`backend/capabilities/apple_calendar.py`** —— `apple_calendar.today_events / upcoming_events / create_event / delete_event` 4 个 capability；create_event 描述明确引导 LLM 先调 `time.now` 算 ISO（chunk 2.5 自然语言录入入口）
- [x] **`backend/capabilities/calendar.py` (router)** —— `calendar.today_events / upcoming_events` 按 `config.yaml.calendar.default_source` 路由到 apple/google；router 的 health_check 转发到当前 source 并标注 source 名
- [x] **`backend/capabilities/google_calendar.py`** —— chunk 1 `calendar.py` 重命名 (git mv 保 history)；cap 名 `calendar.*` → `google_calendar.*`；consumers 降级 SCHEDULER-only；`_gated_health_check` 在 disabled 时返启用提示 warn
- [x] **`config.yaml`**：`calendar.default_source` + `apple_calendar.enabled` + `google_calendar.enabled` (默认 false)
- [x] **`docs/apple-calendar-setup.md`** —— Console 权限 / iCloud 同步 / 多日历 / 切换 source / 故障排查
- [x] **测试**：`tests/test_apple_calendar.py`（35 cases，EventKit 完全 mock，跨平台跑得过）+ `tests/test_calendar_router.py`（22 cases，路由 + namespace rename + briefing 兼容）

**关键决策**：

1. **思路 1（路由 + 平行命名空间）**：`calendar.*` 是 LLM 看到的正路（CHAT_AGENT），`apple_calendar.*` 直接 cap 也 CHAT_AGENT（用户 spec 要求），`google_calendar.*` 直接 cap 仅 SCHEDULER（降低 LLM tool surface 噪音）。LLM 看到 7 个 tool（router 2 + Apple 4 + time 1）；面板看到 9 个（含 Google 2 隐藏 cap 用于状态透明）
2. **Briefing 模块零改**：`from backend.capabilities.calendar import today_events` 仍然能 import —— 装饰器返回原函数，函数名仍是 `today_events`；现在它是 router，按 default_source 自动选 source
3. **跨平台 graceful degradation**：`requirements.txt` 用 PEP 508 `; sys_platform == "darwin"` 限制 pyobjc 仅 macOS 安装；运行时 `EventKit = None` 路径让非 macOS 也能起 lifespan，capability 注册成功，health 返 warn 提示"仅 macOS 可用"
4. **EventKit Cocoa callback 桥接**：权限申请 callback 跑在 main run loop，用 `threading.Event` 同步到调用线程后整体 `asyncio.to_thread` 包装，与 chunk 1 Google Calendar 同步内核 + async wrapper 风格对齐
5. **首次调用惰性请求授权**：用户调任何 capability 时若未授权就触发 `_request_access_blocking()` 弹 macOS 系统框 —— 这是用户必须看到的合法 UX，不预先警告 / 不绕过

#### v3-G chunk 1.5 ✅ 完成（2026-05-07）—— 双向 MCP 集成
- [x] **`backend/mcp/server.py`** —— `Server` (lowlevel) + `@list_tools`/`@call_tool` 装饰器从 CapabilityRegistry 实时派生；`StreamableHTTPSessionManager(stateless=True, json_response=False)` 提供 SSE 流；mount `/mcp` 经 FastAPI raw ASGI 通道；Bearer 鉴权在 mount 前 middleware-style
- [x] **`backend/mcp/client.py`** —— 支持 stdio (`mcp.client.stdio.stdio_client`) + streamable HTTP (`mcp.client.streamable_http.streamablehttp_client`) 两种 transport；外部 tool 反向注册成 `ext.<server>.<tool>` 命名空间 capability；closure 默认参数固化 tool name；启动失败**不阻塞** lifespan
- [x] **CapabilityRegistry 扩展** —— 加 `metadata` 字段（`source_server` / `expose_via_server` 两个语义 key）+ `register_runtime` / `unregister_runtime`（与 `register` 一致 + 同步清 ToolRegistry）
- [x] **`backend/routes/mcp_api.py`** —— `GET /api/mcp/server/status` + `GET /api/mcp/clients/status` + `POST /api/mcp/clients/{name}/reconnect`；`/mcp` endpoint 鉴权 → SessionManager.handle_request 接管 ASGI
- [x] **`backend/main.py` lifespan**：步骤 8 起 SessionManager (`async with .run()`)，步骤 9 init_clients_from_config（失败仅 log warning），yield 后反向 shutdown
- [x] **前端 CapabilityPanel banner + 外部 servers 状态条** —— banner 显示 endpoint + 遮蔽 token + [👁]/[📋] 按钮；外部 servers 红/绿/灰圆点 + tool 数 + last_error + [重连] 按钮；外部 capability 卡片加 `[ext · server]` 徽章
- [x] **`docs/mcp-server-setup.md` + `docs/mcp-client-setup.md`** —— Claude Desktop / Cursor / Claude Code / mcp inspector 配置；filesystem + Brave Search 完整示例；`expose_via_server` 取舍；故障排查表

**关键决策**：

1. **CapabilityRegistry 是统一抽象核心**：runtime 注册 + decorator 注册走同一 `register()` 实现，仅语义别名 `register_runtime` 区分意图。三种来源（内置 / 外部反向 / 自身暴露）共用同一份 registry。
2. **服务端 `/mcp` 走 raw ASGI 而非 FastAPI body parsing**：mcp SDK 的 SessionManager 直接接 scope/receive/send（流式 SSE），不能走 `@router.post` 路径。`add_api_route` 注册 GET / POST / DELETE 三方法到自定义 endpoint 函数。
3. **closure 默认参数固化 tool name**：循环里 `def handler(...): return session.call_tool(tool.name, ...)` 会让所有 handler 共享最后一次循环的 `tool.name`。`def make_handler(_session=session, _tname=tool.name): ...` 默认参数在 def 时求值，正确隔离。
4. **`expose_via_server` 双向语义**：内部 capability 默认 True；外部 reverse-registered 按 `mcp_clients.<name>.expose_via_skyler_server` 配置。MCP server 派生 tool 列表时统一按此过滤，避免 Brave search 这类带 API 配额的外部 server 被多级转发。
5. **外部 server 失败不阻塞主进程**：`init_clients_from_config` 内 `try/except` 包每个 client，失败 → `last_error` 标记 + UI 红点。Skyler 主功能（聊天 / 内置 capability / MCP server 暴露）不受影响。

#### v3-G chunk 1 ✅ 完成（2026-05-07）—— Google Calendar 接入 + 起床简报 v0.1
- [x] **`backend/integrations/google_calendar.py`** —— OAuth 2.0 desktop flow（`run_local_server`） + token.json 自动 refresh + `googleapiclient.discovery.build` 单例懒加载 + tenacity 重试（3 次指数退避，触发 OSError / HttpError / TimeoutError）+ `health_check` 三档（healthy / warn / error，网络异常降级 warn 不刷红）；凭证路径 `~/.skyler/google_credentials.json` + token `~/.skyler/google_token.json`；scope `calendar.readonly`
- [x] **`backend/capabilities/calendar.py`** —— `calendar.today_events`（CHAT_AGENT + SCHEDULER）+ `calendar.upcoming_events`（CHAT_AGENT，参数 days_ahead 1-30）；时区共用 `config.scheduler.timezone`
- [x] **`backend/routes/integrations_api.py`** —— `GET /api/integrations/google/status` + `POST /api/integrations/google/auth`（`asyncio.to_thread` 包同步 OAuth flow）+ `POST /api/integrations/google/revoke`
- [x] **`backend/scheduler/briefing.py` + `backend/routes/briefing_api.py`** —— v0.1 模板拼接生成 + cron 注册（默认 `0 9 * * *` Asia/Tokyo）+ `POST /api/briefing/test` 立刻触发；delivery = ConnectionManager push notify + Momo 音色合成 wav 落 `~/.skyler/last_briefing.wav`
- [x] **前端 CapabilityPanel** —— calendar 卡 footer 显示授权状态 + [连接 Google] / [重新授权] 按钮；calendar 类目右侧 [🧪 测试今日简报] 按钮 + 文本 preview
- [x] **`docs/google-calendar-setup.md`** —— Google Cloud Console 完整配置流程（含 Test users 必加自己 + 国内代理 caveat + Skyler home 路径约定）

**Backlog（chunk 2 一起做）**：简报模板 → ChatAgent 智能生成（含联网新闻 / 天气 / 个性化语气）；proactive 实时音频播放路径（当前只落盘）；OAuth 长 polling 优化；多 calendar 支持。

#### v3-G chunk 0 ✅ 完成（2026-05-06）—— 地基：Capability Registry + cron + n8n receiver
- [x] **Capability Registry**（`backend/capabilities/registry.py`）—— 单例，metadata + handler，``@register_capability`` 装饰器
- [x] **API 路由**（`backend/routes/capabilities_api.py`）—— `GET /api/capabilities` 列表 + 即时 health；`POST /api/capabilities/{name}/healthcheck` 单卡刷新
- [x] **ChatAgent 集成（零改 chat.py）**：CapabilityRegistry.register 时若 `Consumer.CHAT_AGENT` 在 consumers，自动派生 OpenAI schema 注入 ToolRegistry，ChatAgent 现有 `_get_all_tools()` 自然捕获
- [x] **APScheduler cron**（`backend/scheduler/cron.py`）—— 与既有 AlarmScheduler 平行；timezone 从 `config.yaml` `scheduler.timezone` 读取（缺省 Asia/Tokyo）
- [x] **Time capability**（`backend/capabilities/time_capability.py`）—— 第一个内置 capability，`time.now` 返回 `{iso, timezone, human, weekday, is_weekend}`
- [x] **n8n webhook receiver**（`backend/routes/webhooks_api.py`）—— `POST /api/webhooks/n8n/{trigger_name}`；Bearer + HMAC SHA256 双因子鉴权；handler 异步 dispatch；详见 `docs/n8n-integration.md`
- [x] **前端 CapabilityPanel**（`frontend/src/components/CapabilityPanel.tsx`）—— 按 category 分组的卡片视图，挂在 SettingsPanel 顶部 Section（spec "tab" → 现有单列布局做 Section 近似）

v3-H chunk 1 完成时，CapabilityRegistry 已支撑 30+ capability 的注册，ChatAgent 自始至终零代码改动。

#### v3-G chunk 1+：生活 & 工具型能力 📋 计划中（Hermes 借鉴 + DESIGN 原计划）
- [ ] **剪贴板助手** —— Tauri clipboard API 监听变化，AI 可主动评论 / 翻译 / 总结复制内容
- [ ] **每日简报** —— 自然语言定时任务（"每天早上 9 点说今天日程"）通过 ConnectionManager.push() 主动播报
- [ ] **智能提醒** —— 比 alarm 更软的提醒，结合 profile_summary 上下文
- [ ] **自然语言 cron 调度**（Hermes #3 借鉴）—— 复用 chunk 0 的 APScheduler，自然语言定义任意定时任务（不只是 alarm）
- [ ] **角色状态面板 / 成长系统**（OLV v1.4 + DESIGN 计划合并）—— 当前心情 / 亲密度 / 当前思绪 / 当前正在做什么；与 profile_summary 联动；详见 §十九

#### v3-G'：TTS UI + cosyvoice instruct emotion ✅ 完成（5 commit + 2 patch，2026-05-06）
- [x] **`GET /api/tts/voices` 接口**（`de7ebe2`）—— provider/voice 两级结构，从 `config.yaml` `tts.available_voices` 读
- [x] **CharacterPanel 两级下拉**（`bd46a80`）—— provider → voice，下拉项展示 `{label} · {traits}`；patch (d) 加 mount auto-refetch + 刷新按钮（dev 模式时序兜底）
- [x] **`config.yaml` `tts.available_voices.cosyvoice` 列表**（7 音色：longyumi_v3 / longfeifei_v3 / longwan_v3 / longqiang_v3 / longxing_v3 / longanhuan / longanyang）
- [x] **写回逻辑**：用户选择 → `buildVoiceModelJson(provider, voice, instruct_supported)` 写回 character.voice_model 同字段，向后兼容旧 plain 字符串（UI 提示"自定义"）
- [x] **Momo (id=1) 默认音色 lifespan migration**（`bf21915`）`v3_g_default_voice.py` 幂等
- [x] **emotion 真生效路径修正**（`b29662c` + `e73e2bc`）：chunk 1a 把 emotion 包成 `<voice emotion="X">` SSML 是错的——DashScope SSML 标签合法属性是 voice / rate / pitch / volume / effect / bgm，**没 emotion**。撤回 SSML wrapper，改走 SDK `instruction` 字段 (`speech_synthesizer.py:218-219` audit 证实)，仅 `instruct_supported=true` 音色启用
- [x] **instruction 字符串严格匹配文档**（patch (c) `d05d292`）：`"你说话的情感是{emotion}。"`，emotion 与"是"之间**不能**有空格，否则系统音色返 `InvalidParameter 428`。同 commit 加 instruct-aware 男声 longanyang
- [x] **架构验证**：`/api/tts/voices` schema 容纳多 provider，未来 v5-T1 SoVITS 接通时后端追加 entry，前端 0 改动

**TTS provider 抽象层 + emotion 数据流**（v3-G' 定型）：

```
LLM 输出 <emotion>X</emotion> 标记（v3-D 解析）
       ↓
WebSocket emotion 字段（store: turnEmotion）
       ↓
get_tts_engine(character) 解析 voice_model JSON
       ↓                        ┌─ provider="cosyvoice" → CosyVoiceTTS(voice, instruct_supported)
       ↓                        ├─ provider="sovits"    → SoVITSProvider（v5-T1 占位）
       ↓                        └─ provider="edge"      → EdgeTTS（兜底）
CosyVoiceTTS._blocking_synthesize:
  if instruct_supported and emotion ∈ {happy,sad,angry,surprised}:
      kwargs["instruction"] = "你说话的情感是{emotion}。"   # 系统音色固定格式
  else:
      pass   # neutral / 非 instruct 音色 → emotion 字段静默丢弃
  SpeechSynthesizer(**kwargs).call(text)        # instruction 走构造函数，非 call()
```

**系统音色 vs 复刻音色的 instruction 能力差异**（DashScope 文档约束）：

| 音色类型 | 来源 | instruction 格式 | 能力 |
|---|---|---|---|
| 系统音色（`long*` 家族） | 平台预置 | **必须**严格匹配 `"你说话的情感是{emotion}。"` 等固定模板 | 仅 longanyang / longanhuan / longhuhu_v3 三个支持，emotion 限文档 7 枚举 |
| 复刻音色（`myvoice-xxx`） | 用户 fine-tune / voice cloning | 自由自然语言（如"温柔地慢慢说"） | 不限固定模板，未来 Phase 2 真主力 |

**关键决策汇总**：详见 `ROADMAP.md` v3-G' 章节"关键决策（知识沉淀）"四条。

### 📋 阶段六：v4 屏幕感知 + 视觉能力（OLV #4 借鉴）

1. **后端**：vlm/client.py + screen/analyzer.py + filter.py
2. **Tauri**：screen capture API + 像素差对比 + 全局热键监听
3. **前端**：Settings 面板加 Screen Awareness 开关 + 黑名单管理
4. **WebSocket**：增加 `screen` 上行 + `screen_comment` 下行
5. **黑名单**：截图前检查活动窗口（应用名 / 窗口标题 / Bundle ID）
6. **主动模式**：hotkey / 语音命令触发单次截图 → VLM
7. **被动模式**：定时截图 + 像素差预过滤 → VLM 仅在画面真有变化时调用 → AI 主动评论
8. **AI 用自己的浏览器**（OLV #4 后半，可选）—— 内嵌 webview 让 AI 能访问网页查信息（区别于 web_search 工具的纯文本结果）

### 📋 阶段七：v5 部署 + 自定义 TTS

#### v5-D：autodl 部署 + 子 agent 隔离

部署到国内云服务器（autodl / Modal / 自有 VPS）后：
- 后端 → DashScope 国内直连，秒回
- 前端 Mac → 后端通过 SSH tunnel 或 HTTPS
- 用户本地 VPN 状态不再影响 LLM 调用
- **子 agent 隔离**（Hermes #4 借鉴）—— 长任务（屏幕分析、批量记忆压缩、自主信息收集）跑在独立子 agent context，不阻塞主对话

#### v5-T1：GPT-SoVITS 后端接通

依赖 v5-D autodl 部署（SoVITS 推理需要 GPU）：
- [ ] **autodl 起 SoVITS 推理服务器** —— fast inference fork（如 RVC-Project / GPT-SoVITS-Inference），HTTP API 形式
- [ ] **`SoVITSProvider` 真实现** —— 当前 `_LegacyProviderAdapter` 是占位；改为按 §6.2 SoVITS schema 调用，`emotion → ref_audios[emotion]` lookup
- [ ] **`config.yaml` `tts.sovits.available_voices` 列表** —— 列出 autodl 上已部署的 SoVITS 模型
- [ ] **`GET /api/tts/voices` 自动包含 sovits provider** —— UI 下拉自然多一项（v3-G' 的架构 payoff）
- [ ] **路径管理** —— autodl 上的模型路径在 SoVITSProvider 内做翻译；前端只见显示标签

#### v5-T2：训练自己的 voice 模型

依赖 v5-T1（先有 provider 再训模型）：
- [ ] **CosyVoice fine-tune voice cloning** —— 收集 5-10 段角色参考音频 → DashScope voice cloning 工作流 → 拿到 `myvoice-xyz123` ID → 加进 `available_voices` 列表
- [ ] **GPT-SoVITS 专属 model 训练** —— 收集更多角色音频 → autodl GPU 训练 SoVITS / GPT 模型对 → 准备多情感参考音频文件 → 加进 `available_voices` 列表
- [ ] **角色自动绑定**：训练完成的 voice 默认绑定到对应 character（用户手动 confirm）

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
Skyler 是一个可塑型 AI 角色容器（hackable AI companion framework）—— 桌面端、角色驱动、能拆到 agent 内核、所有权归用户（原名 MomoOS，2026-05 改名）。
目标用户：有动手能力的二次元半技术宅。三角坐标：Skyler 站在 Open-LLM-VTuber（强角色但磨光）和 Hermes Agent（强可改但 CLI）中间的空地。
技术栈：FastAPI + WebSocket（后端） + React 18 + Vite + Tauri 2（前端） + SQLite + SQLAlchemy async。
完整背景：仓库根 README.md / DESIGN.md（§零 + §一）/ ROADMAP.md。

【当前状态】
v2.7 + v3-A/B/C/D 完成，v3 整体约 60%。
v3-A: 8 套主题 + lucide-react ✅
v3-B: character.voice_model + CosyVoice ✅
v3-C: PlannerAgent 简化 ✅
v3-D: emotion 后端 ✅（前端等 Live2D）
下一阶段：v3-E1（Live2D 接入用 Hiyori 走通）/ v3-E2（换目标模型）/ v3-F（语音体验）/ v3-G（生活工具层）/ v3-G'（TTS 配置 UI 升级）。
v5 阶段拆为：v5-D autodl 部署 + 子 agent / v5-T1 GPT-SoVITS 接通 / v5-T2 训练自定义 voice。

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

## 十九、三角坐标:Skyler 在 Open-LLM-VTuber 与 Hermes Agent 之间

Skyler 站在两个项目之间的空地。本节不是"借鉴 OLV 哪些 feature + Hermes 哪些 feature"清单,而是说清楚 Skyler 在产品空间里的位置 —— 同意 OLV 的什么设计判断、同意 Hermes 的什么设计判断、跟它俩明确不同的地方、当前真实存在的差距。

### 19.1 在哪些设计判断上 Skyler 同意 OLV

[Open-LLM-VTuber](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber) 是打磨好的桌面 VTuber 陪伴体验。Skyler 在以下设计方向上跟 OLV 共享判断:

- **桌面 Live2D 看板娘是有效的陪伴 UX**(不是 GitHub Issues 风的 CLI)
- **TTS 多音色 + emotion 驱动是角色感的关键**(不是单一 voice 念稿子)
- **语音打断 + 并发 TTS + 文本 emotion 预处理是基础体验需求**(详见 §六)
- **motion 跟 emotion 绑定可以加强角色具象**(详见 §十四之A Live2D 架构)
- **MCP 协议接入是合理选型**(详见 §十五 MCP 工具扩展)

### 19.2 在哪些设计判断上 Skyler 同意 Hermes

[Hermes Agent](https://github.com/NousResearch/hermes-agent)(Nous Research)是服务器跑的个人 agent 平台。Skyler 跟 Hermes 共享以下设计判断:

- **Agent 应该是"框架"而不是"app"**(用户能拆开来改,见 §零所有 0.x)
- **Skill 应该是 declarative 注册**,不需要复杂 plugin manifest(见 §十五之A Capability Registry)
- **子 agent 隔离 / 多执行 backend 是长任务的合理架构**(屏幕分析 / 批量记忆压缩 / 云端 fine-tune)
- **self-improving 是 agent 长期价值的关键** —— 但 Skyler 把这个判断应用到**角色**这一层,不是 skill 这一层(详见 19.3)

### 19.3 Skyler 跟它俩明确不同的地方

- **不是开箱即用 VTuber app**(OLV 是):Skyler 期望用户至少能跑命令行、能改 config、能写一点 Python。这个用户筛选是有意的 —— 详见 §一 1.2 目标用户。
- **不是 CLI / 服务器 agent**(Hermes 是):Skyler 是桌面应用,角色具象化(Live2D / 立绘 / 状态面板)是 first-class concern,不是可选 plugin。
- **self-improving 哲学的应用对象不同**:
  - Hermes:skill 越用越好(skill 库变厚 + 单 skill 内部演化)
  - Skyler:**角色越用越像一个具体的人**(persona-level learning,通过 `character_states` 长期演化)
  - 同一个"系统会变好"哲学,但落在不同对象上。详见 [ROADMAP.md](ROADMAP.md) "Later" 支柱。

### 19.4 哪些缺口是真实存在的

诚实承认 —— 在某些维度 Hermes 当前比 Skyler 强。这些不是被否定的功能,是 Skyler 当前没做到的真实差距:

| 维度 | Skyler | Hermes |
|---|---|---|
| 自我提升 skill 学习 | ❌(理念差异 + 路线图远期) | ⭐⭐⭐⭐⭐ |
| 跨平台 messaging gateway(Telegram 等)| ❌(中期 roadmap) | ⭐⭐⭐⭐⭐ |
| 训练数据导出 | ❌(远期 roadmap,隐藏卖点) | ⭐⭐⭐⭐⭐ |

完整对比 + 用户视角说明见 [README §Comparison](README.md#comparison)。

### 19.5 明确不做的事(避免设计漂移)

| 不做的事 | 原因 |
|---|---|
| 群聊(多角色同时在场对话) | 跟单角色驱动定位冲突 |
| Bilibili 弹幕直播客户端 | 直播场景,跟桌面角色 agent 定位无关 |
| Letta / MemGPT 独立 memory 系统 | 现有 SQLite + sentence-transformers 已够用,引入 Letta 增加运维复杂度 |
| WhatsApp / WeChat gateway | API 限制 + 商业风险(注:Telegram / Discord 在中期 roadmap) |
| 跟 LangChain / AutoGen 比拼通用 agent 框架 | Skyler 是角色驱动桌面 agent,不是通用 agent 框架 |

注:成长系统设计已在 §十五之C 完整展开,不在本节重复。

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
- **v3-WIP+1（2026-05-04 晚，TTS schema + Live2D 拆分）**：§六 TTS 分层重写，加入完整 voice_model JSON schema（CosyVoice / Edge / GPT-SoVITS 三种 provider 的 schema 示例 + GPT-SoVITS 多情感参考音频结构）+ §6.4 前端 CharacterPanel 配置 UI 设计（per-character only，无全局开关，下拉只显示真实可用选项）；v3-E 拆分为 v3-E1（用 Hiyori 走通 Live2D 集成）+ v3-E2（换目标模型）；新增 v3-G'（TTS UI 升级）；v5 阶段拆分为 v5-D（autodl 部署）/ v5-T1（GPT-SoVITS 后端接通）/ v5-T2（自定义 voice 训练）
- **v3-WIP（2026-05-04，Skyler 改名 + v3-A/B/C/D 完成）**：项目 MomoOS → Skyler；v3 拆 A-G 七个子阶段；A/B/C/D 完成（8 套主题 + lucide / character.voice_model + CosyVoice / PlannerAgent 简化 / emotion 后端）；E/F/G 计划写明（Live2D / 语音体验 / 生活工具层）；新增 §十九 OLV/Hermes 借鉴清单 + §二十 跨平台策略
- **v2.7（2026-05）**：v2.5 全模块完成 — schema 加 conversations/characters/character_id/conversation_id 列；删 personality 表；4 个 memory tool（save/delete/list/compress）通过 LiteLLM tool calling；隐式 summarizer 替代每 20 轮显式总结；前端 ChatGPT 模式重构 — 三栏布局 + 折叠侧栏 + Galgame 风（Character 满铺 + 浮动气泡 + 历史抽屉）+ 多角色切换；Sidebar 简化 💬⚙；SettingsPanel 重构（含记忆/基础信息/角色三新区块）；profile_summary 增量重写 + 50 轮 / 删对话触发 + 数据门槛保护；启动模式 localStorage 持久化（默认 Panel）；config.yaml 改用 openai/qwen-plus + DashScope 兼容端点；后端 lifespan 预加载 + asyncio.to_thread + /api/health。
- v2.6（2026-05）：补全 GET /api/config 白名单 JSON；修正 reload 函数为 reload_config_yaml() / get_*() 风格；新增 tts.enabled 全局开关；Tauri 2 write_config_field 命令实现。
- v2.5（2026-04）：v4 屏幕感知模块设计，初版前端 v2 模块清单。
