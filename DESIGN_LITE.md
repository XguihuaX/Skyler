# Skyler 技术设计速览(DESIGN_LITE)v4.0.0 收口 + 进入动画 ship(2026-06-08)

> **当前设计真源**:2026-05-19 docs 第二刀起,本文件(DESIGN_LITE.md)为 Skyler 当前设计的单一真源。
> 完整 5,206 行 DESIGN.md 已归档至 `docs/archive/DESIGN.md` 作为历史机构记忆档案(含每个 chunk / hotfix 的根因分析、testing 覆盖、实施细节);DESIGN.md 不再维护,仅作追溯参考。
>
> 本文档是给 Claude 对话使用的**精简版**技术设计。每次开启新会话时,把本文档粘进上下文即可。
>
> **当前状态(2026-05-17)**:v4-beta 收口完成 + v4.0.0 记忆线收口(audit 完结 + 修复链 ship,代码核验,待真机回归),进入剩余 v4.0.0 ship 路径。
> - v4-alpha shipped 2026-05-13(chunk 14 + UX-004/005/007 + hotfix-3 ~ 10)
> - **Bugfix 1-4 系列** shipped 2026-05-13/14(sanitize 加固 / Settings 拆分 / AI Providers 重构 / observability + 小窗修复)
> - **Persona Engineering Segment 1/2** shipped 2026-05-15(5 层 prompt 框架 + multi-variant + ja tag pipeline)
> - **v4-beta 收口批次** shipped 并真机验证 2026-05-16(回退纯中文 / short_term 三级隔离 / conversation 锚定绑定语义 / character_switch 不杀 in-flight turn / 对话 UI 统一 / token 成本治理)
> - 下一站:文档纠真 ✅ → 长期记忆链路 audit ✅(修复链 ship,代码核验,待真机回归)→ Stage 3 v4.0.0 MVP 封装(TTS cap/throttle **移出 v4.0 范围,deferred** 至多人测试再议;当前仅 `tts_call_log` 监控,无强制闸)

> ⚠️ **接管必读(5 个 red flag,新 Claude 先看这个)**:
> 1. **Mai ja TTS 已活路径 via GSV mai_v4**(2026-05-26 INV-11 Stage 1 ship,**取代** v4-beta "回退纯中文" 旧状态)—— `cid=1` voice_model 切到 `provider=gsv` `model=mai_v4` `tts_language=ja` 完整 schema · GPT-SoVITS 自托管 server(`106.75.224.167:9880`)+ 16 emotion bank LLM 路由 · 人格不动 · 旧 ja 中日交替链(§6.5)仍 deprecated · F0 后处理翻译路径也已 deprecated(因 GSV 直接日语原声达成同目标)。新加 model 走 `backend/config/tts_models.json` + `docs/adding-new-tts-model.md` playbook。**Mai 双 cid 现状**(commit `1b25881`):cid=1 = 显示名 Momo + persona 内核 Mai + GSV ja;cid=101 = 显示名 樱岛麻衣 + 同 Mai 内核(11 字段 byte-identical 覆盖) + **Fish s2-pro ja**。两份并行 = 双 TTS provider A/B。详 §角色映射真值表。
> 2. **TTS provider × model × voice paradigm**(INV-11 Stage 1.5)—— 三级解耦 · `backend/tts/registry.py` + `backend/config/tts_models.json`(pydantic + fail-fast + missing-file fallback)· VoicePicker inline paradigm B(原 modal 已删)· 详 §5.8.5。改 TTS 链前必读。
> 3. **长期记忆链路 audit 完结、修复链已 ship** —— 根因=抽取 prompt 偏 fact-only + 闲聊→合法 [];子 bug=purge 不重置指针。修复链(滚动摘要层 + 指针自愈/reconcile + prompt 重平衡 + 墓碑)已 ship 且代码核验;**陪伴质量待真机回归(验收门)**。§4 声明已更新;详 DESIGN §五·补 + §十五之 Z.5.1。
> 4. **conversation 锚定绑定语义已上线(§5.9)** —— 切角色/串台/回复被吃全靠这套规则 A/B。改对话/角色/proactive 投递相关代码前必读 §5.9,别破坏绑定。
> 5. **进入动画 + 持久"上次选的角色" + 立绘馆发牌入场 ship**(2026-06-07~08,commits `f4fe120` + `3068849`)—— LoadingScreen Beat 0/1/2 + appReady 4 路 gate(embedding + whisper + ws + live2d · 无 VAD)+ engine 起步晚 3s 让 boot-log 0% 起爬 + 加载完成 latch + Enter/Space/click dismiss(Cmd 修饰键拒,bisect 实证);`users.current_character_id` DB 列(v4 migration)+ ws character_switch 真 handler 持久 + 三级兜底链;立绘馆 stack→stage-up→reveal 三态机 + replay。改 LoadingScreen / Gallery intro / `_resolve_conv_char` / `main.tsx` bootstrap 前必读 §11/§12/§13。

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

- **Trigger pack**(时间驱动):`lunch_call` / `dinner_call` / `bedtime_chat` / `long_idle` 常驻;`wake_call` ⇄ `morning_briefing` 互斥(由 `config.proactive.mode` 选其一) — 时间窗 + cooldown + daily cap
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
  ├─ VAD 模式  silero MicVAD(Web,自托管 onnx) → 内部 buffer audio
  │            recordingMode 切手动时 useAudio useEffect 订阅自动 pause silero
  │            (避免双路并行 sendVoice;详 Round 5 系列)
  ├─ 手动      MediaRecorder + 用户点起停
  └─ 文本      直接送

  → ASR        faster-whisper(本地)→ asr_result 推送前端
  → ChatAgent  PromptRenderer + LiteLLM tool calling
                ├─ short_term:(user, character, conversation) 三级隔离,cap 25 turn (=50 messages,SHORT_TERM_MAX_TURNS=25);conv >60 messages 触发 fold
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
> **v4-beta**:chat_history 是对话存档 + restore 源,**不是记忆本身**。运行时短期记忆 = 进程内 short_term buffer,按 **(user, character, conversation)** 三级隔离,cap 最近 25 turn (=50 messages,`SHORT_TERM_MAX_TURNS=25`,代码真值;token 治理);进程重启从此表**按 conversation 过滤**恢复(`get(conv_id=X)` 严格匹配,不跨对话/跨角色串)。删对话 = 硬删 chat_history + conversations,不动 memory/profile/进程内 short_term。

### conversation_summary(v4.0.0 b91505a 有界滚动摘要层)
```
id, user_id, character_id, conversation_id,
summary_text, last_folded_chat_history_id, token_budget, updated_at
UNIQUE(user_id, character_id, conversation_id)
```
> 给每个 (user, character, conversation) 三元组维护一份滚动摘要,worker(`backend/memory/summary.py`)按 `last_folded_chat_history_id` 增量折叠超出 short_term cap 的旧 turn 进 `summary_text`;ChatAgent 注入 prompt 时取最新一行。补 short_term 硬性 cap 25 turn (=50 messages) 之外的"中期记忆"层。fold 触发门 = 会话 messages > 60(`SHORT_TERM_MAX`,见 `summary.py:333-345`),未达阈值的 conv 会有 placeholder 空行(`summary_text=''`)属预期。

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
profile_summary 列保留为空列([RETIRED 2026-05-19],fallback 已退役于 commit c1d65ff;
未 DROP COLUMN,留作后续单独小刀)
```

### users.current_character_id(v4 commit `f4fe120` · 2026-06-07)
```
INTEGER NULL · 软引用 characters.id · 不设 FK 约束
写入:ws.py:_persist_current_character(由 character_switch endpoint loop 真 handler 调)
读取:ws.py:_resolve_conv_char 三级兜底链 incoming → persisted → Momo by name
       users_api.GET /users/{id}/profile 返新字段
指向已删角色 → 静默回落 Momo · 应用层校验 · DB 不级联
v4 migration: backend/database/migrations/v4_users_current_character.py(幂等 PRAGMA)
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
- Trigger pack(确切清单):`lunch_call` / `dinner_call` / `bedtime_chat` / `long_idle` 常驻;`wake_call` ⇄ `morning_briefing` 互斥(由 `config.proactive.mode` 选其一)
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

> **v4.1 待启用 · prompt caching**：按 provider whitelist（Anthropic / Qwen / Bedrock）显式注入 `cache_control: {"type": "ephemeral"}` marker；OpenAI / DeepSeek 自动 caching 自然命中。`config.yaml` 开关默认 ON。陪伴长对话场景，静态前缀（~19k tokens：tools_schema + addendum + persona Layer C1-3 + Layer A/B）按 10% 价缓存，单轮等效付费理论砍 67-83%。详 ROADMAP v4.1。

### 5.8 Observability(v4-beta Bugfix-4)
- tts_call_log + 4 source bucket(chat/proactive/activity_smart/preview)
- input_chars > 500 anomaly 红色高亮
- psutil 抓 RAM/CPU/Whisper/network,3s 刷新
- 见 §7

### 5.8.5 TTS Provider × Model × Voice paradigm(INV-11 Stage 1.5,2026-05-26)

> 接管必读:加新 TTS provider / 加 model / 改 voice_model JSON shape 前必读 + `docs/adding-new-tts-model.md` playbook。

#### 三级解耦架构

```
provider           model                    voice
─────────          ─────────                ─────────
cosyvoice    →     cosyvoice-v3-flash   →   7 系统(longyumi_v3 等)
cosyvoice    →     cosyvoice-v3.5-plus  →   7 系统 + N 复刻(双轨)
fish         →     s2-pro               →   reference upload(per-character)
gsv          →     mai_v4               →   emotion bank(16 ref LLM 路由)
gsv (future) →     gsv-zeroshot-v4      →   reference upload(per-character)
```

#### 注册表 single source of truth

`backend/config/tts_models.json`(项目根 `backend/config/` 下,与 characters.yaml 同级)— 静态 provider × model 配置;pydantic schema validate 启动期 fail-fast;file missing → hardcoded fallback(`backend/tts/registry.py::_hardcoded_fallback`)。

cosyvoice 复刻 voice 不在 json · 走 DB 抽(`characters.voice_model` 字段含 `cosyvoice-v3.5-plus-bailian-*` 前缀的 row · 见 `registry.py::_load_cloned_voices_from_db`)· 跟 json 静态合并产出 `get_provider_tree()`。

#### voice_model JSON schema(per character DB 字段)

```
cosyvoice slim schema(legacy + 现 VoicePicker 写):
  {provider, model, voice, instruct_supported, tts_language?}

fish/gsv 完整 schema(modelMeta spread):
  {provider, model, voice?, tts_language, gpt_weights, sovits_weights,
   emotion_bank_dir, remote_emotion_bank_dir, default_emotion,
   server_url, inference_params, fish_latency, ...}
```

backward compat:GSV `_resolve_weights_field(gpt_weights/gpt_path)` 双字段名 fallback(Lesson #11)· 长期 v4.1 migration v2 force upgrade 立项。

#### GSV 2 mode schema(Part C 预留)

| Mode | 状态 | server 端 | 本地端 | 加新流程 |
|---|---|---|---|---|
| `trained` | 已实施(mai_v4) | 训好的 GPT + SoVITS weights + emotion bank(16 wav + 16 lab) | lab cache(`tts/gsv/<model_id>/*.lab`)| server rsync weights + 16 ref · 本地 rsync .lab · 改 json |
| `zeroshot` | 占位 schema · frontend 待实施 | v4 pretrained base(已存 · 无需新 train) | 用户上传单个 ref audio + prompt text(类似 Fish s2-pro) | 编辑 tts_models.json `mode: "zeroshot"` · ref upload UI 复用 Fish reference upload pattern |

`registry.py::list_voices` 按 mode 分支返不同 placeholder voice(trained → `emotion_bank` · zeroshot → `reference` + `requires_reference_upload=true` + `gsv_mode: "zeroshot"`)· frontend 据 `gsv_mode` 决定 UI 形态。

> 缺省 mode 字段视为 "trained" 向后兼容旧 schema(加 mode 字段前的 gsv entry 仍 work)。

#### Character ↔ Voice ↔ Provider 关系图

```
characters table(DB)
  ┌─────────────────────────────────────────────────────────────┐
  │ id │ name      │ voice_model (JSON)                         │
  ├────┼───────────┼────────────────────────────────────────────┤
  │  1 │ Momo(Mai)│ {provider:"gsv", model:"mai_v4", ...}       │
  │  3 │ 荧        │ {provider:"cosyvoice", model:"v3.5-plus",  │
  │    │           │  voice:"cosyvoice-v3.5-plus-bailian-..."}  │
  │  4 │ 凝光      │ ""(empty · global default fallback)        │
  │101 │ 樱岛麻衣  │ {provider:"fish", model:"s2-pro",          │
  │    │           │  reference_audio_path:..., fish_temp:0.2}  │
  └─────────────────────────────────────────────────────────────┘
                              │
                              ▼ get_tts_engine(voice_model)
  backend/tts/__init__.py::_build_engine
       cosyvoice → CosyVoiceTTS / fish → FishTTS / gsv → GSVTTS
                              │
                              ▼ synthesize(text) → wav bytes
                       ws.py audio_chunk push

  GET /api/tts/providers(nested tree from registry.py + DB merge)
                              │
                              ▼
  frontend/components/character/VoicePicker.tsx
    inline 3 级 dropdown (paradigm B):provider × model × voice
    + voice list 系统音/复刻双 section header
    + auto-save debounce 300ms PATCH /api/characters/{cid}
```

#### inline VoicePicker(paradigm B,Lesson #12)

原 `VoicePickerModal.tsx`(modal 形态)已删 · 替代为 `character/VoicePicker.tsx` inline 进 CharacterPanel · 一屏看全部 voice config + dropdown change auto-save(debounce 300ms · 仅 edit 模式)。触发条件:picker 字段 ≥ 3 级 + 父表单还有其他字段并存 + 用户预期 hover-see-all 而非 click-into。

#### 加新 model 流程速查

详 `docs/adding-new-tts-model.md`(3 例:GSV trained / GSV zeroshot placeholder / Fish 新 model + schema 字段表 + 排错)。Trained model 8 步:server rsync weights + 16 emotion ref · 本地 rsync .lab · 编辑 tts_models.json · backend restart(pydantic validate)· 前端 dropdown 自动显示 · PATCH character voice_model · chat 验证。

### 5.8.6 网易云 audio source 双路径 + mpv subprocess(INV-16/17/18,2026-05-29~31)

> 接管必读:加新音乐 capability / 改 mpv spawn args / 升 mpv 版本 / 改 weapi payload 前必读。详 `docs/SESSIONS/2026-05-30-to-31.md` + `docs/netease-music-setup.md`。

#### 三 dispatcher 矩阵

```
netease_web              netease_local              media
────────────             ─────────────              ─────
weapi + mpv-first        mpv 直接 IPC               MediaRemote framework
(发起播放)               (控 mpv 自身)              (跨 source 系统级 fallback)
─────────────────        ─────────────────          ─────────────────
daily_recommend          play_song(song_id)         next_track
personal_fm              play_playlist(id)          previous_track
play_song(keyword)       pause                      play_pause
play_playlist            resume                     now_playing  ← 看不见 mpv
play_playlist_by_id      stop                       set_volume
like_current             next_in_queue
search                   now_playing                7 + 7 + 5 = 19 total actions
                         (Patch D 2026-05-30)
```

#### tool_addendum audio source 优先级(INV-18,3 条规则)

```
1. 本会话调用过 netease_web 或 netease_local(走 mpv-first 路径)
   → 后续所有播放控制(暂停/继续/下一首/查在播)首选 netease_local.*
   (同 source 闭环 · backend 内嵌 mpv 内部 state 一致)

2. netease_local 返 not_running / 本会话从未走过 mpv-first
   → fallback media.*(MediaRemote 跨 source · 控 NCM 客户端 / Spotify / etc)

3. 用户明确说"系统播放控制 / NCM 客户端那个 / 浏览器那个"
   → 直接走 media.* 不要 netease_local
```

now_playing 默认顺序反转(2026-05-31):旧"先 media → null fallback netease_local" → 新"首选 netease_local → False 再 media"(media 看不见 mpv 是常态非错误)。

#### mpv subprocess lifecycle(INV-17)

```python
# backend/integrations/mpv_player.py · 关键 invariant
spawn_args = [
    binary,
    "--idle=yes",
    "--no-terminal", "--no-video", "--audio-display=no",
    f"--input-ipc-server={SOCKET_PATH}",
    # 注: 无 --media-keys=yes · mpv 0.41+ 该 flag rename 为 --input-media-keys
    # 且默认就 yes · 无需显式传(显式传老名字 fatal · 详 Lesson #36)
    "--force-window=no",
]
# stderr 启动那段必 capture(防黑盒 · 详 Lesson #37)
stderr=subprocess.PIPE  # 不是 DEVNULL
# loadfile 后立即 set pause False(防 sticky pause 跨 loadfile · 详 Pit 1)
await self._send_command(["loadfile", url, "replace"])
await self._send_command(["set_property", "pause", False])  # idempotent
```

**socket path**:`Path(tempfile.gettempdir()) / "skyler_mpv.sock"` · macOS 上是 `/var/folders/.../T/skyler_mpv.sock`(系统 per-user temp)· 非 `/tmp/`(`/tmp` 在 macOS 有权限限制 · 普通用户写不进)。

**stderr capture pattern**:启动失败时(socket 2s 没出现)`_read_stderr_tail()` read 200ms tail · 塞进 `RuntimeError` detail · 下次 incident 不靠 manual repro。helper 实现在 `backend/integrations/mpv_player.py` module-level。

#### weapi 调用 + NCM rotation 防御(INV-16)

**payload schema 演进**:
```python
# 旧(<2024)· 全 400 在 NCM 2024 API rotation 后:
payload = {"ids": json.dumps([sid]), "br": 320000}

# 新(2026-05-31 Patch A · 真通):
_BR_TO_LEVEL = {320000: "exhigh", 192000: "higher", 128000: "standard", 999000: "lossless"}
payload = {"ids": json.dumps([sid]), "level": _BR_TO_LEVEL[br], "encodeType": "flac"}
```

**`_weapi_post` 返类型契约**:总返 dict · 否则上层 raise `NeteaseAPIError`。client 错误路径 diagnostics 留全文(BOM / raw bytes / 非 JSON detail 200 char)。

**5 端点 isinstance 防御矩阵**(NCM 风控 frequent_visit 防御):

| 端点 | 风控返 | type contract bug 现象 |
|---|---|---|
| `playlist_detail` | `data["playlist"]` 非 dict | 下游 `pl.get("tracks")` AttributeError |
| `search`(× 4 type:song/album/artist/playlist) | `data["result"]` 是 str `"frequent_visit"`/`"need_login"` 不是 dict | 下游 `result.get("songs")` AttributeError |

修法 = 每端点入口加 `isinstance(x, dict)` check · 非 dict log warn + 返空 list/dict · 不抛。

#### 错误归类语义(Patch C · INV-16)

```python
# 旧统一 mpv_play_failed → LLM 看字面 "mpv" 推断"装 mpv"(实际可能跟 mpv 无关)
# 新 3 档区分:
"netease_api_error"      # weapi call 失败(get_song_url 400 / 风控 / 网络)
"mpv_error"              # mpv subprocess 死了(--media-keys fatal / spawn 失败 / IPC closed)
"mpv_play_failed"        # mpv 在跑但 play() 抛(loadfile 失败 / IPC timeout)
"mpv_command_failed"     # pause/resume/stop/next_in_queue IPC 抛
"mpv_not_installed"      # health_check 找不到 binary(brew install mpv 引导)
```

**LLM advice 引导**(tool_addendum · 防再编 "装 mpv / 改 PATH"):返 `mpv_error` / `mpv_play_failed` / `mpv_command_failed` 时**不要**瞎编原因(不建议重装 / 改 PATH / 改环境变量 — 那是开发者层 spawn / IPC 问题)· 如实说 "mpv 内部出错 · detail 已记日志" + 把 detail 字段读给用户。

### 5.9 conversation 锚定绑定语义(v4-beta 收口,接管必读)

**模型**:切角色 = 切到该角色**最新 conversation**(无则新建);一个 conversation 1:1 绑一个角色,角色身份**由 conversation 推导**(不是由"UI 当前选中")。

- **规则 A(用户发起)**:对话发起那一刻锁定 conversation(`chat_id` snapshot),响应全程贯穿该 conversation;**即使中途切走,回复无条件投递回原对话**(不丢)。
- **规则 B(系统主动)**:proactive 触发时快照 conversation;投递前 late-gate 校验是否仍是当前对话;过时(已切走)**静默丢弃**,不冒到错角色。
- **character_switch 不进 turn 调度**:ws endpoint loop 对一般新 frame 会 cancel 旧 turn(防并发),但 `character_switch` 帧走 `elif` 分支 set_current+ack+continue,**让 in-flight turn 跑完**(否则 reply_len=0 真·0 产出被吃)。
- **short_term 三级隔离**:per-(user, character, conversation),`get(conv_id=X)` 严格匹配;桶仍按 (user,char) 不破 path-7;5 处调用透传 conv_id(ws / chat / proactive / main restore)。
- **前端守卫**:chunks 附 conv_id snapshot;`useWebSocket` stale-conv 守卫(`msg.conversation_id !== currentConversationId` → drop);emotion/motion/state_update **不**附 conv_id(角色级跨 conv 适用)。

关键路径:`backend/memory/short_term.py`(三级过滤+cap25 trim,代码真值 `SHORT_TERM_MAX_TURNS=25`,勿退)/ `backend/routes/ws.py`(:1320 character_switch 分支 + 绑定快照)/ `backend/proactive/engine.py` + `activity_smart.py`(规则 B late-gate 读 get_current)/ `backend/main.py`(restore character+conv filter)/ `backend/agents/chat.py`(_build_messages 透传 conv_id)。

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
  voice_model = {provider:'gsv', model:'mai_v4', tts_language:'ja',
                 gpt_weights:..., sovits_weights:..., 
                 emotion_bank_dir:'tts/gsv/mai_v4', server_url:...}
  ← INV-11 Stage 1 ship(2026-05-26):由 GSV mai_v4 emotion bank 真接入
    取代旧 cosyvoice longyumi_v3 zh-only · 人格不动 · 真机 chat 验证 OK

character_personas (character_id=1, variant='default'):
  identity.name='樱岛麻衣'  aliases=['麻衣', '麻衣学姐', 'Mai']
  完整 Tier-1 + Tier-2 字段(人格不动,只换语音链路)
  12 voice_samples 含 tolerance_range 三梯级
  cliche_tolerance=0.35
```

**Token cost**:Mai 满字段 (zh) ~9018 chars vs Segment 1 baseline 6636 chars(+36%,预算 ≤+50% 内)。

> **v4-beta known limitation**:`cid=1`=Mai 是**唯一**完整 persona。其他角色(`cid` 2/3/4/5/99/100,八重等)是**空骨架**(只名字 + Live2D 绑定),切过去人格空洞。v4.1 F1 仿本 spec(`docs/mai_prompt.md`)逐个灌真 persona。v4.0.0/v4-beta 主推 Mai 单角色。

### 6.6.5 语音语言机制(文本恒中文 / 语音可切)

文本语言与语音语言**解耦**,三层 + 字幕层:

1. **存储层**:`characters.voice_model` 的 `tts_language` ∈ `{zh, ja, en}`,唯一真源。
2. **Prompt 层**(`backend/agents/prompt/templates/layer_a.j2`):按 `tts_language` 切模板 —— ja 要求 LLM 把每个意群包进 `<ja>「…」</ja>` 独立 tag(一 tag = 一次 TTS);en 用 `<en>"…"</en>`;zh 不写双语指令。
3. **TTS 提取层**(`backend/utils/text_filters.extract_tts_text`):ja/en 抽对应 tag 内文本送合成(无 tag 走 fallback `「」` / 假名 regex,半截未闭合则 skip 该句);zh 反向 —— 剥掉所有 `<ja>/<en>` tag,只把中文送中文 TTS。
4. **字幕 / 历史层**(`strip_ja_en_tags_for_subtitle` + 写库 strip):始终剥成纯中文入库与显示。

→ **ja 模式下用户看到中文字幕、听到日语语音**,即为此机制。

**当前角色语音**:
- `cid=1`(Mai/Momo):`gsv` / `mai_v4` / `ja`(自训 GPT-SoVITS,2026-05-26 INV-11 Stage 1 ship)
- `cid=101`(樱岛麻衣):`fish` / `s2-pro` / `ja`(Fish 零样本参考音频)
- 二者为同一角色 Mai 在两套引擎上的并行验证(GSV 自训 vs Fish 零样本)。

> 历史 `v4_0_0_mai_revert_zh` migration 的 hotfix scope(`provider IN (NULL,'cosyvoice')`)只在 cid=1 仍是 cosyvoice 体系时把 voice/tts_language nudge 回 zh + longyumi_v3;切到 gsv/fish/edge/sovits 后短路不动,故现 cid=1 稳定为 gsv/ja。详 §技术债 mai_revert_zh 条目。

### 6.7 Mode 走 deterministic(v1)
```python
PROACTIVE_ORIGINS = {'cron', 'activity_smart', 'wake_call', 
                     'lunch_call_*', 'dinner_call'}
mode = PROACTIVE if turn_origin in PROACTIVE_ORIGINS else ROLEPLAY
```
TASK 留 enum 口子,v1 fallback to roleplay。不用 LLM classifier(省 100-300ms)。

> **远期立项 · `Mode.WORK` + Toolset by Mode**：v4.1 token 治理一轮完成后单独议。用户显式触发进入工作模式 → toolset 切到精简 dev 子集（砍娱乐类工具）→ 主动陪伴近关 → emotion/motion 表达克制。是 Skyler 的最低 schema 成本运行态。详 ROADMAP "长期技术能力扩展"。

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
- 🎛 **系统状态页**(Round 5 ②,2026-06-05):Sidebar Gauge 图标 → OverlayShell → 5 cards 仪表(语音 / 连接 / 模型 / 角色场景 / 资源);ResourcesCard 复用 `/api/observability/system/resources` poll 3s,救活原 `SettingsPanelLegacy:1155 SystemStatusSection` 死代码渲染;ConnectionCard 加 `/api/health` poll 5s 显示 embedding/whisper/llm 三模型 ready/loading 子状态;ModelsCard 拉 `/api/ai-providers?type=llm/tts` filter `is_active` + `/api/config/asr` 显示 active provider name + model,挂载一次 + 手动刷新(不 poll)

### 7.5 v4.1 加固
- TTS daily char cap per-user enforcement(**deferred · 移出 v4.0 范围,多人测试再议**;当前仅 `tts_call_log` 埋点监控,无强制闸 — 单人 dogfood 烧量可控)
- main chat per-minute throttle(同上 deferred)
- UI token 用量 daily display
- 推送延迟 metric(audio_consumer perf_counter)

---

## §7.5 大窗陪伴 UI 架构(Round 3/4/5,2026-06-01~05 重做)

### 7.5.1 浮件化 + 全窗壁纸

旧版:CharacterView `absolute inset-0` 内含 `panelOverlayStyle = bg-base 40%` scrim + 每角色 background_path 图层,壁纸只覆盖 chat main area(paddingLeft:80 之后),左右两条带和 character wrapper `translateX(-17%)` 漏出 bg-base 兜底色。

Round 3 重做:
- **`SceneBackground.tsx` 成为整窗壁纸唯一渲染层** · 挂 Panel 根 `absolute inset-0 zIndex:0` · img/video cover 真 edge-to-edge
- **CharacterView 透明** · 只渲 Live2D canvas 或 fallback 静态角色图,无任何背景叠加层
- **6 个浮件** 全部 absolute floating + glass token:TopBar / Sidebar dock(垂直居中) / ConversationList(top:20 left:80 width:280 · 折入 dock 后默认收起) / ChatHistoryPanel(右上锚定 + 左下角拖拽手柄改宽高) / ChatInput(底部胶囊 maxWidth:680) / CharacterStatePanel(锚 Panel 根 left:8 top:48,hover/click 展开完整卡)

### 7.5.2 共享玻璃 token(themes.css `--glass-*`)

单源 token,改一处全跟着变,跨 8 主题:

```
--glass-radius   16px
--glass-blur    12px
--glass-border  1px solid var(--color-border-subtle)
--glass-bg      color-mix(bg-surface 50%, transparent)     ; bg-surface 跟主题
--glass-shadow  var(--shadow-card-lift)
--glass-text    rgba(255,255,255,0.94)                     ; 深底主题
                rgba(20,22,32,0.92)                        ; morandi/watercolor 浅底翻深
--glass-text-muted   ~75% alpha
--glass-text-shadow  深底浅字 0 1 2 rgba(0,0,0,.45)
                     浅底深字 0 1 2 rgba(255,255,255,.65)
```

### 7.5.3 背景架构(Round 5)

| 层 | 数据源 | 目录 | 写路径 |
|---|---|---|---|
| **bundled 默认样例**(只读) | git tracked | `frontend/public/backgrounds/` | git commit |
| **user 自传**(可加可删) | runtime | `platformdirs.user_data_dir('com.skyler.momoos', appauthor=False)` / `backgrounds/`(macOS `~/Library/Application Support/com.skyler.momoos/backgrounds/`,对齐 Tauri 2 `appDataDir()` 默认行为) | POST `/api/backgrounds/upload`(multipart + sanitize + 重名 `-1`/`-2` · 200MB 上限流式 413 + cleanup half-written)/ DELETE `/api/backgrounds/{name}`(仅 user · path traversal 双层防御)|

`backend/services/backgrounds_scanner.py` 扫两处合并 + 加 `source: 'bundled'|'user'` 标签;前端 `lib/backgrounds.ts::resolveBackgroundUrl(item)` 根据 source 决定是否拼 `BACKEND_BASE`(bundled 走 Vite `/backgrounds/x` · user 走 backend StaticFiles mount `/userdata/backgrounds/x`)。

**关键解耦**(Round 5 step 1):SceneBackground 只消费 `store.globalScene`,不再消费 `currentCharacter.background_path` — 切角色绝不再换壁纸。`character.background_path` DB 列 + Pydantic 模型 + frontend form 字段保留 dormant(零迁移,见 §8 Tech Debt)。

### 7.5.4 VAD/ASR 单源 LS + 引擎订阅

旧版:`recordingMode` 等 4 个用户偏好硬编码 store default + AsrVadSection `useEffect[]` 懒 hydrate 从 LS · 用户上次 LS=vad 时本次启动 store 是默认 manual,打开能力浮层 hydrate 才同步 → store ≠ LS 长期 desync。切手动时仅 `setRecordingMode` 不动 silero 引擎 → silero 仍 active 继续 send voice。

Round 5 系列修法:
- `store/index.ts` `_readRecordingModeFromStorage()` 等 4 个 helper,store init 直读 LS,setter 直写 LS,LS = 单源
- `useAudio.ts` 新 useEffect 订阅 `recordingMode`,`recordingMode==='manual' && vadState!=='sleep'` → 自动 `toggleVad()` 走 active→sleep race-safe 路径
- **known issue**:手动模式仍有间歇"麦还在听"bug 未根治(P1),根因待用 7.4 系统状态页 🎙 VoiceCard 现场诊断仪 + ConfidenceBar 抓现场

### 7.5.5 关键路径速查

```
frontend/src/components/SceneBackground.tsx         整窗壁纸渲染(z-0)
frontend/src/components/CharacterStatePanel.tsx     心情小标
frontend/src/components/ConversationList.tsx        会话列表浮卡(折入 dock)
frontend/src/components/ChatHistoryPanel.tsx        聊天记录浮卡(右上锚 + 左下拖手柄)
frontend/src/components/Sidebar.tsx                 dock(5 nav · Gauge=系统)
frontend/src/components/system/SystemPanel.tsx      系统状态页主容器
frontend/src/components/system/cards/               5 卡(Voice/Connection/Models/Character/Resources)
frontend/src/components/settings/SettingsPanelV2.tsx::SceneSection
                                                     缩略图网格 + 上传 + 删除 + 高级折叠手填路径
frontend/src/styles/themes.css                      --glass-* token 单源
frontend/src/lib/backgrounds.ts                     resolveBackgroundUrl + uploadBackground + deleteBackground
backend/services/backgrounds_scanner.py             双源扫描(bundled + user)+ source 标签
backend/routes/backgrounds_api.py                   upload/delete endpoint + sanitize + 200MB 上限
```

---

## §7.6 Live2D 表演层(pixiCubism4 runtime · 2026-06-14 commit `c14065b`)

### 7.6.1 设计

SDK 自动跑的:`breath`(BodyAngleX/AngleY/Breath sin)、`eyeBlink`(model3.json Groups[EyeBlink].Ids 非空时自动周期)、`physics`、`pose`、`expression / motion` 经用户触发。SDK 没自动跑的"角色像活物"的小细节(转头幅度收紧 / 身体微晃 / per-model 水印关)走**单一 hook 复用 = `internalModel.on('beforeModelUpdate', ...)`**。

`beforeModelUpdate` emit 时机(`pixi-live2d-display` cubism4 SDK):

```
motion.update → saveParameters → expression.update → eyeBlink → focus → breath
              → physics → pose → emit('beforeModelUpdate') → model.update() → loadParameters
```

= SDK 所有 system 累加完之后 / 渲染前 · 用户钩子标准接口 · 改 codebase 仅 `frontend/src/lib/live2d/runtimes/pixiCubism4.ts` 一个文件。

### 7.6.2 三件事(commit `c14065b`)

| 项 | 实现 | 缺参数模型行为 |
|---|---|---|
| **转头 GAIN ±15°** | `Live2DModel.from(autoFocus: false)` + 自接 `window.mousemove` → 算 canvas-normalized `(x, y) ∈ [-1, 1]` → `internalModel.focusController.focus(x * FOCUS_GAIN, -y * FOCUS_GAIN)` · **`FOCUS_GAIN = 0.5`** → SDK `updateFocus` 内 ×30 倍率 → ParamAngleX/Y 满偏 **±15°**(SDK 原 ±30° 过头);Y 取负 = web 向下正 ↔ Live2D 向上正;复用现有 4 通道 gaze reset(mouseleave / blur / mouseout / mousemove 越界 clamp · 都调 `focusController.focus(0, 0)` 复位)| 全模型适用(标准 `ParamAngleX/Y/Z + EyeBallX/Y` 都在)|
| **身体微晃 BodyAngle Y/Z** | hook 内每帧 `addParameterValueById('ParamBodyAngleY', sin(t/5400 ms))` + `('ParamBodyAngleZ', sin(t/7300 ms + 1.7))` · 振幅 `±1.5°` 错相周期慢速避免规则摇头 · **BodyAngleX 不动**(SDK breath 已经在 BodyAngleX 上跑 ±4° / 15.5s,叠加会过头) | 缺 `ParamBodyAngle*` 的模型(神宫白子 / 秧秧 / 妮可)`addParameterValueById` 对 unknown ID **silent no-op** → 自动跳过 |
| **per-model 水印关**(冰糖)| 每帧 `addParameterValueById('Paramheadxy', 30)` + `('Paramheadxy3', 30)` 复刻冰糖模型自带的 `shuiyin1.exp3.json` / `shuiyin2.exp3.json`(原作者机制 = "按 1 / 2 键去水印" = 应用这俩表情)· 用 `add` 不 `set` → 跟 `red.exp3` 共用 `Paramheadxy` 时叠加 SDK 按 .moc3 烤入的 Min/Max 夹值,不破 red 几何 | 其它模型没这俩 ID → silent no-op,无副作用。**per-model 水印列表配置化**留后(若多 model 都有不同水印 ID 时重构) |

### 7.6.3 反义命名陷阱(冰糖水印)

冰糖 `cdi3.json` 把 6 个 `Paramheadxy*` 的 Name 字段标为"水印开关 / 立绘:神宫凉子 / 建模:杨小唸 / 发布者哔哩哔哩账号 …" — 字面像"水印 ON 控制器"。但真源是模型作者机制 "**按 1/2 键去水印**" = 应用 `shuiyin1/2.exp3.json`(+30 Add)→ `30 = 水印**关** / 0 = 水印**开**`(Name 反义,大概率指代"启用水印控制器"而非"开水印")。

前两版按字面"30 ON / 0 OFF" set 0 全帧强制,等于**把水印死按在开**,真机两次没用。c14065b 是第 3 版方向修正(add 30 复刻 shuiyin 表情)。

### 7.6.4 阿芙洛狄忒 fense(2026-06-14 上线)

- `frontend/public/live2d/阿芙洛狄忒/fense/` · `.moc3 v4`(2.22 MB · 当前 Cubism 4 Core 渲得出)· 6 motion(`jingya / kaixin / shengqi / shuijiao / wink / yaotou`)+ 5 expression(`axy / heilian / kuku / lianhong / shengqi`)
- **lipsync 零代码**:`coreModel` 含标准 `ParamMouthOpenY` · `pixiCubism4.ts:88 LIPSYNC_PARAM_ID = 'ParamMouthOpenY'` hardcode 兜底直接命中 · TTS amplitude 喂入即开合(不读 model3.json Groups[LipSync].Ids · 该字段空也无碍)
- **2 处数据级 patch** 在 `model3.json`(在 `.gitignore` 排除目录内 · 本地生效不入 git):
  - `Groups[EyeBlink].Ids: [] → ["ParamEyeLOpen","ParamEyeROpen"]` → SDK `CubismEyeBlink.create()` 自动周期 4~6s 眨眼
  - `Motions group key: "" → "Idle"` → SDK 找 `groups.idle = "Idle"` 命中 · 6 motion 进入随机 idle 循环
- `ParamBodyAngleX/Y/Z` 3/3 全在 · 7.6.2 身体微晃直接工作
- License(`使用注意事项.txt`):灵境 Sanctuary · 免费使用 · 个人 / 企业 / 公会均可 · 允许直播 · 严禁二次修改 / 销售 / 出租

### 7.6.5 关键路径速查

```
frontend/src/lib/live2d/runtimes/pixiCubism4.ts    全部表演层 · onBeforeModelUpdate hook(L271+)
  · const FOCUS_GAIN = 0.5                         L103
  · const SWAY_BODY_Y_AMP_DEG / Z_AMP_DEG = 1.5    L118-119
  · const SWAY_BODY_Y_PERIOD_MS / Z = 5400 / 7300  L120-121
  · const SWAY_BODY_Z_PHASE_RAD = 1.7              L122
  · const BINGTANG_WATERMARK_OFF_PARAM_IDS         L150 (Paramheadxy / Paramheadxy3)
  · const BINGTANG_WATERMARK_OFF_VALUE = 30        L154
frontend/src/lib/live2d/runtime.ts                  Live2DRuntime interface(组件层调用 abstract)
frontend/src/lib/live2d/registry.ts                 getRuntime() 工厂 · moc3 v5 warn 分支
frontend/public/live2d/<slug>/<file>.model3.json    scanner 真源(一层深 glob)
backend/services/live2d_scanner.py                  scanner + moc3 binary header parser
backend/routes/live2d_api.py                        GET /api/live2d/models + POST /api/live2d/upload
```

---

## §7.7 MCP 能力层(2026-06-15~17 batch · 已 ship · 4 MCP commit + merge `89b9f4e`)

> 状态(2026-06-17 合 main):
> - **已 ship + 真机验**(主链 + xhs 端到端):holder-task 模型 / SSE transport(Amap)/ 配置分文件(mcp.config.yaml + example + loader merge)/ per-tool confirm gate(dangerous_tools)/ browser_login 流(rednote-mcp 扫码)/ batch2 自校验+45s 超时+confirm 队列+deny_all_pending+登录子进程
> - **4 MCP commit**:`834fbac` holder-task / `2e5b914` SSE+拆文件 / `e805d34` confirm gate / `ab7f94a` batch2+browser_login → merge `89b9f4e`(整批同分支跟 GSV `a4a2681` 同 push,共 4 MCP + 1 GSV = 5 commit)
> - **未做(deferred)**:auto-reconnect / health probe / TaskGroup 异常解包 / stdio install-once · 见 ROADMAP TD-MCP-1~6

### 7.7.1 配置分层 + loader

```
config.yaml             (本地)主配置 · 不再放 mcp 段(④ 拆走)
mcp.config.yaml         (本地·gitignored)真名单 + ${VAR} 占位
mcp.config.example.yaml (入库)模板 + 4 范式注释 + 范式 6 browser_login
DB mcp_credentials      真凭证(${VAR} 解析时拉)· 凭证 modal 写盘
DB mcp_client_state     server enabled 持久态
DB mcp_tool_state       tool enabled + require_confirmation(⑤ 新增列)
```

`backend/config/__init__.py:40 load_config_yaml()` merge 语义:`mcp.config.yaml > mcp.config.example.yaml > none` · 整段替换 `mcp_clients` / `mcp_server` 两 key,不深合并(L74)。

### 7.7.2 transport 三种(`backend/mcp/client.py:177-211`)

| transport_kind | SDK | conf 字段 |
|---|---|---|
| `stdio` | `mcp.client.stdio.stdio_client` | `command` + `args` + `env` · `shutil.which` 早 fail |
| `http` (streamable) | `mcp.client.streamable_http.streamablehttp_client` | `url` + `headers` |
| `sse` | `mcp.client.sse.sse_client` | `url`(支持 `${VAR}` 展开 · cred-aware 临时 patch `os.environ`) |

`_CALL_TOOL_TIMEOUT_SECONDS = 45.0`(client.py:62)· 包 `asyncio.wait_for` 防慢 server / 死循环卡 capability handler 永等。

### 7.7.3 client 生命周期 · holder-task 模型

每条 client 一个**后台 holder task** = `_holder_task()`(client.py:142),`async with AsyncExitStack` 的 enter + exit **全在同一 task 内完成**,绕开 anyio cancel-scope 跨 task 报错。

```
_start_holder()  (client.py:400)
  └─ create_task(_holder_task)
       └─ async with stack:
            stack.enter_async_context(stdio_client / streamable / sse)
            stack.enter_async_context(ClientSession)
            session.initialize()
            list_tools → seed mcp_tool_state + seed_require_confirmation
            handle.connected = True
            ready_event.set()              ← _start_holder 此时返回
            await stop_event.wait()         ← HOLD · 等外部
       (退栈 · 自动 aclose · 同一 task)
       holder_task = None

_stop_holder()   (client.py:427)
  └─ stop_event.set()  +  await holder_task
```

字段(`_ClientHandle` L69-94):`stop_event` / `ready_event` / `holder_task` / `connect_error` · 每次 `_start_holder` 重置 · holder 不复用。

### 7.7.4 auth 两类

| 类别 | 标识 | 凭证位置 | UI 入口 | enable 前置 |
|---|---|---|---|---|
| `env_required` | conf `env_required: [...]` | DB `mcp_credentials` | 凭证 modal(password input) | `missing_credentials` 空 |
| `browser_login` | conf `auth: browser_login` | 子进程写 cookie 文件 | 「登录 / 重新登录」按钮(扫码) | `cookie_ready()` 真 |

**browser_login 流**(`backend/mcp/browser_login.py`):
- `start_login()` L89:`asyncio.create_subprocess_exec(login_command, *login_args)` + `asyncio.create_task(_watch_login_proc)` background watcher · HTTP endpoint 立即返,不 hang(10 分钟扫码窗)
- `_watch_login_proc()` L165:子进程 `proc.communicate()` 退出后判 cookie 文件存在 → status 翻 `cookie_ready` / `error`
- `cookie_ready()` L75 = 文件 exists + 非空 · `_holder_task` enter 时 L168 调,**没 cookie 直接 raise FileNotFoundError**,不开浏览器、不卡 holder
- `is_browser_login_entry()` L236:`conf.get("auth") == "browser_login"` · 给 `list_status()` 决定按钮类型
- 状态机 4 态(枚举与 `mcp_api.py:71 MCPLoginStatusItem` 必须同步,否则 response_model 序列化 500 全表):`no_task` / `running` / `cookie_ready` / `error`

### 7.7.5 per-tool confirm gate(⑤)

dangerous_tools 链路:

```
mcp.config.yaml entry · dangerous_tools: [tool, ...]
            ↓ _holder_task ENTER(client.py 内)
seed_require_confirmation(server, tool_names)
   ─ tool_state.py:81 · INSERT OR IGNORE · 不覆盖用户 override
            ↓ runtime call_tool
is_confirmation_required(server, tool)   tool_state.py:37
            ↓ True
request_confirmation()   confirm_gate.py:111
   ─ push WS event 'mcp_tool_confirm_request' via register_push_callback
   ─ await asyncio.Event(120s timeout)
   ─ accept   → 返回(handler 跑真 call_tool)
   ─ reject   → raise ToolConfirmationRejected(非 CancelledError · handler 捕获返"已取消"给 LLM)
   ─ timeout  → 同 reject
   ─ no-callback (WS 未连) → 同 reject
```

WS 边界(`backend/routes/ws.py`):
- 连上时 `register_push_callback(send_json)` · 断开时 `deny_all_pending()`(confirm_gate.py:218 · set Event accept=False · 防 holder task 永等)+ `register_push_callback(None)`
- 入口 `mcp_tool_confirm_response` 早路由 → `resolve_confirmation(request_id, accept)`

**零改 prompt**:dangerous tool 跟其它 tool 同走 `ToolRegistry` 注册 · LLM 看见的 schema 没变 · 是否拦在 call 边界判;tool 关 = 不 spawn / 不注册进 prompt / 零 token 负担。

### 7.7.6 batch 2 自校验 + 边界

| 项 | 位置 | 行为 |
|---|---|---|
| dangerous_tools 名对账 | `client.py` ENTER list_tools 之后 | `stale_dangerous`(配置里有 / 真 tool list 没)+ `possibly_naked`(真 list 像写操作但配置没列)各打一行 WARN · 不阻断启动 |
| 45s call_tool 超时 | `client.py:62` `_CALL_TOOL_TIMEOUT_SECONDS = 45.0` | `asyncio.wait_for` 包 session.call_tool · 慢 server / 死循环不卡死 capability 永等 |
| confirm 队列(并发) | `frontend/src/store/index.ts` | 单 confirm state → 数组 `mcpConfirmQueue` · `Modal` 渲队首 + "队列 +N" 角标 · `enqueueMcpConfirm` 按 request_id dedup |
| WS 断开清理 | `confirm_gate.py:218` `deny_all_pending()` + `ws.py` finally | 断线前所有 pending confirm 自动 deny · holder 不挂 · LLM 看到"已取消"工具结果 |
| 浏览器扫码登录 | `browser_login.py` 全文件 + `mcp_api.py:130-170` 两 endpoint | 见 §7.7.4 |

### 7.7.7 已接 server 现状(`mcp.config.yaml`,16 entries)

| 类别 | 名 | 凭证 | dangerous | 状态 |
|---|---|---|---|---|
| 内置工具/示例 | filesystem / filesystem-skyler / filesystem-test / everything / fetch | 无 / 路径 | — | enabled |
| 搜索 / 笔记 | brave-search / notion | env_required | — | 凭证可填即用 |
| 地图 / 天气 | amap(SSE) / amap-stdio(兜底) | `AMAP_MAPS_API_KEY` | — | SSE 主路径 |
| 行情 / 阅读 | akshare / rss-reader / xmind | 无 | — | 现 npx/uvx 现拉 · 见 §8 stdio install-once 债 |
| 邮箱 | email | 6 条 env | `send_email / reply_email / forward_email` | confirm 拦 |
| 代码托管 | github | `GITHUB_PERSONAL_ACCESS_TOKEN` | 12 条(delete / push / merge / create_pr 等) | confirm 拦 |
| 火车票 | trip12306 | 无 | — | **disabled** · 境外 IP 被 12306 TLS 重置,留 entry 不启用 |
| 小红书 | xhs(rednote-mcp) | `auth: browser_login` · cookie `~/.mcp/rednote/cookies.json` | `[login]`(防 LLM 自调弹浏览器) | **已真机过**:扫码 OK · search_notes / get_note_content / get_note_comments 拉通 |

### 7.7.8 关键路径速查

```
backend/mcp/client.py             holder-task / transport 三种 / call_tool 45s 超时
  · _CALL_TOOL_TIMEOUT_SECONDS = 45.0    L62
  · _ClientHandle stop/ready/holder      L69-94
  · _holder_task                          L142
  · transport stdio / http / sse          L177-211
  · _start_holder / _stop_holder          L400 / L427
  · list_status (auth + login 元数据)     L809-844
backend/mcp/browser_login.py       扫码 login 子进程管理 · 状态机 4 态
  · cookie_ready                          L75
  · start_login + create_task watcher    L89
  · _watch_login_proc(10min 扫码窗)     L165
  · get_login_status / is_browser_login   L209 / L236
backend/mcp/confirm_gate.py        WS push + asyncio.Event 拦截
  · ToolConfirmationRejected              L43
  · register_push_callback                L75
  · request_confirmation(120s timeout)   L111
  · resolve_confirmation                  L200
  · deny_all_pending                      L218
backend/mcp/tool_state.py          enabled + require_confirmation 持久态
  · is_confirmation_required              L37
  · seed_require_confirmation(幂等)      L81
  · set_require_confirmation              L110
backend/routes/mcp_api.py          REST 路由
  · MCPLoginStatusItem(Literal 4 态)     L71
  · MCPClientStatusItem(auth+login 字段) L78
  · GET  /mcp/clients/status              L105
  · POST /mcp/clients/{name}/login        L130
  · GET  /mcp/clients/{name}/login        L154
  · POST /mcp/clients/{name}/reconnect    L172
backend/config/__init__.py         loader merge mcp.config.yaml > example
  · load_config_yaml                      L40
  · mcp_path / mcp_example_path           L59-65
backend/database/migrations/inv_mcp_tool_confirmation.py  ⑤ 加 require_confirmation 列
mcp.config.yaml                    本地真名单 · gitignored
mcp.config.example.yaml            6 范式模板 · 入库
```

---

## §7.8 Live2D 取景层(framing · 2026-06-16~17 commit `79f9f2f`)

> 触发由来:每个 Live2D 模型原生比例 / 站位不同 · 缺统一构图方案。给用户**放大 + 下移让脚出框 = 半身锚底**的「取景」控制 · 绕开「接地阴影 + 比例」两个最难的合成问题。挂**模型**(model_key = scanner slug · 不挂 character)· 共用 slug 角色共享 framing。

### 7.8.1 数据

新表 `live2d_model_settings`:

| 列 | 语义 |
|---|---|
| `model_key` (PK) | scanner slug · 等于 `frontend/public/live2d/<slug>/` 目录名 · 也等于 `character.live2d_model` |
| `settings_json` | JSON 容器 · 本期写 `framing` 一个 section · `param_map` / `director` 留扩展位(未实现) |
| `updated_at` | TIMESTAMP DEFAULT CURRENT_TIMESTAMP |

容器 shape:
```json
{
  "framing": { "scale": 1.0, "offsetX": 0, "offsetY": 0 }
  // 留位:param_map / director / future · PATCH 走 merge 透传不动其它键
}
```

migration 幂等(`CREATE TABLE IF NOT EXISTS`):`backend/database/migrations/inv_live2d_model_settings.py`。ORM:`backend/database/models.py:83 Live2DModelSettings`。

### 7.8.2 API(merge 语义)

`backend/routes/live2d_settings_api.py`:

| route | 行为 |
|---|---|
| `GET  /api/live2d/models/{model_key}/settings` | 无 row → 返 default framing + 空 extra(不写库) |
| `PATCH /api/live2d/models/{model_key}/settings` | **merge** `{**existing, framing: new}` · 其它键(`param_map` / `director`)透传不替换 · backend clamp 防呆 |

clamp 边界(backend + frontend 双 clamp):scale ∈ [0.3, 5.0] / offset ∈ [-2000, 2000]。

resolver 形跟 `resolve_tts_language(backend/tts/voice_config.py:42)` 同款:**DB override > 默认**(2-tier · 因为模型层无 registry spec 层概念)。`resolve_tts_language` 是 3-tier(DB > registry > "zh")· framing 简化成 2-tier · 形态一致。

### 7.8.3 Runtime · base × framing 叠加(不替换)

`frontend/src/lib/live2d/runtimes/pixiCubism4.ts`:
- `MountContext` 加 `framing: Live2DFraming` default `DEFAULT_FRAMING = {1.0, 0, 0}`
- `_fit(ctx)` 改:
  ```
  baseScale  = min(w/nativeW, h/nativeH)
  finalScale = baseScale * ctx.framing.scale            // L497
  model.x    = (w - W*finalScale)/2 + ctx.framing.offsetX  // L502
  model.y    = (h - H*finalScale)/2 + ctx.framing.offsetY  // L503
  ```
  framing scale=1 + offset=0 时跟 base fit 严格等价。
- `setFraming(handle, framing)`(L520+):`ctx.framing = framing` → `_fit(ctx)` · 拖拽/wheel/滑块每次都走这条 · 单次 O(1)。

跟 §7.6 表演层共存验证:`_fit` 写 PIXI `model.x/y/scale`(PIXI Container 空间),`beforeModelUpdate` hook 写 `addParameterValueById('ParamBodyAngleY/Z')`(Cubism 参数空间)· **两条独立通道不互相 stomp**(merge `89b9f4e` 真机验过)。

### 7.8.4 前端 lib

`frontend/src/lib/live2d/settings.ts`:
- 类型 `Live2DFraming` / `Live2DSettings` + `DEFAULT_FRAMING`
- `clampFraming(f)`(跟 backend 同边界 · diff 即 bug)
- API client `fetchLive2DSettings(slug)` / `patchLive2DFraming(slug, framing)` · slug 经 `encodeURIComponent`(支持中文 slug 如 `阿芙洛狄忒`)

### 7.8.5 UI · Live2D 管理组件(scope = 模型)

`frontend/src/components/character/Live2DManagerSection.tsx`:
- 容器标题 "Live2D 管理 · {slug}" · 挂在 CharacterPanel Live2D 模型 dropdown 之后
- **Section 1 取景**(本期):scale 滑块(0.3-5.0 步进 0.05)+ X / Y 数字框(本地 text state · editing ref · 空串/前导 0/负号中途态不卡 · blur 归一化)+ 重置 / 保存 / "未保存"黄字
- **Section 2 / 3 占位注释**(未渲染):未来 param_map / director

实时预览 store 链:
```
拖拽/wheel/滑块 → setPendingFraming
  → Live2DCanvas useEffect [pendingFraming, fallbackFraming] → runtime.setFraming(handle, target)
保存成功 → setSavedFraming(new) → setPendingFraming(null)(顺序很关键 · 防闪回 stale)
```

`savedFraming = { modelKey, framing }` 跨组件同步 · `Live2DCanvas` `fallbackFraming` `useMemo` 派生(slug 匹配才用 saved.framing · 否则 DEFAULT)。

### 7.8.6 Widget gate(小窗永远全身)

`Live2DCanvas:50` 加 `applyFraming: boolean` prop · `CharacterView:52` 按 `mode === 'panel'` 算:
- **Panel(大窗主视图)** → applyFraming=true · 吃 framing(bust 半身锚底)
- **Widget(小窗整窗透明)** → applyFraming=false · adjustMode / pending / saved 全 short-circuit `false/null/null` · 跳过 fetch + 不写 store · 永远 DEFAULT 全身 base fit

小窗整窗 `overflow: hidden`(`App.tsx:228` + `Panel.tsx:114`)· 大窗 framing scale>1 + offsetY 大幅下移时超出部分被裁 = 脚出框成立。

### 7.8.7 容器留位 vs parked 决策(诚实分层)

`live2d_settings` JSON 容器的 `param_map` / `director` 字段是**留位**(`live2d_settings_api.py:12,50` 透传逻辑 + `models.py:93` 注释)· merge 时不识别也不替换 · 0 读 / 0 写 / 0 runtime 路径。

| 块 | 容器位 | 决策路径 | 状态 |
|---|---|---|---|
| framing | ✅ 已 ship(本段) | scale × offset 叠加 _fit | ✅ ship |
| param_map | ✅ 留位(JSON 透传) | per-model 概念→Cubism 参数 map | parked(详 §17.1 / ROADMAP Live2D backlog) |
| director | ✅ 留位(JSON 透传) | emotion → 三仓库 cooldown/weighted 决策 | parked(详 §17.1 brick #2-5) |

### 7.8.8 关键路径速查

```
backend/database/migrations/inv_live2d_model_settings.py  CREATE TABLE
backend/database/models.py:83                              Live2DModelSettings ORM
backend/routes/live2d_settings_api.py                      GET/PATCH merge · clamp
frontend/src/lib/live2d/settings.ts                        类型 + clamp + API client
frontend/src/lib/live2d/runtime.ts                         setFraming 接口
frontend/src/lib/live2d/runtimes/pixiCubism4.ts:497-503    _fit 叠加 base × framing
                                            :520+          setFraming 实现
frontend/src/components/character/Live2DManagerSection.tsx UI · scope=slug
frontend/src/components/Live2DCanvas.tsx:50                applyFraming prop
                                       :100+               fallbackFraming useMemo
frontend/src/components/CharacterView.tsx:52               mode==='panel' gate
frontend/src/store/index.ts                                live2dAdjustMode + pendingFraming + savedFraming
```

---

## §8 当前 Tech Debt 优先级速览

### 🔴 v4.0.0 critical(ship 前必处理,按序)
1. ✅ **文档纠真**(本批次完成;DESIGN.md 大整合立项留待表层重构 pass)
2. ✅ **长期记忆链路 audit + 修复链** —— audit 完结(根因=fact-only prompt + 闲聊→合法 [];子 bug=purge 不重置指针),修复链已 ship 且代码核验;**陪伴质量待真机回归(验收门)**。详 §4 更新 + DESIGN §十五之 Z.5.1
3. ~~TTS daily char cap per-user enforcement~~ → **deferred 出 v4.0,多人测试再议**;当前 `tts_call_log` 监控,无强制闸
4. ~~main chat per-minute throttle~~ → **deferred** 同上

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
15. characters.yaml vs DB:当前 Plan B(DB 主源 + YAML fallback);yaml 仅含 5 个内建角色(八重神子 / 默认 / 荧 / 凝光 / 神里绫华),非 DB 全集 — `cid=99/100/101` 等不在 yaml,仅 DB seed;Plan C(删 yaml DB 单源)deferred
16. config.yaml 双写源拆分
17. MCP 凭证升级 OS keyring
18. LLM 慢(**deepseek/deepseek-v4-pro** 现役 + 网络;绑定锁死后纯性能问题,独立优化不混功能修复)· config.yaml `default_model: dashscope/qwen3.6-max-preview` 仅 fallback,DB `ai_providers is_active=1` 优先(`bugfix-3.1`)· 详 §LLM 全集真值表
19. CosyVoice WS 建链 5s 超时(SDK 写死,弱网失败)
20. **`character.background_path` dormant 字段待清**(Round 5 step 1 衍生)—— 解耦后 view 层不再消费,DB 列 + Pydantic 模型 + frontend form 字段保留 round-trip 透传。未来若做"每角色默认壁纸 + 全局覆盖"混合档可启用,否则按 chore 清(form 字段删 + Pydantic 移除 + DROP COLUMN migration)。详 §7.5.3
21. **`SystemStatusSection` 旧 export 死代码**(Round 5 ② 衍生)—— `SettingsPanelLegacy.tsx:1155` 函数仍在但 caller 已删(`chore: drop dead SettingsPanel default`),Round 5 ② `ResourcesCard.tsx` 已重做同款渲染。顺手 chore 删整个函数 export
22. **VAD 手动模式间歇 bug 根因未抓全**(Round 5 衍生 P1)—— 已修两个表层根因(LS desync + 切手动 silero 未 pause),PM 真机仍偶发"麦还在听"。下一步用 §7.4 系统状态页 🎙 VoiceCard 现场诊断仪复现 + 抓 vadState/WS voice/silero 实例生命周期。详 ROADMAP P1

完整 backlog 见 [ROADMAP.md](ROADMAP.md)。

---

## §9 v4.0.0 ship 计划

| Sub-stage | Goal | ETA |
|---|---|---|
| Stage 0 | **文档纠真**(DESIGN / DESIGN_LITE / ROADMAP / README ×2 对齐 v4.0.0 + §5.8 入册)→ 落地 repo | ✅ 完成 |
| Stage 1 | **长期记忆链路 audit + 修复链** —— audit 完结 + 修复链 ship(代码核验)| ✅ ship,待真机回归 |
| ~~Stage 2~~ | ~~TTS daily char cap per-user + main chat throttle(防烧)~~ → **deferred 出 v4.0,多人测试再议;当前仅 `tts_call_log` 监控,无强制闸** | — |
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
  backend/memory/short_term.py            — per-(user,char,conv) 过滤 + cap25 trim(代码真值 `SHORT_TERM_MAX_TURNS=25` / `SHORT_TERM_MAX=50` messages,勿退)
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
  docs/archive/DESIGN.md  5,206 行 — git 在线查每个 chunk/hotfix 的详细决策
                                  (2026-05-19 docs 第二刀归档,不再维护)
  docs/archive/DESIGN_patch.md     — v4-beta 收口 patch 段,未 merge 入 DESIGN.md,
                                  与主档一起冻结归档
```

---

## §11 进入动画 LoadingScreen(Beat 0/1/2 + appReady 4 路 gate)

> commits `f4fe120`(2026-06-07)+ `3068849`(2026-06-08)· 文件:`frontend/src/components/loading/`(LoadingScreen.tsx + loading.css)+ `frontend/src/lib/loading/`(engine.ts + types.ts + configs/companionLoading.ts)+ `frontend/src/hooks/useLoadingSequence.ts`

### 三拍架构

```
mount
  │
  ├─ Beat 0(0..2.36s)power-on preamble
  │   dark hold 0.5s · 双线 ±55° pivot 1.3s(cubic-bezier(.42,.04,.2,1) · 中性暖白)
  │   convergence 1.6s + flare 0.55s + door 0.76s
  │
  ├─ Beat 1(2.36s..engine done)boot-log
  │   等宽 mono · 真实 BootTracker snapshot 21 行 · 顶 telemetry · 右锚 SVG wireframe
  │   + 弧 HUD · per-line ●/○ glyph + 距离分层(0.28/0.55/0.85/1)
  │   engine 起步晚 3s · 让 boot-log 从 0% 起爬(否则门一开就 ~33%)
  │   appReady 4 路 gate:embedding + whisper + ws + live2d(无 VAD)
  │
  ├─ engine done 真触发 → 加载完成 latch
  │   `> SYSTEM READY ✓` glow 脉冲 0.55s · 600ms 桥
  │
  ├─ Beat 2(crossfade 2.8s)暖揭幕
  │   warm 1.4s · charzone 1.3s/0.5s + transform 1.5s · title 1.3s/0.7s
  │   · enter 0.8s/1.6s · petals 1.3s
  │
  └─ 「輕觸進入」 hold(等用户)· dismiss = Enter / Space / window click
      (Meta/Shift/Ctrl/Alt/Esc/方向/F* 全拒 · bisect 实证 cut)
```

### appReady 4 路接线(只喂 gate · 不决定挂)

| 路 | 写入点 | 真值条件 |
|---|---|---|
| `embeddingReady` | `App.tsx:155` health poll 每 500ms 写 store | `/api/health` 返 `models.embedding == 'ready'` |
| `whisperReady` | 同上 | 同 whisper |
| `wsReady` | `useWebSocket.ts:436/455` onopen/onclose | WS handshake 成功 |
| `live2dReady` | `Live2DCanvas.tsx:177` resolveModel 成功后(静态 import store · race-free) | `runtime.loadModel(...)` resolved · 未 cancel |

engine `is_ready = e && w && ws && live2d` · `missing_ready` 返还缺哪几个 · 进 gate-wait 后 UI 红黄字示真态(`还缺: live2d` 等) · **永不假 100%**。

### 真值数据源(铁律)

- boot-log content 全部来自 `GET /api/observability/boot-summary`(BootTracker 真实 17 mark · `total_ms`)+ companionLoading.ts 兜底真名
- telemetry 6 段(EAGER / BG / MEM / MIG / CAP / MCP)派生 snapshot · 没回落 `—` / `warming` 不造假
- 真角色名 / live2d_model / splash 来自 store characters(DB)· 详 §角色映射真值表

### 关键 React 坑(Lesson #38)

`completionLatched` 早期版本死锁过:`setState(true)` in effect + 该 state 进 deps + cleanup 清 timer → re-render 触发 cleanup 砍 timer → 永不 fire。**修法**:state 改 ref 守一次性 + deps 砍 + 不返 cleanup(让 timer 自然 fire)。详 `docs/LESSONS.md #38`。

### 魔数集中表(调参前看这)

| 参数 | 值 | 改之前看什么 |
|---|---:|---|
| Beat 0 dark hold | 0.5s | `loading.css::.poweron-line` delay |
| Beat 0 pivot duration | 1.3s | `loading.css::.poweron-line.top/bottom` |
| Beat 0 door duration | 0.76s | `loading.css::.poweron-half` |
| Beat 0 total | ~2.36s | preamble 全段 |
| engine start delay | 3000ms | `LoadingScreen.tsx::engineStartDelayMs` · 让 boot 0% 起 |
| floor (engine 9s 时钟) | 9000ms | `companionLoading.ts::FLOOR_MS` · 从 engine.start() 算 |
| 加载完成 latch hold(桥)| 600ms | `LoadingScreen.tsx` `if (!done \|\| latchedRef.current) ...` 后的 setTimeout |
| Beat 2 crossfade ~ | 2.8s | 各 transition delay 累加 |
| App.tsx safety net | 60_000ms | engine 真死兜底 force unmount |

### reduce-motion

`@media (prefers-reduced-motion: reduce)` + React 侧 init `preamble = 'done'` · 不挂任何 preamble timer · 直接进 Beat 1。

---

## §12 持久"上次选的角色"链(`users.current_character_id`)

> commit `f4fe120` · 详 §4 schema 新加段。

### 决策链(write → read)

```
1. 用户点角色 → frontend setCurrentCharacterId + sendCharacterSwitch
2. ws.py endpoint loop(真 handler · :1235)收 `character_switch`:
   - connection_manager.set_current(in-memory)
   - **_persist_current_character(user_id, char_id)** ← UPDATE users
   - send ack · continue
3. _handle_message:643 内同名分支 = dead code(endpoint loop continue 跳过)
   保留并同样调 helper 作保险防新入口漏(bisect 验证)
4. DB 持久 → 重启不丢
5. 启动:App.tsx mount fetchUserProfile() · 优先 `current_character_id`
   校 chars 有效 → use it · 否则 fallback chars[0]
6. ws _resolve_conv_char 三级兜底链:
   incoming → users.current_character_id(校角色存在) → Momo by name
```

### 安全(指向已删角色)

- 不设 DB FK · 不级联
- 应用层校验:`SELECT FROM characters WHERE id = persisted` · 不存在 → 静默回落 Momo · log warn
- frontend `chars.some(c => c.id === persisted)` · false → fallback chars[0]
- 不崩 · 不卡

---

## §13 立绘馆发牌入场(三态机)

> commit `3068849` · 文件:`CharacterGallery.tsx` + `galleryIntro.css`(新)· FanLayout 一字未改。

### 状态机

```
open=true / replay
   │
   ▼
stack  ─── 650ms ───►  stage-up  ─── characters.length > 0 ───►  reveal
(全收住          (bg/HUD 升起 .9s            (fan wrapper .6s 从下方升起到位)
 transition:none) fan 仍 translateY+40
                  scale .82 opacity 0)

没就绪 → 死在 stage-up · 不假展开(铁律:不假数据)
replay → stage 回 stack(snap · transition:none)· 重跑
```

### FanLayout 0 改动 · 决策记

per-card 错峰甩(spec 原意的"发牌")需要 FanLayout 配合 — framer-motion inline transform vs 外部 CSS stagger 冲突,inline 总赢。当前实现"整扇升起"是 PM 接受的最小侵入版。要做 per-card stagger 需给 FanLayout 加 `introStaggerDelay` 单 prop。**入 Tech Debt TD-B**。

---

## §14 角色映射真值表(2026-06-08 audit · DB 现值)

| cid | name(显示) | Live2D 模型(DB) | TTS provider / 音色 / lang | character_personas active identity | 进入动画 accent / EN |
|---:|---|---|---|---|---|
| **1** | **Momo**(壳)| `hiyori` ✅ | **GSV** `mai_v4` `ja` · 自托管 `106.75.224.167:9880` + 16 emotion bank | **`name="樱岛麻衣"`** · aliases [麻衣 / 麻衣学姐 / Mai] | `#c97b8e` / `MOMO` |
| 2 | 八重神子 | `yae` ✅ | **CosyVoice** `cosyvoice-v3.5-plus` 克隆 `...bailian-a61e...` instruct | `name="八重神子"` | `#c97b8e` / `YAE MIKO` |
| 3 | 荧 | (空 → fallback hiyori)| **CosyVoice** `cosyvoice-v3.5-plus` 克隆 `...bailian-ec26...` instruct+ssml | `name="荧"` | `#d4b96e` / `LUMINE` |
| 4 | 凝光 | (空 → fallback hiyori)| (空 · 全局 fallback `cosyvoice-v3-flash` / `longyumi_v3`)| `name="凝光"` | `#c6a86b` / `NINGGUANG` |
| 5 | 神里绫华 | (空 → fallback hiyori)| **CosyVoice** `cosyvoice-v3.5-plus` 克隆 `...bailian-7c61...` instruct+ssml | `name="神里绫华"` | `#88aac4` / `KAMISATO AYAKA` |
| 99 | 一般路过猫娘 | (空) | (空 · 全局 fallback)| `name="一般路过猫娘"` | `#d489a0` / `NEKO` |
| 100 | 祥子-test | (空) | (空 · 全局 fallback)| `name="祥子-test"` | `#9b7bb5` / `SHOKO TEST` |
| **101** | **樱岛麻衣**(正名)| `hiyori` ✅(借)| **Fish** `s2-pro` `ja` · `reference_audio=tts/fish/参考音频/mai/reference.wav` · `temp=0.2` | **`name="樱岛麻衣"`** · 同 cid=1(commit `1b25881` byte-identical 覆盖) | `#b08a4a` / `SAKURAJIMA MAI` |
| 102 | 流萤 | (空) | (空 · `characters.persona` 写"v4 placeholder")| `name="流萤"` | `#3f9e96` / `FIREFLY` |

**Mai 双胞胎钉死**(commit `1b25881` · 2026-05-22 PM dispatch):
- cid=1 = 壳 Momo + 内核 Mai + Hiyori + GSV ja
- cid=101 = 壳 麻衣 + 内核 Mai(同 cid=1)+ Hiyori(共享) + Fish ja
- 两份并存 = Phase 2 §8 "cid=1→cid=101 数据迁移取消" + 真机验收前 cid=101 需要正确 Mai persona → 11 字段覆盖。**两条 Mai 路径并行 = GSV 全栈自托管 vs Fish 云 reference**。

**Live2D 资源真值**:`/frontend/public/live2d/` = `hiyori + yae`(+ `core/` runtime)· 7/9 角色 fallback hiyori · `live2dModelEntry` hardcode dict 仅含 `hiyori`(`yae` 缺登记 · scanner 拾到)· 入 Tech Debt TD-E。

---

## §15 LLM 全集真值表(2026-06-08 audit · DB ai_providers + config.yaml)

| id | name | model 字符串(LiteLLM 路由用) | is_active | enabled |
|---:|---|---|:---:|:---:|
| **19** | **deepseek-v4-pro** | **`deepseek/deepseek-v4-pro`** | ✅ **现役** | ✅ |
| 2 | Qwen 3.6 Max preview | `openai/qwen3.6-max-preview` | — | ✅ |
| 8 | Qwen 3.6 Plus | `openai/qwen3.6-plus` | — | ✅ |
| 16 | qwen3.5-plus | `dashscope/qwen3.5-plus` | — | ✅ |
| 17 | qwen3.6-flash | `openai/qwen3.6-flash` | — | ✅ |
| 18 | deepseek-v4-flash | `deepseek/deepseek-v4-flash` | — | ✅ |

**调度优先**(`bugfix-3.1` 起):DB `is_active=1` > config.yaml `default_model` > `.env` API_KEY。当前 active = `deepseek/deepseek-v4-pro` · yaml `default_model: dashscope/qwen3.6-max-preview` 仅 fallback(实际不命中)。

**副 LLM**(non-main-chat · 不在 ai_providers 表 · 走 yaml 直配):
- Planner / activity_judge: `dashscope/qwen-turbo`
- Memory summary 折叠:`dashscope/qwen3.5-flash`

**前缀双 path 注意**:Qwen 系列 DB 多用 `openai/`(走 DashScope OpenAI-compat)· yaml 用 `dashscope/`(LiteLLM native)· 同模型两条 routing · `bugfix-3.2.7` 修补遗产。

---

## §16 与归档 DESIGN.md 的指针

本 LITE 涵盖 v4-beta 当前架构的关键点。归档版 `docs/archive/DESIGN.md`(5,206 行,2026-05-19 docs 第二刀冻结)含:

- §三~§十四:v1-v3 完整数据 schema 演进、API 设计、前端组件历史
- §十五之A~W:各架构抽象的详细设计(Capability Registry / 双向 MCP / character_states / proactive / activity timeline / sanitize chain)的完整 motivate + alternatives 否决理由 + 实施细节。**其中 A~T = v1–v3α 架构;U/V/W = v4-alpha 期 UX-005/004/007(注意不是 Persona Engineering)。**
- **§十五之X/Y/Z = v4-beta**:X=Persona Engineering / Y=Observability / Z=v4-beta 收口批次 —— 注:`docs/archive/DESIGN_patch.md` 的 Patch 2/3/5 段从未 merge 入 DESIGN.md,patch 与主档一起冻结归档,内容以本 LITE §6/§7 + DESIGN.md 既有段为准。
- §十六~§二十:测试策略 / 性能 / 平台兼容 / 隐私模型
- 每个 chunk 的 audit 决策记录 / 实测覆盖 / 风险评估

追溯历史决策 / 查 chunk 详细 motivate 前可回查归档版。日常设计真源用本 LITE 即可。

---

## §17 Parked · 规划设计(未实现 · 不算当前架构正文)

> 本区收录**规划级设计**:目标 + 模块拆解 + 关系图。**不锚现役代码**(因为还没写)。
>
> 当前架构正文(§1-§16)必须锚真实代码;本区放未实现 idea 的设计草图。任何 brick 上线时把对应行**转出** → 进 §7.x 当前段 + 用 `file:line` 锚改写。

### 17.1 AI character director(Live2D × emotion × sticker)

**目标**:VTuber 是被人操的;Skyler 要当**操偶人** —— LLM 在 curated 素材库上做导演。同一个 `<emotion>` 信号同时驱动 3 条输出通道,canvas 上的模型 + 聊天流里的图像协同表达。

**输入信号**(已实现):
- 主源:LLM 输出第一句 `<emotion>X</emotion>` 锁定本轮 emotion(sanitize chain 已提取 · 见 §3 数据流图 L121 + §5.6)
- 兼用:`<motion>Y</motion>`(sanitize 已提取但 director 未消费)
- 上下文:`character_states`(mood / attention / 当前 activity)

**三个素材仓库**(规划 · 未实现):

| 仓库 | 内容 | 已有原料 | 缺什么 |
|---|---|---|---|
| **motion bank**(在 Live2D 模型上) | 每角色 N 个 `.motion3.json` · 按 emotion 标 tag | 阿芙洛狄忒 fense 6 motion(jingya/kaixin/shengqi/shuijiao/wink/yaotou) · 冰糖 含一批 motion | tag schema · 选择策略(emotion → 候选 → cooldown / weighted random / 防过密) |
| **expression bank**(在 Live2D 模型上) | 每角色 N 个 `.exp3.json` · 按 emotion 标 tag | 阿芙洛狄忒 fense 5 expression(axy/heilian/kuku/lianhong/shengqi) · 冰糖含 red + shuiyin1/2 等 | 同 motion · 注意 watermark 类 exp(冰糖 shuiyin1/2)标 system-only 不进 director 池 |
| **sticker bank**(在聊天流图通道 · **非模型**) | 每角色 N 张 PNG/WebP · IP-clean 原创 · 按 emotion 标 tag | 暂无 · 设计目标:全角色等量补,自画 / 委托,不抓互联网 | 文件目录约定 · tag metadata · 聊天消息插图协议(WS push) · 每角色 license.txt |

**三条输出通道**:

| 通道 | 渲染层 | 关键差异 |
|---|---|---|
| ① **Live2D motion**(模型上) | canvas 内 pixi-live2d-display(`pixiCubism4.ts`)· SDK `model.motion(group, idx)` 或随机 idle | 模型动起来(挥手 / 摇头 / 翻身) |
| ② **Live2D expression**(模型上) | 同上 · SDK `model.expression(name)` | 模型脸切换(脸红 / 黑脸 / 哭) |
| ③ **sticker**(聊天流插图 · **非模型**) | 聊天气泡渲 `<img>` · WS push `sticker_chosen` 事件 → 前端拉本地图 | 模型完全不动 · 聊天流出一张图 |

**关键设计纪律**:
- ①② 在 **canvas 上的 Live2D 模型**(同一 `pixiCubism4.ts` runtime · 单 hook 接 SDK)
- ③ 是 **聊天流图通道**(完全不动模型 · 类似 IM 发表情包)
- 三者是**并行通道不是叠加** —— 同一 `<emotion>` 信号可同时触发多个 / 也可只触发某一条;director 决策"哪条 + 谁"
- 三仓库共享同一 tag schema(emotion / valence / arousal / cooldown)· 目录/路径/管理 UI 独立
- sticker 必须 **IP-clean 原创**(自画 / 委托;不抓互联网)· license 跟 Live2D 模型同纪律
- director 选择策略不写死:每角色独立 weights · 未来可让 LLM 显式 override(如 `<sticker>name</sticker>` tag)

**当前真实状态(三档诚实分层)**:

| 层 | 状态 | 锚 |
|---|---|---|
| **A · 性能层**(角色"活物"基线) | ✅ ship | §7.6 表演层 c14065b · idle sway BodyAngleY/Z ±1.5° + head-turn focus GAIN ±15° + 眨眼 + 呼吸 + 物理/姿态 SDK 自动 idle |
| **B · `<emotion>` → expression 数据流** | 🟡 已接 · **休眠**(0 视觉) | `Live2DCanvas.tsx:148-167` 数据流接通(sanitize → store.currentEmotion → useEffect → `runtime.setExpression(handle, expressionName)`)· 但 `emotionMap` 默认 `{}`(Hiyori / 八重等),lookup miss → **无 SDK 调用 · 当前 0 视觉变化**。等 brick #2 给具体角色填 `emotion_map_json`(per-character JSON 字段)才点亮 |
| **C · director 决策层** | 📋 parked(未实现) | cooldown / weighted random / 防过密 / 跨仓库三通道协同 · 0 代码 |

**别让"性能层 ship"读成"导演在工作"** — 角色 idle sway + 转头是 SDK 物理 + 鼠标 focus 驱动 · 跟 LLM emotion 信号无关。emotion→expression **管线在但管子空**(无 map · 无视觉)· director **管线本身就没**(无策略)。

**brick 顺序**(emergent 建,详 ROADMAP backlog):

1. **brick #1**(✅ done · §7.6)`pixiCubism4` 表演层 = 性能层 A
2. **brick #2** B 层激活 · 给单角色填 `emotion_map_json` + 试一个有 `.exp3.json` 的模型(阿芙洛狄忒 fense 5 expression:`axy/heilian/kuku/lianhong/shengqi` · 见 `frontend/public/live2d/阿芙洛狄忒/fense/expression/` + `fense.model3.json` FileReferences.Expressions)· 不动 Live2DCanvas 代码 · 数据驱动激活
3. **brick #3** motion bank + 选择策略(C 层起步 · cooldown / weighted / 防过密)
4. **brick #4** sticker bank + 聊天流通道 + tag schema
5. **brick #5** 跨仓库 director(同一 emotion 协同三通道 · 防三通道同时炸)
6. **brick #6** 管理 UI(每仓库 CRUD + tag 编辑 + 预览 + 角色级 weights)

**容器留位 vs 决策层**(诚实分层 · 2026-06-17):

`live2d_settings` JSON 容器(§7.8 framing 同表)预留了 `param_map` / `director` 字段位 · merge 透传不识别。**留位是 ship 的**(framing 走的同表 + 同 PATCH merge 走通)· **决策层是 parked**(B/C 层未实现)。容器位不等于 director 在工作。

**关键路径占位**(实现时改 file:line):
```
brick #2 信号:                后端 ws.py 第一句 <emotion> 已 parse → 推 WS event(已通 · §5.6)
brick #2 数据流:              frontend/src/components/Live2DCanvas.tsx:148-167(已通 · 等 map)
brick #2 激活路径:            character.emotion_map_json(per-character DB 字段 · v3-E2 已加 · 等填)
brick #2 现成弹药:            阿芙洛狄忒 fense 5 expression(axy/heilian/kuku/lianhong/shengqi)
brick #4 协议:                WS 新 event 'sticker_chosen' { url, alt } → 聊天气泡内联渲 <img>
```

---

**文档版本**:LITE 1.2(2026-06-08,进入动画 + 持久角色 + 立绘馆发牌 ship 批次更新 · 新 §11/§12/§13/§14/§15)· LITE 1.1(2026-05-16,v4-beta 收口批次)· **2026-05-19 升为当前设计真源**(docs 第二刀)
**归档版**:`docs/archive/DESIGN.md` 5,206 行 + `docs/archive/DESIGN_patch.md` 477 行(均冻结,不再维护)
