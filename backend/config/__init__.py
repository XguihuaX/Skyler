"""backend.config package.

Re-exports the same top-level names that backend/config.py used to provide,
so that all existing `from backend.config import settings` imports keep working.

Sub-modules:
  backend.config.characters   — characters.yaml (loaded by prompt_manager)
  backend.config.prompts      — static prompt strings
  backend.config.prompt_manager — PromptManager + prompt_manager singleton
"""
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    deepseek_api_key: str = ""
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    dashscope_api_key: str = ""
    dashscope_base_url: str = ""    # DashScope OpenAI-compatible endpoint
    serper_api_key: str = ""        # Google search via serper.dev; leave empty to use DuckDuckGo
    sovits_api_url: str = "http://127.0.0.1:9880"
    sovits_model_dir: str = ""      # base directory for SoVITS reference audio files
    whisper_model: str = "small"
    whisper_device: str = "cpu"
    database_url: str = "sqlite+aiosqlite:///./momoos.db"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


@lru_cache()
def get_settings() -> Settings:
    return Settings()


def load_config_yaml() -> dict:
    # config.yaml lives at the project root (two levels up from this file)
    config_path = Path(__file__).parent.parent.parent / "config.yaml"
    if config_path.exists():
        with open(config_path) as f:
            return yaml.safe_load(f) or {}
    return {}


settings: Settings = get_settings()
config_yaml: dict = load_config_yaml()


def reload_config_yaml() -> dict:
    """Reload config.yaml into the existing module-level dict in place.

    Importing modules that hold a reference to ``config_yaml`` (via
    ``from backend.config import config_yaml``) will see the new values
    because we mutate the same dict object instead of rebinding.
    """
    new_data = load_config_yaml()
    config_yaml.clear()
    config_yaml.update(new_data)
    return config_yaml


def get_default_model() -> str:
    """Return the current default LLM model from config.yaml.

    Read on every call so that callers always see the latest value after
    reload_config_yaml(). Do not cache.
    """
    return config_yaml.get("default_model", "deepseek/deepseek-chat")


def get_planner_model() -> str:
    """Return the planner-only LLM model. Falls back to default_model when blank."""
    val = config_yaml.get("planner_model")
    if val:
        return val
    return get_default_model()


def get_tts_enabled() -> bool:
    """每次读最新值，无缓存"""
    return config_yaml.get("tts", {}).get("enabled", True)


def get_long_term_enabled() -> bool:
    return (config_yaml.get("memory") or {}).get("long_term_enabled", True)


def get_profile_enabled() -> bool:
    return (config_yaml.get("memory") or {}).get("profile_enabled", True)


def get_enable_search() -> bool:
    return (config_yaml.get("search") or {}).get("enable_search", True)


def get_base_instruction() -> str:
    """全局通用设定，会拼接到每个角色 persona 之前。

    每次读最新值，无缓存；POST /api/config/base_instruction 写入后
    走 reload_config_yaml() 即可生效，无需重启进程。
    """
    return config_yaml.get("base_instruction", "")


# ---------------------------------------------------------------------------
# v3-D / TTS：CosyVoice 接入
# ---------------------------------------------------------------------------


def get_tts_provider() -> str:
    """全局默认 TTS provider，character.voice_model 为空时生效。"""
    return (config_yaml.get("tts") or {}).get("provider", "cosyvoice")


def get_tts_emotions() -> list[str]:
    """允许 LLM 输出的情感词列表，传入 emotion-instruction 提示中。"""
    return (config_yaml.get("tts") or {}).get(
        "emotions",
        ["neutral", "happy", "sad", "angry", "surprised"],
    )


def get_cosyvoice_config() -> dict:
    """CosyVoice 子配置，含 model / default_voice / instruct_supported。"""
    return (config_yaml.get("tts") or {}).get("cosyvoice", {}) or {}


def get_available_voices() -> dict:
    """v3-G' chunk 1：返回 config.yaml 的 ``tts.available_voices`` 块。

    GET /api/tts/voices 直接序列化此结构。Returns dict like::

        {
          "cosyvoice": [
            {"id": "longyumi_v3", "label": "龙裕米 v3", "ssml": true, ...},
            ...
          ]
        }

    Provider 缺失 / 配置错误时返回 ``{}``，由 router 包成空 providers 列表。
    """
    return (config_yaml.get("tts") or {}).get("available_voices", {}) or {}


def get_default_voice_config() -> dict:
    """全局默认 VoiceConfig 的原始字典。

    用于 backend/tts/__init__.py 的 get_tts_engine 在 character.voice_model
    为空时的 fallback。
    """
    provider = get_tts_provider()
    if provider == "cosyvoice":
        cfg = get_cosyvoice_config()
        return {
            "provider": "cosyvoice",
            "voice": cfg.get("default_voice", "longyumi_v3"),
            "instruct_supported": bool(cfg.get("instruct_supported", False)),
        }
    # 兜底回 Edge-TTS（无外网或 dashscope key 缺失时仍可工作）
    return {
        "provider": "edge",
        "voice": "zh-CN-XiaoxiaoNeural",
        "instruct_supported": False,
    }
