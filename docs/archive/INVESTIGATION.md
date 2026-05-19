# INVESTIGATION — 统一只读调研

> 调研时间：2026-05-19 00:35｜HEAD = `eaa9330`
> 目标：把砍 `switch_character` LLM tool、统一 cid 命名、几项悬而未核的发现，一次性查清
> 全程只读：未改任何代码 / DB / migration / commit / stash / push / backend 未启动

---

## 第 1 节 · switch_character 调用链（为"砍 LLM 工具"做准备）

### 1.1 全代码库 grep 真值（backend + frontend src）

后端调用点（去除注释 / docstring 文本引用）：

| # | 文件:行 | 角色 | 说明 |
|---|---|---|---|
| 1 | `backend/tools/builtin.py:16-25` | **LLM tool 入口** | `async def switch_character(user_id, character_id)`；包了 `prompt_manager.switch_character`，不在则 raise ValueError |
| 2 | `backend/tools/builtin.py:49-71` | **LLM tool schema** | `SWITCH_CHARACTER_SCHEMA`（OpenAI function-calling 描述）—— 暴露给 LLM 的合约 |
| 3 | `backend/tools/registry.py:89` | import | `from backend.tools.builtin import (..., switch_character, ...)` |
| 4 | `backend/tools/registry.py:95` | **ToolRegistry 注册** | `ToolRegistry.register("switch_character", switch_character, SWITCH_CHARACTER_SCHEMA)` |
| 5 | `backend/config/prompt_manager.py:92-105` | **底层实现** | `class PromptManager.switch_character(self, user_id, character_id)`；仅查 yaml 5 个角色名，不命中返 False |
| 6 | `backend/config/prompts.py:117` | LLM prompt 文本 | `BASE_INSTRUCTION` 中告诉 LLM 此 tool 的存在 |
| 7 | `backend/config/prompts.py:227` | LLM prompt 文本 | tool 列表项 |
| 8 | `backend/agents/prompt/tool_addendum.py:37-38` | LLM prompt 文本 | "【系统类】switch_character / clear_short_term…" |

`prompt_manager.get_current_character`（同一模块、同一进程状态）：

| # | 文件:行 | 角色 |
|---|---|---|
| 9 | `backend/config/prompt_manager.py:107-109` | 实现 |
| 10 | `backend/routes/ws.py:932` | **唯一调用点** — `character = prompt_manager.get_current_character(user_id)` |

### 1.2 ws.py:932 的 `character` 变量是否被使用？

实测：从 `ws.py:932` 之后 grep `character`（排除 `character_id` / `character_states` / `character_switch` / `prompt_manager` / 赋值左值）→ **0 行匹配**。

→ **结论**：`ws.py:932` 抓到的 `character` 是死变量，从未被任何代码读。`prompt_manager.get_current_character` 在生产路径上**已经不参与任何决策**。

### 1.3 前端切角色 / 主动陪伴 / 初始化 走的是哪条路？

**真正的前端切角色路径**（不走 prompt_manager）：

```
frontend 发 WS 帧 type="character_switch" + character_id: int
  ↓
backend/routes/ws.py:824
  → connection_manager.set_current(user_id, incoming_char, incoming_conv)
  → ack 回前端
```

随后所有用户 WS 帧（text/voice/touch）携带 `character_id: int`：
```
ws.py:817  raw_char = data.get("character_id")
ws.py:840  conv_id, char_id = await _resolve_conv_char(...)
ws.py:848  state.char_id = char_id      ← 这才是真正的当前角色
ws.py:982  "character_id": char_id      ← ChatAgent payload
ws.py:1235  full_reply, character_id=char_id  ← 写 chat_history
ws.py:1254  character_id=char_id        ← TTS / persona / memory 链全用这个
```

`char_id` 来源是**前端在每个 WS 消息里携带的 DB 角色 id**（数字），完全不经过 `prompt_manager._user_characters`。

**主动陪伴 / 初始化**：proactive trigger / wake_call / lifespan startup 等路径全部使用 DB-side `character_id` 直接查 `characters` 表 / `character_personas` 表；同样不经过 `prompt_manager.switch_character`。

### 1.4 摘除 LLM tool `switch_character` 注册的影响评估

| 依赖路径 | 移除 #4 后是否受影响？ |
|---|---|
| ① LLM tool 调用（用户在对话中说"切到八重"） | ✅ 想要的失效（这条路径本来就是 silent failure 大本营：DB 5 个 cid 切不动） |
| ② 前端 UI 切角色（character_switch WS 帧） | ❌ 不受影响（不走 prompt_manager） |
| ③ proactive / wake_call / lifespan 初始化 | ❌ 不受影响 |
| ④ TTS 路由 / persona 加载 / memory 过滤 | ❌ 不受影响（都用 `char_id` from DB） |
| ⑤ chat.py:1335 fallback `prompt_manager.get_prompt` | ❌ 不受影响（get_prompt 不依赖 switch_character 的状态变更） |
| ⑥ ws.py:932 dead var `character = prompt_manager.get_current_character` | ❌ 仍跑（但是 dead var，可顺手清也可不清） |

**结论：摘除 #4（ToolRegistry 注册）= 完全安全**。一并清理顺序（按最小到完整）：

| 最小 | 充分 | 彻底 |
|---|---|---|
| **删 #4** 一行：`registry.py:95` `ToolRegistry.register("switch_character", ...)` | + **删 #6/#7/#8 提示文字** 让 LLM 不再误以为有此 tool | + **删 #1/#2** `switch_character` 函数 + schema 本体；+ **删 #3** import；+ **可选清 ws.py:932 dead var** |
| LLM 不再被告知这个 tool 存在（schema 不暴露）；但函数体仍存活（无影响） | LLM prompt 不再引导用户调它（治本） | 代码彻底干净 |

**注意**：`prompt_manager` 模块**不能整删** —— `chat.py:1335` 仍在用 `get_prompt` 作为 renderer 失败时的 fallback。该模块的真退役要等 Plan C（全 DB persona）真做完。

---

## 第 2 节 · characters 表 DB 真实全貌

### 2.1 `characters` 表逐 id 真值（来自 `momoos.db`，HEAD = eaa9330）

| cid | name | persona 列长 | live2d | splash_art | voice_model（provider/voice/lang） | 备注 |
|---|---|---|---|---|---|---|
| 1 | Momo | 302 | hiyori | （空） | cosyvoice / longyumi_v3 / **zh** | 持续 default 用户主角；voice 已按 Z.8 改 zh |
| 2 | 八重神子 | 145 | yae | /splash-art/2.png | cosyvoice / cosyvoice-v3.5-plus-…61ea44 / 未设(→zh) | yae live2d 真就位 |
| 3 | 荧 | 186 | （空） | /splash-art/3.png | cosyvoice / …ec2676 / 未设 | 无 live2d |
| 4 | 凝光 | 140 | （空） | （空） | （空 voice_model） | 全空骨架 |
| 5 | 神里绫华 | 179 | （空） | （空） | cosyvoice / …7c617a / 未设 | 无 live2d |
| 99 | 一般路过猫娘 | 1 | （空） | /splash-art/99.png | （空） | persona 长度 = 1 表明 `characters.persona` 列几乎空 |
| 100 | 祥子-test | 1 | （空） | /splash-art/100.png | （空） | 名字带 `-test` 后缀 = 极强测试残留信号 |
| 101 | 樱岛麻衣 | 5541 | hiyori | /splash-art/101.png | cosyvoice / …a19f52 / **ja** | persona 列 5541 字（Mai prompt 原文落 DB）；voice tts_language=ja |
| 102 | 流萤 | 52 | （空） | /splash-art/102.png（untracked） | （空） | AUDIT 后新增；空骨架 |

### 2.2 `character_personas`（多 variant 引擎，X.2 Tier-1 必填 7 字段）

每个 cid 都有恰好 1 个 variant：`variant_name='default'`, `is_active=1`, `is_builtin=1`。Tier-1 `identity.name` 真值：

| cid | character.name（UI 壳） | persona.identity.name（LLM 魂） | personality_core 长 | 状态 |
|---|---|---|---|---|
| 1 | **Momo** | **樱岛麻衣** | 263 | **X.8 借壳活跃**（UI 看到 Momo，LLM 自称樱岛麻衣） |
| 2 | 八重神子 | 八重神子 | 91 | 空骨架（模板） |
| 3 | 荧 | 荧 | 88 | 空骨架 |
| 4 | 凝光 | 凝光 | 89 | 空骨架 |
| 5 | 神里绫华 | 神里绫华 | 91 | 空骨架 |
| 99 | 一般路过猫娘 | 一般路过猫娘 | 89 | 空骨架 |
| 100 | 祥子-test | 祥子-test | 89 | 空骨架（且名字含 -test） |
| 101 | 樱岛麻衣 | 樱岛麻衣 | 89 | **同名重叠** —— variant 是空骨架，与 cid=1 的 Mai variant 实际内容不同 |
| 102 | 流萤 | 流萤 | 89 | 空骨架 |

→ **9 个 character 中只有 cid=1 有真"骨肉" persona**（identity 509 字 + personality_core 263 字）。其余 8 个都是 88-91 字模板骨架。

### 2.3 `character_states` 表（用户-亲密度 / 心情）— 真行数对照

总行数 **21**（AUDIT 写时 20，多了 1 行 = cid=102 流萤的状态）：

| 类别 | 行数 | cid 列表 | 判定 |
|---|---|---|---|
| ✅ 真 character 状态 | 9 | 1, 2, 3, 4, 5, 99, 100, 101, 102 | 对应 9 个 characters 行 |
| ❌ **孤儿** | 12 | 300, 301, 302, 303, 304, 305, 306, 400, 500, 600, 601, 700 | `characters` 表无对应 id，明显测试残留 |

注：`character_states.UNIQUE(character_id)` 约束，所以是 per-character 而非 per-(user,character)。

### 2.4 `chat_history` / `conversations` 实际活跃度

| cid | chat_history 行 | conversations 行 |
|---|---|---|
| 1 | 15 | 21 |
| 2 | 1 | 1 |
| 3 | 1 | 1 |
| 101 | 1 | 1 |
| 其余 (4, 5, 99, 100, 102) | 0 | 0 |

→ default 用户**只在 cid=1 真聊过**。cid=101 仅 1 chat / 1 conv（开发测试痕迹）。

### 2.5 default 用户当前实际 active cid？

由证据三角对账：

- WS 路径下 active 角色由前端在每个消息里携带（无单一"default 当前角色"DB 字段）
- 但 `chat_history` 实际数据：default 用户 15 条记录全在 cid=1（最近一条 2026-05-18）
- `conversations` 表 default 用户 21 个对话，几乎全 cid=1
- 启动恢复路径 `main.py:411-456` 按 `chat_history.character_id distinct` 重建短期记忆，default 用户实际还原的就是 cid=1 bucket

→ **default 用户实际指向 cid=1**（即"Momo 壳 + Mai persona"）。

### 2.6 cid=1 vs cid=101 vs "樱岛麻衣"的真实关系

| 维度 | cid=1（Momo） | cid=101（樱岛麻衣） |
|---|---|---|
| `characters.name`（UI 壳） | Momo | 樱岛麻衣 |
| `character_personas.identity.name`（LLM 魂） | **樱岛麻衣** | 樱岛麻衣 |
| `characters.persona` 列（legacy） | 302 字（yaml 默认 ChatAgent） | 5541 字（Mai 长 prompt 原文） |
| `character_personas.personality_core` 长 | **263 字（真骨肉）** | 89 字（骨架） |
| Live2D | hiyori | hiyori |
| Voice tts_language | zh | ja |
| 实际聊天记录 | 15 chat / 21 conv（活跃） | 1 chat / 1 conv（停滞） |

**真相**：
- cid=1 = "Momo 壳 + Mai 魂"（X.8 借壳）—— **当前真正在用**的 Mai；voice 已按 Z.8 改纯中文
- cid=101 = "独立 Mai 角色（日语 voice 模式）" —— **预备但未启用**；`characters.persona` 列里有 Mai 长 prompt 原文（看似初版用 `characters.persona` 实现，后改走 `character_personas` 多 variant 后这个 5541 字旧实现就被绕过了，character_personas 那条只剩 89 字骨架）
- cid=101 既不是测试残留也不是正式角色 —— 是**架构迁移过程中遗留的中间态**

### 2.7 "cid 现状表"（供一句话定退役/保留/重命名）

| cid | 当前角色 | 数据完整度 | 实际使用 | 建议方向 | 理由 |
|---|---|---|---|---|---|
| 1 | Momo 壳 + Mai 魂 | ✅ 完整 | ✅ 活跃 | 保留，是 default 主角 | X.8 借壳活跃中 |
| 2 | 八重神子（yae live2d） | 🟡 空骨架 persona | 1 chat 痕迹 | 保留，待 v4.1 灌 persona | yae live2d 真就位是亮点 |
| 3 | 荧 | 🟡 空骨架 + splash | 1 chat 痕迹 | 保留，待 v4.1 | |
| 4 | 凝光 | 🟡 空骨架 | 0 | 保留或暂时下线 | 无 splash 无 voice 无 live2d |
| 5 | 神里绫华 | 🟡 空骨架 + voice | 0 | 保留，待 v4.1 | 有 voice_model |
| 99 | 一般路过猫娘 | 🟡 空骨架 + splash | 0 | 待裁决 | 名字非 Genshin/Sakuta 系，孤儿设定 |
| 100 | 祥子-test | 🔴 名字含 `-test` | 0 | **建议清** | 明显测试残留 |
| **101** | 樱岛麻衣（独立 ja 模式） | 🟡 旧 persona 列有内容但被新架构绕过 | 1 chat 痕迹 | **建议拍板**：① 退役（cid=1 已实现 Mai）；② 改名"樱岛麻衣（日语版）"+ 灌真 persona variant 当 v4.1 ja 链路目标；③ 直接合并到 cid=1 | 架构迁移中间态，名实漂移源头 |
| 102 | 流萤 | 🟡 空骨架 + splash | 0 | 待裁决 | AUDIT 后新增，未在任何文档登记计划 |

---

## 第 3 节 · 悬而未核的发现（一次性查清）

### 3.1 M-6：ChatHistoryDrawer / 浮现台词气泡残留 — **PASS（名实相符）**

| 检查项 | 真值 |
|---|---|
| `find frontend/src -name "ChatHistoryDrawer*"` | **空**（文件已删） |
| `find frontend/src -name "CharacterDialogueBubble*"` | **空**（文件已删） |
| `grep ChatHistoryDrawer` | 仅 2 处命中，全是**注释引用** 描述删除决策：`Panel.tsx:74-78`（删除决策注释）+ `ChatHistoryPanel.tsx:5`（"取代 ChatHistoryDrawer"） |
| 替代组件 | `ChatHistoryPanel.tsx`（右侧固定栏，audit_chat_panel 方案 1） |

→ DESIGN §Z.4 叙述 **名实相符** ✅。可关闭。

### 3.2 L-6：SHORT_TERM_MAX / tool_result 截断真值 — **PASS（值与文档一致）**

| 常量 | 文件:行 | 真值 | DESIGN §Z.6 文档号称 |
|---|---|---|---|
| `SHORT_TERM_MAX_TURNS` | `memory/short_term.py:40` | **30** turns | "硬性 cap 最近 30 turn" ✅ |
| `SHORT_TERM_MAX`（messages） | `memory/short_term.py:44` | **60** = 30 × 2 | （隐含） ✅ |
| `TOOL_RESULT_MAX_CHARS` | `agents/chat.py:905` | **4000** chars | "tool_result 注入截断到 4000 字符" ✅ |

注：`short_term.py:9` 注释提到 "SHORT_TERM_MAX 是 dead constant" —— 是描述**修法 A 之前**的旧版状态，现版本（修法 A 后）trim 已 enforce on every `.add()`（L79-87）。注释本身陈旧，可视为 RT-low 文档欠债。

### 3.3 L-7：voice_samples 是否真在 LLM prompt 注入路径 — **PASS（真注入）**

| 检查 | 文件:行 | 真值 |
|---|---|---|
| 模型字段 | `database/models.py:104` `voice_samples = Column(Text, nullable=False)` | NOT NULL 必填 |
| persona dataclass | `agents/prompt/persona_loader.py:37` `voice_samples: List[Dict[str, Any]]` | 加载到运行时 |
| **注入点 1** | `agents/prompt/renderer.py:228-236` | `_filter_samples_by_tolerance(persona.voice_samples or [], _tolerance)` —— **真在 renderer 中被 cliche_tolerance 滑块过滤后注入 prompt** |
| 注入点 2 | `agents/prompt/renderer.py:141-145` `filtered_samples = persona.voice_samples or []` | 默认全集路径 |

→ X.5 描述的 "voice_samples tolerance_range filter（运行时风格滑块）" 真活在 renderer。可关闭。

### 3.4 L-8：cid=1 voice_model JSON 真值 — **PASS（Z.8 真落地）**

```
SELECT id, json_extract(voice_model,'$.provider'),
            json_extract(voice_model,'$.voice'),
            json_extract(voice_model,'$.tts_language')
FROM characters WHERE id=1;

→ 1 | cosyvoice | longyumi_v3 | zh
```

DESIGN §Z.8 修订记录："`tts_language` `'ja'` → `'zh'`；`voice` 复刻日语 voice → 中文音色 `longyumi_v3`" — **真落地**。可关闭。

附：cid=101 仍是 `cosyvoice / cosyvoice-v3.5-plus-bailian-…a19f52 / tts_language=ja` —— 保留 ja 链路（Z.8 修订只动 cid=1）。

### 3.5 M-7 / L-12：测试残留真实计数 — **复核**

| 表 | AUDIT §1.1 写的 | 实测当前 | 差异 |
|---|---|---|---|
| `users` 总行 | 19 (1 default + 18 测试) | **19**（1 default + 18 测试） | 一致 |
| `memory` 总行 | 9（default 0 行） | **11**（default 2 行 + 9 测试） | **+2** = B 路调试中通过 chat 自然累积的 id=14/15 default 用户行（NULL cid）。AUDIT 写时尚未真机回归。 |
| `pending_briefings` 总行 | 234（default 0） | **234**（default **23** + 211 测试） | AUDIT 把 default 计为 0 **不准确** —— 实测 default 名下 23 行（2026-05-07 ~ 2026-05-14） |
| `character_states` 总行 | 20 | **21**（9 真 + 12 孤儿 cid） | +1 = cid=102 流萤新增 |
| `chat_history` 总行 | 8 | **15** | +7 = 本轮 B 路调试 + 真机回归累积 |

孤儿 character_states cid 清单：**300, 301, 302, 303, 304, 305, 306, 400, 500, 600, 601, 700** — 全部不在 `characters` 表中，FK 悬挂。

### 3.6 prompt_manager DEPRECATED 标注但仍被调用 — **复核**

`prompt_manager.py:3` docstring 标 "⚠️ DEPRECATED — v4 persona engineering segment 1 supersedes this module"。实际仍被调用的点：

| # | 调用点 | 用途 | 是否真活？ |
|---|---|---|---|
| 1 | `tools/builtin.py:12,22` switch_character LLM tool | 调 `prompt_manager.switch_character` | ✅ 活（但语义已坏，仅认 yaml 5 名） |
| 2 | `agents/chat.py:50,1335` | renderer 失败时 fallback `prompt_manager.get_prompt(user_id)` | ✅ 活（兜底，正常 renderer 路径不走这里） |
| 3 | `routes/ws.py:60,932` `prompt_manager.get_current_character` | dead var，无下游消费 | ❌ dead（var 从未被读） |

→ **砍 switch_character LLM tool 后，#1 完全清除**。#2 仍需保留（兜底），#3 可顺手清也可暂留。`prompt_manager` 模块**仍不能整删**（#2 仍依赖）。

`prompt_manager` 的真退役需要 Plan C（全 DB persona，删 characters.yaml）一并做。当前 Plan B 现行 → `prompt_manager` 仍承担 yaml fallback 职责。

---

## 第 4 节 · 调研结论汇总

### 4.1 砍 switch_character 的安全改法（最小到充分）

**一句话**：删 `backend/tools/registry.py:95` 这一行 `ToolRegistry.register("switch_character", ...)` 即可让 LLM 立刻不再看见 / 不再调这个工具，且不影响前端切角色 / proactive / 初始化任何路径。

**最小安全改动**（1 处）：
- `backend/tools/registry.py:95` — 删除注册一行

**充分清理**（4 处，建议一起）：
- 上面那 1 处 +
- `backend/config/prompts.py:117` — 从 `BASE_INSTRUCTION` 删 switch_character 说明
- `backend/config/prompts.py:227` — tool 列表项删
- `backend/agents/prompt/tool_addendum.py:37-38` — 删 "【系统类】switch_character / clear_short_term..."（注意 `clear_short_term` 仍要保留为 LLM tool，本句要重写而非全删）

**彻底删函数本体**（可选，2 处）：
- `backend/tools/builtin.py:16-25` + `49-71` — 删 `switch_character` async 函数 + SCHEMA
- `backend/tools/registry.py:89` — import 改 `from backend.tools.builtin import (clear_short_term, ...)`（去掉 switch_character）

**注意保留**：
- `backend/config/prompt_manager.py` 整模块 — `chat.py:1335` 仍依赖 `get_prompt` 作为 renderer 失败兜底
- `backend/routes/ws.py:932` dead var — 可顺手清也可暂留，与 switch_character 无强耦合

### 4.2 cid 现状表 + 命名梳理建议（CC 给依据，最终由人定）

| cid | 当前状态一句话 | 建议方向（待你拍板） |
|---|---|---|
| 1 | Momo 壳 + Mai 魂，default 主角 | 保留，是核心 |
| 2 | 八重神子 + yae live2d，空骨架 | 保留，等 v4.1 灌 persona |
| 3 / 4 / 5 | Genshin 角色，空骨架 | 保留或暂下线 |
| 99 | 一般路过猫娘，孤儿设定 | 待拍板（删 / 改名 / 灌内容） |
| 100 | 祥子-test，明显测试残留 | **建议清** |
| **101** | 樱岛麻衣独立 ja 模式，架构迁移中间态 | **关键拍板**：① 退役（合并到 cid=1）；② 改名"麻衣（日语版）"作为 v4.1 ja 链路目标；③ 删 |
| 102 | 流萤，AUDIT 后新增 | 待拍板（正式角色 / 测试 / 哪个版本灌 persona） |

**孤儿 character_states cid 300/301/302/303/304/305/306/400/500/600/601/700** — `characters` 表无对应行的 12 条状态记录，可在测试残留清理批次一并删。

### 4.3 第 3 节各项 PASS/FAIL/真值汇总

| # | 项 | 结果 | 真值 / 备注 |
|---|---|---|---|
| 3.1 | M-6 ChatHistoryDrawer 残留 | **PASS** | 组件文件已删；2 处 grep 命中均为注释 |
| 3.2 | L-6 SHORT_TERM_MAX / tool_result 截断 | **PASS** | 30 turns（60 messages）/ 4000 chars，与 §Z.6 一致 |
| 3.3 | L-7 voice_samples 在 LLM prompt 注入 | **PASS** | `renderer.py:228-236` 真注入（按 cliche_tolerance 过滤后） |
| 3.4 | L-8 cid=1 voice_model 真值 | **PASS** | `cosyvoice / longyumi_v3 / zh` 与 §Z.8 修订一致 |
| 3.5 | M-7 测试残留计数复核 | **AUDIT 部分不准** | pending_briefings.default 实测 23 行（AUDIT 写 0）；其余有自然 drift；孤儿 12 cid 列出 |
| 3.6 | prompt_manager DEPRECATED 但仍被用 | **可部分清** | 砍 switch_character LLM tool 解 #1；#2 chat.py 兜底必留；#3 ws.py dead var 可顺手清 |

### 4.4 可关闭归档 / 仍需后续动作

**可直接关闭**（已 PASS，无后续动作）：
- M-6 前端 ChatHistoryDrawer 残留核 ✅
- L-6 SHORT_TERM_MAX 与 tool_result 截断常量值 ✅
- L-7 voice_samples LLM prompt 路径 ✅
- L-8 cid=1 voice_model JSON 真值 ✅

**仍需后续动作**：
- **H-1 砍 switch_character LLM tool** — §4.1 已给最小/充分/彻底三档改法；下一步发实施 prompt
- **H-2 cid 命名梳理** — §4.2 表格已给现状 + 方向；下一步需要用户**一句话定 cid=101 / cid=99 / cid=100 / cid=102 的去留**
- **M-7 测试残留清理** — `pending_briefings` 211 行测试 + `character_states` 12 孤儿 + `users` 18 测试 uid + `memory` 9 测试行 + `chat_history` 测试行；需先决定 forensic 保留策略
- **AUDIT-GROUND-TRUTH 局部更新** — pending_briefings.default 实测 23 行（AUDIT 写 0 不准）；character_states 21 行（AUDIT 写 20）；memory / chat_history 行数自然 drift

---

## 边界声明

- 本文件**只读盘点**：未改任何代码 / DB / migration / commit / stash / push / backend 未启动
- DB 查询全部为 `SELECT` / `.schema` / `.tables`，无 `INSERT/UPDATE/DELETE/CREATE/DROP/ATTACH`
- 任何"建议方向"是依据给定不替决，最终拍板由人

---

## 【第一刀 · switch_character 充分档 + 孤儿核实 · 2026-05-19 00:49】

### 前置自检

- `git status --porcelain`：仅 `config.yaml`（豁免）+ docs 系列 untracked + 各 splash-art / db.backup untracked，无新意外
- `git stash list`：`stash@{0}: On main: park: 个人config+调试桩(memsum刀前)` 未动
- HEAD = `eaa9330` (Problem B)
- B 路 4 文件已 commit，不在 M 列表中

### A · 砍 switch_character（充分档，3 处改代码）

#### A1 — `backend/tools/registry.py:95` 删工具注册

```diff
@@ -92,5 +92,8 @@ from backend.tools.builtin import (  # noqa: E402
     CLEAR_SHORT_TERM_SCHEMA,
 )

-ToolRegistry.register("switch_character", switch_character, SWITCH_CHARACTER_SCHEMA)
+#: switch_character LLM tool 已下线 — yaml-only 校验源仅认 5 个角色，DB 中
+#: cid=1/99/100/101/102 切不动 (silent failure)。前端 UI 切角色走 WS frame
+#: type="character_switch" → connection_manager.set_current,不依赖此 tool。
+#: 函数本体 + schema 暂留 backend/tools/builtin.py 不动，仅停止 LLM 暴露。
 ToolRegistry.register("clear_short_term", clear_short_term, CLEAR_SHORT_TERM_SCHEMA)
```

→ `SWITCH_CHARACTER_SCHEMA` 不再注入 ToolRegistry → LLM 看不到此 tool → 不会主动调。

#### A2 — `backend/config/prompts.py` 删 PLANNER_AGENT_SYSPROMPT 中 switch_character 引导

```diff
@@ -113,8 +113,7 @@ personality 表字段：...
 - search_memory(...)

-· ToolAgent：用于执行即时动作，如控制应用程序、切换角色。
-- switch_character(user_id, character_id): 切换角色，支持 '默认'、'八重神子'、'神里绫华'、'凝光'、'荧'
+· ToolAgent：用于执行即时动作，如控制应用程序。
 - clear_short_term(user_id): 清空短期记忆
```

→ 「ToolAgent 职责描述」内删去"切换角色"措辞；删函数行；保留 `clear_short_term`。

#### A2 — `backend/config/prompts.py` 删 example7 整段（switch_character 调用示例）+ 重编号 example8→example7

```diff
@@ -217,23 +216,7 @@ PLANNER_AGENT_FEW_SHOT: str = """
     }
 ]

-例子7 — 切换角色
-输入：请切换角色至八重神子
-输出：
-[
-    {
-        "agent": "ToolAgent",
-        "payload": {
-            "function": "switch_character",
-            "args": {
-                "user_id": "实际用户id",
-                "character_id": "八重神子"
-            }
-        }
-    }
-]
-
-例子8 — 清空短期记忆
+例子7 — 清空短期记忆
 输入：清空我刚才的聊天记录
```

→ 删整个示例 7 + 重命名旧示例 8 为 7（保持连续编号）。

注：PlannerAgent / MemoryAgent / ToolAgent 已在 v3-C 退出主聊天流程（`ws.py:7-12 / 172` 注释明示），但这些 prompts 仍可能被 `agents/planner.py` 调用，按命令清理。

#### A2 — `backend/agents/prompt/tool_addendum.py` 删【系统类】switch_character 引导

```diff
@@ -34,8 +34,7 @@ TOOL_PROMPT_ADDENDUM = (
     "  - 当用户要求忘掉某事，先 list_memories 找匹配再 delete_memory；\n"
     "  - 当用户要求整理记忆，调 compress_memories。\n\n"
-    "【系统类】switch_character / clear_short_term：\n"
-    "  - 仅当用户明确要求切换角色时调 switch_character；\n"
+    "【系统类】clear_short_term：\n"
     "  - 仅当用户明确要求清空当前对话上下文时调 clear_short_term。\n\n"
```

→ 这段是 ChatAgent 主聊天 LLM 的 prompt 增量；删 switch_character 引导，保留 `clear_short_term`。

#### A3 — 未动项（按指令）

| 项 | 文件:行 | 状态 |
|---|---|---|
| `switch_character` 函数本体 | `backend/tools/builtin.py:16-25` | 保留 |
| `SWITCH_CHARACTER_SCHEMA` 常量 | `backend/tools/builtin.py:49-71` | 保留 |
| `registry.py:89` import 行 | `from backend.tools.builtin import (..., switch_character, SWITCH_CHARACTER_SCHEMA, ...)` | 保留 |
| `prompt_manager` 模块整体 | `backend/config/prompt_manager.py` | **必须保留** —— `chat.py:1335` 仍依赖 `get_prompt` 作为 renderer 失败兜底 |
| `chat.py:1335` fallback | `prompt_manager.get_prompt(user_id)` 调用 | 保留 |
| `ws.py:932` dead var | `character = prompt_manager.get_current_character(user_id)` | 保留 |
| 前端 `character_switch` WS 帧路径 | `ws.py:824-838 / 1343-1370` | 保留 |

#### A4 — diff 全文 + git status

`git status --porcelain | grep M`：

```
 M backend/agents/prompt/tool_addendum.py    ← 本刀新增 M
 M backend/config/prompts.py                  ← 本刀新增 M
 M backend/tools/registry.py                  ← 本刀新增 M
 M config.yaml                                ← 既有豁免件
```

新增 M 恰好 3 个 = A1 + A2(2 处同文件) + A2c。无多余文件。

剩余 `switch_character` 字面 grep（全部按 A3 保留，**零 LLM 暴露面**）：

```
backend/tools/builtin.py:16,22,52    — 函数本体 + SCHEMA + name 字段（A3 保留）
backend/tools/registry.py:14         — docstring 调用示例（注释，非 LLM 暴露）
backend/tools/registry.py:89         — import（A3 保留）
backend/tools/registry.py:95         — 本刀替换为注释，已无 register 调用
backend/config/prompt_manager.py:7,8,17,92,99,104  — 模块自身实现（A3 保留）
backend/agents/chat.py:1315          — fallback 路径注释（非 LLM 暴露）
```

零 `ToolRegistry.register("switch_character", ...)` 调用；零 prompt 文本告诉 LLM 此 tool 存在 → LLM 从此不会被引导调用此工具，silent failure 源头消除。

### B · 12 孤儿 character_states 只读核实

12 个孤儿 cid（`character_states` 表中存在，但 `characters` 表无对应行）：**300, 301, 302, 303, 304, 305, 306, 400, 500, 600, 601, 700**

#### B1 — 代码字面 grep（数值字面 / character_id 引用）

```
$ grep -rnE "character_id\s*[=:]\s*${cid}([^0-9]|$)|\"id\"\s*:\s*${cid}([^0-9]|$)" backend/ frontend/src/  for each cid

cid=300/301/302/303/305/306/400/500/600/601/700  → 零命中
cid=304                                            → 1 命中: backend/agents/prompt/renderer.py:47（仅注释）
```

`renderer.py:47` 实读：
```python
# 防御性:degenerate thought(全单字符重复,如 60 个 x)直接 None,避免脏数
# 据原文进 prompt。Phase 0 audit §0.3 实测 character_id=304 的 thought
# 就是 60 个 'x',D-3 sign-off 把孤儿清理留 v4.1,本侧只保护 prompt 不被
# 污染。
_DEGENERATE_THOUGHT_RE = re.compile(r"^(.)\1{10,}$")
```

→ 是**纯历史 audit 注释**（D-3 sign-off 已声明"留 v4.1 清理"）；regex 是通用防御，**不依赖 cid=304 这一行存在**，删除 cid=304 后 regex 仍照常保护任何 degenerate thought。

#### B1 — character_states 全代码消费者扫描

| 文件:行 | 操作 | 是否会触及孤儿 cid？ |
|---|---|---|
| `services.py:646-665` `get_character_state(cid)` | 给定 cid 查 row | 仅在外部传入 cid 时触；外部传入的 cid 都来自 `characters` 表（DB 主键），孤儿 cid 不会被外部传入 |
| `services.py:670-... ` `update_character_state(cid, ...)` | upsert | 同上 |
| `services.py:758-765` `list_state_character_ids()` | 枚举 `character_states.character_id` | ⚠️ **会枚举到孤儿 cid**，被 `intimacy_decay` cron 调 |
| `services.py:750-754` `list_all_character_ids()` | 枚举 `characters.id` | 只返 9 个真 cid，**不含孤儿** |
| `capabilities/character_state.py:158-179` `intimacy_decay` cron | 每天 0:00 跑：遍历 `list_state_character_ids` 结果，对每个 cid 跑 `get_or_create_character_state` + 若 intimacy>0 则 -1 | **会触 12 个孤儿** —— 但都是 idempotent SELECT + 可能的 intimacy decrement，**不会因为 cid 不在 characters 表而 crash**（intimacy_decay 不做 FK lookup） |

#### B2 — 12 孤儿行 SELECT 全字段真值

```
cid | intimacy | activity | thought              | updated_at
300 | 0        | 在看书   | 觉得用户今天很努力   | 2026-05-13 15:00:00
301 | 0        | (空)     | (空)                  | 2026-05-12 05:39:21
302 | 0        | (空)     | (空)                  | 2026-05-12 05:39:21
303 | 0        | (空)     | (空)                  | 2026-05-12 05:39:21
304 | 0        | (空)     | xxxxxxxxxxxxxxxxxxxxxxxxxxxxxx | 2026-05-08 00:30:03
305 | 0        | (空)     | (空)                  | 2026-05-08 00:30:03
306 | 0        | 在烤面包 | 想做点新的尝试         | 2026-05-08 00:30:09
400 | 49 ⚠️    | (空)     | (空)                  | 2026-05-16 15:00:00
500 | 0        | (空)     | (空)                  | 2026-05-12 05:39:21
600 | 0        | (空)     | (空)                  | 2026-05-08 00:32:31
601 | 0        | (空)     | (空)                  | 2026-05-12 05:39:44
700 | 0        | (空)     | (空)                  | 2026-05-12 05:39:21
```

时间戳特征：
- cid=304 / 305 / 306 / 600：updated_at = 2026-05-08，最早一批
- cid=301 / 302 / 303 / 500 / 601 / 700：updated_at = 2026-05-12
- cid=300：2026-05-13
- cid=400：2026-05-16（intimacy=49 显著高于其它，明显是测试场景留的高亲密度值）

12 行 updated_at 跨度 2026-05-08 ~ 2026-05-16，集中在最近的测试/调试期；与 DB 中真 character 1/2/3/4/5/99/100/101 的 cid 编号体系明显不同（真角色用 1-5/99-102 小整数，孤儿用 300+/400+/500+/600+/700 整百段，强测试 fixture 命名签名）。

#### B3 — FK / 外键依赖确认

```
$ sqlite3 momoos.db ".schema" | grep -iE "REFERENCES character_states|character_states\("
（空 — 无任何表 REFERENCES character_states）
```

`character_states` schema 内部：
- `PRIMARY KEY (id)` — 自身主键
- `UNIQUE (character_id)` — 业务唯一性约束
- `character_id INTEGER NOT NULL` — **没有 `REFERENCES characters(id)` FK 约束**（schema 实测）

→ 删 12 行孤儿不会触发任何级联 / 反向引用断裂。

#### B3 — sibling 表对这 12 个 cid 的引用

```
chat_history WHERE character_id IN (12 orphans)      → 0 行
conversations WHERE character_id IN (12 orphans)     → 0 行
character_personas WHERE character_id IN (12 orphans)→ 0 行
pending_briefings WHERE character_id IN (12 orphans) → 0 行
memory WHERE character_id IN (12 orphans)            → 0 行
characters WHERE id IN (12 orphans)                  → 0 行（确认孤儿）
```

**完全孤立**：12 行只存在于 `character_states` 一处，无任何 sibling 表引用。

#### B4 — 结论：12 行确证零活消费者 + 可安全删

| 检查项 | 真值 |
|---|---|
| 代码字面 grep | 11 个 cid 零命中；1 个 cid（304）仅在注释中作为历史 audit 痕迹，不影响代码逻辑 |
| `list_state_character_ids` 枚举触及 | ✅ 会枚举到，但 `intimacy_decay` 处理 idempotent + 不依赖 FK，删后只是 cron 少走 12 个 SELECT |
| 反向 FK 引用 | 零（schema 实测无 `REFERENCES character_states`） |
| 出向 FK 约束 | 零（`character_id` 列无 `REFERENCES characters(id)`，所以孤儿能存在） |
| sibling 表（5 张关键表）引用 | 全部 0 行 |
| 官方文档定性 | `v4_persona_thickening_segment1.py:27` D-3 sign-off 注释明示"12 行 character_states 孤儿行不在本 segment 处理，**留 v4.1 清理**" —— 已是官方设计目标的清理对象 |

**12 行全部归为"零活消费者 + 已设计为 v4.1 清理目标"**。无任何单独存疑行。

删除影响（如顾问批准进第二刀）：
- 行数变化：character_states 21 → 9（与 `characters` 表行数对齐）
- intimacy_decay cron 加速：少走 12 次 SELECT（含 cid=400 的真 intimacy decrement）
- renderer.py:47 注释保留（描述历史 audit，与 row 是否存在无关）
- 零代码改动

#### B5 — 全程禁项遵守

零 DELETE / 零 UPDATE / 零 INSERT / 零 schema 变更 / 零 cron 触发。仅 SELECT + grep。

### 第一刀状态汇总

| 部分 | 改动 | 已落地？ | 待顾问决策 |
|---|---|---|---|
| A1 工具注册删 | `registry.py:95` | ✅ 代码已改 | 是否 commit |
| A2 三处 prompt 引导删 | `prompts.py / tool_addendum.py` | ✅ 代码已改 | 是否 commit |
| A3 不动项 | 函数本体 / import / prompt_manager / dead var | ✅ 全部保留 | — |
| B 孤儿核实 | 12 行确证零活 + 已是 v4.1 清理目标 | ✅ 调研完 | 是否进第二刀（DELETE 12 行） |

零 commit / 零 push / 零 stash / 零 DB 改动 / 零 backend 启动。

### 暂停

等顾问核 A 的 diff + B 的核实结论。A 决定是否 commit；B 决定是否进第二刀（DELETE 12 孤儿行）。

---

## 【第二刀 · 删 12 孤儿 character_states · 2026-05-19 01:03】

### 前置自检

- `git status --porcelain | grep M`：仅 `M config.yaml`（豁免）。第一刀 commit `71b6e99` 后无新代码 M
- `git stash list`：`stash@{0}` 未动
- HEAD = `71b6e99 refactor(character): 下线 switch_character LLM tool（充分档）`

### 本刀新备份

```
-rw-r--r--  1 liujunhong  staff  700416  5月 19 01:03
  /Users/liujunhong/Desktop/MomoOS-v2/momoos.db.backup_orphan_20260519_010303
```
700 416 B，与原 DB 等大。

### 步骤 1 — 删除前 12 孤儿快照（只读）

```
cid | intimacy | activity     | updated_at
300 | 0        | 在看书       | 2026-05-13 15:00:00
301 | 0        | (NULL)       | 2026-05-12 05:39:21
302 | 0        | (NULL)       | 2026-05-12 05:39:21
303 | 0        | (NULL)       | 2026-05-12 05:39:21
304 | 0        | (NULL)       | 2026-05-08 00:30:03
305 | 0        | (NULL)       | 2026-05-08 00:30:03
306 | 0        | 在烤面包     | 2026-05-08 00:30:09
400 | 49 ⚠️    | (NULL)       | 2026-05-16 15:00:00
500 | 0        | (NULL)       | 2026-05-12 05:39:21
600 | 0        | (NULL)       | 2026-05-08 00:32:31
601 | 0        | (NULL)       | 2026-05-12 05:39:44
700 | 0        | (NULL)       | 2026-05-12 05:39:21
```
正好 12 行，与调研 B2 真值完全一致（intimacy=49 cid=400、活动文本"在看书"/"在烤面包"、时间戳分布全部对得上）。

### 步骤 2 — 删除前总数

```
SELECT COUNT(*) FROM character_states → 21
```
符合 AUDIT/INVESTIGATION 复核结论。

### 步骤 3 — 精确 DELETE

```sql
DELETE FROM character_states
WHERE character_id IN (300,301,302,303,304,305,306,400,500,600,601,700);
SELECT changes(); → 12
```

`changes()=12` **精确等于**孤儿数量，无超删 / 无欠删。

### 步骤 4 — 删除后核验

| 检查项 | 实测 | 预期 | 结果 |
|---|---|---|---|
| `SELECT COUNT(*) FROM character_states` | **9** | 9 | ✅ |
| 剩余 cid 集合 | `{1, 2, 3, 4, 5, 99, 100, 101, 102}` | 与 `characters.id` 集合完全对齐 | ✅ |
| `characters.id` 集合 | `{1, 2, 3, 4, 5, 99, 100, 101, 102}` | — | 一致 |
| `chat_history` WHERE cid ∈ 12 孤儿 | 0 | 0（删前本就 0） | ✅ 无误伤 |
| `conversations` WHERE cid ∈ 12 孤儿 | 0 | 0 | ✅ 无误伤 |
| `memory` WHERE cid ∈ 12 孤儿 | 0 | 0 | ✅ 无误伤 |
| `character_personas` WHERE cid ∈ 12 孤儿 | 0 | 0 | ✅ 无误伤 |
| `pending_briefings` WHERE cid ∈ 12 孤儿 | 0 | 0 | ✅ 无误伤 |
| `character_states` 残余孤儿 cid | 0 | 0 | ✅ 干净 |

### 步骤 5 — 全表对账（只动 character_states，其它零变化）

| 表 | 删除前 | 删除后 | 变化 |
|---|---|---|---|
| characters | 9 | 9 | 0 |
| chat_history | 15 | 15 | 0 |
| conversations | 24 | 24 | 0 |
| memory | 11 | 11 | 0 |
| character_personas | 9 | 9 | 0 |
| pending_briefings | 234 | 234 | 0 |
| users | 19 | 19 | 0 |
| **character_states** | **21** | **9** | **-12** ✅ |

→ 仅 `character_states` 一张表减少 12 行，其它 7 张表零变化。

### 9 个真 cid state 完整保留（抽查）

```
cid | intimacy | activity         | updated_at
1   | 45       | 看书             | 2026-05-18 03:26:50  ← default 用户主角，亲密度真值
2   | 4        | 看着屏幕轻笑     | 2026-05-16 15:00:00
3   | 0        | 靠在沙发上看你   | 2026-05-15 15:35:35
4   | 0        | (NULL)           | 2026-05-08 00:30:09
5   | 0        | (NULL)           | 2026-05-11 10:41:31
99  | 0        | (NULL)           | 2026-05-08 00:30:09
100 | 0        | (NULL)           | 2026-05-10 19:55:23
101 | 1        | 看书             | 2026-05-16 15:00:00
102 | 0        | (NULL)           | 2026-05-18 03:28:00  ← AUDIT 后新增
```

cid=1 intimacy=45（default 用户与 Momo/Mai 累计亲密度）+ cid=2 八重 intimacy=4 等真值**完全保留**未触。

### 第二刀状态

- DB 变化：仅 `character_states` 表减少 12 行；schema 未动；其它 7 张表零变化
- 代码改动：零
- 备份：`momoos.db.backup_orphan_20260519_010303`（700 416 B）就位，DELETE 可逆
- 禁项遵守：零代码改 / 零 schema 改 / 零 commit / 零 push / 零 stash 动作 / 零 backend 启动
- `intimacy_decay` cron 副效益：下次 0:00 跑时遍历对象从 21 个缩到 9 个，无浪费的孤儿 SELECT

### 暂停

12 孤儿行全清，character_states 与 characters 表对齐。等顾问核 DB 真值。

---

## 【LLM prompt token 分块账单 · 2026-05-19 05:16】

只读诊断；offline 重建（未启动 backend、未实发 LLM 请求、临时测量脚本测完已撤）；未改任何代码 / DB / commit / stash。tokenizer = `litellm.token_counter(model='qwen3.6-max-preview')`（内部 fallback 到 `tiktoken cl100k_base`；对中文存在 ~20-30% 高估，作为 first-order 诊断够用）。

### 1. 拼装点定位

**主路径**：`backend/agents/chat.py:_build_messages` (L1105-1500+)。最终 LLM 请求由 4 段组成：

```
[1] system_prompt  (L1455: "\n\n".join(system_parts))
[2] conversation_summary  (L1464-1471 滚动摘要,可选,独立 system 块)
[3] short_term 历史 turns  (按 (user, character, conversation) 三级过滤)
[4] 当前用户输入  (text)
+ tools= 参数  (L1614 _get_all_tools() = MEMORY_TOOLS + ToolRegistry.list_schemas())
```

**system_parts 拼装顺序**（L1370-1453 实读）：

```
head_parts (join with \n\n):
  emotion_inst           ← <emotion> 标签格式说明
  thinking_inst          ← <thinking> 内心独白格式说明
  motion_inst            ← <motion> 动作格式说明
  state_inst             ← <state_update> 标签 + 当前角色状态
  (config base_instruction, 可空)
  persona_block          ← characters.persona + BASE_INSTRUCTION + _TOOL_PROMPT_ADDENDUM
  _TOOL_BEHAVIOR_BLOCK   ← 过渡语行为规范

then system_parts.append (按序):
  format_profile_for_prompt(profile_data)             ← 用户画像 (chunk 11)
  format_today_activity_for_prompt(user_id)           ← 活动时间线 (chunk 14)
  "【相关长期记忆】\n" + memory_top5                    ← long-term recall
  "【工具调用结果】..." (rare)                          ← legacy MemoryAgent path
  "【临时指令】..." (touch event etc)
  "【proactive 简报】..." (stage 2 only)
```

### 2. 三场景分块账单（真值）

数据源：default 用户 cid=1（Mai 借壳）现状 DB。

#### Scenario A — 冷启动后第 1 句简单对话（无工具调用）

| 块 | tokens | 占比 | 上限 / 膨胀 |
|---|---:|---:|---|
| `[head] emotion_inst` | 105 | 0.6% | 固定 |
| `[head] thinking_inst` | 182 | 1.1% | 固定 |
| `[head] motion_inst` | 354 | 2.2% | 固定 |
| `[head] state_inst` | 405 | 2.5% | 固定 |
| `[head] characters.persona col (Mai)` | 341 | 2.1% | 固定/角色切则换 |
| `[head] BASE_INSTRUCTION` | 180 | 1.1% | 固定 |
| `[head] TOOL_PROMPT_ADDENDUM` | **3,189** | **19.7%** | 固定 ⚠️ 大 |
| `[head] TOOL_BEHAVIOR_BLOCK` | 251 | 1.5% | 固定 |
| **HEAD 小计** | **5,007** | **30.9%** | 固定 |
| `[body] profile (chunk 11)` | 63 | 0.4% | 字段满后约 100-200 cap |
| `[body] activity_timeline` | 0 | 0% | 当日累计 ≥60s 后 ~100-500（top-5 app） |
| `[body] memory recall top-5` | 0 | 0% | 上限 top-5，~150 |
| **SYSTEM PROMPT 总** | **5,070** | **31.3%** | — |
| `[msg] conversation_summary` | 0 | 0% | 未触发 |
| `[msg] history` | 1 | 0% | 0 turn |
| `[msg] 当前 user 输入` | 2 | 0% | "你好" |
| `[tools=] 全部 tool schemas (58)` | **11,150** | **68.7%** | 固定 ⚠️ 巨 |
| **GRAND TOTAL** | **16,223** | **100%** | — |

#### Scenario B — 聊 15+ 轮（18 条历史 msg）

| 块 | tokens | 占比 | 上限 / 膨胀 |
|---|---:|---:|---|
| HEAD 小计 | 5,007 | 28.7% | 同 A |
| `[body] profile` | 63 | 0.4% | — |
| `[body] activity_timeline` | 0 | 0% | 今日 DB 空（真用户活动较少） |
| `[body] memory recall top-5` | 59 | 0.3% | 当前 default 仅 2 行 NULL memory |
| SYSTEM PROMPT 总 | 5,130 | 29.4% | — |
| `[msg] conversation_summary` | 0 | 0% | 滚动摘要为空（未达 trigger） |
| `[msg] history (18 msg)` | **1,130** | **6.5%** | **每轮 ~63 tokens；线性膨胀** ⚠️ |
| `[msg] 当前 user 输入` | 24 | 0.1% | — |
| `[tools=] 全部 tool schemas (58)` | **11,150** | **64.0%** | 固定 ⚠️ 巨 |
| **GRAND TOTAL** | **17,434** | **100%** | A→B 净增 **+1,211** |

#### Scenario C — 工具调用一来回（time.now + 历史 10 msg）

| 块 | tokens | 占比 | 上限 / 膨胀 |
|---|---:|---:|---|
| HEAD 小计 | 5,007 | 29.4% | 同 A/B |
| `[body] profile / activity / memory` | 122 | 0.7% | 同 B |
| SYSTEM PROMPT 总 | 5,130 | 30.1% | — |
| `[msg] history (10 msg)` | 663 | 3.9% | — |
| `[msg] 当前 user 输入` | 6 | 0.0% | "现在几点?" |
| `[msg] tool_call + tool_result` | **91** | **0.5%** | **每个工具一来回 ~80-150 tokens** |
| `[tools=] 全部 tool schemas (58)` | **11,150** | **65.4%** | 固定 |
| **GRAND TOTAL** | **17,040** | **100%** | — |

### 3. 工具 schema 内部分块（点名最重的）

**全部 58 个 schema 合计 11,100 tokens**（与上面 `[tools=]` 11,150 略差是 wrapping overhead）。逐 schema token 数 top-10：

| Tool name | tokens | 备注 |
|---|---:|---|
| `xhs.parse_url` | 403 | 小红书解析（描述长） |
| `proactive.snooze_wake_call` | 393 | wake_call 推迟 |
| `character.set_activity` | 382 | 角色"在做什么"更新 |
| `apple_calendar.create_event` | 373 | 创建日历事件 |
| `bilibili.get_subtitles` | 367 | B 站字幕 |
| `save_memory` | 359 | 用户主动存记忆 |
| `docx.create` | 348 | Word 文档创建 |
| `netease.daily_recommend` | 310 | 网易云日推 |
| `activity.search_history` | 278 | 活动历史搜 |
| `bilibili.get_video_info` | 250 | 视频信息 |
| ... (剩余 48 个) ... | — | 每个 ~50-200 tokens |
| **TOTAL 58 schemas** | **11,100** | — |

**top-10 占总 schemas 量的 32%（3,563 / 11,100）**，剩余 48 个 schemas 平均每个 ~157 tokens。

### 4. 结论（只诊断）

#### 三场景总 token

| 场景 | total tokens | 净增（vs A） | 关键贡献 |
|---|---:|---:|---|
| A 冷启动第 1 句 | **16,223** | baseline | tool schemas 11,150 + HEAD 5,007 |
| B 15+ 轮 | **17,434** | +1,211 | 历史 +1,129 / memory recall +59 |
| C 工具调用 | **17,040** | +817 | 历史 +662 / tool round-trip +91 / memory +59 |

→ **三场景 token 量集中在 16k-17.5k，固定 ~95%、增量 ~5%**。

#### 最肥的 2-3 块 + 性质判断

| # | 块 | tokens / 占比（场景 A） | 性质 |
|---|---|---:|---|
| **#1** | `[tools=]` 全部 tool schemas (58 个) | **11,150 / 68.7%** | **固定大**（每次请求都全送，不裁剪；新增 capability 还会涨） |
| **#2** | `[head] TOOL_PROMPT_ADDENDUM` 工具引导文字 | **3,189 / 19.7%** | **固定大**（natural-language 工具用法手册，每次请求都送） |
| **#3** | `[head]` motion_inst + state_inst + thinking_inst 等输出格式指令 | 941 / 5.8%（合计） | 固定（4 个输出标签的格式约束 + 当前角色状态） |
| 其它 | persona + BASE_INSTRUCTION + BEHAVIOR | 772 / 4.8% | 固定（角色切则变） |
| 膨胀项 | history 历史 turns | A→B +1,129 / 15 turn = ~75 tokens / turn pair | **随使用线性膨胀**；short_term cap 30 turn → 上限 ~2,250 tokens |
| 膨胀项 | activity_timeline | 当日真用了再涨 | **每天滚动累积，次日清零**；典型 100-500 tokens |
| 膨胀项 | memory recall top-5 | 当前 59 tokens（2 行 NULL） | **有上限 cap top-5**，~150 tokens |
| 膨胀项 | conversation_summary | 当前 0 | 触发后 token_budget 配置 cap |

**95% 固定 / 5% 增量** — 固定开销由 #1 + #2 主导，**单条"你好"也要 16k tokens**。

#### 回复慢归因（区分三类）

| 归因 | 实测依据 | 判定 |
|---|---|---|
| **① prompt token 大导致每次推理慢** | 单条最简对话 16,223 tokens(约 32-48k chars equiv) 进 LLM；Qwen 大上下文 model first-token-latency 显著线性相关于 input token 量 | **首要嫌疑** —— 95% 是固定 #1+#2 |
| ② 冷启动 / 首次工具 / TTS 首载一次性延迟 | 本审计纯算 token，未实测 latency；但冷启动只首次 affect，连续聊不应每次都 hit | **次要 / 仅首次** |
| ③ 工具串行等待 | C 场景的 tool_call + tool_result 仅 +91 tokens；工具自身网络往返延迟另算（time.now 应近 0，但 calendar/bilibili 等真有 100-500ms） | **场景相关**——只在真触发工具时叠加，单工具非主因 |

**实测依据汇总**：
- 16k tokens 固定开销 = #1 tool schemas 11.1k + #2 TOOL_PROMPT_ADDENDUM 3.2k + #3 输出格式指令 + persona 等 ~1.7k
- 历史膨胀很慢（~75 tokens/turn pair），15 轮也只 +1k
- 工具调用本身轻（往返 ~100 tokens），但底层工具执行耗时不在 token 维度

→ **回复慢的首要嫌疑是 ① prompt 大**，主要由两块"固定大"贡献（#1 工具 schemas 全送 + #2 自然语言工具手册）。**不提优化方案**——治法（裁剪 / 按需注入 / 分组等）是下一步权衡的事。

#### 边界声明

- 本审计 token 数为 tiktoken cl100k_base / litellm fallback 估算；对 qwen 中文实际 token 可能高估 20-30%（=真实 12-13k 量级，仍是相对量级判断有效）
- "你好世界 hello world" 7 tokens 在三种 tokenizer 测得一致；中长文本未跨 tokenizer 校准
- 三场景 history 来源真实 DB；scenario A 用空 history，B 用最近 18 条，C 用最近 10 条
- conversation_summary 当前默认用户 0 行；activity_sessions 当日为 0（DB SELECT 实测）
- 临时测量脚本测完已撤（rm /tmp/token_audit.py 已执行）

### 暂停

token 账单完成；仅诊断不开方。等顾问决：是否进入治法环节（裁剪工具 / 工具懒注入 / 摘要 / 等），优先级如何排。

未改任何代码 / DB / commit / stash。

---

## 【前端全面重核 + FRONTEND-OVERVIEW 校准 · 2026-05-19 04:52】

只读勘查 + 仅改 `docs/FRONTEND-OVERVIEW.md` 一个文档。**铁律**：每条 negative 论断都由 CC 亲自 grep + Read 真组件，零信任 agent 中间报告。

### 改动文件清单

| 文件 | 改动 |
|---|---|
| `docs/FRONTEND-OVERVIEW.md` | §3.2 整张表 in-place 重写（5 条原判错的全改正）+ §3.1 MemoryViewer/VoiceButton/ConnectionDot 拆 3 行精确实证 + 新增 §5 全面校准节（112 行新增） |
| 代码 / DB / commit / stash | 未触 |

### §3.2 in-place 修正（原表 → 新表）

| 项 | 原判 | 新表 |
|---|---|---|
| memory | ✅ 前端 MemoryManagerDrawer 真消费 | 不变 |
| **observability** | ⚠️ 前端无可视化 UI 入口 | ✅ **UI 真有**：SystemStatusSection（系统资源 3s 刷新）+ AIProvidersSection（TTS 用量 / 最近调用） |
| **todos** | ⚠️ 前端无 UI | ⚠️ 退役后：无写入 UI；有 RECV-only alarm 通知 dead branch |
| **clipboard** | ⚠️ 前端无直 UI | ✅ **UI 真有**：SettingsPanelLegacy.tsx:604-765 ClipboardSection 完整 UI，V2 真渲染 |
| **profile PATCH** | ⚠️ 无 PATCH 表单 | ✅ **UI 真有**：UserProfileSection.tsx 510 行完整 UI 走 /profile_data |
| **briefing/test** | ⚠️ 前端无调用 | ✅ **真调用**：lib/integrations.ts:58 fetch /api/briefing/test |
| switch_character | 已下线 | 不变 |
| 零差集 | 不变 | 不变（粒度澄清：20 router / 35 endpoint） |

→ §3.2 原 5 条争议项中 **5 条全部判错或半对**（含 briefing/test 当初没察觉）。原表已添加校准标注与重写。

### §3.1 修正

`MemoryViewer.tsx` / `VoiceButton.tsx` 实测**死代码**（grep 外部 import = 0）；`ConnectionDot.tsx` 真活（ControlBar + Sidebar 真消费）。原 §3.1 一行打包"需核"已拆 3 行实证。

### 新增 §5 内容要点

#### 5.1 SystemStatusSection 数据流向（用户重点关切）

**结论 ①：仅前端面板，不进 LLM。**

- 11 字段（CPU / RAM / Whisper / Net）经 `GET /api/observability/system/resources` → `observability/system.py:collect()` (psutil) → 前端 3 秒刷新渲染
- **B 通路（进 LLM）实测零**：grep `fetchSystemResources / backend_rss / whisper_loaded / system_ram_percent / net_recv_kbps` 在 `format_*_for_prompt` / `system_parts` 路径上全代码库零命中
- `system_parts.append` 6 个注入源全清单（chat.py 实读）：profile / activity_timeline / long_term memory / tool_result / extra_system / proactive 简报 —— 无 SystemResources

**SystemStatus 与主动感知非同源**：
- Activity Timeline（chunk 14）喂 LLM：`app_name / browser_url / browser_title / duration_seconds / start_at` → "今天已活跃 7小时30分钟。主要花在: VS Code 3小时…"
- SystemStatus 喂用户：psutil 系统快照（CPU / RAM / 网络）
- 两套独立可视化，互不喂养

#### 5.2 §3.2 修正表 + 5.3 §1/§2/§3.1/§3.3 抽查表（10 条）

抽查结果：**10 条中 7 对 / 2 错（MemoryViewer + VoiceButton "需核"未核 → 实测死代码）/ 1 措辞合理**。

#### 5.4 失误教训沉淀（5 条改进规则）

1. 整段抄 agent 报告未自验 → 每条 negative 必须 grep+Read 实证
2. `@deprecated` 整文件标记 ≠ 内部 section 全死 → 看 wrapper 是否被真活组件 import
3. UI 嵌在 SettingsPanel 内部不是独立组件 → grep 业务关键词 + 翻大文件
4. 一次自纠后必须连带重审整表（防系统性偏差）
5. "需核"类标注必须在本刀内核完，不留外推

### git status 验证

```
$ git status --porcelain | grep -E '^ M|^M '
 M config.yaml         ← 既有豁免，未触
 M docs/FRONTEND-OVERVIEW.md  ← 本刀唯一改动
```

无任何代码 / DB / 其它文件改动。stash@{0} 未动。

### 暂停

等顾问核：① §3.2 改对没（5 条全错→正）② SystemStatus 数据流向"仅前端不进 LLM"证据是否充分 ③ §5 抽查表 10 条中是否还需补 ④ §5 教训沉淀的 5 条规则是否纳入未来流程

---

## 【clipboard 溯源 + 前端勘查误判自查 · 2026-05-19 04:24】

只读勘查；未改任何代码 / DB / commit / stash / backend 未启动。

---

### 第 1 块 · clipboard 溯源

#### 1.1 引入 commit

```
$ git log --diff-filter=A --follow -- backend/capabilities/clipboard.py
166851b  2026-05-08  feat(chunk3): clipboard helper + character state + intimacy decay + state_update parser
```

同 commit 一并引入 `backend/integrations/clipboard.py`、capability、前端 section。距今 11 天 + 大量 commit 之前。

#### 1.2 立项理由（commit message + IMPLEMENTATION_LOG 原文）

**commit `166851b` 原文**（chunk 3a 子模块）：
> v3-G chunk 3，"角色感增强"主题。
>
> **chunk 3a 剪贴板助手**：
> - `backend/integrations/clipboard.py`：ClipboardWatcher 单例。macOS NSPasteboard
>   1Hz 轮询为主路径（pyobjc transitive 已含），跨平台 fallback pyperclip。
>   Ringbuffer 50 条，TTL 24h，重启清空（**不持久化** SQLite，隐私敏感）。
>   content_type 启发式识别（url / code / plain_text / markdown / json）。
>   **不自动响应**剪贴板变化（设计原则：用户只想 Momo 在被问到时回应）。
> - `backend/capabilities/clipboard.py`：3 个 CHAT_AGENT capability —— get_recent
>   / summarize / translate。prompt addendum 引导用户提到「刚复制的」时调，不主动调。

**IMPLEMENTATION_LOG.md L501-520 chunk 3 立项段** 关键 7-8 项：
> 7. **clipboard ringbuffer 不持久化**：故意不写 SQLite（隐私 + 重启即清空）。route 端 clipboard.captured 100KB 截断防大 base64。
> 8. **不自动响应剪贴板变化**：spec 关键设计——自动评论会烦人 + 隐私失控 + 上下文失控。capability 注册让 LLM 在用户**明确提到**剪贴板时调；prompt 引导写明"不要主动调"。

→ **当时为什么做**：v3-G "角色感增强"主题；让 Momo 在用户主动提到"刚复制的"时能调出最近剪贴板内容做 summarize / translate；**坚持"被动响应"原则**（不自动评论）+ "本地内存 / 重启清空 / 不持久化"隐私契约。

#### 1.3 现状（防 todos 式幽灵）

**① UI 真活**：

| 文件:行 | 内容 |
|---|---|
| `frontend/src/components/SettingsPanelLegacy.tsx:604-765` | **ClipboardSection 完整实现**（160+ 行）：捕获开关 toggle + 隐私说明文字 ("🔒 剪贴板内容仅本地内存，重启清空，不外传") + 最近 5 条列表 fetch + 清空按钮 + 空状态提示 |
| `frontend/src/components/SettingsPanelLegacy.tsx:670` | `<Section title="剪贴板">` 标题 |
| `frontend/src/components/SettingsPanelLegacy.tsx:672` | `label="捕获剪贴板（默认开启）"` 开关 |
| `frontend/src/components/SettingsPanelLegacy.tsx:690` | `🔒 剪贴板内容仅本地内存，重启清空，不外传。` |
| `frontend/src/components/settings/SettingsPanelV2.tsx:25, 32` | `import { ClipboardSection, ... } from '../SettingsPanelLegacy'`（V2 复用 Legacy 的 wrapper） |
| `frontend/src/components/settings/SettingsPanelV2.tsx:43` | docstring 注释 `4. 📋 剪贴板 —— ClipboardSection` |
| `frontend/src/components/settings/SettingsPanelV2.tsx:106-107` | tab id `'clipboard'` label `'剪贴板'` |
| `frontend/src/components/settings/SettingsPanelV2.tsx:111` | `<ClipboardSection showToast={showToast} />` 真渲染 |

**② 后端能力真活**：

| 文件:行 | 内容 |
|---|---|
| `backend/capabilities/clipboard.py` | 3 个 capability `clipboard.get_recent` / `clipboard.summarize` / `clipboard.translate`；CHAT_AGENT consumer，真注册 ToolRegistry（参见 BACKEND-OVERVIEW §1.4 LLM tool 全清单） |
| `backend/integrations/clipboard.py` | ClipboardWatcher 单例（NSPasteboard 1Hz 轮询 + ringbuffer 50 条/24h TTL） |
| `backend/routes/character_state_api.py:117-165` | 5 个 REST endpoint：`GET /api/clipboard/recent` / `POST /api/clipboard/clear` / `GET /api/clipboard/enabled` / `POST /api/clipboard/enabled` / `POST /api/clipboard/captured` |
| `frontend/src/lib/integrations.ts:95-133` | clipboard 客户端 4 函数（enabled GET/SET + captured push） |

**③ 端到端真接通**：

| 数据流路径 | 真值 |
|---|---|
| 前端"捕获剪贴板"开关 toggle | `SettingsPanelLegacy.tsx:680` → `POST /api/clipboard/enabled` → 后端 `ClipboardWatcher.set_enabled` runtime override（不写 yaml；重启回 yaml 默认值）|
| 启动时回填开关状态 | `SettingsPanelLegacy.tsx:624` → `GET /api/clipboard/enabled` → 显示当前开关 |
| 后端捕获 | macOS NSPasteboard 1Hz 轮询 → ringbuffer 写入（**内存**，不入 DB） |
| 前端"最近 5 条"列表 | `SettingsPanelLegacy.tsx:630` → `GET /api/clipboard/recent?n=5` → 渲染列表 |
| 前端"清空"按钮 | `SettingsPanelLegacy.tsx:651` → `POST /api/clipboard/clear` → ringbuffer 清空 |
| LLM 调用 | `chat.py` ChatAgent 拿到 LLM tool calling → `clipboard.get_recent / summarize / translate` capability → ringbuffer 数据 → 返 LLM |

→ **端到端完全接通**。clipboard 是真活功能，**非幽灵**。tool_addendum.py 也有完整引导段（"用户提到'刚复制的'时调 clipboard.get_recent" 等）。

---

### 第 2 块 · CC 自查 — 前端勘查"无 UI"误判根因

#### 2.1 当时判定路径还原

FRONTEND-OVERVIEW.md §3.2 表格当时写：
> "后端 `/api/clipboard/*`（3 capability：get_recent / summarize / translate）| ⚠️ **前端无直 UI**；仅 LLM tool 间接调"

**当时具体怎么得出这个结论**：
1. 我 dispatched 一个 Explore agent for "Frontend WS+REST+drift deep-dive"
2. Agent 报告的"后端有但前端未调用（审查差集）"列表里直接写：`/api/clipboard/* — 后端能力完整，前端无 UI 入口`
3. 我**未做独立 grep 验证**，**未亲自打开 SettingsPanelLegacy 翻**，把 agent 的差集列表整段抄进 §3.2

#### 2.2 失误根因（不护短）

**根本原因**：**信任了 agent 报告但未亲自核**。系统 prompt 明示"Trust but verify: an agent's summary describes what it intended to do, not necessarily what it did" —— 我违反了这条。

**具体失误机制**：
- agent 在它自己的 §3 段标"**SettingsPanelLegacy 标记淘汰**" + "@deprecated bugfix-2.2:已被 SettingsPanelV2 + CapabilitiesPanel 完全替代" → 给我一种"Legacy 整文件死代码"的印象
- **实际**：Legacy 是 wrapper 函数 + section 组件的**仓库**，V2 / AIProvidersSection 大量复用其中的 sections（包括 ClipboardSection、SystemStatusSection、UserProfileSection 等）。Legacy `@deprecated` 标记针对的是"作为整 SettingsPanel 入口被替代"，**不是**"内部所有 section 都死了"
- agent 错误把"Legacy 整文件 @deprecated" 推断成"clipboard 没 UI"；我接收时**没有 grep clipboard 关键词**做一道独立验证
- 同样的失误模式重复在 observability、profile_data 上（profile_data 那条后来已自纠，但 §3.2 表格未同步重审）

**为什么 grep 没命中**：我**根本没跑那个 grep**。如果当时简单跑 `grep -rln clipboard frontend/src/`，立即会出 5 个文件命中，直接戳破 agent 的论断。

#### 2.3 同类风险逐项重新核（防进一步漂移）

用本次发现 clipboard UI 的相同方法（grep + Read 真组件），对 FRONTEND-OVERVIEW §3.2 "后端有前端无 UI" 5 个条目逐个重核：

##### A. `/api/clipboard/*`

**原判**：⚠️ 前端无直 UI；仅 LLM tool 间接调
**实证**：`SettingsPanelLegacy.tsx:604-765 ClipboardSection`（160+ 行完整 UI）；V2 在 L111 真渲染；后端 5 endpoint + 前端 4 API client + 端到端通
**修正**：✅ **UI 真有，端到端真活；原判错**

##### B. `/api/observability/*`（tts_call_log 埋点 510 行真数据）

**原判**：⚠️ 前端无可视化 UI 入口；数据写得到但用户看不到
**实证（grep `observability` in frontend）**：
- `frontend/src/lib/observability.ts` — API 客户端 3 函数：`fetchTtsUsage` / `fetchRecentCalls` / `fetchSystemResources`
- `SettingsPanelLegacy.tsx:1157-1185+` **SystemStatusSection 组件**：3 秒刷新一次 `fetchSystemResources`，渲染系统资源面板
- `capabilities/AIProvidersSection.tsx:15-17, 1255` **真用 `fetchTtsUsage` + `fetchRecentCalls`** —— TTS 用量 + 最近调用都有可视化 UI
- `SettingsPanelV2.tsx` 复用上述（同 Legacy import 链）

**修正**：✅ **UI 真有（TTS 用量 + 系统资源都可视化）；原判错**

##### C. `/api/todos/*`

**原判**：⚠️ 前端无 UI；只 LLM tool 间接写（add_todo 等）+ WS `alarm` 推
**当前实证**：
- 已退役（c1d65ff 删除整套）；本身从未有"写入 UI"
- 唯一前端涉及 todo 的字面：`useWebSocket.ts:17, 369-370` 的 `alarm` 帧 RECV + `pushNotification(type='alarm', todoId)` + `store/index.ts:227` 通知队列
- 这是 RECV-only 路径，无写入 UI
- todos 已退役后，alarm 帧不会再被推（无 AlarmScheduler），但前端 RECV 分支仍存在（dead branch，无害）

**修正**：✅ **半对**（确无写入 UI，但有 RECV-only 通知消费；现已退役）；未来可清前端 alarm dead branch

##### D. `/api/profile` PATCH（之前已自纠过的项）

**原判（第一次）**：⚠️ 前端有 GET 但**无 PATCH 表单**
**已自纠（INVESTIGATION 上一条 profile/todos 核实）**：前端 `UserProfileSection.tsx`（510 行）真有完整 PATCH + regenerate UI，走 `lib/profileData.ts` → `/api/users/{uid}/profile_data`
**最终实证**：
- `frontend/src/components/UserProfileSection.tsx:16-22 / 53-85` import + 渲染 fetchProfileData / patchProfileData / regenerateProfileData 全套
- `SettingsPanelLegacy.tsx:18, 1918` import + 渲染
- `SettingsPanelV2.tsx:33, 46` import + 渲染

**修正**：✅ **PATCH UI 真有；原判错（已自纠）**

##### E. `/api/briefing/test` —— 测试接口

**原判**：测试接口，前端无调用
**实证**：grep `briefing/test` in frontend = 0 命中；这是后端测试 endpoint，前端确无调用
**修正**：✅ **原判对**

#### 2.4 修正表

| # | §3.2 原判定 | 真实情况 | 修正 |
|---|---|---|---|
| A | clipboard：前端无直 UI | `SettingsPanelLegacy.tsx:604-765 ClipboardSection` 完整 UI；V2 复用；端到端通 | **判错；需改成"UI 真有（嵌在 Settings 剪贴板栏内）+ 后端 + 端到端真活"** |
| B | observability：前端无可视化 UI 入口 | `SettingsPanelLegacy.tsx:1157+ SystemStatusSection` + `AIProvidersSection.tsx:1255 fetchTtsUsage` | **判错；需改成"TTS 用量 + 系统资源都有可视化 UI"** |
| C | todos：前端无 UI | 退役前从未有写入 UI；有 RECV-only alarm 通知路径；现已 c1d65ff 退役 | **半对；需改成"无写入 UI；有 RECV-only alarm 通知（c1d65ff 退役后 dead branch）"** |
| D | profile PATCH：前端无表单 | `UserProfileSection.tsx` 510 行完整 PATCH + regenerate UI；走 `/api/users/{uid}/profile_data` | **判错（已自纠）；需在 §3.2 表格里同步删除"profile PATCH 缺位"那一行** |
| E | `/api/briefing/test`：测试接口前端无调用 | grep = 0 命中 | **原判对** |

→ **5 个条目里 4 个判错（A/B/C/D），1 个判对（E）。**

#### 2.5 失误教训 / 行为改进

- **不能整段 copy agent 报告**：尤其涉及"无 X / 缺 X"这种 negative claim 时，必须亲自跑 grep 验证
- **`@deprecated` 整文件标记不等于"内部 section 都死"**：要看是否被其它真活组件 import + 渲染
- **"后端有前端无 UI"是高风险论断**：UI 可能嵌在大文件内部 section，不是独立组件，单纯找文件名命中容易漏；要 grep 关键词 + 翻 SettingsPanel 大文件
- **§3.2 表格漏审已暴露**：当 profile_data 那条第一次自纠时，本应同步复查整张表，没做 → 这次发现 clipboard 错时才连带把 observability / todos 都暴出来
- 应在 FRONTEND-OVERVIEW.md 加修正声明（建议下次刀做）

### 暂停

clipboard 溯源 + §3.2 自查完整；4 个条目判错确证，1 个判对。等顾问决：① 修正 FRONTEND-OVERVIEW.md §3.2（一次性把 A/B/C/D 改写）② 是否补一节"§3.5 §3.2 修订" 还是直接 in-place 改 ③ 前端 alarm RECV dead branch 是否一并清

未改任何代码 / DB / commit / stash。

---

## 【memory.confidence 字段溯源 · 2026-05-19 03:51】

只读勘查；HEAD=`c1d65ff`，未改任何代码 / DB / commit / stash。

### 1. memory 表 schema 现状

```sql
CREATE TABLE memory (
    id INTEGER NOT NULL,
    user_id VARCHAR NOT NULL,
    role VARCHAR NOT NULL,
    type VARCHAR NOT NULL,
    content TEXT NOT NULL,
    embedding BLOB,
    expires_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    character_id INTEGER,
    access_count INTEGER DEFAULT 0,
    last_accessed_at TIMESTAMP,
    extracted_at TIMESTAMP,
    source_turn_id INTEGER,
    confidence REAL,              ← 本核实目标列
    quality_score REAL,           ← 同批姊妹列
    entry_type TEXT,
    extraction_source TEXT NOT NULL DEFAULT 'legacy',
    PRIMARY KEY (id),
    CONSTRAINT ck_memory_role CHECK (role IN ('user','system')),
    CONSTRAINT ck_memory_type CHECK (type IN ('fact','instruction','emotion','activity','daily')),
    FOREIGN KEY(user_id) REFERENCES users (user_id)
);
```

**`confidence REAL nullable`** — 浮点列、可空、无默认值。

### 2. 引入时间 — 早就存在（非近期）

```
$ git log --oneline --all -S "confidence" -- backend/database/models.py backend/database/migrations/
a692ac9 feat(chunk10): memory schema 扩展 + extractor_state 表 + migration

$ git show a692ac9 --no-patch --format="%h %ad %s" --date=short
a692ac9 2026-05-12 feat(chunk10): memory schema 扩展 + extractor_state 表 + migration

$ git log --oneline a692ac9~1..HEAD | wc -l
166      ← 166 个 commit 在 a692ac9 之后
```

→ **v3.5 chunk 10**（2026-05-12，距今 7 天 / 166 个 commit 前）引入；与 `entry_type / extracted_at / source_turn_id / access_count / extraction_source / quality_score / last_accessed_at` 一批同时新增的"结构化 memory 扩展"列之一。

迁移文件：`backend/database/migrations/v3_5_chunk10_memory_structured.py:64` `("confidence", "REAL"),`

迁移文件 docstring（L9）原文：
```
* ``confidence`` REAL NULL    —— LLM 自评 0-1（validator 阈值过滤用）
```

### 3. 写入方 + 取值逻辑

| 写入路径 | 文件:行 | 取值规则 |
|---|---|---|
| **extractor server-side worker**（chunk 10 主入口） | `backend/memory/extractor.py:231` 取 `entry["confidence"]`；L266 注入 INSERT 参数 | 来自 LLM 自评：extractor prompt 要求 LLM 输出 `confidence ∈ [0, 1]`，每 5 分钟跑一次 |
| LLM 主 prompt（取值"语法"） | `backend/prompts/memory_extraction.py:73-94` | "随口单次但锚明确 → 提取，**confidence 0.6-0.8**"；"反复出现或用户明确强调 → **提高 confidence (0.85+)**"；validator 阈值 schema |
| `save_memory` LLM tool（用户主动让 LLM 记） | `chat.py:704-717` `_tool_save_memory` 写库 | **不写 confidence** —— 只设 `extraction_source='llm_save_memory'`；confidence 列保持 NULL（默认） |
| `POST /api/memory/add` UI 手填 | `memory_api.py:113-127` | 不传 confidence；列 NULL |
| extractor 调用前的 validator | `backend/utils/memory_entry_validator.py:187` | `cleaned["confidence"] = float(conf_raw)` 经过 `[0,1]` 范围校验 |

**取值数字 0.7/0.8 来源**：纯 LLM 自评输出。extractor prompt 给 LLM 一个评分指南（单次随口 0.6-0.8，反复强调 0.85+），LLM 在 JSON 输出里自填一个浮点；validator 检查 ∈ [0,1] 后传给 extractor 入库。

### 4. 读取方 + 是否参与逻辑

| 读取路径 | 文件:行 | 用途 |
|---|---|---|
| **validator 阈值过滤** | `backend/utils/memory_entry_validator.py:267` `if cleaned["confidence"] < min_confidence: reject` | ⭐ **真参与过滤** —— 低于阈值的 entry 直接丢弃，不入库 |
| 阈值配置 | `backend/memory/extractor.py:67-70` `get_extractor_min_confidence()` 默认 **0.5** | 配置项；config.yaml `memory.extractor.min_confidence` |
| `/api/memory/list` 返回字段 | `routes/memory_api.py:103` `"confidence": m.confidence` | UI 展示用 |
| UI 展示 | `frontend/src/components/MemoryManagerDrawer.tsx:42, 399-400` | 类型声明 + NULL 时不显示；非 NULL 时角标显示 |

**关键发现**：没有任何 `WHERE confidence > X` / `ORDER BY confidence` 的 SQL —— **运行时检索 / 召回路径完全不读 confidence**。它只在两个时点参与决策：
- 入库前：validator 阈值过滤（< 0.5 拒绝写入）
- 入库后：API / UI 展示（非 NULL 时显示数字）

### 5. c1d65ff 影响核 — 零触动

```
$ git show c1d65ff | grep -E "confidence|quality_score|extracted_at"
(空)

$ git show c1d65ff --stat
12 files changed, 41 insertions(+), 1551 deletions(-)
  (12 文件均不含 confidence 字面)
```

→ **c1d65ff（todos + profile_summary 退役刀）完全未触动 confidence**：增 0、删 0、改 0。

### 6. 结论

**三选一答案：① 早就存在的字段，用户此前未注意**。

证据三角：
- DB schema 实测 confidence REAL nullable 列存在 ✅
- git log -S 追溯入口：commit `a692ac9` (2026-05-12 chunk 10)，距今 7 天 + 166 commit 前 ✅
- c1d65ff diff 零触动 ✅

**当前作用 — 既不是"仅展示"也不是"刚加上"**：

| 阶段 | 角色 |
|---|---|
| LLM 抽取阶段 | LLM 自评填 confidence 0-1；prompt 给评分指南（0.6-0.8 / 0.85+） |
| validator 入库前过滤 | `confidence < 0.5` → reject（不入库）— **真功能闸** |
| 入库后检索 / 召回 | **不参与**（无 WHERE / ORDER BY） |
| API + UI | 展示字段，NULL 时隐藏 |

**配套 chunk 10 同期新增的姊妹列**（同样 2026-05-12 a692ac9 入库，非近期变化）：
- `entry_type` TEXT — 4 分类（fact/preference/event/commitment）
- `extracted_at` TIMESTAMP — 抽取时间戳
- `source_turn_id` INTEGER — 来源 chat_history 行
- `extraction_source` TEXT — `worker` / `llm_save_memory` / `legacy`
- `access_count` / `last_accessed_at` — 召回热度
- `quality_score` REAL — 同 confidence 一批加的另一个浮点列，**当前真活 grep 显示 0 个写入源 0 个真消费**（除模型定义本身），是 chunk 10 留的 backlog 槽，未来可能填用

→ 用户看到的 confidence 不是"又多了一个"，是 chunk 10 当时一批加的；本刀只清 todos + profile_summary，未触 memory schema 任何列。

### 暂停

memory.confidence 溯源完整；无后续动作。未改任何代码 / DB / commit / stash。

---

## 【todos 退役 + profile_summary 条件核删 · 2026-05-19 02:58】

### 前置 + 备份

- `git status --porcelain | grep M`：仅 `M config.yaml`（豁免）
- HEAD = `3d76982` / stash@{0} 未动
- 新备份：`momoos.db.backup_todoretire_20260519_024421`（700 416 B）

### 步骤 0 — profile_summary 生死核实

**真值**：
```
sqlite3> SELECT user_id, profile_data 状态, profile_summary 状态 FROM users WHERE user_id='default';
default | profile_data len=208 | profile_summary NULL
```
- default profile_data 实测内容：`{"profession": null, "current_projects": ["MomoOS-v2"], "interests": ["网易云音乐", ...], ...}`（chunk 11 真生成）
- 全部 19 个 user 行 `profile_summary` 均 NULL（含 default）

**chat.py fallback 严格性**（实读 L1392-1398）：
```python
if formatted:                       # ← format_profile_for_prompt(profile_data) 真返非空
    system_parts.append(formatted)
else:                                # ← else 分支
    summary = await get_profile_summary(...)  # ← profile_data 非空时 PERMANENTLY UNREACHABLE
    ...
```

**判定**：**profile_summary 真死，本刀一并删**
- default profile_data 非空 ✅
- fallback else 严格永不命中真用户 ✅
- 19 用户全 profile_summary=NULL ✅
- 即便新用户 profile_data NULL，fallback 也只读 NULL（功能等价）

### 步骤 1 — todos + profile_summary 死代码删除（实际执行）

| 文件 | 操作 | 行数变化 |
|---|---|---|
| `backend/agents/planner.py` | **整文件删** | -252 |
| `backend/agents/memory.py` | **整文件删** | -281 |
| `backend/scheduler/task.py` | **整文件删** | -143 |
| `backend/main.py` | 删 import `from backend.scheduler.task import scheduler` (L171) + AlarmScheduler.start/log (L499-500) + scheduler.stop (L869) + docstring 行 5 | -7 / +5 净 -2 |
| `backend/database/services.py` | 删 `update_profile_summary` / `get_profile_summary` (L49-70) + 删 `create_todo` (L206-238) + 删 `get_todos` (L252-271) + 删 `update_todo_status` (L274-290) + 删 `search_todo` (L364-413) | -150 |
| `backend/routes/memory_api.py` | 删 `/todos/list` + `/todos/add` + `/todos/{id}/status` 三 endpoint (L231-293) + 删 bare `/profile` GET + PATCH (L296-318) + 配套 import + Body class + docstring 行 | -121 |
| `backend/routes/users_api.py` | 删 `update_profile_summary` import + `ProfileSummaryPatchBody` + `ProfileSummaryRegenerateResponse` + GET /profile / PATCH /profile 中 profile_summary 字段 + `/profile_summary` PATCH (L117-160) + DELETE (L163-179) + POST regenerate (L182-232) | -139 |
| `backend/agents/chat.py` | 删 import `get_profile_summary` (L58) + 删 fallback 两处（L1146-1150 renderer path + L1390-1394 legacy path） | -21 |
| `backend/routes/ws.py` | 删 `get_profile_summary` + `update_profile_summary` import (L66-67) + 删 profile_summary background regeneration 整段（含 `_compute_profile_summary` / `_regenerate_profile_summary` / `_filter_user_messages` / `_format_user_history` / `_build_profile_prompt` / 3 个 PROFILE_SUMMARY_* 常量，L269-484 共 217 行）；替换为 3 行 [RETIRED] 注释 | -217 / +4 净 -213 |
| `backend/routes/conversations_api.py` | 删 V2.5-D `_regenerate_profile_summary` kick (L148-152) + 删 unused `import asyncio` (L10) | -7 |
| `backend/config/prompts.py` | 保 L1-12 BASE_INSTRUCTION；删 MEM_AGENT_PROMPT + PLANNER_AGENT_SYSPROMPT + PLANNER_AGENT_INST + PLANNER_AGENT_FEW_SHOT（L13-232 全删，整体 Write 重写）| -220 / +7 净 -213 |
| `backend/database/models.py` | `User.profile_summary` 列上加 `[RETIRED 2026-05-19]` 4 行注释 + 列保留；`Todo` class 上方加 4 行 `[RETIRED 2026-05-19]` 注释 + class 保留 | +8 |

**diff stat 真值**（来自 `git diff --stat`，未含 config.yaml 豁免）：
```
12 files changed in cut + 1 config.yaml(pre-existing,豁免) = 13 in stat
42 insertions(+), 1571 deletions(-)
```

**未做**（按指令保留）：
- DROP TABLE todos / 删 Todo ORM class
- DROP COLUMN users.profile_summary
- 前端 alarm RECV 分支 / `frontend/src/lib/profile.ts` dead client
- DB 数据修改

### 步骤 2 — 【红线】delete_memory ChatAgent 活路径核

| 检查 | 真值 |
|---|---|
| `chat.py:460-538 MEMORY_TOOLS` delete_memory schema (name + description + parameters) | ✅ **零 diff**（diff 仅显示 import 行 `delete_memory as db_delete_memory` 保留未删） |
| `chat.py:721 _tool_delete_memory` 实现函数 | ✅ **零 diff** |
| `chat.py:876` dispatcher `"delete_memory": _tool_delete_memory` 注册 | ✅ **零 diff** |
| `chat.py:588-593 _get_all_tools()` LLM tool 列表生成 = `MEMORY_TOOLS + ToolRegistry.list_schemas()` | ✅ **零 diff** |
| `agents/prompt/tool_addendum.py:32-35` delete_memory 活描述（"当用户要求忘掉某事，先 list_memories 找匹配再 delete_memory"） | ✅ **整文件零 diff** |
| ToolRegistry / capability 注册（`tools/registry.py:99 clear_short_term`） | ✅ **零 diff** |

**结论**：本刀只删 PLANNER dead 段的 `- delete_memory(user_id, memory_id)` 字面声明（在 PlannerAgent 已退主路径的孤儿 prompt 内）。**用户删记忆功能完全未受影响**：ChatAgent delete_memory 注册 + 描述 + 实现 + 列表生成函数 + 主聊天 prompt 引导，一字未动。

### 步骤 3 — 留空表 + 注释

- `users.profile_summary` 列：保留（不 DROP COLUMN），加 [RETIRED 2026-05-19] 注释（models.py:25 上方 4 行）
- `todos` 表 + `Todo` ORM class：保留（不 DROP TABLE），加 [RETIRED 2026-05-19] 注释（models.py:178 上方 4 行）

### 静态自查

| 检查 | 结果 |
|---|---|
| 删除模块后无悬空 import (planner / memory / scheduler.task) | ✅ `grep -rE "from backend.agents.planner\|from backend.agents.memory\|from backend.scheduler.task" backend/` = 零命中 |
| 删除 services 函数后无悬空 import | ✅ 6 函数（4 todo + 2 profile_summary）全代码库零执行性引用（剩余 grep 命中均为我新加的 [RETIRED] 注释文本） |
| 删除 ws.py profile 段后无悬空 helper | ✅ `_compute_profile_summary` / `_regenerate_profile_summary` / `_filter_user_messages` 等剩余 grep 命中均为 docstring 注释字面引用 |
| BASE_INSTRUCTION 保留并真活 | ✅ `chat.py:51` + `prompt_manager.py:26` 真 import，`chat.py:1329` + `prompt_manager.py:51` 真消费 |
| `cron_scheduler` / `scheduler.briefing` 未受影响 | ✅ `main.py:172 from backend.scheduler import cron as cron_scheduler` + 10+ 处 `cron_scheduler.schedule_*` 全活；APScheduler 真路径独立 |
| delete_memory 活路径零触动 | ✅（见步骤 2 红线表） |
| `users.profile_summary` 列保留 + 加注释 | ✅ models.py:24-28 |
| `Todo` ORM + todos 表保留 + 加注释 | ✅ models.py:181-184（class 上方）/ DB 表未触 |
| DB 未触 | ✅ `SELECT COUNT(*) FROM todos = 1`（原 1 行 historical 残留保留）/ profile_summary IS NOT NULL 行数 = 0（原 0 即 0） |

### git status / 改动范围

```
 M  backend/agents/chat.py
 D  backend/agents/memory.py
 D  backend/agents/planner.py
 M  backend/config/prompts.py
 M  backend/database/models.py
 M  backend/database/services.py
 M  backend/main.py
 M  backend/routes/conversations_api.py
 M  backend/routes/memory_api.py
 M  backend/routes/users_api.py
 M  backend/routes/ws.py
 D  backend/scheduler/task.py
 M  config.yaml        ← 既有豁免，未触
```

12 文件本刀范围（9 M + 3 D），config.yaml 豁免未触。无任何超 scope 文件。

### 禁项遵守

零 commit / 零 push / 零 stash 动作 / 零 backend 启动 / 零 DROP TABLE / 零 DROP COLUMN / 零 DB 数据修改。

### 暂停

12 文件 deletion / edit 全部就位。等顾问核：
1. 12 文件改动是否同意（特别是 ws.py 217 行整段移除 + conversations_api delete 路径退役）
2. 是否一组 commit 提交（建议一个 commit："refactor(retire): todos 链路 + profile_summary fallback 全退役"）
3. 后续单独刀（DROP TABLE todos / DROP COLUMN profile_summary / 前端 alarm 分支 / lib/profile.ts dead client）何时做

---

## 【todos 退役 recon · 2026-05-19 02:32】

只读 recon；未改任何代码 / DB / commit / stash / backend 未启动。

### 1 · apple_calendar 底层到底是什么

#### 1.1 Skyler 内建 capability（非 MCP）

`backend/capabilities/apple_calendar.py` 注册 4 个 capability：
```
L34  @register_capability  apple_calendar.today_events
L61  @register_capability  apple_calendar.upcoming_events
L96  @register_capability  apple_calendar.create_event
L184 @register_capability  apple_calendar.delete_event
```

底层实现：`backend/capabilities/apple_calendar.py:22` `from backend.integrations import apple_calendar as ac`

`backend/integrations/apple_calendar.py`（L1-15 模块 docstring）：
```
"""v3-G chunk 1.6 — Apple Calendar 底层 client (macOS EventKit)。
* macOS EventKit 权限申请（macOS 14+ 用 requestFullAccessToEventsWithCompletion_）
* EventKit API 是同步阻塞 + Cocoa run loop callback 风格
"""

import EventKit as _EventKit  # type: ignore  (lazy macOS-only)
EKEventStore.alloc().init()
```

→ **底层 = macOS EventKit 原生 API**（pyobjc-framework-EventKit）；直接调系统日历库。**非 MCP、非 osascript、非 subprocess**。

#### 1.2 MCP 注册表实测无任何 calendar MCP

```
$ sqlite3 momoos.db "SELECT * FROM mcp_client_state"
notion            | 0  | 2026-05-10
filesystem        | 0  | 2026-05-13
brave-search      | 0  | 2026-05-13
_test_disable     | 0  | 2026-05-12
filesystem-skyler | 1  | 2026-05-13  ← 唯一 enabled
test-fail         | 0  | 2026-05-13

$ sqlite3 momoos.db "SELECT * FROM mcp_tool_state"
(空)

$ sqlite3 momoos.db "SELECT * FROM mcp_credentials"
(空)
```

→ 只有 `filesystem-skyler` enabled；**无任何 calendar / event 类 MCP server**。

#### 1.3 calendar 路由抽象层（router pattern）

`backend/capabilities/calendar.py` 注册 2 个 router-style capability：
```
L79  @register_capability  calendar.today_events       (路由)
       → _route_today_events:43 → apple_calendar.today_events
                                  OR google_calendar.today_events
L96  @register_capability  calendar.upcoming_events    (路由)
       → 同上分发
```

LLM 主流程 prompt（`tool_addendum.py`）引导用户走 `calendar.today_events` / `calendar.upcoming_events`（不分平台），底层路由根据 calendar.router 配置选 apple 或 google。

#### 1.4 "提醒/日程"用户链真实路径

**唯一真路径**：
```
用户："提醒我明天 10 点 X"
  ↓
ChatAgent prompt 引导（tool_addendum.py:18-27）："先 time.now → 再 apple_calendar.create_event"
  ↓
LLM 调 apple_calendar.create_event(title, start_time, duration, ...)
  ↓
backend/capabilities/apple_calendar.py:141 create_event
  ↓
backend/integrations/apple_calendar.py EventKit.EKEvent.alloc()...
  ↓
macOS 系统日历（用户可在 Calendar.app 看到）+ 由 macOS 自己负责到点通知
```

无并存路径；无冲突源；无 calendar MCP。

#### 1.5 结论 — todos 替代是否真闭环？

| 项 | 真值 |
|---|---|
| todo 的替代者 | `apple_calendar.create_event`（macOS EventKit） |
| 替代者真活 | ✅ capability 真注册（ToolRegistry 真有此 schema）；LLM 主路径 prompt 真引导 |
| 真在用 | ⚠️ 代码层活；真机层"用户是否真用"待真机验证（但 capability 注册 + prompt 引导双就位 = LLM 会走这条） |
| 提醒到点的"通知" | 由 macOS 系统日历负责（不经 Skyler 后端推送）；与 AlarmScheduler 完全独立 |

✅ **"todo 被取代"基本闭环**：apple_calendar 真活、LLM 真被引导。 todos 路径写入面已无客户；用户感知层不缺。

---

### 2 · todos 相关代码死活全图

#### 2.1 todos 表 schema + 数据

```sql
CREATE TABLE todos (
    id INTEGER NOT NULL PRIMARY KEY,
    user_id VARCHAR NOT NULL,
    owner_type VARCHAR NOT NULL,
        CONSTRAINT ck_todo_owner_type CHECK (owner_type IN ('alarm','agent','schedule')),
    title VARCHAR NOT NULL,
    description TEXT,
    due_time DATETIME NOT NULL,
    status VARCHAR,
        CONSTRAINT ck_todo_status CHECK (status IN ('pending','completed','failed','multiple')),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES users(user_id)
);
```

数据：**1 行**（historical 残留）
```
id=1 | user=default | owner_type='schedule' | title='开会'
    | due_time=2026-05-03 09:00:00 | status='pending'
```
- 超期 16 天但仍 pending → 因 `_mark_stale_alarms_failed` 只处理 owner_type='alarm' 的，`schedule` 它不 touch
- owner_type 'agent' / 'schedule' **全代码库零读取**

#### 2.2 AlarmScheduler 现状

启停：
- 启动：`backend/main.py:499` `await scheduler.start(default_uid)` （lifespan 真注入）
- 停止：`backend/main.py:869` `await scheduler.stop()` （lifespan 终止）

轮询逻辑：
- `scheduler/task.py:14` `_CHECK_INTERVAL = 30` 秒
- 启动一次性 `_mark_stale_alarms_failed`（`scheduler/task.py:64-89`）：search_todo(owner_type='alarm', due_end=now) → 全部 'pending' / 'multiple' → status='failed'
- 周期 `_check_due_alarms`（`scheduler/task.py:91-140`）：search_todo(owner_type='alarm', due_end=now+1s) → 真活的 push `{type:'alarm', content, todo_id}` 到前端 + update_todo_status='completed'

**`owner_type='alarm'` 真活写入源全 grep**：
```
$ grep -rnE "owner_type.*=.*'alarm'|owner_type=\"alarm\"" backend/
backend/scheduler/task.py:76     ← 读（search_todo 过滤条件）
backend/scheduler/task.py:118    ← 读
```
两处都是 **读**，**无任何写入源**写 owner_type='alarm' 的行。

**`create_todo` 调用者全 grep**：
```
backend/database/services.py:206  ← 定义
backend/agents/memory.py:164      ← MemoryAgent _handle_add_todo（DEAD path）
backend/routes/memory_api.py:263  ← /api/todos/add endpoint（无前端 caller，后端零内部调用）
```

→ **AlarmScheduler 是真活码做"空轮询"**：30s 一次 SELECT owner_type='alarm'，永远返 0 行（无人写入），永远 no-op。

**关掉 AlarmScheduler 影响面**：
- apple_calendar create_event 的"到点通知" → 由 macOS 自己负责，**完全独立于 AlarmScheduler**
- 前端 WS `alarm` 帧消费者：`useWebSocket RECV alarm` → `pushNotification(type='alarm')`，但**目前永远不会触发**（无 alarm todos）；删 AlarmScheduler 后该 RECV 分支变 dead branch（前端代码留着无害）
- 关掉无任何活功能影响

#### 2.3 add_todo / delete_todo / search_todo 调用链死活逐段

| 段 | 文件:行 | 状态 |
|---|---|---|
| **prompts.py 声明（LLM prompt 字面）** | `prompts.py:106-108`（PLANNER_AGENT_SYSPROMPT） / `prompts.py:145,165`（FEW_SHOT） | ⚠️ **dead path 残留** —— 只被 planner.py 导入（见下条），不进 ChatAgent LLM 流 |
| **planner.py 消费 PLANNER_AGENT_** | `agents/planner.py:52-54` import + 用 | ❌ **DEAD** — `grep "from backend.agents.planner"` = 零外部 import |
| **PlannerAgent 路由** | `routes/ws.py:7-12 / 172` 注释明示"已退出主流程" | ❌ **DEAD** |
| **MemoryAgent dispatcher** | `agents/memory.py` 整文件 | ❌ **DEAD** — 零外部 import；handler 表 `add_todo / delete_todo / search_todo / update_todo_status` 永不被 dispatch |
| **services.create_todo / search_todo / update_todo_status** | `services.py:206` 等 | 自身 def 还在；调用者全死（agents/memory.py dead + scheduler/task.py 也将退役 + memory_api.py /todos endpoint 无 caller） |
| **REST `/api/todos/*`** | `memory_api.py:235 /todos/list / 257 /todos/add / 286 /todos/{id}/status` | ⚠️ endpoint 真注册但**前端零 grep / 后端内部零调用** |
| **ToolRegistry 注册** | `tools/registry.py:99` 仅 `clear_short_term` | ❌ 零 add_todo 注册 |
| **Capability 注册** | `grep "name=.*todo" capabilities/` → 零命中 | ❌ 零 todo capability |

→ **add_todo 在 LLM 主路径完全调不到**（既不在 MEMORY_TOOLS 也不在 ToolRegistry 也不在 capability）。

---

### 3 · prompts.py "幽灵工具" — 可删 vs 必留分类

#### 3.0 ChatAgent 主路径 LLM 真看到的工具（基线 = 必留）

`chat.py:594` `MEMORY_TOOLS + ToolRegistry.list_schemas()`：
- **MEMORY_TOOLS**（直接 hardcode 在 chat.py:456-538）：`save_memory / delete_memory / list_memories / compress_memories`（4 个）
- **ToolRegistry**：`clear_short_term`（1 个 builtin） + 56 capability = 57 个
- **总计 = 61 个**（去重后；calendar router 是 capability 中 2 个独立条目）

#### 3.1 PLANNER_AGENT_SYSPROMPT (prompts.py:86-119) 中的工具声明

```
L106  - add_todo(user_id, owner_type, title, description, due_time, status)
L107  - delete_todo(user_id, id)
L108  - search_todo(user_id, id=None, owner_type=None, ...)
L109  - add_personality(user_id, type, tag, content)
L110  - delete_personality(user_id, type, tag)
L111  - search_personality(user_id, type=None, tag=None)
L112  - add_memory(user_id, role, type, content)
L113  - delete_memory(user_id, memory_id)
L114  - search_memory(user_id, role=None, type=None, ...)
L117  - switch_character(...)  ← 已在上一刀清
L118  - clear_short_term(user_id): 清空短期记忆
```

逐个判定（与 `ChatAgent 主路径 61 个真工具` 对账）：

| 工具 | LLM 主路径有同名活实现？ | ToolRegistry 注册？ | 判定 |
|---|---|---|---|
| `add_todo` | ❌ 无 | ❌ 无 | **【真死可删】** |
| `delete_todo` | ❌ 无 | ❌ 无 | **【真死可删】** |
| `search_todo` | ❌ 无 | ❌ 无 | **【真死可删】** |
| `add_personality` | ❌ 无 | ❌ 无；且 `personality` 表已在 v2_5_b migration step 9 **DROP**（`grep services.add_personality` = **零命中**，连 service 函数都不存在） | **【真死可删 · 双重保险】** |
| `delete_personality` | 同上 | 同上 | **【真死可删 · 双重保险】** |
| `search_personality` | 同上 | 同上 | **【真死可删 · 双重保险】** |
| `add_memory` | ❌ ChatAgent 用 `save_memory`（不同名） | ❌ 无 | **【真死可删】** — 删 prompts.py 不影响 ChatAgent `save_memory` 真路径 |
| `delete_memory` | ✅ ChatAgent MEMORY_TOOLS L501 真有 `delete_memory` | ❌（ChatAgent 走 chat.py 内嵌 MEMORY_TOOLS，不走 ToolRegistry） | **【可删·名同·实不依赖此 prompt 段】** — PLANNER prompt 死了，但 ChatAgent 自己的 tool 描述在 chat.py:501-518 + `tool_addendum.py:35` 已完整描述。删 PLANNER L113 字面**不影响** ChatAgent 对此 tool 的认知 |
| `search_memory` | ❌ ChatAgent 用 `list_memories`（不同名） | ❌ 无 | **【真死可删】** — 注意 ChatAgent 是 `list_memories` 不是 `search_memory`；删 prompts.py L114 不损 ChatAgent |
| `clear_short_term` | ✅ ToolRegistry L99 真注册 | ✅ 真注册 | **【必留·活】** — 仅在 PLANNER 段的描述行 L118 是 dead 文本；ChatAgent prompt 真描述在 `tool_addendum.py:38` 真活 |

#### 3.2 PLANNER_AGENT_FEW_SHOT (prompts.py:135-249) 中的 function 字面

```
L145 "function": "add_todo"       【真死可删】
L165 "function": "add_todo"       【真死可删】
L193 "function": "search_memory"  【真死可删】
L210 "function": "search_personality"  【真死可删】
L227 "function": "clear_short_term"  ⚠️ 名同但 PLANNER few-shot 是死路径示例
```

#### 3.3 整段拼装：可删粒度 = 整 PLANNER 段 vs 逐行删

**关键发现**：PLANNER_AGENT_SYSPROMPT / PLANNER_AGENT_INST / PLANNER_AGENT_FEW_SHOT 三个常量**外部唯一 import 源 = `agents/planner.py:52-54`**；planner.py 自身**零外部 import**（确认 `grep -rE "from backend.agents.planner|from \.planner" backend/` = 零命中）。

→ **整 PLANNER 段（prompts.py L86-249）+ planner.py 整文件可一并删除**。`MEM_AGENT_PROMPT`（prompts.py L13-83）也是孤儿（零 grep 命中），可同删。

剩下的 `BASE_INSTRUCTION` (prompts.py L3-12) **必留**——被 `chat.py:51` 和 `prompt_manager.py:26` 真活 import。

---

### 4 · profile_summary 退役范围

#### 4.1 profile_summary 真活依赖（必留 / 暂缓）

**chat.py fallback 真活**：
```python
# chat.py:1390-1398（v4 renderer fail 时 fallback path）
profile_data = await get_profile_data(user_id)
formatted = format_profile_for_prompt(profile_data)
if formatted:
    system_parts.append(formatted)
else:
    async with AsyncSessionLocal() as session:
        summary = await get_profile_summary(session, user_id)   # ← fallback 真活
    if summary:
        system_parts.append("【用户画像】\n" + summary)

# chat.py:1147 renderer path 同样 fallback
```

→ **profile_summary 字段 + services.get_profile_summary / update_profile_summary 是真活依赖**（profile_data NULL/空时兜底注入 LLM prompt）。

**真活写入路径**：
- `users_api.py:154` `PATCH /api/users/{uid}/profile_summary` (@deprecated 但 endpoint 真活)
- `users_api.py:178` `DELETE /api/users/{uid}/profile_summary` (同上)
- `memory_api.py:317` `PATCH /api/profile`（bare /profile，无前端 caller）→ 调 `update_profile_summary`
- **无 cron / 无自动 worker 写它**（chunk 11 cron 写 profile_data 不写 profile_summary）

**真活读取**：
- `chat.py:1148, 1396` — fallback ✅ 真活
- `users_api.py /profile_summary GET` — endpoint 真活
- `users_api.py:86` `/profile` GET 也 return profile_summary 字段 — endpoint 真活
- `memory_api.py:306` bare `/profile` GET — endpoint 真活

#### 4.2 profile_summary 退役时序

| 阶段 | 改动 | 风险 |
|---|---|---|
| **本刀（todos 退役）**：不动 profile_summary | 仅清 dead path（PLANNER prompts.py + memory.py + planner.py）；保留 `services.get_profile_summary` / `update_profile_summary` / `users.profile_summary` DB 列 | 零（todos 与 profile_summary 解耦） |
| **Phase 2（未来）**：profile_summary 真退役 | 删 chat.py fallback + 删 services.get/update_profile_summary + DB 列 SET NULL → DROP COLUMN | 需先确认所有 user 的 profile_data 已 cron 跑过非 NULL |

#### 4.3 结论

**profile_summary 必须暂缓**，不与 todos 这刀同时清。理由：
- chat.py:1148/1396 fallback 真活依赖
- 所有用户的 profile_data 是否都已生成需真机抽样验证
- DROP COLUMN 在 SQLite 是破坏性，无法回退

---

### 实施刀可删清单（精确到文件:行 / 整文件）

#### 【真死可删】(✅ 本刀范围)

**代码删除**：
1. `backend/agents/planner.py` — **整文件删**（零外部 import；MEM_AGENT_PROMPT / PLANNER_AGENT_* 唯一消费者）
2. `backend/agents/memory.py` — **整文件删**（v3-C 已退主路径；handler 表全死 + 引用 service 函数将随 #5 一并清）
3. `backend/config/prompts.py` — **删 L13-249**（保留 L1-12 `BASE_INSTRUCTION`；删 `MEM_AGENT_PROMPT` + `PLANNER_AGENT_SYSPROMPT` + `PLANNER_AGENT_INST` + `PLANNER_AGENT_FEW_SHOT`）
4. `backend/routes/memory_api.py` — **删 L231-293**（`/todos/list` + `/todos/add` + `/todos/{id}/status` PATCH 三个 endpoint） + **删 L296-318**（bare `/profile` GET + PATCH 两个 endpoint，重复且无前端 caller；注意：users_api.py 的 `/users/{uid}/profile` 是另一套，保留）
5. `backend/database/services.py` — **删 `create_todo / get_todos / search_todo / update_todo_status` 4 个函数**（调用者全死后无人调）
6. `backend/scheduler/task.py` — **整文件删**（无活写入源；30s 空轮询；apple_calendar 提醒由 macOS 独立负责）
7. `backend/main.py` — **删 L499-500** `await scheduler.start(default_uid)` + log；**删 L869** `await scheduler.stop()`；**删** scheduler import（顶部）

**Import 清理**：
8. `backend/routes/memory_api.py:30-36` 顶部 import `create_todo, get_todos, search_todo, update_todo_status` 删除（随 #5 / #4 删）
9. `backend/database/models.py` — **保留** `Todo` 类（DB 表本身的 schema 定义）暂不删；与下面 DB 行/表清理 **同步决定**

**DB 删除**（破坏性，分两小步）：
10. `DELETE FROM todos WHERE id=1`（清 1 行 historical 残留）
11. `DROP TABLE todos`（如顾问同意彻底退役表）；若决定保留表壳"以备未来"则跳过

#### 【重名但活·必留】(❌ 本刀不动)

- `chat.py:456-538 MEMORY_TOOLS`（save_memory / delete_memory / list_memories / compress_memories）— ChatAgent 主路径 LLM 真看到的工具，必留
- `chat.py:_tool_save_memory / _tool_delete_memory / _tool_list_memories / _tool_compress_memories` 4 个处理函数 — 必留
- `services.py` 中 memory 相关：`add_memory / delete_memory / get_all_memories / get_memory_by_id / etc` — 被 MEMORY_TOOLS + memory_api.py /memory/* + extractor 真消费，必留
- `services.get_profile_summary / update_profile_summary` — chat.py:1148/1396 fallback 真活，必留（暂缓退役）
- `prompts.py:3-12 BASE_INSTRUCTION` — chat.py / prompt_manager.py 真活 import，必留
- `tools/registry.py:99 clear_short_term` 注册 — 真活，必留

#### 【暂缓项】(⏸ 本刀不动；profile_summary 退役要单独刀)

- `users.profile_summary` DB 列
- `services.get_profile_summary / update_profile_summary`（虽然不在 todos 刀里删，但与 profile_summary 退役一刀挂钩）
- `users_api.py /profile_summary 全套 endpoint`（@deprecated 但活）
- `users_api.py /profile GET`（return profile_summary 字段）
- `chat.py:1148, 1396` fallback 分支
- `frontend/src/lib/profile.ts` 前端 dead client（无人 import，但保留无害；与 Phase 2 同退）

#### ⚠️ 拿不准 / 待人工裁决

- **DB `todos` 表本身是否 DROP TABLE**：DELETE 1 行 + 保留空表（无副作用，未来想恢复 todo 功能可用）vs DROP TABLE（彻底）—— 二选一由顾问决
- **`Todo` ORM class (models.py)** 是否删 —— 跟 DROP TABLE 同步决定
- 前端 `useWebSocket.ts` 中 `alarm` 帧 RECV 分支（变 dead branch）：删 vs 留 —— 留无害，可后续清

---

### 暂停

四项 recon 完成。等顾问核：
1. 实施刀可删清单是否同意（11 项代码删 + 2 项 DB 删）
2. todos 表 DROP TABLE vs 留空表
3. profile_summary 退役是否真按"暂缓"处理

不改任何代码 / DB / commit / stash。

---

## 【前后端对齐 · profile 与 todos 核实 · 2026-05-19 02:21】

只读勘查；未改任何代码 / DB / commit / stash / backend 未启动。

### 核实 1 · `/api/profile` 读写的到底是什么

#### 三套 endpoint + 两个 DB 字段（真值清单）

`backend/routes/users_api.py` 共暴露 **3 套相关 endpoint**：

| Endpoint | 方法 | 文件:行 | 读写 DB 字段 | 状态 |
|---|---|---|---|---|
| `/api/users/{uid}/profile` | GET | `users_api.py:71-87` | 返 `user_name / nickname / language / profile_summary`（**只读 profile_summary，不含 profile_data**） | 活 |
| `/api/users/{uid}/profile` | PATCH | `users_api.py:90-114` | 仅写 `nickname / language` 两列（**不动 profile_summary / profile_data**） | 活；用途窄 |
| `/api/users/{uid}/profile_summary` | GET/PATCH/DELETE/POST regenerate | `users_api.py:117-225` | `users.profile_summary`（Text 自由文本） | ⚠️ **legacy chunk 9**；4 处 @deprecated log warning（"chunk 11 prefers /profile_data"） |
| `/api/users/{uid}/profile_data` | GET/PATCH/DELETE/POST regenerate | `users_api.py:226-440` | `users.profile_data`（Text JSON） | ✅ **chunk 11 新真值**，结构化 7 字段 |

#### DB 字段（`backend/database/models.py:25-29`）

```python
profile_summary = Column(Text, nullable=True)   # legacy chunk 9 free-text profile; retained for fallback
# backend/utils/profile_schema.py PROFILE_SCHEMA_V1。``profile_data`` 优先于
# ``profile_summary`` 注入 system prompt；NULL 时 fallback。
profile_data    = Column(Text, nullable=True)
```

#### profile_data 写入路径（who writes）

| 路径 | 文件:行 | 触发 |
|---|---|---|
| Cron 每日自动重生 | `main.py:521-540` 注册 `profile_daily_regenerate`，调 `backend/services/profile_regen.py:393` | 每日定时；遍历所有 user，调 `_regenerate_profile_data(mode='cron')` |
| 用户手动 incremental / reset | `users_api.py:403-429` `POST /profile_data/regenerate` → `_regenerate_profile_data(mode='manual_incremental' or 'manual_reset')` | 前端手点按钮 |
| 用户手动 PATCH | `users_api.py:374` `u.profile_data = _json.dumps(current, ensure_ascii=False)` | 前端按字段编辑 |
| LLM 写入 | **无**（无 capability / tool 写 profile_data） | — |

→ **profile_data 是 cron daily + 用户手动**双源；无 LLM tool 直接写。

#### profile_data 读取路径（who reads）

`backend/agents/chat.py:1140-1143`：
```python
from backend.services.profile_regen import format_profile_for_prompt, get_profile_data
profile_data = await get_profile_data(user_id)
formatted = format_profile_for_prompt(profile_data)
# → 注入 LLM system prompt
```

→ **profile_data 真注入 LLM system prompt**；NULL 时 fallback 到 `profile_summary`（per models.py 注释）。

#### 前端到底用哪个？

| Frontend 模块 | Endpoint | 状态 |
|---|---|---|
| `frontend/src/lib/profile.ts` | `/api/users/{uid}/profile` + `/profile_summary` 全套 | ⚠️ **legacy chunk 9 client**；仅 4 处 grep 命中，**无任何组件 import 它** —— 前端 dead client |
| `frontend/src/lib/profileData.ts` | `/api/users/{uid}/profile_data` 全套（含 regenerate） | ✅ **chunk 11 真消费者** |
| `frontend/src/components/UserProfileSection.tsx:16-22` | `import { fetchProfileData, patchProfileData, regenerateProfileData } from '../lib/profileData'` | ✅ **真在用**；L53-85 真渲染表单 + 按字段编辑 + regenerate 触发 |

→ **更正 FRONTEND-OVERVIEW §3.2 / BACKEND-OVERVIEW §3 L-? 的"profile PATCH 表单缺位"判定**：错误！前端 `UserProfileSection` 真有 PATCH + regenerate 完整 UI，走 `lib/profileData.ts` → `/api/users/{uid}/profile_data`。这条不算缺口。

#### 结论 — "用户画像"与 `/api/profile` 是同一份吗？

**不是同一份**。

| 概念 | 真值 |
|---|---|
| `/api/users/{uid}/profile` (GET) | 只回 user_name / nickname / language / `profile_summary`（legacy 视图）—— **不含 profile_data** |
| `/api/users/{uid}/profile` (PATCH) | 仅写 nickname / language —— 不动任何 profile 内容 |
| 真"用户画像"（AI 自动总结、进 LLM prompt） | 是 `users.profile_data`（chunk 11 structured JSON）—— 由 cron + 手动 regenerate + 字段编辑 PATCH 三路写，由 `format_profile_for_prompt` 注入 system prompt 读 |
| 真"用户画像"暴露 endpoint | `/api/users/{uid}/profile_data`（GET/PATCH/DELETE/POST regenerate） |
| 真"用户画像"前端入口 | `UserProfileSection.tsx`（真有 UI，走 `lib/profileData.ts`） |
| `profile_summary` | legacy chunk 9 自由文本 fallback，cron 不再写它（@deprecated）；前端 `lib/profile.ts` 客户端存在但无组件 import = dead client |

→ **两套数据并存**：`profile_summary`（chunk 9 legacy fallback）+ `profile_data`（chunk 11 真活）。`/api/profile` GET 只显示 legacy 字段，所以**看 `/api/profile` 不等于看用户画像**；要看真画像要看 `/api/users/{uid}/profile_data`。

---

### 核实 2 · todos 是真接线还是空壳

#### 2.1 DB 表 — schema + 当前行数

```sql
CREATE TABLE todos (
    id INTEGER NOT NULL,
    user_id VARCHAR NOT NULL,
    owner_type VARCHAR NOT NULL,
    title VARCHAR NOT NULL,
    description TEXT,
    due_time DATETIME NOT NULL,
    status VARCHAR,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    CONSTRAINT ck_todo_owner_type CHECK (owner_type IN ('alarm','agent','schedule')),
    CONSTRAINT ck_todo_status     CHECK (status IN ('pending','completed','failed','multiple')),
    FOREIGN KEY(user_id) REFERENCES users (user_id)
);
```

行数：**1**。唯一一行：
```
id=1 | user=default | owner_type='schedule' | title='开会' | due_time=2026-05-03 09:00:00 | status='pending'
```
- 已超期 2 周（今天 2026-05-19）但 status 仍 'pending'，说明 startup `_mark_stale_alarms_failed` 没动它 → 因为它 `owner_type='schedule'` 而非 `'alarm'`，scheduler 不 touch
- 所有 owner_type 'agent' / 'schedule' 行**目前没有任何代码读它**（grep 结果：scheduler 只查 `owner_type='alarm'`）

#### 2.2 LLM tool `add_todo / delete_todo / search_todo` 写入路径

| 路径 | 文件:行 | 状态 |
|---|---|---|
| MemoryAgent handler | `agents/memory.py:157-200` `_handle_add_todo / _handle_delete_todo / _handle_search_todo` | ❌ **DEAD** —— MemoryAgent 已在 v3-C 退出主路径（`ws.py:7-12 / 172` 注释明示"PlannerAgent / MemoryAgent / ToolAgent 仍保留... 但已退出主流程"） |
| ToolRegistry 注册 | `tools/registry.py:99` 仅注册 `clear_short_term`（switch_character 上次刀已下线） | ❌ **未注册 add_todo** |
| Capability registry | `grep "name=.*todo" backend/capabilities/` → **零命中** | ❌ **无 todo 相关 capability** |
| 主聊天 LLM tool 列表 | LiteLLM 把 56 capability + 1 builtin (clear_short_term) 喂给 LLM | ❌ **LLM 当前看不到 add_todo** |

#### 2.3 LLM 是否被 prompt 误告知有 add_todo？

```
$ grep "add_todo" backend/agents/prompt/*.py backend/config/prompts.py
backend/config/prompts.py:106  - add_todo(user_id, owner_type, title, ...)
backend/config/prompts.py:107  - delete_todo(user_id, id)
backend/config/prompts.py:108  - search_todo(...)
backend/config/prompts.py:145  "function": "add_todo",
backend/config/prompts.py:165  "function": "add_todo",
```

⚠️ `backend/config/prompts.py` 的这些命中是在 **`PLANNER_AGENT_SYSPROMPT` + `PLANNER_AGENT_FEW_SHOT`** 内（与上轮删 switch_character 时清理过的 example7 同一文件）—— 该 prompt 路径同 `MemoryAgent` 一样**已退出主流程**（不再被 LiteLLM tool calling 用），所以**LLM 在当前主聊天链中并不真看到这些**。但字面上 prompt 内容仍存在，是上一次清理时**只清了 switch_character、保留了 todo 系**。

主聊天 TOOL_PROMPT_ADDENDUM (`agents/prompt/tool_addendum.py`) **未提及** add_todo / todos —— ChatAgent 主路径 LLM 不会被引导调 todo 工具。

#### 2.4 AlarmScheduler 真活码（读出 todo / 推送 alarm）

| 项 | 文件:行 | 状态 |
|---|---|---|
| 类定义 | `scheduler/task.py:25-143` `AlarmScheduler` | ✅ 活码 |
| Lifespan 启动 | `main.py:499` `await scheduler.start(default_uid)` | ✅ 每次 backend boot 启动 |
| 轮询频率 | `_CHECK_INTERVAL = 30` 秒（`scheduler/task.py:14`） | ✅ |
| 启动时 stale alarm 处理 | `_mark_stale_alarms_failed` —— `owner_type='alarm'` 且超期 → status='failed' | ✅ |
| 周期 due 检测 | `_check_due_alarms` —— `search_todo(owner_type='alarm', due_end=now+1s, status IN ('pending','multiple'))` | ✅ |
| 触发 push | `connection_manager.push(user_id, {type:'alarm', content, todo_id})` 推前端 WS `alarm` 帧 | ✅ |
| 触后更新 | `update_todo_status(todo.id, 'completed')` | ✅ |

**前端 RECV** `alarm` 帧：`useWebSocket.ts:RECV` → `pushNotification(type='alarm')` → `NotificationToast` 显示

→ **AlarmScheduler 是真活码** —— 每 30 秒空轮询；如果有 `owner_type='alarm'` 的 todo 到点，**会**推前端 alarm。

#### 2.5 三选一判定

**实情综合**：
- DB 表 ✅ 存在；数据 1 行（owner_type='schedule'，historical 遗留）
- AlarmScheduler ✅ 活码，30s 轮询，能 push alarm
- LLM 写入路径 ❌ 完全断（MemoryAgent dead；无 ToolRegistry / Capability 注册）
- 前端写入 UI ❌ 无（`MemoryManagerDrawer` 仅管 memory 不管 todos）
- prompts.py PLANNER 段仍写着 add_todo ❌ 但 PlannerAgent dead → LLM 不真看到
- 现实里**有谁能写新 todo 进 DB？答案：没有**

**三选一答案**：以 **② + ③ 混合** 为最准确描述：

| 选项 | 判定 |
|---|---|
| ① 后端真有完整逻辑在运作 | ❌ 不成立 —— 写入面完全断；读出面（AlarmScheduler）虽活但无新数据可处理 |
| ② LLM 被告知有此 tool 但底层空壳/没真效果 | ⚠️ **部分成立** —— PLANNER prompts.py 字面仍告诉 add_todo 存在，但该 prompt 已退主流程；ChatAgent 主 prompt 未告知，所以实际 LLM 不会被引导调（"silent" 程度比 switch_character 低） |
| ③ 曾经有、现在被某机制替代 | ✅ **大部分成立** —— v3-C 退 PlannerAgent / MemoryAgent 后，"加待办 / 提醒"的真正落点是 `apple_calendar.create_event`（chat.py TOOL_PROMPT_ADDENDUM L18-27 主推此路径）+ `time.now` 时间锚。todos 表 + AlarmScheduler 是上一代提醒架构的**孤儿活码**：表存在、轮询在跑、但写入端已迁走 |

#### 2.6 "名实不符"清单

| 项 | 名（prompts.py 告诉 LLM 的） | 实（实际能否调到） |
|---|---|---|
| `add_todo` | "可调用"（prompts.py:106） | ❌ ToolRegistry 无注册，ChatAgent LLM 调不到（即使 LLM 试图调，会 missing-tool 错误） |
| `delete_todo` | 同上 | ❌ 同上 |
| `search_todo` | 同上 | ❌ 同上 |
| MemoryAgent 整路（add_memory / delete_memory / search_memory / add_personality / delete_personality / search_personality / get_profile_summary / update_profile_summary）| prompts.py:106-114 列了 | ❌ 同样 dead path；其中 memory 系功能由 ChatAgent 主路径的 `list_memories / save_memory / delete_memory / compress_memories` capability **替代实现**（重名但实现路径不同：通过 capability 注册） |

→ "名实不符"集中在 `backend/config/prompts.py` 的 PLANNER_AGENT_SYSPROMPT / FEW_SHOT 段，**整个段都是 PlannerAgent dead path 的残留**。上次刀只动了 switch_character 那一处，没动 MemoryAgent / ToolAgent / add_todo 等。

但**影响很小**：因为 PlannerAgent 不再被调，这段 prompt 不会真送进 LLM；只在阅读源码时让人误以为 LLM 会调 add_todo。建议后续清 PLANNER prompts.py 时一并扫掉。

#### 2.7 todos 处置建议（CC 给依据，不替决）

| 方案 | 内容 | 风险 |
|---|---|---|
| A | **真退役** —— 停 AlarmScheduler、删 todos 表、清 PLANNER prompts.py 残留 | 低（无人写入、无人读出真数据）；reversal 容易（保留备份） |
| B | **半保留** —— AlarmScheduler 保持活，预留 v4.x 接 capability `task.create` / `task.list`（绕过 MemoryAgent dead path），让 LLM 重新能写 todo | 中（要做新 capability，但能恢复"提醒"原能力） |
| C | **现状保留** —— 不动；接受"孤儿活码" 30s 轮询的小开销 | 零；但 prompts.py:106-114 的"名实不符"困惑保留 |

CharAgent 当前替代方案：日历事件（`apple_calendar.create_event`）已覆盖"加提醒"需求；todos 路径**用户感知层无缺**。

---

### 暂停

两条核实完成；无任何代码 / DB 改动。等顾问决：① profile_summary 是否真退役清栏 ② todos 走 A/B/C 哪条路。

---

## 【后端收尾 · 文档止血整合 · 2026-05-19 01:16】

### 前置自检

- 5 个主文档（README.md / README_zh-CN.md / ROADMAP.md / DESIGN.md / DESIGN_LITE.md）全部 clean（无未提交改动）
- `git stash list`：`stash@{0}` 未动
- HEAD = `71b6e99 refactor(character): 下线 switch_character LLM tool（充分档）`

### 任务 A — ROADMAP.md 历史日志外迁

#### A1 边界自核（只读）

ROADMAP.md 二级/三级标题分布：

```
L1   # 🗺️ Skyler Roadmap
L11  ## Now — v4.0.0 收口
L15  ### 本 session 已 ship 并真机验证(v4-beta 收口批次,2026-05-16)
L27  ### 剩余 v4.0.0 收口项(按序)
L42  ## v4.1 — Mai 之外 + 语言/记忆根治
L60  ## Next — 补诚实承认的缺口
L72  ## Later — Persona-level learning
L84  ## Long vision
L95  ### 长期技术能力扩展
L108 ## Tech Debt & Backlog
L143 ### 遗留测试债
L159 ## Not on the roadmap(明确不做)
L173 ---
L174 (blank)
L175 ## Implementation Log (Historical)      ← 边界
L183 ### v4-beta 收口批次(2026-05-16)
L204 ### 当前进度速览
L257 ### 三梯队优先级矩阵
L307 ### 详细执行清单
L630 ### v3 封盘 Retrospective
L1109 ### v3.5 后续路线（v3 封盘后的连续推进）
L1610 ### 建议下一步
L1651 (EOF)
```

L173-174 前置 `---` + 空行 + L175 标题构成清晰断面；L177-179 的引导段明示"下面这部分是之前以版本号 / chunk 组织的实施记录,完整保留以便追溯。新路线图按上面四条北极星支柱组织未来工作"。

**结论行**：真·路线图 = L1 ~ L174（174 行）；历史日志 = L175 ~ L1651（1477 行）。L175+ 全部为 chunk / retrospective / 历史小结，无未来路线内容夹杂（已 grep 所有 `## / ###` 实证）。

#### A2 执行外迁

实际操作（byte-perfect 搬运，避免 Read→regenerate→Write 字符漂移）：

```bash
# 1. 提取 L175-1651 到 IMPLEMENTATION_LOG.md（带 2 行 + 1 空行 header）
sed -n '175,1651p' ROADMAP.md > /tmp/roadmap_historical.md   # 1477 行
{ printf '> 本文件为 ROADMAP.md 外迁的历史实现日志，原属 ROADMAP，2026-05-19 拆出。\n> 内容字字保留未改；新路线图请见 ROADMAP.md。\n\n'; cat /tmp/roadmap_historical.md; } > IMPLEMENTATION_LOG.md
# 结果：1480 行

# 2. 重建 ROADMAP.md = L1-174 + 1 行指针
{ sed -n '1,174p' ROADMAP.md.orig; printf '> 历史实现日志已外迁至 IMPLEMENTATION_LOG.md\n'; } > ROADMAP.md
# 结果：175 行
```

未触历史日志**内容本身**（一字未改）；未触 ROADMAP 前 174 行（真·路线图原样保留）。

#### A3 完整性自核（行数 + sha1 + 标志性 chunk 命中分布）

**行数算式**：

| 项 | 行数 |
|---|---|
| 搬运前 ROADMAP | 1651 |
| 搬运后 ROADMAP | **175** = 174 kept + 1 pointer |
| IMPLEMENTATION_LOG | **1480** = 3 header + 1477 historical |
| 175 + 1480 | = **1655** |
| 1655 - 1651 | = **+4 行** = 3 header + 1 pointer ✅ |

算式平衡。

**byte-perfect 校验（sha1）**：
```
extract source sha1      : c7419646991837c65adae8533651043ae2dd06e7
IMP_LOG tail-1477 sha1   : c7419646991837c65adae8533651043ae2dd06e7
→ byte-perfect 一致 ✅
```

**标志性 chunk 标题分布**：

| 标志 | ROADMAP 命中 | IMP_LOG 命中 | 判定 |
|---|---|---|---|
| `chunk 14` | 1（L132 Tech Debt 中合法引用） | 1 | 残留 = 0；ROADMAP 命中是真·路线图段的合法引用 |
| `v3-E1` | 0 | 15 | ✅ 搬干净 |
| `v3-G'` | 0 | 10 | ✅ 搬干净 |
| `v4-beta 收口批次` | 1（L15 Now 段标题"本 session 已 ship 并真机验证(v4-beta 收口批次,2026-05-16)"，合法） | 2 | 残留 = 0 |
| `v3 封盘` | 0 | 5 | ✅ 搬干净 |
| `v3.5 后续路线` | 0 | 1 | ✅ 搬干净 |

ROADMAP 的 2 处命中实读位置在 L15 / L132 真·路线图段内，是 Now 与 Tech Debt 节的合法字面引用，**非历史日志残留**。sha1 byte-perfect 一致是最强证据。

### 任务 B — DESIGN_LITE.md §4 补漏表

#### B1 核对（只读）

DESIGN_LITE §4 当前列出的表（10 项）：
```
characters / character_personas / character_personas_builtin_seed / character_states /
memory / chat_history / activity_sessions / tts_call_log / voice_aliases / users.profile_data
```

对照 momoos.db 22 表：
- ✅ `voice_aliases` 已在 L213-217（无需补）
- ❌ `conversation_summary`（v4.0.0 b91505a 新引入）— **缺**
- ❌ `mcp_credentials / mcp_client_state / mcp_tool_state`（MCP 三表）— **缺**

#### B2 补充内容 + B3 diff

仅追加上述缺失项，未改 §4 已有任何条目。完整 diff：

```diff
@@ -196,6 +196,14 @@
 > **v4-beta**:chat_history 是对话存档 + restore 源...

+### conversation_summary(v4.0.0 b91505a 有界滚动摘要层)
+```
+id, user_id, character_id, conversation_id,
+summary_text, last_folded_chat_history_id, token_budget, updated_at
+UNIQUE(user_id, character_id, conversation_id)
+```
+> 给每个 (user, character, conversation) 三元组维护一份滚动摘要,
+> worker(`backend/memory/summary.py`)按 `last_folded_chat_history_id`
+> 增量折叠超出 short_term cap 的旧 turn 进 `summary_text`;
+> ChatAgent 注入 prompt 时取最新一行。补 short_term 硬性 cap 30 turn
+> 之外的"中期记忆"层。
+
 ### activity_sessions(v3.5 chunk 14)
@@ -216,6 +224,14 @@
 ### voice_aliases(v4-beta Bugfix-3.4)
 voice_id(PK), display_name 给 cloned voice 起友好名,UI 显示用

+### mcp_credentials / mcp_client_state / mcp_tool_state(MCP 配置 + 启用态)
+```
+mcp_credentials  : id, server_name, key_name, value, updated_at  (UNIQUE server+key)
+mcp_client_state : server_name(PK), enabled, updated_at
+mcp_tool_state   : id, server_name, tool_name, enabled, updated_at  (UNIQUE server+tool)
+```
+> 三表分管 MCP server 的凭证 / client 启停态 / 单 tool 启停粒度。
+> `mcp_client.py` 启动按 `mcp_client_state.enabled=1` 拉起 server,
+> 按 `mcp_tool_state.enabled` 决定 tool 是否注册进 ToolRegistry;
+> UI 的 MCP 面板 CRUD 走 `routes/mcp.py`。
+
 ### users.profile_data(v3.5 chunk 11)
```

插入位置：
- `conversation_summary` 插在 `chat_history` 之后、`activity_sessions` 之前（memory cluster 内的"中期记忆"层，逻辑相邻）
- `mcp 三表` 插在 `voice_aliases` 之后、`users.profile_data` 之前（utility 类聚合，与运行时配置相邻）

#### Scope 自审

初版我额外加了一段 `memory_tombstone`，**超出用户列出的 scope**（conversation_summary / voice_aliases / mcp 相关）。已 revert 该段，严格回 scope。memory_tombstone 是 v4.0.0 b91505a 同期姊妹表（3f3be08），若需补可在下一轮单独追加。

### git status — 改动范围核验

```
 M DESIGN_LITE.md      ← 本刀任务 B
 M ROADMAP.md          ← 本刀任务 A（搬出 1477 行 + 加 1 行指针）
 M config.yaml         ← 既有豁免件
?? IMPLEMENTATION_LOG.md  ← 本刀任务 A 新文件
其余 untracked 原样
```

本刀涉及恰好 3 个文件（ROADMAP / DESIGN_LITE / IMPLEMENTATION_LOG），全部文档类。**零代码 / 零 DB / 零 commit / 零 push / 零 stash 动作 / 零 backend 启动**。

### 暂停

等顾问核：① ROADMAP 真·路线图 L1-174 未被误伤 ② 历史日志 1477 行 byte-perfect 搬运（sha1 证据）③ DESIGN_LITE §4 补漏 in-scope 无溢出。核过后决定是否 commit（3 个文件分一个 commit / 两个分别 commit 均可）。

---
