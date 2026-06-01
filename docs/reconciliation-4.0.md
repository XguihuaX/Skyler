# MomoOS-v2 4.0 — 文档 vs 代码 对账报告

> 生成时间：2026-05-31
> 基线：代码 = 事实唯一来源；文档若与代码冲突，默认文档过时。
> 范围：根目录 README/ROADMAP/DESIGN_LITE + docs/ 下主要 INV/SESSIONS + backend/* + frontend/src/*。
> 注：本报告只读不改，所有结论附 `文件路径:行号` 证据；无证据点写"未找到 / 无法确认"。

---

## 0. 总览（≤10 行）

4.0 实际跑通的子系统：① Persona 五层框架（DB-backed，唯一活跃 variant）、② 四层记忆（short-term 25 turn · conversation_summary 有界滚动摘要 · long-term memory 表 · users.profile_data）、③ TTS 三 provider（CosyVoice 默认 + Fish-Speech mode_A + GSV mai_v4，Edge 兜底）、④ Live2D（pixi-cubism4 单 runtime，Hiyori/Yae 两份模型）、⑤ 前端双推拉 + 8 主题 + Settings V2、⑥ ASR Whisper（INV-14 修复后已走 hf-mirror）、⑦ Proactive（5 trigger + activity smart）、⑧ Activity Timeline + 5 道隐私闸、⑨ 双向 MCP、⑩ Calendar/网易云/mpv/bilibili/xhs。整体 drift 程度：**中**——架构层文档基本可信，"角色×语言×模型"具体绑定与"4.0 收口前后状态"是重灾区。最该警惕的 3 处：(a) **Mai (cid=1) 语言已被 mai_revert_zh 拉回 zh + cosyvoice/longyumi_v3，文档多处仍写"GSV mai_v4 ja"**；(b) **ROADMAP 提的 `rolling_summary` 表名在代码里不存在，真名 `conversation_summary`**；(c) **switch_character LLM tool 已下线（registry.py:99）但 builtin.py 函数体和 schema 仍保留，前端 WS character_switch frame 才是真路径**。

---

## 1. 记忆架构

| 条目 | 文档怎么说（出处） | 代码实际（文件:行） | 差异 | 判定 | 建议动作 |
|---|---|---|---|---|---|
| short-term raw cap | README.md:187-191、DESIGN_LITE.md：cap=30 turn | `backend/memory/short_term.py:40,44` 实际 `SHORT_TERM_MAX_TURNS=25`（=50 messages）；硬编码 | 数字差 30 → 25 | A | 文档改 25 |
| 隔离层级 | DESIGN_LITE：三级 `(user, character, conversation)` | `short_term.py:79-87` 实际二级 `(user_id, character_id)` bucket，conversation 仅在读端过滤；`conversation_summary` 才是三级 `(user, character, conversation_id)` | 部分一致：摘要层三级、short-term 实际二级 | A | 文档拆开说清两层隔离粒度不一样 |
| 滚动摘要表名 | ROADMAP.md:141-142 称 "实测 `rolling_summary` 表 89 行全空" | 代码里只有 `conversation_summary`（`v4_0_0_conversation_summary.py:54-70`、`summary.py:241/273/280/301`、`extractor.py:330`）；grep 全仓 0 命中 `rolling_summary` | **表名错** | A | ROADMAP 改为 `conversation_summary`，重新核 89 行实测对象 |
| 滚动摘要工作机制 | DESIGN_LITE.md:202-208：worker 按 `last_folded_chat_history_id` 增量折叠 | `summary.py:425-459` fold_worker；阈值 `SUMMARY_BATCH_TURNS=10`、`token_budget=1000`、触发条件 `chat_history > 60`（`summary.py:59-109`）；ChatAgent 注入：`chat.py:1305-1317` | 机制一致；触发阈值 60 turn 文档未写 | 一致 | 文档补"触发阈值 60 turn / batch 10 / budget 1000 token" |
| confidence 质量门 | README.md:187-191："10-stage 质量 filter" | `utils/memory_entry_validator.py:267-274` 实际 `min_confidence` 默认 0.5，可配；filter 数实际是 5 道而非 10 道（length / SUSPICIOUS_TAG / confidence / tombstone / cosine dup） | 数量夸大 10 → 5 | A | 文档改"5 道质量 filter（含 confidence 阈 ≥ 0.5）" |
| save_memory tool | README.md/DESIGN_LITE：LLM 可调 save_memory | `chat.py:495-509` schema 注册（type ∈ fact/instruction/emotion/activity/daily），写入 `memory` 表标 `extraction_source='llm_save_memory'`（`chat.py:615-733`）| 一致 | 一致 | — |
| tombstone | DESIGN_LITE.md:186-193："墓碑修复链已 ship" | `memory_tombstone` 表（`v4_0_0_memory_tombstone.py:49-58`），cosine ≥0.92 或 content 精确等 → 压制；`memory_entry_validator.py:276-286`、`chat.py:656-668` 双侧检查 | 一致 | 一致 | — |
| forgetting curve | README.md:187-191：`score = relevance * (1+log(1+ac)) / (1+age*decay)` | `long_term.py:210-227` 公式完全相同；默认 threshold=0.3、age_decay_factor=0.01；`_bump_access_counters()` 每次召回更新 | 一致 | 一致 | — |
| user profile | README.md:187-191、DESIGN_LITE：`users.profile_data` JSON | `models.py:25-33` 字段存在；生成器 `services/profile_regen.py:6-16,46-48`（4 mode：cron/manual_incremental/manual_reset/delete_conversation）；最小化门 7 天内 user msg < 10 跳过；`profile_summary` 字段已退役 | 一致；`profile_summary` 退役细节文档未写 | A | 文档加一句"`profile_summary` 已退役，全 profile_data" |
| extractor worker | README.md:187-191："每 5 分钟运行" | `main.py:676-683` lifespan startup 起 `MemoryExtractor.run_loop()`；间隔 300s 可配；扫 user/normal turn 增量；`extraction_source='worker'` 写 `memory` 表 + 同次调 `fold_summaries_for_user()` 折叠摘要 | 一致 | 一致 | — |
| prompt 注入顺序 | DESIGN_LITE.md：summary → short-term → 当前 user | `chat.py:1259-1281` renderer 顺序：① stable system（persona + base + tool_addendum）→ ② variable block（profile + activity + long_memory top5）→ ③ rolling summary（独立 system 块，若有）→ ④ short-term ≤25 turn → ⑤ current user | 一致 | 一致 | — |

---

## 2. TTS 子系统

| 条目 | 文档怎么说（出处） | 代码实际（文件:行） | 差异 | 判定 | 建议动作 |
|---|---|---|---|---|---|
| Mai (cid=1) 当前 voice | README.md:30、179-180、ROADMAP.md:29-30、DESIGN_LITE.md:573-577：**GSV `mai_v4` 16-emotion ja TTS** | `v4_0_0_mai_revert_zh.py:50-75` ship-call **回退 cid=1 → cosyvoice `longyumi_v3` / `tts_language='zh'`**；hotfix 行 76-84 给 WHERE 加 provider scope（仅在 NULL 或 'cosyvoice' 时 nudge，切去 gsv/fish/edge 后短路） | **核心 drift**：文档说 ja-via-GSV，代码默认 zh-via-cosyvoice。需运维手动改为 gsv 才能"突破" revert | A | README/ROADMAP/DESIGN_LITE 必须改成"cid=1 默认 zh + cosyvoice/longyumi_v3；可手动改 voice_model 切到 gsv/mai_v4，后续 mai_revert_zh 不会再覆盖（hotfix scope 保护）"；cid=101 才保留 ja |
| CosyVoice SSML | INV-11 实验文档 | `tts/cosyvoice.py:15-21` 注释明确：chunk 1a SSML emotion 方案**已撤销**（DashScope 官方 SSML 不含 emotion 属性），改回 v3-D 起的 `instruction` 参数路径；前端 `tts.ts:11-13` VoiceInfo 接口删除 ssml 字段 | 一致：撤销结论已落地 | 一致 | DESIGN_LITE 主文档若仍提"enable_ssml"开关需删除 |
| CosyVoice instruction 参数 | DESIGN_LITE.md:314-399 | `cosyvoice.py:173-181,201-202` 字段名为 `instruction`（非 `instruct_text`），≤128 chars，固定模板 `"你说话的情感是{emotion}。"`；v3.5-plus/v3.5-flash 不支持 instruction → skip 走 plain text（`cosyvoice.py:77-85,164-172`） | 文档抽象，实际有版本差异 | A | 文档补一句"v3.5-plus/flash 不支持 instruct，仅 longanhuan/longanyang 等老 voice 走 emotion" |
| Fish-Speech LoRA | README/DESIGN_LITE 暗示"自训角色音色" | `tts/fish.py:1-11` 仅支持 mode_A（reference_audio + reference_text inline）；**无 LoRA / 自训权重**；`fish.py:80-109` 缺失时 raise ValueError；`routes/fish_config.py:157-243` user upload reference audio | 文档隐含 LoRA 实际不支持 | A | 文档明示"Fish 仅 zero-shot 参考音频，无 LoRA" |
| GSV (GPT-SoVITS) | ROADMAP.md:29-30：Stage 1 真接入 + mai_v4 + 16 emotion + `/set_gpt_weights` lazy-init | `tts/gsv.py:1-62` 调本地 9880，timeout 30s（CPU 50s 会 fallback stub）；16-emotion bank 真实存在 | 一致 | 一致 | — |
| 3 provider paradigm | README.md:179-180、DESIGN_LITE.md:314-399 | `tts/registry.py:86-139` 默认三 provider（cosyvoice/fish/gsv）+ Edge 兜底；`config/tts_models.json` 是配置真源 + pydantic + fallback hardcoded | 一致 | 一致 | — |
| voice_aliases | DESIGN_LITE：复刻 voice 友好名 | `database/voice_aliases.py:19-60`、`migrations/bugfix_3_4_voice_aliases.py:57-69`：表实存，仅服务复刻音色 display_name；前端 `voiceAliases.ts:14-60` | 一致 | 一致 | — |
| VoicePicker UI | README.md:179-180 / ROADMAP.md:29-30：inline + paradigm B + auto-save 300ms | `frontend/src/components/character/VoicePicker.tsx:1-8,220-241`：inline 3 级 dropdown；`setTimeout 300ms → patchCharacter()`；create 模式不 PATCH | 一致 | 一致 | — |
| voice_lines 试听 | DESIGN_LITE | `frontend/src/components/character/VoiceLinesSection.tsx:1-97` 独立 section，支持上传 + random pick | 一致 | 一致 | — |
| Edge / SoVITS | README："Edge legacy fallback" | `tts/edge.py:1-51` 无情感、返 MP3、TTSManager 兜底；`tts/sovits.py` 旧占位无新路由（`tts/__init__.py:1-11`） | 一致 | 一致 | — |
| TTS 推流路径 | DESIGN_LITE | `routes/ws.py:731-790,790-849` per-sentence 并发入 queue 顺序推；`audio_chunk` base64；前端 `lib/ttsAudio.ts:22-71` HTMLAudioElement + WebAudio analyser 接口 | 一致 | 一致 | — |

---

## 3. Persona 系统

| 条目 | 文档怎么说（出处） | 代码实际（文件:行） | 差异 | 判定 | 建议动作 |
|---|---|---|---|---|---|
| Schema 字段数 | README.md:85-88、DESIGN_LITE.md:521-539：Tier-1 7 必填 + Tier-2 可选 | `database/models.py:78-127`：Tier-1 7 字段 ✓；Tier-2 5 个（`taboo_topics`/`lore`/`capability_overrides`/`style_preset`/`description`）；控制字段 4 个（`is_builtin`/`is_active`/`display_order`/`variant_name`） | 一致 | 一致 | — |
| 多 variant + UNIQUE | DESIGN_LITE.md:521-539 | `models.py:124-127` + `v4_persona_thickening_segment1.py:165-168` 部分 UNIQUE INDEX `WHERE is_active=1`；loader `agents/prompt/persona_loader.py:79-98` 按 `is_active==True` 严格查 | 一致 | 一致 | — |
| Mai persona 大小 | DESIGN_LITE.md:571-589："Mai 满字段 ~9018 chars" | seg1 seed (`v4_persona_thickening_segment1.py:76-120`) 生成基础骨架；DB 实测 cid=1 character_personas 行 ≈ 2471 bytes（7 个 Tier-1 字段汇总） | 数量差远（9018 vs 2471） | A | 9018 可能含其它表（如 `characters` 表 description / lore），需 PM 复核口径 |
| F1 六角色完整性 | ROADMAP.md:122：cid=2/3/4/5/99/100 是空骨架 | `v4_persona_segment2_ensure_defaults.py:33-75` `_build_empty_default_seed` 每个 cid 生成空 list/empty dict；DB 实测 5 个角色 character_personas 行 ≈ 515-522 bytes（差不多就是 schema 字段名 + null） | 一致：六角色确为空骨架 | 一致 | — |
| Mai 语言 | DESIGN_LITE.md:571-589：voice_model='gsv'/'mai_v4'/'ja' | `v4_0_0_mai_revert_zh.py:50-75` 强制回 zh+cosyvoice/longyumi_v3 | drift（同 TTS 表已列） | A | 同上 |
| voice_samples tolerance filter | DESIGN_LITE.md:521-539："tolerance_range 运行时风格滑块" | `agents/prompt/renderer.py:265-288` 真在跑：`filter_samples_by_tolerance()`；filter 空 → fallback 全集 + warning（行 72-109） | 一致 | 一致 | — |
| prompt_manager 数据源 | README.md:479-483：Plan B（DB 主 + yaml fallback） | `backend/config/prompt_manager.py:30-44` 初始化时一次性加载 yaml 到内存字典；运行时 `chat.py:1259` → `render_system_prompt` → `load_active_persona`（**DB**）；prompt_manager 仅作 fallback / 旧路径 | 一致 | 一致 | — |
| switch_character tool | README.md:479-483："commit 71b6e99 已下线"、ROADMAP.md:204-205："计划 Plan C 删 yaml" | `tools/registry.py:99` **只 register `clear_short_term`**，switch_character 函数体在 `builtin.py:16-25` 但 schema 不暴露给 LLM；前端 WS frame `character_switch` 走 connection_manager 路径 | 一致；但 docstring（registry.py:14）和 builtin.py 注释仍举 switch_character 例子，易误导 | A | builtin.py 留 `switch_character` 是无效死代码：要么删，要么明示 `@deprecated`；registry.py:14 docstring 改用 clear_short_term 举例 |
| Plan C（删 yaml） | ROADMAP.md:204-205：deferred | 当前仍 Plan B（yaml + DB），尚未推进 | 一致 | 一致 | — |

---

## 4. 角色数据源（characters.yaml vs DB）

| 条目 | 文档怎么说（出处） | 代码实际（文件:行） | 差异 | 判定 | 建议动作 |
|---|---|---|---|---|---|
| 双源关系 | README.md:479-483、ROADMAP.md:204-205：Plan B | `backend/config/characters.yaml` 实存 44 行 **5 角色**（八重神子/默认/荧/凝光/神里绫华）；DB `characters` 表至少 ≥7 角色（含 cid=1/2/3/4/5/99/100/101） | 一致；但 yaml 角色集 ≠ DB 全集 | 一致 | 文档补一句"yaml 仅为 5 个内建角色，cid=99/100/101 不在 yaml" |
| characters.yaml 用途 | ROADMAP 未明确 | `prompt_manager.py:30-44` 进程内一次性加载，不再读盘；`v4_persona_thickening_segment1.py:55-73` 仅在 seed migration 抽 `default_emotion` | 一致 | 一致 | — |
| `characters.persona` 字段 | DESIGN_LITE.md:156-160：`@deprecated, fallback only` | `models.py:52`（`voice_model` 字段定义）确认 characters 表存在；persona 实质迁到 `character_personas` 表 | 一致 | 一致 | — |
| Mai = cid=1 / 樱岛麻衣 = cid=101 | DESIGN_LITE.md:571-589 | `v4_persona_segment2_mai_ja.py:34-43` 按 voice_id 匹配标 ja；`v4_0_0_mai_revert_zh.py` 仅 cid=1；DB 实测 cid=1 name=Momo(Mai)、cid=101 name=樱岛麻衣 | 一致 | 一致 | — |

---

## 5. Live2D

| 条目 | 文档怎么说（出处） | 代码实际（文件:行） | 差异 | 判定 | 建议动作 |
|---|---|---|---|---|---|
| 默认绑定 | README.md:141-166：Hiyori 默认；ROADMAP.md:5："1 Live2D model (Hiyori on cid=1 Mai)" | `frontend/src/config/live2d.ts:18-20` hardcode `hiyori: 'hiyori_pro_t11.model3.json'`；DESIGN_LITE.md:161：cid=1 绑 hiyori | 一致 | 一致 | — |
| 公开模型集 | README："ships with Hiyori" | `frontend/public/live2d/` 实存：`core/`、`hiyori/`、`yae/`（八重神子皮肤） | 文档未提 yae 也已上架 | A | README 补充 "ships with Hiyori + Yae demo skin" |
| Cubism 3 支持 | README.md:141-166："supports Cubism 3 and 4" | `frontend/src/lib/live2d/runtimes/` 仅 `pixiCubism4.ts` 一个 runtime；`registry.ts:22-36` 单实现且对 moc3 ver≥5 console.warn | drift：Cubism 3 未实装 | A | 文档改 "Cubism 4 only"，moc3 ver≥5 走 warn |
| motionMap per-character | ROADMAP/DESIGN_LITE | `frontend/src/lib/live2d/maps.ts:79-98` `resolveCharacterMaps()` 优先 character.motion_map_json，fallback 全局；`Live2DCanvas.tsx:112-128` 依赖 maps useEffect | 一致 | 一致 | — |
| 模型上传 dropzone | ROADMAP / DESIGN_LITE | `routes/live2d_api.py:126-172` POST /api/live2d/upload；`services/live2d_scanner.py:1-45` GET /api/live2d/models；前端 `lib/live2d.ts:54-86` | 一致 | 一致 | — |
| emotion → motion 绑定 | ROADMAP.md:214-215：阻塞于 `.exp3.json` 资产 | `frontend/src/config/live2d.ts:92-104` emotionMap=`{}` 默认空；`Live2DCanvas.tsx:92-109` miss 时 console.log 占位；`lib/live2d/runtime.ts:59` setExpression 接口存在但 pixi 实现待补 | 一致：阻塞 | B（也算 A 项目已知） | — |

---

## 6. 前端 UI

| 条目 | 文档怎么说（出处） | 代码实际（文件:行） | 差异 | 判定 | 建议动作 |
|---|---|---|---|---|---|
| Settings V2 | README.md:216-231：8-theme System | `frontend/src/modes/Panel.tsx:19` import SettingsPanelV2；`SettingsPanelLegacy.tsx` 标 `@deprecated`，仅复用 section | 一致 | 一致 | — |
| ChatHistoryPanel 替代 Drawer | README.md:207-213 | `Panel.tsx:16,281` import + 渲染 `<ChatHistoryPanel />`；ChatHistoryDrawer 已删 | 一致 | 一致 | — |
| 双推拉布局 | README.md:207-213 | `store/index.ts:270-286` 状态；`Panel.tsx:45-99,137-282` 两侧 resize handle + ResizeObserver 推动 Live2D | 一致 | 一致 | — |
| 8 主题 | README.md:216-231：8 套 | `styles/themes.css:8-126` 实声 8 套（morandi/dusk/glass/watercolor/aurora/sakura/cyber/lavender）；`store/index.ts:177-182` VALID_THEMES 默认 dusk | 一致 | 一致 | — |
| 切角色自动加载最新对话 | README.md:200-205 | `components/CharacterSwitcher.tsx:116-175` `setCurrentCharacterId → fetchConversations → 取第一条/新建 → setCurrentConversationId → fetchMessages → sendCharacterSwitch` | 一致 | 一致 | — |
| 窗口 <1280px 降级 | README.md:207-213 | `store/index.ts:59,80-84` `SMALL_VIEWPORT_PX=1280`，首启 < 1280 默认两侧收起 | 一致 | 一致 | — |
| MemoryManagerDrawer | DESIGN_LITE | `MemoryManagerDrawer.tsx:123-150` 列表展示 + type filter + delete + clearAll；create / edit 未在此段确认 | 一致 | 一致 | — |
| VAD/ASR UI | INV-14 Lesson #19：VAD 一直在 Capabilities ASR tab | 与 `CapabilitiesPanel.tsx` 体系一致，主设置 re-expose 已 revert（与 SESSIONS 对齐） | 一致 | 一致 | — |

---

## 7. ASR / Whisper

| 条目 | 文档怎么说（出处） | 代码实际（文件:行） | 差异 | 判定 | 建议动作 |
|---|---|---|---|---|---|
| HF_HUB_OFFLINE | ROADMAP.md:50：INV-14 已 ship | `main.py:19-34` 注释明示删除硬编码；`os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")`；lifespan 内做 HEAD 探测；fallback OFFLINE=1 三层安全网 | 一致 | 一致 | — |
| Preload 流程 | README | `main.py:580-595` lifespan 并发 create_task 预加载 embedding + whisper；/api/health warming-up 状态 | 一致 | 一致 | — |
| 模型 size | INV-14 文档 | `asr/whisper.py:65,84` `get_whisper_model_size()` 读 yaml override，默认 `small`；支持 hot reload | 一致 | 一致 | — |

---

## 8. Proactive Engine

| 条目 | 文档怎么说（出处） | 代码实际（文件:行） | 差异 | 判定 | 建议动作 |
|---|---|---|---|---|---|
| Trigger 集 | README.md:234-237：5 trigger + 4 activity trigger | `backend/proactive/triggers/` 文件清单：`bedtime_chat.py` / `dinner_call.py` / `lunch_call.py` / `long_idle.py` / `morning_briefing.py` / `wake_call_briefing.py` / `activity.py` = 7 个；外加 `_invite_base.py` / `_stage2_registry.py` 基础设施 | 文档"5 trigger"为收窄计数（wake_call/morning_briefing 互斥；activity 单独） | A | 文档列清单：wake_call vs morning_briefing 互斥（config.proactive.mode），dinner/lunch/bedtime/long_idle 常驻 |
| cron 实际是否触发 | ROADMAP.md:144：v4.1+ "proactive_actions 表 3 天 10 行 · 几乎全 dead" | `main.py:757-855` cron 注册；`scheduler/cron.py:19-34` APScheduler AsyncIOScheduler；具体 throttle 闸代码完整 | 实际"全 dead"是 PM 实测，与代码层不矛盾——调度路径存在，但配置 / proactive.mode 可能未开 | B（可能配置导致） | v4.1+ 需重新核 config + log，不一定是代码 bug |
| Rule A/B 绑定 | DESIGN_LITE.md:267-272 / 499-509 | proactive validate 路径在 `engine.py` 等，符合 stale 静默丢弃描述 | 一致 | 一致 | — |

---

## 9. Activity Timeline

| 条目 | 文档怎么说（出处） | 代码实际（文件:行） | 差异 | 判定 | 建议动作 |
|---|---|---|---|---|---|
| 5 道隐私闸 | README.md:190 / DESIGN_LITE.md:274-279 | `integrations/activity_watcher.py:81-88` blocklist；`services/activity_timeline.py:179-196` `_is_user_idle()`（macOS ioreg）；dedup 用 `_prev_app/_prev_url`；session < `min_session_seconds`（默 30s）过滤；显式删除 + 全本地落盘 | 一致 | 一致 | — |
| 30 天保留 | README.md:190 | `services/activity_timeline.py` cleanup job（`main.py` lifespan 注册 `activity_timeline_cleanup`） | 一致 | 一致 | — |

---

## 10. MCP 双向

| 条目 | 文档怎么说（出处） | 代码实际（文件:行） | 差异 | 判定 | 建议动作 |
|---|---|---|---|---|---|
| Client | README.md:73-76 | `backend/mcp/client.py:125-150` 支持 stdio + streamable HTTP；config.yaml mcp_clients 字典 | 一致 | 一致 | — |
| Server | README.md:73-76 | `backend/mcp/server.py:76-114,145` 动态从 CapabilityRegistry 派生（Consumer.CHAT_AGENT + expose_via_server=True） | 一致 | 一致 | — |

---

## 11. Calendar

| 条目 | 文档怎么说（出处） | 代码实际（文件:行） | 差异 | 判定 | 建议动作 |
|---|---|---|---|---|---|
| Apple EventKit | README.md:240-243 | `integrations/apple_calendar.py:112-120` pyobjc + macOS 14+ `requestFullAccessToEventsWithCompletion_`，旧版回退 | 一致 | 一致 | — |
| Google OAuth | README.md:240-243 | `~/.skyler/` 凭证，config.yaml 无密钥 | 一致 | 一致 | — |
| 默认 source | README | `config.yaml:87` `default_source="apple"` | 一致 | 一致 | — |

---

## 12. 网易云 + mpv + 媒体控制

| 条目 | 文档怎么说（出处） | 代码实际（文件:行） | 差异 | 判定 | 建议动作 |
|---|---|---|---|---|---|
| dispatcher × actions | README.md:240-243："2 dispatcher × 14 actions + macOS media 5 actions"；ROADMAP.md:231-233：19 actions 测试矩阵 | `capabilities/netease_music.py` 统一 dispatcher，路由 7+ 子操作（daily_recommend / personal_fm / play_song / play_playlist_by_id / like_current / search 等）；media_control.py 5 actions | 14 / 19 总数与"7+"模糊；需具体 PM 复核 | A or 一致 | 实际数字需详尽 grep 子 action；推荐用 INV-18 SESSIONS 列出的清单更新文档 |
| mpv player | INV-18 SESSIONS | `integrations/mpv_player.py:28-34,70-83` subprocess + Unix socket IPC + lazy spawn | 一致 | 一致 | — |
| audio source priority | README.md:240-243：mpv-first → media.* fallback | 实际 `agents/prompt/tool_addendum.py`（最新 commit `d712768`）已落地路径一致路由 | 一致 | 一致 | — |
| 网易云 weapi appver 升级 | ROADMAP.md:231-233：2.9.7 → 3.0.x | 最近 commit `06436d8` feat(netease) 4-patch suite weapi rotation；`0a23866` fix(mpv) arg compat | 一致 | 一致 | — |

---

## 13. LLM Client / Prompt Caching

| 条目 | 文档怎么说（出处） | 代码实际（文件:行） | 差异 | 判定 | 建议动作 |
|---|---|---|---|---|---|
| 白名单 + cache marker | ROADMAP.md:133-134："EXPLICIT_CACHE_PROVIDERS + `_inject_cache_marker` + `config.yaml prompt_caching.enabled`" | `backend/llm/client.py:36` `EXPLICIT_CACHE_PROVIDERS={"dashscope/","anthropic/","bedrock/"}`；`client.py:46-71` `_inject_cache_marker` 在 system 第一个 text block 标 `cache_control ephemeral` | 一致 | 一致 | — |
| Default provider | ROADMAP | `client.py:155-200` DB active provider 优先（bugfix-3.1），fallback yaml `default_model`（dashscope/qwen3.6-max-preview） | 一致 | 一致 | — |

---

## 14. Tool Registry / Capabilities

| 条目 | 文档怎么说（出处） | 代码实际（文件:行） | 差异 | 判定 | 建议动作 |
|---|---|---|---|---|---|
| Builtin LLM tools | ROADMAP / README："switch_character 已下线" | `tools/registry.py:99` 仅 `ToolRegistry.register("clear_short_term", ...)`；switch_character 函数体（`builtin.py:16-25`）+ schema（`:52`）保留但不暴露 | 一致；死代码风险 | A | 删 builtin.py 中 switch_character 函数 + schema；或顶 `@deprecated` |
| Capability 自动派生 | README.md:73-76 | `CapabilityRegistry`（Consumer.CHAT_AGENT）自动派生 OpenAI schema 并反注册 ToolRegistry；grep 全仓约 34 个 `@register_capability` 点 | 一致 | 一致 | — |

---

## 15. Observability

| 条目 | 文档怎么说（出处） | 代码实际（文件:行） | 差异 | 判定 | 建议动作 |
|---|---|---|---|---|---|
| tts_call_log | DESIGN_LITE.md:625-649 | `observability/tts_log.py:1-120` ContextVar 埋点；CosyVoiceTTS.synthesize 写表（source/character_id/voice/input_chars/cost_estimate/success） | 一致 | 一致 | — |
| REST API | DESIGN_LITE | `routes/observability_api.py:90-98` `/api/observability/tts/usage`、`/tts/recent_calls`、`/system/resources` | 一致 | 一致 | — |
| daily char cap / per-min throttle | ROADMAP.md:74-102 / DESIGN_LITE.md:625-649：v4.0.0 收口前要做 | 当前未找到 cap/throttle 实装 | B | — | 收口前补 |

---

## 16. Scheduler

| 条目 | 文档怎么说（出处） | 代码实际（文件:行） | 差异 | 判定 | 建议动作 |
|---|---|---|---|---|---|
| 库 | ROADMAP / DESIGN_LITE | `scheduler/cron.py:19` APScheduler AsyncIOScheduler，单例 `_scheduler` | 一致 | 一致 | — |
| 注册 jobs | DESIGN_LITE | `main.py:597-855` 注册 ≥8 个 job：intimacy_decay_daily / profile_daily_regenerate / activity_timeline_cleanup / lunch_call_weekday/weekend / dinner_call / bedtime_chat / long_idle_check + 可选 morning_briefing / wake_call_briefing | 一致 | 一致 | — |

---

## 17. Top Drift 清单（按"会误导后续开发的严重程度"排序）

按从最危险开始：

1. **【最严重】Mai (cid=1) 已 zh + cosyvoice/longyumi_v3，但 README/ROADMAP/DESIGN_LITE 多处仍说 GSV mai_v4 ja**。
   - 文档（如 ROADMAP.md:5、README.md:30/179-180、DESIGN_LITE.md:573-577）必须改成"cid=1 当前是 zh + cosyvoice/longyumi_v3（由 v4_0_0_mai_revert_zh 强制），cid=101 才保留 ja；运维如手动切到 gsv，hotfix scope 不会回滚"。否则 F1 "七套真 persona" 等后续工作会基于错误前提。
2. **【严重】ROADMAP.md:141-142 把 rolling summary 表名写成 `rolling_summary`，代码里真名 `conversation_summary`**。
   - PM"实测 89 行全空"的对象需重新对一遍 `conversation_summary` 表。若真空 → 滚动摘要 worker 实际未跑 / 触发阈值高于实测对话量；若不空 → 之前实测错表。
3. **【严重】switch_character LLM tool 实际下线但 builtin.py 函数 + schema + registry.py:14 docstring 仍存**。
   - 易让后续开发以为还能 LLM-call，造成"silent failure"复现。建议 builtin.py 函数体改 `raise NotImplementedError("downlined since 71b6e99")` 或直接删；docstring 改用 clear_short_term 举例。
4. **short-term 上限文档写 30 turn，代码硬编码 25 turn（=50 messages）**。需要文档同步。
5. **质量 filter 文档写 "10-stage"，代码实际 5 道**（length / SUSPICIOUS_TAG / confidence / tombstone / cosine dup）。
6. **README "Cubism 3 + 4 支持"实际只有 Cubism 4**；后续接入 .exp3.json 之前不要承诺 Cubism 3 模型。
7. **frontend/public/live2d/ 实存 hiyori + yae 两套模型，文档只点名 Hiyori**。README 应补一句"附带八重神子 demo 皮肤"。
8. **characters.yaml 实际只 5 角色，DB 至少 ≥7 角色（含 cid=99/100/101）**——文档说"yaml/DB 双源"但未澄清 yaml 不是全集。Plan C "删 yaml" 推进前需先把 cid=99/100/101 等的 default_emotion 从硬编码迁出。
9. **Proactive trigger 数：文档"5+4"与代码 7 个文件 + 1 个 activity 不完全对得上**。建议文档改用确切清单（lunch/dinner/bedtime/long_idle 常驻 + wake_call ⇄ morning_briefing 互斥 + activity）。
10. **TTS observability "daily char cap / per-minute throttle" 文档列为 4.0.0 收口前必做，代码未见实装**（B 类：代码欠实现）。

---

## 18. 我没能确认 / 需要 PM 复核的事项

- **"Mai persona 满字段 ~9018 chars" 出处**：实测 `character_personas` 行 ≈ 2471 bytes，差距大。可能口径包含 `characters.persona`（旧 deprecated 字段）/ `lore` / `voice_samples` 展开后的多语言版本等。文档需说明 9018 的统计口径。
- **网易云"14 actions" 数字**：dispatcher 内 if/elif 分支数需逐条 grep 才能给死数，本次没穷举。建议以 INV-18 SESSIONS 现场清单为准。
- **MemoryManagerDrawer 是否支持新增/编辑 memory entry**：本次只确认列表 + delete + clearAll，create/edit 路径未读到。
- **MCP server 实际暴露的 tool 名单**：动态派生（取决于 `expose_via_server=True` 的 capability），未做运行时枚举。
- **Proactive 实测"几乎全 dead"**：代码调度路径完整，是否 dead 取决于运行时 config 与触发条件——不是单纯代码问题。

---

> 报告生成完毕。本对账只摆事实，不改文档、不写需求。后续由 PM 据上面 Top Drift 清单决定：先修文档 vs 先补代码。
