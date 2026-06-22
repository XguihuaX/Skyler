# Skyler 角色卡 Schema 调研报告

**对比对象**:SillyTavern(酒馆)角色卡 V2/V3 · 业界标准
**审计对象**:Skyler `character_personas` 真实 schema(CC 只读调查,基于实际 DB + 装配代码)
**日期**:2026-06-22
**目的**:在为新角色写 persona 之前,弄清我们自己的卡结构、和业界标准的差异、有没有值得借鉴或必须修的地方;为「是否/如何改造 schema」做决策依据。
**结论先行**:我们的 schema 结构本身是好的,没输给酒馆结构;真正的债是**三个死字段 + 文档漂移**,不是结构。schema 改动归 post-video,但本报告直接影响**写新角色时劲往哪使**。

---

## 1. SillyTavern 酒馆卡(业界标准)

- **是什么**:JSON 内嵌 PNG 元数据(tEXt chunk,base64),"图是装饰、元数据是载荷"。可移植、model-agnostic、社区分享(Chub.ai),任何兼容前端(SillyTavern / RisuAI / Janitor 等)通吃。
- **核心字段(V2)**:`name` / `description`(最大字段,自由散文,什么都往里塞)/ `personality`(短摘要)/ `scenario` / `first_mes`(开场,对行为影响最大,模型当模板学)/ `mes_example`(示例对话,教音色+回合形状)/ `system_prompt` / `post_history_instructions` / `depth_prompt`(指定注入深度)/ `alternate_greetings` / `character_book`(lorebook,关键词触发注入)/ `tags` / `extensions`。
- **V3 增量**:嵌套 `data` 块、`assets`(表情 sprite / 背景 / voice 样本)、token 高效选择性加载、`{{random}}`/`{{roll}}` 宏。
- **设计哲学**:可移植的**静态 prompt 容器**,自由散文为主,为"一张分享卡跑任何模型/前端"优化。
- **配套**:28 表情 sprite(按情绪切换,需单独做 28 张图)。

---

## 2. Skyler 真实 schema(`character_personas`,18 列)

**元数据(9)**:`id` / `character_id` / `variant_name` / `is_builtin` / `is_active` / `display_order` / `description` / `created_at` / `updated_at`
约束:`UNIQUE(character_id, variant_name)`;单 active 硬约束(唯一索引 WHERE is_active=1)。

**Tier-1 必填(7 列,TEXT JSON,解析失败直接 raise)**
`identity` / `personality_core` / `speech_style` / `signature_phrases` / `voice_samples` / `forbidden_phrases` / `relationship_to_user`

**Tier-2 可选(4 列,NULL 兜底)**
`taboo_topics` / `lore` / `capability_overrides` / `style_preset`(默认 `anime_classic`)

**真实 JSON 结构(举例,以麻衣为准)**
- `voice_samples` = `[{ scene, text, tolerance_range:[lo,hi] }]` × ~12
- `taboo_topics` = `{ hard_no:[{topic, her_reaction}], soft_no:[...] }`
- `lore` = `{ preferences:{likes/dislikes/secretly_appreciates}, emotion_triggers:{<情绪>:{ssml_tag, intensity, triggers, expression}} }`
- `forbidden_phrases` = `{ _global, _character, _qwen, _deepseek }`

> ★**文档漂移(必修债)**:persona-builder skill 文档说 Tier-2 = `preferences / taboo / emotion_triggers`,但真实列是 `taboo_topics / lore / capability_overrides / style_preset`;`preferences` 和 `emotion_triggers` 实际是嵌在 `lore` JSON 里的 sub-key,**没有独立列**。且 skill 引用的 `reference/schema.md` 等文件已不存在。

---

## 3. persona → prompt 装配(真实逻辑)

链路:`chat.py: render_system_prompt` → `renderer.py` → `persona_loader.load_active_persona` + 6 个 j2 模板。

**真正生效的逻辑**
- `voice_samples` **按 `tolerance_range` 过滤是真有效的**(`renderer.py:73-110`):从 `speech_style.cliche_tolerance`(麻衣 0.35,缺失回退 0.5)读糖度,落区间内的命中;无 range 视为 `[0,1]` 全命中;filter 后 0 条 → 兜底回全集(防风格锚点丢失)。麻衣 0.35 命中约 10/12。
- `identity.self_intro` 双梯级:`intimacy ≥ 70` 切 `['70-100']`,否则 `['0-69']`。
- `lore` **不是 always-on 全塞**:装配只解构 `lore.preferences` + `lore.emotion_triggers` 两个固定 sub-key,其余顶层键被忽略(= dead JSON)。
- `emotion_triggers` 渲染**屏蔽 `ssml_tag`**:避免 LLM 看到两套 emotion 词表(Layer A1 的 16 中文 vs lore 的 6 英文)。
- `forbidden_phrases` **vendor-aware**:`_global` + 当前模型分支(`_qwen`/`_deepseek`)+ `_character`。
- stable / variable 切分:A+B+C-stable 进 cache 前缀,C-runtime(now/mood/intimacy/activity)+D 不进。

> ★**三个"死字段"(load 了但 0 模板引用)**
> - `relationship_to_user`(**还是必填!填了白填** —— 麻衣的 companion/slow/intimacy=20 没进上下文)
> - `capability_overrides`
> - `style_preset`(麻衣 = 'mixed',只在 DB 元数据层活着)

---

## 4. 头对头对比

| 维度 | 酒馆卡(V2/V3) | Skyler 卡(`character_personas`) |
|---|---|---|
| 存储/可移植 | PNG 内嵌、可分享、跨前端通吃 | DB 存、绑定运行时、不可移植、多 variant 一个 active |
| 结构 | 大段自由散文(description 最大)+ 短 personality | 强类型分层 schema,字段机器可寻址、可运行时过滤 |
| 静态 vs 活态 | 全静态;状态靠对话历史 + lorebook 注入 | persona 一层,外套 mood/intimacy/activity + DailyAgent 自主日程 |
| 范围 | 卡 = 角色+世界整包(含 scenario、lorebook) | persona = 一块砖,世界/能力/状态都是解耦层 |
| 反 AI 腔 | 靠 description + 越狱 + 示例示范,无专门机制 | `forbidden_phrases` 四桶(`_character` + `_<模型>`)= 显式禁语 |
| 多模态 | V2 纯文本;V3 才加 assets,很多前端不读 | `emotion_triggers` 原生 hook TTS(情绪标记)+ Live2D(`<emotion>` 三通道) |
| 亲密度 | 无内建梯度 | `self_intro` 按 intimacy 分桶,称呼随关系变 |
| 糖度控制 | 无 | `cliche_tolerance` + `tolerance_range` 运行时过滤 voice_samples(前端滑块=真旋钮) |

---

## 5. 发现与判断

1. **我们 schema 结构是好的** —— 过滤工作、vendor-aware 禁语、亲密度分桶、选择性 lore,都是真生效的设计。**没输给酒馆结构。**
2. **真正的债 = 三个死字段 + 文档漂移**,不是结构问题。
3. **lore 没有 always-on 全塞**(选择性 destructure)→ 原本设想的"懒 lore 注入"改造**没必要**。
4. **麻衣 persona JSON 才 ~4KB**(很瘦);16k prompt 膨胀在**装配层**(模板/16 情绪表/few-shot),不在 persona 数据 → "瘦身麻衣 persona"基本是伪命题,真要省看装配。
5. **值得借鉴**:交换式示例(酒馆 `mes_example`)—— 我们的 voice_samples 是孤立台词、只教音色;增加"用户↔角色"交换形可教**回合形状**(长度/`*动作*`/怎么接话)。**零 schema 成本**。
6. **别删的边界**:`forbidden_phrases` / `emotion_triggers`→TTS·Live2D / 亲密度分桶 / cliche 旋钮 —— 酒馆全没有,是 Skyler 角色卡的存在理由。

---

## 6. build-vs-buy 叙事(portfolio)

酒馆卡是为**分享 / 通用前端**设计的静态 prompt 容器;Skyler 要的是**绑定语音 + Live2D + 状态 + 日程的活态角色,且对客服腔零容忍** —— 所以自建了带禁语机制和多模态 hook 的结构化 schema。
> 面试问"为啥不直接用酒馆现成卡":build-vs-buy 按**层**拆 —— 通用件(模型 / TTS / MCP)buy,**角色编排核心**(为具身角色服务的能力编排 + 反 AI 腔机制)build。

---

## 7. ROADMAP 项(建议)

**Persona Schema v2(post-video)**
- 修死字段:`relationship_to_user` —— 要么接进模板、要么砍掉必填;`capability_overrides` / `style_preset` 同理(接入或移除),别让必填字段做无用功。
- 修文档漂移:重写 persona-builder skill 的 schema 文档以匹配真实 18 列,补回缺失的 `reference/`。
- 借交换式示例:`voice_samples` 增加"用户↔角色"形式以教回合形状(纯作者约定,无需改 DB)。

**保持不变**:`forbidden_phrases`、`emotion_triggers`、亲密度分桶、`cliche_tolerance` 过滤。

**跨任务关联**:做 TTS provider 重写(接入 Fish S2-Pro)时,注意 emotion 词表统一 —— 已有两套(Layer A1 的 16 中文 vs lore 的 6 英文),别引入第三套,Fish 情绪标记应映射到现有词表。

---

*本报告供 ROADMAP「Persona Schema v2」backlog 项引用。建议 repo 落点:`docs/research/persona-schema-comparison.md`。*
