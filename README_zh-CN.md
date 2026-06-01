# 🌸 Skyler

> 一个可塑型 AI 角色容器 —— 自带你的 LLM、自带你的 Live2D 模型、自带你的 MCP 工具。Agent 内核给你打好地基,剩下的拼成什么样,自己塑造。

![Python](https://img.shields.io/badge/Python-3.10+-blue) ![FastAPI](https://img.shields.io/badge/FastAPI-async-green) ![Tauri](https://img.shields.io/badge/Tauri-2.0-orange) ![React](https://img.shields.io/badge/React-18-61DAFB) ![Platform](https://img.shields.io/badge/platform-macOS-lightgrey) ![Status](https://img.shields.io/badge/v4--beta-🚧%20收口中-orange)

> **最新**:v4-beta + **INV-11 全段**(2026 年 5 月)—— Persona Engineering 五层框架 + 记忆/对话隔离根治 + conversation 锚定绑定语义 + 对话 UI 统一 + **Mai 日语 TTS 接入自部署 GSV mai_v4** + **9 角色 provider × model × voice paradigm**。完整路线见 [ROADMAP](ROADMAP.md) + [docs/adding-new-tts-model.md](docs/adding-new-tts-model.md)。
>
> **2026-05-26 更新**:9 character DB 行 · 3 TTS provider(CosyVoice / Fish / GSV)· 4 model · 1 Live2D model(Hiyori 绑 cid=1 Mai)。VoicePicker inline paradigm B(原 modal → inline,auto-save debounce 300ms)。tts_models.json + pydantic 校验 + GSV 2 mode schema(trained / zeroshot future placeholder)。
>
> *项目原名 MomoOS,2026-05 改名 Skyler。*

🌐 **Languages**: [English](README.md) · **简体中文**

---

## Skyler 是什么?

Skyler 是一个带 Live2D 角色界面的桌面 AI agent。跟那种打包好的 VTuber app 不一样,Skyler 是个**给你拿来改的容器** —— 内核(MOMOOS)、能力注册表、主动陪伴层 —— 这些是底座;但每一个 capability、每一个外部集成、每一个角色资产,都是你能拆下来换的。

你要是动过这个念头 —— "我能不能有一个真正属于我自己的 AI 陪伴,本地跑、用我喜欢的角色、调我自己注册的工具" —— Skyler 就是给你这种人写的。

角色不是装饰。Persona 级状态(心情 / 最近的想法 / 跟你的亲密度)跨 session 持久化;agent 能调你注册的任何 tool 和你接的任何 MCP server;立绘会响应它说的话和你在屏幕上做的事。这些层没有一个是锁死的。

---

## ⚠️ v4-beta 当前状态(2026-05)

v4-beta 是**收口阶段**,目标是把一个角色做扎实再 ship,而不是铺开七个半成品。

**当前主推 Mai(`cid=1`,借 Momo 壳 + Hiyori 模型,内核是樱岛麻衣 persona)单角色陪伴 —— 文本恒中文字幕,语音走 GSV mai_v4 日语合成(详 INV-11 / DESIGN_LITE §6.6.5 _语音语言机制_)。**

本 session 已根治并真机验证通过:

- **Mai 日语语音 via GSV mai_v4 接入**(INV-11 Stage 1,2026-05-26)—— 上一版"回退纯中文"状态已被取代。Mai(`cid=1`)现走自部署 GPT-SoVITS 服务器(`106.75.224.167:9880`)+ `mai_v4` 模型 + 16 emotion bank(LLM 出 emotion → server 路由到对应 ref wav);CosyVoice / Fish 仍可 per-character 选用。早先"LLM 实时交替标 `<ja>` 让 CosyVoice 中/日 voice 切换"那条不确定路径**休眠**;INV-11 改用 GSV server-side 统一 ja 路径(`voice_model.tts_language=ja`),把不确定性绕开。**v4.1 后处理翻译重做(F0)backlog 因此作废**。详 `docs/INV-11-*.md` + `docs/LESSONS.md` Lesson #11。
- **Per-character TTS paradigm 落地**(INV-11 Stage 1.5,2026-05-26)—— 9 个角色可各自挑 provider × model × voice,通过 inline `VoicePicker`(paradigm B;原 modal 已删)。静态注册表存 `backend/config/tts_models.json`(pydantic 校验、schema 错时 fail-fast、文件缺失走 hardcoded fallback)。GSV models 用 `mode` 字段(`trained` 已 ship 给 `mai_v4`;`zeroshot` 占位预留给未来 ref upload)。加新 model 的 playbook:`docs/adding-new-tts-model.md`。文本语言与语音语言解耦 —— 字幕恒中文,ja/en 语音走 `<ja>…</ja>` / `<en>…</en>` 标记路由;详 DESIGN_LITE §6.6.5 _语音语言机制_ 的四层 + 字幕层。
- **记忆/对话串台根治** —— 短期记忆从只按用户切片,升级为按 **(用户, 角色, conversation)** 三级隔离 + 重启按 conversation 过滤恢复。"切到八重却自报麻衣""删了对话重启还记得旧上下文"均已解。
- **conversation 锚定绑定语义** —— 切角色 = 切到该角色最新对话(无则新建);**规则 A**:用户发起的对话发起时即锁定 conversation,响应无条件回原对话(中途切走也不丢);**规则 B**:系统主动消息触发时快照对话,投递前校验,过时则丢弃。`character_switch` 不再误杀进行中的回复。
- **对话 UI 统一** —— 右上角独立"历史"入口、旧浮现台词气泡均移除;对话内容统一由**左侧推拉 chat panel** 承载;左 conversation list + 右 chat panel 双推拉,两侧全收起 = 纯立绘 Galgame 沉浸;窗口 <1280px 自动降级。
- **token 成本治理** —— 短期记忆硬性 cap 最近 25 turn(=50 messages,代码真值 `SHORT_TERM_MAX_TURNS=25`);tool result 注入截断到 4000 字符。多 round 工具调用不再把单次输入推到几万 token。

**已知限制(诚实列,这就是路线图):**

- 其他角色(八重神子等 `cid=2/3/...`)目前是**空骨架**,没有完整 persona,切过去人格空洞。v4.1 (F1) 逐个补真 persona。
- **长期记忆链路 —— audit 完结,修复链已 ship(代码核验),待真机回归** —— 审计结论:根因是抽取 prompt 偏 fact-only + 稀疏/闲聊语料 → LLM 合法返回 `[]`(非链路全断);子 bug:purge 不重置 extractor 指针。修复链(有界滚动摘要层 + 指针自愈/源头 reconcile + 抽取 prompt 重平衡 + 墓碑)已 ship 且对真 diff 代码核验。**陪伴/功能质量未核验,待真机回归 + friend-test(验收门,CC 不自证)**。详 DESIGN §五·补 + §十五之 Z.5.1。
- **记忆表层历史债(v4.0.0 §5.8 → 表层重构 pass,立项)** —— `memory` 表混存持久事实(`expires_at` NULL)与时效提醒(有值);`type`(5 类)/ `entry_type`(4 类)双列并存;supersede 无自身机制;`expires_at` 接受但 caller 全传 None;墓碑 check 无类型感知。结构债,日常不阻塞,不在 v4.0.0 ship 范围;留待表结构重构那一局。详 DESIGN §十四之B RT-1~5。
- **文档债** —— 中英 README 结构对齐**进行中**:已补 `## ⚠️ 已知问题` 节(含 `characters.yaml` 双源条目);EN 完整 19+ 条已知问题(7 文件测试失败 / 网易云 mpv / MCP 凭证加密 / `config.yaml` 双写源 / 表层重构 等)逐条翻译同步留作后续小刀。DESIGN.md 已加顶注定格为 2026-05-18 v4-beta 收口决策档案,后续以 DESIGN_LITE 为当前真源。
- LLM 首响偏慢(关 VPN 仍 5–10s),为模型 + 网络的独立性能问题,绑定语义锁死后"慢"与"串"已解耦,降级为纯体验问题,后续单独优化。

---

## 这是给谁的?

Skyler 是给**有动手能力的二次元半技术宅**写的:

- 你能跑命令行,也能写一点 Python
- 你在意数据所有权(本地跑 SQLite、本地跑 sentence-transformers,没有云依赖)
- 你喜欢"角色驱动的 AI"这个想法,不喜欢冷冰冰的 chatbot
- 你宁可拿到一个能扩展的框架,也不想要一个磨得很光滑但改不动的 app

要是你想要开箱即用的 VTuber 体验,去看 [Open-LLM-VTuber](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber)。
要是你想要服务器跑的个人 agent 平台,去看 [Hermes Agent](https://github.com/NousResearch/hermes-agent)。

**Skyler 站在它俩之间** —— 一个桌面、角色化、真正属于你自己的 agent。

---

## Skyler 凭什么不一样

### 1. 能力注册表是可拆开的

每个内建 capability 都是一行 `@register_capability` 装饰器注册的。内部 tool(日历 / 剪贴板 / 屏幕感知)、外部 MCP server(filesystem / brave-search / Notion)、你自己写的 skill,**完全是平权的** —— LLM agent 分不出来,也不应该分得出来。

加一个新 skill 5 行代码就够。接一个外部 MCP server 一条 config 就行。除了装饰器和 JSON schema,没有别的 plugin API 要学。

### 2. 双向 MCP

Skyler 既是 MCP **client**(消费 filesystem / brave-search / Notion 等任何 MCP server),也是 MCP **server**(把自己的能力注册表、角色状态、记忆暴露给 Claude Desktop / Cursor / Claude Code 等任何 MCP client)。

你的 AI 角色变成 MCP 生态里的一个节点,而不是一座孤岛。

### 3. Persona 级状态机

大多数 agent 框架只跟踪任务状态。Skyler 还跟踪**角色状态** —— LLM 驱动地累积心情、注意力、当前在做什么、最近的想法、跟你的亲密度。状态不是写死在 prompt 里的,它会随交互演化。

这就是 Momo / Mai 感觉像个具体的人而不是通用工具的原因。也是我们长期路线图里最重要那一条的基础:**persona-level learning**(角色跟你一起成长,不只是变得更能干)。

### 4. Persona Engineering 五层框架(v4-beta)

角色定义不是一坨自由文本。v4-beta 引入五层 prompt 框架(格式契约 / 模式 / 人格 / 上下文 / 对话)+ multi-variant persona schema,Tier-1(身份/性格/语气)+ Tier-2(taboo/lore/emotion triggers/voice samples)。Mai 是这套框架的参考实现(完整 Tier-1+2,见 `docs/mai_prompt.md`)。

---

## 对比

|  | Skyler | Open-LLM-VTuber | Hermes Agent |
|---|---|---|---|
| 形态 | 桌面 + Live2D | 桌面 + Live2D | CLI + messaging gateway |
| 可改造性 | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐⭐⭐ |
| 角色系统 | ⭐⭐⭐⭐ persona 五层框架 + 状态机 | ⭐⭐⭐ Live2D + persona | ❌ |
| 主动陪伴 | ⭐⭐⭐⭐ broadcast + trigger pack | ❌ 只被动 | ⭐⭐⭐ cron |
| MCP 集成 | ✅ 双向 | ✅ 只 client | ✅ workspace |
| 自我提升 skill 学习 | ❌ 路线图远期 | ❌ | ⭐⭐⭐⭐⭐ |
| 跨平台 messaging gateway | ❌ 路线图中期 | ❌ | ⭐⭐⭐⭐⭐ |
| 训练数据导出 | ❌ 路线图远期 | ❌ | ⭐⭐⭐⭐⭐ |
| 本地优先 / 无云依赖 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |

诚实说,右边三行 Hermes 现在比 Skyler 强。这些是真实差距,不假装看不见。中间四行是 Skyler 真正下功夫的地方。

---

## 快速开始

### 前置(macOS)

| 工具 | 最低版本 | 安装 |
|---|---|---|
| Node.js | 18+(推荐 22+)| `brew install node` |
| Rust 工具链 | 1.75+ | `curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \| sh` |
| Xcode Command Line Tools | 最新 | `xcode-select --install` |
| Python | 3.10+ | `brew install python@3.10` |

### 安装

```bash
git clone <你的仓库地址> Skyler
cd Skyler

# ── 后端 ──────────────────────────────────────────────
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# 编辑 .env,至少:
#   DASHSCOPE_API_KEY=sk-xxx
#   DATABASE_URL=sqlite+aiosqlite:///./skyler.db

uvicorn backend.main:app --reload
# 后端跑在 http://127.0.0.1:8000

# ── 前端(另一个终端)──────────────────────────────────
cd frontend
npm install
npm run tauri dev
# 首次 Rust 构建 5–15 分钟,之后启动很快
```

默认 LLM 是 Qwen 走 DashScope(国内不用翻墙)。换 provider 改 `config.yaml` —— Skyler 内部走 LiteLLM,DeepSeek / OpenAI / Anthropic / 本地 Ollama 都是改一行的事。

---

## Live2D 资产管理

Skyler 默认带 Live2D 官方免费样品模型 **Hiyori**(`frontend/public/live2d/hiyori/`),外加一份 **八重神子(Yae)demo 皮肤**(`frontend/public/live2d/yae/`),用于验证 per-character `motion_map_json` 切换。想换自己的角色,四步:

1. **资产放进 `frontend/public/live2d/<slug>/`** —— slug 用小写英文(例如 `yae-miko`、`momo-v2`),后面在 CharacterPanel 里 `live2d_model` 字段填的就是这个名字。
2. **目录里必须有一个 `*.model3.json` 入口文件**,还要有 `*.moc3`、`textures/`,至少一个 motion。完整 checklist 看 [`frontend/public/live2d/README.md`](frontend/public/live2d/README.md)。
3. **接通前先验 moc3 版本**:
   ```bash
   python -m tools.check_moc3_version frontend/public/live2d/<slug>/
   ```
   pixi-live2d-display 不支持 Cubism 5,version ≥ 5 或塞了 Cubism 2 的 `.moc` 都会让脚本退出码非零。
4. **CharacterPanel 里绑定** —— 打开角色编辑器,把 `live2d_model` 字段填成你的 slug,重进对话就生效。

**IP / license 隔离** —— `.gitignore` 默认 ignore `frontend/public/live2d/` 下除 `hiyori/` 以外所有子目录。你扔进去的第三方 / 委托资产不会被 track,也不会被 push 出去。这是有意的:Skyler 项目的 license 没法覆盖不属于你的资产。自制 / 已清理 license 的模型想入库时,在 `.gitignore` 末尾追加 `!frontend/public/live2d/<slug>/`。

**免责声明** —— Skyler 自己的代码用宽松 license,但**不为用户添加的任何 Live2D 资产 license 背书**。资产怎么来的、有没有授权、能不能传播,完全是用户自己的责任。

### 实操示例:从 BCSZ1.1 dump 接入八重神子

具体例子 —— Cubism 4 的八重神子资产在 `<某路径>/BCSZ1.1/`。Skyler 的 character id=2 已经叫「八重神子」,`motion_map_json` / `hit_area_map_json` 也已经由 `v3_e2_yae_maps` 迁移填好。让她渲染只差资产入位:

```bash
# 选项 A:复制资产到 slug 目录
cp -r "<某路径>/BCSZ1.1" frontend/public/live2d/yae

# 选项 B:软链接(省盘 + 改源更方便)
ln -s "<某路径>/BCSZ1.1" frontend/public/live2d/yae
```

任一种方式,`frontend/public/live2d/yae/` 都被 .gitignore 排除 —— 资产留本地,进 git 的只有"character id=2 指向 slug `yae`"这条数据迁移。验证之后刷新 UI:

```bash
python -m tools.check_moc3_version frontend/public/live2d/yae/
# 期望:[OK] version=3 (Cubism SDK 4.0)
```

打开 CharacterPanel,切到八重神子,立绘换成 BCSZ1.1。点击模型 Skyler 会播 `Start` motion(八重的初见配音),而不是 Hiyori 的 `Tap` 随机一条 —— 这就是 per-character `motion_map_json` 生效的视觉信号。

> **注意:八重等其他角色 v4-beta 仍是空骨架 persona**(只有名字 + Live2D 绑定,没有完整人格),切过去对话人格空洞。这是 v4.1 (F1) 待补项。Live2D 资产接入本身不受影响,可以先验证渲染。

> **注意:模型 motion3.json 中引用的配音 wav 默认禁用。** 部分模型(八重 BCSZ1.1 含 6 段配音)会在 motion 自带 wav;Skyler 所有语音输出统一走 LLM + TTS pipeline,让 motion 自动播 wav 会跟 TTS 重叠。当前在 SDK config 层全局关闭。未来 per-character 开关已在 ROADMAP backlog —— 鼠标点击触发的 motion 可以播原声 wav 保留演出价值,LLM 标签触发的不播让 TTS 独占。

---

## 特性

下面列的是 Skyler 当前能做的事。每一层都是设计成可以拆开来换的,没有锁死的。

### 🎙 输入与输出
- **语音输入**两种模式:
  - **手动模式** —— 点击开始录音,再点击发送
  - **VAD 模式** —— 点击激活后,Web Audio API 自动检测语音;1.5 秒静音自动发送;60 秒空闲回 sleep
- **ASR 实时回显** —— 通过 `asr_result` WebSocket 消息把识别结果即时显示在输入框上方,并写入聊天历史
- **流式输出** —— 文字和音频按句到达
- **TTS** —— 3 provider paradigm(INV-11 Stage 1.5,2026-05-26):CosyVoice(DashScope,默认 + 复刻 voice 双轨)· Fish Audio(云端,per-character 上传参考音频)· GSV(GPT-SoVITS,自部署)。Edge-TTS legacy fallback。每角色 `voice_model` JSON 解析 provider × model × voice;注册表在 `backend/config/tts_models.json`。Mai(`cid=1`)当前走 GSV `mai_v4` + 16 emotion bank(日语 TTS)。VoicePicker UI 是 inline(paradigm B),auto-save debounce 300ms。加新 model 走 `docs/adding-new-tts-model.md`。
  - **文本/语音解耦**:LLM 同流输出中文正文 + `<ja>日语</ja>` 标记 → 字幕剥成中文显示 → TTS 抽 `<ja>` 段直接送 GSV mai_v4 合成日语语音,**零额外翻译调用**。详 DESIGN_LITE §6.6.5 _语音语言机制_ 的四层 + 字幕层(含 cid=1 / cid=101 当前真实绑定)。
- **assistant 说话时自动静音 mic**(防回声 loop)
- **Tool 调用过渡** —— agent 调 tool 时先冒一句过渡话("让我看看…"),输入框同时显示对应 loading pill("查日历…"),你不会卡在 30 秒沉默里不知道是不是卡死了。chunk 14 producer/consumer + chunk 6b TTS pipeline 已实现 sentence-by-sentence streaming,经 chunk 15 实测验证体感流畅

### 🧠 记忆 & 人格(三层结构)

> **v4.0.0 更新(取代上方"0 行 / 可能未生效"的审计声明)**:audit 已完结。根因:抽取 prompt 偏 fact-only + 稀疏/闲聊 → LLM 合法返回 `[]`;子 bug:purge 不重置 extractor 指针。修复链(有界滚动摘要层 + 指针自愈/源头 reconcile + 抽取 prompt 重平衡 + 墓碑)已 ship 且对真 diff 代码核验。功能/陪伴质量待真机回归 + friend-test(验收门)。下方文字为设计描述;v4.0.0 收口记录见 DESIGN §五·补 + §十五之 Z.5.1。

- **第 1 层 短期** —— 进程内 short_term buffer,按 **(用户, 角色, conversation)** 三级隔离,每轮取最近 N turn(硬性 cap 最近 25 turn = 50 messages,`SHORT_TERM_MAX_TURNS=25`,token 成本治理;会话 messages 超过 60(`SHORT_TERM_MAX`)时滚动摘要 fold worker 介入);进程重启后从 `chat_history` 表**按 conversation 过滤**恢复(不再跨对话/跨角色串)。
- **第 2 层 长期事实记忆** —— `memory` 表,设计入库主路径为 server-side worker(`MemoryExtractor`,每 5 min batch 提取 + 5 道 quality filter [length / `SUSPICIOUS_TAG` / confidence ≥ 0.5 / tombstone / cosine dup] + entry_type 四分类 + extraction_source 四态来源标签);`save_memory` tool 为"用户明确说要记"的显式入口;检索按遗忘曲线 `score = relevance * (1+log(1+ac)) / (1+age*decay)` + threshold gate。**✅ v4.0.0:audit 完结,修复链已 ship 且代码核验(滚动摘要层 + 指针自愈 + prompt 重平衡 + 墓碑);待真机回归 —— 见上方更新。**
- **第 3 层 用户画像** —— `users.profile_data` JSON schema(profession / current_projects / interests / recurring_topics / communication_style / active_hours / language_preferences),validator 严格 hard-reject 反推词;每日 cron 自动重生。legacy `profile_summary` fallback 已在 commit `c1d65ff` (2026-05-19) 退役 ——`profile_data` 为唯一来源;`users.profile_summary` 列保留为空列（`[RETIRED]` 注释,未 DROP COLUMN）。**用户画像跨角色共享(对你的一份印象);事件/关系型长期记忆按角色隔离的归属分级(F8)是 v4.1 多角色项。**
- **活动时间线** —— 跟 `chat_history` 平行的第二条 timeline,持久化你每天的 app/URL session(已过滤 idle 时长)。角色能在对话里自然引用今天的活动("看你 VS Code 待了 3 小时,跟昨天那个项目吧?")。默认保留 30 天。
- **记忆/对话查看** —— 统一并入**左侧推拉 chat panel**(v4-beta UI 统一,见下);entry_type tab(事实 / 偏好 / 事件 / 承诺)+ extraction_source 角标 + confidence 显示。
- **记忆开关** —— 长期记忆 / 用户画像 / 屏幕感知 / web search / 活动时间线 全在 Settings 可单独 toggle。

### 🤖 Multi-Agent Intelligence
- **ChatAgent direct flow** —— LiteLLM tool calling 在一个 LLM round-trip 里同时驱动 memory + 内建工具 + MCP 工具(不需要单独 planner)
- **真 MCP 工具接入** —— 可扩展 `ToolRegistry`,双向(Skyler 既是 client 又是 server)
- **LiteLLM 统一 LLM 层** —— DeepSeek / Qwen / OpenAI / Claude(config 切换)
- **Web 搜索** —— 模型内置(Qwen Max / DeepSeek),`enable_search` 开关

### 🎭 多角色对话(conversation 锚定语义)
- **conversation 锚定** —— 切角色 = 切到该角色**最新对话**(无则新建);一个 conversation 1:1 绑一个角色,角色身份由对话推导。
- **规则 A(用户发起)** —— 对话发起那一刻锁定 conversation,响应全程贯穿该 conversation;即使中途切走,回复仍无条件投递回原对话(不丢)。
- **规则 B(系统主动)** —— 主动消息触发时快照对话,投递前校验是否仍是当前对话;过时(用户已切走)则静默丢弃,不冒到错的对话。
- **每角色音色** —— `character.voice_model` JSON:cosyvoice slim schema `{provider, model, voice, instruct_supported, tts_language?}`,或 fish / gsv 完整 schema(从 `tts_models.json` spread 默认值:`gpt_weights` / `sovits_weights` / `server_url` / `emotion_bank_dir` / `inference_params` 等);空值 fallback 到全局默认。
- **已知限制** —— v4-beta 仅 Mai(`cid=1`)有完整 persona;其他角色为空骨架,v4.1 (F1) 逐个补真 persona。

### 🎨 对话 UI(v4-beta 统一)

v4-beta 把分裂的对话/历史入口收敛成一套:

- 右上角独立"历史"入口 **已移除**;旧浮现台词气泡 **已移除**(有 bug + 与 chat panel 功能重叠)。
- 对话内容统一由**左侧推拉 chat panel** 承载(显示当前 conversation 完整聊天记录)。
- 左 conversation list + 右 chat panel **双推拉**;切角色自动加载该角色最新对话内容(无对话则空状态引导);两侧全收起 = 纯立绘 Galgame 沉浸;窗口 <1280px 自动降级布局。

### 🎨 UI:8 套主题

Settings → UI 风格切换:

| 主题 | 调性 |
|---|---|
| 🌫️ 莫兰迪 | 暖色极简奶油 |
| 🌆 黄昏 *(默认)* | 梦幻紫色暮色 |
| 🌊 玻璃 | glassmorphism 冷色 |
| 🌸 水彩 | 粉色 |
| 🌌 极光 | 深海绿青 |
| 🌷 樱花 | 樱花夜 |
| 🌃 赛博 | 赛博绛红 |
| 💜 薰衣草 | 薰衣草雾 |

所有组件走 `var(--color-*)`(styles/themes.css),没有硬编码 Tailwind 色值。状态存 `localStorage`,首次渲染 `data-theme` 上 mount 防闪烁。

`lucide-react` 图标全组件覆盖。

### 🔔 主动陪伴
- **Trigger pack** —— `lunch_call` / `dinner_call` / `bedtime_chat` / `long_idle` 常驻;`wake_call` ⇄ `morning_briefing` 互斥(由 `config.proactive.mode` 选其一)。角色在该出现的时候才出现,不是每个 polling 都说话
- **活动触发** —— `ide_open` / `music_playing` / `long_focus` / `url_tech_doc` / `late_night_ide` —— 上下文快路径分类,加 LLM 慢路径判官应对模糊场景(停留 5+ min、多重 throttle、daily cap、idle 闸 —— 人离开电脑就闭嘴)
- **邀请对话模式** —— 主动不只是推送;trigger 可以先冒一句短招呼等你回应,再走完整对话
- **绑定保证(v4-beta)** —— 主动消息走规则 B:投递前校验当前对话,切走后过时消息静默丢弃,不会冒到错的角色对话里

### 🛠 工具生态
- **日历** —— Apple EventKit(默认,零网络)+ Google Calendar(可选)
- **音乐** —— 网易云(2 dispatcher × 14 actions:`netease_web` 7 [`daily_recommend` / `personal_fm` / `play_song` / `play_playlist` / `play_playlist_by_id` / `like_current` / `search`] + `netease_local` 7 [`play_song` / `play_playlist` / `pause` / `resume` / `stop` / `next_in_queue` / `now_playing`] · mpv-first 真闭环 / URL Scheme fallback)+ macOS 媒体控制 5 actions(`next_track` / `previous_track` / `play_pause` / `now_playing` / `set_volume`,Apple Music / Spotify / YouTube / NCM 客户端 通吃)。**音频源优先级**(2026-05-31 INV-18):session 用过 mpv-first → 后续控制首选 `netease_local.*` · 否则 fallback `media.*` · 用户明确"系统级"直接 `media.*`
- **B 站** —— 11 个 capability(search / video info / subtitles 给 AI 总结 / etc.)
- **小红书** —— 只做 URL 被动解析(红线锁在代码层:不暴露 search / recommend / feed)
- **Docx** —— 读 / 写 / append,沙盒在 `~/Documents/Skyler/docs/`
- **Notion** —— 通过官方 `@notionhq/notion-mcp-server` MCP 接入
- **剪贴板助手** —— 最近 50 条 ring buffer(24h TTL,从不写 SQLite),`get_recent` / `summarize` / `translate`
- **屏幕感知** —— active app + 浏览器 URL + 页面正文(19 条黑名单守银行 / 邮箱 / 社交 / localhost)
- **以及自定义 skill** —— 见 [扩展 Skyler](#扩展-skyler)

---

## 架构

Skyler 的架构不是凑出来的。每个大决策 —— 能力注册表、双向 MCP、persona 级 `character_states`、活动时间线、conversation 锚定绑定语义 —— 都是定位决定的直接结果。一个"可改的角色框架"必须有平权的扩展机制、生态参与、人格持久化。想知道为什么一块东西长这样,见 [DESIGN_LITE.md](DESIGN_LITE.md)(当前设计真源) 或 [docs/archive/DESIGN.md](docs/archive/DESIGN.md)(历史机构记忆档案,2026-05-19 归档)。

```
用户输入(语音 / 文字)
  ├─ [VAD 模式]  Web Audio API 检测语音 → MediaRecorder
  │              静音 > 1.5s → 停 → 发音频
  ├─ [手动]      用户点击 → MediaRecorder 开始/结束 → 发
  └─ [文字]      直接打字发送

  → ASR        faster-whisper(后端)→ asr_result 推前端
  → ChatAgent  context 装配 + LiteLLM tool calling
                ├─ short_term:(用户,角色,conversation) 三级隔离,cap 25 turn (=50 messages)
                ├─ memory tools:save / delete / list / compress(LLM 驱动)
                ├─ 内建工具:ToolRegistry(MCP 可扩展)
                ├─ capabilities:@register_capability 自动入 ToolRegistry
                └─ web search:模型内置(Qwen Max / DeepSeek)
  → emotion    首句解析 <emotion>X</emotion> → 锁定本轮 emotion
  → TTS        get_tts_engine(voice_model) → CosyVoice / Fish / GSV / Edge fallback
                (Mai cid=1 走 GSV mai_v4 ja;cid=101 走 fish s2-pro ja)
  → 输出:      流式文字 chunk + 按句音频 chunk + asr_result 预览
                (按发起 conversation 投递,规则 A/B)

能力注册表:
  @register_capability 装饰器 → CapabilityRegistry 单例
    ├─ Consumer.CHAT_AGENT  → 自动导出 OpenAI schema → ToolRegistry → ChatAgent
    ├─ Consumer.SCHEDULER   → APScheduler cron / interval triggers
    └─ Consumer.WEBHOOK     → /api/webhooks/n8n/{trigger}(Bearer + HMAC 认证)
  GET /api/capabilities → frontend CapabilityPanel(按 category 卡片 + 健康点)

双层集成:
  backend/integrations/<service>.py     低层 client(OAuth、retry、健康检查)
  backend/capabilities/<service>.py     每个 action 5 行 @register_capability

双向 MCP:
  ┌─────────────────────────────────────────────────────────────────┐
  │  CapabilityRegistry  ←  装饰器  | 运行时  | aggregator           │
  │  来源 1:@register_capability(内建:time / calendar)            │
  │  来源 2:MCP client(消费外部 server,如 filesystem / brave / Notion) │
  │  Skyler-as-server:POST /mcp 把注册表暴露给                      │
  │            Claude Desktop / Cursor / Claude Code(Bearer 认证)  │
  └─────────────────────────────────────────────────────────────────┘

Persona 级状态:
  character_states 表  ← mood / intimacy / current_thought / current_activity
  <state_update> LLM 标签协议(跟 <emotion> 平行)
  每日 intimacy_decay cron
  用户画像跨角色共享(对你的一份印象)

conversation 锚定绑定:
  切角色 → 该角色最新 conversation(无则新建);角色由 conversation 推导
  规则 A:用户发起 → 发起锁定 conversation,响应无条件回原对话(不丢)
  规则 B:系统主动 → 触发快照,投递前校验当前对话,过时丢弃
  character_switch 不进 turn 调度 → 不误杀进行中回复

活动时间线:
  ActivityWatcher(30s 轮询)
    → (app, url, idle 标志)元组变化 → session 边界
    → SessionWriter 持久化到 activity_sessions 表
    → ChatAgent system-prompt 注入("用户今天 X 用了 Y 小时")
    → 5 道隐私闸(黑名单 / 写入层 dedup / idle 过滤 / 显式删除 / 全本地)
```

---

## 技术栈

- **后端**:Python 3.10 / FastAPI / SQLAlchemy(异步)/ APScheduler / LiteLLM / faster-whisper / sentence-transformers / pyobjc(macOS-only 部分)
- **前端**:Tauri 2 / React 18 / TypeScript / Vite / Tailwind / Zustand / lucide-react / pixi-live2d-display(Cubism 4 only;moc3 ver ≥ 5 走 console.warn 回退)
- **TTS**:3 provider paradigm(CosyVoice / Fish Audio / GPT-SoVITS 自部署),per-character,注册表在 `backend/config/tts_models.json`(pydantic 校验)。Edge-TTS legacy fallback。Mai(`cid=1`)当前走 GSV `mai_v4` + 16 emotion bank(ja)。inline VoicePicker UI(paradigm B,auto-save)。详 `docs/adding-new-tts-model.md`。
- **ASR**:faster-whisper(本地)
- **LLM**:LiteLLM(Qwen / DeepSeek / OpenAI / Claude / 本地 Ollama —— config 切换)
- **DB**:SQLite + Alembic 迁移
- **MCP**:stdio + streamable HTTP,双向
- **Embeddings**:sentence-transformers(paraphrase-multilingual)
- **平台**:macOS Apple Silicon 主力;Linux/Windows 部分支持

---

## 扩展 Skyler

Skyler 是设计成给你扩展的。四条扩展路径覆盖常见 case。

### 1. 加一个 skill(内建 capability)

`backend/capabilities/` 下扔一个文件,装饰一个函数,重启后 LLM 就能调:

```python
# backend/capabilities/weather.py
from backend.capabilities.registry import register_capability, Consumer

@register_capability(
    name="weather.current",
    description="查指定城市的当前天气。用户问天气时调用。",
    consumers=[Consumer.CHAT_AGENT],
    parameters={
        "type": "object",
        "properties": {
            "city": {"type": "string", "description": "城市名,如 '东京'"}
        },
        "required": ["city"],
    },
)
async def get_current_weather(city: str) -> dict:
    # 调你喜欢的 API,返 JSON 可序列化 dict
    return {"city": city, "temp_c": 18, "condition": "多云"}
```

就这样。不用专门注册,不用 plugin manifest。装饰器 + JSON schema 就是契约。

完整 pattern(错误处理、健康检查、多 consumer)见 [docs/skills-extension-guide.md](docs/skills-extension-guide.md)。

### 2. 接一个外部 MCP server

在 `config.yaml` 加一条:

```yaml
mcp_clients:
  - name: filesystem
    command: npx
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/Users/me/Documents"]
    enabled: true
    expose_via_skyler_server: false   # 不要再暴露给 Claude Desktop
```

重启后 MCP client 连上,发现 tool,反向注册成 `ext.filesystem.<tool>` capability。ChatAgent 自动认。

任何 MCP server 都行:brave-search、Notion(`@notionhq/notion-mcp-server`)、Anthropic 的参考 server,或者你自己写的。见 [docs/mcp-client-setup.md](docs/mcp-client-setup.md)。

### 3. 换 Live2D 模型

见上面 [Live2D 资产管理](#live2d-资产管理)章节。前端 `live2d_scanner` 自动发现 `frontend/public/live2d/<slug>/<slug>.model3.json`。Motion map 和 emotion 绑定是 per-character 的;见 [docs/live2d-setup.md](docs/live2d-setup.md)。

### 4. 换 LLM provider

Skyler 内部走 LiteLLM,所以 LiteLLM 支持的 provider 都是改 `config.yaml` 的事:

```yaml
llm:
  provider: openai          # 或 'anthropic' / 'deepseek' / 'ollama' / etc.
  model: gpt-4o
  api_key_env: OPENAI_API_KEY
```

本地 Ollama 模型、私有部署、自定义 endpoint —— 全部一个 config 字段。不动代码。

---

## Skyler 不是什么

- Skyler **不是**开箱即用的 VTuber app。想要包装好的直播 / 角色 UX,去用 [Open-LLM-VTuber](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber)。
- Skyler **不**做自我提升的 skill 学习。Skill 不会用着用着自己变好。这事 [Hermes Agent](https://github.com/NousResearch/hermes-agent) 做得很到位。我们长期路线图上有这事,叫 *persona-level learning*(角色成长,不只是 skill 库变厚)。
- Skyler **不**带 messaging gateway(Telegram / Discord 等)。中期路线图项。当前是桌面 only。
- Skyler **不**导出你的对话数据作为训练数据。长期路线图项,会作为"用你跟角色的对话训练你自己的小模型"功能。
- Skyler **不**跟 LangChain / AutoGen 这种通用 agent 框架比。Skyler 专门是*角色驱动的桌面 agent*。要是不想要角色这一层,就不该用 Skyler。
- v4-beta **暂不**开放多角色完整体验 —— 当前主推 Mai 单角色(cid=1 GSV mai_v4 ja / cid=101 Fish s2-pro ja 双引擎并行验证,文本恒中文)。其他角色 persona + 长期记忆链路均为 v4.0.0/v4.1 收口项,诚实列在上面"v4-beta 当前状态"和路线图里。

诚实列这些,是因为差距真实存在。这些也就是路线图。

---

## 路线图

完整路线见 [ROADMAP.md](ROADMAP.md)。

- **v4.0.0 收口(进行中)**:长期记忆链路审计 ✅(修复链已 ship,代码核验;待真机回归)→ Stage3 Tauri 打包 / dmg / dogfood / tag。_TTS 每用户日字数上限 + 主对话节流 **移出 v4.0 范围、deferred** 至多人测试再议;当前仅 `tts_call_log` 监控用量,无强制闸。_
- **v4.1**:~~ja 后处理翻译重做(F0)~~ **作废**(已被 INV-11 GSV 接入取代) / 七套角色真 persona(F1)/ 长期记忆归属分级(F8)/「记忆架构 v2」(一角色一永久对话流 + RAG)/ 切角色对话联动收尾(F2)/ LLM 性能 / CosyVoice 弱网超时 / 测试债清理
- **中期**:补诚实列的缺口(messaging gateway、训练数据导出、capability marketplace)
- **远期**:persona-level learning(`character_states` 真的能成长)
- **长期愿景**:在桌面端建立一个小而忠诚的可塑型 AI 角色容器爱好者生态

---

## ⚠️ 已知问题

按优先级排列。日常运行不阻塞,但未来需要处理。完整 backlog 散见 [ROADMAP.md §Tech Debt & Backlog](ROADMAP.md#tech-debt--backlog) / [docs/archive/DESIGN.md §十四之B](docs/archive/DESIGN.md);本块是 manual 验收期间发现的活跃 issue 汇总。

> **注**:本节当前仅同步了 `characters.yaml` 双源一条;EN README 完整列了 19+ 条(7 文件 pre-existing test failures / 网易云 mpv / MCP 凭证加密 / `config.yaml` 双写源 / 表层重构 等),逐条翻译同步留作后续单独小刀。

### 低

**`characters.yaml` vs DB 双源真相**(v3-E1 留 v4 Scheme C 修)

- 当前 Scheme B(DB 主 + YAML fallback)—— `_build_messages` 优先 DB persona,YAML fallback
- **2026-06-01 更新**:yaml 仅含 **5 个内建角色**(八重神子 / 默认 / 荧 / 凝光 / 神里绫华),非 DB 全集;`cid=99/100/101` 等仅 DB seed,不在 yaml
- 计划 Scheme C(v3-G 末或 v4):删 yaml、DB 单源、迁移脚本、`prompt_manager` 改 DB-backed
- **2026-05-19 更新**:原条目含的 `switch_character 改 DB query` 已不再适用 —— `switch_character` LLM tool 在 commit `71b6e99` 已整体下线(schema 不暴露给 LLM;前端切角色走 WS `character_switch` 帧);该 backlog 性质已从"接线修复"变为"yaml 退役 + prompt_manager 单源化"

---

## 先前的工作

Skyler 站在两个项目定义出来的空地中间:

- **[Open-LLM-VTuber](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber)** —— 打磨好的 VTuber 陪伴体验。想要一个开箱即用的 app,选它。
- **[Hermes Agent](https://github.com/NousResearch/hermes-agent)**(Nous Research 出品)—— 服务器跑的个人 agent 平台,带自我提升 skill 循环。

它俩在各自方向上都做得很好。Skyler 瞄准的是它俩中间的空地 —— 桌面、角色驱动、能拆到 agent 内核、所有权归你。架构选型是顺着这个空地推出来的,不是按竞品 feature 表抄出来的。

它们当前在哪些事上比 Skyler 强,见上面 [对比](#对比)表 —— 老老实实列出来,让你选对工具。

---

## 项目状态

**v4-beta 收口阶段 + INV-11 全段 ship(2026 年 5 月)。** Persona Engineering 五层框架 + 记忆/对话三级隔离 + conversation 锚定绑定语义 + 对话 UI 统一 + Mai 日语 TTS 走自部署 GSV mai_v4 + 9 角色 provider × model × voice paradigm 已全部 ship 并真机验证。当前主推 Mai 单角色陪伴(文本恒中文,语音可日)。

剩余 v4.0.0 收口项:长期记忆链路审计 ✅(修复链已 ship 且代码核验;待真机回归)→ Stage3 打包发布。_TTS 每用户日字数上限 + 主对话节流 **移出 v4.0 范围、deferred** 至多人测试再议;当前仅 `tts_call_log` 监控用量,无强制闸。_ 完整实施日志(每个 chunk、hotfix、UX 迭代)在 [ROADMAP.md](ROADMAP.md) —— 那是真实的历史。

---

## 许可证

目前 **All rights reserved**(无 LICENSE 文件)。仓库公开后会切换到宽松许可证(MIT 或 Apache 2.0)—— 注意:之后捆绑的 Live2D 模型有 Live2D Inc. 自己的许可证,**不在** Skyler 项目许可证覆盖范围内。

### Live2D 模型许可

Skyler 当前开发期使用 Live2D 官方样本模型 **Hiyori**(位于 `frontend/public/live2d/hiyori/`),由 illustrator Kani Biimu 创作,并附带一份 **八重神子(Yae)demo 皮肤**(位于 `frontend/public/live2d/yae/`)用于验证 per-character `motion_map_json` 切换。Hiyori 遵循 **Live2D Free Material License Agreement**,开发/学习/小规模商用 OK;中大型企业商用需向 Live2D Inc. 申请书面授权。Yae demo 皮肤遵循其上游 license。

后续版本会替换为自有/购买的模型,届时 Skyler 项目本身的 license 不覆盖该模型,模型遵循各自原始 license。

---

## 贡献

私有开发期间不接受外部贡献。等公开后见。
