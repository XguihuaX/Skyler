# Skyler Roadmap

This roadmap reflects the current local codebase, not the older public README.

Status definitions:

- **Built**: the local code path is connected and usable for demo / dogfood.
- **In progress**: the foundation exists, but the behavior, safety, or product
  loop is not complete.
- **Planned**: a design direction only. Do not describe it as current behavior.

## Built

### Desktop UI

- Full main panel for chat, history, character management, capability settings,
  and app configuration.
- Transparent desktop-pet window for low-friction companion presence.
- Live2D rendering, model scanning, model management, framing, idle motion,
  blink / breathe, and lipsync hooks.

### Interaction

- Text input.
- Voice input through Silero VAD or manual recording.
- ASR, LLM streaming, TTS, and Live2D expression hooks.
- Image and file input for the current model turn.
- Attachment inputs are not yet a mature long-term memory system.

### Character system

- `character_personas` schema and active variant.
- Structured Persona fields such as identity, personality core, speech style,
  relationship, voice samples, forbidden phrases, taboo topics, lore, and
  capability overrides.
- Persona loading into the character prompt.
- `card_type` foundation for social cards and assistant cards.
- Assistant-card specific fields are present in the prompt path, but full
  runtime policy separation is still in progress.

### State and memory context

- `CharacterState`: mood, intimacy, current thought, current activity, and
  interaction timestamps.
- `<state_update>` write-back from model output.
- Short-term conversation window.
- Conversation summary.
- Long-term semantic memory.
- User profile context.
- Activity context.

### Activity context

- ActivityWatcher records foreground app, browser URL/title, document path, and
  activity sessions.
- ActivityTimeline writes local `activity_sessions`.
- Activity summaries can be injected into the ChatAgent prompt.
- Early proactive triggers exist, with idle gate, throttle, daily cap, and active
  conversation guard.

### DailyAgent Stage 1

- Daily plan generation.
- Current-activity ticker.
- State write-back into `current_activity`.
- This is Stage 1, not a complete FSM.

### Desktop perception

- Read-only AX / UI Tree summary for the current foreground app.
- The default strategy is on-demand foreground-app reading, mainly to control
  token use, latency, and privacy risk.
- The current implementation should not be described as continuous monitoring of
  all windows.

### Capability layer

- `CapabilityRegistry`.
- Native capability registration.
- MCP client for external tools.
- MCP server exposing Skyler capabilities.
- Per-tool switches.
- Provider replacement for LLM / TTS paths.
- Confirm-gate framework.

## In progress

- Full DailyAgent FSM.
- Multi-character DailyAgent scheduling.
- Runtime strategy split between social cards and assistant cards.
- Better context arbitration across persona, memory, activity, screen context,
  user message, and tool results.
- Window Roster: lightweight app / window / PID roster.
- Watchlist: user-authorized or context-relevant targets.
- Target-PID AX / UI Tree deep read when a watched target still exists, changes,
  or the user asks about it.
- Screenshot or local-crop visual understanding when structured UI information
  is not enough.
- End-to-end validation for dangerous tools and write-action confirmation.
- Credential handling and dangerous-tool governance.
- Long-term persistence and memory consolidation for image / file inputs.
- More complete Persona content for multiple characters.
- Release packaging and update flow.

## Planned

- AX + visual model fusion.
- Continuous visual perception with clear privacy and consent boundaries.
- Multi-character collaboration.
- Long-term autonomous behavior.
- Live2D AI director: expression / motion / action planning.
- Character asset generation pipeline.
- ComfyUI workflow integration.
- Stronger memory architecture and regression tests.
- DMG packaging and auto-update.

## Demo wording boundaries

Safe to say:

- Skyler has a full panel and desktop-pet window.
- Skyler has text, voice, image, and file input for the current turn.
- Persona, `card_type`, and `CharacterState` are connected.
- ActivityWatcher / ActivityTimeline provide local activity context.
- AX / UI Tree is read-only and on demand for the current foreground app.
- MCP / API capabilities are connected through a registry-style capability layer.

Do not say:

- DailyAgent is a complete FSM.
- Skyler continuously reads every window.
- Full VLM screen monitoring is done.
- Write actions are fully safe end to end.
- Social / assistant cards already have complete runtime policy separation.
- Image / file inputs are fully consolidated into long-term memory.
- Multi-character collaboration or long-term autonomy is complete.

## Suggested next order

1. Finish the demo video and keep the wording honest.
2. Harden DailyAgent Stage 1 into a clearer FSM.
3. Add Window Roster and Watchlist before deeper screen perception.
4. Validate dangerous-tool confirmation end to end.
5. Improve card-type runtime behavior.
6. Package a stable macOS build.
