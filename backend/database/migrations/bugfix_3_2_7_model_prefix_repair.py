"""Bugfix-3.2.7 — DB seed model 缺 LiteLLM provider 前缀的 hotfix 修补。

背景
----
Bugfix-3.1 seed 时 model 字段格式不一致:Qwen 走 OpenAI-compatible 协议但 seed
裸名(``qwen3.6-plus`` / ``qwen3.6-max-preview``),DeepSeek 也漏前缀
(``deepseek-chat``)。LiteLLM ``acompletion`` 要求 ``provider/model`` 格式,
裸 model 直接抛 ``BadRequestError: LLM Provider NOT provided`` → 主聊天 500。

修补 3 条 UPDATE,只命中"裸 model name"的行,已修过的不动,幂等:

  qwen3.6-plus        → openai/qwen3.6-plus
  qwen3.6-max-preview → openai/qwen3.6-max-preview
  deepseek-chat       → deepseek/deepseek-chat

并行修补:bugfix_3_1_ai_providers.py seed 数据已同步改前缀,防新 install 同 bug。
两层修补独立 — 新 install 走 3.1 不重复,老用户走 3.2.7 一次性修补。
"""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy import text

from backend.database import engine

logger = logging.getLogger(__name__)


# (old_bare_model, new_prefixed_model)。LiteLLM 协议前缀:
#   - Qwen DashScope OpenAI-compatible → openai/
#   - DeepSeek native LiteLLM provider → deepseek/
_MODEL_PREFIX_REPAIRS = [
    ("qwen3.6-plus",        "openai/qwen3.6-plus"),
    ("qwen3.6-max-preview", "openai/qwen3.6-max-preview"),
    ("deepseek-chat",       "deepseek/deepseek-chat"),
]


async def run_migration() -> None:
    """Bugfix-3.2.7 主迁移。幂等:WHERE model=<bare> 已修过的不命中。"""
    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA foreign_keys = ON"))

        # ai_providers 可能在 fresh install 上还没建(理论上 3.1 在前)。
        # 用 sqlite_master 做防御性检查 — 若表缺失直接跳过(3.1 会兜底 seed
        # 正确前缀,这里没东西修)。
        rows = (await conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='ai_providers'"
        ))).fetchall()
        if not rows:
            logger.info("[bugfix-3.2.7] ai_providers table not present yet, skip")
            return

        total = 0
        for old_model, new_model in _MODEL_PREFIX_REPAIRS:
            result = await conn.execute(text("""
                UPDATE ai_providers
                SET model = :new_model, updated_at = CURRENT_TIMESTAMP
                WHERE model = :old_model
            """), {"old_model": old_model, "new_model": new_model})
            n = getattr(result, "rowcount", 0) or 0
            if n > 0:
                logger.info(
                    "[bugfix-3.2.7] repaired %d row(s): %r → %r",
                    n, old_model, new_model,
                )
            total += n

        if total > 0:
            logger.warning(
                "[bugfix-3.2.7] repaired %d qwen/deepseek model prefix(es) — "
                "DB seeded without LiteLLM provider prefix would have caused "
                "BadRequestError('LLM Provider NOT provided') from acompletion",
                total,
            )
        else:
            logger.info(
                "[bugfix-3.2.7] no bare-model rows to repair (DB already has "
                "LiteLLM prefixes or no seed rows yet)"
            )

    logger.info("[bugfix-3.2.7] migration done")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    asyncio.run(run_migration())
