# Investigation 8 · TTS 模块化 + Fish 集成

> 接 INV-7 子轨 B closure 后第一刀(2026-05-21,-5,949 token / -44.9% 累计)。
> 主线 = TTS 模块化抽象 + Fish Speech 装通;验收门 = Mai 跑出"中文显示 + 日语 TTS"全链路。
> Phase 1 = §1 audit(本节,纯只读)→ Phase 2 = TTSProvider 抽象设计 → Phase 3 = Fish 集成 + 流式管线 + 停顿 fix。
> 5 个 PM 决策的三档结论(✅ / ⚠️ / 🔁)按节滚动落,§1 收口汇总。
> 写法 follow INV-7 风格(数据表 + 双 grep audit + lesson 沉淀)。

## §1 audit (2026-05-22)

  §1.1 句间停顿 0.5-1s 根因 audit ⚠️必做前置
  §1.2 现有 TTS 调用链路 audit
  §1.3 Fish API + s2 pro zero-shot 调研(stage 1 待启)
  §1.4 voice ↔ character ↔ language 关系审计(待启)
  §1.5 LLM 双语 schema design space(待启,与 §1.3 联合)

---

## §1.1 句间停顿 0.5-1s 根因(Stage 1 静态 audit + instrumentation 提案,2026-05-22)

> ⚠️ Phase 3 流式管线设计前置;主问题用户体感"句号后 0.5-1s 显著停顿,反人类"。本节 stage 1 = 纯静态代码 audit + 4 假设代码侧观察 + instrumentation 提案;**stage 2 真机 log 分析待 PM 批 instrumentation + 跑真机后续行**。

### §1.1.1 切句规则 + 调用链时序图(静态侧观察)

#### 切句规则(chat.py:336-448 / base.py:14-34)

两套独立切句实现,生产路径走 chat.py 版本(`_safe_boundary` + `_find_boundary`):

| # | 位置 | 触发标点集 | 用法 |
|---|---|---|---|
| 1 | `chat.py:336` `_SENT_END = frozenset("。！？!?")` | 5 char | 主 LLM stream sentence-yield |
| 2 | `base.py:19` `_SENT_RE = re.compile(r'(?<=[。！？!?])')` | 5 char | 旧 `TTSManager.stream()` (zh 路径未走) |

**切句粒度**:每个 `。/！/？/!/?` 切一句 → LLM 一轮 200 字回复(典型 Mai 风格) **切成 ~5-15 句**(取决于标点密度;sentence_merge.py 在 zh 模式 pass-through,**不合并短句**)。

句末标点**保留在句子尾部**(base.py:31 `[p.strip() for p in _SENT_RE.split(text)]` 等价 lookbehind 后切),意味送进 CosyVoice 的 text 是 `"你好！"` 而非 `"你好"`。

#### chunker boundary 状态机(chat.py:355-425)

`_find_boundary` 是带 paired-tag 跳过的 state machine:
- 扫到 `<tagname>` 开标签 → 判 paired vs 自闭合
- **paired meta tag**(thinking/emotion/state_update/motion/tool_call/function_calls/invoke/**ja**/**en**)内部的句末标点 **不切句**,等 `</tag>` 出现
- 未闭合 → 返 -1 让 sentence stream 累积下个 token

**关键观察**:`_BOUNDARY_PAIRED_TAGS` 已含 `ja` / `en`(v4 segment 2 §2.4 留下的死代码,Mai zh 回退后未触发但 boundary set 仍含)。

#### TTS 调用形态(ws.py:712-1006 主链路)

```
[chat.py.stream()]          [ws.py 主链路]                    [前端 useWebSocket]
LLM token delta             async for sentence in stream      ws.onmessage('audio_chunk')
  → sent_buf += content       → parse emotion/state/...         → new Audio(base64)
  → _safe_boundary(buf)       → strip_*_tags                    → pipeAudioElement
  → idx != -1 ?               → final_chunk = strip_subtitle    → audioQueueRef.push
    yield sentence            → ws.send_json('text_chunk')      → playNextAudio()
                              → tts_text = extract_tts_text
                              → spawn task(_tts_synth_with_timeout)
                              → audio_queue.put(task)
                                                                  
                              [consumer FIFO]                   [handleEnd 三路]
                              → await task (TTS_TIMEOUT=10s)     - 'ended' (不可靠)
                              → ws.send_json('audio_chunk')      - 'error'
                                                                 - setTimeout(dur+1000ms)
                                                                 - or 30s 极端兜底
```

并发控制:`TTS_CONCURRENCY = 3` 信号量 + `TTS_TIMEOUT_S = 10.0`(ws.py:188-190)。

**TTS provider 调用形态 ≡ 非流式**:`cosyvoice.py:201-202 synthesizer.call(text)` 是 DashScope SDK 的**阻塞同步接口**,**一次返完整 WAV 24kHz mono 16bit bytes**(对应 streaming 的 `streaming_call()` 当前未用)。每句 = 一次完整 HTTP/WebSocket 往返 + 完整 WAV decode。

### §1.1.2 4 假设代码侧观察

#### H1 · CosyVoice 模型自带 silence padding(训练时句末加静音)

**代码侧观察**:
- `cosyvoice.py:202` `synthesizer.call(text)` 把 LLM yielded 的完整句子(含尾标点 `。/！/？`)整段送 SDK,**未对 text 做尾标点剥除**
- DashScope CosyVoice 模型训练数据是否在句末加 silence padding 是**黑盒**,代码层无线索
- preprocess_tts_text 的 `_PREPROCESS_PATTERNS`(`__init__.py:49-56`)剥 motion/动作/注释/中括号,**保留句末标点**(prosody cue 需要)

**stage 1 verdict**:H1 **无法在代码层确证**,需要 stage 2 真机录音(`call("你好！")` vs `call("你好")` 对比尾静音 ms)。

#### H2 · 句级 streaming 链路 RT gap(每句独立 synth call)

**代码侧观察 — 时序 gap 的 7 个候选位点**:

| # | 位点 | 文件:行 | 时间估(粗) | 备注 |
|---|---|---|---|---|
| 1 | LLM yield sentence → ws.async for | chat.py:1737 / ws.py:818 | ~0ms | 同协程内 yield |
| 2 | sentence parse + strip(5 道剥) | ws.py:840-913 | ~1-5ms | 纯正则,内存 |
| 3 | spawn TTS task + audio_queue.put | ws.py:963-970 | ~0ms | task 异步起 |
| 4 | TTS task 拿到 semaphore | _tts_semaphore(3) | 0 - N*timeout | 通常 0;并发饱和时积压 |
| 5 | engine.synthesize(text) | cosyvoice.py:212-243 | **核心** | asyncio.to_thread → SDK blocking call → 网络 RT + 模型 inference |
| 6 | consumer await task → ws.send_json | ws.py:257-266 | ~1-5ms | 已 ready 的 task 直接 await |
| 7 | network → frontend ws.onmessage | (网络) | ~1-30ms | 本机 ws + base64 decode |

**关键代码 timing log**(已存,但未跨句配对):
- `chat.py:1731-1736` `[TIME] sentence yield #N: Xms (len=Y)` — 句 yield 时延
- `ws.py:222-225` `[TIME] TTS #N: Xms len=Y` — **单句** TTS 时延(已有埋点)

**stage 1 verdict**:H2 的 #5 (TTS synthesize) 已有 ms 级 log,但 **gap = TTS_n+1 完成 - TTS_n 完成 - audio_n+1 播放完** 这个差量**没有跨句关联的 ts 链路**,需 stage 2 instrumentation 补齐(详 §1.1.3)。

#### H3 · 前端 WebAudio buffer 切换 gap ⚠️ 最高嫌疑

**代码侧观察 — useWebSocket.ts:81-142 playNextAudio 全链路**:

```javascript
// useWebSocket.ts:97-104 注释明确指出:
// "createMediaElementSource 把 audio element 接进 WebAudio 图后,
//  'ended' 事件触发不可靠(方案 A 已实测失败:第二段以后 onended 不打;
//  pause 守卫的 duration 也常 NaN,guard 永 false)"
// 改用三层兜底:
//   1. 'ended' 事件(少数情况下还能打就用)
//   2. 'error' 事件
//   3. wall-clock setTimeout(不依赖元素事件) ── 主要靠这个推进
//      - loadedmetadata 拿到 duration → setTimeout(duration*1000 + 1000)
//      - duration NaN / loadedmetadata 不打 → 30s 极端兜底
```

**关键发现** — `useWebSocket.ts:134-135`:

```javascript
const safeMs = Math.ceil(next.duration * 1000) + 1000;  // ← +1000ms safety margin
playbackTimeoutRef.current = setTimeout(handleEnd, safeMs);
```

**精确兜底版**在 audio 真实 duration 上额外加 **1000ms** 等下一段;这是 v3-E1 step4 修法 B 引入的设计性 trade-off(防止过早切段裁断 audio 尾部),但**在 'ended' 事件不可靠的当前 createMediaElementSource pipeline 下,这 1000ms 是默认每句 gap 的下限**。

**stage 1 verdict**:H3 **几乎确定是 0.5-1s 停顿主因之一**;代码侧已注释承认 'ended' 不可靠依赖 setTimeout + 1000ms margin。需 stage 2 真机 log 量化 audio_ended → next.play() 实际 gap ms,确认这个 1000ms 是否触发(还是 'ended' 偶发成功了)。**建议 Phase 3 流式管线设计时优先解决这条**。

#### H4 · 后端 chunker 切句策略问题(切得过细)

**代码侧观察**:
- `_SENT_END = "。！？!?"` 5 char 触发集,标点密度高的 Mai 风格(大量短句 + 标点)切句 ~5-15 句/turn
- `sentence_merge.merge_short_sentences` v4-Segment2-3 引入 — 短句合并 buffer,**短阈值 8 char / flush 阈值 15 char**
- **关键**:ws.py:815-817 `if tts_language in ("ja", "en"):` 包 merge_short_sentences,**zh 模式不包**(per v4_0_0_mai_revert_zh.py 决策)
- Mai 当前 `tts_language=zh` → **不走短句合并**,每个标点切一句直接送 TTS

**LLM-side 行为**:Layer A1 emotion 密度 + Mai 性格本身偏多短句感叹(实测 Mai voice_samples 短句风格)→ 切得细。

**stage 1 verdict**:H4 **结构性成立**(zh 路径短句不合并 + Mai 风格短句多 → 切句数 N 大),**但 chunker 切得细本身不直接产生 0.5-1s 停顿**,而是放大 H3(每多切一句 = 多一次 +1000ms gap 触发机会)。**H3 × H4 复合效应**。fix 路径:zh 模式也接 merge_short_sentences(单 line config 改),但需评估 zh 模式字幕跟手感降级。

### §1.1.3 Instrumentation 提案(stage 2 落地待 PM 批)

**纪律**:统一 `# DEBUG-INV8` 注释标记,审完一键 `grep -rn "DEBUG-INV8" backend/ frontend/ | wc -l` 然后 `git restore -p` 拔光。

#### 后端 7 个 log 点

| # | 位置 | 字段 | 用途 |
|---|---|---|---|
| 1 | `chat.py:1737` 前(sentence yield 时) | `sentence_idx / char_len / enter_ts=perf_counter()` | 后端 sentence 产生 ts |
| 2 | `ws.py:963` 前(spawn task 时) | `sentence_idx / spawn_ts` | sentence → TTS task 入队 ts |
| 3 | `cosyvoice.py:230` 前(asyncio.to_thread 前) | `sentence_idx / synth_enter_ts` | SDK 调用前 ts |
| 4 | `cosyvoice.py:230` 后(audio bytes return 后) | `sentence_idx / synth_return_ts / audio_bytes_len` | SDK 返回 ts(测真实 SDK RT) |
| 5 | `ws.py:265` 前(consumer await task 前) | `sentence_idx / consumer_await_ts` | FIFO 消费时 ts |
| 6 | `ws.py:798` 内(send_json 前) | `sentence_idx / ws_send_ts` | ws push ts |
| 7 | `cosyvoice.py:201` 内(synthesizer.call return 后) | 如能拿到 WAV bytes 长度 / 采样率 → 估 audio duration | 用于跨 H1 estimate |

#### 前端 4 个 log 点

| # | 位置 | 字段 | 用途 |
|---|---|---|---|
| 8 | `useWebSocket.ts:243` audio_chunk case 入口 | `chunk_idx / receive_ts=performance.now()` | 前端收到 ts |
| 9 | `useWebSocket.ts:127` loadedmetadata handler 内 | `chunk_idx / loadedmetadata_ts / duration` | audio 解码完成 ts + duration |
| 10 | `useWebSocket.ts:141` next.play() 调用前 | `chunk_idx / play_start_ts` | 真正开播 ts |
| 11 | `useWebSocket.ts:113` handleEnd 内 | `chunk_idx / end_ts / trigger=('ended'\|'error'\|'timeout')` | **关键**:测 'ended' 是否触发 / setTimeout 触发率 |

#### Stage 2 真机 PM 跑测脚本

PM 跑 3-5 句典型 Mai 回复(标准 chat,zh 路径),CC 分析 log,对 4 假设各自给 verdict:
- H1 verdict:若有 audio_bytes_len / sample_rate → 算 audio duration vs 实际 play_end - play_start 推 padding ms
- H2 verdict:tts_synth_return - tts_synth_enter 即 SDK RT;sentence_n+1 spawn - sentence_n 完成 = 句间链路 gap
- H3 verdict(**最关键**):play_n+1.play_start - play_n.handleEnd_ts = 前端 gap;若 >900ms 且 trigger='timeout' → 实锤 +1000ms safety margin
- H4 verdict:统计 sentence 数 + char_len 分布

### §1.1.4 Fix 提案方向(Phase 3 设计输入,本节不写代码)

按 verdict 不同 fix 难度排序(从低到高):

| Verdict 假设 | Fix 方向 | 工程量 |
|---|---|---|
| H3 实锤(+1000ms margin) | 改 useWebSocket 抛弃 setTimeout 依赖,改成 WebAudio API decodeAudioData → AudioBufferSourceNode 序列(浏览器原生支持 seamless concat,精确 onended) | 2-3d frontend 重构 audio pipeline |
| H4 实锤(切句过细) | zh 模式接 merge_short_sentences;或参 ja 模式短/flush 阈值改成 zh-friendly(默认 8/15 偏短) | 0.5d backend |
| H2 实锤(链路 RT) | TTS 改 streaming(`streaming_call()` + PCM chunked)+ 前端 AudioWorklet 实时拼接 | 1-2w 全管线重构 |
| H1 实锤(模型 silence padding) | 后端剥句末标点送 TTS(但损 prosody)/ 或音频后处理切尾静音(WAV trim) | 1-2d |

**预判**:H3 + H4 是主因,fix 走 frontend audio pipeline 重构 + zh merge_short_sentences,**Phase 3 流式管线设计同时落**(顺势统一)。

### §1.1.5 PM 决策 leaning 状态(本节产出)

| 决策 | leaning | 三档结论 | 备注 |
|---|---|---|---|
| 决策 5 fallback + quota | Fish 失败/耗尽 → CosyVoice + toast | (待 §1.3) | §1.1 不涉及 |

§1.1 不直接影响 5 决策的任一条,但 fix 方向(H3 frontend pipeline 重构)是 Phase 3 流式管线设计的强约束 — 若用 Fish 走 streaming 也必须重构前端 audio pipeline,**两件事可合并一刀**。

### §1.1.6 收口(Stage 1)

- ✅ 切句规则定位(_SENT_END=5 char / chat.py 主路径 / base.py 旧路径)
- ✅ 调用链时序图(LLM yield → ws spawn → consumer FIFO → ws send → 前端 audio queue → play)
- ✅ 4 假设代码侧观察 + 各自初步 verdict
  - H1 黑盒,需 stage 2 实测
  - H2 SDK RT 大头但已有部分埋点
  - **H3 几乎确定为主因之一(代码侧 +1000ms safety margin 注释明示)**
  - H4 结构性成立,放大 H3 复合效应
- ✅ instrumentation 提案 11 个 log 点(后端 7 + 前端 4,统一 `# DEBUG-INV8` 标记)
- ✅ fix 方向 4 路提案(H3 fix 工程量最小但收益最大;Phase 3 流式管线时合刀)

→ **§1.1 stage 1 完成,等 PM 批 instrumentation(决策点:11 个 log 点全加 / 子集 / 调整字段)+ 跑真机后进 stage 2 分析**。Step 6 流程。

---

## §1.2 现有 TTS 调用链路 audit(单 stage,2026-05-22)

> Phase 2 TTSProvider 抽象层设计的"插点地图"。摸清当前 TTS 从 LLM stream 到前端播放的全链路,定位 3 个候选抽象插点。

### §1.2.1 backend/tts/ 文件树

```
backend/tts/
├── __init__.py        14,712 bytes  (旧 TTSManager + v3-D 新 get_tts_engine 工厂)
├── base.py             2,247 bytes  (TTSBase + TTSProvider + split_sentences)
├── cosyvoice.py       11,782 bytes  ⭐ 当前生产主路径
├── edge.py             1,497 bytes  (legacy fallback, _VOICE_MAP 5 char 硬编码)
├── sovits.py           3,604 bytes  (占位, _VOICE_PRESETS 5 char 硬编码)
└── voice_config.py     3,449 bytes  (VoiceConfig dataclass + parse_voice_config)
```

**两套抽象并存**(base.py:1-11 注释):

| 抽象 | 接口签名 | 用户 | 现状 |
|---|---|---|---|
| `TTSProvider` (legacy) | `synthesize(text, character) → bytes` | `TTSManager` (旧 ws.py 路径,zh 路径已不走) | 保留代码备回滚 |
| `TTSBase` (v3-D 起) | `synthesize(text, emotion="默认") → Optional[bytes]` | `get_tts_engine()` 工厂 + `CosyVoiceTTS` | ⭐ 当前主路径 |

**legacy → new 适配器**:`_LegacyProviderAdapter`(__init__.py:239-264)把 `TTSProvider` 包成 `TTSBase` 形态,emotion 字段忽略,失败返 None 走静默降级。

### §1.2.2 链路文字图(LLM 出第 N 句 → 前端扬声器播 N 句)

```
[Step 1 · LLM 出句]
backend/agents/chat.py:1709-1738
  LLM token delta `delta.content`
  → assistant_text += content / sent_buf += content
  → while True:
      idx = _safe_boundary(sent_buf)              # chat.py:405-425 paired-tag aware
      if idx == -1: break
      sentence = sent_buf[:idx+1].strip()         # 含句末标点
      sent_buf = sent_buf[idx+1:]
      yield sentence                              # → ws.py:818 接

[Step 2 · ws 接句 + 5 道 strip + spawn TTS task]
backend/routes/ws.py:818-970
  async for sentence in _agent_stream:
    # ja/en 模式 wrap merge_short_sentences (ws.py:815-817)
    # zh 模式直 stream
    if isinstance(sentence, dict): ws.send_json(sentence)  # tool_use_start/done
    
    # 5 道 parse + strip:
    parsed_emotion, sentence = _parse_emotion(sentence)        # 第一句锁定 turn_emotion
    parsed_state, sentence   = _parse_state_update(sentence)   # 第一句 DB 写
    thinking, sentence       = _parse_thinking(sentence)       # 每段
    motion, sentence         = _parse_motion(sentence)         # 每段
    sentence                 = strip_tool_call_fallback(sentence)
    
    reply_parts.append(sentence)
    final_chunk = strip_ja_en_tags_for_subtitle(strip_all_for_tts(sentence))  # 字幕路径
    await ws.send_json({"type":"text_chunk","content":final_chunk,"conversation_id":...})
    
    # TTS 路径
    tts_text = extract_tts_text(sentence, tts_language)        # zh 等价 no-op
    task = asyncio.create_task(
        _tts_synth_with_timeout(tts_engine, tts_text, turn_emotion, idx=sentence_idx)
    )
    pending_tts.append(task)
    await audio_queue.put(task)

[Step 3 · TTS task 节流 + 超时]
backend/routes/ws.py:201-240 _tts_synth_with_timeout
  async with _tts_semaphore (concurrency=3):
    audio = await asyncio.wait_for(
        engine.synthesize(text, emotion=emotion),
        timeout=10.0,
    )
  log: [TIME] TTS #N: Xms len=Y

[Step 4 · _PreprocessingEngine.synthesize 包装层]
backend/tts/__init__.py:267-288
  cleaned = preprocess_tts_text(text)              # 第三道 strip(*动作*/(注释)/[标记]/<motion>) + _tts_input_final_guard 兜 <ja>字面
  if not cleaned: return None
  return await self._inner.synthesize(cleaned, emotion=emotion)

[Step 5 · CosyVoiceTTS.synthesize 真合成]
backend/tts/cosyvoice.py:212-257
  emotion_en = _normalise_emotion(emotion)         # 中文→英文枚举
  log_tts_call(...) preset context
  audio = await asyncio.to_thread(self._blocking_synthesize, text, emotion_en)
  # _blocking_synthesize:
  #   - 判 instruct_supported × emotion in _INSTRUCT_EMOTION_WHITELIST
  #     × model not in _MODELS_WITHOUT_INSTRUCT
  #     → 选 instruct 路径 (instruction="你说话的情感是X。") vs plain text 路径
  #   - SpeechSynthesizer(**kwargs).call(text)  ← 阻塞 SDK 调用,一次返完整 WAV
  await log_tts_call(success=..., voice=..., model=..., input_chars=..., input_preview=..., error_message=...)
  return audio  # WAV bytes 24kHz mono 16bit

[Step 6 · audio_queue FIFO consumer + ws push]
backend/routes/ws.py:243-267 _tts_audio_consumer
  while True:
    item = await queue.get()
    if item is None: return                        # 哨兵
    audio = await item                             # FIFO 顺序 await
    await sender(audio)                            # = _send_audio (ws.py:794-802)
    
backend/routes/ws.py:794-802 _send_audio
  audio_b64 = base64.b64encode(audio).decode()
  await ws.send_json({
    "type": "audio_chunk",
    "content": audio_b64,
    "conversation_id": state.conv_id,
  })

[Step 7 · 前端收 audio_chunk]
frontend/src/hooks/useWebSocket.ts:243-261
  case 'audio_chunk':
    const audio = new Audio(`data:audio/wav;base64,${msg.content}`)
    pipeAudioElement(audio)                        # 接进 WebAudio AnalyserNode 图(Live2D 口型同步)
    audioQueueRef.current.push(audio)
    playNextAudio()

[Step 8 · 前端 audio queue 播放]
frontend/src/hooks/useWebSocket.ts:81-142 playNextAudio
  if (isPlayingRef.current) return                 # 已在播则等 handleEnd 再调
  const next = audioQueueRef.current.shift()
  if (!next): status='speaking' → 'idle'; return
  isPlayingRef.current = true
  
  next.addEventListener('ended', handleEnd)
  next.addEventListener('error', handleEnd)
  next.addEventListener('loadedmetadata', () => {
    safeMs = Math.ceil(next.duration*1000) + 1000  # ← H3 主嫌疑 +1000ms
    setTimeout(handleEnd, safeMs)
  })
  setTimeout(handleEnd, 30_000)                    # 极端兜底
  next.play().catch(handleEnd)
  
  # handleEnd:endedHandled=true / clearPlaybackTimer / isPlayingRef.current=false / playNextAudio()
```

### §1.2.3 文件清单表 + Phase 2 改造影响

| 文件:行 | 链路角色 | Phase 2 改造影响 |
|---|---|---|
| `backend/tts/base.py:48-60 TTSBase` | 抽象接口(synthesize) | **可插拔**(Fish 走相同签名;若需流式接口,加 `synthesize_stream(text) → AsyncIter[bytes]`) |
| `backend/tts/base.py:25-34 split_sentences` | 旧切句(只 TTSManager 用,zh 主路径未走) | **不动**(legacy 路径) |
| `backend/tts/base.py:14-22 _SENT_RE / _PUNCT_ONLY` | 同上 | 不动 |
| `backend/tts/__init__.py:291-333 _build_engine` | provider 选择(if cfg.provider == "cosyvoice/edge/sovits") | **必改**(加 `fish` 分支) |
| `backend/tts/__init__.py:336-349 get_tts_engine` | 外部唯一入口 | 不动签名;`_PreprocessingEngine` 包装继续生效 |
| `backend/tts/__init__.py:267-288 _PreprocessingEngine` | preprocess + 调 inner | 不动(Fish 也复用 strip 链) |
| `backend/tts/__init__.py:109-148 preprocess_tts_text` | 5 道 strip + _tts_input_final_guard | 不动(provider-agnostic) |
| `backend/tts/voice_config.py:30-48 VoiceConfig` | dataclass(provider/voice/instruct_supported/model) | **必改**(加 Fish 字段:`reference_audio_path` / `reference_text` / `emotion_markers_supported` / `language`) |
| `backend/tts/voice_config.py:51-92 parse_voice_config` | JSON 解析 | **必改**(透传 Fish 字段) |
| `backend/tts/cosyvoice.py` | 现 provider 实现 | 不动 |
| `backend/tts/edge.py` / `sovits.py` | legacy provider | 不动(保留) |
| **新增** `backend/tts/fish.py` | Fish provider | **新写**(实现 TTSBase) |
| `backend/routes/ws.py:733 tts_engine = get_tts_engine(voice_model)` | 工厂调用 | 不动签名 |
| `backend/routes/ws.py:737-743 tts_language 解析` | per-conv tts_language 读 voice_model JSON | **可能改**(若 Fish 需要 `language` 字段以 voice_model 单一字段表达) |
| `backend/routes/ws.py:201-240 _tts_synth_with_timeout` | 节流 + 超时 + 异常吞 | 不动接口;若 Fish 走流式,**必改**(加 stream 路径 + audio_queue 改 PCM chunked) |
| `backend/routes/ws.py:243-267 _tts_audio_consumer` | FIFO + send_json | 流式时**必改**(改 PCM forward + 前端 AudioWorklet) |
| `backend/observability/tts_log.py` | INSERT tts_call_log | **可能改**(若 Fish 新增字段如 `audio_duration_ms` / `streaming_chunk_count`) |
| `backend/agents/sentence_merge.py` | 短句合并 buffer | **可能改**(zh 模式接 merge,fix H4) |
| `backend/agents/chat.py:1709-1738 stream sentence yield` | LLM token → sentence boundary | 不动(per-LLM 不依赖 TTS) |
| `frontend/src/hooks/useWebSocket.ts:81-142 playNextAudio` | audio queue 播放 | **建议必改**(H3 fix,改 WebAudio API 序列拼接) |
| `frontend/src/lib/ttsAudio.ts:44-71 pipeAudioElement` | createMediaElementSource | 流式时可能淘汰(直接走 AudioWorklet) |

### §1.2.4 现 voice_model JSON 实例(cid=1 Mai 当样本 + 全表 9 char)

`SELECT id, name, voice_model, live2d_model FROM characters ORDER BY id;`(实测 DB momoos.db):

| cid | name | voice_model | live2d_model |
|---|---|---|---|
| 1 | Momo(借壳 Mai) | `{"provider":"cosyvoice","voice":"longyumi_v3","instruct_supported":false,"tts_language":"zh"}` | hiyori |
| 2 | 八重神子 | `{"provider":"cosyvoice","model":"cosyvoice-v3.5-plus","voice":"cosyvoice-v3.5-plus-bailian-a61ea44f8a9648b3920b7ef98280d226","instruct_supported":true,"ssml_supported":true}` | yae |
| 3 | 荧 | `{"provider":"cosyvoice","model":"cosyvoice-v3.5-plus","voice":"cosyvoice-v3.5-plus-bailian-ec2676aa187a44a2b448a37a239b29af","instruct_supported":true,"ssml_supported":true}` | (空) |
| 4 | 凝光 | (空) | (空) |
| 5 | 神里绫华 | `{"provider":"cosyvoice","model":"cosyvoice-v3.5-plus","voice":"cosyvoice-v3.5-plus-bailian-7c617acd71b54130ac14ea7158718916","instruct_supported":true,"ssml_supported":true}` | (空) |
| 99 | 一般路过猫娘 | (空) | (空) |
| 100 | 祥子-test | (空) | (空) |
| **101** | **樱岛麻衣** | `{"provider":"cosyvoice","voice":"cosyvoice-v3.5-plus-bailian-a19f528011c1446eafd4c4990301270f","instruct_supported":true,"tts_language":"ja"}` | hiyori |
| 102 | 流萤 | (空) | (空) |

**关键观察**:
1. **cid=1 Mai 当前活路径**:`tts_language=zh` + `voice=longyumi_v3`(走 yaml default model `cosyvoice-v3-flash`),与 DESIGN_LITE 红 flag #1 一致(Mai 已回退纯中文)
2. **cid=2 / 3 / 5** 已用 cosyvoice-v3.5-plus 自训复刻 voice(bailian-xxx),`instruct_supported=true` + `ssml_supported=true`(SSML 字段当前代码层无消费者,**死字段?待 §1.4 确认**)
3. **cid=101 樱岛麻衣**:**红 flag #1 提到的 ja 链 row 仍存活**!`tts_language=ja` + 复刻日语 voice;DESIGN_LITE 说"Mai 已回退纯中文"是指 cid=1 的活路径,**cid=101 这个独立 ja row 仍在 DB**,§1.4 需确认是否有任何调用者还引用它(`cid=101` row 是 v4-segment2 时代的"另一个完整 Mai 实例 ja 版",可能是 dogfood 期切角色测试用)
4. **4 个空 voice_model**(cid=4/99/100/102)→ `parse_voice_config` fallback 到 yaml default(longyumi_v3 / cosyvoice-v3-flash)
5. **`tts_language` 字段**仅 cid=1 和 cid=101 有(`zh` / `ja`);cid=2/3/5 无该字段 → fallback 何值?ws.py:737-743 默认 `"zh"`

`SELECT .schema characters` 揭示 characters 表无显式 `tts_language` 列,语种全嵌 `voice_model` JSON 里:

```sql
CREATE TABLE characters (
  id INTEGER NOT NULL,
  name VARCHAR NOT NULL,
  persona TEXT NOT NULL,
  avatar_path TEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  voice_model TEXT,          ← 语种 / provider / voice / instruct 全 JSON
  live2d_model TEXT,
  emotion_map_json TEXT,
  motion_map_json TEXT,
  hit_area_map_json TEXT,
  background_path TEXT NULL,
  splash_art_url TEXT,
  PRIMARY KEY (id),
  UNIQUE (name)
);
```

### §1.2.5 抽象插点提案(3 候选)

| 候选 | 插点位置 | 改动面 | trade-off |
|---|---|---|---|
| **A · TTS engine factory** | `_build_engine` (`__init__.py:291-333`) 加 `if cfg.provider == "fish": from ... import FishTTS; return FishTTS(...)` 分支 | 最小:加 1 `fish.py` + factory 1 分支 + voice_config 加 Fish 字段 | **改动最小**(per template P1.media/bilibili pattern);全部抽象保留 in-place;ws.py / consumer / 前端可不动(若 Fish 走非流式 WAV 一次返,与 CosyVoice 形态完全一致) |
| **B · TTS call site** (流式控制点) | `_tts_synth_with_timeout` (`ws.py:201-240`) 加流式 vs 非流式分支;audio_queue 改 PCM chunked | 中:ws.py 主链路重构 + consumer 改 + 前端 AudioWorklet | **Phase 3 流式管线必走**(若 Fish 走 SSE/chunked + 前端 AudioWorklet 实时拼接);A 是 B 的前置(先抽象 provider 再加流式 capability flag) |
| **C · Voice config schema 层** | `VoiceConfig` (`voice_config.py:30-48`) 加 `reference_audio_path` / `reference_text` / `emotion_markers_supported` / `language` / `streaming_supported` | 小:加字段 + parse 透传;不破现接口 | A 的**前提子改**,Fish-specific 字段集中在 VoiceConfig 一处管,db voice_model JSON 直接对应 |

**CC leaning(三档)**:
- ✅ **A + C 联合先 ship**(Phase 2 主体),B 留 Phase 3 流式管线时再做(若 H3 实锤,B 必做)
- A 是抽象层(命名层级:`Fish` 是 cosyvoice/edge/sovits 第 4 个 provider)
- C 是 voice_model JSON schema 扩展(reference_audio_path 等 Fish-specific 字段进 dataclass)
- B 是性能 / UX 升级,与 H3 fix 合刀

### §1.2.6 PM 决策 leaning 状态(本节产出)

| 决策 | leaning(brief 给) | 三档结论 | 备注 |
|---|---|---|---|
| 3 · TTSProvider 抽象接口 | `synthesize(voice_config, text, emotion_hint) → audio_stream` | ⚠️ **需要调整** | 当前 `TTSBase.synthesize(text, emotion) → Optional[bytes]` 是**已实现的抽象**(v3-D 起);brief leaning 改签名加 `voice_config` 参数 + 返流式,会大破现接口(`_PreprocessingEngine` / `_LegacyProviderAdapter` 全要改);**建议保持 `synthesize(text, emotion) → bytes` 单签名**,voice_config 通过**构造时注入**(已是现实现 — `CosyVoiceTTS(voice, instruct_supported, model)`,FishTTS 同 pattern);流式接口**新增** `synthesize_stream(text) → AsyncIter[bytes]` 单独方法,per-provider 可选实现(Fish 实现;CosyVoice 不实现,by default fall back 到 `synthesize`)。**详 §1.5 拍板包**(联合 design space 后给 final 接口提案) |
| 5 · fallback + quota | Fish 失败/耗尽 → CosyVoice + toast | (待 §1.3 落 quota 机制) | 抽象插点 A 天然支持(fish.py 内部 try/except 抛 → factory 在 ws.py 层级 try-fallback;quota 90%/100% 警告需新 endpoint,详 §1.3.6) |

### §1.2.7 收口

- ✅ 文件树(backend/tts/ 6 文件)+ 两套抽象(TTSProvider legacy / TTSBase v3-D)
- ✅ 链路文字图 8 step(LLM 出句 → 前端 play)+ 关键 ts 锚点
- ✅ 文件清单表 20+ 行(每行标 Phase 2 改造影响:必改 / 可插拔 / 不动)
- ✅ 现 voice_model JSON 9 char 实例 + 红 flag #1 cid=101 ja row 仍存活(待 §1.4 复活成本核实)
- ✅ 抽象插点 3 候选 + CC leaning A+C 联合先 ship / B 与 H3 fix 合刀
- ✅ 决策 3 给 ⚠️ 需要调整(接口签名 stick 现状 `synthesize(text, emotion)`,流式走新方法 `synthesize_stream`);决策 5 fallback 天然支持

→ **§1.2 单 stage 完成**。Step 1 整体 closed(§1.1 stage 1 + §1.2 合刀)。下一步 = **Step 2 · §1.4 voice ↔ character ↔ language audit**(单 stage,DB + LLM prompt + ja 链 + 前端 i18n)。

---

## Step 1 收口 · 给 PM 拍板的点

1. **§1.1 stage 1 instrumentation 提案 11 个 log 点**(7 后端 + 4 前端,统一 `# DEBUG-INV8` 标记)是否全加 / 子集 / 调整字段? → **PM ack 2026-05-22:全加 ✅**
2. **H3 几乎确定主因之一**(代码侧 +1000ms safety margin 注释明示)— 是否同意 Step 6 stage 2 真机 log 优先验证 H3? → **PM ack:优先验证 H3 ✅**
3. **决策 3 接口签名**:CC 倾向保留现 `synthesize(text, emotion) → bytes`,流式走新增方法 `synthesize_stream` per-provider 可选;brief leaning 改签名加 voice_config 参数会大破现 `_PreprocessingEngine` / `_LegacyProviderAdapter` — 哪边走? → **PM ack:按 CC 方案 ✅ brief 原签名作废**
4. **抽象插点**:A(provider factory)+ C(VoiceConfig 扩字段)联合先 ship 作 Phase 2 主体;B(流式管线)留 Phase 3 与 H3 fix 合刀 — OK? → **PM ack:A+C 联合 Phase 2 / B 留 Phase 3 ✅**
5. **cid=101 樱岛麻衣 ja row** 仍存活在 DB(与红 flag #1 表面陈述"Mai 已回退纯中文"有 tension)— Step 2 §1.4 顺手核实它的活路径(复活成本估算) → **PM ack:核实 caller 引用 + 复活成本 + 与本轮目标契合度 ✅**

---

## §1.4 voice ↔ character ↔ language 关系审计(单 stage,2026-05-22)

> Phase 2 双语 schema + voice config schema 的基础数据。摸清 9 char 各自 voice/lang 设定 / chat_history 语言现状 / LLM prompt 语言硬约束 / ja 链休眠真假 / 前端 i18n / characters.yaml 现状 / cid=101 三件事核实。

### §1.4.1 9 char voice/lang 矩阵(实测 DB momoos.db)

| cid | name | voice_model 关键字段 | tts_language | live2d_model | character_personas 完整度 | chat_history rows | character_states 状态 |
|---|---|---|---|---|---|---|---|
| 1 | Momo(借壳 Mai) | provider=cosyvoice / voice=longyumi_v3 / instruct=false | **zh** | hiyori | ✅ 完整(identity=樱岛麻衣 + aliases=[麻衣,麻衣学姐,Mai]) | **79 条**(当前活路径) | curious / mood=44 / "这家伙为了一碗粉就能开心一整天" |
| 2 | 八重神子 | model=cosyvoice-v3.5-plus / voice=bailian-a61e... / instruct=true / ssml=true | (无字段,默 zh) | yae | (未查;DESIGN_LITE 红 flag #2 说"空骨架") | 0 | curious / mood=3 |
| 3 | 荧 | model=cosyvoice-v3.5-plus / voice=bailian-ec26... / instruct=true / ssml=true | (无,默 zh) | (空) | 同上空骨架 | 0 | neutral |
| 4 | 凝光 | (空 → yaml fallback longyumi_v3) | (无,默 zh) | (空) | 空骨架 | 0 | neutral |
| 5 | 神里绫华 | model=cosyvoice-v3.5-plus / voice=bailian-7c61... / instruct=true / ssml=true | (无,默 zh) | (空) | 空骨架 | 0 | calm |
| 99 | 一般路过猫娘 | (空 → yaml fallback) | (无,默 zh) | (空) | 空骨架 | 0 | neutral |
| 100 | 祥子-test | (空 → yaml fallback) | (无,默 zh) | (空) | 空骨架 | 0 | neutral |
| **101** | **樱岛麻衣** | provider=cosyvoice / voice=bailian-a19f... / instruct=true / **tts_language=ja** | **ja** ⚠️ | hiyori | ✅ **完整**(identity=樱岛麻衣 + aliases=[]) | **0 条** | tired / "这家伙又熬夜,真是不让人省心。" |
| 102 | 流萤 | (空 → yaml fallback) | (无,默 zh) | (空) | 空骨架 | 0 | neutral |

**关键观察**:
1. **9 char 全部 character_states 表有数据**(persona engine 起步时 ensure_defaults migration 自动 seed)
2. **cid=1 + cid=101 都有完整 character_personas**(都是 "樱岛麻衣" identity;cid=1 借壳 Momo 名 + Hiyori 模型,cid=101 独立"樱岛麻衣" + Hiyori 模型)
3. **cid=2/3/5** 用 cosyvoice-v3.5-plus 自训复刻 voice(`bailian-xxx`)— voice_aliases 表已 seed 友好名(`八重神子 voice / 荧 voice / 神里绫华 voice`)
4. **cid=2/3/5 voice_model JSON 含 `ssml_supported=true`** 字段,但 §1.2 grep 实测 `ssml_supported` **仅 migration 写入,runtime 零消费者**(bugfix_3_3_1_seed_cloned_voices.py:24 注释明示"面向未来 TTS") → **死字段,Phase 2 抽象层重写时可顺手清掉**
5. **当前生产真实活路径只有 cid=1**(79 条 chat_history)— 其它 8 个 character 全是 dogfood seed,用户从未真正对话

### §1.4.2 characters.yaml 现状 + Plan B Plan C 真假

`backend/config/characters.yaml` 实读 5 条目:

| YAML 角色 | DB 对应 cid | 同步状态 |
|---|---|---|
| 八重神子 | cid=2 | ✅ 同名同 persona 描述方向(yaml persona 是简短文字 vs DB character_personas 是结构化 7 字段 Tier-1)|
| 默认 | cid=? | ⚠️ **DB 无名为"默认"的 character**(cid=1 名为"Momo");仅 yaml `default_character: 默认` 指向此 |
| 荧 | cid=3 | ✅ 同名 |
| 凝光 | cid=4 | ✅ 同名 |
| 神里绫华 | cid=5 | ✅ 同名 |

**关键发现**:
1. **yaml 5 角色 ⊊ DB 9 角色**:yaml 缺 Momo / Mai / 樱岛麻衣 / 一般路过猫娘 / 祥子-test / 流萤 6 角色(cid=1/99/100/101/102 全缺) — **yaml 是 v3 时代 5 角色的历史残留**,本身就**不是 9 char 的真源**
2. **yaml 唯一仍有真消费者的 caller**(grep 实测):
   - `backend/config/prompt_manager.py:12` import time 读 yaml(legacy 路径,DB-driven 路径已不走)
   - `backend/tools/builtin.py:20,63` switch_character builtin tool(已 retired,grep 实测 `switch_character` 退役于 commit 71b6e99,registry.py 不再注册 — per INVESTIGATION-INDEX 2026-05-19 第一刀)
   - 2 个 migration 读 yaml 抽 emotion(`v3_e2_restore_momo_persona.py` / `v4_persona_thickening_segment1.py`)— 历史一次性运行,无未来依赖
3. **Plan B**(DESIGN_LITE §8 / ROADMAP Tech Debt)"DB 主源 + YAML fallback"在 **runtime 路径已不成立**(yaml 在主聊天 / TTS / proactive 全链路无消费);**Plan B 实际为 dead code with legacy YAML import**

**Plan C(删 yaml DB 单源)成本估算**:
- 删 yaml 文件本身 0 行代码
- 改 `prompt_manager.py:12` 的 yaml import → 改 DB lookup(估 30-50 行改动)
- 改 `tools/builtin.py:20,63` 的注释(switch_character 已 retired,注释更新)
- migration 历史文件**保留**(冻结历史,不动)
- → **总成本 ~1-2h,纯整洁工作,不在本轮 INV-8 scope** — 但 §1.4 顺手记录,**Plan C 立项 backlog**

### §1.4.3 chat_history 语言现状

`SELECT character_id, COUNT(*) FROM chat_history GROUP BY character_id;` 实测:
```
1 | 79
```

- **chat_history 表全表只有 cid=1 的 79 条数据**;其它 8 个 character 全 0 条
- chat_history schema(per DESIGN_LITE §4):`role / content / kind('normal'/'touch'/'proactive') / created_at`,**无 language 列**
- content 字段单字段存原文(不拆中/日字段);若未来 Mai 走"中文显示 + 日语 TTS"路径,**chat_history 该存什么?**
  - **Option α**:存 LLM 原输出 raw(含 `<ja>日语翻译</ja>` 或 `<tts_ja>...</tts_ja>` tag)→ 占空间,但完整
  - **Option β**:存字幕中文(strip ja 后)→ 简洁,但丢日语历史(用户回看时只看中文 ok,但若未来想 replay TTS 没源数据)
  - **Option γ**:加新列 `tts_content` 存日语 → schema 改 + DBmigration,**v4.1 backlog**

**关键观察**:cid=1 当前 79 条 chat_history 都是 zh 单语(zh 路径以来);切到 ja 路径(本轮)后**新增 history rows 是混存 raw**(含 `<ja>...</ja>` tag)— 现 sanitize chain `_strip_format_tags` 5 档剥 emotion/thinking/state_update/motion/tool_call,**`<ja>` 不在剥列表**(per text_filters.py:461 `_SUSPICIOUS_TAG_WHITELIST = frozenset({"ja", "en"})` 白名单豁免)→ 默认 **Option α**(LLM raw 含 ja tag 存 chat_history)。

### §1.4.4 LLM prompt 各层语言硬约束清单

实测 `backend/agents/prompt/templates/` 5 个 Jinja2 模板 + dataclass 渲染层 grep "中文/Chinese/日语/Japanese/ja/en/language":

| 文件:行 | 内容 | 类型 | 改造影响(Phase 2 双语 schema) |
|---|---|---|---|
| `layer_a.j2:32-69` | `{% if tts_language == 'ja' %} [日语 TTS 模式...]` **完整 ja directive**(意群粒度 / `<ja>「日语」</ja>` 格式 / 中日交替规则 / 短句合并约束) | **显式语言路由** | ⭐ **核心改造点** — 决策 1 schema 设计直接改这里(`<ja>` tag → `<tts_ja>` / 或保留 `<ja>` 命名;emotion markers 集成在 ja 段内) |
| `layer_a.j2:70-83` | `{% elif tts_language == 'en' %} [英语 TTS 模式...]` 类似 ja 但更短 | 同上 | 改 ja 同时改 en(对称) |
| `layer_b.j2:23` | `你永远是角色本人,不是 AI 助手 / 语言模型` | 抗 OOC,**非语言硬约束** | 不动 |
| `layer_c_stable.j2:73` | `无论后续 context 给什么 briefing 或数据,语言风格永远遵循上述 speech_style` | 锚定 speech_style 风格,**非中/日语种约束** | 不动 |
| `layer_c_stable.j2:46+` | voice_samples 渲染段 + forbidden_phrases vendor-aware | **隐式语言约束**(Mai voice_samples 全中文,LLM 学样本风格 → 默认输出中文) | ⚠️ ja 模式下 Mai voice_samples 仍是中文(给字幕参考),日语段 LLM 靠 layer_a.j2 ja directive 指导生成 — 当前架构 OK,Phase 2 无需改 |
| `layer_d.j2` | (无任何 "中文/语言/language" hit) | 数据上下文层 | 不动 |
| `transition.j2` | (无任何 hit) | persona 切换提示 | 不动 |

**核心结论**:**LLM prompt 唯一显式语种路由是 `layer_a.j2` 的 ja/en 模板分支**(28 行 ja + 14 行 en);**universal_constraints / persona Layer C / data Layer D 无任何"必须中文" / "禁止日语"硬约束**。这意味决策 1 schema 设计实质 = **改 `layer_a.j2` 的 ja directive 内容**(命名:`<ja>` vs `<display_zh>/<tts_ja>`;emotion markers 集成方式;意群粒度)— **改造面极小**,prompt token cost 几乎不变(纯 string 替换)。

### §1.4.5 ja 链"保留休眠"现状 + 复活成本

DESIGN_LITE 红 flag #1 称"ja 链代码保留休眠,Mai 已回退纯中文"。实测 grep "ja 链"代码 active 度:

| 文件:行 | 状态 | 备注 |
|---|---|---|
| `layer_a.j2:32-69` ja directive | ✅ active(Jinja2 模板) | 仅 `tts_language='ja'` 时触发 |
| `backend/utils/text_filters.py:298-336 extract_tts_text` | ✅ active(主 caller path) | `ws.py:959` + `proactive/engine.py:522,897` 实测调用 |
| `backend/utils/text_filters.py:341-353 strip_ja_en_tags_for_subtitle` | ✅ active(字幕路径) | `ws.py:935` 实测调用 |
| `backend/utils/text_filters.py:461 _SUSPICIOUS_TAG_WHITELIST = {"ja","en"}` | ✅ active(sanitize 白名单) | 防 `<ja>` 被 SUSPICIOUS_TAG_RE 误剥 |
| `backend/agents/sentence_merge.py merge_short_sentences` | ✅ active(ja/en wrap) | `ws.py:815-817` + `proactive/engine.py:453,861` 实测 wrap |
| `backend/agents/chat.py:344-349 _BOUNDARY_PAIRED_TAGS` | ✅ active(含 "ja","en") | sentence boundary state machine 跳过 `<ja>` 内部句末标点 |
| `backend/tts/__init__.py:71-72 _JA_EN_LITERAL_RE` | ✅ active(_tts_input_final_guard) | bugfix-D1.1 兜底 |
| `backend/database/migrations/v4_persona_segment2_mai_ja.py` | ✅ shipped migration | 历史一次性,按 voice_id 标 ja(cid=1 + cid=101) |
| `backend/database/migrations/v4_0_0_mai_revert_zh.py` | ✅ shipped migration | 仅 cid=1 回退 zh,**cid=101 不动** |

**真实状态**:ja 链**不是"休眠"是"待机"** — 所有代码 active,只是当前生产路径全是 cid=1 zh 路径触发不到 ja 分支。**任何 character 设 `tts_language='ja'` 即激活完整 ja 链**(无需复活,纯 config flag)。

**复活成本 = 零代码改动 + 1 个 DB 操作**:
- ❌ 不需要改任何代码
- ✅ 只需要 voice_model JSON 加 `tts_language='ja'`(单字段 flag)
- ✅ voice_model.voice 切到日语复刻 voice(如 cid=101 已有的 `bailian-a19f...`,或新切 Fish provider zero-shot)

DESIGN_LITE "ja 链保留休眠"的真实意思是**当前没有 character 走 ja 路径**(因为 cid=1 Mai 已回退 zh),但**整条 ja 处理 pipeline 活在 tree 里随时可用**。

### §1.4.6 前端 i18n 现状 + 双语显示改造预估

实测 frontend grep:
- ❌ **无 `react-i18next` / `useTranslation` / `i18n.t` / `FormattedMessage` hooks**(`grep -rn ... frontend/src/` 零命中)
- ✅ `SettingsPanelLegacy.tsx:1339-1440` 有 user `language` profile(zh-CN / 等)— **但这是 USER PROFILE 字段**(给 LLM 知道用户偏好,不是 UI 切语言)
- ✅ `CharacterPanel.tsx:1397-1415` 有 `<select>` TTS 语言切换(zh/ja/en)— 这是 **voice_model JSON 编辑器**,改 `tts_language` 字段(per character)
- ✅ `frontend/src/lib/tts.ts:50,81-113` `VoiceModelJson` 接口含 `tts_language?: 'zh' | 'ja' | 'en'` + `parseVoiceModelJson` / `buildVoiceModelJson` helpers

**全 UI 文案中文硬编码**(`grep -rn "中文" frontend/src/components/` 多处实测中文 label / button text)。

**"中文显示 + 日语 TTS" 前端改造预估**:
- ✅ **chat panel 文字渲染**:已是字幕路径(`ws.py:935 strip_ja_en_tags_for_subtitle` 后 text_chunk push)— **零改动**;现路径已"中文字幕 + 日语 TTS"形态
- ✅ **audio chunk 播放**:已是 WAV bytes(provider-agnostic)— Phase 2 切 Fish provider 不影响前端(audio_chunk schema 不变)
- ⚠️ **CharacterPanel 切 fish provider**:`buildVoiceModelJson` 需扩支持 `provider: 'fish'` + 新字段(reference_audio_path / reference_text 等);UI 加 Fish provider 下拉选项 + Fish voice 选择器(Phase 2 工程量 ~0.5d 前端)
- ⚠️ **CharacterPanel TTS 语言切换**:现已支持 zh/ja/en 三选(zh 是默认);**零改动**
- ⚠️ **subtitle 渲染中文 ✓ done**;若未来加日语字幕 alt(给学日语用户)— 需 chat panel 加 dual-rendering toggle,**v4.1+ backlog**

**前端改造总量 ≈ 0.5d**(只 CharacterPanel 切 Fish provider 字段);chat / audio 主路径**零改动**。

### §1.4.7 cid=101 三件事核实(PM 补一条要求)

#### 1. 有没有任何 caller 引用 cid=101

实测 grep `character_id.*101` / `cid.*101` / `'101'` / `"101"`:

| 文件:行 | 引用类型 | 影响 |
|---|---|---|
| `backend/main.py:363` | 注释("当前 id=1 Momo/Mai 借壳 + id=101 樱岛麻衣") | 无 runtime 影响 |
| `backend/database/migrations/v4_persona_segment2_mai_ja.py:10` | 注释 docstring | 历史 migration,无 runtime |
| `backend/database/migrations/v4_0_0_mai_revert_zh.py:31` | 注释("cid=101 仍持 ja voice") | 历史 migration,无 runtime |
| `backend/tools/registry.py:96` | switch_character builtin 退役 silent failure list 注释 | switch_character 已 retired 无 runtime |
| **frontend/src/** | **零命中** | 前端无硬编码 cid=101 |

**结论**:**cid=101 零 runtime caller 硬编码**;通过 ws frame `character_switch` + `prompt_manager.set_current(user_id, cid)` 切换;前端 CharacterPanel 列出全部 characters table 行,用户自行切。

#### 2. 复活成本

| 项 | 改动 |
|---|---|
| DB schema | **零改动**(characters / character_personas / character_states 三表 cid=101 row 全存活) |
| voice_model JSON | 已有 `{"provider":"cosyvoice","voice":"bailian-a19f...","instruct_supported":true,"tts_language":"ja"}` — Phase 2 切 Fish 时仅需 voice_model JSON 加 `provider: 'fish'` + Fish 字段,或保留 cosyvoice 作 fallback |
| chat_history | 0 条新切角色清白起步;若用户希望延续 cid=1 关系 → 需要拆 cid=101 重用 cid=1 conversations 的方案(**新需求,不在本轮 scope**) |
| character_personas | 已有完整 identity=樱岛麻衣 / variant=default / is_active=1 — 零改动 |
| character_states | 已有 tired / "这家伙又熬夜..." — 零改动(也可由 PM 选 reset 一份新状态) |
| 前端 | 用户在 CharacterPanel 点击 cid=101 切角色,或后端用 default character lookup 改指向 cid=101(`backend/main.py` restore character logic) |

**总成本 ≈ 0 代码改 + 1 个 UI 切换动作(用户 click cid=101 列表项)**。

#### 3. 跟本轮目标(Mai 中文显示 + 日语 TTS)是否天然契合

✅ **天然契合度 = 极高**:
- cid=101 已是"樱岛麻衣"独立 character,`tts_language='ja'`(Mai voice)+ persona 完整
- **复用 cid=101 = 省一次重建**(无需再 migration 给 cid=1 切回 ja)
- 自然演化路径:cid=1(Momo 借壳)是 dogfood 阶段产物;cid=101(樱岛麻衣本体)是**目标态**
- Phase 2 集成 Fish 时,直接改 cid=101 voice_model.provider='fish' + 加 Fish 字段(reference_audio_path 等)

**潜在 trade-off**:
- ⚠️ cid=101 chat_history 空白,**用户感知"重新开始"**(失去 cid=1 79 条历史中的关系积累);**Mai persona / mood / intimacy 状态独立**(cid=1 cur intimacy=44 vs cid=101 intimacy=0)
- 缓解方案 A:复用 cid=1 但改 tts_language=ja(简单 1 行 DB UPDATE,但 Mai "改名"心理感不连续)
- 缓解方案 B:数据迁移 cid=1 → cid=101(转移 chat_history + character_states + memory + conversations,~30-50 行 migration script,**Phase 2 收口后单独刀**)
- 缓解方案 C:cid=1 + cid=101 并存,UI 提供"切到日语 Mai" 让用户主动(无迁移成本,关系数据**分裂**)

**CC leaning**:**方案 B**(数据迁移)Phase 2 收尾刀做,Phase 3 ship Fish 时用户感知是"Mai 升级日语",而非"切到新角色";方案 A 临时 ok 但 character.name="Momo" 名字会困扰用户。**PM 拍板**。

### §1.4.8 PM 决策 leaning 状态(本节产出)

| 决策 | leaning(brief 给) | 三档结论 | 备注 |
|---|---|---|---|
| 1 · LLM 双语 schema | `<display_zh>中文</display_zh><tts_ja>日语</tts_ja>` 顺序流式 | ✅ **几乎站得住**(详 §1.5)| 现 `layer_a.j2` ja directive 已用 `<ja>「日语」</ja>` 形态(等价语义),决策 1 schema **几乎已 deployed in-tree**;命名 `<ja>` vs `<tts_ja>` / `<display_zh>` 是 trade-off 议题(详 §1.5 4 路 Option 对比)|

§1.4 主要为 §1.5 提供基础数据;其它决策(2/3/4/5)在 §1.5 / §1.3 落 verdict。

### §1.4.9 收口

- ✅ 9 char voice/lang 矩阵(实测 DB,4 表 join:characters / character_personas / character_states / voice_aliases)
- ✅ characters.yaml 现状:5 角色 ⊊ DB 9 角色,Plan B "DB 主源 + YAML fallback" 在 runtime 实质为 dead code with legacy import;Plan C 删 yaml ~1-2h backlog
- ✅ chat_history:全表 79 条 cid=1 / 其它全 0 条;现 schema 无 language 列,**Option α**(LLM raw 含 ja tag 存)默认走通,sanitize 白名单豁免 ja/en
- ✅ LLM prompt 4 模板 + persona Layer 实测:**唯一显式语种路由 = `layer_a.j2:32-83` ja/en 分支** ~42 行 Jinja directive,其它层无硬约束 → 决策 1 schema 改动面**极小**
- ✅ **ja 链状态修正:不是"休眠"是"待机"** — 整条 ja pipeline active in tree,任何 character 设 tts_language='ja' 即激活;复活成本 = **零代码** + 1 字段 DB flip
- ✅ 前端:零 i18n hooks(UI 文案中文硬编码);CharacterPanel 已有 tts_language zh/ja/en 切换 UI;chat / audio 主路径**零改动**支持本轮目标;Fish provider 切换需 CharacterPanel 加字段,~0.5d 前端
- ✅ **cid=101 三件事**:
  - caller 引用:零 runtime 硬编码(仅 4 处注释提及)
  - 复活成本:零代码改 + 1 UI 切换
  - 与本轮目标契合度:**极高**(cid=101 = 樱岛麻衣本体 + tts_language=ja + 复刻日语 voice 已就位)
  - **3 缓解方案**(A 改 cid=1 / B 迁移 cid=1→cid=101 / C 并存)— CC leaning B,PM 拍板
- ✅ ssml_supported 字段:cid=2/3/5 voice_model JSON 有此字段但 runtime 零消费者 → **死字段**,Phase 2 抽象层重写时顺手清掉(立项)

### §1.4.10 lesson(沉淀)

#### Lesson INV-8 #1 · DESIGN_LITE 红 flag #1 描述偏差("休眠" vs "待机")

DESIGN_LITE §0 红 flag #1 说"ja 链代码保留休眠",实测 grep ja 链所有 8 个 hot files(layer_a.j2 / text_filters.py / sentence_merge.py / chat.py / __init__.py / proactive/engine.py / ws.py / migration)**全部 active in tree**;"休眠"的实际语义是"当前活路径无 character 走 ja 分支"(因 cid=1 已回退 zh),但**ja pipeline 任何 character flip 一个字段就激活**。

**抽象**:DESIGN_LITE 文档"休眠"措辞容易让接手 Claude 误以为代码可能 broken / 需要"复活成本"高;实际是 **config-driven dormancy**(零代码改激活)。**未来类似"待机但 active"的 pipeline 描述时,DESIGN_LITE 应明示"待机(配置切换即激活)"vs"休眠(代码需重新打通)"**。**docs 增量,backlog**。

→ **Step 2 §1.4 完成**(本节估 ~265 行)。下一步 = **Step 3 · §1.3 stage 1 Fish API 纯 docs 调研**(PM 已预提供 5 条核心信息,scope 由 s2-pro lock 收紧)。

## §1.3 Fish API + s2-pro zero-shot 调研(Stage 1 纯 docs 调研,2026-05-22)

> Phase 2 Fish provider 实现的 spec 基础。Stage 1 走纯 docs 调研(docs.fish.audio 实 fetch);Stage 2 待素材到位实打 API。
> **PM lock 2026-05-22**:本轮只用 **s2-pro**,s1 / v1.6 不调研;抽象层保留 `model` 字段默认 `s2-pro`。
> **PM 预披露 5 条**(已存档):key + balance ready / `$15/1M UTF-8 bytes` pay-as-you-go / s2-pro 支持 emotion / endpoint `https://api.fish.audio/v1/tts` / Bearer auth / SDK `fish-audio-sdk`。

### §1.3.1 API spec 摘要(s2-pro)

| 项 | 值 | 来源 |
|---|---|---|
| Endpoint | `POST https://api.fish.audio/v1/tts` | docs |
| Content-Type | `application/msgpack`(主)/ `application/json`(quickstart 示例兼容) | core-features TTS docs |
| Auth | `Authorization: Bearer $FISH_API_KEY` HTTP header | docs |
| Model 选择 | `model: s2-pro` HTTP header(**不**进 body) | core-features TTS docs |
| **WebSocket** | **`wss://api.fish.audio/v1/tts/live`**(主推流式路径) | websocket-tts-live docs |
| Languages | 80+(s2-pro;日语在内) | models-overview |
| TTFA(time-to-first-audio) | **100 ms**(s2-pro spec'd) | models-overview |
| Multi-speaker dialogue | s2-pro exclusive(本轮单角色不用) | models-overview |

#### Request body 字段(HTTP path)

| 字段 | 类型 | 说明 |
|---|---|---|
| `text` | string (req) | 合成内容 |
| `reference_id` | string | 预上传 voice model ID(本轮**不用**,走 references[] inline 路径) |
| `references` | array | **zero-shot inline 路径**:`[{audio: bytes, text: string}, ...]` |
| `format` | string | `mp3` / `wav` / `pcm` / `opus`(默 mp3) |
| `sample_rate` | int | 默 44100Hz(wav/mp3/pcm) / 48000Hz(opus) |
| `mp3_bitrate` | int | 64 / 128 / 192(默 128) |
| `chunk_length` | int | 100-300 chars 默 200(text 内部分段) |
| `latency` | string | `low` / `normal` / `balanced`(balanced ~300ms latency) |
| `prosody` | object | `{speed: 0.5-2.0, volume: -20~+20dB, normalize_loudness: bool}` |
| `normalize` | bool | 文本标准化默 true |
| `temperature` | float | 0.0-1.0 默 0.7(声学采样) |
| `top_p` | float | 0.0-1.0 默 0.7 |

### §1.3.2 zero-shot 必传字段(references[] inline 路径)

走 references[] inline 路径(per PM 决策 2:每次传 reference_audio + reference_text;不用 reference_id 预上传)。

| 字段 | 约束 |
|---|---|
| `references[].audio` | bytes(文件 read 'rb' 模式);`.wav` 是 docs 主示例;**采样率 / 时长上限 / mp3 是否支持** = docs 未明示,**stage 2 必验** |
| `references[].text` | string(reference audio 的 transcript) |
| 多 sample | 数组可多条提高质量;best practice:10s+ studio quality,或 2-3 clips × 15-20s |
| 语种匹配 | docs **未明示**(日语 reference 能否产生其它语言 / Mai 日语 reference 在 LLM 输出含 emotion markers 的日语 target 上表现) — **stage 2 关键验证项** |
| `enhance_audio_quality` | bool(仅 create_model 路径,instant cloning **不支持**) |

**Python SDK 形态**:

```python
from fishaudio import FishAudio
from fishaudio.types import ReferenceAudio, TTSConfig

client = FishAudio(api_key="...")
with open("mai_reference.wav", "rb") as f:
    audio = client.tts.convert(
        text="<日语 target>",
        config=TTSConfig(
            references=[ReferenceAudio(audio=f.read(), text="<reference transcript>")],
            format="wav",
            latency="balanced",
        ),
    )
```

### §1.3.3 流式支持现状

| 路径 | 支持 | 备注 |
|---|---|---|
| HTTP 单次 | ✅ | `client.tts.convert(...) → bytes`(complete audio binary) |
| **HTTP streaming** | ✅ | `client.tts.stream(...) → AudioStream iterator`(chunk-by-chunk) |
| **WebSocket streaming** | ✅ ⭐ | `client.tts.stream_websocket(text_chunks_iter) → audio bytes iterator`(主推 real-time)|
| MsgPack 协议 | ✅ | WebSocket payload 全 MsgPack;SDK 自动处理 |

**WebSocket 消息流**(`wss://api.fish.audio/v1/tts/live`):
- Client → Server:`StartEvent`(配置 + 可含初始 text)→ N×`TextEvent`(text chunk 流入)→ 可选 `FlushEvent`(强制立即合成 buffer)→ `CloseEvent("stop")`(收尾)
- Server → Client:N×`AudioEvent`(audio chunk,可在 text 还在送时陆续到达)→ `FinishEvent(reason="stop"|"error")`(连接随即关闭)

**关键观察 — 跟 Phase 3 流式管线 + H3 fix 强契合**:Fish WebSocket 是**真正的双向流式 + 100ms TTFA + low/balanced latency 档**;CosyVoice 当前 `synthesizer.call(text)` 是阻塞 SDK 一次完整 WAV 返回,链路 RT 是大头(§1.1 H2)。**切 Fish 流式后 H2 自然消失**;H3(前端 +1000ms gap)仍需 fix 但相比 H2 + H3 复合,**整体感知停顿显著降低**。

`stream_websocket` 文档示例:

```python
def text_chunks():
    yield "Hello, "
    yield "this is "
    yield "streaming!"

audio_stream = client.tts.stream_websocket(text_chunks())  # bytes iterator
play(audio_stream)
```

**FlushEvent** 可强制立即 synthesis,适合做 sentence-boundary flush(LLM yield sentence n 时 push 一个 FlushEvent → Fish 立即生成该句 audio;不等下句)。

### §1.3.4 s2-pro Emotion markers 实例表

**关键校正(对比 S1)**:

| 维度 | S1 | **s2-pro** |
|---|---|---|
| 语法 | `(parenthesis)` | **`[bracket]` 自然语言** |
| Tag 集 | 固定 49 emotion + 5 tone + 10 audio effects ≈ 64 tags | **不限固定集**(docs claim "15,000+ tags") |
| Placement | "MUST go at the beginning of sentences"(强约束) | **mid-sentence 允许**(docs 示例:`"I can't believe it [gasp] you actually did it [laugh]"`) |
| 多 marker 组合 | 最多 3 个,堆叠 `(sad)(whispering)` | docs **未明示**(stage 2 待实测) |
| Scope | "One tag affects the following sentence until the next tag appears" | docs **未明示**(stage 2 待实测) |
| Japanese 示例 | docs 列日语在 13 支持语言但**无 Japanese-specific emotion 示例** | docs **零 Japanese 示例**(stage 2 关键验证) |

**S1 验证 emotion tags 集合**(作 s2-pro 自然语言 markers 候选词参考,不是强约束):

- **24 basic emotion**:happy / sad / angry / excited / calm / nervous / confident / surprised / satisfied / delighted / scared / worried / upset / frustrated / depressed / empathetic / embarrassed / disgusted / moved / proud / relaxed / grateful / curious / sarcastic
- **25 advanced emotion**:disdainful / unhappy / anxious / hysterical / indifferent / uncertain / doubtful / confused / disappointed / regretful / guilty / ashamed / jealous / envious / hopeful / optimistic / pessimistic / nostalgic / lonely / bored / contemptuous / sympathetic / compassionate / determined / resigned
- **5 tone markers**:hurried / shouting / screaming / whispering / soft
- **10 audio effects**:laughing / chuckling / sobbing / gasp / sigh / 等

**s2-pro 自然语言 tag examples**(docs 示例):`[whispers sweetly]` / `[laughing nervously]` / `[gasp]` / `[laugh]`。

**Mai persona 契合度**(初判):
- Mai 风格 = 冷静温柔 + 偶尔讥讽 + 反差暖意 → 候选 markers:`[sarcastic]` / `[gentle]` / `[teasing]` / `[soft tone]` / `[soft chuckle]`
- 中文 markers 是否 work docs 未明示(只 English example) → 全文用英文 markers 安全(s2-pro 自然语言模式应可 cross-lingual)

### §1.3.5 错误码 + 重试 handling

⚠️ **docs 缺口大** — introduction / TTS API reference 子页 404;OpenAPI schema 在 `https://api.fish.audio/openapi.json` 待 stage 2 实 fetch。

已知:
- 429 rate limit 由 tier 决定(starter <$100 = 5 concurrent)
- WebSocket 连接错误走 `FinishEvent(reason="error")` 然后 close
- 完整 status code 列表 / 错误 JSON schema / idempotency key / request ID = **docs 未明示**

**stage 2 实测计划**:
- 触发 400(invalid request)/ 401(bad key)/ 429(concurrent burst)看 JSON schema
- 触发 timeout / network error 观察 SDK behavior
- 验证幂等性(重发同 references[] + text 是否完全一致 audio)
- fetch openapi.json 抽 complete spec

**重试策略 leaning**(待 stage 2 验证):
- 5xx → exponential backoff 重试 2-3 次
- 429 → 等 N 秒后重试(N 视 tier;starter 5 concurrent 应少触发)
- 4xx(非 429)→ 不重试(请求本身错)
- WebSocket close → 单 turn 内不重连(避免双语音 confusing user),fallback CosyVoice

### §1.3.6 Pricing / quota 机制(决策 5 leaning 重大校正)

**实测真相**:

| 项 | 值 |
|---|---|
| s2-pro 价 | **$15.00 / 1M UTF-8 bytes** ≈ $0.0000833/byte ≈ $2.69 / 1M English chars |
| 等价折算 | 1M bytes ≈ 180k English words ≈ 12 hrs 语音 |
| **日语 UTF-8 char 平均 ~3 bytes** | 日语 1 char ≈ $0.00025;**Mai 日语 100 字回复 ≈ $0.025**(中文同样 1 char ≈ 3 bytes) |
| 订阅 | **无订阅 / pay-as-you-go** |
| 免费档 | **无 free tier** |
| Voice cloning | **不分别计费**,用标准 TTS rate |
| Balance check API | **不提供**(只能 dashboard 查) |
| 月配额 | **无月配额**(PM brief 假设 "200 min/月" 与 Plus 网页订阅有关,**与 API 完全解耦**) |
| Rate limits(by cumulative spend tier) | Starter <$100: 5 concurrent / Elevated ≥$100: 15 / High Volume ≥$1k: 50 / Enterprise: custom |

**决策 5 leaning 重大校正**(brief 原 leaning vs 真实可行性):

| brief 原 leaning | 真实可行性 | 校正后 |
|---|---|---|
| "实时累计本月 audio 输出时长,90% 警告,100% 强制切" | ❌ Fish **无月配额** + **无 balance API** | 改:本地累计 char × language → bytes × cost rate → 估 cost;per-user daily/monthly cost cap 由用户 Settings 设 |
| "跨月 reset" | ❌ 无概念(pay-as-you-go) | 改:cap reset 由用户充值 / 用户自配 daily/monthly char cap reset rule |
| "Fish 失败 / 耗尽 → CosyVoice + toast" | ✅ 失败 fallback 真实可行 | 触达 user-set cap **或** API 失败(429 / 5xx / WS close)→ CosyVoice + toast |

**重写决策 5**(CC leaning,PM 拍板):
- ✅ 后端 `tts_call_log` 已有 `input_chars` 列(per §1.2);加 `cost_estimate` 列已存(per `tts_log.py` `estimate_cost`)+ 加 `provider` 列 区分 fish/cosyvoice
- ✅ 加 `byte_count` 列:`len(text.encode('utf-8'))`(精确计费基础)
- ✅ Settings 加 per-user `fish_daily_cost_cap_usd` / `fish_monthly_cost_cap_usd` 字段(默 nil = 不限);存 `users.profile_data` JSON 或新建 `user_settings` 表
- ✅ Phase 3 Fish 调用前查 daily/monthly 累计 cost → 触达 cap → fallback CosyVoice + toast
- ✅ 任何 Fish API 失败 → 单 turn 内 fallback CosyVoice + toast(不重试本句)
- ⚠️ Concurrent rate limit(starter 5)由 `_tts_semaphore` 控制(当前 3,Phase 2 可改 5 给 Fish)

### §1.3.7 跟 §1.5 联合接口(Fish emotion + LLM 输出 schema)

**核心问题**:LLM 在 `<tts_ja>` / `<ja>` 段里输出**纯日语**还是**含 [marker] 的日语**?

候选 schema(只列形式,详对比 §1.5.6):

| Schema | LLM 输出形态 | Fish 处理 |
|---|---|---|
| α · 纯日语 | `<ja>「うん、行きなさい。」</ja>` | Fish 调用 text=「うん、行きなさい。」 emotion 走 turn-level(用 CosyVoice 同样 emotion 通道,Fish s2-pro 默 neutral) |
| β · inline marker | `<ja>[sarcastic]「ま、いいか。」[soft chuckle]「冗談だよ。」</ja>` | Fish 调用 text 含 `[bracket]` markers,s2-pro 原生支持 |
| γ · sentence-level marker | `<ja emotion="sarcastic">「ま、いいか。」</ja>` | tag attribute 进 LLM prompt schema;backend 翻译成 `[sarcastic]` 前缀拼进 Fish text |

**CC leaning(待 §1.5 联合 / PM 拍板)**:**β · inline marker** 最自然
- 优点:s2-pro 原生设计意图;mid-sentence placement 支持;LLM 学 prompt examples 直接产含 marker 的日语
- 缺点:LLM prompt addendum 需教 Mai 在 `<ja>` 段写 `[marker]` 句法,失败时(LLM 漏 marker)体感无情感差异 — 容忍度高
- 跟 CosyVoice 路兼容性:CosyVoice 不识 `[marker]`,**fallback 时需 strip `[bracket]`**(provider-aware sanitize),per-provider addendum 决定 LLM 输出形态

**Phase 2 实现要点**:
- 新增 `_FISH_EMOTION_MARKER_RE = re.compile(r"\[[^\]]+\]")` 用于:
  - CosyVoice 路径 sanitize 剥 `[marker]`(provider-aware)
  - sanitize 链白名单豁免(类比 `_SUSPICIOUS_TAG_WHITELIST`)
- Layer A1 ja directive 按 voice_model.provider 分支(`{% if voice_model.provider == 'fish' %}` 教 markers / else 不教)

#### ⭐ Hard Requirement(PM lock 2026-05-22)· Per-provider 双重隔离

Fish `[bracket]` markers 只在 fish 模式出现在 LLM 输出。其它 provider(CosyVoice / Edge / 未来扩展)保持各自原有 emotion 通道,不被 Fish 设计裹挟。

**生成端(per-provider prompt)**:LLM 是否输出 `[bracket]` markers 取决于 `voice_model.provider`:
- Fish 模式 → Layer A1 教 markers(`{% if voice_model.provider == 'fish' %}` 分支注入 marker 引导文 + Mai 风格候选 markers 示例)
- 其它模式(CosyVoice / Edge / future)→ 不教(不在 prompt 提 `[bracket]` 概念)

**接收端(per-provider sanitize)**:non-Fish provider 接到 LLM 输出时自动 strip `[bracket]`:
- `_FISH_EMOTION_MARKER_RE = re.compile(r"\[[^\]]+\]")` 在 CosyVoice 路径 `_PreprocessingEngine.synthesize` 内或 `_build_engine` 包装时强制剥除
- Edge / SoVITS / 未来 provider 同样剥(default 行为)
- 仅 Fish provider 的 synth path **保留** `[bracket]` 透传给 SDK

**保证语义**:
1. 切角色 / 切 provider 后 LLM 输出立即跟着调整(下一轮 turn 起手 prompt 重渲染),不混
2. Fish 失败 fallback CosyVoice 当 turn 内**已含 markers 的 text** → CosyVoice 收到 stripped 版,不被 `[bracket]` 噎到
3. Phase 2 抽象层(VoiceConfig + factory)按这个隔离设计,**§1.5 design space 评估每个 Option 都把这条作为 hard requirement**

### §1.3.8 PM 决策 leaning 状态(本节产出)

| 决策 | leaning(brief 给) | 三档结论 | 备注 |
|---|---|---|---|
| 2 · Fish 官方 API + s2-pro zero-shot | references[] inline 每次传 audio+text | ✅ **站得住** | references[] inline 路径 docs 实证;每次传 ~100KB-1MB reference_audio bytes(影响 stage 2 实测 cost);未来可换 reference_id 预上传减带宽,留 v4.1+ |
| 4 · Fish 句内 emotion markers | LLM 输出带 markers + CosyVoice 走 SSML wrap | ⚠️ **需调整**(详 §1.3.7 + §1.5 联合) | s2-pro 是**自然语言 `[bracket]` 不限固定集**,不是 brief 假设的 SSML(SSML 是 CosyVoice instruct 路径形态,Fish 不用);LLM 输出 schema **β inline `[marker]`** CC leaning;**CosyVoice 路 fallback 时 strip `[bracket]`**(per-provider addendum + sanitize) |
| 5 · fallback + quota | 实时累计 200min 切回 + 跨月 reset | 🔁 **发现更优新选项** | Fish **无月配额**(pay-as-you-go,$15/1M UTF-8 bytes);**无 balance API**;改:本地 char×language→bytes→cost 估算 + per-user daily/monthly cost cap + 触达 cap 或 API 失败 fallback CosyVoice + toast(详 §1.3.6 重写) |

### §1.3.9 Stage 2 实打验证清单(待 §1.3 stage 2 / Step 5 跑)

PM 给 Fish API key + Mai reference_audio + reference_text 后:

1. ✅ **基础 zero-shot synth**:单句日语 "「こんにちは,お元気ですか。」" + Mai reference,看 audio 自然度
2. ✅ **emotion markers 验证**:
   - `[sarcastic]「ま、いいか。」` 单 marker
   - `[soft chuckle]「うん、まあね。」[gentle]「気にしないで。」` 多 marker 跨句
   - `「[sarcastic]やれやれ[/sarcastic]、君もか。」` 测嵌套语法是否支持(predict: no,但实测确认)
   - `「ね、ねえ[whisper]ちょっと聞いて。」` 测 mid-sentence
   - 跟 cross-lang test:`[teasing]「ま、いい子だね。」` Mai 中文 reference 能否带 Japanese + English emotion 描述
3. ✅ **流式 vs 非流式**:
   - `stream_websocket` 实测 chunk-by-chunk 到达节奏(对比 H2/H3 baseline)
   - `convert` 非流式 latency vs CosyVoice baseline
4. ✅ **错误码触发**:
   - 故意传错 reference_audio(zero bytes)看 4xx schema
   - bad API key 看 401 schema
   - text 超长(若有限制)看 schema
   - fetch `https://api.fish.audio/openapi.json` 完整 spec
5. ✅ **cost 实测**:
   - 100 字日语 single call,观察实际 bytes 计费 vs `len(text.encode('utf-8'))` 估算
6. ✅ **references[] audio 格式约束**:wav vs mp3 / sample rate / 时长上限 / 多 sample 是否真提质量

### §1.3.10 Stage 2 实打验证(2026-05-22)

Probe 脚本:`scripts/fish_probe_T1_T6.py`(13 test calls,~6 sec wall-clock 总耗时);output WAV → `scripts/fish_probe_outputs/`;summary → `scripts/fish_probe_outputs/summary.json`(审完拔脚本 + outputs)。

#### §1.3.10.1 SDK 接口实测确认

`fish-audio-sdk 1.3.0`(`pip install fish-audio-sdk` per PM 给的指令);import 名 = `fish_audio_sdk`(**不是** docs 写的 `fishaudio`);核心类:

```python
from fish_audio_sdk import Session, TTSRequest, ReferenceAudio, HttpCodeErr

s = Session(api_key)                                          # Session(apikey, *, base_url='https://api.fish.audio')
req = TTSRequest(text=..., references=[ReferenceAudio(audio=bytes, text=str)],
                 format="wav", latency="normal", ...)
for chunk in s.tts(req, backend="s2-pro"):                    # Generator[bytes] — 默认流式
    audio_out += chunk

s.get_api_credit()  → APICreditEntity(credit: Decimal)        # ⭐ balance check API 存在
s.get_package()     → PackageEntity(type, total, balance, finished_at)  # ⭐ Plus 配额 API 也存在
```

**§1.3.6 校正**:docs 说"无 balance API"是错的 — `get_api_credit()` + `get_package()` 双 API 都存在并 work,决策 5 quota 设计可以用真实 API 实时查 balance 而非纯本地估算。

#### §1.3.10.2 12 个 test call 结果汇总

| Test | text | bytes | TTFA ms | total ms | audio out KB | audio dur (44.1kHz mono) | status |
|---|---|---|---|---|---|---|---|
| T1 zero-shot 基础 | こんにちは、お元気ですか? | 37 | 2858 | 2974 | 192 | 2.23 sec | ✅ |
| T2.1 单 marker | `[sarcastic]ま、いいか。` | 29 | 981 | 1069 | 112 | 1.30 sec | ✅ |
| T2.2 多 marker 跨句 | `[soft chuckle]うん、まあね。[gentle]気にしないで。` | 64 | 1470 | 1586 | 216 | 2.51 sec | ✅ |
| T2.3 嵌套闭合 form | `[sarcastic]やれやれ[/sarcastic]、君もか。` | 50 | 1450 | 1563 | 220 | 2.56 sec | ✅ 不报错(text 字面接受;语义是否真识闭合待 PM 听 audio) |
| T2.4 mid-sentence | `ね、ねえ[whisper]ちょっと聞いて。` | 45 | 1408 | 1522 | 236 | 2.74 sec | ✅ mid-sentence 接受 |
| T2.5 Mai persona-ish | `[teasing]ま、いい子だね。[soft chuckle]` | 47 | 1303 | 1420 | 192 | 2.23 sec | ✅ |
| T3.1 latency=normal | 今日は天気がいいですね。少し散歩でもしようかな。 | 72 | **2296** | 2437 | 360 | 4.18 sec | ✅ |
| T3.2 latency=balanced | (同 T3.1) | 72 | **593** | 2540 | 364 | 4.23 sec | ⭐ **balanced 4× faster TTFA** |
| T4.1 bad ref(zero bytes) | テスト。 | 12 | n/a | 162 | 0 | — | ❌ **HTTP 400** |
| T4.2 bad API key | テスト。 | 12 | n/a | 602 | 0 | — | ❌ **HTTP 401** |
| **T4.3 NO reference** | テスト。 | 12 | 487 | 539 | 48 | 0.56 sec | ⭐ **成功!** Fish 有内建 default voice,zero-shot **可选** |
| T5 cost 实测 100 ja | (61 char / 181 bytes) | 181 | 4478 | 4650 | 868 | 10.08 sec | ✅ |
| T6 multi-ref(同 ref×2) | あなたはこの話、信じる? | 34 | 1440 | 1549 | 200 | 2.32 sec | ✅ |

**总 wall-clock**:13 calls 跑完 ~22 sec(含序列等待)。

#### §1.3.10.3 关键发现(改写 stage 1 假设)

##### Finding #1 · `references[]` 不是 zero-shot **必需**(T4.3)

⭐ **重大校正**:T4.3 完全不传 references + 不传 reference_id → **成功合成 + 返回正常 WAV**(0.56 sec audio)。Fish s2-pro 有**内建 default voice**;references[] 是 voice **cloning** 路径(选项),非生成必需。

**Phase 2 设计影响**:VoiceConfig.fish 字段层级可以分:
- mode_A · 含 references[](Mai 复刻路径,本轮主路径)
- mode_B · 不含 references[](Fish 默认 voice,适合"主聊天 zh + 偶尔 ja TTS 但用户没特定声音偏好" 兜底)
- 不需要 references[] 时直接省 ~1.2MB 上行带宽

##### Finding #2 · TTFA & latency mode 实测(对 Phase 3 决定性)

| latency | TTFA | total | 含义 |
|---|---|---|---|
| `normal`(T3.1) | **2296 ms** | 2437 ms | 几乎一次返完;TTFA ≈ total(non-streaming-感) |
| `balanced`(T3.2) | **593 ms** | 2540 ms | **TTFA 真做到 ~600ms**;total 相似(audio dur 不变) |
| `low` | (未测) | (未测) | docs 说更激进低延迟,stage 2+ 验证 |

**对比 CosyVoice baseline**(per §1.1 H2 推断):CosyVoice `synthesizer.call(text)` 阻塞 SDK 一次返完整 WAV,日语 100 字典型 SDK RT ~1-2s 完整 — Fish `balanced` mode TTFA ~600ms **快 ~3x**(且后续 audio 边出边收)。

**Phase 3 流式管线设计 lock**:Fish 走 **`latency=balanced` + WebSocket streaming**(`stream_websocket` SDK 路径,详 §1.3.3),TTFA 600ms + 实时流式 audio chunks → **H2(链路 RT)+ H3 部分(首段感知延迟)双重消除**;剩下只剩 H3 buffer 切段 gap(前端 +1000ms safety margin),需独立 fix。

##### Finding #3 · Cost / Balance 行为 — 待 follow-up

实测 12 个成功 call 后 **credit_delta=$0,package_delta=0 bytes** — **零扣费**!可能原因:
- (a) Plus package 在 finished_at=2026-05-22T09:41:37 前是免费配额池,API call 在 trial / pre-billing window
- (b) Balance update 是 batch / 延迟(hourly)
- (c) get_package().balance 字段更新滞后,实际 backend 已扣

**stage 2+ follow-up**:跑大批量 call 后再次 query balance 看 delta(本轮 audit 不深挖;PM Phase 2 ship 后真用户 dogfood 时 monitor)。

**决策 5 设计影响**:既然有 `get_api_credit()` + `get_package()` 真 balance API,**决策 5 重写后可直接调** API 查实时余额(不必纯靠本地 char→bytes 估算),配合 per-user daily/monthly cost cap 双保险。

##### Finding #4 · 错误码

| 触发 | HTTP code | elapsed | 说明 |
|---|---|---|---|
| bad reference(zero bytes audio) | **400 Bad Request** | 162 ms | 快返,client 可立即 fallback |
| bad API key | **401 Unauthorized** | 602 ms | 也快返 |
| (rate limit 未触发) | (untested) | — | starter tier 5 concurrent,本轮单测试无触发 |

`fish_audio_sdk.HttpCodeErr` 暴露 `.status` 属性 + `__str__` 描述,sufficient for routing(401→key 问题告警 / 4xx→client 错单 turn fallback / 5xx→重试 2-3 次后 fallback)。

##### Finding #5 · Emotion markers 全 12 call 接受(语义听感待 PM 听 wav)

T2.1-T2.5 全部成功合成,**SDK / API 字面接受**:
- 单 marker `[sarcastic]`、多 marker 跨句、嵌套闭合形 `[/sarcastic]`、mid-sentence `[whisper]`、组合 emotion `[teasing]+[soft chuckle]`
- 都不报错,正常返 audio

**语义是否真识别**(声学表达对应 emotion)需 PM 听 wav 文件:
- `scripts/fish_probe_outputs/T2_1_single_marker.wav` — 单 marker 是否真有讥讽感
- `scripts/fish_probe_outputs/T2_2_multi_marker.wav` — 跨句 emotion 切换自然度
- `scripts/fish_probe_outputs/T2_3_nested.wav` — `[/sarcastic]` 闭合是否被识别(predict:no,但 SDK accept)
- `scripts/fish_probe_outputs/T2_4_mid_sentence.wav` — 句内 `[whisper]` 切换语气
- `scripts/fish_probe_outputs/T2_5_persona_mai.wav` — Mai 讥讽 + 软笑组合

##### Finding #6 · Reference audio 格式约束

Input:stereo 44100Hz 16bit PCM WAV(1.2MB,5min Mai 复刻录音)→ 直接 work,无需 down-mix。Output:**mono 44100Hz 16bit PCM WAV**(Fish 输出统一 mono;input stereo 自动 down-mix)。

**Phase 2 影响**:
- 现 CosyVoice 输出 **24kHz mono 16bit**;Fish 输出 **44.1kHz mono 16bit**
- 前端 WebAudio API 自适应不同 sample rate(decodeAudioData)→ 不破前端
- 音质升级:**Fish 44.1kHz > CosyVoice 24kHz**(更高频率响应)

#### §1.3.10.4 Stage 1 假设 verdict(校正 §1.3.x)

| Stage 1 假设 | Stage 2 实测 verdict | 校正记入 |
|---|---|---|
| docs "无 balance API" | ❌ 错;SDK `get_api_credit()` + `get_package()` 都存在 | §1.3.6 |
| references[] 必需 | ❌ 错;T4.3 实证 default voice 路径 | §1.3.2 + Phase 2 设计 |
| balanced 模式 ~300ms | 实测 ~593ms TTFA(更保守但仍快 ~3x normal) | §1.3.1 latency 注释 |
| 100ms TTFA(docs claim) | 实测最快 593ms(可能 docs 不含 zero-shot 处理) | §1.3.1 |
| 错误码 docs 缺 | 400 / 401 直接确认;429 未触发 | §1.3.5 |
| 嵌套闭合 form 不支持 | SDK 字面接受 `[/sarcastic]` 不报错;但语义识别度需听 wav | §1.3.4 |

#### §1.3.10.5 Stage 2 收口

- ✅ 13 test call 跑通(11 成功合成 + 2 故意触错误码)
- ✅ SDK 接口 introspect:`fish_audio_sdk 1.3.0` `Session(key).tts(TTSRequest, backend='s2-pro') → Generator[bytes]`,默认流式
- ✅ TTFA 实测 balanced ~593ms / normal ~2300ms;**Phase 3 lock 用 balanced + WebSocket streaming**
- ✅ references[] inline zero-shot 路径成功;**不传 ref 也 work**(default voice 路径)
- ✅ 错误码 schema:`HttpCodeErr.status` 走 400/401(快返便于 fallback)
- ✅ emotion markers 字面全 work;**语义听感待 PM 听 6 个 T2.x WAV 文件 + T5 长句**
- ✅ output 格式:**mono 44.1kHz 16bit PCM WAV**(vs CosyVoice 24kHz,音质升级)
- ⚠️ Cost / balance 行为待 follow-up(本轮 0 扣费,可能 trial window / batch update)
- 🔒 12 个 audio output WAV 文件存 `scripts/fish_probe_outputs/`,审完后由 PM 决定保留 / 拔(可能值得保留作 demo 资料)

→ **§1.3 stage 2 完成**;数据 inform Step 4 §1.5 设计(per PM step swap)。

### §1.3.10.6 给 PM 听 + 拍板的点

1. **听 6 个 T2.x WAV** + T5 长句 — emotion markers 声学表达真识别度如何?
   - 主要 listen:T2.1 单 `[sarcastic]` 是否讥讽感 / T2.2 跨句 `[soft chuckle]→[gentle]` 切换自然度 / T2.5 Mai persona 组合是否符合角色感
   - 决定 §1.5 schema β inline `[marker]` 是否 final lock(stage 1 leaning)
2. **TTFA 600ms balanced** 对 Phase 3 流式 UX 是否可接受?(vs CosyVoice ~1-2s 阻塞)
3. **default voice (T4.3)** 是否值得作 Phase 2 mode_B 备选(无需 references[])?
4. **Output WAV 文件**(共 1.5MB 12 个)— 留作 demo / 删除?

### §1.3.10.7 Stage 2 lesson 沉淀

#### Lesson INV-8 #2 · docs 缺失字段不一定真缺(SDK 是更可靠的 ground truth)

docs.fish.audio 多个页面缺关键字段(无 balance API / 错误码 schema 缺 / Japanese emotion 示例缺),但 `fish-audio-sdk 1.3.0` Python 包 introspect(`dir()` / `inspect.signature()`)直接暴露完整 API 表面:`Session.get_api_credit / get_package / tts / asr / list_models / create_model / delete_model / update_model / get_model`。

**抽象**:第三方 service 调研时,**docs 是描述 contract,SDK 是 ground truth**;两者矛盾时按 SDK(docs 常滞后版本)。INV-7 §2.4 也类似(LiteLLM × DashScope tools= cache_control silently strip;docs 没明示,实测才暴露)。

→ **§1.3 整节完成**(stage 1 + stage 2)。

---



- ✅ Endpoint / auth / model header spec 摘要(`POST /v1/tts` + `model: s2-pro` header + `Bearer auth`)
- ✅ Zero-shot references[] inline 路径字段确认(`audio` bytes + `text`);**格式约束 stage 2 待实测**
- ✅ 流式支持:HTTP stream + **WebSocket `wss://api.fish.audio/v1/tts/live`** 主推流式;100ms TTFA;low/normal/balanced latency 档
- ✅ s2-pro Emotion markers:**`[bracket]` 自然语言不限固定集**(对比 S1 `(paren)` 固定 64);docs 缺 Japanese 示例 + multi-marker syntax(stage 2 必验)
- ✅ 错误码 docs 缺,fetch openapi.json + stage 2 触发测试补
- ✅ **Pricing 决策 5 重大校正**:$15/1M UTF-8 bytes pay-as-you-go;**无月配额 / 无 balance API**(brief "200 min/月切换" 假设作废);改本地 cost 累计 + per-user cap
- ✅ §1.3.7 跟 §1.5 联合接口:**β inline `[marker]`** schema CC leaning;per-provider sanitize(CosyVoice 路径剥 `[bracket]`)
- ✅ 决策 2 ✅ / 决策 4 ⚠️ 调整 / 决策 5 🔁 新选项(详 §1.3.8)
- ✅ Stage 2 实打验证清单 6 大类 ~20 子项

→ **§1.3 stage 1 完成**(估 ~340 行)。下一步 = **Step 4 · §1.5 LLM 双语 schema design space**(按 PM §1.4.11 修正后 scope 走 — 新增 sanitize bug audit + 历史定位 + 三档结论分支)。

---

## §1.5 LLM 双语 schema design space + sanitize bug 现状 audit(单 stage,2026-05-22)

> Phase 2 双语 schema final lock + Phase 3 流式管线设计基础。按 PM §1.4.11 修正后 scope:
> - 命名 `<ja>` vs `<tts_ja>` 不预 lock,留 audit 后评估
> - **新增 §1.5.X · sanitize 链历史 bug 现状 audit**(2 类 PM 担心 bug + 历史定位 + 跨 turn voice 切换)
> - 4 路 Option 对比加列"跟历史 ja sanitize bug 兼容性"
> - 三档结论拍板包(bug 已修沿 `<ja>` / bug 在三选一 A1/A2/C-D-E)
> - **Hard requirement**(PM lock):per-provider 双重隔离 — Fish `[bracket]` markers 只在 fish 模式 LLM 输出 + 接收端 non-Fish provider 强制 strip(per §1.3.7)
> - **Schema CC leaning** = β inline `[marker]`(per §1.3 stage 1+2,PM 待听 WAV 后 final lock)
> - **Voice cloning mode_A only**(per PM Step 5 决策 1 — Phase 2 VoiceConfig.fish 必含 reference_audio + reference_text,缺则 raise 不静默 fallback;mode_B default voice 路径砍掉)

### §1.5.1 历史定位 · ja 链 v4-segment2 → v4.0.0 回退全程

git log 实测 ja 链关键 commits(按时间倒序):

| commit | 日期 | 改动 | 角色 |
|---|---|---|---|
| `2bed353` | 2026-05-14 | `feat(persona): v4 segment 2 — UI 持久化 + ja tag 链路 + renderer 字段升级` | ja 链 v1 引入 |
| `a8287fa` | 2026-05-15 | `hotfix(persona-ja): bugfix-segment2-2 — ja directive 强约束中日交替格式` | bug fix #2(LLM 偏好集中模式) |
| `0d405fb` | 2026-05-15 | `hotfix(persona-ja): bugfix-segment2-3 — ja tag 意群粒度 + sentence_yield 短句合并` | bug fix #3(短句 TTS 崩) |
| `1c094bd` | 2026-05-16 | `fix(text_filters): exempt <ja>/<en> from SUSPICIOUS_TAG_RE strip` | bug fix #4(白名单豁免)|
| `c106f91` | 2026-05-16 | `fix(tts): final guard against literal <ja>/<en> tags reaching TTS provider` | bug fix #5(bugfix-D1.1 末端兜底) |
| **`0e079a4`** | **2026-05-16** | **`feat(tts): Mai 回退纯中文 — tts_language=zh + 换中文 voice,ja 链挂起留 v4.1`** | ⭐ **回退 commit** |

**回退根因**(实读 `0e079a4` commit body + `docs/archive/DESIGN_patch.md` Z.1):

> X.6 的 ja 中日交替链(Layer A1 强 directive + 禁集中模式 + Bugfix-Segment2-2 强化)折腾多版,稳定性仍不达标 —— 根因是"**LLM 实时自己交替标 `<ja>`**"这个不确定性**无法靠 prompt 根除**,弱网/长输出/工具轮次叠加时反复退化为音色错乱或话痨。

具体观察到的失败模式(per commit body + DESIGN_patch.md:299):
1. **话痨**(verbose,LLM 输出多段冗余)
2. **中日混在同一 `<ja>` tag**(LLM 漏切意群,把中日文塞同一 tag)
3. **Mai 复刻日语 voice 合成短中文时音色错乱**(短文本 TTS 质量崩)
4. **ja tag 解析失败 → 整段中日混合送 TTS**(fallback 路径)

**修法尝试范围**:5 个 bugfix(segment2-2/3 + D1.1 + 白名单豁免 + final guard)**全在 LLM 引导层 + 末端 sanitize 兜底**;**后端 sanitize 链核心(`extract_tts_text` 主路径)0 改动**。

→ **关键结论**:回退**不是"sanitize bug 不修弃了"**,是"LLM prompt 工程不可能保证 LLM 总按 ja directive 输出";sanitize chain 自身的兜底**有修(c106f91 + 1c094bd)**,但**未覆盖所有 LLM 失常输出形态**(详 §1.5.2 实测)。

### §1.5.2 Sanitize 链历史 bug 现状实测(PM 2 类 bug audit)

Probe 脚本:`scripts/inv8_sanitize_audit.py`(13 子项,3 大 Part)。

#### §1.5.2.1 Part A · `extract_tts_text(text, 'ja')` 6 子项

| # | case | raw | extract_tts_text → | subtitle → | verdict |
|---|---|---|---|---|---|
| A1 | 单 `<ja>` 块 | `嗯,去吧。<ja>「うん、行きなさい。」</ja>` | `「うん、行きなさい。」` | `嗯,去吧。` | ✅ 完美 |
| A2 | 多 `<ja>` 穿插 | `嗯,去吧。<ja>「うん、行きなさい。」</ja>专心看完。<ja>「ゆっくり読んで。」</ja>` | `「うん、行きなさい。」「ゆっくり読んで。」` | `嗯,去吧。专心看完。` | ✅ 完美(`bugfix-segment2-3 .findall` 生效) |
| A3 | 嵌套 `<ja><ja></ja></ja>` | `嗯。<ja>外层<ja>内层</ja>外层尾</ja>` | `外层<ja>内层` | `嗯。外层尾</ja>` | ⚠️ regex 错乱,但**LLM 实际不会输出嵌套**(prompt 未引导;边缘 case 可忽略)|
| A4 | 跟 emotion/state_update/motion/thinking 混排 | `<thinking>x</thinking><emotion>happy</emotion>开心。<ja>「嬉しいね。」</ja><state_update mood=+2 />` | `「嬉しいね。」` | `开心。` | ✅ 完美(各 strip 函数链工作) |
| **A5** | **半截 `<ja>` 未闭合** | `嗯。<ja>「うん、まだ書き...` | `嗯。<ja>「うん、まだ書き...` | `嗯。<ja>「うん、まだ書き...` | ⚠️ **PM bug #1 残留**:matches=[] → fallback `strip_all_for_tts(raw)` 不剥半截 `<ja>` 内容(白名单豁免) → **中文 + 字面 `<ja>` + 半截日语全送 TTS** |
| A6.1 | `<ja>` 内嵌中文 | `嗯。<ja>这里居然是中文不是日语</ja>` | `这里居然是中文不是日语` | `嗯。` | ⚠️ LLM 错标问题;extract 严格执行 spec(取 `<ja>` 内容),**中文送日语 voice TTS → 音色错乱**(这是 LLM 行为不是 sanitize bug) |
| A6.2 | `<ja>` 全空 | `嗯。<ja></ja>` | `` | `嗯。` | ✅ caller `if not tts_text.strip(): continue` skip synth |
| A6.3 | `<ja>` 含控制字符 | `嗯。<ja>「うん\x00\x07」</ja>` | `「うん\x00\x07」` | `嗯。` | ⚠️ extract 不剥控制字符;Fish/CosyVoice 行为待 stage 2+ 实测,通常 SDK 会 reject 或 ignore |

#### §1.5.2.2 Part B · 切 zh voice 时 sanitize 行为(PM bug #2)

| # | case | raw | extract_tts_text(zh) | subtitle | verdict |
|---|---|---|---|---|---|
| **B1** | **切 zh 后 LLM 输出含 `<ja>`** | `嗯,去吧。<ja>「うん、行きなさい。」</ja>` | `嗯,去吧。<ja>「うん、行きなさい。」</ja>` | `嗯,去吧。` | ⚠️ **PM bug #2 实锤未修**:zh 路径走 `strip_all_for_tts(raw)`,`<ja>` 在 `_SUSPICIOUS_TAG_WHITELIST` 豁免 → **`<ja>` 字面 + 内嵌日语完整送 zh voice TTS** |
| B2 | 切 zh 纯中文 | `嗯,去吧。` | `嗯,去吧。` | `嗯,去吧。` | ✅ 正常 |
| B3 | 切 zh + LLM 错标含中文 `<ja>` | `嗯。<ja>「这里中文」</ja>` | `嗯。<ja>「这里中文」</ja>` | `嗯。` | ⚠️ 同 B1 模式;subtitle 倒是正常(`strip_ja_en_tags_for_subtitle` 走的是另一条路径,会剥 `<ja>...</ja>` 整段) |

#### §1.5.2.3 Part C · `_tts_input_final_guard` (bugfix-D1.1 c106f91) 兜底覆盖度

| # | case | input → preprocess_tts_text → | verdict |
|---|---|---|---|
| C1 | 半截 `<ja>`(A5 全链) | `嗯。<ja>「うん、まだ書き...` → `嗯。「うん、まだ書き...` | ⚠️ `_JA_EN_LITERAL_RE` 剥字面 `<ja>/</ja>` 但**不剥内容**;**中文 + 半截日语仍混合**送 TTS |
| C2 | 切 zh + 含 `<ja>`(B1 全链) | `嗯,去吧。<ja>「うん、行きなさい。」</ja>` → `嗯,去吧。「うん、行きなさい。」` | ⚠️ **PM bug #2 全链验证**:`extract_tts_text('zh')` 不剥 → `preprocess_tts_text._tts_input_final_guard` 只剥字面 tag → **中日混合送 zh voice TTS** |

#### §1.5.2.4 Verdict 汇总

| PM 担心 bug | 当前状态 | 残留路径 |
|---|---|---|
| #1 "中日语一起全给 TTS"(`extract_tts_text(ja)` 不干净) | **部分修了**(A1/A2/A4 理想 case 完美);**A5 半截 + A6.1 LLM 错标残留**(fallback 路径 + LLM 错标行为 sanitize 无法纯靠 regex 防住) | `text_filters.py:323-327` fallback `strip_all_for_tts(raw)` |
| #2 "切 zh voice 仍带日语" | **未修**!`extract_tts_text('zh')` 走 `strip_all_for_tts`,`<ja>` 白名单豁免 → 字面 + 内容全保留 → 送 zh voice | `text_filters.py:337-338` zh 分支 + `_SUSPICIOUS_TAG_WHITELIST = {"ja","en"}` |

**核心问题**:白名单豁免是**给 ja voice 字幕路径设计的**(`strip_ja_en_tags_for_subtitle` 单独剥);但 **zh voice TTS 路径**也走 `strip_all_for_tts` → `<ja>` 在 zh 路径下也豁免 → **设计本意 vs 实际行为不对称**。

**Fix 路径**(若走"bug 还在 → A1 fix 再用 `<ja>`"分支,详 §1.5.10):
- `extract_tts_text`:lang='zh' 时**也剥 `<ja>` / `<en>` 整段**(包括内容),不仅字面 tag(2-3 行改)
- `extract_tts_text`:lang='ja' 半截 fallback 时,加 partial-tag check → 返 ""(让 caller skip synth)(3-5 行改)
- A6.1 LLM 错标 `<ja>` 内嵌中文 → **prompt-side 加强**(Layer A1 加 `<ja>` 内只放日语 + ✗ 错标示范),sanitize 无法纯防(本质 LLM 行为)
- 6 case unit test 落 `tests/test_sanitize_ja.py`

工程量 ~10-20 行代码 + 6 case unit test ≈ 0.3d。

### §1.5.3 跨 turn voice 切换实测(PM 修正 §1.5.X c)

实读 `prompt_manager.py` / `ws.py:712-760` / `chat.py:1232-1240` / `renderer.py:199-214`:

**每 turn 入口路径**(ws.py:712-743):
```python
# user 帧到达 → _handle_message:
character = prompt_manager.get_current_character(user_id)        # current char
voice_model = (await session.execute(
    select(Character.voice_model).where(Character.id == char_id)
)).scalar_one_or_none()                                          # ⭐ 每 turn 重读 fresh DB
tts_engine = get_tts_engine(voice_model)                         # ⭐ 每 turn 重建 engine
tts_language = (json.loads(voice_model) or {}).get("tts_language", "zh")  # ⭐ 每 turn 重 parse
# → chat.py.stream(chat_msg) 走 render_system_prompt(tts_language=tts_language) 重渲染 prompt
```

**render_system_prompt(renderer.py:199-214)**:每 turn 独立调用,参数 `tts_language` 从 caller 传入,**无 cache**;Jinja2 `_jinja_env.get_template("layer_a.j2").render(tts_language=...)` 每次重渲染,**ja 分支按当前 tts_language 决定是否进 prompt**。

**verdict**:
- ✅ **新 turn 起手 LLM 一定用新 prompt**(每 turn 重读 voice_model + 重渲染)
- ✅ **voice_model JSON 更新后下一 turn 立即生效**(无 cache 滞后)
- ⚠️ **同 turn 内 character_switch 帧**:per Rule A,in-flight turn 跑完旧 voice_model.tts_language 路径(`tts_engine` 在 turn start 就 lock)— 这是**有意设计**(不打断回复 / 不丢)而**不是 bug**
- ✅ prompt caching marker(per INV-5)在 `messages[0]` 第一 content block(stable Layer A+B+C 段);**ja directive 是 Layer A 一部分**,但**只有 ja 分支文字变了** prompt cache 才 miss;Mai zh 路径 prompt 不含 ja directive,切到 ja 时 cache miss 一次(预期 thrash,per INV-5 §1.2 矩阵)

**总结**:跨 turn voice 切换 0 风险;sanitize chain 是唯一 bug 源,不是跨 turn race 源。

### §1.5.4 tag-following project archaeology

实测 grep `<thinking>` / `<state_update>` / `<emotion>` / `<motion>` 等 tag 在历史 INV 中的 follow 率描述:

| Tag | follow 率描述(per docs/INV 历史) | 漏 tag 频次 |
|---|---|---|
| `<thinking>` | "first chunk 解析,boundary state machine 防切断"(chat.py:418-422 `_THINKING_OPEN_RE / _THINKING_CLOSE_RE`)| 罕见(LLM 学得好);streaming `_safe_boundary` 跳过 |
| `<state_update mood=N intimacy=N .../>` | "first chunk 解析,DB 写入"(ws.py:866 `_parse_state_update`);**自闭合形态偶发漏属性**(bugfix-1.1 `_find_boundary` 状态机修了 thought 含 `。` 切断 bug) | 中等(LLM 偶发漏 mood / 漏自闭合 `/>`) |
| `<emotion>X</emotion>` | "first chunk 解析,整轮锁定"(ws.py:840);密度约束"每 3-5 回合最多一次,平静对话不标"| 中等(密度约束实际偶超) |
| `<motion>X</motion>` | "每段独立解析,push Live2D 动作"(ws.py:895);允许密度高 | 较高(Mai 风格 motion 较多) |
| `<tool_call>` / `<function_calls>` / `<invoke>` (fallback) | "Qwen 偶发非 OpenAI 协议形式输出"(per `tool_call_resilience.py`);chunk 4 hotfix-1 兜底 | 偶发(Qwen-specific) |
| **`<ja>` / `<en>`**(v4-segment2 旧) | "强约束中日交替 + bugfix-segment2-2/3 多版折腾仍未稳定 → 回退 zh"(per §1.5.1) | **不可靠**(LLM 漏标 / 集中模式 / 中日混塞 / 半截);**回退根因** |

**结论 — `<ja>` 是历史 follow 率最低的 tag**:不是 LLM 不学,是"实时交替双语标 tag"本质难度大(意群切分 × 短句合并 × 跨 chunk 边界 × tool 轮次)叠加。其它 tag(emotion/state_update/motion/thinking)在 first chunk 一次性输出,follow 率 OK;`<ja>` 要求**每意群**输出,频次远高 → 漏一次 = 整段失败。

### §1.5.5 决策 1 可行性裁决

**决策 1 leaning(brief 给)**:`<display_zh>中文</display_zh><tts_ja>日语</tts_ja>` 顺序流式(不并行 / 不交错 / 不双调用 LLM)

**裁决**:

| 维度 | leaning vs 现实 |
|---|---|
| 顺序流式不并行 | ✅ 与现 `_safe_boundary` + `_sentence_stream` 架构契合(单 LLM 调用 + sentence yield streaming) |
| 命名 `<display_zh>` / `<tts_ja>` | ⚠️ 与现 `<ja>` 命名冲突;**改命名 → 重写 sanitize 链** = §1.5.10 Option A2 路径;**保持 `<ja>` → §1.5.10 Option A 路径** |
| 中日交替(每意群) | ⚠️ 历史折腾根因(§1.5.1);**β inline `[marker]` schema 会在 `<ja>` 内嵌 Fish emotion markers,加复杂度** |

**决策 1 可行性 verdict**:✅ **方向站得住**(顺序流式 + 单 LLM call 是对的);命名 + sanitize chain 的具体形态 → §1.5.10 拍板包三档结论决定。

### §1.5.6 Streaming parser 草图

按现 `_sentence_stream` (chat.py:428-448) + `_safe_boundary` (chat.py:405-425) 架构 + 决策 1 顺序流式 schema:

```
LLM token delta → sent_buf += content
  ↓
while True:
  idx = _safe_boundary(sent_buf)              # paired-tag aware
    paired tag set 含 ja/en/tts_ja(若 Option A2 命名)
    + thinking/state_update/motion/emotion/tool_call/function_calls/invoke
  if idx == -1: break (wait next chunk; tag 未闭合或无 boundary)
  sentence = sent_buf[:idx+1].strip()
  yield sentence
  ↓
ws.py main loop:
  parse + strip 5 道(emotion/state/thinking/motion/tool_call) — first chunk lock 轮 emotion
  ↓
  tts_text = extract_tts_text(sentence, tts_language)
                                ↑ ja 路径取 <ja>/<tts_ja> 内容(per Option A/A1/A2)
                                + 切 zh 时**剥 <ja>/<tts_ja> 整段**(Option A1 fix)
  ↓
  if provider == 'fish':
    tts_text 保留 [bracket] markers(per-provider sanitize Hard Requirement)
  else:
    tts_text = _FISH_EMOTION_MARKER_RE.sub("", tts_text)  ← strip [bracket] for CosyVoice/Edge
  ↓
  spawn _tts_synth_with_timeout(engine, tts_text, ...)
  ↓
  per-provider engine.synthesize_stream(text) → AsyncIter[bytes](Fish WebSocket)
                  / engine.synthesize(text)   → bytes(CosyVoice 阻塞 fallback)
```

**streaming parser 关键约束**:
- paired tag set 必含本轮 schema 命名(`<ja>` 或 `<tts_ja>`)— 否则 `_safe_boundary` 会在 tag 内的 `。` 切断 → 半截 tag 进 sentence yield → A5 残留 bug 重现
- LLM 输出**完整闭合 paired tag**前 sentence 不 yield(`_safe_boundary` 返 -1 等下个 chunk)— **这是已有机制,自动保证**

### §1.5.7 边角 case + 降级矩阵

按 brief §1.5.4 列 6 类边角 case:

| Case | 现象 | 降级 |
|---|---|---|
| 1 · LLM 漏 `<tts_ja>` 整段 | 只有中文 / 无日语 | `extract_tts_text(ja)` matches=[] → fallback `strip_all_for_tts(raw)` → 含中文送日语 voice TTS(音色错乱);**修法**:fallback 返 "" → caller skip synth + log warning(用户体感 = 该句无音频,文字字幕仍出) |
| 2 · LLM 漏 `<display_zh>` | 只有日语 TTS / 无中文字幕 | subtitle 路径 `strip_ja_en_tags_for_subtitle` 返空 → 无字幕(LLM 没出中文,用户体感 = 听到日语但 chat 空段);**修法**:Layer A1 严格 directive + sanity assert 至少一段中文 |
| 3 · `<tts_ja>` 内嵌中文 / `<display_zh>` 内嵌日语 | tag 内容混语 | extract 严格执行 spec → 中文进日语 TTS;**修法**:同 case 1,LLM-side 加强 + sanitize 加 lang detect heuristic(Phase 2+,先不做) |
| 4 · tag 嵌套错乱 | parser 错乱(A3 verdict) | `_safe_boundary` paired tag 状态机会跳到 last `</tag>`(实测 A3 `<ja>外层<ja>内层</ja>` regex 取 first match 外层 → 残留外层尾)— **罕见 LLM 不输出**;**修法**:不动(prompt 不引导嵌套即可) |
| 5 · LLM 输出 plain text 无 tag | 退化 v3 老格式 | `extract_tts_text(ja)` matches=[] → fallback;**降级**:返 "" skip synth,或 fallback 整段送(语言混乱);**leaning**:fallback skip + log,push 文字 chunk 给字幕 |
| 6 · `<tts_ja>` 内 Fish emotion marker `[bracket]` 错位 | LLM 错放 `[bracket]` 到 `<display_zh>` 内 | `<display_zh>` 走 subtitle path 不送 TTS,但 `[bracket]` 进字幕用户看到字面会困惑;**修法**:`strip_ja_en_tags_for_subtitle` 走完后跑 `_FISH_EMOTION_MARKER_RE.sub("", subtitle)`(provider-aware:fish 模式下统一剥字幕里的 `[bracket]`) |

### §1.5.8 Fish emotion 集成 prompt 设计草图(联合 §1.3 + Hard Requirement 应用)

Per **Hard Requirement(PM lock 2026-05-22)** · per-provider 双重隔离 + voice cloning **mode_A only**:

#### Layer A1 ja directive · provider 分支(Phase 2 改造)

```jinja2
{% if tts_language == 'ja' %}
[日语 TTS 模式 - 此角色 voice 为日语音色]
... (现有意群粒度 / 中日交替 / <ja>「...」</ja> 格式 directive 保留)

  {% if voice_model.provider == 'fish' %}
[Fish s2-pro 句内情感 markers - 仅 fish provider 模式启用]

可选在 <ja> 内嵌入 [自然语言情感描述] 控制声学表达:
  - 句首 / 句中 / 句尾均可
  - 单 marker 或多 marker 组合
  - 建议词汇集(可自由扩展):
    Mai 风格候选:[sarcastic] / [teasing] / [gentle] / [soft chuckle] /
                  [calm] / [whisper] / [thoughtful]
    通用语气:    [excited] / [surprised] / [tired] / [confused]
    音效:       [laugh] / [sigh] / [gasp] / [chuckle]

正确格式 ✓:
"嗯,真好笑。"<ja>[soft chuckle]「ま、いいか。」</ja>"算了别管了。"<ja>[gentle]「気にしないで。」</ja>

错误格式 ✗(将 [marker] 放进 display_zh / <display_zh>):
"[sarcastic]嗯。"<ja>「ま、いいか。」</ja>  ← markers 只能在 <ja> 内,不进中文段

错误格式 ✗(marker 用方括号外形态):
<ja>(sarcastic)「ま、いいか。」</ja>  ← Fish 用 [bracket] 不是 (paren)

约束:
  - 每意群至多 2-3 markers,密度过高反而崩坏
  - 平静对话可不带 marker(默认 neutral 语气)
  - markers 不嵌套,不闭合形态([/sarcastic] 无效)
  {% endif %}
{% endif %}
```

#### 后端 sanitize chain · per-provider strip 路径(Phase 2 改造)

新增 `_FISH_EMOTION_MARKER_RE = re.compile(r"\[[^\]]+\]")`:

```python
# backend/utils/text_filters.py 新增
_FISH_EMOTION_MARKER_RE = re.compile(r"\[[^\]]+\]")

def strip_fish_emotion_markers(text: str) -> str:
    """剥 Fish [bracket] markers — non-Fish provider 路径必走。"""
    if not text:
        return text
    return _FISH_EMOTION_MARKER_RE.sub("", text)

# backend/tts/__init__.py _PreprocessingEngine.synthesize 或 _build_engine 内 fish-aware 包装:
# - provider == 'fish' → 保留 [bracket] 透传 SDK
# - 否则 → 调用前 strip_fish_emotion_markers(text)

# backend/utils/text_filters.py strip_ja_en_tags_for_subtitle 内追加:
# subtitle = strip_fish_emotion_markers(subtitle)  ← 字幕路径任何 provider 都剥(用户不看 [bracket])
```

#### voice_config.py 扩字段(Phase 2)

```python
@dataclass
class VoiceConfig:
    provider: str
    voice: str
    instruct_supported: bool = False
    model: Optional[str] = None
    # § INV-8 §1.5.8 新增:
    tts_language: str = "zh"                         # 从 JSON 顶层提进 dataclass
    # Fish-specific(provider=='fish' 必填,缺 raise per PM Step 5 决策 1):
    reference_audio_path: Optional[str] = None        # 本地路径 / DB blob ref
    reference_text: Optional[str] = None              # transcript
    fish_latency: str = "balanced"                    # "low" / "normal" / "balanced",默 balanced
```

`parse_voice_config` Fish 分支 + raise:
```python
if provider == "fish":
    if not data.get("reference_audio_path") or not data.get("reference_text"):
        raise ValueError(
            "voice_config: fish provider requires reference_audio_path + reference_text"
        )
    # ...
```

### §1.5.9 4 路 Option 对比表(brief §1.5.6 + 加列"历史 ja sanitize bug 兼容性")

| Option | 描述 | LLM 复杂度 | 流式 UX | 工程实施 | 失败模式 | Fish emotion 集成 | **跟历史 ja sanitize bug 兼容性** | Hard Req 双重隔离契合 |
|---|---|---|---|---|---|---|---|---|
| **A** | `<ja>` 沿用(老命名)+ display_zh 隐式(`<ja>` 外的中文段) | 中 | 先读中文 → 听日语,有小延迟 | 极低(0-1 行代码改) | LLM 漏 `<ja>` 整段 | `<ja>` 内嵌 `[marker]` | ⚠️ **bug #1 部分残留(A5/A6.1)+ bug #2 未修**;不 fix 直接用 → 切 zh 时含 `<ja>` 残留行为复现 | ✅ 完全契合(per-provider sanitize 在 ws.py 层独立) |
| **A1**(CC leaning) | A + fix sanitize 链(extract_tts_text zh 也剥 `<ja>` / fallback skip + 6 case unit test) | 中 | 同 A | 低(~10-20 行 + unit test ≈ 0.3d) | LLM 漏 `<ja>` 整段(已降级 skip + log) | 同 A | ✅ **bug #1/#2 全 fix**;代码一致性最好 | ✅ 完全契合 |
| **A2** | 新 `<tts_ja>` + `<display_zh>` 双 tag + 全新 sanitize 链(留两套) | 中-高 | 同 A | 中(全新 sanitize ~50-80 行 + 旧链保留作 legacy ≈ 1d) | LLM 漏新 tag / 学新 schema 学不会 | `<tts_ja>` 内嵌 `[marker]` | ⚠️ 避开历史 bug 但**两套长期共存认知 burden** | ✅ 完全契合 |
| C | interleave per-sentence(每句一对) | 高 | 边听边看,体感同步 | 中-高 | tag 嵌套错乱概率高 | inline 同 A | ⚠️ tag 密度更高 → bug #1 类残留更易触发 | ✅ 完全契合 |
| D | 后置翻译(LLM 纯中文 → qwen-turbo 翻日 → TTS;ROADMAP v4.1 F0 老路) | 低 | 延迟最高(中 + 翻 + 合成 串行) | 高(新加翻译 layer + cache) | 翻译质量不可控 + 延迟 | 翻译后 inline `[marker]` 难塞(需翻译产物含 markers) | ✅ 完全绕开 `<ja>` 路径,bug 不复现 | ⚠️ Fish [marker] 集成路径需大改(LLM 不知 markers,翻译 LLM 可能也不学;CC 不推) |
| E | 双调用并行(中文 LLM + 日语 LLM) | 低 | 体感同步高 | 极高(双 LLM cost × state 同步 × Mai persona 双份) | 双 LLM state 不一致 / cost 翻倍 | 日语 LLM 直接输出 `[marker]` | ✅ 完全绕开 | ⚠️ Cost / 复杂度爆炸,不推 |

**对每 Option · 5 决策契合度评估**:
- 决策 1(顺序流式不并行):A/A1/A2/C ✅ / D ⚠️(串行)/ E ❌(双调用)
- 决策 2(Fish + zero-shot inline references[]):全 Option ✅(provider 抽象层独立)
- 决策 3(synthesize + synthesize_stream 接口):全 Option ✅(per-provider 实现)
- 决策 4(β inline `[marker]`):A/A1/A2/C ✅ / D ⚠️ / E ✅
- 决策 5(fallback + cap):全 Option ✅(provider 失败 fallback CosyVoice + 剥 `[bracket]` per Hard Req)

**工作量粗估**(per option ship 到 Phase 3 完成):
- A:0-0.5d(直接用,接受 bug 残留)
- **A1**:0.3-0.5d(fix sanitize + unit test)+ Phase 2/3 主体 ~3-5d
- A2:1.5-2d(双 schema 共存)+ Phase 2/3 主体 ~3-5d
- C:1-1.5d(interleave parser + LLM 引导 complexity)
- D:3-5d(翻译 layer + cache + LLM cost monitor)
- E:5-7d(双 LLM 同步 / state 一致性 / cost 翻倍设计)

### §1.5.10 给 PM 的拍板包 · 三档结论

按 PM §1.4.11 修正后的结论分支,实测 evidence 后**结论分支落点**:

> **bug 状态**:bug #1 部分修(A5 半截 + A6.1 错标残留)/ bug #2 未修(切 zh 含 `<ja>` 未剥)

→ **走"bug 还在 → 三选一"分支**

#### 三档对比 + CC leaning

| 档 | 方案 | 工程量 | 长期维护 | 跟决策 1 顺序流式契合 | 跟 Hard Req 双重隔离契合 | CC leaning |
|---|---|---|---|---|---|---|
| **A1** | fix sanitize 链 bug,沿用 `<ja>` | 0.3-0.5d sanitize fix + Phase 2/3 主体 ~3-5d | ✅ 单一 schema,代码一致 | ✅ | ✅ | ⭐ **CC leaning 1st**:工程量小 + 代码一致 + Hard Req 完美契合 |
| A2 | 新 `<tts_ja>` + 全新 sanitize 链 | 1.5-2d 双 schema + Phase 2/3 主体 ~3-5d | ⚠️ 两套长期共存 burden | ✅ | ✅ | CC leaning 2nd(若 PM 担心 `<ja>` 历史包袱影响认知) |
| C/D/E | 走其它 Option 绕开 ja 路径 | 1-7d 大改 | varies | C ✅ / D ⚠️ / E ❌ | varies | CC 不推(C 密度问题 / D Fish marker 集成难 / E cost) |

**CC final leaning**:**A1**(fix sanitize 链 bug 再用 `<ja>`)。

理由:
1. **sanitize fix 工程量极小**(~10-20 行 + 6 case unit test ≈ 0.3d),不值得为此走 A2 双 schema 长期共存
2. **代码一致**:layer_a.j2 ja directive 0 改命名(只加 `{% if provider == 'fish' %}` 子分支教 markers);extract_tts_text + sanitize 链单一路径
3. **Hard Req 完美契合**:per-provider sanitize 加 `strip_fish_emotion_markers`(独立函数),与 `<ja>` 命名解耦
4. **历史 bug 根因不是命名是 LLM 实时双语标 tag 不稳定**;命名换 `<tts_ja>` 不解决根因
5. **β inline `[marker]` schema** 加 sanitize fix 后,**新增的 bug 面 = `[bracket]` strip 路径**(CosyVoice 收 stripped 版,Fish 收原版),独立测试可控

### §1.5.11 决策 1 + 4 leaning 状态最终(本节产出 + Step 5 实测综合)

| 决策 | leaning(brief 给) | 最终三档 | 备注 |
|---|---|---|---|
| 1 · LLM 双语 schema | `<display_zh><tts_ja>` 顺序流式 | ⚠️ **需要调整**(per CC leaning A1) | 顺序流式方向 ✅;命名沿用 `<ja>`(老命名)+ `<ja>` 外中文段隐式作 display_zh;**不引入 `<display_zh>` 命名**(避免 A2 双 schema burden);PM 拍板 |
| 4 · Fish 句内 emotion markers | LLM 输出带 markers + CosyVoice 走 SSML | ⚠️ **需调整**(per §1.3.7 + Hard Req) | **β inline `[bracket]`**(CC leaning,PM 待听 WAV final lock);Hard Req per-provider 双重隔离:fish prompt 教 markers + non-fish provider sanitize strip;CosyVoice **不走 SSML**(SSML 是 instruct 路径形态,本轮不动 CosyVoice emotion 通道) |

### §1.5.12 收口 + lesson

#### §1.5 audit 成果

- ✅ ja 链历史定位:回退 commit `0e079a4`(2026-05-16),根因 = LLM 实时双语 tag 不稳定不可 prompt 根除;5 修法 commit 全在 LLM 引导层 + 末端兜底,sanitize 主路径 0 改动
- ✅ Sanitize bug 现状实测(`scripts/inv8_sanitize_audit.py` 13 子项):
  - **bug #1 部分修**(A5 半截 + A6.1 LLM 错标残留)
  - **bug #2 未修**(切 zh 含 `<ja>` 完整保留送 TTS)
  - 残留路径 = `text_filters.py` zh 分支 + `_SUSPICIOUS_TAG_WHITELIST` 白名单豁免在 zh 路径反作用
- ✅ 跨 turn voice 切换 audit:**0 风险**(每 turn 重读 voice_model + 重渲染 prompt,无 cache);同 turn character_switch 走 Rule A 不打断 in-flight turn(有意设计)
- ✅ tag-following archaeology:`<ja>` 是历史 follow 率最低的 tag(实时双语意群密度高,与其它 first-chunk 一次性 tag 本质不同)
- ✅ 决策 1 可行性 ✅(顺序流式方向对);命名 + sanitize 形态由三档决定
- ✅ Streaming parser 草图(现 `_safe_boundary` paired tag set 含 `<ja>` 自动保证 boundary correctness)
- ✅ 6 边角 case + 降级矩阵(漏 tag / 内嵌错语种 / 嵌套错乱 / plain text 退化 / marker 错位)
- ✅ Fish emotion prompt 集成草图:Layer A1 `{% if provider == 'fish' %}` 子分支教 markers(Mai 风格候选 7 markers + 通用 + 音效);后端 sanitize per-provider 新增 `_FISH_EMOTION_MARKER_RE` + `strip_fish_emotion_markers`;voice_config 加 4 字段(tts_language / reference_audio_path / reference_text / fish_latency)+ Fish provider raise validation(mode_A only per PM Step 5)
- ✅ 4 路 Option 对比(brief 4 路 + A1/A2 细分):5 决策契合度 + Hard Req 双重隔离契合 + **历史 ja sanitize bug 兼容性**(新加列)
- ✅ 三档结论拍板包:bug 状态 = bug 还在 → **CC leaning A1**(fix sanitize + 沿用 `<ja>`)
- ✅ 决策 1 / 4 最终 leaning 状态(⚠️ 需调整,具体 CC leaning 明示)

#### Lesson INV-8 #3 · sanitize 链 sub-language path 设计对称性

`_SUSPICIOUS_TAG_WHITELIST = {"ja", "en"}` 白名单豁免本意是为 ja voice **TTS 路径保留 `<ja>` content** + 字幕路径用独立 `strip_ja_en_tags_for_subtitle` 单独剥;**但 zh voice TTS 路径**复用同 `strip_all_for_tts`,导致 zh 路径下 `<ja>` 也被豁免不剥 → **PM bug #2 根因**。

**抽象**:sanitize chain 在**多 sub-language 路径**(ja/en/zh)下需明示**per-language strip rules**,不能一个 `_SUSPICIOUS_TAG_WHITELIST` 全局豁免;**白名单本应针对 path**(ja-path-WHITELIST vs zh-path-WHITELIST),而非全局。Phase 2 fix 走 `extract_tts_text` 内 lang='zh' 分支显式剥 `<ja>/<en>` 整段。

**类比**:INV-7 §1.7 lesson #9 三 grep 模式(cap-name / module import / frontend prefix)— 同款"多路径 audit 必须 case-by-case 覆盖"模式。

#### Lesson INV-8 #4 · prompt 工程 vs sanitize chain 的边界

ja 链回退根因(per §1.5.1 DESIGN_patch.md Z.1)= "LLM 实时双语标 tag 的不稳定性**无法靠 prompt 根除**"。本节 §1.5.2 实测 bug #1/#2 残留路径,也确认 **sanitize chain 无法 fix LLM 错标本身**(只能 fix 解析 / fallback / 剥除)。

**抽象**:LLM 行为面 ↔ sanitize chain ↔ TTS provider 三层分工:
- LLM 行为面问题(漏 tag / 错语种 / 错标 markers)→ **prompt-side 加强**(directive + ✗ 错误示范 + persona-tied 引导)
- 解析路径 / 边界 / 残留字面 → **sanitize chain 修**
- 声学表达不符(emotion 没识别)→ **provider-side(模型本身)**

**策略**:Phase 2/3 实施时按这三层分工分别给 monitor + alert;不应把 LLM 行为面问题当 sanitize bug 修,反之亦然。

→ **§1.5 单 stage 完成**(本节 ~430 行)。

---

## §1 收口 summary(2026-05-22)

> PM 2026-05-22 Step 4 review 拍板:
> - **决策 1 lock**:沿用 `<ja>` 命名,中文裸文本作隐式 display_zh(不引入 `<display_zh>`)
> - **Option A1 lock**:fix sanitize + 沿用 `<ja>`;Phase 2 落 ~10-20 行 sanitize fix + 6 case unit test
> - **Phase 2 工作量估算 OK**(~3-5d / ~250-300 LoC + 1 新 fish.py 文件)
> - **Step 6(§1.1 stage 2 真机 log)挪 Phase 3 H3 fix 时合刀**,不算独立 audit overhead → INV-8 §1 audit 整段 closed

### §1.收口.1 5 决策 leaning 最终三档汇总

| # | 决策 | brief leaning | **最终三档** | 关键 evidence |
|---|---|---|---|---|
| **1** | LLM 双语 schema | `<display_zh><tts_ja>` 顺序流式 | ⚠️ **需调整 → 沿用 `<ja>` + 中文裸文本隐式 display_zh** | §1.4 `layer_a.j2:32-83` ja directive 已用 `<ja>「日语」</ja>` 形态(等价语义);§1.5 历史定位 = 命名换不解决 LLM 行为根因 |
| **2** | Fish + s2-pro zero-shot references[] | 每次传 reference_audio + reference_text | ✅ **站得住** | §1.3 stage 1+2 实证:`references=[ReferenceAudio(audio=bytes, text=str)]` inline 路径成功;**Phase 2 mode_A only**(PM Step 5 决策 1 lock — fish 缺 ref 必 raise,mode_B 砍) |
| **3** | TTSProvider 抽象接口 | `synthesize(voice_config, text, emotion_hint) → audio_stream` 单签名 | ⚠️ **需调整 → 保留 `synthesize(text, emotion) → bytes` + 新增 `synthesize_stream(text) → AsyncIter[bytes]` per-provider 可选** | §1.2 现 `TTSBase` 抽象已 deployed;brief 单签名大破 `_PreprocessingEngine` / `_LegacyProviderAdapter`(PM Step 1 ack) |
| **4** | Fish 句内 emotion markers | LLM 输出带 markers + CosyVoice 走 SSML wrap | ⚠️ **需调整 → β inline `[bracket]` + Hard Req per-provider 双重隔离** | §1.3 stage 1+2:s2-pro 是 `[bracket]` 自然语言不限固定集(非 SSML);PM 待听 WAV final lock;**CosyVoice 不动 SSML 通道**;非 fish provider 强制 strip `[bracket]`(PM Step 5 Hard Req lock) |
| **5** | fallback + quota | 200min/月 + 90% 警告 + 100% 切 + 跨月 reset | 🔁 **新选项 → 本地 cost 估算 + per-user daily/monthly cost cap + 触达 cap/API 失败 fallback CosyVoice + toast** | §1.3 stage 1+2 实证:Fish **无月配额**(pay-as-you-go $15/1M UTF-8 bytes);**balance API 实有**(`get_api_credit()` / `get_package()`,docs 缺漏);Plus 250k bytes ≈ 200 min(brief 量级吻合但与 API 解耦);PM Step 5 lock |

### §1.收口.2 Phase 2 拍板清单(给 PM 进 Phase 2 前过一遍)

| # | 待 PM 进 Phase 2 前确认 | 当前状态 | 备注 |
|---|---|---|---|
| Q1 | Option A1 fix sanitize 主体(extract_tts_text zh 也剥 `<ja>` 整段 + ja 半截 fallback skip + 6 case unit test)合并入 Phase 2 还是独立刀? | (待 PM 拍板) | 工程量 ~10-20 行 + 0.3d;CC leaning 合并入 Phase 2 起始第 1 commit(模板:类 INV-7 §1 ship pattern) |
| Q2 | cid=1 vs cid=101 3 缓解方案 A/B/C 选哪条?(per §1.4.7) | (待 PM 拍板) | CC leaning **方案 B**(数据迁移 cid=1 → cid=101,Phase 2 收尾刀;~30-50 行 migration) |
| Q3 | T2.x 6 个 WAV + T5 1 个 WAV(`scripts/fish_probe_outputs/`)PM 听完后 schema β inline `[bracket]` final lock? | (PM 待听 WAV) | CC leaning β |
| Q4 | Plan C 删 yaml + ssml_supported 死字段清理是否合并入 Phase 2? | (待 PM 拍板) | CC leaning **不合并**(独立 backlog 刀,~1-2h;per §1.4.2 / §1.4.9) |
| Q5 | Phase 2 改造 7 文件清单(per §1.5.10 / Step 4 summary)— OK? | ✅ ack(PM Step 4 review)| Phase 2 起手前 CC 出 Phase 2 brief / commit 计划 |
| Q6 | Phase 2 完成后 Phase 3 流式管线 + H3 fix + Step 6 instrumentation 合刀 — 节奏 OK? | ✅ ack(PM Step 4 review)| Step 6 11 log 点(§1.1.3)→ 进 Phase 3 H3 fix 前置 audit |
| Q7 | 决策 5 cost cap UI 落地:Settings 新增 `fish_daily_cost_cap_usd` / `fish_monthly_cost_cap_usd` 字段位置(profile_data JSON / 新 `user_settings` 表)? | (待 PM 拍板)| CC leaning `profile_data` JSON(轻量 + 不破现 schema) |

### §1.收口.3 Lesson 沉淀汇总(本 INV-8 §1 新增 4 lesson)

| # | lesson | 出处 | 影响 |
|---|---|---|---|
| **INV-8 #1** | DESIGN_LITE 红 flag 描述偏差("休眠" vs "待机"):`config-driven dormancy` 应明示"配置切换即激活"vs"代码需重新打通" | §1.4.10 | docs 增量 backlog |
| **INV-8 #2** | docs 缺失字段不一定真缺,**SDK 是更可靠 ground truth**;第三方 service 调研:**docs 是 contract,SDK 是 truth**,矛盾时按 SDK(类比 INV-7 §2.4 LiteLLM × DashScope silently strip) | §1.3.10.7 | Phase 2 / 调研方法论 |
| **INV-8 #3** | sanitize chain sub-language path 设计对称性:`_SUSPICIOUS_TAG_WHITELIST` 全局豁免在多 sub-language 路径下反作用(ja 路径设计 vs zh 路径复用同函数);**白名单应 per-path 而非全局** | §1.5.12 | Phase 2 A1 fix 落实 |
| **INV-8 #4** | LLM 行为面 ↔ sanitize chain ↔ TTS provider 三层分工边界:LLM 实时行为不稳定(漏 tag / 错语种 / 错标)→ **prompt-side 加强**;解析 / 残留字面 → **sanitize chain**;声学表达不符 → **provider model 本身**;**三层不可错位修** | §1.5.12 | Phase 2/3 ship 节奏纪律 |

### §1.收口.4 Step 6 backlog 挂起(per PM Step 4 review)

§1.1 stage 2 instrumentation(11 个 `# DEBUG-INV8` log 点,详 §1.1.3)**挪到 Phase 3 H3 fix 时合刀**,不算独立 audit overhead:

- 11 log 点(7 后端 + 4 前端)在 Phase 3 流式管线 + H3 fix 设计期同步加入,Phase 3 ship 前跑真机 log 验证 H3 +1000ms safety margin 假设(per §1.1.2)
- 审完拔光按统一 `grep -rn "# DEBUG-INV8" backend/ frontend/ | wc -l` 检查 + `git restore -p`
- 此项挂 ROADMAP backlog 标 "Phase 3 H3 fix 时合刀"

### §1.收口.5 §1 closure 声明

INV-8 §1 audit(共 5 节 §1.1-§1.5 + sanitize bug audit + 历史定位 + 跨 turn voice 切换 audit)closed,7-step plan 完成 6 step(Step 6 挪 Phase 3,不计独立 audit overhead):

| Step | 节 | 完成 commit / 输出 |
|---|---|---|
| 1 | §1.1 stage 1 + §1.2 合刀 | INV-8 §1.1 + §1.2(~460 行) |
| 2 | §1.4 voice ↔ character ↔ language | INV-8 §1.4(~270 行) |
| 3 | §1.3 stage 1 Fish docs 调研 | INV-8 §1.3.1-1.3.9(~340 行)|
| 5 | §1.3 stage 2 Fish 实打 | INV-8 §1.3.10(~130 行)+ `scripts/fish_probe_T1_T6.py` + 12 WAV outputs(`scripts/fish_probe_outputs/`,gitignore) |
| 4 | §1.5 + sanitize bug audit | INV-8 §1.5(~440 行)+ `scripts/inv8_sanitize_audit.py` |
| 7 | §1 收口 + INDEX 登记 | 本节 |
| 6 | (挪 Phase 3) | backlog ROADMAP |

INV-8 §1 总 ~1,600 行(超 brief 600-900 行预算约 2x,但保持单 INV 紧耦合;per PM Step 5 review "INV-4 1,120 行先例,1,400-1,500 行 OK")。后续 Phase 2/3 实施起新 INV-9 或 INV-8 §2/§3。

→ **Phase 1 §1 audit 整段 closed**。PM 进 Phase 2(TTSProvider 抽象层设计 + 实施)前过 §1.收口.2 拍板清单 Q1-Q7。

### §1.收口.6 Q1-Q7 PM 拍板记录(2026-05-22)

| # | 问题 | CC leaning | **PM 答案** |
|---|---|---|---|
| Q1 | A1 sanitize fix 合并入 Phase 2 第 1 commit 还是独立刀? | 合并入 Phase 2 第 1 commit | ✅ **合并 Phase 2 第 1 commit**(同意 CC leaning) |
| Q2 | cid=1 vs cid=101 3 缓解方案 A/B/C? | B(数据迁移 cid=1 → cid=101,Phase 2 收尾刀) | ✅ **Plan B,Phase 2 收尾刀**(lock) |
| Q3 | PM 听 T2.x + T5 WAV → schema β final lock? | β inline `[bracket]` | ⏳ **后续单独通知,不挡 Phase 2 启动**(Phase 2 起手按 β leaning 走,PM 听完 WAV 若推翻则 hotfix) |
| Q4 | Plan C 删 yaml + ssml 死字段清理合并 Phase 2 还是独立? | 独立 backlog | ✅ **独立 v4.1+ backlog**(同意 CC leaning) |
| Q5 | Phase 2 7 文件改造清单 OK? | (已 ack) | ✅ **ack** |
| Q6 | Phase 3 流式 + H3 fix + Step 6 合刀节奏 OK? | (已 ack) | ✅ **ack** |
| Q7 | cost cap UI 存 profile_data JSON 还是新 user_settings 表? | profile_data JSON | ✅ **profile_data JSON**(同意 CC leaning) |

---

## §INV-8 §1 封存声明(2026-05-22,1,560 行)

INV-8 §1 audit 整段 closed。**1,560 行触发 PM "超 1,500 切节" 决策**(per Step 7 review),后续 Phase 2/3 实施迁 INVESTIGATION-9.md。

### 封存覆盖范围

- §1.1 句间停顿根因 stage 1(静态 audit + 4 假设代码侧 verdict + 11 log 点 instrumentation 提案)
- §1.2 现有 TTS 调用链路(6 文件树 + 8 step 文字图 + 3 抽象插点提案)
- §1.3 Fish API + s2-pro zero-shot 调研 stage 1+2(docs 调研 + 13 test call 实打 + 12 WAV outputs + SDK 接口确认)
- §1.4 voice ↔ character ↔ language audit(9 char DB 矩阵 + cid=101 三件事 + ja 链状态修正 + 前端 i18n + LLM prompt 语言硬约束 + Plan B/C 现状)
- §1.5 LLM 双语 schema design space + sanitize bug audit + 历史定位(13 子项实测 + 回退 commit `0e079a4` + 5 修法 + 4 路 Option 对比 + Option A1 lock)
- §1 收口 summary(5 决策最终三档 + Phase 2 拍板清单 Q1-Q7 + 4 lesson + Step 6 backlog 挂起 + Q1-Q7 PM 拍板记录)

### Phase 2 起手前置

- ✅ Option A1 lock(fix sanitize + 沿用 `<ja>` + 6 case unit test)
- ✅ Hard Req per-provider 双重隔离 lock(layer_a.j2 `{% if provider == 'fish' %}` 教 markers + 接收端 non-fish strip `[bracket]`)
- ✅ Phase 2 7 文件改造清单 + ~3-5d / ~250-300 LoC + 1 新 `backend/tts/fish.py`
- ✅ cid=1 → cid=101 数据迁移 Plan B(Phase 2 收尾刀)
- ⏳ PM 听完 T2.x + T5 WAV → schema β inline `[bracket]` final lock(不挡 Phase 2 启动)

### 后续刀链

- **INV-9**(待 PM "听完 WAV β lock" 通知后起用):Phase 2 TTSProvider 抽象层 + Fish s2-pro 集成 + sanitize A1 fix + cid=1→cid=101 数据迁移收尾刀
- **Phase 3**(Phase 2 ship 后):流式管线(Fish WebSocket `stream_websocket` + `latency=balanced`)+ Step 6 11 log 点 instrumentation 合刀 + H3 +1000ms safety margin fix + 前端 WebAudio API 序列拼接重构
- **独立 backlog**:Plan C 删 yaml + ssml_supported 死字段清理(v4.1+)

INV-8 §1 此处封存,不再追加。Phase 2 起 INV-9。

### §1.4.11 PM 补充 · §1.5 scope 修正(2026-05-22)

PM 历史经验补充 ja 链 2 类历史 bug,**§1.4 audit 说 "ja 链 active in tree (config-driven 待机)" 但没具体验证这两个历史 bug**;若当时是直接弃了没修 → bug 还在 sanitize 链 → 起 ja 路径就会复现,改 tag 命名解决不了。

**2 类历史 bug**:
1. **"中日语一起全给 TTS"** — `extract_tts_text(text, 'ja')` 某些输入形态下没正确剥成纯 ja,中文段一并被送 TTS
2. **"切中文中音还带日语"** — 切 zh voice 时 LLM 输出里的 `<ja>` 段没被 strip 就送 TTS,或 LLM 还按旧 prompt 输出 ja tag

**§1.5 scope 4 项修正**(Step 4 启动前看,Step 3 不受影响):

1. **取消 `<ja>` 命名 leaning** — 命名 `<ja>` vs `<tts_ja>` 不预 lock,留 audit 后评估
2. **新增 §1.5.X sanitize 链历史 bug 现状 audit**:
   - a) `extract_tts_text(text, 'ja')` 多形态 LLM 输出下 ja 段提取干净度(6 边角 case:单 `<ja>` 块 / 多 `<ja>` 穿插 / 嵌套跨段 / 与 emotion/state_update/motion 混排 / 半截未闭合 / 内嵌错误内容)
   - b) `strip_ja_en_tags_for_subtitle` 切 zh voice 时 `<ja>` 段剥除干净度(chat 字幕 + TTS 路径)
   - c) 跨 turn voice 切换实测:voice_model JSON 更新后 prompt_manager 是否同步重渲染 / 新 turn 起手 LLM 用新还是旧 prompt
3. **历史定位**(顺手做):git log + 旧 INV(INV-2 / 早期 INVESTIGATION.md / DESIGN_patch.md)找当时 ja 链回退 commit + 关联 bug 描述
4. **4 路 Option 对比表加一列**:"跟历史 ja sanitize bug 兼容性"

**结论分支**(audit 完按 bug 现状给 PM 三档):
- ✅ bug 已修 → 沿用 `<ja>`,Option A 起步,改造面最小
- ⚠️ bug 还在 → 三选一:
  - **A1**: 先 fix sanitize 链 bug,再用 `<ja>`(代码一致性最好,工程量上升)
  - **A2**: 用新 `<tts_ja>` + 全新 sanitize 链(避开历史代码,代价 = 留两套 ja 处理长期共存)
  - **C/D/E**: 走其它 Option 绕开 ja 路径整体

CC 在 §1.5 拍板包列三档 + 各档 evidence,PM 拍板。

---
