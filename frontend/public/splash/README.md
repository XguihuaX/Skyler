# Launch splash video (v3.5 chunk 5b)

把 `intro.mp4` 丢进本目录。Skyler 启动时全屏播放，结束 / 任意点击 / 任意
按键跳过，fade 300ms 进主视图。

文件不存在时 silent skip —— 不会有任何 error，主视图直接出来。

## 推荐参数

* 文件名固定 `intro.mp4`（不扫描，硬编码）
* 时长 3–8 秒
* 分辨率 1920×1080
* 编码 H.264 + AAC，CRF ≤ 23
* 无声 / 静音版本最佳——浏览器会 autoplay-allow 静音视频，否则 Tauri webview 会拒绝播放

## webm 不支持

只走 mp4 一条路。Tauri webview 在 macOS 上对 webm 的 codec 支持不齐
（VP8 OK / VP9 / AV1 视系统而定），保持简单。

## 关闭播放

SettingsPanel → 顶部 [启动入场视频] toggle 关掉，localStorage key
``momoos.splashEnabled``。
