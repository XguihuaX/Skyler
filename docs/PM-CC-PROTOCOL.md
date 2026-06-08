# PM ↔ CC 工作协议

> 沉淀自反复迭代中观察到的有效模式 · 不是教条,是默认值。任一条 PM 当场覆盖优先。
> 硬律子集(named add / config.yaml 永不 stage / push 显式 / tsc 基线)同时锁进 `CLAUDE.md` 作为强制项。

---

## A · 任务范畴

1. **PM 拍方向 / 锁参数 / 给 spec 引用** —— 比如 "照 spec §3" / "mockup 参数 ±55° / 1.7s / 55% / cubic-bezier(.42,.04,.2,1) 锁死"。CC 不偏移参数。
2. **CC 报实现 diff 在 commit 之前** —— 默认 "别 commit · 我真机看",PM 拍 ship 才 commit。报告含:文件 净改 / 锚点 grep / 真机验收要点 / 已知 trade-off。
3. **PM 给"窄"任务 = "只做 X · 别动 Y"**(明确边界)· CC 不越界 · 越界前先提示 trade-off。

## B · 数据 vs 视觉(铁律)

4. **换皮不换数据** —— engine / 真实 boot marks / 闸 / appReady 四路 / 真模型名 / 真角色名 / splash · 视觉迭代时全保留。CC 不动这层。
5. **不假数据** —— 「绝不假 100%」「不假完成」「没就绪停在真实 warming 态」「没回落 — 或 warming 不造假」。gate 接真 source(engine done / appReady)· 不用 progressPct 假完成。
6. **静态校验是底线** —— `tsc --noEmit` 0 错 · `npx tsc -b` 0 错 · 大改 commit 前必跑(本场撞过一次跳过 `tsc -b` → JSX 注释截断 bug 漏到真机)。

## C · 调试协议(bisect 文化)

7. **PM 怀疑 → CC 先 grep 验** —— 读 X 行真实代码 · 不只回"在"。不让 PM 靠"记得是这样"决策。
8. **bisect 阶段挂临时埋点 · 真凶定后撤干净** —— 本场 dismiss 埋点 = console + backend beacon 双通道 + endpoint 临时 · 抓完 Meta 键 → 整段撤 + 撤后端 endpoint。
9. **不靠真机自证视觉** —— CC tsc 0 错只是底线 · "暖不暖 / 加厚密不密 / 锚压不压得住 / 交接顺不顺" PM 真机判 · CC 只交付代码 + 锚点 table。

## D · Commit / Push 纪律

10. **named `git add`** —— 不 `-A`。`config.yaml` 永远不入 stage(workaround 见 Tech Debt TD-G)。
11. **commit message 中文短描 + bullet 列改动 + Co-Authored-By Claude** —— 风格 ref 历史 commit。
12. **不 force push 主线 · 不 amend** —— 沿用 git 安全协议默认。
13. **commit ≠ push**(硬律 · 本场 `3068849` 漏踩) —— `push` 只在 PM/用户**显式说"推"**时执行。CC commit 完默认停手等指令。

## E · 文档治理节奏

14. **doc commit 周期性 + 批次同步** —— 本场实证 anchor `dcd3327` 之后 90+ code commit 才一次 docs sweep(滞后 ~20 天)。建议改:每 ship 段闭环就同步 `ROADMAP.md` 状态行 + Tech Debt 表 + `DESIGN_LITE.md` 接管必读 red flag · `README.md` features 段可月度 sweep。
15. **lesson 文件单独沉淀** —— `docs/LESSONS.md` 累计 #1-#37 已 ship · 新 cut 学到的 React/Tauri/设计坑都进 · #38+ 编号顺接。
16. **INV(investigation)文件 = 调查 · ROADMAP = 实施**(纪律 ref commit `de3db31`)· 不在 ROADMAP 写 audit 过程 · 不在 INV 写 backlog。

## F · CLAUDE.md / AGENTS.md 关系

17. `CLAUDE.md` 是 CC 启动时的 hard rules(本协议 D 区子集 + tsc 基线)· 本文件是 PM↔CC 工作风格全集 · 后者沉淀到前者要 PM 拍。

---

## 附:本协议从哪些场次沉淀

- 进入动画 cut1-7(Beat 0 preamble / 加载完成 latch / Beat 2 dismiss / 立绘馆发牌)
- bisect 文化:dismiss Meta 键真凶定位 / completionLatched React 死锁 / Tauri 小窗→大窗闪
- 文档治理:`dcd3327..HEAD` 90 commit / 5 文件审计 / 两张真值表
- doc-only 决策:MCP marketplace / 窗口自动切换 / sigil / Hermes 缓存 / 事实有效期
