<!-- English README — mirror of README_zh-CN.md.
     Single source of truth for product framing is the Chinese version; this file
     mirrors content for international visitors. Don't add features here that
     aren't in the CN version, and vice versa. -->

# 🌸 Skyler

> A sculptable desktop AI character container — bring your own LLM, your own Live2D model, your own MCP tools. The agent core gives you a foundation; what it becomes is yours to shape.

![Python](https://img.shields.io/badge/Python-3.10+-blue) ![FastAPI](https://img.shields.io/badge/FastAPI-async-green) ![Tauri](https://img.shields.io/badge/Tauri-2.0-orange) ![React](https://img.shields.io/badge/React-18-61DAFB) ![Platform](https://img.shields.io/badge/platform-macOS-lightgrey)

🌐 **Languages**: **English** · [简体中文](README_zh-CN.md) · Originally MomoOS, renamed Skyler in 2026-05.

---

## What is Skyler?

Skyler is a Live2D AI companion that lives on your desktop. What sets her apart from packaged VTuber apps is that she **isn't a stateless chat box** — she has a persona, a mood, recent thoughts, and an intimacy level with you that persist across sessions; she'll reach out on her own at the right moments, notice what you're doing on screen and bring it into conversation, and the avatar moves with what she says. The direction of the whole project is to make her **an actual character with her own inner state, living her own day** — not a tool that starts from zero on every turn.

The base layer is **a container built for you to modify**: the core, capability registry, and proactive companion layer are the foundation; every capability, every external integration, every character asset can be swapped — no layer is locked. Models, voice, conversation history all stay on your machine (local SQLite + local embeddings, no cloud dependency), nothing goes off-box.

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

### 1. Character mechanism: a persistent "self" for the character (core)

This is where Skyler actually puts effort — and the part hardest to copy. Most companion chatbots re-invent their mood, current activity, and how today's going on every turn — they drift, contradict themselves. Skyler treats the character as **an entity with persistent inner state**, in four layers:

- **Persona (who she is)** — five-layer prompt framework + multi-variant schema (Tier-1 identity / personality / voice + Tier-2 taboo / lore / emotion triggers), not a wall of free text.
- **Persistent state (how she is now)** — mood / intimacy / current activity, maintained in a state layer that the model reads as **input**, not improvised each turn.
- **DailyAgent (what kind of day she's having)** — gives the character a coherent daily routine, so "what she's doing" has continuity instead of being fabricated on the fly.
- **Context arbitration (turning state into reaction)** — composes inner state + your input into the response she should have right now.

In a line: take "tracking who I am, what kind of day I'm having" off the LLM's unreliable improvisation and put it on a persistent, rule-governed state layer.

> *Current status: persona system (Mai complete, second persona slot in progress) + persistent state fields + `<state_update>` + state-aware proactive engine already running. **In progress**: actually feeding state back into generation + DailyAgent + context arbitration — upgrading the layer from "log-only" to "state-driven." This character-mechanism track is the core direction of the project.*

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

- **Conversation** — voice (VAD auto / manual) + text, sentence-by-sentence streaming; multi-character conversation anchoring, switching characters doesn't cross wires or drop replies; deep-thinking / web-search dual toggle.
- **Voice (TTS)** — self-trained voice (GPT-SoVITS `mai_v4` + 16 emotions) + multi-provider (CosyVoice / Fish); voice can be Chinese / Japanese, text and voice languages decoupled; local Whisper ASR.
- **Memory** — short-term (user / character / conversation) three-level isolation + rolling summary + long-term fact extraction (forgetting curve + tombstones) + cross-character user profile + activity timeline.
- **Proactive companion** — scheduled greetings + screen-aware conversation starters; multi-layer throttle + idle gate, shuts up when you walk away.
- **Desktop awareness** — reads the foreground window's UI tree (macOS AX, read-only) and answers from what's actually on screen.
- **Live2D** — performance layer (idle micro-motion / head-follow / blink-breathe / lipsync) + multi-model swap + composable framing.
- **Tools / MCP** — built-in calendar (Apple + Google) / NetEase Music / Bilibili / docs / clipboard / Xiaohongshu (read-only) / Notion + connect any external MCP server; dangerous operations confirm-gated.
- **Multi-modal** — file input / output; image input (read depends on the active model's multi-modal capability, no persistence yet).
- **Interface** — main window / transparent desktop pet, two modes + 8 themes + floating-glass companion mode (contrast customizable) + boot animation + character gallery.
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

- **Now** — v4.0.0 wrap-up (long-term memory on-device regression → packaging release)
- **Next** — demo video · character mechanism (state read-back + DailyAgent) · image-input persistence · desktop write-action confirm gate · seven-character real personas · memory architecture v2 + RAG
- **Later** — context arbitration · persona-level learning · screen VLM · Live2D AI director · Cubism5

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
