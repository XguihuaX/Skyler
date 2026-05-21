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

