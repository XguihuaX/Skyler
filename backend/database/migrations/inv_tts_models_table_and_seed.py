"""INV (2026-06-11) — tts_models 表 + mai_v4 builtin seed。

GSV model 库从静态 backend/config/tts_models.json 搬进 DB · 用户能在前端
GsvTTSCard 加/列/选/编辑/删 model · 各 model 独立 lab_dir + wav_remote_dir +
weights + default_emotion + inference_params · 跟全局 server_url(走 ai_providers
type='tts' name='gsv' 单行 · 阶段 ① B 已 lock)正交。

Schema(per PM Q3 SPEC-LOCK):
  - 强类型字段(对比 ai_providers.extra_json JSON 字符串黏稠)
  - UNIQUE(provider, model_id) 保证幂等 + 业务 key
  - provider CHECK ('gsv','fish','cosyvoice') 留 fish/cosyvoice 扩展位
  - inference_params TEXT(SQLite 无 JSON 类型 · JSON 字符串 · 跟
    ai_providers.extra_json 同 pattern)
  - builtin INT:1 = mai_v4 种入 · 0 = 用户加
  - enabled INT:可禁用单 model · list query filter

Seed mai_v4 builtin(per PM Q6 SPEC-LOCK):
  - INSERT 在 CREATE TABLE 分支内 · 只首次建表时执行 · 删了不复活
  - 字段从 backend/config/tts_models.json 当前 mai_v4 spec 1:1 抄过来(双源期对照 ·
    阶段 ③ B.4-y2 删 tts_models.json 的 server_url 字段后,两份内容字段对齐)
  - 允许 PATCH 编辑 · DELETE 允许(类比 ai_providers builtin 决策)

注意:registry.py::_CONFIG 是 module-import 期 eager load · 本 migration 在
startup hook 跑(post-import)· 不动 registry · 由 tts_models_cache 启动期 sync
读 DB 覆盖 gsv 段(registry.list_models("gsv") 等 gsv 段路径切到 cache)。

幂等:CREATE TABLE IF NOT EXISTS · INSERT 仅在首次建表时跑(后续 restart 表
已存在 → 跳过 INSERT · 不复活已 DELETE 的 builtin · 这是 PM 拍板的"删了不复活"
语义)。
"""
from __future__ import annotations

import logging

from sqlalchemy import text

from backend.database import engine

logger = logging.getLogger(__name__)


async def _table_exists(conn, table: str) -> bool:
    rows = (await conn.execute(text(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=:n"
    ), {"n": table})).fetchall()
    return len(rows) > 0


# mai_v4 builtin row 字段 · 来源:backend/config/tts_models.json gsv.models[0]
# 改字段 = 改这里 + tts_models.json 同步(双源期 fallback 用)。
# label 跟 tts_models.json:42 "Mai v4(樱岛麻衣 ja)" 一致。
# 2026-06-14 · wav_remote_dir 默认值改本地 host 路径(5070ti 局域网机)·
# 旧值是公网 autodl 路径 · seed-only-on-create 不覆盖现有 row · 故 run_migration
# 末尾加幂等 UPDATE 把仍等于旧值的行迁到新值(只迁等于旧值的 · 不覆盖手动设的)。
_OLD_PUBLIC_REMOTE = "/workspace/GSVI/mai_emotion_bank/"
_NEW_LOCAL_REMOTE = (
    "D:/GPT-sovits/GPT-SoVITS-v2pro-20250604-nvidia50/reference_audio/mai_v4/"
)

_MAI_V4_SEED = {
    "provider": "gsv",
    "model_id": "mai_v4",
    "label": "Mai v4(樱岛麻衣 ja)",
    "mode": "trained",
    "tts_language": "ja",
    "gpt_weights": "GPT_weights_v4/mai_v4-e15.ckpt",
    "sovits_weights": "SoVITS_weights_v4/mai_v4_e5_s1380_l32.pth",
    "lab_dir": "tts/gsv/mai_v4",
    "wav_remote_dir": _NEW_LOCAL_REMOTE,
    "default_emotion": "日常",
    "inference_params": (
        '{"top_k":15,"top_p":1.0,"temperature":1.0,"speed_factor":1.0}'
    ),
}


async def run_migration() -> None:
    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA foreign_keys = ON"))

        if await _table_exists(conn, "tts_models"):
            # 2026-06-14 · 表已建过 · 跑幂等更新:若 mai_v4 行 wav_remote_dir
            # 仍等于旧公网路径 → 迁到新本地路径(只在等于旧值时改 · 不覆盖
            # 用户手动改过的值)。
            result = await conn.execute(text("""
                UPDATE tts_models
                SET wav_remote_dir = :new, updated_at = CURRENT_TIMESTAMP
                WHERE provider = 'gsv' AND model_id = 'mai_v4'
                  AND wav_remote_dir = :old
            """), {"new": _NEW_LOCAL_REMOTE, "old": _OLD_PUBLIC_REMOTE})
            n = result.rowcount  # type: ignore[attr-defined]
            if n and n > 0:
                logger.info(
                    "[tts_models_seed] migrated mai_v4 wav_remote_dir: "
                    "old=%r → new=%r (rows=%d)",
                    _OLD_PUBLIC_REMOTE, _NEW_LOCAL_REMOTE, n,
                )
            else:
                logger.info(
                    "[tts_models_seed] table exists · mai_v4 wav_remote_dir "
                    "unchanged (already migrated or user-customized)"
                )
            return

        # ---- CREATE TABLE ----
        await conn.execute(text("""
            CREATE TABLE tts_models (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                provider          TEXT    NOT NULL
                                  CHECK(provider IN ('gsv','fish','cosyvoice')),
                model_id          TEXT    NOT NULL,
                label             TEXT    NOT NULL,
                mode              TEXT,
                tts_language      TEXT,
                gpt_weights       TEXT,
                sovits_weights    TEXT,
                lab_dir           TEXT,
                wav_remote_dir    TEXT,
                default_emotion   TEXT,
                inference_params  TEXT,
                enabled           INTEGER NOT NULL DEFAULT 1,
                builtin           INTEGER NOT NULL DEFAULT 0,
                created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(provider, model_id)
            )
        """))
        await conn.execute(text(
            "CREATE INDEX idx_tts_models_provider_enabled "
            "ON tts_models(provider, enabled)"
        ))
        logger.info("[tts_models_seed] table tts_models created")

        # ---- SEED mai_v4 builtin · 仅首次建表 ----
        await conn.execute(text("""
            INSERT INTO tts_models (
                provider, model_id, label, mode, tts_language,
                gpt_weights, sovits_weights, lab_dir, wav_remote_dir,
                default_emotion, inference_params, enabled, builtin
            ) VALUES (
                :provider, :model_id, :label, :mode, :tts_language,
                :gpt_weights, :sovits_weights, :lab_dir, :wav_remote_dir,
                :default_emotion, :inference_params, 1, 1
            )
        """), _MAI_V4_SEED)
        logger.info(
            "[tts_models_seed] seeded mai_v4 builtin row "
            "(provider=gsv model_id=mai_v4 label=%r)",
            _MAI_V4_SEED["label"],
        )
