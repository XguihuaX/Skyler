<!-- 给用户审阅的新 EVOLUTION(建议落点 docs/EVOLUTION.md)。
     这是「版本 × 功能分类」演进矩阵,取代 ROADMAP 里原来的 dated 时间线。
     ★ 落库前 CC 必做:
       ① 仓库无 git tag → 版本列边界按 IMPLEMENTATION_LOG 章节标题切(PM 定 c 方案);
       ② 标「CC核」的格子回 git log + IMPLEMENTATION_LOG 填实 / 纠正;
       ③ 我没有精确的每版本映射,凡不确定的都标了「CC核」,请勿当真值,逐格核。 -->

# 🧬 Skyler · 能力演进矩阵

> 横轴 = 版本,纵轴 = 功能分类。看每块能力在哪个版本长出来、长成什么样。
> 当前能力到哪一步 → [ROADMAP《当前能力状态》](../ROADMAP.md)。每个 chunk 的细节 → [IMPLEMENTATION_LOG.md](../IMPLEMENTATION_LOG.md)。

**图例**:✅ 该版本落地并验 · 🔧 该版本改进 / 重做 · 🚧 该版本在做未完 · — 该版本无动作

> ⚠️ **草稿**:版本列边界按 IMPLEMENTATION_LOG 章节标题切,各格内容待 CC 回 git log + IMPLEMENTATION_LOG 核填。标「CC核」处尤其勿当真值。

---

| 功能分类 ＼ 版本 | v3 | v3.5 | v4-beta | v4.0 | Next(v4.1+) |
|---|---|---|---|---|---|
| **角色机制** | ✅ persona 基础〔CC核〕 | — | ✅ 五层框架 + 持久状态字段 + conversation 锚定 + 角色详情中心 | — | 🚧 状态读回 + DailyAgent + 上下文仲裁(Brick 1-4) |
| **记忆** | ✅ 基础短期〔CC核〕 | ✅ 三级隔离 + 遗忘曲线 + 墓碑 + 用户画像 + 活动时间线 | 🔧 滚动摘要沉淀 | 🔧 链路 audit + 修复链 | 🚧 RAG 第 4 层 + 架构 v2 |
| **对话** | ✅ 逐句流式〔CC核〕 | 🔧 tool 过渡话 + loading pill | — | ✅ 深度思考/联网双开关 + 聊天时间戳 | — |
| **多模态(语音/图片)** | 🔧 TTS / ASR 基础〔CC核〕 | — | ✅ GSV provider paradigm + 语言解耦 | 🔧 GSV 本地迁移(`mai_v4`,06-17) | 🚧 图片输入持久化 · Fish 挂新角色 · 图片输出 |
| **Live2D** | ✅ 基础 render〔CC核〕 | — | ✅ 表演层 + 模型管理 | 🔧 取景层 + 台词气泡(widget 已上 / panel 暂关) | 🚧 AI 导演 + 贴纸 + 公参表 · Cubism5 |
| **桌面感知 / 控制** | — | ✅ 文本级屏幕感知(8a)+ 活动时间线〔CC核版本〕 | — | ✅ 只读 AX 读屏(UIA,06-21)〔CC核〕 | 🚧 写控件确认门 · 屏幕视觉 VLM |
| **主动陪伴** | — | ✅ trigger pack + 快/慢双路径 judge + idle 闸〔CC核版本〕 | — | — | 🚧 据角色状态搭话 |
| **工具 / MCP** | ✅ 双向 MCP〔CC核〕 | ✅ per-tool 开关 + skill demo〔CC核〕 | — | ✅ 服务器搜索 + 别名 + dangerous_tools gating | 🚧 凭证进钥匙串 · 图片生成 |
| **UI / 界面** | — | — | ✅ 进入动画 + 立绘馆发牌 + 陪伴态 | ✅ 玻璃外观自定义 + 角色详情 + 系统状态浮层〔CC核〕 | 🔵 整体视觉升级 |
| **可观测 / 启动** | — | — | 🔧 用量/资源/启动监控〔CC核〕 | ✅ 启动健康四路 gate | 🚧 成本面板 + 缓存命中率 · dmg/CI |

---

## 备注

- **列边界**:仓库无 git tag,**按 IMPLEMENTATION_LOG 章节标题切版本列**(PM 定 c 方案);`v4-beta / v4.0 / v4.1` 沿用老 ROADMAP 命名。
- **「Next(v4.1+)」列**:计划态,不是已发;跟 ROADMAP《近期计划》同步。
- 本矩阵只给"长出来的脉络",不替代 ROADMAP 的当前状态、也不替代 IMPLEMENTATION_LOG 的 chunk 细节。
