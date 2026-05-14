"""Bugfix-3.1 — AI Providers DB service layer。

3 表的 async CRUD helpers。fernet 加密在 credentials 路径上,plaintext 永远
不写库;写入加密,读取解密。``has_credential`` 状态查询不返回密文。

设计:
  * 跟 backend/mcp/credentials.py 同模式:async + ``engine.begin()`` 事务
  * 不缓存 active provider —— 每次查 DB(开销 ~1ms),好换 active 即时生效
  * vendor / provider 删除走 SQLite ``ON DELETE`` cascade / set null;
    services 层主动 ``PRAGMA foreign_keys = ON`` 每条 connection,以防默认
    OFF 让 FK 静默失效
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import text

from backend.config import settings
from backend.database import engine
from backend.utils.crypto import encrypt, try_decrypt

logger = logging.getLogger(__name__)


# bugfix-3.2.6: 已知 env var 别名(litellm 等老 SDK 用过这些名字)。
# vendor.endpoint_env_name 是 primary; 若 primary 未设, 按这里 alias list 顺序尝试。
_ENDPOINT_ENV_ALIASES = {
    "DASHSCOPE_BASE_URL": ["DASHSCOPE_API_BASE"],
}


# bugfix-3.2.8: builtin vendor → LiteLLM provider prefix。AddModelModal 让
# 用户填 raw model 名(eg "gpt-5-turbo-2026-04"),提交时 backend 按 vendor.id
# 自动 prepend。Qwen 走 OpenAI-compatible 协议 → openai/。custom vendor 无前缀
# (用户填啥就啥,因为可能用自己 protocol)。
_VENDOR_LITELLM_PREFIX = {
    "qwen":      "openai/",
    "openai":    "openai/",
    "anthropic": "anthropic/",
    "deepseek":  "deepseek/",
}


def _normalize_model_for_vendor(
    vendor_id: Optional[str], raw_model: str,
) -> str:
    """按 vendor.id 自动 prepend LiteLLM provider 前缀。

    规则:
      - vendor_id 在 ``_VENDOR_LITELLM_PREFIX`` 内 → prepend 前缀
      - raw_model 已含 '/'(用户自己加了前缀) → 原样返回(不二次前缀)
      - custom vendor / vendor_id=None → 原样返回(用户填啥就啥)
    """
    if not raw_model:
        return raw_model
    if "/" in raw_model:
        return raw_model
    if not vendor_id:
        return raw_model
    prefix = _VENDOR_LITELLM_PREFIX.get(vendor_id)
    if not prefix:
        return raw_model
    return prefix + raw_model


def _env_lookup(env_name: str) -> Optional[str]:
    """Settings (.env 文件) → os.environ (shell export) 两层 lookup。

    pydantic_settings 把 .env 加载到 Settings 对象的小写字段 (eg
    ``DASHSCOPE_API_KEY`` → ``settings.dashscope_api_key``), 但**不**注入到
    os.environ。所以两边都查:
      1. ``getattr(settings, name.lower())`` —— pydantic 字段 (有则用)
      2. ``os.environ.get(name)`` —— shell export 兜底
    """
    field = env_name.lower()
    val = getattr(settings, field, None)
    if isinstance(val, str) and val.strip():
        return val
    val = os.environ.get(env_name)
    if val and val.strip():
        return val
    return None


# ---------------------------------------------------------------------------
# Dataclasses (return shapes)
# ---------------------------------------------------------------------------


@dataclass
class Vendor:
    id: str
    name: str
    vendor_kind: str  # 'builtin' | 'custom'
    default_endpoint: Optional[str]
    credential_key_name: str
    endpoint_env_name: Optional[str]   # bugfix-3.2.6
    color: Optional[str]
    icon: Optional[str]
    has_credential: bool               # True iff DB or env has credential
    credential_source: str             # 'db' | 'env' | 'none'  bugfix-3.2.6


@dataclass
class Provider:
    id: int
    vendor_id: Optional[str]
    type: str  # 'llm' | 'asr' | 'tts'
    name: str
    model: str
    endpoint: Optional[str]
    extra_json: Optional[str]
    provider_kind: str
    enabled: bool
    is_active: bool


# ---------------------------------------------------------------------------
# Vendor CRUD
# ---------------------------------------------------------------------------


_VENDOR_COLS = (
    "v.id, v.name, v.vendor_kind, v.default_endpoint, "
    "v.credential_key_name, v.endpoint_env_name, v.color, v.icon, "
    "CASE WHEN c.vendor_id IS NULL THEN 0 ELSE 1 END AS has_db_cred"
)


def _row_to_vendor(r) -> Vendor:
    """bugfix-3.2.6: build Vendor from row; resolve credential_source via env
    lookup when DB column says no DB credential."""
    has_db_cred = bool(r[8])
    credential_key_name = r[4]
    if has_db_cred:
        credential_source = "db"
    else:
        env_val = _env_lookup(credential_key_name) if credential_key_name else None
        credential_source = "env" if env_val else "none"
    return Vendor(
        id=r[0], name=r[1], vendor_kind=r[2],
        default_endpoint=r[3], credential_key_name=credential_key_name,
        endpoint_env_name=r[5],
        color=r[6], icon=r[7],
        has_credential=(credential_source != "none"),
        credential_source=credential_source,
    )


async def list_vendors() -> list[Vendor]:
    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA foreign_keys = ON"))
        rows = (await conn.execute(text(f"""
            SELECT {_VENDOR_COLS}
            FROM ai_vendors v
            LEFT JOIN ai_vendor_credentials c ON c.vendor_id = v.id
            ORDER BY v.vendor_kind, v.id
        """))).fetchall()
    return [_row_to_vendor(r) for r in rows]


async def get_vendor(vendor_id: str) -> Optional[Vendor]:
    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA foreign_keys = ON"))
        row = (await conn.execute(text(f"""
            SELECT {_VENDOR_COLS}
            FROM ai_vendors v
            LEFT JOIN ai_vendor_credentials c ON c.vendor_id = v.id
            WHERE v.id = :id
        """), {"id": vendor_id})).first()
    if row is None:
        return None
    return _row_to_vendor(row)


async def create_vendor(
    *, id: str, name: str, default_endpoint: Optional[str],
    credential_key_name: str, endpoint_env_name: Optional[str] = None,
    color: Optional[str] = None, icon: Optional[str] = None,
) -> Vendor:
    """Create custom vendor (vendor_kind='custom')。pk 冲突时抛 IntegrityError。"""
    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA foreign_keys = ON"))
        await conn.execute(text("""
            INSERT INTO ai_vendors
                (id, name, vendor_kind, default_endpoint,
                 credential_key_name, endpoint_env_name, color, icon)
            VALUES (:id, :name, 'custom', :ep, :cred, :env_ep, :color, :icon)
        """), {
            "id": id, "name": name, "ep": default_endpoint,
            "cred": credential_key_name, "env_ep": endpoint_env_name,
            "color": color, "icon": icon,
        })
    fetched = await get_vendor(id)
    assert fetched is not None
    return fetched


async def patch_vendor(
    vendor_id: str,
    *, name: Optional[str] = None,
    default_endpoint: Optional[str] = None,
    credential_key_name: Optional[str] = None,
    endpoint_env_name: Optional[str] = None,
    color: Optional[str] = None,
    icon: Optional[str] = None,
) -> Optional[Vendor]:
    """更新 vendor 字段。None 字段不动。"""
    fields = []
    params: dict = {"id": vendor_id}
    if name is not None:
        fields.append("name = :name"); params["name"] = name
    if default_endpoint is not None:
        fields.append("default_endpoint = :ep"); params["ep"] = default_endpoint
    if credential_key_name is not None:
        fields.append("credential_key_name = :cred"); params["cred"] = credential_key_name
    if endpoint_env_name is not None:
        fields.append("endpoint_env_name = :env_ep"); params["env_ep"] = endpoint_env_name
    if color is not None:
        fields.append("color = :color"); params["color"] = color
    if icon is not None:
        fields.append("icon = :icon"); params["icon"] = icon
    if not fields:
        return await get_vendor(vendor_id)
    fields.append("updated_at = CURRENT_TIMESTAMP")
    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA foreign_keys = ON"))
        await conn.execute(
            text(f"UPDATE ai_vendors SET {', '.join(fields)} WHERE id = :id"),
            params,
        )
    return await get_vendor(vendor_id)


async def delete_vendor(vendor_id: str) -> str:
    """删除 vendor。返回:
        'ok'             删成功
        'not_found'      不存在
        'builtin'        builtin 不允许删
    凭证级联删除(FK ON DELETE CASCADE); ai_providers.vendor_id SET NULL。
    """
    v = await get_vendor(vendor_id)
    if v is None:
        return "not_found"
    if v.vendor_kind == "builtin":
        return "builtin"
    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA foreign_keys = ON"))
        await conn.execute(
            text("DELETE FROM ai_vendors WHERE id = :id"),
            {"id": vendor_id},
        )
    return "ok"


# ---------------------------------------------------------------------------
# Vendor credentials (fernet-encrypted)
# ---------------------------------------------------------------------------


async def set_vendor_credential(vendor_id: str, key_value: str) -> bool:
    """整 vendor 一次性 upsert。空 value → 改走 delete 路径。
    返回 True 表示更新成功; False 表示 vendor 不存在。"""
    if not await get_vendor(vendor_id):
        return False
    if not key_value or not key_value.strip():
        await clear_vendor_credential(vendor_id)
        return True
    encrypted = encrypt(key_value)
    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA foreign_keys = ON"))
        await conn.execute(text("""
            INSERT INTO ai_vendor_credentials (vendor_id, key_value, updated_at)
            VALUES (:v, :k, CURRENT_TIMESTAMP)
            ON CONFLICT(vendor_id) DO UPDATE SET
                key_value = excluded.key_value,
                updated_at = CURRENT_TIMESTAMP
        """), {"v": vendor_id, "k": encrypted})
    return True


async def clear_vendor_credential(vendor_id: str) -> int:
    """删 vendor 凭证。返回 row count(0 / 1)。"""
    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA foreign_keys = ON"))
        result = await conn.execute(
            text("DELETE FROM ai_vendor_credentials WHERE vendor_id = :v"),
            {"v": vendor_id},
        )
    return getattr(result, "rowcount", 0) or 0


async def get_vendor_credential(vendor_id: str) -> Optional[str]:
    """取解密后的 plaintext。不存在或解密失败 → None。"""
    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA foreign_keys = ON"))
        row = (await conn.execute(text(
            "SELECT key_value FROM ai_vendor_credentials WHERE vendor_id = :v"
        ), {"v": vendor_id})).first()
    if row is None:
        return None
    return try_decrypt(row[0])


async def resolve_vendor_credential(vendor_id: str) -> Optional[str]:
    """凭证解析链: DB → ``.env`` (vendor.credential_key_name 对应) → None。

    LLM dispatcher 用这条链拿到真实的 api_key 传 LiteLLM。
    """
    db_val = await get_vendor_credential(vendor_id)
    if db_val:
        return db_val
    v = await get_vendor(vendor_id)
    if v is None:
        return None
    return _env_lookup(v.credential_key_name)


async def resolve_vendor_endpoint(
    vendor_id: str,
    provider_endpoint_override: Optional[str] = None,
) -> tuple[Optional[str], str]:
    """bugfix-3.2.6: endpoint 解析链 + 来源标识。

    Order (按 Skyler 拍板 + 实用主义):
      1. ``provider.endpoint`` (UI override per provider)       → 'provider'
      2. ``vendor.endpoint_env_name`` → os env / .env           → 'env'
         (含 alias: DASHSCOPE_BASE_URL ↔ DASHSCOPE_API_BASE)
      3. ``vendor.default_endpoint`` (builtin seed default)     → 'vendor'
      4. None                                                    → 'none'

    将 env 置于 vendor.default 之上 —— 老用户 .env 自定义 base_url 必须能
    覆盖 builtin default, 否则 endpoint_env_name 对 builtin vendor 永远死的。
    """
    if provider_endpoint_override:
        return provider_endpoint_override, "provider"
    v = await get_vendor(vendor_id)
    if v is None:
        return None, "none"
    # env (primary + aliases)
    if v.endpoint_env_name:
        env_val = _env_lookup(v.endpoint_env_name)
        if env_val:
            return env_val, "env"
        for alias in _ENDPOINT_ENV_ALIASES.get(v.endpoint_env_name, []):
            env_val = _env_lookup(alias)
            if env_val:
                return env_val, "env"
    # vendor default
    if v.default_endpoint:
        return v.default_endpoint, "vendor"
    return None, "none"


# ---------------------------------------------------------------------------
# Provider CRUD
# ---------------------------------------------------------------------------


def _row_to_provider(r) -> Provider:
    return Provider(
        id=r[0], vendor_id=r[1], type=r[2], name=r[3], model=r[4],
        endpoint=r[5], extra_json=r[6], provider_kind=r[7],
        enabled=bool(r[8]), is_active=bool(r[9]),
    )


_PROVIDER_COLS = (
    "id, vendor_id, type, name, model, endpoint, extra_json, "
    "provider_kind, enabled, is_active"
)


async def list_providers(provider_type: Optional[str] = None) -> list[Provider]:
    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA foreign_keys = ON"))
        if provider_type:
            rows = (await conn.execute(
                text(f"SELECT {_PROVIDER_COLS} FROM ai_providers "
                     f"WHERE type = :t ORDER BY provider_kind, id"),
                {"t": provider_type},
            )).fetchall()
        else:
            rows = (await conn.execute(text(
                f"SELECT {_PROVIDER_COLS} FROM ai_providers "
                f"ORDER BY type, provider_kind, id"
            ))).fetchall()
    return [_row_to_provider(r) for r in rows]


async def get_provider(provider_id: int) -> Optional[Provider]:
    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA foreign_keys = ON"))
        row = (await conn.execute(
            text(f"SELECT {_PROVIDER_COLS} FROM ai_providers WHERE id = :id"),
            {"id": provider_id},
        )).first()
    return _row_to_provider(row) if row else None


async def get_active_provider(provider_type: str) -> Optional[Provider]:
    """Per-type 至多一个 is_active=1。"""
    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA foreign_keys = ON"))
        row = (await conn.execute(text(
            f"SELECT {_PROVIDER_COLS} FROM ai_providers "
            f"WHERE type = :t AND is_active = 1 LIMIT 1"
        ), {"t": provider_type})).first()
    return _row_to_provider(row) if row else None


async def create_provider(
    *, vendor_id: Optional[str], type: str, name: str, model: str,
    endpoint: Optional[str] = None, extra_json: Optional[str] = None,
) -> Provider:
    # bugfix-3.2.8: backend 主动 normalize model 名加 LiteLLM provider 前缀。
    # 让前端 AddModelModal 收 raw 名(eg "gpt-4o" / "claude-opus-5"), 后端按
    # vendor.id 自动 prepend。已含 '/' 或 custom vendor → 原样。
    normalized_model = _normalize_model_for_vendor(vendor_id, model)
    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA foreign_keys = ON"))
        result = await conn.execute(text("""
            INSERT INTO ai_providers
                (vendor_id, type, name, model, endpoint, extra_json,
                 provider_kind, enabled, is_active)
            VALUES (:v, :t, :n, :m, :e, :x, 'custom', 1, 0)
        """), {
            "v": vendor_id, "t": type, "n": name, "m": normalized_model,
            "e": endpoint, "x": extra_json,
        })
        new_id = result.lastrowid  # type: ignore[attr-defined]
    p = await get_provider(int(new_id))
    assert p is not None
    return p


async def patch_provider(
    provider_id: int,
    *, name: Optional[str] = None,
    model: Optional[str] = None,
    endpoint: Optional[str] = None,
    extra_json: Optional[str] = None,
    enabled: Optional[bool] = None,
) -> Optional[Provider]:
    fields = []
    params: dict = {"id": provider_id}
    if name is not None:
        fields.append("name = :name"); params["name"] = name
    if model is not None:
        fields.append("model = :model"); params["model"] = model
    if endpoint is not None:
        fields.append("endpoint = :ep"); params["ep"] = endpoint
    if extra_json is not None:
        fields.append("extra_json = :ex"); params["ex"] = extra_json
    if enabled is not None:
        fields.append("enabled = :en"); params["en"] = 1 if enabled else 0
    if not fields:
        return await get_provider(provider_id)
    fields.append("updated_at = CURRENT_TIMESTAMP")
    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA foreign_keys = ON"))
        await conn.execute(
            text(f"UPDATE ai_providers SET {', '.join(fields)} "
                 f"WHERE id = :id"),
            params,
        )
    return await get_provider(provider_id)


async def delete_provider(provider_id: int) -> str:
    """删 provider。返回 'ok' / 'not_found'。

    bugfix-3.2.8: builtin 也允许删 (老逻辑禁止 → return 'builtin' 已下线)。
    用户拍板:builtin 极少 (Qwen 2 行),误删了重新 add 回来即可,UI 概念
    比"禁止删 builtin"更清爽。前端 [-] 按钮对 builtin/custom 都显示。
    """
    p = await get_provider(provider_id)
    if p is None:
        return "not_found"
    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA foreign_keys = ON"))
        await conn.execute(
            text("DELETE FROM ai_providers WHERE id = :id"),
            {"id": provider_id},
        )
    return "ok"


async def activate_provider(provider_id: int) -> str:
    """切 provider 为 active。返回:
        'ok'                    成功(同 type 其他 provider deactivate)
        'not_found'             provider 不存在
        'no_credential'         vendor 凭证 (DB or env) 都没有

    bugfix-3.2.6:
      - 移除 'not_enabled' 返回 —— activate 时强制 enabled=1, 避免 UI 操作
        留下 active=1+enabled=0 自相矛盾的 DB state(dispatcher 视为 no_db_active)
      - vendor 凭证检查走 has_credential(DB OR env), env 也算
    """
    p = await get_provider(provider_id)
    if p is None:
        return "not_found"
    # vendor 必须有可用凭证(DB or env)
    if p.vendor_id:
        cred = await resolve_vendor_credential(p.vendor_id)
        if not cred:
            return "no_credential"
    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA foreign_keys = ON"))
        # 同 type 全部 deactivate
        await conn.execute(text(
            "UPDATE ai_providers SET is_active = 0, "
            "updated_at = CURRENT_TIMESTAMP "
            "WHERE type = :t AND id != :id"
        ), {"t": p.type, "id": provider_id})
        # 当前 activate + 强制 enabled=1(bugfix-3.2.6 一致性 invariant)
        await conn.execute(text(
            "UPDATE ai_providers SET is_active = 1, enabled = 1, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = :id"
        ), {"id": provider_id})
    return "ok"
