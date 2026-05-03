"""Long-term memory: SQLite persistence + local embedding-based retrieval.

Embeddings are generated with sentence-transformers using a lightweight
multilingual model that runs entirely on CPU without GPU requirements.
Retrieval uses cosine similarity across all memories for a given user.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import List, Optional

import numpy as np
from sentence_transformers import SentenceTransformer

from backend.database import AsyncSessionLocal
from backend.database.services import add_memory, get_all_memories
from backend.database.models import Memory


_MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"
_model: Optional[SentenceTransformer] = None
_executor = ThreadPoolExecutor(max_workers=1)


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(_MODEL_NAME)
    return _model


async def preload() -> None:
    """Eagerly load the sentence-transformer model in a worker thread."""
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(_executor, _get_model)


async def _encode(text: str) -> np.ndarray:
    """Run model.encode() in a thread so the event loop stays unblocked."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        _executor,
        lambda: _get_model().encode(text, normalize_embeddings=True).astype(np.float32),
    )


async def generate_embedding(text: str) -> bytes:
    """Encode *text* with the shared sentence-transformer and return raw bytes.

    Shared by POST /memory/add and PATCH /memory/{id} so embedding generation
    stays consistent across insert and update paths.
    """
    vec = await _encode(text)
    return vec.tobytes()


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    denom = np.linalg.norm(a) * np.linalg.norm(b) + 1e-8
    return float(np.dot(a, b) / denom)


async def add_memory_with_embedding(
    user_id: str,
    content: str,
    type: str,
    role: str,
    expires_at: Optional[datetime] = None,
) -> None:
    """Encode *content* and persist a memory row with the resulting embedding.

    Args:
        expires_at: Optional expiry datetime.  Pass None (default) for
                    permanent memories; set a future datetime for transient
                    states (e.g. "currently studying for exams → 7 days").
    """
    embedding_blob = await generate_embedding(content)

    async with AsyncSessionLocal() as session:
        await add_memory(
            session,
            user_id=user_id,
            role=role,
            type=type,
            content=content,
            embedding=embedding_blob,
            expires_at=expires_at,
        )


async def search_relevant_memories(
    user_id: str,
    query: str,
    top_k: int = 5,
    character_id: Optional[int] = None,
) -> List[Memory]:
    """Return the *top_k* memories most semantically similar to *query*.

    Memories without a stored embedding are silently skipped.
    Result order is descending similarity (most relevant first).
    When *character_id* is provided, only memories tagged with that character
    are eligible — keeps long-term retrieval isolated per persona.
    """
    async with AsyncSessionLocal() as session:
        all_memories: List[Memory] = await get_all_memories(
            session, user_id, character_id=character_id,
        )

    if not all_memories:
        return []

    query_vec = await _encode(query)

    scored: List[tuple[float, Memory]] = []
    for mem in all_memories:
        if not mem.embedding:
            continue
        mem_vec = np.frombuffer(mem.embedding, dtype=np.float32)
        score = _cosine(query_vec, mem_vec)
        scored.append((score, mem))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [mem for _, mem in scored[:top_k]]
