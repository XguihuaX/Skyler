# v4 Persona Engineering — Segment 2 前置 Audit 发现

> Phase 0 deliverable。**未写任何代码、未跑 migration、未改 schema。**
> 用户 sign-off 后才进 Phase 1。

---

## 0.1 现有角色管理 UI

### 入口位置(主编辑器)

**`frontend/src/components/CharacterPanel.tsx`** —— 11 处 persona 引用。"角色提示词" textarea 是**当前唯一的 persona 编辑入口**:

| 行 | 用途 | 删除策略 |
|---|------|---------|
| 117 | `type Form` 含 `persona: string` 字段 | Tier-1 7 字段不再走 form,改成只读显示已 active variant 名 |
| 130 | form 默认值 `persona: ''` | 删 |
| 234 | comment "拼到每个角色 persona 之前生效" | 改文案 |
| 561 | 加载时 `persona: c.persona` | 删 |
| 574-579 | **validation:`if (!name \|\| !persona)`** | **persona 不再 required**,改成只校验 name |
| 588 / 598 | POST/PUT body 含 `persona` | 删字段,backend Character.persona 不再被 frontend 写 |
| 640 | `formValid = !!form && form.name.trim() && form.persona.trim()` | 去掉 persona.trim() 项 |
| 706-708 | **列表预览**显示 `c.persona.slice(0, PERSONA_PREVIEW_LEN)` | 改成显示 active variant.identity.name(eg "默认 / 樱岛麻衣") |
| 841-851 | **textarea `角色提示词 *`** | **整段删除**(就是 spec 4.1 要清除的入口) |

### 周边显示(只读 modal)

**`frontend/src/components/character/CharacterDetailModal.tsx`** —— 5 处 persona 引用,全是**只读显示**:line 55(state)、81-85(load+truncate)、166-188(render + 「展开全部」展开按钮)。

→ 决策点 **D-S2-1**:这个 modal 还要不要保留旧 persona 显示?现在 DB 字段还在(向后兼容)但已过时(Mai 实际人设走 character_personas)。**推荐**:整段删,改成展示 active variant `identity.name + description + style_preset`。

### 类型定义

**`frontend/src/lib/config.ts`** —— 3 处 `persona: string` 类型(行 100 / 159 / 190)。删 form 字段但**保留类型字段**(API 仍返回 character.persona 做 DB schema 兼容)。

### TTS / Live2D 周边

CharacterPanel.tsx 同文件里 voice 编辑(行 853 起)与 Live2D 配置不动。Segment 2 在 voice 选择**下方**加 TTS 语言下拉(spec 4.4)。

---

## 0.2 character_personas REST API 现状

### Backend 路由

```bash
grep -rln "character_personas\|persona_api\|/api/personas\|/api/characters/.*persona" backend/routes/
```
返回 **0 行**(预期符合 ── Segment 1 没建 API)。

### ORM 关联(Segment 1 已有)

`backend/database/models.py` 已经定义 `CharacterPersona` 类(line 70-122),与 `Character.personas` 反向关联(`cascade="all, delete-orphan"`)。Tier-1 7 字段全是 `Text NOT NULL`,Tier-2 全 nullable。`UniqueConstraint("character_id", "variant_name")` 已加。Partial UNIQUE INDEX `idx_persona_active_per_char` 保证 active 唯一(在 migration 里建)。

### 当前 DB 实测状态

```sql
SELECT character_id, variant_name, is_active, is_builtin, json_extract(identity,'$.name'), length(voice_samples)
FROM character_personas ORDER BY character_id;
```
| character_id | variant_name | is_active | is_builtin | identity.name | voice_samples 长度 |
|--------------|--------------|-----------|------------|---------------|-------------------|
| 1 | default | 1 | 1 | **樱岛麻衣** | **1008**(已灌 Mai) |
| 2 | default | 1 | 1 | 八重神子 | 2(`[]`) |
| 3 | default | 1 | 1 | 荧 | 2 |
| 4 | default | 1 | 1 | 凝光 | 2 |
| 5 | default | 1 | 1 | 神里绫华 | 2 |
| 99 | default | 1 | 1 | 一般路过猫娘 | 2 |
| 100 | default | 1 | 1 | 祥子-test | 2 |

→ **id=1 已有 Mai persona** ✓
→ **id=101 樱岛麻衣 characters 表有但 character_personas 表没有对应行**(见 D-S2-2)

### 决策点 D-S2-2: id=101 缺 active variant

`characters` 表有 8 行 {1, 2, 3, 4, 5, 99, 100, **101**},但 `character_personas` 只有 7 行(缺 id=101)。

→ **Renderer 路径 `load_active_persona(101)` 会 RuntimeError → fall back 到 legacy `prompt_manager`**。
→ 用户若用 id=101 真聊天,会触发 `[prompt_manager] @deprecated` warning。

**原因推断**:id=101 在 Segment 1 migration **跑完之后**才被 SQL 灌入,migration 没回头补 seed。

**3 个选项**:
- **A**: Segment 2 加幂等 "ensure all characters 有 default variant" 入口(eg 在 v4_persona_segment2 migration 或 startup hook 跑一次 ── 7 ﻿character 变 8)。**推荐**。
- **B**: 用户手动 SQL insert,或者直接通过新 REST API `POST /api/characters/101/personas` 建。
- **C**: 不管,留 legacy fallback。Renderer warning 不影响功能。

### Mai/Momo 借壳关系

`characters.id=1` `name='Momo'` `persona=ChatAgent 老文案`(未被 Segment 1 改) + `character_personas(char_id=1, default)` 的 identity.name='樱岛麻衣'。

→ Renderer 路径下 LLM 看到的是 Mai 人设(因为 Layer C 读 `persona.identity.name`,不读 `Character.name`)。
→ Frontend UI 显示 character.name='Momo' 但 active variant 显示 identity.name='樱岛麻衣' ── 这就是 spec 4.5 要的"默认 / 樱岛麻衣"展示。

---

## 0.3 现有 sanitize 链 + TTS 路径

### `_BOUNDARY_PAIRED_TAGS` 实际位置

⚠️ Spec 2.4 写"`backend/utils/text_filters.py::_BOUNDARY_PAIRED_TAGS`",**实际位置是 `backend/agents/chat.py:345`**:

```python
_BOUNDARY_PAIRED_TAGS = frozenset({
    "thinking", "emotion", "state_update", "motion",
    "tool_call", "function_calls", "invoke",
})
```

→ Segment 2 加 `"ja", "en"` 到此 set(chat.py 不是 text_filters.py)。

text_filters.py 里另有相关结构:
- `_OPEN_BLOCK_PAIRS`(行 297-310):partial-open 检测的 open/close 正则 pair 表。
- `_PARTIAL_OPEN_TAG_RE`(行 288-292):兜底未闭合 tag 检测。
- `_CAPABILITY_OPEN_TAG_RE`(行 316-320):专门为 capability-name-as-tag(`<netease.daily>`)的反向引用检测。

`<ja>` / `<en>` 简单 paired tag,**通用 `_PARTIAL_OPEN_TAG_RE` 已能兜住**(它匹配 `<[a-zA-Z][^>]*$` 任何字母开头的未闭合),不需要单独加进 `_OPEN_BLOCK_PAIRS`。

### TTS path —— **5 个 strip_all_for_tts 调用点**(spec 写"找 strip_all_for_tts(sentence) 调用处",实际不止 1 处):

| 文件:行 | 路径 |
|--------|------|
| `backend/routes/ws.py:1024` | **主聊天**:`final_chunk = strip_all_for_tts(sentence)` 后送 WS `text_chunk`(字幕);TTS 接收的是**原始 sentence**(line 1040) |
| `backend/proactive/engine.py:286` | helper `_strip_for_tts(text)`,proactive 共用 |
| `backend/proactive/engine.py:449` | proactive engine `final_chunk` 给 WS |
| `backend/proactive/engine.py:779` | wake_call 短问候 `final_chunk` 给 WS |
| **`backend/tts/__init__.py:85`** | **TTS engine 内部**:`out = strip_all_for_tts(text)` 在 edge / cosyvoice / sovits synthesize 之前 |

→ **关键发现**:TTS engine 自己会 strip。所以送到 engine 的 `sentence`(line 1040 `_tts_synth_with_timeout(tts_engine, sentence, ...)`)实际上**带 `<ja>` tag** 传到 `tts/__init__.py:85`,被那里的 `strip_all_for_tts` **剥光**。

**含义**:若直接用 spec 2.3 的 `extract_tts_text`,需要在 **TTS engine 层**(`tts/__init__.py`)替换 strip 逻辑,或在 caller 端(ws.py / proactive)**预先 extract**好 ja 文本再传给 engine。

**推荐设计**(spec 2.5 隐含):
- caller(ws.py / proactive engine)**预先**调 `extract_tts_text(sentence, tts_language)` 得到 `tts_text` → 传给 `_tts_synth_with_timeout(tts_engine, tts_text, ...)`
- `tts/__init__.py:85` 的 `strip_all_for_tts` 不动(现在 tts_text 已经是"纯日语正文",strip_all_for_tts 是 no-op)
- WS subtitle path:用 `strip_ja_en_tags_for_subtitle(strip_all_for_tts(sentence))` 替换 line 1024 的 `final_chunk`

需要改的 caller 数量:**3 处**(ws.py:1024+1040;proactive/engine.py:449+对应 synth;wake_call 779+对应 synth)。

### TTS engine 接 character / voice_model 的接口

`tts/__init__.py` 实例 `engine.synthesize(text, emotion=emotion)`(line 232)只接 text + emotion,**没拿到 character / voice_model**。`character` 在 router 层是有的(`tts/__init__.py:118` `self._sovits.synthesize(cleaned, character)`),但是 cosyvoice 路径不传 character。

→ caller 端预先 extract 才是干净方案,不污染 engine API。

---

## 0.4 现有 voice_model 字段

```sql
SELECT id, name, voice_model FROM characters WHERE voice_model IS NOT NULL;
```
| id | name | voice_model |
|----|------|-------------|
| 1 | Momo | `{"provider":"cosyvoice","model":"cosyvoice-v3.5-plus","voice":"cosyvoice-v3.5-plus-bailian-a19f528011c1446eafd4c4990301270f","instruct_supported":true,"ssml_supported":true}` |
| 2 | 八重神子 | `... a61ea44f8a9648b3920b7ef98280d226 ...` |
| 3 | 荧 | `... ec2676aa187a44a2b448a37a239b29af ...` |
| 5 | 神里绫华 | `... 7c617acd71b54130ac14ea7158718916 ...` |
| **101** | **樱岛麻衣** | `{"provider":"cosyvoice","voice":"cosyvoice-v3.5-plus-bailian-a19f528011c1446eafd4c4990301270f","instruct_supported":true}` |

→ `tts_language` **不存在任何 voice_model 中**(预期,这是本 segment 新加)。
→ **id=101 (樱岛麻衣) 与 id=1 (Momo/Mai) 用同一个 voice**(`a19f528011c1446eafd4c4990301270f`),**两条记录都是 Mai 复刻日语 voice**。

### 决策点 D-S2-3: Mai voice migration 范围

spec 5 migration WHERE 子句:
```sql
WHERE id = 1
  AND json_extract(voice_model, '$.voice') = 'cosyvoice-v3.5-plus-bailian-a19f528011c1446eafd4c4990301270f'
```
→ **只标 id=1**。

但 id=101 用**同一个 voice**(也是 Mai 复刻)。若 id=101 真的被聊天,它走的也是日语音色,合成中文也会差。

**2 个选项**:
- **A**:**改 WHERE 子句去掉 `AND id = 1` 限制**,改成 `WHERE json_extract(voice_model, '$.voice') = '...'` → 自动给所有用这个 voice 的角色打 ja 标记(当前 id=1 + id=101 共 2 行)。**推荐**。语义上"voice 是日语 sample 复刻 → tts_language=ja"是 voice 自身属性,不依赖 character_id。
- **B**:严格按 spec 只标 id=1,id=101 用户手动改。

→ **推荐 A**,跟 voice 走。

---

## 0.5 决策点 sign-off

### 待用户确认

| ID | 决策 | 我的推荐 |
|----|------|----------|
| **D-S2-1** | CharacterDetailModal 旧 persona 显示是否删 | **删**,改显示 active variant 的 identity.name + description + style_preset(配 4.5 spec) |
| **D-S2-2** | id=101 缺 character_personas row 怎么补 | **A** ─ Segment 2 加幂等 seed migration:扫 characters 表给所有缺 active variant 的角色补默认空 seed(同 Segment 1 builtin_seed 逻辑) |
| **D-S2-3** | Mai voice migration 是否扩到 id=101 | **A** ─ 按 voice 标记不按 id,WHERE 用 voice 匹配,自动覆盖 id=1 + id=101 |
| **D-S2-4** | Phase 4 PersonaEditorModal 的 scope | **降到 MVP** ─ Tier-1 7 字段(identity / personality_core / speech_style / signature_phrases / voice_samples / forbidden_phrases / relationship_to_user)+ cliche_tolerance slider + voice_samples tolerance_range,Tier-2(taboo / lore / capability_overrides)留 v4.2(理由:Modal 字段太多易超时,且 Tier-2 仅 Mai 用,segment 2 完整 spec 估 ~1500 LOC modal 单文件)。**或维持原 spec 全字段** |

### Spec 路径错误 / 不准确处(已替换为正确路径)

| Spec 写 | 实际 |
|--------|------|
| `backend/utils/text_filters.py::_BOUNDARY_PAIRED_TAGS` | 在 `backend/agents/chat.py:345` |
| "grep TTS 触发点(backend/agents/chat.py / backend/routes/ws.py),找 strip_all_for_tts(sentence) 调用处" | 实际 5 处:ws.py:1024 + proactive/engine.py:286/449/779 + tts/__init__.py:85 |
| Migration 调用约定 `run_migration(engine)` | 实际范本是 `async def run_migration() -> None`(无 engine 参数,内部 `from backend.database import engine` 全局)|

### 预期改动文件清单

**新建**(~6):
- `backend/agents/prompt/templates/layer_c.j2` 加 5 段(改文件,非新建)
- `backend/agents/prompt/templates/layer_a.j2` 加 ja/en directive(改文件)
- `backend/agents/prompt/renderer.py` 加 `filter_samples_by_tolerance` + tts_language 参数(改文件)
- `backend/routes/persona_api.py` ★ 新文件(7 endpoint)
- `backend/utils/text_filters.py` 加 `extract_tts_text` / `strip_ja_en_tags_for_subtitle` / `_JA_TAG_RE` / `_EN_TAG_RE`(改文件)
- `backend/database/migrations/v4_persona_segment2_mai_ja.py` ★ 新文件
- 若 D-S2-2 选 A:第二个 migration `v4_persona_segment2_ensure_default_variants.py`,或合并进 mai_ja 文件
- `frontend/src/components/PersonaEditorModal.tsx` ★ 新文件(~1000-1500 LOC if 全字段)
- `frontend/src/components/CharacterPanel.tsx` 改(删 persona textarea + 加 Personas section + TTS language 下拉)
- `frontend/src/components/character/CharacterDetailModal.tsx` 改(若 D-S2-1 选 A)
- `frontend/src/lib/config.ts` 改(可选)
- `backend/agents/chat.py` 加 ja/en 到 `_BOUNDARY_PAIRED_TAGS`
- `backend/routes/ws.py:1024+1040` 改 TTS 路径
- `backend/proactive/engine.py:286+449+779` 改 TTS 路径
- `backend/main.py` 注册新路由 + 新 migration
- `tests/test_persona_segment2.py` ★ 新文件(50+ case)

**预估**:~16-20 文件改动 / 新增,LOC +2500~+3500(spec 预估 +3000,接近)。

### 风险评估

| 风险 | 等级 | 缓解 |
|------|------|------|
| Frontend "角色提示词" 必填校验删除后老 character 创建流程崩 | 中 | Phase 4 同步删校验 + name 仍 required |
| `<ja>` tag 加入 `_BOUNDARY_PAIRED_TAGS` 破现有 sanitize regression | 低 | Sanitize chain 0 代码改动(只增 enum),regression 128 case 必须仍过 |
| Mai voice migration 误标 zh 角色 | 中 | D-S2-3 推荐 A,WHERE 限定 voice id 精确匹配;migration 是 idempotent UPDATE |
| voice_samples tolerance filter 后 LLM 看到 0 条 | 中 | Renderer 加 fallback:filter 结果空则 fall back 到所有 samples,**带 log warning**(spec 决策点单独列了这条) |
| Jinja `is mapping` on dict/string 兼容(preferences 字段格式不统一) | 低 | 模板用 `{% if item is mapping %}` 已覆盖;test 21 验证 mixed type |
| Token 增长超 +50% | 低-中 | Mai persona 全字段 + 5 个新模板段约 +2-3KB,filter 后净增 ~+30%(spec 预期);若超需要 truncate strategy。**测量后再决策**。 |
| PersonaEditorModal 复杂度爆炸(1500 LOC 单文件) | **高** | **D-S2-4 推荐降 MVP**:Tier-1 + tolerance sliders,Tier-2 留 v4.2 |
| id=101 没 default variant 导致 RuntimeError | 高 | D-S2-2 推荐 A,migration 兜底 |

---

## Sign-off 所需

请回复:

1. **D-S2-1**(CharacterDetailModal):删旧 persona 显示改成展示 active variant?(推荐:**删**)
2. **D-S2-2**(id=101 补 seed):segment 2 加幂等 seed migration 给所有缺 active variant 的角色?(推荐:**A**)
3. **D-S2-3**(Mai voice ja 范围):按 voice id 匹配标记(覆盖 id=1 + id=101)还是仅 id=1?(推荐:**按 voice id**)
4. **D-S2-4**(PersonaEditorModal scope):**MVP(Tier-1 only)**,还是**全字段(含 taboo / lore / emotion_triggers 折叠)**?
   - MVP 估 ~600-800 LOC,实施 2-3h
   - 全字段估 ~1200-1500 LOC,实施 4-5h
5. **Phase 1-6 spec 是否还有占位符待补**?(目前看完整,Mai voice WHERE 子句可能要修)

收到 sign-off → 进 Phase 1。
