# 🌸 MomoOS

> A local-first AI agent desktop companion — she listens, speaks, remembers, and acts.

![Python](https://img.shields.io/badge/Python-3.10+-blue) ![FastAPI](https://img.shields.io/badge/FastAPI-async-green) ![Tauri](https://img.shields.io/badge/Tauri-2.0-orange) ![Platform](https://img.shields.io/badge/platform-macOS-lightgrey) ![License](https://img.shields.io/badge/license-MIT-lightgrey)

> **Status (May 2026)**: v1 backend complete. v2 frontend in progress — Tauri shell, Widget/Panel UI, WebSocket streaming chat, voice input with VAD, and reconnection are all working. Memory viewer and settings panel are the last v2 milestones. Currently macOS-only; Windows/Linux support deferred to v3.

---

## What is MomoOS?

MomoOS is a local-first AI agent companion that lives on your desktop. She doesn't just respond — she remembers everything you've shared, understands your habits, and proactively reaches out when it matters.

Built on a multi-agent ReAct architecture with real MCP tool integration, long-term vector memory, and customizable anime character personas.

Two modes, one companion:
- **Widget mode** — transparent, always-on-top floating character for quick voice interaction
- **Panel mode** — full-window app with chat history, memory viewer, and settings

UI style references [Open-LLM-VTuber](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber-Web): dark theme, Live2D canvas as main backdrop, semi-transparent control overlays.

---

## Features

### 🎙 Input & Output
- Voice input with two modes:
  - **Manual mode** — click to start recording, click again to send
  - **VAD mode** — click to activate; auto-detects speech onset via Web Audio API, auto-sends after silence threshold; 1-minute idle timeout returns to sleep
- ASR result preview — recognized text shown above input box in real time via `asr_result` WebSocket message
- Real-time streaming output — text and audio arrive sentence by sentence
- GPT-SoVITS anime voice synthesis; auto-fallback to Edge-TTS
- Auto-mute mic when Momo is speaking (prevents feedback loop)

### 🧠 Memory & Personality
- Short-term memory — always on, recent 20 turns injected into every response
- Long-term memory — SQLite + local vector search (sentence-transformers), Top-5 relevant memories retrieved per turn
- Two-layer user profile — stable traits (personality table) + free-text summary auto-updated by LLM
- Time-aware memory — short-lived states auto-expire
- Memory switches — toggle long-term memory, user profile, and web search on/off in settings
- Memory viewer — browse, edit, and delete what Momo knows about you

### 🤖 Multi-Agent Intelligence
- ReAct loop: Planner → Memory / Tool → Chat
- Three-class intent classifier — chitchat / memory / tool
- Real MCP tool integration — extensible ToolRegistry
- LiteLLM unified LLM interface — DeepSeek / Qwen / OpenAI / Claude
- Web search — model-native search (Qwen Max / DeepSeek), toggled via `enable_search`

### 🔔 Proactive Engagement
- Alarm & reminder system — natural language scheduling, spoken in character when triggered
- Todo management — agent-created and user-created tasks tracked in SQLite
- Proactive push — backend initiates messages at any time via persistent WebSocket connection

### 🌸 Character & Presence
- Customizable anime character personas (not limited to any specific franchise)
- v2: static character image placeholder, layout pre-designed for Live2D drop-in
- v3: Live2D avatar with idle animations, expression sync, lip sync

### 🪟 Interface
- Dual UI modes — transparent floating widget + full panel app (Tauri 2)
- UI style: dark navy theme, Live2D canvas as main backdrop, floating semi-transparent overlays
- Mouse click-through for widget mode
- Settings panel — toggle memory layers, web search, recording mode, and VAD parameters

### 👁 Screen Awareness (v4, planned)
- **Active mode** — voice command or hotkey triggers screenshot, Momo analyzes content via VLM
- **Passive mode** — periodic screenshots with pixel-diff pre-filter, only sends to VLM when screen changes meaningfully; Momo proactively comments when something noteworthy is detected
- VLM analysis runs in cloud (GPT-4o / Qwen-VL / Claude) — no local GPU usage
- Future extension: system operation agent (mouse/keyboard control) — requires macOS Accessibility permission, deferred to a later phase

---

## Architecture

```
User input (voice / text)
  → [VAD mode] Web Audio API detects speech onset → MediaRecorder starts
     silence > threshold (1.5s) → MediaRecorder stops → send audio
  → [Manual mode] user clicks → MediaRecorder start/stop → send audio
  → ASR        faster-whisper (backend) → asr_result pushed to frontend
  → Planner    3-class intent: chitchat / memory / tool
      → MemoryAgent   read/write SQLite (parallel, results injected to context)
      → ToolAgent     MCP tool execution (parallel, results injected to context)
  → ChatAgent  streaming LLM reply + model-native web search (optional)
  → TTS        GPT-SoVITS → Edge-TTS fallback (sentence-streamed)
Output: streamed text + audio chunks + asr_result preview

VAD state machine:
  sleep → [user clicks mic] → active
  active → [speech detected] → recording → [silence 1.5s] → send → active
  active → [1 min no recording] → sleep

Backend → Frontend (proactive push):
  Alarm / task complete / event / screen-aware comment
    → ConnectionManager.push() → WebSocket → frontend

Settings sync (local IPC):
  Frontend toggle → write config.yaml → POST /api/config/reload → backend reloads
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 18 + Vite + TypeScript + Zustand + Tailwind CSS v3.4 |
| Desktop shell | Tauri 2 (transparent window, always-on-top, click-through, custom drag region) |
| Backend | FastAPI + WebSocket (async streaming) |
| LLM | LiteLLM — DashScope (Qwen) / DeepSeek / OpenAI / Claude (config switchable) |
| VLM (v4) | OpenAI / Qwen-VL / Claude vision API (cloud, no local GPU) |
| Tool protocol | MCP (Model Context Protocol) |
| ASR | faster-whisper (local, CPU/GPU) |
| TTS | GPT-SoVITS → Edge-TTS fallback (sentence-streamed); global on/off via config |
| Memory | SQLite + sentence-transformers (local vector search, no GPU needed) |
| Database | SQLite + SQLAlchemy async (aiosqlite) |

---

## Getting Started

### Prerequisites (macOS)

| Tool | Min version | Install |
|---|---|---|
| Node.js | 18+ (recommend 22+) | `brew install node` or [nodejs.org](https://nodejs.org) |
| Rust toolchain | 1.75+ | `curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \| sh` |
| Xcode Command Line Tools | latest | `xcode-select --install` |
| Python | 3.10+ | `brew install python@3.10` (or use system) |

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
#   DASHSCOPE_API_KEY=sk-xxx   (or any other provider's key)
#   DATABASE_URL=sqlite+aiosqlite:///./momoos.db

# Optionally edit config.yaml to set your LLM model:
#   default_model: "dashscope/qwen-plus"   # default; works with the key above

uvicorn backend.main:app --reload
# Backend runs at http://127.0.0.1:8000

# ── Frontend (in another terminal) ────────────────────
cd frontend
npm install
npm run tauri dev
# First Rust build takes 5–15 min; subsequent starts are fast.
```

A transparent floating Widget window appears on your desktop. Click ⚙ to open the full Panel.

---

## Roadmap

### v1 — Backend (✅ Complete)
- [x] Multi-agent ReAct loop (Planner / Memory / Tool / Chat)
- [x] Three-class intent classifier
- [x] Long-term memory — SQLite + vector search
- [x] Short-term memory — 20-turn window
- [x] Memory summarizer
- [x] Two-layer user profile + time-aware memory
- [x] Character persona system
- [x] LiteLLM + model-native web search
- [x] Database layer (SQLite + SQLAlchemy async)
- [x] ChatAgent / MemoryAgent / ToolAgent / PlannerAgent
- [x] ASR / TTS
- [x] WebSocket full pipeline + `asr_result` push message
- [x] ConnectionManager
- [x] memory_api REST endpoints
- [x] Scheduler — alarm execution

### v2 — Frontend (🚧 Current, ~85% done)
- [x] Tauri 2 setup — transparent window + always-on-top + click-through wrapper
- [x] Tauri 2 capabilities — explicit window-control permissions (set-size / decorations / always-on-top / etc.)
- [x] Widget mode — floating character UI (static image, Live2D-ready props)
- [x] Panel mode — full UI (custom top bar with drag region, sidebar, character backdrop, chat input)
- [x] Widget ↔ Panel mode switching — single-window, dynamic size/decorations via Tauri JS API
- [x] UI style — dark navy theme referencing Open-LLM-VTuber-Web
- [x] WebSocket hook — handle text_chunk / audio_chunk / done / notify / alarm / asr_result, exponential-backoff reconnect
- [x] Audio hook — manual mode + VAD state machine (sleep / active / recording, 60s idle timeout)
- [x] ASR result preview — real-time display with 5s fade-out
- [x] AI status display — idle / listening / thinking / speaking / interrupted (English keys, Chinese labels)
- [x] Auto-mute mic when Momo is speaking (feedback prevention)
- [x] Streaming subtitle bar — flows during TTS, clears 5s after `done`
- [x] Notification toast — proactive backend pushes (notify / alarm)
- [x] Connection status indicator — Sidebar bottom dot
- [x] Backend: GET /api/config (whitelist JSON) + POST /api/config/reload
- [ ] **Memory viewer** (in progress) — list / add / edit / delete with type-colored tags
- [ ] **Settings panel** (in progress) — Memory toggles + TTS on/off + ASR/VAD parameters
- [ ] **Settings sync** (in progress) — Tauri `write_config_field` (serde_yaml) + POST /api/config/reload
- [ ] TTS global on/off — backend `chat.py` skips entire TTS chain when `config.tts.enabled=false`

### v3 — Presence (Planned)
- [ ] Live2D avatar (Cubism 5) with idle animations
- [ ] Emotion system — emotion tags + TTS voice switching + Live2D expression sync
- [ ] Live2D lip sync with TTS audio
- [ ] Clipboard assistant
- [ ] Daily briefing
- [ ] Smart context-aware reminders
- [ ] Growth system

### v4 — Screen Awareness (Planned)
- [ ] Tauri screen capture API + image compression
- [ ] Active mode — hotkey / voice trigger → screenshot → VLM analysis
- [ ] Passive mode — periodic capture + pixel-diff pre-filter → VLM only on meaningful change
- [ ] VLM provider abstraction — OpenAI / Qwen-VL / Claude
- [ ] Screen-aware comments via `notify` push message
- [ ] Privacy blocklist — apps/windows to ignore
- [ ] Settings — capture interval, diff threshold, active/passive toggle
- [ ] (Future) System operation agent — mouse/keyboard via enigo, macOS Accessibility permission required

---

## Project Structure

```
MomoOS/
├── backend/              # FastAPI app
│   ├── main.py
│   ├── config/           # config.yaml loader, reload_config_yaml()
│   ├── agents/           # Planner / Chat / Memory / Tool
│   ├── memory/           # short_term / long_term / summarizer
│   ├── database/         # SQLAlchemy models + services
│   ├── llm/              # LiteLLM wrapper
│   ├── asr/              # faster-whisper
│   ├── tts/              # SoVITS + Edge fallback
│   ├── tools/            # MCP-style ToolRegistry
│   ├── routes/           # ws.py + memory_api.py + config_api.py
│   └── scheduler/        # alarm execution
│
├── frontend/             # React + Vite + Tauri 2
│   ├── src/
│   │   ├── App.tsx
│   │   ├── modes/        # Widget.tsx + Panel.tsx
│   │   ├── components/   # CharacterView / StatusBadge / ChatInput / ...
│   │   ├── hooks/        # useWebSocket + useAudio
│   │   ├── lib/          # window.ts (Tauri API wrappers)
│   │   ├── store/        # Zustand global state
│   │   ├── contexts/     # appApi.ts (sendText / sendVoice / ...)
│   │   └── assets/       # character.png (gitignored)
│   └── src-tauri/
│       ├── tauri.conf.json
│       ├── capabilities/default.json   # window control permissions
│       └── src/main.rs                 # invoke_handler + write_config_field
│
├── config.yaml           # runtime config (default_model, memory, tts, ...)
├── .env / .env.example
├── DESIGN.md             # full technical design (v2.6)
└── README.md
```

See `DESIGN.md` for the complete technical design including database schema, agent interfaces, WebSocket protocol, and architectural decisions.

---

## License

MIT
