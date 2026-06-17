"""INV (2026-06-11) — A-ii thin reference · strip GSV spread 字段 + server_url。

阶段 ② migration:把 DB characters.voice_model 里 provider='gsv' 的 spread 副本
全清掉,改成 thin reference {provider, model, voice?, tts_language?}。运行时:
  - server_url: voice_model 已无字段 → 全局 ai_providers (type='tts' name='gsv')
                → _DEFAULT_SERVER_URL(三 tier 第二/三档)
  - 其它 6 字段(gpt_weights / sovits_weights / lab_dir / wav_remote_dir /
                default_emotion / inference_params): voice_model 已无字段 →
                tts_models_cache.get_gsv_model_spec(model_id) → 各字段 _DEFAULT

调研发现:当前 DB 命中 spread 字段的只 cid=1 Momo(provider='gsv' · 借壳 Mai
mai_v4 ja 路径)· 其余 character 都 cosyvoice / fish。所以本 migration 实际只
影响 1 行(per WHERE provider='gsv')· 但 json_remove 是幂等 · 重跑零影响。

策略 · 仅清"被 thin 化的字段",非 thin 字段(provider/model/voice/tts_language)
保留 · 保留 backward compat 防误删 user 后加字段。
"""
from __future__ import annotations

import logging

from sqlalchemy import text

from backend.database import engine

logger = logging.getLogger(__name__)

# spread 字段列表 · 全是 阶段 ① backend tier 已能从 model spec / global / _DEFAULT
# 兜底解析的字段。其余字段(provider/model/voice/tts_language)是 thin reference
# 必留 · 不清。
_FIELDS_TO_STRIP = [
    "server_url",                # → ai_providers global (阶段 ① B.1)
    "gpt_weights",               # → tts_models_cache spec
    "sovits_weights",            # → tts_models_cache spec
    "emotion_bank_dir",          # → tts_models_cache spec (字段名:lab_dir)
    "remote_emotion_bank_dir",   # → tts_models_cache spec (字段名:wav_remote_dir)
    "default_emotion",           # → tts_models_cache spec
    "inference_params",          # → tts_models_cache spec
    "mode",                      # → tts_models_cache spec (trained / zeroshot)
    "label",                     # spread 时被 VoicePicker 排除但保险起见列上
    # 顺手清 V2'' 旧字段别名(gsv.py:_resolve_weights_field 兼容 'placeholder')·
    # 这俩在历史 voice_model 里也可能 spread 进 · 不留隐性副本
    "gpt_path",
    "sovits_path",
]


async def run_migration() -> None:
    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA foreign_keys = ON"))

        # before snapshot · 仅 log 行数 + 是否含 spread · 不 log 完整 JSON 避免 PII
        before_rows = (await conn.execute(text("""
            SELECT id, name FROM characters
            WHERE voice_model IS NOT NULL
              AND json_extract(voice_model, '$.provider') = 'gsv'
        """))).fetchall()
        if not before_rows:
            logger.info(
                "[voice_model_thin] no characters with provider='gsv' · skip"
            )
            return

        logger.info(
            "[voice_model_thin] will strip %d field(s) on %d gsv character(s)",
            len(_FIELDS_TO_STRIP), len(before_rows),
        )

        # 构造 json_remove(...) 调用 · 每字段一个 path arg
        # characters 表无 updated_at 列(只有 created_at)· 不写时间戳
        paths = ", ".join(f"'$.{f}'" for f in _FIELDS_TO_STRIP)
        await conn.execute(text(f"""
            UPDATE characters
            SET voice_model = json_remove(voice_model, {paths})
            WHERE voice_model IS NOT NULL
              AND json_extract(voice_model, '$.provider') = 'gsv'
        """))

        # after snapshot · log thin 后字段(用 json_object 收口避免顺序差异)
        after_rows = (await conn.execute(text("""
            SELECT id, name, voice_model FROM characters
            WHERE voice_model IS NOT NULL
              AND json_extract(voice_model, '$.provider') = 'gsv'
        """))).fetchall()
        for cid, name, vm in after_rows:
            logger.info(
                "[voice_model_thin] post cid=%s name=%r voice_model=%s",
                cid, name, vm,
            )
