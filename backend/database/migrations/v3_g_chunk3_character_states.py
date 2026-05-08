"""V3-G chunk 3b — ``character_states`` 表。

新表：每个 character 一行，承载 mood / intimacy / current_thought /
current_activity 四项跨 turn 累积状态 + 时间戳。

字段语义
========

* ``character_id``       FK → characters.id；UNIQUE 一对一映射
* ``mood``               enum 七选一 ``happy / sad / curious / calm /
                         excited / tired / neutral``。application 层
                         ``_VALID_MOODS`` 校验；下放 DB 不强制（未来加新
                         mood 不需 schema migration）
* ``intimacy``           int 0-100，clamping 在所有写入路径
* ``current_thought``    LLM 偶尔填的短句（"在想用户的项目"）
* ``current_activity``   LLM 偶尔填的短句（"在烤面包"），闲笔感
* ``last_interaction_at`` 任何 user message 都更新；用于"超过 N 小时未互动
                         → mood drift to tired" 之类后续规则
* ``updated_at``         任何字段变化都更新

幂等
====

每个 schema 操作独立 ``IF NOT EXISTS``（chunk 2.6 footgun 教训：单次
``if table_exists: return`` 老 DB 升上来时 INDEX 漏建）。
"""
import asyncio
import logging

from sqlalchemy import text

from backend.database import engine

logger = logging.getLogger(__name__)


async def run_migration() -> None:
    """V3-G chunk 3b 主迁移函数。幂等。"""
    async with engine.begin() as conn:
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS character_states (
                id                  INTEGER     PRIMARY KEY AUTOINCREMENT,
                character_id        INTEGER     NOT NULL UNIQUE,
                mood                VARCHAR(32) NOT NULL DEFAULT 'neutral',
                intimacy            INTEGER     NOT NULL DEFAULT 0,
                current_thought     TEXT        NULL,
                current_activity    VARCHAR(64) NULL,
                last_interaction_at DATETIME    NOT NULL,
                updated_at          DATETIME    NOT NULL
            )
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_character_state_char
            ON character_states (character_id)
        """))
        logger.info(
            "V3-G-chunk3: character_states 表 + 索引就绪（IF NOT EXISTS 幂等）"
        )

    logger.info("V3-G chunk 3b migration done")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    asyncio.run(run_migration())
