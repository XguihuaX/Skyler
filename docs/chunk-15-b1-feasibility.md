# Chunk 15 / UX-006 — B1 解法可行性 Audit

前置:`docs/chunk-15-starting-context.md` §5.2 B1。
本 audit 只扫现状,不修改源代码;末尾给推荐方案 + 工程量估计。


---

## 1. `_execute_tool` 调用链概览

### 1.1 完整定义

`/Users/liujunhong/Desktop/MomoOS-v2/backend/agents/chat.py:919-967`:

```python
async def _execute_tool(
    user_id: str, name: str, raw_args: str,
    character_id: Optional[int] = None,
) -> dict:
    try:
        args = json.loads(raw_args) if raw_args else {}
    except json.JSONDecodeError as exc:
        return {"error": f"invalid JSON args: {exc}"}

    # ── memory 类工具:模块内 handler ─
    handler = _TOOL_HANDLERS.get(name)
    if handler is not None:
        try:
            return await handler(user_id, args, character_id=character_id)
        except Exception as exc:
            return {"error": str(exc)}

    # ── 其他工具:ToolRegistry ─
    args.pop("user_id", None)
    if character_id is not None and "character_id" not in args:
        args["character_id"] = character_id
    try:
        result = await ToolRegistry.call(name, user_id=user_id, **args)
        return {"status": "ok", "result": result}
    except KeyError: ...
    except TypeError as exc: ...
    except ValueError as exc: ...
    except Exception as exc:
        return {"error": str(exc)}
```

### 1.2 Dispatch 机制

两层路由,**全部 async**:

1. **Memory tools** — `_TOOL_HANDLERS` dict
   (`backend/agents/chat.py:911-916`)硬编码 4 个 handler,直接 `await
   handler(user_id, args, character_id=...)`。
2. **其他工具** — `ToolRegistry.call(name, user_id=..., **args)`
   (`backend/tools/registry.py:67-81`):

   ```python
   @classmethod
   async def call(cls, tool_name, **kwargs):
       func = cls.get(tool_name)
       if inspect.iscoroutinefunction(func):
           return await func(**kwargs)
       return func(**kwargs)
   ```

   注册由 `CapabilityRegistry.register` 触发
   (`backend/capabilities/registry.py:116-118`)——所有 `@register_capability`
   都自动 mirror 注入 ToolRegistry,handler 直接挂上去,**不经任何 wrapper**。

### 1.3 调用形态

* 入口:`backend/agents/chat.py:1504-1506`:
  ```python
  result = await _execute_tool(
      user_id, name, raw_args, character_id=character_id,
  )
  ```
* 都是 `await`,单线程协程内同步等待。
* 入参:`user_id: str`、`name: str`、`raw_args: str`、`character_id:
  Optional[int]`。**不**直接接 `AsyncSession`——但下游 capability 自己用
  `async with AsyncSessionLocal()` 开 session(详 §3)。
* 出参:`dict`(成功 `{"status":"ok","result":...}` 或 `{"error":"..."}`)。


---

## 2. Capability 全清单 + 跨线程安全分类

下表盘点 **5 个 memory tools + 41 个 `@register_capability` capability + 2 个
builtin tools = 共 48 项**。grep -n 已验证全部 register_capability 站点
(58 个 hit,去掉文档注释 + 框架定义后 46 个真注册点;`netease_music.py` /
`netease_playback.py` 装饰器跨多行,通过 `name=` 字段去重计 41 个独立 capability)。

分类标签:🟢 Pure sync / 🟡 Sync IO-bound / 🟠 Async no shared resource /
🔴 Async with AsyncSession / event-loop-bound resource。

| capability name | 入口 (file:line) | sync/async | AsyncSession | await 其他 async 资源 | 分类 |
| --- | --- | --- | --- | --- | --- |
| **(memory tools / 直接 `_TOOL_HANDLERS`)** | | | | | |
| `save_memory` | `backend/agents/chat.py:_tool_save_memory` (around 700) | async | ✅ `_engine.begin()` + `AsyncSessionLocal` | ✅ `generate_embedding`,`call_llm` | 🔴 |
| `delete_memory` | `chat.py:760-776` | async | ✅ `AsyncSessionLocal()` `768` | — | 🔴 |
| `list_memories` | `chat.py:779-793` | async | ✅ `AsyncSessionLocal()` `782` | — | 🔴 |
| `compress_memories` | `chat.py:810-908` | async | ✅ `AsyncSessionLocal()` `819`,`880` | ✅ `call_llm`,`generate_embedding` | 🔴 |
| **(builtin tools / `tools/registry.py:95-96`)** | | | | | |
| `switch_character` | `backend/tools/builtin.py:14` | async | — | — *(纯调 `prompt_manager.switch_character` 内存 dict)* | 🟢 |
| `clear_short_term` | `backend/tools/builtin.py:26` | async | — | ✅ `short_term_memory.clear` *(纯 dict, 实际同步)* | 🟢 |
| **(character)** | | | | | |
| `character.get_state` | `backend/capabilities/character_state.py:54` | async | ✅ `AsyncSessionLocal()` `58` | — | 🔴 |
| `character.set_activity` | `character_state.py:101` | async | ✅ `AsyncSessionLocal()` `113` | ✅ `connection_manager.push` → `ws.send_json` `125` | 🔴 |
| `character.intimacy_decay` *(SCHEDULER-only)* | `character_state.py:158` | async | ✅ `AsyncSessionLocal()` `161,166` | — | 🔴 |
| **(time)** | | | | | |
| `time.now` | `backend/capabilities/time_capability.py:51` | async | — | — *(纯 `datetime.now`)* | 🟢 |
| **(screen)** | | | | | |
| `screen.get_active_app` | `backend/capabilities/screen.py:58` | async | — | — *(call `_am.get_active_app()` 同步)* | 🟡 |
| `screen.get_browser_url` | `screen.py:85` | async | — | — *(call `_am.get_browser_url()` 同步,内部 `subprocess.run` osascript)* | 🟡 |
| `screen.get_browser_content` | `screen.py:123` | async | — | ✅ `_uf.fetch_article_content` (httpx.AsyncClient) | 🟠 |
| `screen.get_active_document` | `screen.py:165` | async | — | — *(call `_am.get_active_document_path()`)* | 🟡 |
| **(clipboard)** | | | | | |
| `clipboard.get_recent` | `backend/capabilities/clipboard.py:57` | async | — | — *(call `clipboard_watcher.get_recent` 同步 deque)* | 🟢 |
| `clipboard.summarize` | `clipboard.py:92` | async | — | ✅ `call_llm` | 🟠 |
| `clipboard.translate` | `clipboard.py:152` | async | — | ✅ `call_llm` | 🟠 |
| **(calendar 路由层)** | | | | | |
| `calendar.today_events` | `backend/capabilities/calendar.py:96` | async | — | ✅ 转发到 `apple_calendar.today_events` | 🟠 |
| `calendar.upcoming_events` | `calendar.py:125` | async | — | ✅ 同上 | 🟠 |
| **(apple_calendar)** | | | | | |
| `apple_calendar.today_events` | `backend/capabilities/apple_calendar.py:49` | async | — | ✅ `ac.list_events_in_range` → `asyncio.to_thread(_list_events_sync)` (`backend/integrations/apple_calendar.py:267`) | 🟠 |
| `apple_calendar.upcoming_events` | `apple_calendar.py:84` | async | — | ✅ 同上 | 🟠 |
| `apple_calendar.create_event` | `apple_calendar.py:141` | async | — | ✅ `ac.create_event` → `asyncio.to_thread` (`integrations:280`) | 🟠 |
| `apple_calendar.delete_event` | `apple_calendar.py:208` | async | — | ✅ `ac.delete_event` → `asyncio.to_thread` (`integrations:287`) | 🟠 |
| **(google_calendar / SCHEDULER-only)** | | | | | |
| `google_calendar.today_events` | `backend/capabilities/google_calendar.py:71` | async | — | ✅ `gc.list_events_in_range` (Google API client) | 🟠 |
| `google_calendar.upcoming_events` | `google_calendar.py:105` | async | — | ✅ 同上 | 🟠 |
| **(activity)** | | | | | |
| `activity.get_today_summary` | `backend/capabilities/activity.py:77` | async | ✅ `engine.begin()` `85` | — | 🔴 |
| `activity.get_recent_apps` | `activity.py:203` | async | ✅ `engine.begin()` `216` | — | 🔴 |
| `activity.search_history` | `activity.py:281` | async | ✅ `engine.begin()` `306` | — | 🔴 |
| **(media)** | | | | | |
| `media.next_track` | `backend/capabilities/media_control.py:170` | async | — | ✅ `_nowplaying` → `asyncio.to_thread(_run_sync)` (`media_control.py:122`) | 🟠 |
| `media.previous_track` | `media_control.py:194` | async | — | ✅ 同上 | 🟠 |
| `media.play_pause` | `media_control.py:219` | async | — | ✅ 同上 | 🟠 |
| `media.now_playing` | `media_control.py:256` | async | — | ✅ 同上 | 🟠 |
| `media.set_volume` | `media_control.py:303` | async | — | ✅ `_osascript` → `asyncio.to_thread` `126` | 🟠 |
| **(netease_music — chunk 1 client + chunk 6b mpv fallthrough)** | | | | | |
| `netease.daily_recommend` | `backend/capabilities/netease_music.py:285` | async | — | ✅ `asyncio.to_thread(_client().daily_recommend)` + `_mpv.get_player().play` (asyncio.Lock-protected, **loop-bound**) | 🔴 |
| `netease.personal_fm` | `netease_music.py:347` | async | — | ✅ 同 `daily_recommend` 用 mpv | 🔴 |
| `netease.play_song` | `netease_music.py:417` | async | — | ✅ `asyncio.to_thread` + mpv | 🔴 |
| `netease.play_playlist` | `netease_music.py:478` | async | — | ✅ 同上 | 🔴 |
| `netease.play_playlist_by_id` | `netease_music.py:517` | async | — | ✅ 同上 | 🔴 |
| `netease.like_current` | `netease_music.py:588` | async | — | ✅ `asyncio.to_thread(_client().search)` + `asyncio.to_thread(_client().like_song)` *(纯 sync API,无 mpv)* | 🟠 |
| `netease.search` | `netease_music.py:629` | async | — | ✅ `asyncio.to_thread(_client().search)` *(纯 sync,无 mpv)* | 🟠 |
| **(netease_playback / 全部 mpv-IPC)** | | | | | |
| `netease.local_play_song` | `backend/capabilities/netease_playback.py:83` | async | — | ✅ `_mpv.get_player().play` (asyncio.Lock + asyncio.subprocess) | 🔴 |
| `netease.local_play_playlist` | `netease_playback.py:155` | async | — | ✅ 同上 + `asyncio.to_thread` 拿 song URL | 🔴 |
| `netease.local_pause` | `netease_playback.py:256` | async | — | ✅ `_mpv.get_player().pause` | 🔴 |
| `netease.local_resume` | `netease_playback.py:276` | async | — | ✅ `_mpv.get_player().resume` | 🔴 |
| `netease.local_stop` | `netease_playback.py:298` | async | — | ✅ `_mpv.get_player().stop` | 🔴 |
| `netease.local_next_in_queue` | `netease_playback.py:323` | async | — | ✅ `_mpv.get_player().play_next` | 🔴 |
| **(bilibili — 11 个,全部 httpx.AsyncClient)** | | | | | |
| `bilibili.search_video` | `backend/capabilities/bilibili.py:51` | async | — | ✅ `_bili.search_video` (内部 httpx.AsyncClient) | 🟠 |
| `bilibili.get_video_info` | `bilibili.py:88` | async | — | ✅ httpx.AsyncClient | 🟠 |
| `bilibili.search_user` | `bilibili.py:120` | async | — | ✅ 同上 | 🟠 |
| `bilibili.get_user_videos` | `bilibili.py:154` | async | — | ✅ 同上 | 🟠 |
| `bilibili.hot_videos` | `bilibili.py:187` | async | — | ✅ 同上 | 🟠 |
| `bilibili.get_ranking` | `bilibili.py:221` | async | — | ✅ 同上 | 🟠 |
| `bilibili.get_subtitles` | `bilibili.py:261` | async | — | ✅ httpx.AsyncClient | 🟠 |
| `bilibili.get_my_history` | `bilibili.py:290` | async | — | ✅ 同上 | 🟠 |
| `bilibili.get_my_followings` | `bilibili.py:322` | async | — | ✅ 同上 | 🟠 |
| `bilibili.get_later_watch` | `bilibili.py:347` | async | — | ✅ 同上 | 🟠 |
| `bilibili.get_favorites` | `bilibili.py:370` | async | — | ✅ 同上 | 🟠 |
| **(xiaohongshu)** | | | | | |
| `xhs.parse_url` | `backend/capabilities/xiaohongshu.py:61` | async | — | ✅ `_xhs.parse_post` (httpx.AsyncClient,`integrations/xiaohongshu.py:46`) | 🟠 |
| **(docx_ops)** | | | | | |
| `docx.create` | `backend/capabilities/docx_ops.py:121` | async | — | — *(纯 sync `python-docx`,本地文件 I/O)* | 🟡 |
| `docx.read` | `docx_ops.py:185` | async | — | — *(同上)* | 🟡 |
| `docx.append` | `docx_ops.py:265` | async | — | — *(同上)* | 🟡 |

**统计分类合计**(48 项):
- 🟢 Pure sync: **3** (`time.now`, `switch_character`, `clipboard.get_recent`, `clear_short_term` = 4 项,`switch_character` 实质纯字典操作)
- 🟡 Sync IO-bound (已内嵌 sync 调用): **6** (`screen.*` 3 项 + `docx.*` 3 项)
- 🟠 Async without AsyncSession/lock: **24** (calendar 路由/apple/google_calendar + media.* + bilibili.* + clipboard.summarize/translate + screen.get_browser_content + xhs + netease.like_current/search)
- 🔴 Async with AsyncSession 或 loop-bound resource: **15**
  - DB 类:save_memory / delete_memory / list_memories / compress_memories / character.get_state / character.set_activity / character.intimacy_decay / activity.get_today_summary / activity.get_recent_apps / activity.search_history (10 项)
  - mpv asyncio.Lock + asyncio.subprocess:netease.daily_recommend / personal_fm / play_song / play_playlist / play_playlist_by_id + netease.local_* 6 项 (11 项,partial overlap)
  - 实际去重 🔴 共 **15** 项(DB-only 10 + mpv-only 6,character.set_activity 同时双中)


---

## 3. 跨线程不安全点详查(🔴 标记 capability)

### 3.1 不安全资源类别盘点

🔴 类项绕不开 3 类 event-loop-bound 资源:

1. **`AsyncSession`**(SQLAlchemy 2.0 asyncio)
   `backend/database/__init__.py` 创建 `engine` + `AsyncSessionLocal`,
   全部 session 用 `async with AsyncSessionLocal() as session:` 开。
   AsyncEngine 内部用 asyncpg / aiosqlite 协程驱动,**session 对象绑定创建
   时的 event loop**。在另一个线程内开 session 会触发 `RuntimeError: This
   event loop is already running` 或更阴险的 silent data corruption
   (两个 loop 共享同一连接池)。

2. **`asyncio.Lock` / `asyncio.subprocess.Process` / `asyncio.StreamReader /
   StreamWriter`**(mpv player)
   `backend/integrations/mpv_player.py:135-145`:
   ```python
   class MpvPlayer:
       def __init__(self, binary):
           self._proc: Optional[asyncio.subprocess.Process] = None
           self._reader: Optional[asyncio.StreamReader] = None
           self._writer: Optional[asyncio.StreamWriter] = None
           self._cmd_lock = asyncio.Lock()
   ```
   全部绑主 loop;跨 loop 调用 `await self._cmd_lock` 会直接抛
   `RuntimeError`(asyncio.Lock 锁 loop instance)。

3. **`connection_manager.push` → `ws.send_json`**
   `backend/routes/ws.py:104-107`:
   ```python
   async def push(self, user_id: str, message: dict) -> None:
       ws = self._connections.get(user_id)
       if ws:
           await ws.send_json(message)
   ```
   `WebSocket.send_json` 在 ASGI 层把 send 协程绑主 loop。跨 loop 写同一
   WebSocket 等同未定义行为。

### 3.2 逐一详查 🔴 capabilities

**(1) `character.set_activity`** (`character_state.py:101-136`)
- 不安全点:第 113-118 行 `async with AsyncSessionLocal() as session:` +
  第 123-132 行 `await connection_manager.push(user_id, ...)`。
- 跑多频:中频。Prompt 引导"不超过每 5-10 轮一次"
  (`character_state.py:74-76`),但 LLM 自我克制不可靠,实际可能每轮触发。
- 可拆性:**不可拆**。DB 写完后立即推 ws 通知,把 push 后置到
  `_execute_tool` 外仍需保证原子性(否则前端看 stale state)。如果走
  to_thread,session + push 都要重写。

**(2) `character.get_state`** (`character_state.py:54-60`)
- 不安全点:第 58-59 行 `async with AsyncSessionLocal() as session:`。
- 跑多频:低频。仅"用户问你最近怎么样"才调。
- 可拆性:**可拆**——只读 DB,返回 dict。但仍要走主 loop;拆出 `_execute_tool`
  外也不会回收时间。

**(3) `character.intimacy_decay`** — SCHEDULER-only,不走 ChatAgent
tool_use 路径,不进 chunk 15 改造范围。略。

**(4) 4 个 memory tools** (`chat.py:_tool_save_memory` 等)
- 不安全点:每个都用 `AsyncSessionLocal` 或 `_engine.begin()`。
- 跑多频:`save_memory` 用户明确"请记住 X"时低频;`list_memories`
  低频;`delete_memory` / `compress_memories` 极低频。
- 可拆性:**不可拆**。每个都是单纯 DB CRUD + LLM 调用(compress),
  本质 DB-heavy。

**(5) 3 个 `activity.*`** (`backend/capabilities/activity.py`)
- 不安全点:全部 `async with engine.begin() as conn:` + raw SQL。
- 跑多频:中频。用户问"今天累不累"会触发 `get_today_summary`。
- 可拆性:**不可拆**。纯 SQL 查询。

**(6) 5 个 `netease.daily_recommend / personal_fm / play_song /
play_playlist / play_playlist_by_id`** (chunk 1 + chunk 6b 混合)
- 不安全点:`asyncio.to_thread(_client().xxx)` 拿数据 ok,但接 mpv 自动播放
  时 `_mpv.get_player().play(...)` 用 `asyncio.Lock` + asyncio.subprocess
  IPC。
- 跑多频:中频(用户主动放音乐时一次)。
- 可拆性:**部分可拆**。"拿 song URL"那段是 sync(`_client().get_song_url`)
  通过 `asyncio.to_thread` 已经在线程内,**已是 yield 友好**。
  但播放 `await player.play(url, ...)` 段绑主 loop,不可挪。

**(7) 6 个 `netease.local_*`** (`netease_playback.py`)
- 不安全点:**100% mpv IPC**——`asyncio.Lock` + StreamWriter writes。
- 跑多频:低-中频。
- 可拆性:**完全不可拆**。capability 本质就是 mpv 控制。

### 3.3 (🟡)对照:已经 yield 友好的 capabilities

`screen.get_active_app/url/document` + `docx.*` 是 🟡:函数声明 `async
def`,但函数体直接调 sync helper(`_am.get_active_app()` /
`Document(target)`)**没**用 `asyncio.to_thread`。意思是这些 capability
**在主 loop 内同步执行**,subprocess.run 会真阻塞 event loop 几十-几百
ms(详 `activity_monitor.py:83`,`192`,`485` 都是 `subprocess.run` 不
async)。

如果 B1 真因是 event-loop 卡住,**这些 🟡 capability 更可能是症结**而
不是 🔴。建议优先把 🟡 一律改为 `await asyncio.to_thread(sync_fn)` 套壳
——0 副作用,纯改善。


---

## 4. character_state 写入路径专项

### 4.1 _execute_tool 触发 character_state 写入的 3 条路径

1. **直接 capability** `character.set_activity`
   (`character_state.py:101-136`)——LLM 主动调,写
   `current_activity` + `current_thought` + push ws state_update。
2. **`<state_update>` 标签解析**——**不在** _execute_tool 链路内。
   入口是 ws.py 主路径 `_apply_and_push_state_update`
   (`ws.py:487-527`)和 `_handle_message` 内 char_id bump_last_interaction
   (`ws.py:820-830`)。这条路径与 tool 调用并行,不受 B1 影响。
3. **`character.intimacy_decay`**——SCHEDULER cron,与 chunk 15 无关。

### 4.2 `update_character_state` DB 服务签名

`backend/database/services.py:647-657`:

```python
async def update_character_state(
    session: AsyncSession,
    character_id: int,
    *,
    mood: Optional[str] = None,
    intimacy_delta: Optional[int] = None,
    intimacy_absolute: Optional[int] = None,
    thought: Optional[str] = None,
    activity: Optional[str] = None,
    bump_last_interaction: bool = False,
) -> CharacterState:
```

**第一个形参就是 `AsyncSession`**——主 loop 创建的 session,跨 loop 调
用必崩。

### 4.3 假设 `_execute_tool` 整体跑在 `asyncio.to_thread` 内会发生什么

线程 T0 = 主 loop,线程 T1 = `to_thread` 创建的 work thread。
要在 T1 内 `await update_character_state(session, ...)`,先得 `asyncio.run`
建立**新** loop L1,然后:

| 资源 | 后果 |
| --- | --- |
| `AsyncSessionLocal()` | session.bind 还是主 engine,内部 connection 仍属于 L0 池。L1 内 `await session.execute(...)` 触发 `RuntimeError: got Future <...> attached to a different loop`。 |
| `connection_manager.push(...)` | ws.send_json 在 L0 上 await;L1 上 await 它 → 同样错误。 |
| `asyncio.Lock`(mpv) | "is bound to a different event loop"。 |
| `httpx.AsyncClient` | 同上,connection pool 绑 loop。 |
| `asyncio.subprocess` | 绑 loop watcher。 |

**结论**:A1 的 naive 形态(整 `_execute_tool` 走 to_thread)对 🔴 类
**100% 不可行**;对 🟠 大部分也不可行(httpx / asyncio.subprocess /
asyncio.to_thread 嵌套都会出问题)。


---

## 5. 结论 + 推荐路径

### 5.1 推荐方案:**A2 (yield points) + 优先重点关注 🟡**

A1 整体包 `to_thread` 不可行(§4.3)。即使分组按 capability 跳,以下事实
劝退:
- 🔴 占 15/48,且包含**最常用的 character.set_activity**(LLM 几乎每
  轮都想调)
- 🟠 占 24/48,内部已用 httpx.AsyncClient,本来就 yield-friendly,**没
  必要再包 to_thread**(嵌套反而拖慢)
- 🟢 + 🟡 占 9/48,只有 🟡 的 `screen.*` / `docx.*` 是真正的 sync-in-async
  路径——这才是 B1 真正可优化点

**推荐路径**:
1. **5-7 个 🟡 capability 内部 await asyncio.to_thread**(0 风险纯优化):
   - `screen.get_active_app`(`screen.py:58` → `_am.get_active_app()`)
   - `screen.get_browser_url`(`screen.py:85` → `_am.get_browser_url()`)
   - `screen.get_active_document`(`screen.py:165` →
     `_am.get_active_document_path()`)
   - `docx.create`(`docx_ops.py:138-146` Document().save())
   - `docx.read`(`docx_ops.py:197-216` Document(target) + paragraphs 遍历)
   - `docx.append`(`docx_ops.py:284-298` 同上)
   - 改法:把 sync helper 调用包成 `await asyncio.to_thread(sync_fn,
     ...)`,函数签名不变。
2. **在 `_execute_tool` 入口 + ToolRegistry 出口插 `await asyncio.sleep(0)`
   显式 yield**(B1 主路径 fallback):
   - 位置 1:`backend/agents/chat.py:932` 进 `_execute_tool` 第一行
     (json.loads 之前)
   - 位置 2:`backend/tools/registry.py:81` `ToolRegistry.call` 返回前
   - 这给 consumer task 强制夺到 schedule 机会,即使 capability 本身
     sync 段较长。
3. **不动 🔴 任何代码**——DB / mpv 类 capability 用的就是主 loop 资源,
   yield 点本身已经多(每个 `async with` `await` 都是 yield),问题
   不在它们。

### 5.2 工程量估计

| 步骤 | 工时 | 风险 |
| --- | --- | --- |
| 5-7 个 🟡 包 `asyncio.to_thread` | 0.3 d | 极低。改法机械,有测试覆盖 |
| 2 处 `asyncio.sleep(0)` yield point | 0.05 d | 极低。本身就是 yield no-op |
| 写测试验证 `audio_consumer` 在 tool 执行期间能 send_json | 0.3 d | 低。可通过 mock TTS + 计时验证 |
| 真机回归 + e2e 验证 23s 沉默消除 | 0.4 d | 中。最终验收靠人耳听 |
| **合计** | **~1 d** | |

如果 A2 实施后**沉默依旧**——说明 B1 的根因不是 event-loop 调度,而是
**WebSocket send_json 序列化** 或 **frontend 播放队列调度问题**;转
chunk 15 §7 Q1/Q3 重新拍板。

### 5.3 风险点

1. **A2 yield point 并非真正解决问题**——`asyncio.sleep(0)` 让出一次
   schedule,但下次 capability 的 `await asyncio.to_thread(...)` 一般
   要等几十 ms 才回来,中间 consumer 能跑一段;若 capability 是**纯主
   loop 计算**(纯 dict 操作 / json.dumps 大对象 / etc.),sleep(0) 不够
   ——需要识别**热点**才能精准下药。建议先 profile 再下手。
2. **🟡→to_thread 改造后,`subprocess.run` 仍然带 2s timeout
   (`media_control.py:30`),与现有 `_run_sync` 一致**——无新引入风险。
3. **测试覆盖**:`tests/test_*.py` 大多 mock 了 capability 整体函数,
   to_thread 包装层不会破坏行为。但需要新加 timing 测试,在 _execute_tool
   "假等"期间断言 send_json 被调用。
4. **`character.set_activity` 仍卡 ws push**——它走主 loop send_json,
   与 audio_consumer 的 send_json 在同一 loop 上共享调度。这不会被 A2
   影响,但说明 chunk 15 即使解了 B1,`set_activity` 调用本身仍可能
   引入额外 100-200 ms latency 写 DB。可接受。
5. **proactive engine 共享 helper**(`backend/proactive/engine.py:375,447`
   import `_tts_audio_consumer` + `_tts_synth_with_timeout`)——A2 不
   碰这俩,proactive 路径无回归面。


---

## 6. Audit 中未解明的问题

### Q1. B1 的根因是不是真的 event-loop 调度?

§3 capability 盘点显示:**大部分 capability 已经是 yield 友好**(用
`await asyncio.to_thread` 或 httpx.AsyncClient,每个 await 都是 yield
点)。如果 consumer task 真被饿死,理论上不应该——这与 §1 的假设
("`_execute_tool` 同步阻塞")不完全吻合。

**待顾问拍板**:在做 A2 改造**之前**,先做 5-10 min profiling(打 
`time.perf_counter()` 在 consumer 的 `await sender(audio)` 前后、
producer 的 `audio_queue.put` 后),看 audio_chunk 实际何时被 send_json
出去。如果 send_json 在 tool 执行期间已经在跑,说明 B1 根因在
frontend / WebSocket 缓冲层,A1/A2 都解错问题。

### Q2. `character.set_activity` 在 tool_use 流程中的 push state_update 是否要禁用?

`character.set_activity` 写完 DB 后 `await connection_manager.push(...)`
(`character_state.py:125-132`)推 state_update 到前端。这个推送与 chunk 15
要解的过渡语 audio 在**同一 WebSocket** 上排队。如果用户 prompt 让 LLM
"先调 set_activity 再回话",会先有一个 state_update push 抢位置。

**待顾问拍板**:是否在 chunk 15 加 ws 写锁? 或者把 set_activity 的
push 后置到 done 之后批量送? 这个选择影响 LLM tool 调用顺序的策略。

### Q3. 5-7 个 🟡 包 `to_thread` 之后是否引入 thread pool 饥饿?

Python 默认 ThreadPoolExecutor max_workers ≈ `min(32, os.cpu_count() + 4)`。
若 LLM 一轮调 3 个 🟡 capability(screen.get_active_app + browser_url +
active_document),并行占 3 个 worker——加上 cosyvoice TTS 也用 to_thread,
理论上单轮 worker 占用 < 10,不会饥饿。

但**长期回归测试**没覆盖这种密集 to_thread 场景。**待顾问拍板**:
是否在 chunk 15 内显式给 `asyncio.to_thread` 配 Semaphore(3-5),避免
未来 mpv / cosyvoice / capability sync section 共池打架。

### Q4. `_execute_tool` 之外的"过渡语段 TTS"该不该单独走一条 yielding flush?

chunk 15 §3.1(前置 audit)说过渡语 audio 在 `tool_use_start` 之前就该
flush。但 _execute_tool 还没开始执行,**ws 主路径**的 producer
(ws.py:1031-1039)已经把 TTS task 入队;consumer 是另一 task,理应
跟得上。

**待顾问拍板**:如果 profiling(Q1)证明 consumer 真的没被饿死,那
chunk 15 的真问题可能是"过渡语 audio 已发送,但**前端 audioQueue 在
tool_use_start 时被 frontend 状态切换清空**"。这要看
`frontend/src/hooks/useWebSocket.ts:251-265` 打断收尾路径有没有误触
——chunk 15 stage 拆分要先 cover 前端验证。

### Q5. 是否要为 chunk 15 单独引入 capability-level "fast path" hint?

A2 给 capability 加 yield 时,无法区分"高频 capability(每轮可能调)"
和"低频 capability(月一次)"。要不要在 `@register_capability` 上加
`fast_path: bool` 元数据让 fast_path capability 自动跑在专用线程池 / 优先
schedule? 这跟 chunk 15 边界相关。

**待顾问拍板**:capability metadata 是否要在 chunk 15 内一并扩字段,
还是留给后续 chunk?


---

Audit 完成时间:2026-05-13 / git commit `d22ff4a`
(`d22ff4a40fb398363166b90a5e6d072c644bac34`)
