# 🌸 Skyler

> A local-first AI companion that lives on your desktop — Galgame-style avatar on the outside, full-stack life & tools agent on the inside.

![Python](https://img.shields.io/badge/Python-3.10+-blue) ![FastAPI](https://img.shields.io/badge/FastAPI-async-green) ![Tauri](https://img.shields.io/badge/Tauri-2.0-orange) ![React](https://img.shields.io/badge/React-18-61DAFB) ![Platform](https://img.shields.io/badge/platform-macOS-lightgrey) ![Status](https://img.shields.io/badge/v3-✅%20complete-success)

> **Status (May 2026)**: v3 ✅ complete + v3.5 chunk 5 ✅ + chunk 7 ✅ + chunk 6 (a/b/c) ✅ shipped. Media-integration wrap-up complete: chunk 6b mpv subprocess+IPC self-decoder for netease songs (6 `netease.local_*` capabilities, NCM autoplay actually closes the loop via mpv's native macOS NowPlaying registration — no PyObjC wrapper needed since mpv 0.34+ handles it natively); chunk 6c passive xiaohongshu URL parser (single capability `xhs.parse_url`, zero proactive scraping methods exposed at module level — red line enforced in code, not just policy). 51+ capabilities, 6 proactive triggers, 950+ tests / 0 regressions, 5 abstractions—CapabilityRegistry / ProactiveTrigger ABC / bidirectional MCP / SAFE path util / mpv-IPC wrapper. Next up: chunk 8 v4 屏幕感知（VLM 抽象 + Tauri 截图 + 隐私黑名单）。
>
> *Project formerly known as MomoOS — rebranded to Skyler in 2026-05.*

🌐 **Languages**: **English** · [简体中文](README.zh-CN.md)

---

## What is Skyler?

Skyler is a **local-first AI companion** that lives on your Mac as a transparent, always-on-top desktop avatar. She doesn't just respond — she remembers everything you've shared, understands your habits, and proactively reaches out when it matters.

The dual identity:
- 🎭 **Galgame-style companion experience** — Live2D avatar, persona-driven dialogue, emotion-driven voice synthesis, character status panel
- 🛠️ **Life & tools agent** — long-term memory, MCP tool ecosystem, natural-language scheduling, screen awareness, clipboard assistance, daily briefings

Two interaction modes, one companion:
- **Widget mode** — transparent, always-on-top floating avatar for quick voice interaction
- **Panel mode** — full-window app with chat history, memory viewer, character manager, and settings

Heavy inspiration from [Open-LLM-VTuber](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber) (avatar UX) and [Hermes Agent](https://github.com/NousResearch/hermes-agent) (skill-accumulating tool agent). See [§Inspirations](#inspirations).

---

## Features

### 🎙 Input & Output
- **Voice input** with two modes:
  - **Manual mode** — click to start recording, click again to send
  - **VAD mode** — click to activate; auto-detects speech via Web Audio API; auto-sends after 1.5 s silence; 60 s idle returns to sleep
- **ASR result preview** — recognized text shown above input box in real time via `asr_result` WS message; persists into chat history
- **Streaming output** — text and audio arrive sentence by sentence
- **TTS** — CosyVoice (DashScope, default) → Edge-TTS fallback; per-character `voice_model` config; SoVITS planned
- **Auto-mute mic** when the assistant is speaking (prevents feedback loop)

### 🧠 Memory & Personality
- **Short-term memory** — last 20 turns, always injected
- **Long-term memory** — SQLite + sentence-transformers vector search, top-5 relevant memories per turn, isolated per character
- **4 memory tools** (LiteLLM tool calling) — `save_memory` / `delete_memory` / `list_memories` / `compress_memories`; LLM autonomously manages what to remember
- **Two-layer user profile** — memory entries (facts) + free-text `profile_summary` auto-rewritten incrementally every 50 turns or on conversation deletion
- **Memory viewer drawer** — browse / add / edit / delete with type-colored tags (fact / instruction / emotion / activity / daily)
- **Memory toggles** — long-term memory, profile, web search all toggleable in Settings

### 🤖 Multi-Agent Intelligence (v3-C: simplified)
- **ChatAgent direct flow** — LiteLLM tool calling drives memory + built-in tools in a single LLM round-trip (PlannerAgent retired in v3-C)
- **Real MCP tool integration** — extensible ToolRegistry
- **LiteLLM unified LLM** — DeepSeek / Qwen / OpenAI / Claude (config switchable)
- **Web search** — model-native search (Qwen Max / DeepSeek), toggled via `enable_search`

### 🎭 ChatGPT-Mode Conversations + Multi-Character
- **Per-character isolation** — every character has its own conversations + memory; `profile_summary` is shared across characters (one impression of you)
- **Conversation list** — collapsible sidebar with conversation rename / delete; deleting a conversation triggers `profile_summary` recompute
- **Character switcher** — dropdown in TopBar, full CRUD via CharacterManagerDrawer (Momo / id=1 is the system default and cannot be deleted)
- **Per-character voice** — `character.voice_model` JSON: `{provider, voice, instruct_supported}`; empty falls back to global default

### 🎨 UI: 8-Theme System (v3-A)
Settings → UI 风格 lets you switch between:

| Theme | Vibe |
|---|---|
| 🌫️ Morandi | warm minimal cream |
| 🌆 Dusk *(default)* | dreamy purple twilight |
| 🌊 Glass | glassmorphism cool |
| 🌸 Watercolor | pixiv pastel pink |
| 🌌 Aurora | deep-sea green-teal |
| 🌷 Sakura | sakura night |
| 🌃 Cyber | cyber crimson |
| 💜 Lavender | misty lavender |

All components use `var(--color-*)` from `styles/themes.css` (no hardcoded Tailwind colors). Persisted in `localStorage`. First-paint flash prevented by applying `data-theme` on mount.

`lucide-react` icons across all 11 components (no Unicode emoji icons remain).

### 🔔 Proactive Engagement
- **Alarm & reminder system** — natural-language scheduling, spoken in character when triggered
- **Todo management** — agent-created and user-created tasks tracked in SQLite
- **Proactive push** — backend initiates messages anytime via persistent WebSocket (`notify` / `alarm` / future `screen_comment`)

### 📋 Clipboard Assistant (v3-G chunk 3a, May 2026)
- **后端轮询**：macOS 走 `NSPasteboard.changeCount`（pyobjc transitive，无新装），跨平台 fallback 走 `pyperclip`。1Hz 轮询；每次捕获自动启发式识别 content_type（`url` / `code` / `plain_text` / `markdown` / `json`）。
- **隐私**：仅本地内存 ringbuffer（最近 50 条，TTL 24h），重启清空，**不持久化**到 SQLite，不外传。
- **3 个 capability**（CHAT_AGENT consumer）：`clipboard.get_recent` / `clipboard.summarize` / `clipboard.translate`。LLM 在用户提到「刚复制的」「上面那个」「翻译这段」时按 `_TOOL_PROMPT_ADDENDUM` 引导按需调用——**不自动响应**剪贴板变化，避免烦扰。
- **设置面板**：[剪贴板] section 显示最近 5 条预览（hover 看完整内容）+ 隐私一行说明 + [全部清除]。
- **路由**：`GET /api/clipboard/recent` / `POST /api/clipboard/clear` / `POST /api/clipboard/captured`（备用 frontend-driven 路径）。

### 💗 Character State (v3-G chunk 3b, May 2026)
- **跨 turn 累积状态**：`character_states` 表 (mood / intimacy / current_thought / current_activity)；与 `<emotion>` 标签（per-turn 瞬时）独立不冲突。
- **`<state_update>` 标签协议**：LLM 每轮可在 `<emotion>` 后输出自闭合标签 `<state_update mood="happy" intimacy_delta="+1" thought="..." />`。`backend/agents/chat.py _parse_state_update` 解析，单轮 `intimacy_delta` clamp 到 ±2 防刷高，无效 mood 静默忽略。3 道 strip 防泄露（流式按段 + 写库前 + TTS preprocessor）。
- **3 个 capability**：
  - `character.get_state`（CHAT_AGENT，用户问「你最近怎么样」时调）
  - `character.set_activity`（CHAT_AGENT，让 Momo 自己更新「在做什么」「在想什么」营造连续性，prompt 强引导每 5-10 轮一次）
  - `character.intimacy_decay`（SCHEDULER，每天 0:00 自动 -1，min 0，让长期不互动的关系慢慢冷淡）
- **WS 协议扩展**：新增 `state_update` push 类型，每次 state 变化（标签解析后或 set_activity 调用后或 reset 后）push 一次；前端 `CharacterStatePanel` 自动刷新。
- **前端浮动状态条**：mood emoji + intimacy 进度条 + hover 看 thought / activity。Widget 模式右下角 / Panel 模式 CharacterView 顶部。
- **设置面板**：[角色状态] section "显示状态条" toggle + "重置亲密度"按钮（带确认弹窗）。
- **路由**：`GET /api/characters/{id}/state` / `POST /api/characters/{id}/reset_state`。

### 🌅 Proactive Companionship (v3-G chunk 2 + 2.6, May 2026)
- **通用 proactive engine** — `trigger → aggregate → ChatAgent → WS push` 流水线。`ProactiveTrigger` 抽象类让新触发器只需新建一个文件（cron / interval / event-source 三选一调度方式）。详见 DESIGN §十五之B
- **两种交互哲学**（chunk 2.6 起，`config.proactive.mode` 互斥决定）：
  - **模式 A 单方面播报**（`morning_briefing`）：cron → 整段 200-300 字简报推送。适合"非问也得通知"场景。
  - **模式 B 邀请对话 ⭐推荐**（`wake_call_briefing`）：cron → 8-15 字短问候 → 用户响应 → ChatAgent 按响应风格自适应输出（嗯 → 50-80 字精简 / 精神 → 180-260 字完整 / 拒绝起床 → ≤25 字 + 调 snooze tool 推迟 / 切话题 → 优先回应当前话题，丢弃简报）。适合大多数生活节奏 trigger（早晨 / 饭点 / 睡前），默认 v3-F' 走模式 B
- **stage 2 自适应**：用户响应风格触发 ChatAgent system prompt 末尾自动注入 wake_call addendum（`backend/agents/chat.py _build_messages` consume-on-detect）；assistant 简报回复 `kind='normal'`（让 profile_summary 看见真对话内容）
- **跨进程持久化**：`pending_briefings` 表存 stage 1 聚合数据（time / calendar / instruction memories / city），TTL 默认 30 分钟，超时自动失效；后端 hot-reload 不丢叫醒上下文
- **Snooze tool**：`proactive.snooze_wake_call(minutes)` capability 让 LLM 在用户拒绝起床时调用，APScheduler `DateTrigger` 注册一次性 job（不污染主 cron 配置），冲突避免：snooze 时间晚于下次正常 cron 时跳过
- **WS 协议向后兼容**：`text_chunk` / `audio_chunk` / `done` 加 `proactive=true` + `proactive_trigger` 字段，老前端忽略未知字段照常工作；新前端按 trigger 名映射 toast（`🌅 早安简报` / `🌅 早安`）
- **ChatHistory 渲染**：proactive turn 灰字前缀（`🌅（早安简报）` / `🌅（叫早）`）；`profile_summary` 重写白名单 `kinds=['normal']` 自动排除 proactive / touch 行
- **Settings**：[主动陪伴] section 模式三选一 radio + 各模式特定参数（cron / TTL / snooze 默认 / city）+ 🧪 立即测试按钮按当前模式路由

### 🌸 Character Presence (v3-E1 main line done, May 2026)
- 🎭 **Live2D avatar** (Hiyori sample model, Cubism 4) — rendering + idle / focus / breath, Galgame full-bleed layout
- 👄 **Lip sync** — Web Audio AnalyserNode → `ParamMouthOpenY`, shared AudioContext across multi-segment TTS
- 👆 **Touch response** — click avatar → Tap motion + AI proactive reply (special-turn injection)
- 🎬 **LLM-driven motion** — `<motion>X</motion>` tags drive 16 Chinese motion words → 4 Hiyori `Flick*` motion groups (semantics verified live: 放松甩手 / 害羞收敛 / 加油应援 / 撒娇俏皮)
- 😊 **Emotion data pipeline** — `<emotion>X</emotion>` parsed → WS push → store; visual binding deferred to v3-E3 (Hiyori has no `.exp3.json`)
- 🧠 **Inner monologue** — `<thinking>X</thinking>` lets the LLM think without TTS reading it; not persisted
- v2.7 baseline: emotion tag system drives TTS voice variation; static fallback when no Live2D model bound

### 🪟 Interface
- **Dual UI modes** — transparent floating widget + full panel (Tauri 2)
- **Widget ↔ Panel switching** — single-window dynamic resize via Tauri JS API; persisted across launches
- **Settings panel** — 4 sections (Memory / Basic / Character / UI 风格)
- **Mouse click-through for widget mode**

### 🎵 Music & Media (v3-H chunk 1 🟡 PARTIAL, May 2026)
- **网易云音乐数据接入** — 后端 weapi client + 7 capability（日推 / 私人 FM / 搜歌 / 歌单 / 加红心 / 搜索 …），唤起本地 NCM App。**自动播放链路封存待 chunk 2 重做**（orpheus:// URL Scheme 对路由/播放命令支持不完整）；当前作为「数据查询 + 唤起 NCM」使用，最终播放需手动点击。配置走 `.env` 的 `MUSIC_U` cookie，详见 [`docs/netease-music-setup.md`](./docs/netease-music-setup.md)
- **跨来源系统级播控** — `nowplaying-cli` 包装 5 capability：上一首 / 下一首 / 播放暂停 / 当前在播 / 系统音量。不限来源——网易云 / Apple Music / Spotify / YouTube / B 站网页都能控。详见 [`docs/media-control-setup.md`](./docs/media-control-setup.md)

### 👁 Screen Awareness *(v4, planned)*
- **Active mode** — voice command or hotkey triggers screenshot, VLM analyzes
- **Passive mode** — periodic screenshots with pixel-diff pre-filter, VLM only on meaningful change, proactive comment via `screen_comment` push
- **Privacy blocklist** — apps/windows to ignore
- VLM via cloud (GPT-4o / Qwen-VL / Claude) — no local GPU

---

## Architecture

```
User input (voice / text)
  ├─ [VAD mode]  Web Audio API speech detect → MediaRecorder
  │              silence > 1.5s → stop → send audio
  ├─ [Manual]    user click → MediaRecorder start/stop → send
  └─ [Text]      typed and sent

  → ASR        faster-whisper (backend) → asr_result pushed to frontend
  → ChatAgent  context assembly + LiteLLM tool calling
                ├─ memory tools: save / delete / list / compress (LLM-driven)
                ├─ built-in tools: ToolRegistry (MCP-extensible)
                ├─ capabilities: @register_capability auto-injects into ToolRegistry
                │                (v3-G chunk 0; Time + future Calendar / 网易云 / etc)
                └─ web search: model-native (Qwen Max / DeepSeek)
  → emotion    first sentence parses <emotion>X</emotion> → locks turn emotion
  → TTS        get_tts_engine(voice_model) → CosyVoice / Edge / SoVITS
  → Output:    streamed text chunks + per-sentence audio chunks + asr_result preview

Capability Registry (v3-G chunk 0):
  @register_capability decorator → CapabilityRegistry singleton
    ├─ Consumer.CHAT_AGENT  → auto-derived OpenAI schema → ToolRegistry → ChatAgent
    ├─ Consumer.SCHEDULER   → APScheduler cron / interval triggers
    └─ Consumer.WEBHOOK     → /api/webhooks/n8n/{trigger} (Bearer + HMAC auth)
  GET /api/capabilities → frontend CapabilityPanel (cards by category, health dots)

Two-layer integrations (v3-G chunk 1):
  backend/integrations/<service>.py     low-level client (OAuth, retry, health)
  backend/capabilities/<service>.py     5-line @register_capability per action
  First service wired in: Google Calendar (today_events + upcoming_events)
  Morning briefing cron @ 09:00 → template v0.1 → ConnectionManager.push notify + Momo wav

Bidirectional MCP (v3-G chunk 1.5):
  ┌─────────────────────────────────────────────────────────────────┐
  │  CapabilityRegistry  ←  decorator  | runtime  | aggregator      │
  │                                                                 │
  │  Source 1: @register_capability    (built-in: time / calendar) │
  │  Source 2: register_runtime        (external MCP → ext.*.*)    │
  │  Source 3: list_for_consumer       (CHAT_AGENT subset to expose)│
  └──────┬──────────────────┬─────────────────────────┬─────────────┘
         │                  │                         │
         ▼                  ▼                         ▼
  Internal ChatAgent   APScheduler / Webhook    POST /mcp (Bearer)
  (LiteLLM tools)      (cron / event-driven)    Claude Desktop / Cursor
                                                 ↑
                                                 │ (also: Skyler-as-client)
                                                 │ stdio_client / streamablehttp_client
                                                 │ → reverse-register external tools
                                                 │   as ext.<server>.<tool>
  Per-capability `metadata.expose_via_server` controls whether external
  MCP servers' tools get re-exposed via Skyler's own /mcp.

VAD state machine:
  sleep ─ click ─→ active ─ speech ─→ recording ─ silence 1.5s ─→ send → active
  active ─ 60s idle ─→ sleep

Backend → Frontend (proactive):
  Alarm / task complete / event / screen comment
    → ConnectionManager.push() → WebSocket → frontend toast/notify
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 18 + Vite + TypeScript + Zustand + Tailwind CSS v3.4 |
| Icons | lucide-react |
| Theming | CSS variables (8 themes in `styles/themes.css`) |
| Desktop shell | Tauri 2 (transparent window, always-on-top, click-through, custom drag region) |
| Backend | FastAPI + WebSocket (async streaming) + SQLAlchemy async (aiosqlite) |
| LLM | LiteLLM — DashScope (Qwen) / DeepSeek / OpenAI / Claude (config switchable) |
| TTS | CosyVoice v3-flash (default) / Edge-TTS (fallback) / SoVITS (placeholder) |
| ASR | faster-whisper (local, CPU/GPU) |
| Memory | SQLite + sentence-transformers (local vector search, no GPU) |
| VLM *(v4)* | OpenAI / Qwen-VL / Claude vision API (cloud) |
| Tool protocol | MCP (Model Context Protocol) |

**Cross-platform note**: currently macOS-only. Windows support deferred to v6+ — see [DESIGN.md §Cross-Platform Strategy](DESIGN.md) for why this is harder than it looks.

---

## Getting Started

### Prerequisites (macOS)

| Tool | Min version | Install |
|---|---|---|
| Node.js | 18+ (recommend 22+) | `brew install node` |
| Rust toolchain | 1.75+ | `curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \| sh` |
| Xcode Command Line Tools | latest | `xcode-select --install` |
| Python | 3.10+ | `brew install python@3.10` |

### Setup

```bash
git clone <your-repo-url> Skyler
cd Skyler

# ── Backend ───────────────────────────────────────────
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env — at minimum:
#   DASHSCOPE_API_KEY=sk-xxx
#   DATABASE_URL=sqlite+aiosqlite:///./skyler.db

uvicorn backend.main:app --reload
# Backend at http://127.0.0.1:8000

# ── Frontend (in another terminal) ────────────────────
cd frontend
npm install
npm run tauri dev
# First Rust build takes 5–15 min; subsequent starts are fast.
```

A transparent floating Widget appears. Click ⚙ to open the full Panel.

---

## Live2D Asset Management

Skyler ships with the Live2D official free sample model **Hiyori** as the
default avatar. To add another character, follow these four steps:

1. **Drop assets into `frontend/public/live2d/<slug>/`** — pick a lowercase
   ASCII slug (`yae-miko`, `momo-v2`, etc.). The slug is what you'll later
   write into `characters.live2d_model` from the CharacterPanel UI.
2. **Make sure the directory has a `*.model3.json` entry file** plus a
   `*.moc3`, `textures/`, and at least one motion. See
   [`frontend/public/live2d/README.md`](frontend/public/live2d/README.md)
   for the full integrity checklist.
3. **Validate the moc3 version** before wiring it up:
   ```bash
   python -m tools.check_moc3_version frontend/public/live2d/<slug>/
   ```
   pixi-live2d-display does not support Cubism 5; the script exits non-zero
   if any `.moc3` is too new or if a Cubism 2 `.moc` slips in.
4. **Bind in CharacterPanel** — open the character editor, set the
   `live2d_model` field to your slug. Reload the conversation and the new
   model takes over.

**IP / license isolation** — by default `.gitignore` excludes every
subdirectory under `frontend/public/live2d/` except `hiyori/`. Third-party
or commissioned models you drop in will not be tracked or pushed; this is
intentional, since Skyler's project license cannot cover assets you don't
own. To whitelist a self-made or properly-licensed model into git, append
`!frontend/public/live2d/<slug>/` to `.gitignore`.

**Disclaimer** — Skyler's own code is MIT-licensed, but it makes no
guarantees about any Live2D model assets you add. Sourcing, licensing,
and distribution rights for those assets are entirely the user's
responsibility.

### Walkthrough: adding 八重神子 (Yae Miko) from a BCSZ1.1 dump

Concrete example — a Cubism 4 八重神子 model lives at
`<some-path>/BCSZ1.1/`. Skyler's character with id=2 is already named
"八重神子" and has its `motion_map_json` / `hit_area_map_json` populated
by the `v3_e2_yae_maps` migration. To make her render:

```bash
# Option A: copy assets into the slug dir
cp -r "<some-path>/BCSZ1.1" frontend/public/live2d/yae

# Option B: symlink (saves disk, easier to update)
ln -s "<some-path>/BCSZ1.1" frontend/public/live2d/yae
```

Either way, `frontend/public/live2d/yae/` is gitignored — assets stay
local, the database migration that points character id=2 at slug `yae`
is what's tracked. Validate then refresh the UI:

```bash
python -m tools.check_moc3_version frontend/public/live2d/yae/
# Expected: [OK] version=3 (Cubism SDK 4.0)
```

Open the CharacterPanel, switch to 八重神子, and the avatar swaps to
BCSZ1.1. Click the model and Skyler plays the `Start` motion (Yae's
intro voice line) instead of Hiyori's `Tap` random pick — that's the
per-character `motion_map_json` taking effect.

> **Heads-up — motion-bundled sound is muted globally.** A model's
> `motion3.json` may reference WAV files (BCSZ1.1 ships with six voiced
> motions, for example). Skyler routes all spoken output through its
> LLM + TTS pipeline, so the auto-played motion WAVs would collide with
> TTS output. They're disabled at the SDK config level. A future
> per-character toggle is on the roadmap (so e.g. tap-triggered motions
> can keep the original voice line while LLM-driven ones stay quiet).

---

## Roadmap

See [**ROADMAP.md**](ROADMAP.md) for the full prioritized roadmap.

**TL;DR — the next moves:**

- **v3 finish (Tier 1, 1–3 weeks)**:
  - ✅ **v3-E1 done** (8 commits + Step Z cleanup): Hiyori Live2D — rendering, idle, touch Tap, lip sync, emotion pipeline, LLM-driven motion
  - ✅ **v3-E2 done** (9 commits): runtime abstraction, per-character `*_map_json`, asset scanner API + dropdown, Yae Miko (BCSZ1.1) wired in, emotion visual binding code path live, Momo persona restored
  - **v3-E3**: pure operational task — find a model with `.exp3.json`, fill that character's `emotion_map_json`, art-tune
  - **v3-F'**: proactive dialogue + time awareness (mealtime / bedtime / long idle triggers)
  - ✅ **v3-G' done** (5 commits + 2 patches): per-character voice picker (provider → voice two-level dropdown), seven CosyVoice voices catalogued (incl. instruct-aware male `longanyang`), real emotion control via SDK `instruction` field on instruct-supported voices. The chunk-1a SSML approach turned out to be wrong — DashScope SSML has no `emotion` attribute, so it was reverted in favor of the natural-language instruct path that's been in place since v3-D. Patch (c) further locked the instruction string to the documented strict format (`"你说话的情感是{emotion}。"` — no whitespace) after a `InvalidParameter 428` audit. Phase 2 (custom voice cloning + GPT-SoVITS training) remains pending until reference samples / autodl GPU are ready.
- **v3-G + v4 (Tier 2, 1–2 months)**: clipboard assistant, daily briefing, natural-language cron, character status panel + growth system; screen awareness (active + passive + VLM); AI inner browser
- **v5 (Tier 3, long-term)**:
  - **v5-D**: autodl deployment + sub-agent isolation
  - **v5-T1**: GPT-SoVITS backend (real `SoVITSProvider` impl, multi-emotion ref-audio routing)
  - **v5-T2**: train custom voices (CosyVoice fine-tune + GPT-SoVITS character-specific models)
- **v6+**: multi-device access (Windows client), Hermes-style skill accumulation

---

## ⚠️ Known Problems / 已知问题

按优先级排列。日常运行不阻塞，但未来需要处理。详细 backlog 散落条目散见 [ROADMAP.md §Tech Debt & Backlog](ROADMAP.md#tech-debt--backlog) / [DESIGN.md §十四之B](DESIGN.md)；本块是 manual 验收期间发现的活跃 issue 汇总。

### 中

1. **7 个 pre-existing test failures**（2026-05-11 chunk 6b hotfix-2 audit 发现）
   - 文件：`test_chat_agent` / `test_database` / `test_integration` / `test_llm_client` / `test_memory_agent` / `test_memory` / `test_ws_helpers`
   - 根因：chunk 0–4 累积过程中漏维护，引用已删/改名 API（`upsert_personality` / `DEFAULT_MODEL` / `_personality_to_dict` / `_run_plan`）
   - 影响：每次 hotfix 的 "0 regression" 声明带 false positive（实际新代码 0 regression，但旧测试仍红）
   - 修法：扫 7 文件改成当前 API / 删过时测试
   - 工程量：1–2 小时

2. ~~**`_build_messages` 性能退化 1000x**~~ ✅ chunk 9 Part 0 已优化（2026-05-12）
   - 旧现象：chunk 1.6 → v3-H chunk 1 首条消息 4ms → 4487ms
   - 真根因：embedding 模型 preload 未完成时 lazy load 阻塞首条消息（10s）；不是 per-turn 退化
   - chunk 9 Part 0 渐进优化（3 项零风险）：
     - 短输入（< 10 chars）跳过 memory 检索：~67ms → 0.47ms（**~140x**）
     - embedding LRU + TTL 缓存：~67ms → 0.01ms（**~6700x**，cache hit）
     - device=auto → cpu（mps 与 cpu 短文本 median 相同但 cpu 更稳）
   - 残留风险：模型 preload 未完时首条消息仍 lazy load（10s）—— chunk 10 / backlog "preload-gate 或 not-ready 跳过"

### 低

3. **网易云 mpv 真播降级 url_scheme**（2026-05-11 chunk 6b hotfix-3 验收发现）
   - 现象：NCM 客户端弹出 + 显示歌名，用户手动点播放（理想是 mpv 后台真播）
   - 根因：chunk 6b hotfix-2 自实现的 `NeteaseClient.get_song_url` weapi 签名错，所有歌返回 `{"msg":"参数错误","code":400}`
   - 影响：用户体验降一档；功能可用（Momo 引导用户手动点）
   - 修法：用 `pyncm` 库重写 `get_song_url`
   - 阻塞：`pyncm` 在用户环境安装失败（PyPI / 镜像在 Python ssl 路径被截断，疑代理 TUN 劫持）—— 长期 backlog
   - 工程量：2–3 小时（若 `pyncm` 解决）

4. **MCP 凭证 V1 plaintext 存 SQLite**（v3.5 chunk 7 衍生 backlog）
   - 现状：`mcp_credentials` 表明文存 API key；与 `.env` 风险等价（SQLite 文件在 `~/.skyler/` 已具系统级权限隔离）
   - 升级路径：接 OS keyring（macOS Keychain / Windows Credential Manager / GNOME Keyring）或 master password 派生加密
   - Touchpoint：`backend/mcp/credentials.py` `get_env` / `upsert` 内部加 cipher layer，外部 API 不变

5. **`config.yaml` 双写源**（v3.5 chunk 7 audit 发现）
   - 前端 SettingsPanel 通过 `setConfigField` 写 `config.yaml`（`tts.enabled` / `memory.long_term_enabled` / `search.enable_search` 等），git HEAD 不感知 → 用户改 settings 后 `git status` 显示 dirty
   - 修法：拆静态配置（git 版本控制）vs 运行时设置（DB 表存，参照 chunk 7 `mcp_client_state` pattern）
   - 与第 6 条同性质，建议 v4 一起整改

6. **`characters.yaml` vs DB 双源真相**（v3-E1 留 v4 Scheme C 修）
   - 当前 Scheme B（DB 主 + YAML fallback）—— `_build_messages` 优先 DB persona，YAML fallback
   - 计划 Scheme C（v3-G 末或 v4）：删 yaml、DB 单源、迁移脚本、`switch_character` 改 DB query、`prompt_manager` 改 DB-backed

7. **超长 B 站字幕分段总结**（v3.5 chunk 6a 衍生 backlog）
   - 现状：`bilibili.get_subtitles` 返完整字幕全文不截断
   - MVP 接受：qwen3.6-plus / claude / deepseek 都 200k+ context；B 站常见 5–30 分钟视频字幕 1–3k 字够安全
   - 升级路径：滑动窗口分段 → 各段单独总结 → 终极合并总结（map-reduce 风格）
   - Touchpoint：`backend/integrations/bilibili.py` `get_subtitles` 末尾加 `_segment_and_summarize` 可选 wrapper

8. **cosyvoice WS 建链 5s 超时**（v3-G' 衍生 backlog）
   - 现状：dashscope SDK 默认 5s WebSocket 建链超时（`speech_synthesizer.py:526` 写死 `self.__connect(5)`，无外部参数化入口）
   - 影响：弱网 / 跨境 / VPN 抖动场景下经常 `TimeoutError`，单句 TTS 直接失败
   - 修法（择一）：（A）生产侧 monkeypatch（hack 痕迹）/（B）`_blocking_synthesize` 退避重试 / （C）升级 dashscope SDK 看上游是否暴露 timeout 参数 / （D）迁 SDK 的 streaming_call + 自管连接池

9. **Python 3.10 + `google-api-core` 兼容窗口**
   - `google-api-core` 已宣布 2026-10-04 起停止支持 Python 3.10
   - 影响：到期前 Google Calendar 集成依赖会卡在旧版本，安全补丁停摆
   - 修法：升级到 Python 3.11+（`pyproject.toml` / setup guide / CI 同步）

10. **剪贴板内容写入 log（隐私）**（chunk 3a 起）
    - 现状：clipboard watcher 调试日志会带 content preview；生产环境若 log 级别开 INFO 可能记录剪贴板敏感内容（密码 / token 等）
    - 修法：watcher / capabilities 内部 log 改成 hash / length / type，content 仅 DEBUG 级（默认 WARNING+ 不记）

11. **`users.profile_summary` legacy 字段未来清理**（v3.5 chunk 11 衍生 backlog）
    - 现状：chunk 11 引入结构化 `profile_data` JSON 字段，但 `profile_summary`（chunk 9 自然语言段）**保留作 fallback**（向后兼容 + 用户主动迁移期）
    - 现行注入优先级：`profile_data` 非空 → 模板化注入；NULL → fallback 到 `profile_summary`
    - 修法：N 个版本后（用户 profile_data 全部填充）→ 删 column / 删 legacy 写库路径 / 删 chunk 9 `/profile_summary/*` endpoints（已加 deprecation log）
    - 工程量：1 个 migration（DROP COLUMN）+ 3 个 endpoint 删除 + chunk 9 路径清理；< 1 小时

12. **MemoryExtractor worker 调参 backlog**（v3.5 chunk 10 衍生）
    - 现状：worker 默认 ``interval_seconds: 300`` / ``batch_size: 50`` / ``min_confidence: 0.5`` / ``dup_threshold: 0.9`` —— 全是初始猜测值，未跑长跑数据
    - 待观察：
      - interval 5 分钟在重度使用日是否过密（一天 ~288 次 qwen-turbo 调用 ≈ ¥3-5/天，量级可接受但有省空间）
      - min_confidence=0.5 偏松还是偏紧：实测样本中 LLM 自评 0.8-0.9 居多，0.5 主要拦截"硬猜测"。如果发现漏召回，调到 0.4；如发现噪音多，调到 0.6
      - dup_threshold=0.9 vs 0.85：cosine 0.85 已经语义近似，可能更保守
    - 修法：跑一周后回看 ``extraction_source='worker'`` 的入库率 + 用户在 drawer 手动删除率，迭代默认值

13. **MemoryExtractor LLM judge 默认开关**（v3.5 chunk 10 衍生）
    - 现状：``llm_judge_enabled: false``——第 5 道 filter（再调一次 qwen-turbo 问"这条值不值得记 YES/NO"）默认关
    - 理由：上线时不知道前 4 道闸（schema + 长度 + SUSPICIOUS + confidence + dup）已经能挡多少噪音，先不开避免成本翻倍
    - 待观察：若 drawer 里出现"明明 confidence 0.9 但人类一看就没价值"的 entry 多了，开开看
    - 修法：set ``memory.extractor.llm_judge_enabled: true`` 即激活（fail-open，judge 抛错时 accept）

14. **chunk 8b 完整屏幕感知留 backlog**（v3.5 chunk 8a 衍生）
    - 现状：chunk 8a 只做"看得到 app 名 + 浏览器 URL + 公开页面正文"。**不**截屏 / **不** OCR / **不**装浏览器扩展
    - 缺失场景：能感知到 Chrome 在啥 tab，但看不到代码编辑器里到底在写什么；YouTube 视频只能拿 URL + 标题，不能"看到画面"
    - 修法（chunk 8b）：Tauri Rust 端 ``CGDisplayCreateImage`` + 像素差预过滤 + VLM provider 抽象（Qwen-VL-Plus 主选）；同时浏览器扩展拿 DOM 而非 URL（绕开 Tauri webview 限制）
    - 工程量：2-3 天 / 8-10 commits，单独 session

15. **Windows / Linux 平台 activity_monitor 不可用**（v3.5 chunk 8a 衍生）
    - 现状：activity_monitor 全函数返 None；ActivityWatcher 仍然跑（不抛错），但 listener 拿不到任何 change → smart trigger 永远 skip
    - 跨平台一致性：与 v3 阶段 macOS-only 整体策略一致（[DESIGN §二十](DESIGN.md)）
    - 修法：Windows 用 win32gui ``GetForegroundWindow`` + UIA / Chrome DevTools Protocol 拉 URL；Linux X11 ``_NET_ACTIVE_WINDOW`` + 浏览器扩展。两边都是单独工程，留 v6+ Windows 客户端阶段处理

> ~~**用户画像污染**~~（"温柔陪伴 / 亲密关系 / 细腻敏感" 等反推词写入 profile_summary）✅ chunk 11 治本（2026-05-12）—— LLM 输出严格按 JSON schema，validator hard-reject 违规输出，注入用机械模板而非 LLM。
>
> ~~**LLM hallucinate save_memory**~~（chunk 9 跨角色共享后放大）✅ chunk 10 治本（2026-05-12）—— memory 入库主路径改成 server-side worker（每 5 分钟 batch 提取 + 10 道 filter），``save_memory`` tool 降级为"用户明确说要记"的显式入口；entry 上打 ``extraction_source`` 区分来源，MemoryManagerDrawer UI 角标可见。
>
> ~~**MCP Settings 一条 capability 一行 → 列表过长**~~ ✅ UX-001 治本（2026-05-12）—— ``ExtensionsSection`` 改 accordion，每 server 默认折叠成单行（含 ``X/Y cap`` 角标）；展开后看 capability 列表 + 单 cap toggle。新增 ``mcp_tool_state`` 表 + ``PUT /api/mcp/clients/{name}/tools/{tool}/enabled`` 路由持久化 per-tool override；server 关时所有 tool toggle 自动 disable 不需要清表（``_connect_one`` 时根据 override skip register 即可）。
>
> ~~**情绪 UI 被 TopBar 挡**~~ ✅ UX-001 治本（2026-05-12）—— Panel 模式 ``CharacterStatePanel`` ``top: 12px`` 落在 TopBar (h-10 / z-50) 的 0-40px 范围内被压住。改 ``top: 48px`` 让状态条整体放到 TopBar 下方右侧，z-index 维持 30（不需要浮到 TopBar 之上盖 CharacterSwitcher dropdown）。

---

## Inspirations

Skyler is built on lessons from two projects:

### [Open-LLM-VTuber](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber)
The avatar/companion UX reference. Borrowed concepts:
- Voice interrupt (stop generating tokens immediately on user speech)
- TTS multi-segment concurrent synthesis with first-sentence priority
- TTS preprocessor (strip `*action*` / `(notes)` from spoken output)
- Vision capability (camera + screen share + AI-driven browser)
- AI proactive speaking + visible inner monologue (`thinking` tag)
- Live2D touch response
- motionMap (motion synced with speech)
- MCP protocol integration
- Letta long-term memory option *(considered, not adopted — local SQLite + embeddings already sufficient)*
- Multi-device access (deferred — see Cross-Platform Strategy)
- *Not adopted: group chat, Bilibili Danmaku livestream client (incompatible with single-companion Galgame focus)*

### [Hermes Agent](https://github.com/NousResearch/hermes-agent) by Nous Research
The life & tools agent reference. Borrowed concepts:
- Self-improving skill loop (skills accumulate from experience, refine in use)
- Natural-language cron scheduling (extends Skyler's existing alarm system to general task scheduling)
- Sub-agent isolation (long tasks run in separate context, don't block main conversation)
- Multiple execution backends (local / Docker / SSH / Modal-style serverless) — relevant for autodl deployment
- Persona editor (`SOUL.md`-style) — already partially covered by `characters.persona`
- *Not adopted: messaging gateways (Telegram/Discord/etc) — Skyler is a desktop app, not a remote agent*

---

## Project Status

| Component | State |
|---|---|
| Backend (FastAPI + agents + memory + TTS + ASR) | ✅ v2.7 complete |
| Frontend (Tauri + React + 8 themes + Galgame UI) | ✅ v2.7 complete |
| v3-A: 8-theme system + lucide-react | ✅ done |
| v3-B: `character.voice_model` + CosyVoice | ✅ done |
| v3-C: PlannerAgent simplification | ✅ done |
| v3-D: emotion system | ✅ done (frontend pipeline wired in v3-E1 Step 5; visual binding deferred to v3-E3) |
| v3-E1: Live2D integration via Hiyori | ✅ done (8 commits + Step Z cleanup, May 2026) |
| v3-E2: multi-model Live2D (runtime abstraction + per-character maps + Yae Miko BCSZ1.1) | ✅ done (9 commits, May 2026-05-06) |
| v3-E3: emotion visual binding | 🚧 code path live; needs a model with `.exp3.json` |
| v3-F: voice UX (interrupt + concurrency + preprocessor + thinking) | ✅ done |
| v3-F': proactive dialogue + time awareness | ✅ done (2026-05-08) — engine + 哲学 (chunk 2/2.6) + 5 trigger pack (chunk 4): wake_call / lunch_call / dinner_call / bedtime_chat / long_idle, all via 模式 B 邀请对话 (cron → 8-15 字 → 用户回应 → ChatAgent 自适应) |
| v3-G: life & tools layer (clipboard / daily briefing / cron / growth) | ✅ done (chunks 0–4, 2026-05-08) — see full chunk breakdown below |
| v3-G': TTS UI + cosyvoice instruct emotion | ✅ done (5 commits + 2 patches, 2026-05-06) — SSML reverted, instruct path canonical, instruction string locked to strict no-whitespace format, longanyang male voice added; Phase 2 (custom voice cloning) 📋 pending |
| v3-G chunk 0: Capability Registry + cron + n8n webhook receiver | ✅ done (3 commits, 2026-05-06) — `@register_capability` is the canonical registration for all future tools; CapabilityPanel renders categorized cards in settings; APScheduler cron runs alongside the existing alarm scheduler; `/api/webhooks/n8n/{trigger_name}` accepts external workflow triggers behind Bearer + HMAC auth |
| v3-G chunk 1: Google Calendar + morning briefing v0.1 | ✅ done (3 commits, 2026-05-07) — `backend/integrations/` (low-level client) and `backend/capabilities/` (decorator layer) split established; Google Calendar OAuth desktop flow with auto-refresh + tenacity retry + health check that degrades to warn on transient network errors (China-friendly); two calendar capabilities (today / upcoming) auto-injected into ChatAgent tools; CapabilityPanel calendar cards expose [Connect Google] / [Re-authorize] buttons; morning briefing cron at 09:00 (template v0.1, ChatAgent intelligence in chunk 2); `[🧪 测试今日简报]` test button in panel; setup guide in `docs/google-calendar-setup.md` |
| v3-G chunk 1.5: Bidirectional MCP integration | ✅ done (3 commits, 2026-05-07) — Skyler exposes CapabilityRegistry as a streamable HTTP MCP server (`POST /mcp` with Bearer auth), so Claude Desktop / Cursor / Claude Code can call `time.now`, `calendar.*`, etc.; Skyler also acts as an MCP client connecting to external servers (e.g. Anthropic's filesystem / brave-search) via stdio or HTTP, reverse-registering their tools as `ext.<server>.<tool>` capabilities that ChatAgent picks up automatically; per-server `expose_via_skyler_server` toggle prevents API-quota leakage; CapabilityRegistry now supports both decorator-time and runtime registration with shared `metadata` field; setup guides in `docs/mcp-{server,client}-setup.md` |
| v3-G chunk 1.6: Apple Calendar + dual-source routing | ✅ done (2 commits, 2026-05-07) — `backend/integrations/apple_calendar.py` wraps macOS EventKit via pyobjc (zero network, no VPN — works in mainland China); four capabilities (`apple_calendar.today_events / upcoming_events / create_event / delete_event`); `backend/capabilities/calendar.py` is now a **router** that dispatches `calendar.today_events / upcoming_events` to Apple or Google by `config.yaml.calendar.default_source`; chunk 1's old direct Google caps renamed to `google_calendar.*` and demoted to SCHEDULER-only (panel-visible, LLM-hidden) to keep tool surface clean; Apple is default; setup guide in `docs/apple-calendar-setup.md`; the `create_event` capability is wired up as the entry point for chunk 2.5 NL event entry ("提醒我明天 10 点看牙医") |
| v3-G chunk 1.7: model picker UI | ✅ done (2026-05-07) — Settings → Model section with two-tier dropdown (provider → model), `/api/settings/model` for runtime switching, available_models list configurable via `config.yaml` |
| v3-G chunk 2 + 2.5: smart morning briefing + NL event entry | ✅ done (2026-05-08) — generic `ProactiveTrigger` ABC + `run_trigger` engine (`trigger → aggregate → ChatAgent → WS push`), MorningBriefingTrigger as first concrete impl (200-300 chars, weather + calendar + todos + closing question), full streaming TTS / Live2D / emotion pipeline reused; `_TOOL_PROMPT_ADDENDUM` adds NL event entry guidance ("提醒我明天 10 点 X") |
| v3-G chunk 2.6: wake_call mode B (邀请对话) | ✅ done (2026-05-08) — second proactive trigger pattern: cron → 8-15 char short greeting (with `skip_short_term` to avoid history tone bleed) → user reply → ChatAgent stage 2 with auto-injected addendum (4 user-style branches: vague / curious / refuse / topic-switch); `pending_briefings` table for cross-process state; snooze capability with APScheduler `DateTrigger` one-shot + cron-conflict avoidance; `proactive.mode` mutex |
| v3-G chunk 3: clipboard helper + character state + intimacy growth | ✅ done (2026-05-08) — chunk 3a: `ClipboardWatcher` singleton (NSPasteboard 1Hz polling on macOS, pyperclip cross-platform fallback) + 3 CHAT_AGENT capabilities (get_recent / summarize / translate), ringbuffer 50 items / 24h TTL, **never persisted to SQLite** (privacy); chunk 3b: `character_states` table with mood (7-enum) / intimacy (0-100) / current_thought / current_activity, `<state_update>` LLM tag protocol parallel to `<emotion>`, daily intimacy_decay cron, frontend `CharacterStatePanel` floating widget |
| v3-G chunk 4: v3 closeout pack | ✅ done (2026-05-08) — Part A: **tool_call_resilience** layer (catches Qwen XML / Anthropic invoke / markdown JSON fallbacks at end of turn; chunk 2.6 footgun 4 + chunk 3 footgun 7 真解); Part B: clipboard `set_enabled` REST + frontend toggle wiring; Part C: 4 new v3-F' triggers (lunch_call / dinner_call / bedtime_chat / long_idle) reusing the chunk 2.6 invite-conversation pattern + heartbeat hook; Part D: 3 small cleanups (cosyvoice comment audit confirmed clean; Hiyori StrictMode warning identified as cosmetic library behavior; legacy chat_history tag scrub migration) |
| v3-H chunk 1: 网易云 + macOS media control | ✅ done (2026-05-08) — `backend/integrations/netease_music.py` (weapi encryption + cookie auth) + 7 capabilities (`netease.daily_recommend` / personal_fm / play_song / play_playlist / play_playlist_by_id / like_current / search) + macOS media control (5 capabilities via `nowplaying-cli`: next/previous/play_pause/now_playing/set_volume); cross-source: works with NCM / Apple Music / Spotify / YouTube / Bilibili / etc. |
| v3.5 chunk 5: visual upgrade (per-character background layer + Tauri splash video) | ✅ done (2026-05-11) — 5a `characters.background_path` TEXT NULL + `GET /api/backgrounds` scanner (parallels `live2d_scanner` with `.absolute()` symlink discipline) + `CharacterView` background-layer dispatch (image/video by suffix, Live2D z-10 in front) + `CharacterPanel` dropdown with 120×80 preview; 5b `SplashOverlay` component (localStorage gate → fetch HEAD probe → fullscreen `<video>` → click/key/onEnded/onError fade 300ms, silent skip when missing) + `SettingsPanel [启动]` toggle (`momoos.splashEnabled` localStorage); 38 new tests / 0 regressions; IP isolation via `.gitignore` `frontend/public/{backgrounds,splash}/*` whitelist pattern (reuses `live2d/` recipe) |
| v3.5 chunk 6a: Bilibili integration (11 capabilities + AI subtitle summarization) | ✅ done (2026-05-11) — `bilibili-api-python>=17.4` (Nemo2011 community fork) wrapped in `backend/integrations/bilibili.py` (11 methods + 3-tier health check + risk-control code mapping) + `backend/capabilities/bilibili.py` (11 `@register_capability` decorators with chunk-1.7 verbatim guidance); 6 no-cookie (`search_video`/`get_video_info`/`search_user`/`get_user_videos`/`hot_videos`/`get_ranking`) + 5 cookie-required (`get_subtitles` ⭐ killer use case + `get_my_history`/`get_my_followings`/`get_later_watch`/`get_favorites`); cookie via `.env` `BILIBILI_SESSDATA` (same pattern as netease `MUSIC_U`); subtitle picker prioritizes AI subs → manual zh → none fallback; risk-control codes (-352/-412/etc.) mapped to friendly error keys; 104 new tests / 0 regression across 22 suites (704/704) — see `docs/bilibili-setup.md` |
| v3.5 chunk 6b: netease mpv self-decoder (6 `local_*` capabilities) | ✅ done (2026-05-11) — `NeteaseClient.get_song_url` (new, weapi POST `/song/enhance/player/url/v1`) + `backend/integrations/mpv_player.py` subprocess+Unix-socket JSON IPC wrapper (not python-mpv ctypes — avoids libmpv shared-lib deployment) + 6 `netease.local_play_song`/`local_play_playlist`/`local_pause`/`local_resume`/`local_stop`/`local_next_in_queue` capabilities; MediaRemote upgrade vs spec — mpv 0.34+ natively registers macOS NowPlayingCenter with `--media-keys=yes`, no PyObjC bridge needed (saves ~200 LOC + no entitlement); VIP trial 30s segments transparently flag `is_trial=True`; coexists with chunk 1 `netease.play_song(keyword)` URL Scheme path via `local_*` namespace; 56 new tests (mpv 23 + netease_playback 33) — see `docs/netease-playback-setup.md` |
| v3.5 chunk 6c: xiaohongshu passive URL parser (red line locked in code) | ✅ done (2026-05-11) — single `xhs.parse_url` capability, `backend/integrations/xiaohongshu.py` exposes **zero** proactive scraping methods (no `search`/`recommend`/`fetch_homepage`/`list_followings` — red line enforced at module level, not just policy); domain whitelist (xiaohongshu.com / xhslink.com), follow_redirects for short links, browser UA + Referer disguise; data source priority: `window.__INITIAL_STATE__` JSON (with `undefined→null` fix + last-`}` fallback + 3 candidate paths) → og:meta fallback → `parse_failed`; antibot detection (412/418/403 → `blocked_by_antibot` + "wait minutes" hint); system prompt instructs LLM to refuse "搜小红书" requests honestly without fabricating; 52 new tests (including 4 red-line enforcement assertions) — see `docs/xiaohongshu-setup.md` |
| v3.5 chunk 7: skill integration demo (docx capability stance A + Notion MCP server stance B) | ✅ done (2026-05-11) — stance A: `python-docx` + 3 capabilities (`docx.create`/`read`/`append`) + `backend/utils/safe_path.py` central `safe_resolve` + `ensure_sandbox_dir`, sandbox at `~/Documents/Skyler/docs/`; stance B: `backend/mcp/credentials.py` + `mcp_credentials` / `mcp_client_state` migration tables + extended `backend/mcp/client.py` (enable/disable + DB env injection + `missing_credentials` in status) + extended `backend/routes/mcp_api.py` (PUT/GET credentials, PUT enabled with pre-check) + `ExtensionsSection.tsx` UI section in SettingsPanel; `@notionhq/notion-mcp-server` (official package, makenotion/notion-mcp-server) added to `config.yaml mcp_clients`; 65 new tests / 0 regression across 16 suites (556/556) — see `docs/skills-extension-guide.md` for adding new skills |
| v3.5 chunk 9: memory perf + 遗忘曲线 + 跨角色共享 | ✅ done (7 commits, 2026-05-12) — Part 0 `_build_messages` 性能三项零风险 (短输入门 < 10 chars 跳 memory 检索, embedding LRU+TTL cache size 100/TTL 300s, `device: auto` → cpu); Part 1 检索去 `character_id` 隔离 + UI 角标"由 X 记"; Part 2 `profile_summary` 输入改只读 user (断 LLM 自循环) + SettingsPanel 用户画像 section + 3 endpoints (PATCH/DELETE/regenerate); Part 3 遗忘曲线 — `access_count` + `last_accessed_at` 列, `score = relevance * (1+log(1+ac)) / (1+age*decay)`, threshold gate 0.3 不进 top-k (entry 不删), config `memory.forgetting_curve.{enabled,threshold,age_decay_factor}` 全 hot-readable; 召回 entries 异步 bump access counter best-effort |
| v3.5 chunk 10: server-side memory worker（治本 LLM hallucinate save_memory） | ✅ done (8 commits, 2026-05-12) — memory entry 入库从 LLM tool 主路径改成 server-side worker 主路径; `backend/memory/extractor.py` MemoryExtractor singleton asyncio task (lifespan 拉起/关停, `config.memory.extractor.enabled=false` 整段静默跳过); 每 `interval_seconds` (默认 300s) 跑一轮: fetch `chat_history` after `last_processed_turn_id` → qwen-turbo + JSON list 契约 prompt (14 反推词清单主动避开 + 第三人称约束) → 10 道 filter (schema/type/长度 5-200/SUSPICIOUS/min_confidence/cosine dup/intra-batch dedup/optional llm_judge/反推词 soft warn) → INSERT memory + `extraction_source='worker'` + `source_turn_id` + `confidence` + `entry_type` (fact/preference/event/commitment) + legacy type mapping; `save_memory` tool 降级 (description 收紧到"请记住/以后/别忘了/你要记住", 内部复用 worker 同 filter, 打 `extraction_source='llm_save_memory'`); MemoryManagerDrawer entry_type tab + extraction_source 角标 ("自动提取/你说要记/手动/旧") + confidence 显示; 59 new tests / 0 regression on chunk 9/11/hotfix-3-4 |
| v3.5 chunk 11: structured `profile_data` (治本用户画像污染) | ✅ done (8 commits, 2026-05-12) — `users.profile_data` JSON 字段 + JSON schema (`profession` / `current_projects[]` / `communication_style` / `interests[]` / `language_preferences` / `active_hours` / `recurring_topics[]`); `backend/utils/profile_validator.py` (JSON parse + schema + SUSPICIOUS_TAG + 14 反推词清单 hard reject); `_regenerate_profile_data` 4 模式 (manual_reset / conversation_del / cron_daily / first_seed) 严格 JSON prompt; APScheduler cron `profile_daily_regenerate` 取代 v2.7 50-turn 计数器; `format_profile_for_prompt` 模板化注入 (`_build_messages` 优先 profile_data, NULL → fallback `profile_summary`); 4 endpoints `/profile_data` (GET/PATCH/DELETE/regenerate); SettingsPanel 用户档案 section 重构 (字段级编辑 + [重新生成]/[清空] 双按钮); `profile_summary` 列保留作 fallback (Known Problems #11 长期清理 backlog) |
| v3.5 chunk 8a: simplified activity awareness (active app + browser URL + smart trigger) | ✅ done (9 commits, 2026-05-12) — `backend/integrations/activity_monitor.py` (NSWorkspace 直查 frontmost + `osascript` Chrome/Safari/Word/Pages, timeout 2s + silent None on failure, 跨平台 graceful) + `url_fetcher.py` (httpx 5s GET + 1MB cap + readability-lxml 提正文 + 默认 19 条 blocklist 含银行/邮箱/社交/localhost) + `activity_watcher.py` (asyncio task 30s polling + 5 类 ActivityChange: app/url/doc/focus_long/dwell_long + change listener + URL 内容 best-effort 抓) + `backend/proactive/triggers/activity.py` ActivityProactiveTrigger (5 label: ide_open/music/long_focus/url_tech_doc/late_night_ide, 40-80 字短句风格) + `activity_smart.py` 4 道闸 (classify/active-conv guard/throttle 30min/daily cap 5) + 4 capabilities (`screen.get_active_app` / `get_browser_url` / `get_browser_content` / `get_active_document`) + ActivityAwarenessSection 前端 (toggle / blocklist 增删 / 实时状态显示 30s 刷新) + Tauri NSAppleEventsUsageDescription Info.plist 字段 + ActivityPermissionModal 跳 macOS 自动化设置 + GET/PATCH /api/activity/{status,config,permissions} + lifespan 6c' 起停 hook; ~95 new tests / 0 regression on chunk 9/10/11/UX-001 (隔离运行) |
| v3.5 chunk 8b: full screen awareness (screenshot + OCR + VLM abstraction + browser extension) | 📋 planned (复用 chunk 8a 的 ActivityWatcher + blocklist + smart_trigger 节流框架) |
| v4: Screen awareness | 📋 planned |
| v5-D / T1 / T2: autodl + GPT-SoVITS + custom voice training | 📋 long-term |
| v6+: Multi-device / cloud deployment | 📋 long-term |

---

## License

Currently **All rights reserved** (no LICENSE file). Will switch to a permissive license (MIT or Apache 2.0) when the repo goes public — note: any Live2D models bundled later will carry their own Live2D Inc. licenses, which are *not* covered by Skyler's eventual project license.

### Live2D model license

During development Skyler ships with the official Live2D sample model **Hiyori** (under `frontend/public/live2d/hiyori/`), illustrated by Kani Biimu. The model is distributed under the **Live2D Free Material License Agreement** — development, learning and small-scale commercial use are permitted; medium-to-large enterprise commercial use requires a separate written license from Live2D Inc.

v3-E2 will swap Hiyori out for an owned/commissioned model. At that point the bundled model is governed by its own original license, *not* Skyler's eventual project license.

---

## Contributing

Not currently accepting external contributions while the project is in private development. See you when we go public.
