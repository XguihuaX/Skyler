# Live2D 资产目录

Skyler 所有 Live2D 角色模型资产的标准位置。每个角色一个子目录，CharacterPanel
里 `live2d_model` 字段填子目录名（slug）即可绑定。

## 目录约定

```
frontend/public/live2d/
├── README.md          ← 本文档
├── core/              ← Cubism Core JS SDK runtime（不是角色资产，白名单进 git）
│   └── live2dcubismcore.min.js
├── hiyori/            ← Live2D 官方免费样品，白名单进 git
│   ├── hiyori_pro_t11.model3.json   ← 入口文件
│   ├── hiyori_pro_t11.moc3
│   ├── motion/
│   ├── textures/
│   └── ...
└── <slug>/            ← 第三方 / 同人 / 委托资产，默认 .gitignore
    └── ...
```

**slug 命名规则**：

- 小写英文 + 数字 + 短横，例如 `hiyori`、`yae-miko`、`momo-v2`
- 与 DB `characters.live2d_model` 字段值严格一致（CharacterPanel 写啥这里就叫啥）
- 不允许中文 / 空格 / 大写：URL 直拼路径，避免百分号编码出 bug

**入口文件**：

- 每个角色目录恰好一个 `*.model3.json`
- `frontend/src/config/live2d.ts` 的 `live2dModelEntry` 把 slug 映射到具体文件名
  （Live2D Editor 导出的 model3.json 文件名风格各异，无法靠目录名推断）
- 加新角色时同步在 `live2dModelEntry` 里登记一行

## moc3 版本要求

pixi-live2d-display 及其所有 fork 只支持 Cubism 4 Core，**不支持 Cubism 5**
（GitHub issue #118 自 2023-10 至今未修复）。所以接收 / 购入的资产 .moc3
文件 version 必须 ≤ 4。

资产放进目录后立刻验证：

```bash
python -m tools.check_moc3_version frontend/public/live2d/<slug>/
```

输出三种结果：

| 退出码 | 含义 | 处理 |
|---|---|---|
| `0` | 全部 OK，version ≤ 4 | 可以接通 |
| `1` | 有 version ≥ 5（Cubism 5）/ magic 不匹配（Cubism 2 .moc）| 不可用，要么换资产，要么从 Cubism Editor 用 4.x 兼容选项重导出 |
| `2` | 路径不存在 / 没找到 .moc3 / .moc | 检查路径或资产是否解压 |

## 资产完整性 checklist

放进目录后应包含：

- ✅ `*.moc3`（必须，pixi-live2d-display 加载入口）
- ✅ `*.model3.json`（必须，引用其他所有资源）
- ✅ `textures/`（必须，至少一张贴图）
- ✅ `*.motion3.json`（强烈建议，至少一个 idle motion，否则 Hiyori 那种自动呼吸 / idle 循环跑不起来）
- ⚪ `*.exp3.json`（可选，emotion 视觉绑定走 v3-E3 选项 a；缺失则走选项 b 用 setParameterValueById 自制偏移，详见 `frontend/src/config/live2d.ts` `emotionMap` 注释）
- ⚪ `*.physics3.json`（可选，缺失则物理摆动失效，但 idle / 表情正常）
- ⚪ `*.cdi3.json`（可选，参数显示名 metadata，仅 Editor 调试用，运行时不需要）

## IP / license 风险隔离

`.gitignore` 默认 ignore `frontend/public/live2d/*/`，只白名单
`frontend/public/live2d/hiyori/`。这不是冗余防御 —— 它是**主要 IP 防线**：

- 第三方模型（八重神子 / 加藤惠 / VTuber 同人 / 角色商品付费版）放进各自 slug
  目录后 git 看不到，**不会被 push 进公开仓库**
- 自制模型 / 已清理 license 的资产想入库时，在 `.gitignore` 末尾追加
  `!frontend/public/live2d/<slug>/`
- ⚠️ 即使你 `git add -f` 强制加进去，commit 之前再 review 一次

详细 license 信条见仓库根 `README.md` 的 License 章节 + Skyler 项目本身的
MIT 不覆盖捆绑模型这一点。
