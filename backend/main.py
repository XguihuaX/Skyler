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
from backend.database.migrations.v3_g_default_voice import (
    run_migration as migrate_v3_g_default_voice,
)
from backend.database.migrations.v3_g_chunk2_proactive import (
    run_migration as migrate_v3_g_chunk2_proactive,
)
from backend.database.services import create_user, get_chat_history, get_user
from backend.memory import long_term as long_term_memory
from backend.memory.short_term import short_term_memory
from backend.routes.briefing_api import router as briefing_router
from backend.routes.capabilities_api import router as capabilities_router
from backend.routes.mcp_api import (
    mcp_endpoint as _mcp_endpoint,
    router as mcp_router,
)
from backend.routes.characters_api import router as characters_router
from backend.routes.config_api import router as config_router
from backend.routes.conversations_api import router as conversations_router
from backend.routes.health_api import app_state, router as health_router
from backend.routes.integrations_api import router as integrations_router
from backend.routes.live2d_api import router as live2d_router
from backend.routes.memory_api import router as memory_router
from backend.routes.settings_api import router as settings_router
from backend.routes.tts_api import router as tts_router
from backend.routes.users_api import router as users_router
from backend.routes.webhooks_api import router as webhooks_router
from backend.routes.ws import router as ws_router
from backend.scheduler import cron as cron_scheduler
from backend.scheduler.task import scheduler

# v3-G chunk 0+ — 触发 capability decorator 副作用注册到 CapabilityRegistry +
# ToolRegistry。必须在 FastAPI app 构造前 import，使 ChatAgent 在第一次
# acompletion 调用时就能看到所有 capability。新增 capability 时把 import
# 加到这里。
import backend.capabilities.time_capability    # noqa: F401, E402
# chunk 1.6: 顺序敏感 —— apple / google 直接 capability 必须在 router (calendar)
# 之前 import，否则 router 注册时 apple_calendar / google_calendar 模块还没
# 加载，路由首次调用会触发 import（仍能 work，但 trace 不直观）。
import backend.capabilities.apple_calendar    # noqa: F401, E402  v3-G chunk 1.6
import backend.capabilities.google_calendar   # noqa: F401, E402  v3-G chunk 1.6 (renamed from chunk 1)
import backend.capabilities.calendar          # noqa: F401, E402  v3-G chunk 1.6 router
import backend.capabilities.netease_music     # noqa: F401, E402  v3-H chunk 1
import backend.capabilities.media_control     # noqa: F401, E402  v3-H chunk 1
from backend.mcp import server as mcp_server  # noqa: E402  v3-G chunk 1.5

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

    # ── 1b9. V3-G' chunk 1c: Momo (id=1) 默认 voice_model = cosyvoice/longyumi_v3 ─
    await migrate_v3_g_default_voice()

    # ── 1b10. V3-G chunk 2: chat_history.proactive_trigger 列（idempotent）─
    await migrate_v3_g_chunk2_proactive()

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

    # ── 6. v3-G chunk 0 — Cron scheduler (APScheduler) ──────────────────────
    await cron_scheduler.start()

    # ── 7. v3-G chunk 2 — Proactive engine triggers cron 注册 ────────────
    # 通用 proactive engine 接管：每个 trigger 自带 cron_expr；engine 路径
    # 统一调 run_trigger(trigger, user_id)。chunk 1 的 ``briefing.enabled``
    # config 节已废弃 —— 现按 ``proactive.morning_briefing.enabled`` 启停。
    proactive_cfg = config_yaml.get("proactive") or {}
    if proactive_cfg.get("enabled", False):
        from backend.proactive.triggers.morning_briefing import (
            MorningBriefingTrigger,
            _briefing_enabled as _morning_enabled,
        )
        from backend.scheduler.briefing import deliver_morning_briefing

        if _morning_enabled():
            trigger = MorningBriefingTrigger()
            try:
                cron_scheduler.schedule_cron(
                    trigger.name, trigger.cron_expr, deliver_morning_briefing,
                )
                logger.info(
                    "Proactive morning_briefing cron registered: %s",
                    trigger.cron_expr,
                )
            except ValueError:
                logger.info("Proactive morning_briefing cron already registered")
        else:
            logger.info("Proactive enabled but morning_briefing.enabled=false; skipping cron")

    # ── 8. v3-G chunk 1.5 — MCP server SessionManager（必要 lifecycle）──
    # mcp SDK 的 StreamableHTTPSessionManager 必须在 ``async with .run()``
    # 上下文里才能 handle_request；run() 内部启 anyio task group 管理所有
    # SSE 流。退出 with 块即关闭。
    #
    # ── 9. v3-G chunk 1.5 — MCP clients：连接外部 server 反向注册 capability
    # 任何 client 启动失败都不阻塞主流程（log warning + last_error 标记，UI
    # 提示用户去 docs/mcp-client-setup.md 排查）。
    from backend.mcp import client as mcp_client_module
    mcp_cfg = config_yaml.get("mcp_server") or {}
    server_enabled = bool(mcp_cfg.get("enabled", False))

    if server_enabled:
        async with mcp_server.get_session_manager().run():
            logger.info("MCP server session manager started")
            await mcp_client_module.init_clients_from_config()
            try:
                yield
            finally:
                await mcp_client_module.shutdown_clients()
                logger.info("MCP server session manager shutting down")
    else:
        # mcp server 关掉时 client 仍可独立工作
        await mcp_client_module.init_clients_from_config()
        try:
            yield
        finally:
            await mcp_client_module.shutdown_clients()

    await cron_scheduler.shutdown()
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
app.include_router(settings_router,      prefix="/api", tags=["settings"])
app.include_router(memory_router,        prefix="/api", tags=["memory"])
app.include_router(conversations_router, prefix="/api", tags=["conversations"])
app.include_router(characters_router,    prefix="/api", tags=["characters"])
app.include_router(users_router,         prefix="/api", tags=["users"])
app.include_router(live2d_router,        prefix="/api", tags=["live2d"])
app.include_router(tts_router,           prefix="/api", tags=["tts"])
app.include_router(capabilities_router,  prefix="/api", tags=["capabilities"])
app.include_router(integrations_router,  prefix="/api", tags=["integrations"])
app.include_router(webhooks_router,      prefix="/api", tags=["webhooks"])
app.include_router(briefing_router,      prefix="/api", tags=["briefing"])
app.include_router(mcp_router,           prefix="/api", tags=["mcp"])
app.include_router(ws_router,                            tags=["websocket"])

# v3-G chunk 1.5 — MCP streamable HTTP endpoint。挂在根路径下（不加 /api
# prefix），与 mcp 标准 ``http://host:port/mcp`` 约定对齐。需要 GET / POST
# / DELETE 三种方法（GET = 客户端打开 SSE 流，POST = 客户端发请求，DELETE
# = 终止会话）。
_mcp_endpoint_path = (
    (config_yaml.get("mcp_server") or {}).get("endpoint_path") or "/mcp"
)
app.add_api_route(
    _mcp_endpoint_path,
    _mcp_endpoint,
    methods=["GET", "POST", "DELETE"],
    include_in_schema=False,  # 不进 OpenAPI schema —— mcp 协议不是 REST
    tags=["mcp"],
)
