"""Building each provider's adapter without the provider catalog.

The catalog (``providers/catalog/<name>/``) is the normal path. It needs
PyYAML, from the ``[connectors]`` extra, so these builders are the
zero-dependency fallback, and they must produce what the catalog does.
"""

from __future__ import annotations

import os
from typing import Any, Callable, Iterable

from .anthropic_adapter import AnthropicChatLLM
from .litellm_adapter import (
    BedrockChatLLM,
    GeminiChatLLM,
    GroqChatLLM,
    LiteLLMChatLLM,
    OllamaChatLLM,
    TogetherChatLLM,
    VertexAIChatLLM,
)
from .model_defaults import DEFAULT_MODELS
from .openai_adapter import OpenAIChatLLM
from .simple import ShipitLLM, SimpleEchoLLM


def _require_any(
    names: Iterable[str], *, provider: str, settings: dict[str, Any]
) -> str:
    for name in names:
        value = settings.get(name) or os.getenv(name)
        if value:
            return str(value)
    joined = ", ".join(names)
    raise RuntimeError(
        f"Missing environment variable for {provider}. Set one of: {joined}"
    )


def _shipit(config: dict[str, Any]) -> Any:
    return ShipitLLM()


def _echo(config: dict[str, Any]) -> Any:
    return SimpleEchoLLM()


def _bedrock(config: dict[str, Any]) -> Any:
    region = (
        config.get("AWS_REGION_NAME")
        or config.get("AWS_DEFAULT_REGION")
        or os.getenv("AWS_REGION_NAME")
        or os.getenv("AWS_DEFAULT_REGION")
    )
    if not region and not (config.get("AWS_PROFILE") or os.getenv("AWS_PROFILE")):
        try:
            import boto3  # type: ignore

            session = boto3.session.Session()
            region = session.region_name
            if region:
                os.environ["AWS_REGION_NAME"] = str(region)
                os.environ.setdefault("AWS_DEFAULT_REGION", str(region))
        except Exception:
            region = None
        if not region:
            raise RuntimeError(
                "Bedrock requires AWS_REGION_NAME or AWS_DEFAULT_REGION, or an AWS_PROFILE "
                "configured locally (or a default region in ~/.aws/config)."
            )
    return BedrockChatLLM(
        model=str(
            config.get("model")
            or config.get("SHIPIT_BEDROCK_MODEL")
            or os.getenv("SHIPIT_BEDROCK_MODEL", "bedrock/openai.gpt-oss-120b-1:0")
        )
    )


def _openai(config: dict[str, Any]) -> Any:
    _require_any(["OPENAI_API_KEY"], provider="openai", settings=config)
    tool_choice = (
        config.get("tool_choice")
        or config.get("SHIPIT_OPENAI_TOOL_CHOICE")
        or os.getenv("SHIPIT_OPENAI_TOOL_CHOICE")
        or None
    )
    return OpenAIChatLLM(
        model=str(
            config.get("model")
            or config.get("SHIPIT_OPENAI_MODEL")
            or os.getenv("SHIPIT_OPENAI_MODEL", DEFAULT_MODELS["openai"])
        ),
        tool_choice=tool_choice,
    )


def _anthropic(config: dict[str, Any]) -> Any:
    """Raises ``RuntimeError("Install `anthropic` ...")`` when the package is missing;
    the factory decides whether that falls back to Bedrock."""
    _require_any(["ANTHROPIC_API_KEY"], provider="anthropic", settings=config)
    return AnthropicChatLLM(
        model=str(
            config.get("model")
            or config.get("SHIPIT_ANTHROPIC_MODEL")
            or os.getenv("SHIPIT_ANTHROPIC_MODEL", DEFAULT_MODELS["anthropic"])
        )
    )


def _gemini(config: dict[str, Any]) -> Any:
    _require_any(
        ["GEMINI_API_KEY", "GOOGLE_API_KEY"], provider="gemini", settings=config
    )
    return GeminiChatLLM(
        model=str(
            config.get("model")
            or config.get("SHIPIT_GEMINI_MODEL")
            or os.getenv("SHIPIT_GEMINI_MODEL", DEFAULT_MODELS["gemini"])
        )
    )


def _vertex(config: dict[str, Any]) -> Any:
    _require_any(
        ["GOOGLE_APPLICATION_CREDENTIALS", "SHIPIT_VERTEX_CREDENTIALS_FILE"],
        provider="vertex",
        settings=config,
    )
    credentials_file = str(
        config.get("service_account_file")
        or config.get("SHIPIT_VERTEX_CREDENTIALS_FILE")
        or config.get("GOOGLE_APPLICATION_CREDENTIALS")
        or os.getenv("SHIPIT_VERTEX_CREDENTIALS_FILE")
        or os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    )
    project_id = str(
        config.get("project_id")
        or config.get("VERTEXAI_PROJECT")
        or config.get("GOOGLE_CLOUD_PROJECT")
        or os.getenv("VERTEXAI_PROJECT")
        or os.getenv("GOOGLE_CLOUD_PROJECT")
    )
    location = str(
        config.get("location")
        or config.get("VERTEXAI_LOCATION")
        or config.get("VERTEX_LOCATION")
        or config.get("GOOGLE_CLOUD_LOCATION")
        or os.getenv("VERTEXAI_LOCATION")
        or os.getenv("VERTEX_LOCATION")
        or os.getenv("GOOGLE_CLOUD_LOCATION")
    )
    _require_any(
        ["VERTEXAI_PROJECT", "GOOGLE_CLOUD_PROJECT"],
        provider="vertex",
        settings=config,
    )
    _require_any(
        ["VERTEXAI_LOCATION", "VERTEX_LOCATION", "GOOGLE_CLOUD_LOCATION"],
        provider="vertex",
        settings=config,
    )
    return VertexAIChatLLM(
        model=str(
            config.get("model")
            or config.get("SHIPIT_VERTEX_MODEL")
            or os.getenv("SHIPIT_VERTEX_MODEL", DEFAULT_MODELS["vertex"])
        ),
        service_account_file=credentials_file,
        project_id=project_id,
        location=location,
    )


def _litellm(config: dict[str, Any]) -> Any:
    from .litellm_adapter import LiteLLMProxyChatLLM

    model = str(
        config.get("model")
        or config.get("SHIPIT_LITELLM_MODEL")
        or os.getenv("SHIPIT_LITELLM_MODEL")
        or ""
    )
    if not model:
        raise RuntimeError(
            "Missing environment variable for litellm. Set one of: SHIPIT_LITELLM_MODEL"
        )
    api_key = (
        config.get("api_key")
        or config.get("SHIPIT_LITELLM_API_KEY")
        or os.getenv("SHIPIT_LITELLM_API_KEY")
    )
    api_base = (
        config.get("api_base")
        or config.get("SHIPIT_LITELLM_API_BASE")
        or os.getenv("SHIPIT_LITELLM_API_BASE")
    )
    custom_provider = (
        config.get("custom_llm_provider")
        or config.get("SHIPIT_LITELLM_CUSTOM_PROVIDER")
        or os.getenv("SHIPIT_LITELLM_CUSTOM_PROVIDER")
    )
    if api_base:
        return LiteLLMProxyChatLLM(
            model=model,
            api_base=str(api_base),
            api_key=str(api_key) if api_key else None,
            custom_llm_provider=str(custom_provider or "openai"),
        )
    completion_kwargs: dict[str, Any] = {}
    if api_key:
        completion_kwargs["api_key"] = str(api_key)
    if custom_provider:
        completion_kwargs["custom_llm_provider"] = str(custom_provider)
    return LiteLLMChatLLM(model=model, **completion_kwargs)


def _groq(config: dict[str, Any]) -> Any:
    _require_any(["GROQ_API_KEY"], provider="groq", settings=config)
    return GroqChatLLM(
        model=str(
            config.get("model")
            or config.get("SHIPIT_GROQ_MODEL")
            or os.getenv("SHIPIT_GROQ_MODEL", "groq/llama-3.3-70b-versatile")
        )
    )


def _together(config: dict[str, Any]) -> Any:
    _require_any(
        ["TOGETHERAI_API_KEY", "TOGETHER_API_KEY"],
        provider="together",
        settings=config,
    )
    return TogetherChatLLM(
        model=str(
            config.get("model")
            or config.get("SHIPIT_TOGETHER_MODEL")
            or os.getenv(
                "SHIPIT_TOGETHER_MODEL",
                "together_ai/meta-llama/Llama-3.1-70B-Instruct-Turbo",
            )
        )
    )


def _ollama(config: dict[str, Any]) -> Any:
    return OllamaChatLLM(
        model=str(
            config.get("model")
            or config.get("SHIPIT_OLLAMA_MODEL")
            or os.getenv("SHIPIT_OLLAMA_MODEL", "ollama/llama3.1")
        )
    )


#: Every provider name the inline path accepts, aliases included.
INLINE_BUILDERS: dict[str, Callable[[dict[str, Any]], Any]] = {
    "shipit": _shipit,
    "echo": _echo,
    "bedrock": _bedrock,
    "openai": _openai,
    "anthropic": _anthropic,
    "gemini": _gemini,
    "vertex": _vertex,
    "vertex_ai": _vertex,
    "vertexai": _vertex,
    "litellm": _litellm,
    "litellm_proxy": _litellm,
    "proxy": _litellm,
    "groq": _groq,
    "together": _together,
    "ollama": _ollama,
}
