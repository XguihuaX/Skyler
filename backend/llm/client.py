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

logger = logging.getLogger(__name__)


def _dashscope_kwargs() -> dict:
    """Return api_base/api_key kwargs when DashScope is configured."""
    if settings.dashscope_base_url and settings.dashscope_api_key:
        return {
            "api_base": settings.dashscope_base_url,
            "api_key":  settings.dashscope_api_key,
        }
    return {}


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
    resolved_model = model or get_default_model()
    merged = {**_dashscope_kwargs(), **kwargs}

    if enable_search:
        model_lower = resolved_model.lower()
        if "qwen" in model_lower:
            merged["enable_search"] = True
        elif "deepseek" in model_lower:
            merged["tools"] = [{"type": "web_search_preview"}]

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
