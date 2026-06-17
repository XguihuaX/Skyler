"""TTS Provider × Model × Voice registry · INV-11 Stage 1.5 followup (2026-05-26)。

Sources(per PM ② design lock + Part B 升级):
  - ``backend/config/tts_models.json``(静态 provider × model 注册表;
    pydantic-validate · 启动 fail-fast if 损坏)
  - ``config.yaml`` ``tts.available_voices.cosyvoice``(7 静态 voice · 含 label/traits/instruct)
  - DB ``characters.voice_model`` 抽 ``cosyvoice-v3.5-plus-bailian-*`` 复刻 voice

API:
  list_providers() -> List[str]
  list_models(provider) -> List[ModelInfo]
  list_voices(provider, model) -> List[VoiceInfo]
  get_provider_tree() -> nested dict 给前端 dropdown 一次性 fetch(GET /tts/providers)

JSON file 是 single source of truth · hardcoded fallback 仅在 file 不存在时启用
(file 存在但 schema 损坏 → 启动 raise · 避免静默 drift)。

加 model 流程见 ``docs/adding-new-tts-model.md``(GSV trained / GSV zeroshot
future placeholder / Fish 三类例子)。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import select

from backend.config import get_available_voices
from backend.database import AsyncSessionLocal
from backend.database.models import Character

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic schema · tts_models.json
# ---------------------------------------------------------------------------

class ModelSpec(BaseModel):
    """Per-model entry · 字段集是 union(cosyvoice / fish / gsv 各取所需)。

    ``extra='allow'`` · provider-specific 字段 (eg fish_latency / gpt_weights)
    不需要在 schema 显式列(JSON 改加字段不需要改 ModelSpec)。registry 把
    整个 dict 给前端 spread 进 voice_model · backend GSVTTS/Fish 自取所需。
    """
    model_config = ConfigDict(extra="allow")
    id: str
    label: str
    tts_language: Optional[str] = None
    # GSV 2 mode(Part C 预留):
    #   - "trained"  → 现 mai_v4 范式 · weights + emotion bank
    #   - "zeroshot" → future · v4 pretrained base + ref upload(占位 · frontend 待实施)
    #   缺省视为 "trained" 兼容旧 schema。
    mode: Optional[str] = None


class ProviderSpec(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    label: str
    models: List[ModelSpec]


class TtsModelsConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    providers: List[ProviderSpec]


# ---------------------------------------------------------------------------
# Load + fallback
# ---------------------------------------------------------------------------

_TTS_MODELS_JSON_PATH = Path(__file__).resolve().parent.parent / "config" / "tts_models.json"
_CLONED_VOICE_PREFIX = "cosyvoice-v3.5-plus-bailian-"


def _hardcoded_fallback() -> TtsModelsConfig:
    """File missing 时的兜底 · 与 Stage 1.5 ship hardcoded 数据一致。

    仅文件不存在时启用 · 文件存在但 schema 损坏 → ``_load_config`` raise
    (避免用户编辑 json 出错后静默 drift 回兜底版本 · 难发现)。
    """
    return TtsModelsConfig(providers=[
        ProviderSpec(
            id="cosyvoice",
            label="CosyVoice(阿里云 DashScope · zh)",
            models=[
                ModelSpec(
                    id="cosyvoice-v3-flash",
                    label="v3-flash(快 · 系统 voice)",
                    tts_language="zh",
                ),
                ModelSpec(
                    id="cosyvoice-v3.5-plus",
                    label="v3.5-plus(系统音 + 复刻双轨)",
                    tts_language="zh",
                ),
            ],
        ),
        ProviderSpec(
            id="fish",
            label="Fish Audio(cloud · zh/ja)",
            models=[
                ModelSpec(
                    id="s2-pro",
                    label="Fish s2-pro(cloud · reference upload)",
                    tts_language="ja",
                    fish_latency="balanced",
                ),
            ],
        ),
        ProviderSpec(
            id="gsv",
            label="GPT-SoVITS(self-hosted · ja)",
            models=[
                # PM SPEC-LOCK 2026-06-11 §B.4-y2:删 server_url 字段(全局 tier
                # 在 ai_providers · 见 backend/tts/gsv_settings.py)。
                ModelSpec(
                    id="mai_v4",
                    label="Mai v4(樱岛麻衣 ja)",
                    mode="trained",
                    tts_language="ja",
                    gpt_weights="GPT_weights_v4/mai_v4-e15.ckpt",
                    sovits_weights="SoVITS_weights_v4/mai_v4_e5_s1380_l32.pth",
                    emotion_bank_dir="tts/gsv/mai_v4",
                    remote_emotion_bank_dir="/workspace/GSVI/mai_emotion_bank/",
                    default_emotion="日常",
                    inference_params={
                        "top_k": 15,
                        "top_p": 1.0,
                        "temperature": 1.0,
                        "speed_factor": 1.0,
                    },
                ),
            ],
        ),
    ])


def _load_config() -> TtsModelsConfig:
    if not _TTS_MODELS_JSON_PATH.exists():
        logger.warning(
            "[tts-registry] %s 不存在 · 使用 hardcoded fallback "
            "(运行 OK · 但加 model 需 code change + redeploy · "
            "建议 cp 模板还原 json 文件)",
            _TTS_MODELS_JSON_PATH,
        )
        return _hardcoded_fallback()
    try:
        with _TTS_MODELS_JSON_PATH.open("r", encoding="utf-8") as f:
            raw = json.load(f)
    except json.JSONDecodeError as exc:
        # JSON 语法损坏 · 启动 fail-fast(per PM Part B "启动 fail-fast if json 损坏")
        raise RuntimeError(
            f"[tts-registry] {_TTS_MODELS_JSON_PATH} JSON 语法损坏:{exc}"
            f"\n→ 修复 JSON 后 backend restart · 或临时 rm 该文件回退 hardcoded fallback。"
        ) from exc
    try:
        cfg = TtsModelsConfig.model_validate(raw)
    except ValidationError as exc:
        raise RuntimeError(
            f"[tts-registry] {_TTS_MODELS_JSON_PATH} schema 不匹配:\n{exc}"
            f"\n→ 见 docs/adding-new-tts-model.md schema 规范。"
        ) from exc
    logger.info(
        "[tts-registry] loaded %s · %d providers, %d models total",
        _TTS_MODELS_JSON_PATH.name,
        len(cfg.providers),
        sum(len(p.models) for p in cfg.providers),
    )
    return cfg


# Module-level load · backend 启动一次 · restart 重新读 json
_CONFIG: TtsModelsConfig = _load_config()


# ---------------------------------------------------------------------------
# Public API (signatures unchanged from Stage 1.5 ship)
# ---------------------------------------------------------------------------

def _find_provider_spec(provider: str) -> Optional[ProviderSpec]:
    for p in _CONFIG.providers:
        if p.id == provider:
            return p
    return None


def list_providers() -> List[str]:
    """支持的 provider id 列表。"""
    return [p.id for p in _CONFIG.providers]


def list_models(provider: str) -> List[Dict[str, Any]]:
    """Return models for provider · 字段透传(含 mode / gsv-specific 字段)。

    PM SPEC-LOCK (2026-06-11):
      provider == 'gsv'  → 走 tts_models_cache(DB tts_models 表 · 用户可加/编辑)
      provider == 'fish' / 'cosyvoice' → 仍走 _CONFIG(backend/config/tts_models.json)

    本切换让 GsvTTSCard add/edit/delete model 立即对前端 (GET /api/tts/providers)
    和后端(gsv.py:_get_model_spec 同源)生效 · 不用改 json + restart。
    """
    if provider == "gsv":
        from backend.tts.tts_models_cache import list_gsv_model_specs  # noqa: PLC0415
        return list(list_gsv_model_specs())
    p = _find_provider_spec(provider)
    if p is None:
        return []
    return [m.model_dump(exclude_none=True) for m in p.models]


async def _load_cloned_voices_from_db() -> List[Dict[str, Any]]:
    """从 characters.voice_model 抽 ``cosyvoice-v3.5-plus-bailian-*`` 复刻 voice。

    bugfix_3_3_1_seed_cloned_voices 已灌 cid=2/3/5 复刻 voice。
    """
    try:
        async with AsyncSessionLocal() as session:
            rows = (await session.execute(
                select(Character.id, Character.name, Character.voice_model)
            )).all()
    except Exception as exc:
        logger.warning("[tts-registry] DB cloned voices lookup failed: %s", exc)
        return []
    cloned: List[Dict[str, Any]] = []
    for cid, name, vm in rows:
        if not vm:
            continue
        try:
            data = json.loads(vm) if isinstance(vm, str) else vm
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(data, dict):
            continue
        v = data.get("voice")
        if isinstance(v, str) and v.startswith(_CLONED_VOICE_PREFIX):
            cloned.append({
                "id": v,
                "label": f"复刻 voice({name})",
                "traits": f"用户复刻 · 当前绑 {name}",
                "instruct": False,
                "cloned": True,
                "bound_character_id": cid,
                "bound_character_name": name,
            })
    return cloned


async def list_voices(provider: str, model: Optional[str] = None) -> List[Dict[str, Any]]:
    """Return voices for (provider, model)。

    cosyvoice + ``cosyvoice-v3-flash`` → 7 系统 voice from config.yaml
    cosyvoice + ``cosyvoice-v3.5-plus`` → 7 系统 + DB 复刻 voice(系统音 + 复刻双轨)
    fish + ``s2-pro``                  → reference upload(per-character)· list 占位 1 voice
    gsv + ``mai_v4``                   → emotion bank 占位 1 voice(LLM emotion 输出后 server 内部路由 16 ref)
    gsv + zeroshot model(future)       → 占位 1 voice(标 requires_reference_upload · frontend 待实施 ref upload UI)
    """
    if provider == "cosyvoice":
        raw = get_available_voices().get("cosyvoice") or []
        system_voices: List[Dict[str, Any]] = []
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            vid = entry.get("id")
            if not vid:
                continue
            system_voices.append({
                "id": vid,
                "label": entry.get("label", vid),
                "traits": entry.get("traits", ""),
                "instruct": bool(entry.get("instruct", False)),
                "cloned": False,
            })
        if model == "cosyvoice-v3.5-plus":
            cloned = await _load_cloned_voices_from_db()
            return system_voices + cloned
        return system_voices

    if provider == "fish":
        return [{
            "id": "reference",
            "label": "reference upload(per-character)",
            "traits": "保存 character 时上传 reference audio + text",
            "instruct": False,
            "cloned": False,
            "requires_reference_upload": True,
        }]

    if provider == "gsv":
        # GSV 2 mode (Part C):
        #   - trained  (默认 / 旧 schema): emotion bank N ref · LLM 输出 emotion 路由
        #   - zeroshot (future placeholder): 单 ref audio + prompt text 上传 (frontend 待实施)
        # PM SPEC-LOCK (2026-06-11):mode 从 tts_models_cache 拿(切到 DB 后)·
        # 跟 list_models("gsv") 同源。
        if model is not None:
            for m_dict in list_models("gsv"):
                if m_dict.get("id") == model:
                    mode = (m_dict.get("mode") or "trained").lower()
                    if mode == "zeroshot":
                        return [{
                            "id": "reference",
                            "label": "zero-shot reference(per-character upload · 待实施)",
                            "traits": "单 ref audio + prompt text · v4 pretrained base · 不需 emotion bank",
                            "instruct": False,
                            "cloned": False,
                            "requires_reference_upload": True,
                            "gsv_mode": "zeroshot",
                        }]
                    break
        # 默认 trained
        return [{
            "id": "emotion_bank",
            "label": "emotion bank(N emotion ref · LLM 输出 emotion 决定)",
            "traits": "per-emotion ref wav 自动路由 · N = lab_dir 实际 .lab 数",
            "instruct": False,
            "cloned": False,
            "uses_emotion_bank": True,
            "gsv_mode": "trained",
        }]

    return []


async def get_provider_tree() -> Dict[str, Any]:
    """Return nested provider × model × voice for 前端 dropdown 一次性 fetch.

    schema:
    {
      "providers": [
        {
          "id": "cosyvoice",
          "label": "CosyVoice(...)",
          "models": [
            {
              "id": "cosyvoice-v3-flash",
              "label": "v3-flash(快 · 系统 voice)",
              "tts_language": "zh",
              "voices": [{id, label, traits, instruct, cloned, ...}]
            },
            ...
          ]
        },
        ...
      ]
    }
    """
    out_providers: List[Dict[str, Any]] = []
    for provider in list_providers():
        models_out: List[Dict[str, Any]] = []
        for model in list_models(provider):
            voices = await list_voices(provider, model["id"])
            models_out.append({**model, "voices": voices})
        p_spec = _find_provider_spec(provider)
        out_providers.append({
            "id": provider,
            "label": p_spec.label if p_spec else provider,
            "models": models_out,
        })
    return {"providers": out_providers}


# build_voice_model_json 删除(PM SPEC-LOCK 2026-06-11 §6):dead helper · 全仓
# 零调用方(grep verified)· A-ii thin reference 后 voice_model 只装 thin 4 字段
# {provider, model, voice?, tts_language?},不再需要 spread spec 副本。
# 前端 VoicePicker.tsx::buildJsonFor gsv 分支直接拼 thin object。
