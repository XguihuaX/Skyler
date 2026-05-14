"""v4 persona engineering segment 2 — Mai voice tts_language='ja' migration。

Mai 的 CosyVoice voice (``cosyvoice-v3.5-plus-bailian-a19f528011c1446eafd4c4990301270f``)
是用户复刻的日语 sample,合成中文时音色差。给该 voice 标 ``tts_language='ja'``
后,renderer 走 layer_a.j2 的 ja 分支,LLM 输出 ``<ja>日语翻译</ja>``,TTS
取 ja 段,中文给字幕。

D-S2-3 sign-off:**按 voice_id 匹配,不按 character_id**。同一个 voice 被
任何 character 使用都会自动标 ja。当前 DB 实测覆盖 id=1 (Momo/Mai 借壳)
+ id=101 (樱岛麻衣) 两行 characters。新增 character 用相同 voice 时仍
自动覆盖(下次跑 migration 触发)。

幂等:UPDATE 内含 ``tts_language IS NULL OR tts_language != 'ja'`` 条件,
重复跑只补缺;已标 ja 的行不会被反复 UPDATE(``rowcount`` 准确反映本次实际
改动数)。
"""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy import text

from backend.database import engine

logger = logging.getLogger(__name__)


# Mai 复刻的日语 voice id。与 ``characters.voice_model`` JSON 字段的 ``$.voice``
# 子键完全字符串匹配(SQLite ``json_extract`` 返字符串,无 trailing 空白)。
_MAI_VOICE_ID = "cosyvoice-v3.5-plus-bailian-a19f528011c1446eafd4c4990301270f"


_UPDATE_SQL = """
UPDATE characters
SET voice_model = json_set(voice_model, '$.tts_language', 'ja')
WHERE voice_model IS NOT NULL
  AND json_extract(voice_model, '$.voice') = :voice_id
  AND (
      json_extract(voice_model, '$.tts_language') IS NULL
      OR json_extract(voice_model, '$.tts_language') != 'ja'
  )
"""


async def run_migration() -> None:
    async with engine.begin() as conn:
        result = await conn.execute(text(_UPDATE_SQL), {"voice_id": _MAI_VOICE_ID})
        rowcount = getattr(result, "rowcount", 0) or 0
    logger.info(
        "[v4_seg2_mai_ja] voice=%s tagged tts_language=ja; rows_updated=%d",
        _MAI_VOICE_ID, rowcount,
    )


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    asyncio.run(run_migration())
