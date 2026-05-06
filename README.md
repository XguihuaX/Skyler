# 🌸 Skyler

> A local-first AI companion that lives on your desktop — Galgame-style avatar on the outside, full-stack life & tools agent on the inside.

![Python](https://img.shields.io/badge/Python-3.10+-blue) ![FastAPI](https://img.shields.io/badge/FastAPI-async-green) ![Tauri](https://img.shields.io/badge/Tauri-2.0-orange) ![React](https://img.shields.io/badge/React-18-61DAFB) ![Platform](https://img.shields.io/badge/platform-macOS-lightgrey) ![Status](https://img.shields.io/badge/status-v3--WIP-yellow)

> **Status (May 2026)**: v2.7 backend & UI complete · v3-A/B/C/D + **v3-E1 + v3-E2 + v3-G' + v3-G chunk 0 (Capability Registry foundation)** done (~92% of v3) · Hiyori / Yae Miko Live2D rendering, seven-voice CosyVoice picker with real emotion control on the two instruct-aware voices (longanhuan / longanyang), all future tools register through `@register_capability` (Time + n8n webhook receiver shipped) · next up: v3-G chunk 1+ (clipboard / daily briefing / cron NL scheduling) → v3-F' proactive dialogue.
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
| v3-F': proactive dialogue + time awareness | 📋 planned |
| v3-G: life & tools layer (clipboard / daily briefing / cron / growth) | 📋 planned |
| v3-G': TTS UI + cosyvoice instruct emotion | ✅ done (5 commits + 2 patches, 2026-05-06) — SSML reverted, instruct path canonical, instruction string locked to strict no-whitespace format, longanyang male voice added; Phase 2 (custom voice cloning) 📋 pending |
| v3-G chunk 0: Capability Registry + cron + n8n webhook receiver | ✅ done (3 commits, 2026-05-06) — `@register_capability` is the canonical registration for all future tools; CapabilityPanel renders categorized cards in settings; APScheduler cron runs alongside the existing alarm scheduler; `/api/webhooks/n8n/{trigger_name}` accepts external workflow triggers behind Bearer + HMAC auth |
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
