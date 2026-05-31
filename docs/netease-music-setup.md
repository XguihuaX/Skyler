# 网易云音乐接入（v3-H chunk 1 · 2026-05-31 update · mpv-first 闭环已通)

> **2026-05-31 status update**:本文档原版围绕"唤起 NCM 客户端"叙述。
> v3.5 chunk 6b 起新增 **mpv-first 路径**(内嵌 mpv 自解码 · 真自动播放
> 闭环 · 不依赖 NCM 客户端)· 2026-05-31 INV-16 Patch A 修通 weapi
> rotation 后 mpv-first 在 PM 真机 daily_recommend 已通(Reaching Light
> ✅)。本文档保留原 NCM 客户端 setup 章节(Mode B 路径 · 仍 work 但有
> 限制 · 见末尾 trade-off 章节)· 默认推 mpv-first(Mode A)。

Skyler 内置网易云接入:通过网易云 web API 拿日推 / 歌单 / 搜索 · 默认走
**mpv-first** 内嵌自动播放(`brew install mpv` 后即生效)· fallback 到
**官方网易云 App** URL Scheme(无 mpv 时)。**不下载流、不绕版权、不需要
任何第三方 SDK**。

## 一、装机要求

**Mode A · mpv-first(默认 · 推荐 · 真自动播放闭环):**
- macOS / Linux 都可(mpv 跨平台)
- 已安装 **`mpv`** (`brew install mpv` · 当前测试 v0.41.0)
- Skyler 后端依赖:``pycryptodome``(已写入 `requirements.txt`)

**Mode B · NCM 客户端 URL Scheme(fallback · 仅 macOS · mpv 缺时自动用):**
- macOS only
- 已安装 **网易云音乐 macOS 客户端**(App Store / 官网下载)
- 已安装 **`nowplaying-cli`**(用于触发自动播放 · 详见 Mode B 章节)
  ```bash
  brew install nowplaying-cli
  ```
- 已知限制:URL Scheme `orpheus://song/X/play` 仅跳转不自动播放 · 需
  `nowplaying-cli play` 兜底 · 偶发不响应(2026-05-30 audit 实证不稳定)

```bash
pip install -r requirements.txt
```

### 自动播放（chunk 1 patch · 2026-05-08）

orpheus URL Scheme 在网易云 macOS 客户端的最新版本上**不会自动播放**——`open
"orpheus://playlist/X/play"` 只跳转到歌单页，需要手动点播放键。

Skyler 用 `nowplaying-cli play` 兜底：唤起 App 后等 1.5s（让 NCM 启动 + 加载 UI
+ 注册 MediaRemote 媒体源），然后通过系统 MediaRemote framework 触发播放。
**已被 `media.*` capability 用作底层依赖**——如果 `media.*` 工作，自动播放也会工作。

> ⚠️ 我们**没有**用 AppleScript `tell application "网易云音乐" to play`：网易云 App
> 没注册 AppleScript scripting dictionary（包内无 `.sdef`、`Info.plist` 无
> `OSAScriptingDefinition`），这条命令会被 osascript 拒绝。`nowplaying-cli` 走的
> 是 macOS 系统级 MediaRemote framework，不依赖 App 自身的 scripting 支持。

### 首次使用授权

第一次让 Momo 放歌时，**理论上不弹任何权限框**（MediaRemote framework 是公开 API
路径，不需 Accessibility / Automation 权限）。如果意外弹了"是否允许 X 控制
NeteaseMusic"对话框：

1. 点 **允许**
2. 如果不慎拒绝：系统设置 → 隐私与安全性 → 自动化 → 找到 `python` 或 `uvicorn`
   或 Skyler → 勾选下方对应条目

> 所有权限弹框是 macOS 系统级行为，与 Skyler 代码无关——授权后是机器级一次性。

## 二、抓 MUSIC_U cookie

网易云 web API 鉴权靠 `MUSIC_U` cookie。Chrome 步骤：

1. 打开 <https://music.163.com> 用你的账号登录
2. **F12** → 顶栏切到 **Application**（中文版可能叫"应用"）
3. 左栏 → **Cookies** → 选 `https://music.163.com`
4. 在右侧表格里找 `MUSIC_U` 那一行
5. **双击 Value 单元格** → 复制全部（很长一串十六进制）

> Safari 用户：Develop → Show Web Inspector → Storage → Cookies。

## 三、写入 `.env`

在项目根目录的 `.env` 里：

```bash
NETEASE_MUSIC_U=粘贴你刚才复制的 MUSIC_U 值
```

⚠️ **MUSIC_U 等同账号凭证**：
- **不要 commit `.env`**（项目 `.gitignore` 已经排除）
- **不要分享给别人** —— 别人拿到后能完整登录你的账号
- **不要写到聊天 / 截图里**

## 四、验证

重启 Skyler backend：

```bash
uvicorn backend.main:app --reload
```

启动日志里应见 `netease.* registered`（7 个 capability）。打开前端 → 设置 → 能力面板 → "music" 类目应有 7 张卡片，所有卡片状态应是 **healthy** 绿点。如果是 **warn** 黄点，看错误信息：

| 错误信息 | 解释 + 修法 |
|---|---|
| 未配置 NETEASE_MUSIC_U cookie | `.env` 里 `NETEASE_MUSIC_U=` 是空的 → 按上面第二步抓 |
| cookie 失效或账号未登录 | MUSIC_U 过期了 → 浏览器登录一次重新抓（网易云 cookie 一般几个月才失效，但被风控 / 异地登录 / 手动改密码会立即失效）|
| 网络异常 | 国内能直连 music.163.com，挂代理时也基本不影响。如果代理 TUN 模式劫持 Python 流量可能出错 → 暂时关代理或换网络 |

## 五、聊天示例

跟 Momo 说，看后端日志的 `tool_calls`：

| 你说 | 期望工具序列 | 期望效果 |
|---|---|---|
| 放今天的日推 | `netease.daily_recommend` | 网易云 App 自动开播日推队列 |
| 随便放点 / 听点新的 | `netease.personal_fm` | App 进入私人 FM |
| 放一首夜空中最亮的星 | `netease.play_song` | App 直接放这首 |
| 放我那个跑步歌单 | `netease.play_playlist` → `netease.play_playlist_by_id` | LLM 模糊匹配出歌单 → App 开播 |
| 网易云有没有周杰伦的稻香 | `netease.search` | 返结果（不播放） |
| 好听！加红心 | `media.now_playing` → `netease.like_current` | 当前网易云歌曲被红心 |

## 六、能力清单(2026-05-21 INV-7 §2 P1.netease fold 后:2 dispatcher × 14 action + 5 media = 19 total)

### `netease_web` dispatcher · 7 actions(web API · mpv-first + URL Scheme fallback)

| action | 入参 | 行为 |
|---|---|---|
| `daily_recommend` | 无 | 拉日推 → mpv 后台播(Mode A · autoplay=true)/ NCM 客户端跳转(Mode B · autoplay=false) |
| `personal_fm` | 无 | 私人 FM 队列(Mode A 自动播第一首 · Mode B 唤起 `orpheus://fm`) |
| `play_song` | `keyword: str` | search → 第一结果 → Mode A 直接 mpv 播 / Mode B 唤起客户端(**一步闭环** · 2026-05-31 tool_addendum 统一) |
| `play_playlist` | 无 | **只列**用户所有歌单(让 LLM 模糊匹配)|
| `play_playlist_by_id` | `playlist_id: int` | 按 ID 放歌单(接 play_playlist 第二步) |
| `like_current` | `title: str`, `artist?: str` | search → like (前置 now_playing 拿 title) |
| `search` | `keyword`, `search_type` | 返结果,不播放(`search_type` ∈ song/album/artist/playlist) |

### `netease_local` dispatcher · 7 actions(mpv 直接控 · Mode A 路径专用)

| action | 入参 | 行为 |
|---|---|---|
| `play_song` | `song_id: int` | 直接 mpv 播指定 song_id(已知 ID 时用 · 跳过 search) |
| `play_playlist` | `playlist_id: int`, `limit: int=50` | mpv 播第一首 + 其余入队 |
| `pause` | 无 | mpv 暂停(保留进度 · 可 resume) |
| `resume` | 无 | mpv 恢复暂停的播放 |
| `stop` | 无 | mpv 停 + 清队列(不可 resume) |
| `next_in_queue` | 无 | 切 mpv 入队的下一首 |
| `now_playing` | 无 | **(Patch D 2026-05-30)** mpv 自维护当前 state(title/artist/url/queue_len)· MediaRemote 看不见 mpv 的 fallback |

### `media` dispatcher · 5 actions(MediaRemote · 跨 source 系统级 · 看不见内嵌 mpv)

| action | 入参 | 行为 |
|---|---|---|
| `next_track` | 无 | 系统级下一首(NCM 客户端 / Apple Music / Spotify / 浏览器视频) |
| `previous_track` | 无 | 系统级上一首 |
| `play_pause` | 无 | 系统级 toggle |
| `now_playing` | 无 | nowplaying-cli get title/artist/album · **看不见内嵌 mpv** · null 是常态 |
| `set_volume` | `level: int 0-100` | osascript 调系统音量 |

**audio source 优先级**(2026-05-31 INV-18 tool_addendum 重写):
1. 本会话用过 mpv-first 路径(netease_web / netease_local)→ 后续控制首选 `netease_local.*`(同 source 闭环)
2. `not_running` / 从未走过 mpv → fallback `media.*`
3. 用户明确说"系统级 / NCM 客户端那个" → 直接 `media.*`

## 七、设计取舍

**为什么用 weapi 而不是 linuxapi / eapi？**
weapi 覆盖最完整，所有目标 capability 一条路径解决。代价：多一个 RSA 公钥模数 + AES 预设值，公开常量，与 jixunmoe / Binaryify 主流实现一致。

**为什么不用 pyncm SDK?**(2026-05-30 audit 结论 · **永久判死**)
pyncm 在 PyPI 下架 + GitHub repo 404 · 维护方撤回 · 不能在生产用。我们自己实现 weapi sign(`/v6/playlist/detail` + `/song/enhance/player/url/v1` 等)· 维护成本低于追上游 fork。

**为什么 `play_playlist` 是两步而不是一步？**
歌单名常带 emoji / 别名 / 多语言（如 "🏃 跑步专用" / "🌃 night drive" / "学习 mix"），写代码做模糊匹配又脆又有偏见。让 LLM 看完整列表后用语义匹配是更好的分工。

**为什么 `play_song(keyword)` 是一步而不是两步?**(2026-05-31 tool_addendum 统一)
旧版 tool_addendum 在【网易云本地 mpv】section 写两步(`netease_web.search` → `netease_local.play_song`)· 跟【音乐类】section 一步矛盾。实际 `netease_web(play_song, keyword)` 内部已走 mpv-first 闭环(search → 第一结果 → mpv 真播)· 一步即可。LLM 拿 song_id 自己决定时才用 `netease_local.play_song(song_id=N)`(直接 mpv 不经 search)。

## 八、mpv 后台播 vs NCM 客户端 trade-off(Mode A vs Mode B)

2026-05-31 PM 凌晨真机过 Mode A 后发现 **expectation gap**:Mode A mpv 后台播没 UI · PM 习惯 NCM 客户端的歌词 / 动画 / 完整 UI。4 个选项推 PM(未拍):

| 选项 | 路径 | 优势 | 劣势 |
|---|---|---|---|
| **A** · 保持现状(mpv 后台) | 默认 mpv-first · NCM 客户端只在 mpv 缺时 fallback | 开发体验最干净 · 真闭环 · 跨平台 | 无 UI · 操作只能通过 LLM tool call |
| **B** · 切回 NCM 客户端 | 强制走 URL Scheme + nowplaying-cli play 兜底 | 完整 UI · 歌词动画 | URL Scheme 自动播放不稳定 · 2026-05-30 audit 实证 |
| **C** · 双开(mpv + NCM mirror) | mpv 后台真播 + NCM 客户端 mirror UI(不出声) | 用户能看 UI · mpv 出声 | 复杂 · 难保 sync · NCM 客户端能否纯 UI 模式待 verify |
| **D** · 自建 minimal UI | 立绘馆嵌当前曲信息(title/artist/album cover/进度条) | UI 受控 · 真闭环 | 工程量大 · 跟立绘馆功能耦合 |

**状态:** Mode A 是当前 default(2026-05-31 Patch ABCD + mpv 三 fix 后真打通)· PM 未拍 Mode B/C/D · 等 PM 决策后落地。

## 九、相关 latent bugs 已修(2026-05-29~31)

| Patch | 范围 | bug |
|---|---|---|
| A | `integrations/netease_music.py:337-356` | weapi `get_song_url` `br=320000` 在 NCM 2024 API rotation 后全 400 · 改 `level=exhigh`/`encodeType=flac` 真通 |
| B | 同文件 client error path | 非 JSON / BOM / raw bytes 响应 detail 留 200 char · audit 友好 |
| 回归 | 5 endpoints(daily_recommend / personal_fm / playlist_detail / search × N) | NCM 风控返 `{"code":200, "result": "frequent_visit"}` · `data["result"]` 是 **str** 不是 dict · `data.get("result") or {}` 短路保留 str · 下游 `result.get(...)` AttributeError;修法 = 5 端点加 isinstance dict check |
| C | `capabilities/netease_playback.py:87-93/141-148` | error 归类 3 档(`mpv_error` / `netease_api_error` / `mpv_play_failed`)· 旧统一 `mpv_play_failed` 误导 LLM 推 "装 mpv" |
| D | 同 cap +`now_playing` action | netease_local 自维护 `_current` state · 给 LLM 独立查询路径 · 不依赖 MediaRemote(后者长期看不见 mpv 进程 · null 是常态非错误) |
| mpv 三 fix | `integrations/mpv_player.py` | `--media-keys=yes` mpv 0.41 rename fatal · stderr DEVNULL → PIPE · sticky pause 跨 loadfile |

详见 `docs/INVESTIGATION-INDEX.md` INV-16/17/18 + commit `06436d8`/`0a23866`/`d712768`。
