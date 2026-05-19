本文件接续 docs/INVESTIGATION.md，前端+性能阶段起用。

---

## 【性能治法弹药 · 2026-05-19 15:30】

只读勘查；offline 重建（未启动 backend / 未实发 LLM 请求 / 临时脚本测完已撤）；未改任何代码 / DB / commit / stash。**修正**：上一份账单测的是 **legacy fallback path** (`_build_messages`)，**主路径是 Jinja 5-layer renderer** (`render_system_prompt`)。本份用真主路径重测。

tokenizer：`litellm.token_counter(model='qwen3.6-max-preview')`（cl100k_base fallback；中文高估 20-30%）。

---

### §1 全块清单（主路径 Jinja renderer，逐块单列，所有记忆注入点）

`backend/agents/chat.py:_build_messages` (L1232-1487) 主路径流程：

```
1. system_prompt = await render_system_prompt(character_id, ...kwargs)
   → 5 个 Jinja layer 渲染:
       Layer A  (output format + tts_language directive)
       Layer B  (mode_directive + universal_constraints + TOOL_PROMPT_ADDENDUM)
       Layer C  (persona identity/personality/speech_style/voice_samples/
                 forbidden_phrases/taboo_topics/lore + character_state)
       Layer D  (user_profile + today_activity + long_memory_top5 +
                 tool_results + temp_instructions + proactive_briefing)
       (Transition - 仅切 variant 时)
   → "\n\n".join 成单字符串
2. messages.append({role:system, content:system_prompt})
3. (可选) messages.append({role:system, content:【过往对话摘要(滚动压缩)】\n<sum>}) ← conversation_summary
4. messages += short_term_memory.get(user, char, conv)  ← real turn messages
5. messages.append({role:user, content:current_text})
+ tools= parameter (MEMORY_TOOLS 4 + ToolRegistry.list_schemas() 54 = 58 schemas)
```

**Layer A/B/D 静态/半静态块**（每次请求都送，零或最小膨胀）：

| 块 | tokens | 说明 |
|---|---:|---|
| Layer A (tts_language=zh) | **404** | output format directive（4 个 inline tag 描述 + 长度建议） |
| Layer A (tts_language=ja 跨语种增强) | **1,328** | +924 tokens 仅 cid=101 樱岛麻衣（ja voice）走这路径；cid=1 已 Z.8 改 zh，不走 |
| Layer B (roleplay/proactive 共同) | **3,687** | mode 指令 ~498 + TOOL_PROMPT_ADDENDUM 3189 |
| Layer D (empty) | **20** | 仅"[上下文信息 - 数据陈述,不是行为指令]"头 |
| Layer D (full: profile+activity+memory_top5) | **152** | 132 tokens 增量 |

**所有"记忆/working buffer"注入点全清单（实读 chat.py，4 点无遗漏）**：

| # | 注入点 | 位置 | 上限 | 备注 |
|---|---|---|---|---|
| 1 | **long_term recall (top-5)** | Layer D `long_memory_top5` (renderer kwargs)；底层 `search_relevant_memories(top_k=5)` | top-5 硬 cap | 当前 default 用户 2 行 NULL memory，约 59 tokens |
| 2 | **character_state**（mood/intimacy/activity/thought）| Layer C C4 段（Jinja 内嵌）；`load_character_state(cid)` | 字段长度小 | 是"关系状态/working buffer"，**藏在 persona 块里**容易漏盘 |
| 3 | **conversation_summary**（滚动压缩） | 独立 system msg，chat.py:1466-1471 | `token_budget` 字段控制（每个 conversation 独立 cap） | 当前 default 用户 0 行（未触发） |
| 4 | **short_term history** | 真 user/assistant turn messages，chat.py:1484；`SHORT_TERM_MAX=60 messages = 30 turn` | 30 turn cap | 实测 18 msg = 1130 tokens（≈63 tokens/msg） |

**无第 5 个**：未发现其它把"记忆/摘要/关系/working buffer"塞 prompt 的隐式路径。`tool_results`/`temp_instructions`/`proactive_briefing` 属当前轮上下文，不算"记忆"。

---

### §2 ⭐ persona 按角色实测（Jinja 真渲染 - 修正上一版误判）

**上一份"persona 341 tokens"是 legacy fallback path 测的 `characters.persona` 列原始字段长度，不是真正发往 LLM 的渲染后内容**。主路径走 `load_active_persona()`（读 `character_personas` 多 variant 表）→ Layer C Jinja 模板真渲染。

#### 各角色 Layer C 渲染后 token 表

| cid | name (UI) | variant | layer_c tokens | Tier-2 字段 | voice_samples (filtered/raw) | signature_phrases |
|---:|---|---|---:|---|---|---:|
| **1** | **Momo (Mai 借壳)** | default | **2,759** | taboo + lore.prefs + lore.emotion | **10 / 12** | **3** |
| 2 | 八重神子 | default | 258 | (空) | 0 / 0 | 0 |
| 3 | 荧 | default | 246 | (空) | 0 / 0 | 0 |
| 4 | 凝光 | default | 197 | (空) | 0 / 0 | 0 |
| 5 | 神里绫华 | default | 231 | (空) | 0 / 0 | 0 |
| 99 | 一般路过猫娘 | default | 205 | (空) | 0 / 0 | 0 |
| 100 | 祥子-test | default | 198 | (空) | 0 / 0 | 0 |
| 101 | 樱岛麻衣（独立 ja 模式） | default | 249 | (空) | 0 / 0 | 0 |
| 102 | 流萤 | default | 197 | (空) | 0 / 0 | 0 |

**结论**：
- **cid=1（当前 active，Mai 借壳）= 2,759 tokens**——用户怀疑成立 ✅
- 其余 8 角色都是 197-258 tokens 空骨架（仅基础 identity 模板）
- **极差 14×**（2759 vs 197）

#### cid=1 Mai 内部分解（raw JSON token，非渲染后；但反映各字段相对体量）

| 字段 | tokens (raw JSON) | 占 layer_c 比 (估) |
|---|---:|---:|
| `identity`（含 self_intro 双梯级） | 533 | ~19% |
| `personality_core` | 213 | ~8% |
| `speech_style` | 163 | ~6% |
| `signature_phrases` (3 条) | 25 | ~1% |
| **`voice_samples` (12 raw → 10 filtered@tol=0.5)** | **766** | **~28%** |
| `forbidden_phrases` | 171 | ~6% |
| `taboo_topics` (Tier-2) | 451 | ~16% |
| `lore` (preferences + emotion_triggers, Tier-2) | 940 | ~34% |
| **raw 字段总和** | **3,262** | — |
| **Jinja 渲染后 layer_c** | **2,759** | （模板省略部分结构 + 过滤了 voice_samples 2 条） |

→ **lore + voice_samples + taboo_topics 三大块占 layer_c ~70%**。lore 内含 emotion_triggers（per-emotion 多字段：触发场景+表现+TTS标签）+ preferences（likes/dislikes/secretly_appreciates）。

#### 切角色后 HEAD 总量变化

| 当前 active | layer_a + layer_b + layer_c (system_prompt 主体, empty D) | vs cid=1 baseline |
|---|---:|---|
| cid=1 Mai（当前） | 404 + 3,687 + 2,759 + 20 ≈ **6,870** | baseline |
| 切到 cid=2 八重（空骨架） | 404 + 3,687 + 258 + 20 ≈ **4,369** | **-2,501** |
| 切到 cid=101 樱岛麻衣 ja 模式 | **1,328** + 3,687 + 249 + 20 ≈ **5,284** | -1,586（ja layer_a 反弹 +924） |

→ 切到空骨架角色 system_prompt 主体节省 ~2.5k tokens；但 cid=101 因 tts_language=ja 触发 Layer A 跨语种段反弹。

---

### §3 ADDENDUM 冗余 vs 增量分段（治法弹药 - 用户疑两者重复）

`TOOL_PROMPT_ADDENDUM` (3,189 tokens) 按 `【...】` 段分割（13 段）：

| 段 | tokens | 分类 | 依据 |
|---|---:|:--:|---|
| (开头说明 - 通用) | 41 | **A** 冗余 | 总体提示，与 LLM tool calling 设计冗余 |
| 【日历类】 | 141 | **B** 增量 | 跨工具协同（time.now → apple_calendar.create_event 顺序） |
| 【日程录入】 | 126 | **B** 增量 | 跨工具协同序列指令 |
| 【时间类】 | 87 | **B** 增量 | time.now 触发条件（跨场景判断） |
| 【记忆类】save_memory/delete_memory/list_memories/compress_memories | 133 | **B** 增量 | "不要主动调"约束 + 跨工具组合（list→delete 顺序） |
| 【系统类】clear_short_term | 33 | **A** 冗余 | 单工具短描述，与 schema description 高重叠 |
| 【音乐类】网易云场景 | 536 | **B** 增量 | 跨工具决策树 + autoplay 字段真实/假装区分 |
| 【媒体控制】 | 241 | **B** 增量 | 用户口语→工具映射 + 跨工具消歧 |
| 【角色状态】 | 255 | **B** 增量 | 调用频率约束（每 5-10 轮一次）+ 触发场景 |
| 【剪贴板】 | 129 | **B** 增量 | 调用克制（"不要主动响应"）+ 隐私契约 |
| 【小红书 URL 解析】 | 330 | **B** 增量 | 返回失败处理 + 拒绝假装结果 |
| 【网易云本地 mpv 自动播放】 | 398 | **B** 增量 | 首选路径选择 + 失败诊断引导 |
| 【B 站类】 | 743 | **B** 增量 | 杀手 use case 描述（字幕总结）+ 红线（不投币/不三连） |

**分类汇总**：

| 类别 | tokens | 占 ADDENDUM | 占总请求 |
|---|---:|---:|---:|
| **A 冗余**（与 schema description 重复，理论可压缩） | **74** | 2.3% | 0.4% |
| **B 真增量**（跨工具协同 / 策略约束 / use case 决策树 / 失败诊断 / 红线） | **3,119** | 97.8% | 17.3% |

**结论**：
- ADDENDUM **几乎全是真增量**（97.8%），冗余很少（74 tokens / 2.3%）
- 压缩 ADDENDUM 理论可省 = **~74 tokens 上限**（仅 A 段），收益微小（占总请求 0.4%）
- **风险**：B 部分都是跨工具协同 / 用户口语映射 / 失败处理 / 红线，删了会导致 LLM 不知道何时调何工具、把失败假装成功、突破红线。**不可简单删 B**
- 真要瘦身 ADDENDUM，可能方向是**按场景动态选择载入哪几段**（如音乐场景不载小红书段）——但这就归到"懒加载"问题（见 §5）

---

### §4 58 工具使用盘点（治法弹药）

**Top 8 工具按 schema token 大小**：

| name | tokens | source | 说明 |
|---|---:|---|---|
| `xhs.parse_url` | **403** | Capability | 小红书 URL 解析（含 5 道返回失败状态说明） |
| `proactive.snooze_wake_call` | **393** | Capability | wake_call 推迟（用户 push 后端 trigger） |
| `character.set_activity` | **382** | Capability | 角色"在做什么"更新（含调用频率约束） |
| `apple_calendar.create_event` | **373** | Capability | 创建日历事件（时间字段 + 时区） |
| `bilibili.get_subtitles` | **367** | Capability | B 站字幕（含 source 状态说明） |
| `save_memory` | **359** | MEMORY_TOOLS | 用户主动存记忆（含 type 五分类约束） |
| `docx.create` | **348** | Capability | Word 文档创建（参数 + 模板说明） |
| `netease.daily_recommend` | **310** | Capability | 网易云日推（无参数但 description 长） |

**全部 58 工具按来源汇总**：

| 来源 | 个数 | tokens | 注 |
|---|---:|---:|---|
| MEMORY_TOOLS (chat.py:456 hardcoded) | 4 | 624 | save_memory / delete_memory / list_memories / compress_memories |
| Capability registry (`@register_capability`) | 54 | 10,476 | activity(3) / apple_calendar(4) / google_calendar(2) / calendar(2 router) / bilibili(11) / clipboard(3) / docx(3) / netease(13) / media(5) / screen(4) / character(3) / time(1) / xhs(1) / proactive.snooze(1) / clear_short_term(1) |
| **合计** | **58** | **11,100** | （tools= 实测 11,150，差 ~50 tokens 是 JSON wrapping） |

**僵尸工具核**（实读：`switch_character / add_todo / delete_todo / search_todo` 应已下线）：

```
$ grep ToolRegistry.register backend/tools/registry.py
ToolRegistry.register("clear_short_term", clear_short_term, CLEAR_SHORT_TERM_SCHEMA)
(switch_character 已删,注释保留)
```

→ ✅ **未发现已退役工具混入** ToolRegistry。58 个全是真活注册。

**注**：本审计未对每个工具做"用户实际使用频率"统计（需埋点 / 日志聚合，超出范围）。但 `bilibili 11 个` / `netease 13 个` / `screen 4 个` 等模块化能力区，是否每个都常用 = 治法决策点之一。

**裁僵尸理论可省**：当前 = 0 tokens（无僵尸）。如要瘦，需进入"裁低频/未用工具"——超出僵尸范畴，需埋点支持。

---

### §5 工具懒加载可行性预研（只摸地形，不开方）

#### 注入链实读

```
chat.py:588-593  _get_all_tools() → MEMORY_TOOLS + ToolRegistry.list_schemas()
                 ↑ 唯一返回点,无 context 参数,无过滤逻辑
chat.py:1647     san_tools = sanitize_tools_for_llm(_get_all_tools())
chat.py:1652     tools=san_tools     ← 传给 LiteLLM acompletion()
```

工具注册（启动时一次性，进程内）：
- 主动 `import backend.capabilities.*` 触发 `@register_capability` 装饰器副作用 → `ToolRegistry.register(name, func, schema)`
- `_tools` (Callable map) + `_schemas` (OpenAI schema map) 两个 module-level dict
- `list_schemas()` 全返；无任何过滤接口

#### "改成懒加载"要动的模块（地形清单）

| 改动点 | 文件:行 | 现状 | 改成懒载需要 |
|---|---|---|---|
| 主返回点 | `chat.py:588-593` | `return MEMORY_TOOLS + ToolRegistry.list_schemas()` | 加 `context` 参数 + 路由逻辑 |
| 注入点 | `chat.py:1647-1652` | 直接传 san_tools | 改成"context-aware" 选 subset |
| Registry 查询接口 | `tools/registry.py:62-65 list_schemas()` | 全返 list | 加 `filter(...)` 或新增 `list_schemas_subset(names)` |
| LLM 执行端 KeyError 容错 | `tools/registry.py:46-55 get()` 已有 KeyError raise；`agents/tool.py` + `agents/tool_call_resilience.py` 有局部 fallback | 当前 KeyError → tool_call_resilience 兜底（只有 5-6 个白名单工具） | 扩展为"按需 lazy register" 或 explicit "未载入,请重试"反馈给 LLM |
| 新模块（可能） | `backend/agents/tool_router.py` (不存在) | — | 路由器：决定 "本轮给哪些工具" |

**主要改动点估计**：~4-6 个文件 + 1 个新模块 + 测试覆盖。中等量级。

#### 风险点（实读列出，不替决）

**① 判断"该给哪些工具"的机制选项**（每个有自己代价）：

| 选项 | 优点 | 代价/风险 |
|---|---|---|
| (a) 规则匹配（用户消息关键词 → tool name） | 实现简单、零 latency | 维护成本高（新工具要更新规则）；中文同义词覆盖不全易漏 |
| (b) 向量检索（msg embedding → tool description top-N） | 语义召回较好 | 增加一次 embedding 延迟（即使用本地模型 ~50-200ms）；漏召率不可零 |
| (c) LLM 路由（先小模型分类） | 准确 | **双 LLM 调用**，"治慢"反而增 latency；新依赖 |
| (d) 静态分组+对话状态切换（按角色/场景固定一组） | 简单可控 | 粒度粗；切换边界判断难（一个对话里跨场景常见） |
| (e) 混合（hot + 路由 cold） | 平衡 | 实现最复杂 |

**② 与"主动陪伴/主动调用"架构的冲突点**：

- 当前 LLM 是**完全自主**决定调任何 tool 的 — 工具表整个暴露给它
- 懒加载后：LLM **在某些场景下看不到某些工具**
  - 主动陪伴 trigger（wake_call/proactive briefing）触发 ChatAgent 时，**初始上下文可能不含用户意图信号** → 路由难判
  - 用户在闲聊中突然说"对了帮我建个日历事件" — 若日历工具未在本轮预载，LLM 不会主动调，会"答应了但没做"
- 当前架构假设"LLM 完全主动"，懒加载会引入"工具能力对 LLM 选择性可见"的新心智模型

**③ 静默失灵风险（switch_character/todos 教训）**：

- 当前 KeyError raise 路径不显式告知 LLM "工具未载入"，会被 tool_call_resilience 兜底成 fallback name；但路由漏选时 LLM 根本不知道该工具存在
- **未载入即不可见 = silent functional loss** — 与 switch_character silent failure 同一性质
- 防范成本：需要 LLM-facing 的反馈通道（"我需要某能力但当前未启用"），或单元测试覆盖"路由漏选 → 二次召回"路径

#### §5 小结

懒加载理论可省 **10k+ tokens**（按需选 5-10 个工具 vs 全送 58 个）；但实施风险集中在 ② ③——架构层冲突 + 静默失灵风险。改动点 4-6 个文件 + 1 个新模块。**不给方案，只列地形。**

---

### §6 重算总账（最小请求 vs 现实重度请求）

| 块 | 最小请求 (cid=1 Mai + 空 + "你好") | 现实重度 (Mai + profile + 模拟 8h activity + memory + 30msg 历史 + 摘要) | 备注 |
|---|---:|---:|---|
| Layer A (output format zh) | 404 | 404 | 固定 |
| Layer B (mode + ADDENDUM 3189) | 3,687 | 3,687 | 固定 |
| **Layer C persona (Mai active)** | **2,759** | **2,759** | **半固定，角色切则变** |
| Layer D (profile+activity+memory) | 1 (~empty header) | 152 | 随上下文 |
| **system_prompt 主体** | **6,851** | **7,120** | — |
| conversation_summary (rolling) | 0 | 204 | 触发后受 token_budget cap |
| short_term history | 1 | 1,130 (18 msg) | ~63 tokens/msg, cap 30 turn = ~1,900 max |
| current user text | 2 | 24 | — |
| `tools=` 58 schemas | **11,150** | **11,150** | 固定（懒载理论可省 10k+） |
| **GRAND TOTAL** | **18,004** | **19,628** | A→B 净增 +1,624 |

**对比上一份（legacy path）数值**：

| 场景 | 上一份 (legacy) | 本份 (renderer 主路径) | 差 |
|---|---:|---:|---:|
| 最小请求 | 16,223 | **18,004** | **+1,781** |
| 重度请求 | 17,588 | **19,628** | +2,040 |

差异原因：legacy path 用 `characters.persona` 列原始字段（341 tokens for Mai），renderer 用 `character_personas` 多 variant Jinja 渲染（2,759 tokens for Mai）— **本份才是真发往 LLM 的内容**。

#### 最肥块排序（最小请求）— 修正后

| # | 块 | tokens | 占比 | 性质 |
|---|---|---:|---:|---|
| #1 | `tools=` 58 schemas | **11,150** | **61.9%** | 固定大；懒载可省 |
| #2 | Layer B (含 ADDENDUM 3,189) | **3,687** | **20.5%** | 固定大；ADDENDUM 97.8% 真增量难压 |
| **#3** | **Layer C persona (Mai active)** | **2,759** | **15.3%** | **半固定，角色切则变 197-2,759**（**新进 Top-3，用户怀疑成立**） |
| #4 | Layer A | 404 | 2.2% | 固定（ja 模式反弹至 1,328） |
| #5 | Layer D + history + summary 等 | <60-2,500 | — | 随使用，cap 已就位 |

**记忆相关在重度场景的占比**：history 1,130 + summary 204 + memory_top5 ~60 = **1,394 tokens / 7.1%**——不进前三，仍是次要膨胀。

#### 三种治法弹药估算（不开方，仅算上限）

| 治法 | 理论可省（最小请求） | 风险 |
|---|---:|---|
| 工具懒加载（58 → 5-10 个） | ~9-10k tokens | 高（静默失灵 + 架构冲突，§5） |
| ADDENDUM 压缩 | ~74 tokens (A 段) | 极低（仅 A 段） |
| persona 字段裁剪（删 lore.emotion_triggers / 减 voice_samples） | 500-1500 tokens | 中（影响角色一致性 / 情绪表达） |
| 历史窗口收缩（30 turn → 15 turn） | ~600 tokens | 中（短期连贯性下降） |
| 切到空骨架角色 | ~2,500 tokens | 不是治法（属角色切换） |

### 边界声明

- 主路径已纠正为 Jinja renderer（`render_system_prompt`）；上一份测的是 legacy fallback
- persona 实测用 `load_active_persona` 真读 `character_personas` + Jinja 真渲染
- Layer C 内部分解的"raw JSON tokens"反映各字段相对体量，与渲染后绝对 token 数有差异（模板有结构 + 过滤逻辑）
- 临时测量脚本（/tmp/audit3.py）测完已 `rm`
- 改动范围：仅 `docs/INVESTIGATION-2.md` 本节追加 + 新建 `docs/INVESTIGATION-INDEX.md`；零代码 / 零 DB / 零 commit / 零 stash

### 暂停

只读勘查 + 测量完成；只摸弹药，不开方。等顾问决：是否进入治法环节，哪个方向优先。

---

只读诊断；offline 重建（未启动 backend、未实发 LLM 请求、临时测量脚本测完已撤）；未改任何代码 / DB / commit / stash。

**tokenizer** = `litellm.token_counter(model='qwen3.6-max-preview')`（内部 fallback 到 `tiktoken cl100k_base`；中文存在 ~20-30% 高估，作为 first-order 诊断有效）。

### 1. 拼装点定位（chat.py 实读）

**入口**：`backend/agents/chat.py:_build_messages` (L1105-1500+)。一次 LLM 请求由 4 段 + 1 个 `tools=` 参数组成：

```
[system_prompt]                ← system_parts.append 拼接出来,L1455
[conversation_summary]         ← 滚动摘要,独立 system 块,L1464-1471
[history msgs]                 ← short_term per-(user,char,conv) 最近 turns
[current user text]            ← 用户当前输入
+ tools= 参数                  ← MEMORY_TOOLS + ToolRegistry.list_schemas(),L1614
```

**system_parts 拼装顺序**：

| # | 块 | 来源 | 性质 |
|---|---|---|---|
| 1 | emotion_inst | chat.py `_build_emotion_instruction()` | 固定（`<emotion>` 标签格式） |
| 2 | thinking_inst | chat.py `_build_thinking_instruction()` | 固定 |
| 3 | motion_inst | chat.py `_build_motion_instruction()` | 固定 |
| 4 | state_inst | chat.py `_build_state_update_instruction(state)` | 固定 + 当前角色状态值 |
| 5 | characters.persona 列 | DB `characters.persona` for cid | 固定/角色切则变 |
| 6 | BASE_INSTRUCTION | `config/prompts.py:3` | 固定 |
| 7 | TOOL_PROMPT_ADDENDUM | `agents/prompt/tool_addendum.py` | **固定（大）** |
| 8 | TOOL_BEHAVIOR_BLOCK | chat.py 常量 | 固定 |
| 9 | profile (chunk 11) | `services/profile_regen.format_profile_for_prompt(profile_data)` | 有 cap（7 字段模板） |
| 10 | activity_timeline (chunk 14) | `services/activity_timeline.format_today_activity_for_prompt(user_id)` | **有硬 cap（top-5 apps + 30 字 title 截断）** |
| 11 | 长期记忆 recall | `memory/long_term.search_relevant_memories(top_k=5)` | 有 cap（top-5） |
| 12 | 工具调用结果（rare） | tool_result | 出现即按 4000 字符截断（TOOL_RESULT_MAX_CHARS） |
| 13 | 临时指令（touch event 等） | extra_system | 罕见 |
| 14 | proactive 简报（stage 2） | `_maybe_build_wake_call_addendum` | 罕见 |

后续：
- `messages[0] = {role:system, content:system_prompt}`
- `messages[1] = conversation_summary`（若存在）
- `messages[2..] = short_term history（按 conv_id 严格过滤）`
- `messages[-1] = {role:user, content:current text}`
- `tools = MEMORY_TOOLS (4) + ToolRegistry.list_schemas() (54)` = **58 tool schemas**

### 2. 逐块称重 — 静态块（每次请求都送）

| 块 | tokens | 有无上限 | 会否膨胀 |
|---|---:|---|---|
| `emotion_inst + thinking_inst + motion_inst + state_inst` | **1,046** | 固定（state_inst 含当前角色状态值，但 mood/intimacy/thought/activity 字段长度都很小） | 否 |
| `characters.persona` (Mai cid=1) | **341** | 角色切换时变；当前 Mai persona 字段较短 | 否（除非编辑 persona） |
| `BASE_INSTRUCTION` | **180** | 固定 | 否 |
| **`TOOL_PROMPT_ADDENDUM`** | **3,189** | 固定 ⚠️ 大 | 否 |
| `TOOL_BEHAVIOR_BLOCK` | **251** | 固定 | 否 |
| **HEAD 小计** | **5,007** | — | — |
| **`tools=` 58 个 schema** | **11,150** | 固定 ⚠️ 巨 | 新增 capability 才涨 |
| **静态总计（每次请求都送）** | **16,157** | — | — |

### 2.5 ⭐ Activity Timeline 重点查（用户最怀疑的膨胀源）

**注入逻辑位置**：`backend/services/activity_timeline.py:384-500` `format_today_activity_for_prompt(user_id)`

**注入粒度**（实读代码 + 模拟实测）：
- **不是**逐条 app session 列流水账
- **是**按 app aggregate 后取 **top-5**：每行一句"`- {app_display_name} {总时长}(主要看 {URL host} {标题截 30 字} {该 URL 时长})`"
- 总活跃 <60s → 整块不注入
- header："`## 用户今日活动\n今天已活跃 X 小时 Y 分钟。\n\n主要花在:`"（3 行）
- 末尾："`最近 30 分钟主要在: X`"（1 行，若有近期 app）
- title 截 30 字 + ellipsis（`activity_timeline.py:485`，防 prompt 膨胀显式注释）

**真实测量 — 8 小时重度使用模拟**：

构造 1500+ 模拟 sessions 跨 40 apps（VS Code 4h + Chrome 2.4h + Terminal/WeChat/Music + 16 个尾部 apps），跑过真 format 函数：

```
## 用户今日活动
今天已活跃 7小时51分钟。

主要花在:
- Visual Studio Code 4小时(主要看 github.com feat: add token-counting middl… 4分钟)
- Google Chrome 2小时25分钟(主要看 www.bilibili.com 【深度】大模型 token 经济学 推理成本怎么算 + 案例… 2分钟)
- Terminal 20分钟
- WeChat 15分钟
- Music 10分钟(主要看 music.163.com 私人雷达 - 网易云音乐 (深夜专用) 0分钟)
```

→ **154 tokens / 276 字符**。**与 sessions 数量 / 真实小时数无关**（top-5 + 30 字 title 双重 cap）。

**当前 default 用户 DB 真值**（实测）：`activity_sessions` 今日 0 行 → 整块不注入，**0 tokens**。

**结论**：Activity Timeline **有硬 cap，非膨胀源**。8 小时重度使用 = 154 tokens（占 17k 请求总量 0.9%）。**用户怀疑不成立**。

### 3. 三场景账单（真值）

#### Scenario A — 冷启动第 1 句 "你好"

| 块 | tokens | 占比 |
|---|---:|---:|
| HEAD 小计 | 5,007 | 30.9% |
| `[body]` profile | 63 | 0.4% |
| `[body]` activity_timeline | 0 | 0.0% |
| `[body]` memory recall | 0 | 0.0% |
| `[msg]` history | 1 | 0.0% |
| `[msg]` current user text | 2 | 0.0% |
| `[tools=]` 58 schemas | **11,150** | **68.7%** |
| **GRAND TOTAL** | **16,223** | **100%** |

#### Scenario B — 15+ 轮 + 8h 重度电脑使用（activity 模拟最大）

| 块 | tokens | 占比 |
|---|---:|---:|
| HEAD 小计 | 5,007 | 28.5% |
| `[body]` profile | 63 | 0.4% |
| `[body]` activity_timeline（**模拟 8h heavy**） | **154** | **0.9%** |
| `[body]` memory recall (top-5) | 59 | 0.3% |
| `[msg]` history (18 msg) | 1,130 | 6.4% |
| `[msg]` current user text | 24 | 0.1% |
| `[tools=]` 58 schemas | **11,150** | **63.4%** |
| **GRAND TOTAL** | **17,588** | **100%** |

#### Scenario C — 工具调用一来回（time.now + 历史 10 msg）

| 块 | tokens | 占比 |
|---|---:|---:|
| HEAD 小计 | 5,007 | 29.4% |
| `[body]` profile / activity / memory | 122 | 0.7% |
| `[msg]` history (10 msg) | 663 | 3.9% |
| `[msg]` current user text | 6 | 0.0% |
| `[msg]` tool_call + tool_result | 86 | 0.5% |
| `[tools=]` 58 schemas | **11,150** | **65.5%** |
| **GRAND TOTAL** | **17,035** | **100%** |

### 4. 结论（只诊断）

#### 三场景总 token

| 场景 | total | vs A 净增 | A→B 涨得最凶的块 |
|---|---:|---:|---|
| A 冷启动第 1 句 | 16,223 | baseline | — |
| B 15 轮 + 8h heavy activity | 17,588 | **+1,365** | history **+1,129** (83% of growth); activity **+154** (11%); memory **+59** (4%) |
| C 工具调用一来回 | 17,035 | +812 | history **+662**; tool round-trip +86; memory +59 |

#### 最肥的 2-3 块 + 性质

| # | 块 | 占比（场景 A） | 性质 |
|---|---|---:|---|
| **#1** | `[tools=]` 58 tool schemas | **68.7%** (11,150) | **固定大**——每次请求都全送，58 个 schema 内部均匀分布；新增 capability 才涨 |
| **#2** | `[head] TOOL_PROMPT_ADDENDUM` | **19.7%** (3,189) | **固定大**——自然语言工具使用引导手册，每次都送 |
| **#3** | `[head]` 4 个输出格式指令 + persona + BASE + BEHAVIOR | **8.8%** (1,818) | 固定（角色切则变 persona） |

#### ⭐ Activity Timeline 治理优先级 — 明确回答

| 问题 | 答案（证据） |
|---|---|
| 有无 cap？ | ✅ **有硬 cap**：`activity_timeline.py:469-470 top 5 apps`；`L484-485 title[:30]`；`L482-489` 每 app 只输出 1 行 |
| "重度使用一天"后会涨到多大？ | **~150-200 tokens**（实测 8h / 1500 sessions / 40 apps 模拟 = 154 tokens） |
| 是不是当前最该优先治理的膨胀块？ | ❌ **不是**。当前膨胀首要嫌疑是 #1 tool schemas (11.1k tokens) + #2 TOOL_PROMPT_ADDENDUM (3.2k tokens)。Activity Timeline 即便最坏场景也 <200 tokens，占比 <1%。**用户怀疑不成立** |

→ 用户 "怀疑主动感知/活动时间线无上限膨胀" 的担忧 — **代码层 + 实测双证据证伪**。top-5 cap + title 30 字截断 + display_name 简化（"VS Code" 而非 bundle name）三道收紧已就位。

#### 回复慢归因

| 归因 | 实测依据 | 判定 |
|---|---|---|
| **① prompt token 大致每次推理慢** | 单条最简 16,223 tokens（95% 固定），即"你好" 也送 16k；Qwen LLM first-token-latency 与 input token 量近线性 | **首要嫌疑** —— 由 #1 + #2 主导 |
| ② 冷启动 / 工具首次 / TTS 首载一次性延迟 | 本审计只算 token，未测 latency；冷启动 only first 次 affect | **次要 / 仅首次** |
| ③ 工具串行等待 | 工具往返 token 仅 ~86（单工具）；工具执行耗时（日历/B站等 100-500ms）另算，不算 token | **场景相关** ——只在真触发工具时叠加 |

**实测依据**：
- 16k tokens 固定（#1 tool schemas 11.1k + #2 TOOL_PROMPT_ADDENDUM 3.2k + 输出格式 1.0k + persona/BASE/BEHAVIOR 0.8k）
- history 膨胀缓慢（~63 tokens/turn pair；30 turn cap → ~1,900 tokens 上限）
- activity timeline 重度使用 cap = 154 tokens
- memory recall top-5 cap = ~150 tokens
- conversation_summary 当前 0（未触发）

→ **回复慢首要原因是 ① prompt 大**，由 #1（工具 schemas 全送）+ #2（TOOL_PROMPT_ADDENDUM 全送）双块主导。**不提优化方案**——治法（裁工具 / 工具懒注入 / 改用 retrieved tools / 压缩 ADDENDUM 等）是下一步权衡。

### 边界声明

- token 数为 litellm.token_counter (qwen3.6-max-preview) 估算；fallback cl100k_base 对 qwen 中文实际可能高估 20-30%（真量级 ~12-14k tokens 仍同序）
- "你好世界 hello world" 三种 tokenizer 测得均 7 tokens（短串一致）
- Scenario A 用空 history；B 用最近 18 条；C 用最近 10 条；conversation_summary 默认用户 0 行（DB 真值）
- Scenario B 的 activity timeline 用 **模拟**（1500+ session 跨 40 apps，8h 总时长），跑过真 format 函数生成；未写 DB
- 临时测量脚本（/tmp/token_audit2.py）测完已 `rm` 撤
- 改动范围：仅 `docs/INVESTIGATION-2.md` 新文件 + 本节追加；未触代码 / DB / commit / stash

### 暂停

token 账单完成；只诊断不开方。Activity Timeline 膨胀疑虑双证据证伪。等顾问决：是否进入治法环节（裁工具 / 懒注入 / 等），优先级如何排。

---

## 【docs 整理轮 · 2026-05-19 22:21】

文档治理：归档 + 真源对齐两刀已完成，本节为收尾登记。

### 触发

- `docs/` + 根目录共 **40 份 .md** 混杂积累；职责重叠（设计/施工记录/调研/规划/索引混在一起）
- `DESIGN.md` **5,206 行**层叠 v3 / v3.5 / v3-G / v4-alpha / v4-beta 多代设计意图 + 大量施工记录（[施]占比目测 40-55%），失去"单一真源"性质
- 14 份历史快照（audit_*/bugfix-*/chunk-15-*/fan-ui-starting/stage-2-starting/AUDIT-GROUND-TRUTH/BPATH-PROGRESS/INVESTIGATION/persona-audit/DESIGN_patch）凭定义不该维护却混在主目录

### 决策（已拍板）

- **A 方案**：`DESIGN.md` 冻结归档（机构记忆档案），`DESIGN_LITE.md` 升为当前设计真源
- **4 政策决策**：
  1. `ROADMAP.md` L15-25 "本 session 已 ship" 7 行施工段 → 剥离移到 `IMPLEMENTATION_LOG.md`，ROADMAP 原位删
  2. `DESIGN_patch.md` 不 merge，跟随 `DESIGN.md` 一起冻结归档（patch 内容以 DESIGN_LITE §6/§7 为准）
  3. 中文 `README_zh-CN.md` 保持简版（L44 自陈文档债保留），不补 Known Problems 对称
  4. 7 个死测试不碰代码，仅文档现状描述更新为"引用源已删，问题更严重，仍未修"

### 第一刀 — 归档 19 份（2026-05-19 上午）

- **15 tracked** 走 `git mv` → `docs/archive/`：DESIGN / audit_×4 / persona-audit / bugfix-×3 / chunk-15-×4 / fan-ui-starting / stage-2-starting
- **4 untracked** 走普通 `mv` → `docs/archive/`：DESIGN_patch / AUDIT-GROUND-TRUTH / BPATH-PROGRESS / INVESTIGATION
- **零字节内容改动验证**：`git diff --cached -M --diff-filter=R` 字面输出空；15 个 rename 全部 **R100**（100% similarity）
- 留下当真源/setup/spec 共 16 份（README ×2 / DESIGN_LITE / ROADMAP / IMPLEMENTATION_LOG / 4 全景文档 / mai_prompt / skills-extension-guide / 10 setup-*.md）

### 第二刀 — 5 真源对齐（2026-05-19 下午）

**改动文件**：
- `M README.md` / `M README_zh-CN.md` / `M DESIGN_LITE.md` / `M ROADMAP.md` / `M IMPLEMENTATION_LOG.md`（5 tracked，+61 / -33 行）
- `?? docs/BACKEND-OVERVIEW.md` 219→225 行 / `?? docs/FRONTEND-OVERVIEW.md` 445→458 行（仍 untracked，本会话之前未 commit）

**6 类改动**：
1. **死链修复**：6 文件共 13+ 处链接 `→ docs/archive/<file>`
2. **退役项同步**：profile_summary fallback (c1d65ff) / switch_character LLM tool (71b6e99) / todos 整套 (c1d65ff) / 12 孤儿 character_states / M-6 前端 drawer
3. **HEAD 锚点**：BACKEND-OVERVIEW `eaa9330 → c1d65ff`；FRONTEND-OVERVIEW `3d76982 → c1d65ff`
4. **本会话新成果补录**（严格标"未 commit"）：左右两个 resize handle（4 文件改未 commit）/ docs 归档第一刀（19 份 mv 未 commit）/ 2 个新 localStorage key（momoos.convListWidth / chatHistoryWidth）/ FRONTEND §1.4 vs §3.1 VoiceButton/MemoryViewer 矛盾统一
5. **DESIGN_LITE 补位声明**：顶部明示"当前设计真源"、DESIGN.md 5,206 行真值更新 / DESIGN_patch 冻结说明 / §11 标题改"与归档 DESIGN.md 的指针"
6. **ROADMAP 新挂起项**：v4.1 表 +4 行（八重 UI 线 / token 治理一轮 / docs 第二刀进行中 / Persona 蒸馏确认）

### 真值验证

| 项 | 命令 / 真值 | 结果 |
|---|---|---|
| "本会话新成果"严格标"未 commit" | grep `未 commit` ROADMAP/FRONTEND-OVERVIEW | 6+ 处命中 ✅ |
| 零"已 commit"误标 | grep `已 commit\|已commit` 全 7 文档 | **0 命中** ✅ |
| rename 字节零改动 | `git diff --cached -M --diff-filter=R` 内容 diff | 空 ✅ |
| 15 tracked R100 | `git status --porcelain` 头部 R 类 | 15 行 ✅ |
| 4 untracked moved | `?? docs/archive/{DESIGN_patch,AUDIT-GROUND-TRUTH,BPATH-PROGRESS,INVESTIGATION}.md` | 4 行 ✅ |
| 5 tracked M 文档 | `git diff --stat` | 5 files, +61 -33 ✅ |
| 零代码 / 零 DB / 零 commit / 零 stash 动作 | — | ✅ |

### 遗留待办（已知，非本轮做）

| 项 | 性质 | 处置方向 |
|---|---|---|
| `users.profile_summary` 列 DROP COLUMN | 1 行 DDL migration | 后续单独小刀，估 < 30 分钟 |
| 7 个死测试清理（含 test_memory_agent，引用源已删后更死） | 测试债 | v4.1 测试债清理一并做（ROADMAP 已记） |
| 中文 README_zh-CN Known Problems 对称 | 文档债（自陈） | 政策决定：保持简版 |
| `DESIGN_LITE §2.5` Activity-based 4 trigger 名 `ide_open/music_playing/long_focus/late_night_ide` 是否仍准确 | **[存疑]** 未做 grep 验证 | 单独一次 grep 即可核 |
| 全部 docs 改动（5 tracked M + 2 untracked OVERVIEW + 第一刀 R/?? 共 26 行 status）待 commit 决策 | git 决策 | 人工 + 顾问拍板分次 commit / 一次性 commit |
| 前端左右 resize handle 4 文件改动待 commit 决策 | git 决策 | 同上 |

### 暂停

文档治理轮（归档第一刀 + 真源对齐第二刀）完成；本节为收尾登记 INVESTIGATION-2.md + INVESTIGATION-INDEX.md。等下一步决策（commit 时机 / DROP COLUMN 小刀 / DESIGN_LITE §2.5 存疑项核 / 等）。

