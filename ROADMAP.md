# 🗺️ Skyler Roadmap

> Skyler 是一个**可塑型 AI 角色容器** —— 桌面端、角色驱动、能拆到 agent 内核、所有权归你。这条路线图按四条支柱组织,版本号 / chunk 罗列见末尾 [Implementation Log](#implementation-log-historical)。

> **状态(2026-05-16)**:v4-beta 收口阶段。Persona Engineering 五层框架 + 记忆/对话三级隔离 + conversation 锚定绑定语义 + 对话 UI 统一已 ship 并真机验证。当前主推 Mai 单角色纯中文陪伴,剩余 v4.0.0 收口项见下方 Now。

**Legend**: ✅ shipped · 🚧 in progress · 📋 planned · 🔬 research

---

## Now — v4.0.0 收口

目标:把一个角色(Mai)做扎实再 ship,而不是铺开七个半成品。剩余 v4.0.0 项按序走完即 tag。

> v4-beta 收口批次(2026-05-16)的"本 session 已 ship 并真机验证"7 行成就清单已剥离归档至 [IMPLEMENTATION_LOG.md](IMPLEMENTATION_LOG.md)(2026-05-19 docs 第二刀)。

### 本 session 已 ship（2026-05-19）

| Status | Item | Notes |
|---|---|---|
| ✅ | 左侧 ConversationList 右边缘可拖拽 resize handle | commit `60dea57` (2026-05-19);改 4 文件:store/index.ts / Panel.tsx / ConversationList.tsx / ChatHistoryPanel.tsx 中 2 个;新增 `momoos.convListWidth` localStorage,clamp [160,400] |
| ✅ | 右侧 ChatHistoryPanel 左边缘可拖拽 resize handle | commit `60dea57` (同上);新增 `momoos.chatHistoryWidth` localStorage,clamp [320,600];立绘区 flex-1 min-w-0 +Live2D ResizeObserver 自动响应 |
| ✅ | docs 整理轮(归档第一刀 + 真源对齐第二刀 + 索引登记) | commit `dcd3327` (2026-05-19);19 份归档至 docs/archive/(R100 零字节改动) + 5 真源对齐(死链/退役同步/HEAD 锚点 c1d65ff) + INVESTIGATION-2/INDEX 登记 |

### 剩余 v4.0.0 收口项(按序)

| Status | Item | Goal | ETA |
|---|---|---|---|
| ✅ | **文档纠真(v4.0.0 记忆线收口)** | DESIGN / DESIGN_LITE / ROADMAP / README / README_zh-CN 对齐 v4.0.0 现状 + §5.8 表层债入册;DESIGN.md 大整合(双层保留 / 旧"当前"标签 / chunk 章收并)立项留待表层重构 pass | ✅ 完成 |
| ✅ | **长期记忆链路 audit + 修复链** | audit 完结(根因=抽取 prompt 偏 fact-only + 闲聊→LLM 合法返回 [];子 bug=purge 不重置 extractor 指针)。修复链已 ship:滚动摘要层 b91505a + 902c2c2/f712625/42d1800/bfcd821/3f3be08。**代码对真 git diff 已核验;陪伴/功能质量待真机回归(验收门,CC 不自证)**。详 DESIGN §五·补 + §十五之 Z.5.1 | ✅ ship,待真机回归 |
| 📋 | TTS 每用户日字数 cap + 主对话节流 | 防 dogfood 期间烧 DashScope;per-user daily char cap + main chat throttle | ~0.5 day |
| 📋 | Stage3 — 打包发布 | Tauri build + .dmg + onboarding + dogfood + tag v4.0.0 | ~2-3 days |

> **chunk 15 / UX-006 关闭说明(保留历史结论)**:UX-004 v1 曾实测某些环境体感 23s 沉默。经 4 阶段 audit + 关 VPN 真机实测,backend producer/consumer + chunk 6b TTS pipeline 已实现 sentence-by-sentence streaming,过渡语 + 最终回复语音流畅。"23s 沉默"推测为 VPN + 第一次冷启 tool 叠加偶发,非架构问题。本 session 真机复测再次确认无感知沉默。详 `docs/archive/chunk-15-*`。

> **原 v4-alpha「可塑性易用」清单(Stage 2 纯前端管理资源 / chunk 13 test isolation / skill docs / Live2D swap guide / plugin registry seedling)整体下移 v4.1+**:v4-beta 收口聚焦"一个角色做扎实",可塑性打磨让位于陪伴质量。明细见 Tech Debt & Backlog。

---

## v4.1 — Mai 之外 + 语言/记忆根治

v4.0.0 tag 之后的主线。本 session 多个"治标 vs 治本"的决策都把治本压到了这里,集中一次做对。

| Status | Item | Goal | Notes |
|---|---|---|---|
| 📋 | **F0 — ja 后处理翻译重做** | 停掉 seg2-x 补丁路线,改架构:LLM 出纯中文 → TTS 前 qwen-turbo 翻日 → CosyVoice。把"LLM 实时自己交替标 ja"这个不确定性彻底移出链路 | ja 链代码 v4-beta 已保留休眠,F0 直接复用 |
| 📋 | **F1 — 七套角色真 persona** | `cid` 2/3/4/5/99/100 灌完整 persona(仿 `docs/mai_prompt.md` 的 Tier-1+2 规格)。当前除 Mai 全是空骨架 | persona-builder skill 已就绪 |
| 📋 | **F2 — 切角色对话联动收尾** | Bug Y 切角色→对话联动放大器残余(部分已随 UI 统一的 fetchMessages 补掉),收尾 | 部分已随 v4-beta UI 完成 |
| 📋 | **F8 — 长期记忆归属分级** | fact/profile → user_shared;event/关系型 → character_private(按 character_id);short_term 已 conv 隔离。**v4.0.0 audit 已完结、链路修复链已 ship(代码核验,功能待真机回归);"有没有"已解决,F8"分级"仍 v4.1** | v4.0.0 audit 已出结论,F8 解锁 |
| 🔬 | **记忆架构 v2(陪伴洞察)** | 一角色一永久对话流(非工具型多对话/新对话范式)+ 近期 short_term 原文 + 远期 RAG;"重来"靠显式清空非新对话。与 F8 统一设计 | 陪伴本质的架构终局,v4.0.0 不重构以免拖死 ship |
| 📋 | LLM 性能 | qwen3.6-plus 本身慢 + 网络;绑定锁死后"慢"与"串"已解耦,纯体验问题,独立优化(模型选型 / 流式 / 预热) | 不混进功能修复 |
| 📋 | CosyVoice WS 弱网超时 | 建链 5s 超时(SDK 写死)弱网失败;重试包装 / SDK 升级 / streaming_call | 生产复现触发 |
| 📋 | 测试债清理(原 chunk 13) | 遗留 7 个 **import-死符号断测**(test_chat_agent / test_database / test_llm_client / test_memory_agent / test_ws_helpers / test_memory / test_integration,v2.5-B/v3-C 时代 import 已删符号,**与功能无关**)+ fixture 隔离 + 全套 pytest 跑通。**注:`test_long_term` 不在这 7 个内,它是 Z.5(memory 0 行)的现成 repro,属 v4.0.0 critical,见下方收口批次** | 从 Now 下移 |
| 📋 | 可塑性易用清单(原 v4-alpha Now) | Stage 2 纯前端管理三类资源 / skill docs+examples / Live2D swap guide / plugin registry seedling | v4-beta 让位陪伴质量,v4.1+ 接回 |
| 📋 | **Persona 蒸馏重构（Mai 为先）** | 现 persona 把防御层（讥讽/调侃/话少）当人格本体写成常量，缺底色层与切换规则。重构方向：①补内核底色（被审视的孤独 + 对真实连接的隐秘渴望）②防御层标注为试探机制非本性 ③讥讽/话少由常量改为随对方真诚度变化的变量。蒸馏纪律：素材驱动、写约束非形容词、少而硬、给正反例 | 前端整理后启动 |
| 📋 | **八重 UI 线** | 八重神子(cid=2)的真 persona 灌入 + Live2D yae 模型已就位的前端联动 / 切换体验细化（属 v4.1 F1 七套角色真 persona 的优先一员）| 立项 |
| 📋 | **token 治理一轮** | INVESTIGATION-2 性能弹药已就绪:工具懒加载(被动池 + 主动细化,理论可省 9-10k tokens 但风险高,见 §5 懒加载地形)/ persona 字段裁剪(500-1500 tokens)/ history 窗口收缩(~600 tokens)/ ADDENDUM 压缩(74 tokens 收益微小)。优先级 / 取舍待人工拍板 | 立项 v4.1 |
| ✅ | **prompt caching 启用**（path F · Qwen system 段，已 ship 2026-05-20） | `EXPLICIT_CACHE_PROVIDERS` 白名单 + `_inject_cache_marker` + `config.yaml prompt_caching.enabled` flag；切 `dashscope/` prefix；main_chat 真机 cold/warm cache 命中实证（WARM 5,655 cached_tokens / 99.8% 覆盖率），生产 ~27% prompt 价省；T4 实证 Qwen tools= cache_control silently strip → ROI 缩水到 ~27%（vs brief 假设 67-83%）；T5 实证 DeepSeek 自动 caching 含 tools= 96.4%，路径 D（切 DeepSeek 全量 ~75% ROI）留 v4.1 A/B 评测候选。详 INV-5 §5 |
| 📋 | **docs 第二刀(本刀真源对齐)** | 5 份真源 + 死链 + 退役同步 + HEAD 锚点 + 本会话新成果补录,2026-05-19 执行 | 进行中 |

---

## Next — 补诚实承认的缺口

[README §Comparison](README.md#comparison) 和 [§What Skyler is NOT](README.md#what-skyler-is-not) 列出来的缺口,逐条挪到 roadmap。Hermes 已经验证可行,Skyler 没做不是不该做,只是优先级。

| Status | Item | Goal | ETA |
|---|---|---|---|
| 📋 | Messaging gateway POC | Telegram bot 起步,跟桌面 Skyler 共享 character + memory | ~3-5 days |
| 📋 | Training data export | "用你跟 Momo 的对话训练你自己的小模型"—— SFT / DPO 格式 + PII sanitizer | ~2-3 days |
| 📋 | Capability marketplace | GitHub Pages 起步的社区 skill 索引,PR-based 提交 | ~1-2 weeks |

---

## Later — Persona-level learning

Hermes 的杀手锏是 self-improving skill loop(skill 越用越好)。Skyler 不直接 copy,而是把同样的"系统会变好"应用到**角色这一层**:

| Status | Item | Goal | ETA |
|---|---|---|---|
| 🔬 | character_states evolution | 让 mood / intimacy / activity 长期演化形成角色 pattern(不是 hardcode 规则,是 LLM 推断出的偏好)| research |

具体形式还在探索:可能加 derived field 记 pattern signal 做小步实验,再决定要不要 invest big。这是 Skyler 长期对 Hermes self-improving 的**差异化版本** —— Hermes 让 agent 更能干,Skyler 让 agent 更像一个具体的人。

---

## Long vision

桌面端建立一个**小而忠诚的可塑型 AI 角色容器爱好者生态**。

- 几百到几千的核心用户,每人都改 / 扩展 / 持有自己的版本
- 一个分散但活跃的 skill / character / Live2D 模型生态
- 不卖订阅、不卖模型、不收数据
- 衡量成功不是 GitHub star,是"有多少人真的把 Skyler 当成自己的角色用了一年以上"

不追求大众化。不参与 VTuber 直播 / Agent 框架 / 通用助手任何一个赛道的直接竞争。

### 长期技术能力扩展

支撑上面愿景的基础设施。这些是真长期项,不在 12 个月窗口内。

| Status | Item | Goal | Notes |
|---|---|---|---|
| 🔬 | autodl 部署 + sub-agent 隔离 | 长任务跑独立 context 不阻塞主对话;云端 GPU 跑 fine-tune | 借鉴 Hermes 多执行 backend |
| 🔬 | GPT-SoVITS 后端接通 | 替换 / 补充 CosyVoice,接通自训音色路径 | 依赖 autodl |
| 🔬 | 自定义 voice 训练 | CosyVoice fine-tune + GPT-SoVITS 角色专属模型 | 用户自训 + 接进 Skyler |
| 🔬 | 多设备 / 跨平台 | iPhone / iPad 同步;Windows 客户端 | v6+ |
| 🔬 | 工作模式 + Toolset by Mode | 引入 `Mode.WORK` 显式用户触发；按 Mode 切 toolset 子集（roleplay / proactive / work 各自只看到必要工具）；schema 经济上最低成本的运行态 | 远期立项，需先完成 v4.1 token 治理一轮后单独议 |

---

## Tech Debt & Backlog

按领域分类的活跃技术债。chunk 13 会一次性处理测试相关,其他逐条按优先级。

| Area | Item | Status |
|---|---|---|
| 性能 | `_build_messages` 退化(chunk 1.6 4ms → v3-H chunk 1 4487ms,1000x)—— 嫌疑某 capability 在 prompt 注入做昂贵 IO | audit 待 |
| 数据架构 | Characters 双源(`characters.yaml` + DB)—— 当前 Plan B(DB persona 为主源 + YAML fallback);Plan C(删 yaml、DB 单源、迁移导入、`switch_character`/`prompt_manager` 改 DB-backed)deferred | v4 后期 / v4.1 |
| 数据架构 | `config.yaml` 双写源 —— 静态 / 运行时拆,运行时进 DB 表 | v4 后期 |
| 配置 | git update-index --skip-worktree config.yaml 当前 workaround,升级方案 A `config.local.yaml` 覆盖 | backlog 30 min |
| 角色 | `cid=1`=Mai(借 Momo 壳 + Hiyori 模型,樱岛麻衣 persona,v4-beta 唯一真 persona);其余 `cid` 空骨架,v4.1 F1 逐个灌真 persona | F1(v4.1)|
| 记忆 | 长期记忆链路 audit 完 + 修复链已 ship(b91505a/902c2c2/f712625/42d1800/bfcd821/3f3be08;代码核验)—— 功能/陪伴质量待真机回归(验收门) | ✅ ship,待真机回归(详 DESIGN §十五之 Z.5.1)|
| 记忆·表层 | 异构表 facts+提醒未拆(`memory` 混存 `expires_at` NULL 持久事实 + 有值时效提醒) | 表层重构 pass(立项) |
| 记忆·表层 | 双 type 列 cruft(`type` 5 类 CHECK / `entry_type` 4 类并存,各有真消费者) | 表层重构 pass(立项) |
| 记忆·表层 | supersede 自身机制未实现(新旧事实共存,不替换) | 表层重构 pass(立项) |
| 记忆·表层 | `expires_at` 未正经接线(signature 接受但 caller 全传 None) | 表层重构 pass(立项) |
| 记忆·表层 | 墓碑 check 无类型感知(可能误压合法重建的新提醒) | 表层重构 pass(立项) |
| Live2D | Hiyori 缺挥手/点头/鞠躬;motion3.json 自带 wav 默认禁用,未来 per-character 开关 | 切模型时重写 |
| Live2D | emotion 视觉绑定阻塞于 `.exp3.json` 模型资产(外部依赖) | 外部 |
| 音色 | cosyvoice WS 建链 5s 超时(SDK 写死)—— 弱网失败;修法重试包装 / SDK 升级 / streaming_call | 生产复现触发 |
| 音色 | Phase 2 自训音色(SoVITS / 微调 cosyvoice3) | 用户训练完成 |
| 凭证 | `mcp_credentials` 明文存 —— 升级 OS keyring / master password 派生 | backlog |
| 字幕 | 超长 B 站字幕分段总结(>30k 字符)—— map-reduce 风格 | 200k context 够时延后 |
| 工具链 | skyler CLI thin client(替代 MCP 对外接口的更轻方案) | chunk 13 后 |
| TTS 错误 | TTS timeout idx=1 偶发(chunk 14 chime in 文本到 widget 但语音没出) | 调 timeout / audit ws push 时机 |
| Observability | 推送延迟 metric:ws.py audio_consumer send_json 前后打 perf_counter,记录每段 audio push_latency_ms + size_kb 到 log,便于 dogfood 期间快速定位音频沉默根因(chunk 15 audit 副产物) | v4.1 nice-to-have 2-4h |
| Stage 2.2 Live2D e2e | 2.2.0 backend 29/29 + 2.2.1 frontend yarn build pass,但真机拖 .zip 完整 flow 未测(用户当时无合适 sample model)。补 5 scenario:拖 valid zip / 拒非 zip / slug 冲突重试 / 应用 / 跳过 motion_map / Live2DCanvas 渲染验证。**风险**:CC 没真机验证 Tauri WebView 上传链路,可能有 MIME / fetch 边角问题;dogfood 期间用户拖会自然暴露,补时机最佳 | v4.1 0.3-0.5d |
| Fan UI Vitest + 视觉回归 | Fan-1 backend 34/34 已覆盖,但 frontend 全跳过 Vitest(Fan-2~5 走真机走查通过)。补:CharacterCard / FanLayout(geometry math + windowed mode + click shortest path)/ CharacterGallery(state machine browse↔detail / Esc / CTA → close)/ SplashArtDropzone(MIME/ext fallback / size limit / replace flow)。视觉回归用 Playwright snapshot 抓 fan @ N=4/5/7/10、detail open、bg cross-fade 中段。**理由**:6 个 sub-stage 每次都靠用户真机走查,迭代成本高;Vitest 套件让 layout 数学回归(stepDeg / shortestDelta / fade)瞬间发现 | v4.1 0.5-1d |
| Fan UI tagline / interests | Fan-4 detail modal 的字段缺位决策 backlog:DB schema 加 ``tagline`` / ``interests``(JSON tags) → CharacterPanel 加编辑表单 → DetailModal 渲染。当前 detail 只显示 name / persona / character_state, 用户实测后若觉得"信息少"再补 | v4.1+ backlog 0.5-1d |
| Skill UI | Skill .py 拖入 + 一键重启(Stage 2 原 2.3,推 v4.1+):跨 framework skill 不兼容(详 [stage-2-starting-context.md §5.1](docs/archive/stage-2-starting-context.md)),90% "装别家 skill" 场景由 MCP(Stage 2.1)覆盖;.py 拖入主要价值在 Skyler 社区共享 capability,需早期用户 base 形成后再做 | v4.1+ backlog ~5-7d |
| Skyler-as-MCP-server | 让 Skyler 自身暴露成 MCP server,把 character_state / activity timeline / Live2D control / memory 等 capability 暴露给其他 MCP-compatible 工具(Claude Desktop / Cursor / Cline 等),让 Skyler character 跨工具可见可引用。**理由**:跨 framework skill 市场调研后,MCP 已是事实标准——各 framework 都出 MCP adapter,Skyler 从 MCP client 升级为 MCP server 是差异化方向 | v4.1+ backlog 待估(可能 1-2w)|
| Frontend | UX-003 情绪 UI absolute viewport 锚定 bug(left: 16px 可能被父容器影响) | backlog 15 min |
| Display name | wpsoffice 缺中文 display name(`_APP_DISPLAY_NAMES`)| backlog 5 min |
| URL fetch | bilibili url_fetcher 5s 超时(反爬虫/UA/timeout 调整)| backlog 30 min |

### 遗留测试债

下列测试文件在 v3-F 接手前已经断开,import 早已删除 / 改名的符号。chunk 13 测试 pollution 修复时一并处理。

| 文件 | 失败原因 | 引入版本 |
|---|---|---|
| `tests/test_chat_agent.py` | `upsert_personality` 函数已删 | v2.5-B |
| `tests/test_database.py` | 同上 | v2.5-B |
| `tests/test_llm_client.py` | `DEFAULT_MODEL` 常量改名 | v2.5-B |
| `tests/test_memory_agent.py` | `_personality_to_dict` 已删 | v2.5-B |
| `tests/test_ws_helpers.py` | `_run_plan` PlannerAgent 简化时移除 | v3-C |
| `tests/test_memory.py` | `SHORT_TERM_MAX is 20` 断言过期 | v2.5-B |
| `tests/test_integration.py` | 集成 fixture schema 已变 | v2.5-B |

---

## Not on the roadmap(明确不做)

避免后续想法漂移。

- ❌ **群聊(多角色同时对话)** —— 跟单角色驱动定位冲突
- ❌ **Bilibili 弹幕直播客户端** —— 直播场景,跟桌面角色 agent 定位无关
- ❌ **Letta / MemGPT 等独立 memory 系统** —— 现有 SQLite + sentence-transformers 已够用
- ❌ **WhatsApp / WeChat gateway** —— API 限制 + 商业风险(注:Telegram / Discord 在中期 roadmap,不在禁做列表)
- ❌ **Linux Wayland 完整支持** —— 技术上几乎做不了
- ❌ **系统操作 agent(鼠标键盘控制)** —— 跨平台 + 安全代价太高
- ❌ **跟 LangChain / AutoGen 比拼通用 agent 框架** —— Skyler 是角色驱动的桌面 agent
- ❌ **Settings 全局 TTS 开关** —— 只在 CharacterPanel 上 per-character 提供
- ❌ **TTS UI 提前堆假选项** —— 下拉只显示真实可用的 voices

---

> 历史实现日志已外迁至 IMPLEMENTATION_LOG.md
