# INVESTIGATION-3 · token 治理轮（第一刀 + 第二刀勘查）

> 接续 `docs/INVESTIGATION-2.md`（已封满），token 治理轮独立分卷。
> 第一刀（探针 + 收口）：2026-05-19｜HEAD = `9bd555d`（docs 整理轮 + resize handle 收口后基线）
> 探针就位时间：2026-05-20 00:21｜第一刀 commit `f67dc37`
> 第二刀勘查（§⑥ 5.1–5.6）：2026-05-20｜⑤.1 已应用 patch A（`config.yaml:203 → openai/qwen-turbo`，skip-worktree 豁免件未 commit）

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

## ⑥ 第二刀勘查结果（2026-05-20 续刀 · 5.1–5.6 逐节）

> §⑤ 是第一刀转出的待查清单。本节按 §⑤ 逐条只读勘查 + ⑤.1 已应用最小 patch A；⑤.4 转 backlog。

### 6.1 ⑤.1 — `activity_judge` model 前缀缺失（**已定位 + 已 fix · 修法 A**）

**根因**：`config.yaml:203 activity_judge.model: qwen-turbo`（裸名，漏 `openai/` 前缀）→ `get_judge_model()` (`backend/proactive/activity_judge.py:70-75`) 优先返 yaml 串**原样不补前缀** → `call_llm(model='qwen-turbo')` 进 dispatcher `explicit_override` 分支 (`backend/llm/client.py:54-59`)"尊重 caller 不动"返 `(None, {})` → `resolved_model = "qwen-turbo"` (`client.py:142`) → defensive guard (`client.py:161-166`) **只 warn 不修复** → LiteLLM `BadRequestError('LLM Provider NOT provided')` → `activity_judge.py:212 except LLMError` 静默吞返 None → "judge returned no decision"。

**关键代码段**：

```python
# backend/proactive/activity_judge.py:70-75
def get_judge_model() -> str:
    val = _cfg().get("model")
    if isinstance(val, str) and val.strip():
        return val                       # ★ 优先返 yaml 串,**原样不补前缀**
    return get_planner_model()           # fallback 才回 planner_model

# backend/llm/client.py:54-59  (explicit_override 分支)
if model_override:
    logger.info("[llm.dispatcher] explicit_override model=%s", model_override)
    return None, {}                       # ★ 不读 DB / 不补前缀

# backend/llm/client.py:161-166  (defensive guard)
if "/" not in resolved_model:
    logger.warning(
        "[llm.dispatcher] model=%r lacks LiteLLM provider prefix "
        "(expected 'provider/model'); LiteLLM will likely reject this call",
        resolved_model,
    )                                     # ★ 只 warn,不修复
```

**同类风险面**（全 `call_llm(model=...)` 调用点扫盘）：

| # | 调用点 | model 参数 | 实际串 | 走分支 | 风险 |
|---|---|---|---|---|---|
| 1 | `backend/agents/chat.py:1662` 主对话 stream | **不传** | None | `db_active` → DB | ✅ |
| 2 | `backend/agents/chat.py:795` compress_memories | **不传** | None | 同上 | ✅ |
| 3 | `backend/capabilities/clipboard.py:107` summary | **不传** | None | 同上 | ✅ |
| 4 | `backend/capabilities/clipboard.py:175` translate | **不传** | None | 同上 | ✅ |
| 5 | `backend/memory/extractor.py:289` | `get_planner_model()` | `openai/qwen-turbo` (`config.yaml:2`) | explicit_override | ✅（值带前缀） |
| 6 | `backend/services/profile_regen.py:287` | `get_planner_model()` | 同上 | 同上 | ✅ |
| 7 | `backend/prompts/memory_extraction.py:117` | `get_planner_model()` | 同上 | 同上 | ✅ |
| 8 | `backend/memory/summary.py:193` | `get_summary_model()` | `openai/qwen3.5-flash` (`config.yaml:31`) | 同上 | ✅ |
| 9 | **`backend/proactive/activity_judge.py:207`** | **`get_judge_model()`** | **`qwen-turbo` (`config.yaml:203` 裸名)** | explicit_override | **❌ 中弹** |

→ 当前唯一中弹点 = #9。其它 5 个 explicit_override caller 安全是**因为 yaml 那行碰巧带前缀**，非 dispatcher 兜底——任一 yaml key 改成裸名同类失败立刻复发。

**已应用修复**：A · `config.yaml:203 qwen-turbo → openai/qwen-turbo`（最小 patch；不动 dispatcher，不偏离"让 LiteLLM 报真错保 trace 清晰"原设计；skip-worktree 豁免件，未 commit，用户重启验证）。

**B/C 留 backlog 决策**：
- B · `get_judge_model()` 加 `if "/" not in val: val = get_planner_model()` fallback（治本但语义模糊）
- C · `client.py:161-166` 升级为按 vendor 自动 prepend（偏离原设计）

### 6.2 ⑤.2 — 主动陪伴路径完整性

**结论：主动陪伴有 9 条独立触发路径；judge 死 ≠ 主动陪伴死。**

| # | 路径 | 入口文件:行 | 触发条件 | 是否独立 LLM | 状态 |
|---|---|---|---|---|---|
| 1 | **快路径** classify | `proactive/activity_smart.py:197 _classify()` + `:268 activity_smart_handler()` | IDE / 音乐 / 技术文档 URL / `app_focus_long` / 深夜 IDE **5 类硬编码规则** | **不独立**——走主聊天链 | ✅ |
| 2 | **慢路径** judge_poll | `activity_smart.py:445 judge_poll_handler()` | 停留 ≥ `min_stay` → `activity_judge.maybe_judge()` | **判断**独立 LLM（已 fix） + **生成**走主链 | ❌ → ✅（修法 A 后） |
| 3 | cron morning_briefing | `scheduler/briefing.py:57` 注册 `main.py:798-803` | cron | 走主链 | ✅ |
| 4 | cron wake_call_briefing | `briefing.py:71` 注册 `main.py:785` | cron | 走主链 | ✅ |
| 5 | cron lunch_call（weekday/weekend 2 job） | `main.py:672-704` | cron | 走主链 | ✅ 默认 True |
| 6 | cron dinner_call | `main.py:706-722` | cron | 走主链 | ✅ 默认 True |
| 7 | cron bedtime_chat | `main.py:724-740` | cron | 走主链 | 默认 False |
| 8 | interval long_idle_check | `main.py:742-757 schedule_interval(...)` | 每 N 分钟查 idle + 3 条件 | 走主链 | 默认 False |

**判断链 / 执行链分离**：路径 1 + 3–8 全部最终走 `ChatAgent.stream`（`proactive/engine.py:436+452` 和 `:847+860`）→ `chat.py:1662 call_llm(messages, stream=True, ...)` **不传 model** → dispatcher 走 `db_active` → DB `ai_providers.model`（带前缀，安全）。Judge 只是路径 2 的门，其它路径用硬编码规则 / cron 直接 fire 不调 judge。

→ 用户实测"她仍主动" = #1 + #3–#8 在工作；judge 死只少了路径 2 这一条慢路径决策能力。

### 6.3 ⑤.3 — fold/summary worker 触发机制（**复核 ①.3 自述**）

**调度方式（直读代码）**：

- worker 实体：`memory/extractor.py:316 class MemoryExtractor`，单例 task
- 启动：`main.py:573-589 lifespan` + `get_extractor_enabled()` 默认 True
- 主循环：`extractor.py:445 run_loop()`，interval `get_extractor_interval_seconds()` 默 **300s**
- **fold 调用位置**：`extractor.py:372 await fold_summaries_for_user(uid)` —— per-user 循环**末尾**，**不依赖 extractor 是否抽到新 turn**（extractor 卡死也调 fold）

**三道触发门**（`memory/summary.py:fold_one_key`）：

| 门 | 文件:行 | 命中返 |
|---|---|---|
| `summary.enabled = false` | `summary.py:326` | `"disabled"` |
| `chat_history.COUNT(*) ≤ SHORT_TERM_MAX(60)`（按 user/char/conv 过滤） | `summary.py:343-345` | `"no_cap_breach"` |
| 挤出 batch（`id > last_folded ∧ id < cap_cutoff_id`）行数 `< min_batch(4)` | `summary.py:383-384` | `"too_small"` |

**复核 ①.3 自述（代码裁决）**：

| 参数 | 配置默认 | ①.3 / 记忆#6 自述 | **代码真值** |
|---|---|---|---|
| `SHORT_TERM_MAX` | 60 | "30 turn" | **60 messages 行数**（`short_term.py:44` 直接比 message 行数） |
| `batch_turns` | 10 | "10 turn" | **10 chat_history 行数**（`summary.py:374 LIMIT :lim`），name 是 misnomer |
| `min_batch` | 4 | "4 turn（挤出窗口）" | **4 chat_history 行数**（`summary.py:383 len(batch) < min_batch`）——含 user + assistant 双行各计 1 |

→ **单位差异**：自述说 "turn pair"，代码真值是 **chat_history 行数**（user 行 + assistant 行各计 1）。`turns` 这个 name 是 misnomer，实际是 messages / rows。

**extractor 活 ≠ fold 必产出**：fold 看的是 `chat_history` 持久 DB 行数（per user/char/conv），与 extractor 的 `last_processed_turn_id` 状态**完全独立**。`_extract_batch` 每 tick 调 `fold_summaries_for_user`，但 `fold_one_key` 自检三门，命中任一就静默返。

**§③ 实测 summary 全 0 候选根因**（按可能性排）：

| # | 候选 | 验证 SQL / log |
|---|---|---|
| A | conv=43 chat_history 总行数 ≤ 60 → `no_cap_breach` 静默返 | `SELECT COUNT(*) FROM chat_history WHERE user_id='default' AND character_id=1 AND conversation_id=43` ≤ 60 |
| B | 挤出 batch < 4 行 → `too_small` 静默返 | 同上 SQL > 60 但 (总数 − 60) < 4 |
| C | LLM 失败 | `grep '[summary] LLM call failed' backend.log` 应有 ERROR；本刀实测**未提该日志出现** |
| D | LLM 返 "(无显著进展)" → `get_summary` L248 主动过滤为 None（DB 有写但读侧返空） | `SELECT summary_text FROM conversation_summary WHERE conversation_id=43` 看实值 |

代码本身**无 bug** —— 三道门 + LLM 失败处理 + 重压缩语义都按设计跑。最可能 A 或 B：`chat_history` 持久 DB 行数与 `_store` 60-cap 是不同尺度，§③ probe 测的 `short_term` 来自 `_store.get()`，不代表 DB 行数。**真正命中哪一门要查 backend.log 找 `[summary]` 字样 + 上述 SQL 真值**。

### 6.4 ⑤.4 — 43-68k 数字溯源（**转 backlog**）

43-68k 是 Qwen 官方账单真实计费值，但属"几百–上千请求中最高的极少数尖峰"，非主路径常态（主路径探针实测封顶 22.7k 与此**不矛盾**）。尖峰需探针保持挂载、日常使用中抓现行，**非代码勘查可解** → 移 backlog，**探针保留继续挂载**，等真机出现尖峰时回看 `logs/token_probe.jsonl`。

### 6.5 ⑤.5 — short_term 真实 cap

**硬封代码**（`memory/short_term.py:40-44 / 71-87 / 105-108`）：

```python
SHORT_TERM_MAX_TURNS: int = 30
SHORT_TERM_MAX: int = SHORT_TERM_MAX_TURNS * 2  # = 60 messages

# add() — bucket trim per (user, char), 不分 conv
key: _Key = (user_id, character_id)
self._store[key].append({"role": role, "content": content, "conv_id": conversation_id})
if len(self._store[key]) > SHORT_TERM_MAX:
    self._store[key] = self._store[key][-SHORT_TERM_MAX:]   # trim oldest by msg count

# get() — conv-filter on read
bucket = self._store.get((user_id, character_id), [])
if conversation_id is None:
    return list(bucket)
return [e for e in bucket if e.get("conv_id") == conversation_id]
```

**cap 真值**：

- 硬封 = **60 messages**（按行数，不按 token），per `(user_id, character_id)` 桶
- conv 维度是**读侧过滤**，不进 trim 算法
- 单条 message 内部长度**无防御** —— 极端长 content 不会触发额外 trim

**实测 token/msg**：

§③ probe 字段 `short_term` 626 → 2,388 tokens / 60 messages = **~40 tokens / msg**。

**INV-2 §3 ~1,900 推算偏差**：

- 推算系数：`30 turn × ~63 tokens/turn pair ≈ 1,900` ⇒ 隐含 **~31 tokens / msg**
- 实测：**~40 tokens / msg** → 60 × 40 = 2,400（与 2,388 吻合）
- 偏差源：INV-2 §3 采样的 turn pair 偏短；真实主对话含 tool result / 长 assistant 回应平均 ~40
- → token 上限是 **60 × 真实 token/msg**，浮动 1,500–3,000 都正常，**不是 hard cap**

**结论**：`SHORT_TERM_MAX = 60 messages` enforce 正常，**没有"破 cap"现象** —— INV-2 §3 ~1,900 推算系数偏小造成假警报。`SHORT_TERM_MAX` 实际是 message-count cap，**不是 token cap**。

### 6.6 ⑤.6 — 前端会话计数切 tab 才刷新（**backlog 单句**）

**根因方向**：前端 stale state —— `ConversationList.reload()` 的 `useEffect` 依赖 `[userId, currentCharacterId]`（`frontend/src/components/ConversationList.tsx:51-53`），**切 character 才 refetch**；单一 character 内新增对话 / 新增 message 都不刷新 conv-row 计数 —— store 无 WS push event 触发 invalidate，conv list 也无 polling。本刀**不处理**，留 backlog。

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
| `backend/agents/_token_probe.py` | 新增（第一刀，commit `f67dc37`） | 探针模块（保留挂载，第二刀复用 / 后续尖峰回看） |
| `backend/agents/chat.py` | M（第一刀，commit `f67dc37`） | L1647 后插 13 行（import + `emit_sync` 调用 + try/except 外层 guard） |
| `docs/INVESTIGATION-3.md` | 新增（第一刀） + M（第二刀本节追加 §⑥） | 本文件 |
| `docs/INVESTIGATION-INDEX.md` | M（第一刀，commit `f67dc37`） | 加 INV-3 索引行 + §1 性能/Token 治理类聚补条目 |
| `config.yaml` | M（第二刀 patch A，未 commit） | L203 `qwen-turbo → openai/qwen-turbo`（skip-worktree 豁免件，不进仓库） |

### 收口

**第一刀**（探针 + 收口，commit `f67dc37`）：

- ✅ 探针就位 + 真机 40+ 轮实测完
- ✅ 原假设代码层双排除（实测层未被反证，但 summary 重压缩**未获正向验证**）
- ✅ 硬产出：`tools_schema` 13.25k 实测确认（为后续工具懒加载弹药）
- ⚠️ 主路径 43-68k 症状**未复现**，实测封顶 22.7k —— **不强行定凶**
- → 真凶疑在主动 / 后台链，转**第二刀**

**第二刀**（§⑥ 5.1–5.6 勘查，2026-05-20）：

- ✅ ⑤.1 已定位（`config.yaml:203` 裸名 → explicit_override 分支不补前缀 → LiteLLM 拒）+ 已应用 patch A（最小修法，未 commit）
- ✅ ⑤.2 主动陪伴 9 条触发路径列清，judge 死 ≠ 主动陪伴死（用户实测"她仍主动"由 #1 快路径 + #3-#8 cron/interval 产生）
- ✅ ⑤.3 fold 触发机制代码裁决：①.3 自述的 "turn" 单位错（实际是 chat_history 行数）；extractor 活 ≠ fold 必产出，§③ summary 全 0 最可能命中 `no_cap_breach` 或 `too_small` 门
- → ⑤.4 转 backlog（43-68k 是真实尖峰非常态，探针挂载等抓现行）
- ✅ ⑤.5 short_term 真实 cap = 60 messages 硬封（不是 token cap），INV-2 §3 ~1,900 推算系数偏小造成假警报，无实际"破 cap"
- → ⑤.6 backlog（前端 stale state，与 token 治理无关）

**探针保留挂载**，等后续尖峰真机出现时回看 `logs/token_probe.jsonl` 定位。

---

## ⑦ 第二刀彻查结果（2026-05-20 续刀 · 直读代码，覆盖 ⑤.2 / ⑤.3+⑤.5 / ⑤.6）

> §⑥ 是第二刀首轮勘查。本节按用户重点质疑彻查："另有路径绕过 judge"以及"short_term 砍出是否流向 fold（⑤.3+⑤.5 同因）"。
> 直读代码，不靠记忆 / 不靠 INV-3 ①-⑥ 任何自述（含 §⑥.2 / §⑥.3 自身也再核一次）。

### 7.1 ⑤.2 — judge 恢复后哪些路径仍"裸奔"（绕过 judge 直接开口）

**复核 §⑥.2 的 9 条路径，逐条核"是否经过 `activity_judge` 闸"**：

| # | 路径 | 入口文件:行 | 是否过 judge | 是否独立 LLM |
|---|---|---|---|---|
| 1 | activity_smart 快路径 classify | `proactive/activity_smart.py:197 _classify()` + `:268 activity_smart_handler()` | ❌ **完全不调 judge**——5 类硬编码规则直接 fire | 不独立，走主聊天链 |
| 2 | activity_smart 慢路径 judge_poll | `activity_smart.py:445 judge_poll_handler()` | ✅ **唯一过 judge**——调 `maybe_judge()` | 判断独立 LLM（fix 后正常） + 生成走主链 |
| 3 | cron morning_briefing | `scheduler/briefing.py:57` 注册 `main.py:798-803` | ❌ 不调 | 走主链 |
| 4 | cron wake_call_briefing | `briefing.py:71` 注册 `main.py:785` | ❌ 不调 | 走主链 |
| 5 | cron lunch_call（weekday/weekend 2 job） | `main.py:672-704` | ❌ 不调 | 走主链 |
| 6 | cron dinner_call | `main.py:706-722` | ❌ 不调 | 走主链 |
| 7 | cron bedtime_chat | `main.py:724-740` | ❌ 不调 | 走主链 |
| 8 | interval long_idle_check | `main.py:742-757 schedule_interval(...)` | ❌ 不调 | 走主链 |

→ **9 条路径里只有 #2 经过 judge 闸；其它 8 条全部"裸奔"**（完全不走 judge，靠硬编码规则 / cron / interval 直接触发）。判断链 / 执行链分离设计如此。

**关键代码片段**（核 #1 快路径**真的没调 judge**）：

```python
# backend/proactive/activity_smart.py:197-220 _classify (节选)
def _classify(change: ActivityChange) -> Optional[str]:
    if change.kind == "app_changed":
        new_app = detail.get("new_app")
        if _is_ide(new_app):
            if _is_late_night(change.new.timestamp):
                return "activity_late_night_ide"
            return "activity_ide_open"
        if _is_music(new_app):
            return "activity_music"
        return None
    if change.kind == "url_changed":
        if _is_tech_doc_url(detail.get("new_url")):
            return "activity_url_tech_doc"
        return None
    if change.kind == "app_focus_long":
        return "activity_long_focus"
    return None

# activity_smart.py:268-372 activity_smart_handler — 命中 _classify 后:
#   过 4 道闸(active_conv / throttle / daily_cap)→ run_trigger
#   全程零 `activity_judge` import / 调用
```

**用户体感"她话多 / 老主动"对应路径**（按"裸奔"贡献度排）：

| 排名 | 路径 | 贡献的"主动开口" 场景 |
|---|---|---|
| 最高 | **#1 activity_smart 快路径** | 切到 IDE / 音乐 app / 技术文档 URL / 长时间专注一个 app / 深夜 IDE —— 真机最频繁的"主动" |
| 中 | **#3 morning_briefing / #5 lunch_call / #6 dinner_call** | 早 / 午 / 晚定点 cron，每天固定时段触发 |
| 低 | #4 wake_call_briefing / #7 bedtime_chat / #8 long_idle | 多数默认 False，需用户开 |
| 最低 | #2 judge_poll | 慢路径，min_stay + throttle + idle_threshold 三重门，fix 前死，fix 后也是低频补充 |

**⑤.2 彻查结论**：

- judge 恢复**只解锁了 #2 慢路径**这一条路径的决策能力
- 用户实测"她仍主动 / 话多"主要由 **#1 快路径**（硬编码规则）+ **#3/#5/#6 cron**（定点）贡献，**与 judge 无关**
- "裸奔" = 8 条路径完全绕过 judge 闸；这是设计意图（快路径 + cron 不应被一个 LLM 判断卡）
- judge fix 前后**主动开口频率不会有显著差异**，因为 fix 的只是慢路径决策门，不是主流量

### 7.2 ⑤.3 + ⑤.5 合并 — short_term cap 与 fold 数据源是否同源（用户重点质疑）

**用户质疑**："short_term 砍出的旧消息流向 fold 压缩成 summary——这条链是否断了？"

**彻查结果：质疑的链路根本不存在**。short_term cap 和 fold worker 用的是**两套完全独立的数据源**，逻辑上**不存在"砍出 → 交接 → 压缩"的流水线**。但这**不是 bug** —— 是设计如此（详见下方），fold 全 0 的真因要从 fold 自己的数据源 chat_history DB 表 + 三道门去找。

#### 7.2.1 short_term 砍点：**纯 slice 丢弃，零交接**

```python
# backend/memory/short_term.py:71-87 ShortTermMemory.add
async def add(self, user_id, role, content, character_id=None, conversation_id=None):
    key: _Key = (user_id, character_id)
    if key not in self._store:
        self._store[key] = []
    self._store[key].append({"role": role, "content": content, "conv_id": conversation_id})
    if len(self._store[key]) > SHORT_TERM_MAX:                # SHORT_TERM_MAX = 60 messages
        trimmed = len(self._store[key]) - SHORT_TERM_MAX
        self._store[key] = self._store[key][-SHORT_TERM_MAX:]  # ★ 直接 slice 舍弃,**无任何写入 / 通知 / 回调**
        logger.debug(
            "[short_term] user=%s char=%s trimmed %d old messages, "
            "kept %d (= %d turns)",
            user_id, character_id, trimmed,
            SHORT_TERM_MAX, SHORT_TERM_MAX_TURNS,
        )
```

→ 砍下来的 messages **没有任何代码动作**把它们交给 fold / 写入待压缩队列 / 触发 event。仅一行 `debug` log（甚至不是 info），然后**完全消失在内存里**。

- `_store` 是纯 in-memory dict（`backend/memory/short_term.py:52 self._store: Dict[_Key, List[dict]] = {}`），无持久化、无回调钩子、无 observer
- grep `from backend.memory.short_term` 全 codebase 无 fold / summary 模块 import 它

#### 7.2.2 fold worker 数据源：**直接读 chat_history DB 表**

```python
# backend/memory/summary.py:347-380 fold_one_key (节选)
# cap_cutoff_id = chat_history 中倒数第 SHORT_TERM_MAX 条的 id (= 仍在窗口内的最旧条)
cap_row = (await session.execute(text(
    "SELECT id FROM chat_history "
    "WHERE user_id = :u "
    "  AND character_id ... AND conversation_id ... "
    "ORDER BY id DESC LIMIT 1 OFFSET :off"
), {..., "off": SHORT_TERM_MAX - 1})).fetchone()
if cap_row is None:
    return {"status": "no_cap_breach", "total": int(total)}
cap_cutoff_id = int(cap_row[0])

# 取"挤出窗口的最早 batch":id 在 (last_folded, cap_cutoff_id) 区间内
rows = (await session.execute(text(
    "SELECT id, role, content, created_at FROM chat_history "
    "WHERE user_id = :u "
    "  AND character_id ... AND conversation_id ... "
    "  AND id > :last AND id < :cut "
    "ORDER BY id ASC LIMIT :lim"
), {..., "last": last_folded, "cut": cap_cutoff_id, "lim": batch_turns_cfg})).fetchall()
```

→ fold worker **完全不读** `_store`，**只读 chat_history DB 表**（持久层）。"挤出窗口"= chat_history 中倒数 60 行之外的旧行（由 `OFFSET SHORT_TERM_MAX - 1` 算 `cap_cutoff_id`）。

#### 7.2.3 chat_history 写入路径（同时落 `_store` + DB）

```python
# backend/routes/ws.py:421-443 (每 chat round)
await short_term_memory.add(user_id, "user", user_text, ...)          # 落 _store
await short_term_memory.add(user_id, "assistant", reply, ...)         # 落 _store
async with AsyncSessionLocal() as session:
    if not skip_user_history:
        await add_chat_history(session, user_id, "user", user_text, ...)   # 落 DB
    await add_chat_history(session, user_id, "assistant", reply, ...)      # 落 DB
```

→ 每 round 同时写两处。短期记忆（`_store`）和 fold 数据源（`chat_history` DB）**有共同源头但事后零联动**。`_store` 砍出后，DB 那行还在；fold 之后从 DB 读那些旧行。

#### 7.2.4 SHORT_TERM_MAX 真实语义（彻底裁决，复核 §⑥.3 / §⑥.5）

| 项 | 真值 | 文件:行 |
|---|---|---|
| **按条数 cap，不按 token** | `SHORT_TERM_MAX = 60 messages` | `short_term.py:44` |
| 桶维度 | `(user_id, character_id)`，**不分 conv** | `short_term.py:71 key: _Key = (user_id, character_id)` |
| conv 是读侧过滤 | `get(conv_id=X)` 只过滤，**不进 trim 算法** | `short_term.py:105-108` |
| 单条 message 内容长度 | **无防御** —— 极端长 content 不触发额外 trim | `short_term.py:79-81` 只比 `len(self._store[key])`（条数） |
| 砍出动作 | 纯 `[-SHORT_TERM_MAX:]` slice 丢弃 | `short_term.py:79-81` |
| 任何"交接给 fold"动作 | **零** | grep 全 codebase 0 命中 |

→ `SHORT_TERM_MAX` 是 **message-count cap**，**不是 token cap**。INV-2 §3 ~1,900 tokens 推算假设 ~31 tokens/msg，§③ 实测 ~40 tokens/msg → 60×40 ≈ 2,400（与 2,388 吻合）。token 上限 = 60 × 真实 token/msg，**软上限浮动**，不是 hard cap。**没有"破 cap"现象**。

#### 7.2.5 fold worker 触发链（复核 §⑥.3）

| 环 | 文件:行 | 真值 |
|---|---|---|
| worker 启动 | `main.py:573-589 lifespan` | `get_extractor_enabled()` 默认 True，单例 task |
| 主循环间隔 | `extractor.py:445-459 run_loop()` | `get_extractor_interval_seconds()` 默 **300s** |
| fold 调用位置 | `extractor.py:372` | `await fold_summaries_for_user(uid)` 在 `_extract_batch` per-user 循环末尾，**不依赖 extractor 是否抽到新 turn** |
| key 枚举 | `summary.py:437-440 fold_summaries_for_user` | `SELECT DISTINCT character_id, conversation_id FROM chat_history WHERE user_id=:u` |
| 三道门 (`fold_one_key`) | `summary.py:326 / 343-345 / 383-384` | disabled / `total ≤ 60` `no_cap_breach` / `batch < min_batch(4)` `too_small` |
| `batch_turns` 真实语义 | `summary.py:374 LIMIT :lim` | **chat_history 行数**（`turns` 是 misnomer） |
| `min_batch` 真实语义 | `summary.py:383 len(batch) < min_batch` | **chat_history 行数**（含 user 行 + assistant 行各计 1） |
| LLM 写表 | `summary.py:394-403` 调 `_call_summary_llm` 成功后 `_write_state` 覆盖写 | `conversation_summary.summary_text` 列 |
| `get_summary` 主动过滤 | `summary.py:247-249 if not s or s == "(无显著进展)": return None` | DB 有写但读侧返 None |

**ChatHistory 每 round 写 2 行**（`ws.py:421-443` 实证：user + assistant 双 add，除 `skip_user_history` 特殊场景）。conv=43 跑 40+ 轮 → chat_history **应该 ≥ 80 行 > 60**，理论上 `no_cap_breach` 门不会命中。

#### 7.2.6 fold 全 0 真根因候选（按代码层可能性排）

| # | 候选 | 验证方式（用户真机查） |
|---|---|---|
| A | conv=43 chat_history 行数实际 ≤ 60（与 §③ probe 不一致；可能存在某种写入路径未落 DB / 同 conv 跨 char 拆分等场景） | `sqlite3 momoos.db "SELECT COUNT(*) FROM chat_history WHERE user_id='default' AND character_id=1 AND conversation_id=43"` |
| B | 行数 > 60 但 (总数 − 60) < 4 → `too_small` 静默返；下次 tick 累积满 4 行再 fold | 同上 SQL → 检验 total − 60 是否 < 4 |
| C | LLM 失败 → ERROR log `[summary] LLM call failed`（pointer 不前进，反复重试） | `grep '[summary] LLM' backend.log` |
| D | LLM 成功但内容 = "(无显著进展)" → DB 有写但 `get_summary` 主动过滤为空 | `sqlite3 momoos.db "SELECT summary_text FROM conversation_summary WHERE conversation_id=43"` |
| E | `conversation_summary` 行根本未 init（极端：用户某些场景 conv_id 为 None / `_get_or_create_state` 异常） | `sqlite3 momoos.db "SELECT * FROM conversation_summary WHERE conversation_id=43"` 看是否有行 |

**§③ probe 实测的 `short_term` 字段来自 `_store.get()`，不代表 chat_history DB 行数**。§③ 看 short_term 涨到 60 messages cap 上限 ≠ chat_history DB 行数 > 60。两者尺度可能错位（如 `_store` 因进程重启被重新 restore，DB 持久但 `_store` 重建中状态可能短暂错位）。

**⑤.3 + ⑤.5 彻查结论**：

- 用户质疑的"short_term 砍出 → 流向 fold"链路**根本不存在**，是**架构误解**而非 bug
- short_term cap = in-memory `_store` 60 messages 硬封（条数，**不是 token**），砍出动作纯 slice 丢弃零交接
- fold 数据源 = `chat_history` DB 表（独立持久层），不读 `_store`
- 两者只在写入端有共同源头（`ws.py:421-443` 同时落 `_store` + DB），事后零联动 —— 这是设计意图：fold 独立持久层就算 `_store` 进程重启丢了也能继续 fold
- summary 全 0 的真根因**不在 short_term 砍出环节**，要从 fold 自己的三道门去找；§7.2.6 列了 5 个候选 A-E，需要用户真机 grep + sqlite 查
- ⑤.5 "token 2388 vs 推算 1,900" 与 fold 无关 —— SHORT_TERM_MAX 是 message-count cap 不是 token cap，2,388 是 60 × ~40 tokens/msg 的正常实例，INV-2 §3 推算系数 ~31 tokens/msg 偏小造成假警报

### 7.3 ⑤.6 — 前端会话计数切 tab 才刷新（**根因方向，单句**）

**前端 stale state**：`ConversationList.reload()` 的 `useEffect` 依赖 `[userId, currentCharacterId]`（`frontend/src/components/ConversationList.tsx:51-53`），切 character 才 refetch；单一 character 内新增对话 / 新增 message **不刷新 conv-row 计数** —— store 无 WS push event 触发 invalidate，conv list 也无 polling。本刀**不深查**，留 backlog。

---

## 第二刀彻查（§⑦）收尾

- ⑤.2 彻查：9 条主动陪伴路径**只有 #2 慢路径过 judge**，其它 8 条"裸奔"。judge fix 前后主动开口频率无显著差异；用户体感"她话多 / 老主动"主要来自 #1 快路径 + #3/#5/#6 cron
- ⑤.3 + ⑤.5 合并彻查：**short_term 砍出 → fold 的"交接链"根本不存在**，两者数据源完全独立（in-memory `_store` vs DB chat_history）；这是设计意图非 bug；summary 全 0 真根因不在 short_term 环节，§7.2.6 列 5 个 fold 自身门候选，需用户真机 grep + sqlite 验证
- ⑤.6 backlog 单句确认（前端 stale state）

**本刀仅写文档，零代码 / config / DB 改动**。⑤.1 的 patch A 已在 §⑥.1 收口。

---

## ⑧ ⑤.3 / ⑤.5 收口（非 bug 结案）

> §⑦ 已直读代码 + DB 实证完成事实链。本节作为 ⑤.3 / ⑤.5 的**最终结案**。

### 8.1 事实链（均代码 + DB 实证）

#### 事实 1 — short_term 砍出的数据直接 GC 丢弃，**无任何"交接给 fold"代码**

`backend/memory/short_term.py:71-87` trim 路径只有 `self._store[key][-SHORT_TERM_MAX:]` slice + 一行 `logger.debug`，被切掉的旧 messages 无任何引用接住，**直接 GC 回收**。

全文件 grep `fold` / `summary` **零命中**：

```
$ grep -rn 'fold\|summary' backend/memory/short_term.py
（无输出）
```

→ short_term 模块完全不知道 fold / summary 的存在，trim 时不可能"交接"。

#### 事实 2 — fold **不消费** short_term，自行从 chat_history DB 表反算"挤出窗口"

`backend/memory/summary.py:347-381` 两步 SQL：

- 先算 `cap_cutoff_id = ORDER BY id DESC LIMIT 1 OFFSET 59`（倒数第 60 条 id）
- 再 SELECT `id > last_folded AND id < cap_cutoff_id LIMIT batch_turns`

fold 数据源 = **chat_history DB 表（持久层）**，**不读** `_store`（in-memory）。两套系统**仅共用一个常量** `SHORT_TERM_MAX = 60`（`summary.py:59 from backend.memory.short_term import SHORT_TERM_MAX`）作为 DB OFFSET 数值，**没有任何运行时数据流**。

→ "砍出 → 喂 fold"的链 **从未被设计存在，亦不应存在**。这是设计意图（fold 独立持久层，`_store` 进程重启丢了也能继续 fold），不是断链。

#### 事实 3 — DB 实测 chat_history 行数 < 60 触发线（fold SQL 必然捞空）

```sql
sqlite3 momoos.db "SELECT character_id, conversation_id, COUNT(*) FROM chat_history GROUP BY character_id, conversation_id ORDER BY COUNT(*) DESC;"
```

输出：

```
1|43|49
1|41|8
```

→ 当前 DB 里 chat_history 只有两段对话：

| character_id | conversation_id | 行数 |
|---|---|---|
| 1 (Mai) | 43 | **49** |
| 1 (Mai) | 41 | 8 |

**两段都 < 60**：

- conv=43 行数 49 ≤ `SHORT_TERM_MAX(60)` → `fold_one_key` 命中 `summary.py:343-345` **`no_cap_breach`** 门，**静默返回**
- conv=41 行数 8 ≤ 60 → 同上命中 `no_cap_breach`

`fold_one_key` 即便走到第二步 SELECT（`id > last_folded AND id < cap_cutoff_id`），`cap_cutoff_id` 也算不出来（`OFFSET 59` 在只有 49 行的表里 `fetchone()` 返 None → `summary.py:362-363` 直接返 `no_cap_breach`）。

→ **summary 全 0 是正确预期行为，非故障**。fold 三道门按设计正确拒绝了"还没到 cap 就压缩"的请求。

#### 事实 4 — ⑤.5 "token 2,388 vs 推算 1,900" 的别扭源于用不存在的机制解释现象

⑤.5 把 `SHORT_TERM_MAX` 当作"token cap"去对比 INV-2 §3 的 ~1,900 推算，但代码真值是 **message-count cap = 60 条**（`short_term.py:79-81` 比的是 `len(self._store[key])` 即条数）。

在**真实机制**下：

- in-memory `_store` 桶按条数硬封 60
- token 总量 = 60 × 真实平均 token/msg
- 平均 token/msg 随消息内容浮动（中文长 msg / tool result 拉高），实测 ~40 tokens/msg → 60 × 40 ≈ 2,400 与 §③ probe 实测的 2,388 吻合
- INV-2 §3 推算 ~1,900 隐含的 ~31 tokens/msg 系数偏小（取样的 turn pair 偏短）

→ **没有"破 cap"现象**，2,388 是 60-msg cap 内的正常浮动；INV-2 §3 ~1,900 推算系数偏小造成假警报。

### 8.2 结论

| 编号 | 状态 | 说明 |
|---|---|---|
| **⑤.3 fold 全 0** | **非 bug，结案** | 当前 DB 两段对话 49 / 8 行都 < 60，fold 三道门按设计正确拒绝；未来任一段对话超 60 条后 fold 会正常产出 |
| **⑤.5 short_term cap "token 别扭"** | **非 bug，结案** | `SHORT_TERM_MAX = 60` 是 message-count cap **不是 token cap**；2,388 是 60 × ~40 tokens/msg 的正常浮动；INV-2 §3 推算系数偏小造成假警报 |

### 8.3 后续影响（架构断言）

- **short_term 与 fold 是两套独立系统**（`_store` in-memory + chat_history DB），仅共用 `SHORT_TERM_MAX = 60` 常量做 DB OFFSET，无运行时数据流
- 后续如果改造 short_term（如改为动态 token cap、改 trim 策略等），**不影响 fold**——fold 自己从 DB 反算挤出窗口，与 `_store` trim 行为完全解耦
- 反之亦然：fold 改造（如调 `min_batch` / `batch_turns` / 加新 LLM）也不影响 short_term 注入侧

→ ⑤.3 + ⑤.5 自此结案。后续 token 治理改造可放心在 short_term 或 fold 任一侧动手，不会因为"另一侧没改"出连锁问题。

---

## ⑨ 本轮收尾状态（2026-05-20 深夜）

> 本节作为本轮 token 第一刀（含探针 + ⑤.1–⑤.6 多轮勘查 + ⑤.1 / ⑤.3 / ⑤.5 闭环 + 1 处常量改）的总收尾，下一次开刀前从此读起。

### 9.1 已闭环

- **token 第一刀已 commit** `f67dc37`（探针 `backend/agents/_token_probe.py` 挂载中，**未卸**，等后续尖峰真机回看 `logs/token_probe.jsonl`）
- **⑤.1 `qwen-turbo` 前缀根因定位 + 修复 A 已落地生效**：
  - 改动：`config.yaml:203 activity_judge.model: qwen-turbo → openai/qwen-turbo`（skip-worktree 豁免件，未 commit）
  - 实证：日志见 `[llm.dispatcher] explicit_override model=openai/qwen-turbo`（带前缀，不再被 LiteLLM 拒）
- **⑤.3 / ⑤.5 实证结案【非 bug】**（见 §⑧）：
  - short_term 与 fold 为独立系统，"砍出喂 fold"的链不存在亦不应存在
  - fold 自行从 chat_history DB 表反算挤出窗口读取
  - **实测正向验证**：`short_term` 改 25 turn 降低门槛 + 对话量涨至 conv=43 行数 56 过线后，`logs/token_probe.jsonl` 最后一行（`2026-05-19T19:22:35`）实测 `summary` 字段由 0 → **465** —— fold 链路实证正常工作，重压缩语义首次正向上场
- **`short_term` 改造**：`backend/memory/short_term.py:40 SHORT_TERM_MAX_TURNS: 30 → 25`（自动联动 `SHORT_TERM_MAX = 50 messages`）已写入代码并生效（fold 触发实证反推后端已重启加载新常量）；未 commit

### 9.2 待办两刀（均未开，需清醒 + 对应纪律单独做）

#### 9.2.1 ⑤.2 主动对话路径完整性
- A 已修 `activity_judge` 一条闸（慢路径 judge_poll 决策能力恢复）
- 但 §⑦.1 实证：**9 条主动陪伴路径里仍有 8 条绕过 judge 直接触发**（快路径 5 类规则 + cron 系 + interval）
- 属**产品决策**：是否所有主动路径都过 judge 闸？还是保留"快路径硬编码不过 judge"的设计？
- → 待真机观察 A 效果后定（用户体感 judge fix 前后主动开口频率有无显著变化）

#### 9.2.2 工具懒加载（省 token 最大头，**高危**）
- 实测：`tools_schema` 恒定 **13,250 tokens**，占单次请求 ~58%（§③）
- **高危预警**（记忆 #10）：主动调用工具**不可无脑懒加载** —— 否则静默失灵，同 `switch_character` 死点（INVESTIGATION 早期已踩过）
- 改动面：4-6 文件 + 1 新模块
- 开刀前置：**重档纪律 + 改前只读勘查"主动工具路径有无运行时加载能力"**，**不可照抄主流懒加载方案**
- 不在本轮做

### 9.3 backlog（不开新刀，等触发条件 / 后议）

- **LLM 首字延迟 31,317 ms → 71,752 ms 翻倍恶化**（2026-05-20 03:08 日志实测）—— 疑与"app 加载渐慢"**同源**，独立性能刀，本刀不动
- **`short_term` 按 token 动态优化**：本轮 §⑧.3 已确认与 fold 独立，纯优化非 bug，后议（如有需要可改为动态 token cap，不影响 fold）
- **前端会话计数切 tab 才刷新**：⑤.6 前端 stale state，与 token 治理无关（§⑦.3 已落根因方向）

### 9.4 当前工作树状态（未 commit 项明示）

| 文件 | 状态 | 说明 |
|---|---|---|
| `config.yaml` | M（skip-worktree 豁免，不进仓库） | L203 patch A：`openai/qwen-turbo` 前缀已补 |
| `backend/memory/short_term.py` | M | L40 `SHORT_TERM_MAX_TURNS: 30 → 25`（仅常量值改） |
| `docs/INVESTIGATION-3.md` | M | §⑥ + §⑦ + §⑧ + §⑨ 追加（§⑨ 即本节） |

**探针 `_token_probe.py` 已随 `f67dc37` 入仓**，挂载中不卸。

---

## ⑩ token 第二刀勘查（2026-05-20 · 探针覆盖面扩面只读勘查）

> 接 §⑨ 收尾。本节目的：把现挂在 `chat.py:1647-1660` 的主路径探针的**覆盖面**扩到 §④ 明示的三条未观测链（`activity_judge` 慢路径 / `summary` fold worker / `proactive engine` 各 stream），回答"43-68k 数字是不是这三条链贡献的"。
>
> **本节纯只读勘查 + 文档**，**不写任何探针挂载代码、不动 .py / config / DB**。所有 LLM 调用点 文件:行 直读代码 + grep 验证。

### 10.1 全局事实链——所有 LLM 调用都走 `backend/llm/client.py::call_llm` 统一封装

`grep -rn 'from litellm\|import litellm\|from openai\|import openai' backend/` 全 backend 命中：

```
backend/llm/client.py:15:from litellm import acompletion
backend/llm/client.py:16:import litellm.exceptions as llm_exc
backend/agents/_token_probe.py:55:        import litellm    # ← 仅做 tokenizer,非 LLM 调用
```

→ **`from litellm import acompletion` 全 backend 仅 1 处** = `backend/llm/client.py:15`，是所有 LLM 调用的唯一底层入口。无任何模块直接 `litellm.completion(...)` / `openai.ChatCompletion.create(...)` / 原生 SDK。

`grep -rn 'call_llm(' backend/` 全 backend 命中 9 个调用点（与 §⑥.1 表格一致，本刀复核确认）：

| # | 调用点 文件:行 | 入口函数 | 走 `client.py`? |
|---|---|---|---|
| 1 | `backend/agents/chat.py:1662` | `ChatAgent.stream()` 主对话 stream loop | ✅ |
| 2 | `backend/agents/chat.py:795` | `compress_memories()` LLM 压缩工具 | ✅ |
| 3 | `backend/agents/chat.py:1539` (经 `stream_llm` → `client.py:228 call_llm`) | `ChatAgent.handle()` 非流式分支 | ✅ |
| 4 | `backend/capabilities/clipboard.py:107` | `summarize_clipboard()` | ✅ |
| 5 | `backend/capabilities/clipboard.py:175` | `translate_clipboard()` | ✅ |
| 6 | `backend/memory/extractor.py:287` | `MemoryExtractor._extract_batch()` LLM 抽取 | ✅ |
| 7 | `backend/services/profile_regen.py:285` | `regenerate_profile()` 用户画像 LLM 重算 | ✅ |
| 8 | `backend/prompts/memory_extraction.py:115` | `_call_extraction_llm()` | ✅ |
| 9 | **`backend/memory/summary.py:191`** | **`_call_summary_llm()`** ← **目标 #2** | ✅ |
| 10 | **`backend/proactive/activity_judge.py:205`** | **`_call_judge_llm()`** ← **目标 #1** | ✅ |

→ **全部 10 个 caller 都走 `client.py::call_llm` 统一封装**（含本任务三条目标链）。

**关键架构推论（探针挂法 / 字段对齐都基于这条）**：

- 探针**可在 `client.py::call_llm` 集中挂一次自动覆盖所有 LLM 调用**（一处改动覆盖所有 caller）
- 但 `client.py` 不具备业务感知，要区分 source（main_chat / activity_judge / summary_worker / proactive_engine / ...），需 caller 通过 kwargs 传"魔法字段"
- 现 `chat.py:1647` 主路径探针**不在** `client.py`，而是紧贴 `call_llm` 调用之前的 caller 侧（外层）—— 设计意图是"看到 caller 已经组装完成的 messages + tools"，便于按 marker 切层
- 集中挂 vs 逐点挂的取舍见 §10.5

### 10.2 链 #1 — `activity_judge` 慢路径（独立 LLM 调用）

**唯一 LLM 调用点**：`backend/proactive/activity_judge.py:202-217 _call_judge_llm`

```python
# backend/proactive/activity_judge.py:202-217 (节选)
async def _call_judge_llm(prompt: str) -> Optional[str]:
    """调 qwen-turbo 拿 raw response。失败 → None + log,不抛。"""
    try:
        response = await call_llm(
            messages=[{"role": "user", "content": prompt}],
            model=get_judge_model(),
            stream=False,
        )
        raw = (response.choices[0].message.content or "").strip()
        return raw
    except LLMError as exc:
        logger.warning("[activity_judge] LLM call failed: %s", exc)
        return None
```

**入口调用链**：

- 顶层 entry：`activity_judge.maybe_judge()` (`activity_judge.py:289-371`)
- 上游唯一 caller：`activity_smart.judge_poll_handler()` (`activity_smart.py:400-523`) → `ActivityWatcher.register_poll_listener(...)` 注册（详 §⑦.1 路径 #2 慢路径）
- prompt 来源：`_build_judge_prompt(...)` (`activity_judge.py:157-190`) — 单 string 模板渲染 `_JUDGE_PROMPT_TEMPLATE`（L129-154）

**prompt 结构**：**单一 `user` message，纯裸 prompt，无 `system` 消息、无 `tools` 参数**：

```python
messages=[{"role": "user", "content": prompt}]     # 仅 1 条 user
# 无 tools= 参数
```

**字段适配性**（对照主路径 `_token_probe.py` 13 字段）：

| 字段 | 适用 | 备注 |
|---|---|---|
| `timestamp` | ✅ | emit 时刻 |
| `conv_id` | ❌ | judge 不绑特定 conv（节流靠 `stay_key`），应记 `None` |
| `turn_n` | ❌ | judge 单次调用无 multi-round 概念，应记 `1` 或 `None` |
| `tools_schema` | ❌ | 无 `tools=` 参数 → 应记 `0` |
| `persona` / `character_state` / `addendum` / `layer_a` / `layer_b` / `layer_c` / `layer_d` | ❌ | 无 `system` 消息 → 全应记 `0` |
| `user_profile` / `activity` / `long_memory_top5` | ❌ | 无 system → 全应记 `0` |
| `summary` / `short_term` | ❌ | 不注入 → 全应记 `0` |
| `current_text` | ✅ | 整 prompt 直接当 `current_text`（messages[0].content） |
| `system_combined` | ❌ | 无 system → `0` |
| `total` | ✅ | = `current_text`（其它分量全 0） |

**新增链特有字段建议**（保留主路径 schema 同时加 source-specific 字段，便于排查 43-68k 是否由此链贡献）：

| 字段 | 来源 文件:行 |
|---|---|
| `source` | 固定字面 `"activity_judge"` |
| `prompt_chars` | `len(prompt)` |
| `content_snippet_chars` | `len(content_snippet)`（`maybe_judge` 入参,主要膨胀源 — `stay_info` 的 url 页面摘要,默 max 2000 chars） |
| `stay_key` | `stay_info.get("key")` |
| `today_count` / `daily_cap` | `maybe_judge` 入参 |
| `since_last_speak_minutes` | `maybe_judge` 入参 |
| `judge_model` | `get_judge_model()`（`config.yaml:203` patch A 后为 `openai/qwen-turbo`） |

**接入难度评估**：**低**

- 单点 LLM 调用，prompt 是单 user msg，无需 marker 切层
- `_call_judge_llm` 内部即可读到 `prompt`；要拿"链特有字段"（`stay_key` 等）需在 `maybe_judge` (L289) 入口或 `_call_judge_llm` 调用点（L362）周边 emit
- **推荐挂点**：`activity_judge.py:362 await _call_judge_llm(prompt)` 之前。此处 `maybe_judge` 局部变量齐全（`stay_info` / `today_count` / `daily_cap` / `since_last_speak_minutes` / `content_snippet`），单点局部 emit 即可

### 10.3 链 #2 — `summary` fold worker（独立 LLM 调用）

**唯一 LLM 调用点**：`backend/memory/summary.py:183-218 _call_summary_llm`

```python
# backend/memory/summary.py:183-218 (节选)
async def _call_summary_llm(prompt: str) -> Optional[str]:
    """调 summary_model 拿压缩后的摘要。"""
    model = get_summary_model()
    try:
        response = await call_llm(
            messages=[{"role": "user", "content": prompt}],
            model=model,
            stream=False,
        )
        raw = (response.choices[0].message.content or "").strip()
        ...
    except LLMError as exc:
        logger.error("[summary] LLM call failed model=%s err=%s ...", model, exc)
        return None
```

**入口调用链**：

- 顶层 entry：`summary.fold_one_key(user_id, character_id, conversation_id)` (`summary.py:312-417`)
- 上游 caller：`summary.fold_summaries_for_user(user_id)` (`summary.py:425-459`)，per-user 循环调用
- 调度方：`backend/memory/extractor.py:372 await fold_summaries_for_user(uid)` 在 `_extract_batch` per-user 循环**末尾**
- 主循环：`extractor.run_loop()` (`extractor.py:445-459`) 每 `get_extractor_interval_seconds()` 默 **300s** 一拍
- prompt 来源：`_build_fold_prompt(existing_summary, batch_turns, token_budget)` (`summary.py:117-175`) — string 模板拼 existing_summary + batch chat_history rows + budget 指令

**prompt 结构**：**单一 `user` message，纯裸 prompt，无 `system`、无 `tools`**：

```python
messages=[{"role": "user", "content": prompt}]     # 仅 1 条 user
# 无 tools= 参数
```

**字段适配性**（对照主路径 13 字段）：

| 字段 | 适用 | 备注 |
|---|---|---|
| `timestamp` | ✅ | emit 时刻 |
| `conv_id` | ✅ | `fold_one_key` 入参 `conversation_id` |
| `turn_n` | ❌ | fold 单次调用无 multi-round 概念，应记 `1` 或 `None` |
| `tools_schema` | ❌ | 无 tools |
| `persona` / `character_state` / `addendum` / `layer_a` / `layer_b` / `layer_c` / `layer_d` / `user_profile` / `activity` / `long_memory_top5` | ❌ | 无 system → 全 `0` |
| `summary` | **⚠️ 语义陷阱** | **本链正在*生产* summary**（输入端是 `existing_summary`），不读"已有 summary 注入主对话"语义；硬记会与主路径同字段含义错位 → 应改记 `existing_summary` 元字段 |
| `short_term` | ❌ | 不注入 short_term；fold 自从 chat_history DB 读 batch（语义不同） |
| `current_text` | ✅ | 整 prompt 当 `current_text` |
| `system_combined` | ❌ | 无 system → `0` |
| `total` | ✅ | = `current_text` |

**新增链特有字段建议**：

| 字段 | 来源 文件:行 |
|---|---|
| `source` | 固定字面 `"summary_worker"` |
| `user_id` / `character_id` / `conversation_id` | `fold_one_key` 入参三元组（per-key 维度） |
| `existing_summary_chars` | `len(existing_summary)`（输入端,展示重压缩"前态") |
| `existing_summary_tokens` | `_tok(existing_summary)` |
| `batch_rows_count` | `len(batch)`（fold 本 tick 喂入的 chat_history 行数） |
| `batch_content_chars` | sum `len(r.content)` for r in batch |
| `batch_content_tokens` | `_tok(batch 拼接文本)` |
| `token_budget` | `_get_or_create_state` 返的 budget（目标产物上限,默 1000） |
| `last_folded_was` / `last_folded_now` | pointer 推进态（结案 `folded` 状态时可记） |
| `prompt_chars` | `len(prompt)` |
| `summary_model` | `get_summary_model()`（默 `openai/qwen3.5-flash`） |

**接入难度评估**：**低**

- 单点 LLM 调用，prompt 是单 user msg
- **推荐挂点**：`summary.py:191 response = await call_llm(...)` **之前**，在 `_call_summary_llm(prompt)` 内部仅能拿到 `prompt` + `model`；要拿链特有元字段（`existing_summary_chars` / `batch_rows_count` / `token_budget` / 三元组等），需在 `fold_one_key` 调 `_call_summary_llm` 处（`summary.py:394`）周边 emit，或把元信息作为 `_call_summary_llm` 入参传入
- 简易方案：扩 `_call_summary_llm` 签名加 `_probe_meta: dict` 形参，`fold_one_key` 在 L393-394 调用时传入元字段（极小改动）

### 10.4 链 #3 — `proactive engine` 各 stream（**无独立 LLM 调用点**，全走主路径）

**勘查结论**：`proactive/engine.py` + `proactive/activity_smart.py` 全文 grep **零 `call_llm` 调用**：

```bash
$ grep -n 'call_llm\|acompletion' backend/proactive/engine.py backend/proactive/activity_smart.py
(无输出)
```

→ 9 条主动陪伴路径里：

- **路径 #1 快路径 `activity_smart_handler`**（`activity_smart.py:268-381`）→ `run_trigger(trigger, user_id)` → `engine.py:294 run_trigger` 
- **路径 #2 慢路径 `judge_poll_handler`**（`activity_smart.py:400-523`）→ `activity_judge.maybe_judge()` *(链 #1 独立 LLM)* + `run_trigger(...)` *(走主链)*
- **路径 #3-#7 各 cron**（`main.py:672-740`, `briefing.py:57/71`）→ `run_trigger(...)`
- **路径 #8 interval `long_idle_check`**（`main.py:742-757`）→ `run_trigger(...)`
- **stage1 `wake_call`**（`engine.py:717 run_wake_call_trigger`）→ 独立 path

**所有 `run_trigger` / `run_wake_call_trigger` 内部的"主动开口 LLM 生成"动作**全部走 `ChatAgent.stream(chat_msg)`：

```python
# backend/proactive/engine.py:436+452 run_trigger
chat_agent = ChatAgent()
...
_agent_stream = chat_agent.stream(chat_msg)
...
async for sentence in _agent_stream:
    ...

# backend/proactive/engine.py:847+860 run_wake_call_trigger
chat_agent = ChatAgent()
...
_agent_stream = chat_agent.stream(chat_msg)
```

→ 全部最终汇入 `ChatAgent.stream` → `chat.py:1662 call_llm(messages, stream=True, tools=san_tools, ...)`，**已被 `chat.py:1647-1660` 现有主路径探针覆盖**。

**proactive 路径与 user 路径在主路径上的区别**：仅在 `chat_msg.payload.context.turn_origin` 字段（`engine.py:387 + 807`）：

- 用户路径（`ws.py`）：`turn_origin = "user"`（隐式默认）
- proactive 路径（`engine.py`）：`turn_origin = trigger.name`（如 `wake_call` / `activity_smart` / `cron`）
- `ChatAgent.stream` (`chat.py:1599`) 读 `turn_origin` 传给 `_build_messages` + 决定 `Mode.PROACTIVE` vs `Mode.ROLEPLAY`（`backend/agents/prompt/mode.py:24-31 PROACTIVE_ORIGINS = {cron, activity_smart, wake_call, lunch_call_weekday, lunch_call_weekend, dinner_call}`）

**字段适配性**：与主路径**完全一致** —— `proactive_engine` 走的就是同一份 `_build_messages` + `_get_all_tools()` 链路（renderer Mode.PROACTIVE 只影响 Jinja layer_b 渲染的 directive 内容，字段切层结构不变）。

**新增链特有字段建议**：

| 字段 | 来源 |
|---|---|
| `source` | `"main_chat"` 若 `turn_origin == "user"`；否则 `"proactive_engine"`（按 `turn_origin in PROACTIVE_ORIGINS` 判） |
| `turn_origin` | 原值字面（`"user"` / `"wake_call"` / `"activity_smart"` / ...）— 比布尔 source tag 更细，便于按 trigger 看尖峰来源 |

**接入难度评估**：**极低**

- **零新挂载点** —— 现 `chat.py:1647 _token_probe_emit(...)` 已就位，且 `turn_origin` 在 `ChatAgent.stream` 内是局部变量（`chat.py:1599`）— 可直接作为参数透传
- **改动面**：`_token_probe.py::emit_sync` 加 `turn_origin` 形参 + 内部按 `PROACTIVE_ORIGINS` 判 `source` 标签写入 row；`chat.py:1653` 现 emit 调用加 `turn_origin=turn_origin` kwarg
- 现有 `main_chat` 行向后兼容（`turn_origin` 缺省默认 `"user"` → `source="main_chat"`）

### 10.5 集中挂 vs 逐点挂取舍（供 PM 拍板）

**方案 A — 集中挂在 `client.py::call_llm` 入口**

| 优势 | 劣势 |
|---|---|
| 1 改动覆盖全部 10 个 caller（含本任务范围外的 extractor / profile_regen / clipboard / memory_extraction） | `client.py` 是基础设施层,加业务感知"污染感"强,违 "call_llm 不做业务感知" 原设计 |
| 自动覆盖未来新增 caller | 要识别 source 必须 caller 传"魔法 kwargs"（如 `_token_probe_source="..."`),`client.py` 内还得 strip 掉避免泄漏给 `acompletion` |
| 单挂点统一 | 三条链 prompt 结构差异大（单 user msg vs 完整 5-layer system）,集中挂 + emit_sync 内仍需分流字段计算 |
|  | 现 `chat.py:1647` 探针在 LLM 调用**之前**(紧贴 `sanitize_tools_for_llm`)；client.py 入口挂还需删除现有挂载并验证,动到 commit `f67dc37` 入仓的产物 |
|  | 会覆盖本任务**不要的链**(extractor / profile_regen / clipboard / memory_extraction）—— 不致命但 jsonl 噪音变大 |

**方案 B — 逐点挂 + 共享 `_token_probe.py` 模块**（推荐）

| 优势 | 劣势 |
|---|---|
| 现 `chat.py:1647` 主路径探针**零改动**（仅扩一个 kwarg `turn_origin`） | 三个挂点（main_chat 已有 + activity_judge 新 + summary_worker 新） |
| 字段裁剪可按链定制（自有元字段不污染 main_chat schema） | 未来若新增独立 LLM 链需补挂点 |
| `emit_sync` 共享一份，加 `source` + 链特有字段做条件分支 | `_call_summary_llm` 签名要扩一个 `_probe_meta` 形参传链特有元字段 |
| 与本刀范围（三条目标链）严格对齐，不溢出 |  |
| `client.py` 维持纯基础设施定位 |  |

**推荐 B**：

- `chat.py:1647-1660`：现 emit_sync 加 `turn_origin=turn_origin` kwarg；`emit_sync` 内按 `turn_origin in PROACTIVE_ORIGINS` 决定 `source = "proactive_engine"` 或 `"main_chat"`
- `activity_judge.py:362`：在 `raw = await _call_judge_llm(prompt)` **之前**插 emit_sync 调用，`source="activity_judge"` + 链特有字段
- `summary.py:394`：在 `new_summary = await _call_summary_llm(prompt)` **之前**插 emit_sync 调用，`source="summary_worker"` + 链特有字段
- `_token_probe.py::emit_sync` 重构为支持多 source（字段子集 + 链特有元字段）

**字段 schema 收敛建议**：

| schema 字段集 | main_chat / proactive_engine | activity_judge / summary_worker |
|---|---|---|
| 主路径 13 字段（tools_schema / persona / ... / total） | ✅ 全字段适用，沿用现 `_split_*` 逻辑 | ❌ 全部填 `0`（仅 `current_text` / `total` 有值） |
| `source` tag | ✅ 必加 | ✅ 必加 |
| `turn_origin` | ✅ 主路径必加 | ❌ 不适用（无 trigger.name 概念） |
| 链特有元字段 | ❌ | ✅ 各链独立子集 |

→ 同一行 jsonl 始终 26+ 字段，按 source tag 看哪些字段有值即可。落盘 `logs/token_probe.jsonl` 共用一文件。

### 10.6 真凶推断：43-68k 是不是这三条链贡献的？

**只读勘查无法定论**，但代码层证据指向：

- **`activity_judge` 链**：prompt 含 `content_snippet`（url 页面摘要，max 默 2000 chars ≈ ~1500 tokens），加 prompt 模板（~400 字）≈ **2-3k tokens 单次封顶**。**不可能贡献 43-68k**
- **`summary_worker` 链**：prompt 含 `existing_summary`（≤ token_budget=1000）+ `batch_turns`（默 10 行 chat_history，每行 ~50-200 字），加模板 ≈ **2-4k tokens 单次封顶**。**不可能贡献 43-68k**
- **`proactive_engine` 链**：与 main_chat 完全同 schema，封顶上限本应同 ~22.7k（§③），唯一可能尖峰来源——但 proactive 路径 `_build_messages` 还多注入 `extra_system`（`engine.py:381 chat_msg.payload.context.extra_system = system_prompt`），即 trigger.build_system_prompt 返的额外 system 文本。**这条注入路径未被现 `chat.py:1647` 探针的 marker 切层覆盖**（探针按 layer_a/b/c/d header 切，`extra_system` 拼在何处需 `_build_messages` 实现确认 — 若拼在 system 内会被 system_combined 计入但不归任何 layer；若另起一条 system message 则可能被 short_term 误算或漏算）

→ **若 43-68k 真实存在，最可能在 `proactive_engine` 路径上**（trigger.build_system_prompt 返回的 `extra_system` 可能很长，含 wake_call 的 `briefing_data` 聚合结果 / cron briefing prompt 等）。需写探针挂上后**真机跑一阵触发各 cron 抓现行**才能定。

**推断需验证项**（写探针时一并采）：

1. `_build_messages` 如何处理 `extra_system` —— 拼在 layer_b/c/d 之间？另起 system？append 末尾？
2. `proactive_engine` 路径下 `system_combined` token 实测值 vs 主路径 `main_chat`
3. 各 cron trigger（morning_briefing / lunch_call / dinner_call）`extra_system` 实际长度

### 10.7 改动文件清单（**预告**，本节不动）

下一步（PM 裁定后）写挂载代码涉及：

| 文件 | 预计改动 | 说明 |
|---|---|---|
| `backend/agents/_token_probe.py` | M | `emit_sync` 重构支持多 source + 链特有字段；保持现 main_chat schema 向后兼容 |
| `backend/agents/chat.py` | M | L1653 `emit_sync(...)` 调用加 `turn_origin=turn_origin` kwarg（零业务行为变化） |
| `backend/proactive/activity_judge.py` | M | L362 前插 emit_sync 调用 + 链特有字段透传 |
| `backend/memory/summary.py` | M | `_call_summary_llm` 签名扩 `_probe_meta` 形参；`fold_one_key` L394 调用前 emit_sync + 元字段 |
| `logs/token_probe.jsonl` | 字段集变化 | 同一文件续 append；下游消费方按 `source` 字段过滤即可 |

### 10.8 收口

- ✅ 三条目标链 LLM 调用点全列：`activity_judge.py:205` / `summary.py:191` / `proactive_engine` 实际 = `chat.py:1662`（已覆盖）
- ✅ 全部走 `client.py::call_llm` 统一封装；全 backend 无任何直接 `acompletion` / 原生 SDK 调用
- ✅ 字段适配性矩阵列清：`activity_judge` / `summary_worker` 仅 `current_text` / `total` 适用（裸 prompt），需链特有字段；`proactive_engine` 与 main_chat 同 schema，需 `turn_origin` / `source` 标签
- ✅ 集中挂 vs 逐点挂取舍列清，**推荐 B 方案**（逐点挂 + 共享模块）
- ⚠️ 真凶推断：`activity_judge` + `summary_worker` 单次封顶 2-4k，**不可能贡献 43-68k**；最可能在 `proactive_engine` 的 `extra_system` 注入路径
- 🔒 **本节零代码 / config / DB 改动**，纯只读勘查
- ➡️ **下一步等 PM 裁定 A/B 方案 + 字段裁剪后**才写探针挂载代码

→ **PM 决策（2026-05-20）**：43-68k 真凶推断转 backlog，§10.6 三项验证项延后；token 治理重点转 tools_schema（13,250）砍肥；详 INV-4 §1。

### 10.9 backlog 落档（2026-05-21 子轨 A/B 期间散落项）

> 子轨 A · prompt caching + 子轨 B · 工具治理 实施期间在 PM-CC 对话中发现的次要项,集中落档供未来 archaeology / 单独刀次议。

- **DashScope 偶发 Connection error → 各 worker retry/fallback 行为审计**
  来源:INV-5 §5.2.2 8 caller direct trigger 首次跑撞到 `LLMServiceError: DashscopeException - Connection error / aiohappyeyeballs sock_connect timeout`(profile_regen / memory_extraction / summary fold / activity_judge 4 个 worker 受影响)。第二次重跑全 PASS,判定是公网端点偶发抖动,不是 prefix 切换兼容性问题。但**生产环境后台 worker 遇此错误时 retry/fallback 行为未审计** —— extractor 主循环 300s tick 自然重试;summary fold pointer 不前进等下次;activity_judge 静默吞返 None 等节流过期;profile_regen 单次失败无重试机制。建议单独刀审计各 worker error-recovery 路径,可能需加 exponential backoff retry。

- **Skyler 历史 model 名错位 archaeology 记录**
  `config.yaml:1 default_model: dashscope/qwen3.6-max-preview` 仅作 yaml fallback(DB 无 active 时才用)。Phase 4 prefix 切之后 DB ai_providers id=16 active 行 = `dashscope/qwen3.5-plus`。**main_chat 生产路径实际走 qwen3.5-plus,不是 qwen3.6-max-preview**。所有从 INV-3 §1.1 起的 cost 估算基于 max 价位 — 与 qwen-plus 实际价位约偏高 **~5x**(Qwen-max ~¥0.04/1k input vs Qwen-plus ~¥0.008/1k input)。INV-5 §5.2.2 已注解此事,本条挂在 INV-3 backlog 区供未来 archaeology 用,避免重复踩坑。
  → 影响:子轨 B INV-4 §3.5 实施清单的"~6.8k tokens 收益"按 max 价位换算约 ¥0.27/turn 节省,按 plus 真实价位约 ¥0.054/turn,**绝对成本节省比预估低 5x**。仍有意义但 ROI 量级需调整预期。详 ROADMAP 路径 D 条目下备注。
