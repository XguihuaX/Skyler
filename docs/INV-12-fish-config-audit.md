# INV-12 · Fish TTS 配置管理 UI · Stage 1 audit

> 接 INV-9 Phase 2 closed + INV-10 voice greeting + INV-9 part 5 字幕剥离 hotfix 后第一刀。
> 目标:Fish TTS reference audio + 参数前端可视化管理 + 试听;后端 FishTTS 真用 DB 配置。
> Stage 1 = audit only · 不写代码;落 checklist + flag PM dispatch 与现状的设计冲突,等 PM 拍板进 Stage 2。

## §1 现状 verify(audit · 不动代码)

### §1.1 PM dispatch vs 实际 codebase 偏差

| PM dispatch 描述 | 实际 codebase | 影响 |
|---|---|---|
| `backend/tts/providers/fish.py` | **`backend/tts/fish.py`**(无 providers/ 子目录) | Stage 2 path 修正 |
| `frontend/src/components/CharacterDetailModal/FishConfigSection.tsx` | CharacterDetailModal.tsx **单文件无子目录** | Stage 3 path 修正 |
| voice greeting tab 在 CharacterDetailModal | 实际 `VoiceLinesSection` 集成 in **`CharacterPanel.tsx:1126`** 角色编辑表单(per INV-10 §2.1 ship);CharacterDetailModal 是 **Fan 立绘馆放大 modal**(不同 UI 入口)| Stage 3 设计:跟 voice_lines 同位放 CharacterPanel,不放 DetailModal |
| "characters 表已加 fish_temperature 字段" | characters 表 **未加 fish_* SQL 列**;`fish_temperature=0.2` 在 **voice_model TEXT JSON** 内(per INV-9 §7 commit `a6af74b`)| **核心设计 question**(详 §2)|
| `fish_repetition_penalty` SDK 字段 | **SDK 1.3.0 TTSRequest 字段表无此字段**(per `TTSRequest.model_fields` introspect:只 `temperature / top_p / prosody.speed / prosody.volume`)| Stage 2 字段集裁剪(详 §3.2)|

### §1.2 voice_model JSON 现状(per cid=101 DB query)

```json
{
  "provider": "fish",
  "voice": "mai5min_0033",
  "model": "s2-pro",
  "tts_language": "ja",
  "reference_audio_path": "tts/fish/参考音频/mai/mai5min_0033.wav",
  "reference_text": "自分の方が可愛いって自覚あるくせに、別の誰かのことを可愛いとか言ってる女がサクタは好きなの?",
  "fish_temperature": 0.2
}
```

`VoiceConfig` dataclass(per `backend/tts/voice_config.py:VoiceConfig`)已含完整 fish-related 字段集(per INV-9 §2 + §7):
- `provider / voice / instruct_supported / model / tts_language`(基础)
- `reference_audio_path / reference_text`(mode_A 必填 per INV-9 §2 parse_voice_config raise validation)
- `fish_latency`(默 'balanced')
- `fish_temperature / fish_top_p / fish_seed`(全 Optional default None;per INV-9 §7 sweep + §1.3 stage 2 实证)

`FishTTS` 构造从 voice_config 读全字段(per `backend/tts/fish.py:79-127`),`_build_request` if-not-None 透传 TTSRequest(per INV-9 §7 stage 2 实测)。

### §1.3 ws.py / chat.py 读 voice_model 路径

- `backend/routes/ws.py:725` · `SELECT Character.voice_model WHERE id=char_id` → parse_voice_config → get_tts_engine
- `backend/agents/chat.py:1218` · 同款(给 layer_a.j2 ja directive + voice_provider provider 字段)

→ **现 voice_model JSON 已是真源**,FishTTS 真用 voice_model JSON 字段(不是硬编码)。

### §1.4 voice_lines.py 范式可借鉴度(per INV-10)

`backend/routes/voice_lines.py`(per INV-10 §1)4 endpoints + StaticFiles mount 范式可**几乎一对一**借鉴给 fish_config.py:
- multipart 上传(file + 可选字段 + 415/413 validation + UUID filename + DB INSERT)
- StaticFiles mount `/static/fish_references/`(独立 mount,跟 `/static/voice_lines/` 并列)
- pattern:`backend/static/fish_references/<cid>/<uuid>.<ext>`

### §1.5 已 ship cid=101 fish_temperature=0.2 lock 状态

per INV-9 §7 commit `a6af74b`:
- voice_model JSON 含 `"fish_temperature": 0.2` ✓
- `VoiceConfig.fish_temperature = 0.2` parse OK ✓
- `FishTTS.temperature = 0.2` 透传 TTSRequest ✓
- Phase 2 已 ship · 真机已 work(per PM 18:13 真机日志 [composed] marker 真合成 OK)

→ **Option C(沿用 JSON)对此 lock 0 迁移成本**;Option A(加 SQL 列)需要数据迁移 + FishTTS read path 改写。

---

## §2 ⭐ 核心设计 question · Option A(新 SQL 列)vs Option C(沿用 voice_model JSON)

### §2.1 PM dispatch · Option A 字面

> "characters 表新增字段:fish_reference_audio_path / fish_reference_text / fish_top_p / fish_repetition_penalty / fish_reference_id"

但 audit 实证:**前 3 字段在 voice_model JSON 内已存在并已 work**(`reference_audio_path` / `reference_text` / `fish_top_p`)。`fish_repetition_penalty` SDK 不支持。`fish_reference_id` 是 Fish marketplace 路径新字段。

### §2.2 三 Option 对比

| Option | 描述 | DB 改动 | code 改动 | 迁移 | 与 voice_model JSON 关系 | future-proof |
|---|---|---|---|---|---|---|
| **A · PM dispatch** | 加 5 个 fish_* SQL 列 | DB migration(5 列)| FishTTS / parse_voice_config 改 source(从 JSON parse → 从 SQL 列直读)/ ws.py / chat.py 加新 SELECT | cid=101 voice_model JSON → 新 SQL 列(数据迁移 script) | **重复 / 冗余**(同款数据 2 处存 · JSON 和 SQL 列都含 reference_audio_path / reference_text / fish_top_p)| ⚠️ 跟 v4.2 重构 tech debt "新表 character_tts_config(provider, params_json)" 冲突 |
| **B · 新表 character_tts_config** | 新表 `(character_id, provider, params_json)`(PM dispatch 提的 future v4.2 重构) | DB migration(新表)| 多 provider future-proof | 全 character voice_model JSON → 新表 row | 不冲突(voice_model 仍存基础 provider/voice;新表存 per-provider params)| ✅ future-proof per-provider |
| **C · 沿用 voice_model JSON 扩展**(CC leaning)| 不动 DB schema · voice_model JSON 字段集已含 fish_*;新 endpoint 操作 JSON merge update + audio upload 落盘 | **0 DB 改动** | FishTTS / parse_voice_config / VoiceConfig **0 改动**(已 work);新 fish_config.py routes + StaticFiles mount + frontend section | **0 迁移**(cid=101 lock 自然继承) | **一致**(单一真源 voice_model JSON · per INV-8 §1.2 抽象插点 C "VoiceConfig 字段扩 per-provider" 即此 design)| ⚠️ Future 加新 provider 时 JSON 字段累积膨胀;v4.2 重构时仍需迁移到 Option B 新表 |

### §2.3 CC leaning · Option C

**理由**:
1. **零迁移成本**:cid=101 已 ship fish_temperature=0.2 in JSON;Option A 需写数据迁移 script
2. **零设计冗余**:Option A 同款数据 2 处存(JSON + 新 SQL 列),违反 single source of truth
3. **零 read path 改写**:FishTTS / VoiceConfig / parse_voice_config / ws.py / chat.py 现链路完全不动
4. **跟现 voice_model JSON design 一致**:per INV-8 §1.2 抽象插点 C "VoiceConfig 字段扩 per-provider"(已实施),Option C 是其自然延伸 UI 层
5. **跟 v4.2 重构 path 不冲突**:Option B(新表)将来重构时,Option C 现状 = JSON → Option B SQL 是同款"single-row-of-JSON → relational-rows"标准迁移;Option A 现状 = 5 个 fish_* 列 + JSON 双源,迁移到 B 时需要清理双源

**不利**:
- 长期 voice_model JSON 字段累积膨胀(future 加 GSV / RemoteFish provider 时累积 GSV-specific / Remote-specific 字段);**接受**作为 v4.2 重构 trigger 信号(per ROADMAP "多 provider 扩展刀" backlog)

### §2.4 Tech debt 入 DESIGN_LITE(per PM dispatch + Option C 接受)

**记录**:`characters.voice_model TEXT` 单字段 JSON 容纳全 provider 参数(cosyvoice 字段 + fish 字段 + future GSV / RemoteFish),随 provider 累积膨胀;**v4.2 重构方向 = 新表 `character_tts_config(character_id, provider, params_json)`** future-proof per-provider 干净拆分。Trigger:第 3 个 provider 加入时启动重构(per "多 provider 扩展刀" backlog)。

---

## §3 字段集 audit · 5 个 PM 字段 vs SDK 实际

### §3.1 PM dispatch 字段集 vs SDK TTSRequest

| PM 字段 | SDK TTSRequest 字段 | voice_model JSON 现状 | Stage 2 处理 |
|---|---|---|---|
| `fish_reference_audio_path` | `references[].audio` (bytes) | ✓ `reference_audio_path` 已在 | 沿用;Stage 2 加 upload endpoint 写文件 + JSON merge |
| `fish_reference_text` | `references[].text` (string) | ✓ `reference_text` 已在 | 沿用 |
| `fish_temperature` | `temperature: float = 0.7` | ✓ `fish_temperature` 已在 + cid=101 已 lock 0.2 | 沿用 |
| `fish_top_p` | `top_p: float = 0.7` | ✓ `fish_top_p` 已在(Optional · 未 lock 默 None → SDK default 0.7) | 沿用 |
| `fish_repetition_penalty` | ❌ **SDK 字段表无此字段** | — | **跳过此字段**(per INV-9 #6 SDK 字段表 ground truth lesson;PM dispatch 错记)|
| `fish_reference_id` | `reference_id: str | None`(SDK 真有 · Fish marketplace pre-uploaded voice) | — voice_model JSON **无**(本轮 mode_A inline references[] only,不走 reference_id) | **Stage 2 暂不实**(per Step 5 PM 决策 1 lock "mode_A only references[] inline");留 v4.1+ backlog · "切 reference_id 预上传 voice"(per INV-8 §1.3.2 Phase 2 mitigation option) |

### §3.2 Stage 2 实际字段集(裁剪后)

| 字段 | 类型 | 默 | UI control |
|---|---|---|---|
| reference_audio_path | str | None | 上传 .wav/.mp3/.ogg ≤ 5MB(借 voice_lines.py 范式) |
| reference_text | str | None | textarea |
| fish_temperature | float | None(SDK 默 0.7) | slider 0.0-1.0(cid=101 已 lock 0.2)|
| fish_top_p | float | None(SDK 默 0.7) | slider 0.0-1.0 |
| ~~fish_repetition_penalty~~ | ❌ | ❌ | ❌ 跳过(SDK 不支持)|
| ~~fish_reference_id~~ | ❌(本轮)| ❌ | ❌ 留 v4.1+(mode_A only lock)|

**5 sliders 任务描述 → 实际只 2 sliders**(temperature + top_p)。

---

## §4 Stage 2-4 实施 checklist(基于 Option C + 字段裁剪后)

### §4.1 Stage 2 · Backend(预估 0.5-0.8d,less than PM 1d)

- [ ] **DB · 0 schema 改动**(per Option C);**0 数据迁移**(cid=101 voice_model JSON 已含 fish 字段)
- [ ] `backend/static/fish_references/` mkdir + main.py `app.mount("/static/fish_references", StaticFiles(...))`(类 INV-10 voice greeting mount)
- [ ] `backend/routes/fish_config.py`(新)4 endpoints:
  - [ ] **POST /api/characters/{cid}/fish_config** · multipart audio upload + form `reference_text / fish_temperature / fish_top_p` → 415/413 validation + UUID filename + 落 `backend/static/fish_references/<cid>/<uuid>.<ext>` → JSON merge update voice_model `reference_audio_path / reference_text / fish_temperature / fish_top_p`(per character UPDATE SQL · voice_model TEXT JSON `json_patch` or read-merge-write)
  - [ ] **GET /api/characters/{cid}/fish_config** · 返 voice_model JSON 内 fish-related 字段 dict + audio_url(per fish_references mount)
  - [ ] **POST /api/characters/{cid}/fish_config/synthesize** · body `{text}` → 临时构造 VoiceConfig + FishTTS + synthesize → 返 audio binary `Response(media_type="audio/wav")` 或 save 临时 file 返 URL(选项见 §5.3)
  - [ ] **DELETE /api/characters/{cid}/fish_config** · 删 audio file + voice_model JSON 清空 fish-related 字段 → next FishTTS 构造会 raise(per parse_voice_config mode_A only validation);若需 fallback 到 cosyvoice yaml default,UPDATE provider 改 'cosyvoice'(per PM "DELETE 后 fallback 到现有硬编码")
- [ ] `tests/test_fish_config.py` · 6-8 tests(per voice_lines 测试范式):
  - upload happy + voice_model JSON 写回 verify
  - upload 415 / 413 / 404 unknown cid
  - GET fish_config 字段集 verify
  - synthesize · text 空 → 400 / text OK → 200 audio bytes
  - DELETE · file unlink + JSON 清空
  - fallback · DELETE 后再 GET → 字段空
- [ ] **FishTTS / parse_voice_config / VoiceConfig 0 改动**(Option C 核心优势)
- [ ] **不动** ws.py / chat.py read path(现 select voice_model 已自动反映新配置)

### §4.2 Stage 3 · Frontend(预估 0.5d,less than PM 1d)

- [ ] `frontend/src/lib/fish_config.ts`(新 API client)· 4 functions(per voice_lines.ts 范式)
- [ ] `frontend/src/components/character/FishConfigSection.tsx`(新)· **集成位置:CharacterPanel.tsx**(不是 CharacterDetailModal · per §1.1 PM 描述偏差)位置 = VoiceLinesSection 之后:
  - reference audio 上传(复用 voice_lines 上传 UI 形态)
  - reference_text textarea
  - 2 sliders(temperature default 0.2 for Mai · top_p default 0.7;不实 repetition_penalty)
  - 试听区:textarea + 试听按钮 → POST synthesize → `<audio>` 播放
  - 保存 / 删除按钮
  - 错误 toast(复用 showToast prop)
- [ ] `CharacterPanel.tsx` import + render(form edit mode + form.id + voice_model.provider == 'fish' 时 render;非 fish provider 不显示)

### §4.3 Stage 4 · 真机集成 + 收口(预估 0.3d)

- [ ] PM 真机:Mai chat(cid=101)调用日志 verify voice_model.fish_temperature 真 lock 进 TTSRequest(per existing INV-9 §7 ship · 本任务 reading path 不变)
- [ ] PM 真机:UI 改 temperature 0.2 → 0.5 → 再 chat,日志 verify TTSRequest temperature=0.5
- [ ] PM 真机:DELETE → 切 provider 回 cosyvoice yaml default(若 Option C 设计)→ chat 走中文 voice 验
- [ ] docs/IMPLEMENTATION_LOG.md · 追加 INV-12 Stage 2/3/4 完整记录
- [ ] DESIGN_LITE.md tech debt 加 §2.4 v4.2 重构 path
- [ ] INVESTIGATION-INDEX.md 主表加 INV-12 一行

---

## §5 待 PM 拍板的关键问题

### Q1 · Option A vs B vs C ⭐ 主拍板

CC leaning **Option C**(沿用 voice_model JSON)— 0 DB migration / 0 read path 改 / 0 数据迁移 / 跟现 design 一致 / cid=101 lock 自然继承。详 §2.2-§2.4。

PM 真机 + voice_model JSON 是已 ship reality(per INV-9 §7),Option A 加 SQL 列 = 重复存 same 数据,**反 single source of truth**。

### Q2 · `fish_repetition_penalty` 跳过(per SDK 字段表 ground truth)

CC 提议跳过此字段。如 PM 真希望加这个声学控制 → 需先 verify SDK 升级或别的 Fish 字段(eg prosody?但 SDK Prosody 字段表只 speed / volume,无 repetition_penalty)。

### Q3 · `fish_reference_id` 留 v4.1+ backlog 还是本轮加?

PM dispatch 提议加;但 per Step 5 PM 决策 1 lock "mode_A only references[] inline",reference_id 是 mode_B(预上传)。**CC 提议留 v4.1+ backlog**(per INV-8 §1.3.2 Phase 2 mitigation option),保 mode_A only 一致性。

### Q4 · synthesize endpoint 返 binary 还是 URL?

3 选项:
- (a) binary `Response(content=audio_bytes, media_type="audio/wav")` · 直接 ws audio 类似 · frontend `new Audio(URL.createObjectURL(blob))`
- (b) URL · save 临时 file `/static/fish_references/<cid>/_preview_<timestamp>.wav` + 返 audio_url · frontend `<audio src=audio_url>`(per voice_greeting 同款)— 但**临时 file gc** 麻烦
- (c) base64 inline JSON ·{audio_b64: "..."} · 简单但 payload 大

**CC leaning (a) binary**:简单 · frontend Blob URL 自动 cleanup · 无服务器临时 file gc 负担

### Q5 · DELETE 之后 fallback 到哪?

PM dispatch 说 "DELETE 之后回退 fallback (现有硬编码)"。但 voice_model JSON 是真源(无硬编码)。**3 选项**:
- (a) DELETE 只清 reference_* / fish_temperature 等字段 → voice_model.provider 仍 'fish' + 缺 ref → parse_voice_config raise → FishTTS 构造失败 → ws.py 报 500 / 用户体感断
- (b) DELETE 也改 provider 'fish' → 'cosyvoice' + 写入 yaml default voice → 切回 zh CosyVoice longyumi_v3
- (c) DELETE 等同删 voice_model 字段(全空)→ get_tts_engine yaml default

CC leaning **(b)**:per INV-8 §1.4.7 cid=101 三件事契合(切 cosyvoice 是降级路径而非彻底删配置)+ user 不希望"删 fish config 后角色失声"。但 (b) 改 provider 意味失去 Mai 日语身份,**实际更对**应是 Q5b 选项细分:

实际更对: **(d) 只清 reference_*** 但 provider 保留 fish + raise hint user "需 re-upload audio"。前端 catch raise + show toast。但**这跟 PM dispatch "fallback 到 fallback" 矛盾**。

→ Q5 待 PM 拍板。

### Q6 · CharacterPanel 集成位置 vs PM CharacterDetailModal

PM dispatch 写 CharacterDetailModal(立绘馆 modal)— 但 voice_lines 已在 **CharacterPanel(角色编辑表单)**。CC leaning 跟 voice_lines 同位 = CharacterPanel.tsx,UX 一致。Confirm PM 接受迁位 from DetailModal → CharacterPanel?

---

## §6 收口 + Stage 2 起手前置

- ✅ 现状 verify 完整(voice_model JSON 真源 / FishTTS 真用 / cid=101 已 lock)
- ✅ Option A vs B vs C trade-off + CC leaning Option C(0 DB 改动 + 0 迁移)
- ✅ SDK 字段集 audit(repetition_penalty 不支持 · reference_id 留 v4.1+)
- ✅ Stage 2-4 实施 checklist 调整(估 1.3d total,远低 PM 估 2.5d 因 Option C 砍 DB migration / 数据迁移)
- ⏸ 6 Q PM 拍板(主 Q1 = Option C lock · 其余 Q2-Q6 跟着定)

→ **Stage 1 audit closed**(本文件 ~250 行,远低 1500 切节阈值)。等 PM 拍板 6 Q 后启 Stage 2 backend 实施。

## §7 lesson 沉淀

### Lesson INV-12 #1 · audit 比 dispatch 字面更优先 · 现状 verify 第一原则

PM dispatch 给的 Option A 字面"加 5 个 SQL 列"基于"characters 表已加 fish_temperature 字段"假设;但实际 fish_temperature **早在 voice_model JSON 内**(per INV-9 §7 ship)。若直接按字面 Stage 2 落代码 → 加 SQL 列 → 跟 JSON 重复 → DB migration + 数据迁移 + read path 改写 + 双源不一致 risk。

**Stage 1 audit 提前 flag 设计 question 给 PM 拍板,避免 1-2d 工程量做错方向**。

**抽象**:跨多 commit + 多 PM dispatch 项目里,**PM dispatch 可能基于过时 mental model**;CC audit 必须先 verify 现状 + flag 偏差,再考虑实施。类比 INV-9 #6(SDK 字段表 ground truth)— 本 lesson 是 "项目代码现状是 ground truth"。

### Lesson INV-12 #2 · 跟相邻 INV ship 同主题但不同 lifecycle 区分

PM onboarding 担心 voice_greeting 跟 fish_config 混淆(per "不要假设 voice_greeting 跟本任务是同一个东西")— 正确区分:
- voice_greeting = 立绘馆 onEnter 静态音频随机播(per INV-10 §1-2 ship · 用户 pre-recorded files)
- fish_config = chat 推理时实时合成 reference + 参数(per INV-9 §1.3 stage 1+2 audit · LLM stream → Fish s2-pro 真合成)

两者**共享底层 storage pattern**(StaticFiles mount + multipart upload + UUID filename)但**功能完全独立**:fish_config 改的是 FishTTS 调用参数,voice_greeting 是 pre-recorded audio。

**抽象**:相邻 INV ship 同主题(audio) 但**生命周期/触发路径**不同时,Stage 1 必须明示功能 lifecycle 区分,避免 Stage 2 复用过度导致功能耦合。

### Lesson INV-12 #3 · Schema 适配 minimal diff 优于教科书结构(PM Q5 拍板入)

PM 提议 nested schema `{default: {...}, user_override: {...}}` 是教科书漂亮结构;但 verify 现状 9 char voice_model 全 flat 后,**β prefix 方案**(顶层加 4 个 `user_*` 字段)semantic 1:1 等价 + 0 数据迁移 + 0 测试 regression + +0.1d 工程量(vs nested +1d)。

**抽象**:看到语义抽象(3 层 fallback)不要 reflective 套 nested JSON 结构,先 verify 现状 schema,**在现状基础上加最小字段达成 1:1 等价比重构干净**。Nested 优雅 vs flat-prefix minimal,后者在已 ship 数据 + 多 caller 的现实下完胜。

**应用**:类比 INV-9 #2 docs 是 contract / SDK 是 truth · INV-12 #1 PM dispatch 可能基于过时 mental model · #3 是同款"现状 ground truth 优先于理想抽象"在 DB schema 层。

**实证 ship 结果**(per INV-12 Stage 2):
- VoiceConfig 加 4 Optional 字段(+1 行 dataclass + 4 个 parse 透传 + 1 行 return kwargs)
- FishTTS merge logic +15 行(audio 配对 validate + 独立参数 short-circuit)
- 0 DB migration / 0 数据迁移 / 0 老 voice_model JSON 兼容性破坏
- 0 frontend `VoiceModelJson` 接口破坏(后续 frontend 新加 user_* 字段也 backward compat)
- 老 9 char(含 cid=101 INV-9 §7 a6af74b lock fish_temperature=0.2)行为完全不变,L1 user_override 空 = L2 default 自动生效
