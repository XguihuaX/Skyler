# 媒体控制（v3-H chunk 1）

Skyler 通过 `nowplaying-cli` 给 ChatAgent 5 个 macOS 系统级媒体控制能力：
**跨来源**——网易云 / Apple Music / Spotify / YouTube / Bilibili 网页 / 任何
能在 macOS 媒体控制中心露面的播放器都能控。

## 装机

```bash
brew install nowplaying-cli
nowplaying-cli --version
```

> 仅 macOS。其他平台 capability 仍注册（前端能力面板看得见），调用时返"仅 macOS 可用"。

## 能力清单（5 个）

| capability | 入参 | 行为 |
|---|---|---|
| `media.next_track` | 无 | 下一首（系统级） |
| `media.previous_track` | 无 | 上一首 |
| `media.play_pause` | 无 | toggle 播放/暂停 |
| `media.now_playing` | 无 | 返 `{title, artist, album, playing}` |
| `media.set_volume` | `level: 0-100` | osascript 设系统音量 |

## 聊天示例

| 你说 | 工具调用 | 效果 |
|---|---|---|
| 下一首 / 切歌 | `media.next_track` | 切下一首（不限来源） |
| 暂停 / 继续 | `media.play_pause` | toggle |
| 现在在放什么？ | `media.now_playing` | "夜空中最亮的星 — 逃跑计划" |
| 这首叫啥？谁唱的？ | `media.now_playing` | 同上 |
| 大声点 | `media.set_volume`（LLM 自定增量） | 系统音量上调 |
| 静音 | `media.set_volume(level=0)` | 0 |

## 与网易云的配合

`netease.like_current` 不直接知道当前在放什么——它依赖 `media.now_playing` 拿
title + artist 后再 search → like。这是设计取舍：netease.like 只关心网易云
song id，跨来源识别交给系统层。

如果当前播的是 Apple Music / Spotify 歌曲（不是网易云的），`netease.like_current`
搜不到对应 song id，会返 ``liked: false`` + error，LLM 应礼貌告知用户"这首不是网易云的资源"。

## 故障

| 现象 | 修法 |
|---|---|
| health_check warn `nowplaying-cli 未安装` | `brew install nowplaying-cli` |
| `now_playing` 返全 null | 当前没有任何 app 在播；macOS 媒体控制中心也是空的 |
| `next_track` 返 ok=false | 当前应用不支持媒体键（少数网页播放器）；切到桌面 App 能控 |
| `set_volume` 没反应 | 检查系统输出是否被独占（部分会议软件 / 蓝牙耳机会接管）|

## 隐私

所有调用是**本机进程间通信**，不上云，不联网（`set_volume` 调 osascript，不出 localhost）。`now_playing` 拿到的元数据来自 macOS MediaRemote framework 的本地缓存。
