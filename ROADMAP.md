# 🗺️ Skyler Roadmap

> Living document. 每完成一个里程碑同步更新 + commit + push。
>
> 当前状态（2026-05-04）：v2.7 完整 + v3-A/B/C/D 完成（约 v3 整体 60%）。

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
| **v3-D：emotion 后端解析 + TTS 联动** | ⚠️ 后端 100% / 前端 0% | 50%（前端等 Live2D） |
| **v3-E1：Live2D 接入（用 Hiyori 走通流程）** | 📋 计划中 | 0% |
| **v3-E2：换上目标模型（资产替换不动代码）** | 📋 依赖 E1 | 0% |
| v3-F：语音体验飞跃（打断 / 并发 / 预处理 / 内心独白） | 📋 计划中 | 0% |
| v3-G：生活 & 工具型能力（剪贴板 / 简报 / cron / 成长系统） | 📋 计划中 | 0% |
| **v3-G'：TTS 配置 UI 升级（per-character 两级下拉）** | 📋 计划中 | 0% |
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

### v3-E1：Live2D 接入（用 Hiyori 走通流程）

**核心思路**：用 Live2D 官方免费样本 **Hiyori** 当首发模型，不是因为它是最终目标，而是**先把整个 Live2D + 前后端管道打通**。一旦跑通，换模型只是资产替换（v3-E2）。

**为什么用 Hiyori**：
- Live2D Inc. 官方免费样本，无需购买
- Cubism 4 兼容模型（moc3 ver ≤ 4），参数 ID 标准化（ParamMouthOpenY 等）
- 各种 motion 和 expression 已就绪，直接能测
- ⚠️ 许可：Live2D Free Material License Agreement，**开发期 OK，商用要看条款**

**下载**：从 [Live2D 官方 Sample Data 页面](https://www.live2d.com/zh-CHS/learn/sample/)拿 Cubism Sample Data，里面有 Hiyori 的 .moc3 / .model3.json / motion / expression 全套。放到 `frontend/public/live2d/hiyori/`。

> ⚠️ **关键约束**：pixi-live2d-display 及其所有 fork（advanced / lipsyncpatch / mulmotion）只支持 Cubism 4 Core，**不支持 Cubism 5**（GitHub issue #118 自 2023-10 未修复）。Hiyori 是 Cubism 4 格式（moc3 ver 3），兼容。v3-E2 选购模型时必须确认 moc3 ver ≤ 4。

**实施步骤**：

1. **SDK 集成**：`npm install pixi-live2d-display pixi.js@7`，引入 Cubism 4 Core 作为静态资源（放 `frontend/public/live2d/core/`）
2. **CharacterView.tsx 改造**：
   - 从 `<img src={character.avatar} />` 换成 `<canvas>` + PIXI Application
   - 加载 `.model3.json` → `Live2DModel.from()`
   - 保持现有 Galgame 满铺布局不变（满铺 = stage size match canvas size）
3. **idle 动画**：调用 `model.motion('Idle')` 自动循环（Hiyori 自带 idle group）
4. **口型同步**：
   - `useAudio.ts` 新增 `useAudioAmplitude()` hook 用 AnalyserNode 取样振幅
   - CharacterView 订阅 → 写入 `model.internalModel.coreModel.setParameterValueById('ParamMouthOpenY', value)`
5. **emotion → 表情切换**：
   - 后端 ws.py 当前 `_parse_emotion` 之后**新增 send_json `{"type": "emotion", "value": "happy"}`**
   - 前端 useWebSocket 加 case `'emotion'` → store `setCurrentEmotion`
   - CharacterView useEffect 订阅 `currentEmotion` → `model.expression(emotionMap[X])`
   - emotionMap 配置：哪个情感对应 Hiyori 哪个 expression（后续换模型只改这个映射）
6. **触摸响应**：
   - canvas onClick → 转 PIXI 局部坐标 → `model.hitTest(x, y)`
   - hit area "Head" / "Body" / "Cheek" 触发不同 motion 和后端 special prompt
7. **motionMap**（emotion 扩展）：system prompt 加 `<motion>X</motion>` 输出指令；ws.py push 给前端；前端触发 `model.motion(X)`
8. **DB 字段**：迁移 `v3_e.py` 给 `characters` 加 `live2d_model TEXT`（存模型路径或 ID）；CharacterPanel 加输入框

**估时**：核心接入 + idle + 口型同步 → 2-3 天；emotion + 触摸 + motion 联动 → 1-2 天。Hiyori 现成模型省了找资产时间。

---

### v3-E2：换上目标模型

E1 跑通后，换模型纯粹是**资产替换 + 微调映射**，不动代码逻辑。

**步骤**：

1. **找 / 买 / 自制目标 Cubism 4 兼容模型（moc3 ver ≤ 4）** —— 可选项：
   - VRoid / nizima / BOOTH 等 VTuber 模型站购买
   - Twitter / Pixiv 上找艺术家委托制作
   - 自己用 Cubism Editor 制作（学习曲线陡）
2. **把模型资产放到约定路径** `frontend/public/live2d/<name>/`
3. **CharacterPanel 里改 character 的 `live2d_model` 字段** → 立刻生效
4. **校准 emotionMap** —— 不同模型的 expression 命名不同，需要在 config / 模型注册时配映射
5. **校准 hit area** —— 不同模型的 hit area 命名 / 区域不同，触摸逻辑可能要调
6. **校准 motion 集合** —— motionMap 也要按新模型的 motion list 重映射

**估时**：1-2 天调试 + 模型本身的获取时间。

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

详见 DESIGN §19.3。

---

### v3-G'：TTS 配置 UI 升级

**目标**：把 CharacterPanel 当前的"裸 JSON 文本框"换成 provider + voice 两级下拉。**关键约束：UI 下拉只显示真实可用的选项**，不堆假选项。

**当前阶段下 UI 实际形态**：

```
TTS Provider:  [CosyVoice ▼]   ← 只有这一个
   └─ Voice:   [longyumi_v3 ▼] ← 只有这一个
```

只有 1 个选项也要做下拉而不是固定显示，因为这套架构是为未来扩展准备的：v5-T1 接通 GPT-SoVITS 后，下拉自动多一个 provider；v5-T2 训练 fine-tune voice 后，voice 列表自动多几项。**前端代码不需要改。**

**实施步骤**：

1. **后端 `GET /api/tts/voices` 接口** ——  返回所有可用 provider + voices：
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
     ]
   }
   ```
2. **`config.yaml` 加 `available_voices` 列表** —— 启动时后端读取，缓存
3. **CharacterPanel TTS 表单升级**：
   - 当前的 `voice_model` 文本框换成两级下拉
   - 选 provider → 二级下拉显示对应 voices
   - 用户选择后前端拼出 `voice_model` JSON 写回 character API
4. **schema 兼容性**：写回的 JSON 严格按 DESIGN §6.2 schema，未来切 SoVITS 时不需要 DB 迁移
5. **架构验证**：mock 一个 SoVITS provider 进 `/api/tts/voices` 返回，确认 UI 自动多 provider 选项 → 删掉 mock。这步证明架构经得起 v5-T1 的验收

**估时**：1-2 天。

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
- [ ] **下载 Hiyori 模型**（30 秒，从 Live2D 官方 Sample Data 页面拉，Cubism 4 兼容）
- [ ] **v3-E1 Live2D 核心接入**（用 Hiyori，#1-4 步骤）—— 2-3 天
- [ ] **emotion → Live2D 表情切换**（v3-E1 #5）—— 1-2 天
- [ ] **触摸响应**（v3-E1 #6）—— 1 天
- [ ] **motionMap**（v3-E1 #7）—— 2 天
- [ ] **v3-G' TTS UI 升级**（穿插着做）—— 1-2 天
- [ ] **v3-E2 换上目标模型**（找到模型之后再做）—— 1-2 天

做完这一组，v3-E 完成，Skyler 真正"活"了，TTS UI 也不再是裸 JSON。

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

*文档版本：1.2 | 最后更新：2026-05-04（v3-F 子项 1-3 完成；记录遗留测试债）*
