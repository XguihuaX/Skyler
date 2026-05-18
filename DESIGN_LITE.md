# Skyler 技术设计速览(DESIGN_LITE)v4.0.0 记忆线收口(2026-05-17)

> 本文档是给 Claude 对话使用的**精简版**技术设计。每次开启新会话时,把本文档粘进上下文即可。
> 完整 5200+ 行 DESIGN.md 是历史档案(含每个 chunk / hotfix 的根因分析、testing 覆盖、实施细节),保留作机构记忆。
>
> **当前状态(2026-05-17)**:v4-beta 收口完成 + v4.0.0 记忆线收口(audit 完结 + 修复链 ship,代码核验,待真机回归),进入剩余 v4.0.0 ship 路径。
> - v4-alpha shipped 2026-05-13(chunk 14 + UX-004/005/007 + hotfix-3 ~ 10)
> - **Bugfix 1-4 系列** shipped 2026-05-13/14(sanitize 加固 / Settings 拆分 / AI Providers 重构 / observability + 小窗修复)
> - **Persona Engineering Segment 1/2** shipped 2026-05-15(5 层 prompt 框架 + multi-variant + ja tag pipeline)
> - **v4-beta 收口批次** shipped 并真机验证 2026-05-16(回退纯中文 / short_term 三级隔离 / conversation 锚定绑定语义 / character_switch 不杀 in-flight turn / 对话 UI 统一 / token 成本治理)
> - 下一站:文档纠真 ✅ → 长期记忆链路 audit ✅(修复链 ship,代码核验,待真机回归)→ TTS cap/throttle → Stage 3 v4.0.0 MVP 封装

> ⚠️ **接管必读(3 个 red flag,新 Claude 先看这个)**:
> 1. **Mai 已回退纯中文** —— ja 中日交替强约束(§6.5 旧描述)**已放弃**,ja 链代码保留休眠;`cid=1` `tts_language=zh` + voice `longyumi_v3`,人格不动。日语原声 = v4.1 F0 后处理翻译重做。**不要再给 ja 交替打补丁。**
> 2. **长期记忆链路 audit 完结、修复链已 ship** —— 根因=抽取 prompt 偏 fact-only + 闲聊→合法 [];子 bug=purge 不重置指针。修复链(滚动摘要层 + 指针自愈/reconcile + prompt 重平衡 + 墓碑)已 ship 且代码核验;**陪伴质量待真机回归(验收门)**。§4 声明已更新;详 DESIGN §五·补 + §十五之 Z.5.1。
> 3. **conversation 锚定绑定语义已上线(§5.9)** —— 切角色/串台/回复被吃全靠这套规则 A/B。改对话/角色/proactive 投递相关代码前必读 §5.9,别破坏绑定。

---

## §1 项目定位

**可改造的 AI 角色容器**(hackable AI companion framework)— 桌面端、角色驱动、能拆到 agent 内核、所有权归用户。

不是 VTuber 应用(看 Open-LLM-VTuber);不是无状态 agent 平台(看 Hermes)。在二者中间。

**目标用户**:hacker — 会写 Python,在意数据所有权,想要属于自己的 AI 角色,愿意改框架。

---

## §2 为什么是这些架构选择

### 2.1 为什么 Capability Registry(`@register_capability`)

定位"扩展是核心" → 扩展机制必须低摩擦。
- ❌ 写死 tool 列表 + if/else:每加一个 skill 改一处
- ❌ Plugin manifest + 加载器(LangChain 风格):学习成本高
- ❌ 完全靠 MCP server:启动慢、跨进程 overhead

→ **`@register_capability` 装饰器 + JSON schema** 是唯一契约。一个 Python 函数装饰一行就是 LLM 可调的 tool。`Consumer` enum(CHAT_AGENT / SCHEDULER / WEBHOOK)允许多 subsystem 复用同一 capability。

### 2.2 为什么双向 MCP(client + server)

定位"所有权归你 + 生态参与"。

- 只做 client:能消费,不能贡献,变孤岛
- 只做 server:能贡献,不能消费,重新发明轮子

→ **双向**:Skyler 既消费外部 server(filesystem/brave-search/Notion),又把 capability 暴露给 Claude Desktop/Cursor。

### 2.3 为什么 persona 级 `character_states`

定位"角色化 + 长期使用"。

- ❌ 状态全靠 prompt 注入,每轮 reset → 角色没"自己"
- ❌ 写死状态机(`if mood == happy: ...`)→ 僵硬

→ **DB 表持久化 + LLM 驱动**:`character_states` 跟踪 mood / intimacy / current_thought / current_activity;LLM 通过 `<state_update>` 标签更新;每日 intimacy_decay cron 模拟"不联系就疏远"。

这是长期 vision *persona-level learning* 的基础设施。

### 2.4 为什么活动时间线(chunk 14)是顶层 first-class

定位"陪伴感"。陪伴的关键不是回应快,是**记住**。

不只记 chat_history,还记 activity_sessions(用户今天**在做什么**)。Momo 能说"看你 VS Code 待了 3 小时,跟昨天那个项目吧?",是因为活动时间线是跟 chat_history 平行的**第二条 timeline**。

5 道隐私闸(黑名单/dedup/idle 过滤/显式删除/全本地)— 角色知道用户今天做了什么,但数据不离开本机。

### 2.5 为什么主动陪伴 = trigger pack + activity 双路径

定位"角色化主动性"但有边界 — 不该每个 poll 都说话(那叫 spam)。

- **Trigger pack**(时间驱动):wake_call / lunch_call / dinner_call / bedtime_chat / long_idle / morning_briefing — 时间窗 + cooldown + daily cap
- **Activity-based**(上下文驱动):ide_open / music_playing / long_focus / late_night_ide — 快路径分类 + LLM 慢路径判官 + idle 闸(人离开电脑闭嘴)

共用 throttle / cooldown / 静默时段闸,daily cap 跨 source 全局有效。

### 2.6 为什么 5 层 prompt 框架(v4-beta)

v3 时代 persona 9 段自由拼装 → 字段语义混乱、跨字段冲突、prompt 失控。

→ **5 层分离**:格式契约(A)/ 模式行为(B)/ persona(C)/ 上下文(D)/ 对话(E)。每层职责单一,跨层冲突 meta_rules 仲裁。

→ **typed JSON schema**:Tier-1 7 字段必填(identity / personality_core / speech_style / signature_phrases / voice_samples / forbidden_phrases / relationship_to_user),Tier-2 灵活槽(taboo / lore / capability_overrides)。

详见 §6 Persona Engineering。

### 2.7 为什么 conversation 锚定绑定语义(v4-beta 收口)

多 session 反复出现"切到八重却自报麻衣""删了对话重启还记得旧上下文""切走后回复被吃 / 冒到错的角色"。根因有三层,定位"陪伴 = 一个角色一段连续关系",绑定必须确定性,不能靠时序运气。

- ❌ short_term 只按 user 切片 → 跨角色/跨对话串台
- ❌ 响应跟"当前 UI 选中角色"走 → 用户切走时回复跟着飘
- ❌ endpoint loop 对任何新 frame(含 character_switch)都 cancel 旧 turn → 切角色直接吃掉进行中回复(reply_len=0)

→ **三级隔离 + conversation 锚定 + turn 调度豁免**(详 §5.9):short_term 按 (user, character, conversation) 分桶;对话发起即锁定 conversation(规则 A);proactive 投递前校验(规则 B);character_switch 不进 turn cancel 路径。"慢"与"串"由此解耦 —— LLM 慢退化为纯性能问题(v4.1),不再表现为串台。

---

## §3 核心架构图(数据流)

```
用户输入(语音 / 文本)
  ├─ VAD 模式  Web Audio API speech detect → MediaRecorder
  ├─ 手动      点击起停
  └─ 文本      直接送

  → ASR        faster-whisper(本地)→ asr_result 推送前端
  → ChatAgent  PromptRenderer + LiteLLM tool calling
                ├─ short_term:(user, character, conversation) 三级隔离,cap 30 turn
                ├─ memory 工具:save / delete / list / compress
                ├─ 内置工具:ToolRegistry(MCP 可扩)
                ├─ capabilities:@register_capability auto-injects
                └─ web search:模型原生(Qwen Max / DeepSeek)
  → emotion    第一句解析 <emotion>X</emotion> → 锁定本轮 emotion
  → state      <state_update mood=+2 .../> → character_states 数值更新
  → motion     <motion>Flick</motion> → Live2D 动作
  → TTS        get_tts_engine(voice_model) → CosyVoice / Edge
                + v4-beta Mai = 纯中文链路(tts_language=zh,voice longyumi_v3)
                + ja 链 extract_tts_text(text,'ja') 代码保留休眠(v4.1 F0 重做)
                + tts_call_log: 每次记一行
  → 输出       流式文字 chunks + per-sentence 音频 chunks + 字幕
                按发起 conversation 投递(规则 A/B,§5.9);
                character_switch 不进 turn cancel 路径(进行中回复跑完)

PromptRenderer(5 层框架):
  Layer A  Format Contract
    A1 tag_specs(thinking/state_update/motion/emotion + emotion 密度 + ja/en directive)
    A2 meta_rules(render-only,Python dataclass,不进 prompt)
  Layer B  Mode Behavior
    B1 mode_directive(roleplay / proactive,deterministic by turn_origin)
    B2 universal_constraints(抗 OOC / 安全 / 工具克制 / 长度自觉)
       + _TOOL_PROMPT_ADDENDUM(refactor 留 v4.1)
  Layer C  Persona(核心)
    C1 身份卡 + self_intro 双梯级(intimacy ≥ 70 切深度版)
    C2 性格 + 反差 + anger_style
    C3 speech_style + signature_phrases + filtered voice_samples + vendor-aware forbidden
       + 锚定句"无论 Layer D 给什么 briefing 都遵循 C3"
    C4 运行时(mood/intimacy/activity,thought 防御性 sanitize)
  Layer D  Context(数据,不是指令)
    D1 user_profile / D2 today_activity / D3 long_memory_top5
    D4 tool_results / D5 temp_instructions
    D6 proactive_briefing(schema-validated,指令性短语正则删)
  Layer E  Dialogue(短期 N turn + 当前 message)

  + 切换 variant 时注入 transition prompt
```

---

## §4 核心数据 schema

### characters(角色物理身份)
```
id, name, persona(@deprecated, fallback only), 
live2d_model, voice_model(JSON: provider/voice/model/tts_language),
created_at, updated_at
```

### character_personas(v4-beta 多变体 persona)
```
id, character_id (FK), variant_name, description, style_preset,
is_active(UNIQUE INDEX where is_active=1), is_builtin,
identity, personality_core, speech_style, signature_phrases,
voice_samples, forbidden_phrases, relationship_to_user,  ← Tier-1 7 字段(JSON)
taboo_topics, lore, capability_overrides,                ← Tier-2 槽
created_at, updated_at
```

### character_personas_builtin_seed(v4-beta 备份)
```
character_id, variant_name, [所有 Tier-1+Tier-2 JSON 字段]
→ 给 [恢复默认] 用
```

### character_states(运行时状态)
```
character_id, mood, intimacy, current_thought, current_activity, available,
updated_at
跟 character 走,不跟 variant 走
```

### memory(长期记忆,v3.5 chunk 10)
```
id, user_id, character_id, content, entry_type(fact/preference/event/commitment),
confidence, extraction_source(auto/explicit/manual/legacy),
embedding_vector(blob), access_count, last_accessed,
检索:score = relevance * (1+log(1+access_count)) / (1+age*decay)
```
> ✅ **v4.0.0 更新(取代上方"0 行 / 待 audit"声明)**:audit 完结,根因=抽取 prompt 偏 fact-only + 闲聊→LLM 合法返回 [];子 bug=purge 不重置 extractor 指针。修复链(有界滚动摘要层 + 指针自愈/源头 reconcile + 抽取 prompt 重平衡 + 墓碑)已 ship 且对真 diff 代码核验。功能/陪伴质量待真机回归 + friend-test(验收门)。详 DESIGN §五·补 + §十五之 Z.5.1。

### chat_history
```
id, conversation_id, character_id, role, content,
kind('normal'/'touch'/'proactive'), proactive_trigger, created_at
```
> **v4-beta**:chat_history 是对话存档 + restore 源,**不是记忆本身**。运行时短期记忆 = 进程内 short_term buffer,按 **(user, character, conversation)** 三级隔离,cap 最近 30 turn(token 治理);进程重启从此表**按 conversation 过滤**恢复(`get(conv_id=X)` 严格匹配,不跨对话/跨角色串)。删对话 = 硬删 chat_history + conversations,不动 memory/profile/进程内 short_term。

### conversation_summary(v4.0.0 b91505a 有界滚动摘要层)
```
id, user_id, character_id, conversation_id,
summary_text, last_folded_chat_history_id, token_budget, updated_at
UNIQUE(user_id, character_id, conversation_id)
```
> 给每个 (user, character, conversation) 三元组维护一份滚动摘要,worker(`backend/memory/summary.py`)按 `last_folded_chat_history_id` 增量折叠超出 short_term cap 的旧 turn 进 `summary_text`;ChatAgent 注入 prompt 时取最新一行。补 short_term 硬性 cap 30 turn 之外的"中期记忆"层。

### activity_sessions(v3.5 chunk 14)
```
id, user_id, app_name, url, title, start_time, end_time,
duration_seconds, idle_duration, source
30 天保留,5 道隐私闸
```

### tts_call_log(v4-beta Bugfix-4 observability)
```
id, timestamp, source(chat/proactive/activity_smart/preview),
character_id, voice, model, input_chars, input_preview(200 字),
cost_estimate, success, error_message
```

### voice_aliases(v4-beta Bugfix-3.4)
```
voice_id(PK), display_name
给 cloned voice 起友好名,UI 显示用
```

### mcp_credentials / mcp_client_state / mcp_tool_state(MCP 配置 + 启用态)
```
mcp_credentials  : id, server_name, key_name, value, updated_at  (UNIQUE server+key)
mcp_client_state : server_name(PK), enabled, updated_at
mcp_tool_state   : id, server_name, tool_name, enabled, updated_at  (UNIQUE server+tool)
```
> 三表分管 MCP server 的凭证 / client 启停态 / 单 tool 启停粒度。`mcp_client.py` 启动按 `mcp_client_state.enabled=1` 拉起 server,按 `mcp_tool_state.enabled` 决定 tool 是否注册进 ToolRegistry;UI 的 MCP 面板 CRUD 走 `routes/mcp.py`。

### users.profile_data(v3.5 chunk 11)
```
profession / current_projects / interests / recurring_topics /
communication_style / active_hours / language_preferences
profile_summary @deprecated 但保留 fallback
```

---

## §5 关键架构抽象

### 5.1 Capability Registry
```python
@register_capability(name, description, consumers, parameters)
async def my_skill(...): ...
```
- 装饰器 + JSON schema 是唯一契约
- Consumer enum:CHAT_AGENT / SCHEDULER / WEBHOOK
- 自动派生 OpenAI tool schema → ToolRegistry → ChatAgent

### 5.2 双向 MCP
- **作 client**:连外部 MCP server(filesystem/brave-search/Notion 等)反向注册成 `ext.<server>.<tool>` capability
- **作 server**:把 CapabilityRegistry 暴露给 Claude Desktop / Cursor / Cline,Bearer 认证
- 三层统一:内置 capability + 外部 reverse-registered + Skyler-as-server 暴露 → 同一 CapabilityRegistry

### 5.3 Persona Engine(v4-beta,核心)
见 §6

### 5.4 Proactive Engine
- 5 trigger pack:wake_call / lunch_call / dinner_call / bedtime_chat / long_idle / morning_briefing
- Activity-based 4 trigger:ide_open / music_playing / long_focus / late_night_ide
- Slow path:qwen-turbo judge(stay 5+ min,模糊场景)
- 4 道闸:min_stay + judge_throttle + fire_throttle + daily_cap
- 模式 A 单向 vs 模式 B 邀请对话

### 5.5 Activity Timeline
- ActivityWatcher 30s poll
- get_active_app(osascript,zero pyobjc NSRunLoop 坑)+ get_browser_url(frontmost gate)
- get_idle_seconds(ioreg HIDIdleTime)
- ChatAgent system-prompt 注入 today_activity
- 5 道隐私闸(blocklist / dedup / idle 过滤 / 显式删除 / 全本地)

### 5.6 Sanitize Chain
**Invariant**:LLM 输出可能含 `<thinking>`/`<state_update>`/`<motion>`/`<emotion>`/`<tool_call>`/`<function_calls>`/`<invoke>`/`<ja>`/`<en>` tag,sanitize 状态机识别 + 提取数据 + strip 给 TTS。

4 道防线:
1. ws.py 主路径 `_apply_and_push_state_update`
2. proactive engine 各 stream loop `_apply_proactive_state_update`
3. 最后兜底 `strip_all_for_tts(每个 text_chunk push 前)`
4. 持久化前 `_strip_format_tags` 5 档完整(thinking/emotion/motion/state_update/tool_call)

paired tag boundary set:
```python
_BOUNDARY_PAIRED_TAGS = {
    'thinking', 'emotion', 'state_update', 'motion',
    'tool_call', 'function_calls', 'invoke',
    'ja', 'en',  # v4-segment2 新增
}
```

### 5.7 LiteLLM AI Providers(v4-beta Bugfix-3 重构)
- vendor 分组架构:OpenAI / Anthropic / DeepSeek / Qwen / 自定义
- Fernet 加密凭证(`~/.skyler/.crypto_key` chmod 0600)
- LiteLLM prefix repair(qwen3.6-max → qwen/qwen3.6-max)
- Tool name auto-sanitize(`.` → `_` for DeepSeek 等 strict-schema providers,LLM 看原始名 via 反向 mapping)
- `provider_kind`:builtin(系统预设)/ custom(用户加)

### 5.8 Observability(v4-beta Bugfix-4)
- tts_call_log + 4 source bucket(chat/proactive/activity_smart/preview)
- input_chars > 500 anomaly 红色高亮
- psutil 抓 RAM/CPU/Whisper/network,3s 刷新
- 见 §7

### 5.9 conversation 锚定绑定语义(v4-beta 收口,接管必读)

**模型**:切角色 = 切到该角色**最新 conversation**(无则新建);一个 conversation 1:1 绑一个角色,角色身份**由 conversation 推导**(不是由"UI 当前选中")。

- **规则 A(用户发起)**:对话发起那一刻锁定 conversation(`chat_id` snapshot),响应全程贯穿该 conversation;**即使中途切走,回复无条件投递回原对话**(不丢)。
- **规则 B(系统主动)**:proactive 触发时快照 conversation;投递前 late-gate 校验是否仍是当前对话;过时(已切走)**静默丢弃**,不冒到错角色。
- **character_switch 不进 turn 调度**:ws endpoint loop 对一般新 frame 会 cancel 旧 turn(防并发),但 `character_switch` 帧走 `elif` 分支 set_current+ack+continue,**让 in-flight turn 跑完**(否则 reply_len=0 真·0 产出被吃)。
- **short_term 三级隔离**:per-(user, character, conversation),`get(conv_id=X)` 严格匹配;桶仍按 (user,char) 不破 path-7;5 处调用透传 conv_id(ws / chat / proactive / main restore)。
- **前端守卫**:chunks 附 conv_id snapshot;`useWebSocket` stale-conv 守卫(`msg.conversation_id !== currentConversationId` → drop);emotion/motion/state_update **不**附 conv_id(角色级跨 conv 适用)。

关键路径:`backend/memory/short_term.py`(三级过滤+cap30 trim,勿退)/ `backend/routes/ws.py`(:1320 character_switch 分支 + 绑定快照)/ `backend/proactive/engine.py` + `activity_smart.py`(规则 B late-gate 读 get_current)/ `backend/main.py`(restore character+conv filter)/ `backend/agents/chat.py`(_build_messages 透传 conv_id)。

### 5.10 对话 UI 统一(v4-beta 收口)

分裂的对话/历史入口收敛成一套:

- 右上角独立"历史"入口 **删除**;旧浮现台词气泡 **删除**(有 bug + 与 chat panel 重叠);ChatHistoryDrawer **删除**。
- 对话内容统一由**左侧推拉 chat panel** 承载(当前 conversation 完整记录)。
- 左 conversation list + 右 chat panel **双推拉**;切角色自动加载该角色最新对话内容(方案 A,无对话则空状态引导);两侧全收起 = 纯立绘 Galgame 沉浸;窗口 <1280px 自动降级布局。

---

## §6 Persona Engineering(v4-beta 核心新系统)

### 6.1 多 variant 架构
- `character_personas` 1:N → `characters`
- `(character_id, is_active=1)` UNIQUE INDEX 保证每角色只 1 active variant
- 切换:POST /api/personas/{id}/activate → session flag `just_switched_variant=true` → 下次注入 transition prompt
- **运行时状态(character_states)跟 character 走,不跟 variant 走** — 切 persona 不丢关系/记忆
- `ensure_defaults` migration 防御性补缺失角色的 default

### 6.2 Tier-1 字段(必填 7 个 JSON 字段)
```
identity              身份卡 + self_intro 双梯级(0-69 / 70-100 按 intimacy 切)
personality_core      性格 — core_traits + contrasts(反差) + anger_style
speech_style          说话风格 + cliche_tolerance(0-1)
signature_phrases     1-3 个口头禅
voice_samples         [{scene, text, tolerance_range:[min,max]}, ...]
forbidden_phrases     {_global, _qwen, _deepseek, _character} vendor-aware
relationship_to_user  type / intimacy_progression / intimacy_rules 阶梯
```

### 6.3 Tier-2 槽(可选)
```
taboo_topics    {hard_no: [{topic, her_reaction}], soft_no: [...]}
lore            {preferences, emotion_triggers(6 类各含 ssml_tag/intensity/triggers/expression)}
capability_overrides  per-variant 工具启停
```

### 6.4 voice_samples tolerance_range filter(运行时风格滑块)
```python
def filter_samples_by_tolerance(samples, tolerance):
    return [s for s in samples 
            if s.get('tolerance_range', [0.0, 1.0])[0] 
               <= tolerance 
               <= s.get('tolerance_range', [0.0, 1.0])[1]]
```
UI 滑块拖动立即生效。**`cliche_tolerance` 数值本身 LLM 不响应**(LLM 模仿样本胜过响应抽象参数),靠 filter 实际改变 LLM 看到的样本集合。

### 6.5 跨语种 TTS pipeline(ja / en tag)—— ⚠️ v4-beta 已休眠

> **v4-beta 收口决策**:ja 中日交替链折腾多版(strong directive / 集中模式禁止 / Segment2-2 修复)稳定性仍不达标(LLM 实时自己交替标 ja 的不确定性无法根除)。v4.0.0 决定 **Mai 回退纯中文**(`cid=1` `tts_language=zh` + voice `longyumi_v3`,人格完全不动)。下面的 ja 链描述对应代码**保留但休眠**(sanitize boundary set 仍含 ja/en,见 §5.6)。
> **v4.1 F0 = 后处理翻译架构重做**:LLM 出纯中文 → TTS 前 qwen-turbo 翻日 → CosyVoice。把"LLM 实时交替标 ja"彻底移出链路。**不要再给 ja 交替打补丁。**

旧 ja 链(休眠,F0 复用参考):
- `voice_model.tts_language='ja'` 时 Layer A1 注入 ja directive,强约束"中日交替"格式
- LLM 输出:`"中文句。"<ja>「日本語句。」</ja>"中文句 2。"<ja>...</ja>`
- 禁止集中模式 `[中文全段] + [<ja>日语全段</ja>]`(sentence-level TTS 看不到跨句 tag,会 fallback 中文给日语 voice 念,音色错乱)
- `extract_tts_text(text, 'ja')` 提取 ja 段送 TTS
- `strip_ja_en_tags_for_subtitle` 删 ja 留中文给字幕
- Bugfix-Segment2-2(2026-05-15)修了"LLM 偏好集中模式"问题

### 6.6 Mai 借 Momo 壳(dogfood 第一个完整 persona)
```
characters.id=1  name='Momo'  live2d_model='hiyori'
  voice='longyumi_v3'        ← v4-beta 回退纯中文(原 ja voice 已换)
  tts_language='zh'          ← v4-beta(原 'ja' 已改;勿动)

character_personas (character_id=1, variant='default'):
  identity.name='樱岛麻衣'  aliases=['麻衣', '麻衣学姐', 'Mai']
  完整 Tier-1 + Tier-2 字段(人格不动,只换语音链路)
  12 voice_samples 含 tolerance_range 三梯级
  cliche_tolerance=0.35
```

**Token cost**:Mai 满字段 (zh) ~9018 chars vs Segment 1 baseline 6636 chars(+36%,预算 ≤+50% 内)。

> **v4-beta known limitation**:`cid=1`=Mai 是**唯一**完整 persona。其他角色(`cid` 2/3/4/5/99/100,八重等)是**空骨架**(只名字 + Live2D 绑定),切过去人格空洞。v4.1 F1 仿本 spec(`docs/mai_prompt.md`)逐个灌真 persona。v4.0.0/v4-beta 主推 Mai 单角色。

### 6.7 Mode 走 deterministic(v1)
```python
PROACTIVE_ORIGINS = {'cron', 'activity_smart', 'wake_call', 
                     'lunch_call_*', 'dinner_call'}
mode = PROACTIVE if turn_origin in PROACTIVE_ORIGINS else ROLEPLAY
```
TASK 留 enum 口子,v1 fallback to roleplay。不用 LLM classifier(省 100-300ms)。

### 6.8 关键决策留账
- **D-1**(seg1):_TOOL_PROMPT_ADDENDUM 70 行原样搬迁到 Layer B,refactor 留 v4.1
- **D-3**(seg1):12 行 character_states 孤儿不动,v4.1 cleanup + FK
- **D-4**(seg1):default_emotion 进 personality_core 子段,yaml 字段 @deprecated
- **A1**(seg1):emotion paired-tag form,系统自动注入 SSML/instruct
- **D-S2-1**(seg2):删 CharacterDetailModal 旧 persona 显示
- **D-S2-2**(seg2):加 ensure_defaults 防御性 backfill migration
- **D-S2-3**(seg2):ja tag 按 voice_id 匹配(覆盖 id=1 + id=101 同 voice)
- **D-S2-4**(seg2):UI 仅 MVP Tier-1,Tier-2 留 v4.2

### 6.9 Persona REST API
```
GET    /api/characters/{id}/personas       — list
GET    /api/characters/{id}/personas/active — active
GET    /api/personas/{id}                  — full
POST   /api/characters/{id}/personas       — create
PATCH  /api/personas/{id}                  — update
DELETE /api/personas/{id}                  — delete(active 不能删)
POST   /api/personas/{id}/activate
POST   /api/personas/{id}/restore_to_builtin
```

---

## §7 Observability(v4-beta Bugfix-4)

### 7.1 tts_call_log 埋点
每次 TTS 合成记一行,字段见 §4。source 通过 ContextVar 在 chat/proactive/activity 各路径预设,TTSBase 接口零破坏。

### 7.2 Anomaly detection
`input_chars > 500` 红色标记 — 诊断 state-tag 漏 strip / ja tag 解析失败 / LLM 失控。

### 7.3 REST API
```
GET /api/observability/tts/usage                — today/month 聚合
GET /api/observability/tts/recent_calls?limit=N — 最近调用 + preview
GET /api/observability/system/resources         — psutil RAM/CPU/Whisper/network
```

### 7.4 UI 入口
- ⚙ TTS tab 底部 today/month + [查看最近] modal
- ⚙ 设置 / 系统状态 section(3s 自动刷新)

### 7.5 v4.1 加固
- TTS daily char cap per-user enforcement(ship 前必加,防 100+ 用户烧爆)
- main chat per-minute throttle
- UI token 用量 daily display
- 推送延迟 metric(audio_consumer perf_counter)

---

## §8 当前 Tech Debt 优先级速览

### 🔴 v4.0.0 critical(ship 前必处理,按序)
1. ✅ **文档纠真**(本批次完成;DESIGN.md 大整合立项留待表层重构 pass)
2. ✅ **长期记忆链路 audit + 修复链** —— audit 完结(根因=fact-only prompt + 闲聊→合法 [];子 bug=purge 不重置指针),修复链已 ship 且代码核验;**陪伴质量待真机回归(验收门)**。详 §4 更新 + DESIGN §十五之 Z.5.1
3. TTS daily char cap per-user enforcement(防 dogfood 烧爆)
4. main chat per-minute throttle

### 中(v4.1)
5. F0 ja 后处理翻译重做(LLM出中文→qwen-turbo翻日→cosyvoice;含 proactive ja 路径 e2e)
6. F1 七套角色真 persona(仿 docs/mai_prompt.md)
7. F8 长期记忆归属分级(依赖 #2 audit 结论)
8. **记忆架构 v2(陪伴洞察)** —— 一角色一永久对话流 + 近期 short_term 原文 + 远期 RAG,"重来"靠显式清空非新对话;与 F8 统一设计
9. PersonaEditorModal Tier-2 UI(v4.2)
10. persona automated style check 上线
11. 7 个 **import-死符号断测** cleanup(test_chat_agent / test_database / test_llm_client / test_memory_agent / test_ws_helpers / test_memory / test_integration,v2.5-B/v3-C 时代 import 已删符号,与功能无关)。**注:`test_long_term` 不在这 7 个内 —— 它曾是 Z.5(0 行)的 repro;v4.0.0 修复链已 ship,其当前状态以真机回归为准(见 §十五之 Z.5.1)。**
12. **记忆表层历史债(§5.8 → 表层重构 pass,立项)** —— 异构表 facts+提醒未拆 / 双 type 列 cruft / supersede 无机制 / `expires_at` 未接线 / 墓碑 check 无类型感知。结构债,不在 v4.0.0 ship 范围;详 DESIGN §十四之B RT-1~5 + §十五之 Z.5.1。

### 低
12. _TOOL_PROMPT_ADDENDUM 重构
13. character_states 12 孤儿 cleanup + FK
14. id=101 樱岛麻衣冗余 row cleanup
15. characters.yaml vs DB:当前 Plan B(DB 主源 + YAML fallback);Plan C(删 yaml DB 单源)deferred
16. config.yaml 双写源拆分
17. MCP 凭证升级 OS keyring
18. LLM 慢(qwen3.6-plus + 网络;绑定锁死后纯性能问题,独立优化不混功能修复)
19. CosyVoice WS 建链 5s 超时(SDK 写死,弱网失败)

完整 backlog 见 [ROADMAP.md](ROADMAP.md)。

---

## §9 v4.0.0 ship 计划

| Sub-stage | Goal | ETA |
|---|---|---|
| Stage 0 | **文档纠真**(DESIGN / DESIGN_LITE / ROADMAP / README ×2 对齐 v4.0.0 + §5.8 入册)→ 落地 repo | ✅ 完成 |
| Stage 1 | **长期记忆链路 audit + 修复链** —— audit 完结 + 修复链 ship(代码核验)| ✅ ship,待真机回归 |
| Stage 2 | TTS daily char cap per-user + main chat throttle(防烧) | 0.5d |
| Stage 3a | Tauri build 验证 | 0.5-1d |
| Stage 3b | .dmg + tauri-updater + onboarding | 2-3d |
| Stage 3c | 5+ scenario 真机走查 | 1d |
| Stage 3d | Dogfood 1 周 | 7d |
| Stage 3e | 反馈迭代 + tag v4.0.0 | 0.5-1d |

总:~1.5 week(Stage 0/1 已完成;余下 Stage 2/3)。

dogfood 反馈驱动 v4.1 优先级 — 高频痛点优先于 nice-to-have。

---

## §10 关键路径速查

```
项目根:/Users/liujunhong/Desktop/MomoOS-v2
DB:    /Users/liujunhong/Desktop/MomoOS-v2/momoos.db
凭证 key: ~/.skyler/.crypto_key (chmod 0600)

Persona 核心:
  backend/agents/prompt/                       — renderer + templates + persona_loader
  backend/agents/prompt/templates/layer_*.j2   — A/B/C/D Jinja2 模板
  backend/database/migrations/v4_persona_*.py
  backend/routes/persona_api.py                — 8 endpoint
  backend/utils/text_filters.py                — sanitize 链 + ja/en extract
  frontend/src/components/PersonaEditorModal.tsx
  frontend/src/lib/personas.ts                 — API client

Bugfix 4 observability:
  backend/observability/system.py              — psutil
  backend/routes/observability_api.py
  backend/database/migrations/bugfix_4_observability.py

AI Providers:
  backend/integrations/ai_providers.py
  backend/routes/ai_providers_api.py

v4-beta 收口核心(绑定/记忆,改前必读 §5.9):
  backend/memory/short_term.py            — per-(user,char,conv) 过滤 + cap30 trim(勿退)
  backend/routes/ws.py                    — :1320 character_switch 分支 + 绑定快照(:582 NameError 已修)
  backend/proactive/engine.py
  backend/proactive/activity_smart.py     — 规则 B late-gate 读 get_current
  backend/main.py                         — :387/402 restore character+conv filter
  backend/agents/chat.py                  — :1244/1438 _build_messages 透传 conv_id
  characters cid=1                        — voice=longyumi_v3, tts_language=zh(勿动)
  memory 表                               — ✅ v4.0.0 audit 完结+修复链 ship(待真机回归;见 §十五之 Z.5.1)
  docs/mai_prompt.md                      — Mai 完整 Tier-1+2 spec(F1 七套参考)
  DB 备份系列 momoos.db.backup_*          — 回退兜底(zh_revert/purge/bindfix/2bugfix/chatpanel)

Tests:
  tests/test_persona_segment1.py  — 97 case
  tests/test_persona_segment2.py  — 100 case(91 + 9 hotfix)
  tests/test_sanitize.py          — 128 regression

历史档案:
  DESIGN.md  4779 行 — git 在线查每个 chunk/hotfix 的详细决策
```

---

## §11 与完整 DESIGN.md 的指针

本 LITE 涵盖 v4-beta 当前架构的关键点。完整版 DESIGN.md(4779 行)含:

- §三~§十四:v1-v3 完整数据 schema 演进、API 设计、前端组件历史
- §十五之A~W:各架构抽象的详细设计(Capability Registry / 双向 MCP / character_states / proactive / activity timeline / sanitize chain)的完整 motivate + alternatives 否决理由 + 实施细节。**其中 A~T = v1–v3α 架构;U/V/W = v4-alpha 期 UX-005/004/007(注意不是 Persona Engineering)。**
- **§十五之X/Y/Z = v4-beta**:X=Persona Engineering / Y=Observability / Z=v4-beta 收口批次 —— 经 DESIGN_patch.md 的 Patch 2/3/5 paste 进 DESIGN.md(找 Persona Engineering 去 §十五之X,不是 A~T)。
- §十六~§二十:测试策略 / 性能 / 平台兼容 / 隐私模型
- 每个 chunk 的 audit 决策记录 / 实测覆盖 / 风险评估

调架构 / 改 schema / 大 refactor 前应回查完整版。日常 Claude 对话用本 LITE 即可。

---

**文档版本**:LITE 1.1(2026-05-16,v4-beta 收口批次更新)— 基于 DESIGN.md 4779 行原版整合
**完整版**:DESIGN.md 4779 行(历史档案;v4-beta 收口增量见 DESIGN_patch.md)
