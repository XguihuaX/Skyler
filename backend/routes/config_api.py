"""Config REST API.

Mounted at /api in main.py.  Full URL map:
  GET   /api/config
  POST  /api/config/reload
  GET   /api/config/base_instruction
  POST  /api/config/base_instruction
"""
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.config import config_yaml, reload_config_yaml
from backend.utils.yaml_atomic import write_config_atomic

router = APIRouter()

# config.yaml 与 backend/config/__init__.py 中的 load_config_yaml 保持一致
_CONFIG_PATH = Path(__file__).parent.parent.parent / "config.yaml"


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class MemoryConfig(BaseModel):
    long_term_enabled: bool = True
    profile_enabled: bool = True


class SearchConfig(BaseModel):
    enable_search: bool = True


class CacheConfig(BaseModel):
    profile_ttl_seconds: int = 300


class TtsConfig(BaseModel):
    enabled: bool = True


class MorningBriefingConfig(BaseModel):
    enabled: bool = True
    cron: str = "0 9 * * *"
    city: str = "东京"


class WakeCallBriefingConfig(BaseModel):
    cron: str = "0 8 * * *"
    pending_ttl_minutes: int = 30
    default_snooze_minutes: int = 30
    city: str = "东京"


class ProactiveConfig(BaseModel):
    enabled: bool = True
    # v3-G chunk 2.6 mode 互斥：'wake_call' / 'morning_briefing' / 'off'
    mode: str = "wake_call"
    character_id_override: int | None = None
    morning_briefing: MorningBriefingConfig = MorningBriefingConfig()
    wake_call_briefing: WakeCallBriefingConfig = WakeCallBriefingConfig()


class ConfigResponse(BaseModel):
    default_model: str = "deepseek/deepseek-chat"
    default_user_id: str = "default"
    memory: MemoryConfig = MemoryConfig()
    search: SearchConfig = SearchConfig()
    cache: CacheConfig = CacheConfig()
    tts: TtsConfig = TtsConfig()
    proactive: ProactiveConfig = ProactiveConfig()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_config_response() -> ConfigResponse:
    """Extract the whitelist fields from config_yaml into a ConfigResponse."""
    memory_raw: dict = config_yaml.get("memory") or {}
    search_raw: dict = config_yaml.get("search") or {}
    cache_raw: dict = config_yaml.get("cache") or {}
    tts_raw: dict = config_yaml.get("tts") or {}
    proactive_raw: dict = config_yaml.get("proactive") or {}
    morning_raw: dict = proactive_raw.get("morning_briefing") or {}
    wake_raw: dict = proactive_raw.get("wake_call_briefing") or {}

    char_override = proactive_raw.get("character_id_override")
    if not isinstance(char_override, int):
        char_override = None

    mode_raw = str(proactive_raw.get("mode") or "wake_call").strip().lower()
    if mode_raw not in ("wake_call", "morning_briefing", "off"):
        mode_raw = "wake_call"

    return ConfigResponse(
        default_model=config_yaml.get("default_model", "deepseek/deepseek-chat"),
        default_user_id=config_yaml.get("default_user_id", "default"),
        memory=MemoryConfig(
            long_term_enabled=memory_raw.get("long_term_enabled", True),
            profile_enabled=memory_raw.get("profile_enabled", True),
        ),
        search=SearchConfig(
            enable_search=search_raw.get("enable_search", True),
        ),
        cache=CacheConfig(
            profile_ttl_seconds=cache_raw.get("profile_ttl_seconds", 300),
        ),
        tts=TtsConfig(
            enabled=tts_raw.get("enabled", True),
        ),
        proactive=ProactiveConfig(
            enabled=bool(proactive_raw.get("enabled", True)),
            mode=mode_raw,
            character_id_override=char_override,
            morning_briefing=MorningBriefingConfig(
                enabled=bool(morning_raw.get("enabled", True)),
                cron=str(morning_raw.get("cron") or "0 9 * * *"),
                city=str(morning_raw.get("city") or "东京"),
            ),
            wake_call_briefing=WakeCallBriefingConfig(
                cron=str(wake_raw.get("cron") or "0 8 * * *"),
                pending_ttl_minutes=int(wake_raw.get("pending_ttl_minutes") or 30),
                default_snooze_minutes=int(wake_raw.get("default_snooze_minutes") or 30),
                city=str(wake_raw.get("city") or "东京"),
            ),
        ),
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/config", response_model=ConfigResponse)
async def get_config() -> Any:
    """Return the whitelisted subset of config.yaml for the Settings panel."""
    return _build_config_response()


@router.post("/config/reload")
async def reload_config() -> dict:
    """Reload config.yaml from disk into memory and return status."""
    try:
        reload_config_yaml()
    except yaml.YAMLError as exc:
        raise HTTPException(status_code=500, detail=f"config.yaml syntax error: {exc}") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# v3-B 补丁：通用设定 (base_instruction)
# ---------------------------------------------------------------------------

class BaseInstructionResponse(BaseModel):
    base_instruction: str = ""


class BaseInstructionUpdateBody(BaseModel):
    base_instruction: str


@router.get("/config/base_instruction", response_model=BaseInstructionResponse)
async def get_base_instruction_endpoint() -> Any:
    """读取当前 config.yaml 中的通用设定。"""
    return BaseInstructionResponse(
        base_instruction=config_yaml.get("base_instruction", "") or "",
    )


@router.post("/config/base_instruction")
async def set_base_instruction_endpoint(body: BaseInstructionUpdateBody) -> dict:
    """更新通用设定并写回 config.yaml。

    Stage 2.1.0：read-modify-write 链路下放到 ``write_config_atomic``
    helper(tmp + os.rename 原子 swap + per-path asyncio.Lock 串行化)。
    Mutate 完成后调 reload_config_yaml() 让进程内字典立即生效。
    """
    def _mutate(current: dict) -> None:
        current["base_instruction"] = body.base_instruction

    try:
        await write_config_atomic(_CONFIG_PATH, _mutate)
        reload_config_yaml()
    except yaml.YAMLError as exc:
        raise HTTPException(
            status_code=500, detail=f"config.yaml syntax error: {exc}"
        ) from exc
    except OSError as exc:
        raise HTTPException(
            status_code=500, detail=f"config.yaml write failed: {exc}"
        ) from exc
    return {"status": "ok"}
