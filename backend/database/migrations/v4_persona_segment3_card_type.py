"""V4 persona engineering segment 3 — character_personas.card_type 列。

Persona v2 升级第一步:给 ``character_personas`` 加 ``card_type`` 列(枚举
``'社交' | '助手'``),区分两类卡。当前真实消费点(本迁移 ship 时):

- 前端编辑器(Slice 2)按 card_type 切社交 / 助手两套字段
- ``daily_plan`` 扩 multi-character 那次 commit(backlog · ROADMAP 已记)
  必须 gate ``card_type='助手'`` skip,避免给助手卡生成"她的一天"

本迁移不动模板 / 不动渲染链路(card_type 不进 prompt,只做 gate 元数据)。

幂等:``PRAGMA table_info`` 检查列存在;UPDATE 用 ``is_active=1`` 锚定,
避免误伤同角色其他 variant(虽然当前每 cid 只一个 variant,但 schema 允许
多 variant,本约束写死)。

字段语义::

    card_type TEXT DEFAULT '社交'

    - '社交'  默认 · 现有 9 个角色全部回填 · 有 DailyAgent / 主动陪伴
    - '助手'  助手卡 · 当前仅 cid=100(阿芙洛狄忒)· 无独立日程

回填策略:列加好后立刻 UPDATE cid=100 的 active variant 到 '助手'。
"""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy import text

from backend.database import engine

logger = logging.getLogger(__name__)


async def _column_exists(conn, table: str, column: str) -> bool:
    rows = (await conn.execute(text(f"PRAGMA table_info({table})"))).fetchall()
    return any(row[1] == column for row in rows)


async def run_migration() -> None:
    """V4 persona segment 3 主迁移函数。幂等。"""
    async with engine.begin() as conn:
        if await _column_exists(conn, "character_personas", "card_type"):
            logger.info(
                "V4-persona-seg3: character_personas.card_type 已存在,跳过 ALTER",
            )
        else:
            await conn.execute(
                text(
                    "ALTER TABLE character_personas "
                    "ADD COLUMN card_type TEXT DEFAULT '社交'"
                )
            )
            logger.info(
                "V4-persona-seg3: character_personas.card_type 列已添加 "
                "(DEFAULT '社交' · 现有行自动回填 '社交')",
            )

        # 回填 cid=100 active variant → '助手'。is_active=1 锚定避免误伤其他
        # variant;若 cid=100 已被人手改成 '助手' 也无副作用(UPDATE 同值)。
        result = await conn.execute(
            text(
                "UPDATE character_personas SET card_type = '助手' "
                "WHERE character_id = 100 AND is_active = 1 "
                "AND (card_type IS NULL OR card_type != '助手')"
            )
        )
        if result.rowcount > 0:
            logger.info(
                "V4-persona-seg3: cid=100 active variant card_type → '助手' "
                "(%d 行更新)",
                result.rowcount,
            )
        else:
            logger.info(
                "V4-persona-seg3: cid=100 active variant card_type 已是 '助手' "
                "或无 active variant,跳过 UPDATE",
            )

    logger.info("V4 persona segment 3 migration done")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    asyncio.run(run_migration())
