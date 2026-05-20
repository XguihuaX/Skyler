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

---

## §2 proactive / reactive / hybrid 三分审计（第二步 · 纯只读）

> 接 §1 枚举（58 个进 LLM `tools=` + 3 个 SCHEDULER-only + MCP runtime ext.*）。本节按触发模式三分类，为 §3 候选评估（tag-conversion / 入口折叠 / 描述精简）提供输入。子轨 A · prompt caching 已 INV-5 §5 ship 收口，本节回到子轨 B 工具治理主线。

### 2.1 分类定义（PM 与 CC 前序对齐复述）

- **proactive**：LLM 在**无用户言语线索**时自主决定调用（例：聊天中 LLM 自觉"这事得记"）。**必须 system prompt 常驻**，否则 LLM 不知道存在就不会调（同 `switch_character` 死点，INV-3 早期已踩过）
- **reactive**：用户言语线索触发，LLM 跟随调用（例：用户提到 B 站视频 → `bilibili.search_video`）。**可走 meta-tool 发现**，不需常驻 schema
- **hybrid**：两条 path 都有（例：`calendar.today_events` —— 用户问日程 + cron briefing 主动）。归类时按主要触发模式归

判定证据优先级：
1. `description` 字段内"当用户说/问 X 时调用"明示 → reactive
2. `description` 内"当你想/觉得 X 时" / "LLM 自觉" / 无用户言语 trigger 描述 → proactive
3. `consumers` 含 SCHEDULER + 装饰器 `trigger_modes` 含 SCHEDULED → 主路径为定时触发,LLM 主动调辅 → hybrid

### 2.2 全 capability 分类表（58 LLM 可见 + 3 SCHEDULER-only 占位 + ext.* 注脚）

按 §1 表 category 顺序排,序号继承 §1 表 1-61。

#### activity (3) — 全 reactive

| # | capability | 触发类 | 依据 |
|---|---|---|---|
| 14 | `activity.get_today_summary` | **reactive** | description 明示"当用户问『今天累不累』『今天都干了啥』『我今天看了多久 B 站』时调" |
| 15 | `activity.get_recent_apps` | **reactive** | description 明示"用户问『这周都在干啥』『最近这几天主要用啥』时调" |
| 16 | `activity.search_history` | **reactive** | description 明示"用户问『我之前在哪个网站看过 X』『我那篇 B 站视频是啥时候看的』时调" |

#### calendar (8) — 4 hybrid + 2 reactive + 2 SCHEDULER-only

| # | capability | 触发类 | 依据 |
|---|---|---|---|
| 4 | `calendar.today_events` | **hybrid** | consumers=[C+S], trigger_modes=[ON_DEMAND, SCHEDULED]; 用户问"今天有什么会"为主 + cron `morning_briefing` 自主调辅 |
| 5 | `calendar.upcoming_events` | **hybrid** | 用户问"这周/下周日程"为主 + 同上 cron 调辅 |
| 6 | `google_calendar.today_events` | (S-only · 不进 LLM tools=) | consumers=[S only], cron 专用 |
| 7 | `google_calendar.upcoming_events` | (S-only · 不进 LLM tools=) | 同 #6 |
| 8 | `apple_calendar.today_events` | **hybrid** | 同 #4 (C+S) |
| 9 | `apple_calendar.upcoming_events` | **hybrid** | 同 #5 |
| 10 | `apple_calendar.create_event` | **reactive** | description 明示"用户说『提醒我 X 点 Y 事 / 帮我记一下 / 明天 X 点 Y / 把 X 加到日历』时调用" |
| 11 | `apple_calendar.delete_event` | **reactive** | description 明示"调用前必须先用 today_events / upcoming_events 找到要删的事件" → 用户言语驱动 |

#### character (3) — 1 proactive + 1 reactive + 1 SCHEDULER-only

| # | capability | 触发类 | 依据 |
|---|---|---|---|
| 12 | `character.get_state` | **reactive** | description 明示"当用户问『你最近怎么样』『在干嘛』时调用" |
| 13 | `character.set_activity` | **proactive** ⭐ | description 明示"**当你想让用户感受到「连续性」时偶尔调用** —— 比如长时间没说话后回来时,或者主动开口前" — 无用户言语线索,LLM 自主决定更新自己状态 |
| 14 | `character.intimacy_decay` | (S-only · 不进 LLM tools=) | description 明示"（SCHEDULER）每天 0:00 自动调用",cron 专用 |

#### clipboard (3) — 全 reactive

| # | capability | 触发类 | 依据 |
|---|---|---|---|
| 15 | `clipboard.get_recent` | **reactive** | description 明示"用户提到『刚复制的』『上面那个』『这段』『我刚才复制了什么』时调用" |
| 16 | `clipboard.summarize` | **reactive** | description 明示"用户说『帮我总结一下刚复制的』『这段说的什么』时调用" |
| 17 | `clipboard.translate` | **reactive** | description 明示"用户说『翻译刚复制的』『帮我翻译这段』时调用" |

#### files (3) — 全 reactive

| # | capability | 触发类 | 依据 |
|---|---|---|---|
| 18 | `docx.create` | **reactive** | description 明示"用户说『帮我写一份…』『起草一个文档』『做个周报』" |
| 19 | `docx.read` | **reactive** | description 明示"用户说『读一下我的XX文档』『看看那个周报里都写了啥』" |
| 20 | `docx.append` | **reactive** | description 明示"用户说『再补一段…』『加上 XX 内容』" |

#### media (16) — 全 reactive

| # | capability | 触发类 | 依据 |
|---|---|---|---|
| 21 | `media.next_track` | **reactive** | description 明示"用户说『下一首』"时调用 |
| 22 | `media.previous_track` | **reactive** | description 明示"用户说『上一首』" |
| 23 | `media.play_pause` | **reactive** | description 明示"用户说『暂停 / 播放 / 继续』" |
| 24 | `media.now_playing` | **reactive** | description 含"查当前系统在播什么歌" → 用户问触发 |
| 25 | `media.set_volume` | **reactive** | description 明示"用户说『音量调到 X / 大声点 / 静音』" |
| 26 | `bilibili.search_video` | **reactive** | description 明示"用户说『B 站搜一下…』『B 站上 X 怎么讲的』" |
| 27 | `bilibili.get_video_info` | **reactive** | description 明示"用户说『这个视频是谁发的』『这视频多长』" |
| 28 | `bilibili.search_user` | **reactive** | description 明示"用户说『B 站搜一下 XX UP 主』" |
| 29 | `bilibili.get_user_videos` | **reactive** | description 明示"用户说『XX UP 主最近发了啥』" |
| 30 | `bilibili.hot_videos` | **reactive** | description 明示"用户说『B 站现在有啥热门』" |
| 31 | `bilibili.get_ranking` | **reactive** | description 明示"用户说『B 站排行榜』" |
| 32 | `bilibili.get_subtitles` | **reactive** | description 明示"⭐ 杀手 use case:用户说『帮我总结这个 B 站视频』" |
| 33 | `bilibili.get_my_history` | **reactive** | description 明示"用户说『我最近在 B 站看了啥』" |
| 34 | `bilibili.get_my_followings` | **reactive** | description 明示"用户说『我关注了哪些 UP 主』" |
| 35 | `bilibili.get_later_watch` | **reactive** | description 明示"用户说『我的稍后再看里有啥』" |
| 36 | `bilibili.get_favorites` | **reactive** | description 明示"用户说『我有哪些 B 站收藏夹』" |

#### music (13) — 全 reactive

| # | capability | 触发类 | 依据 |
|---|---|---|---|
| 37 | `netease.daily_recommend` | **reactive** | description 明示"用户说『放日推 / 听今天的推荐』" |
| 38 | `netease.personal_fm` | **reactive** | description 明示"用户说『随便放点 / 听点新的 / 私人电台』" |
| 39 | `netease.play_song` | **reactive** | description 明示"用户说『放某某歌 / 听某歌手的某某 / 来一首 X』" |
| 40 | `netease.play_playlist` | **reactive** | description 明示"用户说『放我的红心歌单 / 放我那个跑步歌单』" |
| 41 | `netease.play_playlist_by_id` | **reactive** | 两步流程第二步,#40 触发后 LLM 自动接力,根触发仍是用户言语 |
| 42 | `netease.like_current` | **reactive** | description 暗示"给当前播放歌加红心" → 用户言语"喜欢/收藏"触发 |
| 43 | `netease.search` | **reactive** | description 明示"用户问『网易云有没有 X / 这首歌的歌手是谁』" |
| 44 | `netease.local_play_song` | **reactive** | description 明示"用户说『放 X 这首歌 / 来一首 Y』" |
| 45 | `netease.local_play_playlist` | **reactive** | description 明示"用户说『放 X 歌单』" |
| 46 | `netease.local_pause` | **reactive** | description 明示"用户说『暂停 / 停一下』" |
| 47 | `netease.local_resume` | **reactive** | description 明示"用户说『继续 / 接着放』" |
| 48 | `netease.local_stop` | **reactive** | description 明示"用户说『停止 / 关掉音乐 / 别放了』" |
| 49 | `netease.local_next_in_queue` | **reactive** | description 明示"用户说『下一首 / 切歌』" |

#### screen (4) — 4 reactive（边缘 hybrid，见 §2.4 notable）

| # | capability | 触发类 | 依据 |
|---|---|---|---|
| 50 | `screen.get_active_app` | **reactive** | description"查当前 macOS frontmost 应用名" 无明示 trigger 词,但生产典型场景 = 用户问"我在用什么 app" / LLM 困惑时自查;主流量 reactive |
| 51 | `screen.get_browser_url` | **reactive** | description"查用户当前在看的浏览器 tab URL + 标题",**仅在浏览器是 macOS frontmost 应用时返回** — 多数 LLM 在用户提及网页时调 |
| 52 | `screen.get_browser_content` | **reactive** | description"查用户当前浏览器 active tab 的 URL,并 fetch 公开页面正文" — 用户说"帮我看下这页/总结这页"触发 |
| 53 | `screen.get_active_document` | **reactive** | description"查 macOS 当前 frontmost 的 Word / Pages 文档路径" — 用户问"我刚才那个文档"触发 |

#### social (1) — reactive

| # | capability | 触发类 | 依据 |
|---|---|---|---|
| 54 | `xhs.parse_url` | **reactive** | description 明示"**只做被动 URL 解析**。用户主动贴小红书笔记链接时调用" |

#### system (2) — 1 hybrid + 1 reactive

| # | capability | 触发类 | 依据 |
|---|---|---|---|
| 55 | `time.now` | **hybrid** | consumers=[C+S]; description"用户问『现在几点』或需要做时间相关判断（晚安提醒 / 工作日识别 / 时段问候）时调用" — LLM 自主时间感知判断也常用 |
| 56 | `proactive.snooze_wake_call` | **reactive** | description 明示"当用户在 wake_call 早晨叫醒后明确表示拒绝起床（'再睡' / '还早' / '困' / '不想起'）时调用" — 用户言语驱动 (name 含 proactive 是 misnomer,行为 reactive) |

#### memory `MEMORY_TOOLS`（chat.py 内联，4 条全 reactive）

| # | capability | 触发类 | 依据 |
|---|---|---|---|
| 57 | `save_memory` | **reactive** | description 明示"**仅在用户明确要求记住时**调用本工具" — 用户的明确信号:『请记住 X』『以后 X 都...』『别忘了 X』『你要记住 X』。**日常对话事实的提取走 background worker(chunk 10),不需要本 tool**(see §2.4 notable) |
| 58 | `delete_memory` | **reactive** | description 明示"当用户主动要求忘掉某件事时调用" |
| 59 | `list_memories` | **reactive** | description 明示"当用户问『你都记得什么』,或需要查找特定记忆删除/修改时调用" |
| 60 | `compress_memories` | **reactive** | description 明示"当用户要求『整理记忆』或记忆条数过多时调用" |

#### builtin (1)

| # | capability | 触发类 | 依据 |
|---|---|---|---|
| 61 | `clear_short_term` | **reactive** | description 明示"仅在用户明确说『清空对话 / 重新开始 / 忘掉刚才的话题』等时调用" |

#### MCP runtime ext.\*（一行汇总）

> `ext.<server>.<tool>` 由 LiteLLM dispatch + 各 MCP server 上游决定,**runtime 反向注册不固定**。schema 字面来自上游 server(我们不控)。默认全部归 **reactive**(per CC §1.4 早期分析:用户言语触发 fs/search/notion 等外部能力,LLM 不主动 ping)。当前 production enabled = `filesystem-skyler` 仅一家(per §1.1)。

### 2.3 分类统计摘要

按 58 个进 LLM `tools=` 的 capability 统计:

| 触发类 | 数量 | 占比 | 列表 |
|---|---|---|---|
| **proactive** | **1** | **1.7%** | `character.set_activity` |
| **hybrid** | **5** | **8.6%** | `calendar.today_events` / `calendar.upcoming_events` / `apple_calendar.today_events` / `apple_calendar.upcoming_events` / `time.now` |
| **reactive** | **52** | **89.7%** | 其余全部 |
| **小计 (LLM 可见)** | **58** | **100%** | |

外加(不进 LLM `tools=`):

- **SCHEDULER-only** 3 个:`character.intimacy_decay` / `google_calendar.today_events` / `google_calendar.upcoming_events` — cron / 调度专用,LLM 不可见
- **MCP runtime ext.\*** runtime 不固定,默认 reactive(详 §2.2 注脚)

### 2.4 notable findings

#### 2.4.1 严格 proactive 仅 1 个,远低于 PM 早期预测的 ≤5

PM brief 估计"真 proactive 不超过 5 个"。严格按 description 字面判定(无用户言语 trigger 词),实际**仅 `character.set_activity` 1 个**符合。这意味:

- **schema 常驻强制约束极弱**:绝大部分 capability 可走 meta-tool / lazy-load,常驻 system prompt 只为 1 个 capability 不划算
- **§3 tag-conversion 候选评估范围窄**:tag-conversion 主要服务 proactive(常驻又 schema 重),只 1 个候选评起来 ROI 有限
- **§3 入口折叠 / lazy-load 主战场**:reactive 52 个 + ext.* 全是 lazy-load / 入口折叠候选

#### 2.4.2 `save_memory` 与 PM brief 例子矛盾(产品决策决定)

PM brief 用 `save_memory | proactive | "LLM 在 chat 中自主决定『这事得记』"` 当例子。但 `chat.py:459` description 明确写:

> **仅在用户明确要求记住时**调用本工具。用户的明确信号:『请记住 X』『以后 X 都...』

且 description 接着补:

> 日常对话事实的提取走 background worker(chunk 10),不需要本 tool。

→ **产品决策上 save_memory 设为 reactive**(LLM 不应自作主张),日常事实抽取交给 `MemoryExtractor` 后台 worker(extractor.py:316,300s tick)。所以本表归 reactive。

若 PM 想让 save_memory 同时支持 LLM 自主调用 → 需改 description 措辞放开 trigger 约束,不在本刀范围。

#### 2.4.3 `screen.*` 4 个属"hybrid 边缘"(归 reactive 保守)

`screen.get_active_app` / `get_browser_url` / `get_browser_content` / `get_active_document` 4 条 description 都**无明示"当用户问 X"** trigger 词,理论上 LLM 在"想知道用户在干嘛"时可自主调用(尤其在 activity_smart 慢路径决策场景)。但:

- 生产典型场景仍是用户提及触发(例:"我刚才那个网页"/"帮我看这页")
- 自主调用模式罕见(LLM 多数被动等用户问)
- description 不诱导 LLM 自主调

本表归 **reactive 保守**。若未来扩 proactive 用法(如让 LLM 真自主"我看看用户在干啥"),这 4 条候选升级为 proactive。

#### 2.4.4 `proactive.snooze_wake_call` 是 reactive(name misnomer)

capability name 含 `proactive.`,但 description 明确:

> 当用户在 wake_call 早晨叫醒后**明确表示拒绝起床**('再睡' / '还早' / '困' / '不想起' / '再睡 X 分钟')时调用

→ 触发依赖用户言语,行为 reactive。`proactive.` 前缀是 namespace 归属(放在 `backend/proactive/snooze_capability.py`),不是触发模式。

#### 2.4.5 hybrid 5 个全是 calendar / time 类

`calendar.today_events` / `upcoming_events` / `apple_calendar.today_events` / `upcoming_events` / `time.now` — 全部因 cron briefing(`morning_briefing` / `wake_call_briefing` / `lunch_call` / `dinner_call`)主动调用而归 hybrid。其它"双触发"模式罕见。

### 2.5 §3 候选评估优先级建议(CC 倾向,待 PM 拍板)

按"治理 ROI / 工程量 / 风险"三维度,§3 三类候选评估的优先级:

#### 优先级 1 · 入口折叠(最大 token 砍头候选)

| 折叠候选 group | 成员数 | 描述同源度 |
|---|---|---|
| `bilibili.*` | 11 个 | 极高(全部 B 站操作,参数维度 keyword / page / mid / bvid 高度同源) |
| `netease.*` | 13 个(7 music + 6 playback) | 高(网易云搜索/播放/控制) |
| `media.*` | 5 个 | 中(媒体控制,但语义已经简单各 50-150 schema chars) |
| `clipboard.*` | 3 个 | 中(get_recent + summarize + translate 三步组合) |
| `docx.*` | 3 个 | 中(create + read + append) |
| `activity.*` | 3 个 | 中(today / recent / search) |
| `screen.*` | 4 个 | 中(get_active_app / browser_url / browser_content / active_document) |
| `apple_calendar.*` | 4 个 | 高(today / upcoming / create / delete) |

**主战场 = bilibili + netease + media + apple_calendar = 33 个 capability(占 LLM 可见 57%)**。折叠成 ~5-8 个入口 capability(`bilibili(action=...)` / `netease(action=...)` / 等),按 INV-5 §3 数学外推可省 8-10k tokens(tools_schema 13.25k 的 60-75%)。

#### 优先级 2 · 描述精简(零风险快速收益)

INV-4 §1 表里有些 description >300 char(如 `xhs.parse_url` 548 / `netease.daily_recommend` 393 / `proactive.snooze_wake_call` 377 / `apple_calendar.create_event` 506 schema chars)。逐条精简到 ~100 char 内,**零行为风险**,~500-1500 tokens 收益。

#### 优先级 3 · tag-conversion(候选范围窄,留观察)

只有 1 个 proactive(`character.set_activity`)符合候选。单独 tag 化 ROI 小,与现有 `<state_update>` tag 重叠(state_update 已含 activity 字段)。**建议 §3 评估时考虑直接把 `character.set_activity` 退役,让 LLM 走 `<state_update activity="..." />` tag 路径**(已有 Skyler inline tag 先例)。

#### 优先级 4 · MCP ext.\* lazy-load(未来扩展用,本子轨 B 不入)

当前 prod 仅 1 个 MCP enabled(`filesystem-skyler`),lazy-load 收益小。若未来启用多 MCP(Notion / Brave search 等),re-evaluate。

### 2.6 收口

- ✅ 58 个 LLM 可见 capability 全部三分类完(1 proactive / 5 hybrid / 52 reactive)
- ✅ 3 个 SCHEDULER-only 占位标记 + ext.* 注脚
- ✅ 严格判定"无用户言语 trigger 词"得 proactive 仅 1 条 = `character.set_activity`,远低于 PM 预测 ≤5(notable §2.4.1)
- ✅ notable findings 5 条覆盖:proactive 稀缺 / save_memory 与 brief 例矛盾 / screen.* 边缘 / snooze_wake_call name misnomer / hybrid 全 calendar+time 类
- ✅ §3 候选评估优先级建议给出:入口折叠主战场 bilibili+netease+media+apple_calendar 33 个 capability,描述精简快速收益,tag-conversion 范围窄留观察
- 🔒 本节零代码 / config / DB 改动,纯只读 description 字面分析

→ **§2 完成。等 PM 看完分类 + 候选评估优先级建议后再开 §3。**

