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
    netease_music_u: str = ""       # v3-H chunk 1 — 网易云 cookie MUSIC_U（账号凭证）
    deepl_api_key: str = ""         # A2 翻译层 — DeepL API key(free/pro tier 均可)

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


@lru_cache()
def get_settings() -> Settings:
    return Settings()


def load_config_yaml() -> dict:
    """Load config.yaml + merge mcp.config.yaml(2026-06-15 ④ 拆文件)。

    主源:`<repo>/config.yaml`(PM 个人偏好 + 运行参数 · 本地不入 stage)
    MCP 拆文件后(④):`<repo>/mcp.config.yaml` 提供 `mcp_clients` + `mcp_server`
    两段(覆盖 config.yaml 同名段;config.yaml 内 mcp_* 段应已搬走,无内容时
    merge no-op)。若 `mcp.config.yaml` 不存在 → 退到 `mcp.config.example.yaml`
    (入库的零凭证模板 · fresh install 起码有几条 demo 跑得起来)。
    """
    # config.yaml lives at the project root (two levels up from this file)
    repo_root = Path(__file__).parent.parent.parent
    config_path = repo_root / "config.yaml"
    if config_path.exists():
        with open(config_path) as f:
            data = yaml.safe_load(f) or {}
    else:
        data = {}

    # 2026-06-15 ④ · MCP 段拆到 mcp.config.yaml(本地清单 · 不入 stage)
    mcp_path = repo_root / "mcp.config.yaml"
    mcp_example_path = repo_root / "mcp.config.example.yaml"
    mcp_source = None
    if mcp_path.exists():
        mcp_source = mcp_path
    elif mcp_example_path.exists():
        mcp_source = mcp_example_path
    if mcp_source is not None:
        try:
            with open(mcp_source) as f:
                mcp_data = yaml.safe_load(f) or {}
        except (OSError, yaml.YAMLError):
            mcp_data = {}
        # 覆盖语义:mcp.config.yaml 的 mcp_clients / mcp_server 整段替换
        # config.yaml 残留同名段(若有)。avoid 深 merge 防 entry 拼凑混乱。
        for key in ("mcp_clients", "mcp_server"):
            if key in mcp_data:
                data[key] = mcp_data[key]
    return data


settings: Settings = get_settings()
config_yaml: dict = load_config_yaml()


def reload_config_yaml() -> dict:
    """Reload config.yaml + mcp.config.yaml into the existing module-level dict.

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


def get_prompt_caching_enabled() -> bool:
    """Whether to inject explicit cache_control marker on supported providers.

    INV-5 §5 Phase 3:provider-aware,仅对 ``EXPLICIT_CACHE_PROVIDERS``
    (dashscope/ / anthropic/ / bedrock/)生效;其它 provider 下注入逻辑
    自动 no-op。详 ``backend/llm/client.py::_inject_cache_marker``。

    Read on every call so caller always sees latest value after
    ``reload_config_yaml()``. Do not cache.
    """
    cfg = config_yaml.get("prompt_caching") or {}
    return bool(cfg.get("enabled", True))


# bugfix-3.3: ``get_available_models()`` 已下线。yaml ``available_models``
# 字段一并删除 — DB ai_providers (bugfix-3.1+) 是新唯一 LLM 路由路径,前端
# 走 /api/ai-providers 拉 vendor / model 卡片。``default_model`` (上面)
# 保留作 dispatcher 的 fallback。


def get_whisper_model_size() -> str:
    """Bugfix-3.3 — 返回 yaml 配的 ASR (Faster Whisper) model 大小。

    优先级:``config.yaml::asr.whisper_model_size`` > ``settings.whisper_model``
    (.env / 默认 'small')。每次读最新值,UI 写回 yaml 后下次模型 reload 生效。

    Allowed values: tiny / base / small / medium / large-v3
    (UI 暂只暴露 small / medium 两档,本 stage 用户拍板:其他 size 留 v4.1+)。
    """
    asr_cfg = config_yaml.get("asr") or {}
    val = asr_cfg.get("whisper_model_size")
    if isinstance(val, str) and val.strip():
        return val.strip()
    return settings.whisper_model


def get_tts_enabled() -> bool:
    """每次读最新值，无缓存"""
    return config_yaml.get("tts", {}).get("enabled", True)


def get_long_term_enabled() -> bool:
    return (config_yaml.get("memory") or {}).get("long_term_enabled", True)


def get_profile_enabled() -> bool:
    return (config_yaml.get("memory") or {}).get("profile_enabled", True)


# ---------------------------------------------------------------------------
# v3.5 chunk 9 Part 0：embedding 检索性能调优
# ---------------------------------------------------------------------------


def _embedding_cfg() -> dict:
    return ((config_yaml.get("memory") or {}).get("embedding") or {})


def get_embedding_device() -> str:
    """``cpu`` / ``mps`` / ``auto``（auto 在 long_term._pick_device 解析）。"""
    return str(_embedding_cfg().get("device", "auto")).lower()


def get_embedding_short_input_threshold() -> int:
    """user 输入字符数 < 此值时跳过 memory 检索。默认 10。"""
    try:
        return int(_embedding_cfg().get("short_input_threshold", 10))
    except (TypeError, ValueError):
        return 10


def get_embedding_cache_size() -> int:
    """embedding LRU 缓存最大条目数。默认 100。"""
    try:
        return int(_embedding_cfg().get("cache_size", 100))
    except (TypeError, ValueError):
        return 100


def get_embedding_cache_ttl_seconds() -> int:
    """embedding 缓存 entry TTL（秒）。默认 300。"""
    try:
        return int(_embedding_cfg().get("cache_ttl_seconds", 300))
    except (TypeError, ValueError):
        return 300


# ---------------------------------------------------------------------------
# v3.5 chunk 9 Part 4：forgetting curve
# ---------------------------------------------------------------------------


def _forgetting_curve_cfg() -> dict:
    return ((config_yaml.get("memory") or {}).get("forgetting_curve") or {})


def get_forgetting_curve_enabled() -> bool:
    """是否启用 forgetting curve 加权 + 阈值（默认 True）。False 退回纯
    cosine 排序。"""
    return bool(_forgetting_curve_cfg().get("enabled", True))


def get_forgetting_curve_threshold() -> float:
    """score 低于此值 → 不进 top-k。默认 0.3。"""
    try:
        return float(_forgetting_curve_cfg().get("threshold", 0.3))
    except (TypeError, ValueError):
        return 0.3


def get_forgetting_curve_age_decay() -> float:
    """每天衰减系数。默认 0.01。"""
    try:
        return float(_forgetting_curve_cfg().get("age_decay_factor", 0.01))
    except (TypeError, ValueError):
        return 0.01


def get_enable_search() -> bool:
    return (config_yaml.get("search") or {}).get("enable_search", True)


def get_enable_thinking() -> bool:
    """qwen3.x 思考模式开关。**默 False**(关 thinking · 优先 first-token 速度)。

    每次读最新值,无缓存(同 ``get_enable_search`` live 行为) — UI 切 toggle
    后 ``setConfigField('thinking.enable_thinking', X)`` 写 yaml,下一个 turn
    立即生效。模型不支持思考(非 qwen3.x)时 ``client.py`` 侧 silent skip · log。
    """
    return (config_yaml.get("thinking") or {}).get("enable_thinking", False)


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
