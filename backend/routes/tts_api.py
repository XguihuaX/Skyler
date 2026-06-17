"""TTS REST API.

Mounted at /api in main.py.  Full URL map:
  GET  /api/tts/voices

v3-G' chunk 1 — 让 CharacterPanel 拿到一份"当前可用 TTS provider + 音色"
清单，替代之前 voice_model 字段裸 JSON 文本框。后端从 ``config.yaml``
``tts.available_voices`` 读，加新音色不动代码。

2026-06-06 · 能力页 GSV/Fish 卡补全 · 加 2 个支撑 endpoint:
  POST /api/tts/gsv/ping       — GSV server 连通性探测(轻量 GET / + 3s timeout)
  GET  /api/tts/fish/key_status — Fish API key 是否已配置 + 来源(env / file)
"""
import logging
import os
import time
from pathlib import Path
from typing import List, Optional

import httpx
from fastapi import APIRouter
from pydantic import BaseModel
from typing_extensions import TypedDict

from backend.config import get_available_voices

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Response types — TypedDict + typing_extensions 是为对 pydantic schema 推断
# 友好（参见 services/live2d_scanner.py 同模式注释）。
# ---------------------------------------------------------------------------


class VoiceInfo(TypedDict):
    id: str
    label: str
    # v3-G' patch：emotion 控制现在走 instruct 自然语言指令，不走 SSML
    # （DashScope SSML 没有 emotion 属性）。``ssml`` 字段在 chunk 1a 误用
    # 后撤销；未来若启用 SSML rate/pitch/volume/effect/bgm 等真实属性，
    # 重新加回此字段并落实到 cosyvoice.py 调用路径。
    instruct: Optional[bool]
    traits: str


class TtsProvider(TypedDict):
    id: str
    label: str
    voices: List[VoiceInfo]


class TtsVoicesResponse(TypedDict):
    providers: List[TtsProvider]


# Provider id → 显示 label（前端两级下拉第一级显示用）
_PROVIDER_LABELS: dict[str, str] = {
    "cosyvoice": "CosyVoice",
    "edge": "Edge-TTS",
    "sovits": "GPT-SoVITS",
}


def _coerce_voice(raw: dict) -> VoiceInfo:
    """把 yaml 行规整成 VoiceInfo，缺字段用合理默认。"""
    raw_instruct = raw.get("instruct")
    if raw_instruct is None:
        instruct: Optional[bool] = None
    else:
        instruct = bool(raw_instruct)
    return VoiceInfo(
        id=str(raw.get("id", "")),
        label=str(raw.get("label", raw.get("id", ""))),
        instruct=instruct,
        traits=str(raw.get("traits", "")),
    )


@router.get("/tts/providers")
async def list_tts_providers() -> dict:
    """INV-11 Stage 1.5(2026-05-26)· provider × model × voice nested registry。

    给前端 ``VoicePickerModal`` 3 step dropdown 一次性 fetch:
      provider (cosyvoice/fish/gsv)
        → model (依赖 provider)
          → voice (依赖 model)

    merge sources(per ``backend/tts/registry.py``):
      - config.yaml ``tts.available_voices.cosyvoice``(7 静态)
      - DB ``characters.voice_model`` 抽 ``cosyvoice-v3.5-plus-bailian-*`` 复刻 voice
      - hardcoded gsv mai_v4 / fish s2-pro models

    不替代 ``/tts/voices``(legacy · 单 provider 形态)· 共存。
    """
    from backend.tts.registry import get_provider_tree
    return await get_provider_tree()


@router.get("/tts/voices")
async def list_tts_voices() -> TtsVoicesResponse:
    """Return providers + voices currently available to CharacterPanel.

    Reads ``config.yaml`` ``tts.available_voices`` on every call (no cache)
    so editing the file + ``POST /api/config/reload`` reflects immediately
    without restart. Empty / malformed entries silently dropped.
    """
    raw = get_available_voices()
    providers: List[TtsProvider] = []
    for provider_id, voice_list in raw.items():
        if not isinstance(voice_list, list):
            continue
        voices: List[VoiceInfo] = []
        for entry in voice_list:
            if not isinstance(entry, dict):
                continue
            voice = _coerce_voice(entry)
            if not voice["id"]:
                continue
            voices.append(voice)
        if not voices:
            continue
        providers.append(TtsProvider(
            id=provider_id,
            label=_PROVIDER_LABELS.get(provider_id, provider_id),
            voices=voices,
        ))
    return TtsVoicesResponse(providers=providers)


# ---------------------------------------------------------------------------
# Bugfix-3.3.1 — Cloned (DashScope 控制台复刻) voice 管理 + 试听 + 用量反查
# ---------------------------------------------------------------------------

import asyncio
import base64
import json
import logging
import time as _time
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

from backend.database import engine

logger = logging.getLogger(__name__)


class ClonedVoice(BaseModel):
    voice_id: str
    create_time: Optional[str] = None
    update_time: Optional[str] = None
    status: Optional[str] = None


class ClonedVoicesResponse(BaseModel):
    voices: List[ClonedVoice]
    cached: bool = False  # True 表示走的内存缓存,未打 DashScope


class VoicePreviewBody(BaseModel):
    voice: str = Field(..., min_length=1)
    text: str = Field(default="你好,我是测试音色。", max_length=200)


class VoicePreviewResponse(BaseModel):
    audio_b64: str
    voice: str
    format: str = "wav-24khz-16bit-mono"


class VoiceUsageEntry(BaseModel):
    voice: str
    characters: List[dict]   # [{id, name}]


class VoiceUsageResponse(BaseModel):
    by_voice: List[VoiceUsageEntry]


# 5 分钟缓存复刻 voice 列表 — 避免每次 UI 刷新都打 DashScope HTTP
_CACHE_TTL_SECONDS = 300
_cached_voices: Optional[List[dict]] = None
_cached_at: float = 0.0


def _cache_fresh() -> bool:
    return (
        _cached_voices is not None
        and _time.monotonic() - _cached_at < _CACHE_TTL_SECONDS
    )


def _ensure_dashscope_key() -> None:
    """同步设置 DashScope 全局 api_key。无凭证 → 400 HTTPException。

    Note: SDK 是模块级 global state, 不好接 async DB resolve;走 .env / settings
    路径即可 (复刻 voice 是高级用户场景, DASHSCOPE_API_KEY 通常已配)。
    """
    import dashscope
    import os
    from backend.config import settings
    key = settings.dashscope_api_key or os.environ.get("DASHSCOPE_API_KEY", "")
    if not key:
        raise HTTPException(
            status_code=400,
            detail=(
                "DASHSCOPE_API_KEY 未配置 — 先在 AI Providers / Qwen vendor "
                "下配凭证, 或写 .env 文件"
            ),
        )
    dashscope.api_key = key


def _blocking_list_cloned_voices() -> List[dict]:
    """同步调 VoiceEnrollmentService.list_voices。page_size=100 覆盖正常用户。"""
    from dashscope.audio.tts_v2 import VoiceEnrollmentService
    _ensure_dashscope_key()
    svc = VoiceEnrollmentService()
    raw = svc.list_voices(page_index=0, page_size=100)
    if not isinstance(raw, list):
        logger.warning(
            "[tts.voices.cloned] DashScope returned non-list: %r", type(raw)
        )
        return []
    return raw


def _blocking_preview(voice: str, sample_text: str) -> bytes:
    """同步 CosyVoice 合成,返回 WAV bytes。"""
    from dashscope.audio.tts_v2 import AudioFormat, SpeechSynthesizer
    from backend.config import get_cosyvoice_config
    _ensure_dashscope_key()
    cfg = get_cosyvoice_config()
    model = cfg.get("model", "cosyvoice-v3-flash")
    synth = SpeechSynthesizer(
        model=model, voice=voice,
        format=AudioFormat.WAV_24000HZ_MONO_16BIT,
    )
    audio = synth.call(sample_text)
    if not audio:
        raise RuntimeError(f"voice={voice} 返回空音频 — voice_id 不存在或过期")
    return audio


def _normalize_voice_dict(d: dict) -> dict:
    """SDK 返回字段名 ('id'/'voice_id', 'gmtCreate'/'create_time') 归一化。"""
    if not isinstance(d, dict):
        return {"voice_id": str(d)}
    voice_id = d.get("voice_id") or d.get("id") or ""
    return {
        "voice_id": voice_id,
        "create_time": d.get("create_time") or d.get("gmtCreate"),
        "update_time": d.get("update_time") or d.get("gmtModified"),
        "status": d.get("status"),
    }


@router.get("/tts/voices/cloned", response_model=ClonedVoicesResponse)
async def list_cloned_voices(force: bool = False) -> Any:
    """拉用户在 DashScope 控制台复刻的所有 cosyvoice voice。

    Args:
        force: ``true`` 跳过缓存强拉。UI 的 [刷新] 按钮加 ``?force=1``。
    """
    global _cached_voices, _cached_at
    if not force and _cache_fresh() and _cached_voices is not None:
        return ClonedVoicesResponse(
            voices=[ClonedVoice(**_normalize_voice_dict(v))
                    for v in _cached_voices],
            cached=True,
        )
    try:
        raw = await asyncio.to_thread(_blocking_list_cloned_voices)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("[tts.voices.cloned] DashScope list_voices failed")
        raise HTTPException(
            status_code=502,
            detail=f"DashScope list_voices failed: {exc}",
        ) from exc
    _cached_voices = raw
    _cached_at = _time.monotonic()
    return ClonedVoicesResponse(
        voices=[ClonedVoice(**_normalize_voice_dict(v)) for v in raw],
        cached=False,
    )


@router.post("/tts/voice/preview", response_model=VoicePreviewResponse)
async def preview_voice(body: VoicePreviewBody) -> Any:
    """合成一段 ``body.text`` 试听 (默认 '你好,我是测试音色。')。返回 base64 wav。"""
    # bugfix-4: 标 source='preview' + 显式记 tts_call_log (preview 不走 CosyVoiceTTS
    # 的 synthesize 路径,所以观测不到自动埋点;这里手动 INSERT)
    from backend.observability.tts_log import (
        set_tts_call_context, log_tts_call,
    )
    from backend.config import get_cosyvoice_config
    set_tts_call_context(source="preview")
    _model = get_cosyvoice_config().get("model", "cosyvoice-v3-flash")
    try:
        audio = await asyncio.to_thread(
            _blocking_preview, body.voice, body.text,
        )
        await log_tts_call(
            success=True, voice=body.voice, model=_model,
            input_chars=len(body.text), input_preview=body.text,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("[tts.voice.preview] failed voice=%s", body.voice)
        await log_tts_call(
            success=False, voice=body.voice, model=_model,
            input_chars=len(body.text), input_preview=body.text,
            error_message=str(exc)[:500],
        )
        raise HTTPException(
            status_code=502,
            detail=f"voice preview failed: {exc}",
        ) from exc
    b64 = base64.b64encode(audio).decode("ascii")
    return VoicePreviewResponse(audio_b64=b64, voice=body.voice)


@router.get("/tts/voices/usage", response_model=VoiceUsageResponse)
async def voice_usage() -> Any:
    """反向 ``{voice_id: [character...]}``,前端 voice gallery 显示
    "已用于角色: 八重神子, 神里绫华"。读 characters.voice_model JSON 实时算。"""
    by_voice: dict[str, List[dict]] = {}
    async with engine.begin() as conn:
        rows = (await conn.execute(text(
            "SELECT id, name, voice_model FROM characters "
            "WHERE voice_model IS NOT NULL"
        ))).fetchall()
    for row in rows:
        cid, cname, vm_str = row[0], row[1], row[2]
        if not vm_str:
            continue
        try:
            vm = json.loads(vm_str)
        except json.JSONDecodeError:
            continue
        if not isinstance(vm, dict):
            continue
        voice = vm.get("voice")
        if not isinstance(voice, str) or not voice:
            continue
        by_voice.setdefault(voice, []).append({"id": cid, "name": cname})
    return VoiceUsageResponse(
        by_voice=[VoiceUsageEntry(voice=v, characters=chars)
                  for v, chars in sorted(by_voice.items())],
    )


# ---------------------------------------------------------------------------
# Bugfix-3.4 — voice_aliases (用户给 cloned voice 自定义友好名)
# ---------------------------------------------------------------------------


class VoiceAliasMap(BaseModel):
    # voice_id → display_name. 直接 dict 给前端 O(1) 查。
    aliases: dict[str, str]


class VoiceAliasSetBody(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=64)


@router.get("/tts/voices/aliases", response_model=VoiceAliasMap)
async def list_voice_aliases() -> Any:
    """全量 voice_id → display_name map。前端拉一次后 O(1) 查。"""
    from backend.database import voice_aliases as svc
    aliases = await svc.list_aliases()
    return VoiceAliasMap(aliases=aliases)


@router.put("/tts/voices/aliases/{voice_id}", status_code=204)
async def set_voice_alias(voice_id: str, body: VoiceAliasSetBody) -> None:
    """Upsert alias。空 display_name → 400。"""
    from backend.database import voice_aliases as svc
    name = body.display_name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="display_name 不能为空")
    await svc.set_alias(voice_id, name)


@router.delete("/tts/voices/aliases/{voice_id}", status_code=204)
async def delete_voice_alias(voice_id: str) -> None:
    """删 alias;下次显示走 fallback (character.name + ' voice' 或截断 id)。"""
    from backend.database import voice_aliases as svc
    await svc.delete_alias(voice_id)


# ---------------------------------------------------------------------------
# 2026-06-06 · 能力页 GSV/Fish 卡支撑 endpoint
# ---------------------------------------------------------------------------


class GsvPingRequest(BaseModel):
    server_url: str


class GsvPingResponse(BaseModel):
    ok: bool
    latency_ms: int
    status_code: Optional[int] = None
    error: Optional[str] = None


@router.post("/tts/gsv/ping", response_model=GsvPingResponse)
async def gsv_ping(body: GsvPingRequest) -> GsvPingResponse:
    """GSV server 连通性探测 · 轻量 GET / 探活 + 3s timeout · 不动 server state。

    GPT-SoVITS 官方 API 无显式 health endpoint(`/tts` `/set_gpt_weights`
    `/set_sovits_weights` 等都会动 state)· 这里走 HTTP GET / + 短超时:
      - 任何 2xx/3xx/4xx → ok=True(server 在线 · 404 也算通,说明 server
        进程在响应,只是没 `/` 路由)
      - 5xx / 超时 / 连接错误 / 协议错误 → ok=False
    走后端 proxy 是 CORS 必要(GSV server 通常不开 CORS,前端直 fetch 会 block)。

    2026-06-07 · ok=True 时 re-arm:清掉 `_MODEL_LOAD_FAILED_KEYS` 里以该
    server_url 开头的所有 key,让下次 synthesize 重跑 `_ensure_model_loaded`
    重试 weights set,不用再 restart backend。只在真 ok 时清,失败别清(失败
    时合成会自己重新 mark FAILED,无死循环)。
    """
    url = body.server_url.strip().rstrip("/") + "/"
    started = time.monotonic()
    try:
        # 2026-06-14 · trust_env=False 绕过 shell HTTP(S)_PROXY · 局域网
        # GSV server 调用不依赖 NO_PROXY · 同 gsv.py synthesize/ensure_model_loaded。
        async with httpx.AsyncClient(timeout=3.0, trust_env=False) as client:
            resp = await client.get(url)
        latency_ms = int((time.monotonic() - started) * 1000)
        ok = resp.status_code < 500
        if ok:
            _rearm_gsv_failed_keys(body.server_url)
        return GsvPingResponse(
            ok=ok,
            latency_ms=latency_ms,
            status_code=resp.status_code,
            error=None if ok else f"HTTP {resp.status_code}",
        )
    except httpx.TimeoutException:
        latency_ms = int((time.monotonic() - started) * 1000)
        return GsvPingResponse(
            ok=False, latency_ms=latency_ms,
            error=f"timeout after {latency_ms}ms",
        )
    except Exception as exc:  # 连接 / DNS / 协议错
        latency_ms = int((time.monotonic() - started) * 1000)
        return GsvPingResponse(
            ok=False, latency_ms=latency_ms,
            error=f"{type(exc).__name__}: {exc}"[:200],
        )


def _rearm_gsv_failed_keys(server_url: str) -> None:
    """ping 成功时清掉该 server 对应的 _MODEL_LOAD_FAILED_KEYS 标记。

    GSV key 构造(`backend/tts/gsv.py::_ensure_model_loaded`):
      key = f"{server_url}|{gpt_weights}|{sovits_weights}"
    每个 server 可能有多个 weights 组合(实际场景通常 1 个,但 schema 允许)·
    匹配第一段(split('|',1)[0])规范化后等于本次 ping 的 server_url 的所有
    keys,全清。规范化用 rstrip('/') 容忍 tts_models.json 写带/不带 trailing /。
    """
    from backend.tts.gsv import _MODEL_LOAD_FAILED_KEYS  # type: ignore[attr-defined]
    server_norm = server_url.strip().rstrip("/")
    to_remove = {
        k for k in _MODEL_LOAD_FAILED_KEYS
        if k.split("|", 1)[0].rstrip("/") == server_norm
    }
    if to_remove:
        _MODEL_LOAD_FAILED_KEYS.difference_update(to_remove)
        logger.info(
            "[gsv.ping] re-arm · ok ping for %s · cleared %d FAILED key(s) · "
            "下次 synthesize 将重跑 _ensure_model_loaded 重试 weights set",
            server_url, len(to_remove),
        )


class FishKeyStatusResponse(BaseModel):
    configured: bool
    source: Optional[str] = None  # 'env' / 'file' / None


@router.get("/tts/fish/key_status", response_model=FishKeyStatusResponse)
async def fish_key_status() -> FishKeyStatusResponse:
    """Fish API key 是否已配置 + 来源 · 不返 key 内容(只 bool + source 标签)。

    跟 `backend/tts/fish.py::_resolve_fish_api_key` 同优先级:
      env FISH_API_KEY > <repo_root>/api_key.txt > 未配置
    """
    if os.environ.get("FISH_API_KEY", "").strip():
        return FishKeyStatusResponse(configured=True, source="env")
    repo_root = Path(__file__).resolve().parent.parent.parent
    key_file = repo_root / "api_key.txt"
    if key_file.exists():
        try:
            if key_file.read_text(encoding="utf-8").strip():
                return FishKeyStatusResponse(configured=True, source="file")
        except OSError:
            pass
    return FishKeyStatusResponse(configured=False, source=None)


# ---------------------------------------------------------------------------
# INV (2026-06-11) · GSV 全局 server_url GET/POST(walks ai_providers · 同 gsv_settings)
# ---------------------------------------------------------------------------


class GsvServerUrlResponse(BaseModel):
    server_url: Optional[str] = None
    source: str  # 'global' | 'default' (default 表示 cache 为 None,显示后端 _DEFAULT)


class GsvServerUrlBody(BaseModel):
    server_url: Optional[str] = None  # None / "" → 清掉全局,运行时回 _DEFAULT


@router.get("/tts/gsv/server_url", response_model=GsvServerUrlResponse)
async def get_gsv_server_url() -> GsvServerUrlResponse:
    """返当前生效的全局 server_url(若 ai_providers 无行 → source='default')。

    前端 GsvTTSCard 卡顶 input 用此初始值;clean state 或 N/A 时显示 backend
    _DEFAULT(让用户知道 fallback 走的是公网 IP · 通常需要改成局域网)。
    """
    from backend.tts.gsv_settings import get_global_gsv_server_url  # noqa: PLC0415
    from backend.tts.gsv import _DEFAULT_SERVER_URL  # noqa: PLC0415
    url = get_global_gsv_server_url()
    if url:
        return GsvServerUrlResponse(server_url=url, source="global")
    return GsvServerUrlResponse(server_url=_DEFAULT_SERVER_URL, source="default")


@router.post("/tts/gsv/server_url", response_model=GsvServerUrlResponse)
async def set_gsv_server_url(body: GsvServerUrlBody) -> GsvServerUrlResponse:
    """写全局 server_url · upsert ai_providers(type='tts' name='gsv' vendor_id=NULL)。

    body.server_url:
      - None / "" → 清掉全局 row(下次启动 / get 走 _DEFAULT)
      - 非空 → upsert · 同时清掉旧 url 对应的 _MODEL_LOADED_KEYS /
              _MODEL_LOAD_FAILED_KEYS(避免老 weights state 误命中)

    设值后建议前端调 POST /api/tts/gsv/ping {server_url: <new>} 立即验通。
    """
    from backend.tts.gsv_settings import set_global_gsv_server_url  # noqa: PLC0415
    set_global_gsv_server_url(body.server_url)
    return await get_gsv_server_url()


# ---------------------------------------------------------------------------
# INV (2026-06-11) · GSV emotion coverage 视图(per-model)
# ---------------------------------------------------------------------------


class EmotionCoverageEntry(BaseModel):
    name: str
    has_local_lab: bool
    lab_size: Optional[int] = None
    lab_preview: Optional[str] = None


class EmotionCoverageResponse(BaseModel):
    model_id: str
    lab_dir: Optional[str] = None
    default_emotion: Optional[str] = None
    default_present: bool
    emotions: list[EmotionCoverageEntry]


@router.get(
    "/tts/gsv/models/{model_id}/emotion_coverage",
    response_model=EmotionCoverageResponse,
)
async def gsv_emotion_coverage(model_id: str) -> EmotionCoverageResponse:
    """fs glob lab_dir/*.lab · 报每条 emotion 状态 + default 是否就位。

    跟 GSVTTS._load_lab_cache 同 glob pattern(_lab_cache 的集合派生)·
    fresh fs read(不带实例 cache)· endpoint per-request 触发。

    model_id 未注册 → 404。lab_dir 字段为空(model 创建时未填)→ emotions 返 []
    + default_present=False。
    """
    from backend.tts.tts_models_cache import get_gsv_model_spec  # noqa: PLC0415
    from backend.tts.gsv import list_refs  # noqa: PLC0415
    spec = get_gsv_model_spec(model_id)
    if not spec:
        raise HTTPException(
            status_code=404, detail=f"gsv model {model_id!r} not registered",
        )
    lab_dir = spec.get("emotion_bank_dir")
    default_emotion = spec.get("default_emotion")
    if not lab_dir:
        return EmotionCoverageResponse(
            model_id=model_id, lab_dir=None,
            default_emotion=default_emotion,
            default_present=False, emotions=[],
        )
    refs = list_refs(lab_dir)
    names = {r["name"] for r in refs}
    return EmotionCoverageResponse(
        model_id=model_id,
        lab_dir=lab_dir,
        default_emotion=default_emotion,
        default_present=bool(default_emotion and default_emotion in names),
        emotions=[EmotionCoverageEntry(**r) for r in refs],
    )


# ---------------------------------------------------------------------------
# INV (2026-06-11) · GSV ref list / upload_local(前端本轮不接 UI)
# ---------------------------------------------------------------------------


class RefEntry(BaseModel):
    name: str
    has_local_lab: bool
    lab_size: Optional[int] = None
    lab_preview: Optional[str] = None


class RefListResponse(BaseModel):
    model_id: str
    lab_dir: Optional[str] = None
    refs: list[RefEntry]


class RefUploadBody(BaseModel):
    emotion: str = Field(..., min_length=1, max_length=80)
    prompt_text: str = Field(..., max_length=2000)


@router.get(
    "/tts/gsv/models/{model_id}/refs", response_model=RefListResponse,
)
async def gsv_list_refs(model_id: str) -> RefListResponse:
    from backend.tts.tts_models_cache import get_gsv_model_spec  # noqa: PLC0415
    from backend.tts.gsv import list_refs  # noqa: PLC0415
    spec = get_gsv_model_spec(model_id)
    if not spec:
        raise HTTPException(
            status_code=404, detail=f"gsv model {model_id!r} not registered",
        )
    lab_dir = spec.get("emotion_bank_dir")
    if not lab_dir:
        return RefListResponse(model_id=model_id, lab_dir=None, refs=[])
    return RefListResponse(
        model_id=model_id, lab_dir=lab_dir,
        refs=[RefEntry(**r) for r in list_refs(lab_dir)],
    )


@router.post(
    "/tts/gsv/models/{model_id}/refs/upload_local",
    response_model=RefListResponse, status_code=201,
)
async def gsv_upload_ref_local(
    model_id: str, body: RefUploadBody,
) -> RefListResponse:
    """写 <lab_dir>/<emotion>.lab(UTF-8)· 不写远程 .wav(SSH 范畴)。

    PM SPEC-LOCK §#2:本轮只本地落 .lab · upload_ref_remote 留 stub。
    """
    from backend.tts.tts_models_cache import get_gsv_model_spec  # noqa: PLC0415
    from backend.tts.gsv import list_refs, upload_ref_local  # noqa: PLC0415
    spec = get_gsv_model_spec(model_id)
    if not spec:
        raise HTTPException(
            status_code=404, detail=f"gsv model {model_id!r} not registered",
        )
    lab_dir = spec.get("emotion_bank_dir")
    if not lab_dir:
        raise HTTPException(
            status_code=400,
            detail=f"gsv model {model_id!r} has no lab_dir configured",
        )
    try:
        upload_ref_local(lab_dir, body.emotion, body.prompt_text)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"write failed: {exc}")
    return RefListResponse(
        model_id=model_id, lab_dir=lab_dir,
        refs=[RefEntry(**r) for r in list_refs(lab_dir)],
    )
