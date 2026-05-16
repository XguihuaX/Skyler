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
from backend.database.migrations.v3_g_chunk2_6_pending_briefing import (
    run_migration as migrate_v3_g_chunk2_6_pending_briefing,
)
from backend.database.migrations.v4_fan_chunk1_splash_art import (
    run_migration as migrate_v4_fan_chunk1_splash_art,
)
from backend.database.migrations.v3_g_chunk3_character_states import (
    run_migration as migrate_v3_g_chunk3_character_states,
)
from backend.database.migrations.v3_g_chunk4_strip_legacy_tags import (
    run_migration as migrate_v3_g_chunk4_strip_legacy_tags,
)
from backend.database.migrations.v3_5_chunk5a_character_background import (
    run_migration as migrate_v3_5_chunk5a_character_background,
)
from backend.database.migrations.v3_5_chunk7_mcp_credentials import (
    run_migration as migrate_v3_5_chunk7_mcp_credentials,
)
from backend.database.migrations.v3_5_chunk6b_hotfix3_clean_polluted_memories import (
    run_migration as migrate_v3_5_chunk6b_hotfix3,
)
from backend.database.migrations.v3_5_chunk9_memory_forgetting_curve import (
    run_migration as migrate_v3_5_chunk9_memory_forgetting_curve,
)
from backend.database.migrations.v3_5_chunk11_profile_data import (
    run_migration as migrate_v3_5_chunk11_profile_data,
)
from backend.database.migrations.v3_5_uxr1_mcp_tool_state import (
    run_migration as migrate_v3_5_uxr1_mcp_tool_state,
)
from backend.database.migrations.v3_5_chunk10_memory_structured import (
    run_migration as migrate_v3_5_chunk10_memory_structured,
)
from backend.database.migrations.v3_5_chunk14_activity_sessions import (
    run_migration as migrate_v3_5_chunk14_activity_sessions,
)
# bugfix-3.1: AI Providers backend foundation
from backend.database.migrations.bugfix_3_1_ai_providers import (
    run_migration as migrate_bugfix_3_1_ai_providers,
)
# bugfix-3.2.6: endpoint_env_name column + enabled/active 一致性修补
from backend.database.migrations.bugfix_3_2_6_endpoint_env_repair import (
    run_migration as migrate_bugfix_3_2_6_endpoint_env_repair,
)
# bugfix-3.2.7: 修补 DB seed Qwen/DeepSeek model 缺 LiteLLM provider 前缀
from backend.database.migrations.bugfix_3_2_7_model_prefix_repair import (
    run_migration as migrate_bugfix_3_2_7_model_prefix_repair,
)
# bugfix-3.2.8: dedup + trim non-Qwen builtin + UNIQUE (vendor_id,name,type)
from backend.database.migrations.bugfix_3_2_8_dedup_and_trim_seed import (
    run_migration as migrate_bugfix_3_2_8_dedup_and_trim_seed,
)
# bugfix-3.3.1: 灌入用户复刻的 3 个 CosyVoice voice_id 到 characters 表
from backend.database.migrations.bugfix_3_3_1_seed_cloned_voices import (
    run_migration as migrate_bugfix_3_3_1_seed_cloned_voices,
)
# bugfix-3.4: voice_aliases 表 + 从 characters 自动 seed 友好名
from backend.database.migrations.bugfix_3_4_voice_aliases import (
    run_migration as migrate_bugfix_3_4_voice_aliases,
)
# bugfix-4: tts_call_log 表 (observability)
from backend.database.migrations.bugfix_4_observability import (
    run_migration as migrate_bugfix_4_observability,
)
# v4 persona engineering segment 1: character_personas + builtin_seed
from backend.database.migrations.v4_persona_thickening_segment1 import (
    run_migration as migrate_v4_persona_thickening_segment1,
)
# v4 persona segment 2: Mai voice tts_language='ja' tagging (D-S2-3: by voice_id)
from backend.database.migrations.v4_persona_segment2_mai_ja import (
    run_migration as migrate_v4_persona_segment2_mai_ja,
)
# v4 persona segment 2: ensure every character has default active variant
# (D-S2-2 backfill: characters inserted after segment-1 migration ship)
from backend.database.migrations.v4_persona_segment2_ensure_defaults import (
    run_migration as migrate_v4_persona_segment2_ensure_defaults,
)
# v4.0.0 ship-call: Mai (cid=1) 回退纯中文 — longyumi_v3 + tts_language=zh
# (ja 链代码保留,留 v4.1 后处理翻译架构重做)
from backend.database.migrations.v4_0_0_mai_revert_zh import (
    run_migration as migrate_v4_0_0_mai_revert_zh,
)
from backend.database.services import create_user, get_user
from backend.memory import long_term as long_term_memory
from backend.memory.short_term import short_term_memory
from backend.routes.activity_api import router as activity_router
from backend.routes.backgrounds_api import router as backgrounds_router
from backend.routes.briefing_api import router as briefing_router
from backend.routes.character_state_api import router as character_state_router
from backend.routes.capabilities_api import router as capabilities_router
from backend.routes.mcp_api import (
    mcp_endpoint as _mcp_endpoint,
    router as mcp_router,
)
from backend.routes.characters_api import router as characters_router
from backend.routes.persona_api import router as persona_router
from backend.routes.config_api import router as config_router
from backend.routes.conversations_api import router as conversations_router
from backend.routes.health_api import app_state, router as health_router
from backend.routes.integrations_api import router as integrations_router
from backend.routes.live2d_api import router as live2d_router
from backend.routes.memory_api import router as memory_router
# bugfix-3.3: settings_api 仅 GET/POST /api/settings/model — DB ai_providers
# 已是新唯一 LLM 路由,该路由整文件删除。yaml available_models 字段一并删。
from backend.routes.tts_api import router as tts_router
from backend.routes.observability_api import router as observability_router
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
import backend.proactive.snooze_capability    # noqa: F401, E402  v3-G chunk 2.6
import backend.capabilities.clipboard         # noqa: F401, E402  v3-G chunk 3a
import backend.capabilities.character_state   # noqa: F401, E402  v3-G chunk 3b
import backend.capabilities.docx_ops          # noqa: F401, E402  v3.5 chunk 7 (姿态 A demo)
import backend.capabilities.bilibili          # noqa: F401, E402  v3.5 chunk 6a (B 站接入)
import backend.capabilities.netease_playback  # noqa: F401, E402  v3.5 chunk 6b (mpv 自解码)
import backend.capabilities.xiaohongshu       # noqa: F401, E402  v3.5 chunk 6c (被动 URL 解析)
import backend.capabilities.screen            # noqa: F401, E402  v3.5 chunk 8a (活动感知 4 cap)
import backend.capabilities.activity          # noqa: F401, E402  v3.5 chunk 14 (timeline 3 cap)
# v3-G chunk 4 Part C — proactive trigger pack（导入触发 register_stage2 副作用）
import backend.proactive.triggers.lunch_call    # noqa: F401, E402
import backend.proactive.triggers.dinner_call   # noqa: F401, E402
import backend.proactive.triggers.bedtime_chat  # noqa: F401, E402
import backend.proactive.triggers.long_idle     # noqa: F401, E402
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

    # ── 1b11. V3-G chunk 2.6: pending_briefings 表（idempotent）─────────
    await migrate_v3_g_chunk2_6_pending_briefing()

    # ── 1b12. V3-G chunk 3b: character_states 表（idempotent）───────────
    await migrate_v3_g_chunk3_character_states()

    # ── 1b13. V3-G chunk 4 D-3: 历史 chat_history 标签脏数据扫表剥离 ────
    await migrate_v3_g_chunk4_strip_legacy_tags()

    # ── 1b14. V3.5 chunk 5a: characters.background_path 列（idempotent）──
    await migrate_v3_5_chunk5a_character_background()

    # ── 1b14a. V4-fan chunk 1: characters.splash_art_url 列（idempotent）──
    # Fan UI 扇面卡牌底图字段。POST /api/characters/{id}/splash-art 写入。
    await migrate_v4_fan_chunk1_splash_art()

    # ── 1b15. V3.5 chunk 7: mcp_credentials + mcp_client_state 表 ────────
    # 必须在 init_clients_from_config 之前（client.py 读 DB enabled override）
    await migrate_v3_5_chunk7_mcp_credentials()

    # ── 1b16. V3.5 chunk 6b hotfix-3: 一次性清存量 SUSPICIOUS_TAG_RE 污染 ─
    # 跑前自动备份 momoos.db → .backup-before-hotfix3（已存在则跳过）。幂等
    # 清 chat_history (assistant) + memory.content + users.profile_summary。
    await migrate_v3_5_chunk6b_hotfix3()

    # ── 1b17. V3.5 chunk 9 Part 4: memory.access_count + last_accessed_at ──
    # forgetting curve 元数据。``ALTER TABLE ADD COLUMN`` 幂等。老 entry 用
    # ``last_accessed_at = created_at`` 回填一次，让衰减从创建时起算。
    await migrate_v3_5_chunk9_memory_forgetting_curve()

    # ── 1b18. V3.5 chunk 11: users.profile_data 列（structured JSON profile）
    # legacy ``profile_summary`` 字段保留作 fallback；chunk 11 cron 触发后
    # 用户的 profile_data 字段开始填充，注入 system prompt 优先用它。
    await migrate_v3_5_chunk11_profile_data()

    # ── 1b19. V3.5 chunk 10: memory 表结构化 6 列 + extractor_state 表 ─────
    # 老 entries 标 extraction_source='legacy'；worker 启动后新 entries 标
    # 'worker'，save_memory tool 调用的标 'llm_save_memory'。
    await migrate_v3_5_chunk10_memory_structured()

    # ── 1b20. UX-001: mcp_tool_state 表 ────────────────────────────────────
    # chunk 7 mcp_client_state 是 server 级 toggle；本表加 per-tool（capability）
    # 级 toggle。未登记的 tool 视为 enabled=True；server 关时 connect 阶段
    # 根本不 register tools，无需查表。
    await migrate_v3_5_uxr1_mcp_tool_state()

    # ── 1b21. V3.5 chunk 14: activity_sessions 表（idempotent）─────────────
    # 跟 chat_history 平行的活动 timeline。session boundary 由
    # backend/services/activity_timeline.py 的 poll-listener 写入。
    # 跑前自动备份 momoos.db → .backup-before-chunk14（已存在则跳过）。
    await migrate_v3_5_chunk14_activity_sessions()

    # ── 1b22a. Bugfix-3.2.7: 修补老 DB seed Qwen/DeepSeek model 缺 LiteLLM 前缀 ──
    # 旧 3.1 seed 把 qwen3.6-* / deepseek-chat 写成裸名,LiteLLM acompletion
    # 抛 "LLM Provider NOT provided" → 主聊天 500。一次性 UPDATE 加 openai/ /
    # deepseek/ 前缀。**必须在 3.1 之前跑** — 否则 3.1 的 seed dedup 用新前缀
    # SELECT 匹配不到旧裸名,会插重复 builtin。table 不存在(fresh install)→ 跳过。
    await migrate_bugfix_3_2_7_model_prefix_repair()

    # ── 1b22. Bugfix-3.1: ai_vendors + ai_vendor_credentials + ai_providers ─
    # 4 个 builtin vendor (qwen/openai/anthropic/deepseek) + 7 个 LLM provider
    # 一次性 seed。fernet 加密 vendor credentials。LLM dispatcher 优先查 DB
    # active provider,无则兜底回 config.yaml::default_model + .env。幂等。
    await migrate_bugfix_3_1_ai_providers()

    # ── 1b23. Bugfix-3.2.6: endpoint_env_name + enabled/active 一致性修补 ──
    # ALTER TABLE ai_vendors ADD COLUMN endpoint_env_name(给 4 个 builtin
    # 回填 DASHSCOPE_BASE_URL / OPENAI_BASE_URL 等)+ 一次性扫表修补 is_active=1
    # AND enabled=0 自相矛盾的 DB state。幂等。必须在 3.1 后跑。
    await migrate_bugfix_3_2_6_endpoint_env_repair()

    # ── 1b24. Bugfix-3.2.8: dedup + trim non-Qwen builtin + UNIQUE index ───
    # 3.1 老 seed 用 (vendor_id, model) 判重,3.2.7 改前缀后导致重插。这里
    # ROW_NUMBER 去重 + 只保留 Qwen 2 个 builtin(其他 vendor seed 行 trim,
    # 用户自填)+ CREATE UNIQUE INDEX 防未来重复。必须在 3.1 seed 后跑。
    await migrate_bugfix_3_2_8_dedup_and_trim_seed()

    # ── 1b25. Bugfix-3.3.1: 灌入用户复刻的 CosyVoice voice_id ──────────────
    # 用户在 DashScope 控制台复刻了 3 个 voice, 这里写入对应 character.voice_model
    # JSON。幂等:已是 cloned voice 不动; 其他 (NULL / 系统 longxxx) 才覆盖。
    await migrate_bugfix_3_3_1_seed_cloned_voices()

    # ── 1b26. Bugfix-3.4: voice_aliases 表 + 从 characters 自动 seed 友好名 ──
    # CREATE TABLE voice_aliases + 反查 characters.voice_model 给已绑 cloned
    # voice 的角色 seed ``<角色名> voice`` 友好名。幂等 (INSERT OR IGNORE)。
    # 必须在 3.3.1 之后跑 — 不然反查不到 char→voice 映射。
    await migrate_bugfix_3_4_voice_aliases()

    # ── 1b27. Bugfix-4: tts_call_log 表 (observability) ────────────────────
    # 给每次 CosyVoice synthesize 调用埋点 (source, voice, model, input_chars,
    # cost_estimate, success)。前端 TTS tab 用量 panel + 异常 call 诊断走这张表。
    await migrate_bugfix_4_observability()

    # ── 1b28. V4 persona engineering segment 1 ─────────────────────────────
    # character_personas + character_personas_builtin_seed 两张表 + 给现有
    # characters 表里每个角色 seed 一行 variant_name='default'。Tier-1 7 JSON
    # 字段必填，default_emotion 从旧 yaml 迁入 personality_core 子字段（D-4）。
    # 必须在 bugfix-3.x 系列把 characters 行 seed 完之后跑（依赖 characters
    # 表的角色行已存在）。幂等：partial UNIQUE INDEX 保证同 character 仅一
    # 行 is_active=1，重复跑只补缺、不重写已有 active variant。
    await migrate_v4_persona_thickening_segment1()

    # ── 1b29. V4 persona segment 2 - ensure-defaults backfill ──────────────
    # D-S2-2 sign-off：防御性给 segment-1 跑完后才插入的 character 补 default
    # active variant。扫 characters 找 NOT EXISTS (is_active=1 variant) 的行，
    # 给每行 seed 一份空模板。幂等（WHERE NOT EXISTS），已有 variant 的 character
    # 不动。**必须在 segment-1 之后跑**（依赖 character_personas + builtin_seed
    # 两张表存在）。
    await migrate_v4_persona_segment2_ensure_defaults()

    # ── 1b30. V4 persona segment 2 - Mai voice tts_language='ja' ───────────
    # D-S2-3 sign-off：按 voice_id 标 ja（不按 character_id），自动覆盖所有
    # 用 Mai 复刻 voice 的角色（当前 id=1 Momo/Mai 借壳 + id=101 樱岛麻衣）。
    # 让 renderer 走 layer_a.j2 的 ja 分支，LLM 输出 <ja>日语翻译</ja>，
    # TTS 取 ja 段，中文给字幕。幂等（WHERE tts_language IS NULL OR != 'ja'）。
    await migrate_v4_persona_segment2_mai_ja()

    # ── 1b31. V4.0.0 ship-call: Mai (cid=1) 回退纯中文 ──────────────────────
    # v4.0.0 产品决策:Mai 放弃 ja pipeline,改用 cosyvoice 内置中文音色
    # longyumi_v3 + tts_language=zh。**必须在 v4_seg2_mai_ja 之后跑** ——
    # 若 seg2 那条按 voice=a19f... 把 cid=1 标 ja,本迁移立刻无条件覆盖回
    # longyumi_v3/zh。一旦 cid=1 已切走 voice,seg2 不再命中 cid=1。
    # ja 链代码全部保留,留 v4.1 后处理翻译架构重做。
    await migrate_v4_0_0_mai_revert_zh()

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
    # 路径 7 修法(audit_role_switch.md / audit_ja_persist.md):
    #   1. **按 character_id 分桶 restore** —— 不再把跨角色历史搅在一个 user bucket
    #      (旧实现 limit=20 by user_id only 会把 cid=1 Mai 历史装回去,切到 cid=2
    #       八重也看到,触发"我是麻衣"持续 bug)。
    #   2. **剥离 ``<ja>``/``<en>`` 历史 tag** —— audit_ja_persist 三定位收敛根因:
    #      短期记忆 ja precedent 让 LLM in-context-learning 继续抄。restore 阶段
    #      就把 tag 剥掉,纯中文 inner 保留(``strip_ja_en_tags_for_subtitle`` 只
    #      删 ja/en 包裹,中文正文 / 其他 meta tag 不动)。
    # 通过 chat_history.character_id 列查 distinct char,逐 char 拉 limit=20 最近
    # 然后 add(user, role, cleaned_content, character_id=cid)。
    from sqlalchemy import distinct as _distinct, select as _select
    from backend.database.models import ChatHistory as _ChatHistory
    from backend.utils.text_filters import (
        strip_ja_en_tags_for_subtitle as _strip_ja_en,
    )

    async with AsyncSessionLocal() as session:
        char_id_rows = (await session.execute(
            _select(_distinct(_ChatHistory.character_id))
            .where(_ChatHistory.user_id == default_uid)
        )).all()
    char_ids = [r[0] for r in char_id_rows]

    total_restored = 0
    for cid in char_ids:
        async with AsyncSessionLocal() as session:
            rows = (await session.execute(
                _select(_ChatHistory)
                .where(_ChatHistory.user_id == default_uid)
                .where(_ChatHistory.character_id.is_(cid) if cid is None
                       else _ChatHistory.character_id == cid)
                .order_by(
                    _ChatHistory.created_at.desc(), _ChatHistory.id.desc(),
                ).limit(20)
            )).scalars().all()
        rows = list(reversed(list(rows)))
        n_cid = 0
        for msg in rows:
            cleaned = _strip_ja_en(msg.content or "").strip()
            if not cleaned:
                continue
            await short_term_memory.add(
                default_uid, msg.role, cleaned, character_id=cid,
            )
            n_cid += 1
        total_restored += n_cid
        logger.info(
            "Restored %d chat_history turns into short-term memory for "
            "user=%s char=%s (ja/en tags stripped)",
            n_cid, default_uid, cid,
        )
    if char_ids:
        logger.info(
            "[restore] total %d turn(s) across %d character bucket(s) "
            "(per-char limit=20, ja/en tag stripped at restore)",
            total_restored, len(char_ids),
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

    # ── 6b. v3-G chunk 3b — intimacy_decay daily cron（每天 0:00）─────────
    try:
        from backend.capabilities.character_state import intimacy_decay
        cron_scheduler.schedule_cron(
            "intimacy_decay_daily", "0 0 * * *", intimacy_decay,
        )
        logger.info("[cron] intimacy_decay_daily registered: 0 0 * * *")
    except ValueError:
        logger.info("[cron] intimacy_decay_daily already registered (hot-reload)")
    except Exception:
        logger.exception("[cron] intimacy_decay_daily registration failed")

    # ── 6b'. v3.5 chunk 11 — structured profile daily regenerate ─────────
    # Cron 取代 chunk 9 的"每 50 turn" in-memory 计数器（已删除）。
    # config ``memory.profile_structured.cron`` 默认 "55 23 * * *"。
    try:
        from backend.services.profile_regen import (
            get_profile_cron_expr,
            profile_daily_regenerate,
        )
        _profile_cron_expr = get_profile_cron_expr()
        cron_scheduler.schedule_cron(
            "profile_daily_regenerate", _profile_cron_expr,
            profile_daily_regenerate,
        )
        logger.info(
            "[cron] profile_daily_regenerate registered: %s",
            _profile_cron_expr,
        )
    except ValueError:
        logger.info(
            "[cron] profile_daily_regenerate already registered (hot-reload)"
        )
    except Exception:
        logger.exception(
            "[cron] profile_daily_regenerate registration failed"
        )

    # ── 6b'''. v3.5 chunk 14 — activity_sessions daily cleanup cron ─────
    # 删 > config.activity_timeline.cleanup_days(默 30 天)的 session 行。
    # cleanup_days=0 → cleanup_old_sessions 函数自己 no-op。
    try:
        from backend.services.activity_timeline import (
            cleanup_old_sessions,
            get_cleanup_cron_expr,
        )
        _cleanup_cron_expr = get_cleanup_cron_expr()
        cron_scheduler.schedule_cron(
            "activity_timeline_cleanup", _cleanup_cron_expr,
            cleanup_old_sessions,
        )
        logger.info(
            "[cron] activity_timeline_cleanup registered: %s",
            _cleanup_cron_expr,
        )
    except ValueError:
        logger.info(
            "[cron] activity_timeline_cleanup already registered (hot-reload)"
        )
    except Exception:
        logger.exception(
            "[cron] activity_timeline_cleanup registration failed"
        )

    # ── 6b''. v3.5 chunk 10 — MemoryExtractor worker ─────────────────────
    # 每 N 分钟扫 chat_history 提取 memory entries。worker 用
    # asyncio.create_task fire-and-forget；shutdown 阶段 stop()。
    # config.memory.extractor.enabled=false 时不启动（log 静默）。
    try:
        from backend.memory.extractor import (
            get_extractor,
            get_extractor_enabled,
            get_extractor_interval_seconds,
        )
        if get_extractor_enabled():
            ex = get_extractor()
            ex._task = asyncio.create_task(ex.run_loop())
            app_state["extractor_worker"] = ex
            logger.info(
                "[extractor] started interval=%ds",
                get_extractor_interval_seconds(),
            )
        else:
            logger.info("[extractor] disabled by config (memory.extractor.enabled=false)")
    except Exception:
        logger.exception("[extractor] worker startup failed")

    # ── 6c. v3-G chunk 3a — clipboard polling task ─────────────────────────
    try:
        from backend.integrations.clipboard import clipboard_watcher
        clipboard_watcher.start_polling()
    except Exception:
        logger.exception("[clipboard] polling task spawn failed")

    # ── 6c'. v3.5 chunk 8a — ActivityWatcher + smart trigger ────────────────
    # activity_watcher.enabled=false → 完全不启动（log 静默）。enabled=true →
    # 把 smart_handler 注册成 listener + start polling。listener / run_loop
    # 内部异常都吞 + log 不阻塞主对话。
    # 启动后做一次 macOS 权限自检：NSWorkspace + AppleScript 都能跑则不报；
    # AppleScript 失败 → log warning + 通过 ConnectionManager push 通知前端
    # 弹"需要授权"modal。
    try:
        from backend.integrations.activity_watcher import (
            activity_watcher,
            check_macos_permissions,
        )
        from backend.proactive.activity_smart import (
            activity_smart_handler,
            judge_poll_handler,
        )
        activity_watcher.register_change_listener(activity_smart_handler)
        # chunk 8a-ext: 慢路径 judge listener,每 poll(默 30s)跑一次
        # maybe_judge — 实际 LLM 调用受 min_stay (5 min) + judge_throttle
        # (10 min) + fire_throttle (30 min) 三重门挡,默频率很低。
        activity_watcher.register_poll_listener(judge_poll_handler)
        # chunk 14: timeline session writer — 同样的 poll listener,但与 judge
        # 完全独立(maintain 自己的 (app, url) 边界游标),每段 stay 结束写
        # activity_sessions 一行。受 activity_timeline.enabled 总开关 + 30s
        # min_session_seconds + chunk 8a 黑名单 + chunk 8a-ext V2 idle 标记。
        from backend.services.activity_timeline import (
            session_writer_poll_handler,
        )
        activity_watcher.register_poll_listener(session_writer_poll_handler)
        activity_watcher.start_polling()
        # 权限自检（异步、不阻塞 startup）
        async def _permission_check() -> None:
            try:
                result = await check_macos_permissions()
                if not result["applescript_ok"] and result["ns_workspace_ok"]:
                    logger.warning(
                        "[activity] AppleScript permission missing; "
                        "browser tab / document detection will silently fail. %s",
                        result.get("hint"),
                    )
                    # 通过 ConnectionManager push 通知 default user（最佳努力）
                    try:
                        from backend.routes.ws import connection_manager
                        default_uid = config_yaml.get("default_user_id") or "default"
                        await connection_manager.push(default_uid, {
                            "type": "activity_permission_missing",
                            "hint": result.get("hint"),
                        })
                    except Exception as exc:
                        logger.debug("[activity] WS push skipped: %s", exc)
            except Exception as exc:
                logger.warning("[activity] permission check failed: %s", exc)
        asyncio.create_task(_permission_check())
    except Exception:
        logger.exception("[activity] watcher startup failed")

    # ── 6d. v3-G chunk 4 Part C — v3-F' trigger pack registration ──────────
    # 4 个新 trigger 各自按 config.proactive.triggers.{name}.enabled 决定。
    # default 全 False（除 lunch_call / dinner_call 默认 True，餐点最低敏感）；
    # bedtime_chat / long_idle default False（用户在面板手动开）。任一注册
    # 失败不阻塞主流程（log warning 继续）。
    try:
        from backend.proactive.engine import run_wake_call_trigger
        from backend.proactive.triggers import (
            lunch_call as _lunch_mod,
            dinner_call as _dinner_mod,
            bedtime_chat as _bedtime_mod,
            long_idle as _long_idle_mod,
        )
        from backend.proactive.triggers.lunch_call import LunchCallTrigger
        from backend.proactive.triggers.dinner_call import DinnerCallTrigger
        from backend.proactive.triggers.bedtime_chat import BedtimeChatTrigger

        # ─ lunch_call (weekday + weekend 各一个 cron job) ────────────────
        if _lunch_mod._enabled():
            async def _fire_lunch_weekday() -> None:
                await run_wake_call_trigger(
                    LunchCallTrigger(weekend=False),
                    user_id=str(config_yaml.get("default_user_id") or "default"),
                )
            async def _fire_lunch_weekend() -> None:
                await run_wake_call_trigger(
                    LunchCallTrigger(weekend=True),
                    user_id=str(config_yaml.get("default_user_id") or "default"),
                )
            try:
                cron_scheduler.schedule_cron(
                    "lunch_call_weekday", _lunch_mod._resolve_cron_weekday(),
                    _fire_lunch_weekday,
                )
                logger.info(
                    "[cron] lunch_call_weekday registered: %s",
                    _lunch_mod._resolve_cron_weekday(),
                )
            except ValueError:
                logger.info("[cron] lunch_call_weekday already registered")
            try:
                cron_scheduler.schedule_cron(
                    "lunch_call_weekend", _lunch_mod._resolve_cron_weekend(),
                    _fire_lunch_weekend,
                )
                logger.info(
                    "[cron] lunch_call_weekend registered: %s",
                    _lunch_mod._resolve_cron_weekend(),
                )
            except ValueError:
                logger.info("[cron] lunch_call_weekend already registered")

        # ─ dinner_call ───────────────────────────────────────────────────
        if _dinner_mod._enabled():
            async def _fire_dinner() -> None:
                await run_wake_call_trigger(
                    DinnerCallTrigger(),
                    user_id=str(config_yaml.get("default_user_id") or "default"),
                )
            try:
                cron_scheduler.schedule_cron(
                    "dinner_call", _dinner_mod._resolve_cron(), _fire_dinner,
                )
                logger.info(
                    "[cron] dinner_call registered: %s", _dinner_mod._resolve_cron(),
                )
            except ValueError:
                logger.info("[cron] dinner_call already registered")

        # ─ bedtime_chat ──────────────────────────────────────────────────
        if _bedtime_mod._enabled():
            async def _fire_bedtime() -> None:
                await run_wake_call_trigger(
                    BedtimeChatTrigger(),
                    user_id=str(config_yaml.get("default_user_id") or "default"),
                )
            try:
                cron_scheduler.schedule_cron(
                    "bedtime_chat", _bedtime_mod._resolve_cron(), _fire_bedtime,
                )
                logger.info(
                    "[cron] bedtime_chat registered: %s",
                    _bedtime_mod._resolve_cron(),
                )
            except ValueError:
                logger.info("[cron] bedtime_chat already registered")

        # ─ long_idle (interval 检查 + 内部三条件判定) ─────────────────────
        if _long_idle_mod._enabled():
            interval = _long_idle_mod._resolve_check_interval_minutes() * 60
            try:
                cron_scheduler.schedule_interval(
                    "long_idle_check", interval, _long_idle_mod.check_and_maybe_fire,
                )
                logger.info(
                    "[cron] long_idle_check registered: every %ds (threshold=%dmin cooldown=%dmin)",
                    interval,
                    _long_idle_mod._resolve_idle_threshold_minutes(),
                    _long_idle_mod._resolve_cooldown_minutes(),
                )
            except ValueError:
                logger.info("[cron] long_idle_check already registered")
    except Exception:
        logger.exception("[cron] v3-F' trigger pack registration failed")

    # ── 7. v3-G chunk 2 / 2.6 — Proactive engine cron 注册（mode 互斥）─
    # ``config.proactive.mode`` 决定哪个 trigger 上 cron：
    #   - "wake_call"        → WakeCallBriefingTrigger（模式 B 邀请对话，默认）
    #   - "morning_briefing" → MorningBriefingTrigger（模式 A 单方面播报）
    #   - "off" / 其他       → 都不注册
    # 互斥避免两个都跑撞车（用户 8 点 wake_call + 9 点 morning_briefing 会
    # 重复叫一次"早安"）。
    proactive_cfg = config_yaml.get("proactive") or {}
    if proactive_cfg.get("enabled", False):
        mode = str(proactive_cfg.get("mode") or "").strip().lower()
        from backend.proactive.snooze_capability import WAKE_CALL_CRON_JOB_ID
        from backend.scheduler.briefing import (
            deliver_morning_briefing,
            deliver_wake_call_briefing,
        )

        if mode == "wake_call":
            from backend.proactive.triggers.wake_call_briefing import (
                WakeCallBriefingTrigger,
            )
            trig = WakeCallBriefingTrigger()
            # 注：用 ``WAKE_CALL_CRON_JOB_ID`` 作为 cron job id（snooze
            # capability 按此 id 查 next_run_time 做冲突避免）；不是
            # ``trigger.name``。schedule_cron 用 name 参数同时作为 id +
            # display name。
            try:
                cron_scheduler.schedule_cron(
                    WAKE_CALL_CRON_JOB_ID, trig.cron_expr, deliver_wake_call_briefing,
                )
                logger.info(
                    "Proactive wake_call cron registered: %s (mode=wake_call)",
                    trig.cron_expr,
                )
            except ValueError:
                logger.info("Proactive wake_call cron already registered")
        elif mode == "morning_briefing":
            from backend.proactive.triggers.morning_briefing import (
                MorningBriefingTrigger,
            )
            trig = MorningBriefingTrigger()
            try:
                cron_scheduler.schedule_cron(
                    trig.name, trig.cron_expr, deliver_morning_briefing,
                )
                logger.info(
                    "Proactive morning_briefing cron registered: %s (mode=morning_briefing)",
                    trig.cron_expr,
                )
            except ValueError:
                logger.info("Proactive morning_briefing cron already registered")
        else:
            logger.info(
                "Proactive enabled but mode=%r (off/unknown); no cron registered",
                mode,
            )

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

    # v3.5 chunk 6b：优雅停 mpv 子进程（如启动过）
    try:
        from backend.integrations.mpv_player import shutdown_player
        await shutdown_player()
    except Exception as exc:
        logger.warning("[mpv] shutdown_player failed: %s", exc)

    # v3.5 chunk 10：优雅停 MemoryExtractor worker（如启动过）
    try:
        ex = app_state.get("extractor_worker")
        if ex is not None:
            await ex.stop()
            logger.info("[extractor] worker stopped")
    except Exception as exc:
        logger.warning("[extractor] stop failed: %s", exc)

    # v3.5 chunk 8a：优雅停 ActivityWatcher（如启动过）
    try:
        from backend.integrations.activity_watcher import activity_watcher
        await activity_watcher.stop_polling()
    except Exception as exc:
        logger.warning("[activity] stop_polling failed: %s", exc)

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
# bugfix-3.3: settings_router (仅 /api/settings/model) 已下线 — DB ai_providers
# 是 LLM 路由唯一入口。前端切 model 走 POST /api/ai-providers/{id}/activate。
app.include_router(memory_router,        prefix="/api", tags=["memory"])
app.include_router(conversations_router, prefix="/api", tags=["conversations"])
app.include_router(characters_router,    prefix="/api", tags=["characters"])
app.include_router(persona_router,        prefix="/api", tags=["persona"])
app.include_router(users_router,         prefix="/api", tags=["users"])
app.include_router(live2d_router,        prefix="/api", tags=["live2d"])
app.include_router(backgrounds_router,    prefix="/api", tags=["backgrounds"])
app.include_router(tts_router,           prefix="/api", tags=["tts"])
app.include_router(observability_router, prefix="/api", tags=["observability"])
app.include_router(capabilities_router,  prefix="/api", tags=["capabilities"])
app.include_router(integrations_router,  prefix="/api", tags=["integrations"])
app.include_router(webhooks_router,      prefix="/api", tags=["webhooks"])
app.include_router(briefing_router,      prefix="/api", tags=["briefing"])
app.include_router(character_state_router, prefix="/api", tags=["character_state"])
app.include_router(activity_router,      prefix="/api", tags=["activity"])
app.include_router(mcp_router,           prefix="/api", tags=["mcp"])
# bugfix-3.1: AI Providers REST API (vendors + providers + credentials + activate)
from backend.routes.ai_providers_api import router as ai_providers_router
app.include_router(ai_providers_router,  prefix="/api", tags=["ai-providers"])
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
