"""Long-term memory: SQLite persistence + local embedding-based retrieval.

Embeddings are generated with sentence-transformers using a lightweight
multilingual model. Retrieval uses cosine similarity across all memories for
a given user.

v3.5 chunk 9 Part 0：性能加固（零风险三项）
-----------------------------------------

1. **跳过短输入**：``len(query.strip()) < short_input_threshold``（默认 10）
   直接返 ``[]`` —— 短问候 / 单字命令 / 标点等向量检索零价值，省 10-30ms
   encode + per-memory cosine 时间。
2. **embedding LRU + TTL 缓存**：``cache_size=100`` / ``cache_ttl=300s``。
   user 重发同一短语 / proactive trigger 重用 trigger text 时直接命中
   缓存，0ms 取回。
3. **device 选择**：``auto`` / ``cpu`` / ``mps``。auto 在 macOS Apple
   Silicon 自动选 mps，否则 cpu。

详见 ``config.yaml memory.embedding`` 段 + ``backend/config/__init__.py``
四个 ``get_embedding_*`` 函数。

# Timing instrumentation

``[TIME]`` 前缀日志：``embedding_encode`` / ``cache_hit`` / ``cosine`` /
``search_total``。便于 audit + 验收持续监控。
"""
import asyncio
import logging
import math
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import List, Optional

import numpy as np
from sentence_transformers import SentenceTransformer
from sqlalchemy import text

from backend.config import (
    get_embedding_cache_size,
    get_embedding_cache_ttl_seconds,
    get_embedding_device,
    get_embedding_short_input_threshold,
    get_forgetting_curve_age_decay,
    get_forgetting_curve_enabled,
    get_forgetting_curve_threshold,
)
from backend.database import AsyncSessionLocal, engine
from backend.database.services import add_memory, get_all_memories
from backend.database.models import Memory


logger = logging.getLogger(__name__)

_MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"
_model: Optional[SentenceTransformer] = None
_executor = ThreadPoolExecutor(max_workers=1)
_device: Optional[str] = None  # resolved at first _get_model() call


def _pick_device() -> str:
    """根据 config 与可用性选 device。

    ``auto`` → **默认 cpu**。chunk 9 Part 0 benchmark 显示对短文本编码
    （20-30 chars）cpu / mps median 几乎一致（~15-16ms），mps avg 因 cold
    JIT 反而更高 + 与 Whisper GPU 抢资源。要 mps 显式 ``device: mps``。
    显式 ``cpu`` / ``mps`` 直用（mps 不可用时 fallback cpu + warning）。
    """
    cfg = get_embedding_device()
    if cfg in ("cpu", "mps"):
        if cfg == "mps":
            # 验证 mps 可用，否则降级
            try:
                import torch
                if not torch.backends.mps.is_available():
                    logger.warning(
                        "[embedding] config device=mps but mps unavailable, "
                        "falling back to cpu"
                    )
                    return "cpu"
            except Exception:
                logger.warning(
                    "[embedding] torch import failed during mps probe, using cpu"
                )
                return "cpu"
        return cfg
    # auto: cpu（benchmark 取舍见 docstring）
    return "cpu"


def _get_model() -> SentenceTransformer:
    global _model, _device
    if _model is None:
        _device = _pick_device()
        t0 = time.perf_counter()
        _model = SentenceTransformer(_MODEL_NAME, device=_device)
        logger.info(
            "[embedding] model loaded device=%s in %.0fms",
            _device, (time.perf_counter() - t0) * 1000,
        )
    return _model


# ---------------------------------------------------------------------------
# LRU + TTL embedding cache
# ---------------------------------------------------------------------------


class _EmbeddingCache:
    """OrderedDict-based LRU with per-entry TTL.

    Thread-safety: 仅在 ``_executor`` 单线程内访问（``_encode`` 通过
    ``run_in_executor`` 串行化），无需锁。
    """

    def __init__(self) -> None:
        self._store: "OrderedDict[str, tuple[float, np.ndarray]]" = OrderedDict()

    def get(self, text: str) -> Optional[np.ndarray]:
        entry = self._store.get(text)
        if entry is None:
            return None
        ts, vec = entry
        ttl = get_embedding_cache_ttl_seconds()
        if time.time() - ts > ttl:
            # 过期 → 丢弃 + miss
            self._store.pop(text, None)
            return None
        # LRU: 命中后移到末尾（最近使用）
        self._store.move_to_end(text)
        return vec

    def put(self, text: str, vec: np.ndarray) -> None:
        size_limit = get_embedding_cache_size()
        if size_limit <= 0:
            return  # 缓存禁用
        # 已存在 → 移到末尾刷新时间戳
        self._store.pop(text, None)
        self._store[text] = (time.time(), vec)
        # 超出容量 → 弹出最久未用（头部）
        while len(self._store) > size_limit:
            self._store.popitem(last=False)

    def clear(self) -> None:
        self._store.clear()

    def stats(self) -> dict:
        return {"size": len(self._store), "limit": get_embedding_cache_size()}


_cache = _EmbeddingCache()


def _reset_cache_for_test() -> None:
    """测试钩子：清空 LRU cache + 强制下次 _get_model 重选 device。"""
    global _device
    _cache.clear()
    _device = None


async def preload() -> None:
    """Eagerly load the sentence-transformer model in a worker thread."""
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(_executor, _get_model)


async def _encode(text: str) -> np.ndarray:
    """Run model.encode() in a thread so the event loop stays unblocked.

    LRU cache: 命中即 0ms 返回；未命中则真 encode + put。
    """
    cached = _cache.get(text)
    if cached is not None:
        logger.debug("[TIME] embedding_cache_hit len=%d", len(text))
        return cached

    loop = asyncio.get_event_loop()
    t0 = time.perf_counter()
    vec = await loop.run_in_executor(
        _executor,
        lambda: _get_model().encode(text, normalize_embeddings=True).astype(np.float32),
    )
    elapsed_ms = (time.perf_counter() - t0) * 1000
    logger.debug("[TIME] embedding_encode len=%d %.1fms", len(text), elapsed_ms)
    _cache.put(text, vec)
    return vec


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


# ---------------------------------------------------------------------------
# v3.5 chunk 9 Part 4：forgetting curve score
# ---------------------------------------------------------------------------


def forgetting_curve_score(
    relevance: float,
    access_count: int,
    age_days: float,
    *,
    decay: Optional[float] = None,
) -> float:
    """score = relevance * (1 + log(1 + access_count)) / (1 + age_days * decay)

    * 同 relevance 下，被频繁召回的 entry score 更高（log 渐进，不让爆款
      永久霸榜）。
    * 老 entry score 衰减但不为 0（divisor 始终 > 1）。
    * ``decay`` 默认从 config 读 ``age_decay_factor``，测试可显式传值。
    """
    d = decay if decay is not None else get_forgetting_curve_age_decay()
    bonus = 1.0 + math.log(1 + max(0, access_count))
    decay_div = 1.0 + max(0.0, age_days) * d
    return float(relevance) * bonus / decay_div


async def _bump_access_counters(memory_ids: list[int]) -> None:
    """召回成功的 entries 更新 access_count + last_accessed_at。

    单次 UPDATE 批量处理，async-safe。
    """
    if not memory_ids:
        return
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE memory SET access_count = COALESCE(access_count, 0) + 1, "
                "last_accessed_at = :now "
                "WHERE id IN (" + ",".join(str(int(i)) for i in memory_ids) + ")"
            ),
            {"now": datetime.utcnow()},
        )


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

    v3.5 chunk 9 Part 0：``len(query.strip()) < threshold`` 直接返 ``[]``。
    短问候 / 单字命令的向量检索价值极低，省 encode + 全表 cosine 开销。
    """
    t_total = time.perf_counter()

    # ── 0. Short-input gate ────────────────────────────────────────────────
    q_stripped = (query or "").strip()
    threshold = get_embedding_short_input_threshold()
    if len(q_stripped) < threshold:
        logger.debug(
            "[TIME] search_total len=%d < threshold=%d → skip 0ms",
            len(q_stripped), threshold,
        )
        return []

    # ── 1. Load all memories for this user/character ───────────────────────
    t_sql = time.perf_counter()
    async with AsyncSessionLocal() as session:
        all_memories: List[Memory] = await get_all_memories(
            session, user_id, character_id=character_id,
        )
    sql_ms = (time.perf_counter() - t_sql) * 1000

    if not all_memories:
        logger.debug(
            "[TIME] search_total no_memories sql=%.1fms total=%.1fms",
            sql_ms, (time.perf_counter() - t_total) * 1000,
        )
        return []

    # ── 2. Encode query (cache check inside _encode) ───────────────────────
    t_enc = time.perf_counter()
    query_vec = await _encode(q_stripped)
    enc_ms = (time.perf_counter() - t_enc) * 1000

    # ── 3. Score (cosine + chunk 9 Part 4 forgetting curve) + top-k ───────
    t_cos = time.perf_counter()
    fc_on = get_forgetting_curve_enabled()
    fc_threshold = get_forgetting_curve_threshold() if fc_on else float("-inf")
    fc_decay = get_forgetting_curve_age_decay()
    now = datetime.utcnow()

    scored: List[tuple[float, Memory]] = []
    for mem in all_memories:
        if not mem.embedding:
            continue
        mem_vec = np.frombuffer(mem.embedding, dtype=np.float32)
        relevance = _cosine(query_vec, mem_vec)
        if fc_on:
            # age_days = (now - last_accessed_at).days；NULL 视同 created_at
            anchor = mem.last_accessed_at or mem.created_at
            age_days = max(0.0, (now - anchor).total_seconds() / 86400.0) if anchor else 0.0
            score = forgetting_curve_score(
                relevance,
                int(mem.access_count or 0),
                age_days,
                decay=fc_decay,
            )
        else:
            score = relevance
        if score < fc_threshold:
            continue
        scored.append((score, mem))
    scored.sort(key=lambda x: x[0], reverse=True)
    cos_ms = (time.perf_counter() - t_cos) * 1000

    top = scored[:top_k]
    total_ms = (time.perf_counter() - t_total) * 1000
    logger.info(
        "[TIME] search_relevant sql=%.1fms encode=%.1fms score=%.1fms "
        "total=%.1fms candidates=%d kept=%d top_k=%d fc=%s",
        sql_ms, enc_ms, cos_ms, total_ms, len(all_memories), len(scored),
        top_k, "on" if fc_on else "off",
    )

    # ── 4. Bump access counters on returned entries ───────────────────────
    if fc_on and top:
        try:
            await _bump_access_counters([m.id for _, m in top])
        except Exception as exc:
            logger.warning(
                "[memory] _bump_access_counters failed: %s", exc,
            )

    return [mem for _, mem in top]
