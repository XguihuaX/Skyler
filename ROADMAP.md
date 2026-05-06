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
