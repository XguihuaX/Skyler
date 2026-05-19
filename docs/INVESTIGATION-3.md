# INVESTIGATION-3 · token 治理轮 第一刀

> 接续 `docs/INVESTIGATION-2.md`（已封满），token 治理轮独立分卷。
> 日期：2026-05-19｜HEAD = `9bd555d`（docs 整理轮 + resize handle 收口后基线）
> 探针就位时间：2026-05-20 00:21

---

## ① 上一轮勘查四项 findings（2026-05-20 00:0X 只读勘查 → 本刀基线）

### 1.1 主对话 prompt 组装汇总点

**入口**：`backend/agents/chat.py:1105 _build_messages(...)` async 函数。

**主路径（v4 renderer）**：`chat.py:1232-1283`，调 `render_system_prompt(...)` 输出 1 个 `system` 消息（Jinja 5-layer：A/B/C/D），然后 append conversation_summary（若有）、short_term history、current user text；`tools=` 参数 = `_get_all_tools()`（MEMORY_TOOLS 4 + ToolRegistry 54 schemas = 58 个）。

一次 LLM 请求 = `system(Jinja)` + 可选 `system(摘要)` + N 条 history turns + 1 条 current user text + `tools=` 参数。

### 1.2 各注入源（chat.py 实读）

| 注入源 | 文件:行 | 真实底层来源 |
|---|---|---|
| 工具 schema | `chat.py:588-593 _get_all_tools()` + `1647 sanitize_tools_for_llm()` + `1652 tools=san_tools` | `MEMORY_TOOLS` (chat.py:456-538) + `ToolRegistry.list_schemas()` (capabilities/registry.py:118) |
| persona (Layer C) | `agents/prompt/persona_loader.py:79 load_active_persona()` + `templates/layer_c.j2` | `character_personas` 表 `is_active=1` 行；Tier-1 7 字段 + Tier-2 可选 |
| character_state (Layer C4) | `persona_loader.py:136 load_character_state()` | `character_states` 表（mood/intimacy/activity/thought） |
| TOOL_PROMPT_ADDENDUM (Layer B) | `agents/prompt/tool_addendum.py:TOOL_PROMPT_ADDENDUM` | 模块常量（114 行自然语言工具引导） |
| Layer A (output format) | `templates/layer_a.j2` + chat.py `_build_*_instruction()` | 模板渲染 |
| user_profile (Layer D) | `services/profile_regen.py:format_profile_for_prompt(get_profile_data(user_id))` | `users.profile_data` JSON |
| activity timeline (Layer D) | `services/activity_timeline.py:384 format_today_activity_for_prompt(user_id)` | `activity_sessions` 表当日 + top-5 app aggregate |
| long_memory_top5 (Layer D) | `memory/long_term.py:276 search_relevant_memories(user_id, query=text, top_k=5)` | 向量 cosine + 遗忘曲线 |
| conversation_summary | `memory/summary.py:228 get_summary()` | `conversation_summary` 表 `summary_text` 列 |
| short_term history | `memory/short_term.py:89 get()` | 进程内 `_store` dict（per-(user, char) bucket + conv_id 过滤） |

### 1.3 conversation_summary 是固定 token 预算（不随轮次涨）

`memory/summary.py:88-93`：
```python
def get_summary_token_budget() -> int:
    """单 conv 摘要的 token 上限(初始化 token_budget 列用)。默认 1000。"""
    return int(_summary_cfg().get("token_budget", 1000))
```

**关键机制 — 重压缩（不 append）**：`summary.py:21-30` 模块 docstring + `summary.py:147-149` fold prompt：

> "把'现有摘要'和'新挤出窗口的对话片段'合并,**重新压缩**成一段不超过 {token_budget} token 的新摘要。这是滚动摘要,会覆盖现有摘要,所以**不许 append**,**必须重压缩**。"

DB schema：`conversation_summary` 表含 `summary_text / last_folded_chat_history_id / token_budget` 三列；写入路径 `_write_state` 是 UPDATE 覆盖写。

→ **固定 1000 token 上限，每次 fold 都重压缩覆盖。不会随轮次膨胀。**

### 1.4 short_term history 按**条数** cap（不按 token）

`memory/short_term.py:37-44`：
```python
SHORT_TERM_MAX_TURNS: int = 30          # 1 turn = user + assistant
SHORT_TERM_MAX: int = SHORT_TERM_MAX_TURNS * 2  # = 60 messages
```

`short_term.py:54-87 add()` 内的 trim 逻辑：
```python
if len(self._store[key]) > SHORT_TERM_MAX:                # 比较 messages 条数
    self._store[key] = self._store[key][-SHORT_TERM_MAX:]  # 保留最新 60 条
```

→ **按条数 cap = 60 messages（30 turn）**。每次 `add()` 都 enforce trim（"修法 A"，注释 L8-11 明示旧版"dead constant 无上限，贡献 5-15k tokens / LLM call"，本版已 enforce）。

INVESTIGATION-2 §3 实测：~63 tokens/turn pair，30 turn cap → 上限 ~1,900 tokens。**单条 message 内部长度无防御**（极端长消息可能突破估算，但主路径罕见）。

### 1.5 真凶指向变化（原假设 → 现假设）

| 原假设 | 代码层证据 | 状态 |
|---|---|---|
| ❌ history 随轮线性膨胀 → 反复放大 prompt | `short_term.py:79-81` enforce trim 每次 add 都比较 60 条上限 | **排除** |
| ❌ conversation_summary 滚雪球累加 | `summary.py:147-149` LLM prompt 明示"不许 append,必须重压缩" + `_write_state` UPDATE 覆盖 | **排除** |
| ❓ 43-68k 真凶 = ？ | 主路径 40+ 轮实测未复现（见 ③④），真凶疑在探针未覆盖的主动/后台链，转第二刀 ⑤ | **未复现·转第二刀** |

---

## ② 原假设被排除的依据（代码层）

### 2.1 short_term 不会无限增长

| 证据 | 文件:行 |
|---|---|
| `SHORT_TERM_MAX = 60` 常量 | `short_term.py:44` |
| 每次 `add()` 末尾 enforce trim | `short_term.py:79-87` |
| 注释明示"修法 A" 之前是 unbounded bug | `short_term.py:8-11` |
| `get()` 按 (user, char) bucket + conv_id 过滤；conv_id=None 返桶内全部 | `short_term.py:89-108` |

**理论上限**：30 turn × ~63 tokens/turn ≈ **1,900 tokens** 封顶（INVESTIGATION-2 §3 已实测）。

### 2.2 conversation_summary 不会累加膨胀

| 证据 | 文件:行 |
|---|---|
| `token_budget` 默认 1000 | `summary.py:88-93` |
| Fold worker 用 `_write_state` 单次 UPDATE 覆盖写，**不是 append** | `summary.py:291-310` |
| LLM fold prompt 内 hard 约束"≤ {token_budget} token" + "覆盖现有摘要" | `summary.py:147-167` |
| 模块顶部 docstring 反复强调"重新压缩"语义 | `summary.py:21-30` |

**理论上限**：每个 (user, char, conv) 三元组的 `summary_text` ≤ 1000 tokens。

### 2.3 因此 43-68k 真凶不可能是 history / summary

INVESTIGATION-2 §6 实测最小请求 18k / 重度请求 19.6k（cid=1 Mai 借壳 active persona）。43-68k 是 INVESTIGATION-2 数字 ~2-3× 量级，超出 short_term + summary 任何合理膨胀。**指向其它注入源或多 turn 累积场景**（如多 round tool calling，每 round 都重发完整 prompt + tool 结果叠加）。本刀实测定位。

---

## ③ 实测数据（真机采集 → 主路径 40+ 轮）

**探针位置**：`backend/agents/chat.py:1647-1660`（紧贴 `sanitize_tools_for_llm` 之后、`call_llm` 之前）。
**探针模块**：`backend/agents/_token_probe.py`（fail-silent，写 `logs/token_probe.jsonl`）。
**字段集**（13 个）：`timestamp / conv_id / turn_n / tools_schema / persona / character_state / addendum / layer_a / user_profile / activity / long_memory_top5 / summary / short_term / current_text / system_combined / total`

**采集窗口**：2026-05-19 16:32–16:50，`conv_id=43`，**单一主对话连续 40+ 轮**，tokenizer = `litellm.token_counter(model='qwen3.6-max-preview')`（对中文 ~20-30% 高估，作为相对量级诊断有效，与 INVESTIGATION-2 同 tokenizer 可对照）。

### 3.1 关键观测

| 字段 | 实测行为 | 量级 |
|---|---|---|
| `total` | 平滑单调微升 | **20,912 → 22,683**（封顶 ~22.7k） |
| `short_term` | **唯一增长源**，随 turn 线性爬升 | **626 → 2,388**（已**破** INV-2 §3 推算的 ~1,900 cap） |
| `tools_schema` | **恒定**，单次请求最大固定块（~58% 占比） | **13,250**（INV-2 估 11k，实测更肥 ~2k） |
| `addendum` | 恒定 | 3,188 |
| `persona` | 恒定（cid=1 Mai 借壳） | 2,688（与记忆#8 实测 2,759 同量级） |
| `summary` | **全程 0** —— 40+ 轮 fold **零产出** | 0 |
| `turn_n` | 多为 1；偶发 `turn_n=2` 但 `total` 未叠加增长 | **未观测到** "多 round tool calling 累积放大 prompt" |
| 其它（layer_a / user_profile / activity / long_memory_top5 / character_state / current_text） | 量级远小于上述大块，未观测异常 | 略 |

### 3.2 核对原假设

| INV-3 ② 排除项 | 本刀实测态 |
|---|---|
| `short_term` 不会无限增长（enforce trim ≤60 条） | **未被反证**：实测 40+ 轮仍单调上升，但封顶 2,388 在数量级合理区，未爆炸；不过**超过 INV-2 §3 推算的 ~1,900**，cap 行为待第二刀直读代码核 |
| `conversation_summary` 不会累加膨胀（重压缩 ≤ 1000） | **未被反证，但未获正向验证**：本刀 summary 全程 0，没产生过 fold 输出 → "重压缩"语义在本刀**未上场**，是否真生效**未测** |

### 3.3 落盘文件

`logs/token_probe.jsonl`（40+ 行，相对路径仓库根）。本刀只贴关键观测，不贴整段原始 JSONL（保留在文件中供第二刀复算）。

---

## ④ 结论（如实收口，**不强行定凶**）

**主路径正常对话下，43-68k 症状未复现**，实测封顶 **~22.7k**。

INV-3 ② 的代码层排除（`short_term` enforce trim / `conversation_summary` 重压缩）**在本刀实测层未被反证**，但 `summary` 全程为 0 使 **"summary 是否真生效"在本刀未获正向验证**（重压缩语义没机会上场）。

**43-68k 真凶未定位**，最可能在**本探针未覆盖的路径**：

- **主动 activity_judge 链**（独立 LLM 调用，不走 ChatAgent.stream 主路径，探针挂不到）（**本刀推断，未经代码核实**：尚无 文件:行 证明此链确实独立于主路径且绕开探针；列为第二刀 ⑤.1 待验证假设）
- **后台 fold worker 链**（独立 LLM 调用，同样不走主路径，探针挂不到；且本刀观测到 fold 零产出 ↔ extractor 仍活的矛盾，需直读代码裁决）（**本刀推断，未经代码核实**：尚无 文件:行 证明此链确实独立于主路径且绕开探针；列为第二刀 ⑤.3 待验证假设）

→ **转第二刀**（⑤ 待查清单）。

**Token 刀本刀唯一硬产出**：

- `tools_schema` = **13,250 tokens 实测确认**（INV-2 估 11k 低估 ~2k）；单次主路径请求最大固定块；为**后续工具懒加载（高危刀）**积累的弹药。

**未做的事（明示）**：

- ❌ 没观测到主动陪伴 / 后台 worker 的 LLM 调用
- ❌ 没追溯 43-68k 数字最初来源
- ❌ 没读 fold worker 的真实触发条件（仅引用了 INV-3 ①.3 自述，本身待第二刀复核）

---

## ⑤ 第二刀待查清单（本刀衍生，未解）

> 本节是本刀的"未解项交班"，**不预设结论**。每条第二刀须直读代码 / 直读日志，结论给 文件:行。

### 5.1 `activity_judge` 主动链 — model 前缀行为不一致（疑代码多路径补前缀不统一）

- 现象一：日志见 `model=qwen-turbo` **缺 provider 前缀** → 被 LiteLLM 拒，`judge returned no decision`（静默失败）
- 现象二：另一次见 `model=openai/qwen-turbo` **带前缀** → 成功
- 同一个调用源出现两种 model 串，疑代码里有多条路径在拼 model 名，前缀补法不统一
- **须勘**：`qwen-turbo` model 串哪里配的（config? planner_model? activity_judge 模块?）、谁在调用、为何前缀时有时无、修复方案
- 给 文件:行
- **待验证假设（来自 ④）**：此链是否为独立 LLM 调用、是否绕开 `chat.py:1647` 探针，须直读代码确认，给 文件:行。

### 5.2 主动陪伴路径完整性（区分"哪条主动路径在工作"）

- 用户观察："她仍能主动"
- 但 §5.1 已证 `activity_judge` 确实静默失败
- **二者不矛盾的前提是：主动陪伴有多条触发路径，`activity_judge` 死了但另一条还活**
- **须勘**：主动陪伴有几条触发路径？各自当前状态？用户观察的"主动"实际由哪条产生？
- 给每条 入口文件:行 + 当前状态

### 5.3 fold / summary worker 触发机制 —— 认知分歧，须代码裁决

**现象**：

- 本刀实测：`summary` 字段 40+ 轮**全 0**
- 同期 `short_term` 已爬至 2,388（远超 30 turn，**大量 turn 已被挤出窗口**）
- 同期 `[extractor] turns=2 → 1 entries saved` —— **extractor worker 确认活着**
- **结论：后台 worker 非全死，fold 偏偏零产出**

**待裁决分歧**：

- 记忆#6 / INV-3 ①.3 记为 `min_batch=4`（挤出窗口 turn 数）+ `batch_turns=10` + async background worker
- 但此为**设计意图 / agent 自述**，**均非直读代码真值**
- 用户记忆中的触发机制与此说法**不一致**（具体差异未明；可能在"按总 turn 数触发"vs"按挤出窗口 turn 数触发"这一点上）

**第二刀须直读代码**（**不靠记忆 / 不靠 agent 自述 / 不靠 INV-3 ①.3 自身** —— ①.3 也需被代码复核）：

- fold worker 真实触发条件？
- 调度方式（谁、何时调它）？
- `min_batch` / `batch_turns` 实际语义？
- 为何 extractor 活而 fold 零产出？
- 给 文件:行
- **待验证假设（来自 ④）**：此链是否为独立 LLM 调用、是否绕开 `chat.py:1647` 探针，须直读代码确认，给 文件:行。

### 5.4 43-68k 数字溯源（**确认是否在追幽灵**）

- 该数字来自交接文档（非真值源）
- 主路径实测最高 22.7k
- **须溯源**：最初哪次观测？哪条 path？哪个 tokenizer？是否在追幽灵？
- 若是真观测，对应 conv_id / 时间 / tokenizer 是？
- 若是估算，估算公式 / 假设是？

### 5.5 `short_term` 真实 cap

- INV-2 §3 推算 ~1,900
- 本刀实测已破 → **2,388**
- **须核**：`SHORT_TERM_MAX` 实际行为（`short_term.py:44` 写的是 60 messages = 30 turn，但 token 换算上限到底是多少？INV-2 §3 推算公式哪里偏了？）
- 给 文件:行 + token/turn 实测平均

### 5.6 （backlog，**低优先，不进第二刀**）前端会话计数不同步

- 前端左侧会话计数与实际不同步，**切 tab 才刷新**
- 属前端 stale state bug，与 token 治理无关，记此备忘
- 第二刀**不处理**

---

## 边界声明

- 探针**纯观测**：不改 prompt 组装、不改 config、不改业务逻辑、不读 DB、不调 LLM、不调向量
- 任何异常 silent 吞 + debug log，**绝不阻塞** LLM 调用
- tokenizer = `litellm.token_counter(model='qwen3.6-max-preview')`（对 Qwen 中文存在 ~20-30% 高估，作为相对量级诊断有效；与 INVESTIGATION-2 同 tokenizer 可对照）
- 探针 marker 解析基于当前 Jinja 模板（`templates/layer_a/b/c/d.j2`）；模板措辞变化时字段会归零，但行仍写出（可看出"哪个 layer 解析失败了"）
- 落盘文件：`logs/token_probe.jsonl`（按行 append，无并发锁——若多 worker 并发 LLM 调用，可能罕见 JSON 行被截断；当前单进程后端无此风险）

### 改动文件清单

| 文件 | 类型 | 说明 |
|---|---|---|
| `backend/agents/_token_probe.py` | 新增 | 探针模块（**保留**给第二刀复用，本刀不卸） |
| `backend/agents/chat.py` | M | L1647 后插 14 行（import + emit_sync 调用 + try/except 外层 guard） |
| `docs/INVESTIGATION-3.md` | 新增 | 本文件（含 ⑤ 第二刀待查清单） |
| `docs/INVESTIGATION-INDEX.md` | M | 加 INV-3 索引行 + §1 性能/Token 治理类聚补条目 |

### 收口

本刀如实收口：

- ✅ 探针就位 + 真机 40+ 轮实测完
- ✅ 原假设代码层双排除（实测层未被反证，但 summary 重压缩**未获正向验证**）
- ✅ 硬产出：`tools_schema` 13.25k 实测确认（为后续工具懒加载弹药）
- ⚠️ 主路径 43-68k 症状**未复现**，实测封顶 22.7k —— **不强行定凶**
- → 真凶疑在主动 / 后台链，转**第二刀**（⑤ 待查清单 6 条，含 fold 触发机制认知分歧待代码裁决）

**探针保留**给第二刀复用 / 复算。
