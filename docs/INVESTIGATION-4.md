# INVESTIGATION-4 · token 治理轮（第三刀：工具治理）

> 接 INVESTIGATION-3.md（1098 行封存）。本文件自 2026-05-20 token 第三刀（工具治理）起用。
> INV-3 §10.6 extra_system 推断验证项 backlog parked，工具治理完再回头追。

---

## § PM 切轨说明（2026-05-20）

INV-3 §10.6 把 43-68k 真凶推断为 `proactive_engine` 路径 `extra_system` 注入（3 个验证项）。PM 决定先治理 `tools_schema` 13,250 token 大头，再回头追 extra_system。理由：

1. 杠杆量级差距明显（13.25k 已知实测 vs 43-68k 未确认幽灵）
2. extra_system 即便是凶手量级上限 ~5-8k，凑不到 43k
3. 治理后 baseline 22.7k → 10-12k，再追幽灵信噪比好

→ INV-3 §10.6 三个验证项 **backlog parked**，工具治理完回头追。

---

## §1 全 capability 枚举（第一步 · 纯只读）

### 1.1 枚举源 4 道（实测）

| # | 源 | 命中数 | 方法 |
|---|---|---|---|
| 1 | `backend/capabilities/*.py` + `backend/proactive/snooze_capability.py` 的 `@register_capability` 装饰器 | **56** | `grep -rn '^@register_capability' backend/` 行首正则 + Python AST `ast.walk` 反取每个 decorator 的 `name / category / description / consumers / trigger_modes / parameters_schema` |
| 2 | `backend/agents/chat.py:455-539` 内联 `MEMORY_TOOLS` 列表 | **4** | `save_memory` / `delete_memory` / `list_memories` / `compress_memories`（直接拼到 `tools=` 参数，不走 ToolRegistry） |
| 3 | `backend/tools/builtin.py` + `backend/tools/registry.py:99` | **1（活）+ 1（休眠）** | `clear_short_term` 真活（L99 `ToolRegistry.register`）；`switch_character` 函数 + schema 留代码但**LLM tool 已下线**（`registry.py:95-98` 注释明示） |
| 4 | `config.yaml:129-170 mcp_clients` 中 `enabled: true` 的客户端 | **1**（`filesystem-skyler`） | `enabled=false`：`filesystem` / `brave-search` / `notion` / **3 个**；`enabled=true`：`filesystem-skyler` 唯一。实际反向注册 tool 数 = runtime（`backend/mcp/client.py:225 cap_name = f"ext.{handle.name}.{tool.name}"`），本刀**纯只读静态勘查不 runtime probe**，仅以 flag 标位 |

### 1.2 全 capability 表（按 category 分组）

下表 56 个 `@register_capability` 装饰器逐条 AST 实拆。`描述` 列截前 50 字；`schema 字符数` = `ast.unparse(parameters_schema)` 长度（含 `{type:object, properties:..., required:...}` 包装，可粗略估 token ≈ `字符数 ÷ 3.5`）。`consumers` 列只标 `CHAT_AGENT` 是否在内（`C` = CHAT_AGENT / `S` = SCHEDULER / `W` = WEBHOOK），决定是否暴露给 LLM `tools=`。

#### activity (3)

| # | name | 文件:行 | description（截 50 字） | schema 字符 | consumers | trigger_modes |
|---|---|---|---|---|---|---|
| 1 | `activity.get_today_summary` | `activity.py:59` | 查用户今天(本地日)在各 app / URL 的总停留时长 + 类别分布。 | 52 | C | ON_DEMAND |
| 2 | `activity.get_recent_apps` | `activity.py:177` | 查最近 N 天(1-30,默 7)用户 top apps + 总停留时长。 | 159 | C | ON_DEMAND |
| 3 | `activity.search_history` | `activity.py:250` | 在历史 session 的 ``browser_url / browser_title / app`` 字段搜关键 | 255 | C | ON_DEMAND |

#### calendar (8)

| # | name | 文件:行 | description（截 50 字） | schema 字符 | consumers | trigger_modes |
|---|---|---|---|---|---|---|
| 4 | `calendar.today_events` | `calendar.py:79` | 获取今天的所有日历事件（本地时区）。当用户问'今天有什么会 | 52 | C+S | ON_DEMAND, SCHEDULED |
| 5 | `calendar.upcoming_events` | `calendar.py:100` | 获取未来 N 天（默认 7 天，1-30）的日历事件。 | 152 | C | ON_DEMAND |
| 6 | `google_calendar.today_events` | `google_calendar.py:55` | 获取今天（本地时区）的 Google Calendar 事件。优先用 calendar.today | 52 | **S only** | ON_DEMAND, SCHEDULED |
| 7 | `google_calendar.upcoming_events` | `google_calendar.py:81` | 获取未来 N 天（默认 7，1-30）的 Google Calendar 事件。 | 152 | **S only** | ON_DEMAND |
| 8 | `apple_calendar.today_events` | `apple_calendar.py:34` | 获取 macOS Apple Calendar 今天的所有事件（本地时区）。 | 52 | C+S | ON_DEMAND, SCHEDULED |
| 9 | `apple_calendar.upcoming_events` | `apple_calendar.py:61` | 获取 macOS Apple Calendar 未来 N 天（默认 7，1-30 范围）事件。 | 152 | C+S | ON_DEMAND |
| 10 | `apple_calendar.create_event` | `apple_calendar.py:96` | 在 macOS Apple Calendar 创建一个事件。当用户说「提醒我 X | 506 | C | ON_DEMAND |
| 11 | `apple_calendar.delete_event` | `apple_calendar.py:184` | 按 event_id 删除 macOS Apple Calendar 事件。**调用前必须先**用 | 161 | C | ON_DEMAND |

#### character (3)

| # | name | 文件:行 | description（截 50 字） | schema 字符 | consumers | trigger_modes |
|---|---|---|---|---|---|---|
| 12 | `character.get_state` | `character_state.py:40` | 查看你（当前角色）此刻的 mood / intimacy / current_thought | 52 | C | ON_DEMAND |
| 13 | `character.set_activity` | `character_state.py:67` | 更新你（当前角色）的 current_activity（在做什么）和可选 thought | 206 | C | ON_DEMAND |
| 14 | `character.intimacy_decay` | `character_state.py:143` | （SCHEDULER）每天 0:00 自动调用：每个 character 的 intimacy 自减 1 | 52 | **S only** | SCHEDULED |

#### clipboard (3)

| # | name | 文件:行 | description（截 50 字） | schema 字符 | consumers | trigger_modes |
|---|---|---|---|---|---|---|
| 15 | `clipboard.get_recent` | `clipboard.py:33` | 拿最近 N 条剪贴板内容（最新在前）。当用户提到「刚复制的」 | 157 | C | ON_DEMAND |
| 16 | `clipboard.summarize` | `clipboard.py:69` | 对最近剪贴板第 item_index 条（默认 0 = 最新）做简洁总结。 | 151 | C | ON_DEMAND |
| 17 | `clipboard.translate` | `clipboard.py:125` | 翻译最近剪贴板第 item_index 条（默认 0 = 最新）。 | 242 | C | ON_DEMAND |

#### files (3)

| # | name | 文件:行 | description（截 50 字） | schema 字符 | consumers | trigger_modes |
|---|---|---|---|---|---|---|
| 18 | `docx.create` | `docx_ops.py:83` | 创建一份新的 Word 文档（.docx），保存到 Skyler 文档沙箱目录。 | 297 | C | ON_DEMAND |
| 19 | `docx.read` | `docx_ops.py:158` | 读取沙箱中已有的 Word 文档内容。 | 124 | C | ON_DEMAND |
| 20 | `docx.append` | `docx_ops.py:233` | 向已有的 Word 文档末尾追加段落（不破坏原有内容）。 | 226 | C | ON_DEMAND |

#### media (16)

| # | name | 文件:行 | description（截 50 字） | schema 字符 | consumers | trigger_modes |
|---|---|---|---|---|---|---|
| 21 | `media.next_track` | `media_control.py:155` | 切到下一首歌（系统级——不限来源：网易云 / Apple Music / Spotify | 52 | C | ON_DEMAND |
| 22 | `media.previous_track` | `media_control.py:181` | 回到上一首。 | 52 | C | ON_DEMAND |
| 23 | `media.play_pause` | `media_control.py:205` | 切换播放 / 暂停状态（toggle）。 | 52 | C | ON_DEMAND |
| 24 | `media.now_playing` | `media_control.py:240` | 查当前系统在播什么歌（歌名 / 歌手 / 专辑），跨来源。 | 52 | C | ON_DEMAND |
| 25 | `media.set_volume` | `media_control.py:279` | 设置 macOS 系统输出音量（0-100）。 | 154 | C | ON_DEMAND |
| 26 | `bilibili.search_video` | `bilibili.py:23` | 搜索 B 站视频。 | 153 | C | ON_DEMAND |
| 27 | `bilibili.get_video_info` | `bilibili.py:61` | 拿 B 站视频元数据（标题 / UP 主 / 描述 / 时长 / 播放数 / 点赞 / 收藏 | 90 | C | ON_DEMAND |
| 28 | `bilibili.search_user` | `bilibili.py:98` | 搜索 B 站 UP 主。 | 119 | C | ON_DEMAND |
| 29 | `bilibili.get_user_videos` | `bilibili.py:130` | 拿指定 UP 主的最近投稿视频列表。 | 146 | C | ON_DEMAND |
| 30 | `bilibili.hot_videos` | `bilibili.py:166` | B 站首页热门视频。 | 97 | C | ON_DEMAND |
| 31 | `bilibili.get_ranking` | `bilibili.py:197` | B 站排行榜（综合 / 新人 / 原创）。 | 148 | C | ON_DEMAND |
| 32 | `bilibili.get_subtitles` | `bilibili.py:231` | 拿 B 站视频字幕用于内容总结。⭐ 杀手 use case。 | 90 | C | ON_DEMAND |
| 33 | `bilibili.get_my_history` | `bilibili.py:271` | 我的 B 站观看历史。 | 68 | C | ON_DEMAND |
| 34 | `bilibili.get_my_followings` | `bilibili.py:300` | 拿我关注的 UP 主列表。 | 97 | C | ON_DEMAND |
| 35 | `bilibili.get_later_watch` | `bilibili.py:332` | 拿稍后再看列表。 | 36 | C | ON_DEMAND |
| 36 | `bilibili.get_favorites` | `bilibili.py:355` | 拿我的收藏夹列表（不含夹内视频，第一版只列夹）。 | 36 | C | ON_DEMAND |

#### music (13)

| # | name | 文件:行 | description（截 50 字） | schema 字符 | consumers | trigger_modes |
|---|---|---|---|---|---|---|
| 37 | `netease.daily_recommend` | `netease_music.py:263` | 拉取网易云今日推荐歌单（30 首）并**自动播放**。 | 52 | C | ON_DEMAND |
| 38 | `netease.personal_fm` | `netease_music.py:328` | 开启网易云私人 FM / 心动模式（无限流推荐）。 | 52 | C | ON_DEMAND |
| 39 | `netease.play_song` | `netease_music.py:393` | 搜索关键词并播放第一个匹配结果。 | 158 | C | ON_DEMAND |
| 40 | `netease.play_playlist` | `netease_music.py:460` | **两步流程的第一步**：列出用户所有自建/收藏歌单。 | 52 | C | ON_DEMAND |
| 41 | `netease.play_playlist_by_id` | `netease_music.py:493` | 唤起本地网易云 App 播放指定 ID 的歌单。 | 159 | C | ON_DEMAND |
| 42 | `netease.like_current` | `netease_music.py:564` | 给当前正在播放的歌曲加红心（收藏）。 | 205 | C | ON_DEMAND |
| 43 | `netease.search` | `netease_music.py:602` | 在网易云搜索关键词；**不播放**，仅返结果。 | 291 | C | ON_DEMAND |
| 44 | `netease.local_play_song` | `netease_playback.py:60` | 本地 mpv 自解码播放网易云单曲。 | 91 | C | ON_DEMAND |
| 45 | `netease.local_play_playlist` | `netease_playback.py:130` | 本地 mpv 播放网易云歌单全曲。 | 129 | C | ON_DEMAND |
| 46 | `netease.local_pause` | `netease_playback.py:241` | 暂停当前 mpv 播放（保留进度，可 resume）。 | 36 | C | ON_DEMAND |
| 47 | `netease.local_resume` | `netease_playback.py:263` | 恢复暂停的 mpv 播放。 | 36 | C | ON_DEMAND |
| 48 | `netease.local_stop` | `netease_playback.py:283` | 停止 mpv 播放并清空播放队列。 | 36 | C | ON_DEMAND |
| 49 | `netease.local_next_in_queue` | `netease_playback.py:307` | 切到 play_playlist 入队的下一首。 | 36 | C | ON_DEMAND |

#### screen (4)

| # | name | 文件:行 | description（截 50 字） | schema 字符 | consumers | trigger_modes |
|---|---|---|---|---|---|---|
| 50 | `screen.get_active_app` | `screen.py:43` | 查当前 macOS frontmost 应用名。 | 52 | C | ON_DEMAND |
| 51 | `screen.get_browser_url` | `screen.py:70` | 查用户当前在看的浏览器 tab URL + 标题（Chrome / Safari）。 | 52 | C | ON_DEMAND |
| 52 | `screen.get_browser_content` | `screen.py:98` | 查用户当前浏览器 active tab 的 URL，并 fetch 公开页面正文。 | 175 | C | ON_DEMAND |
| 53 | `screen.get_active_document` | `screen.py:150` | 查 macOS 当前 frontmost 的 Word / Pages 文档路径。 | 52 | C | ON_DEMAND |

#### social (1)

| # | name | 文件:行 | description（截 50 字） | schema 字符 | consumers | trigger_modes |
|---|---|---|---|---|---|---|
| 54 | `xhs.parse_url` | `xiaohongshu.py:28` | **只做被动 URL 解析**。用户主动贴小红书笔记链接时调用。 | 141 | C | ON_DEMAND |

#### system (2)

| # | name | 文件:行 | description（截 50 字） | schema 字符 | consumers | trigger_modes |
|---|---|---|---|---|---|---|
| 55 | `time.now` | `time_capability.py:37` | 获取当前的精确时间、时区和星期。 | 52 | C+S | ON_DEMAND |
| 56 | `proactive.snooze_wake_call` | `snooze_capability.py:44` | 推迟下次「叫醒」简报触发 N 分钟。 | 163 | C | ON_DEMAND |

#### memory（chat.py 内联 `MEMORY_TOOLS`，不走 CapabilityRegistry）(4)

| # | name | 文件:行 | description（截 50 字） | schema 字符 | consumers | 备注 |
|---|---|---|---|---|---|---|
| 57 | `save_memory` | `chat.py:459` | **仅在用户明确要求记住时**调用本工具。 | ~140（含 enum 列） | C | 直接 list[dict] 拼 tools= |
| 58 | `delete_memory` | `chat.py:500` | 当用户主动要求忘掉某件事时调用。 | ~100 | C | 同上 |
| 59 | `list_memories` | `chat.py:520` | 列出当前关于用户的所有记忆。 | 32 | C | 同上，无 params |
| 60 | `compress_memories` | `chat.py:531` | 整理 + 去重 + 合并记忆库。 | 32 | C | 同上，无 params |

#### builtin（`backend/tools/builtin.py`，走 ToolRegistry 不走 CapabilityRegistry）(1 活)

| # | name | 文件:行 | description（截 50 字） | schema 字符 | consumers | 备注 |
|---|---|---|---|---|---|---|
| 61 | `clear_short_term` | `builtin.py` + `registry.py:99` | 清空当前用户的短期对话缓冲（仅清近端 turns，不动长期记忆）。 | 38 | C | 真活 |
| (休眠) | `switch_character` | `builtin.py:16` | 函数 + schema 保留；`registry.py:95-98` 注释明示**LLM 已下线**，前端切角色走 WS frame `character_switch`，不依赖此 tool | n/a | n/a | 不进 `tools=` |

#### mcp_external（runtime 反向注册，`config.yaml:129-170` 中 `enabled=true` 的客户端）

| # | client name | config 位置 | enabled | expose_via_skyler | 静态可知 tool 数 |
|---|---|---|---|---|---|
| (a) | `filesystem-skyler` | `config.yaml:162-170` | **true** | true | runtime 决定（典型 Anthropic filesystem MCP server 暴露 ~6-11 tool：`read_file` / `write_file` / `list_directory` / `create_directory` / `move_file` / `search_files` / 等） |
| - | `filesystem` | `config.yaml:130-139` | false | true | （未启用） |
| - | `brave-search` | `config.yaml:140-150` | false | false | （未启用） |
| - | `notion` | `config.yaml:151-161` | false | false | （未启用） |

→ 静态枚举**不 runtime probe**；本刀以 `enabled` flag + `_capability_from_external_tool` (`mcp/client.py:221-285`) 命名规则 `ext.filesystem-skyler.<tool_name>` 标位

### 1.3 数量核算 + README "67 capability" 差异说明

| 来源 | 数量 | 是否进 LLM `tools=` |
|---|---|---|
| `@register_capability` 装饰器 | 56 | 53（含 CHAT_AGENT consumer 者）；3 个仅 SCHEDULER 不进 LLM |
| `MEMORY_TOOLS`（chat.py 内联） | 4 | 4（全进） |
| `builtin.py` 真活 | 1（`clear_short_term`） | 1 |
| `builtin.py` 休眠 | 1（`switch_character`） | 0（已下线） |
| MCP runtime `ext.filesystem-skyler.*` | 静态未知，运行时反向注册 | runtime（典型 6-11） |
| **小计静态可枚举** | **62** | **58** |

**与 INV-3 §1.1 实测对账**：

- §1.1 在 HEAD `f67dc37` 时点实测 `MEMORY_TOOLS 4 + ToolRegistry list_schemas() 54 = 58`
- 本刀静态计：53（CHAT_AGENT 装饰器）+ 1（`clear_short_term`）+ 4（`MEMORY_TOOLS`）= **58 ✅ 对得上**
- → INV-3 §1.1 时点 MCP `filesystem-skyler` 反向注册的 ext.* schema **未参与 `list_schemas()` 统计**（运行时 MCP 连接失败 / 时序未注册完 / 或 `_capability_from_external_tool` 路径绕开了 `list_schemas`）。**本刀仅记录此事实，不深查**

**与 README "67 capability" 差异**：

| 解释候选 | 证据 |
|---|---|
| A · README 是历史固定值，c1d65ff todos retire 后未及时回填（67 含已删的 todos 链） | INV-3 §⑥/§⑦ 已结案 c1d65ff 退役 12 文件 + memory_agent dead，todos LLM 写入路径已断 |
| B · README 67 = 含 MCP `filesystem-skyler` 运行时反向注册的 ~6-9 个 ext.* tool（58 + ~9 = ~67） | `mcp/client.py:225` ext.* 命名规则 + filesystem-skyler 是唯一 enabled |
| C · README 67 = 含 SCHEDULER-only 3 个 capability（58 + 3 SCHEDULER-only + ~6 MCP = ~67） | 候选 A + B 合并 |
| D · README "67 cap" 是 UX-002 / UX-003 时期 Settings UI 用户可见数（含 SCHEDULER-only + ext.*） | README:550-560 UX-002/003 描述明示"全部 67 capability accordion 化" |

→ 候选 D 最可信。**README "67" 是 UX 视角全集**（含 SCHEDULER-only 3 + MCP runtime ext.\* ~6-9）；本刀治理对象 = **LLM `tools=` 实际看到的 58 schema + MCP runtime ext.\***（即 token 真正占用面）。

### 1.4 收口

- ✅ 全 capability 枚举完，**静态 62**（56 装饰器 + 4 MEMORY_TOOLS + 1 builtin 活 + 1 builtin 休眠）+ **MCP runtime 静态未知**
- ✅ 与 INV-3 §1.1 实测 58 schema 对账成功（53 CHAT_AGENT 装饰器 + 1 builtin + 4 MEMORY_TOOLS）
- ✅ README "67" 差异 4 候选列清，倾向候选 D（UX 视角全集含 SCHEDULER-only + MCP runtime）
- 🔒 本节零代码 / config / DB 改动，纯只读勘查 + AST 静态分析
- ➡️ **第一步完成，停手报 PM。等 PM 看完本表后再开始第二步 proactive / reactive 二分**

