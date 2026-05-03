# 🌸 MomoOS

> A local-first AI agent desktop companion — she listens, speaks, remembers, and acts.

![Python](https://img.shields.io/badge/Python-3.10+-blue) ![FastAPI](https://img.shields.io/badge/FastAPI-async-green) ![Tauri](https://img.shields.io/badge/Tauri-2.0-orange) ![Platform](https://img.shields.io/badge/platform-macOS-lightgrey) ![License](https://img.shields.io/badge/license-MIT-lightgrey)

> **Status (May 2026)**: v1 backend + v2 frontend + v2.5 (schema migration, multi-character, ChatGPT-style chat history, LLM tool-calling memory, Galgame-style layout) all complete. Currently macOS-only; Windows/Linux deferred. v3 (UI palette switcher + Live2D + per-character voice + emotion system) planned.

---

## What is MomoOS?

MomoOS is a local-first AI agent companion that lives on your desktop. She doesn't just respond — she remembers what matters, forms her own impression of you, and proactively reaches out when it counts.

Built on a multi-agent architecture with LLM tool-calling memory, semantic vector search, multi-character personas, and a ChatGPT-style multi-conversation UI.

Two modes, one companion:
- **Widget mode** — transparent, always-on-top floating character for quick voice interaction
- **Panel mode** — full-window app with Galgame-style layout: character full-bleed background, floating dialogue bubble, slide-in chat history drawer, conversation list, and settings

UI style references [Open-LLM-VTuber](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber-Web): dark theme, Live2D-ready canvas, semi-transparent overlays.

---

## Features

### 🎙 Input & Output
- Voice input with two modes:
  - **Manual mode** — click to start recording, click again to send
  - **VAD mode** — click to activate; auto-detects speech onset via Web Audio API, auto-sends after silence threshold; 1-minute idle timeout returns to sleep
- ASR transcription flows directly into chat history with `message_id` (no longer just a 5-second preview)
- Real-time streaming output — text and audio arrive sentence by sentence
- GPT-SoVITS anime voice synthesis; auto-fallback to Edge-TTS
- Auto-mute mic when Momo is speaking (prevents feedback loop)

### 🧠 Memory & Personality (v2.5 redesign)
Two-layer memory system, no manual fact entry — Momo decides what to remember:

- **Memories (event-driven facts)**
  - LLM autonomously calls `save_memory` / `delete_memory` / `list_memories` / `compress_memories` tools during conversation
  - SQLite + sentence-transformers vector search, top-5 retrieved per turn
  - Per-character isolation — each character has its own memories of you
  - User can browse + delete (single or clear-all) in Settings; cannot manually add (LLM judges saliency)
  - Time-aware: emotion/activity/daily types auto-expire

- **Profile impression (Momo's view of you)**
  - Single 300–500 word evolving paragraph stored in `users.profile_summary`
  - Incremental rewrite: each regeneration takes the previous impression + recent 50-round chat history → produces new impression that preserves stable traits, adjusts recent observations
  - Triggers automatically on: every 50 turns, OR when a conversation is deleted
  - Data safeguards: skip if < 20 chat rows; clear to NULL if 0 rows
  - Cross-character (one impression of you, regardless of which character is active)
  - Not shown in UI — ask Momo in conversation ("你对我什么印象") and she'll articulate naturally from her injected context

### 💬 Conversations (ChatGPT-style)
- Multiple independent conversations per character
- Conversation list (collapsible) with create / rename / delete
- Each conversation maintains independent chat history (chat_history rows linked by `conversation_id`)
- Deleting a conversation cascades its chat history and triggers profile re-evaluation

### 🎭 Multi-Character
- Multiple AI personas with independent persona prompts and (v3) voices
- TopBar character switcher (avatar + name + dropdown)
- Switching character → conversations + memories filter by `character_id`
- Default Momo character cannot be deleted; others freely creatable / editable / removable
- Per-character data isolation enforced through full memory pipeline

### 🤖 Multi-Agent Intelligence
- Planner (qwen-turbo) → 3-class intent: chitchat / memory / tool
- ChatAgent with LLM tool calling: 4 memory tools + extensible MCP tool registry
- LiteLLM unified LLM interface — DashScope (OpenAI-compatible endpoint) / DeepSeek / OpenAI / Claude
- Web search — model-native (Qwen / DeepSeek), toggled via `enable_search`

### 🔔 Proactive Engagement
- Alarm & reminder system — natural language scheduling, spoken in character when triggered
- Todo management — agent-created and user-created tasks tracked in SQLite
- Proactive push — backend initiates messages at any time via persistent WebSocket connection

### 🌸 Character & Presence
- Customizable anime character personas (not limited to any specific franchise)
- v2.x: static character image full-bleed, layout pre-designed for Live2D drop-in
- v3: Live2D avatar with idle animations, expression sync, lip sync

### 🪟 Interface
- Dual UI modes — transparent floating widget + full panel app (Tauri 2)
- Panel layout: Sidebar (💬⚙) | collapsible ConversationList (240px) | main area = full-bleed character + floating dialogue bubble + chat input + slide-in history drawer
- Global drag strip + custom TopBar with character switcher
- Image drag-out blocked, mode persisted in localStorage (default = Panel)
- Settings panel — memory toggles, ASR/VAD parameters, TTS on/off, memory list manager, basic info (nickname/language), character manager
- Keyboard / hover-driven interactions throughout

### 👁 Screen Awareness (v4, planned)
- **Active mode** — voice command or hotkey triggers screenshot, Momo analyzes content via VLM
- **Passive mode** — periodic screenshots with pixel-diff pre-filter, only sends to VLM when screen changes meaningfully
- VLM analysis runs in cloud (GPT-4o / Qwen-VL / Claude) — no local GPU usage
- Future extension: system operation agent (mouse/keyboard control)

---

## Architecture

```
User input (voice / text)
  → [VAD mode] Web Audio API detects speech → MediaRecorder → send audio
  → [Manual mode] click → start/stop recording → send audio
  → ASR (faster-whisper, run_in_executor) → write chat_history → push asr_result {message_id}
  → Planner (qwen-turbo) — 3-class intent
      → MemoryAgent / ToolAgent (parallel via asyncio.gather)
  → ChatAgent
      → _build_messages: persona + profile_summary + memory top-5 (by character_id) + chat_history + input
      → acompletion(stream=True, tools=[save_memory, delete_memory, list_memories, compress_memories])
      → tool calling loop (up to 5 rounds): collect tool_calls → execute → inject result → continue stream
      → sentence streaming → ws.send(text_chunk)
  → TTS sentence-by-sentence (GPT-SoVITS → Edge fallback) → ws.send(audio_chunk)
Output: streamed text + audio chunks + asr_result preview

Background:
  - assistant reply written to chat_history (with conversation_id / character_id)
  - turn_count_per_user++; on threshold → asyncio.create_task(regenerate_profile_summary)
  - DELETE /api/conversations/{id} → cascade chat_history → trigger regenerate_profile_summary

VAD state machine:
  sleep → [click] → active → [speech] → recording → [silence 1.5s] → send → active
  active → [60s idle] → sleep

Settings sync (local IPC):
  Frontend toggle → Tauri write_config_field → config.yaml → POST /api/config/reload
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 18 + Vite + TypeScript + Zustand + Tailwind CSS v3.4 |
| Desktop shell | Tauri 2 (transparent window, always-on-top, click-through, custom drag region) |
| Backend | FastAPI + WebSocket (async streaming) + lifespan model preload |
| LLM | LiteLLM — DashScope (OpenAI-compatible) / DeepSeek / OpenAI / Claude |
| LLM tool calling | OpenAI function format via LiteLLM |
| VLM (v4) | OpenAI / Qwen-VL / Claude vision API (cloud) |
| Tool protocol | MCP (Model Context Protocol) + 4 built-in memory tools |
| ASR | faster-whisper (CPU/GPU) — wrapped in run_in_executor |
| TTS | GPT-SoVITS → Edge-TTS fallback (sentence-streamed); global on/off |
| Memory | SQLite + sentence-transformers (paraphrase-multilingual-MiniLM-L12-v2) |
| Database | SQLite + SQLAlchemy async (aiosqlite) + idempotent migrations |

---

## Getting Started

### Prerequisites (macOS)

| Tool | Min version | Install |
|---|---|---|
| Node.js | 18+ (recommend 22+) | `brew install node` or [nodejs.org](https://nodejs.org) |
| Rust toolchain | 1.75+ | `curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \| sh` |
| Xcode Command Line Tools | latest | `xcode-select --install` |
| Python | 3.10+ | `brew install python@3.10` |

### Setup

```bash
git clone https://github.com/XguihuaX/MomoOS.git
cd MomoOS

# ── Backend ───────────────────────────────────────────
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env — at minimum:
#   DASHSCOPE_API_KEY=sk-xxx
#   DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
#   DASHSCOPE_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
#   HF_HUB_OFFLINE=1
#   TRANSFORMERS_OFFLINE=1

# Optionally edit config.yaml to set your LLM model:
#   default_model: "openai/qwen-plus"      (DashScope OpenAI-compat — fastest from China)
#   planner_model: "openai/qwen-turbo"

uvicorn backend.main:app --reload
# Backend runs at http://127.0.0.1:8000
# First start: lifespan preloads sentence-transformers + whisper models (~10–60s)

# ── Frontend (in another terminal) ────────────────────
cd frontend
npm install
npm run tauri dev
# First Rust build takes 5–15 min; subsequent starts are fast
# App launches in Panel mode by default; mode preference persisted in localStorage
```

A full Panel window appears with the character backdrop. Switch to Widget mode via the top-bar `⌃` button; preference persists across restarts.

> 💡 **Network note**: DashScope is China-based. If you're behind a global VPN, use split-tunnel routing for `*.dashscope.aliyuncs.com → DIRECT`, otherwise LLM responses may stall. Cloud deployment (e.g. autodl) eliminates this issue entirely.

---

## Roadmap

### v1 — Backend (✅ Complete)
- [x] Multi-agent loop (Planner / Memory / Tool / Chat)
- [x] Three-class intent classifier
- [x] Long-term memory — SQLite + vector search
- [x] Short-term memory — N-turn window
- [x] Two-layer user profile + time-aware memory
- [x] Character persona system
- [x] LiteLLM + model-native web search
- [x] Database layer (SQLite + SQLAlchemy async)
- [x] ChatAgent / MemoryAgent / ToolAgent / PlannerAgent
- [x] ASR / TTS
- [x] WebSocket full pipeline + asr_result push
- [x] ConnectionManager
- [x] memory_api REST endpoints
- [x] Scheduler — alarm execution

### v2 — Frontend (✅ Complete)
- [x] Tauri 2 setup — transparent window + always-on-top + click-through wrapper
- [x] Tauri 2 capabilities — explicit window-control permissions (incl. start-dragging)
- [x] Widget mode — floating character UI (static image, Live2D-ready props)
- [x] Panel mode — full UI with custom top bar / sidebar / character backdrop / chat input
- [x] Widget ↔ Panel mode switching — single-window dynamic Tauri JS API
- [x] WebSocket hook — text_chunk / audio_chunk / done / notify / alarm / asr_result + exponential-backoff reconnect
- [x] Audio hook — manual + VAD state machine + 60s idle timeout + feedback prevention
- [x] AI status display + auto-mute mic during TTS playback
- [x] Streaming subtitle bar (deprecated by v2.5 floating bubble in Panel mode)
- [x] Notification toast — proactive backend pushes
- [x] Connection status indicator
- [x] Backend: GET /api/config (whitelist JSON) + POST /api/config/reload
- [x] Memory viewer / Settings panel / Settings sync (Tauri write_config_field)
- [x] TTS global on/off — backend skips TTS chain when disabled

### v2.5 — Memory & UI rework (✅ Complete)
- [x] **A. Backend performance** — lifespan preload, asyncio.to_thread for blocking inference, /api/health endpoint, timing instrumentation, Planner switched to qwen-turbo
- [x] **B. Schema migration + memory tools** — add `conversations` / `characters` tables, `character_id` / `conversation_id` columns; drop `personality` table; ChatAgent registers 4 memory tools (save/delete/list/compress) via LiteLLM tool calling; replace explicit summarizer with implicit tool-driven flow
- [x] **C1. Three-column chat layout** — Sidebar + ConversationList (collapsible) + main; new GET /conversations/{id}/messages endpoint; ws protocol gains conversation_id / character_id (backward compatible)
- [x] **C2a. Galgame-style layout** — full-bleed CharacterView + floating dialogue bubble (latest assistant only) + slide-in ChatHistoryDrawer + 📜 history button; remove SubtitleBar from Panel; remove standalone MemoryPanel; simplify Sidebar to 💬⚙
- [x] **C2b. Settings rework + ASR integration** — Memory section (summary card + manage drawer), basic info (nickname/language), profile_summary 50-turn task, save_memory description tightened with positive/negative examples, ASR transcription enters chat history with message_id
- [x] **C2 small fixes** — drag permission, character image drag-blocked, global drag strip (widget mode), drawer X button position, MemoryManagerDrawer with type filter
- [x] **D. Multi-character system** — CharacterSwitcher in TopBar + CharacterManagerDrawer (CRUD; Momo not deletable) + character_id propagated through full memory pipeline + lifespan backfill for legacy NULL rows
- [x] **E. Mode persistence + profile_summary refinements** — startup defaults to Panel + localStorage 'momoos.mode'; profile_summary becomes incremental (preserves stable traits via old-summary injection); regeneration triggered on conversation delete; data thresholds (skip < 20 rows; clear at 0 rows)

### v3 — Presence & UI (Planned)
- [ ] **UI palette switcher** — 4 themes (莫兰迪奶油 / 暮色梦幻 / 玻璃拟态 / 水彩二次元) selectable in Settings + persisted
- [ ] **lucide-react icon library** — replace Unicode emoji icons throughout
- [ ] **Live2D avatar (Cubism 5)** with idle animations
- [ ] **Emotion system** — `<emotion>` tag parsing + TTS voice switching + Live2D expression sync
- [ ] **Live2D lip sync** with TTS audio
- [ ] **Per-character voice model** — `characters.voice_model` field; TTS pipeline routes by character
- [ ] **PlannerAgent simplification** — let ChatAgent directly handle intent classification, save 1 LLM round-trip per turn
- [ ] **Clipboard assistant**
- [ ] **Daily briefing**
- [ ] **Smart context-aware reminders**
- [ ] **Growth system**

### v4 — Screen Awareness (Planned)
- [ ] Tauri screen capture API + image compression
- [ ] Active mode — hotkey / voice trigger → screenshot → VLM analysis
- [ ] Passive mode — periodic capture + pixel-diff pre-filter → VLM only on meaningful change
- [ ] VLM provider abstraction — OpenAI / Qwen-VL / Claude
- [ ] Screen-aware comments via push message
- [ ] Privacy blocklist — apps/windows to ignore
- [ ] Settings — capture interval, diff threshold, active/passive toggle
- [ ] (Future) System operation agent — mouse/keyboard via enigo

### Cloud deployment (post-v3)
- [ ] Deploy backend to autodl or similar Chinese cloud → eliminates VPN routing concerns for DashScope LLM calls
- [ ] Frontend connects to remote backend via SSH tunnel / HTTPS

---

## Project Structure

```
MomoOS/
├── backend/                          # FastAPI app
│   ├── main.py                       # lifespan: model preload + idempotent migration + backfill
│   ├── config/                       # config_yaml + reload_config_yaml() + get_*() getters
│   ├── agents/                       # Planner / Chat (with 4 memory tools) / Memory / Tool
│   ├── memory/                       # short_term / long_term (vector search w/ character_id filter)
│   ├── database/
│   │   ├── models.py
│   │   ├── services.py
│   │   └── migrations/v2_5_b.py      # idempotent: add conversations/characters; extend chat_history/memory; drop personality
│   ├── llm/                          # LiteLLM wrapper (DashScope OpenAI-compat)
│   ├── asr/                          # faster-whisper + run_in_executor
│   ├── tts/                          # SoVITS + Edge fallback
│   ├── tools/                        # built-in + MCP-style ToolRegistry
│   ├── routes/
│   │   ├── ws.py                     # WebSocket + ConnectionManager + profile_summary trigger
│   │   ├── memory_api.py             # memory CRUD with character_id filter
│   │   ├── conversations_api.py      # conversations CRUD + /{id}/messages
│   │   ├── characters_api.py         # characters CRUD (Momo not deletable)
│   │   ├── users_api.py              # profile (nickname/language) + profile_summary reset
│   │   ├── health_api.py             # GET /api/health
│   │   └── config_api.py             # GET/POST config
│   ├── scheduler/                    # alarm execution
│   └── utils/timer.py                # @contextmanager timed("xxx")
│
├── frontend/                         # React + Vite + Tauri 2
│   ├── src/
│   │   ├── App.tsx                   # health polling → fetchConfig → fetchCharacters → fetchConversations
│   │   ├── modes/Widget.tsx Panel.tsx
│   │   ├── components/
│   │   │   ├── CharacterView.tsx     # full-bleed, draggable=false
│   │   │   ├── CharacterDialogueBubble.tsx
│   │   │   ├── ChatHistory.tsx ChatHistoryDrawer.tsx
│   │   │   ├── ConversationList.tsx  # collapsible, localStorage persisted
│   │   │   ├── CharacterSwitcher.tsx CharacterManagerDrawer.tsx
│   │   │   ├── MemoryManagerDrawer.tsx
│   │   │   ├── ChatInput.tsx ControlBar.tsx VadBar.tsx StatusBadge.tsx
│   │   │   ├── AsrPreview.tsx ConnectionDot.tsx NotificationToast.tsx
│   │   │   ├── TopBar.tsx            # drag region + switcher + 3 buttons
│   │   │   ├── Sidebar.tsx           # 💬 ⚙ + ConnectionDot
│   │   │   └── SettingsPanel.tsx     # Memory toggles / ASR-VAD / TTS / Memory mgr / Basic info / Character mgr
│   │   ├── hooks/useWebSocket.ts useAudio.ts
│   │   ├── lib/
│   │   │   ├── window.ts             # setConfigField + applyModeWindowProps
│   │   │   ├── config.ts             # fetchConfig + fetchHealth
│   │   │   └── api/{conversations,characters}.ts
│   │   ├── store/index.ts            # Zustand: mode (localStorage) / characters / conversations / chatMessages / etc
│   │   ├── contexts/appApi.ts
│   │   └── assets/character.jpeg
│   └── src-tauri/
│       ├── tauri.conf.json
│       ├── capabilities/default.json # incl. core:window:allow-start-dragging
│       └── src/main.rs               # write_config_field (serde_yaml)
│
├── config.yaml                       # default_model / planner_model / memory / tts / search / cache / screen
├── .env / .env.example
├── DESIGN.md                         # full technical design (v2.7)
└── README.md
```

See `DESIGN.md` v2.7 for complete technical design including database schema, agent interfaces, WebSocket protocol, memory system architecture, and v3/v4 roadmap.

---

## License

MIT
