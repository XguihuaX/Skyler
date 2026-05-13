# Chunk 15 / UX-006 — Audio Sentence Streaming · Starting Context

本文档是 chunk 15(UX-006)实施前的 audit 报告,锁定:**backend message 句级
拆分 + audio pipeline sentence streaming + pre-tool / post-tool 两段 TTS** 落地
所需的全部既有事实。文档只描述现状,不含设计方案,不修改任何源代码。

下游 stage 拆分时,直接基于本文档"§5 瓶颈标注"与"§7 未解明问题"开工。


---

## 1. WebSocket message protocol 现状

WS 端点定义在 `/Users/liujunhong/Desktop/MomoOS-v2/backend/routes/ws.py:1163-1217`
(`@router.websocket("/ws")`)。所有 send_json 站点已用 grep 全量盘点。

### 1.1 Client → Server

| type | 字段 schema | payload 样例 | 定义位置 |
| --- | --- | --- | --- |
| `text` | `content: str`, `user_id: str`, `conversation_id?: int`, `character_id?: int` | `{"type":"text","content":"今天天气","user_id":"default","conversation_id":12,"character_id":1}` | `backend/routes/ws.py:17-19`(协议注释)+ `frontend/src/hooks/useWebSocket.ts:513-519`(实际 send) |
| `voice` | `audio: str(base64 wav)`, `user_id: str`, `conversation_id?: int`, `character_id?: int` | `{"type":"voice","audio":"UklGRiQAAAB...","user_id":"default", ...}` | `backend/routes/ws.py:19` + `frontend/src/hooks/useWebSocket.ts:543-549` |
| `interrupt` | (无字段) | `{"type":"interrupt"}` | `backend/routes/ws.py:20`,`1186-1189` + `frontend/src/hooks/useWebSocket.ts:581` |
| `touch` | `user_id: str`, `conversation_id?: int`, `character_id?: int` | `{"type":"touch","user_id":"default","conversation_id":12,"character_id":1}` | `backend/routes/ws.py:21-23`,`802-806` + `frontend/src/hooks/useWebSocket.ts:616-621` |

### 1.2 Server → Client

下表"chat 主路径"列表示该 type 是否在 `_handle_message` 走的主对话流中出现;
"proactive 路径"指 `backend/proactive/engine.py:227+` 的主动触发流(同结构,
携带 `proactive=true` + `proactive_trigger` meta);"后台 push"是
`ConnectionManager.push`(`backend/routes/ws.py:104-107`)的旁路推送。

| type | 字段 schema | 真实 payload 样例 | 主源位置 |
| --- | --- | --- | --- |
| `asr_result` | `content: str`, `message_id: int \| None` | `{"type":"asr_result","content":"今天天气","message_id":4127}` | `backend/routes/ws.py:797-801` |
| `text_chunk` | `content: str`, *(可选)* `proactive: true`, `proactive_trigger: str` | `{"type":"text_chunk","content":"嗯,让我看看。"}` | `backend/routes/ws.py:1021-1025` ; proactive 版 `backend/proactive/engine.py:438-442`,`756-758` |
| `audio_chunk` | `content: str(base64 wav, 24kHz mono 16bit)`, *(可选)* `proactive` meta | `{"type":"audio_chunk","content":"UklGRsQ..."}` | `backend/routes/ws.py:895-897` ; proactive 版 `backend/proactive/engine.py:361-367`,`717` |
| `emotion` | `value: str`(中文情感词,如 "开心" / "默认") | `{"type":"emotion","value":"开心"}` | `backend/routes/ws.py:945-948` ; proactive 版 `backend/proactive/engine.py:390-395`,`737` |
| `thinking` | `value: str`(LLM 内心独白) | `{"type":"thinking","value":"用户想看天气..."}` | `backend/routes/ws.py:970-973` ; proactive 版 `backend/proactive/engine.py:400-405` |
| `motion` | `value: str`(中文动作名,如 "放松" / "撒娇") | `{"type":"motion","value":"撒娇"}` | `backend/routes/ws.py:987-990` ; proactive 版 `backend/proactive/engine.py:408-414`,`742` |
| `state_update` | `character_id: int`, `mood: str`, `intimacy: int`, `thought: str\|None`, `activity: str\|None` | `{"type":"state_update","character_id":1,"mood":"happy","intimacy":42,"thought":null,"activity":null}` | `backend/routes/ws.py:510-517`(主路径 wrap `_apply_and_push_state_update`)+ `backend/capabilities/character_state.py:125-132` + `backend/proactive/engine.py:257`(常量声明)+ `backend/routes/character_state_api.py:69` |
| `tool_use_start` | `tool_name: str` | `{"type":"tool_use_start","tool_name":"apple_calendar.today_events"}` | `backend/agents/chat.py:1499-1501`(yield)→ `backend/routes/ws.py:910-916`(透传) |
| `tool_use_done` | `tool_name: str`, `duration_ms: int` | `{"type":"tool_use_done","tool_name":"apple_calendar.today_events","duration_ms":1843}` | `backend/agents/chat.py:1513-1519` → `backend/routes/ws.py:910-916` |
| `done` | `interrupted?: bool` | `{"type":"done"}` 或 `{"type":"done","interrupted":true}` | `backend/routes/ws.py:1101`(正常)、`1148`(打断);proactive `backend/proactive/engine.py:474-478` |
| `error` | `message: str` | `{"type":"error","message":"ASR failed: ..."}` | `backend/routes/ws.py:770`,`777`,`811`,`1063`,`1158` |
| `notify` | `content: str` | `{"type":"notify","content":"early bedtime"}` | 来自后台任务,通过 `connection_manager.push` 投递;前端 handler `frontend/src/hooks/useWebSocket.ts:332-334` |
| `alarm` | `content: str`, `todo_id: int` | `{"type":"alarm","content":"吃药","todo_id":31}` | `backend/scheduler/task.py:129-132` |
| `activity_permission_missing` | `hint: str` | `{"type":"activity_permission_missing","hint":"在 设置 → 隐私 → ..."}` | `backend/main.py:458-461` |

前端 union 类型与所有 case 分支在
`frontend/src/hooks/useWebSocket.ts:13-44`(WsMessage interface)+
`137-364`(`handleMessage` switch)。


---

## 2. 当前 TTS streaming 行为

### 2.1 调用入口与节流

主入口 `_tts_synth_with_timeout`,定义于
`backend/routes/ws.py:147-186`。每句独立调用,被 `asyncio.Semaphore(3)`
(`backend/routes/ws.py:134-136`)节流,单句 10 s 超时
(`TTS_TIMEOUT_S = 10.0`,`backend/routes/ws.py:135`)。

调用方式:**已经是 "句级" 而非整段 buffer**。`ChatAgent.stream()`
(`backend/agents/chat.py:1323-1540`)在 `_safe_boundary` 命中
(`backend/agents/chat.py:1428-1444`)时 yield 一句,ws.py 立刻
`asyncio.create_task` 一个合成任务并入队
(`backend/routes/ws.py:1031-1039`):

```python
# backend/routes/ws.py:1031-1039
if get_tts_enabled():
    task = asyncio.create_task(
        _tts_synth_with_timeout(
            tts_engine, sentence, turn_emotion,
            idx=sentence_idx,
        )
    )
    pending_tts.append(task)
    await audio_queue.put(task)
```

### 2.2 音频发送

发送链路:

1. Producer:每句一个 `asyncio.Task` 入 `audio_queue`
   (`backend/routes/ws.py:892`)。
2. Consumer:`_tts_audio_consumer`(`backend/routes/ws.py:189-213`)按
   FIFO `await` task,拿到 bytes 后调 `_send_audio`。
3. `_send_audio`(`backend/routes/ws.py:895-897`):

   ```python
   async def _send_audio(audio: bytes) -> None:
       audio_b64 = base64.b64encode(audio).decode()
       await ws.send_json({"type": "audio_chunk", "content": audio_b64})
   ```

每条 `audio_chunk` 携带**单句的完整 WAV bytes**(base64 后塞 JSON),
不是子句切片。一句 = 一次 `audio_chunk` 推送。binary frame 路径不存在,
全部走 JSON。

### 2.3 CosyVoice vs Edge-TTS 行为对比

| 项 | CosyVoice (`backend/tts/cosyvoice.py`) | Edge-TTS (`backend/tts/edge.py`) |
| --- | --- | --- |
| 调用形态 | `asyncio.to_thread` 包同步 SDK,**一次返回完整 WAV bytes**(`backend/tts/cosyvoice.py:167-168`,`186-188`) | 内部 `edge_tts.Communicate.stream()` 按帧拿,**循环 append 后整合**(`backend/tts/edge.py:44-50`) |
| 输出格式 | WAV 24kHz mono 16bit(`backend/tts/cosyvoice.py:140`) | MP3 默认 |
| 单句失败 | 返 None,`_tts_synth_with_timeout` 跳过(`backend/routes/ws.py:178-186`) | raise → `_tts_synth_with_timeout` `except Exception` 兜底 |
| emotion 支持 | 走 `instruction` 字段,**仅 instruct 白名单音色生效**(`backend/tts/cosyvoice.py:69-74`,`125-165`) | 完全忽略 `emotion` 参数(`backend/tts/edge.py:26-50`) |
| 文本预处理 | `_PreprocessingEngine` 包装层 `backend/tts/__init__.py:211-232` 跑 `preprocess_tts_text`(剥 `<emotion>` / `<thinking>` / `<state_update>` / 动作描述等) | 同上,共享同一层包装 |

**统一接口**:两者都实现 `TTSBase.synthesize(text, emotion)`
(`backend/tts/base.py:48-60`),`get_tts_engine`
(`backend/tts/__init__.py:263-276`)按 `character.voice_model` JSON 路由,
ws.py 调用层不区分。所以 chunk 15 改 producer/consumer 模式时,两个 backend
行为对外一致。**当前两者都是 "整句 buffer 后一次返回",没有子句级
streaming**——这对 chunk 15 的 pre-tool / post-tool 两段切分**没有阻碍**,
但意味着无法在"一句话还没合成完时"先推一部分 audio。


---

## 3. UX-004 v1 过渡语 prompt segment

### 3.1 完整 system prompt 片段

定义在 `backend/agents/chat.py:486-517`,常量 `_TOOL_BEHAVIOR_BLOCK`:

```python
# backend/agents/chat.py:503-517
_TOOL_BEHAVIOR_BLOCK = (
    "【工具调用行为】\n"
    "当你需要调用工具(查日历 / 看今日活动 / 查歌单 / 看 B 站 / 查网页 / "
    "看剪贴板 / 等)时,**必须先输出一句简短的过渡语**(6-15 字)让用户知道你在"
    "查询,然后再触发工具调用。\n\n"
    "过渡语要自然贴合你的人设,不要每次重复同一句。例如:\n"
    "  - \"嗯,让我看看\"\n"
    "  - \"等我查一下\"\n"
    "  - \"稍等,我看看日历\"\n"
    "  - \"好,我去查查\"\n"
    "  - (按当前角色 persona 自然变体)\n\n"
    "绝对避免:\n"
    "  - 直接 silent 调用工具不说话(用户体感'app 卡死')\n"
    "  - 过渡前输出长篇分析或解释(把分析留到工具返回后)"
)
```

注入点:`_build_messages` 把它紧贴 persona 之后追加到 system prompt
(`backend/agents/chat.py:1145-1152`):

```python
head_parts = [emotion_inst, thinking_inst, motion_inst, state_inst]
if base:
    head_parts.append(base)
head_parts.append(persona_block)
# UX-004: 过渡语行为规范紧贴 persona 之后, ...
head_parts.append(_TOOL_BEHAVIOR_BLOCK)
```

### 3.2 过渡语 / 最终回复的边界标记

**目前完全没有显式 marker / 分隔符**。LLM 输出形如:

```
<emotion>开心</emotion>嗯,让我看看。
[此处 OpenAI tool_call delta 到达,backend 走 finish_reason="tool_calls"
执行 tool,然后第二次 LLM 调用接续 text delta]
今天有一个 14:00 的会议,在 A 区。
```

句级拆分由 `_safe_boundary`(`backend/agents/chat.py:350-370`)统一切,
**过渡语句和最终回复句在 stream 层不可区分**。唯一的"信号"是 stream 中间
插入的 `tool_use_start` / `tool_use_done` typed event(`chat.py:1501`,
`1515-1519`)—— 通过观察事件序列即可推断:

- `tool_use_start` 之前出现的 `text_chunk` = 过渡语
- `tool_use_done` 之后出现的 `text_chunk` = 最终回复

但 backend 当前没有利用这一边界对 TTS 流做切分,**所有句子统一进 audio
producer 队列**,前端也只看到一个连续的 `audio_chunk` 序列。这是 chunk 15
要利用的关键 hook。

### 3.3 实测样本(从 chat.py 注释 + 实地观察推断)

正常 tool-use 轮次的 stream yield 序列(`chat.py:1444`,`1501`,`1515`,
`1530-1538`):

```
yield "嗯,让我看看。"              # 过渡语,sentence_idx=1
yield {"type":"tool_use_start", "tool_name":"apple_calendar.today_events"}
yield {"type":"tool_use_done",  "tool_name":"apple_calendar.today_events", "duration_ms":1843}
yield "今天 14:00 有 A 区会议。"   # 最终回复,sentence_idx=2
yield "记得别迟到哦。"             # 最终回复,sentence_idx=3
```

ws.py 把所有 sentence 同时 spawn TTS task + send `text_chunk`;但因为
audio_queue 是 FIFO 顺序消费,**用户体感**是:文字 `text_chunk` 飞快到齐
(因为不等 audio),audio 则要等所有句的 TTS 合成完才能依次播——过渡语 audio
被卡在 tool 执行之后(因为 tool 是 sequential 阻塞在 stream 内部,见
`chat.py:1492-1524`)。23 s 沉默瓶颈见 §5。


---

## 4. Frontend audio chunk 接收 + 播放

### 4.1 接收 handler

`frontend/src/hooks/useWebSocket.ts:210-228`:

```ts
case 'audio_chunk': {
  if (!s.ttsEnabled) break;
  if (msg.content) {
    const audio = new Audio(`data:audio/wav;base64,${msg.content}`);
    pipeAudioElement(audio);              // 接进 WebAudio 分析图(口型同步)
    audioQueueRef.current.push(audio);
    if (s.status !== 'speaking') {
      s.setStatus('speaking');
      if (s.muteWhileSpeaking) s.setMicMuted(true);
    }
    playNextAudio();
  }
  break;
}
```

每条 audio_chunk → `new Audio(...)` HTMLAudioElement,push 到 ref 队列
`audioQueueRef`(`useWebSocket.ts:60`),立刻调 `playNextAudio()`。

### 4.2 播放队列

实现:`playNextAudio` `frontend/src/hooks/useWebSocket.ts:74-135`。

- 单 in-flight 锁:`isPlayingRef.current` 标位,保证**严格串行**
  (`useWebSocket.ts:75,87,110`)。
- 推进事件三重兜底(`useWebSocket.ts:88-132`):
  1. `ended` 事件
  2. `error` 事件(单段崩了不卡队列)
  3. wall-clock setTimeout(loadedmetadata 拿到 duration → 精确兜底;
     否则 30 s 极端兜底)
- 队列排空时回 idle + 解除 mic 静音(`useWebSocket.ts:77-85`)。

### 4.3 WebAudio 接管

`pipeAudioElement`(`frontend/src/lib/ttsAudio.ts:44-71`)把每个新 audio
元素 `createMediaElementSource` 接进 TTS AudioContext,
connect 到 `_analyser`(`ttsAudio.ts:27-42`)再 connect 到 `destination`。
分析节点供 `useAudioAmplitude` 给 Live2D 口型同步取振幅。
**关键陷阱**(`ttsAudio.ts:15-20`)`createMediaElementSource` 对同一元素只能
调一次,每条 audio_chunk 新建元素这点必须保留。

### 4.4 多段串行播放能力

**已支持,且实际就是这么用的**。每条 audio_chunk → 队列一段,
playNextAudio 严格 FIFO 串行。chunk 15 引入"过渡语 audio + 最终回复
audio"两段时,**前端无需改动队列实现**——只是入队的段更多,串行串就行。

打断收尾(`useWebSocket.ts:251-265`)和 touch 复位
(`useWebSocket.ts:595-605`)会清空队列;chunk 15 也需复用这些清理路径。


---

## 5. Message flow 时序(含瓶颈标注)

### 5.1 当前流程(纯文字输入,触发一次 tool 调用)

```
[T=0]   用户在 ChatInput 输入 "今天有什么会"
        useWebSocket.sendText() → ws.send({"type":"text",...})
                                         frontend/src/hooks/useWebSocket.ts:484-520

[T=Δ]   backend ws.py 收到 → _handle_message()
        backend/routes/ws.py:740-1110

[T=~50ms]  call_llm(stream=True, tools=...) 启动第 1 轮 LLM
           backend/agents/chat.py:1391-1402

[T=~3-5s]  LLM 输出过渡语 "嗯,让我看看。"
           _safe_boundary 命中 → yield sentence
              ↓ ws.py 收到 sentence:
              ↓   1. 推 text_chunk(立即,frontend 显示文字 ✓)
              ↓   2. spawn TTS task(并发,但要排队 audio_queue)
              ↓
           LLM 继续输出 tool_call delta(accumulator)
           finish_reason="tool_calls" → 退出 inner async-for

[T=~5s]    yield {"type":"tool_use_start", "tool_name":"..."}
           ws.py 透传 → frontend 点亮 loading pill
              ★★ 此时过渡语 audio 已经在排队,但因 tool 执行阻塞
                 在同一 coroutine 内,audio 实际何时被合成 / 推送
                 取决于 _tts_semaphore 与 to_thread 调度 ★★

[T=~5s+]   await _execute_tool(...)   ← **沉默瓶颈起点**
           backend/agents/chat.py:1503-1506
           工具执行同步阻塞 stream 协程,期间:
              - 没有新 sentence yield
              - 但已 spawn 的 TTS task 仍在后台跑(理论上)
              - audio_consumer 一旦拿到首个合成完成的 task → send audio_chunk
              - 实际观测:消费链路常被工具同 event-loop 调度饿死,
                audio 与 text 一起在 tool 完成后才到 frontend

[T=~5+18s] tool 返回 → yield tool_use_done
           messages.append(tool result) → 进入第 2 轮 LLM(continue 循环)
           backend/agents/chat.py:1492-1526

[T=~23s]   第 2 轮 LLM 输出最终回复 sentence 流
           "今天 14:00 有 A 区会议。" / "记得别迟到哦。"
           → text_chunk 立即推、TTS spawn

[T=~23-25s] audio_consumer 顺序播:
            过渡语 audio → 最终回复 audio[1] → 最终回复 audio[2]
            **用户体感:23 s 沉默后,过渡语 + 最终回复一起冒出**
```

### 5.2 瓶颈定位(三处叠加)

| # | 位置 | 性质 | 是否 chunk 15 要解 |
| --- | --- | --- | --- |
| **B1** | `chat.py:1503-1506` `_execute_tool` 同步阻塞在 ChatAgent.stream 内 | 工具执行期间 stream 不出新 token,但 audio_queue consumer 也在同一 event loop——**audio_chunk 实际推送被卡** | **是**(根因) |
| B2 | `ws.py:1042-1044` `await consumer_task` 等所有 audio 发完才发 `done` | 正常完成路径下,frontend 收到 done 时所有 audio 已入队 | 否(行为正确) |
| B3 | CosyVoice `to_thread` 单句网络往返 ~1-3 s | 单句固定开销,无法去除;chunk 15 关心的是"过渡语 audio 先于 tool 完成被推" | 否(可接受) |

**核心症结(B1)**:即便过渡语的 TTS task 已经 spawn,consumer 仍然要顺序
`await audio_queue.get() → await task`(`ws.py:198-213`);
但 LLM stream 主循环 `async for chunk in wrapper` 不让出控制权时——
特别是 `_execute_tool` 是 `await` 的同步性工具——audio_chunk send_json 也
排在同一队列后面执行。**实测体感是 audio 与 text 都被工具阻塞了**,即使
frontend 端的 text_chunk loading pill 提前点亮(LLM 边解码边 yield),
audio 仍然等到 tool 全部完成才到达。

### 5.3 chunk 15 / UX-006 目标流程(供对照,**未实施**)

```
T=0    用户输入
T=3s   过渡语 yield → text_chunk + audio_chunk(pre-tool TTS,独立合成 + 立即 flush)
T=4s   过渡语 audio 在 frontend 开始播放 ★ 沉默期消失 ★
T=5s   tool_use_start(loading pill 接力)
T=5-23s tool 执行
T=23s  tool_use_done
T=23-25s 最终回复句级流(post-tool TTS),每句 audio 落地即播
```

可行性已存在(producer/consumer 已经是按句的),**改的是 "在 tool 执行之
前把过渡语 audio 主动 flush 到 ws,并在 send_json 前 yield 控制权"**,
而不是大改架构。


---

## 6. 已知约束 & helper 盘点

### 6.1 句子拆分 helpers(已有,可复用)

| helper | 位置 | 语义 |
| --- | --- | --- |
| `split_sentences(text)` | `backend/tts/base.py:25-34` | 一次性切完;按 `。！？!?` 切,保留尾标点。当前仅 `tts_manager`(旧路径)使用,主路径不调 |
| `_find_boundary(text)` | `backend/agents/chat.py:340-347` | 流式版,找第一个句末位置 |
| `_safe_boundary(buf)` | `backend/agents/chat.py:350-370` | thinking / fallback tool_call 标签感知的 boundary——**当前 ChatAgent.stream 实际用的就是这个**(`chat.py:1431`) |
| `_sentence_stream(token_gen)` | `backend/agents/chat.py:373-393` | 模板化的 token→sentence buffer(可直接套用) |
| `has_partial_open_tag(buf)` | `backend/utils/text_filters.py:362+` | 标签未闭合检测,`_safe_boundary` 内部用 |

frontend 没有 sentence tokenizer——前端只串行播放 backend 推过来的整段
audio_chunk,无需切分。

### 6.2 TTS 文本预处理与剥离

- `preprocess_tts_text(text)` `backend/tts/__init__.py:65-92` ——
  TTS 合成前最后一道兜底,自动跑在 `_PreprocessingEngine` 包装层
  (`backend/tts/__init__.py:211-232`)。
- `strip_all_for_tts(text)` `backend/utils/text_filters.py:236-251` ——
  统一剥 emotion / thinking / state_update / motion / tool_call fallback 五道。
- 主路径在每句 push 到 ws 前再跑一遍 `strip_all_for_tts`
  (`backend/routes/ws.py:1018-1020`)+ proactive 路径同语义
  (`backend/proactive/engine.py:435-437`)。
- chunk 15 拆分过渡语 / 最终回复后**剥离链路无需改动**——同一函数继续
  覆盖。

### 6.3 Pre-tool / Post-tool 可挂载 hook 点

- `chat.py:1499-1501` 是**唯一的 pre-tool yield 点**:`yield
  {"type":"tool_use_start","tool_name":name}`。chunk 15 可以在此处之前
  flush 累积的过渡语 sentence buffer。
- `chat.py:1513-1519` 是 post-tool yield 点。第二次 LLM 调用从下次循环
  `while True:` 顶部接着开始(`chat.py:1525-1526` `continue`)。
- **目前 ws.py 不基于这两个事件做 audio queue 分段** —— consumer 一根管子
  顺序处理。chunk 15 改造重心:让 audio_queue 在 `tool_use_start` 事件
  到来时主动等已入队 task 全部 flush 再放行,或拆两个独立 audio_queue
  (pre / post)。

### 6.4 下游 consumer 盘点(改 message 拆分时要看的地方)

Grep `audio_chunk / text_chunk` 命中文件:

**Backend(发送侧):**
- `backend/routes/ws.py:1021,1025,895-897` — 主路径
- `backend/proactive/engine.py:364,438-442,717,756-758` — proactive 路径
- `backend/scheduler/briefing.py:8` — 注释:全部走 audio_chunk 推送

**Frontend(消费侧):**
- `frontend/src/hooks/useWebSocket.ts:157-227` — 唯一接收 + 入队点
- `frontend/src/store/index.ts:27` — `streaming` 字段语义注释
- `frontend/src/lib/ttsAudio.ts` — WebAudio 分析图(只关心元素,不关心分段)
- `frontend/src/lib/textFilters.ts` — 前端兜底剥标签(只看 chunk 内容,不
  关心边界)

**Tests:**
- `tests/test_morning_briefing.py`、`tests/test_wake_call_briefing.py`、
  `tests/test_hotfix7_proactive_strip.py`、`tests/test_integration.py`、
  `tests/test_proactive_engine.py` — 都断言 audio_chunk 数量 / 内容 /
  payload 结构。**chunk 15 拆分 audio_chunk 边界后,这些测试需逐个核
  对断言条件**。

### 6.5 改造前置依赖

1. **打断路径必须同步改**。`_request_interrupt`
   (`backend/routes/ws.py:721-733`)cancel `pending_tts` 全部 task;若
   chunk 15 引入两个独立 audio_queue 或 marker task,interrupt 收尾要
   一并 cancel。
2. **proactive engine.py 走的是同一组 helper**(`_tts_audio_consumer`
   / `_tts_synth_with_timeout` 都从 `backend.routes.ws` import),
   `backend/proactive/engine.py:375,447`。改 helper 时 proactive 路径
   会自动跟着变——好处是不必双改,坏处是回归面同步扩大。
3. **frontend 没有 done-per-segment 的概念**。chunk 15 若要让前端知道
   "过渡语段结束、最终回复段开始",需要新增一个 marker message
   type(例如 `tool_use_start` 本身就已经是天然边界,不必新引入)。
4. **ws.send_json 没有 backpressure 机制**。FastAPI WebSocket 在 task
   阻塞时无锁,多个 await send_json 并发会丢消息或乱序;现有
   consumer 单 task 顺序 send 是必要约束,chunk 15 要保留。


---

## 7. Audit 中未解明的问题(留给顾问决策)

下列每一条都直接影响 stage 拆分,不要省。

### Q1. 过渡语 audio 是否应该和最终回复 audio 走同一个 `audio_chunk` 类型?

- **现状**:只有一种 `audio_chunk`。
- **选项 A**:复用同 type,前端串行播放即可——逻辑简单,但前端无法
  在 UX 上区分"过渡语 audio 还在播"vs "最终回复 audio 在播"。
- **选项 B**:新增 `audio_chunk` 的 `segment: "pre_tool" | "post_tool"`
  字段——前端可在 pre_tool 期间额外渲染 loading,post_tool 接力时
  无缝过渡。
- 顾问需明确:**前端是否需要按 segment 类型做不同 UX?** 这决定
  WS schema 是否要扩字段。

### Q2. 过渡语合成失败时 fallback 策略

- 当前单句失败 = `_tts_synth_with_timeout` 返回 None,consumer skip。
- 过渡语失败时,最终回复 audio 仍会播。**但用户已经看到 text_chunk
  loading pill 点亮,听不到声音会怀疑 TTS 坏**——是否要把过渡语
  失败计数提到 metric 层?还是降级 ASR-style 通知?

### Q3. `_execute_tool` 阻塞主 stream 协程的根因要不要在 chunk 15 一并解?

- B1 的根本是 `_execute_tool` 在 `chat.py:1503-1506` `await` 时持有
  stream 协程控制权;若工具是 CPU-bound 同步包装,async event loop
  本身被霸占。
- **如果 chunk 15 只把过渡语 TTS 提前 flush,但 _execute_tool 仍卡
  loop,frontend 仍可能感受到 audio_chunk 推送延迟**(`ws.send_json`
  也要事件循环让出)。
- 解 B1 通常做法:把 `_execute_tool` 包 `asyncio.to_thread` 或加
  `await asyncio.sleep(0)` yield 点。**chunk 15 是否承诺解这条?**
  如果不解,过渡语 audio 提前 flush 的实际增益可能仍打折扣。

### Q4. 过渡语 6-15 字硬约束 vs LLM 实际输出长度

- 当前 prompt 写 "6-15 字"(`chat.py:506`),qwen 3.6 实测大多数走
  这个区间,但偶发输出 25 字以上的"前导分析+过渡"混合句。
- **chunk 15 是否要在 backend 做"过渡语长度兜底裁剪"**?如果做,
  在哪个层(LLM 后处理 / TTS 前处理)?如果不做,过长过渡语会
  让 pre-tool TTS 自己也成新瓶颈。

### Q5. 多 tool 连续调用(per-round)的 audio 切分

- ChatAgent.stream 支持 max 5 轮 tool loop(`chat.py:1379-1389`)。
  如果一轮里 LLM 调 2 个 tool(`apple_calendar.today_events` +
  `time.now`),会出现:
  ```
  过渡语 → tool_A_start → tool_A_done → tool_B_start → tool_B_done → 最终回复
  ```
  或更复杂:每个 tool 之间 LLM 还能再插一句"再让我看看时间"。
- **chunk 15 的 "pre-tool / post-tool 两段"模型在多 tool 场景如何
  退化?** 是每个 tool 之间都允许一段过渡语 audio,还是只切 0 / N
  两段?

### Q6. 整轮 emotion 锁定 vs 过渡语和最终回复情绪不一致

- `turn_emotion` 第一句锁定(`ws.py:854-856,927-934`),整轮 TTS 共
  用同一 emotion 参数。但 LLM 输出形如 "嗯,让我看看。"(中性)
  +"今天没安排,可以放松一下!"(开心)是常见的——过渡语和最终
  回复用同一情感会让最终回复显得平淡。
- **chunk 15 是否要允许在 tool_use_done 之后重新解析 emotion 标签
  (per-segment 而非 per-turn)?** 这牵涉到 prompt 改造(让 LLM 在
  post-tool 段重新打 `<emotion>` 标签),不仅是 pipeline 改动。

### Q7. proactive 路径是否需要同步引入 pre-tool / post-tool 分段?

- proactive 触发(早安简报 / 主动唤起)目前少有 tool 调用——但简报
  类未来会接 calendar / activity timeline。
- **chunk 15 改造是只覆盖 ws.py 主路径,还是把 helper 改完让
  proactive engine.py 自动跟上?** 测试覆盖面差一倍。

### Q8. interrupt 路径在新切分模型下的 partial reply 写库语义

- 当前 `_save_interrupted_turn`(`ws.py:651-718`)把 `reply_parts`
  整段 join,标 `interrupted_at`。如果 chunk 15 引入"过渡语段"与
  "最终回复段"的分段概念,被打断时是否要:
  - (A)合并写一行(现状语义)
  - (B)拆两行 `kind` 分别记
  - (C)只记最终回复段(过渡语没意义)
- **顾问需在 chunk 15 stage 拆分前定调**,否则 `interrupted_at` 字段
  语义在 chat_history 表里会含糊。


---

Audit 完成时间:2026-05-13 / git commit `d22ff4a` (`d22ff4a40fb398363166b90a5e6d072c644bac34`)
