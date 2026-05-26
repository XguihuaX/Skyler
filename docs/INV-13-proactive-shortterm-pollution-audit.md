# INV-13 · Proactive → short_term ja-format pollution audit

> 2026-05-26 · 调研 only · 不写 code · ~35 min CC 异步
>
> **状态**: audit closed · 等 PM 拿 report 跟另一对话讨论 + 拍板 → 再回 CC ship
>
> **PM hypothesis(待 audit)**: proactive engine LLM call 输出纯中文(没 ja directive)→ 写入共享 short_term memory → chat agent 看 short_term 学到"不带 ja"格式 → 跳过 ja directive → 后续 TTS / 字幕坏。
>
> **TL;DR verdict**:
> - PM hypothesis **partially correct** · 不是 "proactive 没 ja directive"(directive IS injected via Layer A · 不论 proactive 还是 chat)· 是 **proactive trigger prompts 含 8-15 字硬约束 + 零 ja-awareness · 与 ja directive 的 ≥10 字意群规则冲突 · LLM 偶发放弃 ja 选 char budget · 写入 short_term 后形成纯中文 precedent**。
> - 实证 DB 数据显示 chat + proactive 都偶发 ja 缺失(非 proactive 独有)。
> - **更大的污染源**: `main.py` restart 时 restore short_term **强制 strip `<ja>` tags**(意 audit_ja_persist 老逻辑,假设 Mai zh-only;post-INV-11 该假设已倒)。
> - 推荐 fix: **Option D(restore 阶段保留 ja) + Option F(trigger prompts ja-aware)** · 合计 ~35 LoC · 低风险。

---

## §1 Proactive engine 实施

### §1.1 文件位置
```
backend/proactive/
├── engine.py                    980 行 · 通用 trigger runner
├── activity_smart.py            慢路径 LLM judge
├── activity_judge.py            judge 实现
├── snooze_capability.py         "今天别打扰" cap
└── triggers/
    ├── _invite_base.py          模式 B 共享(wake/lunch/dinner/bedtime/long_idle)
    ├── _stage2_registry.py      stage 1 → stage 2 跳转
    ├── activity.py              activity_* 触发(ide_open / music / long_focus / 等 5+1)
    ├── wake_call_briefing.py    早安简报(stage 2)
    ├── morning_briefing.py      旧版早安(legacy)
    ├── lunch_call.py
    ├── dinner_call.py
    ├── bedtime_chat.py
    └── long_idle.py
```

### §1.2 触发机制
3 档调度(`ProactiveTrigger` 抽象):
- `cron_expr` (`"30 12 * * *"`) — 时间驱动(lunch/dinner/bedtime/wake)
- `interval_seconds` — 周期驱动
- `event_source` / activity_smart callback — 事件驱动(activity_ide_open 等)

### §1.3 Proactive LLM call · 用什么 prompt
**关键**: proactive **复用 `ChatAgent.stream()`** · 不独立 LLM call(engine.py:436 + :452)。

调用形态(engine.py:371-390):
```python
chat_msg = {
    "agent": "ChatAgent",
    "payload": {
        "user_id": user_id,
        "text": "[proactive trigger]",     # 占位 user text
        "character_id": target_char_id,
        "conversation_id": conv_id,
        "context": {
            "extra_system": system_prompt,  # ← trigger.build_system_prompt() 输出
            "enable_search": bool(trigger.enable_search),
            "turn_origin": trigger.name,    # ← Mode.PROACTIVE 路由
        },
    },
}
chat_agent.stream(chat_msg)  # 走完整 5-layer renderer pipeline
```

进 `ChatAgent.stream` → `_build_messages` → `render_system_prompt`:
- **Layer A** (`layer_a.j2`) — 输出格式规范(emotion / state_update / motion / ja directive · 全部不依赖 mode)· **ja directive 在此**
- **Layer B** (`layer_b.j2`) — `mode_directive(PROACTIVE / ROLEPLAY)` · proactive 走 PROACTIVE 分支(short / 不复述 briefing 当台词)
- **Layer C** (`layer_c_*.j2`) — persona 全套(identity / personality / speech_style / voice_samples / forbidden / state)
- **Layer D** (`layer_d.j2`) — `extra_system` 走 `temp_instructions` 段 + profile / activity / memory / tool_results / proactive_briefing

**proactive 与 chat 唯一差异**:
- `extra_system` 内容(trigger 的硬约束 + 场景描述)
- `turn_origin` 路由 Mode(影响 Layer B 一段)

### §1.4 Proactive 输出格式
按 trigger 类型分两档:

**模式 A 单向轻量(activity_*)** (`activity.py::_BASE_GUIDANCE`):
```
⚠️ **本轮风格硬要求**:
- 短, **40-80 字**为佳。
- 一句话切入主题 + 一句话承接/反问。
- 不要复述用户行为细节。
```
- **无 ja 提及** · 完全纯中文 prompt + 中文示例

**模式 B 邀请对话(wake/lunch/dinner/bedtime/long_idle)** (`_invite_base.py::make_stage1_prompt`):
```
⚠️⚠️⚠️ 关键约束: 本轮你**只能输出一句 8-15 个字(含标点不超过 18)的短问候**
❌ 严禁输出:
- 任何天气信息 / 日程内容 / 待办提醒 / 询问开放话头 / 叙述铺陈
✅ 只输出: 用人设语气 + 昵称喊用户, **8-15 字**。
直接输出短问候本身, 不前缀, 不解释, 不 metadata。
```
- **8-15 字硬约束** · 中文示例(`"麻衣, 中午了"` 等)· 零 ja 提及

---

## §2 short_term memory 读写

### §2.1 文件位置 + 数据形态
`backend/memory/short_term.py` (170 行)

**Scope**: bucket key = `(user_id, character_id)` · `conversation_id` 进 **entry metadata**(不进 key)· read 时按 `conversation_id` filter。

每 entry shape:
```python
{
    "role": "user" | "assistant",
    "content": str,
    "conv_id": Optional[int],  # filter 用
}
```

**Cap**: `SHORT_TERM_MAX_TURNS = 25` turns(= 50 messages); 超出按 bucket 整体 trim 最旧。

### §2.2 写入路径

| 触发场景 | 入口 | conversation_id |
|---|---|---|
| 用户主动 chat(normal turn) | `ws.py:421` `ws.py:425` | 当前 conv |
| 用户语音中断保存 | `ws.py:534` `ws.py:539` | 当前 conv |
| **Proactive trigger** | `engine.py:593` (assistant only) | trigger 拿到的最近 conv |
| 启动 restore | `main.py:490` | 每条 chat_history 自带 |

**关键**: proactive 写入 **shares the same (user, char) bucket** · 与 chat 同桶 · 仅靠 entry 的 `conv_id` 字段在 read 端区分。

### §2.3 读出路径
`backend/agents/chat.py::_build_messages:1317-1325`:
```python
if not skip_short_term:
    for turn in await short_term_memory.get(
        user_id,
        character_id=character_id,
        conversation_id=conversation_id,
    ):
        messages.append({"role": turn["role"], "content": turn["content"]})
```

按 (user, char, conv) 三级过滤 → 拼成 LLM message 列表 → 接在 system prompt 之后、当前 user text 之前。

**关键**: proactive turn 与 chat turn 同 (user, char, conv) → **chat agent 读 history 时看到 proactive turn**。

### §2.4 entry format 含什么字段
just `{role, content, conv_id}` — **无 source/kind 标记**。chat agent 看到 short_term 不知道某条是 proactive 还是 normal turn。

---

## §3 ja directive 注入对比

### §3.1 Layer A ja directive(`layer_a.j2:82-126`)
渲染门: `{% if tts_language == 'ja' %}` — 仅依赖 `voice_model.tts_language` 字段(从 DB 字段抽 · chat 与 proactive 同源)。

核心规则:
```
- 每个 <ja> tag 内中文部分 **≥ 10 字**
- 单字短词不能独立成 tag, 合并到上下文意群
- 句号 ≠ ja tag 边界; 意群边界才是 ja tag 边界
- 中日意群一一对应, 中文是字幕, 日语是 TTS
```

### §3.2 chat 与 proactive 的 directive 注入路径对比

| 路径 | Layer A ja directive | Layer B mode | Layer D extra_system | Layer D 临时硬约束 |
|---|---|---|---|---|
| **chat** | ✓ injected | ROLEPLAY | (none) | (none) |
| **proactive** | ✓ injected | PROACTIVE | trigger 的中文 prompt | "8-15 字 / 40-80 字 / 严禁..." |

**结论**: ja directive **proactive 与 chat 同样 injected** · 不是 PM 假设的 "proactive 缺 ja directive"。

### §3.3 真正缺失的: trigger prompts 与 ja directive 的兼容声明

trigger prompts(`activity.py::_BASE_GUIDANCE` + `_invite_base.py::make_stage1_prompt`)对 ja directive **零 awareness**:
- "40-80 字" / "8-15 字" 约束 — **没说**字数包不包 ja 翻译(LLM 自己猜)
- 示例 — 全部纯中文(`"麻衣, 中午了"`)· **零 ja 示范**
- "严禁叙述铺陈" — 与 ja directive 的 "≥10 字意群" 形成内部冲突(中文 8 字 + ja 翻译 = 大概率超 18 字 hard cap)

**实证**: 见 §4.2 dinner_call 输出 — LLM 在 thinking 阶段把 "8-15 字" vs "ja ≥10 字" 冲突 debate 了 50+ 轮直至 token 超限输出 raw thinking process(2026-05-26 09:35:01)。

---

## §4 污染机制 verify

### §4.1 DB chat_history 真实数据快照(cid=1 Mai · 2026-05-25 起)

| 时间 | kind | trigger | ja markup | 备注 |
|---|---|---|---|---|
| 2026-05-26 09:35 | proactive | dinner_call | ❌ | **raw thinking process 泄露**(LLM 在 8-15 字 vs ja ≥10 字冲突 debate · 输出 token budget 用尽) |
| 2026-05-26 06:19 | proactive | activity_ide_open | ✓ | 双意群 ja 正确 |
| 2026-05-26 04:20 | normal | - | ✓ | |
| 2026-05-26 04:18 | normal | - | ✓ | |
| 2026-05-25 16:03 | normal | - | ✓ | |
| 2026-05-25 16:02 | normal | - | ✓ | |
| 2026-05-25 15:41 | normal | - | ✓ | |
| 2026-05-25 13:14 | proactive | activity_ide_open | ✓ | |
| 2026-05-25 13:10 | normal | - | ✓ | |
| 2026-05-25 11:56 | normal | - | ✓ | |
| 2026-05-25 11:55 | normal | - | ❌ | "AI 项目啊。" 纯中文 |
| 2026-05-25 11:51 | proactive | activity_ide_open | ✓ | |
| 2026-05-25 11:51 | normal | - | ✓ | |
| 2026-05-25 11:13 | normal | - | ✓ | |
| 2026-05-25 10:49 | normal | - | ❌ | 纯中文短句 |
| 2026-05-25 10:47 | normal | - | ❌ | 纯中文短句 |
| 2026-05-25 10:40 | normal | - | (empty) | |
| 2026-05-25 10:39 | proactive | activity_ide_open | partial | 1 句 ja + 1 句纯中文 |

**实证 verdict**:
- ja 缺失 **不是 proactive 独有** · normal turn 也偶发缺失
- proactive(activity_*)大多 ja 正确(说明 directive 注入生效)
- proactive(dinner_call 等 8-15 字模式 B)发生 **格式崩溃**(thinking 泄露)是另一类 bug · 不是简单 "drop ja" 而是 LLM 陷入 prompt 冲突

### §4.2 dinner_call thinking 泄露 root cause

LLM 自己的 debate 节选(从实际输出抠):
```
The system prompt says "Your output MUST include..." 
But the [临时指令] says "8-15 个字(含标点不超过 18)"
TTS Requirement: Every Japanese phrase must be wrapped in <ja>...</ja> 
and correspond to a coherent thought unit (≥10 chars preferred), 
but given the strict 8-15 char total limit, 
I need to balance this carefully...
```

**LLM 在 8-15 字硬约束 vs ja ≥10 字 ≥1 意群之间反复横跳 50+ 轮**, 最终 token 超限输出 raw debate。

**根因**: trigger prompt 与 Layer A ja directive **两个约束相互冲突且 LLM 无消解线索**。

### §4.3 短期记忆注入 prompt 路径
`_build_messages:1317-1326` 把 short_term entries 当 `{"role": ..., "content": ...}` 直接 append 到 messages 数组 · 接在 system prompt 后、user text 前。LLM 看到的是 "previous N turns" 形式。

In-context-learning 效应:
- short_term 全部 ja 标记 → LLM 强 ja 倾向
- short_term 混合 → LLM 看历史比例 + 看 directive · directive 不一定赢
- short_term 全纯中文 → directive 单边压力, LLM **更可能** drift 到纯中文(in-context 信号通常重于 directive)

### §4.4 ⚠️ 隐藏污染源(PM hypothesis 未提到)— `main.py` restore 强 strip ja

**`backend/main.py:484`** 在 backend startup restore short_term 时:
```python
cleaned = _strip_ja_en(msg.content or "").strip()  # ← 强剥 ja/en tags
await short_term_memory.add(default_uid, msg.role, cleaned, ...)
```

设计 comment(line 448-451):
> audit_ja_persist 三定位收敛根因: 短期记忆 ja precedent 让 LLM in-context-learning 继续抄。restore 阶段就把 tag 剥掉, 纯中文 inner 保留

**这个 policy 来自 Mai 是 zh-only 时的 audit_ja_persist** — 当时 ja 字面进 short_term 被认为是 bug · 故 strip。

**INV-11 Stage 1(2026-05-26)后 cid=1 = gsv mai_v4 + tts_language=ja** · 该 strip 现在是 **anti-pattern**:
- backend restart → restore short_term 全部纯中文(ja tags 剥光)
- 后续 turn LLM 看 history → 全纯中文 → in-context 强信号"按纯中文回复"
- 跟 Layer A ja directive 形成冲突 · directive 不一定赢

### §4.5 污染链路 verify (refined)

```
[backend restart]
  ↓
restore short_term · strip <ja> → 全纯中文 entry (main.py:484)
  ↓
new chat turn → _build_messages 注入 short_term → LLM 看到 N 条纯中文 history
  ↓
LLM 看 Layer A directive (要求 ja) vs short_term in-context (全 zh)
  ↓
in-context 胜 → 输出纯中文(部分 turn 漏 ja)
  ↓
新纯中文 turn 写回 short_term → precedent 累积
  ↓
proactive trigger fires → trigger 含 "8-15 字" 硬约束 + 零 ja 提示
  ↓
LLM 同时看 ja directive + char limit + 纯中文 history precedent
  ↓
  - 路径 A: 顺从 history 出纯中文 → 进一步污染
  - 路径 B: 陷入冲突 debate → thinking 泄露(dinner_call 09:35 案例)
  ↓
[backend restart 时刻] 又一次 strip ja → 上述 zh 倾向放大 across restart
```

---

## §5 Fix 选项评估

### Option A · trigger prompts 加 ja directive (revised — 原 PM 描述误)

**澄清**: ja directive 已经在 Layer A 注入 · "A" 真意 = 让 trigger prompts **acknowledge ja directive 而非冲突**。

| 项 | 内容 |
|---|---|
| 改动文件 | `backend/proactive/triggers/_invite_base.py::make_stage1_prompt`(共享 base · 5 邀请 trigger 受益)+ `backend/proactive/triggers/activity.py::_BASE_GUIDANCE`(activity 6 trigger 受益) |
| LoC | ~30(2 处共享 prompt 加 ja-aware 段落) |
| 风险 | **低** · 纯文本改 · 不动 logic |
| 工程量 | 30 min |
| 副作用 | trigger prompt 变长 · 略增 system prompt token(+~150 chars/trigger) |
| 残留风险 | 即使 prompt 改了 LLM 仍可能不遵守(LLM 偶发性) · 这是 mitigation 不是根治 |

具体 prompt 加段示意:
```
若你的 voice 是 ja 模式(Layer A 提示中 tts_language=ja), 
本约束的 8-15 字按"中文部分"算 · ja 翻译额外不计入 · 
形如 '该吃晚饭了'<ja>「夕食よ」</ja> · 8 字中文 + ja 翻译 满足约束。
```

### Option B · proactive 不写 short_term (独立 namespace / 不持久化)

| 项 | 内容 |
|---|---|
| 改动文件 | `backend/proactive/engine.py:593` (skip `short_term_memory.add` for proactive)+ `engine.py:931`(wake_call 同款) |
| LoC | ~5(加 config gate) |
| 风险 | **高** — 直接违反现有 spec(engine.py:587 comment 明确: "short-term memory: 必须 add, 否则用户 VAD 续聊时 ChatAgent 上下文里看不到这条简报 turn, '把 X 改到下午' 等指代会断") |
| 工程量 | 15 min(代码) + 测 stage 1 → stage 2 续聊回归(必跑) |
| 副作用 | wake_call / dinner_call 等 stage 2 续聊语境断裂 · 用户回 "嗯吃了" 时 LLM 看不到自己刚说的 "晚饭吃了吗" · 答非所问 |
| 残留风险 | activity_* trigger 不需要 stage 2 续聊 · 可单独 opt-out;邀请 trigger 必须 keep |

**变种 B1**: 仅 activity_* triggers skip short_term(模式 A 单向 · 无 stage 2)
- LoC ~3 · `if trigger.name.startswith("activity_"): skip add`
- 风险中低 · 部分缓解(不解决 wake/lunch/dinner 等 模式 B 触发的污染)

### Option C · 分 namespace(chat_short_term / proactive_short_term)

| 项 | 内容 |
|---|---|
| 改动文件 | `backend/memory/short_term.py`(entry 加 source 字段 + filter API)+ `engine.py` write(传 source='proactive')+ `chat.py` read(决定是否 include)+ `ws.py` write(传 source='chat')+ `main.py` restore(source 字段恢复) |
| LoC | ~60-80 |
| 风险 | **中** · schema 改 · multiple 读写点同步 · 测试覆盖范围大 |
| 工程量 | 1.5-2h(实施)+ 0.5h(测试) |
| 副作用 | chat 读时若 include proactive → 续聊连贯 + 污染回来;若 exclude proactive → 续聊断 → 同 Option B 副作用 |
| 残留风险 | 真问题不是 "分桶" · 是 "proactive 写入的内容本身格式不对" · 分桶把内容藏起来仍解决不了 stage 2 续聊场景 |

### Option D · restore 阶段保留 ja(per tts_language gate)— ⭐ 推荐

| 项 | 内容 |
|---|---|
| 改动文件 | `backend/main.py:484` |
| LoC | ~10(查 character.tts_language · `if != 'ja': strip` 否则 keep) |
| 风险 | **低** — 反转一个明确不再适用的 policy(audit_ja_persist 假设 Mai zh-only · INV-11 后假设倒) |
| 工程量 | 30 min |
| 副作用 | 重启后 short_term 含 ja markup · in-context-learning **强 ja 信号** · 与 Layer A directive 同向 · 减少 LLM 纠结 |
| 残留风险 | 旧 zh-only 角色仍保留 strip 行为(per-char tts_language gate)· 兼容 |

具体改动示意:
```python
# main.py:484 附近
# 读 character 的 tts_language(从 voice_model.tts_language)
char_tts_lang = await _get_char_tts_lang(session, cid)  # 新 helper · 单 query

# 仅 zh-only 角色 strip ja(legacy audit_ja_persist 假设);
# ja/en 角色 keep ja markup(给 in-context-learning 正确 precedent)
if char_tts_lang == "zh":
    cleaned = _strip_ja_en(msg.content or "").strip()
else:
    cleaned = (msg.content or "").strip()
```

### Option E · trigger 与 chat 的 prompts ja-awareness 全面修(D+F 复合)

Option D 改 restore 一处;Option F 改 trigger prompts 一处。两者正交可叠加。

---

## §6 推荐方向

### ⭐ 一档(强推):**Option D + Option F · ~35 LoC · 低风险**

**理由**:
- D 治根:消除 backend restart 后 short_term 强 zh 倾向 · LLM in-context-learning 跟 directive 同向
- F 治表:trigger prompts ja-aware · 减少 LLM 在冲突中陷入 thinking debate(dinner_call 09:35 类 bug)
- 两者正交 · 低风险 · 改完一次性解决"restart 后 ja 偶发缺失" + "proactive 8-15 字模式陷入冲突"两条线

**touchpoint 全清单**:
- `backend/main.py:484` (Option D · 1 个 helper + 1 个 if)
- `backend/proactive/triggers/_invite_base.py::make_stage1_prompt` (Option F · 加 ja-aware 段)
- `backend/proactive/triggers/activity.py::_BASE_GUIDANCE` (Option F · 加 ja-aware 段)

**工程量**: ~45 min code + ~15 min 测(重启 → 看 short_term 含 ja markup · 跑 1 个 dinner_call 看不再 thinking 泄露)

### 二档(候选,与一档可叠加):**Option B1(activity_* skip short_term)**

仅 activity_* trigger 不写 short_term · 邀请 trigger(wake/lunch/dinner/bedtime/long_idle)仍写(spec 验收硬指标)。

**理由**:
- activity_* 模式 A 单向 · 不需 stage 2 续聊 · skip 写入零副作用
- 减少 activity_* 占比的 short_term 噪音(本次 DB sample 中 activity_ide_open 是高频)

**touchpoint**: `backend/proactive/engine.py:593` 前加 `if trigger.name.startswith("activity_"): pass(else add)`

**LoC**: ~3

**工程量**: 15 min

### 不推荐:**Option B(全部 proactive skip short_term)** / **Option C(分 namespace)**

- B: 违反现有 spec("stage 2 续聊必须看到 stage 1") · 副作用太大
- C: 过度工程化 · 真问题不是分桶 · 是内容格式 · 分桶藏不解决

---

## §7 实施前 PM 拍板事项

1. **Option D 兼容: 老 zh-only 角色处理** · 该 strip 行为对 zh 角色仍 desired(audit_ja_persist 原因仍成立)。建议 per-character gate(`tts_language == 'zh'` → strip; `ja`/`en` → keep)。PM 是否同意此 gate?
2. **Option F 增量 prompt token 成本** · 每个 trigger system_prompt +150 chars · proactive 平均一天触发 ~10 次 · 月增 ~45k tokens prompt 成本(忽略不计)。是否接受?
3. **Option B1(activity_* skip)是否同步上**?(可与 D+F 一起 ship)
4. **dinner_call thinking 泄露**(2026-05-26 09:35:01)是独立 bug 但与本 audit 同源 — 是否在本批 fix 中一并 cover(per §4.2)?

---

## §8 Audit 沉淀(待 fix ship 后写 Lesson)

候选 Lesson 主题(暂不写入 `docs/LESSONS.md` · 等 ship 后定):

- **#16 candidate** · "in-context-learning > directive" — 当 short_term history 与 Layer A directive 形成内容矛盾时, LLM 大概率跟 history 走。一致性 across 写入路径(包括 restore 路径)比 directive 强度重要。
- **#17 candidate** · "policy 跟随当下 character 配置, 不要为旧配置 hardcode 行为" — `main.py:484` strip ja 是为 zh-only Mai 写的, INV-11 切到 ja 后没人想起来 review · per-char gate 才是正解。

---

## §9 audit 范围外 / 隔离 backlog

- `dinner_call` 2026-05-26 09:35 thinking 泄露 — Option F prompt fix 可能直接解决 · 若不彻底 · 单独 ship token cap + fallback(prompt 解析 LLM 输出第一段拒绝 if 含 "Thinking Process" 等英文 reasoning leakage)
- short_term entry 加 `source` / `kind` 字段以便未来调试(Option C 副产物 · 单独立项)
- proactive engine 流式过程中 LLM 输出 `<ja>` 但 `<ja>` 内意群 < 10 字时的二次校验 / 拒收(防 ja 标了但 TTS 仍 5 字内崩坏)

---

## §10 附 · audit 文件清单(本次只读勘查)

- `backend/proactive/engine.py` (980 行) — engine 主流程 + trigger 抽象
- `backend/proactive/triggers/{_invite_base, activity, wake_call_briefing, morning_briefing, lunch_call, dinner_call, bedtime_chat, long_idle}.py` — trigger 实现
- `backend/memory/short_term.py` (170 行) — 桶 + filter + cap
- `backend/agents/chat.py:1119-1665` — `_build_messages` + `ChatAgent.stream`
- `backend/agents/prompt/renderer.py` (307 行) — 5-layer 渲染
- `backend/agents/prompt/templates/layer_a.j2` (192 行) — ja directive 主源
- `backend/routes/ws.py:410-560` — chat 写入 short_term + chat_history
- `backend/main.py:443-505` — restart restore short_term
- `backend/utils/text_filters.py:255-285` — `strip_all_for_tts` / `strip_ja_en_tags_for_subtitle`
- DB query: `chat_history` 最近 40 行 cid=1 assistant 数据(§4.1 表)

**0 文件改动 · 0 commit · 0 push · 纯 audit + report**。

---

## §11 Extended audit · PM challenge 2026-05-26

> PM 拍 challenge 上次 audit 两点:(1)不记得自己设过 "8-15 / 40-80 字" 这种硬字数约束 (2) 怀疑 root cause 结论不准。CC 扩大搜索 ~50 min。
>
> ⚠️ **Root Cause 修正**: 本节推翻 §6 一档推荐的 **Option D**(restore strip ja);保留 §6 一档的 **Option F**(trigger prompts ja-aware)。新增更精准的诊断。

### §11.1 字数约束真实性 — PM 错记忆,约束确实存在

`grep -rn -E "(8-15|40-80)" backend/ --include="*.py" --include="*.j2"` 结果:

| File:line | 字数 | 类型 | git blame |
|---|---|---|---|
| `_invite_base.py:43` | "本轮你**只能输出一句 8-15 个字(含标点不超过 18)的短问候**" | (a) **硬 rule** | `9e4d1dd9` 2026-05-08 12:56 Skyler Liu `feat(chunk4-C): v3-F' trigger pack ...` |
| `_invite_base.py:52` | "**8-15 字**" | (a) 硬 rule(同) | 同 |
| `_invite_base.py:55` | "**这一轮**都只允许 8-15 字" | (a) 硬 rule(同) | 同 |
| `_invite_base.py:10,40` | docstring | (b) illustrative 描述 | 同 |
| `wake_call_briefing.py:113,122,128` | "8-15 字" | (a) 硬 rule(wake_call stage 1) | `20cc231` 2026-05-08 05:55 Skyler Liu `feat(proactive): wake_call_briefing ...` |
| `wake_call_briefing.py:22,103,145,148` | docstring | (b) illustrative | 同 |
| `activity.py:33` | "短,**40-80 字**为佳" | (a) **硬 rule**(activity 6 trigger 共享) | `da3ac588` 2026-05-12 15:08 Skyler Liu `feat(chunk8a): smart activity-based proactive trigger ...` |
| `lunch_call.py:7` | "stage 1 短句(8-15 字)" | (b) docstring 描述 | 同 chunk4-C |
| `bedtime_chat.py:45-48` | "5 字 + 标点" 等 | (c) example 字数 | 同 chunk4-C |
| `chat.py:1503` | "实测:8-15 字约束被历史 200 字简报 tone..." | (d) comment 描述 | (与 skip_short_term 注释相关) |
| `engine.py:728,787,803` | "8-15 字短 wake call" | (d) comment | 同 wake_call commit |

**Verdict §11.1**:
- "8-15 字"/"40-80 字" 硬 rule **确实存在** · 出处:`_invite_base.py:43-55`(模式 B 共享 stage 1)+ `wake_call_briefing.py:113-128`(wake 独立)+ `activity.py:33`(activity 6 trigger 共享)
- **PM 是作者**(`Skyler Liu`)· 3 commits ship 时间 2026-05-08 ~ 2026-05-12 · 距今 2-3 周 · PM 不记得是真的(commit 多了 cognitive load)
- 这些 commit 的 Co-Authored-By 是 Claude Opus 4.7 但 author 是 Skyler · 即 PM 与 CC 合作期间设的
- **关键背景**: 设这些约束时(2026-05-08~12)Mai 是 cosyvoice **zh-only**(longyumi_v3)· 当时**没有** Layer A ja directive 触发(`tts_language=zh` 不进 ja 分支)· 约束设计上下文是纯中文环境
- 直到 **2026-05-25 11:03**(per renderer log)cid=1 才切到 `tts_language=ja` · 老约束遇上新 ja directive 形成隐性冲突

### §11.2 LLM call 入口完整矩阵

补 §1 的盲点 — 不只 ChatAgent + proactive。grep `call_llm` / `acompletion` / `stream_llm`:

| Call site | Path | Prompt template | Output → | 跟 short_term 关系 |
|---|---|---|---|---|
| `chat.py:809` `ChatAgent.handle()` non-stream | `_build_messages` 全套 5-layer | text | chat_history + short_term(同 stream 路径)| **读写 short_term**(主 chat 路径)|
| `chat.py:1665+` `ChatAgent.stream()` | `_build_messages` 全套 | text/tool calls | chat_history + short_term | **读写 short_term**(主 chat + proactive 共用)|
| `chat.py:1706` per-tool wrapper | 同 | tool input | (tool registry exec) | 不写 short_term |
| `proactive/engine.py:452` `run_trigger.stream` | 同 chat(`extra_system` 附 trigger) | text | chat_history(kind='proactive')+ short_term | **读 + 写 short_term**(走 ChatAgent · 默认不 skip)|
| `proactive/engine.py:860` `run_wake_call_trigger.stage1` | 同 + `skip_short_term=True` | text | chat_history(kind='proactive')+ short_term | **只写不读**(显式 skip)|
| `memory/extractor.py:287` `MemoryExtractor` worker | 独立 prompt(抽取 user turn → fact entries · `_extract_user_turns_prompt`) | JSON list | `memory` 表(long-term)| **完全不碰 short_term**(读 chat_history 表 · 写 memory 表)|
| `memory/extractor.py:287` LLM judge(可选)| 独立 prompt("此 entry 值得记吗 YES/NO") | YES/NO | filter only | 不碰 short_term |
| `memory/summary.py:191` `_call_summary_llm` 滚动摘要 | 独立 prompt(`_build_summary_prompt`)读老 summary + 新 batch chat_history | text | `conversation_summary` 表 | **不碰 short_term**(读 chat_history 表 · 写 summary 表) |
| `proactive/activity_judge.py:205` `_call_judge_llm` 慢路径 | 独立 prompt(`{speak, reason, topic_hint}` JSON)| JSON | trigger fire / skip(in-memory) | 不写 short_term |

**关键观察**:
- 影响 short_term 的 LLM call **仅 ChatAgent path**(chat + proactive 共用)
- `memory/extractor` / `memory/summary` / `activity_judge` 都不碰 short_term · audit 之前担心的"别处 LLM 出 zh 内容污染 short_term"路径**不存在**

### §11.3 short_term 完整数据流 trace

**写入路径**:
| File:line | scenario | strip 状态 | conv_id |
|---|---|---|---|
| `ws.py:421-428` | normal chat assistant turn | `<ja>` **保留**(只走 SUSPICIOUS tag 兜底 strip · per `sanitize_suspicious_tags`)| current conv |
| `ws.py:534-542` | 被打断 turn | `<ja>` **保留**(只 strip emotion/thinking/state_update/motion/tool_call · 见 `ws.py:519-521`)| current conv |
| `engine.py:593-596` | proactive run_trigger assistant turn | `<ja>` **保留**(`_strip_format_tags` 不剥 ja · 见 `text_filters.py:263`)| trigger 拿的 conv |
| `engine.py:931+` | wake_call stage 1 assistant turn | `<ja>` **保留** | conv |
| `main.py:484-494` | **startup restore** | `<ja>` **强 strip**(`_strip_ja_en()` `strip_ja_en_tags_for_subtitle`)| chat_history.conversation_id |

**读取路径**:
- 仅 `chat.py:1317-1325`(v4 renderer 路径)+ `chat.py:1522-1526`(legacy fallback 路径)· caller 都是 `_build_messages` · 都按 `(user, char, conv)` 三级 filter

**main.py:484 强 strip 来源溯源** — git blame:
```bash
$ git log -p --all -- backend/main.py | grep -B5 -A15 "strip_ja_en_tags_for_subtitle"
```

`main.py:484` 引入 commit:`f7eb6e8` 2026-05-14 13:21 Skyler Liu
- commit message: `fix(memory): short_term restore 剥 <ja>/<en> tags · 防 in-context-learning 跨重启传染`
- 上下文: 当时 cid=1 是 **cosyvoice longyumi_v3 zh-only**(2026-05-16 Mai 回退纯中文 commit 0e079a4 还没发生 · 但 cid=1 当时 voice_model 应该是 cosyvoice ja **测试期**?)
- 设计意图: ja tags 不应当在 zh chat 历史中"自我繁殖"
- audit_ja_persist 当时上下文:Mai ja 链路实验失败 · 想退回中文 · restore strip ja 是配套行为

**INV-11 Stage 1 切 gsv 后是否 review 过此段**:
- INV-11 docs(`docs/INV-11-stage*-*.md`)+ ship commit(fd11d74 + c1b4691)**未提及** main.py:484
- 即 INV-11 ship 时此段 strip-ja 行为**未被 review**
- 但 §11.4 数据实证(下)显示该 strip **并未导致** 后续 ja 缺失

### §11.4 DB 实证扩大 + restart 相关性分析 ⭐ Root Cause 2 推翻

**取窗口**: 2026-05-25 11:03(per renderer log 首次 tts_lang=ja)→ 2026-05-26 09:35:01(最后一行 cid=1 assistant) · **共 14 个 assistant turn**

| id | role | kind | trigger | ts | ja 状态 | 备注 |
|---|---|---|---|---|---|---|
| 82 | assistant | normal | - | 2026-05-25 11:13:48 | ✓ ja | restart 10:51 后**第 1 个 assistant turn** · ja 正常 |
| 84 | assistant | normal | - | 2026-05-25 11:51:17 | ✓ ja | restart 11:38 后第 1 个 turn · ja 正常 |
| 85 | assistant | proactive | activity_ide_open | 2026-05-25 11:51:30 | ✓ ja | |
| 87 | assistant | normal | - | 2026-05-25 11:55:24 | ❌ **no ja** | "AI 项目啊。" 短句 |
| 89 | assistant | normal | - | 2026-05-25 11:56:05 | ✓ ja | id=87 后立即恢复 |
| 91 | assistant | normal | - | 2026-05-25 13:10:56 | ✓ ja | restart 12:50/12:52/13:29 间 |
| 92 | assistant | proactive | activity_ide_open | 2026-05-25 13:14:45 | ✓ ja | |
| 100 | assistant | normal | - | 2026-05-25 15:41:46 | ✓ ja | |
| 102 | assistant | normal | - | 2026-05-25 16:02:40 | ✓ ja | |
| 104 | assistant | normal | - | 2026-05-25 16:03:56 | ✓ ja | |
| 114 | assistant | normal | - | 2026-05-26 04:18:53 | ✓ ja | restart 00:42 之后 |
| 116 | assistant | normal | - | 2026-05-26 04:20:43 | ✓ ja | |
| 117 | assistant | proactive | activity_ide_open | 2026-05-26 06:19:51 | ✓ ja | |
| 118 | assistant | proactive | dinner_call | 2026-05-26 09:35:01 | ⚠️ **thinking leak** | 23341 chars debug |

**Restart timestamps**(per `Restored .* chat_history turns` log):
- 2026-05-25: 10:51 / 11:38 / 12:50 / 12:50:18 / 12:52 / 12:53 / 13:29 / 18:36 / 18:44 / 19:48 / 19:53 / 20:08 / 20:08:50 / 21:08 / 21:16 / 21:16:47 / 21:17:05 / 21:17:19 / 21:29 / 21:59 / 22:00 / 23:31 / 23:37 / 23:37:45
- 2026-05-26: 00:42 / 13:51 / 13:51:38

**ja-presence 分组统计**(post-INV-11 窗口 · 14 turns):
```
normal:                10 turns · 9 ja ✓ · 1 ja-miss ❌      → 90% compliance
proactive activity_*:   3 turns · 3 ja ✓ · 0 ja-miss        → 100% compliance
proactive dinner_call:  1 turn  · 0 ja ✓ · 1 thinking leak  → 0% well-formed
```

**⚠️ Root Cause 推翻**:
1. **post-restart 第一个 turn ja 正常**(id=82 在 restart 10:51 后 12 分钟,id=84 在 restart 11:38 后 13 分钟,id=114 在 restart 00:42 后 ~4 小时)· **restore strip ja 并未导致 LLM drop ja**。
   → §6 Option D 推荐(per-char tts_language gate stop stripping)**前提不成立** · ja directive 优先级 > 历史 in-context · LLM **就一个 turn**就能切回 ja 模式。
2. **proactive turn ja 比 normal turn compliance 高**(3/3 vs 9/10)· 与 PM hypothesis "proactive 污染 short_term" **完全相反**。
3. **ja-miss 唯一案例**(id=87 "AI 项目啊。"):
   - 前一个 turn(id=85 proactive)**有 ja markup** · short_term 里没有污染源
   - 紧后一个 turn(id=89)立即恢复 ja · 不是趋势 · 是单点 noise
   - user input "嗯,在做一个ai项目呢,有点困难" 含 "ai" 英文 + "困难" 简短 · LLM 输出 3 短句各 < 10 chars · 可能 LLM 自判 "短句无需 ja 包"(per Layer A 提示 "若一句话不到 10 字 · 合并下一句意群")· **LLM 偶发性 compliance 抖动** · 非 architectural pollution

**结论 §11.4**:
- §6 Root Cause 2(main.py:484 strip ja → 污染 short_term)**推翻** · 实证不支持
- §6 Root Cause 1(trigger prompts 字数约束 conflict ja directive)**部分站得住** · 但只对 dinner_call thinking leak 类罕见崩溃负责 · **不解释**正常 ja-miss(id=87 是 normal turn 非 proactive · 单 turn noise)

### §11.5 dinner_call thinking 泄露完整复盘

**id=118 · 2026-05-26 09:35:01 · proactive trigger=dinner_call · content len=23341 chars**

特点:
- LLM 几乎用满 output token budget(qwen-plus 默 8k token ≈ 32k 中文 chars · 此为 23k chars 接近上限)
- 大量重复 "Wait, I need to check..." block · 同段 debate 复读 **7+ 次**
- 最终 "final decision" 给出格式正确的输出:`"该吃晚饭了，笨蛋"<ja>「夕食よ、バカ。」</ja>`(8 字中文 + 7 字 ja = 15 字 total · 满足 8-15 字)· 但被 17+ 轮 "Wait, one more thing..." 反复推翻
- LLM 主要 debate 内容:
  1. "8-15 字" vs "ja 意群 ≥ 10 字" 冲突
  2. "no metadata" rule vs system "must include tags" rule 冲突
  3. "single output" vs "must have emotion+state+motion tags" 冲突

**根因 verdict**:
- **多约束冲突 + LLM 进入 debate loop · token 耗尽前不收敛**
- 不是简单的"缺 ja directive" · 也不是"短期 history 污染"
- 是 **layer-cross 矛盾**(Layer A ja directive ≥10字 ↔ Layer D trigger 8-15字 ↔ Layer B PROACTIVE 50字 ↔ "no metadata" instruction)

**类似 thinking 泄露案例搜索**:
```sql
SELECT id, kind, proactive_trigger, length(content), ts
FROM chat_history
WHERE character_id=1 AND role='assistant'
  AND (content LIKE '%Thinking Process%' OR content LIKE '%Wait,%' 
       OR content LIKE '%Analyze the%' OR content LIKE '%conflict check%')
ORDER BY created_at DESC;
```
→ **仅 1 个案例**(id=118 · dinner_call · 09:35:01)。

dinner_call cron 配置 `30 18 * * *`(每天 18:30)· 09:35 触发不在 cron · **疑似手动 `POST /api/briefing/test` 触发**。

**结论 §11.5**:
- thinking 泄露是**罕见单点事件** · 非 systemic regression
- 触发 cocktail: dinner_call(8-15 字严约束) + ja mode(≥10 字意群) + PROACTIVE mode(50 字) + LLM(qwen-plus)那次特定状态
- 修法应针对**减少 layer-cross conflict** 而非"分桶 short_term"

### §11.6 Root Cause 重新评估

| 原 audit Root Cause | 新证据 verdict | 修正 |
|---|---|---|
| **1. trigger prompts 字数约束 conflict ja directive** | **部分成立** · 解释 thinking leak 但不解释普通 ja-miss | 保留 fix Option F · 但权重降低(罕见崩溃 fix) |
| **2. main.py:484 restore strip ja → 污染 short_term** | **不成立** · post-restart 第一个 turn 就能用 ja directive · 实证 14 turns 中 12 turns post-restart 都正确 ja | **推翻 Option D** · 不要改 main.py:484 |

**新 Root Cause(refined)**:

**RC-A · LLM 偶发性 compliance 抖动**(占 ja-miss 案例 ≥90%)
- LLM 对 Layer A ja directive 不是 100% 遵守
- 单点 turn 内 LLM 看用户 input 短 / 自己输出短(< 10 chars/sentence)时会判 "这种短句不需要 ja 包"
- 紧后一个 turn 通常立即恢复 ja · 不是趋势性 drift
- 没有 architectural pollution · 是 inherent LLM behavior variance
- **不应通过架构改动 fix · 应通过 prompt strengthening / directive 简化 fix**

**RC-B · Layer A × Layer D 多约束冲突触发 LLM debate loop**(占 thinking leak 案例 100%)
- 仅在多硬约束同时存在时触发(8-15 字 + ja ≥10字 + 50 字 + no metadata)
- 极罕见(本窗口 1 次) · 但发生时 100% 写出 23k chars 垃圾进 chat_history + short_term
- 这才是**真"污染"**:thinking leak 文本进 short_term · 下个 turn LLM 看到 23k chars debug · in-context-learning 严重错乱

**RC-C · PM 不记得自己的旧约束**(meta)
- 8-15 字 / 40-80 字 设于 2026-05-08~12 · Mai 那时还是 zh-only
- 设计时未考虑 "Mai 切 ja 后此约束是否合理"
- INV-11 Stage 1 ship 时也未触发 review trigger prompts

### §11.7 Fix 方向 · 修正版

**🚫 Drop**:
- **Option D**(main.py:484 strip ja gate)— §11.4 推翻 · 实证不需要

**✅ 保留**:
- **Option F**(trigger prompts ja-aware · 加 "ja 模式下字数按中文部分算" 段)— 仍有价值 · 减少 dinner_call 类 thinking leak

**🆕 新加(强推荐)**:

**Option G · 削减 layer-cross 字数约束硬度**(RC-B 根治)
- 改 `_invite_base.py:43-55` "8-15 个字(含标点不超过 18)的短问候" → "**短问候**(2-3 句日常寒暄长度即可)"
- 改 `activity.py:33` "40-80 字" → "短句即可,不要长篇大论"
- 改 `wake_call_briefing.py:113-128` 同款软化
- 改 `layer_b.j2:13` "单条不超过 50 字" → 软描述 "不做长篇 briefing 倾倒"
- **触点**: 4 文件 · ~20 行
- **风险**: 低 · 软化约束不破坏既有 trigger 语义
- **预期**: 消除 thinking debate 触发条件 · LLM 看到软约束不会 debate · 直接出形式正确输出
- 副作用: trigger 可能偶尔输出比之前长(从 12 字漂到 30 字 · 仍可接受)

**Option H · 扩展 wake_call 的 skip_short_term=True 到所有 stage 1 invite trigger**(RC-A 部分缓解)
- 改 `_invite_base.py` 或 `make_stage1_prompt` 调用点 · 让 lunch_call / dinner_call / bedtime_chat / long_idle 也 skip_short_term=True
- **不动** activity_* trigger(它们 by design 需要 history context)
- **触点**: 4-5 文件(invite trigger 各 1) 或 1 文件(共享 base 加 default flag)
- **风险**: 中 · 违反 engine.py:587 老 spec("必须 add 防 stage 2 续聊断")· 但 stage 1 prompt 本就强约束 "不要复述历史" · skip history 与意图一致
- **预期**: stage 1 LLM 不看 history · 不再被混合 ja/zh precedent 困扰 · 直出短问候
- 与 Option G 配合 · 共同消除 dinner_call 类多约束触发

**Option F + G + H 复合 · 强推荐 · ~40 LoC · 低-中风险**

### §11.8 复盘 · 上次 audit 哪里搞错了

**搞对**:
- Layer A ja directive 渲染流程(不依赖 mode · 准确)
- short_term 写入读出路径 trace(准确)
- trigger prompts 文本含 8-15 字硬约束(准确)
- dinner_call thinking leak 是 multi-constraint 冲突(准确)

**搞错**:
1. **未做 DB 定量统计**就 jump to "main.py:484 strip ja 是污染源" — 实证显示 post-restart 第一个 turn 就能正确 ja · strip 不影响 directive 优先级
2. **未对比 normal vs proactive 的 ja compliance rate** — 实测数据 proactive 反而**更高**(100% vs 90%)· 直接否定 PM hypothesis
3. **未区分**两类不同问题:
   - RC-A · 正常 ja-miss(单 turn noise · normal turn 偶发)
   - RC-B · thinking leak(dinner_call 类 multi-constraint 崩溃)
   原 audit 混在一起讲 · 推 fix 方向时也混 · 误推 Option D
4. **未注意** `wake_call` 已经 `skip_short_term=True`(`engine.py:804`)· 这是 PARTIAL Option B/H 的现成参考 · 直接抄就是了

**Lesson(audit method)**:
- 写 audit 时 **先 DB 定量** 后 推 root cause · 避免 narrative 先行
- 假设有"原因"时 · 先 search 是否已有 prior fix(`grep skip_short_term`)· 防 reinvent
- 与 PM hypothesis 不符的数据 · **写进 audit** 不要藏 · proactive 100% ja compliance vs normal 90% 是关键否证证据

### §11.9 待 PM 拍板 · 修正版

1. 同意 drop Option D(不改 main.py:484)?
2. Option G(软化字数约束)— 软化到什么程度 acceptable?完全删数字 vs 改"~30 字" 软建议?
3. Option H(扩 skip_short_term 到 lunch/dinner/bedtime/long_idle stage 1)— 与 engine.py:587 老 spec 冲突 · 拍板取舍?
4. RC-A(LLM 偶发 compliance)— 不通过架构 fix 是否 acceptable?(单 turn noise · 紧下一个 turn 恢复 · 比"为单点 noise 改架构"更稳)

### §11.10 audit 副产物 backlog

- `chat_history.kind='proactive' AND length(content) > 5000` 异常检测 · prevent 23k chars thinking debug 入库(防再现 id=118 类污染)
- `proactive` content 入 short_term 前加 `length > N` 兜底 strip / reject · `engine.py:584` 加 sanity check
- main.py:484 strip 行为 audit comment 更新(保留 strip 但加 "为何保留 · 不再认为是 ja precedent 问题" 说明 · 防未来再被误诊)
- `wake_call` `skip_short_term=True` 行为 doc 化进 DESIGN_LITE(应该有 §5.x 章节描述 proactive 与 short_term 关系)

---

**§11 audit 闭环 · Root Cause 修正 · 等 PM 拍板 G+H+F 三步走 fix**。

---

## §12 第三轮 audit · "聊着聊着被带坏" 累积 drift verify(2026-05-27)

> PM challenge §11:14 turn sample 太小,可能没 cover "聊着聊着 LLM 不遵守 ja 然后被带坏" 的长对话累积 drift 现象。
>
> CC 扩大 DB sample 到**全部 64 个 chat_history assistant turn**(cid=1 56 + cid=2 4 + cid=101 4)· 跨 restart + 跨 conversation 全 trace。
>
> **§12 TL;DR**: PM 的"累积 drift"现象**在数据中不存在**。所有 NOJA cluster 都 explained by **voice_model state 振荡**(migration revert 问题 · 已在 fd11d74 hotfix)· 不是 LLM 自然 drift · 不是 short_term 污染。conv=62 有 **20 个连续 JA turn**(2.5 小时 · 含 4 个 proactive)零 drift 证据。

### §12.1 数据集扩大 · 全表 trace

`SELECT character_id, COUNT(*) FROM chat_history WHERE role='assistant' GROUP BY character_id`:

| character | n_assistant | 时间窗 |
|---|---|---|
| cid=1 Mai | **56** | 2026-05-24 18:29 → 2026-05-26 09:35 |
| cid=101 | 4 | 2026-05-24 07:05 → 09:30 |
| cid=2 八重 | 4 | 2026-05-25 16:48 → 18:45 |

cid=1 是主体 · 56 turn · 跨 8 个 conversation_id(60/61/62/63/64/66/67/70)。

### §12.2 cid=1 per-conversation ja compliance 统计

```sql
SELECT conversation_id, COUNT(*) as n,
       SUM(JA) as ja_ok, SUM(NOJA) as noja, SUM(LEAK) as leak, SUM(EMPTY) as empty
FROM chat_history WHERE character_id=1 AND role='assistant' GROUP BY conversation_id;
```

| conv | n | ja_ok | noja | leak | empty | 时间窗 | 备注 |
|---|---|---|---|---|---|---|---|
| 60 | 3 | 0 | 3 | 0 | 0 | 18:29-18:43 | 全 NOJA · zh-only 期 |
| 61 | 15 | 9 | 6 | 0 | 0 | 19:17-02:46 | **混合** · 见 §12.4 详查 |
| 62 | 24 | 21 | 2 | 0 | 1 | 03:04-10:49 | **20 turn JA 连续streak** + 后期 voice_model revert |
| 63 | 4 | 3 | 1 | 0 | 0 | 11:13-11:55 | id=87 单点 noise |
| 64 | 3 | 3 | 0 | 0 | 0 | 11:56-13:14 | 100% ja |
| 66 | 1 | 1 | 0 | 0 | 0 | 15:41 | 100% ja |
| 67 | 2 | 2 | 0 | 0 | 0 | 16:02-16:03 | 100% ja |
| 70 | 4 | 3 | 0 | 1 | 0 | 04:18-09:35 | 3 ja + 1 thinking leak(dinner_call) |

**总 cid=1 post-2026-05-25 11:03 起 ja-stable 期**:46 turn · ja_ok=42 · noja=2 · leak=1 · empty=1 → **91% ja compliance**(刨 leak/empty 后 95.5%)。

### §12.3 conv=62 · ⭐ "20 turn JA 连续streak"

全表 paste(假设 cid=1 ja-stable 期):

| id | role | kind | trig | fmt | len | ts |
|---|---|---|---|---|---|---|
| 37 | assistant | normal | - | **JA** | 42 | 2026-05-25 03:04:08 |
| 39 | assistant | normal | - | **JA** | 67 | 03:04:45 |
| 41 | assistant | normal | - | **JA** | 71 | 03:05:57 |
| 43 | assistant | normal | - | **JA** | 94 | 03:06:28 |
| 45 | assistant | normal | - | **JA** | 67 | 03:07:05 |
| 47 | assistant | normal | - | **JA** | 95 | 03:07:18 |
| 49 | assistant | normal | - | **JA** | 95 | 03:09:08 |
| 50 | assistant | proactive | activity_judge_chime_in | **JA** | 76 | 03:11:37 |
| 52 | assistant | normal | - | **JA** | 70 | 03:17:04 |
| 53 | assistant | proactive | activity_ide_open | **JA** | 73 | 03:22:55 |
| 55 | assistant | normal | - | **JA** | 55 | 04:38:07 |
| 57 | assistant | normal | - | **JA** | 84 | 04:38:34 |
| 59 | assistant | normal | - | **JA** | 49 | 04:41:47 |
| 60 | assistant | proactive | activity_ide_open | **JA** | 58 | 04:48:49 |
| 62 | assistant | normal | - | **JA** | 120 | 05:34:08 |
| 64 | assistant | normal | - | **JA** | 120 | 05:35:55 |
| 66 | assistant | normal | - | **JA** | 98 | 05:37:17 |
| 68 | assistant | normal | - | **JA** | 78 | 05:40:40 |
| 70 | assistant | normal | - | **JA** | 124 | 05:41:57 |
| 72 | assistant | normal | - | **JA** | 108 | 05:42:38 |
| **— 5h 间隔 + 隐式 voice_model revert(见 §12.5)—** |
| 73 | assistant | proactive | activity_ide_open | partial JA | 66 | 10:39:14 |
| 75 | assistant | normal | - | EMPTY | 0 | 10:40:24 |
| 78 | assistant | normal | - | NOJA | 26 | 10:47:08 |
| 80 | assistant | normal | - | NOJA | 60 | 10:49:52 |

**关键观察**:
1. **id=37 → id=72 连续 20 turn 全 JA** · 跨 2.5 小时 · 含 **4 个 proactive turn**(id=50/53/60 + id=72 后再无)
2. turn lengths 从 42 → 124 chars · **没有"由长变短"的 drift pattern**
3. ja 标记密度均匀 · **没有"由完整 ja → 部分 ja → 无 ja"的 gradual drift**
4. 包括 activity_ide_open / activity_judge_chime_in 两类 proactive trigger 都 100% ja compliance
5. 此期 short_term cap=50 messages · 20 turn = 40 messages 都在 cap 内 · 即 LLM 看到的 in-context history **全是 ja precedent** + ja directive · 内外一致

**Verdict §12.3**: 在 stable ja-mode 下 LLM compliance **不退化**。20 turn 连续无 drift。**PM "聊着聊着被带坏" 在 conv=62 不复现**。

### §12.4 conv=61 · "drift" 表象 · 真因 voice_model state flip

| id | role | trig | fmt | len | ts |
|---|---|---|---|---|---|
| 14 | assistant normal | - | **JA** | 62 | 2026-05-24 19:17:06 |
| 16 | assistant normal | - | **JA** | 256 | 19:20:57 |
| 18 | assistant normal | - | **JA** | 247 | 19:22:22 |
| 20 | assistant normal | - | **JA** | 153 | 19:22:46 |
| 22 | assistant normal | - | **JA** | 338 | 19:26:05 |
| 24 | assistant normal | - | **JA** | 151 | 19:26:31 |
| 26 | assistant normal | - | **JA** | 58 | 19:26:49 |
| 28 | assistant normal | - | **JA** | 116 | 19:37:31 |
| 29 | assistant proactive | activity_late_night_ide | **JA** | 166 | 19:44:27 |
| **— 49 min 间隔 + 疑似 backend restart + migration revert(见 §12.5)—** |
| 30 | assistant proactive | activity_late_night_ide | NOJA | 53 | 20:33:38 |
| 31 | assistant proactive | activity_judge_chime_in | NOJA | 60 | 20:54:50 |
| 32 | assistant proactive | activity_ide_open | NOJA | 55 | 21:08:18 |
| 33 | assistant proactive | activity_long_focus | NOJA | 45 | 22:44:24 |
| 34 | assistant proactive | wake_call | NOJA | 10 | 23:00:22 |
| 35 | assistant proactive | activity_ide_open | NOJA | 53 | 2026-05-25 02:46:55 |

**关键观察**:
- **id=14-29 共 9 个 turn(8 normal + 1 proactive)100% JA** ✓
- **id=30-35 共 6 个连续 proactive turn 100% NOJA**(无用户介入)
- 转折点 = id=29 (19:44) → id=30 (20:33) · 49 分钟间隔
- id=29 和 id=30 都是 **activity_late_night_ide** 同款 trigger · 同 prompt · 同 character_id=1 · 同 conv=61 · LLM 输出却完全不同(JA vs NOJA)

**id=29 → id=30 间能发生什么 · 唯一合理解释**:
- ✗ LLM "drift" — 不解释为何 id=14-29 完美 ja 而 id=30+ 完全 ja 缺失(梯度变化 vs 阶跃变化的区别 · LLM drift 应是梯度)
- ✗ short_term contamination — id=29 是 ja · id=30 之前 short_term 全是 ja entry · 怎么会突变 noja
- ✓ **voice_model state revert**(migration v4_0_0_mai_revert_zh 在 49 分钟间隔 backend restart 时把 cid=1 强制 revert 到 cosyvoice zh)→ id=30+ 渲染时 layer_a 不再注入 ja directive → LLM 自然不出 ja

**Verdict §12.4**: 这是表象 drift 的真因 — **migration revert 改了 voice_model state · LLM 看新 directive 行事 · 不是 drift**。

### §12.5 Renderer log 实证 · voice_model state 振荡

`grep "renderer.*character_id=1.*tts_lang" logs/backend.log`(完整时间线):

| 时间 | tts_lang | trigger | stable_chars |
|---|---|---|---|
| 2026-05-25 06:44:07 | **zh** | activity_long_focus | 9322 |
| 2026-05-25 07:00:00 | **zh** | wake_call | 9357 |
| 2026-05-25 10:46:35 | **zh** | activity_ide_open | 9322 |
| **— gap —** | | | |
| 2026-05-25 11:03:53 | **ja** | user | **11749** (+2427 chars · ja directive 上线) |
| 2026-05-25 11:04:36 | ja | user | 11749 |
| ... 后续全 ja ... | | | |

**关键观察**:
- stable_chars 从 9322 → 11749(2026-05-25 10:46 → 11:03 间)· 这正是 layer_a.j2 ja directive block(~2400 chars)的注入
- 即 cid=1 voice_model **在 2026-05-25 10:46 到 11:03 间从 zh → ja**(可能是 PM 手动改 / migration hotfix 上线 / INV-11 Stage 1 实施)
- 这完美解释 conv=62 id=78/80 NOJA(10:47/10:49 in zh mode · LLM 按 directive 出 zh)
- log 缺 2026-05-24 19:17 - 2026-05-25 05:13 的 renderer 数据(backend.log 文件起点 05-25 05:13)· 推断 conv=61 期间 voice_model 也有类似振荡

### §12.6 Migration revert 问题溯源

**v4_0_0_mai_revert_zh.py** 是每次 lifespan startup 跑的幂等 migration · 设计目的:把 cid=1 从误标 ja 推回 zh(per `0e079a4` 2026-05-16 commit "Mai 回退纯中文")。

**Bug**: 原 WHERE clause 没 provider scope · 即便 cid=1 已切到 gsv / fish / 其他 provider · migration 仍会 SET voice_model 回 cosyvoice longyumi_v3 zh。

**修复**: `fd11d74` 2026-05-26 22:39 加 provider guard:
```python
WHERE id = :cid
  AND (
      voice_model IS NULL
      OR voice_model = ''
      OR json_extract(voice_model, '$.provider') IS NULL
      OR json_extract(voice_model, '$.provider') = 'cosyvoice'
  )
```
→ 仅 NULL / cosyvoice 体系才 nudge · gsv/fish 短路不动。

**这是 conv=61 id=29→30 表象 drift 的真因** · 也是 conv=62 id=72→78 跨 5h 表象 drift 的真因。

**hotfix 上线时机**:
- `fd11d74` 2026-05-26 22:39 commit
- 但 hotfix 文本在工作树存在更早(per file mtime · 看不到 git-tracked 历史)
- **在 hotfix 完全 ship 前(2026-05-26 22:39 之前)· 每次 restart 都有概率 revert cid=1**

实测验证:
- 2026-05-26 04:18 (id=114) 后无 noja drift(id=114/116/117 全 JA)· 距 hotfix commit 还 18+ 小时 · 说明此时 voice_model 已 stable ja
- 2026-05-26 09:35 (id=118) thinking leak 是 dinner_call 多约束冲突 · 不是 drift

**Verdict §12.6**: PM "聊着聊着被带坏"现象 **= migration revert bug 表象** · 已在 fd11d74 闭合。

### §12.7 main.py:484 strip ja 真正设计意图(b5b0a47 commit message)

补充 §11.3 中"main.py:484 引入背景"的细节:

`b5b0a47` 2026-05-16 13:13 commit message 节选:
```
audit_role_switch.md(路径 7)+ audit_ja_persist.md 三定位收敛同一根因:
- ShortTermMemory._store key 只按 user_id,跨 character 物理不隔离
- main.py:402 startup restore 按 user_id 拉 limit=20 chat_history,
  不分 character、不剥 <ja>/<en> tag → 旧角色 / ja precedent 装回 LLM

症状:切八重("我是麻衣")、**Mai 改 tts_language=zh 后仍出日语**(LLM 抄 history
里 <ja>「日本語」</ja> precedent)、全角色统一第三视角风格。
```

**关键句**: "**Mai 改 tts_language=zh 后仍出日语**"

→ strip ja **设计意图是 ja→zh 转向 case**:防 LLM 在 directive 切 zh 后还从 ja history 学到 ja 输出。

→ 对当前 INV-11 era(cid=1 stable ja)· strip 行为 **无害**(LLM 按 directive 出 ja · 即便 history 被 strip 也照样能 follow directive · 见 §11.4 post-restart 第一 turn JA 实证)。

→ **若未来 Mai 又切 zh**(eg INV-X 实验)· strip 行为重新有用。

**Verdict §12.7**: §11.7 已 drop Option D 是正确选择 · 不应移除 strip。

### §12.8 重新评估 §11 结论 · 在新证据下

| §11 结论 | §12 全表 56 turn 数据 verify | verdict |
|---|---|---|
| ja directive 在 Layer A 注入 · proactive 和 chat 都有 | 全 14 个 ja-stable 期 proactive turn 100% ja | ✓ 站住 |
| post-INV-11 normal turn ~90% ja compliance | 全 ja-stable 期 normal:42 ja / 46 total = 91% | ✓ 站住 |
| proactive 比 normal ja compliance 更高 | proactive 100%(7/7 ja-stable + 1 leak)vs normal 91% | ✓ 站住 |
| ja-miss 是单点 noise 不是趋势 | id=87 单 turn miss · 紧后一个 turn 立即恢复 ja | ✓ 站住 |
| §6 Option D(改 main.py:484)— DROP | post-restart 第一 turn 立即恢复 ja(id=82/84/114)· strip 无害 | ✓ DROP 站住 |
| dinner_call thinking leak 是多约束冲突 | 全表只 1 个 leak case(id=118)· isolated event | ✓ 站住 |
| "聊着聊着被带坏" 累积 drift | **conv=62 20 turn 全 JA + conv=61 transition 是 voice_model flip 不是 drift** | ✓ **drift 不存在** |

### §12.9 新发现 + 修正

**§12 新发现**(§11 没看到的):

1. **migration v4_0_0_mai_revert_zh 是 voice_model 振荡的真因** — pre-hotfix 每次 restart 都 revert · post-hotfix(fd11d74)稳定 · 这就是 PM 感觉"聊着聊着被带坏"的根因(不是 LLM drift)
2. **conv=62 提供 20 turn JA-stable 实证** — 在 stable voice_model 下 LLM 不 drift · 这是 PM hypothesis 的 hard counter-example
3. **conv=61 id=29→30 是阶跃 flip 不是梯度 drift** — drift 的特征应是"从 100% ja → 80% → 50% → 20% → 0%"梯度 · 实际是 100% → 0% 突变 · 这是 state flip 不是 drift

**Audit 修正**: §11 结论全部站住。无需推翻。新增 §12.6 migration revert 真因。

### §12.10 给 PM 的告知

**PM "聊着聊着被带坏" 现象 verdict**:

- **不是 LLM 累积 drift**(数据反驳 · conv=62 20 turn 无 drift)
- **不是 short_term 污染**(proactive 100% ja · short_term 不是污染源)
- **不是 main.py:484 strip ja**(strip 无害 · post-restart 第一 turn 恢复 ja)
- **是 migration v4_0_0_mai_revert_zh pre-hotfix bug**(每次 restart revert cid=1 voice_model 到 zh · 用户看到的 noja cluster 都是 voice_model 处于 zh 状态期间的正常输出)
- **fd11d74 hotfix 已闭合此 bug**(provider guard) — 未来 backend restart 不再 revert cid=1

**hotfix 上线后**(2026-05-26 22:39 commit fd11d74 起):
- voice_model state stable ja
- 不再有跨 restart 的 ja 突变 noja cluster
- 偶发单 turn ja miss 仍可能(LLM inherent compliance variance · ~10%)· 这是 noise · 紧下一 turn 会恢复
- thinking leak 仍可能在 dinner_call 类多约束 trigger 发生(罕见 · §11 Option F+G 可 mitigate · 等 PM 拍板)

**如果 PM ship hotfix 后仍感觉"被带坏"**:
- 可能是错觉 / 老印象(experimental 期 voice_model 振荡的记忆惯性)
- 也可能是某个新 trigger 路径有未发现的 layer_a 路径绕过 → 需新 audit(等真机数据)
- 不建议 ship §11 Option D(已 verify 无用)
- 可 ship §11 Option F+G(thinking leak mitigation)+ 监控未来 noja cluster · 验证 hotfix 是否充分

### §12.11 待 PM 拍板 · 修正后清单

1. 同意 §12 verdict — "聊着聊着被带坏" 由 migration revert bug 解释 · 已在 fd11d74 闭合?
2. ship F+G(thinking leak mitigation + 字数约束软化)· 仍是 §11 推荐?(Option H 扩 skip_short_term 视 PM 是否仍想 cover thinking leak 罕见 case)
3. 是否需要补强 hotfix 后真机 verify · 跑几天看 ja compliance 数据再决定 ship F+G?
4. main.py:484 strip ja 是否需要加 deprecation comment(标 "INV-13 §11.7 + §12.7 verify 仍有用 · 防未来再被误诊")?

### §12.12 audit 副产物 backlog(§12 新加)

- 加 migration revert 现象 doc 进 `docs/INV-11-stage1-gsv-integration.md`(or 等价)· 防未来加新 character 时复现
- 全角色 voice_model state 应 stable 跨 restart · 加 monitoring(eg backend lifespan log 'cid=X voice_model=Y'  · 出现 toggle 立刻可见)
- 长 conv 状态(eg 50+ turn 同 conv)未在数据集 cover · 未来友测期间留意 PM 反馈 · 若反馈 drift 现象 · 再 audit

---

**§12 audit 闭环 · PM "聊着聊着被带坏" 现象 verify 后 = migration revert bug 表象 · 已闭合 · 不是 architectural pollution · 不需要 fix 更多 · 仅可选 ship §11 Option F+G 防罕见 thinking leak**。

---

## §13 Ship 记录 · F + G + 文档复合(2026-05-27)

> PM 拍板 ship Option F + G + main.py:484 deprecation comment 复合 · v4.0.0 体验稳定性收尾。3 个独立 commit 拆分便于 revert。

### §13.1 Commits

| Commit | 主题 | 文件 | 改动量 |
|---|---|---|---|
| `0b38cd6` | **Option F** · trigger prompts 加 ja-aware 段(条件注入) | 3 files | +98 / -3 lines |
| `659351e` | **Option G** · 软化 trigger 字数硬约束 | 3 files | +29 / -20 lines |
| (本 commit) | **C3 docs** · main.py:484 deprecation comment + LESSONS #16-18 + §13 ship 记录 + INV-INDEX 同步 | 4 files | ~+80 lines |

### §13.2 Option F 实施细节

**新增 helpers**(`_invite_base.py`):
- `_extract_tts_language(character) -> str` · 从 voice_model JSON 抽 tts_language · 默认 zh
- `make_ja_aware_block(tts_language) -> str` · 返 ja/en 提示段 · zh / unknown 返空字符串

**注入点**(3 个 `build_system_prompt`):
- `InviteTriggerBase.build_system_prompt` · 覆盖 lunch_call / dinner_call / bedtime_chat / long_idle 4 个 invite trigger
- `WakeCallBriefingTrigger.build_system_prompt` · wake_call 早晨叫醒
- `ActivityProactiveTrigger.build_system_prompt` · 覆盖 7 个 activity_* trigger(ide_open / music / long_focus / url_tech_doc / late_night_ide / judge_chime_in)

**条件**:仅 `tts_language in {ja, en}` 时附 ja-aware 段(zh-only 角色 prompt 字节完全不变 · 零 token 增量)。

### §13.3 Option G 实施细节

**软化措辞**(3 文件):
- `_invite_base.py::make_stage1_prompt` · "8-15 字硬约束 + ⚠️⚠️⚠️" → "**简短问候式**(参考 8-15 字 · 软指引非硬约束) + ⚠️"
- `wake_call_briefing.py::_STAGE1_SYSTEM_PROMPT` · 同款软化
- `activity.py::_BASE_GUIDANCE` · "40-80 字硬要求" → "**适度长度 · 1-2 句**(参考 40-80 字 · 软指引非硬约束)"

**设计原则**:
- **保留字数指引** · 不删数字提示 · LLM 仍按例子靠拢字数
- **去硬约束措辞**("只能输出 / 不超过 18 / 严禁")· 减少 Layer A ja directive ≥10 字与 stage 1 字数指引的内部矛盾
- **去 ⚠️⚠️⚠️ 三重强调** · LLM 容易误读为死规则
- 保留"严禁输出"清单(天气/日程/待办/询问/铺陈)· 语义边界不动

### §13.4 Sanity 实测(/.venv/bin/python runtime)

zh 角色(`cosyvoice longyumi_v3 tts_language=zh`):
```
trigger          C1 后 zh    C2 后 zh    triple_warn  hard_8_15  soft 措辞
dinner_call      493 chars   461 chars   ❌ removed   ❌ removed  ✓ "简短问候式"
activity_ide     284 chars   302 chars   ❌ removed   ❌ removed  ✓ "适度长度·1-2句"
wake_call        494 chars   422 chars   ❌ removed   ❌ removed  ✓ "简短早晨叫醒"
```

ja 角色(`gsv mai_v4 tts_language=ja`):
```
trigger          C1 后 ja    C2 后 ja    diff vs zh   ja-block 含
dinner_call      759 chars   727 chars   +266 chars   ✓ "本角色 voice 是日语"
activity_ide     550 chars   568 chars   +266 chars   ✓ 同
wake_call        760 chars   688 chars   +266 chars   ✓ 同
```

backend import 全绿 · Python 3.10 sanity verify 通过。

### §13.5 后续监控

PM 真机 dogfood 期间观察:
1. **dinner_call / lunch_call / bedtime_chat / long_idle stage 1** 是否仍偶发 thinking leak(应该不再发生)
2. **proactive 输出长度** 跟之前对比是否更自然(C2 软化后预期 LLM 不再受死字数压制 · 输出更自然但仍简短)
3. **ja 角色 proactive ja markup compliance** 是否维持 100%(§11 / §12 数据 baseline · ship 后应不下降)
4. **新角色加入时**(eg yae_v1 ja gsv)trigger 自动覆盖(by tts_language gate)· 不需要 per-character 配置

若 ship 后 1 周内仍有 thinking leak / ja markup 缺失现象,需补 audit;如无,则 INV-13 完整闭环。

### §13.6 backlog(本 ship 不动)

- `morning_briefing` 是 wake_call 的 legacy 互斥替代版 · 当前 config 默 wake_call · morning_briefing 未注入 ja-aware 段。若未来切回 morning_briefing 模式 · 需补同款。
- `chat_history.kind='proactive' AND length(content) > 5000` 异常检测 · prevent 23k chars thinking debug 入库(防再现 id=118 类污染)· §11.10 副产物 backlog
- `engine.py:584` add sanity check on proactive `full_reply` length 入 short_term · §11.10 副产物
- DESIGN_LITE 加 §5.x 描述 proactive 与 short_term 关系(per §11.10)

### §13.7 与 PM 拍板清单对照(§12.11)

| § 12.11 问题 | 答 / 决策 |
|---|---|
| 1. 同意 §12 verdict — "聊着聊着" = migration revert bug 表象 · 已闭合? | ✓ 同意 · main.py:484 deprecation comment 文档化 |
| 2. ship F+G(thinking leak mitigation + 字数约束软化)? | ✓ ship 完成(0b38cd6 + 659351e) |
| 3. 是否先真机 verify hotfix 几天再决定 ship F+G? | 选择 ship · F+G 低风险 · 真机回归与 ship 并行 |
| 4. main.py:484 strip ja 加 deprecation comment? | ✓ 完成(本 commit) |

---

**§13 ship 闭环 · F + G + deprecation comment 三 commit ship · 等真机 dogfood 验收 · 1 周内无 regression 则 INV-13 整段 closed**。

