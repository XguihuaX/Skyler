# v4 Persona Engineering — Segment 1 前置 Audit 发现

> Phase 0 deliverable。**未写任何代码、未跑 migration、未改 schema。**
> 用户 sign-off + 补齐 Phase 1/2/3/5 缺的 spec 后才进 Phase 1。

---

## 0.1 现有 prompt 链路

### Prompt assembly 文件位置(spec 有路径错误,见决策点)

| spec 描述 | 实际路径 |
|----------|---------|
| `backend/agents/prompt_manager.py` | **不存在**。实际在 `backend/config/prompt_manager.py`(97 行) |
| 拼装主路径 | `backend/agents/chat.py::_build_messages`(行 1115–1310) |

### `prompt_manager` 调用方(grep 全量)

| 文件:行 | 调用 | 用途 |
|--------|------|------|
| `backend/config/prompt_manager.py:96` | `prompt_manager = PromptManager()` | module-level singleton,**进程启动时 yaml 一次加载并缓存** |
| `backend/agents/chat.py:50,1166` | `prompt_manager.get_prompt(user_id)` | **DB persona 查不到时的 fallback**(主路径走 DB `Character.persona`) |
| `backend/tools/builtin.py:10,20` | `prompt_manager.switch_character(user_id, character_id)` | LLM tool `switch_character` 入口 |
| `backend/routes/ws.py:59,837` | `prompt_manager.get_current_character(user_id)` | WS 每轮取当前角色名(写 audit log + DB lookup key) |

**共 3 个外部模块调用方** + 1 个 module-level singleton。Phase 4 全部要切到 `renderer.render_system_prompt(...)` 或对应迁移路径。

### 实际拼装顺序(`_build_messages` 行 1115–1310)

spec 提到"当前 9 段" —— 实测是 **1 个合并的 `head_parts` system 段** + **6 个可选的 system_parts 追加段** + **短期 history(独立 message role)** + **当前用户 message**。

| 序号 | 内容 | 来源 | chat.py 行 |
|-----|------|------|-----------|
| 1 | `emotion_inst` — `<emotion>` 标签格式 | `_build_emotion_instruction()` | 100 / 1169 |
| 2 | `thinking_inst` — `<thinking>` 标签格式 | `_build_thinking_instruction()` | 144 / 1170 |
| 3 | `motion_inst` — `<motion>` 标签格式 | `_build_motion_instruction()` | 196 / 1171 |
| 4 | `state_inst` — `<state_update />` 格式 + **当前 mood/intimacy/thought/activity 数值** | `_build_state_update_instruction(state_dict)`,state 来自 `character_states` 表 | 287 / 1176–1193 |
| 5 | `BASE_INSTRUCTION` | `backend/config/prompts.py:3-11`,via `get_base_instruction()` | 1168 / 1200 |
| 6 | `persona_block` = `db_persona`(主)or `prompt_manager.get_prompt(user_id)["system_prompt"]`(fallback),**追加 `BASE_INSTRUCTION`(主路径)**,再追加 `_TOOL_PROMPT_ADDENDUM` | `Character.persona` ↔ `characters.yaml` | 1148–1167 / 1201 |
| 7 | `_TOOL_BEHAVIOR_BLOCK` | chat.py:556–570 | 1204 |
| **--** | **以上 7 段 `"\n\n".join` 进 head_parts → `system_parts[0]`** | | 1198–1205 |
| 8(可选) | 用户画像 `【用户画像】...` 或 `format_profile_for_prompt(...)` | `users.profile_data` / `profile_summary` | 1216–1229 |
| 9(可选) | 今日活动 `format_today_activity_for_prompt(...)` | `activity_sessions` 表 | 1236–1245 |
| 10(可选) | `【相关长期记忆】` Top-5 | `memory` 表向量检索 | 1252–1258 |
| 11(可选) | `【工具调用结果】` | legacy MemoryAgent tool_result | 1261–1262 |
| 12(可选) | `【临时指令】` | per-turn `extra_system`(触摸事件 / proactive sentinel) | 1264–1266 |
| 13(可选) | `【proactive 简报】` | `pending_briefings` 表 + `build_stage2_addendum(...)` | 1268–1295 |
| **--** | **以上 6 段以 `"\n\n"` 追加到 `system_parts`** | | |
| 14 | `system_prompt = "\n\n".join(system_parts)` | | 1297 |
| 15 | `messages = [{"role":"system", "content":system_prompt}]` | | 1303 |
| 16(可选) | 短期对话 turns(role=user/assistant) | `short_term_memory.get(user_id)` | 1304–1306 |
| 17 | 当前用户输入 `{role:user, content:text}` | 函数入参 | 1309 |

> **澄清**:spec 说"9 段"应理解为"head_parts 7 个 + 后续 5–6 个可选追加",我后续按这个口径设计 5 层渲染框架时会**保留全部 13 个内容点位**,只是用 layer A/B/C/D 重新分桶。

### 三段硬编码常量原文(摘要)

**`BASE_INSTRUCTION`**(`backend/config/prompts.py:3-11`):
```
你收到的输入通常包括三部分：
1. 【近期对话记录】：你与用户最近的几轮对话内容,可作为语境参考;
2. 消息：用户的当前输入;
3. 反馈：工具或其他 Agent 执行的结果,如 ToolAgent 调用工具函数后的反馈,
   或 MemoryAgent 的记忆内容、计划建议等。如有则结合消息进行总结表达。

请你根据这些内容,自然地回复用户。语气亲切、有分寸,可以简洁,也可以适当延展,
但不要啰嗦或堆砌情绪。
```
共 **9 行**,固定字符串,不参数化。

**`_TOOL_BEHAVIOR_BLOCK`**(`backend/agents/chat.py:556-570`,~15 行):
讲"调工具前必须先输出 6–15 字过渡语",含 4 句示例 + 2 条"绝对避免"。

**`_TOOL_PROMPT_ADDENDUM`**(`backend/agents/chat.py:573-` 至少 80+ 行):
按类别枚举工具用法 ——【日历类】【日程录入】【时间类】【记忆类】【系统类】【音乐类】【媒体控制】【角色状态】【剪贴板】【小红书 URL 解析】【网易云本地 mpv】……每类 3–8 行,共约 **80–110 行**。**与 LiteLLM 自动注入的 `tools=[...]` schema 部分重复**(见决策点 D-1)。

---

## 0.2 Sanitize 链路(invariant,**绝不能破**)

### 状态机识别的 tag 全集

#### A. **chat.py 内 inline parse**(per-turn 实时剥):

| Regex / 函数 | 识别 | chat.py 行 |
|-------------|------|-----------|
| `_EMOTION_RE = r"<emotion>(.*?)</emotion>(.*)"` | `<emotion>X</emotion>` **强制首位** | 77 |
| `_THINKING_RE = r"<thinking>([\s\S]*?)</thinking>"` | `<thinking>X</thinking>` 多行 | 116 |
| `_THINKING_OPEN_RE = r"<thinking>"` | 流式 partial 检测 | 117 |
| `_MOTION_RE = r"<motion>([^<]*)</motion>"` | `<motion>X</motion>` 段内任意位置 | 167 |
| `_STATE_UPDATE_RE` | `<state_update ... />` 自闭合 + 容错 `<state_update>...</state_update>` | 229–233 |
| `_STATE_UPDATE_ATTR_RE` | 属性切片:`mood / intimacy_delta / thought / activity` | 235–237 |

#### B. **utils/text_filters.py 内 strip pipeline**(写库前 + TTS 前):

| 函数 | 用途 | 行 |
|------|------|---|
| `strip_thinking(text)` | 去 `<thinking>...</thinking>` | 28 |
| `strip_state_update(text)` | 去自闭合 + 容错变体 | 58 |
| `strip_emotion(text)` | 去 `<emotion>...</emotion>` | 234 |
| `strip_motion(text)` | 去 `<motion>...</motion>` | 216 |
| `strip_tool_call_fallback(text)` | 去 `<tool_call>` / `<function_calls>` / `<invoke>` / ` ```json ` markdown / `<docx.create(...)>` 函数调用风格 | 137 |
| **`strip_all_for_tts(text)`** | **5 链合并**(emotion + thinking + state_update + motion + tool_call_fallback)—— **送 TTS 前必走** | 252 |
| `SUSPICIOUS_TAG_RE` | 白名单否定兜底:`<name>...</name>` 或 `<name />`(name 以 字母/_ 开头,可含 `.`) | 349 |
| `sanitize_suspicious_tags(text)` | 应用上式 | 366 |
| `has_partial_open_tag(text)` | 流式 partial 检测,含 capability-tag `<netease.daily_recommend>` | 378 |
| `sanitize_llm_output(text)` | **code-block-aware** 全套(写库前 / 大段回复整体清理) | 443 |

#### C. **流式 sentence boundary**(`_safe_boundary` / `_find_boundary`,chat.py:353–423):

`_BOUNDARY_PAIRED_TAGS`(chat.py:345):
```python
frozenset({"thinking", "emotion", "state_update", "motion",
           "tool_call", "function_calls", "invoke"})
```
**任何新增的 paired tag(eg Layer A1 spec 里若加 `<persona_lock>` / `<voice_anchor>`)必须同时加进这个 frozenset,否则 `<state_update thought="...粗心了。" />` 这类含 `。/！/？` 的 attr 会被句末切句切坏**(bugfix-1.1 已经因此爆过)。

### state_update 解析 → DB 写入路径

```
chat.py::_parse_state_update(text)       # 280–284 行解析为 dict
  → routes/ws.py 消费 dict
    → backend/database/services.py::update_character_state(...)  # clamp + validate
      → character_states 表 UPDATE
```

`intimacy_delta` clamp 在 `services.py:607` 附近,**LLM 拼错时静默丢弃**而不是整轮挂掉(这是 invariant)。

### TTS 剥 tag 在哪一步

`backend/utils/text_filters.py::strip_all_for_tts(text)`(行 252)—— 5 链合并,**每个 sentence(per `_sentence_stream` yield 出来的 unit)送 cosyvoice / edge / sovits 之前必走**。Bugfix-4 起 `tts_call_log.input_chars` 记录的就是剥后字符数,可用于异常 call 检测(`input_chars > 500` 通常是 thinking/state tag 漏剥)。

### Regression baseline(必须 0 改动 / 0 失败)

| 文件 | 行 | 测试数 | 覆盖 |
|------|----|-------|------|
| `tests/test_sanitize_llm_output.py` | 202 | 10 个 test func | docx.create() 函数调用风格、fenced code 内 tag 保留、HTML attrs 不误剥、state_update 自闭合、嵌套 brackets 等 |
| `tests/test_suspicious_tag_sanitize.py` | 193 | 14 个 test func | capability-tag(`<netease.daily_recommend>`)、`<3` `<=` 不误判、`\1` 反向引用 cross-tag 配对、partial-open 流式检测 |
| `tests/test_tool_name_sanitize.py` | 270 | 16 个 test func | tool name `.`/`:`/`/` / 中文 → `_`,reverse_map 一致性 |

> **本 segment 改动如违反这些 invariant 必须停下来沟通**,不能私自调整 sanitize 链。Layer A1 / A2 模板 spec 看上去只用现有 4 个 tag(emotion/thinking/motion/state_update),理论上**0 改动**,但需验证。

---

## 0.3 character / state 表

### `characters` 实测 schema(`PRAGMA table_info`)

```
0  id                INTEGER PRIMARY KEY NOT NULL
1  name              VARCHAR NOT NULL  (UNIQUE)
2  persona           TEXT NOT NULL
3  avatar_path       TEXT
4  created_at        DATETIME           DEFAULT CURRENT_TIMESTAMP
5  voice_model       TEXT
6  live2d_model      TEXT
7  emotion_map_json  TEXT
8  motion_map_json   TEXT
9  hit_area_map_json TEXT
10 background_path   TEXT
11 splash_art_url    TEXT
```
**12 列**(spec 说 11 列;`id` 也算上是 12 — 不含 id 是 11 内容列。下文以 12 为准)。

### `character_states` 实测 schema

```
0  id                  INTEGER PK
1  character_id        INTEGER NOT NULL  (UNIQUE,**无 ForeignKey**)
2  mood                VARCHAR(32) NOT NULL DEFAULT 'neutral'
3  intimacy            INTEGER NOT NULL DEFAULT 0
4  current_thought     TEXT
5  current_activity    VARCHAR(64)
6  last_interaction_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
7  updated_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
```

### 实测脏数据 + 孤儿行

JOIN 出来 19 行 character_states,只有 **7 行**对应 `characters` 表里真实角色:

| character_id | mood | thought_len | characters.name |
|--------------|------|-------------|-----------------|
| 1 | curious | 15 | Momo |
| 2 | curious | 18 | 八重神子 |
| 3 | neutral | 0 | 荧 |
| 4 | neutral | 0 | 凝光 |
| 5 | calm | 12 | 神里绫华 |
| 99 | neutral | 0 | 一般路过猫娘 |
| 100 | neutral | 0 | 祥子-test |
| **300–306** | mixed | 含 1 行 **60-char 全 'x'** | **❌ characters 无此 id** |
| **400** | neutral | 0 | **❌ orphan** |
| **500** | neutral | 0 | **❌ orphan** |
| **600** | neutral | 0 | **❌ orphan** |
| **601** | neutral | 0 | **❌ orphan** |
| **700** | neutral | 0 | **❌ orphan** |

→ **12 行孤儿** state 行。
→ id=304 的 `current_thought` 实测 60 个 `x`(原 audit 报告里那条脏数据 confirmed)。

**结论 + Segment 1 隐含改动**:`character_states.character_id` 现在 `nullable=False, unique=True` 但**没有 `ForeignKey`**,所以孤儿不会自动级联。Segment 1 加 `character_personas` 新表时,**孤儿 state 行要不要清理 / 加 FK 约束?** —— 这是决策点 D-3。

### yaml `default_emotion` 字段是否在 characters 表

✅ 确认**不在**。`PRAGMA table_info(characters)` 12 列里没有 `default_emotion`。该字段仅存在于 `backend/config/characters.yaml`,通过 `prompt_manager.get_prompt()` 返回 dict 的 `"default_emotion"` 键。

→ Segment 1 若 character_personas 新表想接管 yaml 全部字段,**需要同时迁 default_emotion** —— 否则 yaml fallback 删不掉。这是决策点 D-4。

---

## 0.4 Migration 规范

### 文件命名约定(实测 33 个 migration)

| pattern | 出现次数 | 例 |
|---------|---------|----|
| `v<X>_<Y>.py` | v2_5_b / v3_b / v3_e1 / v3_e1_z / v3_f | 5 |
| `v<X>_<chunk>_<name>.py` | v3_g_chunk2_proactive / v3_5_chunk10_memory_structured | ~15 |
| `bugfix_<X.Y>_<name>.py` | bugfix_3_1_ai_providers / bugfix_4_observability | 8 |
| `v4_<feature>_chunk<N>_<name>.py` | v4_fan_chunk1_splash_art | 1 |

→ Segment 1 推荐命名:**`v4_persona_chunk1_schema_and_seed.py`** 或 `v4_persona_engineering_segment1.py`。

### 注册流程

**没有 auto-discovery / registry**,纯手动:

1. `backend/database/migrations/<file>.py` 暴露 `async def run_migration() -> None`
2. `backend/main.py` 顶部 import: `from backend.database.migrations.<file> import run_migration as migrate_xxx`(main.py:33–115 现有 29 个 import block)
3. `backend/main.py:lifespan()` 内手动 `await migrate_xxx()`(main.py:194–314 现有 28 个 await 调用,**顺序敏感** —— 部分 migration 依赖前一个跑过)

### 幂等机制

实测范本(`bugfix_4_observability.py:38-60`):
- `CREATE TABLE IF NOT EXISTS ...`
- `CREATE INDEX IF NOT EXISTS ...`
- 数据 seed:`INSERT OR IGNORE` 或先 `SELECT EXISTS` 再决定
- `ALTER TABLE ADD COLUMN` 没有 `IF NOT EXISTS`,需要 try/except catch `OperationalError("duplicate column name")` 模式(参考 v3_b.py / v3_e2_per_character_maps.py)

### Log convention

`logger.info("[<migration-tag>] <what was done>")`,例:
```python
logger.info("[bugfix-4] tts_call_log table + indexes ensured")
```

### `__main__` block(可手跑)

每个 migration 文件结尾(`bugfix_4_observability.py:64-69`):
```python
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, ...)
    asyncio.run(run_migration())
```

### builtin_seed 应内联还是单独 fixture?

实测惯例:**内联 migration**。范本:
- `bugfix_3_3_1_seed_cloned_voices.py` —— migration 内 INSERT seed
- `v3_e2_restore_momo_persona.py:50-61` —— migration 内硬编码 `_CHATAGENT_PERSONA` 常量然后 UPDATE
- `bugfix_3_1_ai_providers.py` —— 4 个 builtin vendor seed 内联

→ **`character_personas_builtin_seed` 应放在 v4_persona migration 文件里作为 module-level dict 常量**,不要单独 fixture。

### Backup 习惯

大改 / 涉及数据清洗的 migration 跑前自动 backup `momoos.db`:
- `momoos.db.backup-before-chunk14`(已存在,现实文件)
- `momoos.db.backup-before-hotfix3`(已存在)
- `momoos.db.backup-before-hotfix8`(已存在)

→ Segment 1 涉及新增表 + builtin seed,**建议加 backup 到 `momoos.db.backup-before-v4-persona-s1`**。

---

## 0.5 现有 yaml 与 DB 的 mapping

### yaml 现有结构(`backend/config/characters.yaml`)

```yaml
characters:
  <name>:
    persona: |
      <自由文本人设描述>
    default_emotion: <TTS 情感标签>
default_character: <name>
```

实测 5 个角色:`八重神子 / 默认 / 荧 / 凝光 / 神里绫华`,`default_character: 默认`。

### yaml 字段 → DB mapping

| yaml 字段 | DB characters 列 | 状态 |
|----------|------------------|------|
| `<name>`(顶层 key) | `name` | 一对应,但 yaml 用 `默认`、DB 用 `Momo` —— 历史改名错位(原 audit §5.1 记录) |
| `persona` | `persona` | 一对应,DB 主源,yaml fallback |
| `default_emotion` | **❌ 无对应列** | yaml 独占 |
| **❌** | `avatar_path` `voice_model` `live2d_model` `*_map_json` `background_path` `splash_art_url` `created_at` | DB 独占,yaml 无 |

### Migration 行为(实测)

- `v3_e2_restore_momo_persona.py` 用硬编码 `_CHATAGENT_PERSONA` 字符串 + fingerprint 比对反推"DB 里 Momo 的 persona 是不是被覆盖了" → 若是则 UPDATE 回原文。
- yaml 是 **first-run seed** 的角色,后续 DB 改了 yaml 不会跟着改。
- yaml 至今**不会**被任何 migration 覆盖。

### 跟 Phase 1 spec 的兼容性

Phase 1 用户 spec 提到 `character_personas` 是**新表**(spec 完整内容未贴,但从 segment naming 看是 multi-variant)。如新表设计:
- ✅ 保留旧 `characters` 表不动(spec 已说"留 yaml 作 first-run seed")
- 🤔 `character_personas` 是按 `character_id` 外键关联旧 `characters`,还是独立 name 主键?——**spec 未贴,需补**
- 🤔 default_emotion 迁不迁?——**spec 未明确**

---

## 0.6 跟本 segment spec 的冲突 / 决策点

### D-1. `_TOOL_PROMPT_ADDENDUM` 与 LiteLLM auto tools schema 部分重复

- 现状:`_TOOL_PROMPT_ADDENDUM`(chat.py:573–~660)**~80–110 行**硬编码 prose,LiteLLM 已经会用 `tools=[...]` 把每个 tool 的 description / parameters 注入。
- **重叠程度**:中等。ADDENDUM 提供的是**何时调 / 调用先后顺序 / fallback 行为**(eg "先 time.now 再 create_event"),LiteLLM auto schema 只给单个工具 description —— **二者并非完全冗余**,ADDENDUM 提供的"工作流编排提示"在 schema 里没有。
- **本 segment 建议**:**不删 ADDENDUM 内容**,只是把它从 chat.py 搬到 Layer D 的 jinja partial,内容字字保留。彻底重构留 v4.1。
- **触发"用户决策"条件**:如重构涉及 > 200 行改动 → ping 用户。当前预估改动:挪位置不动文本 ≈ 0 行净增。✅ 不需要 ping。

### D-2. Mode classifier(spec 说 deterministic 2-mode,v4.1+ 再加 automated)

- 现状 `_build_messages` 没有 Mode 概念。proactive 走 `extra_system` 注入 sentinel + `pending_briefings` 表 stage2 addendum 间接区分。
- Renderer 要能感知:
  - `extra_system` 含 sentinel(`wake_call` / `lunch_call` / `dinner_call` / `bedtime_chat` / `long_idle`)→ `Mode.PROACTIVE`
  - 否则 → `Mode.ROLEPLAY`
- **判定逻辑放在 renderer 入参还是 caller?**:建议 caller(`chat.py::_build_messages`)算好 `Mode` 再传给 renderer,**保持 renderer 纯函数,不读 DB / 不解 sentinel**。

### D-3. character_states 12 行孤儿

- 实测孤儿 `character_id` ∈ {300–306, 400, 500, 600, 601, 700}(见 §0.3 表)。
- **本 segment 不属于"persona schema 重构"**,孤儿清理与 character_personas 表无直接耦合。
- **建议**:本 segment **不动孤儿**,只在 audit 里登记。后续单独写 cleanup migration(`v4_persona_chunk_xxx_orphan_states_cleanup.py`)+ 加 FK 约束。
- **触发"用户决策"条件**:无 —— 不涉及 spec 改动。

### D-4. yaml `default_emotion` 字段的归宿

- yaml 独占字段,无 DB 列。
- Segment 1 若 `character_personas` 表完全接管 yaml,**必须包含 `default_emotion` 列**,否则 yaml fallback 永远无法删除。
- **spec 未明确**。请用户 sign-off 时一并确认:
  - **选项 A**:`character_personas` 加 `default_emotion` 列,builtin_seed 内含,Phase 4 yaml fallback 标 deprecated。
  - **选项 B**:`default_emotion` 留 yaml 自己读,character_personas 不管 TTS 字段(更符合"persona = 文字向描述"的语义)。
  - **推荐 A** —— 一处真相,跟 Schema 重构 segment 一起做掉。

### D-5. spec 完整性(必须用户补)

我直接拿到的 Phase 1/2/3/5 spec 里有 4 处 `[这里粘贴...]` 占位符未填:

| Phase | 占位符 |
|------|-------|
| Phase 1 | `[这里粘贴之前 Segment 1 prompt 的完整 Schema spec — character_personas 表 + character_personas_builtin_seed + migration 行为]` |
| Phase 2 | `[粘贴 Layer C1-C4 完整 Jinja 模板,含 vendor-aware forbidden_phrases 注入 + 锚定句]` |
| Phase 3 | `[粘贴 sanitize invariant 要求 + regression test 清单]` |
| Phase 5 | `[粘贴 31+ test case 清单]` |

→ **即使 audit sign-off,缺这 4 段我无法进 Phase 1**。请 sign-off 时一并把这 4 段 spec 贴齐。

### D-6. spec 路径错误

- spec 写 `backend/agents/prompt_manager.py`,实际是 `backend/config/prompt_manager.py`。已按实际路径处理。
- spec 写 `backend/proactive/engine.py`,实际未在 audit 范围深读 —— Phase 0.1 grep 里 `prompt_manager` 不出现在 `backend/proactive/`,proactive 直接调 `ChatAgent.stream()` 走主路径,**与 prompt_manager 无直接耦合**。

### 风险:sanitize 链路改动

按 spec Phase 2 Layer A1 模板,新增 tag = 0(仍只用 `<thinking>` `<state_update>` `<motion>` + `emotion=`),理论上不需改 sanitize。**但**:
- spec 末尾"⭐ Layer A1 模板内容"提到 `emotion="xxx" 嵌入 SSML 或 instruct 参数` —— 这是**属性形式**,而现有路径是 `<emotion>X</emotion>` **标签形式**(`_EMOTION_RE` 强制首位标签)。
- **如果 Layer A1 实际要切到 attribute 风格,会破坏 `_parse_emotion`、`strip_emotion`、`_BOUNDARY_PAIRED_TAGS`、TTS sanitize 链** —— 这是大范围 invariant 破坏,**必须用户 sign-off 沟通**。
- **倾向解读**:模板说"嵌入 SSML 或 instruct 参数"指的是**system 层告诉 LLM 系统会自动注入**,而非 LLM 自己输出 `emotion="..."` 属性。需用户在 sign-off 时确认。

---

## 0.7 预期改动文件清单(Phase 1–4)

**新建**(估 7 文件):
- `backend/database/migrations/v4_persona_chunk1_schema_and_seed.py`(新表 + builtin_seed inline)
- `backend/database/models.py` 加 `class CharacterPersona(Base)`(改文件,非新建)
- `backend/prompts/__init__.py`(新 package)
- `backend/prompts/renderer.py`(`render_system_prompt(character_id, state, profile, mode, ...) -> str`)
- `backend/prompts/modes.py`(`class Mode(Enum): ROLEPLAY / PROACTIVE`)
- `backend/prompts/templates/layer_a.j2`
- `backend/prompts/templates/layer_b.j2`
- `backend/prompts/templates/layer_c.j2`
- `backend/prompts/templates/layer_d.j2`
- `tests/test_persona_renderer.py`(31+ case 按 spec Phase 5)
- `tests/test_persona_schema.py`(migration 幂等 + seed 完整性)

**改动**(估 5 文件):
- `backend/main.py` 加 1 行 import + 1 行 `await migrate_v4_persona_chunk1_schema_and_seed()`,放在 bugfix-4 之后
- `backend/agents/chat.py::_build_messages`(1115–1310)替换 head_parts 拼装 → 调 renderer。**保留** profile / activity / memory / extra_system / stage2_addendum 5 个追加段(spec 没说要移走;Phase 4 验证)
- `backend/config/prompt_manager.py` 顶部加 `@deprecated since v4 segment 1` 注释,**不删除**(spec 说 v4.1 删)
- `backend/tools/builtin.py:20` `switch_character` 工具内部实现是否要查新 character_personas?**待 spec D-5 补完决定**
- `backend/routes/ws.py:837` `prompt_manager.get_current_character` 调用 —— 保持 API 表面不变,内部走 renderer cache(待定)

**不动**(spec 明确 ban + audit 推论):
- frontend/ 全部
- backend/llm/ backend/tts/ backend/asr/
- backend/observability/
- backend/proactive/ 主体(stage2_addendum 由 caller 算好,renderer 只接收)
- `backend/config/characters.yaml`(留作 first-run seed)
- 现有 `characters` 表 schema
- 任何 sanitize 模块(`backend/utils/text_filters.py`、`chat.py` 的 boundary state machine)—— **invariant**

→ **预估总改动 ≈ 12 文件**(spec 说 "~15 文件",误差合理)。

---

## Sign-off 所需

请回复:

1. **D-4 default_emotion 归属**:选 A(随 character_personas 迁)或 B(留 yaml)?
2. **D-5 spec 补齐**:贴齐 Phase 1 Schema spec、Phase 2 Layer C 完整 jinja、Phase 3 sanitize invariant 清单、Phase 5 31+ test case 清单。
3. **D-3 孤儿 state 行**:确认本 segment **不处理**,留单独 cleanup migration?
4. **D-1 _TOOL_PROMPT_ADDENDUM**:确认本 segment **只搬位置不重构内容**,彻底重构留 v4.1?
5. **风险确认**:Layer A1 模板"emotion=xxx 嵌入 SSML"按"系统自动注入,LLM 不直接输出 attr 风格"理解,**保留现有 `<emotion>X</emotion>` 标签形式不动**?如要切 attribute 形式,**必须先专门 sign-off**(破坏 sanitize invariant)。

收到 sign-off + 补完 spec → 进 Phase 1。
