# 🌸 Skyler

> A hackable AI companion framework — bring your own LLM, your own Live2D model, your own MCP tools. The agent core gives you a foundation. The rest is yours to sculpt.

![Python](https://img.shields.io/badge/Python-3.10+-blue) ![FastAPI](https://img.shields.io/badge/FastAPI-async-green) ![Tauri](https://img.shields.io/badge/Tauri-2.0-orange) ![React](https://img.shields.io/badge/React-18-61DAFB) ![Platform](https://img.shields.io/badge/platform-macOS-lightgrey) ![Status](https://img.shields.io/badge/v4--alpha-✅%20shipped-success)

> **Latest**: v4-alpha (May 2026) — Activity Timeline + tool-call transition UX + Live2D-aware fade overlay. See [ROADMAP](ROADMAP.md) for what's shipped and what's next.
>
> *Project formerly known as MomoOS — renamed to Skyler in 2026-05.*

🌐 **Languages**: **English** · [简体中文](README_zh-CN.md)

---

## What is Skyler?

Skyler is a desktop AI agent with a Live2D character interface. Unlike pre-packaged VTuber apps, Skyler is built as a **container you customize** — its agent core (MOMOOS), capability registry, and proactive interaction layer give you a complete foundation, but every capability, every external integration, and every character asset is yours to swap.

If you've ever wanted an AI companion that's actually *yours* — running locally, speaking with your character, calling your tools — Skyler is for you.

The character isn't decoration. Persona-level state (mood, recent thoughts, relationship intimacy) persists across sessions; the agent can call any tool you register and any MCP server you connect; the avatar reacts to what it says and what you do on screen. None of these layers are locked.

---

## Who is this for?

Skyler is built for **hackers who want an AI character of their own**:

- You're comfortable with the command line and can write a bit of Python
- You care about owning your data (everything runs locally — SQLite, sentence-transformers, no cloud lock-in)
- You like the idea of a character-driven AI, not a sterile chatbot
- You'd rather have a framework you can extend than a polished app you can't change

If you want a pre-packaged VTuber experience, check out [Open-LLM-VTuber](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber).
If you want a serverless personal agent platform, check out [Hermes Agent](https://github.com/NousResearch/hermes-agent).

**Skyler sits between them** — a desktop, character-driven agent you actually own.

---

## What makes Skyler different

### 1. Hackable Capability Registry

Every built-in capability is registered through a single `@register_capability` decorator. Internal tools (calendar, clipboard, screen awareness), external MCP servers (filesystem, brave-search, Notion), and your own skills are **first-class citizens** — the LLM agent can't tell them apart and shouldn't have to.

Adding a new skill is five lines. Adding an external MCP server is one config entry. There's no plugin API to learn beyond a decorator and a JSON schema.

### 2. Bidirectional MCP

Skyler is both an MCP **client** (consuming any MCP server: filesystem, brave-search, Notion, anything else you connect) **and** an MCP **server** (exposing its capability registry, character state, and memory to Claude Desktop, Cursor, Claude Code, or any other MCP client).

Your AI character becomes a node in the MCP ecosystem, not an island.

### 3. Persona-level state machine

Most agent frameworks track task state. Skyler also tracks **character state** — LLM-driven accumulation of mood, attention, current activity, recent thoughts, relationship intimacy. The state isn't a hardcoded prompt; it evolves as you interact.

This is what makes Momo feel like a specific person rather than a generic tool. It's also the foundation for the long-term roadmap item we care most about: persona-level learning (the character grows with you, not just gets more capable).

---

## Comparison

|  | Skyler | Open-LLM-VTuber | Hermes Agent |
|---|---|---|---|
| Form factor | Desktop + Live2D | Desktop + Live2D | CLI + messaging gateway |
| Hackability | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐⭐⭐ |
| Character system | ⭐⭐⭐⭐ persona + state machine | ⭐⭐⭐ Live2D + persona | ❌ |
| Proactive engagement | ⭐⭐⭐⭐ broadcast + trigger pack | ❌ reactive only | ⭐⭐⭐ cron |
| MCP integration | ✅ bidirectional | ✅ client only | ✅ workspace |
| Self-improving learning | ❌ on roadmap | ❌ | ⭐⭐⭐⭐⭐ |
| Messaging gateway (Telegram/Discord) | ❌ on roadmap | ❌ | ⭐⭐⭐⭐⭐ |
| Training data export | ❌ on roadmap | ❌ | ⭐⭐⭐⭐⭐ |
| Local-first / no cloud lockin | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |

Skyler is honest about its gaps. The right-most three rows are real — Hermes does them better today, and we're not going to pretend otherwise. The middle four rows are where Skyler earns its place.

---

## Quick Start

```bash
git clone https://github.com/<your-handle>/skyler.git
cd skyler

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
yarn install
yarn tauri dev
# First Rust build takes 5–15 min; subsequent starts are fast.
```

Default LLM is Qwen via DashScope (works in mainland China without VPN). To switch providers, edit `config.yaml` — Skyler uses LiteLLM internally, so DeepSeek / OpenAI / Anthropic / local Ollama all work with a one-line change.

## Live2D Asset Management

Skyler ships with Live2D's official sample model **Hiyori** (in `frontend/public/live2d/hiyori/`) so the app works out of the box. To swap in your own character:

```bash
# Place your model under:
frontend/public/live2d/<slug>/<slug>.model3.json

# Option A: copy assets into the slug dir
cp -r /path/to/MyChar/* frontend/public/live2d/my-char/

# Option B: symlink (saves disk, easier to update)
ln -s /path/to/MyChar frontend/public/live2d/my-char

# Then in CharacterManagerDrawer → set Live2D model = my-char
```

The frontend's `live2d_scanner` picks up new slugs on next launch. To verify your model loads correctly:

```bash
yarn live2d:probe my-char
# Expected: [OK] version=3 (Cubism SDK 4.0)
```

Cubism 3 and 4 models are both supported. See [docs/live2d-setup.md](docs/live2d-setup.md) for motion map config and emotion binding.

---

## Features

Here's what Skyler currently does. None of these are locked — every layer is built to be swapped out, extended, or replaced.

### 🎙 Input & Output
- **Voice input** with two modes:
  - **Manual mode** — click to start recording, click again to send
  - **VAD mode** — click to activate; auto-detects speech via Web Audio API; auto-sends after 1.5 s silence; 60 s idle returns to sleep
- **ASR result preview** — recognized text shown above input box in real time via `asr_result` WS message; persists into chat history
- **Streaming output** — text and audio arrive sentence by sentence
- **TTS** — CosyVoice (DashScope, default) → Edge-TTS fallback; per-character `voice_model` config; SoVITS planned
- **Auto-mute mic** when the assistant is speaking (prevents feedback loop)
- **Tool-call transition** — when the agent calls a tool, it first emits a short transition line ("let me check…") and the input area shows a contextual loading pill ("checking calendar…") so you're never left wondering whether it's frozen <!-- TODO: chunk 15/UX-006 完成后回填 audio pipeline sentence-by-sentence streaming 让过渡语真出声 -->

### 🧠 Memory & Personality (three layers)
- **Layer 1 — short-term** — `chat_history` table, organized by `conversation_id`; the agent picks the last N turns; also the sole input source for the Layer 2 worker
- **Layer 2 — long-term facts** — `memory` table, populated by a **server-side worker** (`MemoryExtractor`, runs every 5 min, 10-stage quality filter, 4-category `entry_type`, 4-state `extraction_source` provenance tag). The `save_memory` tool is demoted to "user explicitly asked to remember." Retrieval uses a forgetting-curve score `score = relevance * (1+log(1+ac)) / (1+age*decay)` with threshold gate and cross-character sharing.
- **Layer 3 — user profile** — `users.profile_data` JSON schema (`profession` / `current_projects` / `interests` / `recurring_topics` / `communication_style` / `active_hours` / `language_preferences`). A strict validator hard-rejects projection language; legacy `profile_summary` kept as fallback; daily cron regenerates from chat history.
- **Activity timeline** — parallel to `chat_history`: every app/URL session you have (with idle-filtered duration) gets persisted. Momo can reference today's activity in conversation ("looks like you spent 3h in VS Code — same project as yesterday?"). 30-day retention by default.
- **Memory viewer drawer** — `entry_type` tab (fact / preference / event / commitment) + `extraction_source` badge (auto / explicit / manual / legacy) + confidence display
- **Memory toggles** — long-term memory, profile, activity awareness, web search, activity timeline — each independently switchable in Settings

### 🤖 Multi-Agent Intelligence
- **ChatAgent direct flow** — LiteLLM tool calling drives memory + built-in tools + MCP tools in a single LLM round-trip (no separate planner needed)
- **Real MCP tool integration** — extensible `ToolRegistry`; bidirectional (Skyler is both client and server)
- **LiteLLM unified LLM** — DeepSeek / Qwen / OpenAI / Claude (config switchable)
- **Web search** — model-native (Qwen Max / DeepSeek), toggled via `enable_search`

### 🎭 Multi-Character Conversations
- **Per-character isolation** — every character has its own conversations + memory; user profile is shared across characters (one impression of you)
- **Conversation list** — collapsible sidebar with rename / delete; deleting triggers profile recompute
- **Character switcher** — dropdown in TopBar, full CRUD via `CharacterManagerDrawer` (Momo / `id=1` is system default and cannot be deleted)
- **Per-character voice** — `character.voice_model` JSON: `{provider, voice, instruct_supported}`; empty falls back to global default

### 🎨 UI: 8-Theme System
Settings → UI lets you switch between:

| Theme | Vibe |
|---|---|
| 🌫️ Morandi | warm minimal cream |
| 🌆 Dusk *(default)* | dreamy purple twilight |
| 🌊 Glass | glassmorphism cool |
| 🌸 Watercolor | pastel pink |
| 🌌 Aurora | deep-sea green-teal |
| 🌷 Sakura | sakura night |
| 🌃 Cyber | cyber crimson |
| 💜 Lavender | misty lavender |

All components use `var(--color-*)` from `styles/themes.css` (no hardcoded Tailwind colors). Persisted in `localStorage`. First-paint flash prevented by applying `data-theme` on mount.

`lucide-react` icons across all components.

### 🔔 Proactive Engagement
- **Trigger pack** — wake_call / lunch_call / dinner_call / bedtime_chat / long_idle / morning_briefing — Momo reaches out when it matters, not on every poll
- **Activity-based triggers** — `ide_open` / `music_playing` / `long_focus` / `url_tech_doc` / `late_night_ide` — fast-path classification on context, with a slow-path LLM judge for ambiguous cases (5+ min dwell, multi-gate throttle, daily cap, idle gate so it stops when you walk away)
- **Invite-conversation pattern** — proactive isn't just push; the trigger can open a short greeting and wait for your response, then route into a regular conversation

### 🛠 Tool ecosystem
- **Calendar** — Apple EventKit (default, zero-network) + Google Calendar (optional)
- **Music** — netease (built-in via mpv self-decoder; also URL Scheme fallback) + macOS media control (next/prev/play_pause/now_playing/volume — works with Apple Music / Spotify / YouTube)
- **Bilibili** — 11 capabilities (search / video info / subtitles for AI summary / etc.)
- **Xiaohongshu** — passive URL parser only (red line locked in code: no scraping / search / feed)
- **Docx** — read / write / append, sandboxed under `~/Documents/Skyler/docs/`
- **Notion** — via official `@notionhq/notion-mcp-server` MCP integration
- **Clipboard helper** — ring buffer of last 50 items (24h TTL, never persisted), `get_recent` / `summarize` / `translate`
- **Screen awareness** — active app + browser URL + page text (with 19-entry blocklist guarding banks / email / social / localhost)
- **And custom skills** — see [Extending Skyler](#extending-skyler)

---

## Architecture

Skyler's architecture isn't incidental. Every major choice — the Capability Registry, bidirectional MCP, persona-level `character_states`, the activity timeline — is a direct consequence of the positioning. A hackable character framework requires first-class extension, ecosystem participation, and persona persistence. If you want to know *why* a piece is shaped a certain way, see [DESIGN.md](DESIGN.md).

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
                └─ web search: model-native (Qwen Max / DeepSeek)
  → emotion    first sentence parses <emotion>X</emotion> → locks turn emotion
  → TTS        get_tts_engine(voice_model) → CosyVoice / Edge / SoVITS
  → Output:    streamed text chunks + per-sentence audio chunks + asr_result preview

Capability Registry:
  @register_capability decorator → CapabilityRegistry singleton
    ├─ Consumer.CHAT_AGENT  → auto-derived OpenAI schema → ToolRegistry → ChatAgent
    ├─ Consumer.SCHEDULER   → APScheduler cron / interval triggers
    └─ Consumer.WEBHOOK     → /api/webhooks/n8n/{trigger} (Bearer + HMAC auth)
  GET /api/capabilities → frontend CapabilityPanel (cards by category, health dots)

Two-layer integrations:
  backend/integrations/<service>.py     low-level client (OAuth, retry, health)
  backend/capabilities/<service>.py     5-line @register_capability per action

Bidirectional MCP:
  ┌─────────────────────────────────────────────────────────────────┐
  │  CapabilityRegistry  ←  decorator  | runtime  | aggregator      │
  │                                                                 │
  │  Source 1: @register_capability    (built-in: time / calendar) │
  │  Source 2: MCP client (consumes external servers, e.g.          │
  │            filesystem, brave-search, Notion)                    │
  │  Skyler-as-server: POST /mcp exposes the registry to            │
  │            Claude Desktop / Cursor / Claude Code (Bearer auth)  │
  └─────────────────────────────────────────────────────────────────┘

Persona-level state:
  character_states table  ← mood / intimacy / current_thought / current_activity
  <state_update> LLM tag protocol (parallel to <emotion>)
  daily intimacy_decay cron
  shared user profile (cross-character impression of you)

Activity timeline:
  ActivityWatcher (30s poll)
    → (app, url, idle_flag) tuple change → session boundary
    → SessionWriter persists to activity_sessions table
    → ChatAgent system-prompt injection ("user did X today for Yh")
    → 5-stage privacy gate (blocklist / dedup / idle-filter / explicit delete / local-only)
```

---

## Tech Stack

- **Backend**: Python 3.10 / FastAPI / SQLAlchemy (async) / APScheduler / LiteLLM / faster-whisper / sentence-transformers / pyobjc (macOS-only bits)
- **Frontend**: Tauri 2 / React 18 / TypeScript / Vite / Tailwind / Zustand / lucide-react / pixi-live2d-display (Cubism 3 + 4)
- **TTS**: CosyVoice (DashScope) primary / Edge-TTS fallback / SoVITS planned
- **ASR**: faster-whisper (local)
- **LLM**: LiteLLM (Qwen / DeepSeek / OpenAI / Claude / local Ollama — config switchable)
- **DB**: SQLite + Alembic migrations
- **MCP**: stdio + streamable HTTP, bidirectional
- **Embeddings**: sentence-transformers (paraphrase-multilingual)
- **Platform**: macOS Apple Silicon primary; Linux/Windows partial

---

## Extending Skyler

Skyler is designed to be extended. Four extension paths cover the common cases.

### 1. Adding a skill (internal capability)

Drop a file in `backend/capabilities/`, decorate a function, and the LLM picks it up on next restart:

```python
# backend/capabilities/weather.py
from backend.capabilities.registry import register_capability, Consumer

@register_capability(
    name="weather.current",
    description="Get current weather for a city. Use when user asks about weather.",
    consumers=[Consumer.CHAT_AGENT],
    parameters={
        "type": "object",
        "properties": {
            "city": {"type": "string", "description": "City name, e.g. 'Tokyo'"}
        },
        "required": ["city"],
    },
)
async def get_current_weather(city: str) -> dict:
    # call your API of choice, return JSON-serializable dict
    return {"city": city, "temp_c": 18, "condition": "cloudy"}
```

That's it. No registration call, no plugin manifest. The decorator + JSON schema is the contract.

See [docs/skills-extension-guide.md](docs/skills-extension-guide.md) for the full pattern (error handling, health checks, multi-consumer).

### 2. Connecting an external MCP server

Add an entry to `config.yaml`:

```yaml
mcp_clients:
  - name: filesystem
    command: npx
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/Users/me/Documents"]
    enabled: true
    expose_via_skyler_server: false   # don't re-expose to Claude Desktop
```

On restart, the MCP client connects, discovers tools, and reverse-registers them as `ext.filesystem.<tool>` capabilities. The ChatAgent picks them up automatically.

Works with any MCP server: brave-search, Notion (`@notionhq/notion-mcp-server`), Anthropic's reference servers, or your own. See [docs/mcp-client-setup.md](docs/mcp-client-setup.md).

### 3. Swapping the Live2D model

See [Live2D Asset Management](#live2d-asset-management) above. The frontend's `live2d_scanner` auto-discovers any model placed in `frontend/public/live2d/<slug>/<slug>.model3.json`. Motion maps and emotion bindings are per-character; see [docs/live2d-setup.md](docs/live2d-setup.md).

### 4. Replacing the LLM provider

Skyler uses LiteLLM, so any provider LiteLLM supports works with a `config.yaml` edit:

```yaml
llm:
  provider: openai          # or 'anthropic' / 'deepseek' / 'ollama' / etc.
  model: gpt-4o
  api_key_env: OPENAI_API_KEY
```

Local Ollama models, on-prem deployments, custom endpoints — all one config field away. No code changes.

---

## What Skyler is NOT

- Skyler is **not** an out-of-the-box VTuber app. If you want pre-packaged streaming/character UX, use [Open-LLM-VTuber](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber).
- Skyler does **not** have self-improving skill learning today. Skills don't refine themselves from use. If that's critical, [Hermes Agent](https://github.com/NousResearch/hermes-agent) does this well. It's on our long-term roadmap as *persona-level learning* (the character grows, not just the skill catalog).
- Skyler does **not** ship messaging gateways (Telegram / Discord / etc). On the medium-term roadmap. Today, Skyler is desktop-only.
- Skyler does **not** export your conversation data as training data. On the long-term roadmap as a "train your own small model on your character" capability.
- Skyler is **not** competing with general-purpose agent frameworks like LangChain or AutoGen. It's specifically a *character-driven desktop agent*. If you don't want the character layer, you don't want Skyler.

We list these honestly because the gaps matter. They're also the roadmap.

---

## Roadmap

See [ROADMAP.md](ROADMAP.md) for the full picture, organized around four pillars:

- **Current focus**: making hackability genuinely easy (skill docs, Live2D swap guide, plugin registry seedling)
- **Medium-term**: filling the honest gaps above (messaging gateway, training data export, capability marketplace)
- **Long-term**: persona-level learning (`character_states` that actually grow)
- **Long-vision**: a small, loyal hobbyist ecosystem around hackable AI characters on the desktop

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

16. **CC restore-user-tweaks 流程非幂等 backlog**（hotfix-8 副产，2026-05-13）
    - 现象：chunk 8a commit 9 docs commit 期间 "restore user's runtime tweaks" 通过 shell ``cat >> file << EOF`` heredoc 拼接,对**已存在**的目标 key 不做幂等检测。结果工作树 ``config.yaml`` 出现 duplicate ``activity_watcher:`` block,Rust ``serde_yaml`` strict parse 报 ``parse yaml: duplicate entry`` 让所有 Tauri ``write_config_field`` 失败
    - hotfix-8 闭环了实例修复(删 duplicate + ``.gitignore`` 备份保护),但**根因机制**仍在:未来 hotfix 期间任何 restore 流程仍可能引入 duplicate
    - 修法 backlog:
      - cc-task spec 中描述的 restore 操作前先 ``grep "^<key>:" file`` 检测,存在则 skip append
      - 或用 ``yq merge`` 声明式合并工具替代 shell heredoc
      - 测试期间用 strict YAML loader(自实现 ``StrictLoader`` mimic serde_yaml,见 ``tests/test_hotfix7_tts_toggle.py`` pattern)而非默认 permissive ``yaml.safe_load``
    - 优先级低（用户授权后才动 config.yaml；非高频路径），工程量 < 1 hr

> ~~**用户画像污染**~~（"温柔陪伴 / 亲密关系 / 细腻敏感" 等反推词写入 profile_summary）✅ chunk 11 治本（2026-05-12）—— LLM 输出严格按 JSON schema，validator hard-reject 违规输出，注入用机械模板而非 LLM。
>
> ~~**LLM hallucinate save_memory**~~（chunk 9 跨角色共享后放大）✅ chunk 10 治本（2026-05-12）—— memory 入库主路径改成 server-side worker（每 5 分钟 batch 提取 + 10 道 filter），``save_memory`` tool 降级为"用户明确说要记"的显式入口；entry 上打 ``extraction_source`` 区分来源，MemoryManagerDrawer UI 角标可见。
>
> ~~**MCP Settings 一条 capability 一行 → 列表过长**~~ ✅ UX-001 治本（2026-05-12）—— ``ExtensionsSection`` 改 accordion，每 server 默认折叠成单行（含 ``X/Y cap`` 角标）；展开后看 capability 列表 + 单 cap toggle。新增 ``mcp_tool_state`` 表 + ``PUT /api/mcp/clients/{name}/tools/{tool}/enabled`` 路由持久化 per-tool override；server 关时所有 tool toggle 自动 disable 不需要清表（``_connect_one`` 时根据 override skip register 即可）。
>
> ~~**情绪 UI 被 TopBar 挡**~~ ✅ UX-001 治本（2026-05-12）—— Panel 模式 ``CharacterStatePanel`` ``top: 12px`` 落在 TopBar (h-10 / z-50) 的 0-40px 范围内被压住。改 ``top: 48px`` 让状态条整体放到 TopBar 下方右侧，z-index 维持 30（不需要浮到 TopBar 之上盖 CharacterSwitcher dropdown）。
>
> ~~**chunk 8a 切 VSCode 等 IDE 无主动消息**~~ ✅ hotfix-6 治本（2026-05-12）—— 根因是 ``_IDE_APPS`` 集合用 ``app.lower()`` 精确匹配，但 macOS NSWorkspace 返 ``"Code"``（CFBundleName），chunk 8a 默认列表只有 ``"visual studio code"`` 和 ``"vscode"`` 漏掉了实际名字。补全 IDE 集合（``code`` / ``code - insiders`` / ``cursor`` / ``windsurf`` / ``zed`` / JetBrains 整族 / Apple 编辑器 / 命令行家族）+ 触发链 6+ 条 INFO 级 log（``app detected`` / ``app changed`` / ``classify`` / ``throttled`` / ``skipped`` / ``proactive trigger fired`` / ``proactive trigger sent``），用户可在 backend.log 自我诊断为什么 trigger 没出。
>
> ~~**MCP Settings 重新出现"全展开 + 平铺一长串"假象**~~ ✅ hotfix-6 防回归（2026-05-12）—— 用户切回 Skyler 后短暂看到旧形态（dev bundle hot-reload 缓存问题，代码本身 UX-001 已正确 gate）。把 ToolList 抽成独立 sub-component + 加 5 条结构断言锁死 ``useState<Set<string>>(new Set())`` / ``client.tools.map`` 出现次数 ≤ 1 / ``isExpanded`` gate 存在 / ``setExpanded`` 调用次数 == 2，未来 refactor 时硬性拦截"默认展开"回退。
>
> ~~**CapabilityPanel 67 cap 平铺一长串 + MCP banner 信息重复**~~ ✅ UX-002 治本（2026-05-12）—— 把 SettingsPanel 内嵌的 CapabilityPanel 内 67 capability 全部 accordion 化 + 删除 CapabilityPanel 顶部 ``MCPServerBanner`` / ``MCPClientsSection``（与 SettingsPanel 底部 ``ExtensionsSection`` 信息重复，UX-001 + hotfix-6 已是更精致的 MCP 入口）。calendar Google OAuth footer + 测试简报按钮从单 capability card 抽到 category-level header（calendar 全 8 cap 共享同一 OAuth 状态）。新 ``CapabilityRow`` 通用 accordion 组件 + ``_briefDesc`` 长 description 截断 + ``{N} cap`` category 计数 badge。Settings 高度从 N 屏缩到 ~1-2 屏。
>
> ~~**proactive trigger 路径 `<state_update>` tag 字面泄露到 widget**~~ ✅ hotfix-7 治本（2026-05-13）—— `backend/proactive/engine.py` 两个 stream 函数 ``run_trigger``（morning_briefing / lunch_call / dinner_call / activity-based 5 个 label）+ ``run_wake_call_trigger``（wake_call stage 2）漏挂 ``_parse_state_update``，state_update raw tag 直接进 ``text_chunk`` push。修法：两个 stream loop 各补一处 ``_parse_state_update`` + apply（与 ws.py 主路径 ``_apply_and_push_state_update`` 同语义，新 ``_apply_proactive_state_update`` helper 用 ``connection_manager.push``）。**外加最后一道 ``strip_all_for_tts`` 兜底**，作为 hotfix-1 4 道防线的第 5 道防回归 —— 每个 ``text_chunk`` push 前都走 strip，正常路径 idempotent no-op，任何 parser 漏点或未来新 LLM 标签格式也不会让 raw tag 进前端。``_strip_format_tags`` 持久化前 strip 链也从只覆盖 3 档（emotion / motion / thinking）升级到 5 档完整（加 state_update + tool_call fallback）。
>
> ~~**SettingsPanel TTS toggle 写入失败显示 "undefined"**~~ ✅ hotfix-7 治本（2026-05-13）—— 真因：Tauri ``invoke('write_config_field', ...)`` 在 Rust 端 ``Result<(), String>`` 返 ``Err(msg)`` 时 JS reject 收到的是**plain string** 不是 Error 对象。前端 catch ``(e as Error).message`` 走 string 上无属性 → 返 undefined → toast "TTS 写入失败：undefined"。修法：``setConfigField`` 用 try/catch 包 invoke + ``typeof e === 'string'`` 分流 + ``throw new Error(...)`` 重新抛；``/api/config/reload`` 失败带 HTTP status + body.slice(0, 120) 摘要；前端新 ``extractErrorMessage(e: unknown)`` 三档兜底 helper（string / Error / object），``remoteToggle`` + ``writeField`` 失败 toast 改用 helper 不用 ``(e as Error).message``。
>
> ~~**config.yaml 出现 duplicate `activity_watcher:` block 让 Tauri 写入全失败**~~ ✅ hotfix-8 治本（2026-05-13）—— 根因是我自己的锅:chunk 8a commit 9 docs commit 期间 "restore user's runtime tweaks" 流程**非幂等** —— restore 脚本对一个**已经含** activity_watcher block 的快照又 ``cat >> EOF`` 第二次追加,工作树出现两个 bit-identical block。Python ``yaml.safe_load`` 永久 permissive(silently 取最后一个)所以 backend lifespan / 测试都没暴露;Rust ``serde_yaml`` strict parse 直接 ``parse yaml: duplicate entry`` Err,导致所有 Tauri ``write_config_field`` 调用失败。**hotfix-7 暴露了真因**(error normalize 让 toast 显示具体 error 而非 undefined)。修法:删除 233-270 重复 block + ``.gitignore`` 加 ``config.yaml.backup-before-*`` pattern + 测试用自实现 ``StrictLoader`` mimic serde_yaml 验证。
>
> ~~**chunk 8a `_IDE_APPS` 中文 macOS 漏 `'终端'` localizedName**~~ ✅ hotfix-8 治本（2026-05-13）—— hotfix-6 commit 3 修过一次 _IDE_APPS 但只覆盖英文 macOS NSWorkspace localizedName(``Code`` / ``Cursor`` 等);中文 macOS 系统下 ``NSWorkspace.frontmostApplication.localizedName`` 对**有 zh-Hans lproj 的 Apple 原生 bundle**(``Terminal.app``)返 ``'终端'`` 而非 ``'Terminal'``。补全 _IDE_APPS 加 ``'终端'`` + ``'terminal'`` + 第三方终端(iTerm2 / Alacritty / WezTerm / Warp / Kitty / Hyper)整族 9 个 alias。**audit finding**(隐式 skill 沉淀): 只有 Apple 自家原生 app 在中文 macOS 上 localize CFBundleDisplayName;第三方编辑器 / IDE / 终端 bundle 不带 zh lproj,中文系统仍返英文名 —— 未来扩展集合无需为 VSCode / Cursor / JetBrains 等加中文 alias。
>
> ~~**CapabilityPanel category 标题固定 + 多 provider category 内 capability 平铺**~~ ✅ UX-003 治本(2026-05-13)—— UX-002 把 67 capability 改单行 accordion 后 Settings 仍 N 屏。UX-003 三层 accordion 全栈:layer 1 — 9 个 category 标题改 ``<div role="button">`` (避免嵌套 ``<button>`` 非法 HTML),整行可点 + Enter/Space 键盘,默认 ``useState<Set<string>>(new Set())`` 全折叠;layer 2 — 多 provider category(calendar 3 provider / mcp_external 2 / media 4)按 ``_extractProvider(capName)`` 自动分组(``ext.X.Y`` 拼回 ``ext.X``,其他取首段),provider row 默认折叠,展开后渲染 capability list。单 provider category(其他 6 个)跳过二层与 UX-002 行为一致;layer 3 — UX-002 CapabilityRow 单 cap 行内 description/谁能调/触发等。``PROVIDER_DISPLAY = {media: 'media_control'}`` 映射避免与 category title MEDIA 视觉撞名。Settings 高度从 ~2 屏 → ~1 屏。
>
> ~~**情绪 UI 在 Panel 右上角挡住聊天历史按钮**~~ ✅ UX-003 治本(2026-05-13)—— UX-001 commit 3 修过情绪条 top offset(``top: 12px → 48px`` 避开 TopBar)但仍 ``right: 16px``,与 modes/Panel.tsx 内 ``<button className="absolute top-4 right-4 z-30">[ScrollText] 历史</button>`` (打开聊天记录抽屉)视觉重叠 + hover 互相覆盖。UX-003 commit 3 改 ``right: 16px → left: 16px``,左上角实测完全空闲(CharacterView ``absolute inset-0 z-0`` 满铺背景无 positioned 元素),挪过去无冲突。Widget 模式不动(无 TopBar/无历史按钮)。z-index 30 维持(不浮 TopBar 之上避免反向遮 CharacterSwitcher dropdown)。
>
> ~~**chunk 8a activity trigger 只覆盖硬编码白名单(IDE/音乐/技术文档),普通网页/Twitter/招聘页等无主动陪伴**~~ ✅ chunk 8a-ext 治本(2026-05-13)—— 加 ``ActivityJudge`` 慢路径:用户停同一 app/URL 5+ min 时调 qwen-turbo 让 LLM 判断 ``{speak: bool, reason, topic_hint}``,yes 走现有 proactive engine fire ``activity_judge_chime_in`` 主动开口,no 静默。三重门防滥用:``min_stay_minutes`` (5) + ``judge_throttle_minutes`` (10) + 共享 ``fire_throttle`` (30 min)。共享 ``daily_cap`` (5/天) 计数器(快慢路径同一 counter,total 主动消息严格 ≤ cap)。``topic_hint`` 作 anchor 注入主 LLM (ChatAgent) system prompt 让 Momo 知道往哪个方向搭话(不强制,LLM 仍自由发挥)。markdown fence 容错 + ``speak`` 字段 bool/string/int 多形态容忍 (chunk 10/11 同模板)。LLM 异常 silent None + 记账 throttle 防 retry storm。``SettingsPanel [活动感知] section`` 加二级 toggle"智能陪伴 — qwen-turbo 判断"默认 ON 可关。新 ``activity_judge.py`` (337 行) + ``activity_smart.judge_poll_handler`` + ``activity_watcher.register_poll_listener``。
>
> ~~**chunk 8a `get_active_app` 用 `NSWorkspace.frontmostApplication` 在 headless backend 进程缓存于启动那一拍,30 min 后切多少次 app 都报启动时的 frontmost(`app='终端' url=—`),所有屏幕感知 / 主动陪伴 / chunk 14 activity timeline 数据全错**~~ ✅ hotfix-10 治本(2026-05-13)—— ``NSWorkspace.sharedWorkspace().frontmostApplication()`` 通过 ``distributed notifications`` 接收 frontmost 变化事件,dispatch 这些事件需要 ``NSRunLoop`` 在主线程跑;headless Python 进程(daemon / 子进程 / 任何非 GUI 应用)没有 NSRunLoop,事件永远不被 deliver → 内部缓存永远是启动那一拍的值。经典 macOS pyobjc 坑。**实测证据**:用户启动 backend 时 Terminal frontmost,之后切 Safari / Chrome / 任何 app,backend log tick=2 到 tick=27 持续 30+ 分钟全是 ``app='终端' url=—``。修法:走 ``osascript -e 'POSIX path of (path to frontmost application)'`` 子进程,每次 fork 不依赖 parent RunLoop,osascript 自己起完整 AppleScript 环境查 frontmost,返完即退;延迟 30-80ms,与 chunk 8a-ext V2 ``ioreg`` + chunk 8a browser tab AppleScript 同 pattern,**零新依赖**。**副作用 — 返英文 bundle 名**(``"Terminal"`` / ``"Code"`` / ``"Safari"``)而非 NSWorkspace.localizedName 在中文 macOS 上返的本地化中文名(``"终端"`` / ``"Safari浏览器"``)。所有下游 ``_IDE_APPS`` / ``_BROWSER_APPS`` / ``_MUSIC_APPS`` frozenset 已涵盖英文 keys,hotfix-6/8 加的中文别名(``"终端"``)post-fix 转为 dead code 但**不删**(backward compat + 历史文档价值)。chunk 14 LLM-facing 注入文本(``format_today_activity_for_prompt``)走单独 ``_APP_DISPLAY_NAMES`` mapping(``Code → "VS Code"`` / ``Terminal → "终端"``)解决中文 macOS 用户阅读体验,DB / stay_key / capability return 一律英文 bundle 名保跨 locale 稳定。**audit 副产物 bug**:``_BROWSER_APPS`` 含 ``"safari 浏览器"`` (带空格),但真实 macOS NSWorkspace 返 ``"Safari浏览器"`` (无空格) — 那条中文别名在 hotfix-10 **之前就已经是无效代码**,中文 macOS Safari 用户 pre-hotfix-10 ``get_browser_url()`` 一直返 None。hotfix-10 incidentally 通过英文 bundle 名绕过这条 bug。**138 PASS** 跨 6 个 chunk 8a / 8a-ext 测试文件 / 0 regression。
>
> ~~**chunk 8a `get_chrome_active_tab` / `get_safari_active_tab` 不查 frontmost,Chrome 后台开着 bilibili 时 stay_timer 仍把 bilibili 算作 active URL,触发 judge 让 Momo 主动聊"看到你在看招聘"**~~ ✅ hotfix-9 治本(2026-05-13)—— chunk 8a 的两个 raw AppleScript helper(``tell application "Google Chrome" to get URL of active tab of front window``)只要 Chrome 进程跑且有窗口就返 URL,**不**查 Chrome 是不是 macOS frontmost。下游 ``ActivityWatcher.snapshot()`` 直接信任这个返值塞进 ``state.browser``,``_detect_changes`` 不重置 ``_url_dwell_start``,``get_current_stay_info`` URL 优先返 ``key=url:bilibili duration=300s+``,chunk 8a-ext judge 调 qwen-turbo 看到"停 5+ min" → fire ``activity_judge_chime_in`` → Momo 主动聊招聘 → 用户错愕"为啥跟我聊我没在看的东西"。**audit 决定**:修法选 activity_monitor 层包 wrapper 而不是 AppleScript 内嵌 ``frontmost of (process X of system events)`` —— 后者需要 Accessibility 权限(NSAppleEvents 之外又一道弹窗,UX 不友好);前者用 ``NSWorkspace.frontmostApplication.localizedName`` 零额外权限,与 chunk 8a ``get_active_app`` 同源。新 ``backend/integrations/activity_monitor.get_browser_url() -> Optional[Tuple[browser, url, title]]``:先 ``get_active_app()`` 拿 frontmost localizedName,在 ``_BROWSER_APPS`` frozenset(Chromium 系 / WebKit / Gecko 中英文 alias 全覆盖,对齐 hotfix-8 i18n 教训)命中才路由对应 AppleScript;非命中 / 识别但无 impl(Firefox/Edge/Arc 等) → None。raw primitives 保留作既有 9 单元测试 + 内部工具。**stay_key 逻辑不动** —— ``get_current_stay_info`` 既有"URL 优先,无 URL fallback app"正确,只要上游 ``snapshot.browser=None``(非浏览器 frontmost)``_detect_changes`` 自然把 ``_url_dwell_start`` 重置到 0,stay 自动 fallback ``app:VSCode``。``backend/capabilities/screen.{get_browser_url, get_browser_content}`` LLM capability 同接 wrapper,LLM 通过 capability 问"用户看什么 URL"时也获得 frontmost 语义。**137 PASS** 跨 7 个 chunk 8a / 8a-ext 相关测试文件 / 0 regression。
>
> ~~**chunk 8a-ext 慢路径 judge 在"人离开电脑但前台不变"(开会去了 / 锁屏睡觉)时仍 fire,Momo 对着空椅子自言自语**~~ ✅ chunk 8a-ext V2 治本(2026-05-13)—— 加键鼠 idle 第 4 道闸:``backend/integrations/activity_monitor.get_idle_seconds()`` 跑 ``ioreg -c IOHIDSystem`` 子进程,正则抽 ``HIDIdleTime`` 字段(纳秒)/ 1e9 转秒。``maybe_judge`` 在 ``_record_judged`` 之后、``_build_judge_prompt`` 之前查 ``get_idle_seconds() > idle_threshold_seconds`` (默 300s),命中 → logger.info 标"away from computer" + return None,**LLM 没跑、不烧 token、不 chime in**;throttle 已经记账避免 idle 闸 on/off 之间反复 retry。**audit 决定:选 ioreg 而非 ``pyobjc-framework-Quartz`` 因为零新 pip 依赖**(复用 chunk 8a osascript subprocess 范式 + timeout 2s + ``check=False`` + silent None fallback)。跨平台 graceful:非 macOS / ``shutil.which("ioreg") is None`` / ``TimeoutExpired`` / 异常 / 非零 returncode / 正则不匹配 → 全部 silent None,调用方按"假定活跃"维持 V1 行为(linux/windows 不挡)。``SettingsPanel`` 在智能陪伴 toggle 下条件渲染 ``<input type="number" min=0 max=3600 step=30>`` (仅 judge 开时显示,关时无意义不暴露),blur/Enter 触发 PATCH ``judge_idle_threshold_seconds``,backend ``max(0, min(3600, v))`` clamp 防 UI 误输入,0 = 关闸保留老 V1 行为。新 ``backend/integrations/activity_monitor.py`` ``get_idle_seconds`` (+70 行) + ``backend/proactive/activity_judge.py`` ``get_idle_threshold_seconds`` + idle 闸 (+27 行) + ``tests/test_chunk8a_ext_v2_idle.py`` 21 case 全 PASS(V1 30 + V2 21 = 51 PASS / 0 regression)。

---

## Prior art

Skyler exists in a landscape where two open projects already define edges of it:

- **[Open-LLM-VTuber](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber)** — the polished VTuber companion experience. A great pre-packaged app if that's what you want.
- **[Hermes Agent](https://github.com/NousResearch/hermes-agent)** by Nous Research — a serverless personal-agent platform with self-improving skill loops.

Both are excellent at what they aim to be. Skyler is aimed at the gap between them — desktop, character-driven, hackable down to the agent core, and owned end-to-end by the user. The architecture choices follow from that gap, not from a checklist of competitor features.

Where they're ahead of Skyler today is in [Comparison](#comparison) above — listed honestly so you can pick the right tool.

---

## Project Status

v4-alpha shipped May 2026. Activity timeline + tool-call transition UX + Live2D-aware fade overlay are live. The full implementation log (every chunk, hotfix, UX iteration) lives in [ROADMAP.md](ROADMAP.md) — that's the honest history. The current focus is making Skyler's hackability genuinely easy for the next contributor, not just the original author.

---

## License

Currently **All rights reserved** (no LICENSE file). Will switch to a permissive license (MIT or Apache 2.0) when the repo goes public — note: any Live2D models bundled later will carry their own Live2D Inc. licenses, which are *not* covered by Skyler's eventual project license.

### Live2D model license

During development Skyler ships with the official Live2D sample model **Hiyori** (under `frontend/public/live2d/hiyori/`), illustrated by Kani Biimu. The model is distributed under the **Live2D Free Material License Agreement** — development, learning and small-scale commercial use are permitted; medium-to-large enterprise commercial use requires a separate written license from Live2D Inc.

A later release will swap Hiyori out for an owned/commissioned model. At that point the bundled model is governed by its own original license, *not* Skyler's eventual project license.

---

## Contributing

Not currently accepting external contributions while the project is in private development. See you when we go public.
