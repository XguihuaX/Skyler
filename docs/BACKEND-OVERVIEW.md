# BACKEND-OVERVIEW

> 后端总功能全景 · 已知问题总账 · 优先级建议 · 一句话现状结论
> 生成时间：2026-05-19 00:09｜更新：2026-05-19 docs 第二刀｜HEAD = `c1d65ff`（往后已 +2 commit：`71b6e99` switch_character 下线、`c1d65ff` todos+profile_summary 退役；含 12 孤儿 character_states 清理）
> 基线：`docs/archive/AUDIT-GROUND-TRUTH.md` §3/§4/§5 + 本轮 Problem B 真机回归
> 只读盘点；不改任何代码 / DB / commit / stash

---

## 第 1 节 · 后端功能全景（实际接线，非文档声称）

按功能域分组。每域标：核心入口（文件:行）、当前是否真接线可用、依赖 DB 表。
统计基线锚定在 AUDIT §3 之上，已合并 commit `eaa9330` 后的实测变更。

### 1.0 总量盘

| 维度 | 数量 | 入口 |
|---|---|---|
| FastAPI router | **20** | `backend/main.py:890-913`（注：AUDIT §3d 写 21，实测 20 不含双计；§3a.1 列表也是 20 行） |
| LLM tool（function-calling） | **58** = 2 builtin + 56 capability-derived | `backend/tools/registry.py:95-96` + `backend/capabilities/registry.py:118` |
| Capability | **56**（`@register_capability` 装饰器统计） | `backend/capabilities/` + `backend/proactive/snooze_capability.py` |
| Proactive trigger 类 | **7** | `backend/proactive/triggers/` |
| stage-2 builder | **5** | `backend/proactive/triggers/_stage2_registry.py` |
| Cron / interval job | **4-5**（按 enabled/mode 互斥决定） | `backend/main.py:680-836` |
| Characters（DB） | **9** | 实测 `SELECT * FROM characters` |
| DB 表 | **22** ✅ 含 `memory_tombstone` | `.tables` 实测 |

### 1.1 功能域：长期记忆（memory）

| 入口 | 文件:行 | 状态 | 依赖表 |
|---|---|---|---|
| 读端 — UI 列表 | `routes/memory_api.py:93-131` `GET /api/memory/list` | ✅ 活；B 路 OR NULL 命中 NULL 行 | `memory` |
| 读端 — LLM tool | `agents/chat.py:741-755` `list_memories` | ✅ 活；B 路 OR NULL 命中 NULL 行 | `memory` |
| 读端 — wake_call instruction | `proactive/engine.py:693-707` `aggregate_briefing_data` | ✅ 活；NULL 行命中（type=instruction 过滤后 1 行） | `memory` |
| 读端 — semantic recall | `memory/long_term.py:276` `search_relevant_memories` | ✅ 活；NULL 行进入候选；cosine + 遗忘曲线决定 top_k | `memory` |
| 写端 — extractor | `memory/extractor.py` + `routes/conversations_api.py:138` 指针 | ✅ 活；clamp-only 修复链已 ship | `memory`, `memory_extractor_state` |
| 写端 — chat tool save | `agents/chat.py` save_memory tool | ✅ 活；写 character_id 做 audit metadata | `memory` |
| 写端 — UI 手工添加 | `routes/memory_api.py:134-170` `POST /api/memory/add` | ✅ 活 | `memory` |
| 墓碑去重 | `memory/tombstone.py` + `services.delete_memory:184-196` | ✅ 活；表存在；双删入口写墓碑；精确 + cosine≥0.92 双比对 | `memory_tombstone` |
| 摘要折叠 | `memory/summary.py` fold worker | ✅ 活；按 (uid, cid, conv_id) 分桶 | `chat_history`, `conversation_summary` |
| 短期窗口 | `memory/short_term.py` | ✅ 活；硬性 cap 30 turn；按 (user, character, conversation) 三级隔离 | `chat_history`（恢复源） |

**B 路 commit `eaa9330` 后的语义闭合**：`memory.character_id IS NULL` = "跨角色共享一等公民"；读端三路 `or_(==cid, IS NULL)` 命中；启动不再抹 NULL→Momo（main.py V2.5-C2c + v2_5_b.py 8b 两处 backfill 已删）。

### 1.2 功能域：角色 / persona

| 入口 | 文件:行 | 状态 | 依赖表 |
|---|---|---|---|
| 列表/读 | `routes/characters_api.py` | ✅ 活 | `characters` |
| 多 variant persona CRUD | `routes/persona_api.py` | ✅ 活 | `character_personas`, `character_personas_builtin_seed` |
| 渲染链（runtime） | `agents/chat.py:1310-1334` | ✅ 活；三路 fallback：renderer → DB persona → yaml | `characters`, `character_personas`, `config/prompt_manager.py` |
| character_state（亲密度等） | `services.py:643-689` + `routes/character_state.py` | ✅ 活 | `character_states` |
| persona builtin restore | `persona_api.py:400` `restore_to_builtin` | ✅ 活 | `character_personas_builtin_seed` |

**实测 9 个 character**（AUDIT §3a.5 有 8 个；新增 cid=102 流萤）：

| cid | name | live2d | splash | character_personas.identity.name | 状态 |
|---|---|---|---|---|---|
| 1 | Momo | hiyori | 空 | **樱岛麻衣**（X.8 借壳活跃） | persona 借壳生效 |
| 2 | 八重神子 | yae | 2.png | 八重神子 | 空骨架 + yae live2d |
| 3 | 荧 | 空 | 3.png | 荧 | 空骨架 |
| 4 | 凝光 | 空 | 空 | 凝光 | 空骨架 |
| 5 | 神里绫华 | 空 | 空 | 神里绫华 | 空骨架 |
| 99 | 一般路过猫娘 | 空 | 99.png | 一般路过猫娘 | 空骨架 |
| 100 | 祥子-test | 空 | 100.png | 祥子-test | 空骨架 |
| 101 | 樱岛麻衣 | hiyori | 101.png | 樱岛麻衣（骨架） | 与 cid=1 借壳命名重叠 |
| 102 | 流萤 | 空 | 102.png（untracked） | 流萤 | **AUDIT 后新增**；空骨架 |

### 1.3 功能域：对话 / 主动陪伴（proactive）

| 入口 | 状态 | 备注 |
|---|---|---|
| ChatAgent（function-calling 主流程） | ✅ `agents/chat.py` | tool calling + short_term + long_term recall + persona 注入 |
| Stage-1 trigger（sentinel） | ✅ 7 类 trigger 真接 | wake_call / morning_briefing / lunch / dinner / bedtime / long_idle / activity |
| Stage-2 reply（邀请回复链） | ✅ 5 registry | `_stage2_registry.py` 注册 wake_call / lunch / dinner / bedtime / long_idle |
| 活动感知（activity_smart） | ✅ ~70 KB 活码 | `proactive/activity_*.py` 全套；DESIGN 文档化偏简略 |
| Conversation Binding | ✅ 三级隔离 | (user, character, conversation) per AUDIT §Z.2/Z.3 |
| Pending briefing 缓存 | ✅ | `pending_briefings`（DB 234 行多为测试残留） |

### 1.4 功能域：多媒体（TTS / Live2D / 媒体接入）

| 入口 | 状态 | 依赖 |
|---|---|---|
| TTS route | ✅ `routes/tts.py` | `voice_aliases`, `tts_call_log`（510 行真埋点） |
| Live2D 配置 | ✅ `routes/live2d.py` | `characters.live2d_model`；hiyori/yae 真就位 |
| 网易云音乐 | ✅ 7 + 6 capability | `netease_music.py` + `netease_playback.py` |
| Bilibili | ✅ 11 capability | `bilibili.py` |
| 媒体控制（系统 now-playing） | ✅ 5 capability | `media_control.py` |
| 剪贴板 | ✅ 3 capability | `clipboard.py` |
| 屏幕感知 | ✅ 4 capability | `screen.py` |

### 1.5 功能域：日历 / 时间 / 文档

| Apple Calendar | ✅ 4 capability | `apple_calendar.py` |
| Google Calendar | ✅ 2 capability | `google_calendar.py` |
| Calendar 抽象层 | ✅ 2 capability（today_events / upcoming_events） | `calendar.py`（router 决定 source） |
| time.now | ✅ 1 capability | `time_capability.py` |
| docx_ops | ✅ 3 capability | `docx_ops.py` |
| xiaohongshu | ✅ 1 capability | `xiaohongshu.py` |

### 1.6 功能域：MCP / AI 接入

| MCP client | ✅ 14 tool 登记 | `backend/mcp/client.py`；filesystem-skyler 实测连接 |
| MCP DB 三表 | ✅ schema 就位 | `mcp_credentials`/`mcp_client_state`/`mcp_tool_state` |
| AI vendor / provider | ✅ | `ai_vendors`(4) / `ai_vendor_credentials`(1) / `ai_providers`(6) |

### 1.7 功能域：observability / webhooks / integrations

| Observability | ✅ `routes/observability.py` | tts_call_log 埋点真活（510 行） |
| Integrations | ✅ `routes/integrations.py` | |
| Webhooks | ✅ `routes/webhooks.py` | |
| Capabilities meta | ✅ `routes/capabilities.py` | 仅暴露 56 capability，**不含 builtin 2 tool** |

### 1.8 ⚠️ 较 AUDIT §3a.5 的变更

1. **新增角色 cid=102 流萤**（character_personas 已 seed 空骨架；splash-art/102.png untracked）
2. **memory_tombstone 表已建**（AUDIT §1.0 的 ⚠️ "DB 实际不存在" 已闭合 —— Problem B 回归三次启动时由 `migrate_v4_0_0_memory_tombstone` 创建）
3. **`memory.character_id` 语义闭合**（Problem B commit `eaa9330`）
4. **`switch_character` LLM tool 下线**（commit `71b6e99`，2026-05-19）—— schema 不再注册到 ToolRegistry；prompts.py / tool_addendum 引导文字删
5. **todos 整套 + profile_summary fallback 退役**（commit `c1d65ff`，2026-05-19）—— 删 `backend/agents/{planner,memory}.py` + `backend/scheduler/task.py` 整文件；`/api/todos/*` + bare `/api/profile` endpoints 删；`services.py` 6 函数（4 todo + 2 profile_summary）删；`ws.py` `_compute_profile_summary` / `_regenerate_profile_summary` 217 行删；`chat.py` profile_summary fallback 删；`Todo` ORM + `users.profile_summary` 列保留空 + `[RETIRED]` 注释
6. **12 孤儿 character_states 已清**（c1d65ff 之前的"第二刀" DB 操作）—— `character_states` 21→9 行，与 9 个真 character 对齐

---

## 第 2 节 · 已知问题总账（合并本轮全部发现）

格式：{问题 | 严重度 | 根因是否查清 | 当前状态 | 建议处置 | 是否阻塞用户}

### 2.1 已闭合 ✅

| # | 问题 | 闭合 commit / 备注 |
|---|---|---|
| C-1 | 墓碑表（Problem A）— 删过的"持久事实"被重抽 | `3f3be08` ✅ 已 ship；表 + helper + 双消费者全就位；本轮真机启动验证表已建 |
| C-2 | extractor 指针越界 / default 卡死 804 | `f712625` + `42d1800` ✅ clamp-only 已就位 |
| C-3 | 短期重启恢复窗口对齐 SHORT_TERM_MAX | `902c2c2` + `1437e48` ✅ |
| C-4 | `memory.character_id IS NULL` 跨角色共享语义（Problem B） | `eaa9330` ✅ 本轮闭合；3 次重启 NULL 持久；三路 OR NULL 命中；recall 无误伤 |
| C-5 | **H-1：`switch_character` LLM tool 切不动 DB cid** | `71b6e99` ✅ 2026-05-19 下线 —— ToolRegistry 不再注册 schema；prompts.py / tool_addendum 引导文字删；函数体 + schema 暂留 builtin.py。前端切角色走 WS `character_switch` 帧不受影响 |
| C-6 | **todos 整套 + profile_summary fallback 退役** | `c1d65ff` ✅ 2026-05-19 —— `agents/{planner,memory}.py` + `scheduler/task.py` 整文件删；`/api/todos/*` + bare `/api/profile` endpoints 删；6 个 service 函数（4 todo + 2 profile_summary）删；ws.py profile_summary regen 段 217 行删；chat.py fallback 删 |
| C-7 | **12 孤儿 character_states 清理** | ✅ 2026-05-19（"第二刀"DB DELETE，c1d65ff 之前）—— `character_states` 21→9 行，与 `characters` 表 9 行对齐 |
| C-8 | **M-6：前端 ChatHistoryDrawer / 浮现台词气泡残留** | ✅ FRONTEND-OVERVIEW §3.4 终核 PASS —— 文件已删；仅注释引用；替代组件 `ChatHistoryPanel.tsx` 真活 |

### 2.2 未闭合（按严重度排序）

#### 高严重度（用户体验真受损 / 阻塞其它项）

| # | 问题 | 根因 | 当前状态 | 建议处置 | 阻塞 |
|---|---|---|---|---|---|
| ~~H-1~~ | ~~`switch_character` LLM tool 切不动~~ | — | ✅ **2026-05-19 闭合（commit `71b6e99`）** | — | — |
| **H-2** | cid=1 / cid=101 / "Mai 借壳" 命名漂移 | DB 实情：`characters.id=1` name=Momo + `character_personas` variant identity name="樱岛麻衣"（X.8 借壳活跃）；同时 `characters.id=101` 也叫"樱岛麻衣"且单独存在 → 两条 Mai 共存，default 主用谁未明示 | AUDIT §3c.1 #3 / §4 #8/#29 已记；未拍板 | 文档对齐：两个 id 的关系、default active 是哪个、cid=101 是否退役或改名 | 阻塞 §F1 文档对齐 |
| **H-3** | characters 双源 `characters.yaml` ↔ DB（Plan B 现行 / Plan C 未做） | 渲染链三路 fallback：renderer → DB persona → yaml。新 character（cid=99/100/101/102）yaml 无条目 | AUDIT §2.7 / §3c.2 #3 实锤；H-1 闭合后性质变更（不再需要"`switch_character` 切 DB 校验源" 这一步），剩余工作为"yaml 退役 + prompt_manager 单源化" | 文档承诺保留 Plan C 待办 | — |

#### 中严重度（功能债 / 行为风险已记录）

| # | 问题（RT 系列） | 根因 | 当前状态 | 建议处置 |
|---|---|---|---|---|
| **M-1**（RT-1） | 异构 memory 表混存（持久事实 + 时效提醒未拆） | 单表混存（expires_at NULL / NOT NULL） | AUDIT §4 #21 表层债入册；仍成立 | v4.1+ 拆表或加 type 字段隔离 |
| **M-2**（RT-2） | 双 type 列 cruft：`type`(5 类) vs `entry_type`(4 类) | `type` 有 WHERE 维度筛选；`entry_type` 仅读+写无 WHERE | AUDIT §4 #3 表层债入册；仍成立 | 文档保留，等下一刀处理 |
| **M-3**（RT-3） | supersede 机制完全未实现 | 全库 0 函数 0 调用，全部 supersede 字面在注释 / docstring | AUDIT §4 #4 已自陈；仍成立 | 文档保留 RT-3；本轮不动 |
| **M-4**（RT-4） | `expires_at` 半接线 | chat/extractor 写端全传 None；UI/LLM tool 写端接受非 None；read 端 active_only 与墓碑 gate 全活 | AUDIT §4 #2 部分准确；陈旧需对齐 | 文档对齐：写端主路不传值是事实 |
| **M-5**（RT-5） | 墓碑 check 无类型感知 | `tombstone.py` 仅按 user_id 维度查；不读 entry_type / type；可能误压新建时效提醒 | AUDIT §4 #5 表层债入册；仍成立 | v4.1+ 加 type 维度 |
| ~~M-6~~ | ~~front-end ChatHistoryDrawer / 浮现台词气泡 残留~~ | — | ✅ **闭合**（FRONTEND-OVERVIEW §3.4 终核 PASS） | — |
| **M-7** | DB 测试残留 | pending_briefings 234 行 / memory 9 行 / users 18 测试 uid（**character_states 已清，现 9 行对齐**） | character_states 部分已闭合（2026-05-19 第二刀 DB DELETE 12 孤儿）；剩 pending_briefings / memory / users 三类未清 | 决定是否清；如清需先备份 |

#### 低严重度（文档欠债 / 待文档对齐）

| # | 问题 | 状态 | 建议处置 |
|---|---|---|---|
| L-1 | DESIGN.md §F1 "cid 2/3/4/5/99/100 空骨架" 列表缺 101 + 102 | AUDIT §4 #9 已记；现实更扩到 102 | §F1 补 101 樱岛麻衣 + 102 流萤 |
| L-2 | DESIGN.md §X.8 / Z.8 "Mai 借壳" 文档化但 character_personas 表机制 / multi-variant 架构未明示 cid=101 重叠风险 | 文档欠债 | 文档对齐（与 H-2 同源） |
| L-3 | conversation_summary（b91505a）/ memory_tombstone（3f3be08）/ voice_aliases / mcp 三表 / activity_smart 一族 — 文档化偏简略 | AUDIT §4 #6/#7/#16/#17/#28/#30 | 主文档补技术细节 |
| L-4 | 14 sentinel commit 具体 sha 集合 | AUDIT §0.5 / §5.3 #1 候选 A/B 列出 | 醒后挑一种入档 |
| L-5 | README L29 "Mai (cid=1, riding the Momo shell...)" 与 DB 命名漂移 | AUDIT §4 #29 | 与 H-2 同源对齐 |
| L-6 | SHORT_TERM_MAX 真实常量 / tool_result 4000 截断 — 是否仍是文档号称值 | AUDIT §4 #13 / §5.3 #10 | 一次 grep 实测即定 |
| L-7 | voice_samples 是否真在 LLM prompt 注入路径 | AUDIT §4 #26 / §5.3 #13 | 一次 grep 实测即定 |
| L-8 | cid=1 voice_model JSON 真值 | AUDIT §4 #25 / §5.3 #12 | 一行 SELECT 即定 |
| L-9 | DB 备份 12 个全保留 vs 清理 | AUDIT §4 #22 / §5.3 #11 | policy 决定 |
| L-10 | 加藤惠 Live2D（Cubism 2 格式锁死） | AUDIT §3c.1 #1 / §4 #10 已自陈无解 | 个人 backlog；不做 |
| L-11 | `prompt_manager.py:3` 注释 "DEPRECATED" 但仍被 chat.py / builtin.py 调用 | AUDIT §3c.2 #2 | 与 Plan C 同步真删 |
| ~~L-12~~ | ~~character_states 20 行（vs 8 character → 12 测试残留疑似）~~ | ✅ **闭合**（2026-05-19 第二刀 DB DELETE） | — |

### 2.3 ⚠️ 待人工裁决项（汇总 AUDIT §5.3 + 本轮新增）

13 项（详 AUDIT §5.3）+ 本轮新增：

14. **cid=102 流萤是否要 yaml 条目 / 是否进 §F1 列表 / 是否要 live2d 资产** —— AUDIT 后新增的角色，未在任何文档中记录其计划

---

## 第 3 节 · 优先级建议

| 梯队 | 项 | 理由 |
|---|---|---|
| **P0 立即** | H-2 命名漂移拍板（独立） | H-1 已闭合，H-3 性质变更；H-2 仍未拍板，影响 §F1 文档对齐 + cid=101 / cid=102 定位 |
| **P1 近期** | M-7 DB 测试残留清理（含 L-12） | 涉及 4 张表（pending_briefings / memory / character_states / users），先决定 forensic 保留策略；如清需备份 |
| **P1 近期** | L-1 + L-2 + L-5 文档对齐三件套（命名 + §F1 列表 + README） | H-2 拍板后顺手对齐，零代码风险 |
| **P1 近期** | L-3 文档补技术细节（conversation_summary / memory_tombstone / activity_smart / mcp 三表 / voice_aliases） | 文档欠债集中处理 |
| **P2 backlog** | M-1（RT-1 拆表）/ M-2（RT-2 双 type 列）/ M-5（RT-5 墓碑加 type 感知） | 真功能债，但用户当前不受阻；v4.1+ 做 |
| **P2 backlog** | L-4 14 sentinel sha 入档 / L-6 / L-7 / L-8 单查类核对 | 不阻塞，分批补 |
| **P2 backlog** | L-9 DB 备份保留 policy | policy 题，与代码无关 |
| **P3 不做** | M-3（RT-3 supersede） | 文档已自陈未实现，零残留；真要时再做 |
| **P3 不做** | L-10 加藤惠 Live2D | 格式锁死无解 |
| **P3 不做** | M-4（RT-4 expires_at）真实现 | 当前半接线模式（写端不传 / 读端 gate 活）实际跑得通；文档对齐即可 |

**梯队设计依据**：用户影响 × 修复成本 × 是否阻塞其它项。最阻塞的一族（H-1/H-2/H-3）建议作为一组拍板，避免分次反复。

---

## 第 4 节 · 一句话现状结论

后端整体健康度**良好**——20 router / 58 LLM tool（switch_character 已下线后 57 → 实测仍 58 含 builtin clear_short_term）/ 7 trigger / 9 character 全数活接线，B 路 + 墓碑 + switch_character + todos/profile_summary 四条主线已闭合（commits `eaa9330` / `3f3be08` / `71b6e99` / `c1d65ff`）；character_states 12 孤儿 + M-6 前端 drawer 也已闭合；剩余债务以**文档欠债**与**H-2 命名漂移**为主，不影响主聊天 / 记忆 / 主动陪伴 / TTS / Live2D 等核心功能。

最该先动的 **1 件事**：

1. **H-2 命名漂移拍板**（cid=1 Momo 借壳 vs cid=101 樱岛麻衣 vs cid=102 流萤新增 —— 用一句话定 default 用谁、cid=101 怎么办、cid=102 是不是正式角色）—— 这一拍带动 §F1 文档对齐 + L-1/L-2/L-5 一起。H-1 已闭合不再阻塞此拍。

其它 RT-1/RT-2/RT-5 是真功能债但用户当前不受阻，可入 v4.1+ backlog；文档欠债（L-1 ~ L-11）可在 H-2 拍板后顺手对齐，无独立阻塞性。

---

## 边界声明

- 本文件**只读盘点**：未改任何代码 / DB / migration / commit / stash / push
- 基线锚定在 `docs/archive/AUDIT-GROUND-TRUTH.md`（HEAD `eaa9330`，AUDIT 写于 commit `2d7b793` 前后；docs 第一刀 2026-05-19 已归档）；2026-05-19 docs 第二刀更新到 HEAD `c1d65ff`
- 本轮新增证据来自：Problem B 真机回归三次启动（轮次 5）+ commit `eaa9330` 后 DB 直读
- 任何"建议处置"与"梯队"是 CC 给依据，**最终决策由人**
