# INVESTIGATION 索引

> 跨 INVESTIGATION.md + INVESTIGATION-2.md 的逐刀索引。
> 每行：日期 | 主题 | 一句话结论 | 位置（文件 + 节标题）

INVESTIGATION.md 已封存（2086 行过长不再追加）；INVESTIGATION-2.md 从前端 + 性能阶段起用。

---

## 全部刀次（按时间倒序）

| 日期 | 主题 | 一句话结论 | 位置 |
|---|---|---|---|
| 2026-05-20 00:21 | **INV-3 · token 治理轮 第一刀（如实收口）** | 原假设代码层双排除；主路径 40+ 轮实测封顶 ~22.7k，43-68k 未复现；tools_schema 13.25k 实测确认；summary 全 0 但 extractor 活（矛盾）；真凶疑在未观测的主动/后台链，转第二刀（⑤ 待查清单 6 条，含 fold 机制认知分歧待代码裁决） | INVESTIGATION-3.md |
| 2026-05-19 22:21 | **docs 整理轮（归档第一刀 + 真源对齐第二刀）** | 40 份 .md 治理；A 方案：DESIGN.md 冻结归档 / DESIGN_LITE 升真源；第一刀 19 份 git mv R100 零字节改；第二刀 5 真源 6 类改动（死链 / 退役同步 / HEAD 锚 / 新成果补录 / LITE 补位 / 新挂起项）；"未 commit" 硬校验通过 | INVESTIGATION-2.md |
| 2026-05-19 15:30 | **性能治法弹药** | persona Mai 实测 2,759 tokens（修正上一版误判，进 Top-3 最肥块）；ADDENDUM 97.8% 真增量难压；活动 timeline 有硬 cap 非膨胀；最大膨胀仍是工具 schema 11.1k（懒载理论可省 9-10k） | INVESTIGATION-2.md |
| 2026-05-19 15:09 | LLM prompt token 分块账单 | activity timeline 8h heavy 154 tokens 有硬 cap；首要膨胀 = tool schemas 11.1k + ADDENDUM 3.2k 固定 95% | INVESTIGATION-2.md |
| 2026-05-19 04:52 | 前端全面重核 + FRONTEND-OVERVIEW 校准 | §3.2 5 条争议项判错 4 + 1 半对；SystemStatus 仅前端面板不进 LLM；MemoryViewer / VoiceButton 实测死代码 | INVESTIGATION.md |
| 2026-05-19 04:24 | clipboard 溯源 + 前端勘查误判自查 | clipboard UI 真有（Settings ClipboardSection 160 行），原判错；agent 报告整段抄录是失误根因 | INVESTIGATION.md |
| 2026-05-19 03:51 | memory.confidence 字段溯源 | confidence 是 chunk 10 (2026-05-12 a692ac9) 早就有的字段，validator 入库前阈值过滤真活，c1d65ff 零触动 | INVESTIGATION.md |
| 2026-05-19 02:58 | todos 退役 + profile_summary 条件核删 | 删 12 文件（agents/memory + planner + scheduler/task 等）；delete_memory 活路径零触动；profile_summary 真死一并删 | INVESTIGATION.md |
| 2026-05-19 02:32 | todos 退役 recon | apple_calendar 是 macOS EventKit 内建非 MCP；AlarmScheduler 真活但 owner_type='alarm' 零写入源；prompts.py 幽灵工具 add_todo/personality 等可整删 | INVESTIGATION.md |
| 2026-05-19 02:21 | 前后端对齐 · profile 与 todos 核实 | `/api/profile` GET 只显 legacy `profile_summary`；真"用户画像"是 `profile_data`；todos LLM 写入路径已完全断（MemoryAgent dead） | INVESTIGATION.md |
| 2026-05-19 01:16 | 后端收尾 · 文档止血整合 | ROADMAP 1477 行历史外迁至 IMPLEMENTATION_LOG.md（byte-perfect sha1 校验）+ DESIGN_LITE §4 补 conversation_summary / mcp 三表 | INVESTIGATION.md |
| 2026-05-19 01:03 | 第二刀 · 删 12 孤儿 character_states | 12 孤儿 cid (300-700) 全 DELETE；character_states 21→9 行；零 sibling 表残留 | INVESTIGATION.md |
| 2026-05-19 00:49 | 第一刀 · switch_character 充分档 + 孤儿核实 | registry.py 删 switch_character 注册；prompts.py + tool_addendum.py 删引导文字；12 孤儿 character_states 调研结论"零活消费者可安全删" | INVESTIGATION.md |
| (2026-05-18 起前期) | 第 1-4 节 · switch_character 调用链 + characters DB 全貌 + 悬而未核发现 + 调研结论 | switch_character 仅 builtin tool，前端切角色走 WS frame；characters 表 9 行（cid=1 Mai 借壳，101 独立 ja 模式）；M-6 ChatHistoryDrawer 真清 + L-6 SHORT_TERM_MAX=30 + L-7 voice_samples 真注入 + L-8 cid=1 voice 已 Z.8 改 zh | INVESTIGATION.md (§1-§4) |

---

## 主题聚类（同主题跨刀次串读用）

### 1. 性能 / Token 治理（持续主题）

- 2026-05-20 00:21 INV-3 第一刀 · 如实收口（INVESTIGATION-3.md）— 40+ 轮实测封顶 22.7k 未复现 43-68k；tools_schema 13.25k 实测；summary 全 0 ↔ extractor 活的矛盾；真凶疑在主动/后台链，转第二刀（⑤ 6 条，含 fold 机制认知分歧）
- 2026-05-19 15:30 性能治法弹药（INVESTIGATION-2.md）— 修正 persona 误判 + 懒加载地形
- 2026-05-19 15:09 token 分块账单（INVESTIGATION-2.md）— activity timeline cap 验证

### 2. 前端勘查 + 失误教训

- 2026-05-19 04:52 前端全面重核（INVESTIGATION.md）— §3.2 5 条判错 4
- 2026-05-19 04:24 clipboard 溯源 + 误判自查（INVESTIGATION.md）— 失误根因

### 3. todos / profile_summary 退役链

- 2026-05-19 02:58 退役实施（INVESTIGATION.md）— 12 文件改动 commit c1d65ff
- 2026-05-19 02:32 退役 recon（INVESTIGATION.md）— 替代者 apple_calendar 确证
- 2026-05-19 02:21 前后端对齐核实（INVESTIGATION.md）— 写入路径已断

### 4. character_states 孤儿清理

- 2026-05-19 01:03 第二刀 DELETE 12 行（INVESTIGATION.md）
- 2026-05-19 00:49 第一刀 + 孤儿调研（INVESTIGATION.md）

### 5. switch_character + characters 命名

- 2026-05-19 00:49 第一刀 + commit 71b6e99（INVESTIGATION.md）
- 早期 INVESTIGATION.md §1-§4 调研

### 6. memory 字段 + schema

- 2026-05-19 03:51 confidence 溯源（INVESTIGATION.md）

### 7. 后端收尾 / 文档止血

- 2026-05-19 01:16 ROADMAP 外迁 + DESIGN_LITE 补表（INVESTIGATION.md）

### 8. 文档治理（新增主题）

- 2026-05-19 22:21 docs 整理轮 — 归档第一刀 + 真源对齐第二刀（INVESTIGATION-2.md）—— A 方案 / 4 政策决策 / 19 份归档 R100 零字节 / 5 真源 6 类改动 / "未 commit" 硬校验

---

## 备注

- 本索引仅记录正式刀次 / 调研段。零碎 bug fix 不入。
- 每次 INVESTIGATION-2.md 追加新刀次时，本表同步加一行。
- INVESTIGATION.md 已封存不再追加；新刀只入 INVESTIGATION-2.md。
- "一句话结论"力求承重不修饰，便于跨周回看快速定位。
