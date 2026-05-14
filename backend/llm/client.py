"""Unified LLM client built on LiteLLM.

Public API
----------
call_llm   — awaitable; returns a ModelResponse (non-stream) or
             CustomStreamWrapper (stream=True).
stream_llm — async generator; yields text chunks from a streaming call.

Both functions read the default model from config.yaml and accept an optional
*model* argument to override it at call time.
"""
import logging
from typing import Any, AsyncGenerator, List, Optional, Union

from litellm import acompletion
import litellm.exceptions as llm_exc

from backend.config import get_default_model, settings
from backend.llm.tool_name_sanitize import sanitize_tools_for_llm

logger = logging.getLogger(__name__)


def _dashscope_kwargs() -> dict:
    """Return api_base/api_key kwargs when DashScope is configured.

    bugfix-3.1: 仅作为 fallback when DB-driven AI Provider 路径未命中。
    DB 路径优先, 这里只为兼容旧 yaml default_model。
    """
    if settings.dashscope_base_url and settings.dashscope_api_key:
        return {
            "api_base": settings.dashscope_base_url,
            "api_key":  settings.dashscope_api_key,
        }
    return {}


async def _resolve_db_provider_kwargs(
    model_override: Optional[str],
) -> tuple[Optional[str], dict]:
    """Bugfix-3.1 / 3.2.5: 从 DB 取 LLM active provider + vendor credential。

    Returns:
        ``(resolved_model, kwargs_dict)``。
        - 命中 DB active provider → ``(provider.model, {api_base, api_key})``
        - DB 无 active 或 caller 显式 model_override → ``(None, {})`` 表示
          让 caller 走老路径(yaml default_model + dashscope env)

    永不抛: DB 异常 / vendor 凭证缺失 → 静默返回 (None, {}), caller 兜底。

    bugfix-3.2.5: 加 ``[llm.dispatcher]`` info log 让真机走查能直接看决策路径。
    每次 call_llm 都打一行: explicit_override / db_active / fallback_yaml 三选一。
    """
    # caller 显式传 model → 尊重不动, 让老路径处理(不要被 DB active 抢)
    if model_override:
        logger.info(
            "[llm.dispatcher] explicit_override model=%s", model_override,
        )
        return None, {}
    try:
        from backend.database import ai_providers as svc
        active = await svc.get_active_provider("llm")
        if active is None or not active.enabled:
            logger.info(
                "[llm.dispatcher] no_db_active (active=%s enabled=%s) → fallback_yaml",
                None if active is None else active.id,
                None if active is None else active.enabled,
            )
            return None, {}
        kwargs: dict = {}
        credential_source = "none"
        endpoint_source = "none"
        if active.vendor_id:
            # 拆开 DB / env 两步以便 log 准确 credential_source
            db_cred = await svc.get_vendor_credential(active.vendor_id)
            if db_cred:
                kwargs["api_key"] = db_cred
                credential_source = "db"
            else:
                env_cred = await svc.resolve_vendor_credential(active.vendor_id)
                if env_cred:
                    kwargs["api_key"] = env_cred
                    credential_source = "env"
            # bugfix-3.2.6: 3-tier endpoint chain via service helper
            #   provider.endpoint > env (vendor.endpoint_env_name + aliases) > vendor.default
            endpoint, endpoint_source = await svc.resolve_vendor_endpoint(
                active.vendor_id,
                provider_endpoint_override=active.endpoint,
            )
            if endpoint:
                kwargs["api_base"] = endpoint
        logger.info(
            "[llm.dispatcher] db_active model=%s vendor=%s "
            "credential_source=%s endpoint_source=%s",
            active.model, active.vendor_id, credential_source, endpoint_source,
        )
        return active.model, kwargs
    except Exception:
        logger.exception(
            "[llm.dispatcher] DB resolve failed, falling back to yaml"
        )
        return None, {}


async def call_llm(
    messages: List[dict],
    model: Optional[str] = None,
    stream: bool = False,
    enable_search: bool = False,
    **kwargs: Any,
) -> Any:
    """Call the LLM and return the raw LiteLLM response object.

    Args:
        messages:       OpenAI-style message list.
        model:          Model identifier (e.g. ``"deepseek/deepseek-chat"``).
                        Defaults to the value in config.yaml.
        stream:         When True, returns an async-iterable stream wrapper instead
                        of a completed ModelResponse.  Use ``stream_llm`` for a
                        higher-level streaming interface.
        enable_search:  When True, injects model-specific web-search parameters:
                        qwen series → ``enable_search=True`` (DashScope param),
                        deepseek series → ``tools=[{"type": "web_search_preview"}]``.
        **kwargs:       Any additional kwargs are forwarded to ``acompletion``
                        (e.g. ``temperature``, ``max_tokens``).

    Returns:
        ``litellm.ModelResponse`` when stream=False.
        ``litellm.CustomStreamWrapper`` when stream=True.

    Raises:
        LLMAuthError, LLMRateLimitError, LLMContextError, LLMServiceError,
        LLMError — all subclass ``LLMError`` for easy catch-all handling.
    """
    # bugfix-3.1: 优先 DB AI Provider 路径, 失败兜底回 yaml + dashscope env。
    db_model, db_kwargs = await _resolve_db_provider_kwargs(model)
    if db_model is not None:
        resolved_model = db_model
        # caller 显式 kwargs > DB > nothing
        merged = {**db_kwargs, **kwargs}
    else:
        resolved_model = model or get_default_model()
        merged = {**_dashscope_kwargs(), **kwargs}
        if not model:  # explicit override 已经在 dispatcher log 过
            logger.info(
                "[llm.dispatcher] fallback_yaml model=%s "
                "dashscope_kwargs=%s",
                resolved_model, "yes" if _dashscope_kwargs() else "no",
            )

    if enable_search:
        model_lower = resolved_model.lower()
        if "qwen" in model_lower:
            merged["enable_search"] = True
        elif "deepseek" in model_lower:
            merged["tools"] = [{"type": "web_search_preview"}]

    # bugfix-3.2.7: defensive guard — LiteLLM 要求 'provider/model' 格式。
    # 裸 model 名(无 '/')会直接 BadRequestError('LLM Provider NOT provided')。
    # 此处 warn 让真机走查一眼看到根因,不抢救 (让 LiteLLM 报真错保 trace 清晰)。
    if "/" not in resolved_model:
        logger.warning(
            "[llm.dispatcher] model=%r lacks LiteLLM provider prefix "
            "(expected 'provider/model'); LiteLLM will likely reject this call",
            resolved_model,
        )

    # bugfix-3.2.9: sanitize tools[*].function.name 防 DeepSeek/OpenAI 按严格 schema
    # 拒(``Invalid 'tools[N].function.name': string does not match pattern.``)。
    # Qwen/Anthropic 宽松接 sanitized name 也 OK,因此对所有 vendor 都跑。
    # 幂等:已合规 name 不变。caller (chat.py) 同时持有 reverse_map 做 dispatch
    # 反查;此处只是 defensive 二保 + 打 log。
    if "tools" in merged and merged["tools"]:
        san_tools, rev_map = sanitize_tools_for_llm(merged["tools"])
        if rev_map:
            sample = list(rev_map.items())[:3]
            logger.info(
                "[llm.dispatcher] sanitized %d tool name(s) (sample: %s)",
                len(rev_map), sample,
            )
        merged["tools"] = san_tools

    try:
        response = await acompletion(
            model=resolved_model,
            messages=messages,
            stream=stream,
            **merged,
        )
        return response
    except llm_exc.AuthenticationError as exc:
        raise LLMAuthError(resolved_model, exc) from exc
    except llm_exc.RateLimitError as exc:
        raise LLMRateLimitError(resolved_model, exc) from exc
    except llm_exc.ContextWindowExceededError as exc:
        raise LLMContextError(resolved_model, exc) from exc
    except (
        llm_exc.ServiceUnavailableError,
        llm_exc.APIConnectionError,
        llm_exc.BadGatewayError,
        llm_exc.InternalServerError,
        llm_exc.Timeout,
    ) as exc:
        raise LLMServiceError(resolved_model, exc) from exc
    except (llm_exc.BadRequestError, llm_exc.InvalidRequestError) as exc:
        raise LLMBadRequestError(resolved_model, exc) from exc
    except Exception as exc:
        logger.exception("Unexpected LLM error (model=%s)", resolved_model)
        raise LLMError(f"Unexpected error calling {resolved_model}: {exc}") from exc


async def stream_llm(
    messages: List[dict],
    model: Optional[str] = None,
    **kwargs: Any,
) -> AsyncGenerator[str, None]:
    """Stream text chunks from the LLM.

    Yields non-empty string deltas.  Swallows empty / None deltas silently.

    Usage::

        async for chunk in stream_llm(messages):
            print(chunk, end="", flush=True)

    Raises the same ``LLMError`` subclasses as ``call_llm``.
    """
    wrapper = await call_llm(messages, model=model, stream=True, **kwargs)
    async for chunk in wrapper:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------

class LLMError(RuntimeError):
    """Base class for all LLM client errors."""


class LLMAuthError(LLMError):
    """Invalid or missing API key."""
    def __init__(self, model: str, cause: Exception) -> None:
        super().__init__(f"Authentication failed for model '{model}': {cause}")


class LLMRateLimitError(LLMError):
    """Provider rate limit exceeded."""
    def __init__(self, model: str, cause: Exception) -> None:
        super().__init__(f"Rate limit exceeded for model '{model}': {cause}")


class LLMContextError(LLMError):
    """Input exceeds the model's context window."""
    def __init__(self, model: str, cause: Exception) -> None:
        super().__init__(f"Context window exceeded for model '{model}': {cause}")


class LLMServiceError(LLMError):
    """Provider is unavailable or the connection failed."""
    def __init__(self, model: str, cause: Exception) -> None:
        super().__init__(f"Service error for model '{model}': {cause}")


class LLMBadRequestError(LLMError):
    """Malformed request rejected by the provider."""
    def __init__(self, model: str, cause: Exception) -> None:
        super().__init__(f"Bad request to model '{model}': {cause}")
