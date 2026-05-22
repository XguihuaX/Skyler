# Investigation 9 · Phase 2 TTS 模块化 + Fish s2-pro 集成

> 接 **INV-8 §1 audit 1,560 行封存**(2026-05-22),Phase 1 5 决策 lock(详 INV-8 §1.收口.1)。
> Phase 2 主线 = TTSProvider 抽象层 + Fish s2-pro 集成 + sanitize A1 fix + cid=1→cid=101 数据迁移收尾刀。
> 工作量预估 ~3-5d / ~250-300 LoC + 1 新 `backend/tts/fish.py`(per INV-8 §1.5.10 + Step 4 review)。
> 5 决策 + Hard Req per-provider 双重隔离 + Option A1 lock + β inline `[bracket]` final lock 全在 INV-8 §1 收口,本 INV 起 Phase 2 实施记录。

## reference list(继承)

- INV-8 §1.5.10 三档结论 + Option A1 lock + 4 路 Option 对比
- INV-8 §1.5.12 lesson #3(sanitize sub-language path 对称性) + #4(LLM/sanitize/provider 三层分工)
- INV-8 §1.收口.1 5 决策最终三档
- INV-8 §1.收口.2 Q1-Q7 PM 拍板清单
- INV-8 §1.收口.4 Step 6 backlog(Phase 3 H3 fix 合刀)

## §1 sanitize A1 fix(Phase 2 第 1 commit, 2026-05-22)

> per INV-8 §1.收口.6 Q1 lock — **A1 sanitize fix 合并入 Phase 2 第 1 commit**。
> 改 `extract_tts_text` 解决 PM bug #1 / #2(per INV-8 §1.5.2 audit verdict);6 + 回归 case unit test 覆盖。
> Stage 1 audit + design 已在 INV-8 §1.5 全完成 + 三档 lock,本节直接 Stage 2 实施 + 回归记录。

### §1.1 改动文件清单

| 文件 | 改动 | 行数 |
|---|---|---|
| `backend/utils/text_filters.py` | (a) 新增 `_PARTIAL_JA_EN_OPEN_RE` regex + `_has_unclosed_ja_en_tag` helper / (b) 重写 `extract_tts_text`:ja 半截 fallback skip + en 同 / zh 分支显式剥 `<ja>/<en>` 整段 + 兜底半截 skip | +52 / -10 = 净 +42 行 |
| `tests/test_sanitize_ja.py`(新) | 6 主 case + 1 backward compat + 1 edge + 1 helper 行为锁 = 共 10 test functions / 32 assertions | +212 行 |

合计 +264 / -10 = 净 +254 行(略超 PM 估 ~20-30 LoC + 80-100 LoC test 上沿,因 6 case 主测加了 backward compat + helper + edge 子项 = 32 assertions 比 PM 给的 6 case 更细;契合 Lesson #3 全路径覆盖要求)。

### §1.2 改动核心 diff(text_filters.py extract_tts_text 主体)

**Fix 1(ja/en 路径)· 半截 `<ja>` fallback skip**:

```python
if lang == "ja":
    matches = _JA_TAG_RE.findall(raw_text)
    if matches:
        return "".join(strip_all_for_tts(m).strip() for m in matches if m)
    # INV-9 §1 fix (PM bug #1):半截 <ja> 未闭合 → skip synth(避免中日混送)
    if _has_unclosed_ja_en_tag(raw_text):
        logger.warning("[tts] tts_language=ja but <ja> unclosed ...,skip synth: ...")
        return ""
    # 真无 tag(LLM 漏标整段) — 降级 fallback 原行为(保留 backward compat)
    logger.warning("[tts] tts_language=ja but no <ja> tag found; falling back ...")
    return strip_all_for_tts(raw_text)
```

**Fix 2(zh 路径)· 切 zh 时剥 `<ja>/<en>` 整段**:

```python
# zh / unknown — INV-9 §1 fix (PM bug #2):
# 切 zh voice 时 LLM 可能仍按旧 prompt 输出 <ja>/<en>(prompt 重渲染滞后 / LLM
# round-trip 学到 ja 锚点)→ 必须剥整段。原行为靠 _SUSPICIOUS_TAG_WHITELIST
# 白名单豁免,反致 <ja> 整段保留送 zh voice TTS。
cleaned = _JA_TAG_RE.sub("", raw_text)
cleaned = _EN_TAG_RE.sub("", cleaned)
if _has_unclosed_ja_en_tag(cleaned):
    logger.warning("[tts] tts_language=zh but <ja>/<en> tag literal remains ...")
    return ""
return strip_all_for_tts(cleaned)
```

**Helper 新增** `_has_unclosed_ja_en_tag(text)`:剥完整闭合块后用 `_PARTIAL_JA_EN_OPEN_RE = re.compile(r"</?(?:ja|en)\b", re.IGNORECASE)` 检测残留字面 = 半截 marker。

### §1.3 Stage 2 smoke · 测试结果

#### Smoke 1 · NEW test suite `tests/test_sanitize_ja.py`

```
[case 1] ja_path · 单 <ja> 块 · 回归保证                              3/3 PASS
[case 2] ja_path · 多 <ja> 穿插 · 回归保证 (bugfix-segment2-3)         2/2 PASS
[case 3] ja_path · 跟 emotion/state_update/motion/thinking 混排 · 回归  5/5 PASS
[case 4] ja_path · 半截 <ja> 未闭合 · NEW fix (PM bug #1)              3/3 PASS
[case 5] zh_path · 切 zh 含 <ja> · NEW fix (PM bug #2)                3/3 PASS
[case 5b] zh_path · 切 zh 含 <en> · NEW fix 对称                       3/3 PASS
[case 6] zh_path · 切 zh 半截 <ja> · NEW fix bonus                    2/2 PASS
[backward compat] ja_path · 真无 <ja> tag(LLM 漏标)· fallback        1/1 PASS
[edge] 空 / None / 默认 lang                                          4/4 PASS
[helper] _has_unclosed_ja_en_tag 行为锁                                6/6 PASS

Results: 32/32 passed
```

**case 4(PM bug #1 fix)实证**:`extract_tts_text("嗯。<ja>「うん、まだ書き...", "ja")` 现在返 `""`(原行为返 `"嗯。<ja>「うん、まだ書き..."`,送日语 voice 念中文 + 字面 + 半截日语)。

**case 5(PM bug #2 fix)实证**:`extract_tts_text("嗯,去吧。<ja>「うん、行きなさい。」</ja>", "zh")` 现在返 `"嗯,去吧。"`(原行为返完整含 `<ja>` 整段,送 zh voice TTS 中日混合)。

#### Smoke 2 · 邻近 4 test suite 回归(159 cases)

| Suite | 状态 |
|---|---|
| `tests/test_text_filters_ja_whitelist.py`(38 cases · `_SUSPICIOUS_TAG_WHITELIST` 白名单豁免)| ✅ 38/38 PASS |
| `tests/test_tts_final_guard.py`(32 cases · bugfix-D1.1 末端兜底)| ✅ 32/32 PASS |
| `tests/test_tts_strip_fallback.py`(57 cases · 旧 TTS strip 链)| ✅ 57/57 PASS |
| `tests/test_sanitize_ja.py`(32 cases · NEW)| ✅ 32/32 PASS |
| **合计** | **159/159 PASS** |

→ NEW fix 完全 backward compat,白名单豁免逻辑(其它 caller `sanitize_suspicious_tags` 等)零破坏;final_guard / strip_fallback 链路无影响。

### §1.4 关键 invariant 锁(per INV-8 §1.5.12 lesson #3)

- ✅ **PM bug #1 fix**(ja 路径半截 → skip):case 4 实证;不返中文 + 半截日语混合
- ✅ **PM bug #2 fix**(zh 路径含 `<ja>` → 剥整段):case 5/5b 实证;不送日语内容给 zh voice
- ✅ **bonus**(zh 路径半截 → skip):case 6 实证;边缘 case 也防御
- ✅ **backward compat**:ja 真无 tag(LLM 漏标整段)→ 仍 fallback `strip_all_for_tts(raw_text)`(送中文,日语 voice 念中文 — 降级体验不崩链);此 case 不进 NEW skip 分支
- ✅ **回归保证**:ja 单 / 多 / 跟 meta tag 混排 3 个理想 case 完美抽取(case 1/2/3)
- ✅ **helper 行为锁**:`_has_unclosed_ja_en_tag` 检测完整 / 半截开 / 半截闭 / 空 / 跨 en 五种边界

### §1.5 收口

- ✅ INV-8 §1.收口.6 Q1 答案落实:A1 sanitize fix 合并入 Phase 2 第 1 commit
- ✅ 32 NEW + 127 回归 = **159 total cases PASS**,0 regression
- ✅ INV-8 §1.5.12 lesson #3 / #4 实践应用:per-language path 显式分支 fix(zh 路径独立处理 `<ja>/<en>`)+ sanitize chain 边界不越位修(LLM 行为问题仍走 prompt-side prevention,本 fix 仅做 sanitize chain 边界 hardening)
- 🔒 0 LLM prompt 改动(本刀纯 sanitize 路径 hardening,不动 Layer A1 ja directive — per INV-8 §1.5.8 Phase 2 §2 将动 Layer A1 加 fish 子分支教 markers)

→ **Phase 2 第 1 commit closed**。下一刀 = **Phase 2 §2 · voice_config 4 字段 + fish provider raise validation**(per INV-8 §1.5.8 改造清单第 2 项)。

### §1.6 lesson(沉淀)

#### Lesson INV-9 #1 · sanitize fix 双层 invariant(fix 行为 + backward compat)

per INV-8 lesson #3(sub-language path 对称性)落实,新增 invariant:
- **fix 行为**:NEW skip 分支(case 4/6)严格 return `""` 让 caller skip synth — 不是"剥到剩中文"而是"直接放弃本句 TTS"
- **backward compat**:LLM 漏标整段(无任何 `<ja>` 字面)仍走原 fallback `strip_all_for_tts`(降级体验保留)— **不要让 NEW fix 把 backward compat path 一起搬走**

**抽象**:sanitize chain fix 时区分"残留字面 tag(LLM 半截 / round-trip 错锚)" vs "真无 tag(LLM 漏标)";两种 case 走不同分支,**前者 skip 后者 fallback**。

→ Phase 2 §1 closed。

---

## §2+§3+§4 TTS 抽象层 + Fish provider(Phase 2 第 2 commit, 2026-05-22)

> PM 拍板合刀:§2 太小 + §3/§4 互依(`_build_engine` fish 分支需 `fish.py` 存在,单独落地留破 import 中间态)。
> per INV-8 §1.5.8 改造清单第 2-4 项 + Hard Req per-provider 双重隔离(本 commit 仅 provider 层,LLM 端教 markers §5 + non-fish sanitize strip §6 留下一刀合刀,Hard Req 必须**双重隔离同时落**)。
> β inline `[bracket]` final lock(PM 2026-05-22 听完 WAV 确认 work)。

### §2 改动 · `backend/tts/voice_config.py`(+90 / -42 行,净 +48)

`VoiceConfig` dataclass 加 4 新字段(默认值齐;backward compat:旧 cosyvoice/edge/sovits voice_model JSON 不传新字段,VoiceConfig 用 default):

```python
@dataclass
class VoiceConfig:
    provider: str
    voice: str
    instruct_supported: bool = False
    model: Optional[str] = None
    # INV-9 §2 新增:
    tts_language: str = "zh"
    reference_audio_path: Optional[str] = None
    reference_text: Optional[str] = None
    fish_latency: str = "balanced"
```

`parse_voice_config` fish 分支 raise validation(per Step 5 决策 1 mode_A only lock,**不静默 fallback**;缺 ref 字段直接 `ValueError`):

```python
if provider == "fish":
    if not (isinstance(reference_audio_path, str) and reference_audio_path.strip()):
        raise ValueError("voice_config: provider='fish' requires reference_audio_path ...")
    if not (isinstance(reference_text, str) and reference_text.strip()):
        raise ValueError("voice_config: provider='fish' requires reference_text ...")
```

边角处理:`tts_language` / `fish_latency` 字符串规范化(`.lower()`);`reference_audio_path` / `reference_text` 空串 → `None`(`.strip()` 后 falsy)。

### §3 改动 · `backend/tts/__init__.py`(+7 行)

`_build_engine` 加 fish 分支:

```python
if cfg.provider == "fish":
    from backend.tts.fish import FishTTS
    return FishTTS(voice_config=cfg)
```

延迟 import:`fish_audio_sdk` 体积适中,仅在 fish 角色使用时加载。其它 provider 分支(cosyvoice / edge / sovits / 未知 fallback)完全不动 — 0 regression。

### §4 改动 · `backend/tts/fish.py`(新 +201 行)

`FishTTS(TTSBase)` 实现 mode_A only zero-shot voice cloning:

**构造**:
- defensive check ref 字段(parse_voice_config 已 raise 兜底)
- 一次性读 `reference_audio` bytes cached(避免每 turn 重读 1.2MB WAV)
- API key resolve 优先级:`FISH_API_KEY` env > `<repo_root>/api_key.txt`(dev 便利)> 空串 + warning
- backend lock `s2-pro`(model 字段默认),latency `balanced`(per Step 5 stage 2 lock)

**synthesize**:
- `asyncio.to_thread(self._blocking_synth, text)` 包阻塞 SDK call
- SDK 返 `Generator[bytes]`,sync collect 到完整 bytes(per Step 5 实测路径)
- `HttpCodeErr` / generic exception 全 catch + `log_tts_call` INSERT(per `cosyvoice.py` pattern)
- emotion 字段 fish 路径下**不使用**(per §1.3.7 schema β:emotion 走 inline `[bracket]` markers in text,不走单独参数);保留签名兼容 `TTSBase.synthesize`

**synthesize_stream** 不实(留 Phase 3 H3 fix 合刀,接 `stream_websocket` WebSocket 协议 + 实时 chunk yield;详 INV-8 §1.收口.4 Step 6 backlog)。

### §5 测试 + smoke 全绿 · 302/302 cases · 0 regression

#### Smoke 1 · NEW `tests/test_fish_provider.py`(37 cases)

```
[1.1] VoiceConfig 4 新字段默认值                       4/4 PASS
[1.2] VoiceConfig 显式赋值 4 字段                       4/4 PASS
[2.1] parse fish 缺 reference_audio_path → ValueError  1/1 PASS
[2.2] parse fish 缺 reference_text → ValueError        1/1 PASS
[2.3] parse fish ref_audio_path 空串 → ValueError      1/1 PASS
[2.4] parse fish ref_text 空串 → ValueError            1/1 PASS
[3]   parse fish 全字段 → VoiceConfig                   7/7 PASS
[3.1] parse fish 省略 fish_latency → 默 'balanced'      1/1 PASS
[4.1] parse cosyvoice cid=1 Mai · backward compat      4/4 PASS
[4.2] parse cid=2 八重 cosyvoice-v3.5-plus · backward  3/3 PASS
[4.3] parse 空 / None / 空白 → default                  3/3 PASS
[4.4] parse 非法 JSON → default 不抛                    1/1 PASS
[5.1] _build_engine cosyvoice → CosyVoiceTTS           1/1 PASS
[5.2] _build_engine fish → FishTTS(全字段)             4/4 PASS
[5.3] _build_engine fish 缺 ref → ValueError 抛        1/1 PASS

Results: 37/37 passed
```

#### Smoke 2 · 直调 `scripts/fish_provider_smoke.py`(纯 provider 层)

```
[smoke] 构造 FishTTS via get_tts_engine(voice_model_json)...
[smoke] engine class = _PreprocessingEngine        ← 工厂返包装层
[smoke] _inner class = FishTTS                     ← inner 真实例

[smoke] synth text = 'こんにちは、今日もよろしくお願いします。'
[smoke] ✅ synth OK in 2978.2ms
[smoke]    audio bytes = 245,804
[smoke]    audio dur ≈ 2.79s (44.1kHz mono)
[smoke]    out = scripts/fish_probe_outputs/INV9_smoke_basic_ja.wav

[smoke] synth text with marker = '[soft chuckle]ま、いいか。気にしないで。'
[smoke] ✅ marker synth OK in 1464.6ms       ← warm,快 ~50%
[smoke]    audio bytes = 192,556 dur ≈ 2.18s
[smoke]    out = scripts/fish_probe_outputs/INV9_smoke_with_marker.wav
```

通过 `get_tts_engine` 工厂(per ws.py:733 生产路径)→ `_PreprocessingEngine` 包 `FishTTS` → SDK call → audio bytes → `log_tts_call`。**整链路通**。

注意:`elapsed_ms` 是 sync collect 完整 audio 的时间,不是 TTFA;balanced TTFA gain 要 `synthesize_stream` 才能感知(Phase 3 H3 fix 合刀)。

#### Smoke 3 · 邻近 5 test suite 回归(265 cases)

| Suite | Cases | 状态 |
|---|---|---|
| `test_sanitize_ja.py`(INV-9 §1 NEW) | 32 | ✅ |
| `test_text_filters_ja_whitelist.py` | 38 | ✅ |
| `test_tts_final_guard.py` | 32 | ✅ |
| `test_tts_strip_fallback.py` | 57 | ✅ |
| `test_tts.py`(CosyVoice / Edge / SoVITS legacy 路径)| 106 | ✅ |
| **本 commit NEW** `test_fish_provider.py` | 37 | ✅ |
| **TOTAL** | **302** | **302/302 PASS** |

→ 0 regression。cosyvoice / edge / sovits legacy 链路完全不破。

### §6 关键 invariant 锁(per INV-8 §1.5.12 lesson #3 / #4)

- ✅ **mode_A only 强制 ref**(per Step 5 决策 1 lock):parse_voice_config raise 早于 _build_engine,defensive check in FishTTS.__init__;3 子 case 实证(缺 audio / 缺 text / 空串 都 raise)
- ✅ **provider 抽象边界清晰**:`_build_engine` 4 分支(cosyvoice / fish / edge / sovits)各自独立 + 未知 fallback;延迟 import 隔离 SDK 依赖
- ✅ **backward compat**:9 char DB 矩阵的 cosyvoice / cosyvoice-v3.5-plus / 空 voice_model 全场景 backward compat 实证(test 4.1-4.4 + smoke 3 回归 106 cosyvoice cases)
- ✅ **TTSBase 接口签名 stick** `synthesize(text, emotion) → bytes`(per Step 1 决策 3 lock);emotion 在 fish 路径下不使用(走 inline `[bracket]`),保留签名
- ✅ **per-provider sanitize Hard Req 待 §5+§6 合刀**:fish 接到 text 透传 `[bracket]`(本 commit 实);non-fish strip `[bracket]`(下一刀)+ Layer A1 教 markers(下一刀)
- ✅ **cost / balance API 可达**:`Session.get_api_credit()` + `get_package()`(per INV-8 §1.3.10 Step 5 实测);本 commit 不实 cost cap(留 §7)
- ✅ **PM 听感 final lock**:β inline `[bracket]` 在 PM 2026-05-22 听完 WAV 后 lock(per 上一轮 PM 决策);[soft chuckle] / [gentle] / [teasing] 等 markers SDK 接受 + 声学表达 work

### §7 收口

- ✅ §2 voice_config 4 字段 + parse fish raise validation
- ✅ §3 `_build_engine` fish 分支(7 行延迟 import)
- ✅ §4 `backend/tts/fish.py` 新建 201 行(synthesize 实现 + synthesize_stream 留 Phase 3)
- ✅ 37 NEW unit test + 直调 smoke + 265 邻近 regression = 302/302 PASS
- ✅ Smoke output WAV 保留(`scripts/fish_probe_outputs/INV9_smoke_basic_ja.wav` + `INV9_smoke_with_marker.wav`,`.gitignore` 已加)给 PM 听感验证
- 🔒 0 backend cap regression / 0 LLM prompt 改动 / 0 ws.py 改动 / cosyvoice / edge / sovits legacy 路径完全不破
- ⏳ 下一刀 = **Phase 2 §5 + §6 合刀**(per-provider 双重隔离 Hard Req · LLM 端 layer_a.j2 `{% if provider == 'fish' %}` 子分支教 markers + 后端 sanitize 链新增 `_FISH_EMOTION_MARKER_RE` + `strip_fish_emotion_markers` + `_PreprocessingEngine` 或 caller 按 provider 决定是否 strip `[bracket]`)

### §8 lesson(沉淀)

#### Lesson INV-9 #2 · provider 抽象分支延迟 import 隔离 SDK 依赖

`_build_engine` 4 分支 + 未知 fallback,每个分支用 `from backend.tts.<provider> import` 局部 import(per cosyvoice 现行 pattern continued)— **fish_audio_sdk** 体积虽适中(SDK + httpx-ws + ormsgpack + wsproto 共 ~500KB)但仅 fish 角色用到,延迟 import 让非 fish 路径无 dependency 加载开销 + 测试 / 部署环境若未装 fish-audio-sdk 也不破 cosyvoice 路径。

**抽象**:provider 抽象层的 SDK 依赖应**严格延迟 import**,放 if 分支内,避免顶层 import 把所有 SDK 都加载。类比 cosyvoice / edge / sovits 现 pattern,fish 新增分支沿用。

#### Lesson INV-9 #3 · mode_A only validation 在 parse 阶段 raise 而非 caller 阶段静默 fallback

per Step 5 决策 1 lock:fish 缺 ref 字段**不静默 fallback** — parse_voice_config 直接 raise ValueError,让 caller(get_tts_engine / _build_engine)立即报错;配错的 fish 角色不会沉默走 default voice 让用户体感"声音变了但不知为啥"。

**抽象**:provider 配置 validation 应在**配置解析阶段** raise,不在 caller 使用阶段静默兜底;早 raise 早暴露 = 配错可见。Phase 3 / Phase 2 后续 commits 沿用此原则(下一刀 layer_a.j2 fish 分支也要类似 — 配错 provider 时 prompt 渲染立即报错而非沉默漏 marker 引导)。

→ Phase 2 §2+§3+§4 closed。下一刀 = §5+§6 合刀(Hard Req per-provider 双重隔离 LLM + sanitize 两端同时)。

---

## §5+§6 Hard Req per-provider 双重隔离(Phase 2 第 3 commit, 2026-05-22)

> PM 拍板合刀:Hard Req 本身要求两端原子化同时落 — §5 alone(LLM 教 markers 但 cosyvoice 收 → garbled)+ §6 alone(strip 机制有了但 LLM 不发 → 没用),两个一起 = airtight per-provider isolation。
> β inline `[bracket]` schema final lock(PM 2026-05-22 听完 WAV 确认 work)+ Mai canon range marker 集 PM 直接给(冷静档 / 挖苦档 / 温柔档 / 罕见档 / Pause + 明确禁用激动 / 大声 / 失控类)。

### §5 改动 · 生成端(LLM prompt)

| 文件 | 改动 |
|---|---|
| `backend/agents/prompt/templates/layer_a.j2` | +50 行 / ja directive 内加 `{% if voice_provider == 'fish' %}` 子分支 |
| `backend/agents/prompt/renderer.py` | +3 行 / `render_system_prompt` + `_render_layer_a` 加 `voice_provider: str = "cosyvoice"` 参数 |
| `backend/agents/chat.py` | +5 行 / 同段 voice_model JSON parse 抽 `voice_provider` 字段透传 `render_system_prompt` |

`layer_a.j2` fish 子分支教 Mai canon range marker 集(per PM lock):

```
[Fish s2-pro 句内情感 markers - 仅 fish provider 模式启用]

placement: 单 / 多 / mid-sentence
适用 Mai 风格 marker 集:
  - 冷静档: [composed] / [calm] / [deadpan]
  - 挖苦档: [teasing] / [sarcastic] / [dry tone]
  - 温柔档: [soft chuckle] / [gentle] / [soft voice]
  - 罕见档: [mildly surprised] / [mild embarrassment]
  - 停顿(跨情绪): [short pause] / [pause] / [long pause]

明确禁用 — 超 Mai canon range:
  - [excited] / [shouting] / [screaming] / [laughing loudly]
  - 任何含"激动 / 大声 / 失控"语义的
  - 含"angry / 愤怒大叫"语义的强冲击 marker

格式约束:
  - markers 只在 <ja> 内,不进中文段
  - 不嵌套 / 不闭合形态
  - 每意群至多 2-3 markers
  - 平静对话可不带 marker
```

含 ✓ 正确示例 + 3 类 ✗ 错误示范(marker 误入中文段 / 用 paren / 超 canon range)。

注:**Mai marker 集是针对当前唯一 fish provider 角色的具体指导**;未来其它角色走 fish 时应按 character 定制 marker 集(本 commit 不实施,future expansion hook 在 `layer_a.j2` fish 分支位置)。

### §6 改动 · 接收端(sanitize chain + provider 分流)

| 文件 | 改动 |
|---|---|
| `backend/utils/text_filters.py` | +30 行 / `_FISH_EMOTION_MARKER_RE` + `strip_fish_emotion_markers` 新增;`strip_ja_en_tags_for_subtitle` 链尾追加 strip(字幕跨 provider 一律剥) |
| `backend/tts/__init__.py` | +25 行 / `_PreprocessingEngine` 加 `provider` 参数 + per-provider 分流(fish pass-through / non-fish strip);`get_tts_engine` parse cfg.provider 透传;**拆 `_LEGACY_BRACKET_NOTATION_RE` 出 `_PREPROCESS_PATTERNS`** + `preprocess_tts_text(text, strip_bracket_notation=True)` opt-in 让 fish 路径跳过历史 v3-F `[stage direction]` 剥(否则 fish 路径 markers 被 preprocess 误剥) |

关键发现 + fix(test 暴露):

```python
# Before fix:_PREPROCESS_PATTERNS 含 r"\[[^\]]+\]"(v3-F 时代设计剥
#            [stage direction] / [aside] notation)→ fish 路径下也剥 markers
# After fix:拆 _LEGACY_BRACKET_NOTATION_RE 独立 + opt-in 控制
preprocess_tts_text(text, strip_bracket_notation=True)   # non-fish backward compat
preprocess_tts_text(text, strip_bracket_notation=False)  # fish 路径 — 保留 [bracket]
```

`_PreprocessingEngine.synthesize` 完整双重 strip 链:

```python
is_fish = self._provider == "fish"
cleaned = preprocess_tts_text(text, strip_bracket_notation=not is_fish)
if not is_fish:
    cleaned = strip_fish_emotion_markers(cleaned)  # 显式 + 兜底 LLM 错放 markers
```

字幕层兜底:

```python
# strip_ja_en_tags_for_subtitle:
out = _JA_TAG_RE.sub("", text)
out = _EN_TAG_RE.sub("", out)
out = strip_fish_emotion_markers(out)  # ← 字幕跨 provider 一律剥
```

### §7 测试 · 35 NEW + 265 回归 = 337/337 PASS

#### Smoke 1 · NEW `tests/test_fish_marker_isolation.py`(35 cases)

```
[1] strip_fish_emotion_markers 单元(8 子)
    1.1 单 marker · [sarcastic] 剥                      1/1 PASS
    1.2 多 markers 跨句 · 全剥                          1/1 PASS
    1.3 mid-sentence [whisper] 剥                       1/1 PASS
    1.4 无 marker · pass-through                        1/1 PASS
    1.5 空 [] / 空白 [ ] 行为                           2/2 PASS
    1.6 嵌套 [outer[inner]] · regex 非贪婪              1/1 PASS
    1.7 中文【】不剥                                     1/1 PASS
    1.8 空 / None                                        2/2 PASS
[2] _PreprocessingEngine 分流(5 子)
    2.1 fish · 透传 markers                              2/2 PASS
    2.2 cosyvoice · 剥 markers                           2/2 PASS
    2.3 edge · 剥 markers                                1/1 PASS
    2.4 默认 cosyvoice · 剥                              1/1 PASS
    2.5 全 markers strip 后空 · skip synth + inner 未调  2/2 PASS
[3] e2e LLM raw → extract → preprocess engine(2 子)
    3.1 fish 路径保留 markers                            2/2 PASS
    3.2 cosyvoice 路径剥 markers                         2/2 PASS
[4] subtitle 字幕层(3 子)
    4.1 中文 + <ja>[marker]日语</ja> → 字幕 + 不含 [bracket] 2/2 PASS
    4.2 中文误带 [bracket] → 字幕兜底剥                  2/2 PASS
    4.3 无 marker pass-through                           1/1 PASS
[5] layer_a.j2 fish 子分支渲染(3 子)
    5.1 voice_provider='fish' · 渲染 Mai marker 引导     4/4 PASS
    5.2 voice_provider='cosyvoice' · 不渲染 marker 引导  2/2 PASS
    5.3 tts_language='zh' · 任何 provider 不渲染 ja markers 2/2 PASS

Results: 35/35 passed
```

#### Smoke 2 · 直调集成 `scripts/fish_marker_e2e_smoke.py`

Mai canon range 5 markers 各跑真合成 + cosyvoice mock 剥除 verify + subtitle 字幕跨 provider 剥除:

```
## Part 1 · fish 路径 5 markers 真合成
[composed]      ✅ 1843ms / 213KB ≈ 2.42s → INV9_e2e_fish_composed.wav
[sarcastic]     ✅  883ms / 148KB ≈ 1.67s → INV9_e2e_fish_sarcastic.wav
[teasing]       ✅ 1042ms / 180KB ≈ 2.04s → INV9_e2e_fish_teasing.wav
[gentle]        ✅ 2043ms / 139KB ≈ 1.58s → INV9_e2e_fish_gentle.wav
[soft chuckle]  ✅ 1374ms / 201KB ≈ 2.28s → INV9_e2e_fish_soft_chuckle.wav

## Part 2 · cosyvoice 路径(mock inner)· markers 剥除 verify
5/5 OK — inner 收到全部不含 [bracket],仅日语内容

## Part 3 · subtitle 字幕层 · 跨 provider 一律剥
5/5 OK — 字幕全部不含 [bracket]

e2e smoke: fish 5/5 + cosyvoice 5/5 + subtitle 5/5 = ✅ ALL PASS
```

5 WAV 输出到 `scripts/fish_probe_outputs/INV9_e2e_fish_*.wav`(`.gitignore` 已加),PM 听感对比 5 markers 声学表达 ↔ Mai canon range 是否契合。

#### Smoke 3 · 邻近 6 suite 回归(302 cases · 0 regression)

| Suite | Cases | 状态 |
|---|---|---|
| `test_sanitize_ja.py` | 32 | ✅ |
| `test_text_filters_ja_whitelist.py` | 38 | ✅ |
| `test_tts_final_guard.py` | 32 | ✅ |
| `test_tts_strip_fallback.py` | 57 | ✅ |
| `test_tts.py`(CosyVoice/Edge/SoVITS legacy) | 106 | ✅ |
| `test_fish_provider.py` | 37 | ✅ |
| **本 commit NEW** `test_fish_marker_isolation.py` | 35 | ✅ |
| **TOTAL** | **337** | **337/337 PASS** |

### §8 关键 invariant 锁(Hard Req 双重隔离契约 lock)

- ✅ **生成端(LLM)**:`voice_provider == 'fish'` 时 Layer A1 教 Mai canon range markers + 明确禁用超 range markers;其它 provider 不教(prompt 渲染条件分支)
- ✅ **接收端(provider 分流)**:`_PreprocessingEngine` 构造时 lock provider,synth 时 fish 路径 `preprocess_tts_text(strip_bracket_notation=False)` + 跳过 `strip_fish_emotion_markers`(完整透传)/ non-fish 路径相反(剥 + 显式 strip)
- ✅ **字幕层**:`strip_ja_en_tags_for_subtitle` 链尾追加 `strip_fish_emotion_markers` — 任何 provider 字幕都剥 `[bracket]`,用户字幕**永远不**出现 marker
- ✅ **切角色 / 切 provider 同步**:`get_tts_engine(voice_model)` 每 turn 重建 → provider 实时 lock 进 engine;LLM prompt 同步重渲染(per INV-8 §1.5.3 跨 turn voice 切换 audit:每 turn 重读 voice_model + 重渲染 prompt + 重建 engine);无 cache 滞后
- ✅ **fish 失败 fallback CosyVoice 时**:turn 内含 markers 的 text → CosyVoice 收到 stripped 版(非 fish provider 的 _PreprocessingEngine 强制 strip),不被 `[bracket]` 噎到(Hard Req 第 2 条契合)
- ✅ **legacy v3-F `[stage direction]` notation 剥行为 backward compat**:non-fish provider 走 `strip_bracket_notation=True` 保留历史行为(test_tts 等 106 cosyvoice cases 全绿实证)

### §9 收口

- ✅ §5 layer_a.j2 fish 子分支教 Mai canon range markers(50+ 行 Jinja directive)+ renderer / chat voice_provider 透传(3 行 + 5 行)
- ✅ §6 strip_fish_emotion_markers + `_PreprocessingEngine` per-provider 分流 + 字幕兜底 + preprocess_tts_text 拆 bracket opt-in(发现并 fix LLM markers 被 preprocess 误剥的 bug)
- ✅ 35 NEW + 265 邻近 regression + 7 markers 实际 fish 合成 + 5 cosyvoice mock 剥除 + 5 subtitle 剥除 = **337/337 cases / 5 fish synth / 0 regression**
- ✅ 5 e2e Mai canon range markers WAV outputs 保留(`scripts/fish_probe_outputs/INV9_e2e_fish_*.wav`)PM 听感验证
- 🔒 0 LLM 生成 / sanitize / TTS 主链路改动外的副作用;cosyvoice/edge/sovits legacy 路径完全不破
- ⏳ 下一刀(Phase 2 收尾刀)= **§7 cost cap + profile_data JSON**(per INV-8 §1.收口.6 Q7 + PM Phase 2 收尾调整 — **§8 cid=1→cid=101 数据迁移取消**,PM 后续 persona 更新时手动处理 momo slot → Mai persona 内容更新)

### §10 lesson(沉淀)

#### Lesson INV-9 #4 · preprocess 链路与新增 marker 语义的潜在冲突

`_PREPROCESS_PATTERNS` 含历史 v3-F 时代 `\[[^\]]+\]` regex 剥 `[stage direction]` notation,**与新 Fish `[bracket]` markers 语义冲突**(fish 路径 markers 被误剥)— test_fish_marker_isolation Part 2.1 / Part 3.1 暴露,fix = 拆 `_LEGACY_BRACKET_NOTATION_RE` 独立 + `preprocess_tts_text(text, strip_bracket_notation=True/False)` opt-in。

**抽象**:引入新语法(markers / 新 tag / 新 schema)时必须 audit **现有 sanitize / preprocess 链路是否含相同字面**的剥除 regex;若有,需 **per-feature opt-in** 或拆独立 regex 让新语义路径绕开。**类比 INV-7 lesson #9 三 grep 模式 + INV-8 lesson #3 sanitize sub-language path 对称性**:多路径 / 多语义共用 sanitize 链时,各路径 / 各语义需有独立 control。

#### Lesson INV-9 #5 · Hard Req 双重隔离的"两端原子化"必要性

PM 决策"§5 + §6 合刀"立 lesson 实证 — 单端落地任一,系统都不工作:
- §5 alone:LLM 教 markers 但 cosyvoice / edge / sovits 接收 → 字面念出 `[soft chuckle]` 等 → garbled
- §6 alone:strip 机制 deploy 但 LLM 不发 markers(Layer A1 未注入引导)→ sanitize 无 effect 浪费

**抽象**:跨层契约(LLM prompt ↔ runtime sanitize ↔ TTS provider)有双向依赖时,**两端必须同 commit 落地**;不可 split commit 留中间态。这是 INV-8 §1.5.12 lesson #4 "三层分工边界" 的对应正面例 — 三层不可错位修,**但跨层契约一致性需 atomic ship**。

→ Phase 2 §5+§6 closed。下一刀 = **§7 cost cap + profile_data JSON**(决策 5 实施;Phase 2 收尾刀,per PM 调整 §8 cid 迁移取消)。

**Phase 2 进度**:
- ✅ §1 sanitize A1 fix(`0aba951`)
- ✅ §2+§3+§4 TTS 抽象 + Fish provider(`f07a842`)
- ✅ §5+§6 per-provider 双重隔离(本 commit)
- ⏳ §7 cost cap + profile_data JSON(Phase 2 收尾刀)
- ❌ ~~§8 cid=1→cid=101 数据迁移~~(per PM 2026-05-22 取消 · 改 PM 手动 momo slot persona 更新)

---

## 中插 · 参数 sweep 刀(Phase 2 第 4 commit, 2026-05-22)

> PM Phase 2 中插刀(承接听 INV9_smoke_basic_ja + soft_chuckle 不够像 Mai 的观察)— Fish s2-pro temperature × text grid 实验诊断 Mai 音色 fidelity。
> 跟主线非冲突:仅改 provider 层(VoiceConfig + FishTTS)+ 加 sweep 脚本;不动 §5+§6 已 ship 的 prompt / sanitize 链路。
> Phase 2 §7 收尾刀 unblocked,本刀完后 PM 听 19 文件 → 拍板默认参数锁进 schema → 进 §7。

### sweep.1 改动文件清单

| 文件 | 改动 |
|---|---|
| `backend/tts/voice_config.py` | +24 行 / VoiceConfig 加 3 字段 `fish_temperature` / `fish_top_p` / `fish_seed`(都 Optional 默 None,parse_voice_config 缺字段不 raise per backward compat);float / int 类型转换 + log warning 容错 |
| `backend/tts/fish.py` | +20 行 / FishTTS 构造接 3 参数;`_build_request` 改 kwargs 模式 + 仅 if not None 透传 TTSRequest(确保未配 = SDK 真默认对照组);`fish_seed` 构造时 log warning("SDK TTSRequest does not accept 'seed' field; param ignored") |
| `scripts/fish_param_sweep.py`(新) | +240 行 / 16 主表 grid + 3 seed sanity + balance check + summary.json + 视觉表格 |

**关键设计决策**:
- `if self.temperature is not None: kwargs["temperature"] = self.temperature` — 未传 = SDK 默认(0.7);避免无意覆盖默认对照组
- `fish_seed` 字段保留作 future hook(SDK 1.3.0 TTSRequest 字段表实测**无 seed**字段,per `inspect TTSRequest.model_fields`);构造时 log warning,sweep 实证 byte-identical 与否

### sweep.2 Grid 结果 · 16 主表 + 3 seed sanity = 19/19 OK

#### Grid 矩阵(audio_dur_sec 视觉对比)

| temp | S1 (basic 日语) | S2 (Mai 自介 canon) | S3 (短 + marker) | S4 (长 + marker) | ms 中位数 |
|---|---|---|---|---|---|
| **T02** (0.2) | 2.37s | 6.50s | 1.53s | 5.02s | ~2610ms |
| **T04** (0.4) | 2.51s | 5.76s | 1.53s | 5.20s | ~2452ms |
| **T06** (0.6) | 3.20s | 6.04s | 1.72s | 5.43s | ~2903ms |
| **T08** (0.8) | 2.69s | 5.71s | 1.58s | 5.06s | ~2563ms |

19 WAV 输出 `scripts/fish_probe_outputs/INV9_param_T{02|04|06|08}_S{1|2|3|4}.wav` + `INV9_param_T04_S2_run{1|2|3}.wav`,`summary.json` 含每条 temp / text_id / seed / latency_ms / bytes / md5 + Grid 视觉总览 + seed verdict。

#### Seed sanity verdict · seed param NON-FUNCTIONAL(per PM 预案标注)

3 runs `T=0.4 S=S2 seed=42` 实测 md5:
- run1: `f37dd64467f52f664da898bdad068742`(585,772 bytes / 6.64s)
- run2: `85dc365d4a3c001958db3f941bd25441`(573,484 bytes / 6.50s)
- run3: `cfb6b78f3b47878926bc0c7928610772`(499,756 bytes / 5.67s)

**3 runs 全不同 md5 + 不同 audio bytes** → **seed param NON-FUNCTIONAL** 实证。这与 SDK introspect 结果一致(`fish-audio-sdk 1.3.0` `TTSRequest.model_fields` 不含 `seed`)。

PM 预案"不 identical → 在 summary 标注 'seed param non-functional'" 触发,`summary.json["seed_verdict"]` 明示。FishTTS 当前实现保留 `fish_seed` 字段作 future hook(若未来 SDK 加 seed 支持,改 FishTTS `_build_request` 加一行 `kwargs["seed"] = self.seed` 即可)。

#### Cost 实测 vs 估算

| 项 | 值 |
|---|---|
| 估算成本 | ~19 × $0.025 ≈ $0.50 |
| 实测 credit delta | $0.000(几乎不动 — Plus package 优先消耗) |
| 实测 package delta | 247,000 → 245,142 = **1,858 bytes** 实扣 |
| 折算 cost | 1858 / 1,000,000 × $15 = **~$0.028** |
| 实测 / 估算比 | ~5.6% — **远低于估算**!(估算用了"日语 1 char ≈ 3 bytes"但 sweep texts 总 char 数远低于估算的"19 × 100 字") |

**生产监控启示**:每 turn Mai 日语 100 字 ≈ 300 bytes,**实际 cost ~$0.0045/turn**;而非 INV-8 §1.3.6 估算的 $0.025/turn(estimate 偏高 ~5x)。Phase 2 §7 cost cap 设计可放宽 daily/monthly cap upper bound(per-user $1/day 已足 ~220 turns 余裕)。

### sweep.3 回归 + 测试 · 248/248 PASS / 0 regression

| Suite | Cases |
|---|---|
| `test_fish_provider.py`(VoiceConfig + parse fish + _build_engine)| 37/37 |
| `test_fish_marker_isolation.py`(per-provider 双重隔离) | 35/35 |
| `test_sanitize_ja.py` | 32/32 |
| `test_text_filters_ja_whitelist.py` | 38/38 |
| `test_tts.py` CosyVoice/Edge/SoVITS legacy | 106/106 |
| **TOTAL** | **248/248 PASS** |

VoiceConfig 加 3 新字段全部 Optional 默 None,**所有现有 voice_model JSON 不破**(verify 37 fish_provider cases + 106 cosyvoice cases legacy 全绿)。

### sweep.4 收口

- ✅ 19/19 calls OK(16 grid + 3 seed sanity)
- ✅ 19 WAV outputs + summary.json 输出 `scripts/fish_probe_outputs/`(`.gitignore` 已加)给 PM 听感对比拍板默认参数
- ✅ **seed param NON-FUNCTIONAL** 实证标注 + future hook 保留
- ✅ Cost 实测 ~$0.028(估算 5.6%);生产 cap 设计可放宽
- ✅ 0 regression(248 邻近 cases 全绿)
- 🔒 0 LLM prompt / sanitize 链路改动;Hard Req 双重隔离不受影响
- ⏳ PM 听 19 文件后拍板默认 (temperature, top_p) → schema 默认值锁,进 Phase 2 §7 收尾刀

### sweep.5 给 PM 听 + 拍板的点

PM 听 19 WAV 后选默认(temperature × top_p)组合(可能 across-S 共识 best 或 per-text 偏好):

- **维度 a · temperature 默认**:0.2 vs 0.4 vs 0.6 vs 0.8(各 4 文件对比)
- **维度 b · 单 text 跨 temp 偏好**:S1/S2/S3/S4 各跨 4 temp 听感最稳的那档
- **维度 c · seed 已 NON-FUNCTIONAL**:`fish_seed` 字段是否真 lock 进 schema 默认(CC leaning **保留**字段作 future hook,但 schema 默认 None 表示不传)
- **维度 d · 是否启用 top_p 调优**:本刀 top_p=0.7 固定未做 sweep;PM 若觉 temperature 不够 → 加 top_p sweep 单独刀

`summary.json` 含完整 19 条记录可读取交叉对比。

### sweep.6 lesson(沉淀)

#### Lesson INV-9 #6 · 第三方 SDK 字段表是真实接受参数集的 ground truth

PM brief 期望"固定 seed=42"控制采样确定性,但 `fish-audio-sdk 1.3.0` `TTSRequest.model_fields` introspect 实测**无 seed 字段** — sweep 实证 3 runs 全不同 md5 落实 verdict "seed NON-FUNCTIONAL"。

**抽象**:第三方 SDK 字段表(`pydantic.model_fields` / `dataclasses.fields()` / 类似 introspect)是**真实接受参数集的 ground truth**;docs 描述 / 用户假设可能与字段表偏离。引入新参数时必先 introspect,**不 blind 传 unknown field**(Pydantic 严格 unknown field 会 raise;非严格类型会 silently drop)。**类比 INV-9 #2(docs 是 contract / SDK 是 truth)** — INV-9 #6 是 SDK 字段表层面的同款 lesson。

→ Phase 2 中插刀 closed。等 PM 听 19 WAV → 拍板默认 → 进 §7 收尾刀。

---

## 中插 part 2 · T0.15/0.20/0.30 narrow window + T0.20 变异度(Phase 2 第 5 commit, 2026-05-22)

> PM 听完 part 1 19 WAV 后:**T=0.2 倾向最优**,但要 narrow 邻域多探 + T=0.2 内变异度。**不下探 T<0.15**(PM:更低听感会过死板)。
> 不动 backend(fish.py / voice_config.py 参数字段 part 1 已加),纯加 sweep 脚本。

### sweep_part2.1 改动

| 文件 | 改动 |
|---|---|
| `scripts/fish_param_sweep_part2.py`(新) | +250 行 / 20 calls grid + 变异度分析 + balance check + summary.json |

### sweep_part2.2 Grid 结果 · 20/20 OK

#### T=0.20 变异度分析(同 T 同 text 3 runs)

| text | run1 bytes | run2 bytes | run3 bytes | range | range/min | unique md5 |
|---|---|---|---|---|---|---|
| S1 | 282,668 | 249,900 | 262,188 | 32,768 | **13.1%** | 3/3 |
| S2 | 520,236 | 569,388 | 512,044 | 57,344 | 11.2% | 3/3 |
| **S3** | 151,596 | 118,828 | 143,404 | 32,768 | **27.6%** | 3/3 |
| S4 | 426,028 | 454,700 | 434,220 | 28,672 | 6.7% | 3/3 |

**关键发现**:
- ✅ T=0.20 同 text 3 runs **bytes 全不同 + md5 全不同**(per part 1 seed NON-FUNCTIONAL 一致 — 无 seed 控制 = 无 byte-identical 保证)
- ⚠️ 变异度 **6.7%-27.6%**;短 text S3(`[teasing] あら、来たのね。` ≈ 1.5s audio)变异最大(短 text 采样随机性放大)
- ✅ 长 text S4(~5s audio)变异最小(6.7%)— inherent stochastic dilutes in longer audio

#### 跨 T 跨 text audio_dur_sec 总览

```
 temp |   S1 |   S2 |   S3 |   S4
------+------+------+------+-------
 T015 | 2.65 | 5.99 | 1.58 | 5.16
T020.1| 3.20 | 5.90 | 1.72 | 4.83
T020.2| 2.83 | 6.46 | 1.35 | 5.16
T020.3| 2.97 | 5.81 | 1.63 | 4.92
 T030 | 2.60 | 5.81 | 1.49 | 4.88
```

**关键观察**:T=0.20 三 runs 之间的差异 ≈ T015↔T030 跨 T 差异。**T 维度对 audio_dur 影响 ≈ inherent stochastic variance**(0.15-0.30 narrow window 内);"默认 T"更多看 PM 听感而非 audio length。

#### Balance 观察(API 延迟刷新)

| | 实测 |
|---|---|
| balance start | credit=$9.965695 / package=245,142/250,000 bytes |
| balance end | credit=$9.965695 / package=245,142/250,000 bytes |
| **delta** | **0 bytes / $0**(本次 batch update 滞后)|

20 calls 实际跑通(WAV 输出正常 + 实际 Fish 服务响应)但 balance API 此次未刷新。Plus package API 已观察过 batch update 滞后(per part 1 也有 inflation 案例)。**生产监控建议**:cost cap 设计不依赖 balance API 实时 — 走本地 char→bytes 累计(per INV-8 §1.3.6 决策 5 重写),balance API 仅作 dashboard / 月报对账。

### sweep_part2.3 输出

20 WAV 文件:
- `INV9_param2_T020_S{1|2|3|4}_run{1|2|3}.wav`(12)
- `INV9_param2_T015_S{1|2|3|4}.wav`(4)
- `INV9_param2_T030_S{1|2|3|4}.wav`(4)
- `INV9_param_sweep_part2_summary.json`(全 20 records + 变异度分析 dict + balance start/end)

全部进 `scripts/fish_probe_outputs/`(`.gitignore` 已加)。

### sweep_part2.4 给 PM 听 + 拍板的维度

PM 听 20 文件后选默认 T:
- **维度 a · T015 vs T020 vs T030**:S1/S2/S3/S4 各跨 3 T 听音质稳定度(T015 死板 vs T030 飘的中间档)
- **维度 b · T=0.20 三 runs 变异度可接受性**:听 T020_S{1-4}_run{1-3} 12 文件,判 6.7%-27.6% byte 变化在听感上的实际差异(若听感差异 small → 接受 T=0.20 作生产默认;若大 → 调更确定档 T=0.15)
- **维度 c · 短 text 变异度(S3 27.6%)**:Mai 短句(如 `[teasing] あら` 1.5s)在生产是高频形态;若 S3 变异度过大 → 触发"短 text 走更低 T"per-call dynamic 设计(本轮不实施 Phase 3+ backlog)

### sweep_part2.5 收口

- ✅ 20/20 calls OK(12 T020 三 runs + 4 T015 + 4 T030)
- ✅ T=0.20 同 text 3 runs **bytes/md5 全不同**实证 → 进一步落实 SDK stochastic sampling 无 deterministic 控制(per part 1 seed NON-FUNCTIONAL)
- ✅ T 维度影响 ≈ inherent variance(0.15-0.30 narrow window 内)— 默认 T 选择**主要看 PM 听感**而非 audio_dur 量化指标
- ✅ 20 WAV + summary part2.json 输出
- ⚠️ Balance API 延迟刷新(0 delta)— 生产 cost 监控不依赖此 API
- 🔒 0 backend 代码改动;0 LLM prompt 改动;不破任何回归

→ **Phase 2 中插刀整段 closed**(part 1 19 calls + part 2 20 calls = 39 WAV outputs);等 PM 听 part 2 20 WAV → 拍板 final 默认 T(0.15 / 0.20 / 0.20 variance 接受 / 调 top_p)→ schema 默认值锁,进 §7 收尾刀(cost cap + profile_data JSON,**§8 cid 迁移已取消**)。

---

## 中插 part 3 · Part 1 vs Part 2 diff audit + repro(Phase 2 第 6 commit, 2026-05-22)

> PM 听后确认:Part 1 T=0.2(`INV9_param_T02_S{1-4}.wav`)质量**明显好于** Part 2 T=0.2 三 runs → 不是抽样运气,两脚本有实质差异需查清。
> 任务 1 · diff 两脚本所有维度。任务 2 · re-run Part 1 T=0.2 验服务器稳定性。任务 3 · 报告 audit verdict + 可能 mitigation。

### part3.1 任务 1 · 两脚本 diff audit

`diff scripts/fish_param_sweep.py scripts/fish_param_sweep_part2.py` 全部差异:

| 维度 | Part 1 | Part 2 | 影响 |
|---|---|---|---|
| docstring / 注释 | grid 4×4 + seed sanity | T0.20 × 3 + T015/030 + 变异度 | ❌ 无 |
| build_voice_model signature | `(temperature, top_p, seed)` | `(temperature, top_p=0.7)` | ⚠️ 见下 |
| **voice_model JSON `fish_seed` 字段** | **含 `"fish_seed": 42`** | **不含 `fish_seed`** | ⭐ **唯一实质差异** |
| `TEMPS` / `SEED` 常量 | 顶层 `[0.2,0.4,0.6,0.8]` / `42` | 不定义 | ❌ 无(Part 2 直接 literal) |
| `temp_label` 精度 | `T{n:02d}` (`T02`) | `T{n:03d}` (`T020`) | ❌ 无(仅文件名命名差) |
| summary 结构 | `calls` + `seed_sanity` | `calls_T020` + `calls_T015` + `calls_T030` + `variance_T020` | ❌ 无(record 形态差,数据等价) |
| balance check 路径 | `Path(...).read_text` | `api_key_file.read_text(encoding='utf-8')` | ❌ 无(都读同 file) |
| reference_audio 加载 | `(ROOT / "tts/fish/...").lab.read_text` | 同上 | ❌ 完全相同 |
| TTSRequest 构造 | (通过 `get_tts_engine → FishTTS._build_request`) | 同上 | ❌ 完全相同(走同一函数)|
| text 编码 | `.read_text(encoding="utf-8")` | 同上 | ❌ 完全相同 |
| import sequence / Session 构造 | 标准 | 同上 | ❌ 完全相同 |

**核心 verdict**:仅 1 实质差异 = voice_model JSON 是否含 `fish_seed: 42`。

**这一差异在代码层的影响**:
1. `parse_voice_config` → Part 1 `VoiceConfig.fish_seed=42` / Part 2 `None`
2. `FishTTS.__init__` Part 1 log warning(`SDK TTSRequest does not accept 'seed' field; param ignored`)/ Part 2 不 log
3. `_build_request` → **两路径都不向 TTSRequest 传 seed**(per fish.py 设计 + INV-9 #6 实证)

**结论**:在 **SDK 端 effective TTSRequest payload 完全相同**(text + references + format + latency + temperature + top_p)。两脚本理论上**应该**产生相同分布的 audio(但 stochastic 采样下每次不同 byte-level)。

### part3.2 任务 2 · Re-run Part 1 T=0.2 实测

`scripts/fish_param_repro.py` 用与 Part 1 完全相同的 build_voice_model(含 `fish_seed=42`)重跑 4 calls T=0.2,对比原 Part 1 输出:

| text | orig Part 1 bytes | repro bytes | Δ bytes | orig dur | repro dur | match |
|---|---|---|---|---|---|---|
| S1 | 208,940 | 258,092 | **+49,152** | 2.37s | 2.93s | md5✗ bytes✗ |
| S2 | 573,484 | 516,140 | **-57,344** | 6.50s | 5.85s | md5✗ bytes✗ |
| S3 | 135,212 | 159,788 | **+24,576** | 1.53s | 1.81s | md5✗ bytes✗ |
| S4 | 442,412 | 471,084 | **+28,672** | 5.02s | 5.34s | md5✗ bytes✗ |

**md5 match: 0/4 · bytes match: 0/4 · duration match: 0/4**

输出 4 WAV → `INV9_repro_T02_S{1|2|3|4}.wav` + `INV9_repro_summary.json`(`.gitignore` 已加)。

### part3.3 任务 3 · Verdict

⭐ **`fish_seed=42` 完全无效**(per INV-9 #6 已实证),Fish 服务器侧**每次 TTS call 独立采样**,即便:
- 完全相同的 reference_audio
- 完全相同的 reference_text
- 完全相同的 target text
- 完全相同的 temperature / top_p / latency / backend
- voice_model JSON 含 `fish_seed=42`(SDK 不识 → 不进 TTSRequest)

→ **Part 1 vs Part 2 听感差异 = 服务器侧抽样运气,不是脚本逻辑差**

这与 INV-9 #6 + #7 lesson 完全一致:
- INV-9 #6 · SDK 字段表是真实接受参数集 ground truth(无 seed)
- INV-9 #7 · stochastic noise floor 跟 T 维度信号同量级

数据印证:
- Part 1 T=0.2 4 文件听感好 = 那 batch 落在 happy-path 样本
- Part 2 T=0.20 12 文件(4 texts × 3 runs)= 跨更多样本暴露 stochastic floor 真实分布
- repro 4 calls 又是另一独立 batch,bytes / dur 全不同于 Part 1

### part3.4 Mitigation 选项(给 PM 拍板)

无 "脚本侧修复方案" — 服务器侧 stochastic 无 deterministic 控制。可能策略:

| Option | 描述 | 工程量 | trade-off |
|---|---|---|---|
| **M0 · 接受 stochastic**(CC leaning) | 设默认 T 后生产实际**每 turn Mai 声音都略有 byte-level 变化**(per part 2 T=0.20 三 runs 6.7%-27.6% byte variance);用户体感"每次说话略不同"= 自然声音特征 | 0 | 听感波动接受度由 PM 用户 dogfood 验 |
| M1 · 切 reference_id 预上传 voice | 走 Fish create_model 把 Mai reference 预存 + 用 reference_id 替代 references[] inline;**可能** server-side 用 cached voice profile 更稳(未实测) | 0.5d(create_model + voice_model JSON schema 加 reference_id 字段)| 不实证 server-side 是否真稳;若不稳 = 浪费工程 |
| M2 · retry per-sentence + 选最好 | 每句 synth 2-3 次 + 后端 audio quality scorer 选优 | 2-3d + 成本 2-3x | 复杂度 / 成本爆炸;quality scorer 难做 |
| M3 · 等 SDK 加 seed 支持(future hook) | `fish_seed` 字段保留 — 未来 SDK 加 seed support 时 fish.py 加一行 `kwargs["seed"]=self.seed` 即可 | 0(已保留) | 不可控时间表 |

**CC leaning M0**:接受 stochastic 作为 Fish s2-pro 的固有特性。PM 拍板默认 T 时主要看**多 runs 听感分布**(Part 1 4 + Part 2 12 + repro 4 = 20+ T=0.2 文件)而非单 batch 最优。

### part3.5 收口

- ✅ 任务 1 diff audit:唯一实质差异 = `fish_seed` 字段(SDK 不识 → TTSRequest payload 等价)
- ✅ 任务 2 re-run:0/4 md5/bytes/duration match → **服务器侧每次独立采样**实证(per INV-9 #6 一致)
- ✅ 任务 3 verdict + 4 mitigation options + CC leaning M0
- ✅ 5 WAV outputs(4 repro + 1 summary.json)
- 🔒 0 backend 代码改动;不破任何回归

→ **Phase 2 中插 part 3 closed**;Part 1 vs Part 2 听感差异 = 服务器侧抽样运气定案;**等 PM 拍板默认 T**(基于 part 1 + part 2 + repro 共 20+ T=0.2 多 batch 听感分布)→ 进 §7 收尾刀。

### part3.6 lesson 沉淀

#### Lesson INV-9 #8 · "复现失败"作为 audit 工具的双重价值

PM 怀疑 Part 1 vs Part 2 脚本差异时,**audit diff 的 falsifiable 假设**:
- (a) 若 diff 发现实质差异 + 改 Part 2 后复现 Part 1 → 脚本 bug,修
- (b) 若 diff 仅 cosmetic 差异 + Part 1 repro 不一致 → **服务器侧 stochastic 实证**(per part 3.2 数据)
- (c) 若 diff 实质差异 + Part 1 repro 一致 → diff 偶然 cosmetic(罕见)

**抽象**:面对"不同 batch 输出质量差异"假设时,**第一步永远是 audit 脚本 diff + 同条件 repro**,而不是直接猜服务器侧 / 改参数。本案 audit diff + repro 直接落实 INV-9 #6/#7 lesson 在 production decision 层面的应用:**Fish s2-pro 输出是 inherent stochastic,默认参数选择应基于多 batch 听感分布,不是 single batch 最优**。

**类比 INV-7 §1.7 lesson #9** 三 grep 模式 — INV-9 #8 是同款"先实测 / 后假设" 在 stochastic output 层面的应用。

### part3.7 PM 后续决策 · audit 留档不再扩(2026-05-22)

PM 听完 Part 1 + Part 2 narrow window 全 sweep 后:
- Part 1 T=0.2 仍是听感最优
- Part 2 narrow window(T0.15/0.20/0.30 多 run)整体不如 Part 1
- **zero-shot from 7s reference 有硬天花板,不再调参**

**Audit 留档不再扩**:
- audit 实证 SDK `fish-audio-sdk 1.3.0` stochastic 行为(per part3.2 0/4 md5 match)
- Lesson INV-9 #8 保留作长期 reference(future 类似 stochastic audit 沿用方法论)
- 不再 iterate temperature / 不扩 sweep — 进 §7 收尾刀
- 真正 fidelity 升级路径转入 **v4.1+ 多 provider 扩展 backlog**(per PM 2026-05-22 重定向 · GPU fine-tuned 远程 Fish 微调 hybrid + GSV (GPT-SoVITS) provider;详 ROADMAP v4.1+ 多 provider 扩展刀)

**关键 reference 数据**:43 WAV outputs(part 1 19 + part 2 20 + repro 4)在 `scripts/fish_probe_outputs/` 本地保留,v4.1+ fine-tuning / 多 provider 评测时作 zero-shot baseline 对比;5min Mai 素材在 `tts/fish/参考音频/mai/` 完整保留作训练(GPU fine-tune)+ GSV reference 起点。

---

## §7 cost cap + profile_data JSON(Phase 2 第 7 / 收尾 commit, 2026-05-22)

> per INV-8 §1.3.6 决策 5 重写 + INV-9 §1.收口.2 Q7 + PM Phase 2 §7 lock(2026-05-22)。
> **Phase 2 整段收尾刀**:决策 5 实施 + cid=101 fish_temperature=0.2 lock(per PM 听感 part 1/2/repro 后定案 — zero-shot 7s ref 硬天花板,默 T 选 Part 1 T=0.2 happy-path)。
> **§8 cid=1→cid=101 数据迁移已取消**(PM 2026-05-22 改手动 momo slot persona 更新)→ §7 是 Phase 2 真收尾。

### §7.1 改动文件清单

| 文件 | 改动 |
|---|---|
| `backend/utils/cost_estimator.py`(新) | +180 行 / `FISH_S2_PRO_COST_PER_M_BYTES_USD=15.0` + `DEFAULT_DAILY_CAP_USD=1.0` / `DEFAULT_MONTHLY_CAP_USD=20.0` + `estimate_fish_cost_for_text` / `_for_chars`(ja/zh 3 bytes / en 1 byte 兜底)+ `get_user_cost_caps(profile_data)` 读 JSON + default + `get_today_fish_cost_usd` / `get_month_fish_cost_usd` DB 聚合 + `check_fish_cost_cap_exceeded(user_id)` 主入口 |
| `backend/observability/tts_log.py` | +20 / -5 行 / `estimate_cost(input_chars, model, raw_text=None)` 加 fish family 路径(`s2-pro`/`s1`/`v1.6` → byte-based);cosyvoice 路径不变 backward compat;`log_tts_call` 内调用传 `raw_text=input_preview`(caller 多数传完整 text) |
| `backend/routes/ws.py` | +43 行 / `_handle_message` 读 voice_model 后 + `get_tts_engine` 前加 fish cost cap check;触达 → `voice_model = None`(fallback yaml default CosyVoice longyumi_v3)+ `ws.send_json({"type":"tts_cost_cap_exceeded", ...})` 给前端 toast |
| `frontend/src/hooks/useWebSocket.ts` | +20 行 / `WsMessage` interface 加 4 字段(reason / today_cost / month_cost / daily_cap / monthly_cap)+ `case 'tts_cost_cap_exceeded'` handler 调 `s.pushNotification({type:'notify', content:'今日/本月 Fish 配额已用 $X / $Y,本轮切回 CosyVoice'})` |
| `tests/test_cost_estimator.py`(新) | +280 / 34 cases / 7 estimate fish 单元 + 6 get_caps + 5 estimate_cost tts_log 桥接 + 6 集成(DB 聚合 + profile_data 覆盖触发 cap)+ 5 edge |
| **DB UPDATE** `characters.id=101` | voice_model = `{"provider":"fish","voice":"mai5min_0033","model":"s2-pro","tts_language":"ja","reference_audio_path":"...","reference_text":"...","fish_temperature":0.2}` — PM 听感 lock T=0.2 + 其它 fish_* default(per PM "不强制覆盖 SDK 默认")|

合计代码 +540 行 / 测试 +280 行 / docs +200 行 = ~1,000 行(略超 PM Phase 2 §7 ~250-300 LoC 预估,因 cost_estimator 完整 module + 34 cases 测试 + frontend 双向贯通)。

### §7.2 cost 估算路径

`tts_log.estimate_cost(input_chars, model, raw_text)` 双路径:

```python
if model in ("s2-pro", "s1", "v1.6"):
    # Fish family · byte-based per INV-8 §1.3.6 $15/1M UTF-8 bytes
    if raw_text:
        return len(raw_text.encode("utf-8")) / 1_000_000 * 15.0  # 精确
    return input_chars * 3 / 1_000_000 * 15.0  # 日语兜底
else:
    # cosyvoice / sovits / edge backward compat per-char rate
    return input_chars * _COST_PER_CHAR.get(model, 0.0007)
```

**caller fish.py / cosyvoice.py** 调 `log_tts_call(input_preview=text, ...)` 传完整 text;`log_tts_call` 内部 `estimate_cost(raw_text=input_preview)` 算精确 bytes,然后 `input_preview` 才截 200 chars 给 log 表的 `input_preview` 列。

### §7.3 cap check 路径(ws.py 主入口)

```python
# ws.py:_handle_message 读 voice_model 后
if voice_model:
    _vm = json.loads(voice_model)
    if _vm.get("provider") == "fish":
        cap_status = await check_fish_cost_cap_exceeded(user_id)
        if cap_status["exceeded"]:
            logger.warning("[tts] fish cost cap %s exceeded ...", cap_status["reason"])
            voice_model = None  # fallback yaml default CosyVoice
            await ws.send_json({"type": "tts_cost_cap_exceeded", ...})
tts_engine = get_tts_engine(voice_model)  # voice_model=None → yaml default longyumi_v3 + tts_language=zh
```

**Fallback 路径副作用**:
- voice_model=None → get_tts_engine yaml default 走 CosyVoice longyumi_v3 + tts_language="zh"
- LLM 输出走 zh 路径(layer_a.j2 ja 分支不触发)→ 中文裸文本
- **本轮**(turn)Mai 临时变 zh / cosyvoice 声音;下一轮 turn 用户若仍在 cap 内继续走 fish
- 前端 NotificationToast 提示 "今日/本月 Fish 配额已用 $X / $Y,本轮切回 CosyVoice"(4 sec 自动消失)

### §7.4 集成 test 触发链(`test_cost_estimator.py` Part 5)

PR-grade 集成 test:
1. INSERT `tts_call_log` 模拟 fish call cost=$0.01
2. PATCH `users.default.profile_data` 加 `fish_daily_cost_cap_usd=0.0001`
3. `check_fish_cost_cap_exceeded("default")` 返 `{exceeded: True, reason: "daily", today_cost: $0.81, daily_cap: $0.0001}`
4. 验 `exceeded==True / reason=="daily" / daily_cap==0.0001`
5. teardown:restore profile_data + DELETE test rows

集成 test passed 实证完整 cap check 路径(profile_data 读 + DB 聚合 + 判定)。

### §7.5 测试 + smoke · 345/345 PASS / 0 regression

| Suite | Cases |
|---|---|
| `test_cost_estimator.py`(NEW) | **34/34** |
| `test_fish_provider.py` | 37/37 |
| `test_fish_marker_isolation.py` | 35/35 |
| `test_sanitize_ja.py` | 32/32 |
| `test_text_filters_ja_whitelist.py` | 38/38 |
| `test_tts.py` CosyVoice/Edge/SoVITS legacy | 106/106 |
| `test_bugfix_4_observability.py` | 31/31 |
| `test_tts_final_guard.py` | 32/32 |
| **TOTAL** | **345/345 PASS** |

`tts_log.estimate_cost` signature 加 `raw_text=None` 默认参数 backward compat — `test_bugfix_4_observability.py` 31 case 全绿实证。

### §7.6 cid=101 DB UPDATE(PM lock fish_temperature=0.2)

```sql
UPDATE characters SET voice_model = '{
    "provider": "fish",
    "voice": "mai5min_0033",
    "model": "s2-pro",
    "tts_language": "ja",
    "reference_audio_path": "tts/fish/参考音频/mai/mai5min_0033.wav",
    "reference_text": "自分の方が可愛いって自覚あるくせに、別の誰かのことを可愛いとか言ってる女がサクタは好きなの?",
    "fish_temperature": 0.2
}' WHERE id = 101;
```

DB 备份 `momoos.db.backup_inv9_§7_20260522_*` 已存(`.gitignore` 已加 `*.db.backup_*`)。

Per PM "其它 fish_* 字段保持 default 不强制覆盖 SDK 默认":
- 显式 lock:`fish_temperature=0.2`(per Part 1 listen verdict)
- 不写 `fish_top_p`(VoiceConfig 默 None → 不传 TTSRequest → SDK 默 0.7)
- 不写 `fish_seed`(per INV-9 #6 SDK 不识)
- 不写 `fish_latency`(VoiceConfig 默 "balanced" — INV-8 §1.3.10 实测 ~593ms TTFA 最优)

### §7.7 关键 invariant 锁(Phase 2 收尾)

- ✅ **决策 5 实施完整**:本地 cost 累计(per-byte 精确 / per-char 兜底)+ profile_data per-user cap(default $1/$20)+ 触达 cap → fallback CosyVoice + frontend NotificationToast
- ✅ **cap fail-safe**:DB 异常 / profile_data 读失败 → `check_fish_cost_cap_exceeded` 默认放行(不让 DB 抖动 fish 路径全断)
- ✅ **historical row 偏保守**:旧 fish call cost_estimate(per-char rate 高估)被 SUM 时 fail-safe 偏早触发(不 leak 真实用量)
- ✅ **cid=101 Mai 真实生产化**:DB row fish provider + fish_temperature=0.2 lock;用户 CharacterPanel UI 切到"樱岛麻衣"即走 fish + Mai 日语(per INV-8 §1.4.7 cid=101 三件事完整契合)
- ✅ **single-user 假设**:tts_call_log 无 user_id 列,聚合不分 user(per single-user 现状);multi-user 精确 per-user 聚合留 v4.1+ backlog
- 🔒 **backward compat**:cosyvoice / edge / sovits 路径完全不破(test_tts 106 + test_bugfix_4_observability 31 全绿);frontend 老前端忽略 `tts_cost_cap_exceeded` 未知 type(per useWebSocket 老前端无 case → silent ignore)

### §7.8 收口

- ✅ §7 改动 6 文件 ship(cost_estimator 新 / tts_log fish path / ws.py cap check + fallback + WS event / frontend useWebSocket toast handler / 34 test cases / DB cid=101 UPDATE)
- ✅ 345/345 cases PASS / 0 regression
- ✅ 集成 test 实证完整 cap trigger path(profile_data 极低 cap → exceeded=True → reason="daily")
- ✅ frontend NotificationToast 复用现有 store `pushNotification` API(无需新 component)
- 🔒 Phase 2 主体改造 7 文件全 ship(per INV-8 §1.5.10 + PM Phase 2 拍板清单 Q5)+ §1 sanitize fix + §2/3/4 抽象 + §5/6 双重隔离 + 中插 sweep 1/2/3 + §7 cost cap
- 🔒 §8 cid=1→cid=101 数据迁移取消(per PM 2026-05-22 改手动 momo slot persona 更新)
- 🔒 Phase 3 流式管线 + Step 6 H3 fix + 11 log 点 instrumentation 留待后续(per INV-8 §1.收口.4)

### §7.9 lesson(沉淀)

#### Lesson INV-9 #9 · cap fail-safe 方向选择 · 偏保守 vs 偏放行

cost cap check 在 DB 异常 / profile_data 读失败时 2 选 1:
- **偏放行**:`exceeded=False` 默认 → 不让 DB 抖动让 fish 路径全断;cost 可能短暂超 cap(unmonitored 短窗)
- **偏保守**:`exceeded=True` 默认 → DB 抖动时整个 fish 路径自动 fallback CosyVoice;cost 不超 cap 但用户体感变化

本 §7 选 **偏放行**(`exceeded=False` on error)— 理由:cap check 是辅助治理不是 critical path,DB 抖动让 fish 全断会让用户体感"突然中文化"频次过高;真实生产 cap 触达通常是渐进的(逐步累积接近 cap),不是瞬间 spike,放行短窗 cost 可控。

**抽象**:辅助治理路径(quota / rate-limit / monitoring)的失败方向应该**偏向不打断主流程**(per 类比 INV-7 §1.7 lesson #10 `_CAPABILITY_TAG_RE` fallback 失效接受 trade-off — 同款"辅助路径失败不阻断主链"原则)。

#### Lesson INV-9 #10 · estimate_cost signature 加 optional kwarg 模式

`estimate_cost(input_chars, model, raw_text=None)` 新加 `raw_text` 默 None — 既支持精确 byte 估算(fish 路径 caller 传完整 text)又保持 backward compat(cosyvoice 老 caller 不传 raw_text 走 input_chars × rate)。

**抽象**:估算 / 度量函数升级时,**新精度选项加 optional kwarg + 默 None** 是最 backward-compat 模式;不破现有 caller signature 不强制升级,新 caller 渐进采用。**类比 INV-9 #3 mode_A only validation parse 阶段 raise 不静默 fallback** — #10 是同款"渐进升级"思路在度量函数层面。

→ Phase 2 §7 closed · Phase 2 整段 closed。

### §7.10 Phase 2 整段 closure summary

7 commits + 1 DB UPDATE:
- ✅ §1 sanitize A1 fix(`0aba951`)
- ✅ §2+§3+§4 TTS 抽象 + Fish provider(`f07a842`)
- ✅ §5+§6 per-provider 双重隔离(`9a7608c`)
- ✅ 中插 part 1 · 参数 sweep(`6ddc94f`)
- ✅ 中插 part 2 · narrow window 变异度(`416d488`)
- ✅ 中插 part 3 · diff audit + repro · stochastic verdict(`b34ad70`)
- ✅ §7 cost cap + profile_data + cid=101 fish lock(本 commit)

**Phase 2 整段 closed**。后续:
- Phase 3 流式管线 + H3 fix + Step 6 instrumentation(per INV-8 §1.收口.4)
- **v4.1+ 多 provider 扩展刀**(per PM 2026-05-22 重定向 · ROADMAP v4.1+):
  - **GPU 远程 inference** — FastAPI wrap `/tts` HTTP endpoint,backend 新 `RemoteFishTTS(TTSBase)` 对接(GPU always-on 配合 backend 直连**无冷启动延迟**)
  - **GSV** — GPT-SoVITS 官方 `api.py` 直接用,backend 新 `GSVTTS(TTSBase)` provider
  - 触发:PM GPU 资源就位 + API key 配齐
  - reference:`b34ad70` audit 数据 + Lesson INV-9 #8 + `tts/fish/参考音频/mai/` 5min Mai 素材
- v4.1+ multi-user per-user cap 精确聚合(tts_call_log 加 user_id 列)
- 等 PM 启 Phase 3 / next milestone



### sweep_part2.6 lesson 沉淀

#### Lesson INV-9 #7 · Stochastic sampling 的"参数 sweep 解释力"边界

T=0.20 三 runs byte range 6.7%-27.6% × T015↔T030 跨 T audio_dur 差异同量级 → **T 维度信号被 inherent stochastic noise 淹没**(0.15-0.30 narrow window 内)。

**抽象**:做 single-param sweep 调采样模型时,需先 audit"同参数多 runs 的 variance"作 noise floor;若 sweep dimension 影响 ≈ noise floor → **该 dimension 对生产决策的信号有限**,需要更激进 sweep range 或多维 sweep。

**应用**:本轮 PM 拍板默认 T 的依据应该是**听感对比 6+ runs**(part 1 T02 + part 2 T020 × 3 runs)而非 audio_dur 量化指标;若听感 also 在 noise floor 内 → 默认 T 选择**对生产质量无显著影响**,选 SDK 默认 0.7 也 acceptable(降低维护配置 + 信任 SDK 调优)。

**类比 INV-9 #6**(SDK 字段表 ground truth)— #7 是同款"实测胜过假设"在 stochastic 输出层面的应用。



