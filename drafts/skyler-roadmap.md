<!-- 给用户审阅的新 ROADMAP(对应 ROADMAP.md)。落库前:
     ① CC 把所有状态 badge 回代码核;② 完整时间线已移出 → docs/EVOLUTION.md(版本×功能矩阵)+ IMPLEMENTATION_LOG.md;
     ③ 深 chunk 历史 + 详细 Tech Debt 由 CC 迁到 IMPLEMENTATION_LOG,这里只留近期计划 + 当前状态 + 前瞻。 -->

# 🗺️ Skyler · ROADMAP

> 一眼看清:现在每块能力到哪一步、接下来做什么。
> 项目怎么一步步长出来的(版本 × 功能)→ [EVOLUTION.md](docs/EVOLUTION.md)。
> 完整 chunk / hotfix 级实施日志 → [IMPLEMENTATION_LOG.md](IMPLEMENTATION_LOG.md)。

---

## 近期计划

**Now —— v4.0.0 收口**
- 长期记忆链路真机回归 + friend-test(验收门,CC 不自证)
- Stage3 Tauri 打包 / dmg / dogfood / tag

**Next**
- **demo 视频**(锁定里程碑,作品集核心交付)
- **角色机制 Brick 1+2** —— 状态读回 + DailyAgent 切片(见下「核心专项」)
- **新角色 TTS:Fish 挂载** —— Fish S2-Pro provider + 可插 provider 层**已通**(GSV / CosyVoice / Fish);Next = 给新角色真挂上 + per-character 选择验收
- **第二个独立角色(`cid=100`)** —— 完整 persona + 立绘 + 音色(先挂 Live2D + 默认,全套后续)
- **图片输入持久化** · **桌面写控件确认门验证** · **七角色真 persona** · **记忆架构 v2 + RAG 第 4 层**

**Later**
- **角色机制 Brick 3+4** —— 状态加规则 + 上下文仲裁(见下)
- **Persona Schema v2** —— 修死字段(`relationship_to_user` 等 load 了不进 prompt)+ 文档漂移 + 借交换式 voice_samples;详 [docs/research/persona-schema-comparison.md](docs/research/persona-schema-comparison.md)
- **persona-level learning** · **屏幕视觉 VLM** · **多模态图片输出(ComfyUI)**
- **Live2D AI 导演 + 贴纸系统 + 公参表** · **Cubism5** · **整体 UI 升级**
- **messaging gateway**(Telegram / Discord)· **凭证进系统钥匙串** · **DESIGN_LITE 更新**(单独 pass)

---

## 当前能力状态

> 🟢 已验 · 🟡 在做 / 已建未验 · 🔴 有 bug · 🔵 想升级 · ⚪ 计划 / 未实现。状态回代码核。

### 角色(= 核心「角色机制」)
- 🟢 Persona 五层框架
  - 🟢 Tier-1(身份 / 性格 / 语气)+ Tier-2(禁忌 / 设定 / 情绪触发 / voice samples)+ 多 variant
  - 🟢 Mai(`cid=1`)完整 persona(参考实现)
  - 🟡 第二个独立角色搭建中(`cid=100` 槽位,Live2D 挂上、默认;人格 · 音色 · 立绘后续)· `cid=101` = Mai 日语变体(独立)· ⚪ 其余空骨架
- 🟡 角色状态层(FSM)—— **弱 / 花架子**
  - 🟡 mood / intimacy / current_activity / current_thought 字段 + `<state_update>` 写入
  - 🟢 intimacy 每日衰减 cron
  - ⚪ 规则演化 · 🟡 状态部分读回(C4 段已注入 mood/intimacy/activity,影响力 / 范围待评)
- 🟡 DailyAgent(连贯的一天)—— Stage1 + 立绘馆日程 viz 已建,HOLD 未验;设计 → [docs/design/dailyagent-plan.md](docs/design/dailyagent-plan.md)
- ⚪ 上下文仲裁(状态 + 输入 → 反应)
- ⚪ persona-level learning
- 🟢 角色详情中心(立绘馆内看 persona / 心情 / 状态 + 编辑 persona)
- 🟢 多角色 conversation 锚定(切角色不串台、回复不丢)

### 记忆
- 🟢 短期记忆(用户 / 角色 / 对话 三级隔离 + 滚动摘要)
- 🟡 长期事实记忆(事实抽取 + 遗忘曲线 + 墓碑,代码核验;陪伴质量待真机回归)· ⚪ RAG 第 4 层
- 🟢 用户画像(跨角色一份印象)· 🟢 活动时间线(30 天,可被角色引用)
- ⚪ 记忆架构 v2(一角色一永久对话流)

### 对话
- 🟢 语音 / 文字皆可 · 🟢 逐句流式(文字 + 按句音频)
- 🟢 tool 调用过渡话 + loading pill(不卡 30s 沉默)
- 🟢 assistant 说话时自动静音 mic(防回声)
- 🟢 深度思考 / 联网双开关(聊天框 + 设置双入口,默认关思考求快)
- 🟢 聊天气泡本地时间戳

### 多模态(输入 / 输出)
- 🟢 语音输入:VAD(silero,阈值可调)/ 手动录音 / 本地 whisper ASR + 实时回显
  - 🔴 手动模式偶发"麦还在听"间歇 bug(诊断仪器已就绪)
- 🟢 语音输出 TTS:多 provider(GSV / CosyVoice / Fish)+ per-character 选择;自训 `mai_v4`(本地,16 情绪,ja);文本 / 语音语言解耦
  - 🔵 字幕恒中文 → 多语言
- 🟢 文件输入 / 输出
- 🟡 图片输入(传图 → 喂当前主模型;⚪ 持久化:现仅存"[图片]"占位,重启丢图)
- ⚪ 图片输出(接 ComfyUI / anime)

### Live2D
- 🟢 表演层(待机微动 / 转头看你 ±15° / 眨眼呼吸 / 口型同步)
- 🟢 模型管理(多模型可换 + 扫描接入,Cubism 4)· 🟢 取景层(构图缩放 / 移动)
- 🟡 情绪 → 表情(`<emotion>` 驱动)
- 🟡 角色台词气泡:🟢 桌宠(widget)已上 · 🟡 大窗(panel)暂关留复活
- ⚪ 统一管理:动作库 + 选择策略 · AI 导演(一情绪同调 动作+表情+贴纸)· 原创贴纸通道 · 公参表
- ⚪ Cubism5

### 桌面感知 / 控制(UIA)
- 🟢 文本级屏幕感知(active app + 浏览器 URL + 页面正文,19 条隐私黑名单)
- 🟢 只读 AX 读屏(`read_current_screen`,macos-use,06-21 真机验)
  - 🔴 self_frontmost 大小写 bug(Skyler 前台会读自己的树;一行修待 build)
- 🟡 桌面写控件(macos-use 8 工具:click / type / open / scroll / ...)
  - 🟢 已建 + DB enabled + ChatAgent 可调
  - 🟡 确认门 model-driven 触发**未验**(安全门)
- ⚪ 屏幕视觉 VLM(AX 盲区 fallback)

### 主动陪伴
- 🟢 到点问候(早 / 午 / 晚 / 睡前,trigger pack)
- 🟢 活动触发(快路径分类 + 慢路径 LLM judge)
- 🟢 防滥用(多重 throttle + daily cap + idle 闸)
- 🟡 据角色状态搭话(待角色机制深化)

### 工具 / MCP
- 🟢 MCP 双向(client 消费外部 server + server 暴露自身能力)
- 🟢 服务器搜索 + 别名 · 🟢 per-tool 开关 + dangerous_tools gating(框架)
- 🟢 内建集成:日历(Apple + Google)/ 网易云 / B站 / 文档读写 / 剪贴板 / 小红书(只读)/ Notion
- 🟢 web 搜索(模型内置,可开关)
- 🟢 危险操作二次确认门(框架在;model-driven 写触发未验)
- 🟡 凭证明文 → ⚪ 进系统钥匙串
- ⚪ 图片生成(ComfyUI)· ⚪ skill 系统

### UI / 界面
- 🟢 双模式(大窗 Panel / 透明桌宠 Widget)· 🟢 进入动画(4 路健康 gate)
- 🟢 立绘馆(发牌入场 + 角色详情)· 🟢 浮玻璃陪伴态(玻璃外观自定义,对比度可调)
- 🟢 8 套主题 · 🟢 全局壁纸(跟角色解耦)· 🟢 系统状态浮层
- 🟢 各管理面板(MCP / Live2D / 角色 / 音色)· 🔵 整体视觉升级

### 可观测 / 启动
- 🟢 用量 / 资源 / 启动耗时监控 + 异常高亮 · ⚪ 成本面板 + 缓存命中率
- 🟢 启动健康检查(embedding / whisper / ws / live2d 四路 gate)· 🟢 持久"上次角色"· 🟢 Tauri 框架
- ⚪ dmg 打包 / 自动更新 / CI release

---

## 核心专项:角色机制(角色判断状态机)

> 项目最核心的差异化方向 —— 把现在"弱 / 花架子"的角色状态,做成一套真正驱动反应的**判断管线**:
> 感知 / 输入(UIA · 活动 · 用户消息)→ 状态(persona + FSM + DailyAgent)→ **上下文仲裁(判断)** → 反应。
> 完整管线设计 → `docs/design/character-mechanism.md`(本节只列"做什么 + 什么时候")。

分四步走,emergent 不 big-bang(每块基于已有砖):

| Brick | 内容 | 阶段 |
|---|---|---|
| **1 · 状态真读回** | mood / current_activity 进 prompt、真影响生成(最便宜的第一步) | Next |
| **2 · DailyAgent 最小切片** | 每天生成连贯日程 → ticker 驱动 current_activity(Stage1+viz 已建,HOLD;设计 [dailyagent-plan.md](docs/design/dailyagent-plan.md)) | Next |
| **3 · 状态加规则** | mood / energy 衰减 / 转移,成真 FSM | Later |
| **4 · 上下文仲裁** | 状态 + 输入 → 判断当下该有的反应(判断管线的"判断点")| Later |

> 前置:CC 先只读 dump `character_states` 现状(状态是否读回生成),定 Brick 1 是"补"还是"从头"。

---

## 已知问题 / 技术债(摘要)

> 完整列表 + 历史债 → [IMPLEMENTATION_LOG.md](IMPLEMENTATION_LOG.md)。本节只列当前活跃大项。

- **桌面写控件确认门未验(安全)** —— 8 写工具当前 enabled,但"LLM 主动调写工具时确认 modal 是否弹"从未验证。定姿态前建议默认关。
- **`screen.py` self_frontmost 大小写 bug** —— Skyler 前台问"看屏幕"会读自己的树;一行修待 build + 验。
- **Persona schema 死字段** —— `relationship_to_user`(必填)/ `capability_overrides` / `style_preset` load 了但 0 模板引用;skill 文档与真实列漂移。归 Persona Schema v2,详 [研究报告](docs/research/persona-schema-comparison.md)。
- **图片无持久化** —— 重启后历史只剩"[图片]"占位。
- **VAD 手动模式"麦还在听"间歇 bug** —— 表层根因已修两个,仍偶发;诊断仪器已就绪待复现。
- **长期记忆陪伴质量未验** —— 代码核验完成,待真机回归 + friend-test。
- **GSV 中文音色跨语种漂(🔴 未决)** —— 本地链路 ship,但中文文本喂 ja-训练的 `mai_v4`,音色仍飘(跨语种音素漂移);新角色走 Fish 部分规避。
- **GSV ops 坑** —— server 重启重置 `tts_infer.yaml` 到 CPU(需 SSH 修);失败 latch `FAILED_KEYS` 需双重启恢复。

---

## 端点迁移

回国后从国际 DashScope 迁到国内百炼端点(`dashscope.aliyuncs.com`),账号 / Key 不通用。

---

## 历史

版本 × 功能演进 → [EVOLUTION.md](docs/EVOLUTION.md)。完整实施日志(每个 chunk / hotfix)→ [IMPLEMENTATION_LOG.md](IMPLEMENTATION_LOG.md)。
