"""Bugfix-3.2.8 — ai_providers dedup + trim non-Qwen builtin + UNIQUE index。

老 DB 现状(3.2.7 ship 后真机查):
  - Qwen 下 Plus / Max preview 各 2 个(3.1 seed 用 (vendor_id, model) 判重,
    3.2.6→3.2.7 升级时 model 字符串换前缀导致 seed 漏匹配重插)
  - 非 Qwen builtin (openai/anthropic/deepseek) 凭证未配但默认 seed 出来,
    UI 概念混乱;用户拍板:只保留 Qwen 2 个 builtin 作 dogfood,其他 vendor
    一律 trim 空,用户用 [+ 添加模型] 弹 modal 自填

3 件:

1. **dedup** —— ROW_NUMBER() OVER (PARTITION BY vendor_id, name ORDER BY
   is_active DESC, enabled DESC, id ASC) 保最优行,删其他。
   "最优" = active 优先 > enabled 优先 > 早 seed (id 小) 优先。

2. **trim non-Qwen builtin** —— DELETE FROM ai_providers WHERE type='llm'
   AND provider_kind = 'builtin' AND vendor_id IN ('openai','anthropic',
   'deepseek')。
   仅删 builtin seed 行;custom 行(用户自填的 deepseek-v4-flash 等)保留。
   bugfix-Providers (2026-05-15):原版漏 ``provider_kind`` 守卫,每次启动
   把用户加的 custom DeepSeek 一并清掉,导致 UI 加 model → 重启消失。

3. **UNIQUE INDEX** —— ix_ai_providers_vendor_name_type ON
   ai_providers(vendor_id, name, type)。防未来 INSERT 重复。

幂等:
  - dedup ROW_NUMBER 跑两次:第二次每 (vendor_id, name) 仅 1 行 → rn>1 永空,
    DELETE 命中 0 行
  - trim non-qwen 跑两次:第二次目标行已无 → DELETE 0 行
  - CREATE UNIQUE INDEX IF NOT EXISTS

Caveat:
  vendor_id 可能为 NULL (ungrouped provider) — SQLite NULL 在 UNIQUE INDEX
  里允许多个,所以多个 NULL+同 name+同 type 都过。这是 SQL 标准行为,符合预期
  (本 stage 不强制 NULL 唯一)。
"""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy import text

from backend.database import engine

logger = logging.getLogger(__name__)


_TRIM_VENDORS = ("openai", "anthropic", "deepseek")


async def _table_exists(conn, table: str) -> bool:
    rows = (await conn.execute(text(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=:n"
    ), {"n": table})).fetchall()
    return len(rows) > 0


async def run_migration() -> None:
    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA foreign_keys = ON"))

        if not await _table_exists(conn, "ai_providers"):
            logger.info("[bugfix-3.2.8] ai_providers table not present yet, skip")
            return

        # ---- Step 1: dedup by (vendor_id, name) ----
        # SQLite 3.25+ 支持 ROW_NUMBER() window function。
        # 保留每组最优行(active>enabled>id ASC),DELETE 其他。
        dedup = await conn.execute(text("""
            DELETE FROM ai_providers
            WHERE id IN (
                SELECT id FROM (
                    SELECT id, ROW_NUMBER() OVER (
                        PARTITION BY vendor_id, name, type
                        ORDER BY is_active DESC, enabled DESC, id ASC
                    ) AS rn
                    FROM ai_providers
                )
                WHERE rn > 1
            )
        """))
        deduped = getattr(dedup, "rowcount", 0) or 0
        if deduped > 0:
            logger.warning(
                "[bugfix-3.2.8] deduped %d duplicate row(s) "
                "(kept active>enabled>id-asc per (vendor_id, name, type))",
                deduped,
            )
        else:
            logger.info("[bugfix-3.2.8] no duplicates to dedup")

        # ---- Step 2: trim non-Qwen **builtin** LLM ----
        # 用户拍板:只 Qwen 2 个 builtin 作 dogfood (依赖 .env DASHSCOPE_API_KEY)。
        # OpenAI / Anthropic / DeepSeek seed 行删除 — 用户用 [+ 添加模型] modal
        # 自填(走 AddModelModal 的 raw model name + 自动前缀 helper)。
        #
        # bugfix-Providers (2026-05-15):必须 ``AND provider_kind = 'builtin'``
        # 守卫。原版一刀切,migration 每次启动 idempotent 跑 → 用户在 UI 加的
        # custom DeepSeek (provider_kind='custom') 会被一并清掉 → 重启 model
        # 消失。Qwen custom 行幸运逃过是因为 Qwen 不在 ``_TRIM_VENDORS``。
        trim = await conn.execute(text(f"""
            DELETE FROM ai_providers
            WHERE type = 'llm'
              AND provider_kind = 'builtin'
              AND vendor_id IN ({", ".join("'" + v + "'" for v in _TRIM_VENDORS)})
        """))
        trimmed = getattr(trim, "rowcount", 0) or 0
        if trimmed > 0:
            logger.warning(
                "[bugfix-3.2.8] trimmed %d non-Qwen builtin LLM provider(s) "
                "(vendors=%s) — users add their own via [+ 添加模型]",
                trimmed, _TRIM_VENDORS,
            )
        else:
            logger.info(
                "[bugfix-3.2.8] no non-Qwen builtin LLM to trim "
                "(custom rows for these vendors are preserved)"
            )

        # ---- Step 3: UNIQUE INDEX 防未来重复 ----
        # NOTE: 若 dedup 没清干净 (理论上不可能, ROW_NUMBER 已保证), 这条会报错。
        await conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS ix_ai_providers_vendor_name_type
            ON ai_providers(vendor_id, name, type)
        """))
        logger.info(
            "[bugfix-3.2.8] ensured UNIQUE INDEX ix_ai_providers_vendor_name_type"
        )

    logger.info("[bugfix-3.2.8] migration done")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    asyncio.run(run_migration())
