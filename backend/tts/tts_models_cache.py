"""GSV model 元数据 cache · 跟 backend/tts/gsv_settings.py 同 pattern。

启动期 sync sqlite 直读 tts_models 表 · 进程内 module cache · CRUD setter 调
reload。让 GSVTTS sync __init__ 能 sync 拿 model spec(否则 await DB 要把整
_build_engine 链 async 化 · blast 大)。

PM SPEC-LOCK §3:cache 整体加载失败时 fallback 到 backend/config/tts_models.json
的 gsv 段(仅整体失败触发 · 不补个别缺失 model)· 触发时 logger.warning
"cache 加载失败,回落 tts_models.json,配置可能过期"。

PM SPEC-LOCK §5:gsv.py::_get_model_spec 不调 registry.list_models("gsv"),
改调本模块 get_gsv_model_spec(model_id)。

模块 cache 结构:
    _GSV_MODELS_CACHE: Dict[model_id, model_spec_dict]
    model_spec_dict 字段(对外):
        id, label, mode, tts_language,
        gpt_weights, sovits_weights,
        emotion_bank_dir,            ← DB 列名 lab_dir → 对外暴露 emotion_bank_dir 兼容 gsv.py 现状
        remote_emotion_bank_dir,     ← DB 列名 wav_remote_dir → 对外 remote_emotion_bank_dir
        default_emotion,
        inference_params(dict · 已 json.loads)

字段名映射理由:gsv.py:__init__ 现读 `spec.get('emotion_bank_dir')` /
`spec.get('remote_emotion_bank_dir')`(阶段 ① 落) · 跟 tts_models.json 历史
字段名一致 · 不改 gsv.py · 在本 cache 里把 DB 列名 lab_dir/wav_remote_dir 映射
到对外名。前端 / CRUD endpoint 用 DB 列名 lab_dir/wav_remote_dir(更直白)。
"""
from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Module cache · 启动期 reload 后写入 · setter 同步更新
# key = model_id (e.g. "mai_v4") · value = spec dict(字段对外名 · 不含 DB 控制位)
_GSV_MODELS_CACHE: Dict[str, Dict[str, Any]] = {}
# True iff 最近一次 reload 走的是 tts_models.json fallback(用于 self-check)
_FELL_BACK_TO_JSON: bool = False

# DB file path · backend/tts/tts_models_cache.py → parent.parent.parent = repo root
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_DB_PATH = _REPO_ROOT / "momoos.db"


def _connect() -> sqlite3.Connection:
    return sqlite3.connect(str(_DB_PATH))


def _parse_inference_params(raw: Optional[str]) -> Dict[str, Any]:
    """DB inference_params TEXT 解析为 dict · 失败返 {}。"""
    if not raw:
        return {}
    try:
        v = json.loads(raw)
        return v if isinstance(v, dict) else {}
    except (json.JSONDecodeError, TypeError):
        logger.warning(
            "[tts_models_cache] inference_params parse failed: %r · using {}", raw,
        )
        return {}


def _row_to_spec(row: tuple) -> Dict[str, Any]:
    """tts_models 行 → 对外 spec dict(字段名跟 tts_models.json 对齐)。

    Row column order:
        model_id, label, mode, tts_language,
        gpt_weights, sovits_weights, lab_dir, wav_remote_dir,
        default_emotion, inference_params
    """
    (model_id, label, mode, tts_language, gpt_weights, sovits_weights,
     lab_dir, wav_remote_dir, default_emotion, inference_params) = row
    spec: Dict[str, Any] = {
        "id": model_id,
        "label": label,
    }
    if mode:
        spec["mode"] = mode
    if tts_language:
        spec["tts_language"] = tts_language
    if gpt_weights:
        spec["gpt_weights"] = gpt_weights
    if sovits_weights:
        spec["sovits_weights"] = sovits_weights
    # DB 列名 → 对外名(对齐 tts_models.json + gsv.py:__init__ 读取键)
    if lab_dir:
        spec["emotion_bank_dir"] = lab_dir
    if wav_remote_dir:
        spec["remote_emotion_bank_dir"] = wav_remote_dir
    if default_emotion:
        spec["default_emotion"] = default_emotion
    ip = _parse_inference_params(inference_params)
    if ip:
        spec["inference_params"] = ip
    return spec


def _load_from_db() -> Dict[str, Dict[str, Any]]:
    """同步读 tts_models 表 · 仅 provider='gsv' AND enabled=1 行。

    raise sqlite3.OperationalError 让 reload_gsv_models_cache 走 fallback。
    """
    if not _DB_PATH.exists():
        raise sqlite3.OperationalError(f"DB file missing: {_DB_PATH}")
    conn = _connect()
    try:
        rows = conn.execute("""
            SELECT model_id, label, mode, tts_language,
                   gpt_weights, sovits_weights, lab_dir, wav_remote_dir,
                   default_emotion, inference_params
            FROM tts_models
            WHERE provider='gsv' AND enabled=1
            ORDER BY id
        """).fetchall()
    finally:
        conn.close()
    out: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        spec = _row_to_spec(r)
        out[spec["id"]] = spec
    return out


def _load_from_json_fallback() -> Dict[str, Dict[str, Any]]:
    """tts_models.json gsv 段 fallback · 仅 cache 整体失败时触发。

    per PM SPEC-LOCK §3:不补个别缺失 model · 仅整体回落。本函数若也失败 → 返
    {} · 让 GSVTTS 回 _DEFAULT 常量兜底(server 端拿不到 ref 时退到本地 stub wav)。
    """
    json_path = _REPO_ROOT / "backend" / "config" / "tts_models.json"
    if not json_path.exists():
        logger.warning(
            "[tts_models_cache] fallback failed · tts_models.json missing: %s",
            json_path,
        )
        return {}
    try:
        with json_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning(
            "[tts_models_cache] fallback failed · tts_models.json load: %s", exc,
        )
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    for prov in data.get("providers", []):
        if prov.get("id") != "gsv":
            continue
        for m in prov.get("models", []) or []:
            mid = m.get("id")
            if not isinstance(mid, str):
                continue
            spec = {k: v for k, v in m.items() if k not in ("id", "label")}
            spec["id"] = mid
            spec["label"] = m.get("label", mid)
            out[mid] = spec
    return out


def get_gsv_model_spec(model_id: Optional[str]) -> Dict[str, Any]:
    """sync getter · gsv.py:_get_model_spec 调本函数。

    PM SPEC-LOCK §5 渐进:gsv.py:_get_model_spec 接口不变 · 内部数据源切到本
    模块 · 三 tier(DB voice_model > model spec > _DEFAULT)pattern 不动。

    返 {} 表示 model_id 未注册 · gsv.py 用 _DEFAULT 兜底 + warn(若 model 字段
    本身在 voice_model 里有但 cache 拿不到 spec)。
    """
    if not model_id:
        return {}
    return _GSV_MODELS_CACHE.get(model_id, {})


def list_gsv_model_specs() -> List[Dict[str, Any]]:
    """全部启用的 gsv model spec(供 registry.list_models("gsv") + get_provider_tree 用)。"""
    return list(_GSV_MODELS_CACHE.values())


def is_model_registered(model_id: Optional[str]) -> bool:
    """gsv.py:__init__ 用:model 字段在 voice_model 里有,cache 是否含此 id?

    返 False 时 gsv.py warn:已选 model 但 cache 没注册 · 多半是用户选了一个
    后来 DELETE 掉的 builtin · voice_model 副本还指向它。
    """
    if not model_id:
        return False
    return model_id in _GSV_MODELS_CACHE


def reload_gsv_models_cache() -> int:
    """启动期 + 每次 CRUD setter 后调 · 写入 module cache。

    Returns:
        最新 cache 中的 gsv model 数。

    流程:
      1. 尝试 DB SELECT · 成功 → 写 cache · 返计数
      2. DB OperationalError(表不存在 · 数据库锁等)→ tts_models.json fallback
         + WARNING("cache 加载失败,回落 tts_models.json,配置可能过期")
      3. fallback 也失败 → cache 留 {} · 让 _DEFAULT 兜底
    """
    global _GSV_MODELS_CACHE, _FELL_BACK_TO_JSON
    try:
        loaded = _load_from_db()
        _GSV_MODELS_CACHE = loaded
        _FELL_BACK_TO_JSON = False
        logger.info(
            "[tts_models_cache] DB load · %d gsv model(s) cached: %s",
            len(loaded), list(loaded.keys()),
        )
        return len(loaded)
    except sqlite3.OperationalError as exc:
        logger.warning(
            "[tts_models_cache] cache 加载失败,回落 tts_models.json,"
            "配置可能过期 (DB error: %s)",
            exc,
        )
        loaded = _load_from_json_fallback()
        _GSV_MODELS_CACHE = loaded
        _FELL_BACK_TO_JSON = True
        logger.info(
            "[tts_models_cache] JSON fallback · %d gsv model(s) cached: %s",
            len(loaded), list(loaded.keys()),
        )
        return len(loaded)


def fell_back_to_json() -> bool:
    """self-check · True 时最近一次 reload 走的 JSON fallback,UI/log 可以提示。"""
    return _FELL_BACK_TO_JSON
