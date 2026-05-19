# Audit:Chat 单次 LLM 调用 input tokens 膨胀根因定位

> **审计任务**:阿里云 5-14 单日 ¥22.7 全在 qwen3.6-max-preview;单次最贵 68,679 input tokens,平均 ~10k tokens/call。定位膨胀来源。
> **本审计未修任何代码**。修法等用户确认后再开新 task。

---

## 1. 数据真相

### 1.1 chat_history(SQLite 持久层)

| character_id | name | rows | avg_len | max_len | total_chars |
|--:|---|--:|--:|--:|--:|
| 1 | Momo/Mai | **322** | 33.4 | 1294 | 10,747 |
| 2 | 八重神子 | 33 | 50.7 | 237 | 1,672 |
| 99 | 一般路过猫娘 | 29 | 2.0 | 2 | 58 |
| 101 | 樱岛麻衣 | 7 | 26.7 | 61 | 187 |

- Mai 322 turns 跨 **2026-05-07 ~ 2026-05-15**(8 天)
- 5-14 单日 75 turns,5-13 59 turns,5-12 46 turns;最大单条 1294 chars(`<think>` block)
- **总计 10.7k chars** ── 小,即便全量注入也只占 ~5k tokens

### 1.2 activity_sessions

| day | sessions | total_sec | avg_meta_len | max_meta |
|---|--:|--:|--:|--:|
| 2026-05-14 | **351** | 35,586(9.9 h) | 30.3 | 723 |
| 2026-05-15 | 46 | 4,800 | 44.7 | 223 |
| 2026-05-13 | 219 | - | - | - |

5-14 单日 351 sessions。若全部 dump 进 prompt → 10-15k chars。**但** `format_today_activity_for_prompt` 已聚合 top-5 apps + 30 字 title 截断,实测输出 ~300-500 chars,这条 NOT 嫌疑。

### 1.3 memory 表

| character_id | rows | avg_len | total_chars |
|--:|--:|--:|--:|
| 1 | 13 | 10.7 | 139 |

13 条 × avg 11 chars = 139 chars 总,top_K=5 检索后更少。**这条完全 NOT 嫌疑**。

### 1.4 TTS 调用 5-14(推 chat 节奏)

| source | calls | total_input_chars |
|---|--:|--:|
| chat | 85 | 1,224 |
| activity_smart | 40 | 800 |

→ Mai 5-14 主动 + 被动加起来 **125 个 LLM 触发的 chat round**。

---

## 2. 代码路径真相

### 2.1 chat_history 注入

**chat_history 表本身 NOT 注入 prompt**。`_build_messages` 走 `short_term_memory.get(user_id)`,**进程内存**结构。

但 ⚠️:
- `backend/memory/short_term.py:10` `SHORT_TERM_MAX: int = 50` ── **dead constant!**
- `short_term.py:17-21` `add()` 方法**直接 append,不 trim**:
  ```python
  async def add(self, user_id, role, content):
      if user_id not in self._store:
          self._store[user_id] = []
      self._store[user_id].append({"role": role, "content": content})  # ← 无上限
  ```
- 全 backend 没有任何 caller 调 `short_term_memory.trim()`(grep 确认):仅 tests 文件
- `clear_short_term` tool(builtin.py:28)是**唯一**清理路径,但需要 LLM 主动调

**含义**:backend 启动后**短期记忆永远只增不减**,直到 backend 重启或用户说"清空对话"。如果 Mai 用户连续聊几小时,short_term 可累积**百+条 turns**。

### 2.2 today_activity 注入

`backend/services/activity_timeline.py:384` `format_today_activity_for_prompt()`:
- query 当天所有 idle-filtered=0 sessions
- aggregate by app_name → top-5 apps
- 每个 app 显示 1 个 top URL host + 30 字 title 截断
- 输出 ~6 行,实测 300-500 chars
- **✓ 已有合理上限**

### 2.3 long_memory top_K

`backend/memory/long_term.py:279` `top_k: int = 5`,`_build_messages` 调 `search_relevant_memories(user_id, query=text, top_k=5)`(chat.py:1093 / 1325)。memory 表共 13 条,top-5 最多 5 条 × ~11 chars。**✓ 已 enforce**。

### 2.4 token budget 截断

`_build_messages` **无任何 token budget 截断逻辑**。无 `truncate_if_over_N` / `tiktoken` / 字符上限检查。

### 2.5 Tool 调用 message 累积

`backend/agents/chat.py:1659-1663`:
```python
messages.append({
    "role": "tool",
    "tool_call_id": ...,
    "content": json.dumps(result, ensure_ascii=False),  # ← 无截断
})
```

**每个 tool result 全量 JSON dump 进 messages**。`max_rounds = 5`(line 1506),单 user-turn 最多 5 轮 LLM 调用,每轮**累加**所有 prior round 的 tool 结果。

各工具的返回上限:
- `screen.get_browser_content`:`max_chars` 参数,默认 5000,LLM 可改到 20000 ✓
- `xhs.parse_url` / `bilibili.get_subtitles` / `activity.search_history`:**无明显上限**(待 deep audit 但本 audit 不展开)
- 单工具异常返大 result(eg 长字幕)轻易 5-20k chars

---

## 3. 实测各 Layer 字符数

跑 `_build_messages('Skyler', '学姐好', character_id=1, turn_origin='user')`(冷启动 — 无 short_term / 无 profile / 无 activity):

| Section | chars | 备注 |
|---|--:|---|
| Layer A 头(`[输出格式规范]` + tag specs) | 615 | A1 核心 |
| **Layer A ja directive(seg2-3)** | **1,179** | 意群+示例,seg2-3 加长 |
| Layer B 模式头(`[本轮模式: roleplay]`) | 113 | |
| Layer B 行为基线(universal_constraints) | 493 | |
| **`_TOOL_PROMPT_ADDENDUM`(seg1 D-1 留账)** | **5,109** | 70 行 prose,所有 turn 重复 |
| Layer C(Mai persona 满字段) | 2,593 | persona 真值,合理 |
| Layer C 运行时状态 | 79 | mood/intimacy/state |
| Layer D(冷启动,无 profile/activity/memory) | 21 | 只 section header |
| **system_prompt TOTAL** | **10,202** | |
| user message("学姐好") | 3 | |
| **tools schema JSON(58 capabilities)** | **24,034** | 每 round 重传 |
| **GRAND TOTAL 冷启动 1 round** | **~34,239 chars** | ≈ 18-22k tokens |

### 3.1 Tools schema top 25(共 58 tools)

| chars | tool name |
|--:|---|
| 831 | apple_calendar.create_event |
| 790 | xhs.parse_url |
| 788 | save_memory |
| 689 | docx.create |
| 685 | activity.search_history |
| 663 | bilibili.get_subtitles |
| 598 | character.set_activity |
| 569 | docx.append |
| 557 | netease.daily_recommend |
| 530 | netease.local_play_playlist |
| 526 | bilibili.get_video_info |
| 518 | activity.get_recent_apps |
| ... | (其余 33 tools) |

top-10 tools 占 6,700 chars,top-25 占 14k 字。

---

## 4. 根因定位(按嫌疑度排序)

### 🔴 #1 ── tools schema 24,034 chars/call

58 个 capability tool 每轮 LLM 调用**全量重传**。58 中很多是 niche tool(eg `netease.local_play_playlist` / `bilibili.get_my_followings` / `docx.append`),日常 chat 用不到。

- **每 round 固定开销**: ~10k tokens(JSON 偏 ASCII,token 密度低)
- **5-14 ¥22.7 中估计 ~50% 来自这条**

### 🔴 #2 ── short_term unbounded

`SHORT_TERM_MAX=50` 是 dead constant,`.add()` 不 trim。

- Mai 8 天 322 turns ── 单次重启间累积 50-100 turns 很正常
- 100 turns × avg 100 chars(含 think block 实际偏大)= 10-30k chars
- **可贡献 5-15k tokens/call**,跟 backend 启动时长成正相关
- 解释了"持续运行后单次调用越来越贵"现象

### 🔴 #3 ── `_TOOL_PROMPT_ADDENDUM` 5,109 chars/call

seg1 D-1 sign-off **已知** tech debt,延 v4.1。70 行硬编码 prose,与 tools schema description 部分重叠。

- ~2-3k tokens/call,所有 turn 重复
- 重构后预计降到 1,500 chars(seg1 audit 估算)

### 🟡 #4 ── Tool result append 无截断

`messages.append({"role":"tool","content":json.dumps(result)})` (chat.py:1662)。

- `screen.get_browser_content` 上限 20k 字 ✓
- `xhs.parse_url` / `bilibili.get_subtitles` 未审,可能无上限
- 单 round 一个工具返 10k chars → 下一 round prompt 多 5k tokens
- **单次最贵 68,679 tokens 可能来自这条**(prior tool 返长 + 多 round 累积)

### 🟡 #5 ── Layer A ja directive 1,179 chars

seg2-3 引入意群规则 + 3 example。功能必需但可压。

- 估能压到 600-800 chars(合并 ✓/✗ example)
- ~300 tokens/call 节省

### 🟢 #6 ── Layer C Mai persona 2,593 chars

实际 persona 数据,not bloat。8 字段全填(身份卡/性格/说话风格/口头禅/voice_samples/forbidden_phrases/relationship/preferences 等)。**保持现状**。

### 🟢 #7 ── Layer D(profile/activity/memory)冷启动 21 chars

已有合理上限:
- `format_today_activity_for_prompt`:top-5 apps + 30 字 title 截断 → ~500 chars max
- `long_memory top_K=5`:5 条 memory bullets
- `format_profile_for_prompt`:固定模板
- 即使热启动也 ~1-2k chars 上限

**NOT 嫌疑**。

### 🟢 #8 ── chat_history 表 NOT 直接注入

`short_term_memory` 是进程内存,与 DB chat_history 表无关。表 10.7k chars 不进 prompt。

---

## 5. 修法建议(按 ROI / ETA)

### A. 🥇 ETA 15 min ── `SHORT_TERM_MAX` 真生效

`backend/memory/short_term.py:add` 加 trim:
```python
async def add(self, user_id, role, content):
    if user_id not in self._store:
        self._store[user_id] = []
    self._store[user_id].append({"role": role, "content": content})
    # ★ 修法
    if len(self._store[user_id]) > SHORT_TERM_MAX:
        self._store[user_id] = self._store[user_id][-SHORT_TERM_MAX:]
```

**节省**:long-session 下 5-15k tokens/call。直接砍掉根因 #2。

### B. 🥈 ETA 30 min ── tool result 截断

`backend/agents/chat.py:1659-1663` 加上限:
```python
result_json = json.dumps(result, ensure_ascii=False)
TOOL_RESULT_MAX = 3000  # chars,新 constant
if len(result_json) > TOOL_RESULT_MAX:
    truncated = result_json[:TOOL_RESULT_MAX] + '... [truncated]'
    logger.warning(
        "tool %s result truncated %d → %d chars",
        name, len(result_json), len(truncated),
    )
    result_json = truncated
messages.append({"role": "tool", "tool_call_id": ..., "content": result_json})
```

**节省**:多 round 场景下 5-30k tokens/call。直接砍根因 #4。

### C. 🥉 ETA 2-4 hours ── `_TOOL_PROMPT_ADDENDUM` 重构(v4.1 已规划)

seg1 D-1 已留账。审 LiteLLM auto tools schema 重复行,保留 3 条策略并入 Layer B2,删剩余冗余。

**节省**:~2-3k tokens/call。所有 round 减。

### D. ETA 2-3 hours ── tools schema 精简

策略选项:
- 短 description:每 tool desc 砍 50%(从 400 → 200 chars)→ -10k chars
- 按 turn_origin 动态加载:proactive trigger 不需要 docx / xhs / bilibili 全套
- 按 character 配 capability_overrides(Tier-2 字段已 schema 占位)

**节省**:5-10k tokens/call。需要先决定剪哪些(可联合 #C 一起做)。

### E. ETA 30 min ── Layer A ja directive 压缩

合并 ✓/✗ 多示例。**节省**:~300 tokens/call。

### F. ETA 1-2 hours ── xhs/bilibili tool result 加 max_chars

`xhs.parse_url` / `bilibili.get_subtitles` 参考 `screen.get_browser_content` 加 LLM 可调 max_chars 参数,默认 3000-5000。

**节省**:配合 #B,降低需要截断的频率。

---

## 6. 综合 ROI 摘要

| 修法 | ETA | 节省 tokens/call | 累积节省(125 calls/天 × 假设) |
|---|--:|--:|--:|
| **A** SHORT_TERM_MAX trim | 15 min | 5-15k | ~1M tokens/天 ≈ ¥10/天 |
| **B** tool result 3k 截断 | 30 min | 5-30k | ~2M tokens/天 ≈ ¥15/天 |
| **C** ADDENDUM 重构 | 2-4 h | 2-3k | ~300K tokens/天 ≈ ¥3/天 |
| **D** tools schema 精简 | 2-3 h | 5-10k | ~900K tokens/天 ≈ ¥8/天 |

**A+B 一起做(总 45 min)预计已能让 5-14 ¥22.7 类调用降到 ~¥7-10/天**,68,679 tokens 单次最贵调用应回落到 25-30k 区间。

---

## 7. 注意事项 / 风险

1. **修法 A**:trim 短期记忆可能影响 LLM 长 context recall(用户提的事忘了)。配合 **long_term memory 已开**(top_K=5)做覆盖,且 chat_history 表持久(可走 conversation 历史接口查)。
2. **修法 B**:tool result 截断不能破坏 JSON structure(LLM 依赖结构化字段)。建议截断 `content` / `text` 等长字段而非整 JSON。或保留 outer keys + 截断 inner value。
3. **修法 C 与 v4.1 segment 1 D-1 留账重叠**,可一起做。
4. **修法 D 与 capability_overrides(Tier-2 字段)有协同**:per-persona 配 tool 白名单。Mai 不需要 docx / xhs。

---

## 8. 等用户确认

请决定:
1. 修法 A(15 min)是否立刻做?── 极低风险,巨大收益。
2. 修法 B(30 min)的 `TOOL_RESULT_MAX=3000` 合理吗?(可调)
3. 修法 C 是合并到 v4.1 还是单独 hotfix?
4. 修法 D 要 trim 哪些 tool?(待新 task spec)
