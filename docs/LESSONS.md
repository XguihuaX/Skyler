# Lessons (Quick Reference)

> 跨 INV 系列沉淀的工程教训速查表 · 单行索引 + 一句话总结 + 跳转到详细 memory entry。
> 完整正文见 `~/.claude/projects/.../memory/inv11_lesson_N_*.md`(或对应 INV doc 沉淀段)。
>
> 更新时机:新 lesson 沉淀 → 同步加一行;不删旧 lesson。
> 当前覆盖:INV-7/8/9/10/11/13/14/15 + INV-16/17/18(网易云 weapi / mpv subprocess / tool 路径混乱) 阶段 lessons(37 条)。

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
| 19 | "用户找不到旧入口" ≠ "入口缺失" · audit 前先 visibility verify | INV-14 误判:VAD UI 一直在 Capabilities → AI Providers → ASR tab(深 3 层路径)· audit 只 grep `import.*Section` 没看到 SettingsPanelV2 import AsrVadSection 就推"入口失踪"。P2 commit `3f24d6c` 加冗余 section 后 PM verify 实际 path 在 · 即 revert(`aed67cc`)。真教训:visibility 差(深 tab) vs 入口失踪 是不同问题 · 修法也不同(文档化 / quick-access vs 加回入口)· **audit "UI 失踪" 类问题前必须 mental walkthrough 实际 path** · 不仅 grep | INV-14 §7.8 + P2 revert |
| 20 | chunk closed 时假设的稳定性必须 long-running verify | chunk 15(2026-05-16)closed 时假设 "TTS 单句合成时间稳定 · FIFO 顺序不影响体感" · 实测当时 short session 验收通过。INV-15 实测发现 cosyvoice cloud 偶发 9s outlier(vs avg 4s · 2x 慢)→ consumer FIFO HOL blocking 5s 沉默。close 时只跑短 session 没 sample outlier 分布。**audit closure 应带"假设破坏阈值"** + 定期 sample DB / log 验证 stability 假设 · 否则 close 后用户体感问题难溯回 closed 假设 | INV-15 §1.3 chunk 15 vs 现况 |
| 21 | 新功能 enable gate 用语义需求 · 不用"那时唯一支持的语种" 绑死 | `merge_short_sentences` 设计为防 "短 audio TTS 合成质量崩"(Bugfix-segment2-3)· 当时 ja/en 是唯一支持的 ja TTS 路径 · gate 写 `if tts_language in ("ja","en")`。INV-11 切 ja 后此约束语义仍成立 · 但 INV-15 PM 切 cosyvoice zh 后 zh 短句同样 benefit。原 gate 凭"那时支持的语种白名单"绑死 · 长期 brittle。修法 INV-15 P1 直接删 gate · merge 对所有 tts_language 启用 · 内部已有 short_threshold / flush_threshold 自己控制(语义需求 gate 在 module 内部不在外层)。**功能 enable gate 用功能需求语义**(eg "short audio quality")· **不用"那时支持的语种白名单"** · 切换 / 扩支持时不会忘 review | INV-15 P1 ship |
| 22 | 实时 input(VAD/mic/keyboard hook 等)必须有 3 件套:(a) 健康检查 (b) onended recovery (c) diagnostic UI | INV-15 PM 反馈 "VAD 时好时不好 · 后续才不好" · audit verify 真因 = `MediaStream` track 在系统切 mic / Tauri webview suspend / 权限 revoke 后变 stale · `useAudio.initStream` 原 `if (streamRef.current) return` stale-blind 复用 · 老的 stale stream 持续被用。修法三件套:(a) `isAudioGraphHealthy()` 验 `track.readyState === 'live'` + `AudioContext.state !== 'closed'` · 不健康 teardown 重建;(b) `MediaStreamTrack.onended` listener + 周期 frame check 兜底(onended 漏 fire) · 触发 `recoverStream()` 单飞行锁防 race · sleep 时不偷偷重申 mic;(c) `vadCurrentMax` 写 store · `VadBar` 实时显示 "now: X / threshold: Y" + threshold marker · PM 一眼诊断:数字不动 = stream stale · 数字动但 < threshold = 阈值问题。**三件套缺一不可**:只 (a) 没 onended 漏自动恢复;只 (b) 偶尔 onended 漏 fire 仍卡;只 (c) 用户看到数字不动但还得 reload。**触发条件**:任何实时浏览器 device API(getUserMedia / Bluetooth / Serial / WebHID)长期 hold reference · 必三件套 | INV-15 P2 ship |
| 23 | 国内部署 transformers/sentence-transformers 应用必须 mirror + offline fallback 双保险 | PM 实测 `_build_messages` 49952ms · sentence-transformers runtime HEAD check `huggingface.co` 5 retry × ~10s 累积 50s 阻塞。单 mirror(eg `HF_ENDPOINT=hf-mirror.com`)能解 99% 场景 · 但 mirror 自己挂时(维护 / 网络抽风)仍卡。单 `HF_HUB_OFFLINE=1` 首次启动模型 cache 缺失会直接报错。**正解三层安全网**:(L1) `.env HF_ENDPOINT=hf-mirror.com` + module setdefault 兜底;(L2) lifespan startup HEAD probe(3s timeout)· 不通自动 `HF_HUB_OFFLINE=1` + `TRANSFORMERS_OFFLINE=1`;(L3) cached snapshot 持续 load · 即便 L1+L2 都挂也能跑。**单层任意 fail 不让用户感知 50s 阻塞** · 这是国内部署 transformers 应用的标准 pattern。**触发条件**:任何 `transformers` / `sentence-transformers` / `huggingface_hub` / `diffusers` / `datasets` 应用 ship 给国内用户前 · 必三层 review · 缺一就标 backlog | INV-14 §8 ship + commit 2680921 |
| 24 | audit 别跟用户 narrative 单点 · enumerate 同型判定 | 用户报"X 不工作" → 助手常 anchor 在 X 单点深挖。但 X 经常只是同类问题里的一个 surfaced sample。**正解**:enumerate 同型(同 cap / 同 endpoint / 同 hook)所有 instance · DB count + log grep · 看 X 是孤例还是普遍问题。**孤例 → 单点 fix**;**普遍 → 抽 helper + 集中防御**。eg INV-13 §11 audit 单点 ja_persist · §12 enumerate 56 turn 后真因是 migration revert(普遍 · 不是单点)。**触发条件**:user-reported bug 落入 "X 不工作" 描述时 · 先 grep cap-name 看 instance count 再下假设 | INV-13 §12 method 反推 + 2026-05-28 网易云 audit |
| 25 | patch 间必须真机 baseline · 不能盲叠 | 4 patch ship 后 CC 跑 smoke 单元 PASS 就推 PM "可上" · 实际 patch A 修了的 latent bug 暴露了 patch C 没覆盖的下一层(eg 网易云 Patch A weapi level → 暴露 mpv_error)。**正解**:每 patch ship 后**必须** PM 真机过一遍 baseline 场景 · 才能 stack 下一个 patch。盲叠的代价 = incident 时不知道是哪个 patch 引入 · 也不知道前面的 patch 还能不能再 trust。**触发条件**:多 patch 同 PR / 同 commit / 同会话叠加 · 必每 patch 真机 checkpoint | 2026-05-29 Patch ABCD smoke OK 推 PM 后 2026-05-30 凌晨 mpv_error 暴露 |
| 26 | patch 前 verify 用户用对模式 + 代码真 ship 到运行环境 | PM 报"功能坏了" · 助手第一反应是去 audit 代码 · 但代码可能本来就 work · 真因是(a) PM 用错模式触发了别的路径 ·(b) 代码改了但 frontend `yarn build` 没跑 / backend reload 没生效 · 用户跑的是旧 binary。**正解**:audit 前先 verify (a) 用户截图 / log 显示走的哪条 path · (b) 用户的运行版本(commit hash / build timestamp)是不是真包含改动。**触发条件**:任何"PM 报功能坏了"前先 verify · 不直接 grep 代码 | 2026-05-28 网易云 audit · PM 不知道 18 actions 已实现 = 用户没用对入口 不是功能缺失 |
| 27 | surface symptom 超出方案物理上限 · challenge 方案本身 | PM 报现象超出方案物理上限时(eg "TTS 单句 9s" vs 方案理论 <2s · "VAD 5s 沉默" vs 方案 200ms 检测)· 助手别在方案内调参 · **方案本身可能错了**。eg INV-15 chunk 15 closed 时假设"TTS 稳定" · 现实 cosyvoice cloud stochastic 9s outlier 破假设 → consumer FIFO HOL blocking 5s。修法不是调 TTS 参数 · 是改 consumer 调度。**触发条件**:symptom 数字远超方案 SLA · 先 challenge 方案前提是否仍成立 · 再下调参 | INV-15 §1 + 2026-05-28 silero VAD 默认值 0.3 → 0.6(超 SLA 后 challenge 默认值) |
| 28 | 推 "对齐 maintainer baseline" 前必须 verify 在我们环境真跑得起 | upstream maintainer 推荐的 baseline(eg vad-web 默认 0.3 / mpv 0.41 推荐 args / litellm 1.86 vs 1.87-rc deepseek-v4-pro reasoning_content) 不一定能在我们环境复制 · upstream 测试环境 ≠ 我们用户环境(macOS Tauri / 中文用户 / 国内网络)。**正解**:推荐 baseline 前必须本地实测在我们 stack 跑通 · 不通就标 backlog 不盲推 PM 升级。**触发条件**:看到 "upstream 文档说 X" / "GitHub issue 推荐 Y" 时 · 先本地实测 + 报实证再推 | 2026-05-28 silero VAD 默认 0.3 实测误触发 → 升 0.6 + deepseek-v4-pro 1.86 reasoning_content 1.87-rc 才修(没升 · 留 backlog) |
| 29 | audit CC 实施时必查 实施≠调研推荐 · smoke ≠ 真测 | CC 调研推荐 Option A · 真实施时偶尔实际落地的代码偏离调研推荐(typo / 抽象层选错 / 多写一行)· 自己跑 smoke 单元说 PASS 但跟调研意图不一样。**正解**:audit CC 实施时不只看代码改了没 · 要 diff 检查改的内容是否跟调研推荐 1:1 对齐 · smoke OK 不等于真测 OK。**触发条件**:任何"调研 → 实施 → smoke OK"链 · audit 时必三件 diff 对齐 | 2026-05-28 4 件套 patch + 2026-05-29 Patch ABCD smoke OK · 真机回归 PM 真机才暴露 |
| 30 | 集成第三方库前必查 maintainer 集成 docs · 不靠通用框架知识猜 | 助手用通用 React/Python 知识猜 vad-web 或 mpv 或 pyncm 的集成 pattern · 常错。eg 助手以为 mpv `--media-keys=yes` 在 0.41 还有效(通用 mpv 知识 0.34+ 在 docstring 写了)· 实证 0.41 rename 为 `--input-media-keys`。**正解**:集成第三方库前**先**查 maintainer docs(GitHub README / changelog / option list)· 通用框架知识只用于决策维度选择 · 不用于具体 API 假设。**触发条件**:任何第三方库版本升级 / 新集成时 · 必先 visit maintainer 文档 source-of-truth | 2026-05-29 silero VAD docs / 2026-05-31 mpv 0.41 --list-options 实证 |
| 31 | 任何 "系统有 X 功能" 静态结论 · 涉及 runtime 必须查 DB/log 实证 | 助手看代码注册 7 cap 就推 "系统有 7 网易云 capability" · 实际 backend 重构后已 fold 成 2 dispatcher × 14 action + 5 media = 19 action · 但 PM 不知道。**正解**:任何"系统有 X 功能"声明涉及 runtime 时 · 必查 DB(capabilities 表)/ live log(tool_call 实证)· 不靠源码注释。**触发条件**:任何 capability / endpoint / feature flag 数量声明 · 必 DB/log 实证 | 2026-05-28 网易云能力 audit · 18 actions PM 不知道 |
| 32 | 跨 patch 同一 endpoint 改动 · 必给三条 path 走查表防回归 | Patch A 改 weapi get_song_url payload 后 · 同 endpoint 还有 4 个 callsite(daily_recommend / personal_fm / search / playlist_detail) · 每个走的是 weapi 不同字段。Patch A 单点改后 latent bug 可能藏在其它 callsite。**正解**:跨 patch 改 endpoint 前必先 grep callsite · 列三条 path(成功 / 风控 / 失败)走查表 · 每 callsite 都过 isinstance + None guard 三条 path · 不只测主路径。**触发条件**:任何 endpoint payload schema 改 / 返回值 schema 改 · 必列 callsite × path 矩阵 | 2026-05-29 NCM 风控 frequent_visit 5 端点 isinstance 防御 |
| 33 | PR 引用前必须 gh api 实证 merged_at + landed-in-release | 助手引 "litellm PR #XXXX 修了 reasoning_content bug" 时常假设 PR 已 merged + 已 release · 实际可能 (a) PR 还 open · (b) 已 merged 但还没 release · (c) 已 release 但不在我们安装的版本。**正解**:引 PR 前 `gh api repos/X/Y/pulls/N` 验 merged_at · 再 `gh release list` 验落在哪个 release · 我们 pip freeze 看的版本是否包含。**触发条件**:任何"X PR 已修"声明 · 必 gh api 三步验 | 2026-05-29 litellm 1.86 deepseek-v4-pro reasoning_content bug 调研 |
| 34 | 面对 PM 真机反证时 · 助手应停止推论而非换新假设 | 助手提假设 → PM 真机反证 → 助手立刻换新假设 → PM 再反证 → ...形成"跳判断"链。eg silero-VPN 现象 3 跳(proxy / 外网 / LLM API)CC 实证全推翻 · 助手未停手仍换新假设。**正解**:PM 真机反证后助手应**停推论 · 让 PM 拿更多 sample / 等可复现路径** · 不要在零 reproducible 路径上烧 token。**触发条件**:同一会话内同一现象 ≥2 次 PM 真机反证 · 强制停手 audit 自己的假设 generator | 2026-05-29 silero-VPN 3 跳 + 2026-05-30~31 9 次完整样本(SESSIONS 2026-05-30-to-31 §6) |
| 35 | subprocess 启动错 · 第一反应 "复现 spawn + 开 stderr" · 不是 "我猜" | 助手第一反应是猜 subprocess 启动错原因(PATH / 权限 / 找不到 binary)。但这些猜测都基于"binary 没启动"假设 · 实际 binary 可能启动了但秒退。**正解**:遇到"subprocess 启动失败"症状 · 第一反应是 manual repro spawn 同 args + 把 stderr 接出来看 · 不是先猜。stderr 一行真错误比 10 个假设管用。**触发条件**:任何 subprocess.Popen / asyncio.create_subprocess_exec 启动失败 · 第一刀 repro + stderr | 2026-05-31 mpv 0.41 `--media-keys=yes` fatal exit · 全靠 manual `--msg-level=all=debug` 才看到真错 |
| 36 | binary 升版本 arg 兼容性必查 · rename 通常非破坏性但老 arg 直接 fatal 不是 warning | brew 升 mpv 0.39 → 0.41 · `--media-keys=yes` 被 rename 为 `--input-media-keys` · 老 arg 不是 warning 而是 fatal exit。这类 rename 在 changelog 通常标"deprecated"但实际 binary 不接受老名字。**正解**:升 binary 版本时(brew upgrade / apt upgrade / docker base image 升)· 必跑一遍 `binary --list-options` 对比之前的 args · rename 的要同步代码改。**触发条件**:任何 subprocess 跑的 binary 升版本 · 必 args compat 走查表 | INV-16 mpv subprocess 2026-05-31 commit 0a23866 |
| 37 | stderr=DEVNULL 在 incident 是黑盒 · 启动失败那一窗口必 capture | `stderr=subprocess.DEVNULL` 在 happy path 干净 · incident 时全部信息被吞。这次 mpv incident 全靠 manual repro 才拿到 fatal 行 · 实际 backend 跑的 mpv 死了我们看不见任何 detail。**正解**:subprocess 启动一段(spawn ~ socket/health ready 这窗口)必 capture stderr · 即便后续切 DEVNULL · 启动这段先存 tail 200 char 防黑盒。配合 helper `_read_stderr_tail` 启动失败时塞 RuntimeError detail。**触发条件**:任何 subprocess 启动 + 后续不读 stderr 的场景 · 启动那段 PIPE + tail capture 必备 | INV-16 mpv subprocess 2026-05-31 commit 0a23866 |

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

### UI 重构 + 入口可达性 (INV-14)
#19 大重构后必须 verify 旧 section 入口仍可达

### TTS pipeline + chunk closed 假设(INV-15)
#20 chunk close 时稳定性假设要 long-running verify / #21 enable gate 用语义需求不用语种白名单

### 实时 input device API(INV-15 P2)
#22 VAD/mic 等实时 input 三件套:健康检查 + onended recovery + diagnostic UI · 缺一不可

### 国内部署 cloud-dep 安全网(INV-14 §8)
#23 transformers/sentence-transformers 三层安全网:mirror + offline probe + cache hit · 单层 fail 不让用户感知阻塞

### Audit 纪律 + patch stacking + maintainer 推荐(2026-05-28~29)
#24 audit 别跟用户 narrative 单点 / #25 patch 间真机 baseline / #26 patch 前 verify 用户模式 + 代码真 ship / #27 surface symptom 超 SLA challenge 方案 / #28 maintainer baseline 必 verify 本地 / #29 实施 ≠ 调研推荐 · smoke ≠ 真测 / #30 集成第三方库前必查 maintainer docs / #31 "系统有 X 功能" 静态结论必 DB/log 实证 / #32 跨 patch 同 endpoint 三 path 走查表 / #33 PR 引用前必 gh api 三步验

### 助手跳判断 + 推论停手(2026-05-29~31)
#34 PM 真机反证 ≥2 次必停推论 · 不换新假设(silero-VPN 3 跳 + mpv 9 次完整样本)

### subprocess 启动 + arg 兼容(INV-16 mpv subprocess 2026-05-31)
#35 subprocess 启动失败第一反应 repro + stderr / #36 binary 升版本 args compat 必查 · rename 老 arg 可能 fatal / #37 stderr=DEVNULL 启动那段必 capture 防黑盒

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
