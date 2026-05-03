"""Per-user character state and system-prompt assembly.

Characters are loaded once at import time from characters.yaml.
Each user independently tracks their active character; switching is instant
and requires no DB round-trip.
"""
import logging
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict

import yaml

from backend.config.prompts import BASE_INSTRUCTION

logger = logging.getLogger(__name__)

_YAML_PATH = Path(__file__).parent / "characters.yaml"


def _load_characters() -> tuple[Dict[str, Any], str]:
    """Parse characters.yaml and return (characters_dict, default_character_id)."""
    with open(_YAML_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    characters: Dict[str, Any] = data.get("characters", {})
    default: str = data.get("default_character", "默认")
    if not characters:
        raise RuntimeError(f"characters.yaml has no 'characters' entries: {_YAML_PATH}")
    return characters, default


_CHARACTERS, _DEFAULT_CHARACTER = _load_characters()


def _build_system_prompt(character_id: str) -> str:
    """Combine persona + BASE_INSTRUCTION into the system prompt for *character_id*."""
    cfg = _CHARACTERS.get(character_id) or _CHARACTERS.get(_DEFAULT_CHARACTER, {})
    persona: str = cfg.get("persona", "")
    return f"{persona}\n\n{BASE_INSTRUCTION}" if persona else BASE_INSTRUCTION


class PromptManager:
    """Tracks each user's active character and builds the corresponding system prompt."""

    def __init__(self) -> None:
        self._user_characters: defaultdict[str, str] = defaultdict(
            lambda: _DEFAULT_CHARACTER
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_prompt(self, user_id: str) -> dict:
        """Return prompt metadata for *user_id*'s current character.

        Returns a dict with keys:
          character_id    — active character name
          system_prompt   — full system prompt (persona + BASE_INSTRUCTION)
          default_emotion — emotion label for TTS (passed to SoVITS)
        """
        character_id = self._user_characters[user_id]
        cfg = _CHARACTERS.get(character_id, _CHARACTERS.get(_DEFAULT_CHARACTER, {}))
        logger.debug("get_prompt: user=%s character=%s", user_id, character_id)
        return {
            "character_id": character_id,
            "system_prompt": _build_system_prompt(character_id),
            "default_emotion": cfg.get("default_emotion", ""),
        }

    def switch_character(self, user_id: str, character_id: str) -> bool:
        """Switch *user_id* to *character_id*.

        Returns True on success, False if *character_id* is not registered.
        """
        if character_id not in _CHARACTERS:
            logger.warning(
                "switch_character: unknown character '%s' for user %s",
                character_id, user_id,
            )
            return False
        self._user_characters[user_id] = character_id
        logger.info("switch_character: user=%s -> %s", user_id, character_id)
        return True

    def get_current_character(self, user_id: str) -> str:
        """Return the name of *user_id*'s currently active character."""
        return self._user_characters[user_id]

    @staticmethod
    def list_characters() -> list[str]:
        """Return all registered character IDs."""
        return list(_CHARACTERS.keys())


prompt_manager = PromptManager()
