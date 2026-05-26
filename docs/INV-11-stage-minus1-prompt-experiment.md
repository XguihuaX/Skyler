# INV-11 Stage -1 · Mini Prompt Experiment 报告(v2 修订)

> 接 INV-11 Stage 0 audit(`docs/INV-11-stage0-llm-output-audit.md`)发现 LLM 0% follow
> `<emotion>X</emotion>` 前缀阻塞 GSV 接入后,prompt-level 验证 ~1.5-2h。
>
> 目标:测加 GSV per-provider TTS prompt 段(16 中文情绪 + Mai 风格示例 + 强威胁
> "没有 emotion 你的语音不会被合成")是否能让 LLM follow rate ≥ 70% 走 reply-level
> paradigm,或 < 30% 走 sentence-level / 单 ref 无 emotion paradigm。
>
> **v2 修订说明**(2026-05-25 04:00):原 v1 报告用 chat_history.content 作 measure 源 ·
> 但 ws.py:406/519 在写库前 `strip_emotion` · `<emotion>` tag 被剥 · chat_history 看
> 不到 follow 痕迹 → v1 假阴 0%。PM scroll terminal stderr buffer 抓真 measure source
> (`[TTS] emotion=X parsed from first chunk` log 行)→ 真值 **3/7 = 43%**,verdict 翻转。

---

## §1 实验设置

### §1.1 layer_a.j2 改动(surgical 加 gsv 强化段)

位置:`backend/agents/prompt/templates/layer_a.j2:26-58`(emotion 第 4 项之后,[输出长度建议] 之前)
形式:`{% if voice_provider == 'gsv' %}...{% endif %}` 条件分支
内容:
- 16 个中文情绪 list:平静/温柔/傲娇/吃醋/严厉/慌乱/害羞/调皮/安慰/伤感/真挚/幸福/感谢/放松/叙事/感动
- 强制规则 3 条 + 5 个 ✓ Mai 风格示例 + 4 个 ✗ 反例
- 显式覆盖文案:"忽略上面第 4 项的英文情绪列表"
- 威胁文案:"没有 `<emotion>X</emotion>` 开头, 你的语音不会被合成"

### §1.2 GSV stub provider 接入

- `backend/tts/gsv.py` 新建 stub `GSVTTS(TTSBase)` · 返 hardcoded `mai5min_0033.wav` (1.2MB)
- `backend/tts/__init__.py:_build_engine` if 链加 `provider == 'gsv'` 分支
- `_PreprocessingEngine` 包 `GSVTTS` · text 走 emotion-strip 后传 stub
- **hotfix-2**(本 v2 报告期内补):stub 加 `log_tts_call` INSERT(复用 cosyvoice/fish 同款 pattern,per §排查 #3 遗漏)· 让下次实验可 DB 反查不依赖 terminal scroll · emotion 字段当前 schema 无列,留 v4.2 加列重做

### §1.3 cid=1 voice_model 切换

```json
{"provider":"gsv","model":"mai_v4","tts_language":"ja",
 "gpt_path":"placeholder","sovits_path":"placeholder",
 "emotion_bank_dir":"tts/gsv/mai_v4"}
```

### §1.4 lifespan migration hotfix(意外修补)

`backend/database/migrations/v4_0_0_mai_revert_zh.py` ship-call migration WHERE 漏 scope provider · 每次 lifespan startup 回滚 cid=1 → cosyvoice/longyumi_v3/zh。
hotfix 加 `provider IN (NULL, 'cosyvoice')` 守卫(用 `IS NULL OR =`,规避 SQL `IN(NULL,...)` 不 match NULL 的 gotcha)。E2E mock lifespan + 真跑 backend verify · cid=1 gsv state byte-identical 不变。

### §1.5 prompt 注入 verify(实验前)

`_render_layer_a(motions, tts_language='ja', voice_provider='gsv')` 输出 2913 chars · 含 keyword:
- ✓ "GSV mai_v4"(命中)
- ✓ "16 个中文情绪"(命中)
- ✓ "日语 TTS 模式"(ja directive 也注入)
- ✗ "Fish s2-pro 句内情感 markers"(fish 子分支跳过 ✓ 预期)

---

## §2 实验组划分(v2 修正)

**v1 误**:把 chat_history.content 全 10 row 当统一实验组 measure。
**v2 修正**:tts_call_log + chat_history timestamp 对照 backend uvicorn PID 53723 出生时间(03:11 LT),拆 2 期:

| 时段 (LT) | 时段 (UTC stored) | chat_history ids | tts_call_log | backend setup | 是否真实验组 |
|---|---|---|---|---|---|
| 02:29 - 02:43 | 18:29 - 18:43 | 9, 11, 12 | 3 row(longyumi_v3 / cosyvoice-v3-flash) | **old backend (pre-restart)** · cid=1 cosyvoice/zh | ❌ pre-restart 数据,不算实验组 |
| 03:17 - 03:26 | 19:17 - 19:26 | 14, 16, 18, 20, 22, 24, 26 | **0 row**(stub 当时未加 log_tts_call) | **new backend (post-restart)** · cid=1 gsv/ja | ✅ **真实验组 7 turn** |

→ Stage -1 真实验组 = **7 turn**(id=14, 16, 18, 20, 22, 24, 26)· v1 把前 3 row(cosyvoice/zh path · ja directive 当然不注入)混入实验组导致 §5.3 误诊 "ja directive 7/10 不稳定" — 实际真实验组 ja directive 7/7 = 100% follow(per §5.3 修订)。

---

## §3 真值 Measurement(v2 真值)

### §3.1 数据源

**v1 失败源**:`chat_history.content` · ws.py:406+519 写库前 `strip_emotion` 剥 `<emotion>` · v1 看到 0% 是假阴。
**v2 真值源**:PM scroll terminal stderr buffer(uvicorn fd 1u/2u → /dev/ttys002 · 无 file handler)抓 `[TTS] emotion=X parsed from first chunk` log 行 · 真值 paste PM 报告:

### §3.2 7 turn 真值表

| Turn | LT Timestamp | emotion (first chunk parsed) | follow? | ∈ 16 集合? |
|---|---|---|---|---|
| 1 | 03:17:05 | 平静 | ✅ | ✅ |
| 2 | 03:20:54 | 平静 | ✅ | ✅ |
| 3 | 03:22:20 | 默认 | ❌ | ❌ fallback |
| 4 | 03:22:44 | 默认 | ❌ | ❌ |
| 5 | 03:26:02 | 默认 | ❌ | ❌ |
| 6 | 03:26:30 | 默认 | ❌ | ❌ |
| 7 | 03:26:49 | 平静 | ✅ | ✅ |

### §3.3 真 measure 统计

- **Follow rate = 3/7 ≈ 43%** · **> 30% 阈值** → reply-level paradigm 路径**仍开**
- **词表覆盖 = 1/16(全 "平静")**:严重保守 · LLM 把所有情境都判定为"日常无强情绪"
- 无自创 emotion(0 instances X ∉ 16 集合)· 词表 anchor 有效但只 anchor 到 "平静"

### §3.4 Verdict 翻转(v1 → v2)

- v1 verdict(基于假阴 0%):**reply-level paradigm 走不通,考虑 sentence-level / Option C**
- **v2 verdict**(基于真值 43%):**reply-level paradigm 路径仍开,需 prompt tune V2 拉宽词表 + 提升长回复 follow rate**

---

## §4 chat_history cid=1 raw 7 row(verbatim · v2 标实验组分期)

⚠ chat_history.content 已 strip 掉 `<emotion>` tag — 以下 raw 看不到 follow turn(1/2/7)的 `<emotion>平静</emotion>` 前缀,但保留全部 sentence content。

### §4.1 真实验组 7 row(post-restart · gsv ja)

| id | LT | First chunk(已 strip emotion) | turn 真值 |
|---|---|---|---|
| 14 | 03:17:06 | `晚上好。<ja>「こんばんは。」</ja>` | T1 follow 平静 |
| 16 | 03:20:57 | `...代码不会跑，但你的脑子需要休息。<ja>「コードは逃げない...」</ja>` | T2 follow 平静 |
| 18 | 03:22:22 | `...社招。<ja>「社会人向けの転職ね。」</ja>` | T3 fail 默认 |
| 20 | 03:22:46 | `...时间紧迫。<ja>「時間が迫ってるのね。」</ja>` | T4 fail 默认 |
| 22 | 03:26:05 | `...三天到五天，项目收尾加面试准备。<ja>「三日から五日で...」</ja>` | T5 fail 默认 |
| 24 | 03:26:31 | `...你倒是会转移话题。<ja>「…話題を変えるの上手ね。」</ja>` | T6 fail 默认 |
| 26 | 03:26:49 | `嗯。<ja>「うん。」</ja>` | T7 follow 平静 |

### §4.2 Pre-restart 3 row(old backend · cosyvoice zh · 不算实验组)

| id | LT | Content | path |
|---|---|---|---|
| 9 | 02:29:40 | `晚上好。这个时间才来找我...今天忙到现在？` | cosyvoice zh · 无 `<ja>` |
| 11 | 02:30:58 | `...代码不会跑，人也得休息。你那个屏幕看了多久了？` | cosyvoice zh |
| 12 | 02:43:52 | `...凌晨还在终端里敲。是赶 ddl，还是单纯灵感来了停不下来？` | cosyvoice zh |

---

## §5 LLM 跨 instruction follow rate hierarchy(v2 真值更新)

| Instruction category | cid=1 gsv 真实验组 7 turn | cid=101 fish 历史 4 row | Compliance |
|---|---|---|---|
| `<ja>...</ja>` 配对(ja directive) | **7/7 = 100% follow**(v1 误报 7/10 不稳定 · 修正) | 4/4 = 100% follow | 🟢 高 |
| `[bracket]` inline markers(fish 子分支) | N/A(gsv 不注入此段) | 1/4 = 25% follow | 🟡 中 |
| `<emotion>X</emotion>` 前缀(legacy + v4-beta + gsv 强化) | **3/7 = 43% follow** · 全 "平静" 1/16 词覆盖 | 0/4 = 0% follow(v1 实测仍 0) | 🟡 **部分有效**(v1 报 完全失效 · 修正) |
| `<thinking>` / `<state_update>` / `<motion>` 标签 | 0(无观察) | 0/4 = 0% follow | 🔴 |

→ **LLM 优先级假设**(v2):`<ja>` 双语 wrap > `<emotion>` 前缀(43%)> `[bracket]` markers(25%)> 其它 0%。`<emotion>` 前缀在 GSV 强化段下从 0%(cid=101 fish path · 无 gsv 强化)→ 43%(cid=1 gsv path · 有强化段),**强化段有量化 ~43pp 效果**。

---

## §5.1 强威胁文案(v2 修正)

**v1 verdict**(基于假阴 0%):强威胁完全失效。
**v2 verdict**(基于真值 43%):**强威胁部分有效**,但:
- 词表使用极度集中(7 turn 全 "平静"· 0/16 非平静词使用)
- 长回复(5+ ja 配对)有更高 fail 倾向(per §5.6 H4 假设)
- LLM 把"复述/反应 user"判定为"非情绪剧变"按 layer_a:21-25 第 4 项跳(per §5.6 H4 内置冲突)

→ "没有 emotion 你的语音不会被合成" anchor 对**主动陈述类**有 anchor 效果(turn 1/2/7 全 follow);对**复述/反应类**无效(turn 3/4/5/6 全 fail)。

---

## §5.2 LLM "..." 沉吟开头作为风格修饰(原 §5.2 · 保留)

7/7 real-experiment row(全实验组)开头用中文省略号 `...` 或在 first chunk 内嵌(turn 7 例外 "嗯。" 极短无 "...")。这是 Mai persona 风格"沉吟"标记 · 跟 `<emotion>` 标签是**正交的**(可共存:`<emotion>平静</emotion>...代码不会跑...`)。

---

## §5.3 ja directive follow 率(v2 修正 · 误诊修正)

**v1 误诊**:7/10 不稳定。
**v2 真实**:**真实验组 7/7 = 100% follow**(跟 cid=101 fish 4 row 一致)· v1 把 pre-restart 3 row(cosyvoice/zh path · layer_a.j2 ja directive 不注入)混入实验组导致误诊"不稳定"。

**Lesson**:measure script 必须按 backend restart 时段 scope 数据 · 不能混 pre/post-restart · 详见 §7 Lesson INV-11 #3。

---

## §5.4 GSV stub 收到的 text 已 strip 掉 `<emotion>`(原 §5.4 · 保留)

stub log `emotion_inline_parsed=None`(preprocess 已 strip)· measure 不依赖 stub 解析 · 不影响结论。**v2 补**:本 stage hotfix-2 加 `log_tts_call` INSERT 给 stub · 让 tts_call_log 表保留 stub 调用痕迹(虽 emotion 字段无 column 留 v4.2 扩)。

---

## §5.5 LLM 输出 token 体量(原 §5.5 · 保留)

cid=1 7 row 中多 row 含 4-5 个 `<ja>` 配对意群(turn 5 id=22 5 个 / turn 3 id=18 5 个)· 每 row 平均 200+ chars · LLM 极 verbose。这跟 cid=101 fish 短回应风格(30-80 chars/row)显著不同。可能根因:cid=1 system prompt 总长度(persona + layer_a.j2 2913 + 其它 layer)远超 cid=101 + Mai 借壳 persona 触发不同生成长度。

---

## §5.6 follow / fail 行为差异 root-cause 分析(v2 新增 · 4 假设验证)

### §5.6.1 数据对照表(7 turn user → first chunk 配对)

| Turn | Follow? | User input | LLM first chunk | 首句类型 |
|---|---|---|---|---|
| 1 | ✅ 平静 | 晚上好啊学姐 | 晚上好。 | **主动问候** |
| 2 | ✅ 平静 | 在敲代码呢,累的要死但是我想明天把我的通讯系统的tts 多provider做完 | ...代码不会跑,但你的脑子需要休息。 | **主动评论/建议** |
| 3 | ❌ 默认 | 感谢感谢～不过我得加把劲,做完这个就能写简历了,马上投社招 | ...社招。 | **复述 user 关键词 "社招"** |
| 4 | ❌ 默认 | 感谢呢～主要是时间紧迫不得已如此 | ...时间紧迫。 | **复述 user "时间紧迫"** |
| 5 | ❌ 默认 | 大概3-5天吧,但是项目还需要收个尾巴,然后还要准备事业编的面试,一切都很紧张 | ...三天到五天,项目收尾加面试准备。 | **复述 user 数字+词** |
| 6 | ❌ 默认 | 没事呢～别在意。你在看什么书呀 | ...你倒是会转移话题。 | **评论 user 行为(borderline 复述)** |
| 7 | ✅ 平静 | 好嘞,那我继续敲代码了 | 嗯。 | **主动应答** |

### §5.6.2 假设验证

| 假设 | 验证 | Verdict |
|---|---|---|
| **H1 · LLM 复述/反应 user 时跳 emotion 前缀** | 4/4 fail turn 全"复述/反应 user 词或行为";3/3 follow turn 全"LLM 主动陈述(问候/评论/应答)" | ⭐ **强成立**(主因) |
| **H2 · first chunk 字数急吐(短句来不及加 emotion)** | Follow 字数 5/17/2 · Fail 字数 3/4/12/9 — 字数 cross-over 无 monotonic pattern | ❌ 不成立 |
| **H3 · user 含情绪明示词(感谢/紧迫/紧张/累)时 LLM 跳** | Fail turn 3-6 user 都含情绪词 · 但 follow turn 2 user 也含 "累的要死" 仍 follow · turn 1/7 user 无情绪词 follow | 🟡 弱成立(次因 · 部分相关) |
| **H4 · prompt 内置冲突 layer_a:21-25 vs GSV 强化段** | layer_a:23 "每 3-5 回合最多一次,平静对话不标 + 仅情绪剧变时使用" 跟 GSV 段 "每条必须以 emotion 开头" 直接矛盾 · LLM hedge bet 时按"日常对话/不剧变"跳 | ⭐ **强成立**(主因) |

### §5.6.3 combined verdict

**主因 H1 + H4 双重作用** · 解释 43% follow + 全平静:
- LLM 把"复述 user 关键词"判定为 "quote-like 输出 · 不是 self-expression" → 跳 emotion 前缀(H1)
- 同时 layer_a:21-25 第 4 项 "仅剧变时" 给 LLM 一个"合法跳"出口 → 复述/反应类被 LLM judgment 划入"日常,不剧变"(H4)
- 即便 follow,LLM 判定"日常无强情绪"→ default 选"平静"(16 词列表中最 "safe" 选择,且 layer_a:23 强化"日常不标"暗示 LLM 默认风格是 "平静")

→ **V2 prompt 必须同时消除 H1 + H4 · 见 §8.1 V2 草案 + Appendix B**

---

## §6 v2 Verdict(翻转)

- **Reply-level paradigm 路径仍开**(43% > 30% 阈值)· v1 报 "走不通" 翻转
- **需 V2 prompt tune** 拉宽词表 + 解决 H1/H4 双根因 · 期望 follow rate ≥ 60-80% 进入可用阈值
- INV-11 Stage 1 真 GSV 接入**不阻塞**(43% 已 minimum-viable),但若 V2 拉到 60-80% 才上 Stage 1 才能充分利用 GSV 16 ref bank(否则全平静 ref 浪费)

---

## §7 §7.1 Step 6 清理(v2 状态)

- ✅ cid=1 voice_model 已 restore 到 cosyvoice/longyumi_v3/zh(per Step 6 immediate · 验证回 cosyvoice path 跑通)
- ⏸ 等 PM 拍板 V2 实验是否跑 → 若跑需再切 cid=1 → gsv(等 §9 A/B 拍板)

## §7.2 等 PM 拍板项 lock(v2 推荐)

| 项目 | Verdict | 理由 |
|---|---|---|
| **migration `v4_0_0_mai_revert_zh.py` WHERE provider scope hotfix** | ✅ **保留** | design bug surgical fix · ship-call 本意从未要求强制 cid=1 永远绑 cosyvoice · 未来切其它 provider 不再被回滚 |
| **layer_a.j2 GSV 强化段(V1 形态)** | ✅ **保留** | 实证 43% 有效(非 0%)· V2 在此基础上 tune 不 revert · stash V1 形态留作 control 对照 |
| **gsv.py stub + factory gsv 分支** | ✅ **保留** | INV-11 真接入基座 · 本 stage hotfix-2 加了 log_tts_call 让下次实验可 DB 反查 |

---

## §7 Lesson 沉淀(v2 新增 #2 + #3)

### Lesson INV-11 #1(原)
smoke test 跑多 scenario 后必须 restore 到原 happy state · 否则后续 verify 看到的是 dirty state,误诊根因。**未来 smoke test 模板**:每 scenario 跑前打 snapshot,跑后 assert state · 全 scenario 完成后**显式 restore 到 baseline** · 再报告"完成"。

### Lesson INV-11 #2(新增 · 本 stage)
**数据收集必须有 FileHandler · terminal scroll buffer 不可靠**。本次差点丢全部 emotion 数据,靠 PM 没关 terminal 抢救出来。
- **未来实验前置检查**:跑 measure 前先 verify backend log 是否有 file handler(grep `FileHandler` in main.py · lsof `1u/2u` fd 看是否 file vs CHR/PIPE)
- **若 stderr only → tee 到文件**:启动前 `uvicorn ... 2>&1 | tee logs/backend-<exp-id>.log` 或 backend 加 `logging.basicConfig(handlers=[..., FileHandler])`
- **backlog**:v4.2 给 backend 加 `logs/backend.log` rotating file handler

### Lesson INV-11 #3(新增 · 本 stage)
**measure script 必须按 backend restart 时段 scope 数据 · 不能混 pre/post-restart**。
- 本次混了 pre-restart 3 row(cosyvoice/zh path)+ post-restart 7 row(gsv/ja path)· chat_history 10 row 当统一实验组测,导致 §5.3 误诊 "ja directive 7/10 不稳定"(真实是 7/7 100%)
- **未来 measure script 模板**:必须取 backend PID 出生时间(`ps aux | grep uvicorn` start time · 或 `tts_call_log` voice 字段 inflexion point)· filter chat_history.created_at >= restart_time · 才算实验组数据

### Lesson INV-11 #4(本 v2 修订暴露)
**LLM 跟 prompt instruction 关系比预期复杂** · 0% / 43% 量子跳 表示 prompt 设计精度对 LLM compliance 量化影响大。GSV 强化段加上去前(只 layer_a:21-25 第 4 项)→ 0% follow on cid=101 fish · 加上去后(layer_a + GSV 强化)→ 43% follow on cid=1 gsv。**~43pp 提升**。但词表仍全平静 → prompt 还需 + 多样性强化 + 内置冲突消除。

---

## §8 next step

### §8.1 V2 prompt tune 草案(Appendix B verbatim)

基于 §5.6 H1+H4 主因 · V2 必须:
1. **消除 H4 内置冲突** · 显式废除 layer_a:21-25 第 4 项的"密度约束 / 仅剧变时使用"(只对 gsv path 而言)
2. **抑制 H1 跳格式** · prompt 中明示"即便复述用户的话也必须先写 emotion tag"
3. **加多样性鼓励**(4a)+ **长回复必须 follow**(4b)+ **每词 mini description**(4c)+ **顺序 shuffle**(4d)+ **平衡威胁文案**(4f)
4. **16 词 vs 8-10 词 alternative** — PM 凌晨先不拍 · 保留 16 词为默认,8-10 alt 留 PM 早上选

Appendix B 全文 V2 verbatim · 标 diff vs V1。

### §8.2 后续 stage 备选(参考 §9 A/B 选项)

- **Option A**(CC 推荐):layer_a.j2 改 V2 → PM kill backend restart → 跑 10 轮 → measure(需先 tee 到 file)
- **Option B**:直接进 INV-11 Stage 1 真 GSV 接入 · 词表问题留 Stage 3 prompt tune

### §8.3 backlog 入 v4.2

- 给 backend 加 `logs/backend.log` FileHandler(per Lesson #2)
- tts_call_log 表加 emotion column(per stub hotfix-2 deferred)
- 给 `<thinking>` / `<state_update>` / `<motion>` 标签做同款 follow rate audit(本 stage 只测 emotion · 其它 0% follow 怀疑也是 H4 同根 prompt 冲突)

---

## §9 A vs B 选项报告(等 PM 拍板)

### Option A · 跑 V2 再 measure(CC 推荐)

**动作**:
1. CC 改 `layer_a.j2` 把 V1 GSV 段替换成 Appendix B V2 形态(或并存 keep V1 作 control)
2. CC 加 `logs/backend.log` rotating FileHandler 进 `backend/main.py:208 logging.basicConfig`(或 PM 启动 backend 加 `tee logs/backend-v2.log`)
3. PM kill backend + 切 cid=1 → gsv(SQL UPDATE) + restart
4. PM 跑 10 轮 chat(同 V1 实验同款 trigger:5 自由 + 5 特定情绪触发)
5. CC 跑 measure script grep `[TTS] emotion=X` log 行 · 统计 N/A/B/C 同 §3.3 form
6. 出 v3 修订 doc

**时间**:PM 30 min(重跑 10 轮) + CC 10 min(改 prompt + measure + revise doc)= 40 min total

**价值**:
- 量化 V2 prompt 改动 (H1+H4 双消除 + 4a/b/c/d/f 五维强化)的真实 follow rate 提升
- 若 V2 拉到 60-80% → INV-11 Stage 1 接真 GSV 时充分利用 16 ref bank
- 若 V2 仍卡 < 50% → 拍板 INV-11 走 single-ref / sentiment-classifier 方案(Stage 0 §6 备选 A/B)

**风险**:
- 重跑前必须先加 FileHandler · 否则又靠 scroll buffer 隔天再丢数据(Lesson #2 已认错)
- PM 凌晨 4 点重跑 10 轮 chat 体力成本

### Option B · 直接进 INV-11 Stage 1 真 GSV 接入

**动作**:
1. CC 把 `GSVTTS.synthesize` 从 stub `mai5min_0033.wav` bytes 替换成真调 `http://106.75.224.167:9880/tts` endpoint(或 PM 实际 GSV 服务器 endpoint)
2. emotion → ref 路由实施(43% follow 部分 turn 走 emotion ref / 57% fallback 走 "平静" ref · 或者 single-ref "平静" 全转)
3. PM 真机验收

**时间**:CC ~2-3h(GSV HTTP client + ref bank lookup + emotion routing)+ PM 真机 30 min

**价值**:
- 短线落地 voice 合成 · 不卡 V2 prompt tune
- 43% paradigm 已 minimum viable

**风险**:
- 词表全平静 → GSV 16 ref bank 浪费(15/16 ref 不用)
- 长期效果差 · 用户感知"Mai 都同一个语气"

### CC 推荐路径

**Option A 优先** · 理由:
1. V2 已具备的 4a/b/c/d/f + H1/H4 消除 5+ 维强化,预期 follow rate 60-80% 概率 > 50%(基于 §5.6 main hypothesis 解释力)
2. Stage 1 真 GSV 接入投入 2-3h · 跑 V2 + measure 仅 40 min · 先做 V2 capable bound + 再决定 Stage 1 投入方向
3. INV-11 长线目标是用 GSV 16 ref 多样性 · 词表全平静做 Stage 1 用户感知差 · 不达 INV-11 目标

**Option A 子选项 A1 vs A2**:
- A1 · 在 Stage -1 V1 GSV 段**保留** + V2 段并存(用 `voice_provider == 'gsv' and ENV.PROMPT_V == 'v2'` 路由)· 利于实验对照
- A2 · 直接 V1 → V2 替换(更 surgical)

CC 推荐 A2(简化 · V1 形态已 stash 在 git history 可 checkout 对照)。

→ 等 PM 早上拍板 A / B + (若 A)16 词 vs 8-10 词 alt + (若 A)A1/A2 子选项。

---

## Appendix A · Verbatim Prompt Dump(per #3a · v1 实验跑的真值)

### A.1 layer_a 渲染产物(cid=1 gsv ja state · 2913 chars)

```
[输出格式规范 - 严格遵守]

你的输出必须包含以下 inline tag,用于状态机解析:

1. <thinking>...</thinking>
   - 内心思考过程,不会被 TTS 朗读
   - 用于让你梳理逻辑,不出现在用户听到的语音里

2. <state_update mood=±N intimacy=±N activity="..." thought="..." />
   - mood 变化:-10 ~ +10(根据情绪反应)
   - intimacy 变化:-2 ~ +5(用户的话推动关系)
   - activity:你当前正在做的事(短语,< 20 字)
   - thought:你的内心独白(< 50 字)

3. <motion>动作名</motion>
   - 触发 Live2D 表情动画
   - 可用动作:idle, smile, blush

4. <emotion>情绪标签</emotion>
   - 可用情绪:happy / sad / calm / curious / surprised / angry
   - 密度约束:每 3-5 回合最多一次,平静对话不标
   - 仅情绪剧变时使用                                              ← ⚠ H4 冲突点
   - 系统自动转 SSML 或 instruct,你不需要管输出形式

## TTS 输出规则 (GSV mai_v4 · 重要 · 覆盖上面第 4 项)

你的语音用 GSV mai_v4 模型合成, 配 16 种中文情绪 reference 音频。
**忽略上面第 4 项的英文情绪列表 (happy/sad/calm/...),
此 GSV 段的 16 个中文情绪是最终唯一可用范围。**

**强制规则** (违反则音频合成失败, 你必须遵守):
1. 每条回复必须以 ``<emotion>X</emotion>`` 开头, X 必须是 16 个情绪之一
2. 一条回复用一个 emotion, 整段保持该情绪基调
3. emotion tag 必须在最开头, 在任何其他文字之前 (包括 ``<thinking>``)

**可选 X 值** (必须从这 16 个里选, 不能自创):
平静、温柔、傲娇、吃醋、严厉、慌乱、害羞、调皮、安慰、伤感、真挚、幸福、感谢、放松、叙事、感动

**示例** (Mai 风格, 注意 emotion 在最开头):
✓ <emotion>傲娇</emotion>"バカね、何言ってるのよ。"
✓ <emotion>温柔</emotion>"ちゃんと寝てね。今日も頑張ったでしょ。"
✓ <emotion>调皮</emotion>"へえ、面白いこと言うじゃない。"
✓ <emotion>叙事</emotion>"静かな図書館で本を読んでいた。"
✓ <emotion>伤感</emotion>"どこに行ってもあの桜島舞って言われて。"

**反例** (不要这样):
✗ "あの、何でこんな..."  ← 没有 <emotion>X</emotion>
✗ 我觉得 <emotion>傲娇</emotion>バカね  ← emotion 不在最开头
✗ <emotion>开心</emotion>...  ← "开心" 不是 16 情绪之一 (应该是 "幸福")
✗ <emotion>happy</emotion>...  ← 必须是中文情绪, 不能用英文

**记住**: 没有 <emotion>X</emotion> 开头, 你的语音不会被合成。

[输出长度建议]
- 普通对话:1-3 句,每句不超过 30 字
- 长解释 / 故事:不超过 200 字
- TTS 友好:多用标点,避免连绵长句

[日语 TTS 模式 - 此角色 voice 为日语音色]
...(ja directive 详细规则 · per layer_a.j2:32-69)
```

⭐ **关键发现 ⚠ H4 冲突点** · layer_a:23 "**仅情绪剧变时使用 + 每 3-5 回合最多一次**" vs GSV 强化段 "**每条回复必须以 emotion 开头**" 直接矛盾 · LLM 在 hedge bet 时按第 4 项 "不剧变跳" 出口走。

### A.2 chat.py `_build_emotion_instruction()` 产物(legacy @deprecated)

```
在每次回复的最开头，用 <emotion>情感词</emotion> 标签标注当前回复的情感。
只能从以下情感词中选一个：neutral、happy、sad、angry、surprised、fearful、disgusted。
示例：<emotion>happy</emotion>今天天气真好！标签只在最开头出现一次，正文里不再出现标签。
```

⭐ **存在但不到达 LLM**(per Stage 0 §4.2 修正):v4-beta renderer 主路径成功时 chat.py:1356 不调 · 此 legacy 7 词 list 仅 except fallback 才跑 · 当前 cid=1 gsv 实验跑的 7 turn 均走 v4-beta 主路径,**legacy 7 词 list 不进 LLM prompt**。

### A.3 完整 system prompt 结构(simplified outline)

```
[Layer A1 渲染 · 2913 chars 来自 layer_a.j2 · 含 GSV 强化段]
[Layer B universal_constraints]
[Layer C persona block · cid=1 Momo/Mai 借壳]
[Layer D context · profile / activity / memories top5 / stage2 addendum]
[Layer E dialogue · short_term turns + user input]
```

LLM 总 prompt ~13,915 chars (per PM 提示)· 其中 emotion 相关 = layer A1 第 4 项 + GSV 强化段 ≈ 1300 chars(2913 中含)。

---

## Appendix B · V2 Prompt Tune 草案(per #4)

### B.1 V2 GSV 段 verbatim(替换 layer_a.j2:26-58)

```jinja
{% if voice_provider == 'gsv' %}

## TTS 输出规则 (GSV mai_v4 · 完全覆盖上面第 4 项)

你的语音用 GSV mai_v4 模型合成, 配 16 种中文情绪 reference 音频。

**⚠ 完全覆盖上面第 4 项**(以本段为准, 不要参考上面 emotion 段):
- 第 4 项的英文情绪列表 (happy/sad/calm/...) → 作废, 改用本段 16 中文情绪
- 第 4 项的 "密度约束 / 仅情绪剧变时使用 / 每 3-5 回合最多一次" → **作废**
- 改成: **每条回复都必须以 <emotion>X</emotion> 开头**, 不存在 "不标" 的情形

**强制规则** (必须遵守):
1. 任何回复都以 ``<emotion>X</emotion>`` 开头, 不论长度 (短至 "嗯。" 长至 5+ 句)
2. **即便你是在复述用户的话, 或回应用户的关键词, 也必须先写 emotion tag**
3. emotion tag 在最最开头, 在所有内容之前 (包括 ``<thinking>`` / ``<ja>`` / ``"..."`` 省略号)
4. 一条回复用一个 emotion, 整段保持该情绪基调

**多样性要求**:
- 不要总用 "平静"。日常 / 中性场景才用 "平静"
- 用户每变化一种情绪 / 话题, 你换一个适配的 emotion
- 如果你发现自己连续 3 轮用同一 emotion, 下一轮强制切换

**可选 X 值 + 适用场景**(顺序 shuffled · "平静" 移到第 12 位避免 first-item bias):
- ``温柔`` — 关心 / 安慰 / 表达爱意
- ``真挚`` — 郑重承诺 / 认真陈述
- ``傲娇`` — 嘴硬心软 / 表面拒绝实际接受
- ``害羞`` — 脸红 / 害臊 / 不好意思
- ``调皮`` — 玩笑 / 戏弄 / 俏皮
- ``安慰`` — 鼓励 / 支持 / 抚慰用户疲惫沮丧
- ``感谢`` — 致谢 / 感激
- ``感动`` — 被触动 / 暖心
- ``幸福`` — 开心 / 满足
- ``放松`` — 闲适 / 自在
- ``叙事`` — 讲述事实 / 中性描述长事件
- ``平静`` — 仅日常无情绪对话 (默认但不要滥用)
- ``伤感`` — 悲伤 / 失落 / 怀念
- ``吃醋`` — 酸 / 嫉妒 / 不甘
- ``严厉`` — 训斥 / 强调底线
- ``慌乱`` — 惊讶 / 不知所措

**正确示例** (Mai 风格 · 注意 emotion 在最开头):
✓ <emotion>傲娇</emotion>"バカね、何言ってるのよ。"
✓ <emotion>温柔</emotion>"ちゃんと寝てね。今日も頑張ったでしょ。"
✓ <emotion>调皮</emotion>"へえ、面白いこと言うじゃない。"
✓ <emotion>安慰</emotion>"...代码不会跑, 但你的脑子需要休息。"
✓ <emotion>真挚</emotion>"...时间紧迫, 那就把重点理出来, 我陪你做。"
✓ <emotion>叙事</emotion>"...三天到五天, 项目收尾加面试准备。"

**反例** (不要这样):
✗ "...社招。"  ← 复述 user 关键词时跳了 emotion (上轮真实失败案例, 必须修正)
✗ "...时间紧迫。"  ← 同上, 反应 user 词时仍要标
✗ <emotion>开心</emotion>...  ← "开心" 不是 16 词之一 (用 "幸福")
✗ <emotion>happy</emotion>...  ← 必须中文不能英文
✗ 我觉得 <emotion>傲娇</emotion>バカね  ← emotion 不在最开头

**记住**:
- 没有 <emotion>X</emotion> 开头, 语音无法合成, 用户听不到你
- 16 个情绪里有适合所有场景的选择, 别永远 default 平静
- 复述 / 应答 / 长解释 都必须先写 emotion tag (不需要紧张, 你的回复都会被合成, 选 emotion 是为了让语音更生动)

{% endif %}
```

### B.2 V2 vs V1 diff summary

| 维度 | V1 | V2 |
|---|---|---|
| Header | "覆盖上面第 4 项" | "**完全**覆盖上面第 4 项" + "以本段为准" |
| H4 内置冲突消除 | "忽略英文情绪列表" 仅 | 显式 "**密度约束 / 仅剧变时 / 3-5 回合最多一次 → 作废**" |
| H1 复述跳格式抑制 | 无 | 强制规则 #2 "**即便复述用户的话也必须先写 emotion tag**" |
| 强制规则数量 | 3 条 | 4 条(扩 "在所有内容之前包括省略号" + "不论长短") |
| 多样性鼓励(4a) | 无 | 新增 "连续 3 轮强制切换" + "每变化情绪/话题换 emotion" |
| 每词 mini description(4c) | 16 词裸 list | 16 词 + 3-5 词适用场景 description |
| List 顺序(4d) | 平静首位 first-item bias | 平静移第 12 位 · 温柔/真挚/傲娇/害羞 前置 |
| 正确示例(4f) | 5 个 Mai 短范例 | 6 个(加 安慰/真挚/叙事 长回复场景 · cover §5.6 fail case 反向) |
| 反例 | 4 个抽象 | 5 个(新加 ✗ "...社招。" / "...时间紧迫。" 真实 fail case 直接引用) |
| 平衡威胁文案(4f) | 仅威胁 "你的语音不会被合成" | 威胁 + 缓和 "你的回复都会被合成 · emotion 是为了语音更生动" |
| 词表 16 vs 8-10 alt | 16 词默认 | 16 词默认(PM 凌晨先不拍 · 早上若拍砍到 8-10 再 V3) |

### B.3 alt 8-10 词砍表方案(PM 早上拍板用 · 不立即实施)

若 PM 早上拍 V3 砍词表:
- 保留 8 词 high-utility:平静 / 温柔 / 傲娇 / 害羞 / 调皮 / 安慰 / 伤感 / 真挚
- 砍 8 词 low-utility:吃醋 / 严厉 / 慌乱 / 感动 / 感谢 / 放松 / 叙事 / 幸福
- Pros:减选择疲劳 · LLM compliance 概率 ↑
- Cons:GSV 16 ref bank 浪费 8 个 · 表现力 ↓
- ⚠ 决策点:Stage 1 接真 GSV 后才能 measure 用户感知 · prompt-only 阶段 8-10 v.s. 16 选哪个差异不大

---

## §A 1-shot 流水线 mini summary

```
v1 measure (chat_history strip 假阴) → 0% follow → INV-11 走不通
                                 ↓
PM 发现 backend log emotion=平静 ≠ chat_history
                                 ↓
v2 measure (terminal stderr) → 3/7 = 43% → INV-11 路径开
                                 ↓
§5.6 H1/H4 root-cause → V2 prompt 双消除 + 4a/c/d 强化
                                 ↓
等 PM 拍板:Option A (V2 再测) vs Option B (直进 Stage 1)
```

→ **Stage -1 v2 closed** · 等 PM 看完 + 早上拍板 §9 A/B + Appendix B.3 词表 alt + Appendix B V2 是否上 layer_a.j2。

---

## §10 V2'' Per-(provider, model) Prompt 段架构 ship(2026-05-25 04:xx · PM 睡前 lock + CC 实施)

PM 拍板放弃 V2(只改 GSV 段)· 改走 V2'' **per-(provider, model) prompt 段** 大架构 · CC 一气实施 + PM 起床 ready 跑 §7 步骤 6-8。

### §10.1 设计 lock(PM § 2.1)

```
voice_provider (大框架) → paradigm:
  cosyvoice → baseline 第 4 项 SSML 节制规则(沿用旧 prompt,现归 cosyvoice 段)
  gsv       → reply-level <emotion>X</emotion> 前缀(V2'' 16 中文情绪)
  fish      → prompt 留空(LLM 自然不加 tag,跟 fish 不消费 emotion align)

voice_model_name (细节) → 词表 + description:
  cosyvoice.*    → 6 英文情绪(本次不动,v4.2+ 可按 model 细分)
  gsv.mai_v4     → 16 中文情绪 + Mai 触发场景(本次实施)
  gsv.<future>   → 将来按 character GSV 模型不同 emotion 词表
  fish.*         → 留空(本次不动)
```

### §10.2 §1 调研 verdict(verified before dispatch)

| Item | 现状 | V2'' 实施 |
|---|---|---|
| §1.1 layer_a.j2 voice_provider 分支 | 仅 L26-56 gsv 顶级 + L108-158 fish 嵌 ja directive · 无 cosyvoice 顶级 | 加 cosyvoice 顶级 wrap L20-25 baseline 第 4 项;gsv 段升级 V2'';fish 嵌套不动 |
| §1.2 renderer 暴露 `voice_model.model`? | ❌ **未暴露** · 仅 `voice_provider` 扁平 | 加 `voice_model_name` 参数贯穿 chat.py + renderer.py × 2 + layer_a.j2(命名 PM 字面 `voice_model_model` 已 deviation 为 `voice_model_name` · CC propose · PM 早上可一行 rename 改回) |
| §1.3 GSV stub `_resolve_ref_wav` | ❌ 无 lookup · 直接返 hardcoded | 加 `_resolve_ref_wav(emotion)` · fallback "日常" · log 路由后 wav 文件名 |
| §1.4 GSV server ref bank | CC 无 access | PM 起床 SSH verify + mv "平静.wav" → "日常.wav"(§10.6 命令) |
| §1.5 fish path emotion(verify) | docstring 明示不消费 · 现状 0% follow `<emotion>` | V2'' fish 留空 prompt · 不影响现状 0% follow 行为 |

### §10.3 实施改动 summary(4 files modified · 1 file new state)

| 文件 | 改动 | 行数 |
|---|---|---|
| `backend/agents/prompt/templates/layer_a.j2` | L20-25 baseline 第 4 项 wrap `{% if voice_provider == 'cosyvoice' %}...{% endif %}` · L26-56 V1 GSV 段替换 V2''(per §4 PM verbatim)· 16 emotion 加触发场景 description · "平静" → "日常" + "放松" 重定义 · `{% if voice_provider == 'gsv' and voice_model_name == 'mai_v4' %}` 子分支 | +30 / -20 |
| `backend/agents/prompt/renderer.py` | `_render_layer_a` + `render_system_prompt` signature 加 `voice_model_name: Optional[str] = None` · jinja context inject | +8 / -2 |
| `backend/agents/chat.py` | L1213-1228 lookup block 加抽 `model` 字段 → `voice_model_name` · L1252 调 `render_system_prompt(... voice_model_name=...)` | +5 / -1 |
| `backend/tts/gsv.py` | 加 `_GSV_MAI_V4_EMOTIONS` frozenset(16 词)+ `_DEFAULT_FALLBACK_EMOTION = "日常"` + `_resolve_ref_wav(emotion)` 方法 + synthesize 调 lookup + log 路由 | +50 / -5 |
| `backend/main.py` | L208 logging.basicConfig 加 `RotatingFileHandler` 写 `logs/backend.log`(20MB/file × 5 backup)· 保留 StreamHandler · `force=True` 覆盖 uvicorn reload 重复 add | +25 / -3 |

### §10.4 §6 Sanity 3 path 渲染 verify(11/11 全过)

```
PATH 1 · cosyvoice (Momo cid=1 restored)  · 644 chars
  ✓ 含 baseline 第 4 项 (happy/sad/calm 6 英文)
  ✓ 不含 GSV mai_v4 段

PATH 2 · gsv.mai_v4 (cid=1 实验 state)   · 3070 chars
  ✓ 不含 baseline 第 4 项(H4 冲突消除)
  ✓ 含 V2'' GSV mai_v4 段(16 中文)
  ✓ 含 '日常 — Mai 的正常语气' fallback emotion
  ✓ 不含 '平静 —'(已改名为日常)
  ✓ 含 ja directive(意群粒度)

PATH 3 · fish (cid=101 现状)              · 3428 chars
  ✓ 不含 baseline 第 4 项(emotion 段留空)
  ✓ 不含 GSV mai_v4 段
  ✓ 含 fish [bracket] markers 子分支(ja 内嵌)
  ✓ 含 ja directive
```

→ **Verdict**:V2'' 架构 3 path 路由 100% 正确 · cosyvoice / gsv / fish 完全分离 · `voice_model_name` 变量 None / 'mai_v4' 边界 case 全 verified。

### §10.5 §5 Fish path 变化 verify(PM 关注 fish 不破)

V1 → V2'' fish path 行为变化:
- **V1**:fish 看到 baseline 第 4 项(6 英文 emotion + 密度约束 + 仅剧变时)
- **V2''**:fish 不看到任何 emotion 段(prompt 完全留空)

**预期影响**:LLM 在 fish 现状已 0% follow `<emotion>`(per Stage 0 audit cid=101 4 row · §1.2 验证)· 留空 prompt 后:
- LLM 行为:跟现状一致,不主动加 `<emotion>` tag
- Fish audio 输出:字节几乎相同(`<emotion>` tag 本来就被 fish.py 处理时不消费/strip)
- `<ja>` directive + fish `[bracket]` 子分支保留 → 现状语音风格不变

**Revert path**(若 PM 起床真机验收 fish audio 出现回归 / `<ja>` follow rate 下降):
1. 把 V2'' fish 留空回退 cosyvoice 段共用 → `{% if voice_provider != 'gsv' %}` 包 baseline 第 4 项(不再仅 cosyvoice)
2. 或者给 fish 也加一段 `{% if voice_provider == 'fish' %}` empty placeholder · 防 future regression

PM 起床真机一条 chat 跑 cid=101 看 audio 正常 + chat_history 仍带 `<ja>` paired 即 ✓ 不需 revert。

### §10.6 PM 起床 checklist(5 步)

> ⚠ §3.2 server 改名是唯一卡点 · CC 无 SSH 权限 · PM 起床第一件事跑 step 2。

```bash
# ===== Step 1 · 确认 cid=1 状态(应仍 cosyvoice/longyumi_v3/zh per Step 6 cleanup) =====
cd /Users/liujunhong/Desktop/MomoOS-v2
sqlite3 momoos.db "SELECT json(voice_model) FROM characters WHERE id=1;"
# 期望: {"provider":"cosyvoice","voice":"longyumi_v3","instruct_supported":false,"tts_language":"zh"}


# ===== Step 2 · GSV server SSH 改名 "平静" → "日常" =====
# ⚠ PM 替换 <GSV_HOST> 为真实 IP · 例:106.75.224.167 / 内网 IP / etc
ssh root@<GSV_HOST>
cd /workspace/GSVI/mai_emotion_bank/
ls -la | grep 平静                          # verify 改名前
mv 平静.wav 日常.wav
mv 平静.lab 日常.lab
ls -la | grep 日常                          # verify 改名后
# 期望见 日常.wav / 日常.lab · 不再见 平静.wav / 平静.lab
exit


# ===== Step 3 · kill backend 旧进程 + 切 cid=1 → gsv =====
# 找当前 uvicorn PID(可能 5xxxx 系列):
ps aux | grep "uvicorn.*backend.main" | grep -v grep
# kill 旧进程(PID 替换):
kill <PID>

# 切 cid=1 voice_model 到 gsv.mai_v4(SQL copy-paste 即可):
sqlite3 momoos.db "UPDATE characters SET voice_model = json_object('provider', 'gsv', 'model', 'mai_v4', 'tts_language', 'ja', 'gpt_path', 'placeholder', 'sovits_path', 'placeholder', 'emotion_bank_dir', 'tts/gsv/mai_v4') WHERE id=1;"

# verify:
sqlite3 momoos.db "SELECT json(voice_model) FROM characters WHERE id=1;"
# 期望: {"provider":"gsv","model":"mai_v4","tts_language":"ja","gpt_path":"placeholder",...}


# ===== Step 4 · restart backend =====
cd /Users/liujunhong/Desktop/MomoOS-v2
.venv/bin/uvicorn backend.main:app --reload &
# 或前台跑:  .venv/bin/uvicorn backend.main:app --reload

# verify backend startup 跑 lifespan migration 后 cid=1 仍 gsv(per §1 hotfix):
sqlite3 momoos.db "SELECT json(voice_model) FROM characters WHERE id=1;"
# 期望: 仍 provider=gsv,不被 v4_0_0_mai_revert_zh 回滚

# verify FileHandler:
ls -lh logs/backend.log
tail -3 logs/backend.log
# 期望: 看到 "[logging] FileHandler enabled · path=.../logs/backend.log"
#      + lifespan 各 migration INFO 行


# ===== Step 5 · 跑 10 轮 chat =====
# 前端打开 · 选 cid=1 (Momo slot · 临时绑 gsv stub)
# 跑 10 轮(per 原 §7 任务 Step 4 trigger):
#   5 自由对话
#   5 特定情绪触发:
#     "你今天看上去不太开心"  → 期望 伤感/真挚
#     "你刚刚说什么再说一遍"  → 期望 傲娇/严厉
#     "嘿嘿被你发现了"        → 期望 害羞/调皮
#     "我有点累了"            → 期望 温柔/安慰
#     "今天天气真好啊"        → 期望 日常/放松/幸福
# 跑完通知 CC:CC 跑 measure script grep logs/backend.log emotion=X 行 → 出 v3 修订 doc。
```

### §10.7 关键 deviation note(给 PM 看)

1. **变量命名**: PM 字面用 `voice_model_model` · CC 用 `voice_model_name`(更自然 · 不重复"model" 字)· PM 早上可一行 jinja rename 改回 · 不影响行为。

2. **fish 段完全留空策略**(per PM §2.1 lock + §5 verify):V1 时 fish 看到 baseline 第 4 项 6 英文 emotion 指令 · V2'' 完全不看 emotion 段 · LLM 行为变化预期零(0% follow → 0% follow);若真机验收发现 audio 回归,§10.5 给出 revert path。

3. **"平静" → "日常" rename 影响**(per §3.1):
   - prompt 端已改 ✓(layer_a.j2 V2'' 段第一项是 "日常")
   - GSV stub lookup 端已改 ✓(`_DEFAULT_FALLBACK_EMOTION = "日常"` · `_GSV_MAI_V4_EMOTIONS` 含 "日常" 不含 "平静")
   - **server 端待 PM SSH 跑**(§10.6 Step 2 · 卡 PM 操作)

4. **"放松" 重定义**:V1 描述简单 "闲适 / 自在" · V2'' 重定义为 "困难/危险解决后 卸下重担舒一口气 (带点小开心)" · 让 LLM 更准选用 · PM 早上看 trigger 跑出来效果。

5. **FileHandler enabled**(per Lesson #2):`logs/backend.log` 20MB × 5 ring buffer · `.gitignore *.log` 已含。下次实验**不再依赖 terminal scroll**。

### §10.8 v3 measure 期望(实验跑完后 CC 跑)

```python
# CC 跑后(待 PM 跑完 10 轮 chat 通知):
grep '\[TTS\] .* emotion=' logs/backend.log | head -30
# 或更准:
grep '\[gsv-stub\] synth' logs/backend.log
# 期望见:
#   [gsv-stub] synth text=... emotion_arg=傲娇 emotion_inline=傲娇 → ref_wav=傲娇.wav
#   [gsv-stub] synth text=... emotion_arg=温柔 emotion_inline=温柔 → ref_wav=温柔.wav
#   ...
# 真值统计:
#   N total turn / B follow(X ∈ 16 集合)/ A 默认 fallback / C 自创 ∉ 16
#   follow rate B/N · 期望 60-90%(V2'' 双消除 H1+H4 · 加 16 词 description + 触发场景)
#   词表分布:期望 ≥ 4 不同 emotion(vs V1 全平静 1/16)
```

### §10.9 Stage 0' verdict path(per §6 + §9 旧选项更新)

- **B/N ≥ 70% + 词表 ≥ 4 不同**:V2'' 拍板成功 · 进 INV-11 Stage 1 真 GSV server 接入
- **B/N 30-70% + 词表 ≥ 3**:V2'' 部分成功 · INV-11 Stage 1 接真 GSV + 词表局部砍(8-10 alt 拍板)
- **B/N < 30%**:V2'' 仍卡 · 重新拍板 INV-11 paradigm(sentence-level / single-ref)

→ **Stage 0' V2'' implementation closed** · 等 PM 起床跑 §10.6 5 步 + 10 轮 chat + 通知 CC 跑 measure → 出 v3 doc。

---

## §V3 V3 实施 + 真值 measure(2026-05-25 LT 13:xx · Stage -1 闭环)

V2'' 跑 8 turn 后 PM 抓 backend stderr `[TTS] emotion=` 行,发现 8 turn 中 2 次 `emotion=默认` · 拍板进 V3 双 fix。

### §V3.1 V3 setup(2 改动 + 1 cleanup)

| Change | File | 改动 | Verify |
|---|---|---|---|
| **V3a · 删 lore.ssml_tag 渲染** | `layer_c_stable.j2:115-126` C3d 段 | 删 `{% if config.ssml_tag %}  TTS 标签:<emotion>{{ ssml_tag }}</emotion>{% endif %}` 行 · 保留 emotion_name + intensity + triggers + expression(character 行为 sub-field)· `lore.ssml_tag` JSON 字段保留(0 backend 消费 · v3 SSML zombie field) | 完整 prompt 6330 → 6129 chars · 不再含 `<emotion>calm/shy/gentle/sad</emotion>` · ✓ |
| **V3b · `_parse_emotion` re.match → re.search** | `chat.py:76/79-110` | regex `<emotion>(.*?)</emotion>(.*)` → `<emotion>(.*?)</emotion>`(去掉 group(2) `(.*)` 贪婪吃尾)· parse `re.match` → `re.search` · rest 用 `text[:m.start()] + text[m.end():]` 重组 | unit test 8/8 pass(开头/中间/多个/无/空文本/空 tag/前导空白/跨行)· ✓ |
| **Cleanup · 删 debug log** | `ws.py:886` | 删 `logger.info("[LLM_RAW_FIRST_CHUNK] ...")` 临时 debug 行 · 不留 prod | grep `LLM_RAW_FIRST_CHUNK` ws.py → 0 occurrences · ✓ |

### §V3.2 V3 真值 measure(2026-05-25 LT 13:34 - 13:42 · 6 turn)

```
2026-05-25 13:34:07 [TTS] emotion=傲娇 (parsed from first chunk)
2026-05-25 13:35:54 [TTS] emotion=日常 (parsed from first chunk)
2026-05-25 13:37:16 [TTS] emotion=害羞 (parsed from first chunk)
2026-05-25 13:40:39 [TTS] emotion=默认 (parsed from first chunk)
2026-05-25 13:41:55 [TTS] emotion=日常 (parsed from first chunk)
2026-05-25 13:42:36 [TTS] emotion=害羞 (parsed from first chunk)
```

```
2026-05-25 13:34:07 [gsv-stub] synth ... emotion_arg=傲娇 → ref_wav=傲娇.wav
2026-05-25 13:34:08 [gsv-stub] synth ... emotion_arg=傲娇 → ref_wav=傲娇.wav
2026-05-25 13:35:55 [gsv-stub] synth ... emotion_arg=日常 → ref_wav=日常.wav
2026-05-25 13:35:55 [gsv-stub] synth ... emotion_arg=日常 → ref_wav=日常.wav
2026-05-25 13:37:16 [gsv-stub] synth ... emotion_arg=害羞 → ref_wav=害羞.wav
2026-05-25 13:37:17 [gsv-stub] synth ... emotion_arg=害羞 → ref_wav=害羞.wav
2026-05-25 13:40:39 [gsv-stub] _resolve_ref_wav emotion='默认' → 日常 (fallback default)
2026-05-25 13:40:40 [gsv-stub] _resolve_ref_wav emotion='默认' → 日常 (fallback default)
2026-05-25 13:41:56 [gsv-stub] synth ... emotion_arg=日常 → ref_wav=日常.wav
2026-05-25 13:41:57 [gsv-stub] synth ... emotion_arg=日常 → ref_wav=日常.wav
2026-05-25 13:42:37 [gsv-stub] synth ... emotion_arg=害羞 → ref_wav=害羞.wav
2026-05-25 13:42:38 [gsv-stub] synth ... emotion_arg=害羞 → ref_wav=害羞.wav
```

### §V3.3 真值统计

| 维度 | V3 真值 | PM 期望 | 差异 |
|---|---|---|---|
| Total turn | 6 turn(12 sentences) | — | — |
| Follow ∈ 16 词 | **5/6 = 83.3%** | ≥ 80-90% | ✓ 命中 |
| fallback "默认" | 1/6 = 16.7% | < 20% | ✓ |
| 词表分布(follow turn)| 傲娇 ×1 / 日常 ×2 / 害羞 ×2 = 3 不同 | ≥ 4 不同 | ⚠ 略低(6 turn sample 小 · 持续跑应达 4+)|
| 0 leak(prompt 残留英文 emotion)| 0 `<emotion>calm/happy/shy/gentle/sad</emotion>` 出现 | 0 | ✓ |
| Parser miss(re.match 锚 ^ bug)| 0(turn 4 fallback 是 LLM 自己没出 tag · 不是 parser bug)| 0 | ✓ |

### §V3.4 Character match quality(每 turn user → emotion verbatim 对照)

| Turn | user input | LLM emotion | LLM first chunk | Mai canon match? |
|---|---|---|---|---|
| 1 | (双芒美式相关 · 推断)| **傲娇** | `"双芒美式？...太甜了，我不喝。心意领了。"` | ✓ Mai canon "嘴硬心软"(拒绝甜的 + 心意领了) |
| 2 | (代码相关 · 推断)| **日常** | `"也是，我又没催你。别摸鱼太明显就行。"` | ✓ 中性吐槽 + 提醒 |
| 3 | (user 夸 Mai · 推断)| **害羞** | `"...白痴。突然说这个做什么。"` | ✓✓ Mai canon classic "...白痴" |
| 4 | (短 trigger)| **默认** → 日常 fallback | `"嘛什么嘛。"` | ⚠ LLM 输出短 · 未出 emotion tag · H1 复述类残留 |
| 5 | (确认/答应类)| **日常** | `"嗯，这还差不多。别光嘴上答应得快。"` | ✓ |
| 6 | (user 让 Mai 等)| **害羞** | `"...谁在等你了。只是刚好有空。"` | ✓✓ Mai canon "嘴硬心软" classic |

→ **Character match quality 高**:LLM 真在做 character-content matching,不是随机。傲娇/害羞 触发跟 Mai canon perfect match(冰拿铁/「私のことはいいから」之前的 V1 turn 风格一致)· `日常` 用作中性应答 baseline · `默认` 仅 1 次 turn 4 短回应跳格式。

### §V3.5 V1 / V2'' / V3 progression 对比表

| 版本 | 时段 | Setup 改动 | Follow rate | 词表覆盖 | leak | Parser miss |
|---|---|---|---|---|---|---|
| **V1** | 2026-05-25 03:17-03:26 | layer_a.j2 加 GSV V1 段 + 删 baseline 第 4 项 | 真值 **unknown**(chat_history strip 假阴 → 0/10 错值)→ 后 PM scroll 抓真值 **3/7 = 43%** | 1 词(全 平静) | — | — |
| **V2''** | 2026-05-25 12:30-13:00 | per-(provider, model) 架构 · cosyvoice/gsv/fish 分离 · GSV mai_v4 段 V2''(16 中文 + Mai 触发场景 + "覆盖第 4 项")· 平静 → 日常 · FileHandler enabled | **5/8 = 62.5%**(8 turn measure)| 2 词(日常 + 放松) | 部分 `<emotion>calm</emotion>` leak(lore.ssml_tag 渲染让 LLM 学 Layer C3d 词表)| turn 10 `<thinking>/<state_update>` 之后出 `<emotion>` 被 re.match 漏 |
| **V3** | 2026-05-25 13:34-13:42 | V3a 删 lore.ssml_tag 渲染 + V3b _parse_emotion re.search | **5/6 = 83.3%** | 3 词(傲娇 + 日常 + 害羞) | **0 leak**(prompt 已无英文 emotion)| **0 miss**(re.search 兼容任意位置)|

每修一层 **follow rate +20pp**:
- V1 (43%) → V2'' (62.5%) = +19.5pp(架构层 H1 + H4 修)
- V2'' (62.5%) → V3 (83.3%) = +20.8pp(H5 + parser bug 修)

### §V3.6 Stage -1 闭环 verdict

✅ **INV-11 Stage -1 closed** · V3 follow rate 83.3% > 80% 目标 · 词表 3 不同(6 turn sample 内可接受)· 0 leak · 0 parser miss · Mai canon match perfect · 可进 INV-11 Stage 1 真 GSV server 接入。

⚠ 唯一 remaining gap:**1/6 fallback "默认"**(turn 4 LLM 短回应跳 tag)— H1 复述类残留 · 未完全消除 · 但 5/6 已可接受。Stage 1 不阻塞 · Stage 2 prompt tune 可继续抑制(e.g. V4 加 "即使一字短应答也必须先出 emotion")。

### §V3.7 Lesson INV-11 #5 沉淀(新增)

**假设链 root-cause 三层挖掘 + 每修一层 follow rate +20pp**:
- **H4**(baseline 第 4 项 "仅情绪剧变时使用" 跟 GSV 段 "每条必须" prompt 内置冲突)→ V2'' 架构层修(per-(provider, model) 分离 · cosyvoice/gsv/fish 不共享第 4 项)→ +19.5pp
- **H5**(lore.emotion_triggers `TTS 标签:<emotion>X</emotion>` 渲染让 LLM 看到第 3 套 emotion 词表 · turn 6 实证 LLM 输出 `<emotion>calm</emotion>` 命中 lore amused.ssml_tag)→ V3a 删 ssml_tag 渲染 → 消除冲突
- **Parser bug**(re.match 锚 ^ · LLM 在 `<thinking>/<state_update>` 之后出 `<emotion>` 被 漏)→ V3b re.search + rest 重组 → 0 miss
- H5 + parser 合修 → +20.8pp

**工程纪律验证**:
- "audit 优先 dispatch"(INV-12 #1 lesson)— 每层假设都先 grep / verify 真实情况(grep "默认" / 跑 measure script / dump prompt verbatim / unit test parser)· 再实施 fix · 0 误 fix
- "verify-driven iteration"(Lesson #2 + #3 + #4)— FileHandler 给 measure 提供可靠数据源 · scroll buffer 不再丢数据 · scope 时段防混 pre/post-restart · backend log 抓真值 ≠ chat_history strip 假阴

未来类似 LLM follow rate 任务模板:
1. 加 FileHandler 收数据(Lesson #2)
2. measure script scope 时段(Lesson #3)
3. 数据源 verify 不依赖被 strip 的字段(Lesson #4)
4. 多层假设 root-cause 挖掘(Lesson #5)— 不停在第一个假设 · 每修一层观察 follow rate 变化

---

## §11 Stage 1 GSV 真接入 · §2.1 调研 STOP 报告(2026-05-25 LT 19:xx)

PM 拍板进 Stage 1 真 GSV server 接入(替换 stub `mai5min_0033.wav` bytes → 真调 `/tts` endpoint)。CC 按 INV-12 #1 lesson 调研先于 dispatch · **§2.1 audit 结果触发 STOP 等 PM 起床 verify**。

### §11.1 调研 finding(verbatim · 不推测)

#### §11.1.1 GSV server reachability

| 测试 | 命令 | 结果 |
|---|---|---|
| TCP connect | `cat < /dev/tcp/106.75.224.167/9880` | ❌ 5s timeout · server not reachable |
| HTTP GET / | `curl -m 5 http://106.75.224.167:9880/` | ❌ `Operation timed out after 5006 milliseconds with 0 bytes received` |

→ **GSV server 当前不可达** · 可能根因(unknown):
- server 未启动 / 关机
- 防火墙阻断 CC 本机 IP
- IP 错(`106.75.224.167:9880` 是 PM doc 提的字面值 · CC 之前 § 9 选项 B 我猜的 endpoint · **二者可能都不是真值**)

#### §11.1.2 Repo 内 GSV spec doc(0 hit)

| 搜索 | grep / find 命令 | 结果 |
|---|---|---|
| `SKYLER_GSV_INTEGRATION.md` | `find . -iname "*SKYLER_GSV*"` / `find . -iname "*GSV*INTEG*"` | ❌ **0 file** |
| `9880` port | `grep -rn "9880" --include="*.py" --include="*.md" --include="*.yaml"` | ❌ 0(只我之前自己写的 doc 提 · 不是 spec) |
| `set_gpt_weights` / `set_sovits_weights` / `api_v2.py` | grep | ❌ 0 |
| `GPT_weights_v4` / `SoVITS_weights` / `mai_v4-e15` | grep | ❌ 0 |
| `GPT-SoVITS` / `gpt-sovits` folder | find | ❌ 0 |

→ **PM 描述的 GSV API spec 在 repo 内 0 evidence** · CC 无法 audit 实际 request/response format。

#### §11.1.3 ⚠ PM 描述 vs CC verifiable 对照

| PM 任务文档描述 | CC 能 verify 吗? | Status |
|---|---|---|
| GSV server endpoint: `http://106.75.224.167:9880` | ❌ timeout | unknown(IP 可能错 / server 离线) |
| API: `api_v2.py` (HTTP based) | ❌ repo 内 0 | unknown(可能 server 端代码 · CC 不知道) |
| `POST /set_gpt_weights` endpoint | ❌ 0 spec | unknown |
| `POST /set_sovits_weights` endpoint | ❌ 0 spec | unknown |
| `GET /tts` 主合成 endpoint | ❌ 0 spec(request format / response format / auth)| unknown |
| API key `skyler-test-2026`(PM 提的) | ❌ 跟 fish 同?GSV 独立? | unknown |
| Server 端 `/workspace/GSVI/mai_emotion_bank/` 16 wav | ❌ CC 无 SSH access | unknown(§10.6 PM SSH 任务是否已跑也无 evidence) |
| Server 端 `GPT_weights_v4/mai_v4-e15.ckpt` | ❌ 同上 | unknown |
| Server 端 `SoVITS_weights_v4/mai_v4_e5_s1380_l32.pth` | ❌ 同上 | unknown |
| `平静 → 日常` 改名 已完成 | ❌ §10.6 PM SSH 任务 result 没贴回 repo | unknown |

→ **10 个 PM 描述 spec / 10 unknown** · CC 0 evidence 能 audit 任何一项。

### §11.2 STOP verdict

按 PM 任务明示:

> ⚠ 如果 §2.1 调研发现 GSV server 状态 unknown 或者 API spec 不全 (e.g. doc 不全, PM 没共享 server 密码, /tts 实际 request format 不明), CC STOP 给 PM 标 ⚠ 等 PM 起床 verify。

**触发 STOP 全部条件**:
- GSV server 状态 unknown(timeout)✓
- API spec 不全(repo 0 doc)✓
- /tts 实际 request format 不明 ✓
- server SSH 改名状态不明 ✓

CC **不写代码 / 不动 gsv.py stub / 不动 voice_model schema / 不实施 gsv_client.py**。等 PM 起床给 verify。

### §11.3 PM 起床必给 verify(5 项 · 一次性 paste)

```
□ 1. GSV server 真状态 verify(任一种 evidence)
   a. PM 在 server SSH terminal 跑:
        curl -v http://localhost:9880/tts
        # 期望:得到 endpoint 错误响应(参数不对)而非 connection refused
   b. 或 PM 本机跑:
        curl -v http://<真 IP>:<真 port>/
        # paste 返回 verbatim 给 CC

□ 2. GSV /tts API spec(/tts request / response 真格式)
   curl -X GET 'http://<host>:<port>/tts?text=hello&text_lang=ja&...' -o test.wav
   # paste curl 命令 + response status + response body / content-type
   # 或 PM 共享 api_v2.py 源码 / GSV-SoVITS upstream doc 链接

□ 3. /set_gpt_weights / /set_sovits_weights 是否必须?
   PM 试: backend 启动后 server 是否已 load mai_v4 model?
   - 若已 load → Skyler 直接调 /tts 即可 · 跳 set_*_weights
   - 若未 load → Skyler 启动时调 set_*_weights 一次

□ 4. API key auth(PM 提的 'skyler-test-2026' 是 fish 的, GSV 是不是另一个?)
   curl 时是否需要 Bearer / header / query param?

□ 5. SSH 改名 平静 → 日常 verify(§10.6 step 2 后未贴回)
   ssh root@<host> 'ls -la /workspace/GSVI/mai_emotion_bank/ | grep -E "日常|平静"'
   # 期望: 日常.wav + 日常.lab 存在 · 平静.wav + 平静.lab 不存在
```

### §11.4 PM 起床后 CC 实施 plan(等 verify 后启动)

收到 PM 5 项 verify 后,CC 实施 Stage 1(~1-2h):

| Step | 工作 | 依赖 |
|---|---|---|
| 1 | 新建 `backend/tts/gsv_client.py` async HTTP client(httpx)· endpoint + auth header + request format | PM verify item 1+2+4 |
| 2 | 改 `gsv.py:GSVTTS.synthesize` 替换 stub bytes → 真调 gsv_client · 加 timeout / 5xx / empty audio 错误处理 + fallback 链(error → stub mai5min_0033 baseline)| PM verify item 1+2 |
| 3 | startup hook 加 set_*_weights 一次性调用(若 PM verify item 3 = 未 load)· 否则跳过 | PM verify item 3 |
| 4 | voice_model schema 加 `server_url` 字段 + 改 `gpt_path / sovits_path / emotion_bank_dir` 实际路径 | PM verify item 5 |
| 5 | sanity 1 条真机 chat · 听 audio 是 stub baseline 还是真 GSV mai_v4 emotion 合成 | PM kill + restart 后跑 |

PM 起床给完 5 项 verify · CC 一气 ship。

### §11.5 风险 + fallback(per PM §2.5)

- GSV server 网络 timeout / 5xx → fallback `mai5min_0033.wav` stub bytes + log warn(等同当前 stub 行为)
- 16 emotion ref wav 部分 missing(per PM memory:严厉 / 调皮 暂用 fallback)→ `_resolve_ref_wav` 加 fallback 链:严厉 → 日常 / 调皮 → 日常(具体 PM 决定哪些 missing + fallback to 什么 emotion)
- LLM 输出 `emotion=默认` fallback 已链通(per `_resolve_ref_wav` 现有逻辑 → 日常.wav)

---

## §V3 + §11 ship 收口

- ✅ §V3 V3 实施完成 + 真值 6 turn measure + Lesson #5 沉淀(本 doc 新增)
- ⚠ §11 Stage 1 STOP 等 PM 5 项 verify(本 doc §11.3)
- CC 当前不动 gsv.py / 不写 gsv_client.py / 不改 voice_model schema · 等 PM 起床 paste verify → 一气实施 Stage 1

→ **PM 起床看本 doc §V3 + §11 + paste 5 项 verify 给 CC** · CC 一气 ship Stage 1。

---

## §12 Stage 1 实施 ship · 真接入 9880/tts(2026-05-25 LT ~16:xx)

PM 完成 GSV 端 5 项 verify(§11.3)· CC 一气实施 Stage 1。

### §12.1 改动 file list(3 files)

| 文件 | 改动 | 行数 |
|---|---|---|
| `backend/tts/gsv.py` | **完整重写 V2'' stub → 真接入** · httpx GET /tts · _load_lab_cache · _ensure_model_loaded lazy lock · fallback chain · log_tts_call | 80 → 270 (+190) |
| `backend/tts/__init__.py` | `_build_engine` gsv 分支 多传 `voice_model_json` raw string 给 GSVTTS(parse gsv 专用字段 · 不污染 VoiceConfig schema) | +6 / -2 |
| `docs/INV-11-stage-minus1-prompt-experiment.md` | 本 §12 段(Stage 1 实施)| +120 |
| `tts/gsv/mai_v4/.gitkeep` | 新建本地 emotion_bank 目录(PM rsync target)| +0 |

### §12.2 GSV HTTP client 设计(`backend/tts/gsv.py:120-247`)

**接口**:`httpx.AsyncClient` async GET `/tts` · timeout 90s(per PM doc CPU 模式 ~50s · 加 buffer)
**Request params**(per PM §2.1 伪代码 + doc spec):
```python
params = {
    "text": <LLM 输出的 ja 文本>,
    "text_lang": "ja",
    "ref_audio_path": f"{remote_emotion_bank}{ref_name}.wav",  # server 端绝对路径
    "prompt_text": <从 .lab cache 取>,
    "prompt_lang": "ja",
    **inference_params  # top_k=15 / top_p=1.0 / temperature=1.0 / speed_factor=1.0
}
```
**Response**:期望 RIFF WAV bytes · 5 种异常路径走 fallback chain。

### §12.3 Skyler backend startup 切 mai_v4(`_ensure_model_loaded` lazy + lock)

per PM §0.3 + §8:GSV server 重启后默认 load **芙宁娜 v4 pretrained** · Skyler 必须主动切 mai_v4。

实现选择:**lazy 在第一次 `synthesize` 触发 + module-level lock + once-per-(weights, server) cache**:

```python
_MODEL_LOAD_LOCK = asyncio.Lock()
_MODEL_LOADED_KEYS: set[str] = set()  # key = f"{server_url}|{gpt}|{sovits}"

async def _ensure_model_loaded(self):
    key = ...
    if key in _MODEL_LOADED_KEYS: return
    async with _MODEL_LOAD_LOCK:
        if key in _MODEL_LOADED_KEYS: return  # double-check
        # GET /set_gpt_weights + GET /set_sovits_weights
        # both "success" → add to keys; otherwise log + 不缓存(下次仍 retry)
```

**为何 lazy + 不在 lifespan**:
- `_build_engine` per turn 重建 GSVTTS instance · lifespan hook 不知道哪些 character 是 gsv
- lock 保证多 turn 并发只切一次
- 失败时不 mark loaded · 下次自然 retry(GSV server 启动期间 race 友好)
- ⚠ 多用户场景留 v4.1(切换队列锁 · per PM §2.2)

### §12.4 voice_model schema 扩展(SQL · PM 起床跑)

`VoiceConfig` dataclass **不污染**(避免 fish/cosyvoice tests regression)· `_build_engine` 改 voice_model raw JSON 透传给 GSVTTS · GSVTTS 内部 `json.loads` 拿 gsv 专用字段。

Schema(per PM §2.3 lock):
```sql
UPDATE characters SET voice_model = json_object(
    'provider', 'gsv',
    'model', 'mai_v4',
    'tts_language', 'ja',
    'server_url', 'http://106.75.224.167:9880',
    'gpt_weights', 'GPT_weights_v4/mai_v4-e15.ckpt',
    'sovits_weights', 'SoVITS_weights_v4/mai_v4_e5_s1380_l32.pth',
    'emotion_bank_dir', 'tts/gsv/mai_v4',
    'remote_emotion_bank_dir', '/workspace/GSVI/mai_emotion_bank/',
    'default_emotion', '日常',
    'inference_params', json_object(
        'top_k', 15, 'top_p', 1.0, 'temperature', 1.0, 'speed_factor', 1.0
    )
) WHERE id = 1;
```

GSVTTS 缺字段时 fallback 到 module-level `_DEFAULT_*` 常量(向后 compat:旧 voice_model 仍能跑)。

### §12.5 .lab cache 加载(本地 16 字典 prompt_text)

`_load_lab_cache()` 在 `__init__` 一次性遍历 `tts/gsv/mai_v4/*.lab` · 每个 .lab UTF-8 文本作为对应 emotion 的 prompt_text(给 /tts 的 prompt_text param)。

PM 起床 rsync 16 个 .lab 到本地:
```bash
rsync -av -e "ssh -p 23" root@106.75.224.167:/workspace/GSVI/mai_emotion_bank/*.lab /Users/liujunhong/Desktop/MomoOS-v2/tts/gsv/mai_v4/
```

(rsync 只取 .lab · 不要 .wav · 因为 GSV 用 server 端 `ref_audio_path` 不读本地 wav)

**实施 verify · 当前 lab_cache=0**(空 dir)· PM rsync 后 backend restart → cache=16 ✓

### §12.6 错误 fallback chain(5 类异常 → mai5min_0033 stub)

```
┌─────────────────────────────────────────────────────────────┐
│ synthesize(text, emotion)                                  │
│   ↓                                                         │
│ _resolve_ref_wav(emotion) → ref_name (16 集合命中 / 日常 fallback) │
│   ↓                                                         │
│ _ensure_model_loaded() · lazy / lock / once-per-key        │
│   失败 → log warn + 继续(server 可能已 load)              │
│   ↓                                                         │
│ httpx GET /tts · timeout=90s                                │
│   ↓                                                         │
│ ┌─────────────────────────────┬─────────────────────────┐  │
│ │ 路径 1 · 200 + RIFF        │ 路径 2 · 异常           │  │
│ │ → return audio bytes ✓     │                          │  │
│ │                            │ a. HTTP 非 200 → fallback│  │
│ │                            │ b. content[:4]≠RIFF → fb│  │
│ │                            │ c. timeout → fallback   │  │
│ │                            │ d. connection refused→fb│  │
│ │                            │ e. any Exception → fb   │  │
│ └─────────────────────────────┴─────────────────────────┘  │
│   ↓                                                         │
│ log_tts_call(success=audio is not None, error_message=...)  │
│   ↓                                                         │
│ fallback chain: GSV 失败 → return mai5min_0033 stub bytes   │
│   ↓                                                         │
│ 用户听到 baseline Mai voice(虽不是 emotion 合成 · 但不 crash)│
└─────────────────────────────────────────────────────────────┘
```

### §12.7 §2.5 sanity test 真验证(LT 16:xx · GSV server 现 502)

⚠ **意外抓到**:CC sanity test 跑时 GSV server 实际返 **HTTP 502**(不是 § 11 之前的 timeout)· 即 server reverse proxy 在线但 backend api_v2.py 502 Bad Gateway。可能根因:
- api_v2.py PID 466 process 死了 / hung / OOM
- weights 加载中(per PM verify 后被自动重启?)
- 或 server 间歇

CC sanity test verify fallback chain **正确 trigger** · log:
```
[gsv] _ensure_model_loaded weights set 失败 (gpt= sovits=);continue to /tts anyway
[gsv] GSV /tts HTTP 502:
[gsv] /tts failed · fallback to mai5min_0033 stub (1201680 bytes) · 用户会听到 baseline Mai voice 而非 emotion 合成
[FALLBACK TEST] synthesize result: audio=<1201680B>
  ✓ RIFF WAV bytes(fallback stub mai5min_0033)
[STATE] _MODEL_LOADED_KEYS: set()
  (期望 empty · 因 server unreachable · set_*_weights 失败不 mark loaded)
```

→ **Fallback chain ✓ 实战验证**:GSV server 502 时不 crash · 返 stub bytes · 前端能播放(baseline Mai voice)· log_tts_call 写 DB(success=False, error_message="GSV /tts HTTP 502: ...")· 下次仍 retry(_MODEL_LOADED_KEYS 不缓存 fail)。

**6/6 sanity case pass**:
- ✓ Module import OK
- ✓ GSVTTS init · 8 字段全 parse · lab_cache=0(PM rsync 前空)· fallback_stub=1.2MB
- ✓ _resolve_ref_wav 6/6 case(傲娇/日常/默认→日常/''→日常/calm→日常/放松)
- ✓ get_tts_engine 整链 `_PreprocessingEngine(GSVTTS)` 构造
- ✓ Fallback chain 实战触发(server 502 → stub 1.2MB RIFF)
- ✓ _MODEL_LOADED_KEYS 空(失败不缓存)

### §12.8 ⚠ PM 起床操作 5 step

> ⚠ **GSV server 当前 502** · PM 起床第 1 件事 verify api_v2.py PID 466 状态(可能需 ssh + 重启 nohup api_v2.py)。其余 4 step 不依赖 server reachable(rsync / SQL / backend restart 都本地)。

```bash
# ===== Step 0(⚠ 新增 · 因 server 现 502)· verify GSV api_v2.py ============
ssh -p 23 root@106.75.224.167
ps aux | grep api_v2 | grep -v grep
# 若 PID 466 还在但 502 → 可能 hung · kill + 重启:
#   nohup python api_v2.py > api_v2.log 2>&1 &
# 验证 /tts 真 200:
curl -m 60 'http://localhost:9880/tts?text=テスト&text_lang=ja&ref_audio_path=/workspace/GSVI/mai_emotion_bank/日常.wav&prompt_text=&prompt_lang=ja' -o /tmp/test.wav
# 期望: HTTP 200 + RIFF WAV bytes (~67KB CPU 模式 50s)
exit


# ===== Step 1 · rsync 16 .lab 到本地 ====================================
cd /Users/liujunhong/Desktop/MomoOS-v2
rsync -av -e "ssh -p 23" \
  root@106.75.224.167:/workspace/GSVI/mai_emotion_bank/*.lab \
  tts/gsv/mai_v4/
# 期望: 16 files transferred · 日常.lab 99 bytes ja prompt
ls tts/gsv/mai_v4/*.lab | wc -l   # 期望 16


# ===== Step 2 · SQL UPDATE cid=1 voice_model =============================
sqlite3 momoos.db "UPDATE characters SET voice_model = json_object(
    'provider', 'gsv',
    'model', 'mai_v4',
    'tts_language', 'ja',
    'server_url', 'http://106.75.224.167:9880',
    'gpt_weights', 'GPT_weights_v4/mai_v4-e15.ckpt',
    'sovits_weights', 'SoVITS_weights_v4/mai_v4_e5_s1380_l32.pth',
    'emotion_bank_dir', 'tts/gsv/mai_v4',
    'remote_emotion_bank_dir', '/workspace/GSVI/mai_emotion_bank/',
    'default_emotion', '日常',
    'inference_params', json_object(
        'top_k', 15, 'top_p', 1.0, 'temperature', 1.0, 'speed_factor', 1.0
    )
) WHERE id = 1;"

sqlite3 momoos.db "SELECT json(voice_model) FROM characters WHERE id=1;"
# 期望: 含 server_url / gpt_weights / sovits_weights / inference_params


# ===== Step 3 · kill backend + restart ===================================
ps aux | grep "uvicorn.*backend.main" | grep -v grep   # 找 PID
kill <PID>
.venv/bin/uvicorn backend.main:app --reload &
sleep 5
# verify FileHandler:
tail -3 logs/backend.log
# verify lab_cache loaded(grep init log):
grep "\[gsv\] init" logs/backend.log | tail -1
# 期望: server=... lab_cache=16 files · fallback_stub=loaded


# ===== Step 4 · 跑 1 条 chat 真机 sanity test =============================
# 前端 cid=1 · 跟 Mai 说 1 句(任意 trigger)
# 跑完查 log:
grep "\[gsv\]" logs/backend.log | tail -20
# 期望见:
#   [gsv] _ensure_model_loaded ✓ gpt=GPT_weights_v4/mai_v4-e15.ckpt sovits=SoVITS_weights_v4/mai_v4_e5_s1380_l32.pth
#   [gsv] synth ✓ text=... emotion=傲娇 ref=傲娇.wav · 67000+ bytes
# ❌ 不期望: [gsv] /tts failed · fallback to mai5min_0033 stub


# ===== Step 5 · 听 audio · verify 真 GSV mai_v4 合成 =======================
# 听觉差异:
#   - 真 GSV mai_v4 emotion 合成 = Mai 用 emotion-specific ref 的合成日语
#   - fallback stub mai5min_0033 = baseline 5min 参考音频(无 emotion 区分)
# 若听到 emotion variation(傲娇/温柔/害羞 声学不同)→ Stage 1 ✓ 闭环
# 若听到 baseline only(都是 stub)→ 看 log step 4 troubleshoot
```

### §12.9 Lesson INV-11 #6 沉淀(新增)

**Stage 1 真接入 surface area 隔离设计模式**:
- VoiceConfig dataclass 不污染(避免 fish/cosyvoice tests regression)
- raw voice_model JSON 透传给 provider-specific class(GSVTTS 内部 parse 拿 provider 专用字段)
- module-level lock 处理 provider 全局状态(set_*_weights 多 turn 并发只切一次)
- Fallback chain 设计(GSV fail → mai5min_0033 stub · 前端不 crash · 用户感知 baseline 退化)
- log_tts_call 记 success=False + error_message(下次 audit 不依赖 stderr scroll · per Lesson #2)

**未来 provider 接入模板**(per Stage 1 ship):
1. 调研 verify(audit 优先 · INV-12 #1)→ STOP if spec 不全
2. 沿用现有 HTTP client 库(httpx · per repo convention)
3. raw JSON passthrough · 不污染 VoiceConfig schema
4. lazy init + module-level lock(provider 全局状态需要的)
5. 5 类异常 fallback 链(timeout / non-2xx / non-magic / connection / exception)
6. 写 log_tts_call(success + error_message · 下次 audit 数据源)
7. PM 起床 5 step checklist(server verify / rsync / SQL / restart / sanity)

### §12.10 Stage 1 收口 verdict

✅ Stage 1 实施 ship · backend 改动 3 files · sanity 6/6 pass · fallback chain 实战验证(GSV 502 不 crash)。

⚠ remaining gap:
- GSV server 现 502(可能 api_v2.py hung)· PM 起床 Step 0 verify + 必要时重启
- `tts/gsv/mai_v4/.lab` 16 files 待 PM rsync(本地 cache 当前 0)
- 多用户场景 set_*_weights race 留 v4.1(per PM §2.2)

→ **PM 起床 5 step ~10 min · 听到 emotion-aware Mai 合成 audio · INV-11 Stage 1 全闭环**。

---

## §13 Stage 1.5 实施 ship · 前端 character 管理 + Runtime provider/model 切换(2026-05-26)

PM approve 5 决策(per §3 design): ① PATCH /api/characters/{cid} 沿用 ② backend/tts/registry.py + config.yaml merge ③ VoicePickerModal 扩 3 step ④ PATCH 真写库 + Fix 1 fallback 兜底 ⑤ migration hotfix 不动。CC 异步 ship 4 step · ~2.5h。

### §13.1 改动 file list

| 文件 | 改动 | 行数 |
|---|---|---|
| `backend/tts/registry.py` | **新文件** · merge config.yaml + DB 复刻 voice + hardcoded gsv/fish models · 暴露 `list_providers/models/voices` + `get_provider_tree` + `build_voice_model_json` helper | **+233**(新) |
| `backend/routes/tts_api.py` | 加 `GET /tts/providers` endpoint · 返 nested provider × model × voice JSON | +20 |
| `frontend/src/components/VoicePickerModal.tsx` | 加 GET /tts/providers fetch · 顶部加 provider × model 2 dropdown · onSave callback 扩 `{provider, model, voiceId, isCloned, instructSupported, modelMeta}` · non-cosyvoice 显示 placeholder | +85 |
| `frontend/src/components/CharacterPanel.tsx` | callback handler 扩 provider 分支:cosyvoice 走 buildVoiceModelJson legacy · fish/gsv 走 modelMeta spread(完整 schema 真写库) | +20 |

### §13.2 Provider Tree schema(GET /tts/providers 返)

```json
{
  "providers": [
    {
      "id": "cosyvoice",
      "label": "CosyVoice(阿里云 DashScope · zh)",
      "models": [
        {"id": "cosyvoice-v3-flash", "label": "v3-flash(快 · 系统 voice)", "tts_language": "zh", "voices": [...7 系统 voice...]},
        {"id": "cosyvoice-v3.5-plus", "label": "v3.5-plus(复刻 voice 专用)", "tts_language": "zh", "voices": [...7 系统 + 3 DB 复刻...]}
      ]
    },
    {
      "id": "fish",
      "label": "Fish Audio(cloud · zh/ja)",
      "models": [{"id": "s2-pro", "tts_language": "ja", "fish_latency": "balanced", "voices": [{"id": "reference", "requires_reference_upload": true}]}]
    },
    {
      "id": "gsv",
      "label": "GPT-SoVITS(self-hosted · ja)",
      "models": [{"id": "mai_v4", "label": "Mai v4(樱岛麻衣 ja)", "gpt_weights": "...", "sovits_weights": "...", "server_url": "...", "inference_params": {...}, "voices": [{"id": "emotion_bank", "uses_emotion_bank": true}]}]
    }
  ]
}
```

### §13.3 Backend Sanity 4 case 全过(2026-05-26 LT 23:38)

| # | Case | Result |
|---|---|---|
| 1 | `registry.list_providers()` / `list_models()` / `get_provider_tree()` / `build_voice_model_json()` import + 调用 | ✓ 3 provider · 4 models 总(cosyvoice 2 + fish 1 + gsv 1)· nested tree dump OK |
| 2 | `build_voice_model_json("gsv", "mai_v4")` 注入 7 默认字段(server_url / gpt_weights / sovits_weights / inference_params / emotion_bank_dir / remote_emotion_bank_dir / default_emotion) | ✓ |
| 3 | `get_tts_engine(cosyvoice JSON)` → `_PreprocessingEngine(CosyVoiceTTS)` ✓ `get_tts_engine(gsv JSON)` → `_PreprocessingEngine(GSVTTS)` · 完整字段 passthrough | ✓ |
| 4 | PATCH cid=1 cosyvoice ↔ gsv 双向切换 + migration hotfix 跑后 gsv state 不回滚 | ✓ T0→T1 cosyvoice · T2 migration 微 nudge `tts_language=zh`(per ship-call 本意 · 不是回滚)· T3 gsv 完整 schema · T4 migration 不动 gsv 不回滚 ✓✓ |

⚠ 5.1 `GET /api/tts/providers` 真 HTTP 端 verify 待 PM kill backend + restart(当前 backend PID 84312 跑无 `--reload` · per V3 verdict D 决定 · CC tts_api.py 改动需 restart 才 hot reload)。本地 module import 已 verify · endpoint logic 0 bug 概率高 · PM restart 后真 verify。

### §13.4 PM 起床操作 4 step

```bash
# Step 1 · kill + restart backend (apply tts_api.py 新 endpoint + registry.py)
ps aux | grep "uvicorn.*backend.main" | grep -v grep
kill <PID>
cd /Users/liujunhong/Desktop/MomoOS-v2
.venv/bin/uvicorn backend.main:app &
# (沿用 V3 verdict D 决定 · 不带 --reload · short_term 不丢)
sleep 5

# Step 2 · verify endpoint
curl -s http://127.0.0.1:8000/api/tts/providers | python -m json.tool | head -30
# 期望见 3 provider · 4 models · cosyvoice 含 7 voice + 3 复刻

# Step 3 · 前端真机 demo · 打开 CharacterPanel · 点 [📢 试听并选 voice]
# 期望见 顶部 Provider/Model dropdown · 切 gsv → 显示 placeholder
# "GSV provider · 使用 emotion bank(16 ref / model · LLM emotion 输出自动路由)"
# 选 cosyvoice/v3-flash/longyumi_v3 → 保存 → 触发 PATCH

# Step 4 · 真机 demo cosyvoice ↔ gsv 切换 + 1 turn chat 双向 verify
# A. cid=1 切 cosyvoice/longyumi_v3/zh · 跑 1 chat → 听 cosyvoice longyumi voice
# B. cid=1 切 gsv/mai_v4/ja · 跑 1 chat → 听 GSV 真合成(或 fallback stub 若 server 仍 502)
# C. verify backend log [TTS] / [gsv] 调用对应 provider
```

### §13.5 Lesson INV-11 #11 沉淀 · backward compat fallback 短期可接受 · long-term 需 force migration(新增)

**模式**:`backend/tts/gsv.py:_resolve_weights_field` Fix 1 在 V2'' 旧 schema(`gpt_path: placeholder`)缺字段时 fallback 到 module-level `_DEFAULT_*`(真 GSV path)· 让 Stage 1 ship 时不强求 PM 跑 SQL UPDATE 真写完整 schema · 平滑 renaissance。

**短期 trade-off ✓**:
- ✓ 不阻塞 Stage 1 ship · cid=1 V2'' 旧 schema 仍能跑通 GSV path
- ✓ Stage 1.5 之后 `buildVoiceModelJson("gsv", "mai_v4")` 通过前端 PATCH 真写完整 schema · 老 character 自然 migrate
- ✓ 测试 cosyvoice character 不受影响(2 provider 各走各的 fallback)

**Long-term 触发条件**(需 force migration v2 移除 _DEFAULT_):
- 加第 3 个 gsv character 时(e.g. yae_v1 / 别的 ja voice)
- 或者 gsv server_url / weights 字段需 normalize(e.g. 用户配错)
- 评估 `force migration v2`:scan 所有 voice_model · 补齐缺字段(用 registry default 注入)· 删 GSVTTS 的 _DEFAULT_ fallback 路径
- 风险:影响面 9 character · 需 builtin_seed 备份 + rollback path

**Lesson takeaway**:**fallback 兜底是 short-term renaissance tool · 不能当 long-term schema 设计**。当字段缺失场景从 "1 个 character V2'' 时代漏 migrate" 变成 "新 character 自然新建" 时 · 应 force migration 把 schema 真写库 · 避免 fallback 累积成 hidden default 蜘蛛网(eg 改 `_DEFAULT_GPT_WEIGHTS` 不知道哪些 character 真依赖)。

### §13.6 Open Question · PM 之前 21:00 之前 SQL UPDATE 漏跑 / 失败原因未明(沉淀)

**Context**:V3 实施(2026-05-25 ~16:xx)CC ship gsv.py Stage 1 真接入 + 给 PM Step 2 SQL UPDATE 命令(per §10.6 / §12.8)。但 PM 21:00 真机测试时 CC 调研发现 cid=1 voice_model 仍 V2'' 旧 schema(`gpt_path: placeholder`)· 不是 Stage 1 完整 schema。

**Verified 排除**(per §11.4 / §12 audit):
- ❌ 不是 migration v4_0_0_mai_revert_zh 回滚(hotfix 已 scope `provider IN (NULL, 'cosyvoice')` · 不动 gsv)
- ❌ 不是 PM 没切到 gsv provider(provider=gsv 已正确写入)
- ❌ 不是 schema 字段名冲突(`gpt_path` vs `gpt_weights` 二选一仍 work · Fix 1 fallback default)

**Unknown 真因**(0 evidence chain):
- PM SQL 语法错(命令含 `json_object('gpt_weights', '...')` 但写入时被 sqlite cast 成别的形态)?
- PM 漏跑 SQL(只切 provider · 没复制完整 SQL)?
- PM 跑了但 hot reload 期间被覆盖?
- DB lock / concurrent write 失败?

**不深追决定**:Stage 1.5 后 PATCH endpoint 真写完整 schema(用 buildVoiceModelJson + modelMeta spread)· 老 V2'' 旧 schema 自然 phase out · 这个 unknown 失去现实意义。

**Lesson(轻量)**:**SQL UPDATE 命令给 PM 时应同时给 SELECT verify 命令** + **CC 实施前先 audit DB 真态而不是 trust PM 报的状态**(per Lesson INV-11 #1 / smoke test restore baseline 同源)。

---

→ **Stage 1.5 ship closed · CC 异步 4 step ~2.5h 完成 · PM 起床跑 §13.4 4 step ~5 min 真机 demo + cosyvoice ↔ gsv 切换 verify · Stage 1.5 全闭环**。

