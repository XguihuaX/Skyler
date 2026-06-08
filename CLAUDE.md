# CLAUDE.md · Skyler / MomoOS-v2 强制项

> 启动时硬律。完整工作协议(任务/调试/文档节奏)在 `docs/PM-CC-PROTOCOL.md`。

## 不可越界

1. **commit ≠ push** —— `git push` 只在 PM/用户**显式说"推 / push"**时执行。`git commit` 完默认停手等指令。
2. **named `git add` only · 不 `-A`** —— 永远列具体文件。`-A` / `git add .` / `git commit -a` 禁用。
3. **`config.yaml` 永远不入 stage** —— 它长期 modified 不入 commit(workaround 见 ROADMAP Tech Debt TD-G)。需要 stage 前端/后端代码时挨个 add,不带 config.yaml。
4. **静态校验底线** —— frontend 大改 commit 前必跑 `npx tsc --noEmit`(默认 tsconfig)+ 必要时 `npx tsc -b`(build 模式 · 更严)。0 错才能交。
5. **不 force push 主线 · 不 amend · 不 skip hooks**(`--no-verify`)。

## 数据真源不动

6. **换皮不换数据** —— engine / 真实 boot marks / appReady 4 路 gate / 真模型名 / 真角色名 / splash。视觉迭代时这一层一字不动。
7. **不假完成** —— gate 接真 source(engine done / appReady),不用 progressPct 假完成。「绝不假 100%」「没就绪停在真实 warming 态」是 Loading/动画类铁律。

## 默认行为

8. **默认不 commit** —— PM 没说"commit / 提交"就只交 diff。
9. **报告含锚点** —— 改动报告附 `file:line` + `grep` 验证 + 真机验收要点 · 让 PM 一眼能 cross-ref。
10. **不自证视觉** —— "暖不暖 / 顺不顺 / 晃不晃眼" 让 PM 真机判。CC 只交付代码 + tsc 0 + 锚点。

## 项目特定路径锚

- 设计真源:`DESIGN_LITE.md`(归档版 `docs/archive/DESIGN.md` 不再维护)
- 路线图 / Tech Debt:`ROADMAP.md`
- 经验沉淀:`docs/LESSONS.md`(顺序加 #N)
- 调查文档:`docs/INV-*.md`(调查走 INV / 实施走 ROADMAP · 不混)
- 工作协议:`docs/PM-CC-PROTOCOL.md`
