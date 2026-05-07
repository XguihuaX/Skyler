"""V3-G chunk 2.6 — ``pending_briefings`` 表。

新表：跨进程 / 跨重启的 wake_call_briefing 中间状态。stage 1 cron 触发时
聚合数据写一行，stage 2 用户响应时 ChatAgent 读出来注入 system prompt。

为什么用表而不是内存 dict
=========================

* **跨重启幸存**：用户在 wake call 后正要回应，后端被 hot-reload，内存
  dict 蒸发 → 用户的"嗯"再也对不上简报。表确保 stage 1 写、stage 2 读
  在不同进程实例间也成立。
* **TTL 过期判定**：``created_at + ttl_minutes < now`` 在 SQL 端就能筛，
  不需 schedule 后台 sweeper。
* **多 user 并发**：dict 也行但 lock-free 索引（user_id, consumed_at,
  created_at）走 SQLite 更省事。

字段语义
========

* ``user_id``       行主人。索引第一段。
* ``trigger_name``  一定 ``"wake_call"``（其他 trigger 暂不写本表）。预留
  字符串而非枚举：未来加 ``meal_call`` / ``evening_call`` 之类同 pattern
  trigger 时不需要 schema 变动。
* ``briefing_data_json``  聚合阶段拿到的结构化数据（time / calendar /
  todos / city）。stage 2 prompt 的 ``{briefing_data_json}`` 占位由它填。
  weather / news 不存（stage 2 LLM 用 enable_search 自己查 —— 缓存在表里
  也是死的，stage 2 时再查更新鲜）。
* ``character_id``  stage 1 解析的目标 character。stage 2 必须用同一个，
  否则人设错位。
* ``conversation_id``  stage 1 用的 conversation。stage 2 默认沿用让
  历史连贯（用户可能切了 conv，但本 chunk 不处理这种边缘情况，保留下次
  conversation 的 wake_call 仍写新行）。
* ``ttl_minutes``  默认 30，从 ``config.proactive.wake_call_briefing.
  pending_ttl_minutes`` 继承。超时不再注入 addendum，但行不删 —— 后续
  housekeeping job 一并扫。
* ``consumed_at``  NULL = 未消费。stage 2 ChatAgent 注入 addendum 后
  写入 utcnow。non-null = 不再命中。

幂等
====

PRAGMA + CREATE TABLE IF NOT EXISTS。重复执行不报错；表已存在跳过 index
重建（SQLite ``CREATE INDEX IF NOT EXISTS``）。
"""
import asyncio
import logging

from sqlalchemy import text

from backend.database import engine

logger = logging.getLogger(__name__)


async def _table_exists(conn, table: str) -> bool:
    rows = (await conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name=:t"),
        {"t": table},
    )).fetchall()
    return len(rows) > 0


async def run_migration() -> None:
    """V3-G chunk 2.6 主迁移函数。幂等。

    表 + 索引各自单独 ``IF NOT EXISTS`` ——一次只创建缺失部分。这样旧 DB
    （chunk 2.6 早期版本只建了表没建索引）二次跑也能补上索引。
    """
    async with engine.begin() as conn:
        # 表
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS pending_briefings (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id             VARCHAR(64)  NOT NULL,
                trigger_name        VARCHAR(64)  NOT NULL,
                briefing_data_json  TEXT         NOT NULL,
                character_id        INTEGER      NOT NULL,
                conversation_id     INTEGER      NOT NULL,
                created_at          DATETIME     NOT NULL,
                ttl_minutes         INTEGER      NOT NULL DEFAULT 30,
                consumed_at         DATETIME     NULL
            )
        """))
        # 复合索引：stage 2 query 走 (user_id, consumed_at IS NULL, created_at DESC)
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_pending_briefings_lookup
            ON pending_briefings (user_id, consumed_at, created_at)
        """))
        logger.info(
            "V3-G-chunk2.6: pending_briefings 表 + 索引就绪（IF NOT EXISTS 幂等）"
        )

    logger.info("V3-G chunk 2.6 migration done")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    asyncio.run(run_migration())
