# 🗺️ Skyler Roadmap

> Skyler 是一个**可塑型 AI 角色容器** —— 桌面端、角色驱动、能拆到 agent 内核、所有权归你。这条路线图按四条支柱组织,版本号 / chunk 罗列见末尾 [Implementation Log](#implementation-log-historical)。

> **状态(2026-05-16)**:v4-beta 收口阶段。Persona Engineering 五层框架 + 记忆/对话三级隔离 + conversation 锚定绑定语义 + 对话 UI 统一已 ship 并真机验证。当前主推 Mai 单角色纯中文陪伴,剩余 v4.0.0 收口项见下方 Now。

**Legend**: ✅ shipped · 🚧 in progress · 📋 planned · 🔬 research

---

## Now — v4.0.0 收口

目标:把一个角色(Mai)做扎实再 ship,而不是铺开七个半成品。本 session 已把多 session 的硬仗(语言/记忆/绑定/UI)全部收口并真机验证;剩余 v4.0.0 项按序走完即 tag。

### 本 session 已 ship 并真机验证(v4-beta 收口批次,2026-05-16)

| Status | Item | Goal |
|---|---|---|
| ✅ | 回退纯中文 | Mai `cid=1` `tts_language=zh` + voice `longyumi_v3`,人格不动;ja 链代码保留休眠 |
| ✅ | 记忆/对话串台根治 | short_term 升级 (用户,角色,conversation) 三级隔离 + 重启按 conv 过滤恢复 |
| ✅ | conversation 锚定绑定语义 | 规则 A(用户发起锁定 conv,响应无条件回原对话)+ 规则 B(主动消息投递前校验,过时丢弃) |
| ✅ | character_switch 不杀 in-flight turn | 切角色帧不进 turn 调度,进行中回复跑完不被 cancel |
| ✅ | 对话 UI 统一 | 删右上历史入口 + 删旧台词气泡;左 conv list + 右 chat panel 双推拉;全收起 Galgame 沉浸;<1280px 降级 |
| ✅ | token 成本治理 | short_term cap 30 turn(修法 A)+ tool_result 截断 4000(修法 B) |
| ✅ | 测试不污染主库 | 26+ 测试改 in-memory,清掉污染数据;short_term per-(user,char,conv) 隔离回归 139 passed |

### 剩余 v4.0.0 收口项(按序)

| Status | Item | Goal | ETA |
|---|---|---|---|
| ✅ | **文档纠真(v4.0.0 记忆线收口)** | DESIGN / DESIGN_LITE / ROADMAP / README / README_zh-CN 对齐 v4.0.0 现状 + §5.8 表层债入册;DESIGN.md 大整合(双层保留 / 旧"当前"标签 / chunk 章收并)立项留待表层重构 pass | ✅ 完成 |
| ✅ | **长期记忆链路 audit + 修复链** | audit 完结(根因=抽取 prompt 偏 fact-only + 闲聊→LLM 合法返回 [];子 bug=purge 不重置 extractor 指针)。修复链已 ship:滚动摘要层 b91505a + 902c2c2/f712625/42d1800/bfcd821/3f3be08。**代码对真 git diff 已核验;陪伴/功能质量待真机回归(验收门,CC 不自证)**。详 DESIGN §五·补 + §十五之 Z.5.1 | ✅ ship,待真机回归 |
| 📋 | TTS 每用户日字数 cap + 主对话节流 | 防 dogfood 期间烧 DashScope;per-user daily char cap + main chat throttle | ~0.5 day |
| 📋 | Stage3 — 打包发布 | Tauri build + .dmg + onboarding + dogfood + tag v4.0.0 | ~2-3 days |

> **chunk 15 / UX-006 关闭说明(保留历史结论)**:UX-004 v1 曾实测某些环境体感 23s 沉默。经 4 阶段 audit + 关 VPN 真机实测,backend producer/consumer + chunk 6b TTS pipeline 已实现 sentence-by-sentence streaming,过渡语 + 最终回复语音流畅。"23s 沉默"推测为 VPN + 第一次冷启 tool 叠加偶发,非架构问题。本 session 真机复测再次确认无感知沉默。详 `docs/chunk-15-*`。

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
| Skill UI | Skill .py 拖入 + 一键重启(Stage 2 原 2.3,推 v4.1+):跨 framework skill 不兼容(详 [stage-2-starting-context.md §5.1](docs/stage-2-starting-context.md)),90% "装别家 skill" 场景由 MCP(Stage 2.1)覆盖;.py 拖入主要价值在 Skyler 社区共享 capability,需早期用户 base 形成后再做 | v4.1+ backlog ~5-7d |
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

## Implementation Log (Historical)

> 下面这部分是之前以"版本号 / chunk"组织的实施记录,完整保留以便追溯。新路线图按上面四条北极星支柱组织未来工作;过去交付的具体清单(每个 chunk、hotfix、UX 迭代)在这里。
>
> 文档版本:2.0(2026-05-13 北极星支柱重组 + GitHub 风格表格)| 历史保留版本:1.5(2026-05-06)

---

### v4-beta 收口批次(2026-05-16)

> 本 session(多 session 硬仗的最后收口)交付。历史档案以下内容逐字保留;这一节是最近一段的实施记录,补在最前。

| 项 | 内容 | 关键 commit |
|---|---|---|
| 回退纯中文 | Mai `cid=1` `tts_language=zh` + voice `longyumi_v3`,人格不动;ja 链代码全保留休眠(v4.1 F0 复用) | `0e079a4` |
| 清污染 + short_term per-(user,char) 隔离 | 清测试污染数据 + short_term 按 (user,char) 分桶 | `9e434e3` `b5b0a47` |
| conversation 锚定绑定语义 | 规则 A 对话发起锁定 / 规则 B proactive 投递校验(三 commit) | `0c9c082` `cfa006c` `9039d75` |
| short_term per-conversation 过滤 | short_term entry 加 conv_id,add/get/count/clear 透传;桶仍 (user,char) 不破 path-7;`get(conv_id=X)` 严格匹配 | `eeb427a` |
| character_switch 不杀 in-flight turn | ws endpoint loop 加 `elif character_switch` 分支让进行中回复跑完;前端 chunks 附 conv_id snapshot + stale-conv 守卫 | `5766493` |
| 对话 UI 统一 | 删右上历史入口 + 删旧台词气泡 + 删 ChatHistoryDrawer;左 conv list + 右 chat panel 双推拉;切角色自动加载该角色最新对话(方案 A);全收起 Galgame 沉浸;<1280px 降级 | UI 统一批次 |
| 测试不污染主库 | 26+ 测试改 in-memory;回归 139 passed / **1 fail = `test_long_term` —— 不是"无关 pre-existing"、不是 v4.1:它是 Z.5(默认用户 memory 0 行)的现成 repro,属 v4.0.0 critical,Z.5 audit 第 0 步入口(见 HANDOFF_CORRECTIONS #2)。与上方 v4.1 那 7 个 import-死测是不同集合。** | — |
| audit 发现 | 默认用户 `memory` 表 0 行 → 长期记忆链路提为 v4.0.0 critical(非 v4.1);"删了还记得"根因 = short_term 不按 conv;"切走回复被吃"根因 = endpoint loop 对 character_switch 帧也 cancel | — |

**真机验证**:ja 错乱 / 话痨 / 串台 / 绑定竞态 / 删了还记得 / 回复被吃 / UI 混乱 —— 全部关闭。整个 multi-session 硬仗打完。

**DB 备份系列**(回退兜底):`momoos.db.backup_zh_revert_*` / `_purge_*` / `_bindfix_*` / `_2bugfix_*` / `_chatpanel_*`。

---

### 当前进度速览

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
| **v3-F'：主动对话 + 时间感知（饭点 / 睡前 / 长时无互动）** | ✅ 完成（chunk 4 Part C，2026-05-08）—— 5 trigger pack 全部上线（wake_call / lunch_call / dinner_call / bedtime_chat / long_idle） | 100% |
| v3-G：生活 & 工具型能力（剪贴板 / 简报 / cron / 成长系统） | ✅ 完成（chunks 0–4，2026-05-08） | 100% |
| **v3-G'：TTS UI 升级 + cosyvoice emotion 走 instruct（chunk 1a SSML 路径已撤回）** | ✅ 完成（5 commit + 2 patch，2026-05-06）；Phase 2 复刻音色 / SoVITS 训练 📋 PENDING | Phase 1 100% |
| **v3-H：媒体接入（网易云内置 / 媒体控制 / B站）** | 🚧 chunk 1 🟡 PARTIAL（数据查询 + 媒体控制可用；NCM 自动播放封存待 chunk 2 重做，2026-05-08）；B 站 📋 TODO | 50% |
| v4：屏幕感知 + 视觉能力 | 📋 远期 | 0% |
| **v5-D：autodl 部署 + 子 agent 隔离** | 📋 远期 | 0% |
| **v5-T1：GPT-SoVITS 后端接通（依赖 v5-D）** | 📋 远期 | 0% |
| **v5-T2：训练自定义 voice（CosyVoice fine-tune + SoVITS 模型）** | 📋 远期 | 0% |
| **v3.5 chunk 5：视觉跃迁包（背景层 + splash video）** | ✅ 完成（4 commit，2026-05-11） | 100% |
| **v3.5 chunk 6a：B 站接入（11 capability + 字幕总结）** | ✅ 完成（4 commit，2026-05-11） | 100% |
| **v3.5 chunk 6b：网易云 mpv 自解码（6 个 local_* capability）** | ✅ 完成（5 commit，2026-05-11） | 100% |
| **v3.5 chunk 6c：小红书 URL 被动解析（红线锁死）** | ✅ 完成（5 commit，2026-05-11） | 100% |
| **v3.5 chunk 7：Skill 集成 demo（docx capability + Notion MCP）** | ✅ 完成（5 commit，2026-05-11） | 100% |
| **v3.5 chunk 9：memory 性能 + 遗忘曲线 + 跨角色共享** | ✅ 完成（7 commit，2026-05-12） | 100% |
| **v3.5 chunk 10：server-side MemoryExtractor worker（治本 LLM hallucinate save_memory）** | ✅ 完成（8 commit，2026-05-12） | 100% |
| **v3.5 chunk 11：structured profile_data（治本反推词污染）** | ✅ 完成（8 commit，2026-05-12） | 100% |
| **UX-001：MCP per-tool accordion + 情绪 UI 修复** | ✅ 完成（4 commit，2026-05-12） | 100% |
| **hotfix-6：chunk 8a 切 VSCode 无主动消息根因修 + UX-001 平铺防回归** | ✅ 完成（6 commit，2026-05-12） | 100% |
| **UX-002：CapabilityPanel 67 cap 全面 accordion + 删冗余 MCP banner + calendar header 归位** | ✅ 完成（4 commit，2026-05-12） | 100% |
| **hotfix-7：proactive trigger state_update strip 漏防 + WS send 5 道兜底契约 + TTS toggle "undefined" 真因修** | ✅ 完成（5 commit，2026-05-13） | 100% |
| **hotfix-8：config.yaml duplicate block 合并 + _IDE_APPS 中文 macOS i18n + commit Info.plist + .gitignore 备份保护** | ✅ 完成（4 commit，2026-05-13） | 100% |
| **hotfix-9：get_browser_url frontmost gate(chunk 8a spec 漏洞,后台 Chrome bilibili URL 不再泄露给 stay_timer/judge)** | ✅ 完成（3 commit，2026-05-13） | 100% |
| **hotfix-10：get_active_app NSWorkspace → osascript(headless 进程 NSRunLoop 缺失导致 frontmost 永远卡在启动那一拍,backend 30 min 后仍报 app='终端')** | ✅ 完成（4 commit，2026-05-13） | 100% |
| **UX-003：CapabilityPanel 三层 accordion(category → provider → capability)+ 情绪 UI 左上角(避开历史按钮)** | ✅ 完成（5 commit，2026-05-13） | 100% |
| **v3.5 chunk 8a：简化屏幕感知（active app + browser URL + smart trigger）** | ✅ 完成（9 commit，2026-05-12） | 100% |
| **v3.5 chunk 8a-ext：智能陪伴 judge 慢路径(qwen-turbo + stay 5+ min + 共享 daily_cap)** | ✅ 完成（6 commit，2026-05-13） | 100% |
| **v3.5 chunk 8a-ext V2：macOS idle 闸(ioreg HIDIdleTime + judge 第 4 道闸,防"人不在电脑前自言自语")** | ✅ 完成（5 commit，2026-05-13） | 100% |
| **v3.5 chunk 14：activity timeline 系统(跟 chat_history 平行,session writer + Timeline API + 3 capability + ChatAgent 注入 + Drawer + cleanup cron)** | ✅ 完成（9 commit，2026-05-13） | 100% |
| **UX-005：CapabilityPanel media/music 去重(netease 单一归 music + xhs 新 social)+ SettingsPanel 剪贴板 accordion 折叠** | ✅ 完成（4 commit，2026-05-13） | 100% |
| **UX-004：tool 调用过渡语 prompt 引导 + WS tool_use_start/done event + ChatInput loading pill 文案 mapping(治"问完后 30 秒沉默"体感)** | ✅ 完成（5 commit，2026-05-13） | 100% |
| **UX-007：Momo bubble 1 min 渐进淡化(60s 100% → 5min+ 25%)+ Hover 恢复 + TTS 例外 + ChatHistoryDrawer 半透明 scrim(Live2D 始终视觉主体)** | ✅ 完成（3 commit，2026-05-13） | 100% |
| **v4-beta 收口批次(2026-05-16):回退纯中文 + short_term 三级隔离 + conversation 锚定绑定语义(规则 A/B)+ character_switch 不杀 in-flight turn + 对话 UI 统一 + token 成本治理** | ✅ 完成并真机验证（多 session 硬仗收口） | 100% |
| **v3.5 chunk 8b：完整屏幕感知（截屏 + OCR + VLM 抽象 + 浏览器扩展）** | 📋 计划中 | 0% |
| v6+：多设备访问 + Hermes 风格 skill 累积 | 📋 长期愿景 | 0% |

---

### 三梯队优先级矩阵

#### 🟢 第 1 梯队：v3 内可完成（1-3 周）

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

#### 🟡 第 2 梯队：v4 工具层 + 屏幕（1-2 个月）

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

#### 🟠 第 3 梯队：架构改造（v5 / v6+，长期）

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

### 详细执行清单

#### v3-E1：Live2D 接入（用 Hiyori 走通流程）✅ 主线完成

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

##### v3-E1 Step Z cleanup（剩余 4 条，进入 v3-E2 之前统一处理）🚧

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

#### v3-E2：多模型 Live2D 接入 ✅ 完成（2026-05-06）

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

#### v3-E3：emotion 视觉绑定真上线

⚠️ chunk 7 已经在 `Live2DCanvas` emotion useEffect 接通了 `runtime.setExpression(handle, name)`，**视觉绑定的代码路径全部就绪**。剩下的纯粹是"找一个有 `.exp3.json` 的模型 + 填该角色 `emotion_map_json`" 的运营工作，不再是技术任务。

**剩余清单**：

- [ ] **找 / 接入 / 自制有 `.exp3.json` 的目标模型** —— Hiyori / 八重 (BCSZ1.1) 都没自带 expression 文件
- [ ] **填该角色 `emotion_map_json`** —— `Record<string, string>`，emotion 词 → expression 名（CharacterPanel 编辑或直接 SQL UPDATE）
- [ ] **美术调参** —— 试每个 emotion（happy / sad / angry / surprised），不自然时换 expression / 调参数权重
- [ ] **验收**：跟角色说不同情感的话，面部有可见变化

`Live2DRuntime.setExpression` 选项 a（model.expression）已实现；选项 b（参数偏移）需扩 runtime 接口加 `setParameter(id, value)`，未来需要时再加。

**估时**：1 天（有 `.exp3.json`）/ 2-3 天（自制偏移）。

---

#### v3-F：语音体验飞跃

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

#### v3-F'：主动对话 + 时间感知

让 Momo 不只是被动回应，而是主动开启对话（饭点 / 睡前 / 长时间无互动等情境）。

**🎯 当前状态（2026-05-08）：通用 proactive engine + 模式 A/B 哲学已就位（v3-G chunk 2 + 2.6），剩余工作 = 写 N 个 trigger 配置 + 各自 prompt 模板**。
engine 流水线 `trigger → aggregate → ChatAgent → WS push` 完整跑通；wake_call stage 1/2 跨进程持久化（pending_briefings 表）也已落地。新增触发器只需新建一个文件实现 `ProactiveTrigger` 抽象（详见 DESIGN §十五之B）。
**默认 v3-F' 所有生活节奏 trigger 走模式 B**（邀请对话）；模式 A（单方面播报）保留给"非问也得通知"场景。

| trigger | 模式 | 调度 | system prompt 关注点 |
|---|---|---|---|
| ✅ `morning_briefing` | A 单方面 | cron 09:00 | 天气 / 日程 / 待办 / 闲笔 / 开放话头 |
| ✅ `wake_call_briefing` | **B 邀请** | cron 08:00 | 8-15 字叫醒 + stage 2 自适应（嗯/精神/拒绝/切话题）|
| ⬜ `meal_lunch_call` / `meal_dinner_call` | B 邀请 | cron 12:00 / 18:00 | 关心吃了什么；调 `list_memories` 拿口味偏好 |
| ⬜ `evening_wind_down_call` | B 邀请 | cron 22:00 | 一天总结 + 睡前关心；调 `calendar.today_events` 复盘 |
| ⬜ `long_idle_call` | B 邀请 | interval 30min（条件：last user turn > 2h） | 主动开口；话题源自 profile_summary |

**剩余任务清单**：

- [x] 后端定时调度器（chunk 0 APScheduler 已建）
- [x] 通用 proactive engine（chunk 2）：trigger 抽象 + character 解析 + WS proactive 协议
- [x] `chat_history.kind='proactive'` + `proactive_trigger` 字段（profile_summary 已自动排除）
- [x] 首个 trigger 上线（morning_briefing）
- [ ] 多 trigger 并发的 audio / emotion 状态隔离验证
- [ ] 用户当前 active 状态判断（Tauri 是否在前台 / 最近有交互）—— 离开时不打扰
- [ ] 频率限制（不能太烦，profile_summary 里记下用户偏好）
- [ ] 实现上面表里 3 个剩余 trigger

**估时**：每个 trigger ~半天；并发 / active 检测 / 频率限制各 ~半天。

---

#### v3-G：生活 & 工具型能力

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

**chunk 4 ✅ 完成（2026-05-08）— v3 收尾包：tool_call_resilience + clipboard 联动 + v3-F' trigger pack + Step Z 杂项 + 文档全收尾**

5 部分按 spec 优先级 A > B > C > D > E 全部落地。这是 v3 封盘最后一个 chunk。

| Hash | 内容 |
|---|---|
| `<本 commit pack>` | feat(chunk4): tool_call_resilience layer + clipboard set_enabled REST + 4 v3-F' triggers + heartbeat + legacy tag scrub + DESIGN/README/ROADMAP v3 closeout |

**Part A — Tool Call Resilience Layer（最高优先）**：

通用 fallback layer 真修 chunk 2.6 footgun 4 + chunk 3 footgun 7。`backend/agents/tool_call_resilience.py` 用 3 条 regex 扫 LLM 输出文本：
1. `<tool_call>{json}</tool_call>` (Qwen 内部 XML)
2. `<function_calls><invoke name="X"><parameter ...>` (Anthropic 风格)
3. `\`\`\`json\n{name, arguments}\n\`\`\`` (markdown 兜底)

每条命中 → 容错 JSON parse → ToolRegistry 检查 name 存在 → 真执行 + 剥离 XML 残骸。挂 ws.py 的 turn pipeline 终点（`done` 之前），cleaned_text 进 chat_history，capability 副作用真生效。**MVP 不喂 result 回 LLM**——LLM 自欺"已完成" + capability 真生效 = 用户视角无伤。同步修复 chunk 3 latent bug：`_execute_tool` 走 ToolRegistry 路径时之前不传 `character_id`，chunk 4 显式注入与 fallback 路径对称。

**Part B — Clipboard 后端联动**：

`POST /api/clipboard/enabled` + `GET /api/clipboard/enabled` 真接通 `ClipboardWatcher.set_enabled`。runtime override only（不写 yaml；重启回默认值，避免误入"持久关闭"找不到入口）。前端 `[剪贴板]` toggle 启动时 GET 同步 + onChange 真 POST，乐观更新 + 错误回滚。

**Part C — v3-F' Trigger Pack（4 个新 trigger）**：

`backend/proactive/triggers/_invite_base.py` 抽出共享的 stage 1 短句 prompt 骨架 + stage 2 addendum 模板生成器；`_stage2_registry.py` 把 trigger.name → (sentinel, addendum builder) 注册成总表，chat.py 按 `last_assistant.proactive_trigger` 分发。每个新 trigger ~30 行：

| trigger | 调度 | stage 1 例子 | default |
|---|---|---|---|
| `lunch_call` | cron 工作日 `0 12 * * 1-5` + 周末 `30 11 * * 0,6` | "嘿，饿了吗？" | enabled |
| `dinner_call` | cron `30 18 * * *` | "忙完了？要吃啥？" | enabled |
| `bedtime_chat` | cron `30 22 * * *` | "今天累不累？" | **disabled**（敏感） |
| `long_idle` | interval `5 min` 检查 + 三条件 gate | "嘿，还在吗？" | **disabled** |

`long_idle` 三条件：用户消息 idle > 30 min + 上次 proactive turn cooldown 已过 + 前端 heartbeat 显示在前台。`POST /api/heartbeat` + 前端 `useWebSocket` 在 `visibilitychange` / `focus` / `blur` 事件下 start/stop 15s 轮询。frontend `ChatHistory` + `useWebSocket` 各自加 4 个新 trigger 的灰字前缀 + toast label。**chat.py 同步小重构**：`_maybe_build_wake_call_addendum` generalize 成多 trigger 通用，gate 改为 `proactive.enabled` 而非 hardcode `mode == 'wake_call'`；`_build_messages` 的 sentinel 检测改成扫所有注册 sentinels（任一命中即跳过 stage 2 探测，防递归）。

**Part D — 3 小 cleanups**：

1. **cosyvoice EMOTION_MAP 注释**：audit 后确认注释 + 代码已一致（v3-G' 后已锁定 instruct 路径，EMOTION_MAP 仍服务 plain path 中文 → 英文 normalize）；spec 让"改注释让其与代码一致"已经一致，按 chunk 0–3 自决规则跳过 + commit msg 写明。
2. **Hiyori StrictMode m01/m05 fetch Aborted**：audit React 18 StrictMode 双 mount 路径——cleanup 已正确（cancelled flag + unloadModel 时序对齐）；warning 是 pixi-live2d-display 库内部对 motion 资产的 fetch 被 unloadModel 中断的副作用，**库行为 cosmetic 无害**。在 `Live2DCanvas.tsx` 顶部 docstring 加详细说明，让未来维护者不追幻 bug。
3. **legacy tag scrub migration**：`v3_g_chunk4_strip_legacy_tags.py` 一次性扫 `chat_history` 全表，剥离历史 `<emotion>` / `<thinking>` / `<state_update>` 脏数据。LIKE 粗筛 + Python strip + UPDATE。幂等：每行检查含标签才更新，重启时无标签行规则跳过零开销。

**Part E — 文档 v3 封盘叙事**：

- README badge 改 `v3-WIP` → `v3 ✅ complete`；Status 段重写为 v3 全交付列表 + Next Up = v4 / v5-D / v3-G' Phase 2；Project Status 表加 chunks 1.7 / 2 / 2.5 / 2.6 / 3 / 4 + v3-H chunk 1 全部 ✅。
- DESIGN §十五之E **Tool Call Resilience Layer** 设计（3 fallback pattern + 处理路径 + character_id 注入修）；§十五之F **v3-F' Trigger Pack 设计 + chunk 0 抽象的复利证明**（30+ capability + 5 trigger 全部用 3 次最小化 chat.py 改动落地）。
- ROADMAP（本节）+ v3 retrospective 见下面。

**测试覆盖**（4 新套件 + 0 回归）：

| 套件 | 通过 | 内容 |
|---|---|---|
| `test_tool_call_resilience.py` | 65/65 | 3 fallback patterns + 容错 / 不存在的 name / pattern 互斥 / character_id 注入 / e2e 真解 chunk 2.6 + chunk 3 quirk + 日志 |
| `test_clipboard_enabled_api.py` | 15/15 | GET/POST 路由 + watcher 联动 + 不持久化 / 可手动 add_item 不受 disabled 影响 / round-trip |
| `test_v3_f_trigger_pack.py` | 97/97 | 5 sentinel 全部注册 + 互不冲突 + 各 trigger metadata + stage1 prompt 8-15 字约束 + stage2 addendum 4-style 分支 + `_enabled` gate + heartbeat 路由 + long_idle 三条件 |
| (legacy strip migration 内嵌测试在 e2e 走) | — | LIKE 筛选 + idempotent 检查 + scrub 验证 |

**总计 177 新 case + 0 回归**（chunk 2/3 的 320 case 全部仍通过）。

**Footgun audit / pivots**：

* **chunk 3 latent bug 同步修复**（pivot）：`_execute_tool` 走 ToolRegistry 路径时之前没传 `character_id` → `character.set_activity` 报错。chunk 4 fallback resilience 路径必须传 character_id（capability 需要），顺手把 chat.py 主路径也修了，对称契约。
* **stage 2 addendum mode gate 太严**（pivot）：chunk 2.6 strict 检查 `proactive.mode == 'wake_call'` 才允许 stage 2。chunk 4 加了 4 个新 trigger 后这个 gate 把它们挡死了。改为只检查 `proactive.enabled` + 由 `_stage2_registry` 决定 trigger 是否注册。chunk 2.6 的测试随之更新（patch.dict 加 `enabled: True`）。
* **DB pollution across test runs**（pivot 重复 chunk 2.6/3 教训）：`character_id=1` 在 chunk 3 e2e 里被改成 mood=happy/intimacy=2，chunk 4 测试用 `character_id=1` 检查"默认值"会失败。改用 `character_id=700` 高位 ID + 显式 `reset_character_state` 起点。
* **wake_call test pending pollution**（pivot）：跨 run 累积的 unconsumed pendings 让 second-probe 测试看到旧行不返 None。在 test 头加一次性 `UPDATE pending_briefings SET consumed_at = CURRENT_TIMESTAMP WHERE user_id = 'wc_stage2_user' AND consumed_at IS NULL` 清理。
* **cosyvoice 注释和代码已一致**（spec 项已存在，跳过）：spec D-1 让"改注释让其与代码一致"，audit 后 EMOTION_MAP / `_INSTRUCT_EMOTION_WHITELIST` / `_blocking_synthesize` 三处一致。按 chunk 0–3 自决规则跳过实施 + commit msg 写明。
* **Hiyori fetch Aborted warning 是库行为**（spec 项确认 cosmetic）：cleanup 时序已正确，warning 来自 pixi-live2d-display 内部对 motion 资产的 fetch 被 unloadModel abort。封装抑制库内部 fetch 得不偿失。加详细注释说明，让未来维护者不追幻 bug。

---

### v3 封盘 Retrospective

#### 三个抽象的复利

v3 的"加新功能"成本曲线极其平缓，全因三个 chunk 0/1.5/2 早期定型的抽象：

1. **CapabilityRegistry**（chunk 0）：``@register_capability`` 装饰器 + 自动派生 OpenAI schema 同步注册到 ToolRegistry。整个 v3 共加 30+ capability，``backend/agents/chat.py`` 主体一行没改（chat 看 ``ToolRegistry.list_schemas()`` 就行）。
2. **ProactiveTrigger ABC**（chunk 2）：``trigger → aggregate → ChatAgent → WS push`` 流水线 + ``stream + 双写契约``（chat_history + short_term）。chunk 4 加 4 个新 trigger 共 ~30 行 / 个，没改 ``run_trigger``。
3. **bidirectional MCP**（chunk 1.5）：CapabilityRegistry 同时是"对外暴露"和"反向注册"的中枢。Skyler 既是 MCP server 给 Claude Desktop / Cursor 调，又是 client 反吃外部 server 的工具。`metadata.expose_via_server` 一字段就解决配额隔离 + LLM 看见控制。

#### v3 落地数据点

* **总 commits**：~50（v3 全段）
* **新 capability 数**：30+
* **新 proactive trigger**：5（wake_call / lunch_call / dinner_call / bedtime_chat / long_idle）+ 1 个 morning_briefing
* **chat.py 主体改动次数**：3（minimal）
  - chunk 2: 加 ``enable_search``透传
  - chunk 2.6: 加 ``_maybe_build_wake_call_addendum`` + sentinel detection
  - chunk 4: addendum generalize 成多 trigger 注册表 + tool resilience hook
* **测试套件**：500+ case，全程零回归（每个 chunk 都跑前置 chunk 全套）
* **footgun audit/pivot 次数**：~30（按 chunk msg 累计），核心模式 = "spec 让做的事实施前先 audit；已存在则跳过 + commit 注释"

#### 哲学小结

每个 chunk 的 prompt 都用同一套自决授权（"audit + pivot + 不需向用户申请权
限"），让模型在大型多文件改动里能自己处理 schema 变化 / 路径假设错误 /
LLM 形态变异等真实 footgun。这种"信任 model + 让它自己写 tracebackable
commit"是 v3 整段最重要的 process invariant。

#### 下阶段路线

| 阶段 | 状态 | 节奏建议 |
|---|---|---|
| **v4 屏幕感知**（VLM provider 抽象 + Tauri 截图 + 像素差预过滤 + 隐私黑名单 + 主动 / 被动模式）| 📋 远期 | 主动模式（hotkey / 语音命令）先；被动模式因隐私 / 成本风险延后 |
| **v5-D autodl 部署 + 子 agent 隔离**（Hermes #4 借鉴）| 📋 远期 | 解决用户本地 VPN / 国内直连 / GPU 训练等基础设施依赖 |
| **v5-T1 GPT-SoVITS 后端接通** | 📋 远期 | 依赖 v5-D autodl GPU |
| **v5-T2 训练自定义音色**（CosyVoice fine-tune + GPT-SoVITS 模型） | 📋 远期 | v3-G' Phase 2 真主力；依赖用户提供参考音频 |
| **v3-H chunk 2 网易云重做**（fork URL Scheme handler / 自解码 / 纯查询模式 三选一） | 📋 可选 | chunk 1 partial 状态决定的 backlog；不阻塞 v4 |
| **v3-G chunk 5 per-trigger aggregator 真实接通**（lunch / dinner 饮食 memory；bedtime 今日 review）| 📋 可选 | chunk 4 stage 2 prompt 已经引导 LLM 现查；这个 chunk 是优化项 |

---

**chunk 3 ✅ 完成（2026-05-08）— 剪贴板助手（3a）+ 角色状态面板 / 成长系统（3b）**

两个独立子模块同 commit pack，"角色感增强"主题：
- **chunk 3a 剪贴板助手**：Tauri 不动，后端 NSPasteboard 1Hz 轮询为主路径（pyobjc transitive 已含，pyperclip 跨平台 fallback）；3 个 CHAT_AGENT capability（get_recent / summarize / translate）+ ringbuffer (50 条 / 24h TTL) + content_type 启发式 + 隐私契约（仅本地内存，重启清空，不外传）。**不自动响应**剪贴板变化（设计原则）。
- **chunk 3b 角色状态面板 + 成长系统**：``character_states`` 表 + 7 mood enum + intimacy 0-100 + thought / activity 闲笔；``<state_update>`` 标签解析（**3 道剥离防泄露** + ±2 per turn delta clamp）+ system prompt 注入当前 state；3 个 capability（get_state / set_activity / intimacy_decay daily cron）；前端 ``CharacterStatePanel`` 浮动小条 + WS ``state_update`` push 类型 + SettingsPanel [角色状态] section。

| Hash | 内容 |
|---|---|
| `<本 commit>` | feat(chunk3): clipboard integration + capabilities + character_states DB + state_update parser + cron decay + frontend panels + 5 test suites + docs |

**架构关键点**：

1. **mood vs emotion 双层模型**（chunk 3b）：`emotion`（per-turn 瞬时，TTS / Live2D 用）vs `mood`（跨 turn 累积，状态条 / 后续 prompt 用），独立不冲突。同一句 LLM 输出可同时含 `<emotion>` + `<state_update mood>`。
2. **`<state_update>` 三道剥离**（chunk 2.6 footgun 教训）：流式按段（chat.py `_parse_state_update`）+ 写库前（ws.py `strip_state_update`）+ TTS preprocessor（utils/text_filters.strip_state_update）。chat_history 实测无标签泄漏。
3. **`intimacy_delta` clamp ±2 per turn**：防 LLM 滥用 +99 一次刷高；叠加后再 clamp 到 [0, 100]。LLM 拼错 mood 静默忽略不抛错。
4. **`character.intimacy_decay` SCHEDULER-only**：故意不是 CHAT_AGENT consumer——LLM 看不到也调不了，只 cron `0 0 * * *` 自动跑。同样**没有** `update_mood` / `update_intimacy` 显式 capability，避免 LLM 滥用。mood / intimacy 写入路径只有：标签解析 / decay cron / reset API。
5. **`list_state_character_ids` vs `list_all_character_ids`**（pivot 1）：第一版 decay 遍历 `Character` 表，但测试创建 state 不写 Character。改成遍历 `character_states.character_id distinct` 真实"已有 state 的角色"。
6. **stage 1 prompt 强引导**（chunk 2.6 教训复用）：第一版 `<state_update>` 提示宽松（"可选输出"），实测 Qwen3.6 多数轮跳过。改成"必须 / 触发规则四条 / 只有中性 chitchat 可省略"后发出率明显提升（实测 3 turns 收到 2 次 push）。
7. **clipboard ringbuffer 不持久化**：故意不写 SQLite（隐私 + 重启即清空）。route 端 clipboard.captured 100KB 截断防大 base64。
8. **不自动响应剪贴板变化**：spec 关键设计——自动评论会烦人 + 隐私失控 + 上下文失控。capability 注册让 LLM 在用户**明确提到**剪贴板时调；prompt 引导写明"不要主动调"。
9. **migration `IF NOT EXISTS` 各自独立**（chunk 2.6 footgun 教训）：`character_states` 表 + 索引各自 IF NOT EXISTS，老 DB 升上来时索引能自动补建。
10. **WS 协议加新 `state_update` type**：服务端 → 客户端推送；前端 `useWebSocket` 加分支 → 更新 store `currentCharacterState` → `CharacterStatePanel` 自动重渲染。

**测试覆盖**（5 新套件 + 0 回归）：

| 套件 | 通过 | 内容 |
|---|---|---|
| `test_clipboard_integration.py` | 40/40 | content_type 启发式 + ringbuffer add/get/clear/dedup + 容量 50 上限 + TTL 24h evict + 启用开关 + polling lifecycle |
| `test_clipboard_capabilities.py` | 19/19 | 3 capability 注册 + CHAT_AGENT consumer + get_recent / summarize（mock LLM）/ translate（target_lang prompt 验证） |
| `test_state_update_parser.py` | 50/50 | `<state_update>` 自闭合 / 容错变体 / 单引号 / 多 tag first-wins / 负 delta / 非数字 delta / activity attr / strip 三道一致性 / clamp 函数 / mood normalize / instruction with state |
| `test_character_state_capability.py` | 38/38 | 3 capability 注册 + DB CRUD + intimacy clamp ±2 + floor 0 / ceil 100 + 无效 mood 静默忽略 + thought 截断 60 + set_activity WS push + intimacy_decay -1 + reset_character_state |
| `test_character_state_routes.py` | 19/19 | GET /state + POST /reset_state + POST /clipboard/captured 写入 + 拒绝空 + GET /clipboard/recent + POST /clipboard/clear |

**总计 166 新 case 全过 + 0 回归**（chunk 2 / 2.6 套件 179/179 仍通过）。

**端到端实测**（hardpoints 验证）：

| 指标 | 状态 | 实测 |
|---|---|---|
| 复制文字 → 5s 内 ringbuffer 出现 | ✅ | ``/api/clipboard/recent`` 显示捕获，type=plain_text |
| `clipboard.translate` LLM 调用 | ⚠️ Qwen 模型变异 | unit test 验证架构正确；端到端 LLM 偶尔不调（同 chunk 2.6 snooze quirk） |
| 跟 Momo 聊天 → state 真变 | ✅ | 3 turns 收到 2 次 `state_update` push，mood neutral→happy，intimacy 0→1→2 |
| 重启后端 → state 持久化 | ✅ | `character_states` SQLite 表，REST GET 跨重启可读 |
| 第二天 0:00 → intimacy -1 | ✅ | cron registered "0 0 * * *"；单元测试验证 -1 floor 0 |
| 状态条 hover thought / activity | ✅ | Momo 自然填 "听到用户说跟我聊天很治愈，觉得很幸福" |
| TTS 不读 `<state_update>` | ✅ | chat_history 全 [normal] 无标签泄漏 |
| profile_summary 不污染 | ✅ | `kind='normal'` 真对话，标签已剥离；chunk 2 白名单 + chunk 3 strip 双保险 |

**Footgun audit / pivots**：

* **stage 1 prompt 弱**（pivot 1，重复 chunk 2.6 教训）：第一版 `<state_update>` 提示"可选输出"，实测 Qwen 跳过率高。改成"必须 / 触发规则四条"后发出率提升。
* **decay 遍历 Character 而非 character_states**（pivot 2）：第一版 `list_all_character_ids` 查 Character 表，但 chunk 3b 设计上"未在 Character 注册的 character_id 也可有 state"（测试场景 + 未来扩展）。改成 `list_state_character_ids` 查 `character_states.character_id distinct`。
* **migration short-circuit 已修**（chunk 2.6 教训沿用）：每个 `CREATE TABLE/INDEX IF NOT EXISTS` 独立。
* **3 道 strip 缺一不可**（chunk 2.6 教训沿用）：流式按段 + 写库前 + TTS preprocessor。`strip_state_update` 加到 utils/text_filters。
* **测试 cross-run pollution**（pivot 3）：SQLite DB 文件跨 test runs 持久；character_id=300 的 state 累积。修：每个测试需要 fresh state 时显式 `reset_character_state` 起点。
* **set_enabled 路由未接通**（backlog）：前端 [捕获剪贴板] toggle 暂只写 localStorage，未通后端 `ClipboardWatcher.set_enabled`。已写入 DESIGN backlog。
* **Qwen3.6 LLM tool call 形态变异**（chunk 2.6 model quirk 重现）：`clipboard.translate` 实测 LLM 决定不调而是回应"翻好了"。架构正确（capability 注册 + parameter schema + 单元测试通过），端到端真调用率与模型相关。

---

**chunk 2.6 ✅ 完成（2026-05-08）— wake_call_briefing trigger（"邀请对话"模式 B）**

把 chunk 2 的 proactive engine 哲学补完：除"模式 A 单方面播报"外，加上"模式 B 邀请对话"——cron 8-15 字短问候 → 等用户响应 → 用户响应风格触发 ChatAgent 自适应输出（嗯 → 50-80 字 / 精神 → 180-260 字 / 拒绝起床 → 调 snooze tool / 切话题 → 优先回应当前话题）。**默认 v3-F' 所有生活节奏 trigger 走模式 B**（用户决定要不要听 / 听多少 / 切到别的话题）。

| Hash | 内容 |
|---|---|
| `<本 commit>` | feat(proactive): wake_call_briefing trigger + pending_briefings DB + ChatAgent stage 2 injection + snooze capability + frontend mode radio + tests + docs |

**架构关键点**：

1. **`pending_briefings` 表**：跨进程 / 跨重启的 wake_call stage 1/2 中间状态。stage 1 cron 触发时聚合数据（time / calendar / instruction memories / city；weather / news 留 stage 2 现查）写一行；stage 2 ChatAgent `_build_messages` 读出最近未消费 + 未 TTL 过期的行注入 addendum。**为什么用表而不是内存 dict**：跨重启幸存 + TTL 在 SQL 端就能判 + 多 user 索引天然 lock-free。
2. **`config.proactive.mode` 互斥**：``wake_call`` / ``morning_briefing`` / ``off``。决定哪个 trigger 注册到 cron_scheduler，避免两个都跑撞车。
3. **stage 1 must skip_short_term**（chunk 2.6 关键 footgun）：早期实测 LLM 受历史长简报 tone 影响把 8-15 字 wake call 输出成 100+ 字。`payload.context.skip_short_term=True` 让 `_build_messages` 跳过 short_term 拼接，仅在 system + persona 上下文生成。stage 2 仍走全量短期记忆（用户响应需要历史 context）。
4. **WAKE_CALL_STAGE1_SENTINEL 哨兵**：stage 1 自己调 ChatAgent.stream → 进 _build_messages → 又触发 stage 2 探测（无限递归 / 重复注入）。哨兵嵌在 stage 1 的 extra_system 开头，detection 跳过 addendum 探测。
5. **consume-on-detect 语义**：`_build_messages` 检测到 pending 命中即立即标 `consumed_at = utcnow`，不等 turn 完成。理由：若 turn 失败用户重发，pending 已消费 → fallback 普通短回复（更可预期，避免连续两次都触发简报）。
6. **stage 2 assistant kind='normal'**（**故意**）：让 profile_summary 看见这条真对话内容。只有 stage 1 的 8-15 字短问候是 `kind='proactive' proactive_trigger='wake_call'`。
7. **snooze capability**：APScheduler `DateTrigger` 一次性 job（不污染 cron 主配置），冲突避免：snooze 时间晚于下次正常 wake_call cron 时跳过。`user_visible=False` 减少 tool surface 噪音。
8. **stage 1 prompt 重复多遍长度约束**：单遍"8-15 字"不够强 → 三层强调（⚠️⚠️⚠️ 关键约束 / ❌ 严禁 / ✅ 只输出 + 例子）才稳定让 LLM 输出 8-15 字。
9. **briefing_api `?mode=` 路由**：`auto`（按 config 路由）/ `wake_call` / `morning`。前端 SettingsPanel mode radio 改变时按 UI 当前选中传过来；旧前端不传走 `auto`。

**测试覆盖**：3 个新测试套件（`test_pending_briefing.py` 19/19 + `test_wake_call_briefing.py` 35/35 + `test_snooze_capability.py` 19/19）+ 0 回归。**总计 73 个新 case 全过**。

**实测端到端验证**（5 种用户响应风格）：

| 风格 | 用户输入 | stage 1 wake | stage 2 reply 长度 | 行为 |
|---|---|---|---|---|
| 简短模糊 | "嗯嗯" | 10 字 | 22 字 | 精简响应 ✓ |
| 好奇精神 | "早，今天怎么样" | 10 字 | 271 字 | 完整简报（含天气/日程/待办/闲笔/话头）✓ |
| 拒绝起床 | "再睡 5 分钟" | 6 字 | 12 字 | 安抚短句（snooze tool 调用稳定性是 Qwen 模型 quirk，backlog）|
| 切换话题 | "今天天气怎么样" | 11 字 | 86 字 | 优先回答天气 + pending 仍消费 ✓ |
| 普通问候 | "你好啊" | 8 字 | 41 字 | 简短打招呼 ✓ |

**Footgun audit / pivots**：

* **stage 1 LLM 输出过长**（pivot）：第一版 wake call 实测 144 字（远超 8-15）。两个修复合一：a) prompt 改成三层强调 ⚠️ 严禁 ✅ 例子模式；b) 加 `skip_short_term` 让 stage 1 不看历史。两改后稳定 6-14 字。
* **无限递归探测**（pivot）：stage 1 自己经 ChatAgent.stream → _build_messages → stage 2 probe → 又注入 addendum。加 `WAKE_CALL_STAGE1_SENTINEL` 哨兵（stable 字符串嵌 stage 1 prompt 头）让 _build_messages 检测后跳过。
* **migration short-circuit 漏 index**（pivot）：第一版迁移 `if table_exists: return` 跳过整段 → 老 DB 升上来时 INDEX 没建。改成 `CREATE TABLE IF NOT EXISTS` + `CREATE INDEX IF NOT EXISTS` 各自独立幂等。
* **Qwen3.6 snooze tool call 形态变异**（model quirk，backlog）：用户说"再睡 5 分钟"时，Qwen 有时把 `proactive.snooze_wake_call` 调用以 Anthropic XML 格式发到 text content，而非 OpenAI function_call delta。capability 路径已验证正确（mock test 全过 + 直接调注册一次性 job 工作），但端到端真调用率与模型相关。已写入 DESIGN backlog。
* **kind='normal' for stage 2 reply**（intentional design）：spec 明确指出"用户响应后的 assistant 简报回复**是 'normal'**——重要：让 profile rewrite 能看见这条真对话内容"。区分 stage 1 的 wake call 短问候（kind='proactive'）和 stage 2 的真对话回复（kind='normal'）。

**v3-F' 进一步收紧**：本 chunk 之后 v3-F' 的工作量从"engine 工程"降级到"配置工程"——每个 trigger 半天到一天写完。模式 A/B 哲学也写进 DESIGN，未来加 trigger 时只需在 DESIGN trigger pack 表里加一行决定走哪种模式。

---

**chunk 2 ✅ 完成（2026-05-08）— 通用 proactive engine + 智能早晨简报 + chunk 2.5 NL 日程录入**

把 chunk 1 的"模板简报 v0.1"升级为 ChatAgent 智能生成，并**抽象出通用 proactive engine**——同一条流水线 `trigger → aggregate → ChatAgent → WS push` 服务所有未来主动陪伴场景。v3-F' 多 trigger 路线在本 chunk 之后变成"写若干个 trigger 配置文件"而非工程项目（详见 DESIGN §十五之B）。

| Hash | 内容 |
|---|---|
| `<本 commit>` | feat(proactive): generic engine + morning_briefing trigger + DB migration + chunk 2.5 prompt addendum + frontend WS proactive handling + SettingsPanel section + tests + docs |

**架构关键点**：

1. **`ProactiveTrigger` ABC**（`backend/proactive/engine.py`）：`name` / `cron_expr|interval_seconds|event_source` 三选一调度 / `enable_search` / `build_system_prompt(character)` / `resolve_capabilities()`。子类是纯配置加少量 system prompt 文本。
2. **`run_trigger(trigger, user_id)`**：统一聚合 + 流式 + 持久化路径。**character 解析三档**：override > 最近活跃用户 turn > Momo fallback。**对话**：拉最新或新建 title='主动陪伴'。
3. **WS 协议向后兼容**：`text_chunk` / `audio_chunk` / `done` 加 `proactive=true` + `proactive_trigger=<name>` 字段；老前端忽略未知字段照常工作。
4. **`chat_history.kind='proactive'` + `proactive_trigger`**：profile_summary 重写白名单 `kinds=['normal']` 已自动排除 proactive 行（v3-E1 Step Z.2 落地，本 chunk 零改动证明老抽象支撑住了新需求）。
5. **`enable_search` 真接通到 ChatAgent.stream**：通过 `payload.context.enable_search` 透到 `call_llm(enable_search=True)`，qwen → DashScope `enable_search=true`，deepseek → `web_search_preview` tool。
6. **briefing.py 缩成薄包装**：`deliver_morning_briefing()` 现在就是 `run_trigger(MorningBriefingTrigger(), user_id)` + 返回字典补 chunk 1 兼容字段（`audio_path` / `voice_model`）。`POST /api/briefing/test` 路由零改动。
7. **chunk 2.5 NL 日程录入**：`_TOOL_PROMPT_ADDENDUM` 加【日程录入】verbatim 段，明确"先 time.now → 再 apple_calendar.create_event；时长缺省 1 小时；地点 / 备注从原话提取"。
8. **前端**：`useWebSocket.ts` 识别 proactive chunk → 流式气泡 `kind='proactive'` + 推 toast "🌅 早安简报"；`ChatHistory.tsx` 渲染灰字前缀；`SettingsPanel` 新增 [主动陪伴] section（enabled 总开关 / 早晨简报 / cron / 城市 / 角色覆盖 / 🧪 立即测试简报）。

**测试覆盖**：3 个新测试套件（`test_proactive_engine.py` 21/21 + `test_morning_briefing.py` 30/30 + `test_briefing.py` 重写 14/14）；旧 `_format_event_for_briefing` / `generate_morning_briefing` 测试随 chunk 1 模板生成器一并删除（chunk 2 走 LLM 路径，单元测 mock-LLM 不再有 template-text 断言意义）；`test_calendar_router.py` import 测试更新为 chunk 2 薄包装。**总计 65 个新 case 全过 + 0 回归**。

**Footgun audit / pivots**：

* **chat_history.kind 已存在**：v3-E1 Step Z.2 已加，spec 让"加 kind 字段"可跳过。**只新增 `proactive_trigger`**。commit message 写明。
* **profile_summary 白名单已生效**：v3-E1 Step Z.2 已实现 `kinds=['normal']` 白名单 ⇒ proactive 行自动排除。**零额外改动**。回归测试加断言验证。
* **frontend `ChatKind` 已含 'proactive'**：v3-E1 Step Z.2 也提前预留。直接复用。
* **`enable_search` 未通到 ChatAgent.stream**：发现 `call_llm(enable_search=...)` 已支持但 ChatAgent.stream 没透。本 chunk 加 `payload.context.enable_search` 通道。
* **`resolve_capabilities` 不裁剪 ToolRegistry**：spec 说"空 = 全 CHAT_AGENT 集合"——为减小 chat.py 改动面，**当前实现走 prompt-time hint 而非硬裁剪**。LLM 仍可见所有 capability，trigger 在 system prompt 里说"推荐调用 A/B/C"。后续若需硬裁剪再扩 ChatAgent 接 `tool_subset` 参数。已在 DESIGN backlog 标。
* **briefing.py 改写后旧 test 接口失效**：旧 `_format_event_for_briefing` / `generate_morning_briefing` 已删，`tests/test_briefing.py` 重写覆盖薄包装语义；`tests/test_calendar_router.py` 内的 chunk 1 兼容测试更新。
* **测试 DB 不自动跑 migration**：发现 `init_db` 只 `create_all`，不增列。在测试 setup 显式调 migrations 链。

**v3-F' payoff**：v3-F'（饭点 / 睡前 / 长闲）在本 chunk 之后从"工程项目"降级为"配置工程"——每个 trigger ~半天，engine 零改动。详见上面 v3-F' 章节表。

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

#### v3-G'：TTS UI 升级 + cosyvoice emotion 真生效

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

##### Phase 2 📋 PENDING — 复刻 / fine-tune 自定义音色

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

#### v3-H：媒体接入（音乐 / 视频 / 系统播放控制）

延展 v3-G chunk 1.5 的 capability 架构，把第三方媒体能力接入成 capability。三条**互不依赖**的子链路。

| 子任务 | 状态 | 路径要点 |
|---|---|---|
| 网易云内置接入 | 🟡 chunk 1 PARTIAL（2026-05-08）| 数据查询 + 唤起 NCM 可用；自动播放封存待 chunk 2 重做 |
| 媒体控制（nowplaying-cli）| ✅ chunk 1 完成（2026-05-08）| `brew install nowplaying-cli` + 5 个 capability，跨来源播控 |
| B 站接入 | 📋 TODO | 独立链路；MCP client 或直接 integrations/bilibili.py |

#### v3-H chunk 1 — 网易云音乐接入 ✅ 自动播放问题已被 v3.5 chunk 6b 替代 (2026-05-11)

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

##### chunk 1 交付详情（2026-05-08）— 网易云内置接入 + macOS 媒体控制

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

#### v4：屏幕感知

DESIGN §13 已有完整设计。要点：

1. **VLM provider 抽象**：`backend/vlm/client.py` 统一调用 GPT-4o / Qwen-VL / Claude vision
2. **Tauri 截图 API**：单次截图 vs 持续监听
3. **像素差预过滤**：算法见 DESIGN §13.3
4. **隐私黑名单**：基于活动窗口的 app name / window title / Bundle ID
5. **WebSocket 协议扩展**：`screen` 上行 + `screen_comment` 下行
6. **Settings 加屏幕感知开关 + 黑名单管理**

**优先做主动模式（hotkey + 语音命令）**，被动模式延后 —— 理由见 DESIGN §20.3。

---

#### v5-D：autodl 部署 + 子 agent 隔离

详见 DESIGN §阶段七。要点：

1. 后端打包 Docker 部署 autodl GPU 实例
2. 前端通过 SSH tunnel 或 HTTPS 访问
3. **子 agent 隔离**（Hermes #4）—— 长任务（屏幕分析 / 批量记忆压缩 / 自主信息收集）跑独立 context
4. 数据库 / 模型权重存 autodl 持久卷

**估时**：3-5 天（Docker + 部署调试）。

---

#### v5-T1：GPT-SoVITS 后端接通

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

#### v5-T2：训练自定义 voice

依赖 v5-T1（先有 provider 再训模型）。

**两条并行训练路径**：

##### A. CosyVoice fine-tune voice cloning（短路径，云端）

1. 收集 5-10 段角色参考音频（每段 5-30 秒，安静环境，单一情感）
2. 走 DashScope CosyVoice voice cloning API 或 Web 工作流
3. 训练完成后拿到一个 `myvoice-xyz123` ID
4. 加进 `config.yaml` `tts.cosyvoice.available_voices`
5. CharacterPanel 下拉自动多一项

**估时**：训练 1-2 小时；流程跑通 1 天。

##### B. GPT-SoVITS 专属 model 训练（长路径，本地 / autodl）

1. 收集更多角色音频（推荐 30 分钟+ 高质量样本，多情感）
2. 数据清洗 / 切分 / 转写
3. autodl GPU 训练 GPT 模型（数小时） + SoVITS 模型（数小时）
4. 准备多情感参考音频文件 → 按 `ref_audios` schema 组织
5. 模型 + 参考音频部署到 autodl 推理服务
6. 加进 `config.yaml` `tts.sovits.available_voices`

**估时**：数据准备 1-3 天；训练 1-2 天；调优 1-3 天。

**角色绑定**：训练完成的 voice 默认绑定到对应 character（用户在 CharacterPanel 手动 confirm）。

---

#### v6+：多设备访问（高代价）

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

### v3.5 后续路线（v3 封盘后的连续推进）

> v3 封盘后没有"必须立刻做"的事，全是"想做 vs 想做"。下面按用户感知 × 工程量 × 依赖关系排序。每个 chunk 之间无强依赖，**用户可调整顺序**。

#### chunk 5 — 视觉跃迁包（背景层 + splash video）✅ 完成 2026-05-11

**主题**：Skyler 的"看板娘陪伴"视觉感再升一档。

##### 5a Live2D 角色背景层（per-character + 多媒体）✅

* DB：``characters.background_path TEXT NULL``，幂等迁移
  ``v3_5_chunk5a_character_background.py``
* Scanner：``backend/services/backgrounds_scanner.py`` + ``GET
  /api/backgrounds``，与 ``live2d_scanner`` 完全对称（``.absolute()`` 不
  ``.resolve()``，IP 资产 symlink 兼容）
* CharacterView：背景层 ``z-0``（``<img>``/``<video>`` 按后缀分发），
  Live2D canvas ``z-10`` 在背景之上；onError 静默回退原 fallback 链
* CharacterPanel：[背景层] 下拉，第一项 "(无)" → 落库 NULL；右侧
  120×80 实时预览
* ``.gitignore`` IP 隔离 pattern 复用 ``live2d/``

##### 5b 启动入场 splash video ✅

* 用户离线用 Grok / Sora 生成 ``intro.mp4`` 丢进
  ``frontend/public/splash/``——Skyler 工程**不集成**生成 API
* ``SplashOverlay`` 组件：localStorage gate → fetch HEAD probe → 全屏
  ``<video>`` → onEnded/click/keydown/onError 任一 fade 300ms 跳过
* 文件不存在 / disabled → silent skip，控制台无 error
* App.tsx 主视图 opacity 受 splashDone 控制，fade-in 300ms
* SettingsPanel [启动] section 加 [启动播放入场视频] toggle

##### 交付清单

* `2534eb3` feat(chunk5a) — backend (migration + scanner API + .gitignore)
* `b07fe1d` feat(chunk5) — frontend (CharacterView dispatch + Panel UI + SplashOverlay)
* `1ef5c8d` test(chunk5) — 38 cases (5 migration + 21 scanner/API + 12 PATCH)
* `<docs>`  docs(chunk5) — DESIGN §十五之G + ROADMAP + README

测试 0 回归（character_state 19/19 · state_update 50/50 · tool_call_resilience
65/65 · proactive_engine 21/21 · morning_briefing 30/30 · tts_strip_fallback
57/57）。

**5a + 5b 同 cc-task**：共用 video 播放基础 + asset 管理 + 同一对 IP 隔离
``.gitignore`` 段。

---

#### chunk 6 — 媒体接入收尾包（v3-H chunk 2 系列）📋

##### 6a B 站接入 ✅ 完成 2026-05-11

* `bilibili-api-python>=17.4`（Nemo2011 社区 fork，2025-12 stable +
  2026-01 pre-release，活跃维护）
* **6 个无 cookie capability**：search_video / get_video_info /
  search_user / get_user_videos / hot_videos / get_ranking
* **5 个 cookie capability**（spec pivot：原计划 4+1，audit B 站 2024-2025
  风控收紧字幕 API 后 `get_subtitles` 也归到 cookie 组）：
  get_subtitles ⭐ / get_my_history / get_my_followings / get_later_watch /
  get_favorites
* **杀手 use case**：`get_subtitles` + LLM → 视频内容总结（用户「帮我
  总结这个 B 站视频」自动闭环）
* 红线：投币 / 三连 / 评论 / 弹幕 / 下载 / 关注（DESIGN §十五之I 明文）
* SESSDATA cookie 走 `.env`（与 chunk 1 NETEASE_MUSIC_U 同 pattern，
  不走 chunk 7 mcp_credentials 表 —— 本地 capability 非 MCP server）

###### 交付清单

* `8db9087` feat(integrations) — wrapper + 11 methods + 健康检查三档
* `3a0855d` feat(capabilities) — 11 @register_capability + prompt 引导 + .env
* `c87cbf9` test(chunk6a) — 104 cases (38 integration + 66 capabilities) 全 mock
* `<docs>`  docs(chunk6a) — DESIGN §十五之I + ROADMAP + bilibili-setup.md +
  Tech Debt 2 条

##### 6b 网易云 mpv 自解码 ✅ 完成 2026-05-11

* **Spec 偏差修正**：chunk 1 NeteaseClient 实际**没**有 song/url 方法
  （audit 实测）。本 chunk 补 ``get_song_url`` weapi POST
  ``/song/enhance/player/url/v1``
* mpv subprocess + Unix-socket JSON IPC（**不**走 python-mpv ctypes —
  避免 libmpv 共享库部署）
* **MediaRemote 升级**：spec 计划自写 PyObjC 桥接，audit 后取消 ——
  mpv 0.34+ 原生注册 NowPlaying（``--media-keys=yes``），通知中心 /
  TouchBar / 媒体键 / nowplaying-cli 全部直接 work，节省 ~200 行 PyObjC
  代码 + 不需 Skyler 进程 entitlement
* **命名 pivot**：chunk 6b 6 capability 全加 ``local_`` 前缀避免与 chunk 1
  ``netease.play_song(keyword)`` namespace collision。LLM system prompt 引导
  默认走 ``local_*``；NCM 歌词路径作为可选保留
* 错误归一：mpv_not_installed / mpv_exec_failed / cookie_required /
  url_unavailable / netease_api_error / mpv_play_failed / mpv_command_failed
* VIP 试听 (~30s) 透传 ``is_trial=True`` 让 LLM 提示用户

###### 6b 交付清单

* `bf9d8a1` feat(integrations) — netease.get_song_url + mpv subprocess+IPC wrapper
* `3ed2005` feat(capabilities) — netease playback 6 ``local_*`` + system prompt
* `b3a9177` test(chunk6b+6c) — 56 cases (mpv 23 + netease_playback 33)
* `<docs>`  docs(chunk6b+6c) — DESIGN §十五之J + netease-playback-setup.md

###### 6b hotfix-1 ✅ 完成 2026-05-11 — 场景 capability fall-through mpv + autoplay 字段诚实

* **问题**：chunk 6b push 后验收发现 ``netease.daily_recommend`` 仍走 chunk 1
  URL Scheme 路径，返 ``autoplay: true`` 但 NCM 客户端实际**不自动播放指定
  歌曲**（只接管系统媒体键），LLM 收到 autoplay:true 后回"已在放"造成假成功
* **scope**：chunk 6b Pivot #2 只改了显式 ``netease.play_*`` → ``local_play_*``,
  没动 4 个场景 capability（daily_recommend / personal_fm / play_song(keyword)
  / play_playlist_by_id）
* **修法**：在 ``backend/capabilities/netease_music.py`` 顶部新加共享 helper
  （``_mpv_available_and_cookie_ok`` / ``_try_mpv_play_single`` /
  ``_try_mpv_play_song_queue`` / ``_mpv_unavailable_hint``）；4 个场景
  capability fall-through 模式：mpv healthy + cookie OK → mpv 真闭环 +
  ``autoplay: true``；其余 → URL Scheme + ``autoplay: false`` + ``hint`` 引导装 mpv
* **向后兼容**：``opened`` / ``autoplay`` / ``songs`` / ``song`` /
  ``alternatives`` / ``playlist_id`` 字段全部保留，仅新增 ``backend`` /
  ``hint`` / ``queued`` / ``is_trial``
* **音乐 scheme audit**：全 backend 0 个 ``music://`` 引用（用户报告"Mac
  自带音乐被打开"非代码 bug，是 macOS handler 在 NCM 未注册 orpheus 时的
  默认 app 回退）
* **system prompt**：``_TOOL_PROMPT_ADDENDUM`` 【音乐类】段新增 verbatim
  引导，让 LLM 看返回 ``backend`` / ``autoplay`` 字段诚实回话

####### hotfix-1 交付清单

* `2d63a4a` fix(capabilities) — 网易云场景类 fall through 到 mpv + autoplay 字段诚实
* `<tests+docs>` test(scene) + docs(hotfix) — scene capability 35 cases
  + chunk 1 mod 6 cases + DESIGN §十五之J mpv-default 策略

##### 6c 小红书 URL 被动解析 ✅ 完成 2026-05-11

* **工程红线锁死**：``backend/integrations/xiaohongshu.py`` 不暴露
  search / recommend / fetch_homepage / list_followings 等任何主动方法。
  无主动调用路径 ⇒ 即便 prompt injection 也调不到
* **只 1 个 capability** ``xhs.parse_url``（撤回 spec 的 ``summarize_post``
  —— 总结是 LLM 本职，单独 cap 无价值）
* 数据源：``window.__INITIAL_STATE__`` JSON（``undefined`` → ``null``
  修正 + 截 ``}`` fallback + 多候选路径）→ og:meta fallback
* URL 域名白名单：仅 xiaohongshu.com / xhslink.com（防 SSRF + 防误传）
* 反爬识别：412/418/403 → ``blocked_by_antibot`` + "过几分钟再试" hint
* System prompt 明文红线：用户问主动搜索时如实告诉无能力 + **不要瞎编**

###### 6c 交付清单

* `a3e4a1b` feat(chunk6c) — 小红书 URL 被动解析 + 系统 prompt 红线
* `b3a9177` test(chunk6b+6c) — xiaohongshu 52 cases（其中红线 enforcement 4 cases）
* `<docs>`  docs(chunk6b+6c) — DESIGN §十五之K + xiaohongshu-setup.md

---

#### chunk 7 — Skill 集成 demo（个人乐高底盘真兑现）✅ 完成 2026-05-11

两条姿态各一个 demo，验证未来加任何 skill 都有清晰路径：

##### 7a 姿态 A：本地 capability（docx demo）✅

* ``python-docx`` 依赖 + ``backend/capabilities/docx_ops.py`` 三 capability
  （``docx.create`` / ``docx.read`` / ``docx.append``），与 chunk 0
  capability registry 完全对齐
* ``backend/utils/safe_path.py`` 集中 path traversal 防御
  （``safe_resolve`` + ``ensure_sandbox_dir``）；docx 沙箱
  ``~/Documents/Skyler/docs/``（用户可见 vs ``~/.skyler/`` 内部 token）
* ``config.yaml skills.docx.safe_dir`` 可覆盖

##### 7b 姿态 B：MCP server 一键启用（Notion demo）✅

* **不重建** chunk 1.5 的 MCP client——扩展现有 ``backend/mcp/client.py`` +
  ``routes/mcp_api.py``：
  - ``mcp_credentials`` 表：UI 输入凭证写 DB，子进程启动时注入 env
  - ``mcp_client_state`` 表：UI toggle 持久化 override config.yaml enabled
  - 新 endpoints: ``PUT /api/mcp/clients/{name}/enabled`` /
    ``PUT,GET /api/mcp/clients/{name}/credentials``
* ``ExtensionsSection.tsx`` 在 SettingsPanel：列 server + 状态徽章 +
  [配置凭证] modal；缺凭证时 toggle disabled
* config.yaml 加 ``notion`` entry：``@notionhq/notion-mcp-server`` 官方
  包，``env_required: [NOTION_API_KEY]``，``enabled: false``

##### 决策树（DESIGN §十五之H 详）

```
新 skill 想接入？
  ├─ Python 库能跑 → 姿态 A（直接 capability + SAFE 沙箱）
  ├─ 第三方 SaaS 有官方 MCP → 姿态 B（config.yaml + UI 凭证）
  └─ 两种都行 → A（少一层进程）
```

##### 交付清单

* `a8c096e` feat(capabilities): docx + safe_path util + 3 capability
* `1c62385` feat(mcp): credentials 表 + enable/disable + Notion config
* `665e938` feat(frontend): ExtensionsSection + 凭证 modal
* `f67920a` test(chunk7): 65 new + 2 regression fix
* `<docs>`  docs(chunk7): DESIGN §十五之H + ROADMAP + skills-extension-guide

测试 0 回归：16 suites 556/556 全过（docx_capabilities 31/31 + mcp_chunk7
34/34 + 14 个既有 suite 全过含 mcp_client 28/28 / mcp_server 22/22 /
capability_registry 18/18 / chunk 5 系列）。

工程量：~1 个 session / 5 commits

---

#### chunk 9 — 记忆 perf + 遗忘曲线 + 跨角色共享 ✅ 完成 2026-05-12

**主题**：把 v2.7 memory 系统从"角色隔离 + 永久保留 + per-turn 退化"
推到"用户级共享 + 遗忘曲线让位 + 短输入门 + cache"。

##### Part 0 ``_build_messages`` 性能优化（perf 三项零风险） ✅

* 短输入门：``len(query.strip()) < short_input_threshold`` 直接返 ``[]``
  （默认 10 chars）—— 短问候 / 单字命令 跳过 memory 检索
* embedding LRU + TTL 缓存（size 100 / TTL 300s）—— cache hit 0.01ms
* ``device: auto`` → cpu（mps median 与 cpu 一致但 cpu 更稳，不与 Whisper
  抢 GPU；显式 ``device: mps`` 才走 GPU）
* 4487ms 退化 audit 后定位真根因是**模型未 preload 完时首条消息触发
  lazy load**（不是 per-turn）—— 本 chunk 不修，留 backlog "preload-gate"

##### Part 1 跨角色共享 + UI 来源角标 ✅

* 检索去 ``character_id`` 隔离——所有角色共享用户长期事实
* memory 行保留 ``character_id`` 字段不删（向后兼容）
* MemoryManagerDrawer 加"由 X 记"角标显示原始记忆角色

##### Part 2 profile_summary 自循环切断 + UI 编辑 ✅

* prompt 输入改为"只读 user 消息"（不再混入 assistant 自己的话，断 LLM
  自循环放大反推词的根因）
* SettingsPanel 加用户画像 section：编辑 / 清空 / 重生 modal
* API endpoints PATCH/DELETE/regenerate /profile_summary

##### Part 3 遗忘曲线 ✅

* memory 加 ``access_count`` + ``last_accessed_at`` 两列（幂等 migration）
* score 公式：``relevance * (1 + log(1 + access_count)) / (1 + age_days * decay)``
* 阈值 gate：score < ``threshold`` (默认 0.3) 不进 top-k，仍在 DB
* config ``memory.forgetting_curve.{enabled, threshold, age_decay_factor}``
  全 hot-readable
* 召回成功 entries 异步 bump ``access_count + 1`` + ``last_accessed_at=now``
  （best-effort）

##### 交付清单

* `efb22a0` perf(chunk9): _build_messages audit + 短输入 + cache + device
* `5d54818` feat(chunk9): motion strip helper + ws.py 入库链补完
* `1b0cea3` feat(chunk9): profile_summary prompt 输入改只读 user
* `705d7e6` feat(chunk9): profile_summary API endpoints
* `8a71fc7` feat(chunk9-frontend): SettingsPanel 用户画像 section
* `6e8dee5` feat(chunk9): memory 检索去 character_id 隔离 + UI 角标
* `ba0399e` feat(chunk9): memory forgetting curve schema + score 公式 + config

工程量：1 个 session / 7 commits / 18 new test cases (forgetting_curve)
+ 22 (build_messages_perf)

---

#### chunk 10 — server-side memory worker（治本 LLM hallucinate save_memory） ✅ 完成 2026-05-12

**主题**：把 memory entry 入库从 LLM tool **主路径**改成 server-side worker
**主路径**。LLM 不再为每条 chitchat 拍脑袋决定要不要 save，而是 background
worker 按批 + 严格 filter 提取。tool 不删但降级为"用户明确说要记"的显式入口。

##### Why（root cause）

chunk 9 把 ``character_id`` 隔离去掉后，所有角色共享的 memory 表里**反推词
污染 + 重复 + 无意义条目**问题被放大。根因是 ``save_memory`` tool 在主
对话路径里挂着，LLM 自己拍脑袋判断"这个值不值得记"——既费 token，又
经常 hallucinate（记下情绪 / 反推词 / 单次提问）。chunk 11 治了 profile
层的反推词污染，本 chunk 治 memory 层的。

##### Pipeline（8 commit 全图）

```
chat_history (kind='normal', role='user')
   │  last_processed_turn_id 之后
   ▼
MemoryExtractor worker（asyncio task，每 300s 一批）
   │
   ▼ build_extraction_prompt(turns) ─→ qwen-turbo
   │
   ▼ JSON list 输出（type/content/confidence，14 反推词 prompt 主动避开）
   │
   ▼ validate_and_filter_entries (10 道闸):
   │    hard reject  — JSON parse / type 不在四分类 / 长度 5-200 / SUSPICIOUS
   │                 / confidence < min_confidence / cosine dup > threshold
   │                 / intra-batch dedup / (opt) llm_judge
   │    soft warn   — 反推词命中 accept + log
   │
   ▼ _save_worker_entries
   │    INSERT memory: extraction_source='worker' / confidence /
   │                   source_turn_id / extracted_at / entry_type / type
   │    embedding best-effort
   │
   ▼ update_last_processed_turn_id (state pointer 推进)
   │
   ▼ search_relevant_memories（用户下次提问）
        遗忘曲线 score（chunk 9）+ top-5 → ChatAgent prompt
```

##### entry_type 双维度 + extraction_source 四态

* ``type`` (chunk 2 五分类 CHECK 锁死) + ``entry_type`` (chunk 10 四分类)
  并存。worker 写入时 _TYPE_LEGACY_MAP 把 entry_type 映射到 legacy type：
  fact→fact / preference→instruction / event,commitment→activity
* extraction_source：worker / llm_save_memory / manual / legacy
  → MemoryManagerDrawer 角标显示来源（"自动提取" / "你说要记" / "手动" / "旧"）

##### save_memory tool 降级

* description 收紧到 4 个明确触发信号（"请记住/以后/别忘了/你要记住"）
* 明文禁令"日常事实由 server-side worker 提取，不要主动调"
* _TOOL_PROMPT_ADDENDUM 同步
* 内部 _tool_save_memory 复用 worker 同 quality filter（长度 / SUSPICIOUS /
  cosine dup → status='duplicate' 不抛错）
* 写入打 extraction_source='llm_save_memory' 标签

##### 交付清单

* `a692ac9` feat(chunk10): memory schema 扩展（6 列）+ extractor_state 表 + migration
* `f250072` feat(chunk10): MemoryExtractor worker 骨架 + last_processed_turn_id
* `a57fa59` feat(chunk10): extraction prompt + qwen-turbo + JSON list 契约
* `750d16f` feat(chunk10): quality filter pipeline + extractor end-to-end 接通
* `86ba1f1` feat(chunk10): save_memory tool 降级 + extraction_source 标记
* `3dc2349` feat(chunk10-frontend): MemoryManagerDrawer 升级（entry_type tab + 角标 + confidence）
* `c4834cc` feat(chunk10): worker startup/shutdown lifecycle + config.yaml extractor 段
* `<docs>`  docs(chunk10): DESIGN §五 三层版 + ROADMAP + README Known Problems

##### 验收硬指标对照

| # | 指标 | 状态 |
|---|------|------|
| 1 | 后端启动 log ``[extractor] started interval=300s`` | ✅ commit 7 |
| 2 | ``config.yaml memory.extractor.enabled=false`` worker 不启动 | ✅ commit 7 |
| 3 | 用户说"请记住 X" → save_memory tool 入库 ``extraction_source='llm_save_memory'`` | ✅ commit 5 |
| 4 | 日常 chitchat 入库走 worker ``extraction_source='worker'`` | ✅ commit 4 |
| 5 | worker 写入填齐 confidence / source_turn_id / extracted_at / entry_type | ✅ commit 4 |
| 6 | LLM 输出反推词 prompt 主动避开 + validator soft warn | ✅ commit 3 + 4 |
| 7 | MemoryManagerDrawer 显示 entry_type tab + extraction_source 角标 | ✅ commit 6 |
| 8 | 切 entry_type tab 列表正确过滤（legacy 仅在"全部"显示） | ✅ commit 6 |
| 9 | worker 任一步异常 state pointer 仍推进（不 stuck loop） | ✅ commit 4 |
| 10 | dup_threshold 同 batch 内 intra-batch dedup | ✅ commit 4 |
| 11 | 老 entry 自动 ``extraction_source='legacy'`` 不重处理 | ✅ commit 1 |
| 12 | shutdown 时 worker stop() 优雅退（5s timeout cancel 兜底） | ✅ commit 7 |

##### 0 regression（chunk 9 + 11 + hotfix-3/4）

chunk 9 + 11 测试套件（forgetting_curve / build_messages_perf /
profile_* 系列）**100 cases all PASS**，chunk 10 新增 59 cases all PASS。
全套残留 failure 全部是 README Known Problems #1 列出的 pre-existing
test debt 范围（test_chat_agent / test_database / test_integration /
test_llm_client / test_memory_agent / test_ws_helpers / test_ws_interrupt
家族），与 chunk 10 改动**无因果关系**。

##### 手动实测样本（worker 真 LLM 真 DB 跑一次）

default 用户，把 ``memory_extractor_state.last_processed_turn_id`` 倒回
320，让 worker 重扫最近 15 条 user normal turn（涉及"播放网易云日推 +
mpv"主题）。一次 ``_extract_batch()`` 后 worker 入库 3 条：

```
entry_type=preference src=worker conf=0.9 source_turn=405
  用户喜欢播放网易云音乐的日推歌曲
entry_type=preference src=worker conf=0.8 source_turn=405
  用户喜欢使用mpv播放音乐
entry_type=event src=worker conf=0.9 source_turn=405
  用户多次要求播放日推歌曲
```

* 全部第三人称客观陈述 ✅
* 零反推词（无温柔/陪伴/亲密等） ✅
* confidence 全 > min_confidence 阈值 ✅
* source_turn_id 正确指向最后一条 user turn ✅
* state pointer 推进到 405 ✅

##### 工程量

1 个 session / 8 commits（7 feat + 1 docs）/ 59 new test cases:

| File | Tests |
|---|---|
| test_memory_schema_chunk10.py | 1 (containing 10 sub-asserts) |
| test_memory_extractor_skel.py | 9 |
| test_memory_extraction_prompt.py | 9 |
| test_memory_entry_validator.py | 21 |
| test_memory_extractor_e2e.py | 5 |
| test_save_memory_chunk10.py | 8 |
| test_memory_api_chunk10_fields.py | 2 |
| test_extractor_lifecycle.py | 4 |

---

#### chunk 8a — 简化屏幕感知（active app + browser URL + smart trigger）✅ 完成 2026-05-12

**主题**：v4 屏幕感知 "M-version" —— **不**截屏 / **不** OCR / **不**装浏览器
扩展，只靠 NSWorkspace + AppleScript 拿 active app / 浏览器 tab URL / 文档
路径，加 url_fetcher 抓公开页面正文，让 Momo 按"你在用什么"主动开口。

##### 9 commit 全图

| # | hash | subject |
|---|------|---------|
| 1 | `7af03f1` | feat(chunk8a): activity_monitor 系统状态查询 + 跨平台 graceful |
| 2 | `2fe1f99` | feat(chunk8a): screen capabilities (active_app / browser_url / browser_content / active_document) |
| 3 | `c25263e` | feat(chunk8a): url_fetcher 公开页面内容 + readability-lxml + 黑名单 |
| 4 | `db5761f` | feat(chunk8a): ActivityWatcher 后台 polling + change detection + lifecycle |
| 5 | `da3ac58` | feat(chunk8a): smart activity-based proactive trigger + 节流 + 黑名单 skip |
| 6 | `b5fca86` | feat(chunk8a-frontend): SettingsPanel 活动感知 section + 状态显示 + 黑名单管理 |
| 7 | `3fe2183` | feat(chunk8a): macOS 权限处理 + Tauri Info.plist + 前端权限弹窗 |
| 8 | `edb5142` | feat(chunk8a): API endpoints (/api/activity/status, /api/activity/config) + lifespan register |
| 9 | `<this>` | docs(chunk8a): DESIGN §十五-L + ROADMAP + Known Problems + config.yaml + run-all tests |

##### Pipeline

```
ActivityWatcher (asyncio task, 30s tick)
   ↓ NSWorkspace.frontmostApplication / osascript (Chrome|Safari|Word|Pages)
   ↓ 黑名单 app/URL 字段置 None
   ↓ _detect_changes → 5 类 ActivityChange
   ↓ (url_changed → url_fetcher: 5s GET + readability)
   ↓ listeners 串行
       activity_smart_handler:
         1. _classify(change) → label or None
         2. 最近 5min 有 user turn → skip
         3. 同 label throttle (默 30 min) → skip
         4. daily cap (默 5/day) → skip
         5. ActivityProactiveTrigger(label, detail) → run_trigger
   ↓ 40-80 字短句 → ChatAgent → WS push (kind='proactive', proactive_trigger='activity_*')
```

##### v1 规则集

| change | label | 触发条件 |
|---|---|---|
| app_changed → IDE | activity_ide_open | new_app ∈ _IDE_APPS（VSCode / Cursor / JetBrains / Xcode / Sublime / vim 等 15 个） |
| app_changed → IDE @ 0-5am | activity_late_night_ide | 同上 + 凌晨时段 |
| app_changed → 音乐 | activity_music | new_app ∈ _MUSIC_APPS（Spotify / 网易云 / Apple Music / QQ 音乐 / YouTube Music） |
| url_changed → 技术文档 | activity_url_tech_doc | URL 含 docs.python.org / MDN / dev.to / realpython / `/tutorial` / `/learn` 等 18 个 pattern |
| app_focus_long | activity_long_focus | 同 app 持续 > 90 分钟跨阈值首拍 + latching off |

##### 验收硬指标对照（12 条）

| # | 指标 | 状态 |
|---|------|------|
| 1 | 后端启动 log `[activity] watcher started interval=30s` | ✅ commit 8 lifespan 6c' |
| 2 | 切 active app → 30s 内 backend log app change detection | ✅ commit 4 _detect_changes |
| 3 | Chrome 切新 tab → URL 被识别 + 标题提取 | ✅ commit 1 osascript Chrome 路径 |
| 4 | 公开技术文档 URL → 后台 fetch + 正文 | ✅ commits 3 + 4 _maybe_fetch_url_content |
| 5 | 黑名单 URL (mail.google.com) → skip fetch + log 'blocked' | ✅ commit 3 默认 patterns |
| 6 | `screen.get_active_app` capability 可调 + 返当前 app | ✅ commit 2 + ToolRegistry runtime smoke |
| 7 | 切到 VSCode → 1-2 min 内触发 activity proactive trigger | ✅ commit 5 _classify + run_trigger（要 GUI session 实测，CLI 限制下走 unit test 路径覆盖） |
| 8 | 同类型 trigger 节流（30 min 内不重发） | ✅ commit 5 throttle dict + test |
| 9 | 用户活跃对话 5 min 内 → activity trigger skip | ✅ commit 5 _active_conversation_recent + test |
| 10 | SettingsPanel 黑名单增删工作 | ✅ commit 6 PATCH /api/activity/config |
| 11 | macOS 权限未授予 → 前端友好弹窗 + 跳转设置 | ✅ commit 7 ActivityPermissionModal + x-apple.systempreferences URI |
| 12 | 0 regression on chunk 9/10/11/UX-001 (隔离运行) | ✅ commit 9 文末测试汇总 |

##### 测试

chunk 8a 新增 8 文件、~95 tests / 全 PASS（隔离运行，已知 chunk 0-4 pre-
existing test debt 仍在 README #1）：

| 文件 | tests |
|------|------:|
| test_activity_monitor.py | 21 |
| test_screen_capabilities.py | 18 |
| test_url_fetcher.py | 13 |
| test_activity_watcher.py | 16 |
| test_activity_smart_trigger.py | 15 |
| test_chunk8a_settings_section.py | 9 |
| test_chunk8a_permissions.py | 10 |
| test_activity_api.py | 7 |

##### 工程量

1 个 session / 9 commits / ~95 new test cases / 0 regression on chunk 7
MCP + chunk 9 forgetting curve + chunk 10 extractor + chunk 11 profile_data
+ UX-001 (隔离运行)。

---

#### chunk 8b — 完整屏幕感知（截屏 + OCR + 浏览器扩展） 📋 backlog

DESIGN §13 已有完整设计；本 chunk 是 chunk 8a 之后的 v4 完整版：

* VLM provider 抽象（**Qwen3.5-Plus 主选**——多模态降价后 ¥0.8/M tokens 输入，被动监听 ~¥9/月；Claude Vision / GPT-4o 备选）
* Tauri Rust 端 `CGDisplayCreateImage` + 全局热键
* 像素差 64x64 预过滤
* 隐私黑名单（app name / window title）—— **复用 chunk 8a 的 `activity_watcher.blocked_*`**
* WS 协议加 `screen` 上行 + `screen_comment` 下行
* proactive engine 复用：屏幕事件作为新 trigger（"IDE 卡同一行 5 分钟" / "切应用频率异常"）—— 复用 chunk 8a 的 ActivityWatcher + smart_trigger 节流框架

工程量：2-3 天 / 8-10 commits / **单独 session 大 chunk**，不合并。

---

#### 远期（不本次 session）

* v5-D autodl 部署 + 子 agent 隔离
* v5-T1 GPT-SoVITS 后端接通
* v5-T2 训练自定义音色
* v3-G chunk 5 per-trigger aggregator 真接通（lunch 饮食 memory / bedtime 今日 review）
* v3-H chunk 1.x 增强（add_to_playlist 暴露 / like_current 两步保证）

---

### 建议下一步

按"性价比"排序，建议你接下来这么走：

#### Step 1（本周末）：固化 + git 卫生
- [x] 新建 GitHub repo `Skyler`
- [ ] git push 三份新文档（README / DESIGN / ROADMAP）
- [ ] 配置 `.gitignore` 防止 `.env` / `*.db` / `node_modules` 误提交
- [ ] 设置 git 工作流：每完成一个独立模块 commit 一次（conventional commits）

#### Step 2（接下来 1 周）：低成本快收益
按从易到难做这几件，能快速看到体验飞跃：
- [ ] **TTS 预处理器**（v3-F #3）—— 半天就能做完，立刻不读 `*笑*` 这种东西
- [ ] **AI 内心独白 `<thinking>` 标签**（v3-F #4）—— 1-2 天，参考 emotion 实现模式
- [ ] **语音打断**（v3-F #1）—— 2-3 天，体验飞跃明显
- [ ] **TTS 多段并发**（v3-F #2）—— 2-3 天，首句延迟显著降低

做完这一组，v3-F 完成，体验上一个台阶。

#### Step 3（接下来 2-3 周）：v3 灵魂
- [x] **下载 Hiyori 模型**
- [x] **v3-E1 Live2D 主线**（Step 1-6 + 角色修复 + Step Z.1，8 commit 完成）
- [x] **v3-E1 Step Z 收尾**（4 条 cleanup 完成：commits `488a6a1` / `f2d7f78` / `d984916`）
- [x] **v3-E2 多模型接入**（runtime 抽象层 + per-character maps + 八重 BCSZ1.1 接入 + Momo persona 还原；9 commit 完成 2026-05-06）
- [x] **v3-E3 emotion 视觉绑定**（代码路径已接通 chunk 7 `950710e`，剩纯运营找模型）
- [x] **v3-G' TTS UI 升级 + cosyvoice instruct emotion**（5 commit + 1 patch，2026-05-06）—— SSML 路径事后撤回，改走 instruct
- [ ] **v3-F' 主动对话**（依赖 [touch] kind 字段同设计）—— 1-2 天

v3-E 全套 + 主动陪伴中两条已完成 + 收尾。剩 v3-F' / v3-G' / v3-G。

#### Step 4（接下来 1-2 个月）：工具层
v3-G 全部 + v4 主动屏幕感知。从剪贴板助手开始（最简单），逐步加每日简报、智能提醒、cron、屏幕感知。

#### Step 5（远期）：autodl 部署 + 自定义 voice
- v5-D autodl 部署 + 子 agent 隔离
- v5-T1 GPT-SoVITS 后端接通
- v5-T2 训练 CosyVoice fine-tune voice + GPT-SoVITS 专属 model

等 GPU 推理需求真出现了再做。CosyVoice fine-tune 可以更早做（不需要 autodl）。

---

