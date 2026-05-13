# Frontend Profile 跑 Log 指引(chunk 15 / UX-006 stage 1.1b)

前置阅读:
* `docs/chunk-15-starting-context.md` §4(前端 audio 接收 + 播放当前实现)
* `docs/chunk-15-b1-profile.md`(backend profile 已 verdict P2 — 后端
  event-loop 不是 B1 症结,根因在 frontend 或 transport 层)

本指引让**你**(用户)在真机上跑一次完整 tool_use 轮次,把前端
console.log 收集回来给顾问拍板 1.1b 修复路径。

CC(Claude Code)已在 `frontend/src/hooks/useWebSocket.ts` 加好 11 个
`console.log('[FE_PROFILE]', ...)` 写点(F1-F11,详见末尾"Instrumentation
对照"),你只需按下面 5 步操作。**这些临时代码不进 commit**,跑完通知 CC
回滚。


---

## 1. 启动

打开 2 个 terminal,**先 backend 后 frontend**:

**Terminal A — backend**:
```bash
cd /Users/liujunhong/Desktop/MomoOS-v2
.venv/bin/uvicorn backend.main:app --reload
```
等到看到 `Uvicorn running on http://127.0.0.1:8000` 再开 Terminal B。

**Terminal B — frontend (Tauri 窗口)**:
```bash
cd /Users/liujunhong/Desktop/MomoOS-v2/frontend
yarn tauri dev
```
首次 build ~1-3 min;之后增量 ~10 s。Tauri 窗口弹出 + Live2D 角色出现 =
就绪。

**确认前提**:
* `config.yaml` 里 `tts.enabled: true`(默认 `false`,你应该已经手动开
  过;不开的话 backend 不会推 audio_chunk,这次 profile 抓不到东西)
* Apple Calendar 权限已授予(用 `calendar.today_events` 触发 tool_use
  的话)


---

## 2. 准备 DevTools

1. Tauri 窗口里 **右键 → Inspect Element**(或 `Cmd+Opt+I`)
2. 切到 **Console** tab
3. `Cmd+K` 清空 console
4. 在 Console **Filter 框**输入 `[FE_PROFILE]`
   * 这样后续只看 instrumentation log,不被其它 `[FRONT]` / `[WS]`
     log 淹没
   * 注意:某些 Chromium 版本的 Filter 默认对 object log 也会过滤;
     如果 filter 后看不到任何 log,**清空 filter 框**,改成手动眼挑
     `[FE_PROFILE]` 字符串
5. (可选)右上角 Settings 齿轮 → 勾 **Preserve log**(防误清)


---

## 3. 触发完整 tool_use 流程

1. 焦点切到 Momo 输入框
2. 输入(完整复制粘贴这一句,确保触发 tool_use):

   ```
   今天有什么会
   ```

3. 按 **Enter** 发送
4. **静等 30 秒**(完整覆盖:LLM 生过渡语 ~3-5s + tool 执行 ~15-20s
   + 第二轮 LLM ~2-3s + audio 播放尾巴)
   * **不要**点窗口、不要触 Live2D、不要发新消息 — 任何打断都会
     把 INTERRUPT_CLEAR / TOUCH_RESET 触发,污染主线 log

观察(肉眼 sanity check):
- 输入框上应出现 user 气泡
- ~5 秒内应见到过渡语文字气泡("嗯,让我看看"/"等我查一下"等)
- 紧接着 loading pill 应亮起("查询日历..."类)
- ~20 秒后 loading 灭,最终回复文字气泡出现
- **关键**:你应该听到 audio。**如果没听到** → 这就是 chunk 15 要 audit
  的症状,继续抓 log 一定能定位


---

## 4. 抓 log

1. DevTools Console **如果开了 filter**:
   - 鼠标点到 Console 区域,`Cmd+A` 全选(只选 filter 过的可见 log)
   - `Cmd+C` 复制
2. **如果没开 filter** / filter 过滤掉 object log:
   - 滚到最早一条 log,从那行起手动选到最后
   - 或右键 console → **Save as…** → 存成 `.log` 文件
3. 粘贴 / 上传给顾问(或 CC),文件名建议 `fe-profile-<日期>.txt`

### 一份合格 log 应包含

按发送时序大致这样(idx 是 audio 计数器,每个 audio_chunk 自增):

```
[FE_PROFILE] {tag: 'AUDIO_RECV',     t: ..., idx: 1, contentLength: ...}
[FE_PROFILE] {tag: 'PIPE_PRE',       t: ..., idx: 1}
[FE_PROFILE] {tag: 'QUEUE_PUSH',     t: ..., idx: 1, queueLen: 1}
[FE_PROFILE] {tag: 'PLAY_NEXT_ENTER',t: ..., isPlaying: false, queueLen: 1}
[FE_PROFILE] {tag: 'TIMEOUT_ARM',    t: ..., idx: 1, duration: 30000, reason: 'initial'}
[FE_PROFILE] {tag: 'PLAY_PRE',       t: ..., idx: 1}
[FE_PROFILE] {tag: 'PLAY_POST',      t: ..., idx: 1}             ← 浏览器接受播放
[FE_PROFILE] {tag: 'TIMEOUT_ARM',    t: ..., idx: 1, duration: ..., reason: 'loadedmetadata'}
[FE_PROFILE] {tag: 'TOOL_START',     t: ..., toolName: ..., queueLen: 0, isPlaying: true}
[FE_PROFILE] {tag: 'AUDIO_ENDED',    t: ..., idx: 1}             ← 或 TIMEOUT_FIRE
[FE_PROFILE] {tag: 'PLAY_NEXT_ENTER',t: ..., isPlaying: false, queueLen: 0}
... (第二段 audio 同样套路,idx: 2)
```

特别需要看清的两组对比:

* **`PLAY_POST` 何时打出** vs **第一次听到声音** — 如果 `PLAY_POST` 出
  现但听不到声音 → autoplay policy / WebAudio ctx suspended;如果根本
  没 `PLAY_POST` → play() Promise 一直 pending(常见于 Tauri 沙箱)
* **`TOOL_START` 时 `queueLen` 和 `isPlaying` 的值** — 关键看是不是 tool
  loading 状态切换导致前端误清队列(B1 真根因候选 #1)
* **是否出现 `TIMEOUT_FIRE` duration=30000** — 出现意味着 `ended` 事件
  没打,30 s 兜底救场;这 30 s 数字与 23 s 沉默体感太接近,是当前最大
  嫌疑


---

## 5. 完成后通知 CC

抓完 log 把以下信息发给 CC / 顾问:

1. log 文件(粘贴或附件)
2. 主观体感:
   * 是否听到过渡语 audio?(听到 / 没听到)
   * 是否听到最终回复 audio?(听到 / 没听到)
   * 总沉默时长大概多少秒?
3. 用户输入的完整句子 + LLM 实际产出的过渡语文字(从聊天气泡读)
4. backend uvicorn terminal log(`[TIME]` / `[TTS]` / `[interrupt]`
   行),用 `>` 重定向到文件或 Cmd+A 复制

收到信息后:
* **CC 会**:`git stash` 或手动删除 `useWebSocket.ts` 内 `CHUNK15-FE-PROFILE`
  标记的 12 个写点(grep 即可定位),恢复 commit 前状态
* **顾问会**:基于 log + 体感,拍板 1.1b 修复路径(候选已列在
  `docs/chunk-15-b1-profile.md` §6.2):
  - 候选 A:`useWebSocket.ts:74-135` `playNextAudio` 的 30s 兜底
    timer 是不是误触发
  - 候选 B:`tool_use_start` 接收时是否有 state 切换误清队列
  - 候选 C:Tauri WebView 的 audio autoplay policy
  - 候选 D:WebSocket transport 顺序乱(audio_chunk vs tool_use_start
    race)


---

## 6. 故障排查

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| 触发后**没有任何 audio_chunk** 到达(backend 也没发) | tool_use 没走通(LLM 没调 calendar tool) | 看 backend log 里有没有 `ChatAgent tool call: ...`;没有就换更明确的句子("帮我查一下今天的日历")或确认 Apple Calendar 权限 |
| `[FE_PROFILE]` 一条都没有 | instrumentation 没生效;Vite HMR 漏 reload | Terminal B 里 `Ctrl+C` 停 dev → `yarn tauri dev` 重起;Tauri 窗口出来后强刷(右键 → Reload) |
| `AUDIO_RECV` 有但 `PLAY_POST` 永远不出 | autoplay policy 拒绝 / Tauri WebView 沙箱 | 这是有意义的发现,**就这一条 log 也要送出** |
| Console 被其它 `[FRONT]` 刷屏 | 老有的诊断 log | 用 Filter `[FE_PROFILE]`;如果 filter 失效改成 negative filter `-[FRONT]` |
| Filter 后看不到 object 内容 | 某些 Chromium 版本 filter 对 object 的支持差 | 关 filter,改右键 Console → Save as… 全量存盘后再用 grep `[FE_PROFILE]` 提 |


---

## Instrumentation 对照(F1-F11 位置)

| # | 文件:行号(approx) | tag | 触发时机 |
| --- | --- | --- | --- |
| F1 | `useWebSocket.ts` `case 'audio_chunk'` 入口 | `AUDIO_RECV` | 每条 audio_chunk WS message 到达 |
| F2 | 同上,`pipeAudioElement(audio)` 前 | `PIPE_PRE` | createMediaElementSource 接 WebAudio 图 前 |
| F3 | 同上,`audioQueueRef.current.push` 后 | `QUEUE_PUSH` | 入前端 audio 队列 |
| F4 | `playNextAudio` 入口 | `PLAY_NEXT_ENTER` | 每次尝试调度下一段 |
| F5 | `next.play()` 前 + Promise resolve 后 | `PLAY_PRE` / `PLAY_POST` | HTMLAudioElement 开始播放(浏览器接受) |
| F6 | `'ended'` 事件 listener | `AUDIO_ENDED` | 段落自然播完 |
| F7 | `'error'` 事件 listener | `AUDIO_ERROR` | 解码 / 播放失败 |
| F8 | 三处 `setTimeout(handleEnd, ...)` | `TIMEOUT_ARM` / `TIMEOUT_FIRE` | 30s 极端兜底 / loadedmetadata 精确兜底 / 初始兜底 |
| F9 | `case 'tool_use_start'` | `TOOL_START` | backend 发 tool_use_start 到达前端 |
| F10 | `done` interrupted 分支 + `sendInterrupt` | `INTERRUPT_CLEAR` | 队列被强清(打断 / 异常收尾) |
| F11 | `sendTouch` 起始 | `TOUCH_RESET` | touch 事件触发队列复位 |

每个写点统一 marker `CHUNK15-FE-PROFILE`,清理时:
```bash
cd /Users/liujunhong/Desktop/MomoOS-v2
grep -n "CHUNK15-FE-PROFILE\|FE_PROFILE\|audioIdxRef\|audioIdxMapRef" frontend/src/hooks/useWebSocket.ts
```

12 个 hit(11 个 console.log + 2 个 ref 声明合并算 1 site,加上 idx 注入
点)。CC 会在 cleanup 阶段一并 revert,本指引文档**自身** commit
保留,以便未来回归 chunk 15 后续 stage 时复用。


---

Instrumentation 完成时间:2026-05-13
git commit hash(本指引文档对应基线):`d22ff4a`
(`d22ff4a40fb398363166b90a5e6d072c644bac34`)

`yarn build` 状态:**PASS**(`tsc -b && vite build` 无新 error / 新 warning;
唯二既存 warning 是 Tauri `@tauri-apps/api/dpi.js` 动态-vs-静态 import
混用 + chunk 1.0 MB 超 500 kB 提示,与本次 instrumentation 无关)

`yarn lint`:本项目 `package.json` 未定义 `lint` script(只有 `dev` /
`build` / `preview` / `tauri`);`yarn build` 已包含 `tsc -b` 的全量
TypeScript 类型检查,等价于 lint 主要价值。
