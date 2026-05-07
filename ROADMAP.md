# 🗺️ Skyler Roadmap

> Living document. 每完成一个里程碑同步更新 + commit + push。
>
> 当前状态（2026-05-06）：v2.7 完整 + v3-A/B/C/D + **v3-E1 (8 commit) + v3-E2 多模型 (9 commit) + v3-G' TTS UI + instruct emotion (5 commit + 2 patch) 完成**（约 v3 整体 90%）。Hiyori / 八重神子 Live2D 端到端正常；TTS provider/voice 两级下拉 + 7 个 cosyvoice 音色（含 instruct-aware 男声 longanyang）+ emotion 真生效（instruction 格式严格匹配文档）。剩 v3-F' 主动对话 / v3-G 成长系统。

---

## 当前进度速览

| 阶段 | 状态 | 完成度 |
|---|---|---|
| v1 后端核心 | ✅ 完成 | 100% |
| v2 前端 + Tauri | ✅ 完成 | 100% |
| v2.5-A 性能 / B Schema 迁移 / C ChatGPT 模式 / D 多角色 / E 启动模式 | ✅ 完成 | 100% |
| v2.6 / v2.7（Settings 同步 + 记忆系统重构） | ✅ 完成 | 100% |
| **v3-A：8 套主题 + lucide-react** | ✅ 完成 | 100%（超 DESIGN 范围 4→8 套） |
| **v3-B：character.voice_model + CosyVoice** | ✅ 完成（schema 已支持多 provider） | 100% |
| **v3-C：PlannerAgent 简化** | ✅ 完成 | 100% |
| **v3-D：emotion 后端解析 + TTS 联动** | ✅ 完成（前端数据流 v3-E1 step5 接入；视觉绑定 v3-E3） | 100% |
| **v3-E1：Live2D 接入（用 Hiyori 走通流程）** | ✅ 主线完成（8 commit） | 95%（Step Z cleanup 4 条剩余） |
| **v3-E2：多模型 Live2D 接入（runtime 抽象层 + per-character maps）** | ✅ 完成（9 commit，2026-05-06）| 95%（IP license / 加藤惠 Cubism 4 重制版 / hit-area 路由 backlog 不阻塞）|
| **v3-E3：emotion 视觉绑定真上线** | 🚧 代码路径已接通，等有 `.exp3.json` 的模型 | 90%（运营任务）|
| v3-F：语音体验飞跃（打断 ✅ / 并发 ✅ / 预处理 ✅ / 内心独白 ✅） | ✅ 完成 | 100% |
| **v3-F'：主动对话 + 时间感知（饭点 / 睡前 / 长时无互动）** | 📋 计划中 | 0% |
| v3-G：生活 & 工具型能力（剪贴板 / 简报 / cron / 成长系统） | 📋 计划中 | 0% |
| **v3-G'：TTS UI 升级 + cosyvoice emotion 走 instruct（chunk 1a SSML 路径已撤回）** | ✅ 完成（5 commit + 2 patch，2026-05-06）；Phase 2 复刻音色 / SoVITS 训练 📋 PENDING | Phase 1 100% |
| **v3-H：媒体接入（网易云内置 / 媒体控制 / B站）** | 🚧 chunk 1 🟡 PARTIAL（数据查询 + 媒体控制可用；NCM 自动播放封存待 chunk 2 重做，2026-05-08）；B 站 📋 TODO | 50% |
| v4：屏幕感知 + 视觉能力 | 📋 远期 | 0% |
| **v5-D：autodl 部署 + 子 agent 隔离** | 📋 远期 | 0% |
| **v5-T1：GPT-SoVITS 后端接通（依赖 v5-D）** | 📋 远期 | 0% |
| **v5-T2：训练自定义 voice（CosyVoice fine-tune + SoVITS 模型）** | 📋 远期 | 0% |
| v6+：多设备访问 + Hermes 风格 skill 累积 | 📋 长期愿景 | 0% |

---

## 三梯队优先级矩阵

### 🟢 第 1 梯队：v3 内可完成（1-3 周）

| 任务 | 子阶段 | 价值 | 成本 | 依赖 |
|---|---|---|---|---|
| **Live2D 集成（用 Hiyori 走通）** | v3-E1 | 极高（v3 灵魂） | 中-高 | 下载 Hiyori |
| emotion → 前端 → Live2D 表情切换 | v3-E1 | 高 | 低（已 50%） | Live2D 接入 |
| Live2D 触摸响应（OLV #6） | v3-E1 | 中 | 低 | Live2D 接入 |
| motionMap（OLV #8，emotion 扩展） | v3-E1 | 中-高 | 中 | emotion 系统 |
| **换上目标模型（资产替换不动代码）** | v3-E2 | 高 | 低-中 | E1 完成 + 找模型 |
| 语音打断（OLV #1） | v3-F | 高（体验关键） | 中 | 无 |
| TTS 多段并发（OLV #2） | v3-F | 高（首句延迟） | 中 | 无 |
| TTS 预处理器（OLV #3） | v3-F | 中 | 极低 | 无 |
| AI 内心独白 `<thinking>`（OLV #5） | v3-F | 中-高 | 低-中 | 无 |
| **TTS 配置 UI 升级（per-character 两级下拉）** | v3-G' | 中（重要 UX 修） | 低 | 无 |

第 1 梯队全部完成后 → v3 真正完整 + Live2D 真正活起来 + TTS UI 不再是裸 JSON。

### 🟡 第 2 梯队：v4 工具层 + 屏幕（1-2 个月）

| 任务 | 子阶段 | 价值 | 成本 | 依赖 |
|---|---|---|---|---|
| 剪贴板助手 | v3-G | 中-高（独特） | 低-中 | Tauri clipboard API |
| 每日简报 | v3-G | 高（陪伴感） | 中 | 现有 ConnectionManager |
| 自然语言 cron 调度（Hermes #3） | v3-G | 高 | 中 | 现有 scheduler |
| 智能提醒 | v3-G | 中 | 中 | profile_summary |
| 角色状态面板 + 成长系统 | v3-G | 高（陪伴感） | 中 | 新表 + 前端组件 |
| 屏幕感知主动模式 | v4 | 极高（独特） | 高 | VLM provider 抽象 |
| 屏幕感知被动模式 | v4 | 高 | 高 | 主动模式 |
| AI 用自己的浏览器（OLV #4） | v4 | 中 | 高 | 内嵌 webview |
| MCP 协议真正接入 | v4 | 中 | 中 | 现有 ToolRegistry 抽象 |

### 🟠 第 3 梯队：架构改造（v5 / v6+，长期）

| 任务 | 子阶段 | 价值 | 成本 | 依赖 |
|---|---|---|---|---|
| **autodl 部署 + SSH tunnel** | v5-D | 高 | 高 | 无 |
| 子 agent 隔离（Hermes #4） | v5-D | 中 | 高 | autodl 部署 |
| **GPT-SoVITS 后端接通（SoVITSProvider 真实现）** | v5-T1 | 中-高 | 高 | v5-D autodl + GPU |
| **训练 CosyVoice fine-tune voice** | v5-T2 | 高（角色独特音色） | 中-高 | DashScope 流程 |
| **训练 GPT-SoVITS 专属 model** | v5-T2 | 高（深度定制） | 高（GPU 训练时间） | v5-T1 + 角色音频 |
| **Windows 客户端** | v6 | 高（你明说要的） | **极高** | 见 §跨平台代价 |
| 用户认证 + WS 鉴权 + TLS | v6 | 必要 | 中-高 | 多设备前置 |
| Postgres 迁移 | v6 | 必要 | 中-高 | 多设备前置 |
| Hermes 风格 skill 累积系统 | v6+ | 高 | **极高** | 长期愿景 |
| 移动端 | v6+ | 中 | 高 | 多设备完成 |

---

## 详细执行清单

### v3-E1：Live2D 接入（用 Hiyori 走通流程）✅ 主线完成

**核心思路**：用 Live2D 官方免费样本 **Hiyori** 当首发模型，不是因为它是最终目标，而是**先把整个 Live2D + 前后端管道打通**。一旦跑通，换模型只是资产替换（v3-E2）。

**为什么用 Hiyori**：
- Live2D Inc. 官方免费样本，无需购买
- Cubism 4 兼容模型（moc3 ver ≤ 4），参数 ID 标准化（ParamMouthOpenY 等）
- 各种 motion 已就绪（无 .exp3.json，emotion 视觉绑定 deferred 到 v3-E3）
- ⚠️ 许可：Live2D Free Material License Agreement，**开发期 OK，商用要看条款**

**下载**：从 [Live2D 官方 Sample Data 页面](https://www.live2d.com/zh-CHS/learn/sample/)拿 Cubism Sample Data，里面有 Hiyori 的 .moc3 / .model3.json / motion 全套。放到 `frontend/public/live2d/hiyori/`。

> ⚠️ **关键约束**：pixi-live2d-display 及其所有 fork（advanced / lipsyncpatch / mulmotion）只支持 Cubism 4 Core，**不支持 Cubism 5**（GitHub issue #118 自 2023-10 未修复）。Hiyori 是 Cubism 4 格式（moc3 ver 3），兼容。v3-E2 选购模型时必须确认 moc3 ver ≤ 4。

**主线完成清单（8 commit）**：

| Step | Commit | 内容 |
|---|---|---|
| ✅ Step 1 | `0eed29a` | scaffold + assets + DB column（characters.live2d_model）|
| ✅ Step 2 | `06b5829` | CharacterView Live2D 渲染（PIXI canvas + Galgame 满铺 + idle / focus / breath）|
| ✅ Step 3 | `861bce2` | 触摸点击 → Tap motion + AI 主动回复（特殊 turn 注入）|
| ✅ Step 4 | `e7bc013` | 口型同步（共享 AudioContext analyser → ParamMouthOpenY）+ 多段 TTS 顺序播放修复 |
| ✅ Step Z.1 | `be0c6f4` | `<thinking>` 标签持久化 + 渲染剥离（v3-F 回归修复）|
| ✅ Step 5 | `dce6d23` | emotion 数据流（后端 push → store → 监听点；视觉绑定 deferred to v3-E3）|
| ✅ 角色修复 | `ba2efd2` | DB persona 主源 + YAML fallback（修复 UI 切角色 system prompt 不变 bug）|
| ✅ Step 6 | `c6f5d3f` | motionMap 端到端（LLM `<motion>` → Hiyori 4 个 Flick* group 真动作；语义实测对齐）|

**Hiyori motion 资源真实分配（Step 6 实测后确定）**：

| Group | 索引 | 用途 | 真实动作语义 |
|---|---|---|---|
| Idle | m01/m02/m05 | 自动 idle 循环 | - |
| Tap | m07/m08 | Step 3 触摸点击 | 触摸响应 |
| Tap@Body | m09 | 保留扩展点 | "摸身体" 语义未启用 |
| Flick | m03 | Step 6 LLM 驱动 | 放松甩手（慵懒 / 随意）|
| FlickDown | m04 | Step 6 LLM 驱动 | 双手别身后（害羞 / 收敛）|
| FlickUp | m06 | Step 6 LLM 驱动 | 小臂举起晃（加油 / 应援）|
| Flick@Body | m10 | Step 6 LLM 驱动 | 复合动作 + 表情（撒娇 / 俏皮）|

⚠️ **Hiyori 没有"挥手 / 点头 / 鞠躬 / 打招呼"等具体语义动作**。Step 6 已在 `_build_motion_instruction` 显式告诉 LLM 哪些词不可用，避免 LLM 惯性输出后被 motionMap miss。换模型时整体重写 motionMap。

**实际耗时**：~5 天（Step 1-4 + Step 5-6 + 角色修复 + Step Z.1 回归 + 动作语义实测对齐）。

#### v3-E1 Step Z cleanup（剩余 4 条，进入 v3-E2 之前统一处理）🚧

1. **`[touch]` 污染 profile_summary**
   - chat_history 加 `kind` 字段（`'normal' | 'touch' | 'proactive'`）
   - profile rewrite 过滤 `kind != 'normal'` 的行
   - 对话历史抽屉 special turn 显示成"（碰了一下）"灰字
   - 同时为 v3-F' 主动对话的 `kind='proactive'` 铺路（同设计）
   - **预计**：半天

2. **cosyvoice EMOTION_MAP 注释 / 行为不一致**
   - `backend/tts/cosyvoice.py:31-51` 注释说 miss → neutral，代码实际透传
   - 改注释或改代码二选一（v3-G' 改走 instruct 路径不再用 SSML，本条独立处理即可）
   - **预计**：5 分钟

3. **Hiyori idle motion m01/m05 fetch Aborted**
   - 现象：Hiyori 模型加载时 idle motion m01/m05 fetch 被 Aborted
   - 嫌疑：React 18 StrictMode 双 mount 的 race（cancelled flag + AbortController 时序）
   - 需 audit 是否真的影响 idle 行为，可能只是 cosmetic warning
   - **预计**：audit 半小时，修法看具体情况

4. **chat_history 历史 `<thinking>` 脏数据 SQL 清洗（可选）**
   - DB 里 `be0c6f4` 修复前的旧 assistant 消息 content 仍含 `<thinking>` 标签
   - 前端 textFilters 已防御性剥，但 DB 里仍是脏的
   - 可写一次性 SQL UPDATE（或 Python `re.sub` 脚本）清掉
   - **预计**：10 分钟（如果做）

---

### v3-E2：多模型 Live2D 接入 ✅ 完成（2026-05-06）

任务：让 Skyler 支持多个 Live2D 模型，不只是临时的 Hiyori。E1 跑通后，换模型主要是**资产替换 + per-character 配置升级**，但 v3-E1 当前的全局共享 motionMap / emotionMap 必须先升级为 per-character。

**主线完成清单**：

- [x] **moc3 ver ≤ 4 校验脚本** —— `tools/check_moc3_version.py`（`1831836`，扫 .moc3 + Cubism 2 .moc 都走 magic 校验）
- [x] **资产路径规范化 + IP 隔离 .gitignore + 资产管理文档** —— `frontend/public/live2d/` 标准目录 + `frontend/public/live2d/README.md`（`661d428`，commit 2 of v3-E2）
- [x] **`GET /api/live2d/models` 扫描 API + CharacterPanel 下拉** —— 后端 `daaae81` + 前端 `c723ec8`（commit 3a + 3b of v3-E2）
- [x] **per-character `*_map_json` 字段（DB 迁移 + ORM + Pydantic + 前端类型）** —— `0397b72`（commit 4 of v3-E2）
- [x] **`Live2DRuntime` 抽象层 + `PixiCubism4Runtime` + `RuntimeRegistry`** —— `daf7b3a`（commit 5 of v3-E2）
- [x] **`Live2DCanvas` 重写：runtime 接口调用 + `resolveCharacterMaps` fallback** —— `9ba5b72`
- [x] **八重神子 (id=2) 接入 BCSZ1.1 + maps 数据迁移** —— `5cab58a`（commit 6 of v3-E2）
- [x] **emotion 视觉绑定接通（`runtime.setExpression`）** —— `950710e`（chunk 5 偏离 6 收口）
- [x] **Momo (id=1) persona 还原成 ChatAgent 原文** —— `d01f3b4`

**v3-E2 commit 范围**：`1831836` (moc3 checker) → 主线 `d01f3b4` (Momo restore) + 收尾 patch 链。

**收尾 patch 历史**：

| Hash | 内容 |
|---|---|
| `1a16953` | scanner symlink 兼容（`Path.resolve()` → `.absolute()`，让 `ln -s` 进 slug 不炸 relative_to）|
| `f021899` | `resolveLive2dModelUrl` 走 scanner store 主源 + hardcode 仅兜底 + App.tsx eager-load（修 "unknown model name: yae" 切八重显示静态图）|
| `0cd4fa5` | document.mouseleave / window.blur 把 gaze focus 拉回中央（修鼠标拖出 Tauri 视线卡住）|
| `<本次>` | 全局禁用 motion-bundled sound（修 BCSZ1.1 motion3.json 自带 wav 与 TTS 重叠）|

**Backlog（不阻塞 v3-E2 关闭）**：

- [ ] **模型 license 风险评估** —— 八重神子 / 加藤惠 = 米哈游 IP；当前 `frontend/public/live2d/yae/` 走 .gitignore 隔离不入库，**公开发布前必须清掉或换自制 / 已授权资产**
- [ ] **加藤惠 Cubism 4 重制版搜寻** —— 现有加藤惠资产是 Cubism 2（`.moc` 不是 `.moc3`），完全不兼容 pixi-live2d-display。要么找重制版，要么放弃这套资产
- [ ] **hit-area 路由真接通** —— 八重 8 个 HitAreas 已经在 `hit_area_map_json` 写好契约，但 `Live2DCanvas` 当前 click 仍走整体 canvas（`autoHitTest=false`）。接通需要改 `handleTouch` 拿到 PIXI 局部坐标 → `runtime.hitTest()` → 查 hitAreaMap → 派发对应 motion group
- [ ] **资产分发方案** —— git 入库（不可，IP 风险）vs git-lfs vs release tag 分发；自制 Momo 模型完成后要决定怎么 ship
- [ ] **角色装饰显隐 (parts opacity toggle)** —— 八重等模型有可显隐部件（头饰 / 装饰 / 服装层），通过 `model.internalModel.coreModel.setPartOpacity()` 控制。实施需要：`characters.customizable_parts_json` 字段 + 后端从 `.cdi3.json` 列出 parts 的 API + CharacterPanel toggle UI + Live2DCanvas 同步 state。估 1–1.5 天独立 chunk
- [ ] **Motion-bundled sound per-character toggle** —— 当前 v3-E2 patch 全局禁用 motion-bundled sound 避免与 TTS 重叠。未来按调用路径区分：鼠标点击触发 → 播 motion wav（保八重原声）/ LLM 标签触发 → 不播（让 TTS 独占）。需要 `Live2DRuntime.startMotion` 接口加 `playSound?: boolean` 参数 + 区分 `Live2DCanvas.handleTouch` vs `currentMotion` useEffect 调用路径

---

### v3-E3：emotion 视觉绑定真上线

⚠️ chunk 7 已经在 `Live2DCanvas` emotion useEffect 接通了 `runtime.setExpression(handle, name)`，**视觉绑定的代码路径全部就绪**。剩下的纯粹是"找一个有 `.exp3.json` 的模型 + 填该角色 `emotion_map_json`" 的运营工作，不再是技术任务。

**剩余清单**：

- [ ] **找 / 接入 / 自制有 `.exp3.json` 的目标模型** —— Hiyori / 八重 (BCSZ1.1) 都没自带 expression 文件
- [ ] **填该角色 `emotion_map_json`** —— `Record<string, string>`，emotion 词 → expression 名（CharacterPanel 编辑或直接 SQL UPDATE）
- [ ] **美术调参** —— 试每个 emotion（happy / sad / angry / surprised），不自然时换 expression / 调参数权重
- [ ] **验收**：跟角色说不同情感的话，面部有可见变化

`Live2DRuntime.setExpression` 选项 a（model.expression）已实现；选项 b（参数偏移）需扩 runtime 接口加 `setParameter(id, value)`，未来需要时再加。

**估时**：1 天（有 `.exp3.json`）/ 2-3 天（自制偏移）。

---

### v3-F：语音体验飞跃

**1. 语音打断**（最高优先级，体验飞跃明显）

实施：
- 前端 useAudio VAD 检测到用户说话 → 立即调 `useWebSocket` 发送 `{"type": "interrupt"}`
- 后端 ws.py 收到 interrupt → 取消当前 ChatAgent stream task（`asyncio.CancelledError`）+ 不再 yield 新的 text_chunk / audio_chunk
- 前端收到 done 或检测到 stream 取消 → 立即停止 audio playback queue + finishChatMessage（标记 streaming=false）
- chat_history 保存已生成部分 + 加标记字段 `interrupted_at`（可选）
- store `status: 'interrupted'` 状态已就绪，差最后接通 UI 反馈

**2. TTS 多段并发**

当前：`for sentence in sentences: chunk = await synthesize(sentence)` —— 串行，第 N 句要等前 N-1 句合成完
改为：用 `asyncio.gather` 或 producer/consumer queue 并发合成多句，但发送给前端时按顺序发（前端按顺序播）
注意：emotion 需要按"整轮一致"约束，不能并发改 emotion

**3. TTS 预处理器**

正则剥离不读的内容：
- `\*[^*]+\*` 动作描述
- `\([^)]+\)` 注释
- `\[[^\]]+\]` 标记
- `<thinking>...</thinking>` 内心独白（这个由 `<thinking>` 标签解析路径走，但 TTS 也要双保险）

实施位置：`backend/tts/__init__.py` 在 `synthesize` 调用前预处理一遍

**4. AI 内心独白 `<thinking>`**

参考 emotion 系统的实现模式：
- chat.py 加 `_THINKING_RE` 和 `_parse_thinking()`
- `_build_thinking_instruction()` 提示 LLM 可选输出 `<thinking>X</thinking>`
- ws.py 解析后 push `{"type": "thinking", "value": X}` 给前端
- 前端 store 加 `currentThinking` + UI 显示在角色状态面板（与 v3-G 联动）或独立 thoughts 抽屉
- TTS 预处理器要剥离不读

---

### v3-F'：主动对话 + 时间感知

让 Momo 不只是被动回应，而是主动开启对话（饭点 / 睡前 / 长时间无互动等情境）。

**清单**：

- [ ] 后端定时调度器（cron / scheduler，复用 v3-G 自然语言 cron 基础设施）
- [ ] 触发场景：午饭 / 晚饭点 / 睡前 / 长时间无互动 / 用户日历事件前
- [ ] LLM 主动生成 prompt（非用户输入触发，从 profile_summary + chat_history 拉上下文）
- [ ] chat_history 标 `kind='proactive'`（跟 v3-E1 Step Z [touch] 加 kind 字段同设计，profile rewrite 一并跳过）
- [ ] 用户当前 active 状态判断（Tauri 是否在前台 / 是否最近有交互）—— 用户离开时不打扰
- [ ] 频率限制（不能太烦，profile_summary 里记下用户偏好）

**估时**：1-2 天。

---

### v3-G：生活 & 工具型能力

**chunk 1.6 ✅ 完成（2026-05-07）— Apple Calendar 接入（macOS EventKit，国内可用）**

接入第二个日历数据源：macOS 原生 EventKit。**零网络 / 零 VPN / 零外部账号**——彻底解决国内用户 Google Calendar 卡防火墙的问题。同时建立"统一路由 + 双源"架构：用户改一行 yaml 即可切换 Apple ↔ Google。

| Hash | 内容 |
|---|---|
| `0f7c5a9` | feat(integrations): apple calendar via macOS EventKit —— `backend/integrations/apple_calendar.py` 用 pyobjc-framework-EventKit；macOS 14+ 走 `requestFullAccessToEventsWithCompletion_`，旧版回退 `requestAccessToEntityType_completion_`；threading.Event 把 Cocoa callback 同步到 asyncio.to_thread；非 macOS / pyobjc 缺失 / macOS<12 / 未授权全部降级 warn 不阻塞主流程；4 个 capability：`apple_calendar.today_events / upcoming_events / create_event / delete_event` —— **create_event 是 chunk 2.5 自然语言录入的关键入口**；`docs/apple-calendar-setup.md` 含权限框 / iCloud 同步 / 多日历选择 / 故障排查 |
| `<本 commit>` | feat(capabilities): calendar router + google chunk 1 namespace rename —— chunk 1 的 `backend/capabilities/calendar.py` 改名 `google_calendar.py`（git mv 保 history），cap 名 `calendar.*` → `google_calendar.*`，consumers 降级 SCHEDULER-only（避免 LLM tool surface 噪音）；新建 `backend/capabilities/calendar.py` 作**统一路由**，按 `config.yaml.calendar.default_source` 路由到 apple 或 google；briefing 模块零改（`from backend.capabilities.calendar import today_events` 自动走路由）；docs/ + ROADMAP / DESIGN / README 同步 |

**关键决策**：

1. **路由 vs 平行命名空间**：选思路 1（用户视角统一）。`calendar.today_events` 是 LLM 看到的正路；`apple_calendar.*` 4 个 + `google_calendar.*` 2 个直接 capability 仍注册（`user_visible=True` 让能力面板看得到，便于调试 + 状态透明），但只有 Apple 4 个直接 cap 同时 CHAT_AGENT consumer（用户 spec 要求）；Google 2 个直接 cap 仅 SCHEDULER（避免 LLM 看到 6 个雷同 tool 困惑）
2. **Google chunk 1 代码保留 + 默认禁用**：`google_calendar.enabled: false` 默认；启用 Google 时切 `default_source: google` + `enabled: true` 即可。OAuth 流程、健康检查、retry 全部 chunk 1 已验证可用，零回归
3. **non-macOS 平台不阻塞**：`pyobjc-framework-EventKit` 在 `requirements.txt` 用 PEP 508 marker `; sys_platform == "darwin"` 限制安装；运行时 `IS_MACOS` 检测 + `EventKit = None` 路径让 health_check 直接返 warn，capability 仍注册但报告"仅 macOS 可用"
4. **macOS 系统权限弹框是正常 UX**：第一次调用任意 calendar capability 时 macOS 弹"Skyler 想访问您的日历"——这是 macOS 系统级保护机制，**不绕过 / 不预先警告 / 不替用户点击**。文档明确说明
5. **create_event 描述里写明"先调 time.now 拿当前时间再算 ISO"**：用户说"明天上午 10 点"时 LLM 需要知道"今天"；description 直接引导这条调用链，避免 LLM 自己猜日期出 bug
6. **跨日历支持**：默认写到系统默认日历；可显式传 `calendar_name="工作"` 写到指定日历

**测试覆盖**：8 个测试套件 / **总计 175+ cases 全过**（chunk 0/1/1.5 累计 109 + chunk 1.6 新增 35 apple + 22 router = **166 cases**）

**Backlog**：

* **chunk 2.5 自然语言录入**：用户说"提醒我明天 10 点看牙医"→ ChatAgent 自动调 `time.now` → `apple_calendar.create_event`，pipeline 已就位，prompt 优化属下个 chunk
* **Reminders 集成**：当前只 Events；macOS Reminders 需要单独申请 `requestFullAccessToRemindersWithCompletion_`，是另一个独立权限框
* **Google 写能力**：当前 OAuth scope 仅 `calendar.readonly`，要支持 `google_calendar.create_event` 需扩 scope + 重新授权（path 已写到 docs）
* **多 source 同时聚合**：用户哪天想"同时看 Apple 和 Google"，router 加 `default_source: both` 模式合并去重 —— 现在没需求不做

---

**chunk 1.5 ✅ 完成（2026-05-07）— 双向 MCP 集成（暴露 server + 调用外部 client）**

让 Skyler 同时是 MCP server（把 capability 自动派生暴露给 Claude Desktop / Cursor / Claude Code 等外部 LLM 工具）和 MCP client（连接外部 MCP server，反向把对方 tool 注册成 capability）。**统一抽象**：一份 CapabilityRegistry，三种来源：(1) 内置 Python decorator；(2) 外部 MCP server 派生（runtime 注册）；(3) 内部 → 外部暴露（自动从 1+2 派生，按 `expose_via_server` 过滤）。

| Hash | 内容 |
|---|---|
| `6714374` | feat(mcp): expose capability registry as mcp server —— `backend/mcp/server.py` 用 `mcp.server.lowlevel.Server` + `@list_tools/@call_tool` 装饰器从 CapabilityRegistry 实时派生 tool；`StreamableHTTPSessionManager` 走 SSE 流；FastAPI mount `/mcp` + Bearer auth；CapabilityRegistry 加 `metadata` 字段 + `register_runtime` / `unregister_runtime`；前端 banner 显示 endpoint + 遮蔽 token + [👁][📋] 按钮 + 配置链接 |
| `7544df5` | feat(mcp): connect external mcp servers as capabilities —— `backend/mcp/client.py` 支持 stdio + streamable HTTP transport；环境变量插值（`${HOME}` / `${BRAVE_API_KEY}`）；closure 默认参数固化 tool name 解决循环捕获；外部 capability metadata 带 `source_server` + `expose_via_server`；MCP server 派生层按 `expose_via_server` 过滤；启动失败**不阻塞**主流程；`/api/mcp/clients/status` + `/{name}/reconnect`；前端外部 servers 状态条 + `[ext · server]` 卡片徽章 |
| `<本 commit>` | docs(mcp): bidirectional setup guides —— `docs/mcp-server-setup.md`（Claude Desktop / Cursor / Claude Code / mcp inspector 配置）+ `docs/mcp-client-setup.md`（filesystem 与 brave-search 完整示例 + expose_via_server 取舍 + 故障排查 + 命名空间约定 `ext.<server>.<tool>`） |

**架构验证**：

* CapabilityRegistry 现在同时支持 import-time decorator（chunk 0）+ runtime register（chunk 1.5）—— 两条路径 API 一致，`metadata` 字段是关键扩展点
* ChatAgent `_get_all_tools()` 路径**零改动**：runtime 注册的外部 capability 自动同步到 ToolRegistry → ChatAgent 看见
* 内部 capability + 外部 reverse-registered capability + Skyler 自身的 MCP server expose **三个消费者共用同一份 CapabilityRegistry** —— 这是统一抽象的核心
* 外部 server 启动失败仅 log warning，主进程继续；UI 显示红点 + last_error，可手动 [重连]

**测试覆盖**：109/109 个 case 全过（capability_registry 18 + cron_time_webhook 20 + google_calendar 21 + briefing 11 + mcp_server 22 + mcp_client 28，跨 6 个测试套件）

**Backlog**：

* OAuth-protected MCP server（用 mcp SDK 内置 OAuth provider 替代 Bearer）—— 当 Skyler 部署到远程 / 多用户场景时
* 外部 server tool list 变更监听（当前 init 时拉一次；外部 hot-add tool 需要 reconnect）
* Resource / Prompt 类型的派生（当前只暴露 tool；MCP 标准还有 resources / prompts 两类）

---

**chunk 1 ✅ 完成（2026-05-07）— Google Calendar 接入 + 起床简报 v0.1**

第一个真实第三方 tool 落地，验证 capability 抽象层在真实场景能撑住整套链路（OAuth + 重试 + 健康检查 + 前端授权 UI + cron + 简报生成）。chunk 0 的 4 行 pattern 在 calendar.py 里得到验证：

| Hash | 内容 |
|---|---|
| `61d6231` | feat(integrations): Google Calendar OAuth + API client（**底层**，不带 `@register_capability`，只作 client）+ tenacity 重试（3 次指数退避，OSError/HttpError/TimeoutError）+ 健康检查（网络异常一律降级 warn 不刷红 —— 国内常态而非真故障）+ `~/.skyler/` 凭证存储 + `docs/google-calendar-setup.md` Console 配置指南（含国内代理 caveat）；mock 单元测试 21/21 通过 |
| `12852f2` | feat(capabilities): `calendar.today_events` + `calendar.upcoming_events` 两个 capability（前者也给 SCHEDULER 用）；`/api/integrations/google/{status,auth,revoke}` 路由（`run_local_server` 走 `asyncio.to_thread` 不堵 event loop）；CapabilityPanel 增强：calendar 卡 footer 显示授权状态 + [连接 Google] / [重新授权] 按钮 |
| `<本 commit>` | feat(scheduler): 起床简报 v0.1 模板拼接 + cron 注册（默认 0 9 * * * Asia/Tokyo）+ `POST /api/briefing/test` 立刻触发 + CapabilityPanel calendar 类目右侧 [🧪 测试今日简报] 按钮；delivery v0.1 = ConnectionManager 推 notify text + Momo 音色合成 wav 落 `~/.skyler/last_briefing.wav` 离线验证（proactive 实时音频播放路径属 chunk 2 智能简报上线时再做） |

**架构验证 payoff**：

* `backend/integrations/` 与 `backend/capabilities/` 两层分离正确 —— 底层 client 完全可独立测（mock 21/21），上层 capability 调底层加 5 行装饰器即接入。
* `Consumer.CHAT_AGENT` 自动同步到 ToolRegistry 在 calendar 上**第二次得到验证**（time.now 之后），证明 chunk 0 的零改 chat.py 结论可复用。
* `health_check` 三档区分（healthy / warn / error）在真实集成里证明价值：未配 credentials / 未授权 / 网络超时全归 warn，UI 黄点不打扰，跟红色 error 形成对比。

**Backlog 标记**：

* **简报智能版**（v3-G chunk 2）：当前是模板拼接，下个 chunk 升级为 ChatAgent 智能生成（含联网新闻 / 天气 / 个性化语气）。chunk 1 的 cron + delivery + 测试入口直接复用。
* **Proactive 音频播放路径**（v3-G chunk 2 一起）：当前 wav 只落盘不播放；要让简报真正"早上响起来"需要把 `audio_chunk` 推送到前端的逻辑从 chat turn 解耦，由 ConnectionManager 触发 audio queue 入队。
* **OAuth 长 polling**：当前 `POST /api/integrations/google/auth` 阻塞到用户在浏览器完成。v0.1 接受这个 UX；优化路径（独立 polling endpoint / SSE 进度推送）等用户实际反馈再做。
* **多 calendar 支持**：当前固定 `calendarId=primary`，后续要支持工作日历 / 个人日历分开拉时再加。

---

**chunk 0 ✅ 完成（2026-05-06）— 地基：Capability Registry + cron + n8n receiver**

地基层：所有后续 tool（Calendar / 网易云 / Bilibili / Pollinations …）**必须**通过 ``@register_capability`` 注册到 ``backend.capabilities.CapabilityRegistry``，不再走 v3-C 时期"直接 ToolRegistry.register"路径。CapabilityRegistry 多承载了 display_name / category / icon / consumers / trigger_modes / health_check 五项 metadata，使前端 "能力面板" + 后端调度 + 鉴权三个子系统能各自只看自己关心的字段，无需互相耦合。

| Hash | 内容 |
|---|---|
| `0549f6c` | feat(capabilities): backend Capability Registry + decorator + `/api/capabilities` 路由 + 单元测试 (18/18 通过) |
| `54536b7` | feat(capabilities): 前端 CapabilityPanel + `lib/capabilities.ts` API client；挂在 SettingsPanel 顶部（spec 称 "tab"，但 SettingsPanel 是单列 Section 布局 → 当成顶部 Section 渲染） |
| `<本 commit>` | feat(scheduling): APScheduler cron scheduler (与既有 AlarmScheduler 平行) + Time capability + n8n webhook receiver (Bearer + HMAC 双因子) + `docs/n8n-integration.md` |

**架构决策**：

1. **CapabilityRegistry 不替代 ToolRegistry**：注册时若 ``Consumer.CHAT_AGENT`` 在 consumers，自动派生 OpenAI schema 同步注入 ``ToolRegistry`` —— ``backend/agents/chat.py`` 的 ``_get_all_tools()`` 零改动。
2. **scheduler 双轨**：``backend/scheduler/task.py`` 保留为 AlarmScheduler（30s 轮询 DB 到期 alarm，v2.5 起就有），``backend/scheduler/cron.py`` 新增 APScheduler 跑 cron / interval。lifespan 顺序起停。
3. **n8n webhook**：双因子鉴权（Bearer + HMAC SHA256 over raw body bytes），handler 异步 dispatch 立即 ack，避免 n8n 默认 30s 超时。当前注册 `test` trigger 一个，作 echo demo。

**v3-G chunk 1+ 后续顺序**（以下都是建立在 chunk 0 之上）：

**1. 剪贴板助手**

- Tauri 2 plugin-clipboard-manager 注册 clipboard 监听
- 前端检测到剪贴板变化 → 显示浮动按钮 "让 Skyler 看看？"
- 用户点 → 通过 ws 上行 `{"type": "clipboard", "content": "..."}`  
- ChatAgent 收到 → 自然语言回应（翻译 / 总结 / 评论）
- **隐私**：默认不自动发送，必须用户主动触发；不监听 password manager

**2. 每日简报**

- 已有 alarm 系统是固定时间 + 固定文本
- 简报需要：固定时间 + LLM 生成内容（基于近期 chat_history + profile_summary + 当天日历）
- 实施：scheduler 注册"每天 9:00"任务 → ChatAgent 用专用 prompt 生成简报 → ConnectionManager.push notify
- 用户在 Settings 里配置时间和内容偏好（时事 / 日程 / 鼓励 / 全部）

**3. 自然语言 cron 调度**（Hermes #3 借鉴）

- 用户："以后每周一早上提醒我开周会"
- ChatAgent 用 tool calling 调 `schedule_task(cron_expr="0 9 * * 1", action="提醒开周会")`
- scheduler 持久化到 DB（新表 `scheduled_tasks`）
- 启动时 lifespan 加载所有 task 注册 cron

**4. 智能提醒**

- 比 alarm 更软：基于 profile_summary 和 chat_history 上下文，主动想起"该做什么了"
- 例："你昨天说想看《三体》今天看了吗？"
- 实施：后台任务 + LLM 推理 + 阈值控制频率（不能太烦）

**5. 角色状态面板 + 成长系统**

详见 DESIGN §19.3。v3 阶段最重要的"AI 同伴感"差异化功能：让 character 跟用户聊得越多越熟悉。

- [ ] per-character profile_summary 自动 rewrite（聊天历史触发，已部分就绪 v2.7）
- [ ] 长期记忆向量检索 per-character 隔离（已就绪 v3-D）
- [ ] profile_summary 注入下次对话作为"她记得你的"信息
- [ ] character 演化指标（chat 轮数 / 用户分享深度 / 主动对话次数）
- [ ] 角色状态面板 UI（亲密度 / 当前心情 / 当前思绪 / 当前正在做什么）

**估时**：3-5 天。

---

### v3-G'：TTS UI 升级 + cosyvoice emotion 真生效

**目标**：把现有的 voice_model JSON 文本框升级成生产级 voice picker，**同时让 cosyvoice emotion 真正生效**（当前 emotion 字段被 SDK 忽略，audit 已确认）。

**主线完成清单（5 commit + 2 patch）**：

| Hash | 内容 |
|---|---|
| `de7ebe2` | ⚠️ chunk 1a：`/api/tts/voices` 接口 + cosyvoice.py SSML emotion 包装。**SSML emotion 路径事后证实是错的**（DashScope SSML 标签没 emotion 属性，被 SDK 静默忽略），但其他改动（API + config 结构）继续生效 |
| `bd46a80` | chunk 1b：CharacterPanel 两级下拉（provider → voice）+ tts.ts API client + 兼容 badge |
| `bf21915` | chunk 1c：Momo (id=1) lifespan 默认音色 = `cosyvoice/longyumi_v3` |
| `b29662c` | patch (a)：撤销 SSML emotion 包装；emotion 真生效改走 **instruct 自然语言指令路径**；config.yaml 改 6 音色（longyumi_v3 / longfeifei_v3 / longwan_v3 / longqiang_v3 / longxing_v3 / longanhuan） |
| `e73e2bc` | patch (b)：前端 SSML badge 删除；保留 Instruct badge 改名"情感控制 / 纯音色"；下拉选项展示 `{label} · {traits}` |
| `7efe3e8` | tools：独立测试脚本 `tools/test_cosyvoice_emotion.py`，复刻生产 instruct 调用形态，4 emotion × longanhuan 端到端跑通 |
| `d05d292` | patch (c)：instruction 字符串去空格（`"你说话的情感是{emotion}。"`，与文档严格匹配）+ 新增 instruct-aware 男声 longanyang；测试脚本同步去空格 + scoped monkeypatch 把 SDK 5s WS 建链超时放宽到 30s（仅测试，生产未动） |

**为什么撤回 SSML**：DashScope 官方 SSML 标签合法属性是 voice / rate / pitch / volume / effect / bgm，**没有 emotion**。chunk 1a 的 `<voice emotion="happy">...</voice>` 是非法 SSML，请求要么被忽略要么返 400。真情感控制走 SDK 的 `instruction` 参数（`speech_synthesizer.py:218-219` audit 证实），**v3-D 起一直就有这条路径**，但仅在音色 `instruct: true` 时启用。chunk 1a 没改正机制，只是在并行加了一条无效的 SSML wrapper。patch (a) 撤销 wrapper + 把 instruct 路径作为 emotion 真生效的唯一通道。

**关键决策（知识沉淀）**：

1. **DashScope 系统音色全平台仅 3 个支持 Instruct**：`longanyang`（男 · 阳光大男孩）/ `longanhuan`（女 · 欢脱元气女）/ `longhuhu_v3`（女童）。其他系统音色（longyumi_v3 / longfeifei_v3 / longwan_v3 / longqiang_v3 / longxing_v3 等）传 `instruction` 会被服务端拒绝。
2. **支持的 7 个英文 emotion 枚举**：`neutral` / `fearful` / `angry` / `sad` / `surprised` / `happy` / `disgusted`。当前 LLM prompt 引导 5 个（neutral 不需要 instruction，剩下 4 个：happy / sad / angry / surprised），fearful / disgusted 未引导，instruct 白名单也对应排除。
3. **系统音色 instruction 字符串必须严格匹配固定格式**：`"你说话的情感是{emotion}。"`——emotion 与"是"之间**不能**有空格，否则系统音色返 `InvalidParameter 428`。chunk 1a → patch (a) 期间因为读了文档示例的 markdown 视觉空白当字符空格，跑过一段时间 happy=neutral 听感差不出来，patch (c) 才 audit 出根因。
4. **复刻音色（自训 / cosyvoice voice cloning 创建的 myvoice-xxx）支持自由自然语言指令**：不受固定格式限制，可以传 `"温柔地慢慢说"` `"语速加快、带笑意"` 这类自由 prompt。这是后续 Phase 2 复刻音色场景的能力释放点。

**当前 config.yaml 已登记的 cosyvoice 音色**：

| voice | traits | instruct |
|---|---|---|
| longyumi_v3 | 正经青年女 | ❌ |
| longfeifei_v3 | 甜美娇气女 | ❌ |
| longwan_v3 | 柔声女 | ❌ |
| longqiang_v3 | 浪漫女 | ❌ |
| longxing_v3 | 邻家女 | ❌ |
| **longanhuan** | **欢脱元气女** | **✅** |
| **longanyang** | **阳光大男孩** | **✅** |

→ 想要 emotion 真生效（开心 / 难过 / 生气 真有差异）必须切到 longanhuan / longanyang。其余 5 个音色 emotion 字段被静默丢弃，TTS 仍正常播但情感由音色本身固定风格决定。`longhuhu_v3`（女童）平台支持但暂未登记进 config.yaml，等真有女童角色再加。

**emotion 白名单**：instruct 路径只对 happy / sad / angry / surprised 生效；neutral 等价"不指定"不传 instruction；fearful / disgusted 当前 LLM prompt 未引导，先不实验性派发。

**架构验证（已 done）**：`/api/tts/voices` schema 容纳多 provider，未来 v5-T1 SoVITS 接通时只要后端追加 entry，前端代码 0 改动 ✓。

**Phase 1 实际工时**：~1.5 天（含两轮 audit + 全部 patch + 独立验证脚本）。

#### Phase 2 📋 PENDING — 复刻 / fine-tune 自定义音色

**目标**：超越 7 个固定系统音色的局限，为每个角色训出专属音色。

**条件门槛**：

- 用户准备好角色参考音频样本（5-10 段，每段 5-30s，干净环境，覆盖目标情感分布）
- v5-D autodl 部署完成（SoVITS 训练需要 GPU）；CosyVoice 云端 voice cloning 不依赖 v5-D，可独立先行

**两条路径**（详见 v5-T2 章节）：

1. **CosyVoice fine-tune voice cloning**（短路径，云端，~1-2 小时训练）→ 拿到 `myvoice-xyz123` ID → 加进 `config.yaml` `tts.cosyvoice.available_voices` → CharacterPanel 下拉自动多一项；复刻音色 instruction 接受自由自然语言指令，能力比固定格式系统音色强。
2. **GPT-SoVITS 角色专属训练**（长路径，autodl GPU）→ 多情感参考音频文件 → SoVITSProvider 按 `emotion → ref_audios[emotion]` 路由。

**触发时机**：用户某天主动说"我准备好 Momo 的录音了 / autodl 训完了 SoVITS 模型"——届时把 Phase 2 改 🚧。

**估时（届时）**：CosyVoice 路径 1 天；SoVITS 路径 3-5 天。

---

### v3-H：媒体接入（音乐 / 视频 / 系统播放控制）

延展 v3-G chunk 1.5 的 capability 架构，把第三方媒体能力接入成 capability。三条**互不依赖**的子链路。

| 子任务 | 状态 | 路径要点 |
|---|---|---|
| 网易云内置接入 | 🟡 chunk 1 PARTIAL（2026-05-08）| 数据查询 + 唤起 NCM 可用；自动播放封存待 chunk 2 重做 |
| 媒体控制（nowplaying-cli）| ✅ chunk 1 完成（2026-05-08）| `brew install nowplaying-cli` + 5 个 capability，跨来源播控 |
| B 站接入 | 📋 TODO | 独立链路；MCP client 或直接 integrations/bilibili.py |

### v3-H chunk 1 — 网易云音乐接入 🟡 PARTIAL

**已交付**：
- 网易云 web API client（weapi 加密）
- 7 个 netease.* capabilities（日推/歌单/搜歌/加红心/私人 FM 等数据查询）
- 5 个 media.* capabilities（基于 nowplaying-cli）
- macOS 媒体控制基础设施（独立可复用）

**已知限制**：
- 自动播放功能不稳定（NCM macOS 客户端的 orpheus:// URL Scheme 对路由/播放命令支持不完整，与版本相关）
- 当前可作为「数据查询 + 唤起 NCM」使用，最终播放需用户手动点击

**后续 v3-H chunk 2 备选方向**（自决，不阻塞主线）：
- 方向 A：fork NCM URL Scheme handler 找其他 hook 点
- 方向 B：Skyler 自己解码音频（song/url API + afplay/mpv），完全可控但失去 NCM 客户端的歌词/动画
- 方向 C：纯查询模式（Momo 告诉你播什么，你手动点）

#### chunk 1 交付详情（2026-05-08）— 网易云内置接入 + macOS 媒体控制

**关键决策：放弃 cloud-music-mcp，自己写 weapi**

之前 v3-H 计划走 [Code-MonkeyZhang/cloud-music-mcp](https://github.com/Code-MonkeyZhang/cloud-music-mcp) MCP client 路径，被 `pyncm` 装不上卡住（PyPI / 镜像在 Python ssl 路径被截断，怀疑代理 TUN 劫持）。本 chunk **改自己写 weapi 内置实现**：weapi 加密参数（AES-128-CBC + RSA-1024）公开已久，jixunmoe / Binaryify 等都用同一组常量，不是逆向破解；体积代价仅 `pycryptodome` 一个新 dep（~3MB BSD/PD，已是 bce-python-sdk 的 transitive，本地零增量）。

| Hash | 内容 |
|---|---|
| `a00f696` | feat(integrations): netease cloud music client (web API + url scheme) —— `backend/integrations/netease_music.py`：weapi 加密 + 7 个 client 方法（daily_recommend / personal_fm / my_playlists / playlist_detail / search / like_song / add_to_playlist）+ orpheus:// URL scheme builder + Chrome 风控 headers + cookie 走 `.env` `NETEASE_MUSIC_U`；health_check 三档；42/42 mock 单测 |
| `6d63958` | feat(capabilities): netease music 7 capabilities —— `backend/capabilities/netease_music.py`：7 个 capability 全 CHAT_AGENT consumer，description 强引导（chunk 1.7 verbatim 模式）；`play_playlist` 设计成两步流程让 LLM 用语义模糊匹配 emoji / 别名 / 多语言歌单名（"跑步" → "🏃 跑步专用"）；49/49 单测 |
| `5632660` | feat(capabilities): media control via nowplaying-cli —— `backend/capabilities/media_control.py`：5 个 capability（next/previous/play_pause/now_playing/set_volume），`subprocess.run` 包装 `nowplaying-cli` + `osascript`，IS_MACOS / 缺 CLI 双重 graceful，timeout=2s；48/48 单测 |
| `<本 commit>` | docs+chat: netease & media control system prompt + setup guides —— `_TOOL_PROMPT_ADDENDUM` 加【音乐类】+【媒体控制】两段 verbatim 引导；`docs/netease-music-setup.md` 含 Chrome F12 抓 cookie 图文 + 风控提示 + 故障排查；`docs/media-control-setup.md` 含装机 / 能力 / 与网易云配合 / 隐私说明；ROADMAP v3-H chunk 1 ✅ |

**架构验证**：
- 网易云 7 cap + 媒体控制 5 cap 共 **12 个新 capability**，全部经 `@register_capability` 一次性进 CapabilityRegistry + ToolRegistry，ChatAgent 零改动看到（chunk 0 抽象第三次得到验证）
- 跨来源体验：用户用网易云 App 听歌时，"下一首"走 `media.next_track`（系统级 MediaRemote framework）；用 Apple Music / Spotify / YouTube 听歌时，同一句"下一首"完全等价工作
- "好听！加红心"复合调用链：`media.now_playing` 拿 title+artist → `netease.like_current` 用关键词回搜 song id → `like_song` 写回。LLM 自然能编排（chunk 1.7 system prompt 强引导后）

**测试覆盖**：3 个新测试套件 / **总计 139 cases 全过**（netease_music 42 + netease_capabilities 49 + media_control 48）

**Backlog**：

* **chunk 2 — B 站接入**：搜视频 / 拉首页 / 指定 UP 主投稿。**不做**直播弹幕（已在"不在路线图里"排除）。两条候选：MCP client（找现成 bilibili-mcp）/ 直接 integrations/bilibili.py。估时半天到 3 天。
* **chunk 1.x 增强**：网易云 `add_to_playlist` 没单独包成 capability（client 层有），等用户复盘有需求再暴露；`like_current` 当前不会自动判断当前播的是不是网易云资源，搜不到时返 error，由 LLM 包装；后续可加"先 search 验证再调 like"两步保证

---

### v4：屏幕感知

DESIGN §13 已有完整设计。要点：

1. **VLM provider 抽象**：`backend/vlm/client.py` 统一调用 GPT-4o / Qwen-VL / Claude vision
2. **Tauri 截图 API**：单次截图 vs 持续监听
3. **像素差预过滤**：算法见 DESIGN §13.3
4. **隐私黑名单**：基于活动窗口的 app name / window title / Bundle ID
5. **WebSocket 协议扩展**：`screen` 上行 + `screen_comment` 下行
6. **Settings 加屏幕感知开关 + 黑名单管理**

**优先做主动模式（hotkey + 语音命令）**，被动模式延后 —— 理由见 DESIGN §20.3。

---

### v5-D：autodl 部署 + 子 agent 隔离

详见 DESIGN §阶段七。要点：

1. 后端打包 Docker 部署 autodl GPU 实例
2. 前端通过 SSH tunnel 或 HTTPS 访问
3. **子 agent 隔离**（Hermes #4）—— 长任务（屏幕分析 / 批量记忆压缩 / 自主信息收集）跑独立 context
4. 数据库 / 模型权重存 autodl 持久卷

**估时**：3-5 天（Docker + 部署调试）。

---

### v5-T1：GPT-SoVITS 后端接通

依赖 v5-D（SoVITS 推理需要 GPU）。

1. **autodl 上起 SoVITS 推理服务器** —— fast-inference fork（推荐 GPT-SoVITS-Inference 或 RVC-Project）；HTTP API 形式起服务
2. **`SoVITSProvider` 真实现**：
   - 当前是 `_LegacyProviderAdapter` 占位
   - 改为读取 `voice_model` 的 `gpt_path` / `sovits_path` / `ref_audios` 字段
   - 合成时按 `emotion` 在 `ref_audios` 里找对应文件，找不到用 `default_emotion` 兜底
   - HTTP POST 到 SoVITS server，body 含 text + ref_audio_path + 模型路径
   - 返回 WAV bytes 透传
3. **`config.yaml` 加 `tts.sovits.available_voices` 列表** —— 列出 autodl 上已部署的 SoVITS 模型
4. **路径管理**：autodl 上的 `/path/to/model.pth` 等绝对路径在 SoVITSProvider 内做翻译；前端只见显示标签
5. **`/api/tts/voices` 自动包含 sovits provider**（v3-G' 架构 payoff —— 前端代码不动）

**估时**：3-5 天（SoVITS 服务器配置占大头）。

---

### v5-T2：训练自定义 voice

依赖 v5-T1（先有 provider 再训模型）。

**两条并行训练路径**：

#### A. CosyVoice fine-tune voice cloning（短路径，云端）

1. 收集 5-10 段角色参考音频（每段 5-30 秒，安静环境，单一情感）
2. 走 DashScope CosyVoice voice cloning API 或 Web 工作流
3. 训练完成后拿到一个 `myvoice-xyz123` ID
4. 加进 `config.yaml` `tts.cosyvoice.available_voices`
5. CharacterPanel 下拉自动多一项

**估时**：训练 1-2 小时；流程跑通 1 天。

#### B. GPT-SoVITS 专属 model 训练（长路径，本地 / autodl）

1. 收集更多角色音频（推荐 30 分钟+ 高质量样本，多情感）
2. 数据清洗 / 切分 / 转写
3. autodl GPU 训练 GPT 模型（数小时） + SoVITS 模型（数小时）
4. 准备多情感参考音频文件 → 按 `ref_audios` schema 组织
5. 模型 + 参考音频部署到 autodl 推理服务
6. 加进 `config.yaml` `tts.sovits.available_voices`

**估时**：数据准备 1-3 天；训练 1-2 天；调优 1-3 天。

**角色绑定**：训练完成的 voice 默认绑定到对应 character（用户在 CharacterPanel 手动 confirm）。

---

### v6+：多设备访问（高代价）

⚠️ **这个阶段会让项目从"桌面应用"跃迁到"小型 SaaS"**。代价：

- 用户认证（OAuth / passkey / 自有账号系统）
- WebSocket 鉴权
- TLS（自签 + Let's Encrypt 或购买）
- **数据库迁移到 Postgres** —— SQLite 不支持多客户端并发写
- 多端状态同步（WebSocket broadcast 还是 polling？冲突解决策略？）
- 部署运维（监控 / 日志 / 备份 / 健康检查）
- 不同 OS 客户端打包（Windows / Linux 见 DESIGN §二十）

工作量评估：**等于把整个项目再写半遍**。除非真有强烈需求，否则建议永远停在 v5（远程后端 + 单设备 Mac 客户端）。

---

## 建议下一步

按"性价比"排序，建议你接下来这么走：

### Step 1（本周末）：固化 + git 卫生
- [x] 新建 GitHub repo `Skyler`
- [ ] git push 三份新文档（README / DESIGN / ROADMAP）
- [ ] 配置 `.gitignore` 防止 `.env` / `*.db` / `node_modules` 误提交
- [ ] 设置 git 工作流：每完成一个独立模块 commit 一次（conventional commits）

### Step 2（接下来 1 周）：低成本快收益
按从易到难做这几件，能快速看到体验飞跃：
- [ ] **TTS 预处理器**（v3-F #3）—— 半天就能做完，立刻不读 `*笑*` 这种东西
- [ ] **AI 内心独白 `<thinking>` 标签**（v3-F #4）—— 1-2 天，参考 emotion 实现模式
- [ ] **语音打断**（v3-F #1）—— 2-3 天，体验飞跃明显
- [ ] **TTS 多段并发**（v3-F #2）—— 2-3 天，首句延迟显著降低

做完这一组，v3-F 完成，体验上一个台阶。

### Step 3（接下来 2-3 周）：v3 灵魂
- [x] **下载 Hiyori 模型**
- [x] **v3-E1 Live2D 主线**（Step 1-6 + 角色修复 + Step Z.1，8 commit 完成）
- [x] **v3-E1 Step Z 收尾**（4 条 cleanup 完成：commits `488a6a1` / `f2d7f78` / `d984916`）
- [x] **v3-E2 多模型接入**（runtime 抽象层 + per-character maps + 八重 BCSZ1.1 接入 + Momo persona 还原；9 commit 完成 2026-05-06）
- [x] **v3-E3 emotion 视觉绑定**（代码路径已接通 chunk 7 `950710e`，剩纯运营找模型）
- [x] **v3-G' TTS UI 升级 + cosyvoice instruct emotion**（5 commit + 1 patch，2026-05-06）—— SSML 路径事后撤回，改走 instruct
- [ ] **v3-F' 主动对话**（依赖 [touch] kind 字段同设计）—— 1-2 天

v3-E 全套 + 主动陪伴中两条已完成 + 收尾。剩 v3-F' / v3-G' / v3-G。

### Step 4（接下来 1-2 个月）：工具层
v3-G 全部 + v4 主动屏幕感知。从剪贴板助手开始（最简单），逐步加每日简报、智能提醒、cron、屏幕感知。

### Step 5（远期）：autodl 部署 + 自定义 voice
- v5-D autodl 部署 + 子 agent 隔离
- v5-T1 GPT-SoVITS 后端接通
- v5-T2 训练 CosyVoice fine-tune voice + GPT-SoVITS 专属 model

等 GPU 推理需求真出现了再做。CosyVoice fine-tune 可以更早做（不需要 autodl）。

---

## 不在路线图里的东西（明确不做）

避免后续想法漂移：

- ❌ 群聊（多角色同时对话）—— 与单角色 Galgame 看板娘定位冲突
- ❌ Bilibili 弹幕客户端 —— 直播场景，与桌面伴侣定位无关
- ❌ Letta / MemGPT —— 现有 SQLite + sentence-transformers 已够用
- ❌ Telegram / Discord / WhatsApp gateway —— 桌面应用而非远程 agent
- ❌ Linux Wayland 完整支持 —— 技术上几乎做不了
- ❌ 系统操作 agent（鼠标键盘控制）—— DESIGN 里曾提过，但跨平台 + 安全代价太高
- ❌ **Settings 全局 TTS 开关** —— TTS 配置只在 CharacterPanel 上 per-character 提供，避免双层配置带来的认知负担
- ❌ TTS UI 提前堆假选项 —— 下拉只显示真实可用的 voices，新 provider 接通后自动出现

---

## Tech Debt & Backlog

### 性能
- ⚠️ `_build_messages` 性能退化：chunk 1.6 实测 4ms，v3-H chunk 1 实测 4487ms（1000x）。嫌疑路径：某个新 capability 在 prompt 注入时做昂贵 IO（同步 health_check 远程 API？）。修复时间窗：v3-G 主线封盘前 audit。

### 数据架构
- Characters 双源技术债：`characters.yaml` 与 DB `characters` 表两套数据源不一致。当前 Scheme B（DB 主 + YAML fallback）。计划 Scheme C（v3-G 末或 v4）：删 yaml、DB 单源、写迁移脚本、`switch_character` 工具改 DB query、`prompt_manager` 改 DB-backed。

### 角色
- Momo (id=1) 当前是 Yae Miko 临时占位人设（chunk 1.6 时为绑 Hiyori 模型设的）。v3-E2 多 Live2D 模型扩展完成后，恢复 `characters.yaml` default 条目里的原 ChatAgent 人设。

### Live2D
- Hiyori motionMap 完整语义已用户验证（Flick=轻挥、FlickDown=手藏背后、FlickUp=举手欢呼、Flick@Body=组合）。Hiyori 缺挥手 hello / 点头 / 鞠躬等动作。v3-E2 切换其他模型时全表重写。
- v3-E3 emotion 视觉绑定阻塞于 `.exp3.json` 模型资产（外部依赖）。

### 音色
- v3-G' Phase 2 自训音色（SoVITS / 微调 cosyvoice3）等用户训练完成后接入。

### 工具链
- skyler CLI 工具（thin client 调 backend HTTP）：替代 MCP 作为对外接口的更轻方案。v3-G 封盘后做。
- MCP server 暴露层（chunk 1.5 已建）作为标准化备选保留，默认 disabled，按需启用。

### 媒体接入
- 网易云音乐自动播放重做（v3-H chunk 1 partial）
- B 站 / Pollinations 表情包 / OpenClaw 等其他媒体源（v3-H 后续）

---

## 技术债（v3-G 后期或 v4 处理）

### cosyvoice provider WS 建链超时增强（v3-G' 衍生 backlog）

**现状**：

- 生产 `backend/tts/cosyvoice.py` 用 SDK 默认 5s WebSocket 建链超时（`venv/.../speech_synthesizer.py:526` 写死 `self.__connect(5)`，无外部参数化入口）
- 弱网 / 跨境链路 / VPN 抖动场景下 5s 经常不够，会 raise `TimeoutError("websocket connection could not established within 5s")`，单句 TTS 直接失败
- v3-G' patch (c) 期间 `tools/test_cosyvoice_emotion.py` 已 scoped monkeypatch 把超时放到 30s（仅作用于测试脚本进程），生产路径**未动**

**修复方向**（独立 chunk，不在 v3-G' 范围）：

- 选项 A：生产侧加同等 monkeypatch（最少改动，但 hack 痕迹）
- 选项 B：cosyvoice.py 增加重试包装（`_blocking_synthesize` 失败后退避重试 1-2 次），同时记录 telemetry
- 选项 C：升级 dashscope SDK 看上游是否已暴露 timeout 参数 / 重试机制
- 选项 D：长远迁到 SDK 的 streaming_call + 自管 WebSocket 连接池

**触发时机**：用户在生产环境复现 5s 超时报错（或 telemetry 累计若干次），届时按上面四选一处理。

---

### characters 双源真相 → 方案 C 统一

**当前现状（v3-E1 角色修复 `ba2efd2` 后）**：

- **DB `characters` 表**：UI 切角色用，per-character chat_history / memory / voice_model / live2d_model 隔离
- **`config/characters.yaml`**：prompt_manager 用，`switch_character` LLM tool 用
- `_build_messages` 优先 DB persona，YAML fallback —— 这是**方案 B**

**方案 B 引入的张力点**：

- UI 切角色 → DB id → 用 DB persona ✓
- LLM tool 切角色 → 改 prompt_manager state → 但前端仍带原 character_id → DB persona 仍命中 ✗

**方案 C 彻底统一**：

- 删 `characters.yaml`
- DB 是单一真相源
- 写 migration 把 YAML "默认" / Momo 等条目灌进 DB
- 改 `switch_character` LLM tool 按 name 查 DB
- prompt_manager 改成 DB-backed

**估时**：1 天。

---

## 遗留技术债（pre-existing test debt）

下列测试文件在 v3-F 接手前已经断开，import 早已删除 / 改名的符号；与 v3-F 无关，
未来想跑全套 pytest 之前需要单独修一次。**v3-F 阶段不动**，避免 scope creep。

| 文件 | 失败原因 | 引入版本 |
|---|---|---|
| `tests/test_chat_agent.py` | `from backend.database.services import upsert_personality` —— 函数已删 | v2.5-B |
| `tests/test_database.py` | `from backend.database.services import upsert_personality` —— 同上 | v2.5-B |
| `tests/test_llm_client.py` | `from backend.config import DEFAULT_MODEL` —— 常量已改名 | v2.5-B |
| `tests/test_memory_agent.py` | `from backend.agents.memory import _personality_to_dict` —— 已删 | v2.5-B |
| `tests/test_ws_helpers.py` | `from backend.routes.ws import _run_plan` —— PlannerAgent 简化时移除 | v3-C |
| `tests/test_memory.py` | 单条断言 `SHORT_TERM_MAX is 20`，当前实际值不同 | v2.5-B |
| `tests/test_integration.py` | 集成 fixture 期望 `r.json()[0]["tag"]`，路由返回 schema 已变 | v2.5-B |

修复策略（未来）：要么按现有代码补回 / 改名对应符号，要么删掉 / 重写这些测试。
一次性单 PR：`chore(tests): repair pre-existing test debt from v2.5-B / v3-C`。

---

*文档版本：1.5 | 最后更新：2026-05-06（v3-G' TTS UI + cosyvoice instruct emotion 完成：5 commit + 1 patch；chunk 1a SSML emotion 路径事后撤回——DashScope SSML 标签没 emotion 属性，audit 后改走 SDK instruction 字段）*
