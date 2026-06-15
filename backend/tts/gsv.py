"""GSV (GPT-SoVITS) TTS · INV-11 Stage 1 真接入实施(2026-05-25)。

per PM SKYLER_TTS_MODEL_SWITCHING.md spec(repo 外 doc · PM 已 verify 5 项):
  1. api_v2.py 启动 Uvicorn 9880 · nohup 持久
  2. /set_gpt_weights + /set_sovits_weights 切 mai_v4 → "success"
  3. /tts 合成 RIFF WAV 67KB(CPU 模式 ~50s)
  4. 16 个 .wav + .lab 配对(平静 → 日常 改名已 SSH)
  5. 公网 9880 TCP connected

实施架构:
  - httpx.AsyncClient GET /tts · timeout 90s(给 CPU 模式 50s 留 buffer)
  - lazy `_ensure_model_loaded` · module-level lock + once-per-(weights,server)
  - _load_lab_cache 启动时读 tts/gsv/mai_v4/*.lab in-memory
  - _resolve_ref_wav 复用 V2''(emotion → wav · 16 集合命中 / 否则 "日常" fallback)
  - 错误 fallback 链:timeout / 5xx / non-RIFF / lab missing → mai5min_0033.wav stub bytes
  - log_tts_call INSERT(success / error_message)· emotion 字段 schema 待 v4.2

⚠ 多用户 race(per PM §2.2):set_*_weights 是 GSV server 全局状态 · 多用户共享会互相
覆盖。Stage 1 单用户 cid=1 不阻塞;多角色多 gsv model 切换留 v4.1 加切换队列锁。
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

from backend.tts.base import TTSBase
from backend.tts.gsv_settings import get_global_gsv_server_url

logger = logging.getLogger(__name__)

_EMOTION_PREFIX_RE = re.compile(r"^\s*<emotion>(.+?)</emotion>", re.IGNORECASE)

# stub fallback wav · GSV server unreachable / 5xx / non-RIFF 时返这个
# (~5min Mai 参考音频 · 1.2MB · V2'' 一直在用)
_FALLBACK_STUB_WAV = (
    Path(__file__).resolve().parent.parent.parent
    / "tts" / "fish" / "参考音频" / "mai" / "mai5min_0033.wav"
)

# 2026-06-11 · 删 V2'' _GSV_MAI_V4_EMOTIONS frozenset · emotion 集合从
# self._lab_cache.keys() 派生(每 model 自然成立 · 无 hardcoded)。default
# 走 model spec 的 default_emotion 字段 / fallback 常量 _DEFAULT_FALLBACK_EMOTION。
_DEFAULT_FALLBACK_EMOTION = "日常"

# 默认值(per PM §2.3 SQL schema · voice_model 若缺字段则用此 default)
_DEFAULT_SERVER_URL = "http://106.75.224.167:9880"
_DEFAULT_GPT_WEIGHTS = "GPT_weights_v4/mai_v4-e15.ckpt"
_DEFAULT_SOVITS_WEIGHTS = "SoVITS_weights_v4/mai_v4_e5_s1380_l32.pth"
_DEFAULT_REMOTE_BANK = "/workspace/GSVI/mai_emotion_bank/"
_DEFAULT_LOCAL_BANK = "tts/gsv/mai_v4"
_DEFAULT_INFERENCE_PARAMS: Dict[str, Any] = {
    "top_k": 15, "top_p": 1.0, "temperature": 1.0, "speed_factor": 1.0,
}


def _get_model_spec(model_id: Optional[str]) -> Dict[str, Any]:
    """拿 provider='gsv' + model_id 对应的 spec dict · 跟 tts_models_cache 同步。

    PM SPEC-LOCK §5 渐进:阶段 ① 用 registry.list_models("gsv") 读 tts_models.json,
    现切到 tts_models_cache.get_gsv_model_spec() · 后者 sync 读 DB tts_models 表 ·
    cache 整体加载失败时回落 tts_models.json(per LOCK §3 仅整体 fallback,不补
    个别)。三 tier helper 与外部接口签名不变。

    返空 dict 时 6 字段全走 _DEFAULT 常量兜底。fail-safe:cache 异常 / model id
    缺失 / spec 缺字段都不 raise · 让 _DEFAULT 兜住。

    model 字段已存在 voice_model 但 cache 没注册 → __init__ 内 warn(model 被
    DELETE 后 character 仍指向它的典型场景)· 本函数仅返 {} 不打 warn。
    """
    if not model_id:
        return {}
    try:
        from backend.tts.tts_models_cache import get_gsv_model_spec  # noqa: PLC0415
        return get_gsv_model_spec(model_id)
    except Exception as exc:
        logger.warning(
            "[gsv] _get_model_spec(%r) failed: %s · falling back to _DEFAULT",
            model_id, exc,
        )
    return {}
_TTS_TIMEOUT_S = 30.0       # INV-11 Stage 1 (2026-05-25 PM lock): 90s → 30s · GPU 模式 ~5s 6x buffer 充足 · CPU 模式 50s 会 timeout → 直接 fallback stub(比 user 静默等 90s 强 · early signal 更可接受)
_WEIGHTS_TIMEOUT_S = 30.0   # set_*_weights 轻量切换

# Module-level 模型加载状态 · 避免每 turn 都 set_*_weights(GSV server 全局状态)
_MODEL_LOAD_LOCK = asyncio.Lock()
_MODEL_LOADED_KEYS: set[str] = set()
# INV-11 Stage 1 hotfix (2026-05-25 21:xx PM lock):
# _ensure_model_loaded 失败时 mark key · synthesize 检测后直接 fallback stub,
# **不调 /tts**(避免拿空 weights state 进 /tts → server 进 inconsistent state →
# 后续 502 全 corrupt)。backend restart 后 module state 清空 · 自然 retry。
_MODEL_LOAD_FAILED_KEYS: set[str] = set()


def _resolve_weights_field(
    raw: Dict[str, Any], primary_key: str, legacy_key: str, default: str,
) -> str:
    """读 voice_model JSON 的 weights 字段 · backward compat + placeholder skip。

    优先级:primary(Stage 1 新名)→ legacy(V2'' 旧名)→ default。
    跳过 "placeholder" 字面值(V2'' 默认值 · 不是真路径)。
    """
    v = raw.get(primary_key) or raw.get(legacy_key)
    if not v or not isinstance(v, str) or v.strip() in ("", "placeholder"):
        return default
    return v.strip()


def _load_fallback_stub_bytes() -> Optional[bytes]:
    """读 fallback stub wav bytes · 启动期 lazy load,失败返 None。"""
    if not _FALLBACK_STUB_WAV.exists():
        logger.warning("[gsv] fallback stub wav missing: %s", _FALLBACK_STUB_WAV)
        return None
    try:
        return _FALLBACK_STUB_WAV.read_bytes()
    except OSError as exc:
        logger.warning("[gsv] fallback stub wav read failed: %s", exc)
        return None


class GSVTTS(TTSBase):
    """GSV (GPT-SoVITS) HTTP provider · 真调 9880/tts(2026-05-25 Stage 1 ship)。

    voice_model JSON 字段(per PM §2.3 schema):
      - server_url               GSV server (http://106.75.224.167:9880)
      - gpt_weights              GPT 权重 server 端路径
      - sovits_weights           SoVITS 权重 server 端路径
      - emotion_bank_dir         本地 .lab 缓存目录(Skyler 端)
      - remote_emotion_bank_dir  server 端 wav 目录(传 ref_audio_path 给 /tts)
      - default_emotion          fallback emotion(默 "日常")
      - inference_params         {top_k, top_p, temperature, speed_factor}
      - tts_language             ja / zh / en
    """

    def __init__(
        self, voice_config, voice_model_json: Optional[str] = None,
    ) -> None:
        self._cfg = voice_config
        # parse raw voice_model JSON 拿 gsv 专用字段
        # (per PM §2.3 lock · 不污染 VoiceConfig dataclass schema)
        raw: Dict[str, Any] = {}
        if voice_model_json and voice_model_json.strip():
            try:
                _parsed = json.loads(voice_model_json)
                if isinstance(_parsed, dict):
                    raw = _parsed
            except (json.JSONDecodeError, TypeError) as exc:
                logger.warning(
                    "[gsv] voice_model_json parse failed: %s · fallback defaults",
                    exc,
                )
        # A-ii thin reference + § 1 spec(2026-06-11):三 tier 优先级
        #   server_url:  DB > global ai_providers > _DEFAULT
        #   其它 6 字段: DB > registry model spec > _DEFAULT(model 字段缺失才回 _DEFAULT)
        # spread 副本(DB 已存的 cid=1 等历史快照)仍优先于 model 级,保留 per-char
        # override 语义;阶段 ② migration json_remove 之后副本消失 → 全走 model 级。
        model_id = raw.get("model") if isinstance(raw.get("model"), str) else None
        spec = _get_model_spec(model_id)
        # PM SPEC-LOCK:model 字段在 voice_model 已选但 cache 没注册 → warn
        # (典型场景:用户选了 model_X · 后来 PM 把 model_X DELETE 了 ·
        #  character.voice_model 副本仍指向 model_X · 此时 spec 是 {} ·
        #  __init__ 全 6 字段会兜 _DEFAULT 常量 = mai_v4 隐藏耦合)
        if model_id and not spec:
            try:
                from backend.tts.tts_models_cache import is_model_registered  # noqa: PLC0415
                if not is_model_registered(model_id):
                    logger.warning(
                        "[gsv] voice_model.model=%r 未在 tts_models cache 注册 · "
                        "6 字段全走 _DEFAULT(可能是 model 被 DELETE 后 character "
                        "副本未更新)· character_id=%s",
                        model_id, getattr(self._cfg, "character_id", "<unknown>"),
                    )
            except Exception:  # noqa: BLE001
                pass

        self.server_url: str = (
            raw.get("server_url")
            or get_global_gsv_server_url()
            or _DEFAULT_SERVER_URL
        )
        # hotfix (2026-05-25):向后兼容 V2'' 旧字段名(gpt_path/sovits_path · 值为
        # "placeholder")· 跳过 placeholder fallback default(真路径)。model spec 同名字段
        # 当作 fallback default 传入 · DB 命中 placeholder 时跳到 spec / 再到常量。
        self.gpt_weights: str = _resolve_weights_field(
            raw, "gpt_weights", "gpt_path",
            spec.get("gpt_weights") or _DEFAULT_GPT_WEIGHTS,
        )
        self.sovits_weights: str = _resolve_weights_field(
            raw, "sovits_weights", "sovits_path",
            spec.get("sovits_weights") or _DEFAULT_SOVITS_WEIGHTS,
        )
        self.remote_emotion_bank: str = (
            raw.get("remote_emotion_bank_dir")
            or spec.get("remote_emotion_bank_dir")
            or _DEFAULT_REMOTE_BANK
        )
        self.local_emotion_bank: str = (
            raw.get("emotion_bank_dir")
            or spec.get("emotion_bank_dir")
            or _DEFAULT_LOCAL_BANK
        )
        self.default_emotion: str = (
            raw.get("default_emotion")
            or spec.get("default_emotion")
            or _DEFAULT_FALLBACK_EMOTION
        )
        # ensure remote_emotion_bank trailing slash · 避免 path join 错
        if not self.remote_emotion_bank.endswith("/"):
            self.remote_emotion_bank += "/"
        # inference_params 合并三 tier(_DEFAULT < spec < raw)
        self.inference_params: Dict[str, Any] = dict(_DEFAULT_INFERENCE_PARAMS)
        _spec_ip = spec.get("inference_params") or {}
        if isinstance(_spec_ip, dict):
            self.inference_params.update(_spec_ip)
        _ip = raw.get("inference_params") or {}
        if isinstance(_ip, dict):
            self.inference_params.update(_ip)
        # tts_language from cfg(由 voice_config.resolve_tts_language 解析 ·
        # 2026-06-15 SPEC 收口)。cfg.tts_language dataclass field 默认 "zh" ·
        # 永远是 truthy str · 原 `or "ja"` dead fallback 删掉(误导且永不触发)。
        self.tts_language: str = getattr(self._cfg, "tts_language", None) or "zh"

        # 启动时 lazy 读 <local_emotion_bank>/*.lab 进 in-memory cache
        # 集合 = cache.keys() · 见 _resolve_ref_wav · per-model 自然成立
        self._lab_cache: Dict[str, str] = self._load_lab_cache()
        # § 4 spec:启动校验 default_emotion 是否在 cache,不在则 warn(否则
        # fallback 自己又缺 ref → server 拿不到 ref_audio_path → stub)
        if self.default_emotion not in self._lab_cache:
            logger.warning(
                "[gsv] default_emotion=%r NOT in lab_cache (%d entries) · "
                "fallback 自身缺 ref,server 端 ref_audio_path 也可能缺 wav · "
                "用户 LLM 输出未命中集合的 emotion 时会 stub-mode 兜底",
                self.default_emotion, len(self._lab_cache),
            )
        # fallback stub bytes(reused per V2'' · GSV unreachable 时返这个)
        self._fallback_stub_bytes: Optional[bytes] = _load_fallback_stub_bytes()

        # PM SPEC-LOCK:init log 打全 6 resolved 字段(weights / lab_dir /
        # remote_bank / default_emotion / inference_params)+ server_url + lang
        # · 真机调试时一行看清当前 tier 解析结果(DB vs spec vs _DEFAULT)
        logger.info(
            "[gsv] init model=%s server=%s gpt=%s sovits=%s lab_dir=%s "
            "lab_cache=%d remote_bank=%s default_emotion=%s ip=%s lang=%s · "
            "fallback_stub=%s",
            model_id, self.server_url, self.gpt_weights, self.sovits_weights,
            self.local_emotion_bank, len(self._lab_cache), self.remote_emotion_bank,
            self.default_emotion, self.inference_params, self.tts_language,
            "loaded" if self._fallback_stub_bytes else "MISSING",
        )

    def _load_lab_cache(self) -> Dict[str, str]:
        """启动时一次性读本地 emotion_bank_dir/*.lab 文件。

        每个 .lab 文件:UTF-8 文本 · 1 行 ja prompt text(per PM §0.4 verify
        日常.lab 99 bytes 含 ja prompt)。缺失 / IO 错 → log warn · 该 emotion
        在 lookup 时 fallback 到 default emotion 的 prompt_text。
        """
        cache: Dict[str, str] = {}
        bank_dir = Path(self.local_emotion_bank)
        if not bank_dir.is_dir():
            logger.warning(
                "[gsv] local_emotion_bank dir missing: %s · 0 .lab loaded "
                "(PM rsync 后 restart 生效)",
                bank_dir,
            )
            return cache
        for lab_path in bank_dir.glob("*.lab"):
            try:
                cache[lab_path.stem] = lab_path.read_text(encoding="utf-8").strip()
            except OSError as exc:
                logger.warning(
                    "[gsv] .lab read failed %s: %s", lab_path, exc,
                )
        return cache

    def _resolve_ref_wav(self, emotion: str) -> str:
        """emotion → wav 文件名(不含 .wav 后缀)· 带 fallback。

        2026-06-11 · § 4 spec:集合改 self._lab_cache.keys() 派生(per-model
        自然成立 · 删 V2'' hardcoded _GSV_MAI_V4_EMOTIONS frozenset)。
          - emotion ∈ ("默认", "", None) → default_emotion
          - emotion ∈ lab_cache.keys() → emotion 本身
          - 其它(LLM 自创 X / 集合外) → default_emotion + log warn
        """
        if not emotion or emotion in ("默认", "<NULL>"):
            logger.info(
                "[gsv] _resolve_ref_wav emotion=%r → %s (fallback default)",
                emotion, self.default_emotion,
            )
            return self.default_emotion
        if emotion in self._lab_cache:
            return emotion
        logger.warning(
            "[gsv] _resolve_ref_wav emotion=%r 不在 lab_cache (%d entries) · "
            "fallback → %s",
            emotion, len(self._lab_cache), self.default_emotion,
        )
        return self.default_emotion

    async def _ensure_model_loaded(self) -> bool:
        """Lazy 调 /set_gpt_weights + /set_sovits_weights · per-process once-per-key。

        per PM §0.3 + §8:GSV server 重启后默认 load 芙宁娜 v4 pretrained ·
        Skyler 必须主动切 mai_v4。本 method 在第一次 synthesize 调用前触发,
        module-level lock 保证多 turn 并发只切一次。

        Returns:
            True  · weights set 成功 / 已加载过 → synthesize 可继续调 /tts
            False · weights set 失败 → synthesize 应直接 fallback stub,**不调 /tts**

        hotfix (2026-05-25 21:xx PM lock):失败时 mark _MODEL_LOAD_FAILED_KEYS,
        avoid 拿空 / 错 weights state 进 /tts → corrupt server 9880 state →
        后续 /tts 全 502(PM 真机实测)。backend restart 后 module state 清空 ·
        FAILED_KEYS 也清 · 下次 synthesize 自然 retry。
        """
        key = f"{self.server_url}|{self.gpt_weights}|{self.sovits_weights}"
        if key in _MODEL_LOADED_KEYS:
            return True
        if key in _MODEL_LOAD_FAILED_KEYS:
            return False  # 已 fail 过 · 不再尝试(backend restart 后才 retry)
        async with _MODEL_LOAD_LOCK:
            if key in _MODEL_LOADED_KEYS:
                return True
            if key in _MODEL_LOAD_FAILED_KEYS:
                return False
            try:
                # 2026-06-14 · trust_env=False 显式绕过 shell HTTP(S)_PROXY ·
                # 局域网 GSV server(eg 192.168.x.x:9880)调用 · 不依赖
                # NO_PROXY 环境变量 · 详见同 client 在 synthesize / gsv_ping 同款。
                async with httpx.AsyncClient(
                    timeout=_WEIGHTS_TIMEOUT_S, trust_env=False,
                ) as client:
                    r_gpt = await client.get(
                        f"{self.server_url}/set_gpt_weights",
                        params={"weights_path": self.gpt_weights},
                    )
                    r_sov = await client.get(
                        f"{self.server_url}/set_sovits_weights",
                        params={"weights_path": self.sovits_weights},
                    )
                gpt_ok = r_gpt.status_code == 200 and "success" in r_gpt.text.lower()
                sov_ok = r_sov.status_code == 200 and "success" in r_sov.text.lower()
                if gpt_ok and sov_ok:
                    _MODEL_LOADED_KEYS.add(key)
                    logger.info(
                        "[gsv] _ensure_model_loaded ✓ gpt=%s sovits=%s",
                        self.gpt_weights, self.sovits_weights,
                    )
                    return True
                _MODEL_LOAD_FAILED_KEYS.add(key)
                logger.error(
                    "[gsv] _ensure_model_loaded FAIL · weights set 失败 "
                    "(gpt: status=%d text=%r · sovits: status=%d text=%r);"
                    "SKIP /tts call · synthesize 将 fallback stub。"
                    "PM 需手动 SSH server `curl /set_gpt_weights?weights_path=%s` "
                    "+ `curl /set_sovits_weights?weights_path=%s` 恢复 9880 state,"
                    "然后 backend restart 清空 FAILED_KEYS 重新 retry。",
                    r_gpt.status_code, r_gpt.text[:120],
                    r_sov.status_code, r_sov.text[:120],
                    self.gpt_weights, self.sovits_weights,
                )
                return False
            except Exception as exc:
                _MODEL_LOAD_FAILED_KEYS.add(key)
                logger.error(
                    "[gsv] _ensure_model_loaded EXCEPTION %s: %s "
                    "· server 可能离线 / 网络断 · SKIP /tts call · "
                    "synthesize 将 fallback stub",
                    type(exc).__name__, exc,
                )
                return False

    async def synthesize(
        self, text: str, emotion: str = "默认",
    ) -> Optional[bytes]:
        """合成单句 · GSV /tts → RIFF WAV bytes;失败 fallback stub。"""
        if not text or not text.strip():
            return None

        # 路由 emotion → ref wav 文件名(V2'' 已 16 集合 + "日常" fallback)
        m = _EMOTION_PREFIX_RE.match(text)
        parsed_emotion = m.group(1).strip() if m else None
        chosen = parsed_emotion or emotion
        ref_name = self._resolve_ref_wav(chosen)
        ref_audio_path = f"{self.remote_emotion_bank}{ref_name}.wav"
        prompt_text = (
            self._lab_cache.get(ref_name)
            or self._lab_cache.get(self.default_emotion, "")
        )

        # 启动期 lazy 切 mai_v4 weights(仅 per-process 第一次 + per key 一次)
        # hotfix (2026-05-25 21:xx PM lock):若 weights set 失败 → SKIP /tts,
        # 直接 fallback stub(避免拿空 / 错 weights state 进 /tts corrupt server)。
        model_loaded = await self._ensure_model_loaded()
        if not model_loaded:
            from backend.observability.tts_log import log_tts_call
            await log_tts_call(
                success=False,
                voice=self._cfg.voice,
                model=self._cfg.model,
                input_chars=len(text),
                input_preview=text,
                error_message="GSV weights set failed · skipped /tts · fallback stub",
            )
            if self._fallback_stub_bytes:
                logger.warning(
                    "[gsv] weights NOT loaded · SKIP /tts · fallback stub "
                    "(%d bytes) · PM 需 SSH server 手动恢复 weights + backend restart",
                    len(self._fallback_stub_bytes),
                )
                return self._fallback_stub_bytes
            logger.error("[gsv] weights NOT loaded AND fallback stub missing · return None")
            return None

        # 调用 /tts
        params: Dict[str, Any] = {
            "text": text,
            "text_lang": self.tts_language,
            "ref_audio_path": ref_audio_path,
            "prompt_text": prompt_text,
            "prompt_lang": self.tts_language,
            **self.inference_params,
        }
        audio: Optional[bytes] = None
        error_msg: Optional[str] = None
        try:
            # 2026-06-14 · trust_env=False 绕过 shell HTTP(S)_PROXY · 局域网
            # GSV server 调用不依赖 NO_PROXY · 同 _ensure_model_loaded / ping。
            async with httpx.AsyncClient(
                timeout=_TTS_TIMEOUT_S, trust_env=False,
            ) as client:
                resp = await client.get(f"{self.server_url}/tts", params=params)
            if resp.status_code != 200:
                error_msg = (
                    f"GSV /tts HTTP {resp.status_code}: {resp.text[:160]}"
                )
                logger.warning("[gsv] %s", error_msg)
                audio = None
            elif not resp.content or resp.content[:4] != b"RIFF":
                error_msg = (
                    f"GSV /tts non-RIFF response · ct={resp.headers.get('content-type')} "
                    f"head={resp.content[:80]!r}"
                )
                logger.warning("[gsv] %s", error_msg)
                audio = None
            else:
                audio = resp.content
                logger.info(
                    "[gsv] synth ✓ text=%r emotion=%s ref=%s.wav · %d bytes",
                    text[:80], chosen, ref_name, len(audio),
                )
        except Exception as exc:
            error_msg = f"{type(exc).__name__}: {exc}"
            logger.warning("[gsv] /tts exception: %s", error_msg)
            audio = None

        # log_tts_call(per V2'' hotfix-2 · 复用 cosyvoice/fish 同款 pattern)
        from backend.observability.tts_log import log_tts_call
        await log_tts_call(
            success=audio is not None,
            voice=self._cfg.voice,
            model=self._cfg.model,
            input_chars=len(text),
            input_preview=text,
            error_message=error_msg[:500] if error_msg else None,
        )

        # Fallback chain · GSV 失败时返 stub bytes(per V2'' baseline 行为)
        if audio is None:
            if self._fallback_stub_bytes:
                logger.warning(
                    "[gsv] /tts failed · fallback to mai5min_0033 stub "
                    "(%d bytes) · 用户会听到 baseline Mai voice 而非 emotion 合成",
                    len(self._fallback_stub_bytes),
                )
                return self._fallback_stub_bytes
            logger.error(
                "[gsv] /tts failed AND fallback stub missing · return None"
            )
            return None

        return audio


# ---------------------------------------------------------------------------
# Module-level ref management(per SPEC-LOCK · #2 · 2026-06-11)
# 单独函数 · 不挂 GSVTTS 实例(实例 per-turn 重建 · CRUD 路径不该现造实例)。
# 跟覆盖视图(routes/tts_api.py::emotion_coverage)同源:fs glob lab_dir/*.lab。
# 远程 wav 上传留 stub NotImplementedError(本轮 SSH 范畴 defer)。
# ---------------------------------------------------------------------------


def list_refs(local_bank_dir: str) -> List[Dict[str, Any]]:
    """fs glob 本地 lab_dir/*.lab · 返每条 emotion 状态。

    Args:
        local_bank_dir: 本地 .lab 缓存目录(repo 相对路径或绝对路径)

    Returns:
        [{"name": <emotion stem>, "has_local_lab": True,
          "lab_size": <int bytes>, "lab_preview": <str 前 60 字符>}, ...]
        目录不存在 / 0 个 .lab → 返 [](调用方决定如何展示)。

    跟 GSVTTS._load_lab_cache 同 glob pattern · 但本函数无实例 cache · 每次
    fresh fs read(ms 级,适合 endpoint per-request 触发)。
    """
    p = Path(local_bank_dir)
    if not p.is_dir():
        return []
    out: List[Dict[str, Any]] = []
    for lab_path in sorted(p.glob("*.lab")):
        try:
            text_content = lab_path.read_text(encoding="utf-8").strip()
            size = lab_path.stat().st_size
        except OSError as exc:
            logger.warning("[gsv.list_refs] read %s failed: %s", lab_path, exc)
            continue
        out.append({
            "name": lab_path.stem,
            "has_local_lab": True,
            "lab_size": size,
            "lab_preview": text_content[:60],
        })
    return out


def upload_ref_local(
    local_bank_dir: str, emotion: str, prompt_text: str,
) -> Path:
    """写 <local_bank_dir>/<emotion>.lab(UTF-8 文本一行)· 返写入路径。

    PM SPEC-LOCK §#2:本轮只本地落 .lab · server 端 wav 仍手动放(SSH 范畴)。

    安全:
      - emotion 不允许含 path separator(./.. / / \\)避免 path traversal
      - 目录不存在 → mkdir parents=True(允许新 model 的新 lab_dir 首次写)
      - 已存在 .lab 直接 overwrite(类比"编辑 emotion 提示词")

    Args:
        local_bank_dir: 本地 .lab 缓存目录
        emotion: emotion 名(将作 stem · 不含 .lab 后缀)
        prompt_text: .lab 文件内容(ja prompt text · 通常一行)

    Returns:
        实际写入文件的 Path。

    Raises:
        ValueError: emotion 含非法字符
        OSError: 文件 IO 失败
    """
    if not emotion or any(c in emotion for c in ("/", "\\", "..", ":")):
        raise ValueError(
            f"emotion contains path separator / unsafe chars: {emotion!r}"
        )
    bank = Path(local_bank_dir)
    bank.mkdir(parents=True, exist_ok=True)
    target = bank / f"{emotion}.lab"
    target.write_text(prompt_text.strip(), encoding="utf-8")
    logger.info(
        "[gsv.upload_ref_local] wrote %s (%d bytes)",
        target, target.stat().st_size,
    )
    return target


def upload_ref_remote(
    server_url: str, wav_remote_dir: str,
    emotion: str, wav_bytes: bytes,
) -> None:
    """远程 wav 上传 · 本轮 stub · server 端推送走 SSH 范畴 · defer。"""
    raise NotImplementedError(
        "upload_ref_remote: 远程 wav 上传未实现 · 本轮 PM SPEC-LOCK 范围外 · "
        "请 SSH server 手动放到 wav_remote_dir 下"
    )
