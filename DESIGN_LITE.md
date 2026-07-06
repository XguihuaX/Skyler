# Skyler Design Lite

This is the short design note for the current local codebase. It is not a
marketing document and it does not replace source code.

## Project shape

Skyler is a Live2D desktop AI companion system. The main design choice is to
make the character stateful before making it more agentic.

The project is built around:

- structured Persona;
- runtime character state;
- memory and activity context;
- Live2D + voice expression;
- desktop presence through a main panel and a floating window;
- tools exposed through a capability layer.

## Main design principle

The character should not be rebuilt from a prompt on every turn.

A turn should have access to:

- who the character is;
- what kind of card it is;
- how the character is currently doing;
- what has happened recently;
- what the user is asking now;
- what tools or screen evidence are available.

This is why Persona, `CharacterState`, memory, activity context, and capabilities
are separate layers instead of one large prompt string.

## UI forms

Skyler has two desktop forms.

### Main panel

The main panel is for deeper interaction:

- full chat;
- history;
- character details;
- Persona editing;
- provider and capability settings;
- Live2D management.

### Desktop-pet window

The floating window is for low-friction presence:

- transparent Live2D window;
- idle animation;
- brief message bubbles;
- voice / VAD state;
- quick controls.

The two forms share the same character, state, and context. They should not be
treated as separate character instances.

## Persona and card type

Persona is structured because a single prompt blob is hard to maintain.

Current Persona fields include Tier-1 style fields such as identity,
personality core, speech style, relationship, voice samples, and forbidden
phrases. Extended fields include taboo topics, lore, and capability overrides.

`card_type` is the first split between social cards and assistant cards.

- Social cards lean toward companionship, relationship, and emotional expression.
- Assistant cards lean toward task positioning, tool capability, and behavior
  boundaries.

The schema, API, editor path, and prompt path are connected. Full runtime policy
separation is still in progress.

## Character state

`CharacterState` stores runtime state such as:

- mood;
- intimacy;
- current thought;
- current activity;
- last interaction time.

The model can read state through the prompt and can write updates through a
`<state_update>` protocol. This is intentionally simple: the state layer is
there to make the character less forgetful and less improvised, not to pretend
that a full mental model is finished.

## Memory and context

The current memory/context stack should be described by its real sources:

- short-term conversation window;
- conversation summary;
- long-term semantic memory;
- user profile;
- activity context;
- current character state.

It is okay to call this "four-layer memory" in demo wording, but the detailed
docs should name the actual sources above. Do not invent a separate memory
architecture that is not in code.

## Activity context

ActivityWatcher records what the user has recently been doing on the computer:

- foreground app;
- browser URL/title;
- document path;
- activity sessions.

ActivityTimeline stores this locally in `activity_sessions` and can format a
daily activity summary for the ChatAgent prompt.

This gives the character background context. It is different from reading the
current screen structure.

## Layered Desktop Perception

The current desktop perception design is layered.

### Built

- ActivityWatcher and ActivityTimeline provide recent activity context.
- `screen.read_current_screen` reads the current foreground app's AX / UI Tree
  summary on demand.
- The current default is intentionally narrow: foreground app, read-only,
  on-demand.

This default exists to control token use, latency, and privacy risk. Skyler
should not continuously read every window by default.

### In progress

The next layer is:

- Window Roster: maintain an app / window / PID roster.
- Watchlist: maintain user-authorized or context-relevant targets.
- On-demand Deep Read: if a target still exists, changes, or the user asks about
  it, read that target PID with AX / UI Tree.

If structured UI information is not enough, the later fallback is screenshot or
local-crop visual understanding. That is not the same thing as user-uploaded
image input.

## DailyAgent

DailyAgent is not complete yet.

Current Stage 1 includes:

- daily plan generation;
- current-activity ticker;
- writing current activity back into character state.

The next steps are a clearer FSM, stronger context judgement, and multi-character
scheduling.

## Capability layer

Capabilities are registered through a common registry instead of being hardcoded
inside the chat loop.

Current pieces:

- `CapabilityRegistry`;
- native Python capabilities;
- MCP client for external tools;
- MCP server for exposing Skyler capabilities;
- provider configuration;
- per-tool switches;
- confirm-gate framework.

Dangerous tools and write actions still need end-to-end validation. The design
should assume that any mutating action requires explicit confirmation and
credential governance.

## Voice and Live2D

The current voice chain covers:

- VAD;
- ASR;
- LLM streaming;
- TTS;
- Live2D lipsync / expression hooks.

Emotional TTS can use character state. Live2D motion selection and a full action
library are future work, not current capability.

## What not to overstate

Do not describe these as finished:

- full DailyAgent FSM;
- full social / assistant runtime split;
- continuous VLM screen monitoring;
- reading all windows in the background;
- write-action safety fully verified end to end;
- multi-character collaboration;
- long-term autonomy;
- Live2D motion planning;
- Anime asset generation;
- ComfyUI workflow integration.

## Code vocabulary

Use these terms consistently:

- Persona
- card_type
- CharacterState
- ActivityWatcher
- ActivityTimeline
- Layered Desktop Perception
- Window Roster
- Watchlist
- On-demand Deep Read
- CapabilityRegistry
- MCP
- Confirm Gate
