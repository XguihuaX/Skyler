# Lessons (Quick Reference)

> 跨 INV 系列沉淀的工程教训速查表 · 单行索引 + 一句话总结 + 跳转到详细 memory entry。
> 完整正文见 `~/.claude/projects/.../memory/inv11_lesson_N_*.md`(或对应 INV doc 沉淀段)。
>
> 更新时机:新 lesson 沉淀 → 同步加一行;不删旧 lesson。
> 当前覆盖:INV-7/8/9/10/11/13 阶段 lessons(18 条)。

---

## TL;DR · 高频引用 top 3

- **#17 audit 必须 DB 定量 + counter-example · 防 narrative 先行** · INV-13 §11 误诊教训 · 推 Option D 后 §12 数据反驳
- **#11 backward compat fallback 短期可接受 · long-term force migration** · 不要把 fallback 当永久补丁
- **#14 hardcoded ≥ 5 entries → 升级 json config + pydantic** · 防 model/registry 数据膨胀

---

## Full table (按 # 顺序)

| # | 主题 | 一句话 | 来源 / 触发 |
|---|---|---|---|
| 1 | sanitize ja/en 半截 tag fallback 双层 invariant | NEW skip 分支处理半截开 tag · 原 fallback 留作"无 tag 漏标整段"兜底 · 两层语义不可合并 | INV-9 §1 sanitize A1 fix |
| 2 | 延迟 import 隔离 SDK 依赖 | fish SDK 在 `_build_engine` fish 分支内 `import` · 其他 provider 不依赖时 module 不加载 | INV-9 §2+§3+§4 fish provider ship |
| 3 | mode_A validation parse 阶段 raise · 不静默 fallback | voice_config parse 时缺 reference_* 直接 raise · 比 runtime "音频空" 静默吞错好 | INV-9 §2+§3+§4 fish provider ship |
| 4 | preprocess 链与新 marker 语义冲突需 per-feature opt-in | `_LEGACY_BRACKET_NOTATION_RE` 拆 `_PREPROCESS_PATTERNS` 加 `strip_bracket_notation: bool` · 防 fish `[markers]` 被历史 regex 误剥 | INV-9 §5+§6 per-provider 双重隔离 |
| 5 | Hard Req 双重隔离两端原子化必要性 | 生成端(layer_a.j2 `{% if provider == 'fish' %}` 子分支)+ 接收端(sanitize provider 分流)同 commit 落 · 单边 ship 中间态可能 LLM 输出 markers 漏剥进字幕 | INV-9 §5+§6 |
| 6 | SDK 字段表 introspect 是真源 | `TTSRequest.model_fields` introspect verify 字段存在性 · 比 docs / brief 假设可靠;Fish SDK 1.3.0 实测无 seed | INV-9 中插 part 1 Fish 参数 sweep |
| 7 | stochastic sampling 参数 sweep 解释力边界 | T 维度信号被 inherent stochastic noise 淹没 → 默认 T 选择主要看 PM 听感而非 audio_dur 量化 | INV-9 中插 part 2 narrow window |
| 8 | 复现失败作 audit 工具的双重价值 | 先 audit diff + repro 同条件 · 后改参数 · Fish s2-pro stochastic 实测确认服务器侧抽样运气 · 不是脚本侧 bug | INV-9 中插 part 3 Part 1 vs Part 2 repro |
| 9 | cap fail-safe 偏放行原则 | tts_cost cap check 失败时静默放行(不阻断 main chat)· 辅助治理路径失败不能拖死主链 | INV-9 §7 cost cap ship |
| 10 | 度量函数升级 backward-compat 渐进采用 | `estimate_cost` 加 optional kwarg(raw_text)· caller 渐进迁移 · 不破老调用点 | INV-9 §7 cost cap ship |
| 11 | backward compat fallback 短期可接受 · long-term force migration | GSV `_resolve_weights_field(gpt_weights/gpt_path)` fallback 当下接受 · 留 v4.1 migration v2 force upgrade backlog · 不当永久补丁 | INV-11 Stage 1 GSV 真接入 |
| 12 | early modal ≠ 终态 paradigm | voice picker ship 时先做 modal · paradigm 完整后(provider × model × voice 3 级 + 父表单还有其他字段)inline 一屏体验更好 | INV-11 Stage 1.5 paradigm B |
| 13 | label 必须如实 reflect 行为 | cosyvoice-v3.5-plus 起初标 "复刻 voice 专用" 误导用户 · 实际支持系统 + 复刻双轨 · label 不准 = 功能 hidden | INV-11 Stage 1.5 followup Part A |
| 14 | hardcoded → json config 升级触发条件 | ≥ 5 entries + "改这个数据"是非开发活动(运维 / PM 配)→ 升级 json + pydantic validate + 启动 fail-fast + missing-file fallback | INV-11 Stage 1.5 followup Part B |
| 15 | GSV paradigm 2 mode (trained vs zeroshot) schema 前瞻 | tts_models.json gsv model entry 带 `mode` 字段 · 缺省视为 "trained" 向后兼容 · zeroshot 占位为 future ref upload UI 预留 | INV-11 Stage 1.5 followup Part C |
| 16 | audit_ja_persist 残留 policy 在大切换后需 review | `main.py:484` strip ja 是为 Mai zh-only 时代设计 · INV-11 切 ja 后该 policy 没人复查 · 也没人想起来撤 · 大架构切换时应该全 grep 老 policy(eg `grep -rn "audit_ja\|ja_persist\|zh_revert"`)审视前提是否仍成立 | INV-13 §11.7 / §12.7 |
| 17 | audit 必须 DB 定量 + counter-example · 防 narrative 先行 | INV-13 §11 audit 漏做 DB 定量统计就 jump 到 root cause · 推 Option D 误诊。§12 用 conv=62 20-turn JA streak counter-example + per-source compliance ratio(proactive 100% / normal 91%)直接否定 §11 假设。先 numbers 后 narrative · 假设有矛盾时 search 现成 fix(`grep skip_short_term`)防 reinvent | INV-13 §11.8 / §12 method |
| 18 | 旧 zh-only 字数约束在 ja 切换后会跟 directive 撞车 | trigger prompts `_invite_base.py` "8-15 字硬约束"(2026-05-08 chunk4-C 写)+ Layer A ja directive "中文意群 ≥ 10 字"(INV-11 加)= LLM 陷 thinking debug · token 耗尽。修法 = trigger prompt 加 ja-aware 段(字数按中文部分算)+ 软化硬约束。设老约束时复查"未来语种切换会破吗?" | INV-13 §11.5 + Option F+G ship |

---

## 主题聚类

### TTS provider × model × voice paradigm (INV-9 / INV-11)
#2 SDK 隔离 / #3 fail-fast validation / #4-5 per-provider 双重隔离 / #6 SDK introspect 真源 / #11 fallback 阶段化 / #12 modal→inline / #13 label 真 / #14 hardcoded→json / #15 GSV 2 mode

### stochastic / sampling 实验方法论 (INV-9 中插)
#6 SDK 字段表 / #7 sweep 解释力 / #8 复现失败作 audit 工具

### sanitize / format-tag 链路 (INV-8 / INV-9)
#1 ja/en 半截 tag 双层 invariant / #4 preprocess opt-in

### 度量 / 治理 (INV-7 / INV-9)
#9 cap fail-safe 放行 / #10 度量函数 backward-compat

### Audit 方法论 (INV-13)
#17 DB 定量 + counter-example 先行 / #16 大切换后老 policy review / #18 旧约束在切换后撞车

---

## 与 ROADMAP / DESIGN_LITE 的关系

- Lesson 是**回溯型沉淀** · 不规定未来怎么做
- 触发未来动作时:lesson → ROADMAP backlog 立项(eg #11 → migration v2 force upgrade backlog · #14 → ROADMAP 加新 model 走 json playbook)
- 通用模式 → DESIGN_LITE 加段(eg #14 hardcoded→json 升级规则可入 DESIGN_LITE §5.x 配置管理)

## 加新 lesson 的流程

1. 沉淀时机:**修正性**(从失败 / 走弯路得到)OR **确认性**(意外发现某做法 work 且非显然)
2. 写入 `~/.claude/projects/.../memory/inv<N>_lesson_<M>_<slug>.md`
3. 单行加进本表(# / 主题 / 一句话 / 来源)
4. 主题聚类有现成桶 → 加进去 · 没桶 → 新增桶
