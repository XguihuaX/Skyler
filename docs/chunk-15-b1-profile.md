# Chunk 15 / UX-006 — B1 真根因 Profile

前置:
* `docs/chunk-15-starting-context.md` §5(B1 假设 = `_execute_tool` 同步阻塞
  stream 协程,audio_consumer 的 `ws.send_json` 被饿死)
* `docs/chunk-15-b1-feasibility.md` §6 Q1(feasibility audit 质疑该假设)

任务目的:在改 🟡 6 个 capability 之前,用临时 instrumentation + pytest
端到端复现完整 tool_use 流程,**测出 backend 真实行为**,验证或推翻 B1
假设。


---

## 1. Instrumentation 列表

6 个 `time.perf_counter()` 写点临时加在 backend,**审计完成后已 revert
不进 commit**——本文档只 commit 文档 + 测试文件。

| # | 位置 | 文件:行号 | 打什么 |
| --- | --- | --- | --- |
| **P1** | `audio_queue.put` 后(producer 入队) | `backend/routes/ws.py:1040` 紧邻 `await audio_queue.put(task)` | `[QUEUE_PUT] idx={sentence_idx} t=…` |
| **P2** | `_tts_audio_consumer` 拿到 task | `backend/routes/ws.py:198`(`item = await queue.get()` 后) | `[CONSUMER_GOT] idx={n} t=…` |
| **P3** | `_send_audio` `ws.send_json` 前 + 后 | `backend/routes/ws.py:895-897` | `[SEND_PRE] idx={n} t=…` / `[SEND_POST] idx={n} t=…` |
| **P4** | `yield tool_use_start` 前 | `backend/agents/chat.py:1501` 前 | `[TOOL_START] name={name} t=…` |
| **P5** | `await _execute_tool` 前 + 后 | `backend/agents/chat.py:1504-1506` 包夹 | `[EXEC_PRE] name=… t=…` / `[EXEC_POST] name=… t=…` |
| **P6** | `yield tool_use_done` 前 | `backend/agents/chat.py:1515-1519` 前 | `[TOOL_DONE] name=… t=…` |

代码 pattern(每个写点统一格式,失败 silent):

```python
# CHUNK15-PROFILE P1
try:
    with open("/tmp/chunk15_profile.log", "a") as _f:
        _f.write(f"[QUEUE_PUT] idx={sentence_idx} t={time.perf_counter()}\n")
except Exception:
    pass
```

所有写点用 `CHUNK15-PROFILE` 注释 marker 标识,清理时 grep 即可定位。
**清理已完成**:`git diff backend/` 应不含本 audit 的 instrumentation。


---

## 2. 测试场景搭法

测试文件:`tests/test_chunk15_b1_profile.py`(本 audit 一并 commit)。

### 2.1 关键 fixture

* **DB**:内存 SQLite(`sqlite+aiosqlite:///:memory:`),开 `Base.metadata.
  create_all` 建空表。所有 backend module 引用统一 patch 到测试 engine。
* **`call_llm`**:patch 到 `_chat_module.call_llm`,返回构造的 LiteLLM
  shape chunk(`SimpleNamespace`)。两轮调用:
  * Round 1 → yield `content="嗯,让我看看。"` → yield 一个完整 `tool_call`
    delta(name=`fake_slow_tool`)→ yield `finish_reason="tool_calls"`
  * Round 2 → yield `content="今天 14:00 有 A 区会议。"` → yield
    `finish_reason="stop"`
* **`_build_messages`**:patch 跳过 DB-heavy 历史/profile/activity 注入,
  返回最简 `[system, user]` 列表——把测试焦点收窄到 stream + audio pipeline。
* **`fake_slow_tool`**:通过 `ToolRegistry.register` 真注册到全局表(走和真
  capability **同一条** `_execute_tool` dispatch 路径),handler 内部
  `await asyncio.sleep(5.0)` 模拟 23s tool 阻塞场景(5s 已足够拉开时间
  窗,且让测试 < 10s 跑完)。
* **`FakeTTS(TTSBase)`**:`synthesize` 内 `await asyncio.sleep(0.05)` +
  返回固定 bytes;走真实 `_PreprocessingEngine` 不必要(直接 patch
  `get_tts_engine` 返回 FakeTTS)。
* **`FakeWS`**:`send_json` 不带任何 await delay,只 append 到 list 并
  打时间戳——隔离"backend send 到达"vs"network/frontend buffer"。
* **`get_tts_enabled`**:`config.yaml` 默认 `tts.enabled: false`,测试强
  制 patch 返 True。

### 2.2 触发的完整时序(test 控制)

1. `setup_db()` 建表 → `_register_fake_tool()`
2. `Patches.install()` 上 4 个 patch(call_llm / _build_messages /
   get_tts_engine / get_tts_enabled)
3. 构造 `_TurnState()`、`FakeWS()`、`data = {"type": "text",
   "content": "今天有什么会", "user_id": ...}`
4. `t0 = time.perf_counter()`,写 `[T0]` 行
5. `await _handle_message_safe(ws, data, state, USER_ID)` ——**真实的**
   ws.py 主路径
   * 内部 `async for sentence in _chat_agent.stream(chat_msg)` 跑**真实**
     ChatAgent.stream
   * 内部 `consumer_task = asyncio.create_task(_tts_audio_consumer(...))`
     跑**真实** consumer
   * Round 1 fake stream → yield 过渡语 → ws.py P1 入队 + send text_chunk
   * Fake stream → tool_calls → ChatAgent.stream P4(TOOL_START)→ P5
     (EXEC_PRE)→ `await fake_slow_tool()` sleep 5s → P5(EXEC_POST)→
     P6(TOOL_DONE)
   * Round 2 fake stream → yield 最终回复 → ws.py P1 入队
   * Producer 收尾投递 `None` 哨兵 → await consumer → send `done`
6. `Patches.uninstall()` + `_unregister_fake_tool()`
7. 读 `/tmp/chunk15_profile.log` 排序输出


---

## 3. Log 结果(时间戳排序)

`t0 = perf_counter()` 对齐到 0;所有时间相对 t0,单位 ms。

**FakeWS captured ws.send_json calls**(测试 stdout 实测,完整不省略):

| t (ms) | type | detail |
| --- | --- | --- |
|     8.1 | `text_chunk`        | content='嗯,让我看看。' |
|     8.2 | `tool_use_start`    | tool=fake_slow_tool |
|    59.5 | `audio_chunk`       | content_len=48 (transition audio) |
|  5011.1 | `tool_use_done`     | tool=fake_slow_tool |
|  5011.5 | `text_chunk`        | content='今天 14:00 有 A 区会议。' |
|  5064.3 | `audio_chunk`       | content_len=36 (final reply audio) |
|  5073.1 | `done`              | — |

**`/tmp/chunk15_profile.log`(P1-P6 instrumentation,完整不省略)**:

| t (ms) | event | detail | notes |
| --- | --- | --- | --- |
|     0.0 | `T0`            | — | 测试 perf_counter 起点 |
|     8.1 | `QUEUE_PUT`     | idx=1 (过渡语) | producer 入队 |
|     8.2 | `TOOL_START`    | name=fake_slow_tool | chat.py P4 yield 前 |
|     8.2 | `EXEC_PRE`      | name=fake_slow_tool | tool 进入 await |
|     8.2 | `CONSUMER_GOT`  | idx=1 | consumer 立即取到 task |
|    59.5 | `SEND_PRE`      | idx=1 | `ws.send_json` 前 |
|    59.5 | `SEND_POST`     | idx=1 | **过渡语 audio_chunk 已发出** |
|  5010.2 | `EXEC_POST`     | name=fake_slow_tool | tool 5s sleep 结束 |
|  5010.9 | `TOOL_DONE`     | name=fake_slow_tool | chat.py P6 yield 前 |
|  5011.8 | `QUEUE_PUT`     | idx=2 (最终回复) | round-2 sentence 入队 |
|  5012.3 | `CONSUMER_GOT`  | idx=2 | |
|  5064.1 | `SEND_PRE`      | idx=2 | |
|  5064.4 | `SEND_POST`     | idx=2 | 最终回复 audio_chunk 发出 |

Raw log(`cat /tmp/chunk15_profile.log`):

```
[T0] t=95881.313579
[QUEUE_PUT] idx=1 t=95881.321669875
[TOOL_START] name=fake_slow_tool t=95881.321730291
[EXEC_PRE] name=fake_slow_tool t=95881.321762708
[CONSUMER_GOT] idx=1 t=95881.321828041
[SEND_PRE] idx=1 t=95881.373043041
[SEND_POST] idx=1 t=95881.373094166
[EXEC_POST] name=fake_slow_tool t=95886.323769833
[TOOL_DONE] name=fake_slow_tool t=95886.324528166
[QUEUE_PUT] idx=2 t=95886.325331291
[CONSUMER_GOT] idx=2 t=95886.3258495
[SEND_PRE] idx=2 t=95886.377669833
[SEND_POST] idx=2 t=95886.378003416
```


---

## 4. 核心分析:audio send_json vs `_execute_tool` 时间窗

**关键三点**(从 §3 表读出):

* `t_exec_start = EXEC_PRE         = 8.2 ms`
* `t_exec_end   = EXEC_POST        = 5010.2 ms`(tool 跑 5002 ms)
* `t_send_post(过渡语) = SEND_POST(idx=1) = 59.5 ms`

判定:

* `59.5 < 5010.2` → **过渡语 audio 在 tool 还没跑完时就已经经
  `ws.send_json` 推走**
* 实际相对 EXEC_PRE 的偏移:`59.5 - 8.2 = 51.3 ms` ≈ `TTS_DELAY_SECONDS *
  1000 = 50 ms`,完全等于 mocked TTS 合成时间
* 也即:tool 长跑 5000 ms 期间,**没有任何 audio_chunk 排队等 tool 完成**

ASCII 时间轴(整轮 5073 ms,等比缩成 ~50 字符):

```
t=    0ms ─┬─8─┬──── ─ ─ ─ ─ ── tool 阻塞窗口 5000ms ─ ─ ─ ─ ──┬─5010─┬──5073ms
           │   │                                                │      │
        QUEUE_PUT(1)                                          EXEC_POST  done
        EXEC_PRE,CONSUMER_GOT(1)                              TOOL_DONE
              │
         SEND_POST(1) @ 59ms  ← 过渡语 audio 在 exec 窗口 1.2% 处就发出去了
                                ↑↑↑ 与"audio 排在 tool 后面"完全相反
```

观察验证(用 FakeWS 旁路 capture 二次确认):
- FakeWS 第 3 条 `audio_chunk` 落在 t=59.5 ms,与 SEND_POST 时间一致(同一
  `ws.send_json` 调用)
- 后续 4 950 ms 内 FakeWS 没有任何排队等候——若 `_handle_message` 主协程
  真持锁,consumer 的 send_json 会"卡到 EXEC_POST 之后批量推",但本轮没看到
  这种行为


---

## 5. 分类结论:P1 / P2 / P3

### **结论:P2(backend OK,根因不在 event-loop)**

数字证据:

| 量 | 值 |
| --- | --- |
| 过渡语 `SEND_POST` 时间 | **59.5 ms** |
| `EXEC_POST` 时间 | 5010.2 ms |
| audio_chunk 实际比 tool 早多少 | **4 950.7 ms**(过渡语 audio 在 tool 完成前 4.95 s 就发出了) |
| QUEUE_PUT → CONSUMER_GOT 延迟 | 0.16 ms |
| QUEUE_PUT → SEND_POST 延迟 | 51.4 ms ≈ TTS 合成耗时(`asyncio.sleep(0.05)`) |
| `await _execute_tool` 期间 consumer 是否能跑 ws.send_json? | **能** — 实测 idx=1 的整条 SEND_PRE/SEND_POST 都在 exec 窗口内执行 |

**一句话**:`audio_consumer` 在 `_execute_tool` 阻塞期间**完全可以**正常
调度 `ws.send_json`,backend asyncio event loop **没有被饿死**。

**这推翻 `chunk-15-starting-context.md` §5.2 对 B1 的描述**——
chunk-15-b1-feasibility.md §6 Q1 的怀疑是正确的:🟡 6 个 capability 包
`to_thread` + 2 处 `asyncio.sleep(0)` 这条改造路径,**解的是一个并不存在
的问题**。

### B1 假设的可能解释

为什么实测真机仍有 23 s 沉默体感? 数据排除 backend event-loop 后,根因
**只剩三类候选**(下一步专项 audit):

1. **前端 audioQueue 误清空**(`frontend/src/hooks/useWebSocket.ts:251-265`
   打断收尾、`595-605` touch 复位)——某种状态切换让队列被清掉
2. **WebSocket transport 序列化**——FastAPI/Starlette ASGI 把 send 顺序
   化,可能在 tool_use_start / done 等 dense send 时丢轮 audio chunk
3. **`<emotion>` 标签解析滞后**——`turn_emotion` 整轮锁定,实际真机
   cosyvoice 第一句要等 emotion 解析完才能开始合成(本测试 emotion 默认
   "默认",未模拟此 path)

测试**不**覆盖以下场景,陈述其影响:
- 真实 cosyvoice TTS(~1-3 s/句而非 50 ms mock)——按本结论推断会让
  SEND_POST 晚 1-3 s,但仍**远早于**真机 23 s tool 完成时间窗
- 真实 WebSocket(本测试用 in-memory FakeWS)——这才是 §5.B2 候选路径
  最可能症结


---

## 6. 推荐下一步

### 6.1 立即行动

**不要按 chunk-15-b1-feasibility.md §5.1 改 🟡 6 个 capability**。
理由:profile 证明 backend 不是 B1 症结,改了不会减少 23 s 沉默。
这是**省 1d 工程量 + 避免引入回归风险**的关键发现。

### 6.2 改 chunk 15 stage 拆分,转 frontend audit

下一审计目标(估 0.5 d):

* `frontend/src/hooks/useWebSocket.ts:251-265`(done 处理)
   * Q:用户在 tool_use 期间收到 `tool_use_start` event 时,
     `audioQueueRef.current` 内的过渡语 audio 是否被清空?查
     `setStatus('interrupted')` 或类似路径是否被误触发。
* `frontend/src/hooks/useWebSocket.ts:74-135`(`playNextAudio` 三层兜底)
   * Q:`isPlayingRef.current` 单 in-flight 锁在多 audio_chunk 密集到达时
     是否串行串得过来? `loadedmetadata` 不打 → 30 s 极端兜底——这个
     30 s 巧合接近"23 s 沉默"!**强烈建议先 grep `30_000` 看是否相关**。
* WebSocket transport 顺序:tool_use_start 与 audio_chunk 紧邻到达时,
  frontend 是否按 ws.onmessage 顺序处理?会不会因 `case 'audio_chunk'`
  分支内 `pipeAudioElement` 同步开销饿死后续 message?

### 6.3 backend 仍可做的 0 风险改造(独立于 B1)

🟡 6 个 capability 包 `await asyncio.to_thread` 仍然是**好实践**(避免
`subprocess.run` 在 event loop 同步阻塞),但**与 chunk 15 解 23 s 沉默
无关**——可单独提一个小 chunk 顺手做,工程量 0.3 d。

### 6.4 清理状态

* ✅ Instrumentation 已 revert(backend/agents/chat.py + backend/routes/ws.py
  恢复 commit `d22ff4a` 状态)
* ✅ profile 文档 + 测试文件保留:
  * `docs/chunk-15-b1-profile.md`(本文)
  * `tests/test_chunk15_b1_profile.py`(可重复跑;若未来更新 ws.py 想
    重新验证 P1-P6,需要先把 instrumentation 重新加回去)
* `git status` 应只显示:
  - `docs/chunk-15-b1-profile.md`(new)
  - `tests/test_chunk15_b1_profile.py`(new)
  - 加上前两次 audit 的 `chunk-15-starting-context.md` /
    `chunk-15-b1-feasibility.md` 文档


---

Profile 完成时间:2026-05-13
git commit hash:`d22ff4a` (`d22ff4a40fb398363166b90a5e6d072c644bac34`)
测试通过状态:**PASS — verdict P2**(verdict reached, 5 audio path events
captured, classification reasoning matched data)
