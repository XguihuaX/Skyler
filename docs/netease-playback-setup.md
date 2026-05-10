# 网易云本地 mpv 自解码播放（v3.5 chunk 6b）

Skyler 自己拉 song/url → mpv 本地播放 → 注册 macOS NowPlaying。**自动播放
真闭环**，不依赖 NCM 客户端是否打开。

| 模式 | 自动播放 | 歌词 / 动画 | 控制 | 何时用 |
|---|---|---|---|---|
| **chunk 6b (本路径, local_*)** | ✅ 真闭环 | ❌ 无 | mpv 自身 + 系统媒体键 | 默认首选 |
| chunk 1 (URL Scheme, 已封存) | ⚠️ 不可靠 | ✅ NCM 客户端 | NCM 自身 | 仅当用户想要 NCM 歌词/动画 |

## 装 mpv

### macOS

```bash
brew install mpv
```

### Linux

```bash
# Debian/Ubuntu
sudo apt install mpv

# Fedora
sudo dnf install mpv

# Arch
sudo pacman -S mpv
```

### 验证

```bash
which mpv      # 应回 /opt/homebrew/bin/mpv (Apple Silicon) 或 /usr/local/bin/mpv (Intel)
mpv --version  # 0.34+
```

Skyler 启动后看 SettingsPanel → Capability Panel → ``netease.local_*`` 行
应显示 🟢 ``healthy``。若 🔴 ``mpv_not_installed`` 说明 PATH 找不到。

## macOS NowPlaying / 媒体键集成

**mpv 0.34+ 原生注册** macOS NowPlaying Center，**不需要 PyObjC 桥接**。
启动时加 ``--media-keys=yes``（Skyler 已默认开），下列功能自动可用：

* 通知中心「正在播放」widget
* MacBook Touch Bar 媒体控制
* 系统媒体键 F7（上一首）/ F8（播放/暂停）/ F9（下一首）
* nowplaying-cli 能读到 mpv 在播什么
* Apple Watch「正在播放」glance

**前提**：mpv 必须**在前台进程**列表里有 audio output 活动。Skyler
后端启动 mpv 时走 ``--idle`` keep-alive，第一次 play_song 后开始播音
频，系统识别为「正在播放的应用」。

## 6 个 capability

| Capability | 描述 |
|---|---|
| ``netease.local_play_song(song_id)`` | 立即播放单曲，URL 失效返 ``url_unavailable`` |
| ``netease.local_play_playlist(playlist_id)`` | 拉歌单全曲：第一首立即 play + 其余入 mpv 队列 |
| ``netease.local_pause`` | 暂停（保留进度） |
| ``netease.local_resume`` | 恢复 |
| ``netease.local_stop`` | 停 + 清队列 |
| ``netease.local_next_in_queue`` | 切下一首；空队列返 ``queue_empty`` |

## 试听片段 (VIP) 处理

VIP 付费下架歌曲 NCM API 返试听 URL（~30s 片段）。本 capability:

* 正常 play 这段试听
* 返回字段 ``is_trial: True`` + ``note: "试听片段（~30s）"``
* LLM **如实告诉用户**「这是试听片段」，不假装是完整版

## 排错

| 现象 | 可能原因 | 修法 |
|---|---|---|
| ``mpv_not_installed`` | mpv 没装或不在 PATH | ``brew install mpv`` |
| ``mpv_exec_failed`` | binary 在但跑不起来 | ``mpv --version`` 看错误；首次启动 macOS Gatekeeper 弹「无法验证开发者」 → 系统设置 → 隐私与安全 → 允许 |
| ``cookie_required`` | NETEASE_MUSIC_U 没配 | 参 ``docs/netease-music-setup.md`` |
| ``url_unavailable`` | VIP 下架 / 地区限制 / 已下线 | 让用户换首歌 |
| ``netease_api_error`` | NCM cookie 失效 / 限流 / 网络断 | 重抓 MUSIC_U |
| ``mpv_play_failed`` | 解码错误（罕见） / mpv 子进程崩 | 重启 Skyler 后端 |

## 与 chunk 1 ``netease.play_song`` 并存

* chunk 1 ``netease.play_song(keyword)`` 仍 work，触发 NCM 客户端 URL
  Scheme 启动播放。自动播放不可靠（chunk 1 partial 封存）但**有歌词**
* chunk 6b ``netease.local_play_song(song_id)`` 走 mpv 自解码。自动播放
  可靠但**无歌词**
* LLM 默认走 ``local_*``（system prompt 强引导）；用户明确说「在 NCM 客
  户端打开 / 想要歌词」时回 chunk 1 路径

## 不实现

* 歌词同步显示（mpv 无 NCM 歌词源）
* 桌面 lrc 浮窗
* 音质切换 UI（默认 br=320000，VIP 限制时自动 clamp）
* 上一首跳回（mpv 队列单向；用户要循环 → stop + replay_playlist）
