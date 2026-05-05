"""V3-G' chunk 1c：把 Momo (id=1) 的 voice_model 默认填成 cosyvoice longyumi_v3。

背景：v3-G' 之前 Momo voice_model 字段为 NULL，后端 ``parse_voice_config``
回退到 ``config.yaml`` ``tts.cosyvoice.default_voice`` 全局默认。这条路径仍然
work，但 CharacterPanel 编辑 Momo 时下拉显示"未配置（使用全局默认）"，体验
不如显式选中。

迁移把"全局默认"具象化写到 character.voice_model 字段：

    {"provider": "cosyvoice", "voice": "longyumi_v3", "instruct_supported": false}

幂等：仅在 ``voice_model`` 为 NULL / 空时写入；用户已经配置（旧 plain 字符串
/ 新 JSON / 自定义其他 provider）一律保留不动。

为何不用 SQL DEFAULT
--------------------
SQLAlchemy column ``default=None`` 无法在 v3-G' 启动时回填已有行（DEFAULT
只对 INSERT 生效）。改用一条幂等 lifespan migration 一次性处理。
"""
import asyncio
import json
import logging

from sqlalchemy import text

from backend.database import engine

logger = logging.getLogger(__name__)


_MOMO_CHARACTER_ID = 1

# 默认音色 = cosyvoice longyumi_v3 / instruct_supported=false。
# 与 config.yaml ``tts.cosyvoice.default_voice`` 保持一致；未来要换默认在
# config.yaml + 这里同步改即可。
_DEFAULT_VOICE_JSON = json.dumps(
    {
        "provider": "cosyvoice",
        "voice": "longyumi_v3",
        "instruct_supported": False,
    },
    ensure_ascii=False,
)


async def run_migration() -> None:
    """V3-G' Momo 默认音色填充。幂等。"""
    async with engine.begin() as conn:
        row = (await conn.execute(
            text(
                "SELECT id, name, voice_model FROM characters WHERE id = :id"
            ),
            {"id": _MOMO_CHARACTER_ID},
        )).fetchone()

        if row is None:
            logger.warning(
                "V3-G' momo voice: character id=%d not found, skipping",
                _MOMO_CHARACTER_ID,
            )
            return

        _, name, voice_model = row
        logger.info(
            "V3-G' momo voice: found id=%d name=%s, current voice_model=%r",
            _MOMO_CHARACTER_ID, name,
            (voice_model[:60] if voice_model else voice_model),
        )

        # 仅 NULL / 空 / 全空白 → 写默认；任何非空值（包括用户手填的旧 plain
        # 字符串）保留，由 CharacterPanel UI 提示"自定义"让用户决定是否覆盖。
        if voice_model and voice_model.strip():
            logger.info(
                "V3-G' momo voice: voice_model already populated, keeping",
            )
            return

        await conn.execute(
            text(
                "UPDATE characters SET voice_model = :v WHERE id = :id"
            ),
            {"v": _DEFAULT_VOICE_JSON, "id": _MOMO_CHARACTER_ID},
        )
        logger.info(
            "V3-G' momo voice: voice_model set to %s",
            _DEFAULT_VOICE_JSON,
        )

    logger.info("V3-G' momo default voice migration done")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    asyncio.run(run_migration())
