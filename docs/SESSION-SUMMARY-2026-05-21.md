# Session Summary · 2026-05-21 · v4.1 Token 治理整轮 closed → TTS Phase 准备

> 本文档目的:给下一个对话(TTS 模块化 + Fish 集成)作起点参考,新会话粘此文件 +
> INVESTIGATION-INDEX + ROADMAP + DESIGN_LITE 即可承接完整上下文。

---

## 1 · TL;DR (3 行)

- v4.1 token 治理子轨 A (prompt caching) + 子轨 B (工具治理 fold 6 commit) 整轮 ship 完毕
- path D 评测 (Qwen-Plus vs DeepSeek-V4-Pro 盲测) closed,角色感无显著差异 → 留 deepseek-v4-flash 当前生产
- 下一轮 (新对话) = TTS 模块化抽象层 + Fish Speech 官方 API 集成 (s2 pro zero-shot)

---

## 2 · 本轮(2026-05-21)已完成

### 2.1 子轨 A · Prompt Caching 启用

- INV-5 closure 声明(§5.5 收口,后续追加进 IMPLEMENTATION_LOG / 不再修主文)
- 9 commit 主轴 + 6 commit 前置清账 ship(`b10fa2b` Phase 4 文档落地为终点)

主轴 9 commit 序列:

| # | commit | Phase | 内容 |
|---|---|---|---|
| 1 | `53f0331` | Phase 2 | renderer 返 `(stable, variable)` 二元组 + layer_c.j2 拆 + content blocks 拼装 |
| 2 | `c0ed1ec` | Phase 3 | `EXPLICIT_CACHE_PROVIDERS` 白名单 + `_inject_cache_marker` + config flag |
| 3 | `5af572e` | Phase 4.1 | `_token_probe._flatten_system_content` 兼容 list-of-blocks content |
| 4 | `95c5d72` | Phase 4.2 | config.yaml 4 处 model prefix `openai/` → `dashscope/` + migrate script + DB id=16 apply |
| 5 | `4d906d0` | Phase 4.3 | probe schema 扩 + `stream_options={include_usage:True}` + stream end emit |
| 6 | `77120df` | Phase 4.3.1 | `_extract_cache_fields` 从 `prompt_tokens_details` 内取 cache_creation/cache_type(LiteLLM 字段嵌套位置 fix) |
| 7 | `d2ab7cb` | Phase 4 回归 | 10 caller direct trigger 真机回归(8 非主链 caller 单 string content,自动 no-op) |
| 8 | `b10fa2b` | Phase 4.4 | INV-5 §5 收口 + INDEX + IMPL_LOG + ROADMAP 4 处真源对齐 |
| 9 | `1b88e0f` | 衍生 | 子轨 A/B 期间散落 backlog 落档(per PM 纪律) |

- warm cache 命中 system 段 **5,655 token**,**dev 测试覆盖率 99.8%**(per INV-5 §5.2.1
  COLD turn 1 cache_creation_input_tokens=5,655 → WARM turn 1 cached_tokens=5,655)
- 适用 provider prefix:**`dashscope/` + `openai/deepseek/`**(per `EXPLICIT_CACHE_PROVIDERS`
  白名单);其它 prefix 自动 no-op
- 主路径 cache 覆盖率与真实 conv 命中率差距来自 5-min ephemeral TTL × Mai 间歇陪伴节奏

### 2.2 子轨 B · 工具治理 6 commit (P2 + P3 + 4 dispatcher fold)

| 顺序 | 主题 | commit | tools_schema | 单刀减幅 | 累计 |
|---|---|---|---|---|---|
| 1 | P2 长 desc 压缩(10 cap) | `72808ef` | 13,250 → 10,336 | -2,914 | 22.0% |
| 2 | P3 character.set_activity 退役 → `<state_update>` tag 接管 | `81205f5` | 10,336 → 9,954 | -382 | 24.9% |
| 3 | P1.media 5→1 fold(模板首刀) | `a835677` | 9,954 → 9,697 | -257 | 26.8% |
| 4 | P1.apple_calendar 4→1 fold(复用 #1) | `f20a931` | 9,697 → 9,606 | -91 | 27.5% |
| 5 | P1.bilibili 11→1 fold(复用 #2 · 最大头) | `6bac94a` | 9,606 → 8,437 | -1,169 | 36.3% |
| 6 | P1.netease 13→2 双 dispatcher fold(复用 #3 · 收尾) | `e0bd2ba` | 8,437 → 7,301 | -1,136 | **44.9%** |

- 累计 tools_schema(synthetic dev 测):**13,250 → 7,301 token / -5,949 / -44.9%**
- 真实生产 tools_schema(含 ext.* MCP runtime 注册):**~9,402 token / -29% off baseline**
  (per PM 真机实测)
- 5 lesson 沉淀(per INV-7 § 收尾归档 B.2):
  - **#1-#6** · dispatcher 模板 6 要点(命名 / 单一 enum union schema / handler routing /
    旧 cap clean cut / smoke 三档 / 行为兼容性)— 见 INV-6 §2.7.4
  - **#7** · audit 双 grep 模式(cap-name + Python module import)— P1.apple_calendar 实证
  - **#8** · dispatcher 实写 chars 比预估高 30-80%(union schema 描述 + enum + wrap overhead)
  - **#9** · audit 第三维度 frontend `startsWith` pattern(P1.bilibili 实证,3 prefix retro-fix)
  - **#10** · `_CAPABILITY_TAG_RE` fallback regex 失效(挂 backlog,无 evidence 触发不修)
- 模板复用 3 次(apple_calendar → bilibili → netease)
- INV-3/4/6 已封存,INV-7 子轨 B 收尾刀 ship 后整轮 closed

### 2.3 Path D 评测 closed

- 框架 commit:**`6853e0f`** `feat(eval): add path D evaluation framework (Qwen Plus
  vs DeepSeek-V4-Pro blind comparison)`(+642 行)
- 3 dev script:
  - `scripts/path_d_eval.py` — runner(绕开 client.py 直调 litellm.acompletion 避免
    `_dashscope_kwargs()` 污染 DeepSeek 路径,per INV-5 §4 T5 模式)
  - `scripts/path_d_eval_renderer.py` — 匿名化 markdown 报告(每场景独立 random 把
    qwen/deepseek 分配 "输出 1"/"输出 2",mapping 持久化盲态)
  - `scripts/path_d_eval_scoresheet.py` — 4 维度空白评分表
    (persona / tag / 自然度 / 工具决策)
- 5 场景 × ~5-6 turn × 2 model = **52 calls**(server-side error 4/52 ≈ 7.7%,
  InternalServerError × 3 + APIError × 1,renderer 已标 ⚠️ ERROR 跳过)
- 5 场景:daily_chat / affectionate / boundary / factual / emotional_dip
- **结论(PM 盲态评分判定):DeepSeek-V4-Pro 与 Qwen-Plus 角色感无显著差异**
- DeepSeek auto-cache 实测 turn 1 cold `miss=10,649 hit=0` → turn 2+ warm `hit=10,624
  miss=25-36`,**~99.7% prefix 覆盖**(per INV-5 §4 T5 实证延续到 multi-turn)
- 决定:**留 deepseek-v4-flash 当前生产**(同家族最便宜成员,陪伴质量无显著差异 →
  按价格选)
- 评测 artifacts(本地,不进 git):`logs/path_d_eval/*.jsonl` + `logs/path_d_eval_report.md`
  + `logs/path_d_eval_scoresheet.md` + `logs/path_d_eval_mapping.json`

---

## 3 · 当前生产状态 (snapshot at 2026-05-21 23:xx)

- **Main chat LLM**:`deepseek/deepseek-v4-flash`(DB `ai_providers` active row,
  provider id=18;`config.yaml:1 default_model` 仅 yaml fallback,当前 DB 有 active 不走它)
- **Prompt caching**:enabled(`config.yaml prompt_caching.enabled: true` + `EXPLICIT_CACHE_PROVIDERS`
  覆盖 `dashscope/` + `openai/deepseek/`)
- **tools_schema 真实生产**:**9,402 token**(含 ext.* MCP runtime;synthetic dev test 显 7,301)
- **avg prompt size**:~**16,700 token/turn**(real chat conv 44)
- **cache 命中率**:~**12.5% warm hit**(Mai 间歇陪伴 × 5-min ephemeral TTL dominance,
  cold start 频次高于 dev 测试连续 1.5s 间隔的 99.8%)
- **主路径单 turn 真实成本**:~¥**0.005-0.015**(warm hit) / ~¥**0.033**(cold miss)

---

## 4 · 未做的事(下一轮 TTS Phase)

### 4.1 主线 · TTS 模块化 + Fish 集成

- **Layer 1** · `TTSProvider` 抽象接口 + voice config schema + per-voice prompt
  addendum 机制 + LLM 双语输出改造
- **Layer 2** · Fish Speech s2 pro zero-shot 集成 + 流式管线(含句间停顿 fix)+
  quota tracking + fallback to CosyVoice
- **Layer 3** · (远期)Fish on-device self-hosted 自训练 model · **不在本轮范围**

### 4.2 PM 已拍板的 5 个 TTS 核心决策(下一轮直接以此为前提,不重新议)

1. **LLM 双语输出**:`<display_zh>中文(chat 显示)</display_zh><tts_ja>日语(送 TTS)</tts_ja>`,
   流式顺序中文先 / 日语后,前端按 tag 分流
2. **Fish 部署**:官方 API s2 pro standard + zero-shot voice cloning(不用自训练),
   200 min/月配额
3. **TTS 模块化**:`TTSProvider` 接口抽象,CosyVoice 重构进抽象层,Fish 新增,
   voice ↔ character mapping(Mai = Fish,其它角色 = CosyVoice)
4. **Fish 句内情绪**:emotion markers 句内嵌入(syntax 待 INV-8 §1.3 audit),
   LLM prompt per-voice addendum 说明
5. **Fallback + Quota**:软降级(Fish 失败 / quota 满 → CosyVoice + 前端 toast),
   实时跟踪本月 audio 时长达 90% / 100% 阈值

### 4.3 Phase 1 INV-8 §1 audit scope(新对话第一刀)

- **§1.1** · 句间停顿 0.5-1s 反人类 4 假设拆分实测 ⚠️ **重点前置**
- **§1.2** · 现有 TTS 调用链路 audit(CosyVoice 路径 + chunk-6b 流式管线)
- **§1.3** · Fish API + s2 pro zero-shot docs 调研(含句内 emotion syntax)
- **§1.4** · voice ↔ character ↔ language ↔ prompt 关系审计
- **§1.5** · LLM 流式输出 + 双语 schema 协调 design space
  (Option A 起步 + 备选 C/D/E 简评)

---

## 5 · Backlog 仍挂着的项(本轮未处理)

### 5.1 需 PM 一次性触发

- **frontend `yarn build`** · 4 处 tool_labels.ts retro-fix 待生效(P1.media / P1.apple_calendar /
  P1.bilibili / P1.netease 累计 5 prefix 改);当前生产 UI loading label 显 fallback "查询中…"
  而非具体文案

### 5.2 evidence-driven(无触发不做)

- **lesson #10** · `_CAPABILITY_TAG_RE` 容忍单字 cap-name(独立 PR ~10 行) · 监控 chat_history
  错误回退污染再做;P1.media / apple_calendar / bilibili / netease ship 后无观察
- **P4** · MCP `ext.*` lazy-load · 单 MCP 场景 ROI 不够,等多 MCP 真实使用再议
- **v4.1 三件 memory 远期** · 20k 多层 buffer / lightweight RAG / 关系认知引擎 ·
  等朋友测试反馈

### 5.3 文档 backlog

- **DESIGN_LITE §5.7** · model 解析路径文档(config.yaml fallback vs DB active 优先级,
  per `_resolve_db_provider_kwargs` 行为)
- **INV-3 §10.9** · extractor 5-min 频率 audit
- **INV-3 §10.9** · DashScope 偶发 Connection error worker retry 审计
- **INV-5 §5.6** · Qwen Plus vs Max / Plus vs DeepSeek 评测候选(后者 path D 已 close,
  前者保留)

### 5.4 TTS 子项(并入 INV-8 §1.1-§1.5 audit)

- 句间停顿 0.5-1s 根因(已升级为 Phase 1 重点前置)
- 多语言文本路由策略(含 LLM 中日双语输出 schema)
- Fish 句内情绪 syntax 探明

---

## 6 · 工作流纪律(强约束,新对话承继)

### 6.1 PM-CC 工作流

- **PM** = 规划 / 决策 / 写 brief / 审 stage 报告
- **CC** = 审计 / 设计 / 落代码 / 写 INV / 报告停手
- 每 stage 之间停手,PM 拍板再进下一 stage

### 6.2 文档纪律

- **调查 / audit / 评测** → INV files(当前 active = **INV-8**,本轮新建)
- **实施 / 新功能 / 架构修改** → ROADMAP / DESIGN_LITE / IMPLEMENTATION_LOG
- INV 是单流,跨 ~1,000 行换下一个,INVESTIGATION-INDEX 记封存
- INV-3 / 4 / 5 / 6 / 7 已 closure(content sealed,formal seal 标注按需追加)

### 6.3 代码改动纪律

- Multi-stage:audit → design → PM 拍板 → 落代码 → smoke 验证 → INV 收口
- 每 stage 独立 commit,git status 干净
- 任一 stage 出意外 → 停手报告,不 hot fix

### 6.4 Brief 偏离纪律

- CC 看到仓库现实约定 vs brief 起冲突 → 按仓库约定走 + 透明报告偏离
- 不盲信 brief 假设,实测优先

---

## 7 · 关键文件指针(新对话需要时翻这些)

| 文件 | 作用 |
|---|---|
| `docs/INVESTIGATION-INDEX.md` | 主导航 |
| `docs/INVESTIGATION-3.md` | v3-G 早期审计(性能 + extractor) |
| `docs/INVESTIGATION-4.md` | 子轨 B 设计 + token 密度方法论 |
| `docs/INVESTIGATION-5.md` | 子轨 A prompt caching 实施 + T1-T5 探针 |
| `docs/INVESTIGATION-6.md` | 子轨 B 前 3 commit(P3 / media / apple_calendar) |
| `docs/INVESTIGATION-7.md` | 子轨 B 后 2 commit(bilibili / netease)+ B closure 归档 |
| `ROADMAP.md` | v4.1 全状态 + backlog(repo root) |
| `DESIGN_LITE.md` | 整体架构(repo root) |
| `IMPLEMENTATION_LOG.md` | 已 ship 实施记录(repo root) |

> 注:`ROADMAP.md` / `DESIGN_LITE.md` / `IMPLEMENTATION_LOG.md` 在 **repo root**,
> 非 `docs/` 子目录(per 仓库现实)。

---

## 8 · 新对话起步建议(TTS Phase)

新对话粘 prompt 后 PM 写 INV-8 §1 audit brief,CC 按 §6.3 Multi-stage 接力。

第一 stage = **INV-8 §1 audit**(纯只读 30-60 分钟),输出 §1.1-§1.5 五节 audit 报告。
PM 审完决定 Phase 2 Layer 1 设计起点。

新对话粘以下 4 个文件即承接完整上下文:
1. 本文件 `docs/SESSION-SUMMARY-2026-05-21.md`
2. `docs/INVESTIGATION-INDEX.md`(跨 INV 索引)
3. `ROADMAP.md`(当前 v4.1 状态 + backlog)
4. `DESIGN_LITE.md`(整体架构)

> 本文档 **lock 状态**:2026-05-21(本会话归档时刻)。后续如 token 治理或 path D
> 有新数据,在 `IMPLEMENTATION_LOG.md` 追加,**不修本文**。
