<!-- 版本 × 功能演进矩阵。来源:drafts/skyler-evolution.md + git log + IMPLEMENTATION_LOG.md 章节标题切版本边界。
     仓库无 git tag,版本列按 IMPLEMENTATION_LOG.md 章节标题 + commit 时间窗推:
       v3 = IMPLEMENTATION_LOG §"v3 封盘 Retrospective"(L498) 之前的 v3-WIP / v3-E / v3-F / v3-F' / v3-G / v3-G' / v3-H 各 chunk
       v3.5 = §"v3.5 后续路线"(L977) chunk 5 ~ chunk 10(2026-05-11 ~ 05-13)
       v4-beta = §"v4-beta 收口批次"(L51 = 2026-05-16)起,直到 §"进入动画 + 持久角色 + 立绘馆发牌入场批次"(L1559 = 2026-06-07~08)止
       v4.0 = 2026-06-13 起的 Live2D framing / GSV 本地 / MCP batch / UIA / 玻璃自定义 / 角色详情 / 双开关 / 时间戳 / 台词气泡 / DailyAgent Stage1
       Next = v4.1+,计划态
     近版本(v4-beta / v4.0)边界更可信(逐 commit 锚得到);早版本(v3 / v3.5)粒度更粗。 -->

# 🧬 Skyler · 能力演进矩阵

> 横轴 = 版本,纵轴 = 功能分类。看每块能力在哪个版本长出来、长成什么样。
> 当前能力到哪一步 → [ROADMAP《当前能力状态》](../ROADMAP.md#当前能力状态)。每个 chunk 的细节 → [IMPLEMENTATION_LOG.md](../IMPLEMENTATION_LOG.md)。

**图例**:✅ 该版本落地并验 · 🔧 该版本改进 / 重做 · 🚧 该版本在做未完 · 🔵 计划升级 · — 该版本无动作

> 版本边界回 `IMPLEMENTATION_LOG.md` 章节标题切(仓库无 git tag),格内 commit 锚直接对应该版本批次。早版本(v3 / v3.5)粒度更粗;近两版(v4-beta / v4.0)逐 commit 锚得住。

---

| 功能分类 ＼ 版本 | v3 | v3.5 | v4-beta | v4.0 | Next(v4.1+) |
|---|---|---|---|---|---|
| **角色机制** | ✅ persona 基础(`characters.persona` 单文本字段)[^1] | — | ✅ 五层框架 + 持久状态字段 + multi-variant schema + conversation 锚定(migration `v4_persona_thickening_segment1`) | ✅ 角色详情中心 Build 1(`b75efdc` 2026-06-19) | 🚧 状态读回 + DailyAgent + 上下文仲裁(Brick 1-4) |
| **记忆** | ✅ 基础短期(沿用 v2.x)[^1] | ✅ 三级隔离 + 遗忘曲线 + 用户画像 + 活动时间线(chunk 9 `ba0399e` + chunk 10 worker · 2026-05-12) | 🔧 滚动摘要沉淀 + 墓碑(`3f3be08` 2026-05-17)[^2] | 🔧 链路 audit + 修复链(`docs/INV-13-proactive-shortterm-pollution-audit.md`) | 🚧 RAG 第 4 层 + 架构 v2(一角色一永久对话流) |
| **对话** | ✅ 逐句流式(`2226929` concurrent sentence synthesis + ordered playback) | 🔧 tool 过渡话 + loading pill(UX-004 backend `244d5d7` + frontend `7f35c1e` 2026-05-13)[^3] | — | ✅ 深度思考 / 联网双开关(`ba835af`)+ 聊天气泡时间戳(`9d45fd1`)| — |
| **多模态(语音 / 图片)** | 🔧 TTS / ASR 基础(cosyvoice SSML emotion `de7ebe2` v3-G' chunk 1a) | — | ✅ GSV provider paradigm + 语言解耦(INV-11 Stage 1+1.5 `fd11d74` 2026-05-26)· Fish s2-pro provider(INV-9 Phase 2 `f07a842` 2026-05-22) | 🔧 GSV 本地迁移 `mai_v4`(ship `a4a2681` 2026-06-17 · merge `89b9f4e`)· 文件输入 / 输出(`98e0b3e` / `0d4e246`)· 图片输入(`0ed1b37` / `cb99fef`,持久化未做) | 🚧 图片输入持久化 · Fish provider 真挂第二角色 · 图片输出(ComfyUI) |
| **Live2D** | ✅ 基础 render(v3-E1 Hiyori `0eed29a` + v3-E2 多模型)| — | ✅ 表演层(转头 ±15° / 眨眼呼吸 / 身体微晃 / 冰糖去水印 `c14065b` 2026-06-14)+ 模型管理 | 🔧 取景层 per-model framing(`79f9f2f`)+ 台词气泡(widget 🟢 已上 / panel 🟡 暂关 · `2bc42da`) | 🚧 AI 导演 + 贴纸系统 + 公参表 · Cubism5 |
| **桌面感知 / 控制** | — | ✅ 文本级屏幕感知 chunk 8a(`3fe2183` 2026-05-12)+ 慢路径 LLM judge + idle 闸 chunk 8a-ext(2026-05-13)+ 活动时间线 | — | ✅ 只读 AX 读屏 `read_current_screen`(`bf66ec3` 2026-06-21,设计 → [`docs/design/desktop-control.md`](./design/desktop-control.md))| 🚧 写控件确认门真验 · 屏幕视觉 VLM(AX 盲区 fallback) |
| **主动陪伴** | ✅ trigger pack 雏形 + 时间感知(v3-F') | 🔧 快路径分类 + 慢路径 LLM judge + idle 闸(chunk 8a-ext `e6873af` / `7927371` 2026-05-13 · daily_cap 共享) | — | — | 🚧 据角色状态搭话(待 Brick 1 · 状态真读回) |
| **工具 / MCP** | ✅ 双向 MCP(`7544df5` connect external + `6714374` expose registry) | ✅ per-tool 开关(UX-001 `dd8169d`)+ skill 集成 demo(chunk 7 `1c62385` 2026-05-11) | — | ✅ 服务器搜索(`5cef7b9`)+ 别名 / 昵称(`7298ee9`)+ dangerous_tools 二次确认(`e805d34`)+ batch 2 自校验 / browser-login / WS 边界(`ab7f94a`) | 🚧 凭证进系统钥匙串 · 图片生成(ComfyUI) |
| **UI / 界面** | — | — | ✅ 大窗陪伴态重做 + 浮玻璃组件(`4399494` / `c6da1e6`)· 进入动画 + 立绘馆发牌入场(`3068849` 2026-06-07~08)· 系统状态浮层(`4cb4eec`) | ✅ 玻璃外观自定义器(`16d3afa`)+ 角色详情中心 Build 1(`b75efdc`) | 🔵 整体视觉升级 |
| **可观测 / 启动** | — | — | ✅ 用量 / 资源 / 启动监控 + 系统状态页(`4cb4eec`)+ 启动健康四路 gate(进入动画批 2026-06-07~08) | — | 🚧 成本面板 + 缓存命中率 · dmg 打包 / 自动更新 / CI release |

---

## 备注

- **列边界回 `IMPLEMENTATION_LOG.md`** —— 仓库无 git tag,版本列以 `IMPLEMENTATION_LOG.md` 章节标题为切点(见顶部 HTML 注释)。v4-beta / v4.0 边界以 commit 锚得住(2026-06-13 是非正式分界);v3 / v3.5 粒度较粗,合并写入。
- **「Next(v4.1+)」列**:计划态,不是已发;跟 ROADMAP《近期计划》同步。
- 本矩阵只给"长出来的脉络",不替代 ROADMAP 的当前状态、也不替代 IMPLEMENTATION_LOG 的 chunk 细节。

[^1]: v3 行内"基础"标注 = v2.x 沉淀进 v3-WIP baseline(`61c4d7b "Skyler v3-WIP baseline: v2.7 + v3-A/B/C/D in progress"`);精确分界在仓库 history 之前,无法 commit 锚。
[^2]: 墓碑表 commit `3f3be08` 2026-05-17 严格属 v4-beta 窗口,但功能上延续 v3.5 chunk 9 遗忘曲线 / chunk 10 server-side worker · 一并写入 v4-beta 列。
[^3]: UX-004 commits 2026-05-13 落在 v3.5 (~05-12) 与 v4-beta (~05-16) 中间;按功能批次归 v3.5 收尾。
