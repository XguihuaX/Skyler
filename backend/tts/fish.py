"""Fish Audio s2-pro TTS implementation(INV-9 §4 / Phase 2 第 2 commit)。

per INV-8 §1.3 调研 + §1.5.8 + §1.收口.6 PM 拍板:
  - references[] inline mode_A only(强制 reference_audio + reference_text;
    缺则 parse_voice_config 已 raise,本类构造再 defensive 校验)
  - backend='s2-pro' HTTP header(per PM Step 5 lock,s1 / v1.6 不调研)
  - latency='balanced' default(per Step 5 stage 2 实测 ~593ms TTFA,vs
    normal ~2296ms;详 INV-8 §1.3.10 Finding #2)
  - synthesize(text, emotion) → bytes(per Step 1 决策 3:保留旧签名,
    流式走新增 synthesize_stream 留 Phase 3 H3 fix 合刀)

per-provider sanitize Hard Req(INV-8 §1.3.7 / §1.5.8 / PM Step 5 lock):
  Fish [bracket] markers 仅在 fish 模式 LLM 输出;非 fish provider 接收端
  必须 strip [bracket]。本 provider 接到 text 时**保留** [bracket] 透传
  给 SDK。下游 strip 在 _PreprocessingEngine(本 commit 不动)或 LLM
  生成端 prompt addendum(本 commit 不动,留 INV-9 §5/§6 合刀)管。

cost / balance 监控(Step 5 实测):SDK 提供 get_api_credit() 和
get_package() 双 API;本 commit 不实 cost cap 路径(留 INV-9 §7);本
commit 仅 log_tts_call INSERT input_chars,后续聚合时按 $15/1M UTF-8
bytes 计算 cost_estimate。
"""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Optional

from fish_audio_sdk import HttpCodeErr, ReferenceAudio, Session, TTSRequest

from backend.tts.base import TTSBase
from backend.tts.voice_config import VoiceConfig

logger = logging.getLogger(__name__)


def _resolve_fish_api_key() -> str:
    """读取 Fish API key。

    优先级:
      1. ``os.environ['FISH_API_KEY']``(生产 / CI 推荐)
      2. ``<repo_root>/api_key.txt``(dev / audit 期间便利;`.gitignore` 已加)
      3. 空串 + warning(synth 时调用会 401,由 caller try/except 兜底)
    """
    env_key = os.environ.get("FISH_API_KEY", "").strip()
    if env_key:
        return env_key
    repo_root = Path(__file__).resolve().parent.parent.parent
    key_file = repo_root / "api_key.txt"
    if key_file.exists():
        try:
            return key_file.read_text(encoding="utf-8").strip()
        except OSError as exc:
            logger.warning("[fish] api_key.txt read failed: %s", exc)
    return ""


def _resolve_reference_path(p: str) -> Path:
    """relative 路径相对 repo root;absolute 路径 as-is。"""
    path = Path(p)
    if path.is_absolute():
        return path
    return Path(__file__).resolve().parent.parent.parent / p


class FishTTS(TTSBase):
    """Fish s2-pro TTS with zero-shot voice cloning (mode_A only).

    构造时一次性读 reference_audio bytes + 解析 API key + 构 Session,后续
    synthesize 调用复用。voice_config 必须含 reference_audio_path +
    reference_text(parse_voice_config 已校验,这里 defensive 再 check)。

    emotion 字段在 fish provider 路径下**不使用**(per INV-8 §1.3.7 schema β:
    emotion 通过 LLM 输出的 ``[bracket]`` markers inline 在 text 内,不走
    单独参数)。保留 ``emotion`` 形参兼容 ``TTSBase.synthesize`` 接口签名。
    """

    def __init__(self, voice_config: VoiceConfig) -> None:
        # INV-12 Stage 2(2026-05-23)· PM Q5 lock 3 层 fallback merge:
        # L1 user_override(voice_config.user_*) > L2 角色 default(voice_config.*)
        # > L3 yaml global default(parse_voice_config 兜底 cfg.provider 已切走)
        #
        # 配对约束(audio + text):违反 → log warning + 两字段全回退 L2。
        # 独立参数(temperature / top_p):单独 None 独立回退该字段到 L2。
        _u_audio = voice_config.user_reference_audio_path
        _u_text = voice_config.user_reference_text
        _audio_paired = (_u_audio is not None and _u_text is not None)
        _audio_violation = ((_u_audio is None) != (_u_text is None))
        if _audio_violation:
            logger.warning(
                "[fish] user_reference_* 配对约束违反 audio=%s text=%s · "
                "回退 L2 default reference(防 alignment 错位)",
                bool(_u_audio), bool(_u_text),
            )
        ref_audio_path_effective = (_u_audio if _audio_paired
                                    else voice_config.reference_audio_path)
        ref_text_effective = (_u_text if _audio_paired
                              else voice_config.reference_text)

        # Defensive: parse_voice_config 已校验 L2 必填,但 user 可能没传 +
        # L2 default 也没配的极端 case(per Q5 三层 fallback 之外的 raise hint)
        if not ref_audio_path_effective or not ref_text_effective:
            raise ValueError(
                "FishTTS requires reference_audio_path + reference_text "
                "(L1 user_override 或 L2 default 至少一层完整);"
                "mode_A only · INV-9 §4 + INV-12 Stage 2 defensive check"
            )

        self.voice_config = voice_config
        # model field 承载 Fish backend 选择;本轮 lock 's2-pro'
        self.backend: str = voice_config.model or "s2-pro"
        self.latency: str = voice_config.fish_latency or "balanced"
        # INV-9 参数 sweep 刀(2026-05-22)+ INV-12 Stage 2(2026-05-23)·
        # 独立参数 user_override > default merge(短路 L1 → L2)
        self.temperature: Optional[float] = (
            voice_config.user_fish_temperature
            if voice_config.user_fish_temperature is not None
            else voice_config.fish_temperature
        )
        self.top_p: Optional[float] = (
            voice_config.user_fish_top_p
            if voice_config.user_fish_top_p is not None
            else voice_config.fish_top_p
        )
        # seed: SDK TTSRequest 字段表不含 seed;保留作 future hook,
        # 不向 TTSRequest 透传,仅 log warning 提醒
        self.seed: Optional[int] = voice_config.fish_seed
        if self.seed is not None:
            logger.warning(
                "[fish] voice_config.fish_seed=%r configured but SDK TTSRequest "
                "does not accept 'seed' field; param ignored (future SDK hook)",
                self.seed,
            )

        api_key = _resolve_fish_api_key()
        if not api_key:
            logger.warning(
                "[fish] FISH_API_KEY env unset + api_key.txt missing; "
                "synth will 401 — set FISH_API_KEY or place api_key.txt at repo root",
            )
        self._session: Optional[Session] = Session(api_key) if api_key else None

        # INV-12 Stage 2:用 merge 后的 effective ref path / text(L1 or L2)
        ref_path = _resolve_reference_path(ref_audio_path_effective)
        if not ref_path.exists():
            raise FileNotFoundError(
                f"FishTTS reference_audio_path not found: {ref_path}"
            )
        self._ref_audio_bytes: bytes = ref_path.read_bytes()
        self._ref_text: str = ref_text_effective

        # INV-12 Stage 2:log 标 user_override 层是否生效(便 PM 真机 verify)
        _ref_layer = "L1 user_override" if _audio_paired else "L2 default"
        _temp_layer = ("L1" if voice_config.user_fish_temperature is not None
                       else "L2")
        _top_p_layer = ("L1" if voice_config.user_fish_top_p is not None
                        else "L2")
        logger.info(
            "[fish] init voice=%s backend=%s latency=%s "
            "ref=%s (%d bytes) ref_text_chars=%d · merge: ref=%s temp=%s top_p=%s",
            voice_config.voice, self.backend, self.latency,
            ref_path.name, len(self._ref_audio_bytes), len(self._ref_text),
            _ref_layer, _temp_layer, _top_p_layer,
        )

    def _build_request(self, text: str) -> TTSRequest:
        # INV-9 参数 sweep 刀 · 仅 if not None 时传 temperature / top_p;
        # 未传 = SDK 真默认(0.7 / 0.7)作对照组,per PM lock
        kwargs: dict = {
            "text": text,
            "references": [ReferenceAudio(
                audio=self._ref_audio_bytes, text=self._ref_text,
            )],
            "format": "wav",
            "latency": self.latency,
        }
        if self.temperature is not None:
            kwargs["temperature"] = self.temperature
        if self.top_p is not None:
            kwargs["top_p"] = self.top_p
        # seed: SDK 不接受,见构造 log warning(此处不传)
        return TTSRequest(**kwargs)

    def _blocking_synth(self, text: str) -> Optional[bytes]:
        """SDK ``Session.tts()`` 返 ``Generator[bytes]``;sync collect to bytes。

        Phase 3 流式管线对接 ``synthesize_stream`` 改走 ``stream_websocket``
        + 实时 chunk yield(per INV-8 §1.3.3 + H3 fix 合刀)。
        """
        if not self._session:
            return None
        req = self._build_request(text)
        out = b""
        for chunk in self._session.tts(req, backend=self.backend):
            out += chunk
        return out if out else None

    async def synthesize(
        self, text: str, emotion: str = "默认",
    ) -> Optional[bytes]:
        """合成单句;失败返 None 由上层静默跳过(per TTSBase 契约)。

        emotion 字段 fish 路径下不使用(走 inline ``[bracket]`` markers)。
        log_tts_call 与 cosyvoice.py 同 pattern,source 走 ContextVar(由
        caller 在 ws.py / proactive 入口 set_tts_call_context)。
        """
        if not text or not text.strip():
            return None
        from backend.observability.tts_log import log_tts_call
        input_chars = len(text)
        try:
            audio = await asyncio.to_thread(self._blocking_synth, text)
            await log_tts_call(
                success=audio is not None,
                voice=self.voice_config.voice,
                model=self.backend,
                input_chars=input_chars,
                input_preview=text,
                error_message=(None if audio is not None
                               else "Fish returned empty audio"),
            )
            return audio
        except HttpCodeErr as exc:
            logger.error(
                "[fish] HTTP %s voice=%s text=%r",
                exc.status, self.voice_config.voice, text[:30],
            )
            await log_tts_call(
                success=False,
                voice=self.voice_config.voice,
                model=self.backend,
                input_chars=input_chars,
                input_preview=text,
                error_message=f"HttpCodeErr({exc.status}): {exc}"[:500],
            )
            return None
        except Exception as exc:
            logger.error(
                "[fish] synth failed voice=%s err=%s text=%r",
                self.voice_config.voice, exc, text[:30],
            )
            await log_tts_call(
                success=False,
                voice=self.voice_config.voice,
                model=self.backend,
                input_chars=input_chars,
                input_preview=text,
                error_message=str(exc)[:500],
            )
            return None

    # synthesize_stream:留 Phase 3 H3 fix 合刀实现
    # (per INV-8 §1.5.10 Option A1 lock + §1.收口.4 Step 6 backlog)。
    # 走 fish_audio_sdk.WebSocketSession + StartEvent/TextEvent/AudioEvent/
    # FinishEvent 协议(MsgPack),latency='balanced',TTFA ~593ms 实测。
