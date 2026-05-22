"""V4 voice greeting — character_voice_lines 表(2026-05-22)。

立绘馆放大组件 onEnter 触发随机 voice line 播放;PM 提前上传音频文件,
系统纯 storage + serve(不走 TTS 预渲染)。每 character 可挂 N 条 voice
lines,随机选 1 条播放。

字段语义:
    id                INTEGER PRIMARY KEY · auto-increment
    character_id      INTEGER NOT NULL REFERENCES characters(id) ON DELETE CASCADE
    audio_path        TEXT NOT NULL · 相对 backend/static/voice_lines/ 路径,
                      形如 ``101/<uuid>.wav``;前端通过 ``/static/voice_lines/
                      101/<uuid>.wav`` 拿
    text_description  TEXT NULL · 文本描述(optional;PM 填 Mai 风格台词
                      或 emotion marker 注)
    language          TEXT NULL · 语言代码 'ja' / 'zh' / 'en'(optional)
    duration_ms       INTEGER · mutagen 提取的音频时长(ms)
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP

幂等:CREATE TABLE IF NOT EXISTS。
"""
import asyncio
import logging

from sqlalchemy import text

from backend.database import engine

logger = logging.getLogger(__name__)


async def _table_exists(conn, table: str) -> bool:
    rows = (await conn.execute(text(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=:t"
    ), {"t": table})).fetchall()
    return len(rows) > 0


async def run_migration() -> None:
    """V4 voice greeting 主迁移函数。幂等。"""
    async with engine.begin() as conn:
        if await _table_exists(conn, "character_voice_lines"):
            logger.info("[v4_voice_greeting] character_voice_lines 已存在,跳过")
            return

        await conn.execute(text("""
            CREATE TABLE character_voice_lines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                character_id INTEGER NOT NULL
                    REFERENCES characters(id) ON DELETE CASCADE,
                audio_path TEXT NOT NULL,
                text_description TEXT,
                language TEXT,
                duration_ms INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        # 加 index 加速 per-character list / random 查询
        await conn.execute(text("""
            CREATE INDEX idx_voice_lines_character_id
            ON character_voice_lines(character_id)
        """))
        logger.info("[v4_voice_greeting] character_voice_lines 表已创建 + index")

    logger.info("[v4_voice_greeting] migration done")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    asyncio.run(run_migration())
