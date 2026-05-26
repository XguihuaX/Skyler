# FRONTEND-OVERVIEW

> 前端代码现状图 · 前后端对接全貌 · 漂移点
> 生成时间：2026-05-19 02:05｜更新：2026-05-26 docs 第三刀(INV-11 Stage 1.5 paradigm B 反映)｜HEAD = `c1d65ff` + INV-11/12 增量
> 只读勘查；未改任何代码 / DB / commit / stash / backend 未启动 / 未跑构建
> 配套：`docs/BACKEND-OVERVIEW.md` / `docs/archive/INVESTIGATION.md`（已归档）+ `docs/INVESTIGATION-2.md` + `docs/INV-11-*.md` + `docs/INV-12-fish-config-audit.md` + `docs/adding-new-tts-model.md`

## 第 0 节 · 2026-05-26 INV-11 Stage 1.5 paradigm B 更新点(增量速读)

- **`components/VoicePickerModal.tsx` 删除** · 替代为 `components/character/VoicePicker.tsx`(inline 3 级 dropdown:provider × model × voice + voice list 含系统/复刻双 section header + TTS 语言 + auto-save debounce 300ms)
- **CharacterPanel.tsx** TTS section 改:删原 simplified 两级 dropdown + 删 [📢 试听并选 voice] modal trigger button + 内联 `<VoicePicker .../>`
- ttsProviders / clonedVoices / voiceAliases / ttsLoading 等 state 从 CharacterPanel **内化进 VoicePicker**(自己 fetch `/api/tts/providers` nested tree + aliases)
- 详 `docs/INV-11-stage0-llm-output-audit.md` + `docs/adding-new-tts-model.md` + Lesson INV-11 #12 (`docs/LESSONS.md`)

---

## 第 1 节 · 前端技术栈与结构

### 1.0 技术栈

| 层 | 选型 | 版本 | 备注 |
|---|---|---|---|
| Shell | **Tauri 2** | `@tauri-apps/api 2.11` + `@tauri-apps/cli 2.11` | Rust 桌面壳，`frontend/src-tauri/`（`Cargo.toml` + `tauri.conf.json`） |
| 构建 | **Vite 6** + TypeScript 5.6 | `vite.config.ts` / `tsconfig.json` / `tsconfig.app.json` / `tsconfig.node.json` | dev=`vite` / build=`tsc -b && vite build` |
| UI 框架 | **React 18.3** | StrictMode | `main.tsx:6-10` 单根 root |
| 样式 | **Tailwind 3.4** + `framer-motion 12` | + CSS 主题变量（8 套） | `tailwind.config.js` / `styles/themes.css` |
| 状态 | **Zustand 5** | 单 store | `store/index.ts`（591 行，所有全局态在此） |
| Live2D | `pixi.js 7.4` + `pixi-live2d-display 0.5-beta` | Cubism 4 only | `lib/live2d/` + `components/live2d/` |
| 图标 | `lucide-react 1.14` | — | — |

后端是 FastAPI + uvicorn（参见 BACKEND-OVERVIEW.md §1）；前端通过 WS（主聊天流）+ REST（CRUD / 配置）双通道与之对接。

### 1.1 顶层结构（frontend/src/）

```
App.tsx (260)              ← 入口：mode 切换 widget/panel + 5 重 overlay 挂载
main.tsx (10)              ← createRoot + StrictMode
modes/
  Panel.tsx (141)          ← 主面板模式：TopBar + Sidebar + 4 view 路由（chat/characters/capabilities/settings_v2）
  Widget.tsx (85)          ← Widget 模式（小窗）
hooks/
  useWebSocket.ts (686)    ← ★ WS 主驱动：5 SEND + 13 RECV 帧 + 流式状态机
  useAudio.ts (243)        ← 麦克风 / VAD / 录音
  useAudioAmplitude.ts (72)
  useFullscreen.ts (105)
store/index.ts (591)       ← ★ Zustand 单 store；所有全局态
contexts/appApi.ts (28)    ← AppApiContext：把 useWebSocket 返回的 5 个 sender 注入整树
lib/                       ← REST 层（17 个 .ts 文件，按后端 router 分桶）
components/                ← 35 个 .tsx + 5 个子目录（character / live2d / capabilities / extensions / settings）
config/live2d.ts           ← 角色 → motionMap/emotionMap 静态映射
styles/themes.css          ← 8 套主题色变量
```

### 1.2 视图 / 页面清单

`Panel.tsx` 由 store `panelView` 4 选 1 路由：

| view | 入口组件 | 行数 | 角色 |
|---|---|---|---|
| `chat` | `ConversationList` + `CharacterView` + `ChatInput` + `ChatHistoryPanel` | 337 / 183 / 189 / 53 | 主对话视图，Galgame 式立绘 + 左右推拉 + **左右两侧可拖拽 resize handle**（2026-05-19 已实现真机验证通过未 commit） |
| `characters` | `CharacterPanel` | **1862** | 角色 CRUD / 立绘 / Live2D / TTS / persona variant |
| `capabilities` | `CapabilitiesPanel` | — | 能力开关（→ `CapabilityPanel 911` + `ExtensionsSection 900` + AI providers / MCP） |
| `settings_v2` | `SettingsPanelV2` | — | 新规范设置（导入 `SettingsPanelLegacy` 中的 wrapper 函数复用） |

Widget 模式（`Widget.tsx 85`）只显示 `CharacterView` + `CharacterStatePanel` + 极简控制，无 panelView 路由。

### 1.3 Overlay 挂载（App.tsx）

`App.tsx:193-256` 顶层挂 5 个 overlay：
1. `CharacterStatePanel(position="widget")` — widget 模式下角色情绪条
2. `ActivityPermissionModal` — 后端 push `activity_permission_missing` 时弹
3. `NotificationToast` — notify/alarm 队列
4. `CharacterGallery` — `store.galleryOpen=true` 时全屏角色馆（v4-fan chunk 4，z=990）
5. `SplashOverlay` — 启动溅屏（z=10000）+ `warming` 健康检查 spinner

### 1.4 组件清单（按职责分组）

- **对话主链**：`ConversationList` / `ChatHistoryPanel` / `ChatHistory` / `ChatInput` / `ControlBar` / `AsrPreview` / `VadBar`（注：`VoiceButton.tsx` 见 §3.1，**实测死代码**待清，不在主链）
- **角色相关**：`CharacterPanel` / `CharacterView` / `CharacterSelect` / `CharacterSwitcher` / `CharacterStatePanel` / `character/{CharacterCard, CharacterDetailModal, CharacterGallery, FanLayout, SplashArtDropzone, VoiceLinesSection, VoicePicker}` / `PersonaEditorModal`
  - `character/VoicePicker.tsx` — INV-11 Stage 1.5 paradigm B(2026-05-26)inline 3 级 voice picker · 替代原 `VoicePickerModal.tsx`(已删)
- **Live2D**：`Live2DCanvas` + `live2d/{Live2DDropzone, MotionMapConfirmDialog}`
- **能力/扩展**：`CapabilityPanel` / `CapabilityRow` / `capabilities/{CapabilitiesPanel, AddModelModal, AddVendorModal, AIProvidersSection, VendorCredentialsModal}` / `ExtensionsSection` / `extensions/AddMCPServerForm`
- **记忆**：`MemoryManagerDrawer`（注：`MemoryViewer.tsx` 见 §3.1，**实测死代码**待清）
- **活动感知**：`ActivityAwarenessSection` / `ActivityPermissionModal` / `ActivityTimelineDrawer`
- **设置**：`settings/SettingsPanelV2` / `SettingsPanelLegacy(@deprecated)` / `UserProfileSection`
  - 注:`VoicePickerModal` 已删(2026-05-26 INV-11 Stage 1.5 paradigm B inline 化);voice 选择见 `character/VoicePicker.tsx`
- **基础壳**：`TopBar` / `Sidebar` / `TwoPaneShell` / `SplashOverlay` / `NotificationToast` / `ConnectionDot` / `StatusBadge`

### 1.5 状态管理

**Zustand 单 store**（`store/index.ts`，591 行）。无 Redux、无 Context state（除 `AppApi` 单纯把 WS sender 注入树）。

持久化（localStorage）：
- `momoos.mode` — widget/panel
- `momoos.theme` — 8 套主题 key
- `momoos.convListCollapsed` / `momoos.chatPanelCollapsed` — 左右推拉折叠态
- `momoos.showStatePanel` — 角色状态条开关
- `momoos.convListWidth` — ConversationList 拖拽宽度（2026-05-19 新增；clamp [160, 400]，default 240，未 commit）
- `momoos.chatHistoryWidth` — ChatHistoryPanel 拖拽宽度（2026-05-19 新增；clamp [320, 600]，default 420，未 commit）

按域分组（store 内部）：mode/theme / status(idle/listening/thinking/speaking/interrupted) / recording / connection / VAD 参数 / TTS 开关 / 通知队列 / config 镜像（fetchConfig 同步进来）/ proactive 配置镜像 / characters & conversations & chatMessages / Live2D 模型扫描 / TTS providers / current{Thinking,Tool,Emotion,Motion,CharacterState}。

---

## 第 2 节 · 前后端对接全貌

### 2.1 WebSocket 帧 — SEND（前端发出）

`hooks/useWebSocket.ts` 暴露 5 个 sender，注入 `AppApiContext`（`contexts/appApi.ts:13`）：

| Type | 文件:行 | Payload 字段 | 触发点 |
|---|---|---|---|
| `text` | `useWebSocket.ts:547` | `content, user_id, conversation_id, character_id` | `ChatInput`（用户提交文本） |
| `voice` | `useWebSocket.ts:577` | `audio(base64), user_id, conversation_id, character_id` | `VoiceButton` 长按 + `useAudio.stopManualAndSend` |
| `interrupt` | `useWebSocket.ts:614` | （无负载） | `ControlBar` 🚫 按钮 + 用户语音打断 |
| `touch` | `useWebSocket.ts:650` | `user_id, conversation_id, character_id` | `Live2DCanvas` 点击立绘 |
| `character_switch` | `useWebSocket.ts:669` | `user_id, character_id, conversation_id` | `sendCharacterSwitch(cid, conv_id)`，由切角色 UI 触发；后端 `ws.py:824` 收，仅更新 `connection_manager`，不触 LLM |

### 2.2 WebSocket 帧 — RECV（前端收）

`useWebSocket.ts:172-396` 13 种 type 路由：

| Type | 处理 | 写到 store / 触发 UI |
|---|---|---|
| `asr_result` | 显示用户语音转写 | `appendChatMessage(role=user)` + `setAsrText` |
| `text_chunk` | 流式回复段 | 首段 `appendChatMessage(streaming=true)`；后续 `appendChatMessageContent(id, delta)`；proactive 首段弹 toast |
| `audio_chunk` | TTS 段音频 base64 wav | 创建 `Audio` 元素 → `audioQueueRef` → `playNextAudio` 顺序播放 |
| `done` | 当轮结束 | `finishChatMessage` + `setStatus → idle/interrupted`；若 interrupted 清音频 queue |
| `thinking` | 内心独白（v3-F） | `setCurrentThinking` → `StatusBadge` 旁短显 |
| `emotion` | 情绪（v3-E1 step5） | `setCurrentEmotion` → `Live2DCanvas` 监听 |
| `motion` | 动作（v3-E1 step6） | `setCurrentMotion` → `motionMap` 映射 → `model.motion(group, idx)` |
| `state_update` | 心情/亲密度变化 | `setCurrentCharacterState` → `CharacterStatePanel` 刷新 |
| `notify` | 通知 | `pushNotification(type='notify')` |
| `alarm` | 闹钟（todo 到点） | `pushNotification(type='alarm')` |
| `activity_permission_missing` | 后端权限自检失败 | `setActivityPermissionHint` → 弹 modal |
| `tool_use_start` | LLM 开始调 tool | `setCurrentToolName` → 进度条 |
| `tool_use_done` | LLM tool 完成 | `setCurrentToolName(null)` |
| `character_switch_ack` | 切角色 ack | （由 ws.py:831 发，前端确认连接态同步） |

**关键过滤**（`useWebSocket.ts:147-170`）：流式段按 `conversation_id` 严格匹配；不匹配丢弃。配合后端 Bug 1 修法（每 entry 记录 conv_id 严格匹配）。

### 2.3 REST 接口调用全清单

前端调的 `/api/*` 路径（按 `lib/*.ts` 分桶 + 组件直 fetch）：

| Endpoint | 方法 | 后端 router | 状态 |
|---|---|---|---|
| `/api/config` | GET | `routes/config.py` | ✅ |
| `/api/config/reload` | POST | `routes/config.py` | ✅ |
| `/api/config/base_instruction` | GET/POST | `routes/config.py` | ✅ |
| `/api/health` | GET | `routes/health.py` | ✅（启动轮询） |
| `/api/heartbeat` | POST | `routes/health.py` | ✅（long_idle gate） |
| `/api/characters` (list) | GET | `routes/characters_api.py` | ✅ |
| `/api/characters/create` | POST | `routes/characters_api.py:128` | ✅（创建角色） |
| `/api/characters/{id}` | PATCH/DELETE | `routes/characters_api.py` | ✅ |
| `/api/characters/{id}/splash-art` | POST/DELETE | `routes/characters_api.py` | ✅ |
| `/api/characters/{id}/state` / `/reset_state` | GET/POST | `routes/character_state.py` | ✅ |
| `/api/characters/{id}/personas` (4 endpoints) | GET/POST/PATCH/DELETE | `routes/persona_api.py` | ✅ v4 多 variant |
| `/api/conversations` (list/create/messages/PATCH/DELETE) | 多方法 | `routes/conversations_api.py` | ✅ |
| `/api/live2d/models` / `upload` | GET/POST | `routes/live2d.py` | ✅ |
| `/api/tts/voices` | GET | `routes/tts.py` | ✅ |
| `/api/users/*` | 多方法 | `routes/users.py` | ✅（含 profile） |
| `/api/ai-vendors` / `/api/ai-providers` | GET/POST | `routes/ai_providers.py` | ✅ |
| `/api/capabilities` | GET | `routes/capabilities.py` | ✅ |
| `/api/activity/*` | 多方法 | `routes/activity.py` | ✅ |
| `/api/mcp/clients` 等 | 多方法 | `routes/mcp.py` | ✅ |
| `/api/backgrounds` | GET | `routes/backgrounds.py` | ✅ |
| `/api/memory/list` 等 | GET/POST/PATCH/DELETE | `routes/memory_api.py` | ✅ `MemoryManagerDrawer` 用 |

**差集**（后端有但前端未消费）：
- `/api/observability/*`（tts_call_log 埋点 API）— 前端无可视化页面入口
- `/api/integrations/*` 部分子路由（日历 OAuth 流走它，部分可能未接 UI）
- `/api/webhooks/*` / `/api/briefing/*` 部分测试 endpoint

**前端有但后端无**：无差集（已实测对齐）。

### 2.4 关键交互契约抽查

| 交互 | 前端发 | 后端收/字段 | 一致性 |
|---|---|---|---|
| 发文本消息 | `{type:'text', content, user_id, conversation_id, character_id}` | `ws.py:817-819` 读 `data.get('conversation_id'/'character_id')`，str→int | ✅ 对齐 |
| 切角色 | `{type:'character_switch', character_id, conversation_id}` | `ws.py:824` 仅 `connection_manager.set_current`，发 ack | ✅ 对齐；不触 LLM 符合设计 |
| 改记忆 | `PATCH /api/memory/{id}`（前端 `MemoryManagerDrawer`） | `routes/memory_api.py:173 @router.patch` | ✅ 对齐 |
| TTS 播放 | RECV `audio_chunk` base64 wav | `ws.py` 后端 stream TTS 字节 | ✅ 顺序队列播放 |
| Live2D 驱动 | RECV `emotion` / `motion` | `Live2DCanvas` useEffect → `motionMap`(`config/live2d.ts`) → `model.motion(group, idx)` | ✅ 静态 motionMap 映射；新角色无 motionMap 时降级 no-op |

### 2.5 新增角色全流程 — cid 生成确切位置

**UI 入口**：
- `CharacterPanel.tsx:860` 附近 `startForm(null)` → 进入创建表单
- 表单提交调 `createCharacter()`（`lib/characters.ts` / `lib/config.ts`）

**前端请求**：
```
POST /api/characters/create
body: { name, persona, avatar_path?, voice_model?, live2d_model?, background_path? }
```
**不传 character_id** —— 用户只填名字 + persona 等可选字段。

**后端处理**：`backend/routes/characters_api.py:128-154`
```python
@router.post("/characters/create", status_code=201)
async def create_character(body: CharacterCreateBody, session: AsyncSession):
    c = Character(name=body.name, persona=body.persona, ...)
    session.add(c)
    await session.commit()
    await session.refresh(c)   # ← 回填 DB 分配的 id
    return _to_dict(c)
```

**cid 生成位置**：`backend/database/models.py` — `Character` 类
```python
class Character(Base):
    __tablename__ = "characters"
    id = Column(Integer, primary_key=True, autoincrement=True)
    ...
```

→ **cid 完全由 SQLite AUTOINCREMENT 分配**，前端、API、用户都不参与；流萤 `cid=102` 就是这样自然产生的下一个 id（cid=101 之后的 +1）。

这给"统一 cid 命名"提供了关键约束：
- ✅ **新增角色的 cid 是单调递增的自然主键**，无法人为指定
- ⚠️ **cid=99/100/101 是历史遗留 / 测试植入的"大数字"**（绕过自然递增；可能由 migration 或手 INSERT 注入）
- ⚠️ **若想"统一命名"重排 cid**，会涉及大量外键级联（character_personas, character_states, chat_history, conversations, memory, pending_briefings 全部按 character_id 外键），实操**几乎不可逆**

---

## 第 3 节 · 前端已知问题 / 技术债 / 漂移

### 3.1 前端代码内部技术债

| 项 | 位置 | 状态 | 处置建议 |
|---|---|---|---|
| **TODO / FIXME / HACK 数量** | `frontend/src/` 全库 | **0 命中** ✅ | 无 |
| **@deprecated 标记** | 仅 `SettingsPanelLegacy.tsx:1659` 一处 | 已标 bugfix-2.2 完全替代 | 见下条 |
| **巨型 `SettingsPanelLegacy.tsx`** (1953 行) | 整文件 @deprecated | **未被 `Panel.tsx` 直接渲染**；但 `SettingsPanelV2.tsx:32` + `capabilities/AIProvidersSection.tsx:33` 仍 import 其中导出的 wrapper 函数 | 删之前需把那些 wrapper 函数迁出 / 内联；v4.1 真清 |
| **巨型 `CharacterPanel.tsx`** (1862 行) | 角色 CRUD + 立绘 + Live2D + TTS + persona variant 混合一体 | 全 section 仍在用，**无死代码** | 可拆但不阻塞；v4.x 重构候选 |
| **巨型 `CapabilityPanel.tsx`** (911 行) / `ExtensionsSection.tsx` (900 行) | capability + MCP 配置 | 仍在用 | 可拆但不阻塞 |
| **`MemoryViewer.tsx`** (24 行) | **实测死代码** —— grep 外部引用 = **零命中**（自身 export，无人 import / 无 `<MemoryViewer />` 使用） | 可删 |
| **`VoiceButton.tsx`** (21 行) | **实测死代码** —— grep 外部引用 = **零命中**（自身 export，无人 import / 无 `<VoiceButton />` 使用） | 可删 |
| `ConnectionDot.tsx` (22 行) | ✅ **活**：`ControlBar.tsx:4,121` + `Sidebar.tsx:9,80` 真 import + 渲染 | 保留 |

### 3.2 前后端对接漂移

> **[2026-05-19 校准]** 原 §3.2 系 agent 报告未自验导致系统性误判（5 条判错 4 + 1 半对）。
> 本次逐条 grep + 组件实证修正。详见 INVESTIGATION.md【clipboard 溯源 + 前端勘查误判自查】+【前端全面重核】。

| 项 | 真值 |
|---|---|
| 后端 `/api/memory/*` 全活 | ✅ 前端 `MemoryManagerDrawer.tsx`（475 行）真消费 |
| 后端 `/api/observability/*` | ✅ **UI 真有**：(a) `SettingsPanelLegacy.tsx:1157+ SystemStatusSection` 3 秒刷新 `fetchSystemResources`（CPU/RAM/Whisper/Net 系统监控）；(b) `capabilities/AIProvidersSection.tsx:1255 fetchTtsUsage` + `fetchRecentCalls`（TTS 用量 + 最近调用埋点可视化）。**原判完全错** —— 漏盘整块 SystemStatusSection |
| 后端 `/api/todos/*` | ⚠️ 退役后：**无写入 UI**（从未有过）；有 RECV-only `alarm` WS 帧 → `NotificationToast` 通知路径（`useWebSocket.ts:369-370 + store/index.ts:227` + `NotificationToast.tsx:30-31`）。c1d65ff 退役 AlarmScheduler 后该 RECV 分支变 **dead branch**（无人推 alarm，但 RECV 代码留着无害）。原判"前端无 UI"半对 |
| 后端 `/api/clipboard/*` | ✅ **UI 真有**：`SettingsPanelLegacy.tsx:604-765 ClipboardSection`（160+ 行完整 UI：捕获开关 + 隐私说明"🔒 仅本地内存,重启清空,不外传" + 最近 5 条列表 fetch + 清空按钮）；`SettingsPanelV2.tsx:25,32,111` 真渲染。端到端真活：开关 toggle → `POST /clipboard/enabled` → `ClipboardWatcher.set_enabled`；列表 → `GET /clipboard/recent?n=5`。**原判完全错** |
| 后端 `/api/users/{uid}/profile_data` PATCH | ✅ **UI 真有**：`UserProfileSection.tsx`（510 行）完整 PATCH + regenerate UI，走 `lib/profileData.ts → /api/users/{uid}/profile_data`；Legacy L1918 + V2 L33 双路 import 渲染。**原判"无 PATCH 表单"错（已自纠）** |
| 后端 `/api/briefing/test` | ✅ **前端真调用**：`lib/integrations.ts:58` `${BACKEND_BASE}/api/briefing/test?mode=${mode}`。**原判"前端无调用"错** |
| `switch_character` LLM tool | ✅ 已下线（commit `71b6e99`）；前端切角色走 `character_switch` WS 帧 → `ws.py:824 connection_manager.set_current`，不依赖此 tool |
| 前端调了但后端无的 endpoint | ✅ 实测零差集（前端 fetch /api/* 全清单 35 个 endpoint，每个在 backend/routes/ 都有对应 router） |

### 3.3 与文档漂移

| 文档说法 | 前端实情 | 漂移 |
|---|---|---|
| DESIGN.md §Z.4 "删 ChatHistoryDrawer / 浮现台词气泡" | `find ChatHistoryDrawer* CharacterDialogueBubble*` → 文件**已删**；`Panel.tsx:73-75` + `ChatHistoryPanel.tsx:5` 注释引用是历史叙述 | ✅ **PASS** 名实相符（M-6 终核） |
| DESIGN.md §F1 "v4-beta 主推 Mai 单角色" | 前端 `CharacterPanel` / `CharacterGallery` / `CharacterSelect` 等待所有 9 个 character 通用渲染，无"主角"特殊化 | ⚠️ 文档措辞与代码实情有距离（与 BACKEND-OVERVIEW §3 L-1/L-5 同源） |
| BACKEND-OVERVIEW §2 H-1 `switch_character` silent failure | 已闭合（`71b6e99` 下线 LLM tool）；前端切角色完全靠 `character_switch` WS 帧 → `connection_manager.set_current`，与文档新状态对齐 | ✅ 闭合 |

### 3.4 M-6 ChatHistoryDrawer 残留 — 终核归档

| 检查 | 真值 |
|---|---|
| 文件是否存在 | `find frontend/src -name "ChatHistoryDrawer*"` → **空**（已删） |
| `CharacterDialogueBubble*` 同 | 同上空 |
| import / use grep | 仅 `Panel.tsx:74` 注释 + `ChatHistoryPanel.tsx:5` 注释，无 `<ChatHistoryDrawer />` 实际使用 |
| 替代组件 | `ChatHistoryPanel.tsx`（48 行，右侧推拉栏） |

→ **✅ M-6 PASS 终结**（与 INVESTIGATION §3.1 一致）；可在 AUDIT 中归档关闭。

### 3.5 新角色 cid=102 流萤前端能否正常显示 / 选择 / 驱动 Live2D

**代码层判断**：

| 渲染路径 | 处理 cid=102（无 live2d_model / splash-art 单图） | 状态 |
|---|---|---|
| `CharacterSelect` / `CharacterSwitcher` 下拉 | 按 `characters` 数组遍历，无特殊化 → 流萤会出现 | ✅ 应正常 |
| `CharacterCard.tsx`（角色馆/Gallery 卡片） | 若 `splash_art_url` 为空走 `_placeholder.png` 兜底 | ✅ 应正常（流萤有 `/splash-art/102.png` 但 untracked，需真机看上传是否落） |
| `CharacterView` + `Live2DCanvas` | `characters.live2d_model` 为空时走 fallback → 静态图 / `_placeholder.png` | ✅ 不崩；但**无 Live2D 动画**（流萤无 live2d 字段） |
| `motion` / `emotion` WS 帧驱动 | 流萤无 `motion_map_json` / `emotion_map_json`（DB 实测空），motionMap fallback no-op | ✅ 不崩；无表情 / 动作变化 |
| 创建对话 + 发消息 | `character_switch` WS 帧把 `character_id=102` 推到后端 → 正常进入 ChatAgent | ✅ 应正常 |

⚠️ **真机验证项**：
- 流萤 102.png splash-art 上传链路是否走通（`untracked` 状态意味着可能是直接放进 `frontend/public/splash-art/` 目录而非走 `/api/characters/{id}/splash-art` POST，需要真机看上传后 DB 字段是否填）
- 在 `CharacterGallery` 中流萤卡片是否能被点击 + 进入 `CharacterDetailModal` 不崩
- 流萤切换后状态条 (`CharacterStatePanel`) 显示是否合理

---

## 第 4 节 · 现状结论 + 后续建议

### 4.1 整体健康度

前端整体**健康**：
- 栈现代（Tauri 2 + React 18 + Vite 6 + Zustand 5 + Tailwind 3）
- 0 TODO/FIXME、唯一 @deprecated 标记清晰
- WS 5 SEND + 13 RECV 帧契约与后端 `ws.py` 实测对齐
- REST 21 endpoint 全活，零接口差集
- 状态管理单 store（Zustand），全树用 `useAppStore` 统一访问
- 主要技术债集中在 3 个巨型文件（Legacy / CharacterPanel / CapabilityPanel）— 全部仍在用，**无死代码**

### 4.2 真 bug vs 文档漂移 vs 待真机验证

| 类型 | 项 |
|---|---|
| **真 bug**（影响用户） | 无明确发现 |
| **文档漂移**（描述/代码不齐） | DESIGN.md §F1 "Mai 单角色"措辞 与前端通用渲染 9 个角色现实有距离 |
| **隐性接口缺位**（后端能力前端无可视化） | observability / todos / clipboard / profile PATCH — 不阻塞用户但功能未完整暴露 |
| **待真机验证** | ① 流萤 (cid=102) 在 CharacterGallery / Live2D fallback / 状态条全路径是否健康 ② splash-art untracked → 实际落地路径 ③ 切角色 + 长时间空闲后 wake_call 投递路径在前端的呈现 ④ 主题切换 8 套 在 widget vs panel 双模式下的视觉一致性（顾问美学审查项） |

### 4.3 前端整理优先级建议（CC 给依据，人定）

| 梯队 | 项 | 理由 |
|---|---|---|
| **P0 立即** | 真机抽测流萤 cid=102 全路径 | 唯一 AUDIT 后新增角色，未经过真机验证；splash-art untracked 状态尤其需要确认 |
| **P0 立即** | profile PATCH 前端表单（如已规划 v4.x） | 后端能力齐全但用户无法手编自己档案，是用户感知的"缺口" |
| **P1 近期** | `SettingsPanelLegacy` 真清退 | 1953 行已 @deprecated；先把 `SettingsPanelV2` / `AIProvidersSection` import 的 wrapper 函数迁出 / 内联，再删整文件 |
| **P1 近期** | DESIGN.md §F1 "Mai 单角色"措辞对齐 | 与 BACKEND-OVERVIEW §3 L-1 同源；与 cid 命名梳理一并做 |
| **P1 近期** | `CharacterPanel.tsx` (1862 行) 拆分 | 立绘 / Live2D / TTS / persona variant 4 段拆 4 文件；不阻塞但减少认知负担 |
| **P2 backlog** | observability / todos / clipboard 前端可视化 | 后端能力存量，UI 接出后能多一层用户感知；不影响核心聊天 |
| **P2 backlog** | `CapabilityPanel` (911) / `ExtensionsSection` (900) 拆分 | 与 CharacterPanel 同源决策 |
| **P3 不做** | 切换主题 / Live2D fallback 视觉一致性 | 顾问美学审查项；改前需用户截图 |

### 4.4 必须靠真机 / 截图才能定的点

1. **流萤 cid=102** 在 CharacterGallery / Live2D fallback / 状态条 / 切换链路上的实际表现（代码判应 OK，但 untracked splash-art 是不确定源）
2. **切换主题 8 套** 在 widget vs panel 双模式下的视觉一致性（顾问美学审查）
3. **角色馆 (CharacterGallery)** v4-fan 重新设计后的实际观感（FanLayout / SplashArtDropzone / CharacterDetailModal 三件套是否流畅）
4. **wake_call / morning_briefing / activity proactive trigger** 在前端的 toast / 主动消息呈现（用户体验链）
5. **CharacterPanel 的 PersonaEditorModal** v4 多 variant 编辑流（保存 / restore_to_builtin / 切换 active variant 是否符合心智模型）

---

## 第 5 节 · 2026-05-19 全面校准

> 用户真机戳破多处 §3.2 / §3.1 误判后做的完整重核。
> **铁律**：本节每条 negative 论断（"无 X / 缺 X / 死代码 / 零差集"）都由 CC 亲自 grep + Read 真组件确证，零信任 agent 中间报告。

### 5.1 SystemStatusSection 数据流向核（用户重点关切）

#### 真实显示字段（前端 + 后端契约对齐）

`SettingsPanelLegacy.tsx:1154-1185+ SystemStatusSection` 显示 `SystemResources` interface 字段（`lib/observability.ts:51-63`）：

| 字段 | 类型 | 含义 |
|---|---|---|
| `has_psutil` | boolean | psutil 包是否装（无则降级显示） |
| `backend_rss_mb` | number\|null | backend 进程 RSS 内存（MB） |
| `backend_cpu_percent` | number\|null | backend 进程 CPU 占用率 |
| `system_total_ram_mb` | number\|null | 系统总内存 |
| `system_used_ram_mb` | number\|null | 系统已用内存 |
| `system_ram_percent` | number\|null | 系统 RAM 百分比 |
| `whisper_loaded` | boolean | Whisper ASR 模型是否预加载 |
| `whisper_size` | string\|null | Whisper 模型尺寸（small / medium / large） |
| `whisper_disk_mb` | number\|null | Whisper 磁盘占用（MB） |
| `net_recv_kbps` | number\|null | 网络下行速率 |
| `net_sent_kbps` | number\|null | 网络上行速率 |

数据流：前端 3 秒一次 `fetchSystemResources()` → `GET /api/observability/system/resources`（`observability_api.py:112-116`）→ `backend/observability/system.py:collect()` → psutil 实时采集 → 返 dict → 前端 `<SystemStatusSection />` 渲染。

#### A/B 通路核 — 仅前端面板，**不进 LLM**

| 通路 | 状态 | 证据 |
|---|---|---|
| **A 通路**：前端 SettingsPanel 系统状态面板 | ✅ 活 | 见上 |
| **B 通路**：进 LLM system prompt | ❌ **不进** | grep `fetchSystemResources / backend_rss / whisper_loaded / net_recv_kbps / system_ram_percent` 在 `backend/`（除 `observability_api.py` 与 `observability/system.py` 自身）= **零命中** |

**`system_parts.append` 全注入源清单**（`chat.py` LLM system prompt 构造点 grep）：

```
chat.py:1142,1387  format_profile_for_prompt(profile_data)        ← 用户画像 (chunk 11)
chat.py:1155,1398  format_today_activity_for_prompt(user_id)      ← 活动时间线 (chunk 14)
chat.py:1416       "【相关长期记忆】\n" + mems                       ← long-term memory recall
chat.py:1420       "【工具调用结果】\n" + tool_result                 ← tool result
chat.py:1424       "【临时指令】\n" + extra_system                    ← touch event inject
chat.py:1453       "【proactive 简报】\n" + stage2_addendum          ← proactive briefing
```

→ **6 个注入源都不含 SystemResources**。

**结论 ① 仅前端面板，不进 LLM**。证据：grep 全代码库 SystemResources 字段（backend_rss_mb / whisper_loaded 等）在 `format_*_for_prompt` / `system_parts` 路径上**零命中**。

#### 主动感知 / 活动感知与 SystemStatus 同源吗？

| 维度 | Activity Timeline | SystemStatus |
|---|---|---|
| 数据源 | macOS 前台 app + 浏览器 URL/title（`activity_watcher` + `activity_monitor`） | 系统 psutil + Whisper 加载态 + 网络 |
| 存储 | `activity_sessions` 表（chunk 14） | 实时 collect 不存表 |
| 喂 LLM 字段 | `app_name / browser_url / browser_title / duration_seconds / start_at`（`format_today_activity_for_prompt`，`activity_timeline.py:384-473`） | **无**（仅前端面板可视化） |
| LLM 注入文本例 | "今天已活跃 7小时30分钟。主要花在: Visual Studio Code 3小时, Google Chrome 2小时…" | — |
| 用户隐私模型 | 5 道隐私闸（活动 blacklist / URL pattern 拒），30 天保留 | 不存储，仅快照 |

→ **两套完全不同源**。Activity Timeline 给 LLM 提供"用户在干什么"的上下文（主动陪伴根据这个 chime in），SystemStatus 仅给用户看"机器跑得怎么样"。

### 5.2 §3.2 修正表（与 INVESTIGATION 一致）

| # | §3.2 原判 | 实际证据 | 修正结果 |
|---|---|---|---|
| A | clipboard 无直 UI | `SettingsPanelLegacy.tsx:604-765 ClipboardSection` 160+ 行 UI，V2 真渲染 | **判错 → §3.2 已重写** |
| B | observability 无可视化 UI | `SystemStatusSection`（系统监控） + `AIProvidersSection.tsx:1255 fetchTtsUsage` | **判错 → §3.2 已重写**；漏盘 SystemStatusSection 整块 |
| C | todos 前端无 UI | 无写入 UI ✓；有 RECV-only alarm 通知（dead branch） | **半对 → §3.2 改 dead branch 说明** |
| D | profile PATCH 无表单 | `UserProfileSection.tsx` 510 行完整 UI 走 `/profile_data` | **判错（已自纠）→ §3.2 删该误判行** |
| E | briefing/test 前端无调用 | `lib/integrations.ts:58 fetch /api/briefing/test?mode=...` 真调用 | **判错（INVESTIGATION 此前也判错）→ §3.2 已重写** |

5 条全部判错（含 1 半对）。

### 5.3 §1 / §2 / §3.1 / §3.3 抽查表

| # | 章节 | 论断 | 实际证据 | 结果 |
|---|---|---|---|---|
| 1 | §3.1 | `TODO/FIXME/HACK 0 命中` | `grep -rnE "TODO\|FIXME\|XXX\|HACK" frontend/src/` = 0 行 | ✅ 对 |
| 2 | §3.1 | `@deprecated` 仅 `SettingsPanelLegacy.tsx:1659` 一处 | grep 全库 = 2 命中（同文件 L1655 + L1659，同一段注释） | ✅ 对 |
| 3 | §3.1 | `MemoryViewer.tsx (24 行)` 极小，"需核是否还活" | grep `MemoryViewer` 外部 = **0 import / 0 `<MemoryViewer />`** → **实测死代码** | ❌ 原"需核" → 改 "实测死代码 可删" |
| 4 | §3.1 | `VoiceButton.tsx (21 行)` 极小，"需核" | grep `VoiceButton` 外部 = **0 import / 0 `<VoiceButton />`** → **实测死代码** | ❌ 原"需核" → 改 "实测死代码 可删" |
| 5 | §3.1 | `ConnectionDot.tsx (22 行)` 极小，"需核" | `ControlBar.tsx:4,121` + `Sidebar.tsx:9,80` 真消费 | ✅ 活 |
| 6 | §2.3 | "REST 21+ endpoint 全活，零接口差集" | 前端 fetch `/api/*` 实测 35+ 唯一路径（含 activity 3 / briefing 1 / clipboard 4 / integrations.google 3 / mcp 4 / observability 3 / etc.）；每个在 `backend/routes/` 都有对应 router | ✅ 对（21 是 router 数，35 是 endpoint 调用数，原描述粒度对齐） |
| 7 | §2.3 router 数 | "20 router" | `grep -c "include_router" backend/main.py` = 20 | ✅ 对 |
| 8 | §3.2 | `switch_character` LLM tool 已下线 | `grep "ToolRegistry.register.*switch_character" backend/` = 0；prompts.py 中也已清 | ✅ 对（与 commit `71b6e99` 一致） |
| 9 | §3.3 | "M-6 PASS：ChatHistoryDrawer / CharacterDialogueBubble 文件已删" | `find` = 0；grep 命中仅注释 | ✅ 对 |
| 10 | §3.5 cid=102 | "代码层应正常显示" | 已是"应正常"判断 + 留真机验证项标注 | ✅ 措辞合理（未实证不可强判） |

**抽查结果**：10 条中 7 ✓ / 2 ❌（§3.1 MemoryViewer + VoiceButton 应该是死代码而非"需核"）/ 1 措辞合理。

✅ **§3.2 / §3.1 修正已 in-place 完成**。

### 5.4 失误教训沉淀

| # | 失误模式 | 改进 |
|---|---|---|
| 1 | 整段抄 agent 报告未自验 | 任何 negative claim（"无 X / 缺 X"）必须亲自 grep + Read 真组件 |
| 2 | `@deprecated` 整文件标记误推为"内部 section 都死" | `@deprecated` 看 wrapper 是否被其它真活组件 import + 渲染再判 |
| 3 | UI 嵌在 SettingsPanel 大文件内部不是独立组件 → 简单 `find` 命名找不到 | grep 业务关键词（"剪贴板" / "clipboard" / "observability"）+ 翻 SettingsPanelLegacy.tsx |
| 4 | 一次自纠（profile）后未连带重审整表 | 任一条修正触发整张表重新核（防系统性偏差） |
| 5 | §3.1 "需核" 留作待办从未补做 | "需核" 类标注必须在本刀内核完，不留外推 |

### 5.5 校准后未办

- ⏸ MemoryViewer.tsx / VoiceButton.tsx 死代码清理（独立小刀）
- ⏸ 前端 WS RECV `alarm` 分支 + `store.AppNotification.todoId` 字段（todos 退役后 dead branch，无害但可清）
- ⏸ FRONTEND-OVERVIEW.md 写于 HEAD=3d76982，5.x 校准在 HEAD=c1d65ff 之后；§3.2 中"已下线"对 c1d65ff 退役 todos 也对齐

### 5.6 本会话新成果（2026-05-19 docs 第二刀补录）

| Item | 文件改动 | 状态 |
|---|---|---|
| 左侧 `ConversationList` 右边缘可拖拽 resize handle | `store/index.ts` +43 行（`conversationListWidth` state + setter + clamp + localStorage） / `ConversationList.tsx` +5 -2 行（width 改 inline style） / `Panel.tsx` +95 行（pointer handlers + handle JSX） | 已实现，真机验证通过，**未 commit** |
| 右侧 `ChatHistoryPanel` 左边缘可拖拽 resize handle | `store/index.ts` +45 行（`chatHistoryWidth` state + setter；同模式镜像）/ `ChatHistoryPanel.tsx` +5 -2 行 / `Panel.tsx` +80 行（dx 取反 + 镜像 handle） | 已实现，真机验证通过，**未 commit** |
| 立绘区自动响应 | `Panel.tsx:76` `flex-1 min-w-0` 容器 + Live2D runtime `pixiCubism4.ts:234-241` ResizeObserver 真活 | 无需 canvas 改动；左右双 handle 同时拖立绘区被动吸收，互不冲突 |
| 新增 localStorage keys | `momoos.convListWidth`(clamp [160,400], default 240) / `momoos.chatHistoryWidth`(clamp [320,600], default 420) | 见 §1.5 |
| docs 归档第一刀 | 15 tracked（含 `DESIGN.md` / 多 audit_*）走 `git mv` R100 + 4 untracked 走普通 mv，全部移到 `docs/archive/` | **未 commit** |
| FRONTEND-OVERVIEW 配套修订 | §3.2 5 条 negative 论断校准 + §1.4 `VoiceButton/MemoryViewer` 矛盾统一 + §1.5 新 keys + §1.2 resize handle 标注 + 边界锚定更新 | 本刀（docs 第二刀） |

---

## 边界声明

- 本文件**只读勘查 + 文档校准**：未改任何代码 / DB / migration / commit / stash / push / 前端构建 / backend 启动
- 基线锚定在 HEAD = `3d76982`（§1-§4 原写）/ HEAD = `c1d65ff`（§5 校准 + 本刀文档对齐）
- 前端组件代码逐文件 grep + 关键文件 Read 实证
- 任何"建议方向"是依据给定不替决，最终拍板由人
