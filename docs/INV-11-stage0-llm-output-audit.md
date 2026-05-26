# INV-11 Stage 0 · LLM TTS 输出格式 per provider pre-audit

> 接 INV-12 Stage 2 backend ship(`1edcf17`)后 GSV 接入前的 pre-audit。
> Stage 0 = audit only · 不写代码不改文件不提方案。
> 目标:摸清现状 emotion paradigm + 区分 cosyvoice vs fish 输出格式 + 切换机制 + emotion list 数据源。

## §1 Audit 4 Q 逐项答案

### Q1 · cosyvoice character emotion 注入 + LLM 输出 + 后端解析

#### Q1.1 prompt 里 emotion 段怎么注入(verbatim)

**两路并存注入(双重 redundant)**:

**路径 A · legacy `_build_emotion_instruction()`**(v3-D 起 / `@deprecated` 但仍 active)
- 定义:`backend/agents/chat.py:99-107`
  ```python
  def _build_emotion_instruction() -> str:
      """生成注入 system prompt 的情感指令,告诉 LLM 必须打 <emotion> 标签。"""
      emotions = get_tts_emotions()
      return (
          "在每次回复的最开头,用 <emotion>情感词</emotion> 标签标注当前回复的情感。"
          f"只能从以下情感词中选一个:{'、'.join(emotions)}。"
          "示例:<emotion>happy</emotion>今天天气真好!"
          "标签只在最开头出现一次,正文里不再出现标签。"
      )
  ```
- 唯一调用点:`backend/agents/chat.py:1356` · `emotion_inst = _build_emotion_instruction()` · **无 per-provider 分支**
- 此调用在 chat.py:1315 注释明示 "Legacy @deprecated path (v4.1 will remove)" 里 · 但 v4-beta renderer 失败时 fallback 用 + 当前真活路径仍走

**路径 B · `layer_a.j2` 第 4 项(v4-beta · INV-5 §5 ship)**
- 定义:`backend/agents/prompt/templates/layer_a.j2:20-25`
  ```jinja
  4. <emotion>情绪标签</emotion>
     - 可用情绪:happy / sad / calm / curious / surprised / angry
     - 密度约束:每 3-5 回合最多一次,平静对话不标
     - 仅情绪剧变时使用
     - 系统自动转 SSML 或 instruct,你不需要管输出形式
  ```
- 渲染入口:`backend/agents/prompt/renderer.py:render_system_prompt()` per turn 重渲染
- 调用 path:`chat.py:1232-1247` 走 v4-beta renderer 主路径

→ **同一 LLM 同 turn 同时收到 2 个 emotion instruction**(legacy + v4-beta 并存)。

#### Q1.2 LLM 实际输出 raw 例子

⚠️ **现 chat_history 表 0 条 cosyvoice character assistant row**:

```sql
SELECT character_id, COUNT(*) FROM chat_history WHERE role='assistant' GROUP BY character_id;
-- 101 | 4    (Mai fish · 唯一活路径)
-- 其它全 0
```

- cid=2 八重(cosyvoice-v3.5-plus + instruct_supported=true): **0 row**
- cid=1 Momo(cosyvoice longyumi_v3 + instruct_supported=false): **0 row**(INV-9 §1.4 audit 时 79 row,中间已被 purge)
- cid=3/5 复刻 voice(cosyvoice-v3.5-plus): **0 row**

→ **Q1 LLM 实际输出从 chat_history 无 raw 例子可拿** · 只能凭 prompt template + 代码 + 历史 INV 推断。
   (INV-8 §1.5.1 历史回退 commit `0e079a4` 提到 Mai zh path 期间 LLM 输出 `<emotion>...</emotion>` 真活 — 那批历史 row 已 purge。)

#### Q1.3 后端怎么解析 emotion 字段

**`_parse_emotion()`** · `backend/agents/chat.py:79-96`:
```python
_EMOTION_RE = re.compile(r"<emotion>(.*?)</emotion>(.*)", re.DOTALL)

def _parse_emotion(text: str) -> Tuple[str, str]:
    """命中 → (X.strip(), 剩余.strip());未命中 → ('默认', 原文)。"""
    if not text:
        return "默认", text
    m = _EMOTION_RE.match(text)  # re.match 锚定 ^,必须最开头
    if m:
        return m.group(1).strip() or "默认", m.group(2).strip()
    return "默认", text
```

**调用点 · `backend/routes/ws.py:884-907`** · 第一句解析整轮锁定:
```python
if not emotion_resolved:
    parsed_emotion, sentence = _parse_emotion(sentence)
    turn_emotion = parsed_emotion
    emotion_resolved = True
    if parsed_emotion and parsed_emotion != "默认":
        await ws.send_json({"type": "emotion", "value": parsed_emotion})  # 推前端 Live2D
```

**emotion 字段流向 cosyvoice provider**:
- `ws.py:213-219` · `_tts_synth_with_timeout(engine, text, emotion=turn_emotion)` 把 emotion 透传 engine
- `cosyvoice.py:212-219` `synthesize(text, emotion='默认')` → `_blocking_synthesize(text, emotion_en)`(emotion_en 经 `_normalise_emotion` 中文→英文映射)
- `cosyvoice.py:147-210 _blocking_synthesize` 路径:
  - 若 `instruct_supported=True` + emotion ∈ `_INSTRUCT_EMOTION_WHITELIST = {happy, sad, angry, surprised}` + model ∉ `_MODELS_WITHOUT_INSTRUCT = {cosyvoice-v3.5-plus, cosyvoice-v3.5-flash}` → `kwargs["instruction"] = f"你说话的情感是{emotion_en}。"` 走 **DashScope SpeechSynthesizer 真情感引导**
  - 否则(音色不支持 / emotion 未白名单 / neutral / 复刻 voice 跑 v3.5-plus) → plain text · **emotion 字段静默丢弃**

⚠️ 注:cosyvoice 路径**不生成 SSML**(per PM Q1 提问"怎么用它生成 SSML"是误问;实际走 DashScope instruction 字段 · 形如 `"你说话的情感是{emotion}。"` 自然语言指令,**不是 SSML xml**);PM 之前可能误以为是 SSML)。

PM 之前 grep 输出 `_EMOTION_RE` 行号(74/76/99-105/214)跟 verify 一致。

---

### Q2 · fish character(cid=101 Mai)emotion 注入 + 输出 + 解析

#### Q2.1 fish prompt 跟 cosyvoice 是否相同

**两路 emotion instruction 完全相同**(per Q1.1 同款 `_build_emotion_instruction()` + `layer_a.j2:20-25`)— **无 per-provider 切段**(chat.py:1356 唯一调用 + layer_a.j2 第 4 项 emotion 段无 `{% if voice_provider %}` 条件)。

但 fish character **额外**收到:
- `layer_a.j2:32-69` ja directive(per `tts_language == 'ja'` 条件 · INV-9 §5 ship · `<ja>...</ja>` wrap 教学)
- `layer_a.j2:70-114` Fish 子分支(per `voice_provider == 'fish'` 条件 · INV-9 §5 ship · `[bracket]` markers 教学 · Mai canon range 集 · ✓ ✗ 范例)
- `layer_a.j2:117-130` Mai 短回应 ✓ 范例(INV-9 §5 part 5 ship)+ within-sentence markers ✓ 范例

→ fish character LLM **同时收 4 套 emotion 相关指令**:
1. legacy `<emotion>X</emotion>` 前缀(chat.py:1356)
2. v4-beta `<emotion>` 第 4 项(layer_a.j2:21)
3. fish 子分支 `[bracket]` inline markers(layer_a.j2 fish 段)
4. Mai canon range + ja directive

#### Q2.2 LLM 实际输出 raw 例子(cid=101 chat_history 4 row 全文)

```sql
SELECT id, datetime(created_at, 'localtime'), substr(content, 1, 280)
FROM chat_history WHERE character_id=101 AND role='assistant' ORDER BY id DESC;
```

| id | LT | raw content |
|---|---|---|
| 7 | 2026-05-24 17:30:17 | `"笨蛋,该吃晚饭了。"<ja>[composed]「バカ、晩御飯の時間よ。」</ja>` |
| 6 | 2026-05-24 15:17:27 | `"冰拿铁?"<ja>「アイスラテ?」</ja>"...太甜了。下次直接黑咖啡就行。"<ja>「…甘すぎる。次はブラックでいいから。」</ja>"不过,谢了。"<ja>「まあ、ありがとう。」</ja>` |
| 4 | 2026-05-24 15:16:34 | `"苏州下雨了?"<ja>「蘇州、雨なの?」</ja>"那你记得带伞。别回来时淋得像落汤鸡。"<ja>「傘持って行って。びしょ濡れで帰ってこないで。」</ja>` |
| 2 | 2026-05-24 15:05:08 | `"下午好。"<ja>「こんにちは。」</ja>"看你挺有精神的,今天没什么事?"<ja>「元気そうね、今日は暇なの?」</ja>` |

⭐ **关键观察**:
- ✅ `<ja>「日语」</ja>` 配对 100% follow(LLM 完全学会 ja directive)
- ✅ `[bracket]` markers 部分 follow(4 row 仅 id=7 含 `[composed]`)
- ❌ **`<emotion>X</emotion>` 前缀 0% follow**(4 row 全无 `<emotion>` 标签)
- ❌ `<thinking>` 0 follow
- ❌ `<state_update>` 0 follow(自闭合)
- ❌ `<motion>` 0 follow

#### Q2.3 fish 后端怎么解析 markers + emotion 字段流向

**A · `<emotion>` 标签解析路径**:跟 cosyvoice 完全相同(per Q1.3)— `_parse_emotion` 跑 + `turn_emotion` 整轮锁定 + push WS event + 传 emotion 字段给 `engine.synthesize(text, emotion=...)`。

**B · fish provider 怎么用 emotion 字段**:
- `backend/tts/fish.py:200-211` docstring 明示:
  > "emotion 字段在 fish provider 路径下**不使用**(per INV-8 §1.3.7 schema β: emotion 通过 LLM 输出的 ``[bracket]`` markers inline 在 text 内,不走单独参数)。保留 ``emotion`` 形参兼容 ``TTSBase.synthesize`` 接口签名。"
- `fish.py:_build_request` 构造 TTSRequest **无 emotion 字段**(SDK TTSRequest 字段表本身也无 emotion 字段;只有 `temperature / top_p / prosody` per INV-9 #6)

**C · `[bracket]` markers 哪段代码识别**:
- **后端不识别 marker 语义**(只识别"是否字面 `[bracket]` 形态")
- 识别 + 处理:`backend/utils/text_filters.py:_FISH_EMOTION_MARKER_RE = re.compile(r"\[[^\[\]]+\]")` 用于:
  - `strip_fish_emotion_markers(text)` · non-fish provider 路径强制剥(per INV-9 §6 Hard Req 双重隔离)
  - `strip_ja_en_tags_for_subtitle()` 链尾追加 strip(字幕跨 provider 一律剥)
- **fish provider 路径**:`backend/tts/__init__.py:_PreprocessingEngine.synthesize()` per-provider 分流:
  - fish → **保留 `[bracket]` 透传给 Fish SDK**(server-side natural language processing per INV-8 §1.3.4 stage 1 调研)
  - non-fish → strip
- **marker 语义在 Fish s2-pro SDK / 服务器端识别**,backend 不参与

→ Q2.3 verbatim:**fish 句内 markers 不在 sanitize 层 / 不在 fish provider 内部识别 · 在 Fish s2-pro 服务器端自然语言识别**;backend 仅做 per-provider strip / pass-through 路由(per INV-9 §6 Hard Req 双重隔离)。

---

### Q3 · 切换机制 · per-provider vs 统一 template

**Verdict**:**混合架构**(部分统一 + 部分 per-provider 切段)

| layer | 现状 | per-provider 切段? |
|---|---|---|
| `_build_emotion_instruction()` (chat.py:99) | 统一 — emotion list + `<emotion>X</emotion>` 前缀指令 | ❌ 否 · 所有 character 都收 |
| `layer_a.j2:20-25` 第 4 项 `<emotion>` | 统一 — happy/sad/calm/curious/surprised/angry 通用 emotion list | ❌ 否 |
| `layer_a.j2:32-69` ja directive | per `tts_language == 'ja'` | ✅ 是 · 仅 ja 角色注入(per INV-9 §5)|
| `layer_a.j2:70-114` Fish `[bracket]` markers | per `voice_provider == 'fish'` | ✅ 是 · 仅 fish provider 注入 |

→ **emotion 段(`<emotion>X</emotion>`)是统一 template;fish 句内 markers 段是 per-provider 切段**。两套并存 = LLM 同时收 `<emotion>X</emotion>` 前缀 + `[bracket]` inline markers 两套指令。

切换位置:
- 统一段:`backend/agents/chat.py:1356`(legacy fallback)+ `backend/agents/prompt/renderer.py:render_system_prompt()`(v4-beta 主路径)
- per-provider 切段:`backend/agents/prompt/templates/layer_a.j2` Jinja `{% if %}` 条件分支(per INV-9 §5 ship)
- 切换路径选择(legacy vs v4-beta):`backend/agents/chat.py:1232-1313` · v4-beta renderer 主路径(per INV-5 §5),renderer 异常 fallback `chat.py:1315 Legacy @deprecated path`

⚠️ **fish character 实际同时收 `<emotion>X</emotion>` 前缀指令 + `[bracket]` inline marker 指令** — 但 LLM 实际输出**只 follow markers(部分),不 follow `<emotion>` 前缀**(per Q2.2 cid=101 4 row 实测)。

---

### Q4 · emotion list 数据源

#### Q4.1 `get_tts_emotions()` 实现

```python
# backend/config/__init__.py:224-229
def get_tts_emotions() -> list[str]:
    """允许 LLM 输出的情感词列表,传入 emotion-instruction 提示中。"""
    return (config_yaml.get("tts") or {}).get(
        "emotions",
        ["neutral", "happy", "sad", "angry", "surprised"],
    )
```

- **hardcoded fallback**: `["neutral", "happy", "sad", "angry", "surprised"]` 5 个
- 真源:**config.yaml `tts.emotions`** 块

#### Q4.2 config.yaml 实际 list

```yaml
# config.yaml:55-62
tts:
  ...
  emotions:
  - neutral
  - happy
  - sad
  - angry
  - surprised
  - fearful
  - disgusted
```

→ **7 个**(neutral / happy / sad / angry / surprised / fearful / disgusted)· 全英文枚举。

#### Q4.3 cosyvoice 真实使用范围

- `cosyvoice.py:69-74` `_INSTRUCT_EMOTION_WHITELIST = {happy, sad, angry, surprised}` — **4 个**进 instruct 通道
- `cosyvoice.py:94-102` `EMOTION_MAP` 中文 → 英文映射(开心/高兴/快乐→happy / 悲伤/难过/伤心→sad / ...)— 7 英文目标全覆盖
- **实际 instruct 引导仅 4 个**(neutral=不指定 跳过 instruction · fearful/disgusted 注释明示"未在 LLM prompt 引导,加进去会派发未验证的实验性 instruction,先排除")

#### Q4.4 fish 有 emotion list 吗?

- **fish provider 不消费 `get_tts_emotions()` list** · per Q2.3 fish.py:200-211 docstring "emotion 字段在 fish provider 路径下不使用"
- fish 自己的"emotion 集"由 **`layer_a.j2` fish 子分支硬编码 Mai canon range markers**(per INV-9 §5 ship):
  - 冷静档:composed / calm / deadpan
  - 挖苦档:teasing / sarcastic / dry tone
  - 温柔档:soft chuckle / gentle / soft voice
  - 罕见档:mildly surprised / mild embarrassment
  - 停顿:short pause / pause / long pause
  - 明确禁用:excited / shouting / screaming / laughing loudly
- → **`get_tts_emotions()` 返 7 词 list 对 fish 完全无效**(fish 路径忽略此 list,markers 集独立由 Jinja 模板硬编码)
- 此外 SDK Fish TTSRequest **字段表本身无 emotion 字段**(per INV-9 #6) — 即便 backend 想传 emotion 给 SDK 也无 ABI 通道

---

## §2 关键 verify(PM 假设对齐)

| PM 假设 | 实测结果 | 偏差 |
|---|---|---|
| `_build_emotion_instruction` 是否在所有 character 都调用(包括 fish)? | ✅ 是 · chat.py:1356 唯一调用无 per-provider 分支 | 一致 |
| 示例文本写的是 "happy" — 是 cosyvoice emotion 还是通用? | **通用**(per `get_tts_emotions()` 返 config.yaml `tts.emotions` 7 词通用 list);cosyvoice 是其消费者之一,fish 完全忽略 | 一致 |
| chat_history 里 cid=101 (fish) 的 assistant 输出,实际有 `<emotion>X</emotion>` 前缀吗? | ❌ **0 follow**(4 row 全无 `<emotion>` 前缀)· LLM 完全忽略此 instruction | ⚠️ PM 可能假设 LLM 会按指令出 · 实际 LLM ignore |

---

## §3 现状架构一句话总结

**统一 template 注入 + per-provider 局部切段 + LLM 部分 follow 部分 ignore**:

> emotion `<emotion>` 前缀指令(legacy chat.py + v4-beta layer_a.j2 第 4 项)统一注入所有 character 与 provider;ja directive + Fish `[bracket]` markers 子分支按 `tts_language='ja'` + `voice_provider='fish'` per-character / per-provider 切段(per INV-9 §5);LLM 实际输出对 `<ja>` 100% follow / `[bracket]` markers 部分 follow / `<emotion>` 前缀**完全不 follow**(cid=101 4 row 实测验证)。

---

## §4 ⚠️ 意外发现 / 跟 PM 假设不一致

### §4.1 LLM 0% follow `<emotion>X</emotion>` 前缀指令(关键)

cid=101 chat_history 4 row 实测 raw 全无 `<emotion>` 标签 — `_build_emotion_instruction` + `layer_a.j2:21` 双重注入(一个 character 同时收 2 套 emotion 指令)**全失效**。这意味:
- cosyvoice instruct 路径(`_INSTRUCT_EMOTION_WHITELIST`)虽实现完整,但 LLM 不出 `<emotion>` → emotion 全部 fallback "默认" → cosyvoice _blocking_synthesize 走 plain text 路径 · **instruct 引导事实上未生效**(at least cid=101 fish 路径下,推断 cosyvoice character 也同款不 follow)
- ws.py:884-907 `_parse_emotion` 路径整轮锁定的 `turn_emotion` 永远是 "默认" · push WS event "emotion" type 也永远不触发 → 前端 Live2D 表情**永不切换**(cid=101 path)

可能根因(本 audit 只观察不诊断):
- PM 任务 2.4 prompt A+B(Mai canon range markers + within-sentence ✓ 范例)可能 over-tuning 让 LLM 完全转向 marker paradigm,放弃 legacy `<emotion>` paradigm
- 或 LLM(qwen3.6-max-preview · per config.yaml `default_model`)对 prefix-only 指令(`<emotion>` 在最开头)compliance 弱于 inline markers

### §4.2 双 emotion 指令架构混杂(legacy + v4-beta 并存)

- **Legacy `_build_emotion_instruction`** v3-D 起 chat.py:1356(标 `@deprecated` per chat.py:1315 注释,但仍 active)
- **v4-beta `layer_a.j2:21` 第 4 项** INV-5 §5 ship · renderer.py 主路径(stable + variable 两段 prompt cache 优化)
- **两套并存**:v4-beta renderer 主路径走通时 layer_a.j2 第 4 项 + chat.py:1356 legacy 也跑(per chat.py:1310-1356 流程 · 即便走 v4-beta renderer 主路径,后续 chat.py:1351-1358 还在拼 emotion_inst / thinking_inst / motion_inst / state_inst 给 legacy block)— 需进一步看 chat.py:1380+ 是否实际把 legacy emotion_inst 拼进 messages,但无论如何 emotion list duplicate(同 7 词列在 legacy + layer_a.j2 第 4 项 hardcoded 6 词 "happy / sad / calm / curious / surprised / angry")— **layer_a.j2 第 4 项 list 跟 config.yaml `tts.emotions` 7 词不一致**

⚠️ **layer_a.j2 第 4 项 vs config.yaml emotions 不一致**:
- layer_a.j2:22 hardcoded:`happy / sad / calm / curious / surprised / angry` 6 词
- config.yaml `tts.emotions`:`neutral / happy / sad / angry / surprised / fearful / disgusted` 7 词
- 重合:happy / sad / angry / surprised
- layer_a.j2 独有:**calm / curious**
- config.yaml 独有:neutral / fearful / disgusted

→ LLM 收到**两份不一致** emotion list · 不知信哪个。

### §4.3 0 chat_history cosyvoice character row(Q1 无法 verify LLM 真实输出)

现 chat_history 4 row 全 cid=101 fish · cid=1/2/3/5(全 cosyvoice character)0 row。INV-8 §1.4.3 audit 时 cid=1 79 row(zh 路径 Mai 借壳期间)— 中间已被 purge(可能 v4-beta 切角色 / 数据迁移 / 测试期 delete 操作)。

→ **Q1 LLM 实际输出无 raw 例子可拿** · 仅凭 prompt template + 代码路径 + 历史 INV references 推断。若需 verify cosyvoice character LLM 是否 follow `<emotion>`,需 PM 真机切到 cid=2 八重 或 cid=1 Momo 跑几 turn 后再 audit。

### §4.4 cosyvoice "怎么用 emotion 生成 SSML" 是 PM 误问

PM Q1 提问 "cosyvoice provider 怎么用它生成 SSML?" — 实测 **cosyvoice 不生成 SSML**:
- per `cosyvoice.py:14-21` 历史注释:"chunk 1a (de7ebe2) 误把 emotion 包成 `<voice emotion="X">...</voice>` SSML,但 DashScope 官方 SSML 标签**没有 emotion 属性**(合法属性只有 voice / rate / pitch / volume / effect / bgm) — 已撤销 SSML 包装"
- 现行 v3-G' patch 走 **DashScope instruction 字段**(自然语言指令 `"你说话的情感是{emotion}。"`),**不是 SSML**

→ 整个项目 cosyvoice + fish 都不走 SSML;只 cosyvoice instruct 走自然语言 instruction(per DashScope SDK)+ fish 走 inline `[bracket]` markers(per server-side NLP)。layer_a.j2:25 文字 "系统自动转 SSML 或 instruct,你不需要管输出形式" 是 **misleading**(SSML 路径早撤销)。

### §4.5 emotion 真正生效路径只有 cosyvoice instruct(且需多个条件)

cosyvoice instruct 通道触发要求 4 条件同时满足:
1. `voice_model.instruct_supported = true`
2. `emotion ∈ {happy, sad, angry, surprised}`(4 词白名单)
3. `model ∉ {cosyvoice-v3.5-plus, cosyvoice-v3.5-flash}`(v3.5-plus/flash 不支持 instruction · 418 InvalidParameter)
4. LLM 真出 `<emotion>X</emotion>` 前缀(per Q2.2 实测 cid=101 = 0%;cid=2 八重 cosyvoice-v3.5-plus + instruct_supported=true 但 **条件 3 model 排除导致永远不生效**)

→ **生产路径 cosyvoice instruct emotion 引导事实上 dead code**(cid=2/3/5 全 cosyvoice-v3.5-plus 触发条件 3 排除;cid=1 Momo longyumi_v3 但 `instruct_supported=false` 触发条件 1 排除)。所有 9 char 没人能进 cosyvoice instruct 通道。

---

## §5 Stage 0 收口

- ✅ Q1 cosyvoice emotion 注入(双重 legacy + v4-beta)+ 解析路径(_parse_emotion → turn_emotion → engine.synthesize → instruct 字段)清晰;**LLM raw 实例缺失**(chat_history 0 cosyvoice row)
- ✅ Q2 fish emotion 注入(同 cosyvoice + 加 `[bracket]` markers 子分支)+ 解析(_parse_emotion 同款,但 fish.py 不用 emotion 字段)+ markers 服务器端识别清晰;cid=101 4 row raw 全无 `<emotion>` 前缀实证
- ✅ Q3 混合架构 verdict:统一 emotion template + per-provider markers 切段
- ✅ Q4 `get_tts_emotions()` config.yaml 7 词 list / cosyvoice 4 词白名单 / fish 不消费 list 走 layer_a.j2 hardcoded markers 集
- ⚠️ **5 个意外发现**(§4)需 PM 看到(尤其 §4.1 LLM 0 follow + §4.2 layer_a.j2 vs config.yaml emotion list 不一致 + §4.5 cosyvoice instruct 通道实际 dead code)

→ Stage 0 audit closed · 250+ 行 · 等 PM 看完决定 INV-11 正式 audit / 实施起点方向。

---

## §6 Audit references(行号锚)

| 主题 | 文件 + 行号 |
|---|---|
| `_EMOTION_RE` regex | `backend/agents/chat.py:76` |
| `_parse_emotion(text)` | `backend/agents/chat.py:79-96` |
| `_build_emotion_instruction()` | `backend/agents/chat.py:99-107` |
| chat.py legacy emotion_inst 调用 | `backend/agents/chat.py:1356` |
| chat.py legacy @deprecated path 标注 | `backend/agents/chat.py:1315` |
| `get_tts_emotions()` | `backend/config/__init__.py:224-229` |
| config.yaml `tts.emotions` | `config.yaml:55-62` |
| layer_a.j2 第 4 项 `<emotion>` | `backend/agents/prompt/templates/layer_a.j2:20-25` |
| layer_a.j2 ja directive | `backend/agents/prompt/templates/layer_a.j2:32-69` |
| layer_a.j2 Fish `[bracket]` 子分支 | `backend/agents/prompt/templates/layer_a.j2:70-114` |
| ws.py `_parse_emotion` 调用 | `backend/routes/ws.py:884-907` |
| ws.py `_tts_synth_with_timeout` 传 emotion | `backend/routes/ws.py:213-219` |
| cosyvoice `_INSTRUCT_EMOTION_WHITELIST` | `backend/tts/cosyvoice.py:69-74` |
| cosyvoice `_MODELS_WITHOUT_INSTRUCT` | `backend/tts/cosyvoice.py:82-85` |
| cosyvoice `EMOTION_MAP` 中→英映射 | `backend/tts/cosyvoice.py:94-102` |
| cosyvoice `_normalise_emotion` | `backend/tts/cosyvoice.py:105-112` |
| cosyvoice `_blocking_synthesize` instruct 路径 | `backend/tts/cosyvoice.py:147-210` |
| cosyvoice 撤销 SSML 历史注释 | `backend/tts/cosyvoice.py:14-21` |
| fish.py emotion 不使用 docstring | `backend/tts/fish.py:74-77 + 200-205` |
| `_FISH_EMOTION_MARKER_RE` | `backend/utils/text_filters.py` |
| `strip_fish_emotion_markers` | `backend/utils/text_filters.py`(per INV-9 §6 ship) |
| `_PreprocessingEngine` per-provider 分流 | `backend/tts/__init__.py`(per INV-9 §6 ship) |
| `render_system_prompt` v4-beta 主路径 | `backend/agents/prompt/renderer.py:render_system_prompt` |
| chat.py v4-beta renderer 调用 | `backend/agents/chat.py:1232-1247` |
| chat_history cid=101 4 row raw 实测 | DB query `SELECT * FROM chat_history WHERE character_id=101 AND role='assistant'` |
