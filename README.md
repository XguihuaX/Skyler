# 🌸 Skyler

> A local-first AI companion that lives on your desktop — Galgame-style avatar on the outside, full-stack life & tools agent on the inside.

![Python](https://img.shields.io/badge/Python-3.10+-blue) ![FastAPI](https://img.shields.io/badge/FastAPI-async-green) ![Tauri](https://img.shields.io/badge/Tauri-2.0-orange) ![React](https://img.shields.io/badge/React-18-61DAFB) ![Platform](https://img.shields.io/badge/platform-macOS-lightgrey) ![Status](https://img.shields.io/badge/status-v3--WIP-yellow)

> **Status (May 2026)**: v2.7 backend & UI complete · v3-A/B/C/D in progress (~60% of v3 done) · Live2D, voice interrupt, screen vision, and life-tools layer up next.
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

### 🌸 Character Presence
- v2.7: static character image + Galgame layout (full-bleed character + floating dialogue bubbles + history drawer)
- v3 (in progress): emotion tag system (`<emotion>...</emotion>`) parsed from LLM, drives TTS voice variation
- v3 (next): Live2D Cubism 5 avatar with idle animations, expression sync, lip sync, touch response

### 🪟 Interface
- **Dual UI modes** — transparent floating widget + full panel (Tauri 2)
- **Widget ↔ Panel switching** — single-window dynamic resize via Tauri JS API; persisted across launches
- **Settings panel** — 4 sections (Memory / Basic / Character / UI 风格)
- **Mouse click-through for widget mode**

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
                └─ web search: model-native (Qwen Max / DeepSeek)
  → emotion    first sentence parses <emotion>X</emotion> → locks turn emotion
  → TTS        get_tts_engine(voice_model) → CosyVoice / Edge / SoVITS
  → Output:    streamed text chunks + per-sentence audio chunks + asr_result preview

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

## Roadmap

See [**ROADMAP.md**](ROADMAP.md) for the full prioritized roadmap.

**TL;DR — the next moves:**

- **v3 finish (Tier 1, 1–3 weeks)**: Live2D + emotion frontend wiring, voice interrupt, TTS preprocessor + concurrency, Live2D touch response
- **v4 (Tier 2, 1–2 months)**: screen awareness (active + passive + VLM), AI inner monologue, natural-language cron, character status panel + growth system, GPT-SoVITS local
- **v5+ (Tier 3, long-term)**: multi-device access (Windows client), autodl deployment, sub-agent isolation for long tasks, Hermes-style skill accumulation

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
| v3-D: emotion system (backend) | ✅ done (frontend wiring waits for Live2D) |
| v3 remaining: Live2D + voice interrupt + TTS UX + life-tools layer | 🚧 in progress |
| v4: Screen awareness | 📋 planned |
| v5+: Multi-device / cloud deployment | 📋 long-term |

---

## License

Currently **All rights reserved** (no LICENSE file). Will switch to a permissive license (MIT or Apache 2.0) when the repo goes public — note: any Live2D models bundled later will carry their own Live2D Inc. licenses, which are *not* covered by Skyler's eventual project license.

---

## Contributing

Not currently accepting external contributions while the project is in private development. See you when we go public.
