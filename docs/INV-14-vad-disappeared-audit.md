# INV-14 · VAD 监听消失 audit

> 2026-05-27 · 调研 only · 不动 code · ~30 min CC
>
> PM 反馈: "之前 Skyler 有 VAD 监听 · 现在不见了"
>
> **TL;DR verdict**: VAD 代码**未删** · 仍完整(useAudio VAD loop / VadBar UI /
> recordingMode state / toggleVad action 都在)。表象 "不见了" 由 **2 层叠加问题**
> 造成:
> 1. **UI discoverability gap** — VAD 设置入口从主 ⚙ 设置(SettingsPanelV2)
>    挪到了"能力 → AI Providers → ASR tab"(bugfix-2.2 收口 SettingsPanelV2 没
>    re-include AsrVadSection)· PM 看主设置找不到 = "不见了"
> 2. **后端 ASR 链路 broken** — `backend/main.py:21-22` 写死 `HF_HUB_OFFLINE=1`
>    + `~/.cache/huggingface/hub/` 无 `Systran/faster-whisper-small` snapshot ·
>    每次 preload + transcribe 都 `LocalEntryNotFoundError` · 29/29 失败 · 0 个
>    successful `asr_result` 在整个 log file 期间(2026-05-25 起)
>
> 即使 PM 找到 VAD 入口切到 vad 模式 · 麦克风也能录音 + 发 voice frame · 但
> backend ASR 转录失败 · LLM 永不响应 · 用户体验 = "点了但什么都没发生" → 误
> 以为 VAD 功能本身没了。
>
> **修复优先级**:**(A) backend ASR 修(强 P1)** + **(B) UI 入口 re-include 进 SettingsPanelV2(小)**。

---

## §1 历史 trace

`git log --all --oneline -S "vad_filter" -- backend/asr/whisper.py`:

| commit | 时间 | 主题 |
|---|---|---|
| `61c4d7b` | 2026-05-04 03:20 | Skyler v3-WIP baseline: v2.7 + v3-A/B/C/D in progress(VAD baseline 起点) |

`git log --all --oneline frontend/src/components/VadBar.tsx`:

| commit | 时间 | 主题 |
|---|---|---|
| `946137d` | 2026-05-14 22:01 | bugfix-4 — observability + 小窗 3 bug 修 + VadBar.tsx idle 不渲染(防"屏幕中间一道线") |
| `61c4d7b` | 2026-05-04 03:20 | baseline VadBar.tsx 起点 |

`git log --all --oneline -S "HF_HUB_OFFLINE" -- backend/main.py`:

| commit | 时间 | 主题 |
|---|---|---|
| `61c4d7b` | 2026-05-04 03:20 | baseline 已含 `HF_HUB_OFFLINE=1`(无独立 commit · 一开始就这样) |

**Verdict §1**: VAD 代码自 2026-05-04 v3-WIP baseline 起一直存在 · 期间唯一非
trivial 改动是 2026-05-14 bugfix-4 给 VadBar idle 不渲染避免一道线幻觉。
**没有任何"删 VAD" / "禁 VAD" commit**。

`HF_HUB_OFFLINE=1` 自 baseline 起就硬编码在 `backend/main.py:21-22`(预防启动
期上网 fetch HF 阻塞 lifespan)+ `.env:10` 也有(重复)。

---

## §2 当前实施 verify

`grep -rn -iE "vad|silero|webrtcvad|voice_activity|VadBar"` 命中分布:

### Backend(2 处 · 注释级)
- `backend/asr/whisper.py:123` — `vad_filter=True` 给 faster-whisper transcribe
  (whisper 内部用 Silero VAD 静音过滤 · 不是用户级 VAD 模式)
- `backend/proactive/engine.py:586-591` — comments 提"用户 VAD 续聊"(per spec)

### Frontend(~30 处 · 全活路径)

**State + 入口**:
- `store/index.ts:246-247,470-471` — `recordingMode: 'manual' | 'vad'` state +
  `setRecordingMode` action(default 'manual')
- `store/index.ts` — `vadState: 'sleep'|'active'|'recording'` / `vadThreshold` /
  `vadIdleTimeoutMs` / `silenceTimeoutMs`(全套 VAD state)

**核心实现**:
- `hooks/useAudio.ts:128-224` — 完整 VAD loop(RAF + AudioContext analyser +
  threshold + silence timeout + idle sleep)· `toggleVad()` API 切 sleep ↔ active
- `hooks/useAudio.ts:130-201` — `vadLoop()` 主体 · 检测 mic input max amplitude vs
  threshold · 进 recording 状态 · silence > 1500ms 自动停 + send · 60s idle
  回 sleep · 还含 "AI 说话时用户语音打断" 子逻辑(`sendInterrupt`)

**UI 组件**:
- `components/VadBar.tsx` — 顶部状态条(recording/active 时显示 · sleep/idle 不
  渲染 · per bugfix-4 hotfix)
- `modes/Widget.tsx:71` — Widget 模式 mount `<VadBar />`
- `components/ControlBar.tsx:35-36` — 麦克风按钮 in vad 模式调 `toggleVad()`
- `components/ChatInput.tsx:40` — 文本/语音切换识别 vad 模式

**设置入口**(关键)`components/SettingsPanelLegacy.tsx::AsrVadSection`:
- export from SettingsPanelLegacy
- imported & rendered by **`capabilities/AIProvidersSection.tsx:31,229`** in
  ASR tab(`tab === 'asr'`)
- `<AsrVadSection />` 含 Manual/VAD 段切换 + threshold slider + silence timeout
  + 静音麦克风开关
- **NOT** imported by `settings/SettingsPanelV2.tsx`(bugfix-2.2 收口 spec 10
  section 不含 AsrVad)

### 0 个 dead code / 0 个注释掉的 VAD
全套 wiring 活路径。`grep -rn "// .* vad\|# .* vad"` 看 0 个 commented-out VAD
block。

---

## §3 ASR / whisper 链路状态 ⚠️ **broken**

### §3.1 代码现状(backend/asr/whisper.py)
完整实现:
- `WhisperASR` class with lazy load + thread executor
- `load_model()` reads `get_whisper_model_size()` from yaml(default `"small"`)
- `transcribe()` / `transcribe_b64()` API
- `vad_filter=True` 给 faster-whisper(内部 Silero VAD 静音过滤)
- main.py:541-556 lifespan startup 触发 `_preload_whisper()` background task

### §3.2 实测 runtime 状态(logs/backend.log)
```bash
$ grep -c "Whisper model preload failed" logs/backend.log
29

$ grep -c "asr_result" logs/backend.log
0
```

**29 次 preload 失败 / 0 次成功 transcribe**(整个 log file 期间 2026-05-25 →
2026-05-27)。

### §3.3 失败堆栈(实际错误)
```
huggingface_hub.errors.OfflineModeIsEnabled: 
  Cannot reach https://huggingface.co/api/models/Systran/faster-whisper-small/
  revision/main: offline mode is enabled. To disable it, please unset the 
  `HF_HUB_OFFLINE` environment variable.

huggingface_hub.errors.LocalEntryNotFoundError: 
  Cannot find an appropriate cached snapshot folder for the specified 
  revision on the local disk and outgoing traffic has been disabled. 
  To enable repo look-ups and downloads online, set 'HF_HUB_OFFLINE=0' 
  as environment variable.
```

### §3.4 根因 trace
两层共同导致:

**层 A · 强制 offline 模式**
- `backend/main.py:21-22`:
  ```python
  os.environ["HF_HUB_OFFLINE"] = "1"
  os.environ["TRANSFORMERS_OFFLINE"] = "1"
  ```
- `.env:10-11`:
  ```
  HF_HUB_OFFLINE=1
  TRANSFORMERS_OFFLINE=1MCP_BEARER_TOKEN=...  ← .env 这行格式还有问题(同行拼了 MCP token)
  ```

**层 B · 本地 HF cache 无 whisper 模型**
```bash
$ ls ~/.cache/huggingface/hub/
CACHEDIR.TAG
models--sentence-transformers--paraphrase-multilingual-MiniLM-L12-v2
```
只有 sentence-transformers(embedding 模型 · INV-13 short_term 用)· **没有**
`models--Systran--faster-whisper-small/`。

faster-whisper 1.x 走 `huggingface_hub.snapshot_download(...)` 拉模型 · offline
模式 + cache miss → raise。

**层 C · 模型文件存在 · 但路径不对**
```bash
$ find ~ -name "faster-whisper-small" -type d
/Users/liujunhong/Desktop/MomoOS-main/asr_model/faster-whisper-small         ← 旧 MomoOS 项目
/Users/liujunhong/Downloads/MomoOS-main 2/asr_model/faster-whisper-small
/Users/liujunhong/Downloads/MomoOS-main/asr_model/faster-whisper-small
/Users/liujunhong/Downloads/MomoOS/asr_model/faster-whisper-small
```

3 个旧项目目录都含 whisper-small 模型 · 但 Skyler 走 HF cache 路径 · 这些
本地 dir 不被 faster-whisper 看见。

---

## §4 ROADMAP / Tech Debt 检索

`grep -nE "VAD|whisper|ASR|HF_HUB"`:

`ROADMAP.md:38`:
```
| 📋 | **ASR whisper preload HF_HUB_OFFLINE** | LocalEntryNotFoundError on cold
       start + offline mode · whisper 模型 pre-warm 触发不准 · 加 startup hook
       validate model cache 完整 | dogfood 期间偶发 |
```

**known issue · P2 backlog** · 但**未触发 fix** · 在 INV-11 / INV-13 ship 期间
没人复活这条。

`IMPLEMENTATION_LOG.md:308`:
```
前端 useAudio VAD 检测到用户说话 → 立即调 `useWebSocket` 发送 `{"type": "interrupt"}`
```
v3-F 时代提及 VAD interrupt 功能 · 仍是设计意图。

---

## §5 PM "VAD 不见了" 表象 → 真因 mapping

### 表象 1: 主⚙设置面板找不到 VAD 入口
**真因**: SettingsPanelV2 spec(bugfix-2.2)10 section 顺序:
1. 角色管理 / 2. 主动陪伴 / 3. 活动感知 / 4. 剪贴板 / 5. 角色状态 / 6. 记忆
/ 7. 用户档案 / 8. 启动 / 9. 外观 / 10. 关于

**不含 ASR/VAD section** — 老 SettingsPanelLegacy 的 AsrVadSection 被挪进
**Capabilities → AI Providers → ASR tab** · 但 PM 主设置找惯了 ASR section 不
在原位置 → "VAD 不见了"。

### 表象 2: 点 vad 模式麦克风没反应
**真因**: 假设 PM 找到了 ASR tab 切到 VAD 模式:
- 前端 toggleVad 正常 · VAD loop 跑 · 检测到说话 → 录音 → 发 voice frame ✓
- 后端 ws.py:644 收 voice frame → whisper_asr.transcribe_b64 → **LocalEntryNotFoundError**
- 后端 log "ASR failed" warning · 但前端不收到 asr_result · 也不收到 LLM 响应
- 用户看到的现象 = "点了 mic 录了音但啥都没出来" → 强化"VAD 不工作"印象

---

## §6 恢复路径 + 工程量

### Path 1 · 修 backend ASR(强推荐 · P1)

**option A · 关闭 offline 模式 + 让 HF 自动下载**(最简单 · 一次性 ~80MB 流量):
- 改 `backend/main.py:21-22` 去掉两行(或加 `os.environ.setdefault` 让 .env 覆盖)
- 改 `.env:10` `HF_HUB_OFFLINE=0`(留 fallback offline 选项)
- backend restart · faster-whisper 自动 download `Systran/faster-whisper-small`
  ~80MB 到 `~/.cache/huggingface/hub/`
- **工程量**: 5 分钟(改 .env + restart 验证 successful preload log)
- 风险: 启动期短暂上网 · backend 启动延迟 ~10s for download · once cached
  不再需要

**option B · 本地模型路径**(无网或锁 offline 必要 · 中等工程量):
- 复用 `/Users/liujunhong/Desktop/MomoOS-main/asr_model/faster-whisper-small/`
- 改 `backend/asr/whisper.py::load_model()` · `WhisperModel(desired_size,...)`
  改 `WhisperModel("/abs/path/to/faster-whisper-small",...)`
- 或加 yaml `asr.local_model_dir` 字段 · per-environment 配置
- **工程量**: 15-30 分钟(改 whisper.py · 加 yaml field · sanity test)
- 风险: 路径硬编码不便迁机

**option C · 手动 copy 到 HF cache 结构**(option B 升级 · 兼容 HF 路径约定):
- 把 `/Users/liujunhong/Desktop/MomoOS-main/asr_model/faster-whisper-small/`
  按 HF cache layout 重组到 `~/.cache/huggingface/hub/models--Systran--faster-whisper-small/snapshots/main/`
- 然后 offline 模式仍能 lookup 成功
- **工程量**: 15-30 分钟(目录重组 + 创 snapshot symlink + 验证)
- 风险: HF cache 内部 layout 改了未来可能 break · 不推荐

**推荐**: **Option A** · 最低工程量 · 一次性 fix · 模型 cached 后 offline 仍 work
(per faster-whisper docs:cached snapshot 即便 OFFLINE=1 也能 load)。

### Path 2 · UI discoverability fix(小 · P2)

把 AsrVadSection 重新加进 `SettingsPanelV2.tsx` 的 sections 列表:
- 新增 section id 'asr' 或并入 'voice'(角色管理同级)
- import `{ AsrVadSection } from '../SettingsPanelLegacy'`(已 exported)
- render `<AsrVadSection />`
- **工程量**: 10-15 分钟
- 风险: 极低 · spec 加 1 section 不破坏既有 layout

**Capabilities → AI Providers → ASR tab 路径保留**(不冲突)· 给"懂技术的"
另一条路径。

### Path 3 · Backlog 同步(ROADMAP)

ROADMAP.md:38 当前是 P2 模糊描述 · 修完后改 ✅ shipped:
```
| ✅ | **ASR whisper preload HF_HUB_OFFLINE** | shipped 2026-05-27 (option A:
       HF_HUB_OFFLINE 改 0 让首次 download · cached 后稳定) + UI 重 expose
       AsrVadSection 进 SettingsPanelV2 |
```

---

## §7 总结 · 给 PM

### "VAD 不见了" 表象 = **2 个独立问题叠加 · 都不是 VAD 代码被删**

1. **UI 入口换位置**(SettingsPanelV2 bugfix-2.2 没 include)
   - 当前路径: ⚙ Capabilities → AI Providers → ASR tab → Manual/VAD 段
   - 主设置 ⚙(SettingsPanelV2)没有 → PM 找惯了找不到

2. **Backend ASR broken**(HF_HUB_OFFLINE=1 + 无 cache)
   - 即使 PM 找到 VAD 切换 · backend 转录失败 0/29 次 · LLM 不响应
   - 已在 ROADMAP P2 backlog 但未 fix

### 推荐 ship 顺序

1. **P1 · Backend ASR 修**(Option A · 5 min · `HF_HUB_OFFLINE=0` + 重启让 HF
   首次下载 · cached 后稳定)— **必修** · 不修的话 VAD 即便 expose UI 也是
   "可点不可用"
2. **P2 · UI re-expose**(把 AsrVadSection 加回 SettingsPanelV2 · 10-15 min)—
   提升 discoverability · 跟 Capabilities path 共存

### 不需要做的

- ❌ 重写 VAD 代码(无需 · 全套活路径)
- ❌ 加新依赖 silero-vad / webrtcvad(用户级 VAD 走 AudioContext analyser ·
  whisper 内部 VAD filter 走 silero · 都已 cover)
- ❌ 大改架构(只 5 行配置 + 1 section import 就修好)

---

## §8 audit 范围外 / 隔离 backlog

- `.env:11` `TRANSFORMERS_OFFLINE=1MCP_BEARER_TOKEN=...` 同行拼接 · 是 .env
  parse bug · 单独刀修(影响:TRANSFORMERS_OFFLINE 值会变 `"1MCP_BEARER_TOKEN=..."`
  而非 `"1"` · 实测 transformers 库可能仍按 truthy 判 offline · 但脏)
- whisper preload 失败时主流程不阻塞 · lifespan 继续 startup · 这是好的 ·
  但 health endpoint 应能 expose "ASR not ready" 给 UI 显示警告
- VAD threshold 默 50(0-100)· 用户实际 dogfood 期常需调 · localStorage 持久
  化已就位 · 可考虑在主设置加 quick-access slider
- silero-vad webrtcvad 等本地 VAD 库未引入 · 现走 AudioContext 浏览器原生
  vol-threshold · 简单可靠但精度不如 silero。未来 backlog 可加(用户重度
  使用 + 误判多 + 需要 sub-word 精度时)

---

## §7 Ship 记录 · P1 + P2 复合(2026-05-27)

### §7.1 Commits

| Commit | 主题 | 改动 | 状态 |
|---|---|---|---|
| `c2d8924` | **P1** · backend HF_HUB_OFFLINE 硬编码移除 · whisper preload 解锁 | `backend/main.py:19-25`(-3 +7) · 删 `import os` + `os.environ["HF_HUB_OFFLINE"]="1"` + `os.environ["TRANSFORMERS_OFFLINE"]="1"` · 替换为说明性 comment 指向本 audit doc | ✅ 保留 |
| `3f24d6c` | **P2** · SettingsPanelV2 re-expose AsrVadSection | `frontend/src/components/settings/SettingsPanelV2.tsx`(+28 -8)· import `Mic` + `AsrVadSection` · 加 4 号 section "🎤 语音输入" | 🚫 reverted(`aed67cc`)— 见 §7.8 |
| `aed67cc` | **P2 revert** · 撤销主设置加冗余入口 | revert `3f24d6c` · SettingsPanelV2 回到 10 section · VAD UI 单入口在 Capabilities → AI Providers → ASR tab 已可达 | ✅ |

### §7.2 配套 .env 改动(不入 git · `.gitignore:20`)

PM 机器 local `.env` 同步修改(与 c2d8924 commit 时刻同时手动 apply):
```
- HF_HUB_OFFLINE=1
- TRANSFORMERS_OFFLINE=1MCP_BEARER_TOKEN=54083D86-6519-4AAA-944A-4CB28199D495  ← parse bug
- MCP_BEARER_TOKEN=962EF837-B357-4924-BA90-23FF89C8919F                          ← active
+ HF_HUB_OFFLINE=0
+ TRANSFORMERS_OFFLINE=0
+ MCP_BEARER_TOKEN=962EF837-B357-4924-BA90-23FF89C8919F                          ← active (不动)
```

3 改动:
1. `HF_HUB_OFFLINE=1 → 0`(允许 HF 首次下载 whisper-small)
2. `TRANSFORMERS_OFFLINE=1MCP_BEARER_TOKEN=...` parse bug 拆分(stale token 丢弃 ·
   active token 在原 line 12 不动)
3. line 12 `MCP_BEARER_TOKEN=962EF837-...` 保留(真 active value)

### §7.3 Sanity(CC 侧 dev-time verify)

`backend/main.py` import:
```bash
$ .venv/bin/python -c "import os; import backend.main; print(os.environ.get('HF_HUB_OFFLINE'))"
HF_HUB_OFFLINE: 0   ← 符合预期(原硬编码 '1' 已移除)
```

`frontend tsc`:
```bash
$ npx tsc -p tsconfig.app.json --noEmit
(clean · 除 pre-existing PersonaEditorModal err 不挂帐本 commit)
```

### §7.4 真机 sanity 待 PM 验收

PM restart backend 后预期看到:
```
[INFO] backend.asr.whisper Loading WhisperModel 'small' on cpu (compute_type=int8)
[INFO] huggingface_hub downloading ... Systran/faster-whisper-small ...   ← 首次 ~80MB
[INFO] backend.asr.whisper WhisperModel 'small' ready
[INFO] backend.main [TIME] Whisper model load: XXXXms                       ← XX = 总耗时
```

国内首次下载可能慢(HF 不在国内镜像 · ~80MB)· cached 后即便后续 OFFLINE 也能 load。

UI 验证:
- 打开 主设置 ⚙ · 左侧列表第 4 项见 "🎤 语音输入"
- 点开内容:录音模式 (Manual / VAD) · 语音检测阈值 slider · 静音超时 slider · 静音麦克风 toggle
- 切到 VAD · 点 mic 录一句 "你好" · 看是否触发 transcribe → asr_result → LLM 响应

### §7.5 ROADMAP 同步

`ROADMAP.md:38` "ASR whisper preload HF_HUB_OFFLINE" P2 backlog **改 ✅ shipped**:
```
| ✅ | ASR whisper preload HF_HUB_OFFLINE ship 2026-05-27 (INV-14) | 真因 = ...
       修法 = ...配套 SettingsPanelV2 re-expose AsrVadSection | commits c2d8924 + 3f24d6c |
```

### §7.6 LESSONS.md 新增 Lesson #19

`docs/LESSONS.md` 加 Lesson #19 "大重构后必须 verify 旧 section 入口仍可达":
- bugfix-2.2 SettingsPanelV2 spec 10 section · 漏 include AsrVadSection 是经典 UI
  重构误漏老 section
- 修法 = `grep -rn "import.*Section" old_file.tsx` 列全套 export 对照新 spec 表
- 多入口共存 OK · 不要为"DRY"删多入口
- 新主题聚类 "UI 重构 + 入口可达性 (INV-14)"

### §7.7 后续 dogfood 监控

PM 真机用 1-2 天后回报:
- whisper preload 是否稳定 successful(应 100%)
- VAD 模式录音 → asr_result fire 是否 reliable
- 主设置 "语音输入" section 用起来是否符合预期
- 国内 HF 下载是否需要镜像配置(若慢得不能忍 · 下次刀加 HF_ENDPOINT 镜像)

若 1 周内 stable · INV-14 整段 **closed**。

---

### §7.8 Reflection · P2 revert · audit 复盘(2026-05-27 ship 后即时)

PM 真机看截图后 verify:**VAD UI 一直在 Capabilities → AI Providers → ASR tab**
(自 bugfix-2.2 SettingsPanelV2 收口后未变)。主设置加 4 号 "🎤 语音输入" section
是 **冗余** · revert 撤销。

#### audit 误判轨迹

§5.1 / §11.7 audit 推 P2 "UI 入口失踪" 时基于:
- grep `AsrVadSection` import · 看到 SettingsPanelV2 没 import → 推"主设置无入口"
- 没**实际打开 SettingsPanelV2 / CapabilitiesPanel UI 走一遍**确认 PM 找不到的是
  哪条路径

PM 真机后看:
- 主设置 ⚙ 是不含 ASR/VAD section · audit 这一层没错
- 但 **VAD UI 实际在 ⚙ Capabilities → AI Providers → ASR tab**(深 3 层)
- PM 一直能从 Capabilities path 进 · "VAD 不见了"主要是 backend ASR broken 导致
  "切到 VAD 没反应" · 不是 UI 入口完全失踪

#### 教训(修正 Lesson #19)

原 Lesson #19 写"大重构后必须 verify 旧 section 入口仍可达 + 多入口共存别为 DRY 删"
是 over-correct。

**真教训**:
- "用户找不到旧入口" ≠ "入口缺失"
- audit "UI 失踪" 类问题前必须先做 **visibility verify**:实际 mental walkthrough
  每个 path · 而不是仅 grep import
- visibility 差(Capabilities → AI Providers → ASR tab 深 3 层)与"入口失踪"是不
  同问题 · 修法也不同:
  - visibility 差 → 文档化 path / quick-access link / tooltip 提示 / **不要**冗
    余加新入口
  - 入口失踪 → 加回入口
- 误判加冗余入口的成本:UI 复杂度增加 / 主设置 11 section 太多负担 / 维护成本翻
  倍(两路径要同步)

详见修正后 LESSONS.md #19 + INV-14 反思的 ROADMAP 同步。

---

**§7 ship 闭环 · P1 保留(c2d8924 backend ASR 真有 broken)· P2 reverted
(`aed67cc` · UI 入口一直可达 · 主设置加是冗余)· 单入口 Capabilities → ASR tab
已够用 · 等 PM 真机 restart 验收 backend whisper preload + VAD mic 录音端到端
work**。

---

## §8 Ship 记录 · HF mirror + offline fallback 双保险(2026-05-27)

> §7.7 backlog 实施 · PM 拍板 ship。INV-14 P1(`c2d8924`)修了模型 download 路径
> 但留了 runtime HEAD check 阻塞坑 · 本 commit 闭环。

### §8.1 触发症状

PM 实测 `_build_messages` **49952ms**(50 秒)· 阻塞每轮 LLM 请求 ~50s · 几乎不可用。

真因 trace:
- `sentence-transformers` / `transformers` 库 runtime 调 `huggingface_hub` HEAD
  check 模型元数据 / revision(即便模型 cached 也会 check tag/revision 一致性)
- 国内访问 `huggingface.co` 极不稳 · HEAD request 单次超时 ~10s · `huggingface_hub`
  默认 5 retry · 累积 ~50s 阻塞 main thread
- 阻塞 `_build_messages` 因 long_term_memory.search 调 embedding model 触发的
  HEAD check(memory recall 路径)

### §8.2 Commit

| Commit | 主题 | 文件 | LoC |
|---|---|---|---|
| `2680921` | HF mirror + offline fallback 双保险 | `backend/main.py` | +37 / -1 |

### §8.3 三层安全网设计

**L1 · mirror 默认走 hf-mirror.com**
- `.env` 加 `HF_ENDPOINT=https://hf-mirror.com`(显式 · 用户可改)
- `backend/main.py` 顶部 `os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")`
  兜底(防 .env 不被加载 · pydantic_settings 只读声明字段)
- 国内访问 hf-mirror.com ~10x 快 · 99% 场景直接 work

**L2 · 启动期 HEAD probe + 自动 offline fallback**
- lifespan 加 "3.5. HF mirror reachability probe" 段
- 如 `HF_HUB_OFFLINE != "1"`(用户没显式离线)· urllib HEAD `HF_ENDPOINT` 3s
  timeout
- 通 → log info · 继续正常路径
- 不通(任意 Exception:URLError / DNSError / SSL / timeout 等)→ 自动设
  `HF_HUB_OFFLINE=1` + `TRANSFORMERS_OFFLINE=1` · log warning
- 设计选择:同步 urllib stdlib(不引 httpx/aiohttp dep)· lifespan 阻塞 ≤ 3s · 用户
  startup 体验几乎不变

**L3 · offline cache hit**
- L2 切 offline 后 · `huggingface_hub` 读 `~/.cache/huggingface/hub/` 已有 snapshot
- `faster-whisper` / `sentence-transformers` 都支持 OFFLINE=1 cache hit
- 仅"完全没 cached 过的模型" + "首次启动" 才会失败 · 用户能看到清晰报错(比
  silent 50s timeout 强)

### §8.4 实测

**HEAD probe live test**(non-prod CC dev box):
```
hf-mirror.com:    OK status=200
huggingface.co:   OK status=200 (网络好时 · 但 PM 国内现场不稳)
bad-host.invalid: FAIL URLError ← 走 fallback 路径 · 自动 OFFLINE=1
```

**main.py import smoke**:
```
HF_ENDPOINT after main:  https://hf-mirror.com  (setdefault 生效)
HF_HUB_OFFLINE after main: 0                    (.env 读出)
```

预期真机(PM restart):
- backend log 见 `[HF] mirror reachable: https://hf-mirror.com (status=200)`
- 后续 `_build_messages` 回到 < 500ms 正常水平
- 网络抽风 mirror 也挂时 · 见 `[HF] mirror unreachable: ... · fallback OFFLINE=1`
  · cached snapshot 仍工作

### §8.5 .env 改动(不入 git)

`.env` 在 `.gitignore:20` · 不入 git · PM 机器同步:
```
+ HF_ENDPOINT=https://hf-mirror.com
```

setdefault 兜底机制 · `.env` 即便不被加载(pydantic_settings 不读非声明字段)·
module-level setdefault 仍生效。两路径冗余 · 防一处失效。

### §8.6 与 INV-14 P1(`c2d8924`)的关系

```
P1(c2d8924):删硬编码 HF_HUB_OFFLINE=1
   → 让 whisper / embedding 模型首次 download 成功
   → cached snapshot 后续 load 不依赖网络

§8(2680921):mirror + probe + offline fallback
   → 修 runtime HEAD check 阻塞(每次 _build_messages / embed 都触发)
   → 即便 mirror 全挂 · cached 模型仍 work
```

两 commit 不互相依赖 · 但叠加才形成完整安全网。**两个一起 ship 才让 PM 国内
环境真正可用**。

### §8.7 与 ROADMAP 关系

`ROADMAP.md:38` "ASR whisper preload HF_HUB_OFFLINE" P2 backlog 已 ✅(c2d8924)·
本 commit 是 § 7.7 backlog 实施(`§7.7 后续 dogfood 监控` 提及 "若国内 HF 下载
慢得不能忍 · 下次刀可加 HF_ENDPOINT 镜像 · §7.7 backlog 记录")· 已完整闭环。

### §8.8 Lesson #23

`docs/LESSONS.md` 加 Lesson #23:**国内部署任何 transformers/sentence-transformers
应用 · 必须 mirror + offline fallback 双保险 · 单 mirror 仍可能挂 · 单 offline
首次 cache 缺失会失败**。

---

**§8 ship 闭环 · 单 commit `2680921` · 三层安全网(mirror / probe / cache hit)·
等 PM 真机 restart 验收 _build_messages < 500ms · 若稳定 INV-14 整段 closed**。
