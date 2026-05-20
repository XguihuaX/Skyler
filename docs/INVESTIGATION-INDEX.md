# INVESTIGATION 索引

> 跨 INVESTIGATION.md + INVESTIGATION-2.md 的逐刀索引。
> 每行：日期 | 主题 | 一句话结论 | 位置（文件 + 节标题）

INVESTIGATION.md 已封存（2086 行）；INVESTIGATION-2.md 已封存；INVESTIGATION-3.md 1098 行封存。
INVESTIGATION-4.md 工具治理子轨 B，暂停在 §1（203 行），子轨 A 完成后续 §2。
INVESTIGATION-5.md 自 2026-05-20 prompt caching 子轨 A 勘查与实施起用。

---

## 全部刀次（按时间倒序）

| 日期 | 主题 | 一句话结论 | 位置 |
|---|---|---|---|
| 2026-05-21 | **INV-4 §3 · 子轨 B · 三类候选评估 + v4.1 实施清单** | P1 入口折叠 4 group(bilibili 11→1 / netease 13→2 / media 5→1 / apple_calendar 4→1)估省 **~5,960 tokens** + dispatcher 设计草图 + tool_addendum 引导重写;P2 desc 精简 top 10 长 cap 估省 **~700 tokens**;P3 character.set_activity 与 `<state_update>` tag 100% 重叠,clean cut 退役 ~150 tokens;PM §2.5 估 8-10k 校正为 **~6.8k**(扣 union schema 开销);v4.1 实施清单 6 动作排序按风险×工程量×收益;P4 MCP lazy-load 挂 v4.1+ backlog | INVESTIGATION-4.md §3 |
| 2026-05-20 | **INV-4 §2 · 子轨 B · proactive/reactive 三分审计** | 58 个 LLM 可见 capability 全部分类:**1 proactive**(character.set_activity) / **5 hybrid**(全 calendar+time 类) / **52 reactive**;严格判定下"真 proactive"远低于 PM 预测 ≤5;notable 5 条(proactive 稀缺/save_memory 与 brief 例矛盾/screen.* 边缘/snooze_wake_call misnomer/hybrid 全 calendar+time);§3 优先级建议主战场 = bilibili+netease+media+apple_calendar 33 cap 入口折叠 | INVESTIGATION-4.md §2 |
| 2026-05-20 | **INV-5 §5 · 子轨 A · 路径 F 真实施 + 真机回归** | PM 选路径 F，4-phase 推进 8 commit ship（Phase 2 renderer tuple + Phase 3 inject_cache_marker + Phase 4 prefix 切 + probe schema 扩 + bug fix）；DB id=16 active 行 apply（dashscope/qwen3.5-plus）；main_chat 真机 cold/warm 实测 `cached_tokens=0→5,655` 完美命中，99.8% 覆盖率；ROI 与 §3.4 预测 ~27% 吻合；8 非主链 caller marker no-op 无 regression；migrate_provider_prefix.py idempotent + rollback ready | INVESTIGATION-5.md §5 |
| 2026-05-20 | **INV-5 §4 · 子轨 A · T5 实测 DeepSeek 自动 caching = 绿档** | preflight 改 DB lookup 后跑通：`prompt_cache_hit_tokens 2,816 / 2,921 = 96.4% 覆盖率`，**含 tools= 列表全自动 cache**（与 Qwen `dashscope/` T4 silently strip 完全相反）；ROI 外推主路径 ~75%（vs 路径 F Qwen system-only 27%）；新三选一 D/E/F，CC 倾向 F + D 列入 v4.1 A/B 评测候选；陪伴质量风险面 = Mai 中文 persona 切 LLM 需真机评测 | INVESTIGATION-5.md §4 |
| 2026-05-20 | **INV-5 §3 · 子轨 A · T4 实测 tools= 列表 cache_control** | T4 = ⚠️ 档加深版：`dashscope/` + tools[-1] 顶层 cache_control 被完全 silently strip（cached_tokens null / 无 cache_creation 字段），与 T1 `openai/` 响应字段模式同；ROI 从 brief 假设 ~79% 缩水到 **~27-30%**（仅 system 段可缓存）；CC 倾向**路径 1 仅缓存 system 段**，tools 大头交给 INV-4 子轨 B 正面攻；零产品代码改动 | INVESTIGATION-5.md §3 |
| 2026-05-20 | **INV-5 §2 · 子轨 A · cache_control pass-through 实测裁决** | 三测全跑通：T1 `openai/` + cache_control = silently strip（无命中）/ T2 `dashscope/` + cache_control = **完美命中 1214 cached_tokens** / T3 `openai/` + 无 marker = implicit cache 客户端不可见；方案 a 实施路径明确 = **切 `dashscope/` prefix + 注入 cache_control**；外推主路径理论省 ~79% prompt token；零产品代码改动；脚本落 scripts/cache_probe_T1-3.py | INVESTIGATION-5.md §2 |
| 2026-05-20 | **INV-5 · 子轨 A · prompt caching 装配结构勘查** | grep 绿地确认 + 6 问事实链：messages[0] 单 system 大 string、layer 渲染 join 大 string、tools_schema 走 tools= 参数、字节稳定性代码层 OK 但物理结构无 marker 落点；**brief 假设需校正**：Skyler `openai/qwen-...` prefix 走 OpenAI 路径 + DashScope endpoint，LiteLLM 是否 pass-through cache_control 官方未明示需实测；CC 倾向方案 a（content blocks + cache_control），前置 2 个实测点 | INVESTIGATION-5.md §1 |
| 2026-05-20 | **INV-4 · token 第三刀（工具治理）第一步：全 capability 枚举** | PM 切轨：放弃追 43-68k 幽灵，治理 tools_schema 13.25k 大头；本步纯只读枚举全 capability（含 @register_capability + MEMORY_TOOLS + builtin + MCP active），形成 proactive/reactive 二分前置表 | INVESTIGATION-4.md §1 |
| 2026-05-20 00:21 | **INV-3 · token 治理轮 第一刀（如实收口）** | 原假设代码层双排除；主路径 40+ 轮实测封顶 ~22.7k，43-68k 未复现；tools_schema 13.25k 实测确认；summary 全 0 但 extractor 活（矛盾）；真凶疑在未观测的主动/后台链，转第二刀（⑤ 待查清单 6 条，含 fold 机制认知分歧待代码裁决）；本轮续：A 修复落地生效 / ⑤.3 实证结案（fold 正常，summary 0→465）/ short_term 改 25 生效；待办：⑤.2 主动对话 + 工具懒加载（高危大头）；backlog 首字延迟 31→71s 恶化；§⑩ 第二刀勘查：三条目标链 LLM 调用全走 client.py 统一封装，proactive_engine 无独立调用点，43-68k 推断转 backlog；详 INV-3 §⑩ | INVESTIGATION-3.md |
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

- 2026-05-21 backlog 重定位（per 纪律「调查/audit/评测 → INV files;实施 → ROADMAP」）— **INV-3 §10.9 + 1 backlog**（extractor 5-min 频率 audit）;**INV-5 §5 + 2 backlog**（Qwen Plus vs Max / Qwen Plus vs DeepSeek 评测候选,新增 §5.6）
- 2026-05-21 INV-4 §3 子轨 B · 三类候选评估 + v4.1 实施清单（INVESTIGATION-4.md §3）— P1 fold ~5,960 + P2 desc ~700 + P3 set_activity 退役 ~150 = **~6.8k tokens 收益**;6 动作按风险×工程量排好序;与子轨 A 5.6k 叠加主路径 prompt 砍 ~55%
- 2026-05-20 INV-4 §2 子轨 B · proactive/reactive 三分审计（INVESTIGATION-4.md §2）— 58 cap 分类 1 proactive / 5 hybrid / 52 reactive;严格判定下 proactive 远低 PM 预测 ≤5;§3 优先级建议 33 cap 入口折叠主战场
- 2026-05-20 INV-5 §5 子轨 A · 路径 F 真实施 + 真机回归（INVESTIGATION-5.md §5）— PM 选 F，4-phase 8 commit ship；main_chat WARM 5,655 cached_tokens 99.8% 覆盖率完美命中；8 非主链 caller no-op 无 regression；DB+config+probe+migrate script 全 ready
- 2026-05-20 INV-5 §4 子轨 A · T5 实测 DeepSeek 自动 caching = **绿档**（INVESTIGATION-5.md §4）— preflight 改 DB lookup 后跑通：96.4% 覆盖率含 tools= 全 cache；外推 ROI ~75%；新三选一 D/E/F，CC 倾向 F + D 列入 v4.1 A/B 评测
- 2026-05-20 INV-5 §3 子轨 A · T4 实测 tools= 列表 cache_control（INVESTIGATION-5.md §3）— tools 段 cache_control silently strip；ROI 从 ~79% 缩水到 ~27-30%；CC 倾向路径 1（仅缓存 system 段）+ INV-4 子轨 B 正面攻 tools_schema
- 2026-05-20 INV-5 §2 子轨 A · cache_control pass-through 实测（INVESTIGATION-5.md §2）— T2 `dashscope/` prefix 完美命中 1214 cached_tokens；T1 `openai/` prefix silently strip；T3 implicit cache 客户端不可见；方案 a 路径明确 = 切 `dashscope/` prefix + 注入 cache_control，理论省 ~79%
- 2026-05-20 INV-5 子轨 A · prompt caching 装配结构勘查（INVESTIGATION-5.md §1）— 6 问事实链 + brief 假设校正（`openai/qwen-...` prefix vs LiteLLM 原生 `dashscope/` prefix 路径分流）+ 三方案 proposal，CC 倾向方案 a 前置 2 实测点
- 2026-05-20 INV-4 第三刀 · 工具治理（INVESTIGATION-4.md §1）— PM 切轨砍 tools_schema 13.25k 大头；第一步全 capability 枚举（proactive/reactive 二分 + tag-conversion 候选 + 入口折叠候选评估前置）
- 2026-05-20 00:21 INV-3 第一刀 · 如实收口（INVESTIGATION-3.md）— 40+ 轮实测封顶 22.7k 未复现 43-68k；tools_schema 13.25k 实测；summary 全 0 ↔ extractor 活的矛盾；真凶疑在主动/后台链，转第二刀（⑤ 6 条，含 fold 机制认知分歧）；§⑩ 第二刀勘查 LLM 调用全走 client.py 统一封装，43-68k 转 backlog
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
