"""Bugfix-3.1 — AI Providers backend foundation。

3 张表 + builtin seed:
  1. ``ai_vendors``            —— provider 厂商(qwen / openai / anthropic /
                                  deepseek / 用户自定义)。每个 vendor 一组
                                  凭证, 多个 model 共用
  2. ``ai_vendor_credentials`` —— 厂商 API key (fernet 加密)。UNIQUE on
                                  vendor_id, 每 vendor 一组
  3. ``ai_providers``          —— 具体 model 条目, FK 指 vendor。type ∈
                                  {llm, asr, tts}, per-type 至多一个 is_active

Seed 4 个 builtin vendor + 2 个 LLM provider(bugfix-3.2.8 后只 Qwen):
  qwen      → Qwen 3.6 Plus / Max preview
  openai / anthropic / deepseek → vendor 留, provider 由用户在 UI 自填
  (走 AddModelModal + _normalize_model_for_vendor 自动加 LiteLLM 前缀)

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


# 4 个 builtin vendor (拍板)。bugfix-3.2.6: endpoint_env_name 给老用户 .env 兜底。
_BUILTIN_VENDORS = [
    {
        "id": "qwen",
        "name": "Qwen",
        "default_endpoint": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "credential_key_name": "DASHSCOPE_API_KEY",
        "endpoint_env_name": "DASHSCOPE_BASE_URL",
        "color": "#615CED",
        "icon": "Sparkles",
    },
    {
        "id": "openai",
        "name": "OpenAI",
        "default_endpoint": "https://api.openai.com/v1",
        "credential_key_name": "OPENAI_API_KEY",
        "endpoint_env_name": "OPENAI_BASE_URL",
        "color": "#10A37F",
        "icon": "Brain",
    },
    {
        "id": "anthropic",
        "name": "Anthropic",
        "default_endpoint": "https://api.anthropic.com",
        "credential_key_name": "ANTHROPIC_API_KEY",
        "endpoint_env_name": "ANTHROPIC_BASE_URL",
        "color": "#CC785C",
        "icon": "Brain",
    },
    {
        "id": "deepseek",
        "name": "DeepSeek",
        "default_endpoint": "https://api.deepseek.com",
        "credential_key_name": "DEEPSEEK_API_KEY",
        "endpoint_env_name": "DEEPSEEK_BASE_URL",
        "color": "#4D6BFE",
        "icon": "Brain",
    },
]

# Builtin LLM provider seed —— bugfix-3.2.8 拍板:只 Qwen 2 个 (dogfood 用
# .env 的 DASHSCOPE_API_KEY 即开即聊)。OpenAI / Anthropic / DeepSeek seed
# 全部下线 — 用户配凭证后在 UI 里点 [+ 添加 X 模型] 自填 model 名(走
# AddModelModal + _normalize_model_for_vendor 自动加 LiteLLM 前缀)。
#
# bugfix-3.2.7: model 字段必须含 LiteLLM provider 前缀。Qwen 走
# OpenAI-compatible 协议 → openai/。
_BUILTIN_PROVIDERS = [
    # (vendor_id, name, model)
    ("qwen", "Qwen 3.6 Plus",        "openai/qwen3.6-plus"),
    ("qwen", "Qwen 3.6 Max preview", "openai/qwen3.6-max-preview"),
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
        # bugfix-3.2.6: ``endpoint_env_name`` 字段加入 CREATE TABLE 让 fresh
        # 安装就有此列; 旧 DB 由 bugfix_3_2_6_endpoint_env_repair.py 的 ALTER
        # TABLE 追加该列(幂等)。
        if not await _table_exists(conn, "ai_vendors"):
            await conn.execute(text("""
                CREATE TABLE ai_vendors (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    vendor_kind TEXT NOT NULL DEFAULT 'custom'
                        CHECK(vendor_kind IN ('builtin', 'custom')),
                    default_endpoint TEXT,
                    credential_key_name TEXT NOT NULL,
                    endpoint_env_name TEXT,
                    color TEXT,
                    icon TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
            logger.info("[bugfix-3.1] ai_vendors table created (with endpoint_env_name)")
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
                     credential_key_name, endpoint_env_name, color, icon)
                VALUES (:id, :name, 'builtin', :default_endpoint,
                        :credential_key_name, :endpoint_env_name,
                        :color, :icon)
            """), v)
            seeded_vendors += getattr(result, "rowcount", 0) or 0
        logger.info("[bugfix-3.1] seeded %d builtin vendors (existing kept)",
                    seeded_vendors)

        # ---- seed builtin LLM providers ----
        # bugfix-3.2.8: 判重 key 从 (vendor_id, model) 改成 (vendor_id, name, type)
        # 跟 ix_ai_providers_vendor_name_type UNIQUE 一致 — 防 model 字段升级
        # 改写时(如 3.2.7 加 LiteLLM 前缀)旧裸名行匹配不到 → 重复 seed。
        seeded_providers = 0
        for vendor_id, name, model in _BUILTIN_PROVIDERS:
            row = (await conn.execute(text("""
                SELECT id FROM ai_providers
                WHERE vendor_id=:v AND name=:n AND type='llm'
            """), {"v": vendor_id, "n": name})).first()
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

    # ---- bugfix-3.2.5: auto-activate first provider with resolvable credential ----
    # 老用户首次启动新版本时, DB seed 全部 is_active=0, dispatcher 会
    # fallback 到 yaml default_model — 跟"用 UI 切换 provider"的语义不一致。
    # 这里幂等检查: 若已有任一 is_active=1 → 跳过(尊重用户选择); 否则按 seed
    # 顺序找第一个 vendor 凭证可用(DB or .env)的 builtin provider, 自动 activate。
    #
    # 优先级:yaml default_model 匹配的 provider 优先(老用户最熟悉)。匹配靠
    # substring(yaml `openai/qwen3.6-max-preview` vs DB `qwen3.6-max-preview`,
    # 不严格相等以容忍 prefix 差异)。匹配失败回退到 seed 顺序第一个有 cred 的。
    await _auto_activate_if_none(engine)

    logger.info("[bugfix-3.1] migration done")


async def _auto_activate_if_none(engine_obj) -> None:
    """Bugfix-3.2.5: 若 DB 无 LLM is_active → 选第一个凭证可用的 builtin activate。
    幂等: 已有 is_active=1 → 不动; 都无凭证 → 留空(dispatcher fallback yaml)。"""
    from backend.config import get_default_model
    from backend.database import ai_providers as svc

    async with engine_obj.begin() as conn:
        await conn.execute(text("PRAGMA foreign_keys = ON"))
        row = (await conn.execute(text(
            "SELECT id FROM ai_providers WHERE type='llm' AND is_active=1 LIMIT 1"
        ))).first()
        if row is not None:
            logger.info("[bugfix-3.2.5] auto-activate skip — existing active LLM provider")
            return

    yaml_default = get_default_model() or ""
    # 候选: yaml-default substring 命中的先, 其余按 seed 顺序
    providers = await svc.list_providers("llm")
    builtin = [p for p in providers if p.provider_kind == "builtin"]
    matching = [p for p in builtin if p.model and (
        p.model == yaml_default or
        p.model in yaml_default or yaml_default in p.model
    )]
    candidates = matching + [p for p in builtin if p not in matching]

    for p in candidates:
        if not p.vendor_id:
            continue
        cred = await svc.resolve_vendor_credential(p.vendor_id)
        if not cred:
            continue
        result = await svc.activate_provider(p.id)
        if result == "ok":
            # bugfix-3.2.6: activate_provider 已强制 enabled=1, 这里仅 log
            logger.info(
                "[bugfix-3.2.5] auto-activated provider id=%s name=%r model=%s "
                "(matched yaml_default=%r)",
                p.id, p.name, p.model, yaml_default,
            )
            return
        logger.warning(
            "[bugfix-3.2.5] auto-activate candidate id=%s failed: %s",
            p.id, result,
        )

    logger.info(
        "[bugfix-3.2.5] auto-activate skip — no builtin LLM provider with "
        "resolvable credential (DB or .env). Set DASHSCOPE_API_KEY / "
        "OPENAI_API_KEY / etc, or POST /api/ai-vendors/<id>/credentials"
    )


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    asyncio.run(run_migration())
