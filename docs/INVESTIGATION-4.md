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

---

## §3 三类候选评估（第三步 · 纯只读）

> 接 §2 分类（1 proactive / 5 hybrid / 52 reactive）。本节对 P1 入口折叠 / P2 描述精简 / P3 character.set_activity 退役 三类做评估，**产出 v4.1 实施清单**。
>
> 估算口径(per INV-5 §3 实测数据):tools_schema 实测 13,250 token / 58 cap ≈ **平均 228 tokens/cap**(包含 function-calling wrap + JSON-serialized parameters_schema)。每个折叠后入口 cap ≈ **250-350 token**(union schema 加 action enum 多一些参数)。

### 3.1 P1 入口折叠评估

#### 3.1.1 Group A · bilibili 11 cap → 1

**当前 11 cap**(总 schema chars 3,460 / ~2,500 token est):

| # | cap name | desc chars | ps chars | 主要参数维度 |
|---|---|---|---|---|
| 26 | `bilibili.search_video` | 233 | 153 | keyword / page / page_size |
| 27 | `bilibili.get_video_info` | 326 | 90 | bvid |
| 28 | `bilibili.search_user` | 160 | 119 | keyword / page |
| 29 | `bilibili.get_user_videos` | 237 | 146 | mid / page / page_size |
| 30 | `bilibili.hot_videos` | 146 | 97 | page / page_size |
| 31 | `bilibili.get_ranking` | 209 | 148 | rank_type / day |
| 32 | `bilibili.get_subtitles` | 461 | 90 | bvid |
| 33 | `bilibili.get_my_history` | 182 | 68 | page_size |
| 34 | `bilibili.get_my_followings` | 156 | 97 | mid / page_size |
| 35 | `bilibili.get_later_watch` | 136 | 36 | (无参) |
| 36 | `bilibili.get_favorites` | 134 | 36 | (无参) |

**折叠后入口设计** `bilibili(action: enum, ...params)`:

```python
@register_capability(
    name="bilibili",
    description=(
        "B 站全功能入口。按 action 选具体操作:\n"
        "- search_video / search_user: 搜索视频或 UP 主(keyword)\n"
        "- get_video_info / get_subtitles: 视频元数据 / 字幕(bvid)\n"
        "- get_user_videos / get_my_followings: 看 UP 主投稿 / 关注列表(mid)\n"
        "- hot_videos / get_ranking: 热门 / 排行\n"
        "- get_my_history / get_later_watch / get_favorites: 个人数据"
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": [
                "search_video","get_video_info","search_user","get_user_videos",
                "hot_videos","get_ranking","get_subtitles","get_my_history",
                "get_my_followings","get_later_watch","get_favorites",
            ]},
            "keyword": {"type": "string"},
            "bvid": {"type": "string"},
            "mid": {"type": "integer"},
            "page": {"type": "integer", "default": 1},
            "page_size": {"type": "integer", "default": 20},
            "rank_type": {"type": "string"},
        },
        "required": ["action"],
    },
)
async def bilibili(action: str, **params): ...
```

**后端 dispatcher 草图**:
```python
async def bilibili(action: str, **params):
    handlers = {
        "search_video": _search_video,
        "get_video_info": _get_video_info,
        # ... 11 个
    }
    handler = handlers.get(action)
    if handler is None:
        return {"error": f"unknown action: {action}"}
    return await handler(**params)
```

参数校验位置:每个 sub-handler 自己校验(沿用原 11 cap 的现有校验逻辑,**最小重写**)。

**估省**:
- 折叠后单 cap ≈ 350 token(union schema 加 action enum + 7 个 union 参数)
- 省 ~2,500 - 350 = **~2,150 token**

**实施风险**:**中**
- `tool_addendum.py:103-115` 含 11 个 bilibili cap name 引导文(`"用户说『B 站搜 X』→ bilibili.search_video"`),折叠后需重写成 `→ bilibili(action="search_video", keyword=X)` 形式
- `tool_call_resilience.py:87-89` 含 `<netease.daily_recommend>` 这类 capability-name-as-tag fallback,bilibili 同款 fallback 也可能存在;折叠后 fallback 形式变化
- B 站 API 反爬变化敏感(常见 SESSDATA cookie 过期 / 风控弹窗),但与本折叠无关

#### 3.1.2 Group B · netease 13 cap → 2(web+local)

**当前 13 cap**(总 schema chars 3,796 / ~2,960 token est) 分两套独立 path:

| 子组 | cap | desc chars | ps chars | 备注 |
|---|---|---|---|---|
| **web (7 cap)** | netease.daily_recommend / personal_fm / play_song / play_playlist / play_playlist_by_id / like_current / search | 总 1,611 | 总 1,011 | 借助原生网易云 App URL Scheme |
| **local (6 cap)** | netease.local_play_song / local_play_playlist / local_pause / local_resume / local_stop / local_next_in_queue | 总 1,052 | 总 322 | mpv 自解码自动播放 |

**两路径底层不同**(per tool_addendum.py:88-97 引导),**不应当合成单一 cap**;折叠成 2 个入口:

- `netease_web(action: enum, ...)` — 现有 web API path
- `netease_local(action: enum, ...)` — mpv 本地播放 path

**估省**:
- web 7 cap → 1: ~1,600 → ~350 token,省 ~1,250
- local 6 cap → 1: ~1,360 → ~250 token(参数维度简单),省 ~1,110
- **总省 ~2,360 token**

**实施风险**:**中-高**
- web/local 两路径 LLM 切换语义需保留(tool_addendum.py:97 `"何时用 chunk 1 netease.play_song(旧 URL Scheme 路径):仅当用户..."` 决策逻辑),折叠后 LLM 仍需选 `netease_web(action="play_song")` vs `netease_local(action="play_song")`
- like_current 需 media.now_playing 前置(`tool_addendum.py:48-49`),跨 cap 协议保留
- `<netease.daily_recommend>` capability-name-as-tag fallback(tool_call_resilience hotfix-3)需配套迁移

#### 3.1.3 Group C · media 5 cap → 1

**当前 5 cap**(总 schema chars 887 / ~1,140 token est):

| # | cap | desc chars | ps chars | 参数 |
|---|---|---|---|---|
| 21 | media.next_track | 105 | 52 | (无) |
| 22 | media.previous_track | 38 | 52 | (无) |
| 23 | media.play_pause | 79 | 52 | (无) |
| 24 | media.now_playing | 180 | 52 | (无) |
| 25 | media.set_volume | 123 | 154 | volume 0-100 |

折叠成 `media(action: enum, volume?: int)`:

```python
parameters_schema={
    "type": "object",
    "properties": {
        "action": {"type":"string","enum":[
            "next_track","previous_track","play_pause","now_playing","set_volume",
        ]},
        "volume": {"type":"integer","minimum":0,"maximum":100,
                   "description":"action=set_volume 时必填"},
    },
    "required": ["action"],
}
```

**估省**:5 cap × 228 - 1 cap × 250 = **~890 token**

**实施风险**:**低**
- 5 个 action 参数维度极简(只 set_volume 有 volume 参数)
- 全是系统级 media control,行为稳定无 API 兼容性问题
- tool_addendum.py:57-61 引导段重写为 `media(action="next_track")` 形式

#### 3.1.4 Group D · apple_calendar 4 cap → 1 + calendar router 整合选项

**当前 4 cap**(总 schema chars 1,425 / ~910 token est):

| # | cap | desc chars | ps chars | 参数 |
|---|---|---|---|---|
| 8 | apple_calendar.today_events | 106 | 52 | (无) |
| 9 | apple_calendar.upcoming_events | 97 | 152 | days_ahead |
| 10 | apple_calendar.create_event | 217 | **506** | title / start_iso / duration / desc / cal_name |
| 11 | apple_calendar.delete_event | 134 | 161 | event_id |

折叠成 `apple_calendar(action: enum, ...)`:

```python
parameters_schema={
    "type": "object",
    "properties": {
        "action": {"type":"string","enum":[
            "today_events","upcoming_events","create_event","delete_event",
        ]},
        "days_ahead": {"type":"integer","default":7,"minimum":1,"maximum":30,
                       "description":"action=upcoming_events 时用"},
        "title": {"type":"string","description":"action=create_event 时必填"},
        "start_iso": {"type":"string","description":"ISO 8601 含时区"},
        "duration_minutes": {"type":"integer","default":30},
        "description": {"type":"string"},
        "calendar_name": {"type":"string"},
        "event_id": {"type":"string","description":"action=delete_event 时必填"},
    },
    "required": ["action"],
}
```

**估省**:4 × 228 - 1 × 350 = **~560 token**(create_event 参数多,折叠后 schema 较大)

**实施风险**:**低**
- 4 个 action 参数维度同源(全是日历 CRUD)
- 与 `apple_calendar.py` 现有实现路径同源,折叠仅在 dispatcher 层

**`calendar router` 整合决策(留 PM 拍板)**:

当前 `calendar.today_events` / `upcoming_events` 是 router 层,内部决定 data source(`apple_calendar.*` / `google_calendar.*`)。整合选项:

| 选项 | 描述 | 优劣 |
|---|---|---|
| **D1** | 仅折 apple_calendar 内 4 cap,保留 `calendar.today_events / upcoming_events` router | 改动小;LLM 仍能用 `calendar.today_events` 自动路由 |
| **D2** | 折 apple_calendar 4 + calendar router 2 + google_calendar 2(S-only)→ 单 `calendar(action, source?: enum)` | 改动大;统一入口,LLM 不再纠结 router/具体源;但 router 业务逻辑 + source 选择参数侵入 |
| **D3** | 折 apple_calendar 4 → 1 + 保留 calendar router 2 不动 + google_calendar 2 SCHEDULER-only 不动 | 与 D1 等价 |

→ **CC 倾向 D1/D3**(只动 apple_calendar 4 cap),理由:`calendar.today_events` router 是 LLM 默认入口(per `tool_addendum.py:20-23` 引导),不破坏现有路由约定;`google_calendar.*` 已 SCHEDULER-only 不进 tools=,无 token 收益空间。

#### 3.1.5 P1 入口折叠汇总表

| Group | 当前 cap 数 | 折叠后 cap 数 | 估省 tokens | 实施风险 | 工程量估 |
|---|---|---|---|---|---|
| bilibili | 11 | 1 | **~2,150** | 中 | 2 day |
| netease (web+local) | 13 | 2 | **~2,360** | 中-高 | 2-3 day |
| media | 5 | 1 | **~890** | 低 | 1 day |
| apple_calendar | 4 | 1 | **~560** | 低 | 1 day |
| **总计** | **33** | **5** | **~5,960** | | **~6-7 day** |

**vs PM §2.5 早期估"8-10k"**:实际 ~6k 更准。早期估偏乐观因未扣"折叠后 union schema 含 action enum + 多 union 参数"的开销。即便如此,~6k 减幅是 tools_schema 13.25k 的 **~45%**,与子轨 A 27% 叠加 → 主路径 prompt 22.7k 砍至 ~11k 量级,约 **52% 总 reduction**。

### 3.2 P2 描述精简评估

按 `desc + ps` 总长排,top 10 长 cap:

| # | cap | desc | ps | 总 | 长在哪 |
|---|---|---|---|---|---|
| 54 | `xhs.parse_url` | 548 | 141 | 689 | **被动 URL 解析**段过长,含 4 段语义说明 |
| 10 | `apple_calendar.create_event` | 217 | **506** | 723 | ps 内 5 个参数各自 description 字段累积 |
| 32 | `bilibili.get_subtitles` | **461** | 90 | 551 | 杀手 use case 描述 + 30k 字符截断逻辑说明 |
| 14 | `activity.get_today_summary` | 345 | 52 | 397 | 返回结构 + 隐私语义说明 |
| 18 | `docx.create` | 293 | 297 | 590 | desc 用法说明 + ps 内 file_name/title 等参数注释 |
| 37 | `netease.daily_recommend` | 393 | 52 | 445 | mpv 路径 + URL Scheme 路径双说明 |
| - | `proactive.snooze_wake_call` | 377 | 163 | 540 | wake_call 流程上下文 + 拒绝起床信号枚举 |
| 16 | `activity.search_history` | 326 | 255 | 581 | 隐私(双重黑名单 + idle 过滤)说明 |
| 27 | `bilibili.get_video_info` | 326 | 90 | 416 | 元数据字段枚举 |
| 38 | `netease.personal_fm` | 304 | 52 | 356 | 实际路径 + 历史 chunk 引用 |

**精简策略**:

- 删历史 chunk 引用(`"chunk 1 / chunk 6b hotfix-3"` 等,LLM 不需要 archeology)
- 合并语义重复段(`"用户说『X』时调"` 已在引导文,description 内再写一次冗余)
- 截参数字段 description 到 1 句话(参数名 + 类型 + 主要约束,不重复 description)
- 保留杀手 use case 短句(如 bilibili.get_subtitles 的 `"⭐ 帮我总结这个 B 站视频"`)
- 删 verbose 用法举例(LLM 看 1-2 个例子就够)

**精简前后对照示例 - `xhs.parse_url`**:

```
当前(548 chars):
**只做被动 URL 解析**。用户主动贴小红书笔记链接(xiaohongshu.com / xhslink.com 域名)
时调用,返回 title / text / 图片 url 列表。**注意**:
1. 不能搜索小红书,不能拿 feed,不能模拟登录 — 只解析单条 URL
2. 不接受 share id;必须完整 URL
3. 返 401 / 403 → 该笔记可能私密 / 删除,跟用户解释
4. 长 text 可能含表情 emoji,前端会渲染
5. 图片 url 列表前端会自动渲染图集
6. 解析失败时返 error,跟用户解释"链接可能无效"

建议精简(~150 chars):
小红书笔记 URL 解析。仅接受 xiaohongshu.com / xhslink.com 完整链接,返
{title, text, images}。不支持搜索 / feed / 私密笔记(401/403 时跟用户说明)。
```

**估省**:top 10 长 cap 各砍 ~150-300 chars ≈ 平均 70 token / cap → **~700 tokens**

**实施风险**:**零**(纯文字精简,不动 ps 字段约束 / handler 逻辑)

#### 3.2.1 P2 desc 精简改动提案(Stage 1 草稿,2026-05-21)

> 实施第 1 刀 Stage 1 产出。每条产出 current vs proposed 对照 + 删除内容标注 + 信息丢失评估。**纯文档草稿,Stage 2 PM 拍板后才落代码改 .py。**
>
> Top 10 按 description chars 长度排(排除 `character.set_activity` 因 P3 退役)。

##### 1. `xhs.parse_url` (548 → ~220 chars)

**Current**(548 chars):
> **只做被动 URL 解析**。用户主动贴小红书笔记链接(xiaohongshu.com / xhslink.com 域名)时调用,返回 title / text / images / author / tags。**没有**主动搜索 / 推荐流 / 抓评论 / 账号自动化 capability——如果用户问「帮我搜小红书 X」「拉一下小红书首页」,**如实告诉用户**:「Skyler 不主动爬小红书;你贴具体笔记链接给我就能解析」,**不要瞎编**结果或假装调了什么 capability。
> 拿到内容后用你自己的话总结 / 翻译 / 回答用户问题——不要原样输出 tags 列表 / 完整 text(小红书笔记常有大量 emoji / 标签噪声)。
> 参数:
> - url: 笔记链接(短链 xhslink.com 也支持,自动 follow redirect)
> 返回 ``{title, text, images, author, tags, url, source}``;error 字段:``invalid_url`` / ``blocked_by_antibot``(反爬限流) / ``parse_failed`` / ``timeout`` / ``http_error``。

**Proposed**(~250 chars,PM 拍板回填后):
> 小红书笔记 URL 解析(仅 xiaohongshu.com / xhslink.com 域名,被动解析不主动爬)。用户贴笔记链接时调用,返 {title, text, images, author, tags}。
> 用户问"搜小红书/拉首页"等主动场景如实告知"不主动爬,贴具体链接才解析",不要假装调用。
> 拿到内容后用自己话总结,别原样输出 tag 噪声。
> 参数 url:完整笔记链接(短链自动 follow)。失败 error:invalid_url / blocked_by_antibot / parse_failed / timeout。

**删了什么**:
- 删 "不要瞎编结果" 强调(LLM 一般行为)
- 合并 5 个 error code 枚举到一行
- 删 source 字段(error 文案足够)
- 保留 "用自己话总结,别原样输出 tag 噪声"(PM 2026-05-21 拍板回填:小红书 tag 噪声 LLM 易 dump,30 chars 成本免费规避事故)

**信息丢失评估**:✅(PM 回填后)。tool_addendum 全局兜底 + cap-specific 短引导双保险。

##### 2. `bilibili.get_subtitles` (461 → ~215 chars)

**Current**(461 chars):
> 拿 B 站视频字幕用于内容总结。⭐ 杀手 use case:用户说「帮我总结这个 B 站视频」「这个视频讲了啥」「太长不看」「3 分钟讲完」「视频内容概括一下」时调用,拿到字幕后用你自己的话**总结**(不要原样输出字幕,字幕有时间戳 / 重复 / 口语化)。
> 策略:优先 AI 字幕(多数视频有);无 AI 字幕取 UP 主上传字幕;都没有返 ``source='none'`` —— 此时回话告诉用户「这个视频没有字幕,我没法看到内容」,**不要瞎编内容**。
> **需要 cookie**(B 站 2024-2025 风控限制):未配 BILIBILI_SESSDATA 时返 ``cookie_required``,直接转告用户去 docs/bilibili-setup.md 配。
> 参数(二选一):
> - bvid / aid
> 返回 ``{bvid, title, subtitle_text, source: 'ai'|'manual'|'none', duration, lan, lan_doc}``。

**Proposed**(~215 chars):
> B 站视频字幕用于内容总结。⭐ 杀手 use case:用户说"帮我总结这个 B 站视频/讲了啥/太长不看"时调用,拿字幕后用自己话总结(字幕有时间戳/重复/口语化,别原样输出)。
> 策略:AI 字幕 → UP 主字幕 → source='none'(后者跟用户说"没字幕看不到")。需 BILIBILI_SESSDATA cookie,未配返 cookie_required。
> 参数 bvid / aid 二选一。返 {bvid, title, subtitle_text, source, duration}。

**删了什么**:
- 5 个触发例缩成 3 个核心
- 删 "B 站 2024-2025 风控限制" 历史背景
- 删 "docs/bilibili-setup.md 配" 路径引用(用户配置不是 LLM 问题)
- 删 "不要瞎编内容" 重复强调
- 返字段去 lan / lan_doc(次要)

**信息丢失评估**:✅ 关键策略 + 兜底语义 + cookie 信号全保留。

##### 3. `netease.daily_recommend` (393 → ~200 chars)

**Current**(393 chars):
> 拉取网易云今日推荐歌单(30 首)并**自动播放**。当用户说"放日推 / 听今天的推荐 / 给我来点新歌"时调用,**不**需要用户给关键词。
> 实际播放路径优先级(自动 fall through):
>   1. **mpv 装好 + MUSIC_U cookie OK** → Skyler 内嵌 mpv 自解码真自动播放(``autoplay: true`` 诚实生效);
>   2. **mpv 没装 / cookie 缺 / song URL 失败** → 唤起 NCM 客户端作fallback,返 ``autoplay: false`` + ``hint`` 引导用户装 mpv。
> **调用后看返回的 ``autoplay`` 字段决定回话**:true 时直说「已经在播第 X 首日推」;false 时如实告诉用户「网易云客户端已经打开,但自动播放需要装 mpv...」。

**Proposed**(~200 chars):
> 拉网易云今日推荐歌单(30 首)并自动播放。用户说"放日推/听今天的推荐/给我来点新歌"时调,不需要关键词。
> 路径优先:mpv 装好 + MUSIC_U cookie OK → 内嵌 mpv 真自动播(autoplay=true);否则唤起 NCM 客户端 fallback(autoplay=false + hint 装 mpv)。
> 按 autoplay 字段回话:true 直说"在播第 X 首日推";false 如实说"NCM 已打开但自动播放需装 mpv"。

**删了什么**:
- 编号 1/2 fallback 流程缩成一行
- 删 markdown 加粗字符(LLM 一样能读)
- 例子语缩短

**信息丢失评估**:✅ 全保留(autoplay 字段语义是核心)。

##### 4. `proactive.snooze_wake_call` (377 → ~210 chars)

**Current**(377 chars):
> 推迟下次「叫醒」简报触发 N 分钟。当用户在 wake_call 早晨叫醒后明确表示拒绝起床('再睡' / '还早' / '困' / '不想起' / '再睡 X 分钟')时主动调用。minutes 参数:用户说'再睡 X 分钟'则 minutes=X,没明说用 config 默认(一般 30)。范围 5-120。
> 调用前不需要询问'要推迟多久' —— 从用户原话推断或用默认即可。不要在用户没明确拒绝起床时调用(如'今天天气如何'是切换话题,不是拒绝,应直接回答天气,**不**调本 capability)。
> 返回 ``{ok, run_at, message}``:``run_at`` 是即将触发的 ISO 时间;``ok=false`` 一般是 snooze 时间超过了下一次正常 cron(用户已经睡过头,下次正常叫醒就够了,不需要重复)。

**Proposed**(~215 chars):
> 推迟下次"叫醒"简报触发 N 分钟。用户在 wake_call 早晨明确拒绝起床('再睡'/'还早'/'困'/'不想起'/'再睡 X 分钟')时调用。minutes:用户说'再睡 X 分钟'则 X,否则用 config 默认(一般 30),范围 5-120。
> ⚠️ 用户切换话题(如'今天天气如何')不是拒绝,**不调**本 cap。
> 返 {ok, run_at, message};ok=false = snooze 跨过了下次正常 cron 不需重复。

**删了什么**:
- 删 "调用前不需要询问'要推迟多久' —— 从用户原话推断或用默认即可"(冗余,minutes 参数说明已含)
- "应直接回答天气" 例子保留为 "切换话题不是拒绝" 通用规则
- ok=false 详注精简

**信息丢失评估**:✅ negation 信号(切换话题不调)的关键 ⚠️ 保留显眼。

##### 5. `activity.get_today_summary` (345 → ~190 chars)

**Current**(345 chars):
> 查用户今天(本地日)在各 app / URL 的总停留时长 + 类别分布。当用户问「今天累不累」「今天都干了啥」「我今天看了多久 B 站」时调。返``{available, total_active_seconds, total_active_pretty, top_apps[], by_category{}, recent_focus}``;无数据 → ``{available: false}``。**不会泄露**已被用户拉黑的 app / URL,也**不**包含 idle 期间(用户 AFK)的session。ChatAgent 默认会自动在 system prompt 注入简短今日摘要;本 capability 用于用户问具体细节时(如「我今天在 B 站待了多久」)主动查。

**Proposed**(~190 chars):
> 查用户今天在各 app / URL 的总停留时长 + 类别分布。用户问"今天累不累/都干了啥/看了多久 X"时调。返 {available, total_active_seconds, top_apps[], by_category, recent_focus};无数据 → {available: false}。
> 不返黑名单 app/URL,不含 idle session(双重隐私)。ChatAgent 已在 system prompt 注入简短摘要,本 cap 用于查具体细节。

**删了什么**:
- 返字段 `total_active_pretty` 删(LLM 不需细到 pretty 字段)
- 触发例 3 个缩成 1 行
- "本 capability 用于用户问具体细节时主动查" 缩短

**信息丢失评估**:✅ 全保留。

##### 6. `activity.search_history` (326 → ~190 chars)

**Current**(326 chars):
> 在历史 session 的 ``browser_url / browser_title / app_name`` 字段里搜关键词(case-insensitive substring)。用户问「我之前在哪个网站看过 X」「我那篇 B 站视频是啥时候看的」时调。参数 ``keyword: str``(必填)+ ``days: int``(默 30,clamp [1, 90])。返 ``{available, keyword, matches[]}``,每个 match 含 ``id / app / url / title / start_at / duration_seconds``。黑名单 / idle session 不在返值内(双重隐私)。

**Proposed**(~190 chars):
> 在历史 session 的 browser_url / browser_title / app_name 字段搜关键词。用户问"我之前在哪个网站看过 X / 那篇 B 站视频是啥时候看的"时调。
> 参数 keyword(必填) + days(默 30,clamp 1-90)。返 {available, matches[]} 每 match 含 id/app/url/title/start_at/duration_seconds。黑名单 / idle session 不返(双重隐私)。

**删了什么**:
- "case-insensitive substring" 实现细节删(LLM 默认知道字符串搜索)
- 返字段顶层删 `keyword`(冗余,参数已有)
- 参数类型注释精简

**信息丢失评估**:✅ 全保留。

##### 7. `bilibili.get_video_info` (326 → ~205 chars)

**Current**(326 chars):
> 拿 B 站视频元数据(标题 / UP 主 / 描述 / 时长 / 播放数 / 点赞 / 收藏 / 弹幕 / 评论 等)。用户说「这个视频是谁发的」「这视频多长」「视频简介」或粘了 B 站链接(bilibili.com/video/BVxxx / BV 开头编号)时**默认**调本 capability 拿信息。
> 参数(二选一):
> - bvid: BV 号(推荐,B 站新版主流)
> - aid: AV 号(兼容老链接)
> 返回 ``{bvid, aid, cid, title, description, duration, owner: {mid, name}, stat: {view, like, favorite, ...}, url}``。

**Proposed**(~205 chars):
> 拿 B 站视频元数据(标题/UP 主/描述/时长/播放数/点赞/弹幕/评论等)。用户说"这个视频是谁发的/视频多长/简介"或粘 B 站链接(bilibili.com/video/BVxxx)时**默认**调本 cap 拿信息。
> 参数二选一:bvid(BV 号,新版主流) / aid(AV 号,老链接兼容)。返 {bvid, title, description, duration, owner: {mid, name}, stat: {view, like, favorite, ...}, url}。

**删了什么**:
- 元数据字段枚举:收藏 删(stat.favorite 已含),`cid` 删(LLM 不用)
- 触发例 3 个缩成 2 个
- 参数详注合并一行

**信息丢失评估**:✅ 全保留。

##### 8. `netease.personal_fm` (304 → ~180 chars)

**Current**(304 chars):
> 开启网易云私人 FM / 心动模式(无限流推荐)。用户说"随便放点 / 听点新的 / 私人电台"等无明确目标时调用。
> 实际路径:mpv 装好 → Skyler 内嵌播 FM 首批 ~5 首 + 队列;mpv 没装 → 唤起 NCM 客户端 ``orpheus://personalFM`` (NCM 接管 FM 模式,原生支持 autoplay),``autoplay: false`` 但 NCM 自己会播。
> 看 ``autoplay`` 字段:true 是 Skyler mpv 在播;false 是 NCM 客户端在播(也 OK,FM scheme 是 NCM 自带 autoplay 语义之一)。

**Proposed**(~180 chars):
> 开启网易云私人 FM / 心动模式(无限流推荐)。用户说"随便放点/听点新的/私人电台"等无明确目标时调用。
> 路径:mpv 装好 → 内嵌播 FM 首批 ~5 首(autoplay=true);mpv 没装 → 唤起 NCM FM 模式(autoplay=false 但 NCM 自己播)。
> 看 autoplay 字段回话(false 是 NCM 在播,也算 OK)。

**删了什么**:
- "orpheus://personalFM" URL scheme 删(实现细节)
- "NCM 接管 FM 模式,原生支持 autoplay" 注释合并
- "FM scheme 是 NCM 自带 autoplay 语义之一" 解释删

**信息丢失评估**:✅ 全保留。

##### 9. `netease.local_play_song` (297 → ~190 chars)

**Current**(297 chars):
> 本地 mpv 自解码播放网易云单曲。用户说「放 X 这首歌」「来一首 Y」「听一下 Z」时(先用 netease.search 拿 song_id 再调本 capability)触发。**自动播放真闭环**——不依赖 NCM 客户端是否打开。
> VIP / 付费下架歌曲返试听片段(~30s),返回字段 ``is_trial=True``,如实告诉用户「这是试听片段」。
> 参数:
> - song_id: NCM 歌曲 ID(必填)
> 返回 ``{status, url, is_trial, song_id}``;URL 失效 → ``{error: 'url_unavailable'}``。

**Proposed**(~190 chars):
> 本地 mpv 自解码播放网易云单曲(自动播放闭环,不依赖 NCM 客户端)。用户说"放 X / 来一首 Y / 听一下 Z"时调(先 netease.search 拿 song_id 再调本 cap)。
> VIP/付费下架返试听片段 ~30s,is_trial=True 时如实告诉用户"这是试听片段"。
> 参数 song_id 必填。返 {status, url, is_trial, song_id};URL 失效 → {error: 'url_unavailable'}。

**删了什么**:
- 触发例 3 个缩成单行
- "自动播放真闭环" 改成括号注释
- 参数详注合并

**信息丢失评估**:✅ 全保留。

##### 10. `docx.create` (293 → ~195 chars)

**Current**(293 chars):
> 创建一份新的 Word 文档(.docx),保存到 Skyler 文档沙箱目录。适用场景:用户说「帮我写一份…」「起草一个文档」「做个周报」。
> 参数:
> - filename: 文件名(你按内容自己起名,如 ``周报_2026年05月.docx``。可不带后缀,会自动补 .docx;不能含路径分隔符)
> - title: 文档一级大标题(一句话,不能为空)
> - paragraphs: 正文段落列表(list[str],每段一项;可为空表示只要标题)
> 返回 ``{path, size_bytes}``。若 filename 重复会**覆盖原文件**——需要保留旧版本时让用户先确认。

**Proposed**(~195 chars):
> 创建新 Word 文档(.docx),保存到 Skyler 文档沙箱目录。适用:用户说"帮我写一份/起草个文档/做个周报"。
> 参数:filename(自起,可不带后缀,不含路径分隔符)/ title(一句话非空)/ paragraphs(段落 list[str],可空只要标题)。
> 返 {path, size_bytes}。filename 重复会**覆盖原文件**,需保留旧版时先让用户确认。

**删了什么**:
- 3 段参数详注合并一行
- 触发例缩短
- 文件名举例 "`周报_2026年05月.docx`" 删

**信息丢失评估**:✅ 全保留(覆盖警告醒目保留)。

#### 3.2.2 P2 改动汇总(Stage 1)

| # | cap | current | proposed | 节省 chars | 信息丢失 |
|---|---|---|---|---|---|
| 1 | xhs.parse_url | 548 | ~250 | -298 | ✅(PM 拍板回填"用自己话总结,别原样输出 tag 噪声") |
| 2 | bilibili.get_subtitles | 461 | ~215 | -246 | ✅ |
| 3 | netease.daily_recommend | 393 | ~200 | -193 | ✅ |
| 4 | proactive.snooze_wake_call | 377 | ~215 | -162 | ✅ |
| 5 | activity.get_today_summary | 345 | ~190 | -155 | ✅ |
| 6 | activity.search_history | 326 | ~190 | -136 | ✅ |
| 7 | bilibili.get_video_info | 326 | ~205 | -121 | ✅ |
| 8 | netease.personal_fm | 304 | ~180 | -124 | ✅ |
| 9 | netease.local_play_song | 297 | ~190 | -107 | ✅ |
| 10 | docx.create | 293 | ~195 | -98 | ✅ |
| **合计** | | **3,670** | **~2,030** | **~-1,640** | **10 ✅ / 0 ⚠️**(PM 拍板回填 xhs ⚠️ 后) |

**估省 token**:~1,640 chars × ~0.4 token/char(Qwen tokenizer 中文均值) ≈ **~656 tokens**(与 §3.2 估 ~700 tokens 吻合,偏低 ~6% 正常)。

→ **Stage 1 完成 + PM 拍板回填(2026-05-21),进 Stage 2 落代码**。

### 3.3 P3 character.set_activity 退役评估

#### 当前状态

`backend/capabilities/character_state.py:67-138`:
- desc 282 chars + ps 206 chars ≈ ~150 tokens
- handler 行为:接 `activity` / `thought` → 调 `update_character_state` 写 DB → push WS `state_update` event 给前端

#### 与 `<state_update>` tag 完全功能重叠

`<state_update>` tag 路径(`chat.py:219-260 _parse_state_update`):

| 字段 | tool path (character.set_activity) | tag path (`<state_update>`) |
|---|---|---|
| activity | ✅ required | ✅ optional |
| thought | ✅ optional | ✅ optional |
| mood | ❌ 不支持 | ✅ optional |
| intimacy_delta | ❌ 不支持 | ✅ optional |
| 触发场景 | LLM 自主调(proactive,需 schema 常驻) | LLM 输出尾部内嵌 tag(无 schema,模式约定) |
| DB 写入 | services.update_character_state | services.update_character_state(同函数) |
| WS push | character_state.py 内手动 push | ws.py 主路径已挂 _apply_and_push_state_update |
| Layer A 模板引导 | tool_addendum.py:64(可偶尔调) | layer_a.j2:9 输出格式规范第 2 项 |

→ **tag 路径完全覆盖 tool 路径的 activity/thought 功能,且多支持 mood/intimacy_delta**。`character.set_activity` cap 100% 冗余。

#### Migration path

**Step 1** · 移除 LLM 引导:
- `tool_addendum.py:64-65` 删 `"你可以偶尔调 character.set_activity 更新自己「当前在做什么 / 在想什么」"` 段
- 替换为(可选)`"使用 <state_update activity='...' thought='...' /> 标签即可,不要调 tool"`
- 实际更简洁:layer_a.j2:9 已有 state_update 引导,**直接删 tool_addendum 那段**就行

**Step 2** · 退役 cap:
- 选项 A(clean cut):`backend/capabilities/character_state.py:67-138` 整段删
- 选项 B(consumers 移除):把 `consumers=[Consumer.CHAT_AGENT]` 改为 `consumers=[]`(cap 仍 register 但不进 LLM tools=)— 不优雅,与无 consumer 的 cap 设计风格不一致
- → **选 A**

**Step 3**(可选 · backward-compat 短期):
- ToolRegistry 保留 dispatch 兼容(若 LLM 误调 character.set_activity,fallback 到 update_character_state)
- 1 周观察期后(LLM 完全不再尝试调),再删 backward-compat
- → CC 倾向**跳过 backward-compat**,因 LLM 看不到 schema 就不会调;若误调走 tool_call_resilience 已有 unknown-tool 兜底

#### 估省 + 风险

- **省 ~150 tokens**(cap 单独的 schema)
- **风险**:极低
  - tag 路径已成熟(INV-3 §6 / §7 / §8 多次引用 + chat.py:219-260 解析齐全 + ws.py:1320 主路径处理已 fork 给 proactive `_apply_proactive_state_update`)
  - tool_addendum.py:64 删段后 LLM 不再被引导调,但即便 LLM 尝试调,unknown-tool fallback 返 error 后会自然 retry 用 `<state_update>` tag(LLM 自身有 fallback 能力)

### 3.4 P4 · MCP ext.* lazy-load(挂 v4.1+ backlog,不入本节评估)

> 当前 prod 仅 `filesystem-skyler` 1 个 MCP enabled(per §1.1),lazy-load 收益小(单 MCP 注册的 ext.* 总 token < 1k)。若未来启用多 MCP(Notion / Brave search / 等),re-evaluate。本节不做评估。

### 3.5 v4.1 token 治理子轨 B 实施清单（待 PM 拍板后逐条改代码）

按"风险 × 工程量 × 收益"排序的 PM 决策视图。**总计估省 ~6,800 tokens(子轨 B 单独),与子轨 A 叠加主路径砍 ~52%**。

#### 实施动作 1 · P2 描述精简 top 10 长 cap

- **工程量**:0.5-1 day
- **改动文件**:`backend/capabilities/*.py`(8 个 module 各改 1-2 处 description / parameters_schema)
- **风险**:**零**(纯文字精简,不动行为)
- **估省**:**~700 tokens**
- **触发要求**:无前置
- **何时做**:**先做**(零风险快速收益,且不动接口)

#### 实施动作 2 · P3 character.set_activity 退役

- **工程量**:0.5 day
- **改动文件**:
  - `backend/capabilities/character_state.py`(删 L67-138 cap)
  - `backend/agents/prompt/tool_addendum.py`(删 L64-65 引导段)
- **风险**:**极低**(`<state_update>` tag 已成熟,functionally 重叠)
- **估省**:**~150 tokens**
- **触发要求**:无前置
- **何时做**:**第二做**(独立短工)

#### 实施动作 3 · P1 Group C media 5 → 1

- **工程量**:1 day
- **改动文件**:
  - `backend/capabilities/media_control.py`(5 个 cap 合并为 1,内部 dispatch)
  - `backend/agents/prompt/tool_addendum.py:57-61`(引导段重写为 `media(action="X")` 形式)
- **风险**:**低**(参数维度极简 + 系统级 stable API)
- **估省**:**~890 tokens**
- **触发要求**:dispatcher pattern 走通后,Group D / A / B 可复用

#### 实施动作 4 · P1 Group D apple_calendar 4 → 1

- **工程量**:1 day
- **改动文件**:
  - `backend/capabilities/apple_calendar.py`(4 cap → 1 + dispatcher)
  - `backend/agents/prompt/tool_addendum.py:20-30`(引导段重写)
  - `backend/capabilities/calendar.py`(router 保留 `calendar.today_events / upcoming_events` 不动 — 选 D1)
- **风险**:**低**
- **估省**:**~560 tokens**
- **触发要求**:Action 3 dispatcher pattern 走通

#### 实施动作 5 · P1 Group A bilibili 11 → 1

- **工程量**:2 days
- **改动文件**:
  - `backend/capabilities/bilibili.py`(11 cap → 1 + dispatcher;最大改动)
  - `backend/agents/prompt/tool_addendum.py:103-115`(引导段重写)
  - `backend/agents/tool_call_resilience.py`(若有 `<bilibili.*>` capability-name-as-tag fallback,同步迁移)
- **风险**:**中**
- **估省**:**~2,150 tokens**(最大头)
- **触发要求**:Action 3 dispatcher pattern 走通

#### 实施动作 6 · P1 Group B netease 13 → 2(web+local)

- **工程量**:2-3 days
- **改动文件**:
  - `backend/capabilities/netease_music.py`(7 web cap → `netease_web`)
  - `backend/capabilities/netease_playback.py`(6 local cap → `netease_local`)
  - `backend/agents/prompt/tool_addendum.py:40-50 / 88-97`(双路径引导重写)
  - `backend/agents/tool_call_resilience.py`(`<netease.daily_recommend>` etc. fallback 迁移)
- **风险**:**中-高**(双路径语义切换 + like_current 需 media.now_playing 前置协议)
- **估省**:**~2,360 tokens**
- **触发要求**:Action 5 跑通后,bilibili dispatch pattern 验证可复用;netease 是双 path,设计需仔细

#### 实施动作 7 · v4.1 路径 D A/B 评测(切 DeepSeek 候选,留 v4.1 后期议)

per INV-5 §4.5 + §5.4.5,v4.1 候选,与本子轨 B 正交。

#### 总收益预估表

| 动作 | 收益 (tokens) | 工程量 | 累计收益 | 累计工程量 |
|---|---|---|---|---|
| 1 · P2 desc 精简 | ~700 | 0.5-1 d | 700 | 1 d |
| 2 · P3 set_activity 退役 | ~150 | 0.5 d | 850 | 1.5 d |
| 3 · media 5→1 | ~890 | 1 d | 1,740 | 2.5 d |
| 4 · apple_calendar 4→1 | ~560 | 1 d | 2,300 | 3.5 d |
| 5 · bilibili 11→1 | ~2,150 | 2 d | 4,450 | 5.5 d |
| 6 · netease 13→2 | ~2,360 | 2-3 d | **~6,810** | **~8 d** |

→ **总计 ~6.8k tokens(子轨 B)**,加子轨 A 5.6k cache 收益,主路径 prompt 22.7k → ~10.3k(**减幅 ~55%**)。

### 3.6 收口

- ✅ P1 / P2 / P3 三类候选评估完,实施清单 6 动作排好序
- ✅ 估省 token 与 PM §2.5 早期估 ~8-10k 校正为更准的 **~6.8k**(扣折叠后 union schema 开销)
- ✅ P3 `character.set_activity` 与 `<state_update>` tag 100% 功能重叠,clean cut 删除可
- ✅ P4 MCP lazy-load 挂 v4.1+ backlog
- 🔒 本节零代码 / config / DB 改动,纯只读评估 + 设计草图

**v4.1 实施清单优先级总结**(给 PM 决策视图):

| 排序 | 动作 | 风险 | 收益 | 备注 |
|---|---|---|---|---|
| 1 | P2 desc 精简 | 零 | ~700 | 先做(无前置)|
| 2 | P3 set_activity 退役 | 极低 | ~150 | 第二(独立短工)|
| 3 | media 5→1 | 低 | ~890 | dispatcher pattern 试水 |
| 4 | apple_calendar 4→1 | 低 | ~560 | 复用 pattern |
| 5 | bilibili 11→1 | 中 | ~2,150 | 最大头 |
| 6 | netease 13→2 | 中-高 | ~2,360 | 双路径设计仔细 |

→ **§3 完成。等 PM 拍板后启动逐条改代码刀(4-phase 框架 per 子轨 A 经验)**。

