# Bugfix-2 Audit — Setting 拆 "能力" + "设置"

## 1. 入口现状

* **Sidebar.tsx** (w-16 左侧 stripe)：3 个 icon 按钮
  - 💬 chat → `panelView='chat'`
  - 👥 characters → `panelView='characters'` → `<CharacterPanel/>`(角色管理含编辑器 + Live2D dropzone)
  - ⚙ settings → `panelView='settings'` → `<SettingsPanel/>`(一切其他)
* **store**：`panelView: 'chat' | 'settings' | 'characters'`，setter 同名
* **TopBar** 没设置入口，只有窗口控制 + Gallery overlay 入口

## 2. SettingsPanel 现有 16 个 section（顺序自上而下）

| # | Section                       | 内容                                       | 拟挪入       |
|---|-------------------------------|--------------------------------------------|--------------|
| 1 | ThemeSection                  | 8 个 UI 风格主题选择                       | ⚙ 设置 → 外观 |
| 2 | ModelSection                  | AI 模型 (qwen/deepseek 等) 切换            | 📂 能力 → AI Providers |
| 3 | CapabilityPanel               | 能力总览（v3-G chunk 0 嵌入）              | 📂 能力 → MCP/AI 总览（暂留 SettingsPanel 不挪以免 chunk 0 回归） |
| 4 | Memory toggles                | 长期记忆 / 用户画像 / 联网搜索             | ⚙ 设置 → 隐私 / 数据 |
| 5 | ProactiveSection              | 主动陪伴（wake_call / morning_briefing）   | ⚙ 设置 → 主动陪伴 |
| 6 | ClipboardSection              | 剪贴板捕获 + 最近 5 条                     | ⚙ 设置 → 隐私 / 数据 |
| 7 | ExtensionsSection             | MCP 服务器                                 | 📂 能力 → MCP Servers |
| 8 | ActivityAwarenessSection      | 活动感知开关 + 黑名单                      | ⚙ 设置 → 隐私 / 数据 |
| 9 | ActivityTimelineSection       | 活动 timeline drawer 入口                  | ⚙ 设置 → 隐私 / 数据 |
| 10 | CharacterStateSection        | 状态条显隐 + 重置亲密度                    | ⚙ 设置 → 角色管理 |
| 11 | ASR/VAD                      | 录音模式 / VAD 阈值 / 静音超时             | ⚙ 设置 → 系统 |
| 12 | TTS                          | 启用 TTS                                   | ⚙ 设置 → 系统 |
| 13 | 启动                          | splash 视频 toggle                         | ⚙ 设置 → 系统 |
| 14 | MemorySection                | 记忆条数 + 管理 drawer                     | ⚙ 设置 → 隐私 / 数据 |
| 15 | ProfileSection               | 称呼 + 语言                                | ⚙ 设置 → 关于（基础信息）|
| 16 | UserProfileSection           | profile_summary 重生 / 编辑                | ⚙ 设置 → 隐私 / 数据 |

## 3. 角色管理 & Live2D 现状

* **CharacterPanel.tsx**(`panelView='characters'`)：完整角色编辑器，**已含** Live2D
  dropzone（`<Live2DDropzone />`）+ 模型 dropdown(每角色独立 live2d_model 字段)。
  没有 app-level "Live2D 模型库" 视图 —— 模型扫描 (`fetchLive2DModels`) 仅供
  dropdown 数据。
* **本 stage 处理**：⚙ 设置 → 角色管理 子节渲染整个 `<CharacterPanel/>`；
  📂 能力 → Live2D Models 子节单独提供 "模型库列表 + 上传" 视图（用
  `fetchLive2DModels` + `<Live2DDropzone />`，与 CharacterPanel 数据 backend
  共享，不冲突）。

## 4. 拆分规划

### 📂 能力 (Capabilities)
- 🔌 MCP Servers → 渲染现有 `<ExtensionsSection />`(原 section 7)
- 🎭 Live2D Models → 新视图：`fetchLive2DModels` 列表 + 上传按钮唤起
  `<Live2DDropzone />`
- 🧠 AI Providers → 占位 "即将推出 (Bugfix-3)"（task 明确说本 stage 空）
- 🧩 Skills (.py) → 占位 "即将推出 v4.1+"

### ⚙ 设置 (Settings V2)
- 👥 角色管理 → 渲染现有 `<CharacterPanel />`(原 panelView='characters'
  组件)；含 splash art 上传 + Live2D dropdown
- ✨ 主动陪伴 → 复用 `ProactiveSection`（从 SettingsPanel.tsx export）
- 🎨 外观 → 复用 `ThemeSection`（从 SettingsPanel.tsx export）
- ⌨ 系统 → 占位 "暂未启用"（ASR/VAD / TTS / 启动 等仍在老 SettingsPanel）
- 🔒 隐私 / 数据 → 占位 "暂未启用"（Memory / Activity / Clipboard 等仍
  在老 SettingsPanel）
- ℹ 关于 → 简版（app name + 当前 LLM model + GitHub）

## 5. 老入口处理（选项 A：新老共存）

老 `<SettingsPanel />` 不动，沿用 `panelView='settings'`。新 Sidebar 增加:
- 📂 能力 → `panelView='capabilities'` → `<CapabilitiesPanel />`
- ⚙ 设置 → 新 view `panelView='settings_v2'` → `<SettingsPanelV2 />`
- 原 ⚙ Settings 改 label "高级"/icon `Wrench`，仍指向 `<SettingsPanel />`，
  让用户可回退访问没挪过来的 section（ASR/VAD / TTS / Memory 等）。Bugfix-4
  后再决定是否删。

## 6. 风险 / 决策

- **CapabilityPanel** (section 3) 留在老 SettingsPanel 不挪：v3-G chunk 0
  spec 明文该组件是 "能力总览"；目前 V2 已经按子导航分类，CapabilityPanel
  那张总览表语义重复，留老处不动，避免 chunk 0 回归。
- **不破坏 CharacterPanel**：⚙ 设置 → 角色管理只是 mount 同一个组件实例，
  内部所有 callback / state 都不动。回归面积≈0。
- **bundle 增量**：新 panel 两个组件，每个 ~150 行，预计 < 5 KB gzip。
- **可访问性回退**：老 SettingsPanel 1700+ 行不删，user 真机出问题可立即
  点 "高级" icon 回到完整面板。
