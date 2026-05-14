"""Bugfix-3.1 — AI Providers backend foundation。

3 张表 + builtin seed:
  1. ``ai_vendors``            —— provider 厂商(qwen / openai / anthropic /
                                  deepseek / 用户自定义)。每个 vendor 一组
                                  凭证, 多个 model 共用
  2. ``ai_vendor_credentials`` —— 厂商 API key (fernet 加密)。UNIQUE on
                                  vendor_id, 每 vendor 一组
  3. ``ai_providers``          —— 具体 model 条目, FK 指 vendor。type ∈
                                  {llm, asr, tts}, per-type 至多一个 is_active

Seed 4 个 builtin vendor + 7 个 LLM provider(用户拍板列表):
  qwen      → Qwen 3.6 Plus / Max preview
  openai    → GPT-4o / GPT-4o Mini
  anthropic → Claude Sonnet 4.6 / Opus 4.7
  deepseek  → DeepSeek Chat

ASR / TTS 暂不 seed, 下一 sub-stage (3.3) 加 ASR dispatcher 时再处理。

幂等: ``CREATE TABLE IF NOT EXISTS`` + builtin seed 用 ``INSERT OR IGNORE``
(vendor pk 已存在跳过)。重启不会重复 seed。
"""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy import text

from backend.database import engine

logger = logging.getLogger(__name__)


async def _table_exists(conn, table: str) -> bool:
    rows = (await conn.execute(text(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=:n"
    ), {"n": table})).fetchall()
    return len(rows) > 0


# 4 个 builtin vendor (拍板)
_BUILTIN_VENDORS = [
    {
        "id": "qwen",
        "name": "Qwen",
        "default_endpoint": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "credential_key_name": "DASHSCOPE_API_KEY",
        "color": "#615CED",
        "icon": "Sparkles",
    },
    {
        "id": "openai",
        "name": "OpenAI",
        "default_endpoint": "https://api.openai.com/v1",
        "credential_key_name": "OPENAI_API_KEY",
        "color": "#10A37F",
        "icon": "Brain",
    },
    {
        "id": "anthropic",
        "name": "Anthropic",
        "default_endpoint": "https://api.anthropic.com",
        "credential_key_name": "ANTHROPIC_API_KEY",
        "color": "#CC785C",
        "icon": "Brain",
    },
    {
        "id": "deepseek",
        "name": "DeepSeek",
        "default_endpoint": "https://api.deepseek.com",
        "credential_key_name": "DEEPSEEK_API_KEY",
        "color": "#4D6BFE",
        "icon": "Brain",
    },
]

# 7 个 builtin LLM provider (拍板)
_BUILTIN_PROVIDERS = [
    # (vendor_id, name, model)
    ("qwen",      "Qwen 3.6 Plus",         "qwen3.6-plus"),
    ("qwen",      "Qwen 3.6 Max preview",  "qwen3.6-max-preview"),
    ("openai",    "GPT-4o",                "openai/gpt-4o"),
    ("openai",    "GPT-4o Mini",           "openai/gpt-4o-mini"),
    ("anthropic", "Claude Sonnet 4.6",     "anthropic/claude-sonnet-4-6"),
    ("anthropic", "Claude Opus 4.7",       "anthropic/claude-opus-4-7"),
    ("deepseek",  "DeepSeek Chat",         "deepseek-chat"),
]


async def run_migration() -> None:
    """Bugfix-3.1 主迁移。幂等。"""
    async with engine.begin() as conn:
        # SQLite FK enforcement 默认 OFF — 我们用 ON DELETE CASCADE 必须开。
        # PRAGMA 是 per-connection, 这里 begin() 拿到一条连接, 写完 commit 即释放;
        # 全局生效靠每条连接出场都打开。aiosqlite 用 connect_args 可设, 但本
        # migration 只在自己作用域开就够 — CASCADE 是 DDL-defined 行为, table
        # 一旦建好后续 DELETE 即使 PRAGMA off 也能按定义工作? 不能 — 必须每次
        # query 时 ON。所以 services 层每次也要开。这里在 migration 完成后留
        # PRAGMA 注释, services 层自己管。
        await conn.execute(text("PRAGMA foreign_keys = ON"))

        # ---- ai_vendors ----
        if not await _table_exists(conn, "ai_vendors"):
            await conn.execute(text("""
                CREATE TABLE ai_vendors (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    vendor_kind TEXT NOT NULL DEFAULT 'custom'
                        CHECK(vendor_kind IN ('builtin', 'custom')),
                    default_endpoint TEXT,
                    credential_key_name TEXT NOT NULL,
                    color TEXT,
                    icon TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
            logger.info("[bugfix-3.1] ai_vendors table created")
        else:
            logger.info("[bugfix-3.1] ai_vendors exists, skip")

        # ---- ai_vendor_credentials ----
        if not await _table_exists(conn, "ai_vendor_credentials"):
            await conn.execute(text("""
                CREATE TABLE ai_vendor_credentials (
                    vendor_id TEXT PRIMARY KEY,
                    key_value TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (vendor_id) REFERENCES ai_vendors(id)
                        ON DELETE CASCADE
                )
            """))
            logger.info("[bugfix-3.1] ai_vendor_credentials table created")
        else:
            logger.info("[bugfix-3.1] ai_vendor_credentials exists, skip")

        # ---- ai_providers ----
        if not await _table_exists(conn, "ai_providers"):
            await conn.execute(text("""
                CREATE TABLE ai_providers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    vendor_id TEXT,
                    type TEXT NOT NULL CHECK(type IN ('llm', 'asr', 'tts')),
                    name TEXT NOT NULL,
                    model TEXT NOT NULL,
                    endpoint TEXT,
                    extra_json TEXT,
                    provider_kind TEXT NOT NULL DEFAULT 'custom'
                        CHECK(provider_kind IN ('builtin', 'custom')),
                    enabled INTEGER NOT NULL DEFAULT 1,
                    is_active INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (vendor_id) REFERENCES ai_vendors(id)
                        ON DELETE SET NULL
                )
            """))
            await conn.execute(text(
                "CREATE INDEX idx_ai_providers_type_active "
                "ON ai_providers(type, is_active)"
            ))
            await conn.execute(text(
                "CREATE INDEX idx_ai_providers_vendor "
                "ON ai_providers(vendor_id)"
            ))
            logger.info("[bugfix-3.1] ai_providers table created")
        else:
            logger.info("[bugfix-3.1] ai_providers exists, skip")

        # ---- seed builtin vendors ----
        seeded_vendors = 0
        for v in _BUILTIN_VENDORS:
            result = await conn.execute(text("""
                INSERT OR IGNORE INTO ai_vendors
                    (id, name, vendor_kind, default_endpoint,
                     credential_key_name, color, icon)
                VALUES (:id, :name, 'builtin', :default_endpoint,
                        :credential_key_name, :color, :icon)
            """), v)
            seeded_vendors += getattr(result, "rowcount", 0) or 0
        logger.info("[bugfix-3.1] seeded %d builtin vendors (existing kept)",
                    seeded_vendors)

        # ---- seed builtin LLM providers ----
        seeded_providers = 0
        for vendor_id, name, model in _BUILTIN_PROVIDERS:
            # Idempotent: 用 (vendor_id, model) 组合判断是否已存在。复杂的
            # INSERT OR IGNORE 需要 UNIQUE 索引, 嫌重再加; 这里 SELECT 检查。
            row = (await conn.execute(text("""
                SELECT id FROM ai_providers
                WHERE vendor_id=:v AND model=:m AND provider_kind='builtin'
            """), {"v": vendor_id, "m": model})).first()
            if row is not None:
                continue
            await conn.execute(text("""
                INSERT INTO ai_providers
                    (vendor_id, type, name, model, provider_kind,
                     enabled, is_active)
                VALUES (:v, 'llm', :n, :m, 'builtin', 1, 0)
            """), {"v": vendor_id, "n": name, "m": model})
            seeded_providers += 1
        logger.info("[bugfix-3.1] seeded %d builtin LLM providers (existing kept)",
                    seeded_providers)

    logger.info("[bugfix-3.1] migration done")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    asyncio.run(run_migration())
