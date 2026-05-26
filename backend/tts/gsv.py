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

logger = logging.getLogger(__name__)

_EMOTION_PREFIX_RE = re.compile(r"^\s*<emotion>(.+?)</emotion>", re.IGNORECASE)

# stub fallback wav · GSV server unreachable / 5xx / non-RIFF 时返这个
# (~5min Mai 参考音频 · 1.2MB · V2'' 一直在用)
_FALLBACK_STUB_WAV = (
    Path(__file__).resolve().parent.parent.parent
    / "tts" / "fish" / "参考音频" / "mai" / "mai5min_0033.wav"
)

# V2'' 16 emotion ref bank 集合(per PM §3.1 lock · "平静" → "日常")
_GSV_MAI_V4_EMOTIONS: frozenset[str] = frozenset({
    "日常", "温柔", "傲娇", "吃醋", "严厉", "慌乱", "害羞", "调皮",
    "安慰", "伤感", "真挚", "幸福", "感谢", "放松", "叙事", "感动",
})

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
        self.server_url: str = raw.get("server_url") or _DEFAULT_SERVER_URL
        # hotfix (2026-05-25):向后兼容 V2'' 旧字段名(gpt_path/sovits_path · 值为
        # "placeholder")· 跳过 placeholder fallback default(真路径)。
        self.gpt_weights: str = _resolve_weights_field(
            raw, "gpt_weights", "gpt_path", _DEFAULT_GPT_WEIGHTS,
        )
        self.sovits_weights: str = _resolve_weights_field(
            raw, "sovits_weights", "sovits_path", _DEFAULT_SOVITS_WEIGHTS,
        )
        self.remote_emotion_bank: str = (
            raw.get("remote_emotion_bank_dir") or _DEFAULT_REMOTE_BANK
        )
        self.local_emotion_bank: str = (
            raw.get("emotion_bank_dir") or _DEFAULT_LOCAL_BANK
        )
        self.default_emotion: str = (
            raw.get("default_emotion") or _DEFAULT_FALLBACK_EMOTION
        )
        # ensure remote_emotion_bank trailing slash · 避免 path join 错
        if not self.remote_emotion_bank.endswith("/"):
            self.remote_emotion_bank += "/"
        # inference_params 合并 default + raw overrides
        _ip = raw.get("inference_params") or {}
        self.inference_params: Dict[str, Any] = dict(_DEFAULT_INFERENCE_PARAMS)
        if isinstance(_ip, dict):
            self.inference_params.update(_ip)
        # tts_language from cfg (parsed at voice_config layer)
        self.tts_language: str = (
            getattr(self._cfg, "tts_language", None) or "ja"
        )

        # 启动时 lazy 读 16 个 .lab 进 in-memory cache
        self._lab_cache: Dict[str, str] = self._load_lab_cache()
        # fallback stub bytes(reused per V2'' · GSV unreachable 时返这个)
        self._fallback_stub_bytes: Optional[bytes] = _load_fallback_stub_bytes()

        logger.info(
            "[gsv] init server=%s gpt=%s sovits=%s lab_cache=%d files "
            "remote_bank=%s lang=%s · fallback_stub=%s",
            self.server_url, self.gpt_weights, self.sovits_weights,
            len(self._lab_cache), self.remote_emotion_bank,
            self.tts_language,
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

        per V2'' (2026-05-25):
          - emotion ∈ ("默认", "", None) → "日常"
          - emotion ∈ 16 集合 → emotion 本身
          - 其它(LLM 自创 X)→ "日常" + log warn
        """
        if not emotion or emotion in ("默认", "<NULL>"):
            logger.info(
                "[gsv] _resolve_ref_wav emotion=%r → %s (fallback default)",
                emotion, self.default_emotion,
            )
            return self.default_emotion
        if emotion in _GSV_MAI_V4_EMOTIONS:
            return emotion
        logger.warning(
            "[gsv] _resolve_ref_wav emotion=%r 不在 16 集合 · fallback → %s",
            emotion, self.default_emotion,
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
                async with httpx.AsyncClient(timeout=_WEIGHTS_TIMEOUT_S) as client:
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
            async with httpx.AsyncClient(timeout=_TTS_TIMEOUT_S) as client:
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
