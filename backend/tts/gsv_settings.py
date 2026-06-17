"""GSV 全局 server_url 解析 · 跟 fish API key resolver 同 pattern。

§ 1 spec 锁定 GSV server_url 三 tier 优先级:
    DB voice_model.server_url (per-character override)
        > ai_providers (type='tts', name='gsv') global
            > _DEFAULT_SERVER_URL (gsv.py 常量)

本模块负责中间一档:全局 ai_providers row 的 endpoint 字段。

为何不走 AsyncSessionLocal:GSVTTS.__init__ 是同步函数(_build_engine 同步链),
不能 await。fish.py::_resolve_fish_api_key 用 os.environ 同步读 → 同 pattern,
本模块用 sqlite3 同步直读。读路径独立于主用 AsyncSessionLocal,但只在启动期 +
setter 时刻读,频次低,不冲突。

Module cache:_global_gsv_server_url 启动期 reload_global_gsv_server_url() 一次性
读;setter 时 set_global_gsv_server_url() 写 DB + 更新 cache + 清掉旧 url 的
LOADED/FAILED key(避免 server_url 变更后旧 weights state 误命中)。

vendor FK 关系:ai_providers.vendor_id NULL 可空(self-hosted 无凭证 vendor),
直接 vendor_id=NULL upsert。应用层 SELECT-then-INSERT/UPDATE,不依赖 UNIQUE
(NULL 在 SQLite UNIQUE 不强制 enforce)。
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Module-level cache · 启动期 reload 后写入 · setter 同步更新
# None 表示"全局未配置 / DB 表不存在"· gsv.py 拿到 None 走 _DEFAULT 兜底
_global_gsv_server_url: Optional[str] = None

# DB file path · backend/tts/gsv_settings.py → parent.parent.parent = repo root
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_DB_PATH = _REPO_ROOT / "momoos.db"


def _connect() -> sqlite3.Connection:
    """同步 sqlite3 连接 · 跟 AsyncSessionLocal 共用同一 DB 文件 · 短连接立即关。"""
    return sqlite3.connect(str(_DB_PATH))


def get_global_gsv_server_url() -> Optional[str]:
    """同步 getter · 返 module cache · None 时调用方走 _DEFAULT 兜底。

    GSVTTS.__init__ 调此函数三 tier 中间一档:
        raw.get("server_url") or get_global_gsv_server_url() or _DEFAULT_SERVER_URL
    """
    return _global_gsv_server_url


def reload_global_gsv_server_url() -> Optional[str]:
    """启动期 + setter 时调 · 同步 sqlite 读 ai_providers row · 更新 module cache。

    Returns:
        最新 server_url(可能 None)· 同时写入 _global_gsv_server_url。

    DB 表不存在(fresh install · ai_providers migration 未跑)→ 返 None · 不 raise。
    """
    global _global_gsv_server_url
    if not _DB_PATH.exists():
        logger.info("[gsv-settings] DB file missing · global server_url=None")
        _global_gsv_server_url = None
        return None
    try:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT endpoint FROM ai_providers "
                "WHERE type='tts' AND name='gsv' AND vendor_id IS NULL LIMIT 1"
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.OperationalError as exc:
        # ai_providers table 不存在 · migration 还没跑(启动 race)
        logger.info(
            "[gsv-settings] ai_providers query failed (%s) · global server_url=None "
            "(migration not yet applied?)", exc,
        )
        _global_gsv_server_url = None
        return None
    if row is None or not row[0] or not str(row[0]).strip():
        _global_gsv_server_url = None
        logger.info("[gsv-settings] no global gsv row · server_url=None")
        return None
    url = str(row[0]).strip()
    _global_gsv_server_url = url
    logger.info("[gsv-settings] global gsv server_url loaded: %s", url)
    return url


def set_global_gsv_server_url(url: Optional[str]) -> None:
    """setter · POST /api/tts/gsv/server_url 调 · 写 DB upsert + 清旧 key + reload cache。

    Args:
        url: 新 server_url · None / 空串视为 "清掉全局配置"(下次 reload 返 None)。

    行为:
      1. 记旧 url(用于清 key)
      2. upsert ai_providers:命中 (type='tts', name='gsv', vendor_id=NULL) 行 → UPDATE endpoint
         未命中 → INSERT(vendor_id=NULL · provider_kind='builtin' · enabled=1 · is_active=1)
      3. reload cache
      4. clear LOADED / FAILED keys 给旧 url(避免 server_url 变更后旧 weights state 误命中
         _MODEL_LOADED_KEYS · 或旧 url 已 FAILED 但新 url 还没机会试)
    """
    old_url = _global_gsv_server_url
    cleaned = url.strip() if isinstance(url, str) else None
    if cleaned == "":
        cleaned = None

    if not _DB_PATH.exists():
        logger.warning(
            "[gsv-settings] DB missing · set_global_gsv_server_url no-op (fresh install?)"
        )
        return

    try:
        conn = _connect()
        try:
            existing = conn.execute(
                "SELECT id FROM ai_providers "
                "WHERE type='tts' AND name='gsv' AND vendor_id IS NULL LIMIT 1"
            ).fetchone()
            if existing is None:
                if cleaned is None:
                    # nothing to do · 全局本来就空 · 用户传 None 清空
                    logger.info("[gsv-settings] no existing row · url=None · skip insert")
                else:
                    conn.execute(
                        "INSERT INTO ai_providers "
                        "(vendor_id, type, name, model, endpoint, "
                        " provider_kind, enabled, is_active) "
                        "VALUES (NULL, 'tts', 'gsv', 'mai_v4', ?, "
                        " 'builtin', 1, 1)",
                        (cleaned,),
                    )
                    logger.info(
                        "[gsv-settings] inserted ai_providers tts/gsv row · endpoint=%s",
                        cleaned,
                    )
            else:
                conn.execute(
                    "UPDATE ai_providers SET endpoint=?, updated_at=CURRENT_TIMESTAMP "
                    "WHERE id=?",
                    (cleaned, existing[0]),
                )
                logger.info(
                    "[gsv-settings] updated ai_providers tts/gsv row id=%s endpoint=%s",
                    existing[0], cleaned,
                )
            conn.commit()
        finally:
            conn.close()
    except sqlite3.OperationalError as exc:
        logger.error(
            "[gsv-settings] upsert failed: %s · cache not updated", exc,
        )
        return

    reload_global_gsv_server_url()

    if old_url and old_url != cleaned:
        _clear_keys_for_url(old_url)


def _clear_keys_for_url(server_url: str) -> None:
    """清掉 gsv.py module 的 _MODEL_LOADED_KEYS + _MODEL_LOAD_FAILED_KEYS 中
    以 server_url 开头的 key。

    跟 routes/tts_api.py::_rearm_gsv_failed_keys 同 pattern · 但本函数同时
    清 LOADED + FAILED 双集合(对称 · server_url 变更后旧 weights state 既不该
    "已 loaded" 也不该 "已 failed"·下次合成自然 retry)。

    late import 避免 gsv_settings ↔ gsv 循环 import(gsv.py 顶部 import
    get_global_gsv_server_url 时,本函数不在 import 期被调用)。
    """
    from backend.tts.gsv import (  # noqa: PLC0415
        _MODEL_LOADED_KEYS, _MODEL_LOAD_FAILED_KEYS,
    )
    norm = server_url.strip().rstrip("/")

    def _match(key: str) -> bool:
        return key.split("|", 1)[0].rstrip("/") == norm

    loaded_drop = {k for k in _MODEL_LOADED_KEYS if _match(k)}
    failed_drop = {k for k in _MODEL_LOAD_FAILED_KEYS if _match(k)}
    if loaded_drop:
        _MODEL_LOADED_KEYS.difference_update(loaded_drop)
    if failed_drop:
        _MODEL_LOAD_FAILED_KEYS.difference_update(failed_drop)
    if loaded_drop or failed_drop:
        logger.info(
            "[gsv-settings] cleared keys for old server_url=%s · loaded=%d failed=%d",
            server_url, len(loaded_drop), len(failed_drop),
        )
