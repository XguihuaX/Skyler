# INV-15 · 句间 audio gap + VAD 卡空闲 audit

> 2026-05-27 · 调研 only · 不动 code · ~40 min CC
>
> PM 真机反馈 2 issues(clarified):
> - (a) LLM 多句输出 + audio chunk 之间 gap(切到 cosyvoice longxing_v3 仍体感)
> - (b) VAD 有时一直听 · 有时开着但状态卡"空闲" · 声音再大也没用
>
> **TL;DR**:
> - (a) **真因 = TTS consumer FIFO head-of-line blocking on outlier 慢句子合成** ·
>   不是 LLM 拆得更碎(INV-13 Option F+G 不相关 · 它们只动 proactive trigger
>   prompts);PM 切到 cosyvoice zh 后 `merge_short_sentences` 失效(仅 ja/en 启
>   用)放大了 HOL 概率
> - (b) **VAD 卡空闲多种可能 · 最可能 threshold 太高**(PM 65 / 100 = raw 166 / 255
>   阈值)+ 缺 stream 健康检查(stale stream / suspended AudioContext 无 recovery)

---

## §1 (a) LLM 多句 + audio chunk gap

### §1.1 PM 实测 log 数据(2026-05-27 15:12 turn · cid=1 切到 cosyvoice 后第一 turn)

```
15:12:50,982  LLM raw first chunk: 5720ms (round=1)
15:12:51,476  sentence yield #1: 6214ms (len=91)   raw: '"...行吧。"<ja>「…わかった。」</ja>'
15:12:51,789  sentence yield #2: 6527ms (len=31)   raw: '"正好我也休息一会儿。"'
15:12:52,121  sentence yield #3: 6859ms (len=37)   raw: '"说吧，想聊什么？"'
15:12:52,455  sentence yield #4: 7193ms (len=25)   tail

15:12:55,958  TTS #1: 4475ms len=7
15:12:55,961  TTS #4: 3505ms len=1
15:12:56,145  TTS #2: 4356ms len=14
15:13:01,153  TTS #3: 9030ms len=12   ← outlier
```

**4 sentences** yielded ~300ms apart by LLM(秒级数字看着大是因为 LLM first
chunk 本身延迟 5.7s)· 4 TTS tasks 并发 fired ·**3 个 4-5s 完成 / 1 个 9s outlier**。

### §1.2 backend TTS pipeline 实施 verify(代码读)

`backend/routes/ws.py:188-265 + 1008-1019`:

```python
TTS_CONCURRENCY = 3
_tts_semaphore = asyncio.Semaphore(TTS_CONCURRENCY)

# producer (in stream loop):
task = asyncio.create_task(_tts_synth_with_timeout(...))  # 立即 spawn
audio_queue.put(task)                                       # 入 FIFO 队

# consumer (单独 task · 跟 producer 并行):
while True:
    item = await queue.get()      # 取出 task
    audio = await item            # ← **await 顺序 · 阻塞**
    await sender(audio)           # WS push audio_chunk
```

**架构特点**:
- ✓ TTS 合成 **真并发**(semaphore=3 · 3 句可同时 hit cosyvoice API)
- ✓ Producer / Consumer 异步 · LLM 出句快 · TTS 慢可在背后跑
- ⚠ **Consumer 严格 FIFO 顺序 await · 即 head-of-line blocking**:
  task_3 即便比 task_1 先完成 · consumer 仍要 wait task_1 → push 1 → wait task_2 →
  push 2 → wait task_3 → push 3

### §1.3 chunk 15 历史 closure(ROADMAP §40)与 PM 现状对比

ROADMAP "chunk 15 / UX-006 关闭说明":
> backend producer/consumer + chunk 6b TTS pipeline 已实现 sentence-by-sentence
> streaming · 过渡语 + 最终回复语音流畅。"23s 沉默"推测为 VPN + 第一次冷启
> tool 叠加偶发 · 非架构问题。

**当时 closed 假设**: TTS 单句合成时间稳定 · sentences 长度均匀 · FIFO 顺序
不影响体感(每个 audio 播完邻接下一个 audio 已 ready)。

**现在 PM 实况 verify**:
- 同一 turn 的 4 个 sentence TTS 时间 stochastic: 3505 / 4356 / 4475 / **9030** ms
- 9s 是 4s 的 2x · 是 HOL blocking 5s 沉默感的真因
- chunk 15 关闭假设的"单句合成时间稳定"**不成立** · cosyvoice cloud 偶发 9s 是
  cloud API jitter · 不是 VPN / 冷启 · PM 关 VPN 仍体感

### §1.4 mental model · 4 sentence + 9s outlier gap

```
T=0      LLM yields sentence_1 → TTS task_1 starts (~4.5s)
T+313    sentence_2 → task_2 starts (~4.4s)
T+645    sentence_3 → task_3 starts (~9.0s outlier!) · sem 满 → 排队
T+979    sentence_4 → task_4 排队 · 等 sem

T+4500   task_1 done · consumer push audio_1 → 用户开始听
T+4500   task_4 升 sem · 开始(~3.5s)
T+4863   task_2 done · 但 consumer 在 await task_1 完之后立即 push audio_2(无 gap)

         用户播 audio_1 (假设 ~2.5s 中文)
T+7000   audio_1 播完 · 立即播 audio_2 ✓

         用户播 audio_2 (~2s)
T+9000   audio_2 播完 · **audio_3 还没 ready**(task_3 还有 600ms 才完)· **没声音**

T+9645   task_3 done · push audio_3 · 用户听 audio_3
         → 用户体感 = "audio_2 播完后 ~600-1000ms 没声"

         实际可能更糟 — 若 sentence_2 / 3 间还有更长 task_3 延迟 / WS push
         延迟 / 前端解码延迟叠加 · 体感 gap 可达 1-2s

T+8000   task_4 done (排队完 4500 → +3500 = 8000) · 在 consumer 仍 await task_3 处等待
T+9645   task_3 push 后 · 立即 push audio_4 (already ready)
```

PM 描述 "chunk 1 → chunk 2 (间隔 0-5s) → chunk 3 (间隔大) → chunk 4" 完全 match。

### §1.5 LLM 输出 pattern verify · INV-13 是否相关

PM clarify:"LLM 现在倾向一句一句 4-5 个短句 · 之前可能 1-2 长句"。

`merge_short_sentences` 模块(`backend/agents/sentence_merge.py`)在 ja/en 模式下
合并 < 8 字短句到 buffer · ≥ 15 字 flush。**仅 ja/en 启用**(`ws.py:861`)。

PM 切到 **cosyvoice longxing_v3 zh** 后(renderer log 15:12:45 显示 tts_lang=zh) ·
`merge_short_sentences` **失效** · 每个 Chinese 句号 / 逗号 / 问号都触发独立
sentence yield → 4-5 个短句被独立 TTS·HOL blocking 概率放大。

**DB 实证**(cid=1 normal turn 平均 ja tag 数):
```
2026-05-25 (3 turns):  2.0 ja tags avg · 87 chars avg
2026-05-27 (4 turns):  2.0 ja tags avg · 68 chars avg
```

2 sentences avg 看着不算多 · 但 PM 15:12 turn 是 **4 sentences**(高于均值)·
属 outlier·撞上 cosyvoice 9s outlier = 双 outlier 叠加 = 用户体感糟糕。

**INV-13 Option F+G 相关性 verdict**:
- F(ja-aware 段)/ G(软化字数硬约束)**仅改 proactive trigger prompts**(invite/
  wake/activity)· **不改 ROLEPLAY mode 的 chat agent 主路径**
- PM 15:12 是 normal user turn(`mode_origin=user`)· 走 Layer B `roleplay` 分支 ·
  不受 F/G 影响
- ❌ **INV-13 改动与本 issue 无关**

### §1.6 推荐 fix 方向

| Option | 描述 | 工程量 | 风险 | 副作用 |
|---|---|---|---|---|
| **A** | `merge_short_sentences` **对 zh 也启用**(ws.py:861 删 `if tts_language in (...)` gate)| 5-10 min | 低 | zh 角色字幕推送会延 short_threshold(8 chars)· 但 flush 阈值 15 chars · 实测 latency 影响 < 200ms · 不阻塞首字 |
| **B** | 提高 `TTS_CONCURRENCY` 3 → 5/6(more parallel sem)| 5 min | 中 | cosyvoice rate limit 风险(需查 quota)· 但 HOL 仍存在(只缓解极端情况) |
| **C** | **out-of-order playback**(前端按 task 完成顺序播 · 不按 sentence 顺序)| 1-2 day | 高 | UX 破:句子乱序播 · 用户听感断裂 · **不推荐** |
| **D** | **整 turn 预 buffer**(全部 task 完成后再 push)| 2-4h | 中 | 首字延迟从 ~4.5s 升到 ~9s · 长 turn 用户等更久 · **不推荐** |
| **E** | LLM **prompt 鼓励长句**(Layer A "每句不超过 30 字"改"每句 15-30 字")| 30 min | 低 | LLM 不一定 strict follow · 长句对 TTS 是双刃(更长合成时间)· 效果不确定 |
| **F** | `_tts_synth_with_timeout` 在排队时长 > threshold 时 **fallback**(降级到无 audio · 纯字幕)| 1-2h | 低 | 用户偶发收不到 audio · 但不卡 · UX 半全 |

### §1.7 §1 推荐(强推)

**Option A · `merge_short_sentences` 扩到 zh** · 5-10 min · 低风险

理由:
- zh 是当前 PM 主用路径(切到 cosyvoice longxing_v3)
- merge_short_sentences 已在 ja/en 模式 ship 验证 work(防短音质量崩)
- zh 同样 benefit:更少 / 更长 sentence · 更少 TTS call · HOL 概率降低
- 字幕推送延 < 200ms · 用户感知 negligible
- 改动:`ws.py:861` 删 `if tts_language in ("ja", "en"):` 条件 · 改 always wrap

可选叠加 **Option B**:`TTS_CONCURRENCY 3 → 5` · 给 outlier 留更多 sem · 5 min。
风险中:cosyvoice rate limit(需 PM 看 quota 或先调到 4 试试)。

---

## §2 (b) VAD 卡空闲

### §2.1 VAD 状态机(`frontend/src/hooks/useAudio.ts:128-224`)

状态 enum:`'sleep' | 'active' | 'recording'`

转换:
```
sleep   --[toggleVad]-->  active   (initStream + RAF loop start)
active  --[max ≥ threshold]-->  recording   (startRecorder + emit listening)
recording --[silence > silenceTimeoutMs]-->  active   (stopAndSend)
active  --[60s 无录音]-->  sleep   (idle timeout)
* --[toggleVad while active/recording]-->  sleep   (cancelRAF)
```

VAD loop(RAF 每帧 ~16ms 跑一次)算法:
1. 取 `analyser.getByteFrequencyData(dataArray)` 得 frequency bins
2. 取最大值 `max`
3. threshold = `(vadThreshold / 100) * 255`
4. `if vadState === 'active' && max ≥ threshold && !recording` → startRecorder
5. `if vadState === 'recording' && max < threshold` → silence countdown
6. `if vadState === 'active' && !recording` → check idle 60s → sleep

### §2.2 "卡空闲" 可能原因排查

| # | 原因 | 概率 | 表象 |
|---|---|---|---|
| 1 | **vadThreshold 太高** | **高**(PM 65 → raw 166 / 255)| max 永不达 threshold · loop 跑但不触发 record |
| 2 | **MediaStream tracks ended** · 系统其他 app 抢 mic | 中 | analyser 仍工作 · 但 dataArray 不更新 · max ≈ 0 |
| 3 | **AudioContext suspended** · 浏览器 autoplay policy | 中 | analyser 工作 · 但 getByteFrequencyData 返 zero |
| 4 | **vadState === 'sleep'** · 60s idle timeout 后 · PM 没 toggleVad | 中 | loop 跑但所有 branch fail · VadBar 不渲染(per bugfix-4)· 显示像 mic 闲置 |
| 5 | **App 后台 / Tauri webview suspend** | 低-中 | mic 流暂停 · 切回前台未自动恢复 |
| 6 | **micMuted = true**(AI 说话期间)· 用户以为 mic 关 | 低 | vad loop 进 muted 分支 · 不录但仍跑打断检测 |

### §2.3 PM 当前 threshold 65 分析

```js
threshold_raw = (65 / 100) * 255 = 165.75
```

正常人说话(20cm mic) frequency bin max 通常:
- 安静呼吸:10-30
- 轻声说话:50-100
- 正常说话:120-180
- 大声说话:200-255

**threshold 165 落在"正常说话"上沿 · 大概率压不过**。default 50 = 127 raw 是合理设置。
PM 调到 65 是为了避免误录(打字 / 周围声 / 风扇)· 副作用 = 录不到自己说话 · 表象 = "VAD 不响应"。

### §2.4 WS reconnect 影响 verify

PM 观察 backend log "15:12:54 Websocket connected" 连续 3 次(0.5s 内)。
更多频繁 reconnect:14:14:36 - 14:15:16 6 次 reconnect / 30s。

**WS reconnect 不直接影响 VAD**:
- VAD loop 在 `useAudio.ts` · 独立 of WS
- MediaStream + AudioContext 是 React useRef 持久 · 不随 WS 重连重置
- 但 reconnect 期间 sendVoice 可能失败(WS closed)· 用户录的音丢
- 频繁 reconnect 提示 WS 健康问题 · 单独 audit backlog

### §2.5 缺 stream 健康检查

`useAudio.ts:58-71 initStream` 是幂等:
```js
if (streamRef.current) return streamRef.current;  // ← idempotent · 不 verify stream alive
```

如果 `streamRef.current.getTracks()[0].readyState === 'ended'` · initStream 仍返回
那个 stale stream · analyser 不出数据 · VAD 卡。

**没有 recovery mechanism**:
- ❌ AudioContext.state === 'suspended' 时未 resume
- ❌ MediaStreamTrack.onended 未监听
- ❌ visibilitychange / pagehide 未处理
- ❌ getUserMedia permission 撤销 未处理

### §2.6 推荐 fix 方向

| Option | 描述 | 工程量 | 风险 |
|---|---|---|---|
| **G** | UI 加 **VAD threshold quick-feedback**(实时显示当前 max 值 + 阈值 bar)| 1-2h | 低 |
| **H** | `initStream` 加健康检查:track readyState / context state · 不健康则 re-init | 30 min - 1h | 低 |
| **I** | `MediaStreamTrack.onended` listener · 自动 re-init + 提示用户 | 30 min | 低 |
| **J** | `visibilitychange` listener · 后台时 vadState→sleep · 前台时 auto resume(可选)| 30 min | 低 |
| **K** | PM **暂时把 threshold 调回 50**(default)· 直接 work-around 当前问题 | 0(纯设置)| 0 |
| **L** | WS 重连频繁 audit(独立 issue · 跟 VAD 不直接相关)| 1-2h | 单独立项 |

### §2.7 §2 推荐(强推)

**Option K · PM 把 threshold 调回 50** · 0 工程量 · 直接 verify 是不是 threshold 问题

如果调回 50 后 VAD 工作正常 → 真因就是 threshold 太高 · Option G 加个实时 bar
让 PM 调到合适值就完事
如果调回 50 仍卡 → 真因在 stream stale / AudioContext suspended · 走 Option H+I+J
组合 fix(2-3h)

---

## §3 §1 与 §2 互动 · 与 INV-13 相关性 explicit verdict

| 改动 | 是否相关本次 issue |
|---|---|
| INV-13 Option F · trigger prompts ja-aware | ❌ 仅 proactive trigger · 不影响 normal chat |
| INV-13 Option G · 软化 trigger 字数硬约束 | ❌ 同上 · 仅 proactive |
| INV-14 P1 · backend HF_HUB_OFFLINE 移除 | ❌ ASR 路径 · 与 TTS / VAD 无关 |
| INV-14 P2 revert · UI re-expose | ❌ UI 入口 · 与 runtime 无关 |
| INV-13 §12 v4_0_0_mai_revert_zh hotfix | ❌ voice_model state stable · 与本 issue 无关 |
| **PM 切到 cosyvoice longxing_v3 zh** | ✓ **相关** · `merge_short_sentences` 失效(zh 不启用)放大 HOL 概率 |
| **cosyvoice cloud API 偶发 9s outlier** | ✓ **相关** · TTS 时间 stochastic 直接造成 HOL blocking 5s |

**总结**: 本次 issue **完全独立于 INV-13 系列改动**。是 chunk 15 closed 时的
"TTS 单句合成时间稳定"假设在 cosyvoice cloud 偶发慢 + zh 模式无 merge 时不再
成立。

---

## §4 §1 + §2 联合 fix · 工程量 + 风险评估

### 推荐 ship 顺序

| Priority | 项 | 工程量 | 预期效果 |
|---|---|---|---|
| **P1** | Option A · `merge_short_sentences` 扩 zh | 5-10 min | 多句 turn HOL 概率显著降 · zh 体验提升 |
| **P1** | Option K · PM 调 vad threshold 回 50 | 0 | 验证 VAD 卡是否 threshold 问题 |
| **P2** | Option G · VAD UI 加实时 max + threshold bar | 1-2h | PM 看 bar 直观调 · 防再误设过高 |
| **P2** | Option H · `initStream` 加 stream 健康检查 + auto re-init | 30min-1h | mic stream 自愈 · 切 app / 系统抢 mic 后能恢复 |
| **P3** | Option B · TTS_CONCURRENCY 3 → 5 | 5 min | sem 利用率提升 · 但 HOL 仍存在 · 副作用 cosyvoice quota |
| **P3** | Observability:WS audio_consumer push_latency_ms log(ROADMAP:206 backlog)| 2-4h | dogfood 期间快速定位 audio gap 根因 |
| **不推荐** | Option C 乱序播 / Option D 全 buffer | - | UX 破坏 / 首字延迟显著恶化 |

**最低成本组合**:**A + K · 总 10 min**

- A 改 ws.py 1 行 · 解决 zh 多句 HOL
- K PM 自己改 UI slider 回 50(无需 commit)

如效果不充分(PM 真机后仍体感 gap)· 升级到 P2 组合(G + H · 共 2-3h)。

### §4 与 ROADMAP 关系

ROADMAP.md 已有 backlog:
- L30 "句子并发 TTS pipeline(chunk 15 复活)"P1 — 本 audit 数据可输入此 backlog
- L206 "推送延迟 metric · audio_consumer perf_counter 记录"v4.1 nice-to-have —
  Option G 实现时一并加 instrumentation 复用

---

## §5 audit 副产物 backlog(本 audit 不动)

- WS reconnect 频繁(15:12:54 / 0.5s 3 次 + 14:14-15:15 30s 6 次)· 单独 audit
  backlog · 可能 Tauri webview / 心跳超时 / 服务端 idle 断
- `extract_tts_text` 在 zh 模式下剥 `<ja>` 标签 · 看 15:12 turn 内容 id=126 仍含
  ja 标签 · 说明 LLM 即便 directive 切 zh 也仍 in-context 抄 ja history · 这是
  INV-13 Lesson #17 "in-context > directive" 复现 · 单独立项决定是否给 short_term
  加 zh 切换时清 ja 痕迹的 helper
- cosyvoice provider rate limit / latency SLO 文档化 · 给 TTS_CONCURRENCY 调参提供
  数据
- audio chunk push_latency observability(ROADMAP:206 现有 backlog)+ "max(synth_time)
  / median(synth_time) ratio" alert · stochastic outlier 自动检测

---

## §6 给 PM 的告知

### 真问题 mapping

**(a) audio 间隔大**:
- **不是** "LLM 拆得更碎"(DB 实证 ja 模式 avg 2 sentence / turn 没变)
- **不是** "INV-13 改动副作用"(INV-13 只动 proactive · 不动 normal chat)
- **是** TTS consumer FIFO 排队 · 一句慢(cosyvoice cloud 9s outlier)就 block 后续 5s
- PM 切 zh 后 `merge_short_sentences` 失效放大了概率(更多更短句 = 更多 outlier 机会)

**(b) VAD 卡空闲**:
- **最可能 threshold 65 太高**(raw 166 / 255 · 压不过正常说话 120-180)
- 备选:stream stale(系统抢 mic / 应用后台)· 但缺 stream 健康检查无法自动 recovery

### Quick fix 验证(5 分钟 PM 自己可做)

1. **(b) VAD**: 把 vadThreshold 调回 50(default)· 测说话是否能触发 record
2. **(a) audio gap**: 让 CC ship Option A(`merge_short_sentences` 扩 zh)· 5-10 min

### 如果 quick fix 不解决

- (b) VAD 调回 50 仍卡 → 真因不在 threshold · 走 Option H+I+J 组合(2-3h)
- (a) Option A ship 后仍体感 gap · 走 Option B(TTS_CONCURRENCY +)或 P3 instrumentation

### 不需要做的

- ❌ 重写 LLM prompt 鼓励长句(Option E · 效果不确定)
- ❌ 改播放顺序(Option C · UX 破)
- ❌ 整 turn 预 buffer(Option D · 首字延迟恶化)

---

## §7 audit 沉淀候选 Lesson(待 ship 后定)

- **#20 候选** · "chunk closed 时假设的稳定性必须 long-running verify" — chunk 15
  closed 时假设"TTS 单句合成时间稳定 · FIFO 顺序不影响体感" · 实际 cloud API
  stochastic 出 9s outlier 让假设破。closed 时只跑了短 session 验收 · 缺 long-running
  outlier 统计 · audit 应该带"假设破坏阈值" + 定期 sample DB log 验证
- **#21 候选** · "新功能 enable 条件不能凭"那时唯一支持的语种"绑死" — merge_short_sentences
  当时只为 ja/en 设(short-audio quality 问题)· INV-11 切 ja 后此约束语义改变 ·
  zh 角色 cosyvoice 同样 benefit · 但没人复查。**功能 enable gate 用功能需求语义**
  (eg "short audio quality") **而非 "支持的语种白名单"** · 长期更稳

---

**§1-§7 audit 闭环 · 0 code 改 · 0 commit 改 · 0 push · 纯 audit + report**。PM
拿到后跟另一对话讨论 priority + ship。强推 **A + K · 10 min** 见效后再决定升级。

---

## §8 Ship 记录 · P1 Option A(2026-05-27)

### §8.1 Commit

| Commit | 主题 | 文件 | LoC |
|---|---|---|---|
| `534a6ca` | **P1 Option A** · `merge_short_sentences` 扩到 zh · HOL blocking 概率降低 | `backend/routes/ws.py` + `backend/proactive/engine.py` | +15 / -11 |

### §8.2 改动细节

`backend/routes/ws.py:857-866`(chat 主路径):
- 删 `if tts_language in ("ja", "en"):` gate
- `merge_short_sentences(_agent_stream)` 对所有 tts_language(zh / ja / en)生效
- 注释 update · 标 INV-15 + 副作用说明

`backend/proactive/engine.py:449-455`(proactive trigger 路径):
- 同款改动 · 对称(Bugfix-segment2-3 原本就要求两路径同源)

### §8.3 Sanity 实测(CC 侧 dev-time)

mock 5 短 zh sentences:
```
Input:  ['...行吧。', '正好我也休息一会儿。', '说吧，', '想聊什么？', '随便扯都行。']
Output: 3 merged sentences (5 → 3 · -40% TTS call)
```

merge 触发场景:
- sentence 1 '...行吧。' (4 chars subtitle): buffer it · 等下个 sentence
- sentence 2 (10 chars): not short → flush sentence 1 + buffer 2
- sentence 3 '说吧，' (3 chars): short + buffer 非空 → merge into buffer 2
- sentence 4 '想聊什么？' (5 chars): short + merge · buf ≥ 15 → flush merged
- sentence 5: end-of-stream residue flush

### §8.4 ⚠️ 限制(诚实告知)

PM 15:12 turn 实际 sentence lengths(subtitle chars):**7 / 11 / 12 / 25**。
default `short_threshold=8` 下 · 仅 sentence #1(7 < 8)算 "短" · 但 buffer 空时
进 "first short" 分支被 sentence #2 flush · **本 turn 实际无 merge fire**。

→ Option A 对 **更短 sentence pattern**(≤ 7 chars · eg 单字回应 "嗯" "好" "走吧")
显著见效;对 PM 15:12 类 "中等长度 + 一个 9s outlier" turn 仍可能体感 gap(因
merge 没触发 · TTS call 数不减)。

### §8.5 真机回归 PM 拿到后验证

预期看到:
- 简短回答类 turn(≤ 3 sentences 各 < 8 chars)· merge 后 audio chunk 数减少
- 中长 turn 多句不全短(eg PM 15:12 case)· merge 可能不触发 · HOL 仍可能
- 字幕推送延 < 200ms(merge buffer flush 阈值 15 chars)· 用户感知 negligible

如 ship 后 PM 仍体感 gap · 升级 P2/P3 candidates:
- **threshold tune**:`short_threshold 8 → 12` + `flush_threshold 15 → 25` ·
  更激进 merge · 覆盖 PM 15:12 类 sentence 长度区间 · 0.5h 改 default + 实测
- **TTS_CONCURRENCY 3 → 5**(需查 cosyvoice quota · 5 min 改)
- **audio_consumer push_latency 实例化**(ROADMAP:206 现有 backlog · 2-4h)
- **out-of-order playback / 整 turn 预 buffer**(不推荐 · UX 破)

### §8.6 配套 Lessons 沉淀

- **Lesson #20** · chunk closed 时假设的稳定性必须 long-running verify
  (chunk 15 假设 "TTS 时间稳定" 被 INV-15 实测打破)
- **Lesson #21** · enable gate 用语义需求 · 不用"那时唯一支持的语种"白名单
  (`if tts_language in ("ja","en")` 案例 · INV-15 直接删 gate)

### §8.7 与 INV-13/14 改动关系(explicit verdict 复述)

**完全独立** · INV-13 F+G 仅动 proactive trigger prompts · INV-14 是 ASR / UI ·
都不动 TTS pipeline。本次 issue 真因 = cosyvoice cloud stochastic outlier + PM
切到 zh 后 merge 失效叠加。

### §8.8 ROADMAP 同步

`ROADMAP.md:30` "句子并发 TTS pipeline(chunk 15 复活)" P1 backlog · 状态保持
📋(本 commit ship 是 Option A 缓解 · 不是 chunk 15 完整复活)· 加 reference:
"已 INV-15 P1 Option A 部分 mitigation · 见 docs/INV-15-*.md §8 + commit 534a6ca · 完整
out-of-order / 整 turn 预 buffer 不推荐 · 留 backlog 待新场景触发"。

ROADMAP:206 "推送延迟 metric" 仍 P3 nice-to-have · INV-15 §6 推 P3 项叠加触发。

---

**§8 ship 闭环 · P1 Option A 单 commit · zh 路径 merge 启用 · 等 PM 真机回归 ·
若效果不足 · 升级 P2(threshold tune)/ P3(concurrency / observability)**。
