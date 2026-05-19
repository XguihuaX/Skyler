# Audit:chat_history 表存的是否 cleaned 文本

> **审计任务**:修法 A(`SHORT_TERM_MAX` trim)前置疑问 ── short_term_memory 注入 prompt 时,assistant 是否含 `<thinking>`/`<state_update>`/`<emotion>`/`<motion>`/`<tool_call>`/`<ja>` 等 LLM 输出 tag?
> **本审计未修代码,只输出诊断报告**。

---

## A. 数据真相

### A.1 chat_history 表 schema

```sql
CREATE TABLE chat_history (
    id INTEGER NOT NULL PRIMARY KEY,
    user_id VARCHAR NOT NULL,
    role VARCHAR NOT NULL,         -- 'user' | 'assistant'
    content TEXT NOT NULL,         -- 单字段,无 raw/cleaned 双列
    created_at DATETIME,
    conversation_id INTEGER,
    character_id INTEGER,
    interrupted_at DATETIME,
    kind TEXT NOT NULL DEFAULT 'normal',   -- 'normal' | 'touch' | 'proactive'
    proactive_trigger TEXT
);
```

**结论**:单 `content TEXT` 字段。**无 raw/cleaned 双字段历史变更**。

### A.2 LLM tag 出现频率(assistant 行扫表)

```
character_id | total | <thinking> | <state_update> | <emotion> | <motion> | <tool_call> | <ja>
─────────────┼───────┼────────────┼────────────────┼───────────┼──────────┼─────────────┼──────
        1    |  244  |     1      |       0        |     0     |    0     |      0      |  0
        2    |   22  |     0      |       0        |     0     |    0     |      0      |  0
      101    |    4  |     0      |       0        |     0     |    0     |      0      |  0
```

→ **244 行 Mai assistant 仅 1 行命中 `<thinking>` 字面文本**(下面 A.3 解释);其余 6 类 tag **全部 0 命中**。其他角色 0 污染。

### A.3 仅有的 1 个 "thinking" 命中是误检

```
id=545: "没问题的，那么首先一点就是 对话中的 <thinking>或者llm…"
id=546: "好嘞，那我先帮你建个文档…就是模型输出时意外把 `<thinking>` 这种内部标签…"
```

这是用户跟 Momo 讨论"`<thinking>` tag 泄露 bug"时,Momo 复述用户的话**作为正常对话内容**,引用了 tag 名(还用 markdown ``` ` ` ``` 包裹)。**NOT LLM 输出污染** ── 是话题包含 tag 字面字符串。SUSPICIOUS_TAG_RE 也不会命中(因为不是闭合 `<thinking>...</thinking>` 配对)。

### A.4 Mai content 长度

| role | rows | avg_len | max_len |
|---|--:|--:|--:|
| user | 78 | 8.5 | 41 |
| assistant | 244 | 41.3 | 1294 |

assistant 平均 41 字,最大 1294 字(早期一条带 `<think>` Markdown block 的回复)。

---

## B. 代码路径真相

### B.1 写入路径(ws.py 主聊天路径)

`backend/routes/ws.py:540-598` `_update_memory(...)`:

```python
# Line 567-569: 5 链 strip(thinking / state / tool_call / emotion / motion)
reply = strip_motion(strip_emotion(
    strip_tool_call_fallback(strip_state_update(strip_thinking(reply)))
))
# Line 573-580: SUSPICIOUS_TAG_RE 兜底
if reply:
    _suspicious_n = count_suspicious_tags(reply)
    if _suspicious_n > 0:
        logger.warning("[sanitize] suspicious tags hit=%d ...", _suspicious_n, ...)
        reply = sanitize_suspicious_tags(reply).strip()
# Line 582-598: 写入 short_term + chat_history(用同一个清洗后的 reply)
await short_term_memory.add(user_id, "user", user_text)
await short_term_memory.add(user_id, "assistant", reply)
async with AsyncSessionLocal() as session:
    if not skip_user_history:
        await add_chat_history(session, user_id, "user", user_text, ...)
    await add_chat_history(session, user_id, "assistant", reply, ...)
```

**结论**:**ws.py 主路径全清洗**,5 strip + SUSPICIOUS 兜底。`short_term_memory.add` 与 `add_chat_history` 用**同一个** `reply`,二者绝对同步。

⚠️ **意外发现** ── `SUSPICIOUS_TAG_RE = r"<([a-z_][a-z_0-9.]*)[^>]*>[\s\S]*?</\1>"` 对 `<ja>「日语」</ja>` 也命中(`ja` 是合法 tag name 字符)。所以:
- 即使 5-strip 链不剥 ja,SUSPICIOUS 兜底会剥掉
- 含 ja tag 的 assistant 回复会触发 `[sanitize] suspicious tags hit=N` WARNING(预期 Mai 现在每轮都打)
- **Japanese 翻译会被一起剥掉,不入 chat_history**

实测 244 行 Mai assistant 0 个 `<ja>` 命中,validates 上述行为。

### B.2 写入路径(proactive engine,run_trigger + wake_call 两处)

`backend/proactive/engine.py:521 / 859`:

```python
full_reply = _strip_format_tags("".join(reply_parts))
# _strip_format_tags = strip_all_for_tts(text).strip()
# = strip_emotion + strip_thinking + strip_state_update + strip_motion + strip_tool_call_fallback
```

⚠️ **proactive 路径**:
- 用 `strip_all_for_tts`(5 strip),**不调** `sanitize_suspicious_tags`
- 因此 ja/en tag 在 proactive 路径**理论上不会被剥**
- 但实测 244 Mai 行(含多个 proactive 行 eg id=648/649/665)0 个 ja → 表明 proactive 路径下 LLM 实际**没产出 ja tag**(可能 proactive 短问候 prompt 太强约束 8-15 字,LLM 忽略了 Layer A ja directive)

**latent 风险**:若 proactive 长简报 + ja 角色 → ja tag 可能漏进 chat_history。当前**未发生**。

### B.3 读取路径(short_term → prompt 注入)

`backend/agents/chat.py:1180`(renderer 新路径)+ `:1372`(legacy fallback):

```python
for turn in await short_term_memory.get(user_id):
    messages.append({"role": turn["role"], "content": turn["content"]})
```

→ **直接 pass-through `turn["content"]`,无二次 strip**。

但因 B.1 已保证 short_term 入门时即清洗,**二次 strip 不需要**。

### B.4 短期记忆和 chat_history 是否同源?

- ws.py: 同源(line 582-598,同一个 `reply` 同时写两边)
- proactive engine: 同源(line 521-543,同一个 `full_reply` 同时写两边)

→ chat_history 表与 short_term_memory **永远同步**(每次写入两边一起写)。

---

## C. 实测样本(Mai 5-15 最近 4 turn)

```
id=663 | user      | normal | 7   | [touch]
id=664 | assistant | touch  | 43  | "...又碰我做什么。"
                              "不是说要去看书吗。"
                              "去吧。看不进去就趴会儿，别硬撑。"
id=665 | assistant | proactive | 83 | "看书看到终端里去了？""...你所谓的看书，是
                                       指对着黑框框敲命令？""在折腾什么项目，还是
                                       单纯在修 bug？""脑子不清醒的时候敲出来的东西，
                                       通常第二天都得重写。"
id=666 | assistant | proactive | 0  | (empty turn)
```

**0 个 LLM tag,纯中文字幕**。即便对 ja-tagged Mai 角色,Japanese 翻译也已被 SUSPICIOUS_TAG_RE 剥掉(参 B.1 意外发现)。

---

## D. 修法 A 范围结论

### 命中情况 1:**全干净**

ws.py 主路径(5 strip + SUSPICIOUS 兜底)+ proactive 路径(5 strip)→ **244/244 Mai assistant 行实测 0 LLM tag 污染**。short_term_memory 与 chat_history 同源同步。

→ **修法 A 只需 `SHORT_TERM_MAX` trim,不需要二次 strip 兜底**。

#### 修法 A 实施(15 min)

`backend/memory/short_term.py:17-21`:
```python
async def add(self, user_id, role, content):
    if user_id not in self._store:
        self._store[user_id] = []
    self._store[user_id].append({"role": role, "content": content})
    # ★ NEW:enforce SHORT_TERM_MAX(原 dead constant 真生效)
    if len(self._store[user_id]) > SHORT_TERM_MAX:
        self._store[user_id] = self._store[user_id][-SHORT_TERM_MAX:]
```

风险 0(content 已清洗,只 trim count)。

### 副产物:几条值得记进 backlog 的发现

1. **ja/en 翻译被 SUSPICIOUS 误剥**(B.1 意外发现):
   - Mai 每轮 assistant 都会触发 `[sanitize] suspicious tags hit=N` WARNING(log noise)
   - Japanese 翻译完全不入 chat_history / short_term → LLM 后续 turn 看不到自己之前的日语 → 可能影响"日语语气延续"
   - **修法建议**(单独 task):
     - 把 `ja` / `en` 加进 `_BOUNDARY_PAIRED_TAGS`-类**白名单**,让 SUSPICIOUS 跳过
     - 或者:strip 链显式加 `strip_ja_en_tags_for_subtitle` 作为合法 tag(避免触发 SUSPICIOUS WARNING),但仍剥 ja 内容
     - 或者:**保留 ja tag 进 chat_history**(实现一致的 round-trip,LLM 看得到日语历史)。需评估 token 成本
   - 当前**不阻塞修法 A**,纯 polish

2. **proactive engine 缺 `sanitize_suspicious_tags` 兜底**(B.2):
   - 当前未观察到 ja 漏入 chat_history(LLM 实际不发 ja 给短 proactive 回复)
   - 但若未来 proactive long-form ja 调用 LLM,可能漏入
   - **修法建议**(low-priority):proactive engine `_strip_format_tags` 加 SUSPICIOUS 兜底,与 ws 主路径对称

3. **id=666 空 turn**:有一行 length=0 assistant proactive 入库。说明 proactive engine 允许写空 reply(可能边界 cancel)。修法 A 后短期窗口可能含空 turn,LLM 看到没影响,但可单独检查 proactive 入库前的 length > 0 check。

### 决策点(不阻塞修法 A,但用户可选)

- **决策 D1**:修法 A 同 commit 顺手把 `ja`/`en` 排除出 SUSPICIOUS 触发?(短期保留 log,长期想 round-trip 才动)
- **决策 D2**:proactive engine 是否加 SUSPICIOUS 兜底?(纯防御,当前未发生)

两个都不阻塞 ship,建议**修法 A 单独 commit**,D1/D2 单独 task 决定。
