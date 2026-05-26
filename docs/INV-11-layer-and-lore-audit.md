# INV-11 · Layer 架构 + Lore Schema Audit

> PM 任务 (2026-05-25 V2'' follow rate 62.5% 后) · 停手 H5 修复讨论 · 先 audit 真实情况。
>
> **方法**:verbatim grep / read 代码 + git log + DESIGN.md spec doc · **不推测设计意图**。
> 凡 code 注释 unclear / docs 无 rationale 记录 → 报告 "设计意图未知"。

---

## §1 Layer 架构 audit(spec vs reality)

### §1.1 文件清单(verbatim)

`backend/agents/prompt/templates/`(6 files · 没有 layer_e.j2):

| 文件 | size | 修改时间 |
|---|---|---|
| `layer_a.j2` | 9281 B | 2026-05-25 05:11(本次 INV-11 修改) |
| `layer_b.j2` | 1958 B | 2026-05-15 01:38 |
| `layer_c_runtime.j2` | 312 B | 2026-05-20 19:39 |
| `layer_c_stable.j2` | 4821 B | 2026-05-20 19:39 |
| `layer_d.j2` | 735 B | 2026-05-15 01:38 |
| `transition.j2` | 154 B | 2026-05-15 01:38 |

`backend/agents/prompt/*.py`:

| 文件 | 角色 |
|---|---|
| `__init__.py` | export |
| `briefing_sanitize.py` | proactive briefing schema validate + strip 指令性短语 |
| `meta_rules.py` | A2 meta_rules · render-only Python dataclass · 不进 prompt 字符串 |
| `mode.py` | B1 mode 决定:`determine_mode(turn_origin)` deterministic 走 roleplay/proactive |
| `persona_loader.py` | `load_active_persona` 加载 character_personas active row → `LoadedPersona` |
| `renderer.py` | 主入口 `render_system_prompt` · 调 5 个 `_render_layer_*` 函数 |
| `tool_addendum.py` | `_TOOL_PROMPT_ADDENDUM` 大段字符串(Layer B 内嵌)|

### §1.2 5 层架构(per DESIGN.md X.4 spec verbatim 引用)

| Layer | DESIGN.md spec 定义 | 真实 template / 渲染源 | 渲染顺序 |
|---|---|---|---|
| **A · Format Contract(格式契约)** | A1 tag_specs:注入 LLM 4 inline tag(thinking/state_update/motion/**emotion**)+ emotion 密度约束(平静对话不标 emotion)+ ja/en directive · A2 meta_rules:render-only Python dataclass 不进 prompt | `layer_a.j2`(9281 B 含 V2'' GSV mai_v4 段 + ja directive + Fish 子分支)+ `meta_rules.py`(Python · 不进 prompt) | 1st in `stable_parts` |
| **B · Mode Behavior(模式行为)** | B1 mode_directive(roleplay/proactive deterministic)· B2 universal_constraints(抗 OOC / 安全 / 关系 / 工具克制 / 长度自觉)+ `_TOOL_PROMPT_ADDENDUM` 原样搬迁 | `layer_b.j2`(1958 B · mode + universal_constraints · 内嵌 `{{ tool_prompt_addendum }}` jinja 变量) | 2nd in `stable_parts` |
| **C · Persona(核心)** | C1 身份卡 + self_intro 双梯级(intimacy ≥ 70 切深度版)· C2 性格 + 反差 + anger_style · C3 说话风格 + signature_phrases + filtered voice_samples + vendor-aware forbidden · C4 运行时(mood/intimacy/activity/safe_thought) | `layer_c_stable.j2`(C1/C1b/C2/C3 + **C3b taboo / C3c preferences / C3d emotion_triggers** Tier-2 segment 2 加)+ `layer_c_runtime.j2`(C4) | C_stable 3rd in `stable_parts` · C_runtime 1st in `variable_parts` |
| **D · Context(数据陈述)** | D1 user_profile · D2 today_activity · D3 long_memory_top5 · D4 tool_results · D5 temp_instructions · D6 proactive_briefing 强制 schema | `layer_d.j2`(735 B · 6 段 if-defined 渲染) | 2nd in `variable_parts` |
| **E · Dialogue** | 短期 N turn + 当前 user message | ❌ **没有 layer_e.j2 jinja template** · 实际由 `backend/agents/chat.py:1295-1305` 程序化 append messages list(`short_term_memory.get(...)` + `{"role":"user", "content":text}`)| 在 `messages: List[dict]` 而非 system prompt 内,跟前 4 层渲染脱离 |

### §1.3 渲染顺序(verbatim from `renderer.py:render_system_prompt`)

```python
# renderer.py:275-292
stable_parts: List[str] = [
    _render_layer_a(available_motions, tts_language, voice_provider, voice_model_name),  # Layer A
    _render_layer_b(mode, tool_prompt_addendum),                                          # Layer B
    _render_layer_c_stable(persona, states, llm_vendor, filtered_samples),                # Layer C stable
]
stable = "\n\n".join(p.strip() for p in stable_parts if p and p.strip())

variable_parts: List[str] = [
    _render_layer_c_runtime(states, safe_thought),  # Layer C runtime (C4)
    _render_layer_d(...),                            # Layer D
]
if just_switched_variant:
    variable_parts.append(_render_transition(persona.variant_name))  # transition (可选)
variable = "\n\n".join(p.strip() for p in variable_parts if p and p.strip())

return stable, variable
```

`stable + variable` 拼接顺序:**A → B → C_stable | C_runtime → D → transition?**

→ `chat.py:1267-1304` 把 (stable, variable) 拼成 messages[0] content blocks(若 variable 非空)/ 单 string(若 variable 空)· 后追加 `summary` system block + short_term turns(Layer E)+ current user input。

### §1.4 stable vs variable 分段(per cache_control 标记设计)

- **稳定前缀(进 prompt cache)**:Layer A + B + C_stable(C1/C1b/C2/C3/C3b/C3c/C3d)
- **变量段(per turn 变化)**:Layer C_runtime(C4)+ Layer D + (optional)transition
- **跨 cache 边界 risk**(per `docs/INVESTIGATION-5.md`):
  - intimacy 跨 70 阈值 → C1b self_intro 切深度版 → cache miss
  - llm_vendor 切换 → C3 forbidden_phrases vendor 分支 → cache miss
  - mode 切换 → B1 mode_directive 切 roleplay/proactive → cache miss

---

## §2 Lore Schema audit

### §2.1 `character_personas` DB schema(verbatim from `.schema`)

```sql
CREATE TABLE character_personas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    character_id INTEGER NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
    variant_name TEXT NOT NULL,
    is_builtin BOOLEAN DEFAULT 0,
    is_active BOOLEAN DEFAULT 0,
    display_order INTEGER DEFAULT 0,
    description TEXT,

    -- Tier 1 必填(JSON,SQLite TEXT 存,Python json.dumps/loads)
    identity TEXT NOT NULL,
    personality_core TEXT NOT NULL,
    speech_style TEXT NOT NULL,
    signature_phrases TEXT NOT NULL,
    voice_samples TEXT NOT NULL,
    forbidden_phrases TEXT NOT NULL,
    relationship_to_user TEXT NOT NULL,

    -- Tier 2 可选
    taboo_topics TEXT,
    lore TEXT,
    capability_overrides TEXT,
    style_preset TEXT DEFAULT 'anime_classic',
    ...
);
```

Per DESIGN.md X.3 Tier-2 字段 spec verbatim:

```
lore  世界观 — {preferences: {likes, dislikes, secretly_appreciates},
                emotion_triggers: {happy/shy/amused/annoyed_cold/soft/vulnerable
                  每类含 {ssml_tag, intensity, triggers, expression}}}
```

→ **spec 只定义"字段结构"**,**不说"为什么这样设计"**(rationale 缺失)。

### §2.2 cid=1 lore 完整 verbatim(已 dump · 摘要)

两个顶级 key:

**`lore.preferences`**(3 子段):
- `likes`(8 items)· `dislikes`(7 items)· `secretly_appreciates`(4 items)
- 每条可以是 string("雨天")或 dict({"item": "猫", "why": "不主动靠近的同类"})

**`lore.emotion_triggers`**(6 emotion key,每 key 含 4 sub-field):

| emotion_name | ssml_tag | intensity | triggers(中文 user input 描述) | expression(中文 character 行为) |
|---|---|---|---|---|
| `happy` | `happy` | `low-mid` | 用户记得她说过的小事 / 用户做完手头事主动来找她 / 听到聪明吐槽 | 嘴角几乎不动,眼睛停留更久,语气稍软。不笑出声 |
| `shy` | `shy` | `mid-high` | 被认真夸眼睛/声音/笑 / 突然牵手/触碰(70+) / 认真告白 | 移开视线一秒;'白痴'频率上升;整句变短或沉默 |
| `amused` | `calm` | `low` | 用户笨拙撒娇 / 用户出洋相装没事 / 听到冷笑话 | 嘴角微动,'真是的'频率高;不评论但不打断 |
| `annoyed_cold` | `calm` | `mid` | 被打断深度思考 / 敷衍的问题 / 用户连续不诚实 | 声音变平,'笨蛋'消失。冷却模式信号 |
| `soft` | `gentle` | `low` | 用户生病 / 用户深夜失眠说想她 / 用户回家说累死了 | 完整句变多,主动问'要不要 X',语气慢下来;不说煽情话 |
| `vulnerable` | `sad` | `low` | 重要纪念日 / 用户认真问"如果我消失了你会怎么办" / 用户长时间不出现后回来第一晚 | 未完成的省略号,'...嗯'然后停很久;不哭,但会消失一会儿 |

⭐ 观察:6 个 emotion_name(happy/shy/amused/annoyed_cold/soft/vulnerable)只映射到 **4 个不同 ssml_tag**(happy/shy/calm/gentle/sad)· `amused` 和 `annoyed_cold` 共用 ssml_tag=`calm` · 字段不是 1:1 映射。

### §2.3 emotion_triggers 设计意图 audit

#### §2.3.1 Git log 引入 commit

```
2bed353 feat(persona): v4 segment 2 — UI 持久化 + ja tag 链路 + renderer 字段升级
Date: 2026-05-15 05:40:35
```

Commit message **只说"字段升级"**(Phase 1 — Renderer 升级 5 字段:`layer_c.j2: taboo_topics.hard_no/soft_no with her_reaction、lore.emotion_triggers`)· **没有"为什么这样设计"的 rationale**。

#### §2.3.2 渲染产物 verbatim(`layer_c_stable.j2:115-126`)

```jinja
{# C3d 情绪触发参考(Tier-2 lore.emotion_triggers)#}
{% if persona.lore and persona.lore.emotion_triggers %}
[情绪触发参考]
不同情境下你的情绪倾向:
{% for emotion_name, config in persona.lore.emotion_triggers.items() %}
- {{ emotion_name }}{% if config.intensity is defined %}(强度 {{ config.intensity }}){% endif %}:
{% if config.triggers %}  触发:{{ config.triggers | join('、') }}
{% endif %}{% if config.expression %}  表现:{{ config.expression }}
{% endif %}{% if config.ssml_tag %}  TTS 标签:<emotion>{{ config.ssml_tag }}</emotion>
{% endif %}
{% endfor %}
{% endif %}
```

→ 给 LLM 看的渲染结果(cid=1 Mai persona):

```
[情绪触发参考]
不同情境下你的情绪倾向:
- happy(强度 low-mid):
  触发:用户记得她说过的小事、用户做完手头事主动来找她、听到聪明吐槽
  表现:嘴角几乎不动,眼睛停留更久,语气稍软。不笑出声
  TTS 标签:<emotion>happy</emotion>
- shy(强度 mid-high):
  触发:被认真夸眼睛/声音/笑(不是身材)、突然牵手/触碰(70+)、认真告白
  表现:移开视线一秒;'白痴'频率上升;整句变短或沉默
  TTS 标签:<emotion>shy</emotion>
- amused(强度 low):
  ...
  TTS 标签:<emotion>calm</emotion>
- annoyed_cold(强度 mid):
  ...
  TTS 标签:<emotion>calm</emotion>
- soft(强度 low):
  ...
  TTS 标签:<emotion>gentle</emotion>
- vulnerable(强度 low):
  ...
  TTS 标签:<emotion>sad</emotion>
```

⭐ **关键观察**:`TTS 标签:<emotion>{{ config.ssml_tag }}</emotion>` 形式 — **跟 Layer A1(V2'' GSV 段)的输出 tag spec 完全一致**!都是 `<emotion>X</emotion>`,LLM 看到两套 emotion 词表都用同款 tag 形式。

---

## §3 emotion_triggers 4 sub-field 真实用途分析

### §3.1 每 sub-field 字面 + 渲染层行为(verbatim · 不推测)

| sub-field | 字面含义 | layer_c_stable.j2:115-126 渲染层动作 | 代码消费 |
|---|---|---|---|
| `ssml_tag` | "TTS SSML 标签 hint" | 渲染成 `TTS 标签:<emotion>{{ config.ssml_tag }}</emotion>` 给 LLM | **未找到 backend 代码直接消费** · grep `ssml_tag` 整个 backend/ 无引用,只 layer_c_stable.j2 渲染 + docs spec 提及 |
| `intensity` | "情绪强度" | 渲染成 `- {emotion_name}(强度 {{ intensity }}):` 给 LLM | 同上 · 无代码消费 |
| `triggers` | "触发场景 list(user input 描述)" | 渲染成 `触发:{{ triggers \| join('、') }}` 给 LLM | 同上 · 无代码消费 |
| `expression` | "character 行为表达描述" | 渲染成 `表现:{{ expression }}` 给 LLM | 同上 · 无代码消费 |

→ **4 个 sub-field 都仅在 layer_c_stable.j2 渲染层用** · backend 代码无其它消费路径 · `intensity`/`triggers`/`expression` 完全是给 LLM 看的 character 行为指引 · `ssml_tag` **看起来像 TTS 字段但实际 TTS provider(cosyvoice/fish/gsv)都不消费此字段**。

### §3.2 ssml_tag 是历史 v3 SSML 遗留(verified)

**SSML 撤销历史**(per `backend/tts/cosyvoice.py:14-21` 注释 verbatim):

> chunk 1a (de7ebe2) 误把 emotion 包成 `<voice emotion="X">...</voice>` SSML,但 DashScope 官方 SSML 标签**没有 emotion 属性**(合法属性只有 voice / rate / pitch / volume / effect / bgm)— 已撤销 SSML 包装。

现行 cosyvoice instruct 路径(v3-G' patch)走 **DashScope SDK instruction 字段** + 自然语言指令 `"你说话的情感是{emotion}。"` · **不是 SSML**(per Stage 0 audit §4.4)。

→ **`ssml_tag` 字段在 cosyvoice/fish/gsv 三 provider 全 dead path**(无代码消费 · 仅 layer_c_stable.j2 渲染给 LLM 看)· 是 v3 SSML 设计时代遗留 · DESIGN.md X.3 spec 保留了字段定义但**未说明此字段在 SSML 撤销后是否仍有用途 / 是否应删除**。

### §3.3 维度混合 verdict

DESIGN.md / git log / code 注释**全 0 行说明 emotion_triggers 设计意图**。

只能从 layer_c_stable.j2 渲染层行为推断:
- `triggers` + `expression` = **character 行为指引**(教 LLM 什么 user input 应该触发什么 emotion 名词 + 用什么口吻 / 描述方式表达)
- `intensity` = **修饰** character 行为强度(给 LLM 看)
- `ssml_tag` = **TTS 词表 hint**(原本 SSML 设计时代真用 · 现 dead path · 但 layer_c_stable.j2:123 仍渲染成 `<emotion>X</emotion>` 给 LLM)

→ **混合 4 维度**:character 行为(triggers + expression + intensity)+ TTS 词表(ssml_tag · 现 dead path)· **设计意图原本可能是"一个 emotion key 既描述 character 行为又指示 TTS 输出"**,但 v3 SSML 撤销后 ssml_tag 维度失效,**字段未跟进清理**。

⚠ **设计原意未在 docs 明示** · 以上仅 code 行为推断 · PM 早上若想真知决策必须翻 Skyler 设计历史聊天记录 / 当事人确认。

---

## §4 跟 V2'' 关系(H5 怀疑 verify)

### §4.1 两套 emotion 词表平行存在(verified)

| 词表 source | 词表 verbatim | 渲染位置 | 标签形式 | 词数 |
|---|---|---|---|---|
| **V2'' GSV mai_v4(Layer A1)** | 日常/温柔/真挚/傲娇/害羞/调皮/安慰/严厉/伤感/慌乱/吃醋/感动/幸福/感谢/放松/叙事 | `layer_a.j2:27-77` GSV mai_v4 子段 | `<emotion>X</emotion>` 输出指令(强约束 "每条回复必须以...") | **16 中文** |
| **lore.emotion_triggers(Layer C3d)** | happy/shy/amused/annoyed_cold/soft/vulnerable(emotion_name)→ ssml_tag: happy/shy/calm/calm/gentle/sad | `layer_c_stable.j2:115-126` C3d 段 | `TTS 标签:<emotion>X</emotion>`(描述 character 行为 · 不是输出指令但 LLM 可能误读) | **6 英文(emotion_name)/ 4 不重复 ssml_tag** |

⭐ cid=1 gsv 实验完整 prompt 6330 chars **同时含两套** · 在 prompt 中:
- Layer A1 V2'' 段说:"每条回复必须以 `<emotion>X</emotion>` 开头, X 必须是 16 个情绪之一(日常/温柔/...)"
- Layer C3d 段说:"happy(强度 low-mid): 触发:... 表现:... TTS 标签:`<emotion>happy</emotion>`"

LLM 看到 2 套不同 emotion 词表都被表示成 `<emotion>X</emotion>` 形式 · **prompt 内置冲突源 H5 假设 verified**。

### §4.2 设计是否有意分化(verbatim grep)

- **DESIGN.md X.4 5 层 spec**: emotion **只在 Layer A1**(`A1 tag_specs 注入 LLM:4 inline tag · emotion 密度约束`)· **Layer C spec 没提 emotion**
- **DESIGN.md X.3 Tier-2 spec**: emotion_triggers 字段定义 4 sub-field 结构 · **没说"跟 Layer A1 emotion 是同维度还是异维度"**
- **commit 2bed353 message**: 只说"v4 segment 2 · 字段升级" · 没说设计意图
- **docs/INVESTIGATION-2.md L96**: 提到"emotion_triggers(per-emotion 多字段:**触发场景 + 表现 + TTS 标签**)" — **承认是三维度混合** · 但 audit doc · 不是设计 doc
- **其它 docs(mai_prompt.md / INVESTIGATION-5.md / archive/*)**: 仅 audit / spec / reference · **0 设计 rationale doc**

→ **设计是否有意分化:docs 无记录 · unknown**

### §4.3 历史揉一起 vs 有意分化 二者证据

**支持"历史揉一起"假说**(可能性较高):
1. v3 SSML 设计时代 `ssml_tag` 真起作用 · 当时 emotion_triggers 是"行为 + TTS 一体"设计
2. v3-G chunk 1a SSML 撤销后 ssml_tag 失去 TTS 维度 · **字段未跟进清理** · 留在 lore 里渲染给 LLM
3. V2'' Layer A1 加 16 中文 emotion paradigm 时,**没考虑 Layer C3d 也用 `<emotion>X</emotion>` tag** · 造成两套词表平行
4. commit 2bed353 把 emotion_triggers 升级渲染 layer_c.j2 时,渲染层措辞 "`TTS 标签:<emotion>X</emotion>`" 是字面直译 ssml_tag 字段名 · 未审 cosyvoice 撤销 SSML 后该字段真用途

**支持"有意分化"假说**(可能性较低):
1. layer_c_stable.j2:115 注释明示 "C3d 情绪触发参考(Tier-2 lore.emotion_triggers)" — "参考" 字眼暗示**给 LLM 作 character 行为参考** · 不是 TTS 词表
2. emotion_name 用 happy/shy/amused/annoyed_cold/soft/vulnerable(6 个 character 行为名词)而非 cosyvoice 4 词白名单 · 暗示是为 character 行为分类

→ **二者证据并存** · **无 docs / commit / code 注释 hard evidence** 能 lock 设计意图 · CC 推断"历史揉一起" 概率较高(80%)但**不 100% 确定** · 需 PM 真源确认。

### §4.4 H5 怀疑量化结论

V2'' follow rate 卡在 62.5% + 词表全"日常"/"放松"(2/16) · **可能根因**:

- LLM 看到 prompt 同时含两套 `<emotion>X</emotion>` 标签词表
- Layer A1 V2'' 16 中文严约束 "每条必须" · Layer C3d 6 英文 ssml_tag 描述 "TTS 标签" 弱约束 character 行为 grouping
- LLM 在某些 turn 可能 hedge:看到 Layer C3d 描述更详细(triggers + expression + intensity)→ 关联 character 行为 → 但 output 时**不知该走 Layer A1 16 中文 还是 Layer C3d 6 英文** → fallback 跳 tag

H5 假设 **prompt 验证成立**(2 套词表确实同 prompt) · 但 **LLM 真行为根因待 §2 动态 verify**(`[LLM_RAW_FIRST_CHUNK]` debug log 等 PM 跑 chat 后 grep)。

---

## §5 Audit 收口 + 不写代码 verdict

### §5.1 已 verify 的 facts

- ✅ **5 层架构实际只 4 层 jinja**(A/B/C/D · C 拆 stable + runtime · 没有 layer_e.j2)
- ✅ **Layer E 是程序化 messages list 追加**(chat.py 不是 jinja)
- ✅ **emotion_triggers 字段在 layer_c_stable.j2:115-126 C3d 段渲染**(verbatim grep)
- ✅ **`ssml_tag` 在 backend 代码无任何消费**(仅 layer_c_stable.j2 渲染)
- ✅ **DESIGN.md X.3 spec / commit 2bed353 message / code 注释 全部 0 行设计 rationale**
- ✅ **V2'' 16 中文 + lore.emotion_triggers 6 英文 同时进 LLM prompt**(per 6330 chars 完整 cid=1 gsv prompt render verify)

### §5.2 设计意图 verdict

- **emotion_triggers 4 sub-field 真实用途**: 从代码行为反推**3 个给 LLM 看的 character 行为指引 + 1 个(`ssml_tag`)v3 SSML 历史遗留 dead path**
- **DESIGN.md / commit / code 注释**: 无 1 行明示设计 rationale → **设计意图未知**(unknown · 不是 unclear · 是 0 docs 记录)
- **二者(Layer A1 emotion / Layer C3d emotion_triggers)是否有意分化**: 证据不足 lock · CC 推断"v3 SSML 时代揉一起 · 撤销 SSML 后 ssml_tag 字段未清理"概率 80% · 需 PM 真源确认

### §5.3 PM H5 修复方向参考(基于 verified facts · 不基于推测)

3 个 option 列给 PM 拍板,**CC 不预选**:

**Option H5-A · 字段维度分离**
- 把 `ssml_tag` 字段从 lore.emotion_triggers 移除 · 改造 layer_c_stable.j2:123 不渲染 "TTS 标签" 行 · 让 Layer C3d 纯 character 行为指引(emotion_name + triggers + expression + intensity)
- 不动 Layer A1 V2'' 16 中文 paradigm
- **Pros**: 消除 prompt 词表冲突 · Layer A1 / Layer C3d 维度分明
- **Cons**: lore JSON schema 改 · 现有 cid=1 / cid=101 Mai persona 字段裁剪 · 影响 builtin_seed 备份

**Option H5-B · 词表统一**
- emotion_triggers.ssml_tag 改用 V2'' 16 中文词表(日常/温柔/...)· 6 emotion_name 映射到 16 中文 subset
- layer_c_stable.j2:123 "TTS 标签:`<emotion>X</emotion>`" 行保留 · 但 X 是中文 · 跟 Layer A1 V2'' 一致
- **Pros**: prompt 不矛盾 · 两层 reinforcing
- **Cons**: 6 → 16 映射决策需 PM 定 · Mai canon 6 行为 names 跟 16 中文情绪不 1:1

**Option H5-C · 不动 lore · 改 Layer A1 V2''**
- Layer A1 V2'' GSV 段加 explicit 措辞: "下文 Layer C3d 的 `<emotion>X</emotion>` 是 character 行为描述参考 · 不是输出指令 · 你的输出必须用 Layer A1 16 中文词表"
- **Pros**: 0 lore schema 改 · 仅 prompt tune
- **Cons**: 增加 prompt 长度 · 依赖 LLM 理解 "Layer A1 vs C3d" 元指令(可能仍 hedge)

→ Audit 收口 · PM 早上看 + 拍板 H5 方向 · CC 待 PM 决定后实施。
