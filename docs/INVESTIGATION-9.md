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
