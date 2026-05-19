# DESIGN.md Patch 段(v4-beta 收口更新,2026-05-16)

> 把下面 patch 段按指示位置 paste 进现有 4779 行 DESIGN.md 历史档案。
> DESIGN.md 是机构记忆(历史档案):patch **不覆盖**既有历史段,只追加"后来又改了什么"——保留"当时怎么想"+"收口怎么改"双层记录。
> Patch 1-4 = Segment 1/2 + Bugfix 系列(2026-05-15);**Patch 5 = v4-beta 收口批次(2026-05-16);Patch 6 = footer 变更日志补全**。
>
> ⚠️ **章节编号说明(必读,防 paste 翻车)**:DESIGN.md 现存 §十五 系列已排到 **§十五之W**,且 **U/V/W 三个字母已被 v4-alpha 期内容占用**(§十五之U=UX-005 capability 单一归属 / §十五之V=UX-004 tool 过渡语 / §十五之W=UX-007 Momo 淡化)。本批次新章节因此**续编为 §十五之X / Y / Z**,排在老 §十五之W 之后、`## 十六` 开发进度之前 —— v4-beta 比 UX-005/004/007 新,时间序=字母序,零撞车,符合本文件"append 不覆盖"原则。**CC paste 时若 grep 到 §十五之U/V/W 那是 v4-alpha 老内容,不是本批次,不可据此误判"已 paste"。**

---

## 📌 Patch 1:顶部状态更新(line 7 那行整行替换)

**找到这一行:**
```
> **当前状态(2026-05-13)**:v4-alpha shipped。chunk 14 activity timeline、UX-004 v1 tool-call transition、UX-005 capability 单一归属、UX-007 Momo bubble fade,以及 hotfix-3 ~ hotfix-10 已上线。**65+ capabilities, 11 proactive triggers, 7 architectural abstractions, 950+ 测试**。剩 chunk 8b 完整屏幕感知 + chunk 12/13/15 + 长期路线见 [ROADMAP.md](ROADMAP.md) 四支柱组织。
```

**整行替换为:**
```
> **当前状态(2026-05-16)**:v4-beta 收口完成,进入 v4.0.0 ship 路径。v4-alpha(chunk 14 + UX-004/005/007 + hotfix-3 ~ 10)shipped 2026-05-13。v4-beta:Bugfix 1-4 系列 + Persona Engineering Segment 1/2 shipped 2026-05-14/15;**v4-beta 收口批次 shipped 并真机验证 2026-05-16(回退纯中文 / short_term (user,char,conv) 三级隔离 / conversation 锚定绑定语义规则 A/B / character_switch 不杀 in-flight turn / 对话 UI 统一 / token 成本治理 / 测试不污染主库)**。**65+ capabilities, 11 proactive triggers, 8 architectural abstractions(+ PersonaEngine + ConversationBinding), 1080+ 测试 + 收口回归 139 passed**。下一站:文档重写 → **长期记忆链路 audit(critical,默认用户 memory 表 0 行)** → TTS cap/throttle → Stage 3 v4.0.0 MVP 封装。长期路线见 [ROADMAP.md](ROADMAP.md)。
```

---

## 📌 Patch 2:新加大章节 §十五之X Persona Engineering

**位置**:插在整个 §十五 系列**最末尾**——即老 `## 十五之W`(UX-007 Momo 淡化)章节之后、`## 十六`(开发进度)之前。
**定位法(稳,不依赖老 W 内容)**:`grep -n "^## 十六" DESIGN.md` 找到 §十六 标题行 N,在第 N 行**之前**插入下面整段(整个 §十五之X 块,行尾留一个空行再接原 `## 十六`)。
**勿**插在 §十五之T 之后(那会插进老 UX-005 内容中间,产生重复编号 + 交叉引用歧义)。

**整段插入:**

```markdown
---

## 十五之X、Persona Engineering 系统(v4-beta)

Skyler 的角色"立体度"通过多 variant + Tier-1 typed 字段 + 5 层 prompt 框架实现。本章是 v4-beta 引入的核心新系统。

### X.1 多 variant 架构

`character_personas` 表 1:N 关联到 `characters`,通过 `(character_id, is_active=1)` 唯一索引保证每个角色同时只有 1 个激活 persona。`character_personas_builtin_seed` 表持有系统预设的完整字段备份,[恢复默认] 通过它实现。

切换 variant:`POST /api/personas/{id}/activate` → 写 session flag `just_switched_variant=true` → 下次 prompt 渲染时检测 flag → 注入 transition prompt 告知 LLM 风格已变(不打断 character_states / memory / chat_history)。

**关键不变量**:
- 运行时状态(`character_states.mood / intimacy / activity / current_thought`)跟 character 走,不跟 variant 走 — 切换 persona 不清空关系/记忆
- 每个 character 至少有 1 个 active variant — `ensure_defaults` migration 防御性兜底,补缺失角色的 default
- builtin variant 可以编辑,但 `is_builtin=1` 标记保留;[恢复默认] 从 `character_personas_builtin_seed` 读 + 覆盖

### X.2 Tier-1 字段 schema(必填,7 个 JSON 字段)

```
identity              身份卡 — name / aliases / self_reference / age / occupation / origin
                      + self_intro 双梯级(0-69 公开版 / 70-100 深度版,按 intimacy 切)
personality_core      性格 — core_traits(3-5 词)/ contrasts(反差点,1-3 条)
                      + energy_level / default_emotion / anger_style
speech_style          说话风格 — vocabulary / sentence_rhythm / user_address
                      + emoji_habit / punctuation_quirk / cliche_tolerance(0-1)
signature_phrases     口头禅 — 1-3 个,真人说话频率
voice_samples         真实样本 — [{scene, text, tolerance_range: [min, max]}, ...]
                      每条标糖度区间,运行时按 cliche_tolerance 过滤
forbidden_phrases     禁止句式 — {_global, _qwen, _deepseek, _character} 子段
                      vendor-aware:不同 LLM 各自的 AI 腔
relationship_to_user  关系建模 — type / intimacy_progression / initial_intimacy
                      + intimacy_rules(0-30 / 30-50 / 50-70 / 70-85 / 85-100 阶梯规则)
```

### X.3 Tier-2 字段(可选,JSON 灵活槽)

```
taboo_topics       禁区与反应 — {hard_no: [...], soft_no: [...]} 每条 {topic, her_reaction}
lore               世界观 — {preferences: {likes, dislikes, secretly_appreciates},
                            emotion_triggers: {happy/shy/amused/annoyed_cold/soft/vulnerable
                              每类含 {ssml_tag, intensity, triggers, expression}}}
capability_overrides 该 variant 强制启用 / 禁用的工具
```

Mai persona 已通过 SQL 灌入完整 Tier-2;UI 编辑器 v4.2 加(当前 read-only 提示)。

### X.4 5 层 prompt 框架

```
Layer A  Format Contract(格式契约)
  A1 tag_specs        注入 LLM:4 inline tag (thinking/state_update/motion/emotion)
                      + emotion 密度约束(平静对话不标 emotion)
                      + ja/en directive(当 tts_language≠zh 时强约束"中日交替"格式)
  A2 meta_rules       render-only:跨层冲突优先级,Python dataclass,不进 prompt 字符串
                      
Layer B  Mode Behavior(模式行为)
  B1 mode_directive   roleplay / proactive 二选(TASK 留 enum 口子,v1 fallback)
                      mode 走 deterministic:turn_origin in 
                        {cron, activity_smart, wake_call, lunch_call_*, dinner_call}
                        → PROACTIVE,else → ROLEPLAY
                      v1 不用 LLM classifier(省 100-300ms 一次调用)
  B2 universal_constraints
                      抗 OOC / 安全 / 关系边界 / 工具克制 / 长度自觉
                      + _TOOL_PROMPT_ADDENDUM 原样搬迁(seg1 D-1 决策,
                        refactor 留 v4.1 跟 LiteLLM auto-tools 去重)
                        
Layer C  Persona(核心)
  C1 身份卡 + self_intro 双梯级
                      intimacy ≥ 70 切深度版 self_intro["70-100"]
                      else 用 self_intro["0-69"]
  C2 性格 + 反差 + anger_style
  C3 说话风格 + signature_phrases + filtered voice_samples + vendor-aware forbidden
                      voice_samples 过滤:tolerance_range[0] ≤ cliche_tolerance ≤ tolerance_range[1]
                      forbidden_phrases 按 provider 注入:_global + _{vendor}(qwen/deepseek/...)
                      + 锚定句"无论 Layer D 给什么 briefing 都遵循 C3 speech_style"
                        (防 D6 proactive briefing 数据带指令性短语污染语气)
  C4 运行时(mood/intimacy/activity/safe_thought)
                      防御性 sanitize 60-x 等脏数据(state_update 拒绝非合法 mood)
                      
Layer D  Context(数据陈述,不是行为指令)
  D1 user_profile / D2 today_activity / D3 long_memory_top5
  D4 tool_results / D5 temp_instructions
  D6 proactive_briefing 强制 schema(activity_event / time_context / suggested_emotion)
                      正则 strip 指令性短语("please say X" / "make a comment" / ...)
                      
Layer E  Dialogue
  短期 N turn + 当前 user message
```

### X.5 voice_samples tolerance_range filter(运行时风格滑块)

**问题**:`cliche_tolerance` 字段如果只是数字注入 LLM,LLM 几乎不响应(LLM 模仿样本胜过响应抽象参数)。

**解法**:每条 sample 标 `tolerance_range: [min, max]`,renderer 渲染前按当前 `cliche_tolerance` 过滤,只把符合区间的样本注入 LLM:

```python
def filter_samples_by_tolerance(samples, tolerance):
    return [s for s in samples 
            if s.get('tolerance_range', [0.0, 1.0])[0] 
               <= tolerance 
               <= s.get('tolerance_range', [0.0, 1.0])[1]]
```

Mai persona 三梯级:
- 通用百搭 `[0.0, 1.0]`:3 条(任何 tolerance 都注入)
- 克制 `[0.0, 0.4]`:4 条(真实/克制场景)
- 中庸 `[0.3, 0.7]`:3 条(常规对话)
- 放大 `[0.6, 1.0]`:2 条(撒娇/反差时刻)

UI 滑块拖动 0.35 → 0.8 立即生效,LLM 看到的样本集合切换,角色说话风格随之改变。**无需重写人格文本**。

### X.6 跨语种 TTS pipeline(ja / en tag)

**问题**:Mai 角色的 voice 是日语 sample 复刻的,直接用日语 voice 合成中文 → CosyVoice 音色错乱("日式中文")。

**解法**:per-character `voice_model.tts_language` 字段(zh/ja/en),控制 LLM 输出 + TTS 路由:

```
voice_model.tts_language = 'zh'(default,99% 角色)
  → LLM 中文输出 → TTS 直接合成
  
voice_model.tts_language = 'ja'
  → Layer A1 注入 ja directive:
    强约束"中日交替"格式:每个中文句后立刻跟 <ja>翻译</ja>
    (不能 [中文全段]+[<ja>日语全段</ja>] 集中模式,
     否则 sentence-level 流式 TTS 看不到跨句 ja tag,
     会 fallback 中文给日语 voice 念,音色错乱)
  → Sanitize 链识别 <ja> paired tag(加入 _BOUNDARY_PAIRED_TAGS)
  → extract_tts_text(text, 'ja') 提取 ja 段送 TTS
  → strip_ja_en_tags_for_subtitle 删 ja 留中文给字幕
  
voice_model.tts_language = 'en'
  → 同 ja 逻辑,<en>...</en> tag
```

Bugfix-Segment2-2(2026-05-15)通过强化 Layer A1 ja directive(加 ✗ 错误示范 + 解释 why)修了"LLM 偏好集中模式"的痛点。后端 sanitize 链 0 改动。

### X.7 Sanitize 链 invariant

5 层框架不影响 LLM 输出格式契约。Sanitize 状态机 0 改动,boundary paired tags 集合扩展:

```python
_BOUNDARY_PAIRED_TAGS = {
    'thinking', 'emotion', 'state_update', 'motion',
    'tool_call', 'function_calls', 'invoke',
    'ja', 'en',   # v4-segment2 新增,跨语种 TTS pipeline
}
```

state_update 信号源单向化:**数值进 character_states,persona 文本禁止描述当前 mood**。解决 v3 时代"自由文本 mood 描述跟 state_update 数值打架"问题(v3 phrase manager 已 deprecate,新 renderer 不读 yaml mood 文本)。

### X.8 Mai 借 Momo 壳(dogfood 第一个完整 persona)

设计选择:Mai(樱岛麻衣)persona 内核 + Momo(id=1)壳 + Hiyori Live2D 资产:

```
characters.id = 1                  ← 角色物理身份
  name = 'Momo'                    ← UI 显示
  live2d_model = 'hiyori'          ← Live2D 模型(Mai 无 2D 资产,借 Hiyori)
  voice_model.voice = 'cosyvoice-v3.5-plus-bailian-a19f528011c1446eafd4c4990301270f'
                                   ← 复刻 voice(日语 sample)
  voice_model.tts_language = 'ja'  ← 中文字幕 + 日语朗读

character_personas.character_id = 1
  variant_name = 'default'
  is_active = 1
  is_builtin = 1
  identity.name = '樱岛麻衣'         ← LLM 内核身份
  identity.aliases = ['麻衣', '麻衣学姐', 'Mai']
  + 完整 Tier-1 + Tier-2 字段全填(12 voice_samples / 6 emotion_triggers / 
    5 hard_no + 4 soft_no taboo / 8 likes + 7 dislikes + 4 secretly_appreciates)
  cliche_tolerance = 0.35
```

LLM 自称樱岛麻衣,用户在 UI 看到 Momo,聊起来发现"她叫麻衣"— 借壳关系透明。

**Token cost**:
- Segment 1 baseline(Momo 空 persona):6636 chars
- Segment 2 Mai 满 Tier-1+Tier-2(zh):9018 chars(+36%)
- Segment 2 Mai + ja directive(ja 模式):9383 chars(+41%)
- 预算 ≤+50% safe;空字段 character(其他角色)仅 +2.5%(Jinja `{% if %}` 守卫不渲染空段)

### X.9 Persona REST API

```
GET    /api/characters/{character_id}/personas       — list all variants for character
GET    /api/characters/{character_id}/personas/active — get active variant
GET    /api/personas/{persona_id}                    — single variant full JSON
POST   /api/characters/{character_id}/personas       — create new variant (is_builtin=0)
PATCH  /api/personas/{persona_id}                    — update partial fields
DELETE /api/personas/{persona_id}                    — delete (active variant 不能删,需先激活其他)
POST   /api/personas/{persona_id}/activate           — switch active variant
POST   /api/personas/{persona_id}/restore_to_builtin — restore from builtin_seed
```

是否 active variant 不能删:防误删后角色无 persona 可用。
builtin variant 可以删:用户完全控制权(`ensure_defaults` migration 会自动补默认)。

### X.10 PersonaEditorModal(UI)

frontend/src/components/PersonaEditorModal.tsx,Tier-1 MVP(Segment 2 ship):

```
基本(variant_name / description / style_preset)
身份卡(identity 含 self_intro 双梯级文本框)
性格(personality_core 含 contrasts 多行 + anger_style)
说话风格(speech_style 全 6 子字段 + cliche_tolerance 滑块带实时风格预览)
口头禅(signature_phrases tag input,1-3 个)
真实样本(voice_samples 列表,每条 scene/text + tolerance_range 双滑块)
禁止句式(forbidden_phrases 4 子段 tag input)
关系(relationship_to_user 嵌套)

底部蓝色提示(若 persona 含 Tier-2 字段):
  "本 persona 含 Tier-2 字段(taboo_topics / lore / capability_overrides),
   保存时保留不动。完整编辑请等 v4.2"
```

Tier-2 字段 UI 编辑器 v4.2+ 加(留账 v4.1 backlog #1)。

详见 [ROADMAP §v4.1 — Persona 收尾 + Tech Debt](ROADMAP.md#v41--persona-收尾--tech-debt)。
```

---

## 📌 Patch 3:新加章节 §十五之Y Observability

**位置**:紧接 Patch 2 刚插入的 `## 十五之X`(Persona Engineering)章节末尾、`## 十六` 之前。`grep -n "^## 十五之X\|^## 十六" DESIGN.md`,在 §十五之X 块结束、§十六 之前插入下面整段。

**整段插入:**

```markdown
---

## 十五之Y、Observability(v4-beta Bugfix-4)

让用户和开发者都能看到系统在做什么,出问题时第一时间定位。

### Y.1 tts_call_log 埋点

每次 TTS 合成调用记一行:

```sql
CREATE TABLE tts_call_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    source        TEXT,         -- chat / proactive / activity_smart / preview
    character_id  INTEGER,
    voice         TEXT,         -- cosyvoice-v3.5-plus-bailian-...
    model         TEXT,         -- cosyvoice-v3.5-plus / cosyvoice-v3.5-flash / edge-tts
    input_chars   INTEGER,      -- 实际送 TTS 的字符数(strip 后)
    input_preview TEXT,         -- 200 字预览(用于 anomaly 诊断)
    cost_estimate FLOAT,        -- 估算成本(用户透明)
    success       BOOLEAN,
    error_message TEXT
);
```

`source` 通过 ContextVar 在 chat/proactive/activity 各路径预设,TTSBase 接口零破坏。

### Y.2 Anomaly detection

`input_chars > 500` 红色标记 — 用于诊断:
- LLM 失控输出超长段落
- state_update / thinking tag 没 strip 干净泄漏到 TTS
- ja tag 解析失败导致整段中日文混合送 TTS

### Y.3 REST API

```
GET /api/observability/tts/usage                 — today/month 聚合
GET /api/observability/tts/recent_calls?limit=50 — 最近调用 + input_preview
GET /api/observability/system/resources          — psutil RAM/CPU/Whisper/network
```

### Y.4 UI 入口

- ⚙ TTS tab 底部 — today/month 用量 + [查看最近] 按钮打开 recent_calls modal
- ⚙ 设置 / 系统状态 section — RAM / CPU / Whisper model size / 网络吞吐量,3s 自动刷新

### Y.5 v4.1 计划

- TTS daily char cap per-user enforcement(ship 前必加)
- main chat per-minute throttle
- UI token 用量 daily display(用户透明)
- 推送延迟 metric(audio_consumer send_json 前后 perf_counter)
```

---

## 📌 Patch 4:v4-beta 衍生 Tech Debt 段

**位置**:`## 十四之B、已知技术债`(`grep -n "^## 十四之B" DESIGN.md`)。追加在该章节**内容末尾**——即 §十四之B 标题后的最后一行、下一个 `^## ` 出现之前,**不要紧贴标题插入**(会插到既有技术债条目前面打乱顺序)。若该章节内有 `### 遗留测试债` 子段,追加在其后。

**整段追加:**

```markdown
### v4-beta 衍生 Tech Debt(2026-05-15)

| # | 项 | Touchpoint | 优先级 |
|---|---|---|---|
| v4.1-1 | TTS daily char cap per-user enforcement | `backend/tts/__init__.py` 加 daily counter,超额降级 Edge | 高(ship 必加)|
| v4.1-2 | main chat per-minute throttle | `backend/routes/ws.py` per-conversation 60/min 软 cap | 高 |
| v4.1-3 | PersonaEditorModal Tier-2 UI | `frontend/src/components/PersonaEditorModal.tsx` 加 collapsible advanced sections | 中 |
| v4.1-4 | _TOOL_PROMPT_ADDENDUM 重构 | seg1 D-1 留账,审 LiteLLM auto-tools 去重 + Layer B2 抽 3 条策略 | 低 |
| v4.1-5 | character_states 12 孤儿 cleanup + FK | seg1 D-3 留账,加 ON DELETE CASCADE migration | 低 |
| v4.1-6 | proactive ja 路径 e2e 测试 | seg2 留账,2 个 e2e case(cron + activity_smart 触发 Mai 时)| 中 |
| v4.1-7 | persona automated style check | forbidden_phrase_detector / style_consistency_scorer / persona_distinguishability_test | 中 |
| v4.1-8 | id=101 樱岛麻衣冗余 row cleanup | seg2 ensure_defaults 副产 | 低 |
| v4.2-1 | Tier-2 字段完整 UI 编辑器 | taboo_topics / lore / capability_overrides JSON form | 中 |
| v4.2-2 | cosyvoice-v3.5-plus instruct 解锁 | 等 DashScope 上游放开 | 等上游 |
| v4.2-3 | CosyVoice 日语合成声学质量验证 | dogfood 反馈驱动 | 等反馈 |
```

---

## 📌 Patch 5:新加章节 §十五之Z v4-beta 收口批次(2026-05-16)

**位置**:紧接 Patch 3 刚插入的 `## 十五之Y`(Observability)章节末尾、`## 十六` 之前。`grep -n "^## 十五之Y\|^## 十六" DESIGN.md`,在 §十五之Y 块结束、§十六 之前插入下面整段。至此 §十五 系列顺序应为:…T → U/V/W(v4-alpha 老内容)→ X → Y → Z → `## 十六`。

**整段插入:**

```markdown
---

## 十五之Z、v4-beta 收口批次(2026-05-16)

多 session 反复出现的 ja 错乱 / 话痨 / 串台 / 绑定竞态 / "删了还记得" / "切走回复被吃" / UI 混乱,本批次一次性收口并真机验证全绿。本章记录每项的根因与修法;DESIGN.md 是历史档案,本章是对 §十五之X(Persona Engineering)/ §十五之Y(Observability)当时设计的**收口修订记录**(不覆盖原章,双层保留)。

### Z.1 回退纯中文(对 X.6 跨语种 TTS pipeline 的收口修订)

**问题**:X.6 的 ja 中日交替链(Layer A1 强 directive + 禁集中模式 + Bugfix-Segment2-2 强化)折腾多版,稳定性仍不达标——根因是"LLM 实时自己交替标 `<ja>`"这个不确定性无法靠 prompt 根除,弱网/长输出/工具轮次叠加时反复退化为音色错乱或话痨。

**决策(v4.0.0)**:Mai **回退纯中文**。`characters.id=1` `voice_model.tts_language` 由 `'ja'` 改 `'zh'`,voice 改中文音色 `longyumi_v3`。**persona 完全不动**(只换语音链路,不动人格)。X.6 描述的 ja 链代码**保留但休眠**(sanitize boundary set 仍含 ja/en,见 X.7,不破坏既有契约)。

**v4.1 F0 方向**:不再给 ja 交替打补丁;改**后处理翻译架构**——LLM 出纯中文 → TTS 前 qwen-turbo 翻日 → CosyVoice。把"LLM 实时交替标 ja"彻底移出链路,一次做对。X.6 旧链描述作 F0 重做的参考保留。

### Z.2 short_term (user, character, conversation) 三级隔离

**根因**(audit 实锤):short_term buffer 此前按 (user, character) 分桶但**不按 conversation**。conv A 旧历史 + conv B 当前轮被合并喂 LLM → 出现"连说两遍""删了对话重启还记得旧上下文"(排除 long-term 残留:default 用户 memory 表 0 行;排除没切 conv:新对话确是新 id)。

**修法**:short_term entry 加 `conversation_id`;add/get/count/clear 加 `conversation_id` 参数;`get(conv_id=X)` 严格匹配;5 处调用透传(ws / chat `_build_messages` / proactive engine / main restore)。**桶仍按 (user, char) 不破 path-7**;进程重启从 chat_history **按 conversation 过滤**恢复。

**不变量**:删对话 = 硬删 chat_history + conversations,**不动** memory / profile / 进程内 short_term;short_term 永不跨 conversation/character 串。

### Z.3 conversation 锚定绑定语义(新架构抽象 ConversationBinding)

**根因**:响应此前跟"UI 当前选中角色"走,用户切走时回复跟着飘;且 ws endpoint loop 对任何新 frame 都 cancel 旧 turn(只放过 interrupt),`character_switch` 帧也触发 cancel → LLM 没 yield 就 reply_len=0 真·0 产出被吃。

**模型**:切角色 = 切到该角色**最新 conversation**(无则新建);conversation 1:1 绑角色,角色身份**由 conversation 推导**。

- **规则 A(用户发起)**:对话发起即锁定 conversation(`chat_id` snapshot);响应无条件投递回原对话,中途切走也不丢。
- **规则 B(系统主动)**:proactive 触发时快照 conversation;投递前 late-gate 校验(读 `get_current`);过时静默丢弃,不冒错角色。
- **character_switch 调度豁免**:ws endpoint loop 在 interrupt 后/cancel 前加 `elif character_switch` 分支 → set_current + ack + continue,**让 in-flight turn 跑完**。
- **前端守卫**:chunks 附 conv_id snapshot;`useWebSocket` stale-conv 守卫(`msg.conversation_id !== currentConversationId` → drop);emotion/motion/state_update 不附 conv_id(角色级跨 conv 适用)。

"慢"与"串"由此**解耦**:LLM 慢退化为纯性能问题(v4.1 独立优化),不再表现为串台。

### Z.4 对话 UI 统一

分裂的对话/历史入口收敛:删右上角独立"历史"入口 + 删旧浮现台词气泡 + 删 ChatHistoryDrawer;对话内容统一由**左侧推拉 chat panel** 承载;左 conversation list + 右 chat panel 双推拉;切角色自动加载该角色最新对话内容(方案 A,无则空状态);两侧全收起 = 纯立绘 Galgame 沉浸;窗口 <1280px 自动降级。

### Z.5 长期记忆链路 audit 发现(⚠️ 提为 v4.0.0 critical)

收口审计实锤:**默认用户 `memory` 表 0 行**(9 行全测试 uid)。意味着 §十五之X/§memory schema 描述的 server-side MemoryExtractor 提炼链路**可能根本没在写**。现象:聊超 30 turn(short_term cap)后角色失忆——既不在近期窗口,又没提炼进 long-term。这砸陪伴核心定位。

**修正既往判断**:此前"v4.0.0 单角色全共享=正确,F8 留 v4.1"的前提是"long-term 在工作",已被推翻。→ "有没有"(链路是否生效)必须 **v4.0.0 audit**(只读排查 → 据结论修);"分级"(F8 归属:fact/profile→user_shared,event/关系→character_private)才 v4.1。

### Z.6 token 成本治理

- **修法 A**:short_term 硬性 cap 最近 30 turn(trim 旧 turn)。
- **修法 B**:tool_result 注入截断到 4000 字符。

多 round 工具调用不再把单次输入推到几万 token。与 Z.2 三级隔离同 commit 系列。

### Z.7 测试不污染主库

26+ 测试改 in-memory DB;清掉此前测试写进主库 momoos.db 的污染数据(测试 uid 行)。收口回归 **139 passed / 1 pre-existing 无关 fail**(test_long_term,v4.1 清单)。

### Z.8 对 X.8 Mai 借壳的收口修订

X.8 记录的 `characters.id=1` 配置在本批次更新:`voice_model.tts_language` `'ja'` → `'zh'`;`voice` 复刻日语 voice → 中文音色 `longyumi_v3`。**identity / Tier-1 / Tier-2 全部不动**(借壳关系、樱岛麻衣内核、12 voice_samples 等均保留)。其余角色仍是空骨架,v4.1 F1 仿 `docs/mai_prompt.md` 逐个灌真 persona。

### Z.9 关键 commit 留账

| 项 | commit |
|---|---|
| 回退纯中文 | `0e079a4` |
| 清污染 + short_term per-(user,char) | `9e434e3` `b5b0a47` |
| conversation 锚定绑定语义(规则 A/B) | `0c9c082` `cfa006c` `9039d75` |
| short_term per-conversation 过滤 | `eeb427a` |
| character_switch 不杀 in-flight turn | `5766493` |
| 对话 UI 统一 | UI 统一批次 |

DB 备份系列(回退兜底):`momoos.db.backup_{zh_revert,purge,bindfix,2bugfix,chatpanel}_*`。
```

---

## 📌 Patch 6:DESIGN.md footer 变更日志补全

**背景**:Patch 1 只更新了顶部状态行;DESIGN.md 末尾还有独立的 `文档版本：v3-WIP | 最后更新：2026-05-04` + 变更日志块,5 个 Patch 都没动它 → 顶部已 2026-05-16、footer 还停 2026-05-04,档案不自洽。补这条保持历史档案完整。

**位置**:DESIGN.md 文件末尾的 `文档版本：… | 最后更新：…` 行 + 其下变更日志块(`grep -n "最后更新" DESIGN.md`,通常在文件最后 20 行内)。

**操作**:
1. 版本行更新:`最后更新：2026-05-04` → `最后更新：2026-05-16`;`文档版本：v3-WIP` → `文档版本：v4-beta 收口`。
2. 变更日志块**追加**一条(不覆盖既有 entry):
```
- 2026-05-16 v4-beta 收口:回退纯中文(Mai cid=1 ja→zh)/ short_term (user,char,conv) 三级隔离 / conversation 锚定绑定语义(规则 A/B)/ character_switch 不杀 in-flight turn / 对话 UI 统一 / token 成本治理 / 测试不污染主库。long-term memory 链路 audit 发现 default 用户 0 行,提为 v4.0.0 critical。详 §十五之X/Y/Z + §十四之B v4-beta 衍生 Tech Debt。
```

---

## ✅ Patch 应用完成 checklist

完成 **6 处编辑**后,DESIGN.md:
- (Patch 1)顶部状态反映 v4-beta 收口(2026-05-16)+ 1080+ 测试 + 收口回归 139 passed
- (Patch 2)新增 §十五之X Persona Engineering(~250 行)— 在老 §十五之W 之后、§十六 之前
- (Patch 3)新增 §十五之Y Observability(~50 行)— 紧接 §十五之X 后
- (Patch 4)§十四之B 末尾追加 v4-beta 衍生 Tech Debt 表
- (Patch 5)新增 §十五之Z v4-beta 收口批次(~120 行)— 紧接 §十五之Y 后
- (Patch 6)footer 版本行 + 变更日志补 v4-beta entry

总长度从 4779 行 → ~5200 行。

📌 **请 paste 后跑验证(全部需通过)**:
```bash
# 1. 新章节各恰好 1 行
grep -nc "^## 十五之X" DESIGN.md   # 应 = 1
grep -nc "^## 十五之Y" DESIGN.md   # 应 = 1
grep -nc "^## 十五之Z" DESIGN.md   # 应 = 1
# 2. 老 v4-alpha 章节未被破坏(仍各 1 行,内容仍是 UX-005/004/007)
grep -n "^## 十五之U\|^## 十五之V\|^## 十五之W" DESIGN.md
#    → 应仍指向 UX-005 / UX-004 / UX-007 老内容,未被新内容覆盖
# 3. §十五 系列顺序正确:…T → U → V → W → X → Y → Z → 十六
grep -n "^## 十五之\|^## 十六" DESIGN.md
#    → X/Y/Z 必须全部在 W 之后、十六 之前,顺序 X→Y→Z
# 4. 其它锚点
grep -n "v4.1-1" DESIGN.md          # 应在 §十四之B 末尾
grep -nc "2026-05-16" DESIGN.md     # ≥3(顶部状态 + §十五之Z 标题 + footer)
grep -n "最后更新：2026-05-16" DESIGN.md  # footer 已更新
```
**任一不过 → 停,回报,不要硬修。** 最危险信号:grep §十五之X 得 0 行(说明 Patch 2 被误跳过,Persona Engineering 没进档案)。
