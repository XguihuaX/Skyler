"""MomoOS FastAPI application entry point.

Lifespan sequence
-----------------
1. init_db()                — create tables if absent
2. Ensure default user      — create from config.default_user_id if missing
3. Restore short-term mem   — load last ≤20 chat_history rows into memory
4. Preload local models     — sentence-transformers + faster-whisper
5. AlarmScheduler.start()   — begin 30 s polling loop for due alarms

Routes
------
  /api/memory/*    — memory / personality / todo REST API (memory_api.py)
  /api/health      — model warm-up status (health_api.py)
  /ws              — WebSocket streaming conversation (ws.py)
"""
import os

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
import asyncio
import logging
import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.asr.whisper import whisper_asr
from backend.config import config_yaml
from backend.database import AsyncSessionLocal, init_db
from backend.database.migrations.v2_5_b import migrate as migrate_v2_5_b
from backend.database.migrations.v3_b import run_migration as migrate_v3_b
from backend.database.migrations.v3_e1 import run_migration as migrate_v3_e1
from backend.database.migrations.v3_e1_z import run_migration as migrate_v3_e1_z
from backend.database.migrations.v3_e2_per_character_maps import (
    run_migration as migrate_v3_e2_per_character_maps,
)
from backend.database.migrations.v3_e2_restore_momo_persona import (
    run_migration as migrate_v3_e2_restore_momo_persona,
)
from backend.database.migrations.v3_e2_yae_maps import (
    run_migration as migrate_v3_e2_yae_maps,
)
from backend.database.migrations.v3_f import run_migration as migrate_v3_f
from backend.database.services import create_user, get_chat_history, get_user
from backend.memory import long_term as long_term_memory
from backend.memory.short_term import short_term_memory
from backend.routes.characters_api import router as characters_router
from backend.routes.config_api import router as config_router
from backend.routes.conversations_api import router as conversations_router
from backend.routes.health_api import app_state, router as health_router
from backend.routes.live2d_api import router as live2d_router
from backend.routes.memory_api import router as memory_router
from backend.routes.tts_api import router as tts_router
from backend.routes.users_api import router as users_router
from backend.routes.ws import router as ws_router
from backend.scheduler.task import scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # ── 1. Database ─────────────────────────────────────────────────────────
    await init_db()
    logger.info("Database initialised")

    # ── 1b. V2.5-B schema migration (idempotent) ─────────────────────────────
    await migrate_v2_5_b()

    # ── 1b2. V3-B schema migration: characters.voice_model (idempotent) ──────
    await migrate_v3_b()

    # ── 1b3. V3-F schema migration: chat_history.interrupted_at (idempotent) ─
    await migrate_v3_f()

    # ── 1b4. V3-E1 schema migration: characters.live2d_model (idempotent) ────
    await migrate_v3_e1()

    # ── 1b5. V3-E1 Step Z.2 schema migration: chat_history.kind (idempotent) ─
    await migrate_v3_e1_z()

    # ── 1b6. V3-E2 schema migration: characters.{emotion,motion,hit_area}_map_json ─
    await migrate_v3_e2_per_character_maps()

    # ── 1b7. V3-E2 data migration: 八重 (id=2) live2d_model='yae' + maps ──────
    await migrate_v3_e2_yae_maps()

    # ── 1b8. V3-E2 data migration: Momo (id=1) persona 还原成 ChatAgent 原文 ──
    await migrate_v3_e2_restore_momo_persona()

    # ── 1c. V2.5-C2c backfill: legacy memory rows pre-date character_id, so
    #         tag them as Momo's so per-character filters keep showing them.
    from sqlalchemy import text
    from backend.database import engine as _engine
    async with _engine.begin() as _conn:
        momo_id_row = (await _conn.execute(
            text("SELECT id FROM characters WHERE name = 'Momo' LIMIT 1")
        )).fetchone()
        if momo_id_row is not None:
            momo_id = int(momo_id_row[0])
            res = await _conn.execute(
                text("UPDATE memory SET character_id = :cid WHERE character_id IS NULL"),
                {"cid": momo_id},
            )
            updated = getattr(res, "rowcount", None)
            if updated:
                logger.info(
                    "[V2.5-C2c] Backfilled %d legacy memory rows -> character_id=%d (Momo)",
                    updated, momo_id,
                )

    # ── 2. Default user ──────────────────────────────────────────────────────
    default_uid: str  = config_yaml.get("default_user_id", "default")
    default_name: str = "Momo"

    async with AsyncSessionLocal() as session:
        user = await get_user(session, default_uid)
        if user is None:
            await create_user(session, default_uid, default_name)
            logger.info("Created default user: %s (%s)", default_uid, default_name)
        else:
            logger.info("Default user already exists: %s", default_uid)

    # ── 3. Restore short-term memory from chat_history ───────────────────────
    async with AsyncSessionLocal() as session:
        history = await get_chat_history(session, default_uid, limit=20)

    if history:
        for msg in history:
            await short_term_memory.add(default_uid, msg.role, msg.content)
        logger.info(
            "Restored %d chat_history turns into short-term memory for user %s",
            len(history), default_uid,
        )

    # ── 4. Preload local models (embedding + whisper) ────────────────────────
    async def _preload_embedding() -> None:
        t0 = time.perf_counter()
        try:
            await long_term_memory.preload()
            app_state["embedding_ready"] = True
            logger.info(
                "[TIME] Embedding model load: %.0fms",
                (time.perf_counter() - t0) * 1000,
            )
        except Exception:
            logger.exception("Embedding model preload failed")

    async def _preload_whisper() -> None:
        t0 = time.perf_counter()
        try:
            await whisper_asr.load_model()
            app_state["whisper_ready"] = True
            logger.info(
                "[TIME] Whisper model load: %.0fms",
                (time.perf_counter() - t0) * 1000,
            )
        except Exception:
            logger.exception("Whisper model preload failed")

    # Run both loads concurrently in the background — startup completes immediately
    # so /api/health can answer "warming" while models load in parallel.
    asyncio.create_task(_preload_embedding())
    asyncio.create_task(_preload_whisper())

    # ── 5. Alarm scheduler ───────────────────────────────────────────────────
    await scheduler.start(default_uid)
    logger.info("AlarmScheduler started")

    yield

    await scheduler.stop()


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="MomoOS API",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router,        prefix="/api", tags=["health"])
app.include_router(config_router,        prefix="/api", tags=["config"])
app.include_router(memory_router,        prefix="/api", tags=["memory"])
app.include_router(conversations_router, prefix="/api", tags=["conversations"])
app.include_router(characters_router,    prefix="/api", tags=["characters"])
app.include_router(users_router,         prefix="/api", tags=["users"])
app.include_router(live2d_router,        prefix="/api", tags=["live2d"])
app.include_router(tts_router,           prefix="/api", tags=["tts"])
app.include_router(ws_router,                            tags=["websocket"])
