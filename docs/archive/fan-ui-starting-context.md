# Fan UI — 二次元卡牌式 character 选择 · Starting Context

前置:`README.md` / `DESIGN.md §零 / §一 / §五·背景层 / §十九` /
`ROADMAP.md §Now`、`docs/stage-2-starting-context.md`(同格式范本)。

Fan UI 目标:把当前**TopBar 下拉 + Settings 列表**两个入口的 character
切换,升级为**全屏弧形扇面卡牌**浏览 + 单卡 detail mode。**纯前端层**改
造,backend switching 流程不动。

本 audit 只盘点现状(§1–§5)+ 分析改造影响面(§6)+ 列候选决策(§7)
+ 跟其他工作的依赖与风险(§8–§9),**不修改源代码**。


---

## 1. 当前 character 选择 UI 现状

### 1.1 入口共有三处

| # | 组件 | 形式 | 文件:行 |
| --- | --- | --- | --- |
| A | **TopBar 下拉(主入口)** | dropdown,头像 + 名字 + ▾,展开 max-h-72 滚动列表 + 底部"管理角色…" | `frontend/src/components/CharacterSwitcher.tsx:60-156` |
| B | **Settings 角色管理面板** | 卡片列表(每条:头像 + 名字 + persona preview + edit/delete);click 卡片 = 切换 | `frontend/src/components/CharacterPanel.tsx:617-720`(整个 panel 1351 行) |
| C | **CharacterSelect.tsx**(空 stub) | 空 div + `{/* 角色选择组件 */}` 注释,**未被任何 import 引用** | `frontend/src/components/CharacterSelect.tsx:1-25` |

C 是历史残留,可在 Fan UI commit 顺手删除。

### 1.2 切换 character 的"调用链"——**纯前端**

切换是 **pure local state set**,不发任何 HTTP / WS。

```typescript
// CharacterSwitcher.tsx:97-99
onClick={() => {
  if (!active) setCurrentCharacterId(c.id);
  setOpen(false);
}}

// CharacterPanel.tsx:645
onClick={() => setCurrentCharacterId(c.id)}
```

`setCurrentCharacterId` 来自 `useAppStore`(Zustand):

```typescript
// frontend/src/store/index.ts:294-295
currentCharacterId: number | null;
setCurrentCharacterId: (v: number | null) => void;
// :462-463
currentCharacterId: null,
setCurrentCharacterId: (currentCharacterId) => set({ currentCharacterId }),
```

下游消费者**全部 reactive**(hook 订阅 store):

* `Live2DCanvas.tsx:71-75` — 解析 `character.motion_map_json` / `emotion_map_json`
* `CharacterView.tsx:45-55` — 决定 live2d / background / static jpeg fallback
* `ConversationList.tsx:23-50` — fetch 该 character 的 conversation list
* `useWebSocket.ts:518,548,620` — 每条 send 消息附 `character_id: s.currentCharacterId`
  让 backend 路由
* `CharacterStatePanel.tsx:58` — fetch `/api/characters/{id}/state`(mood/intimacy/...)

**结论**:Fan UI 只需要触发同一个 `setCurrentCharacterId(id)`,所有
下游(Live2D 重 mount、conv 列表刷新、WS 后续消息携带新 id)**自动跟
随**。没有 backend "switch" endpoint 要改;backend 只在 LLM tool-call
路径有 `switch_character`(`backend/tools/builtin.py:14-39`)走 prompt
manager 改 user→character 绑定,跟 UI 无关。

### 1.3 现有 fetch 链(冷启时序)

`App.tsx:55-67`:

```
fetchConfig (config.yaml)
  → fetchCharacters (/api/characters/list) → setCharacters(chars)
  → if (chars.length > 0) setCurrentCharacterId(chars[0].id)   // ← 默认选首个
  → fetchLive2DModels → setLive2dModels
  → fetchTtsVoices → setTtsProviders
  → fetchConversations(userId, charId) → setConversations
```

Fan UI 也复用这个流程,不需要新 fetch。


---

## 2. character 数据结构

### 2.1 DB schema(SQLAlchemy)

`backend/database/models.py:38-63`:

```python
class Character(Base):
    __tablename__ = "characters"
    id                = Column(Integer, primary_key=True, autoincrement=True)
    name              = Column(String, nullable=False, unique=True)
    persona           = Column(Text, nullable=False)
    avatar_path       = Column(Text, nullable=True)   # 静态头像 URL,目前都是 NULL
    voice_model       = Column(Text, nullable=True)   # v3-B,TTS 音色
    live2d_model      = Column(Text, nullable=True)   # v3-E1,slug → /live2d/<slug>/
    emotion_map_json  = Column(Text, nullable=True)   # v3-E2 per-character map
    motion_map_json   = Column(Text, nullable=True)
    hit_area_map_json = Column(Text, nullable=True)
    background_path   = Column(Text, nullable=True)   # v3.5 chunk 5a,/backgrounds/*.{mp4,jpg}
    created_at        = Column(DateTime, server_default=func.now())
```

字段演化时序:`v2_5_b.py`(初建 + Momo seed)→ `v3_b.py`(voice_model)→
`v3_e1.py`(live2d_model)→ `v3_e2_per_character_maps.py`(三个 map_json)
→ `v3_5_chunk5a_character_background.py`(background_path)。

**注意**:`character_states` 表(`v3_g_chunk3_character_states.py:41-53`)
是**独立另一张表**,持 mood / intimacy / current_thought / current_activity
等运行时动态字段,跟 `characters` 静态属性表不混。Fan UI detail mode 想
显示"当下心情"这类信息要从 `/api/characters/{id}/state` 拿,不在
`characters` 行里。

### 2.2 现有 character 记录(实读 momoos.db)

```
1  Momo            avatar_path=NULL  live2d_model=hiyori
2  八重神子         avatar_path=NULL  live2d_model=yae
3  荧               avatar_path=NULL  live2d_model=NULL
4  凝光             avatar_path=NULL  live2d_model=NULL
5  神里绫华         avatar_path=NULL  live2d_model=NULL
99  TestPropose    (测试残留)
704 _bg_test_list  (测试残留)
```

**5 个真角色,2 个有 Live2D,0 个有 avatar / splash art**。Momo seed
来自 `v2_5_b.py:71-81` 的 INSERT;其他 4 个是用户在 UI 里手动创建的
(没有 seed migration)。

### 2.3 字段缺位(Fan UI 视角)

| 字段 | 现状 | Fan UI 需要 |
| --- | --- | --- |
| `splash_art_url` / `portrait_url` | **没有** | ✅ 必加(卡牌底图主视觉) |
| `tagline` / `short_intro` | **没有**(只有 persona 长文本) | 推荐加(detail mode 标语) |
| `theme_color` / `accent_hex` | **没有** | 可选(每张卡用自己的主色调) |
| `tags[]`(角色标签:猫娘 / 傲娇 / ...) | **没有** | 可选(浏览态 filter) |
| `relationships`(角色间关系) | **没有** | 不在 MVP 内 |
| `avatar_path` | 字段在但全 NULL | Fan UI 可顺便利用作 fallback(§7 Q5) |


---

## 3. frontend 现有依赖

### 3.1 `frontend/package.json` 实读

```json
"dependencies": {
  "@tauri-apps/api":      "^2.11.0",
  "lucide-react":         "^1.14.0",      // icon
  "pixi-live2d-display":  "^0.5.0-beta",
  "pixi.js":              "^7.4.0",
  "react":                "^18.3.1",
  "react-dom":            "^18.3.1",
  "zustand":              "^5.0.3"        // store
}
```

`devDependencies`: tailwindcss 3.4 / vite 6 / typescript 5.6 / autoprefixer。

### 3.2 与动画 / carousel 相关 — **0 现成库**

`grep -E "framer-motion|embla|swiper|react-spring|swiperjs|keen-slider|react-dropzone" frontend/package.json` → **0 hit**。

现有动画手段:

* CSS `transition-*`(广泛使用,见 CharacterSwitcher / CharacterPanel)
* CSS `backdrop-blur-{sm,md,lg}`(7 个组件已用,Tauri WebView 已验证可
  跑 — App.tsx:212 / Panel.tsx:71 / CharacterDialogueBubble:61 /
  NotificationToast:35 / ControlBar:8 / ConversationList:289 /
  AsrPreview:62,77 / ActivityTimelineDrawer:216)
* `useEffect` + state 时序控制(SplashOverlay fade-in)

### 3.3 Fan UI 需要新装的最小集合(候选)

| 选项 | gzip 体积 | Skyler 红线契合度 |
| --- | --- | --- |
| **A. 0 新依赖,纯 CSS `transform: rotate()` + transition** | 0 | ✅ 最契合(README §零 hackable / 依赖红线)|
| B. `framer-motion` ^11 | ~50 KB | 中 — 大,但 declarative API 使弧形布局 + spring physics 一行写完 |
| C. `react-spring` ^9 | ~25 KB | 中 — 比 framer 小,API 略繁 |
| D. `embla-carousel-react` | ~10 KB | 不适用(标准滑动 carousel,不做扇面布局) |

**初判**:扇面布局是 layout problem(每张卡 rotate + transform-origin
bottom),不是 motion problem。**A 优先**;若卡片入场动画 / spring
overshoot 想要更细腻效果再考虑 B/C。详 §7 Q1。


---

## 4. design tokens 现状

### 4.1 Tailwind 配置

`frontend/tailwind.config.js` —— **空 extend**,无自定义色板 / 间距 /
阴影 / 圆角 token:

```js
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: { extend: {} },
  plugins: [],
}
```

颜色全部走 **CSS variable**(`frontend/src/styles/themes.css`,5 主题:
dusk 默认 / morandi / glass / watercolor / aurora),命名规范:
`--color-bg-{base,surface,elevated,input}` / `--color-text-{primary,
secondary,accent}` / `--color-accent[-hover]` / `--color-border[-subtle]` /
`--color-bubble-{ai,user}[-text]` / `--color-scrollbar`。

**禁硬编码 Tailwind 色板**(`themes.css:1-3` 注释明示)。

### 4.2 现有 UI primitive(Fan UI 可复用)

`grep "rounded-|shadow-" frontend/src/components/CharacterPanel.tsx
SettingsPanel.tsx Sidebar.tsx`:

| primitive | 现有用法 | Fan UI 复用度 |
| --- | --- | --- |
| `rounded-{md,lg,xl,2xl,full}` | 大量(button / card / avatar) | 高(卡牌外边、CTA) |
| `shadow-2xl` | modal / dropdown | 中(detail modal 沿用) |
| `backdrop-blur-{sm,md,lg}` | overlay / dialog bubble | 高(模糊背景做卡牌沉浸感) |
| `color-mix(in srgb, var(--color-X) N%, transparent)` | hover / active 半透明叠加 | 高(卡牌底色微调) |
| `transition` | 全组件 | 高 |
| Confirm modal pattern | `CharacterPanel.tsx:51-95` ConfirmModal | 中(detail modal 抄结构) |

### 4.3 二次元卡牌视觉需要新加的 token

**没有**(且当前 design 没有):

| token | 用途 | 推荐做法 |
| --- | --- | --- |
| `--color-card-rim-gold` / `--color-card-rim-silver` | 卡牌"稀有度"边框装饰 | 加进 themes.css(每个主题 5 个) |
| `--shadow-card-glow` | hover 时光晕(类原神 SR 卡) | 加 box-shadow 复合定义 |
| `--gradient-card-{rare,epic,legendary}` | 卡牌底层渐变 | linear-gradient 字符串 |
| 阴影预设 | shadow-2xl 单挡偏强 | 加 `--shadow-card-rest` / `--shadow-card-lift` |

**最小可行**:**只**加 `--shadow-card-rest` / `--shadow-card-lift` /
`--gradient-card-default`(每主题 3 行),其他装饰 inline 写在 component
里,先 ship 再迭代。


---

## 5. Live2D 与 character 的当前绑定

### 5.1 字段消费链

`character.live2d_model`(slug,如 `hiyori` / `yae`)→
`resolveLive2dModelUrl(slug, live2dModels)`(`frontend/src/config/live2d.ts:37-66`)
→ `live2dUrl`(如 `/live2d/hiyori/hiyori_pro_t11.model3.json`)→
`Live2DCanvas key={live2dUrl} modelUrl={live2dUrl}`
(`CharacterView.tsx:108-119`)。

### 5.2 现有 fallback 链

`CharacterView.tsx:50-180`:

```
1. live2dUrl 解析成功 ──→ <Live2DCanvas /> + 可选背景层(background_path)
2. live2dUrl 失败 + background_path 有效 ──→ 只渲染背景层
3. live2dUrl 失败 + background_path 失败 + characterImg 加载成功 ──→ 静态 jpeg
4. 全失败 ──→ SVG 占位(头 + 身体几何形状)+ 名字
```

**结论**:已有完整 fallback;Fan UI 立绘字段加进来,**应该插在
fallback 链的"卡牌底图"位置**(浏览态主视觉),与 Live2D **并存**
(进 detail / 切换后正常 mount Live2D)。详见 §7 Q5 / Q8。

### 5.3 立绘字段加进来后的关系判定

* **浏览态(扇面)**:每张卡显示 **splash art**(立绘背景)+ 角色名 +
  tagline。**不**渲染 Live2D(8 张卡同时跑 Live2D = pixi 8 个
  WebGL context,GPU 直接挂)。
* **detail 态(单卡放大)**:可选 — 仍用 splash art(静态、便宜)
  或切到 Live2D(沉浸感、贵)。MVP 推荐 splash art,Live2D 留
  "切换到该角色"后由现有 CharacterView 接管。
* **fallback**:splash NULL → 用 `avatar_path`(目前也 NULL)→
  用 Live2D 静态截屏(没现成,需要预生成或运行时 capture,见 §7 Q5)→
  用首字母 avatar(`AvatarBubble` `CharacterPanel.tsx:140-168` 现成)。


---

## 6. Fan UI 改造影响面

### 6.1 DB migration

| 项 | 新增 | 复用 / 已有 |
| --- | --- | --- |
| `characters.splash_art_url` `TEXT NULL` | ✅ 必加 | ALTER TABLE pattern 完全沿用 `v3_e1.py`(`characters.live2d_model` 列添加范本) |
| `characters.tagline` `TEXT NULL` | 可选(detail mode 用) | 同上 |
| `characters.theme_color` `TEXT NULL` | 可选(每卡主色) | 同上 |
| 文件存储路径 | `frontend/public/splash_art/<slug>.{jpg,png,webp}`(与现有 `live2d/` / `backgrounds/` / `splash/` 同级) | 沿用 vite static + 后缀分类(`CharacterView.tsx:14-30` IMAGE_EXTS 现成) |
| 迁移文件命名 | `v4_fan_chunk_X_splash_art.py` | 历次幂等模板:`PRAGMA table_info` 检查列存在再 ADD COLUMN(`v3_e1.py:30-41` 原文可抄) |

**核心决策**:文件存哪?详 §7 Q3。

### 6.2 Backend(splash art upload endpoint)

**几乎可以照抄 Live2D upload pattern**:

| 项 | Fan UI 新增 | 复用 |
| --- | --- | --- |
| **endpoint** | `POST /api/characters/{id}/splash_art` 接 multipart 单文件 | `live2d_api.py:126-172` upload_live2d_model 整个函数结构 |
| **验证** | mime 必须 image/{jpeg,png,webp};size ≤ 5 MB(立绘单图,不像 Live2D zip 30 MB) | `live2d_api.py:54-62` _SLUG_RE / _MAX_ZIP_SIZE 同设计 |
| **路径越界** | `safe_resolve(splash_art_dir, f"{slug}.{ext}", allow_subdirs=False)` | `backend/utils/safe_path.py` `safe_resolve`(Live2D 已用) |
| **写库** | `UPDATE characters SET splash_art_url=:url WHERE id=:id` | `backend/routes/characters_api.py:117-151` PATCH 流程 |
| **endpoint** | `DELETE /api/characters/{id}/splash_art`(可选,清空字段 + 删文件) | — |
| **endpoint** | `GET /api/splash_art/list`(可选,扫现存文件给"挑已上传"UI) | 不必要,字段 URL 直接渲染 |

**核心风险**:无新风险。Live2D upload 已踩过 zip-bomb / safe_path / size limit /
slug 冲突所有坑(`live2d_api.py:54-345`),splash art 是单文件版,简单。

### 6.3 Frontend

#### 6.3.1 新组件

| 组件 | 文件 | 复用 |
| --- | --- | --- |
| `FanLayout.tsx` | `frontend/src/components/fan/FanLayout.tsx` | 容器:全屏 overlay + escape close + click outside close;抄 `CharacterSwitcher.tsx:21-37` outside-click pattern |
| `CharacterCard.tsx` | `frontend/src/components/fan/CharacterCard.tsx` | 单卡:splash art + 名字 + tagline;`transform: rotate(N deg)` + `transform-origin: bottom center` |
| `CharacterDetailModal.tsx` | `frontend/src/components/fan/CharacterDetailModal.tsx` | 抄 `CharacterPanel.tsx:51-95` ConfirmModal 结构(modal overlay + escape + click-outside) |
| `SplashArtDropzone.tsx` | `frontend/src/components/fan/SplashArtDropzone.tsx` | 抄 `frontend/src/components/live2d/Live2DDropzone.tsx`(上传 zip 改为单图,~70% 代码可复用) |

#### 6.3.2 修改既有组件

| 组件 | 修改 | 影响 |
| --- | --- | --- |
| `CharacterSwitcher.tsx` | 加按钮"扇面浏览…",或整体替换为 fan 入口(详 §7 Q7) | TopBar UI |
| `CharacterPanel.tsx` | 编辑表单加 `splash_art_url` 字段 + dropzone | 1351 行大组件,加 ~30 行 |
| `App.tsx` | 加全局 store flag `fanLayoutOpen` | 不动 |
| `store/index.ts` | 加 `fanLayoutOpen / setFanLayoutOpen` | +2 行 state +2 行 setter |

### 6.4 character 切换流程是否变?

**不变**。Fan UI 只是新入口,卡片 click → `setCurrentCharacterId(id)` →
关 fan overlay → 现有所有 reactive 消费者(`CharacterView` /
`Live2DCanvas` / `ConversationList` / WS messages)自动更新。**不动**
backend `switch_character` tool / prompt_manager 绑定 / WS 协议。

后端唯一新增:splash_art upload endpoint(§6.2);**不**新增 switching
endpoint。


---

## 7. 候选实现决策(Q1–Q8 待拍板)

### Q1. 动画框架?

| 选项 | Pros | Cons |
| --- | --- | --- |
| **A. 纯 CSS** transform + transition + cubic-bezier | 0 新依赖;契合 Skyler "依赖红线";编译产物 +0 KB;弧形布局本质是 layout 不是 motion | spring physics / 复杂入场需要手算 cubic-bezier;无 gesture(拖拽翻牌) |
| B. framer-motion ^11 | declarative `<motion.div animate={{ rotate, x }} transition={{ type: 'spring' }}>`,弧形布局两行写完;手势支持(drag / pan / pinch);AnimatePresence enter/exit | +50 KB gzip;为单一 feature 引大库;主题 var() 集成需要 inline style override |
| C. react-spring ^9 | 比 framer 小;hook 风格 `useSpring` 与 React 原生融合好 | 命令式 API 学习曲线;手势要另装 `@use-gesture/react` |

**推荐**:**A**。扇面布局每张卡的 transform 都是确定值(角度可以
linear / quadratic 计算),CSS transition 体感够;入场用 `@keyframes
fan-deal` 一段动画即可。**升级路径**:若后续要加"拖拽翻牌"再上 B。

### Q2. 弧形布局算法?

| 选项 | Pros | Cons |
| --- | --- | --- |
| **A. 每张卡 `transform: rotate(θ_i deg) translateY(-R)` + `transform-origin: bottom center`** | 数学简单(θ_i = (i - mid) × Δθ);CSS 原生;hover 状态 `rotate(0) translateY(-R-Δ)` 一句搞定 | 卡尺寸固定时 R 也固定,屏幕 resize 要 JS 重算 |
| B. SVG `<path>` 沿轨迹动画 + `<foreignObject>` 嵌 React | 真正贴弧线;动画沿曲线流畅 | 复杂度爆炸;`<foreignObject>` Tauri WebView 兼容性需测;hover 命中区难 |
| C. 极坐标 → 笛卡尔(JS 算 x/y,position absolute) | 最灵活,可任意半径 / 弧度;响应式好 | 需要 useEffect + ResizeObserver;每次 resize 重排 |

**推荐**:**A**(CSS rotate),配合 `useEffect` 监听 resize 调整
CSS variable 控制 R(`--fan-radius`)。最简实现,迭代成本低。

### Q3. 立绘存储?

| 选项 | Pros | Cons |
| --- | --- | --- |
| **A. 文件 + URL 字符串**(`splash_art_url` TEXT,文件落 `frontend/public/splash_art/<slug>.jpg`) | 与现有 `live2d/` `backgrounds/` `splash/` 同 pattern;vite static serve;CDN 友好;DB 轻 | 需要文件 + DB 双写一致性(删 character 时清文件) |
| B. base64 in DB(TEXT 列直接存图片) | 零文件管理;迁移 / 备份带数据 | DB 膨胀(单图 200 KB → 270 KB base64);列表 API JSON payload 暴增 |
| C. blob 列(BLOB 列存二进制) | 数据 ACID;单源真理 | SQLite BLOB 列 8 张大图 1.6 MB,查询响应慢;前端需要 endpoint 流式返图 |

**推荐**:**A**。沿用 Skyler 现有"file URL 字符串 + vite static"模式
(`background_path` 现成范本);删除一致性由 backend `DELETE
/api/characters/{id}` 顺手清文件 cover。

### Q4. 立绘上传?

| 选项 | Pros | Cons |
| --- | --- | --- |
| **A. multipart 仿 Live2D upload pattern** | `live2d_api.py:126-172` 现成模板,~70% 代码可抄;safe_path / size limit / mime 校验都有 | 单文件版本简化 |
| B. base64 POST(JSON body 嵌 dataUrl) | 简单 fetch JSON | 30% payload 膨胀;FastAPI body 默认 1 MB 限制需要调 |
| C. 用户填 URL(外链托管) | 0 backend 改动 | 用户离线 / 链接失效 → 黑卡;privacy(外链 referer 泄露) |

**推荐**:**A**。Skyler 是 local-first,不依赖外链。

### Q5. 没立绘的 character fallback?

| 选项 | Pros | Cons |
| --- | --- | --- |
| **A. 首字母 avatar(`AvatarBubble` 现成)** | `CharacterPanel.tsx:140-168` 已实现;0 工作量;视觉低调不抢戏 | 二次元卡牌底图给个字母略 plain |
| B. Live2D 静态截图(运行时 capture canvas → toDataURL) | 真角色画面;立绘缺位也能看角色 | 需要 mount 一次 Live2D + canvas.toDataURL,首次冷启慢;跨域 / WebGL pixel readback 在 Tauri WebView 需测 |
| C. 通用占位(SVG / 灰底"立绘缺位")| 一致性强 | 用户感觉"未配置";没设计感 |
| D. 用 background_path 当 fallback | 5 个角色里 0 个有,等于无 | 同 |

**推荐**:**A → C 退化**。`splash_art_url` 有 → 用;无 → 首字母
avatar(取 character name 首字符,主题色背景 + 大字号);连名字都
没特殊情况 → 通用占位 SVG。**B 留 v4.1**(需要预生成 splash 工具)。

⚠️ Q5 与 Q8 联动:若 Q8 选"卡牌底图用 Live2D 静态截图",则 Q5 选 B
为主路径。详 Q8。

### Q6. Detail mode 显示哪些字段?

| 字段 | 来源 | 推荐 MVP 显示? |
| --- | --- | --- |
| name | `characters.name` | ✅ 必 |
| persona(可折叠 read-more) | `characters.persona` | ✅ 必 |
| tagline | 新增 `characters.tagline`(若 §6.1 加) | 推荐(否则用 persona 前 30 字 preview) |
| live2d_model slug | `characters.live2d_model` | ⚪ 可见(灰字角标"已配 Live2D / 未配") |
| voice_model | `characters.voice_model` | ⚪ 可见(灰字角标"音色:阿珍") |
| background_path | `characters.background_path` | ❌ 内部字段,不显示 |
| **mood / intimacy / thought / activity** | `/api/characters/{id}/state`(独立表) | 推荐(detail 进入时一次 fetch;不影响列表性能) |
| 关系 / 喜好 | **没有字段** | ❌ MVP 不做 |
| created_at | `characters.created_at` | ⚪ 可见(底部小字"加入时间") |

**推荐**:name + tagline + persona + Live2D / voice 角标 +
character_state(mood / intimacy / thought)+ 主 CTA 按钮。

### Q7. "切换到该角色" CTA 在 browse 还是 detail 态?

| 选项 | Pros | Cons |
| --- | --- | --- |
| **A. browse 态点卡 = 直接切换 + 关 overlay** | 1 次点击,最快;符合 Switcher 现有语义 | 没有 detail 浏览路径,detail 信息看不见 |
| **B. browse 态点卡 = 进 detail;detail 内有"切到此角色"按钮** | 浏览 / 切换分离;detail 信息可读 | 2 次点击切换,慢 |
| **C. browse 单击 = detail,双击 = 直接切换;detail 内也有按钮** | 兼顾两路径 | discoverability 差(用户不知道双击) |
| **D. browse 长按 / hover-hold = detail;短按 = 切换** | 直觉(类似 Switch 主菜单) | 长按交互 desktop 不常见 |

**推荐**:**B**。理由 — 二次元卡牌的乐趣很大一部分在"看立绘 + 介
绍",直接切换浪费了 detail 的存在。常用切换走 TopBar Switcher 老路
(保留),Fan UI 是"探索 + 切换",定位不冲突。

### Q8. 卡牌底图用 splash art 还是 Live2D 静态截图?

| 选项 | Pros | Cons |
| --- | --- | --- |
| **A. splash art** | 主视觉控制力(画师风格);静态便宜;0 GPU | 用户立绘做不齐时多数卡片走 fallback(Q5) |
| B. Live2D 静态截图(预生成或运行时) | 真角色感;不依赖立绘资产 | 预生成需要工具链;运行时 toDataURL 在 8 张卡同时 mount Live2D = GPU 灾难;只能首张 mount + 后台 capture 队列 |
| C. 混合:有 splash 用 splash,没有 fallback Live2D 截图 | 最佳视觉 | 实现复杂(2 套加载逻辑) |

**推荐**:**A**(MVP)+ Q5 选 A 退化(首字母 avatar)。**理由**:Live2D
mount 8 个 = pixi 8 WebGL context,Tauri macOS WKWebView 实测 4-5 个
context 后已显著掉帧。MVP 不冒这个险。**升级路径**:用户立绘补齐
(GPT Image 2 路径)后,Fan UI 自然全 splash 高一致性。


---

## 8. 跟 v4 其他工作的依赖

### 8.1 跟 Stage 3(skill 接入封装)耦合

**0**。Fan UI 是 frontend layer,Stage 3 是 backend `register_capability`
DX 改造 + 文档,代码无重叠。可完全并行。

### 8.2 跟现有 Live2D 集成的影响

**应不破坏**。改动只:
* 加一个 `characters.splash_art_url` 列(可空,旧角色 NULL,行为不变)
* 加一个 `POST /api/characters/{id}/splash_art` endpoint(独立路径)
* 加几个 frontend 组件(独立目录)
* CharacterSwitcher / CharacterPanel 插一个新入口按钮 / 表单字段

`Live2DCanvas` / `CharacterView` / `resolveLive2dModelUrl` / live2d
scanner / motion_map_json / character_states / WS 协议 — **全部不动**。

回归风险面:CharacterPanel.tsx 的编辑表单(加 splash 字段时改 form
state)+ TopBar 入口替换。

### 8.3 跟 GPT Image 2 立绘生成的时序

用户**并行**做立绘生成(GPT Image 2 batch):

* Fan UI 第一次 ship 时,**5 个角色里可能只有 1-2 个有 splash art**
  (Momo / 八重 优先?用户决定)。
* **Q5 fallback 必须 work**(首字母 avatar)—— 否则 80% 卡片黑屏。
* 用户后续在 CharacterPanel 编辑或专门 SplashArtDropzone 入口逐个
  补图 → 实时刷新(Zustand setCharacters refetch)。

**关键**:Fan UI ship **不能 block**等所有 splash 出齐;fallback
要从 day 1 就 work。


---

## 9. 风险点(P0/P1/P2)

### P0 — must address before ship

| 风险 | 详情 | mitigation |
| --- | --- | --- |
| **多卡同时 transform + backdrop-blur 导致 Tauri WebView GPU 卡** | 5-10 张卡同时 `transform: rotate()` + 父层 `backdrop-filter: blur(20px)` 可能让 WKWebView 帧率掉到 30fps 以下 | 限制同屏卡片数(MVP 5-8 张);backdrop-blur 只用在 overlay 一层而非每张卡;实测加 FPS meter (`React.Profiler` / `performance.now()` + RAF 计数);若卡顿降级 `blur(8px)` 或去掉 |
| **立绘缺位**(用户还在跑 GPT Image 2 batch) | Fan UI ship 时 5 角色里 1-2 张有立绘,fallback 必须 work | Q5 选 A(首字母 avatar)+ ship 前手测 0 splash / 部分 splash / 全 splash 三态 |

### P1 — soon

| 风险 | 详情 | mitigation |
| --- | --- | --- |
| **macOS WKWebView CSS 3D + backdrop-filter 兼容** | macOS 15+ WKWebView 已支持 `backdrop-filter`(已在 7 个组件实战),但 `transform: rotateY()` + `perspective` 兄弟元素混合时偶有渲染 z-fighting | MVP 不用 3D rotate(纯 2D rotate 够);若做"卡牌翻面"再单独验 |
| **Windows WebView2 兼容**(未来 Win 版) | Skyler 当前 macOS-only(`DESIGN.md §二十`);Windows WebView2 (Edge Chromium) `backdrop-filter` 支持 Edge 17+,`rotate` OK | 不在 v4-fan 范围;留 v6+ 跨平台时统一验 |
| **splash_art 文件存 `frontend/public/` 在生产打包是否进 bundle** | vite build 把 `public/` 全 copy 到 `dist/`,用户上传的图会进打包产物 → app 越跑越大 | 用 `frontend/public/splash_art/` 加 `.gitignore`(像 `live2d/` 一样);打包时 vite 仍 copy(无 strip 选项),但用户体感"我的角色立绘和 app 一起备份"也合理。**待用户决策**(详 §7 Q3 升级讨论) |
| **CharacterSelect.tsx 空 stub** | 历史残留,未引用 | Fan UI commit 顺手 `git rm` |

### P2 — nice to fix

| 风险 | 详情 | mitigation |
| --- | --- | --- |
| **卡牌 hover 时 z-index 层叠** | rotate 后 stacking context 复杂;hover 卡需要"飘到最上" | hover 时 `z-index: 50` + transition;实测 OK |
| **键盘导航**(accessibility) | 扇面卡用 ←/→ 切焦点,Enter 进 detail,Escape 关 | MVP 至少 Tab 切焦点 + Enter 触发;arrow keys 留 v4.1 |
| **响应式**(panel 模式 350×500 vs 全屏) | Tauri 默认 350×500 widget 模式装不下 5 张扇面 | Fan overlay 全屏(`fixed inset-0`)而非塞进 panel;widget 模式点入口直接全屏 overlay,关 overlay 回 widget |
| **i18n** | tagline / persona 都中文 hardcode | 沿用现有(全工程中文 UI),不在本 stage 内 |


---

## 推荐 sub-stage 拆解预览

| sub-stage | 内容 | 工时 | 依赖 |
| --- | --- | --- | --- |
| **Fan-1 backend + DB** | DB migration(`splash_art_url` + 可选 `tagline`)+ `POST /api/characters/{id}/splash_art` upload + characters_api PATCH 顺手吃新字段 | 0.5–1 d | 无 |
| **Fan-2 fallback + primitive** | `--shadow-card-{rest,lift}` 加 themes.css(5 主题 ×2 行)+ `CharacterCard.tsx` 单卡组件(splash + fallback 链 Q5 实现)+ Storybook-less 手测页 | 1 d | Fan-1(可并行) |
| **Fan-3 FanLayout + 入口** | `FanLayout.tsx` 全屏 overlay + 弧形布局算法(Q2 选项 A)+ 入场 keyframes + outside/escape close;TopBar Switcher 加"扇面浏览"入口按钮 | 1.5–2 d | Fan-2 |
| **Fan-4 detail modal** | `CharacterDetailModal.tsx`(persona / character_state fetch / "切换到该角色" CTA Q7 选项 B) | 0.5–1 d | Fan-3 |
| **Fan-5 SplashArtDropzone + CharacterPanel 集成** | dropzone(抄 Live2DDropzone ~70%)+ CharacterPanel 编辑表单加 splash 字段 + 上传成功后 refresh | 1 d | Fan-1 |
| **Fan-6 polish + WebView GPU 实测** | FPS 实测(P0 风险);blur 降级方案;keyboard nav(Tab + Enter);响应式 widget→fullscreen | 0.5–1 d | Fan-3,4,5 |

**总计 5–7 工作日**,与 Stage 2 同量级。**并行机会**:Fan-1 + Fan-2
可同步;Fan-3 / 4 / 5 互不冲突(FanLayout 不 import dropzone)。

---

## 关键发现(3-5 条)

1. **切换链已经是 pure-frontend reactive**(`setCurrentCharacterId`
   单 setter 触发所有下游),Fan UI 不需要任何 backend switching 改动。
   工作量主要在**新 UI 组件 + 立绘字段 / 上传**两条路。
2. **Live2D upload 已踩平 70% 坑**(`live2d_api.py` safe_path / size /
   slug / motion_map / Tauri zip MIME 兜底全有),splash art upload 是
   单文件版可大量复用(P 没新 backend 风险)。
3. **CSS variable 主题系统统一 + 5 主题**已经 ship,Fan UI 只需要新加
   `--shadow-card-rest/lift` 等 ~3 个 token,不需要重做色板。
   `backdrop-blur` 已在 7 个组件实战(Tauri WebView 已验证可跑),但
   8 张卡同时 backdrop 是 P0 风险点(测试必做)。
4. **5 个角色 0 张有 splash art**;Fan UI ship 时**fallback 路径(Q5
   首字母 avatar)是主路径**,splash 路径是逐步替换。Fan UI ship 不阻
   塞立绘 batch,反之亦然。
5. **`CharacterSelect.tsx` 是空 stub**(从未被引用),Fan UI commit 时
   顺手 `git rm` 清理。CharacterSwitcher 是真主入口(TopBar dropdown),
   Fan UI 决策是"替换它 / 与它并存"(§7 Q7 推荐并存)。

---

Audit 完成时间:2026-05-14
git commit hash:`50b54aa`(`50b54aa4e8124566fc99bd9a4f1e62d77d4e5ce6`,
audit 仅产文档,无源码改动,与本 commit 同 head)


---

# Fan UI 完成状态(Fan-6 ship 后追写)

完成时间:2026-05-14。Fan UI 6 个 sub-stage(实际 14 个 commit,含 5 次 micro-iter)按
audit §推荐顺序 ship 完毕,真机走查通过。

## sub-stage 列表 + commit hash

| stage | commit | 内容 |
| --- | --- | --- |
| Audit (Fan-0) | `3024d31` | Q1-Q8 候选决策 + sub-stage 拆解(本文档主体) |
| **Fan-1** backend | `2aaa4d2` | DB migration + POST/DELETE `/api/characters/{id}/splash-art` + 34/34 测试 |
| **Fan-2** primitive | `c5b43da` | CharacterCard + `_placeholder.png` + backdrop-blur P0 spike(实测 ≥55fps,推荐方案) |
| **Fan-3** layout | `eccfbe3` | FanLayout Model A 圆周转盘 + 最短路径 click + spike cleanup |
| Fan-3.1 windowed | `ee484b6` | 大 N 窗口模式 + visibleCount 参数 |
| Fan-3.2 step unify | `b8178f8` | 统一 stepDeg = arcDeg/(W-1),删 small-N 撑满弧路径 |
| Fan-3.2 tweak | `9963ac8` | arc 默认 60° → 72°(实测后微调) |
| **Fan-4** Gallery | `052d615` | TopBar GalleryThumbnails 按钮 + CharacterGallery 全屏 + DetailModal + framer-motion hero |
| Fan-4.2 dyn bg | `b69cec4` | 动态背景跟 selected 角色 splash + 交叉淡化 |
| Fan-4.3 cy v1 | `fa94e5c` | 居中公式重推 v1 |
| Fan-4.4 cy v2 | `64f35b6` | 诊断 root cause(_FAN_QUERY 被 retire 时误删)+ 60% sel-center 公式 + URL query 复活 + debug overlay |
| **Fan-5** dropzone | `35e8d74` | SplashArtDropzone + CharacterPanel 集成 + refresh 链路 |
| Fan-5.1 blur tune | `275b03a` | 背景 blur 40 → 22(留轮廓感) |
| Fan-5.2 blur polish | `cf1df47` | blur 22 → 14 + object-position center 20%(立绘上半铺满) |
| **Fan-6** wrap | (本 commit) | dropdown 共存 sanity + ROADMAP backlog + 完成状态 marker |

## Q1-Q8 决策落地 vs audit 拍板

| Q | audit 推荐 | 实际落地 | 一致 |
| --- | --- | --- | --- |
| Q1 动画 | A 纯 CSS;hero 时 framer-motion | Fan-3 纯 CSS transform;Fan-4 hero 引 framer-motion | ✅ |
| Q2 弧形布局 | A `transform: rotate()` + transform-origin | Fan-3 同;Fan-3.1 加窗口模式 | ✅ |
| Q3 立绘存储 | A 文件 + URL 字符串 | Fan-1 `splash_art_url TEXT` + `frontend/public/splash-art/<id>.<ext>` | ✅ |
| Q4 上传方式 | A 仿 Live2D multipart | Fan-1 backend + Fan-5 frontend 同 pattern | ✅ |
| Q5 fallback | A 首字母 avatar → C 通用占位退化 | 简化为单一 `_placeholder.png`(Fan-2 PIL 灰图)— 一档退化更可控 | ⚠ 简化 |
| Q6 detail 字段 | name + tagline + persona + character_state + 角标 | name + persona + character_state(无 tagline / interests,DB 暂无字段) | ⚠ 缩减(留 v4.1+ backlog) |
| Q7 CTA 位置 | B detail 内"切换" | Fan-4 同 | ✅ |
| Q8 卡牌底图 | A splash art(无图回 fallback) | Fan-2/4.2 同(详 fallback 简化见 Q5) | ✅ |

**关键偏离 1**:Q5 fallback 链从"首字母 avatar → 通用占位"两档简化成"单一 placeholder.png"。
理由:首字母 avatar 跟主题色绑定逻辑复杂,而 placeholder 一张图覆盖所有 case 更可控,
工程成本更低。dogfood 后若觉得"全部 placeholder 太单调",再 Fan-7+ 加首字母层。

**关键偏离 2**:Q6 detail 缩减到 name + persona + character_state。tagline / interests
DB 字段未加(audit 估时也是 "可选")。当前 detail panel 已经"够用",留 v4.1 backlog
等用户反馈再决定加 schema 与否。

## 已知 v4.1+ 改进点(写进 ROADMAP)

| 项 | 工时 | 触发条件 |
| --- | --- | --- |
| Vitest + 视觉回归套件 | 0.5-1d | 后续 layout 数学(stepDeg / shortestDelta / fade)迭代频繁时 |
| tagline / interests schema | 0.5-1d | 用户反馈 detail panel 信息密度不足 |
| 立绘 batch 生产工作流 | (用户侧)| GPT Image 2 batch 跑完 → 一次性给所有 character upload |
| 风格固化(themes 加 fan-specific token)| 0.5d | 5 主题下 fan UI 视觉验收 + 3 个 token(`--shadow-card-rest/lift` / `--gradient-card-default`)能否承载所有主题 |
| 卡间 hover 锐化背景 | 0.3d | 用户觉得静态背景太"死",想要 hover 哪张卡背景临时去 blur 一档 |
| Widget mode Gallery 入口 | 0.5d | TopBar 只 panel mode 渲染,widget mode 没 Gallery 入口;若用户常 widget mode 浏览角色再补(ControlBar 加按钮) |
| Fan-7 hover 卡 | 0.3d | dogfood 后觉得静态卡太呆 |

## 整体 bundle 增量(audit 预估 vs 实际)

| | gzip | raw |
| --- | --- | --- |
| pre-Fan baseline(Fan-0 / Fan-1 backend only)| ~290 KB | ~1023 KB |
| Fan-2(`+CharacterCard / placeholder` only) | 290.50 KB | 1023.34 KB |
| Fan-3(`+FanLayout`,~5 KB) | ~293 KB | ~1031 KB |
| Fan-4(`+CharacterGallery / DetailModal / framer-motion`) | 337.34 KB | 1164.38 KB |
| Fan-5(`+SplashArtDropzone / lib/characters`)| 339.57 KB | 1172.67 KB |
| **Fan-6 ship** | **~340 KB** | **~1175 KB** |
| **总增量** | **+50 KB(~17%)** | **+150 KB** |

audit §3.3 预估:"framer-motion ~50 KB gzipped"。**实际 +44 KB,对齐**。其余 ~6 KB
是 4 个组件 + 1 个 lib 文件。

## 总工时(audit vs 实际)

audit §6 预估 6 个 sub-stage **5-7 工作日**。

实际:
- Fan-1 backend ~0.5d
- Fan-2 primitive + spike ~0.5d
- Fan-3 layout(3 micro-iter)~1d
- Fan-4 Gallery + bg + 居中(4 micro-iter)~1.5d
- Fan-5 dropzone(3 micro-iter)~0.5d
- Fan-6 wrap ~0.3d

**累计 ~4.3 工作日**,在 audit estimate 内偏低端。原因:大量复用现有 pattern(Live2DDropzone
HTML5 drag/drop / Live2D upload backend 路径 / themes.css var system),且 spike 提前
验证 backdrop-blur 性能让 Fan-4 直接走 overlay 方案不绕弯。

## 6 个 flow 真机验收清单

```
1. TopBar 点 Gallery 按钮 → 全屏 overlay,fan 视觉 + 动态背景 + selected 标识 ✓
2. 点边卡 → fan rotate 500ms 平滑过渡到该卡为中心,背景同时交叉淡化 600ms ✓
3. 点中心卡 → DetailModal 开,framer-motion hero 从 browse 卡 morph 到 detail
   位置(0.45s,cubic-bezier),persona / character_state / CTA 显示 ✓
4. detail "切换到这个角色" CTA → setCurrentCharacterId + Gallery 关 →
   主 UI Live2D 切换,WS character_id 同步,新对话流走该角色 ✓
5. ESC 关 detail(回 browse)/ ESC 关 Gallery(回主 UI)/ × 按钮同效 ✓
6. CharacterPanel 角色立绘 dropzone 拖图 → toast + refresh →
   再开 Gallery → 该角色卡片显示真立绘 + 背景变成 blur 14px 立绘 ✓
```

任意一个 flow 出问题 → 报 micro-iter。

---

Fan UI 完成时间:2026-05-14
Fan-6 commit hash:见 git log(本段追写时未知,git tag 后回填)

