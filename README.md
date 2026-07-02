<!-- English README — mirror of README_zh-CN.md.
     Single source of truth for product framing is the Chinese version; this file
     mirrors content for international visitors. Don't add features here that
     aren't in the CN version, and vice versa. -->

# 🌸 Skyler

> A continuity-driven Live2D desktop AI companion system.

![Python](https://img.shields.io/badge/Python-3.10+-blue) ![FastAPI](https://img.shields.io/badge/FastAPI-async-green) ![Tauri](https://img.shields.io/badge/Tauri-2.0-orange) ![React](https://img.shields.io/badge/React-18-61DAFB) ![Platform](https://img.shields.io/badge/platform-macOS-lightgrey)

🌐 **Languages**: **English** · [简体中文](README_zh-CN.md) · Originally MomoOS, renamed Skyler in 2026-05.

---

## What is Skyler?

Skyler is a continuity-driven Live2D desktop AI companion system.

It is not a Q&A chatbot with a character skin. Skyler is built around structured Persona, persistent character state, four memory/context layers, an activity timeline, and multi-source context assembly so a character can accumulate state over time and develop a rhythm and a sense of life.

Skyler has two desktop forms: a full panel for conversations, character management, and capability configuration, and a transparent desktop-pet window for low-friction companionship, proactive check-ins, and desktop context awareness. Live2D rendering, model management, and framing controls are already wired in; appearance, voice, persona, and capabilities can be configured separately.

The current local code supports text, voice, image, and file input. The voice path covers VAD, ASR, LLM streaming, TTS, and Live2D performance. Images and files can enter the current model turn as context, but long-term persistence and memory consolidation for attachments are still in progress.

Desktop perception is currently based on read-only macOS AX / UI Tree: Skyler can read structured context such as the foreground app, window title, visible UI text, and browser content. Active visual perception is still under construction; the planned direction is a small resident model that watches for changes and, when needed, sends the current window or a local crop to an image-capable model.

DailyAgent is also still being built. Stage 1 is connected today: daily plan generation, a current-activity ticker, and state write-back. The next step is turning that into a fuller daily rhythm system for characters.

Skyler is local-first, not a promise of being fully offline. Conversation history, character state, memory, and activity data are held locally in SQLite/files, while LLM / TTS / ASR providers can be swapped between cloud and self-hosted services.

*(Honest note: this is a one-person project, currently validated primarily on macOS Apple Silicon.)*

---

## A glimpse

<!-- TODO: real screenshots under docs/assets/. A Live2D-driven product README has to be visual. -->

| Floating-glass companion mode | Character gallery / detail |
|---|---|
| ![companion](docs/assets/companion.png) | ![gallery](docs/assets/gallery.png) |

| Main chat + Live2D | MCP / capabilities |
|---|---|
| ![chat](docs/assets/chat.png) | ![mcp](docs/assets/mcp.png) |

> How the project grew (version × feature evolution) → [docs/EVOLUTION.md](docs/EVOLUTION.md).

---

## Recent updates (2026-06)

> Full capability status → [ROADMAP.md](ROADMAP.md); version evolution → [docs/EVOLUTION.md](docs/EVOLUTION.md).

- **2026-06-21** · Desktop awareness (read-only) shipped — character can read the foreground window's UI tree (macOS AX) and answer from evidence; read-only. Write-action capability is built but the confirm gate isn't verified yet — recommend keeping it off manually until it is.
- **2026-06-21** · Chat experience: deep-thinking / web-search dual toggle + bubble local-time stamp — chat box + settings entry, default fast (thinking off), flip on when you want depth; local-time tag under each bubble.
- **2026-06-20** · Glass-skin customizer + character-detail center Build 1 — companion-mode glass widget auto-tunes contrast to wallpaper, persists across theme switch; gallery surfaces persona / mood / state and lets you edit persona inline.
- **2026-06-17** · Local voice via GSV migration — self-trained `mai_v4` + 16 emotions moved from cloud onto a LAN-local box; inference no longer crosses the public internet.

---

## What makes it different

### 1. Continuity first: a persistent "self" for the character (core)

This is where Skyler actually puts effort — and the part hardest to copy. Most companion chatbots re-invent their mood, current activity, and how today's going on every turn. Skyler treats the character as **an entity with persistent inner state**:

- **Persona (who she is)** — structured character cards and variants: identity, personality, speech style, boundaries, examples, and lore instead of one large prompt blob.
- **card_type (what kind of card she is)** — social cards emphasize daily conversation, relationship, and emotional expression; assistant cards emphasize tasks, tools, and behavioral boundaries. The base chain is wired; runtime policy separation is still evolving.
- **Persistent state (how she is now)** — mood / intimacy / current_thought / current_activity are maintained in the state layer and read as input, not invented on every turn.
- **Four memory/context layers** — short-term window, conversation summary, long-term semantic memory, and user-profile / activity / state context are assembled into the prompt.
- **DailyAgent Stage 1** — daily plan generation, current-activity ticker, and state write-back are connected; full FSM behavior, multi-character scheduling, and richer daily rhythm are in progress.

In a line: take "who I am and what kind of day I'm having" out of the LLM's unreliable improvisation and put it into persistent state and context.

> *Current status: structured Persona, base card_type wiring, state fields, `<state_update>`, activity timeline, and DailyAgent Stage 1 are present in local code. **In progress**: full FSM behavior, multi-character DailyAgent, stronger context arbitration, attachment memory consolidation, and stricter safety boundaries.*

### 2. A composable capability registry

Each built-in capability registers with a single `@register_capability` line; built-in tools (calendar / clipboard / screen awareness), external MCP servers, and your own skills are **fully peer**, the LLM can't tell them apart. New skill = 5 lines of code; new MCP server = one config entry.

### 3. Safe by design (gates for an agent that can act)

The capability registry covers both native capabilities and MCP tools uniformly; write / mutating tools go into `dangerous_tools` with a confirm gate before invocation; desktop control **separates read from write** — reading the UI tree is safe; write-action capability is built but the confirm gate hasn't been verified end-to-end yet, so keep it off manually until it has. When an agent can call external tools and read or control your desktop, this layer is a requirement, not decoration.

---

## Honest positioning

Skyler sits in the gap between two mature projects:

- **[Open-LLM-VTuber](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber)** — a polished, install-and-go VTuber companion app. Want something ready-made? Pick that — it's more mature than Skyler.
- **[Hermes Agent](https://github.com/NousResearch/hermes-agent)** (Nous Research) — a server-side personal-agent platform with a self-improving skill loop. Want a pure agent platform? It's more specialized.

Skyler aims at the space neither occupies: **desktop, character-driven, hackable down to the agent core, ownership stays with you**. The architecture choices follow from that gap — not from copying anyone's feature list.

**Where Skyler is honestly still short**: one-person project; primarily validated on macOS; only Mai has a complete persona right now; packaging (dmg / auto-update) not done; long-term memory quality awaiting on-device regression. For a finished feel, the two above are steadier; Skyler's value is in that **hackable + character-mechanism** gap.

---

## What it can do (overview)

> Which items are 🟢 verified / 🟡 in progress / ⚪ planned — see [ROADMAP § Current Capability Status](ROADMAP.md). This is just the broad strokes.

- **Two desktop forms** — full panel + transparent desktop-pet window; the panel is for deep interaction and configuration, the widget is for low-friction companionship and context awareness.
- **Interaction chain** — text, voice, image, and file input for the current turn; voice covers VAD / ASR / LLM streaming / TTS / Live2D performance.
- **Persona / character cards** — structured Persona, variants, and base card_type wiring; social / assistant cards have a foundation, but not a finished character ecosystem yet.
- **State and memory** — mood / intimacy / current_thought / current_activity; short-term window, conversation summary, long-term semantic memory, user profile, and activity context.
- **Activity / proactive companion** — activity timeline + prompt injection; early proactive triggers with idle gate / throttle / daily cap / active-conversation guard.
- **DailyAgent** — Stage 1 connects daily plan generation, current-activity ticker, and state write-back; full FSM / multi-character scheduling is in progress.
- **Desktop perception** — read-only AX / UI Tree for foreground app, window title, visible UI text, and browser content; screenshot-style visual understanding is still under construction.
- **Live2D** — rendering, idle motion, head-follow, blink/breathe, lipsync, multi-model management, and framing.
- **Tools / MCP** — CapabilityRegistry, MCP client/server, per-tool switches, provider replacement, and a confirm-gate framework; dangerous-tool end-to-end validation and credential governance are still being hardened.
- **Observability** — usage / resource / boot-time monitoring + anomaly highlight.

> Only Mai has a complete persona today; a second independent character is being built (Live2D model in place; persona / voice / portrait to follow). The rest are skeletons (filling in one at a time).

---

## How to run it

### Quick start (macOS)

Prereq: Node 18+ (22+ recommended) · Rust 1.75+ · Xcode CLT · Python 3.10+.

```bash
git clone <your-repo-url> Skyler && cd Skyler

# Backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # fill at least DASHSCOPE_API_KEY
uvicorn backend.main:app --reload   # http://127.0.0.1:8000

# Frontend (separate terminal)
cd frontend && npm install && npm run tauri dev
# First Rust build: 5–15 min, fast after that
```

Default LLM is Qwen via DashScope (no proxy required from inside CN). Switch provider in one config line — internals route through LiteLLM, so DeepSeek / OpenAI / Anthropic / local Ollama all work.

### Extending Skyler (four paths)

1. **Add a skill** — drop a file under `backend/capabilities/`, decorate a function; restart, and the LLM can call it.
2. **Connect an external MCP server** — add an entry to `config.yaml`, restart; tools auto-discovered and registered as `ext.<server>.<tool>` capabilities.
3. **Swap a Live2D model** — drop assets under `frontend/public/live2d/<slug>/`, bind it via CharacterPanel. Cubism 4 only.
4. **Swap the LLM** — one field in `config.yaml`, any LiteLLM-supported provider.

### Architecture at a glance

```
User input (voice / text) → ASR (local Whisper)
  → ChatAgent: context assembly + LiteLLM tool calling
      ├─ Short-term memory: (user, character, conversation) three-level isolation
      ├─ Memory tools (LLM-driven save/recall)
      ├─ Capabilities = @register_capability → ToolRegistry (extensible via MCP)
      └─ Web search (model-native)
  → Emotion parsing → TTS (CosyVoice/Fish/GSV)
  → Streaming text + per-sentence audio (delivered to originating conversation)
```

Three foundations: **capability registry** (decorator → singleton, schema auto-exported) · **bidirectional MCP** (client + server) · **persona-level state** (`character_states` + `<state_update>` tag protocol). Why each layer is shaped the way it is → [DESIGN_LITE.md](DESIGN_LITE.md) (design source of truth).

---

## Roadmap

Full → [ROADMAP.md](ROADMAP.md). In a line:

- **Now** — demo video, documentation refresh, and local capability positioning.
- **Next** — full DailyAgent FSM / multi-character scheduling, stronger context arbitration, attachment memory consolidation, active visual perception, and end-to-end validation of desktop write-action confirmation.
- **Later** — AX + vision-model fusion, richer multi-character collaboration, long-term autonomy, Live2D AI director, packaging / dmg / auto-update.

---

## License

Code is currently **All rights reserved** (no LICENSE file); on public release will switch to a permissive license (MIT / Apache 2.0).

**Live2D models are separate** — the development build bundles the official Hiyori sample (Live2D Free Material License, small-scale commercial OK; mid/large enterprise commercial use requires written authorization from Live2D Inc.) plus a Yae demo skin (per its upstream license). Future builds will switch to owned / commissioned models; those will remain under their own licenses and are **not** covered by the Skyler project license. Any assets you add yourself, you're responsible for licensing.

---

## Deeper reading

- [DESIGN_LITE.md](DESIGN_LITE.md) — design source of truth, anchored to code
- [ROADMAP.md](ROADMAP.md) — current capability status + near-term plan
- [docs/EVOLUTION.md](docs/EVOLUTION.md) — version × feature evolution matrix
- [docs/research/persona-schema-comparison.md](docs/research/persona-schema-comparison.md) — persona-card schema research (vs SillyTavern)
- [docs/design/character-mechanism.md](docs/design/character-mechanism.md) — character-mechanism design seed
- [docs/design/dailyagent-plan.md](docs/design/dailyagent-plan.md) — DailyAgent (Brick 2) full design
- [docs/design/desktop-control.md](docs/design/desktop-control.md) — desktop awareness / control roadmap
- [docs/PM-CC-PROTOCOL.md](docs/PM-CC-PROTOCOL.md) — how I work with Claude Code
