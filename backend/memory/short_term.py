"""Per-user in-memory short-term conversation store.

Holds up to SHORT_TERM_MAX turns per user. Long-term promotion happens via
the LLM-driven save_memory tool in backend/agents/chat.py rather than a
standalone summariser.
"""
from typing import Dict, List


SHORT_TERM_MAX: int = 50


class ShortTermMemory:
    def __init__(self) -> None:
        self._store: Dict[str, List[dict]] = {}

    async def add(self, user_id: str, role: str, content: str) -> None:
        """Append a turn to the user's short-term buffer."""
        if user_id not in self._store:
            self._store[user_id] = []
        self._store[user_id].append({"role": role, "content": content})

    async def get(self, user_id: str) -> List[dict]:
        """Return all turns for the user in chronological order."""
        return list(self._store.get(user_id, []))

    async def count(self, user_id: str) -> int:
        """Return the number of stored turns for the user."""
        return len(self._store.get(user_id, []))

    async def trim(self, user_id: str, keep: int) -> None:
        """Keep only the most recent *keep* turns, discarding the rest."""
        buf = self._store.get(user_id)
        if buf is not None:
            self._store[user_id] = buf[-keep:]

    async def clear(self, user_id: str) -> None:
        """Remove all stored turns for the user."""
        self._store.pop(user_id, None)


short_term_memory = ShortTermMemory()
