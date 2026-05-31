# 🗺️ Skyler Roadmap

> Skyler 是一个**可塑型 AI 角色容器** —— 桌面端、角色驱动、能拆到 agent 内核、所有权归你。这条路线图按四条支柱组织,版本号 / chunk 罗列见末尾 [Implementation Log](#implementation-log-historical)。

> **状态(2026-05-26)**:v4-beta 收口阶段后期 + **INV-11 全段 ship**(GSV 真接入 + 全角色 provider × model × voice paradigm)。Persona Engineering 五层框架 + 记忆/对话三级隔离 + conversation 锚定绑定语义 + 对话 UI 统一 + Mai ja TTS via GSV mai_v4 emotion bank 全部 ship 并真机验证。9 character · 3 TTS provider(cosyvoice / fish / gsv)· 4 model · 1 Live2D model(Hiyori on cid=1 Mai)。下方 Now / P1 / P2 / P3 + 5070ti 触发清单见 INV-11 闭环段。

**Legend**: ✅ shipped · 🚧 in progress · 📋 planned · 🔬 research

---

## INV-16/17/18 全段闭环(2026-05-29~31 · 网易云 mpv-first + 系列 latent bug)

| INV | 主题 | 状态 | Notes |
|---|---|---|---|
| ✅ | **INV-16 · 网易云 weapi schema audit + 4-patch suite** | shipped + 真机 ✓(Mode A daily_recommend Reaching Light)| commit `06436d8` · Patch A weapi `br→level/encodeType`(NCM 2024 rotation 全 400 修通)+ Patch B client diagnostics + 5 端点 isinstance 防御(NCM 风控 frequent_visit type contract)+ Patch C error 归类 3 档 + Patch D netease_local self-state now_playing(MediaRemote 看不见 mpv fallback);**audit §3 #1 pyncm 切换 → 永久判死**(PyPI 下架 + GitHub repo 404);**audit §3 #2 weapi 全 400 → 闭环 Patch A ship 2026-05-31**;**Mode B URL Scheme autoplay → 退役 dead code**(mpv-first 后不再走);详 `docs/SESSIONS/2026-05-29.md` + `docs/netease-music-setup.md` |
| ✅ | **INV-17 · mpv subprocess latent bugs** | shipped + smoke ✓ | commit `0a23866` · `--media-keys=yes` mpv 0.41 rename `--input-media-keys` fatal · stderr DEVNULL → PIPE + `_read_stderr_tail` helper · loadfile 后 set pause False(sticky pause 跨 loadfile 防御);Lessons #35/#36/#37 沉淀;详 `docs/SESSIONS/2026-05-30-to-31.md` §2-§3 |
| ✅ | **INV-18 · tool 路径混乱 + audio source 优先级** | shipped(待 19 actions 真机回归)| commit `d712768` · tool_addendum 删旧 3 矛盾 section + 新建【音频源优先级】3 条规则 + 【网易云本地 mpv 自动播放】整合 + 【媒体控制】fallback 定位;`now_playing` 默认顺序反转(`netease_local` 首选 / `media` fallback);PM 醒后跑 19 actions P0-P2 矩阵收口;详 `docs/SESSIONS/2026-05-30-to-31.md` §4 |

> 详 `docs/LESSONS.md` (#24-#37 共 14 条新沉淀:audit 纪律 + patch stacking + 助手跳判断 + subprocess 启动)+ `docs/INVESTIGATION-INDEX.md` 主题聚类 §-4/-5/-6。

---

## INV-11 全段闭环(2026-05-25/26 · 主线 GSV + provider paradigm)

| Stage | 主题 | 状态 | Notes |
|---|---|---|---|
| ✅ | **Stage 0 · LLM output audit** | shipped | docs/INV-11-stage0-llm-output-audit.md · audit baseline · GSV 接入前 layer A 形态 |
| ✅ | **Stage -1 · prompt experiment** | shipped(V3 success)| docs/INV-11-stage-minus1-prompt-experiment.md · Layer A1 ja directive 配 GSV 16 emotion 输出格式实证 work |
| ✅ | **Stage 1 · GSV 真接入** | shipped + 真机 ✓ | `backend/tts/gsv.py` GSVTTS provider · mai_v4 emotion-aware ja TTS · `/set_gpt_weights` lazy-init + 16 emotion bank LLM 路由 · DB cid=1 voice_model 切到 gsv mai_v4 |
| ✅ | **Stage 1.5 · 全角色 provider × model × voice paradigm** | shipped + 真机 ✓ | `backend/tts/registry.py`(pydantic + json config + GSV 2 mode schema)· `backend/config/tts_models.json`(3 provider · 4 model)· `frontend/src/components/character/VoicePicker.tsx`(inline paradigm B · auto-save debounce 300ms)· `docs/adding-new-tts-model.md` playbook · Lesson INV-11 #11-#15 沉淀 |

> 详 docs/LESSONS.md(#11 fallback 阶段化 / #12 modal→inline / #13 label 真 / #14 hardcoded→json / #15 GSV 2 mode 前瞻)+ INVESTIGATION-INDEX 主题聚类 §0。

---

## P1 (本周候选)

| Status | Item | Goal | Notes |
|---|---|---|---|
| 📋 | **Conversation-vs-Character paradigm 决策** | 现状:conversation 1:1 绑 character(§5.9 锚定语义);PM 提出 "一 character 多 conversation" vs "一 character 一永久 stream + RAG 远期" 选型未定 · 影响记忆架构 v2 / F8 归属分级路径 | 待 PM 拍板 |
| 📋 | **Proactive 污染 short_term 长期 fix** | proactive 推送 turn 写入 short_term · 跟用户主动 turn 混 · 长期影响"对话连贯感";现状靠 proactive 文本压缩 mitigate · 长期解 = 分桶 + 注入分层 | 立项 |
| 📋 | **句子并发 TTS pipeline(chunk 15 复活)** | sentence-level 并发合成 + 顺序播放 · 改善 ja TTS 长句首字延迟(现 GSV ja 7-15s 单句串行)· chunk 15 实施过但未 ship 留 backlog。**2026-05-27 INV-15 P1 Option A 部分 mitigation**(commit 534a6ca · `merge_short_sentences` 扩 zh · HOL blocking 概率降)· 完整 out-of-order / 整 turn buffer **不推荐**(UX 破) · P3 candidate:TTS_CONCURRENCY 3→5 / push_latency observability(ROADMAP:206)/ threshold tune | INV-8 §1.1 Step 6 + INV-15 §6/§8 |
| 📋 | **Persona 蒸馏 Mai 三层** | 现 persona 把防御层(讥讽/调侃/话少)当人格本体写成常量 · 缺底色层与切换规则。重构方向:①补内核底色(被审视的孤独 + 对真实连接的隐秘渴望)②防御层标注为试探机制非本性 ③讥讽/话少由常量改为随对方真诚度变化的变量。蒸馏纪律:素材驱动、写约束非形容词、少而硬、给正反例 | 内容方向 · 立项 |

## P2 (~2 周)

| Status | Item | Goal | Notes |
|---|---|---|---|
| 📋 | **GSV server GPU 持久化** | reboot 后 tts_infer.yaml 回 cpu 已知 bug · 手动 SSH 改回 GPU + restart · 用 systemd unit + 配置 baseline 锁 | INV-11 Stage 1 衍生 |
| ✅ | **ASR whisper preload HF_HUB_OFFLINE** ship 2026-05-27(INV-14)| 真因 = `backend/main.py:21-22` 硬编码 `HF_HUB_OFFLINE=1` + `~/.cache/huggingface/hub/` 无 whisper-small snapshot → preload 29/29 失败 / asr_result 0 次。修法 = 删硬编码 + .env `HF_HUB_OFFLINE=0` + 首次启动 HF download · cached 后稳定。**P2 主设置 re-expose AsrVadSection 已 revert**(PM 真机 verify VAD UI 一直在 Capabilities → AI Providers → ASR tab · 单入口已可达 · 主设置加冗余了)· INV-14 audit 教训记 Lesson #19(修正:audit 前先 visibility verify)。详 docs/INV-14-vad-disappeared-audit.md §7.8 | commits c2d8924(P1)+ aed67cc(P2 revert) |
| 📋 | **加新角色 yae_v1**(走完整 json config trained mode flow)| `docs/adding-new-tts-model.md` Example 1 落地验证 · 8 步流程(server weights + emotion bank rsync + 本地 lab cache + 编辑 tts_models.json + backend restart)· dogfood paradigm 完整性 | INV-11 Stage 1.5 followup 衍生 |
| 📋 | **Migration v2 force upgrade** | phase out GSVTTS `_resolve_weights_field` `gpt_weights/gpt_path` 字段名 fallback(Lesson #11)· DB 批量 normalize voice_model JSON schema · 老字段名 drop | Lesson #11 立项 |
| 📋 | **UI polish**(当前 voice 高亮 / TTS 语言 dropdown 上移 / search box)| VoicePicker 增量 UX · 当前 voice radio 视觉强化 + TTS 语言挪到 model dropdown 上方(语义对齐)+ system voice 列表加 search box(7 voice 不算多 · 但 dogfood 增 system voice 后受益)| backlog |

## P3 (长线)

| Status | Item | Goal | Notes |
|---|---|---|---|
| 📋 | **INV-12 Stage 3 frontend universal TTS config** | Fish reference upload UI per-character + 通用 TTS config 编辑(覆盖 model default)· Stage 1.5 已 cover provider/model/voice 选择 · Stage 3 补 reference upload + custom 参数 | INV-12 Stage 2 backend 已 ship |
| 📋 | **Memory v4.1**(20k buffer / RAG fallback / character cognition)| short_term cap 30 → 20k token buffer(短期 token 治理)· RAG fallback(远期记忆)· character cognition(角色独立认知)· 友测后触发 | 友测反馈驱动 |
| 📋 | **Phase 3 streaming + H3 fix** | INV-8 §1 Step 6 instrumentation 11 log 点 + 前端 WebAudio API 序列拼接重构 + H3 +1000ms safety margin fix | 立项 backlog |

## 5070ti 触发(PM 已订 · 等到货)

| Status | Item | Goal | Notes |
|---|---|---|---|
| 🔬 | **zero-shot GSV mode 真实施** | 本地跑 GSV server · ref 本地完成 · 不需 server SFTP push · 配套 Stage 1.5 followup Part C tts_models.json `mode: "zeroshot"` schema 预留 + frontend ref upload UI(复用 Fish reference upload pattern)| GSV server 5070ti 本地化 |
| 🔬 | **多 character GSV trained model 本地 train** | yae_v1 / 凝光 / 其他角色 GPT + SoVITS weights 本地训 · 不依赖 GPU 远程 server · 配套 tts_models.json mode="trained" 加 entry | 5070ti GPU 算力 |
| 🔬 | **LLM 本地化**(qwen2.5-7b-instruct 4bit ~5GB) | 配 GSV ~4GB · 余 7GB buffer(假设 5070ti 16GB VRAM)· 本地推理 / Ollama / 自部署 | 性能与质量 trade-off 待评测 |
| 🔬 | **Skyler 全本地化** | 去云端依赖 · DashScope / Fish cloud / OpenAI 全切本地 · privacy / 离线场景就绪 | 长期 vision |

---

## Now — v4.0.0 收口

目标:把一个角色(Mai)做扎实再 ship,而不是铺开七个半成品。剩余 v4.0.0 项按序走完即 tag。

> v4-beta 收口批次(2026-05-16)的"本 session 已 ship 并真机验证"7 行成就清单已剥离归档至 [IMPLEMENTATION_LOG.md](IMPLEMENTATION_LOG.md)(2026-05-19 docs 第二刀)。

### 本 session 已 ship（2026-05-22）

| Status | Item | Notes |
|---|---|---|
| ✅ | **v4.0 立绘馆 voice greeting feature** ship(独立主线 · 不挡 Phase 3)| backend(`2b597bc`)· DB character_voice_lines + 4 endpoints + StaticFiles + 31/31 tests + cid=101 6 Mai seed(canon range markers);frontend(本 session)· lib/voice_lines.ts + CharacterDetailModal onMount fetch random + play + CharacterPanel "🎙 语音问候" section(list/upload/preview/delete);PM 提前上传音频系统纯 storage+serve · 不走 TTS 预渲染。详 INVESTIGATION-10.md |

### 本 session 已 ship（2026-05-19）

| Status | Item | Notes |
|---|---|---|
| ✅ | 左侧 ConversationList 右边缘可拖拽 resize handle | commit `60dea57` (2026-05-19);改 4 文件:store/index.ts / Panel.tsx / ConversationList.tsx / ChatHistoryPanel.tsx 中 2 个;新增 `momoos.convListWidth` localStorage,clamp [160,400] |
| ✅ | 右侧 ChatHistoryPanel 左边缘可拖拽 resize handle | commit `60dea57` (同上);新增 `momoos.chatHistoryWidth` localStorage,clamp [320,600];立绘区 flex-1 min-w-0 +Live2D ResizeObserver 自动响应 |
| ✅ | docs 整理轮(归档第一刀 + 真源对齐第二刀 + 索引登记) | commit `dcd3327` (2026-05-19);19 份归档至 docs/archive/(R100 零字节改动) + 5 真源对齐(死链/退役同步/HEAD 锚点 c1d65ff) + INVESTIGATION-2/INDEX 登记 |

### 剩余 v4.0.0 收口项(按序)

| Status | Item | Goal | ETA |
|---|---|---|---|
| ✅ | **文档纠真(v4.0.0 记忆线收口)** | DESIGN / DESIGN_LITE / ROADMAP / README / README_zh-CN 对齐 v4.0.0 现状 + §5.8 表层债入册;DESIGN.md 大整合(双层保留 / 旧"当前"标签 / chunk 章收并)立项留待表层重构 pass | ✅ 完成 |
| ✅ | **长期记忆链路 audit + 修复链** | audit 完结(根因=抽取 prompt 偏 fact-only + 闲聊→LLM 合法返回 [];子 bug=purge 不重置 extractor 指针)。修复链已 ship:滚动摘要层 b91505a + 902c2c2/f712625/42d1800/bfcd821/3f3be08。**代码对真 git diff 已核验;陪伴/功能质量待真机回归(验收门,CC 不自证)**。详 DESIGN §五·补 + §十五之 Z.5.1 | ✅ ship,待真机回归 |
| 📋 | TTS 每用户日字数 cap + 主对话节流 | 防 dogfood 期间烧 DashScope;per-user daily char cap + main chat throttle | ~0.5 day |
| 📋 | Stage3 — 打包发布 | Tauri build + .dmg + onboarding + dogfood + tag v4.0.0 | ~2-3 days |

> **chunk 15 / UX-006 关闭说明(保留历史结论)**:UX-004 v1 曾实测某些环境体感 23s 沉默。经 4 阶段 audit + 关 VPN 真机实测,backend producer/consumer + chunk 6b TTS pipeline 已实现 sentence-by-sentence streaming,过渡语 + 最终回复语音流畅。"23s 沉默"推测为 VPN + 第一次冷启 tool 叠加偶发,非架构问题。本 session 真机复测再次确认无感知沉默。详 `docs/archive/chunk-15-*`。

> **原 v4-alpha「可塑性易用」清单(Stage 2 纯前端管理资源 / chunk 13 test isolation / skill docs / Live2D swap guide / plugin registry seedling)整体下移 v4.1+**:v4-beta 收口聚焦"一个角色做扎实",可塑性打磨让位于陪伴质量。明细见 Tech Debt & Backlog。

---

## v4.1 — Mai 之外 + 语言/记忆根治

v4.0.0 tag 之后的主线。本 session 多个"治标 vs 治本"的决策都把治本压到了这里,集中一次做对。

| Status | Item | Goal | Notes |
|---|---|---|---|
| 📋 | **v4.1+ Mai emotion marker 实测精炼刀** | 现状:`layer_a.j2` fish 子分支 Mai marker 集(冷静/挖苦/温柔/罕见/Pause)基于 Mai canon range **推测**(per INV-9 §5 ship),未做大规模 A/B 实测验证。已知 work:`[composed]` / `[teasing]` / `[sarcastic]`(per PM 部分 sweep 听感反馈);已知不 work / 怀疑 markers 待 PM 进一步实测列出。**任务**:每 marker × 多 texts(Mai 风格典型句)A/B grid,统计 listen-grade work rate;按数据精炼 marker 集(剔除不 work 的、加新 work 的、调节优先级)→ 更新 `layer_a.j2` fish 子分支 directive;同步更新 INV-9 §5 marker 集 reference。**触发**:v4.1+ Mai 产品级体验启动时(用户长时间真实对话暴露 markers 表达问题);**联动**:跟 "多 provider 扩展刀" cross-dependency — Fish / GPU fine-tune / GSV 各自 emotion 通道形态可能不同,marker 精炼需 per-provider(per INV-9 §5+§6 Hard Req 双重隔离 + per-provider Layer A1 子分支扩展) | 立项 v4.1+,reference INV-9 §5(当前 marker 集)+ INV-9 §5+§6 Hard Req per-provider 双重隔离 + ROADMAP "多 provider 扩展刀" 联动 |
| 📋 | **v4.1+ 多 provider 扩展刀 · GPU 远程 Fish 微调 hybrid + GSV (GPT-SoVITS) provider** | INV-9 中插 sweep 实证 zero-shot from 7s reference 有硬天花板(per audit `b34ad70` Lesson INV-9 #8 stochastic 验证 + 43 WAV outputs 听感对比 Part 1/Part 2/repro);本轮 Phase 2 ship 接受 stochastic 作 Fish s2-pro 固有特性。**v4.1+ 多 provider 扩展路径**(2 sub-anchors):**(a) GPU 远程 inference** · FastAPI wrap `/tts` HTTP endpoint(任意 fine-tuned 模型 / Fish 自训 / 进阶 cosyvoice 复刻),backend 写 `RemoteFishTTS(TTSBase)` 类对接 — GPU always-on 配合 backend 直连**无冷启动延迟**;**(b) GSV (GPT-SoVITS)** · GPT-SoVITS 官方 `api.py` 直接用,backend 写 `GSVTTS(TTSBase)` provider 对接(per-provider sanitize Hard Req per INV-9 §5+§6:non-fish provider 默 strip `[bracket]` markers,GSV 沿用;若 GSV 未来加 emotion 通道,extend `_PreprocessingEngine` provider 分流加 GSV-specific 处理)。**触发**:PM GPU 资源就位 + API key 配齐。新 provider 接入沿用 INV-8 §1.2 抽象插点 A(provider factory)+ C(VoiceConfig 字段扩 per-provider);UI CharacterPanel 提供 voice_model JSON 编辑器切换 provider | 立项 v4.1+,reference `b34ad70` audit + Lesson INV-9 #8 + `tts/fish/参考音频/mai/` 完整 5min Mai 素材 |
| 🚧 | **TTS 模块化 + Fish s2-pro 集成主线**(2026-05-22 INV-8 §1 audit closed)| Phase 1 audit 闭环:5 决策最终三档 lock(1 沿 `<ja>` 隐式 display_zh / 2 ✅ Fish refs[] mode_A only / 3 `synthesize` + 新增 `synthesize_stream` / 4 β inline `[bracket]` 待 WAV final lock / 5 本地 cost + per-user cap)+ Option A1 lock(sanitize fix + 沿 `<ja>`)+ Hard Req per-provider 双重隔离。**Phase 2** ~3-5d / ~250-300 LoC + 1 新 `backend/tts/fish.py`(TTSProvider 抽象层 fish + sanitize A1 fix + voice_config 4 字段 + layer_a.j2 `{% if provider == 'fish' %}` 子分支教 markers + 6 case unit test);**Phase 3** 流式管线(Fish WebSocket `stream_websocket` + `latency=balanced` + Step 6 11 log 点 instrumentation 合刀 + H3 +1000ms safety margin fix + 前端 WebAudio API 序列拼接重构)。详 INV-8 §1 收口 + INVESTIGATION-INDEX | 取代原 F0 "ja 后处理翻译重做" — INV-8 §1.5 实测确认 LLM 实时双语 tag 行为问题不可纯翻译绕开;直接走 Fish s2-pro `[bracket]` 自然语言情感 + 顺序流式 `<ja>` schema 更优(详 §1.5.9 4 路 Option 对比 + CC leaning A1)|
| 📋 | **~~F0 — ja 后处理翻译重做~~**(2026-05-22 路线转向 → 上方 TTS 模块化 + Fish 集成主线)| ~~停掉 seg2-x 补丁路线,改架构:LLM 出纯中文 → TTS 前 qwen-turbo 翻日 → CosyVoice~~ | INV-8 §1.5.9 Option D 评估:翻译 layer 工程量 3-5d + Fish [marker] 集成路径需大改 + 翻译 LLM 不学 markers → 不推;路线转向 TTS 模块化 + Fish s2-pro 直出日语 |
| 📋 | INV-8 §1 Step 6 backlog · §1.1 stage 2 instrumentation 11 log 点 | 7 后端 + 4 前端(`# DEBUG-INV8` 标记)挪 Phase 3 H3 fix 时合刀,不算独立 audit overhead;Phase 3 ship 前跑真机 log 验证 H3 +1000ms safety margin 假设(per INV-8 §1.1.2)。审完拔光 `grep -rn "# DEBUG-INV8" backend/ frontend/` + `git restore -p` | 立项 backlog,Phase 3 起手前激活 |
| 📋 | INV-8 §1.4 Plan C 删 yaml + ssml_supported 死字段清理 | `backend/config/characters.yaml` 5 角色 ⊊ DB 9 角色,runtime 路径已不消费(仅 prompt_manager import time legacy);`ssml_supported` 字段 cid=2/3/5 voice_model JSON 有但 runtime 零消费者 — 顺手清。改 prompt_manager 改 DB lookup + 删 yaml + 清 ssml_supported 字段 ~1-2h | 立项 backlog,与 Phase 2 独立(per §1.4.9 / §1.收口.2 Q4)|
| 📋 | INV-8 §1.4 cid=1 vs cid=101 数据迁移方案 | CC leaning **方案 B**(数据迁移 cid=1 → cid=101,Phase 2 收尾刀;~30-50 行 migration);转移 chat_history + character_states + memory + conversations,用户感知 = "Mai 升级日语"而非"切到新角色"(cid=101 = 樱岛麻衣本体 + tts_language=ja + 复刻日语 voice 已就位)| 待 PM 拍板,Phase 2 收尾刀候选 |
| 📋 | **F1 — 七套角色真 persona** | `cid` 2/3/4/5/99/100 灌完整 persona(仿 `docs/mai_prompt.md` 的 Tier-1+2 规格)。当前除 Mai 全是空骨架 | persona-builder skill 已就绪 |
| 📋 | **F2 — 切角色对话联动收尾** | Bug Y 切角色→对话联动放大器残余(部分已随 UI 统一的 fetchMessages 补掉),收尾 | 部分已随 v4-beta UI 完成 |
| 📋 | **F8 — 长期记忆归属分级** | fact/profile → user_shared;event/关系型 → character_private(按 character_id);short_term 已 conv 隔离。**v4.0.0 audit 已完结、链路修复链已 ship(代码核验,功能待真机回归);"有没有"已解决,F8"分级"仍 v4.1** | v4.0.0 audit 已出结论,F8 解锁 |
| 🔬 | **记忆架构 v2(陪伴洞察)** | 一角色一永久对话流(非工具型多对话/新对话范式)+ 近期 short_term 原文 + 远期 RAG;"重来"靠显式清空非新对话。与 F8 统一设计 | 陪伴本质的架构终局,v4.0.0 不重构以免拖死 ship |
| 📋 | LLM 性能 | qwen3.6-plus 本身慢 + 网络;绑定锁死后"慢"与"串"已解耦,纯体验问题,独立优化(模型选型 / 流式 / 预热) | 不混进功能修复 |
| 📋 | CosyVoice WS 弱网超时 | 建链 5s 超时(SDK 写死)弱网失败;重试包装 / SDK 升级 / streaming_call | 生产复现触发 |
| 📋 | 测试债清理(原 chunk 13) | 遗留 7 个 **import-死符号断测**(test_chat_agent / test_database / test_llm_client / test_memory_agent / test_ws_helpers / test_memory / test_integration,v2.5-B/v3-C 时代 import 已删符号,**与功能无关**)+ fixture 隔离 + 全套 pytest 跑通。**注:`test_long_term` 不在这 7 个内,它是 Z.5(memory 0 行)的现成 repro,属 v4.0.0 critical,见下方收口批次** | 从 Now 下移 |
| 📋 | 可塑性易用清单(原 v4-alpha Now) | Stage 2 纯前端管理三类资源 / skill docs+examples / Live2D swap guide / plugin registry seedling | v4-beta 让位陪伴质量,v4.1+ 接回 |
| 📋 | **Persona 蒸馏重构（Mai 为先）** | 现 persona 把防御层（讥讽/调侃/话少）当人格本体写成常量，缺底色层与切换规则。重构方向：①补内核底色（被审视的孤独 + 对真实连接的隐秘渴望）②防御层标注为试探机制非本性 ③讥讽/话少由常量改为随对方真诚度变化的变量。蒸馏纪律：素材驱动、写约束非形容词、少而硬、给正反例 | 前端整理后启动 |
| 📋 | **八重 UI 线** | 八重神子(cid=2)的真 persona 灌入 + Live2D yae 模型已就位的前端联动 / 切换体验细化（属 v4.1 F1 七套角色真 persona 的优先一员）| 立项 |
| 📋 | **token 治理一轮** | INVESTIGATION-2 性能弹药已就绪:工具懒加载(被动池 + 主动细化,理论可省 9-10k tokens 但风险高,见 §5 懒加载地形)/ persona 字段裁剪(500-1500 tokens)/ history 窗口收缩(~600 tokens)/ ADDENDUM 压缩(74 tokens 收益微小)。优先级 / 取舍待人工拍板 | 立项 v4.1 |
| ✅ | **prompt caching 启用**（path F · Qwen system 段，已 ship 2026-05-20） | `EXPLICIT_CACHE_PROVIDERS` 白名单 + `_inject_cache_marker` + `config.yaml prompt_caching.enabled` flag；切 `dashscope/` prefix；main_chat 真机 cold/warm cache 命中实证（WARM 5,655 cached_tokens / 99.8% 覆盖率），生产 ~27% prompt 价省；T4 实证 Qwen tools= cache_control silently strip → ROI 缩水到 ~27%（vs brief 假设 67-83%）；T5 实证 DeepSeek 自动 caching 含 tools= 96.4%，路径 D（切 DeepSeek 全量 ~75% ROI）留 v4.1 A/B 评测候选。详 INV-5 §5 |
| 📋 | **path D · 切 DeepSeek 全量评测**（v4.1 候选，**优先级调低**） | T5 实证 DeepSeek 自动 caching 96.4% 覆盖率（含 tools=），理论 ROI ~75%。**但按 Qwen-Plus 真基线（非历史误算的 Qwen-Max 价位，详 INV-3 §10.9 archaeology 记录）重估，路径 D 切 DeepSeek 边际收益小于原估**：Qwen-Plus input 价 ~¥0.008/1k vs DeepSeek-V4-Pro ~$0.07/M token（~¥0.5/1k），DeepSeek cached ~$0.014/M（~¥0.1/1k）；按完整缓存命中算 DeepSeek 仍贵于 Qwen-Plus,且陪伴质量需 Mai 中文盲测确认。**A/B 评测仍可挂 backlog 但不在 v4.1 优先档**。详 INV-5 §4.5 + INV-3 §10.9 |
| 📋 | **token 治理子轨 B · 工具治理实施**（v4.1 候选） | INV-4 §3 v4.1 实施清单 6 动作（P2 desc 精简 / P3 character.set_activity 退役 / P1 入口折叠 media+apple_calendar+bilibili+netease）按风险×工程量×收益排序，总省 ~6.8k tokens 子轨 B 单独；与子轨 A 5.6k cache 叠加主路径 prompt 砍 ~55%（按 Qwen-Plus 真基线绝对成本节省 ~¥0.054/turn）。详 INV-4 §3.5 |
| 📋 | speculative cache warming | 前端 keystroke 触发预热 Qwen ephemeral cache(TTL 5min),应对用户停顿超 5min 后回到对话时的 cold start。需评估 keystroke event → 后端 warming endpoint → call_llm 空跑设计 + 预热成本 vs cold start 体验改善 | 立项 backlog |
| 📋 | layered cache markers | 子轨 A 当前只在 stable system block 标单个 cache_control marker。若 MCP toggle / 用户切角色 / persona 变化时只 invalidate 部分前缀（如分 tools/addendum/persona/Layer A-B 各自 marker）能减少 cache miss penalty。Anthropic 支持多 cache_control marker;Qwen `dashscope/` 路径未实测。详 INV-5 §5.4 衍生 | 立项 backlog |
| 📋 | cap naming convention 治理 | INV-4 §2.4.4 暴露 `proactive.snooze_wake_call` 是 misnomer(name 含 proactive 但行为 reactive,prefix 是 namespace 归属不是触发模式)。建议未来 cap naming 约定 namespace prefix 与 trigger 类对齐,避免 audit 误读 | 立项 backlog |
| 📋 | DESIGN_LITE §5.7 补 model 解析路径文档 | config.yaml fallback vs DB active 当前未文档化,导致历史 model 名错位 archaeology(INV-3 §10.9) | 文档增量,低优先级 |
| 📋 | **docs 第二刀(本刀真源对齐)** | 5 份真源 + 死链 + 退役同步 + HEAD 锚点 + 本会话新成果补录,2026-05-19 执行 | 进行中 |
| 📋 | **v4.1+ rolling summary 重设计** | 2026-05-29 PM 实测 `rolling_summary` 表 89 行**全空**(schema 在 / 没数据)· PM 拍 "设计没平衡好 · v4.1+ 重想" · 当前 ChatAgent 部分路径走不带 rolling summary 的模板 · 间接撞 ja TTS 静默根因(SESSIONS 2026-05-29 §2)。重设计方向待定 · 旧表 schema/数据保留不动 | v4.1+ 立项,详 SESSIONS 2026-05-29 §7 |
| 📋 | **v4.1+ 角色记忆 UI**(rolling summary 重设计后)| 角色级 long-term memory + 短期 rolling summary 视化 + 用户可编辑 / 删除 · 依赖 rolling summary 重设计完成后启动 | v4.1+ 立项 |
| 📋 | **v4.1+ Mai persona token 数失衡**(~2759 tokens · 持续调中)| 当前 Mai persona block ~2759 tokens 占整 prompt 显著比例 · PM 持续调蒸馏中 · 跟 P1 "Persona 蒸馏 Mai 三层" 相关但独立(蒸馏是内容方向 / 本项是 token 数控制)| 立项,持续 |
| 📋 | **v4.1+ proactive cron 重构**(DB 实证几乎全 dead)| 2026-05-28 audit 实证 `proactive_actions` 表 3 天 10 行 · 几乎全 dead · 现 cron 调度逻辑没真触发 · 需 audit cron job 调度路径 + trigger 路由 + 重构 | v4.1+ 立项,详 SESSIONS 2026-05-28 §2.5 |

---

## Next — 补诚实承认的缺口

[README §Comparison](README.md#comparison) 和 [§What Skyler is NOT](README.md#what-skyler-is-not) 列出来的缺口,逐条挪到 roadmap。Hermes 已经验证可行,Skyler 没做不是不该做,只是优先级。

| Status | Item | Goal | ETA |
|---|---|---|---|
| 📋 | Messaging gateway POC | Telegram bot 起步,跟桌面 Skyler 共享 character + memory | ~3-5 days |
| 📋 | Training data export | "用你跟 Momo 的对话训练你自己的小模型"—— SFT / DPO 格式 + PII sanitizer | ~2-3 days |
| 📋 | Capability marketplace | GitHub Pages 起步的社区 skill 索引,PR-based 提交 | ~1-2 weeks |

---

## Later — Persona-level learning

Hermes 的杀手锏是 self-improving skill loop(skill 越用越好)。Skyler 不直接 copy,而是把同样的"系统会变好"应用到**角色这一层**:

| Status | Item | Goal | ETA |
|---|---|---|---|
| 🔬 | character_states evolution | 让 mood / intimacy / activity 长期演化形成角色 pattern(不是 hardcode 规则,是 LLM 推断出的偏好)| research |

具体形式还在探索:可能加 derived field 记 pattern signal 做小步实验,再决定要不要 invest big。这是 Skyler 长期对 Hermes self-improving 的**差异化版本** —— Hermes 让 agent 更能干,Skyler 让 agent 更像一个具体的人。

---

## Long vision

桌面端建立一个**小而忠诚的可塑型 AI 角色容器爱好者生态**。

- 几百到几千的核心用户,每人都改 / 扩展 / 持有自己的版本
- 一个分散但活跃的 skill / character / Live2D 模型生态
- 不卖订阅、不卖模型、不收数据
- 衡量成功不是 GitHub star,是"有多少人真的把 Skyler 当成自己的角色用了一年以上"

不追求大众化。不参与 VTuber 直播 / Agent 框架 / 通用助手任何一个赛道的直接竞争。

### 长期技术能力扩展

支撑上面愿景的基础设施。这些是真长期项,不在 12 个月窗口内。

| Status | Item | Goal | Notes |
|---|---|---|---|
| 🔬 | autodl 部署 + sub-agent 隔离 | 长任务跑独立 context 不阻塞主对话;云端 GPU 跑 fine-tune | 借鉴 Hermes 多执行 backend |
| 🔬 | GPT-SoVITS 后端接通 | 替换 / 补充 CosyVoice,接通自训音色路径 | 依赖 autodl |
| 🔬 | 自定义 voice 训练 | CosyVoice fine-tune + GPT-SoVITS 角色专属模型 | 用户自训 + 接进 Skyler |
| 🔬 | 多设备 / 跨平台 | iPhone / iPad 同步;Windows 客户端 | v6+ |
| 🔬 | 工作模式 + Toolset by Mode | 引入 `Mode.WORK` 显式用户触发；按 Mode 切 toolset 子集（roleplay / proactive / work 各自只看到必要工具）；schema 经济上最低成本的运行态 | 远期立项，需先完成 v4.1 token 治理一轮后单独议 |

---

## Tech Debt & Backlog

按领域分类的活跃技术债。chunk 13 会一次性处理测试相关,其他逐条按优先级。

| Area | Item | Status |
|---|---|---|
| 性能 | `_build_messages` 退化(chunk 1.6 4ms → v3-H chunk 1 4487ms,1000x)—— 嫌疑某 capability 在 prompt 注入做昂贵 IO | audit 待 |
| 数据架构 | Characters 双源(`characters.yaml` + DB)—— 当前 Plan B(DB persona 为主源 + YAML fallback);Plan C(删 yaml、DB 单源、迁移导入、`switch_character`/`prompt_manager` 改 DB-backed)deferred | v4 后期 / v4.1 |
| 数据架构 | `config.yaml` 双写源 —— 静态 / 运行时拆,运行时进 DB 表 | v4 后期 |
| 配置 | git update-index --skip-worktree config.yaml 当前 workaround,升级方案 A `config.local.yaml` 覆盖 | backlog 30 min |
| 角色 | `cid=1`=Mai(借 Momo 壳 + Hiyori 模型,樱岛麻衣 persona,v4-beta 唯一真 persona);其余 `cid` 空骨架,v4.1 F1 逐个灌真 persona | F1(v4.1)|
| 记忆 | 长期记忆链路 audit 完 + 修复链已 ship(b91505a/902c2c2/f712625/42d1800/bfcd821/3f3be08;代码核验)—— 功能/陪伴质量待真机回归(验收门) | ✅ ship,待真机回归(详 DESIGN §十五之 Z.5.1)|
| 记忆·表层 | 异构表 facts+提醒未拆(`memory` 混存 `expires_at` NULL 持久事实 + 有值时效提醒) | 表层重构 pass(立项) |
| 记忆·表层 | 双 type 列 cruft(`type` 5 类 CHECK / `entry_type` 4 类并存,各有真消费者) | 表层重构 pass(立项) |
| 记忆·表层 | supersede 自身机制未实现(新旧事实共存,不替换) | 表层重构 pass(立项) |
| 记忆·表层 | `expires_at` 未正经接线(signature 接受但 caller 全传 None) | 表层重构 pass(立项) |
| 记忆·表层 | 墓碑 check 无类型感知(可能误压合法重建的新提醒) | 表层重构 pass(立项) |
| Live2D | Hiyori 缺挥手/点头/鞠躬;motion3.json 自带 wav 默认禁用,未来 per-character 开关 | 切模型时重写 |
| Live2D | emotion 视觉绑定阻塞于 `.exp3.json` 模型资产(外部依赖) | 外部 |
| 音色 | cosyvoice WS 建链 5s 超时(SDK 写死)—— 弱网失败;修法重试包装 / SDK 升级 / streaming_call | 生产复现触发 |
| 音色 | Phase 2 自训音色(SoVITS / 微调 cosyvoice3) | 用户训练完成 |
| 凭证 | `mcp_credentials` 明文存 —— 升级 OS keyring / master password 派生 | backlog |
| 字幕 | 超长 B 站字幕分段总结(>30k 字符)—— map-reduce 风格 | 200k context 够时延后 |
| 工具链 | skyler CLI thin client(替代 MCP 对外接口的更轻方案) | chunk 13 后 |
| TTS 错误 | TTS timeout idx=1 偶发(chunk 14 chime in 文本到 widget 但语音没出) | 调 timeout / audit ws push 时机 |
| Observability | 推送延迟 metric:ws.py audio_consumer send_json 前后打 perf_counter,记录每段 audio push_latency_ms + size_kb 到 log,便于 dogfood 期间快速定位音频沉默根因(chunk 15 audit 副产物) | v4.1 nice-to-have 2-4h |
| Stage 2.2 Live2D e2e | 2.2.0 backend 29/29 + 2.2.1 frontend yarn build pass,但真机拖 .zip 完整 flow 未测(用户当时无合适 sample model)。补 5 scenario:拖 valid zip / 拒非 zip / slug 冲突重试 / 应用 / 跳过 motion_map / Live2DCanvas 渲染验证。**风险**:CC 没真机验证 Tauri WebView 上传链路,可能有 MIME / fetch 边角问题;dogfood 期间用户拖会自然暴露,补时机最佳 | v4.1 0.3-0.5d |
| Fan UI Vitest + 视觉回归 | Fan-1 backend 34/34 已覆盖,但 frontend 全跳过 Vitest(Fan-2~5 走真机走查通过)。补:CharacterCard / FanLayout(geometry math + windowed mode + click shortest path)/ CharacterGallery(state machine browse↔detail / Esc / CTA → close)/ SplashArtDropzone(MIME/ext fallback / size limit / replace flow)。视觉回归用 Playwright snapshot 抓 fan @ N=4/5/7/10、detail open、bg cross-fade 中段。**理由**:6 个 sub-stage 每次都靠用户真机走查,迭代成本高;Vitest 套件让 layout 数学回归(stepDeg / shortestDelta / fade)瞬间发现 | v4.1 0.5-1d |
| Fan UI tagline / interests | Fan-4 detail modal 的字段缺位决策 backlog:DB schema 加 ``tagline`` / ``interests``(JSON tags) → CharacterPanel 加编辑表单 → DetailModal 渲染。当前 detail 只显示 name / persona / character_state, 用户实测后若觉得"信息少"再补 | v4.1+ backlog 0.5-1d |
| Skill UI | Skill .py 拖入 + 一键重启(Stage 2 原 2.3,推 v4.1+):跨 framework skill 不兼容(详 [stage-2-starting-context.md §5.1](docs/archive/stage-2-starting-context.md)),90% "装别家 skill" 场景由 MCP(Stage 2.1)覆盖;.py 拖入主要价值在 Skyler 社区共享 capability,需早期用户 base 形成后再做 | v4.1+ backlog ~5-7d |
| Skyler-as-MCP-server | 让 Skyler 自身暴露成 MCP server,把 character_state / activity timeline / Live2D control / memory 等 capability 暴露给其他 MCP-compatible 工具(Claude Desktop / Cursor / Cline 等),让 Skyler character 跨工具可见可引用。**理由**:跨 framework skill 市场调研后,MCP 已是事实标准——各 framework 都出 MCP adapter,Skyler 从 MCP client 升级为 MCP server 是差异化方向 | v4.1+ backlog 待估(可能 1-2w)|
| Frontend | UX-003 情绪 UI absolute viewport 锚定 bug(left: 16px 可能被父容器影响) | backlog 15 min |
| Display name | wpsoffice 缺中文 display name(`_APP_DISPLAY_NAMES`)| backlog 5 min |
| URL fetch | bilibili url_fetcher 5s 超时(反爬虫/UA/timeout 调整)| backlog 30 min |
| 网易云 | **appver 2.9.7 → 3.0.x 升级**(weapi User-Agent 内嵌版本号 · 防 NCM 风控对老 appver 收紧)| 2 min · INV-16 audit 顺手项 |
| 网易云 | **`add_to_playlist` action 暴露**(`NeteaseClient.add_to_playlist` 已实现 · 未注册成 `netease_web` action)| 5 min · INV-16 audit 顺手项 |
| 网易云 | **19 actions 测试矩阵 P0-P2**(PM 醒后跑) | INV-18 ship 后真机回归 · P0(mpv 闭环 8 action · 含 Pit 1 验证)/ P1(Patch D + Patch B 验 6 action)/ P2(媒体控制 fallback 5 action)· 详 `docs/SESSIONS/2026-05-30-to-31.md` §5 | 立项 · PM 真机驱动 |

### 遗留测试债

下列测试文件在 v3-F 接手前已经断开,import 早已删除 / 改名的符号。chunk 13 测试 pollution 修复时一并处理。

| 文件 | 失败原因 | 引入版本 |
|---|---|---|
| `tests/test_chat_agent.py` | `upsert_personality` 函数已删 | v2.5-B |
| `tests/test_database.py` | 同上 | v2.5-B |
| `tests/test_llm_client.py` | `DEFAULT_MODEL` 常量改名 | v2.5-B |
| `tests/test_memory_agent.py` | `_personality_to_dict` 已删 | v2.5-B |
| `tests/test_ws_helpers.py` | `_run_plan` PlannerAgent 简化时移除 | v3-C |
| `tests/test_memory.py` | `SHORT_TERM_MAX is 20` 断言过期 | v2.5-B |
| `tests/test_integration.py` | 集成 fixture schema 已变 | v2.5-B |

---

## Not on the roadmap(明确不做)

避免后续想法漂移。

- ❌ **群聊(多角色同时对话)** —— 跟单角色驱动定位冲突
- ❌ **Bilibili 弹幕直播客户端** —— 直播场景,跟桌面角色 agent 定位无关
- ❌ **Letta / MemGPT 等独立 memory 系统** —— 现有 SQLite + sentence-transformers 已够用
- ❌ **WhatsApp / WeChat gateway** —— API 限制 + 商业风险(注:Telegram / Discord 在中期 roadmap,不在禁做列表)
- ❌ **Linux Wayland 完整支持** —— 技术上几乎做不了
- ❌ **系统操作 agent(鼠标键盘控制)** —— 跨平台 + 安全代价太高
- ❌ **跟 LangChain / AutoGen 比拼通用 agent 框架** —— Skyler 是角色驱动的桌面 agent
- ❌ **Settings 全局 TTS 开关** —— 只在 CharacterPanel 上 per-character 提供
- ❌ **TTS UI 提前堆假选项** —— 下拉只显示真实可用的 voices

---

> 历史实现日志已外迁至 IMPLEMENTATION_LOG.md
