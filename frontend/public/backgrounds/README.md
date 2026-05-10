# Per-character backgrounds (v3.5 chunk 5a)

把图 / 视频文件直接丢进本目录，启动后端后 CharacterPanel 的"背景"下拉会
自动扫到。可以平铺：

```
frontend/public/backgrounds/
├── tokyo_rain.mp4
├── shrine_night.jpg
└── desk_morning.webp
```

也支持一层分组：

```
frontend/public/backgrounds/
├── tokyo/
│   ├── rain.mp4
│   └── neon.jpg
└── shrine/
    ├── day.jpg
    └── night.jpg
```

## 后缀白名单

| 后缀 | 类型 | 前端渲染 |
|---|---|---|
| `.jpg` / `.jpeg` | image | `<img>` |
| `.png` | image | `<img>` |
| `.webp` | image | `<img>` |
| `.mp4` | video | `<video autoplay loop muted playsinline>` |
| `.webm` | video | 同上 |

其他后缀（含本 README）一律忽略，不进列表。

## 推荐编码

* mp4：H.264 + AAC，CRF ≤ 23，分辨率 ≥ 1280×720
* webm：VP9
* 时长 5–20 秒循环最佳（视频是无声后台元素，太长占内存）

## IP 风险隔离

本目录走 ``.gitignore`` 全屏蔽（同 ``frontend/public/live2d/``）—— 仅 README
和 ``.gitkeep`` 占位入库。第三方 / 委托作品丢进来不会进 git 历史。
