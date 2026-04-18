from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Iterable

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
from .openai_adapter import OpenAIChatLLM
from .simple import ShipitLLM, SimpleEchoLLM

SUPPORTED_PROVIDERS = (
    "shipit",
    "bedrock",
    "openai",
    "anthropic",
    "gemini",
    "vertex",
    "litellm",
    "groq",
    "together",
    "ollama",
)


def _discover_env_file() -> Path | None:
    start = Path.cwd().resolve()
    for candidate in (start, *start.parents):
        dotenv = candidate / ".env"
        if dotenv.exists():
            return dotenv
    return None


def load_env_file(path: str | Path | None = None) -> dict[str, str]:
    env_path = Path(path) if path else _discover_env_file()
    loaded: dict[str, str] = {}
    if env_path is None or not env_path.exists():
        return loaded

    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)
        loaded[key.strip()] = value
    return loaded


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


def _normalized_settings(settings: dict[str, Any] | None) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in (settings or {}).items():
        normalized[str(key)] = value
    return normalized


def _apply_settings_to_env(settings: dict[str, Any]) -> None:
    for name in (
        "AWS_REGION_NAME",
        "AWS_DEFAULT_REGION",
        "AWS_PROFILE",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "SHIPIT_VERTEX_CREDENTIALS_FILE",
        "VERTEXAI_PROJECT",
        "GOOGLE_CLOUD_PROJECT",
        "VERTEXAI_LOCATION",
        "VERTEX_LOCATION",
        "GOOGLE_CLOUD_LOCATION",
        "SHIPIT_LITELLM_MODEL",
        "SHIPIT_LITELLM_API_KEY",
        "SHIPIT_LITELLM_API_BASE",
        "SHIPIT_LITELLM_CUSTOM_PROVIDER",
        "GROQ_API_KEY",
        "TOGETHERAI_API_KEY",
        "TOGETHER_API_KEY",
        "SHIPIT_OPENAI_TOOL_CHOICE",
    ):
        value = settings.get(name)
        if value:
            os.environ[name] = str(value)


def build_llm_from_settings(
    settings: dict[str, Any] | None = None,
    *,
    provider: str | None = None,
    load_env: bool = True,
):
    if load_env:
        load_env_file()

    config = _normalized_settings(settings)
    _apply_settings_to_env(config)
    explicit_provider = provider is not None
    selected = (
        str(
            provider
            or config.get("provider")
            or config.get("llm_provider")
            or os.getenv("SHIPIT_LLM_PROVIDER", "bedrock")
        )
        .strip()
        .lower()
    )

    if selected in {"shipit", "echo"}:
        return ShipitLLM() if selected == "shipit" else SimpleEchoLLM()
    if selected == "bedrock":
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
    if selected == "openai":
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
                or os.getenv("SHIPIT_OPENAI_MODEL", "gpt-4o-mini")
            ),
            tool_choice=tool_choice,
        )
    if selected == "anthropic":
        _require_any(["ANTHROPIC_API_KEY"], provider="anthropic", settings=config)
        try:
            return AnthropicChatLLM(
                model=str(
                    config.get("model")
                    or config.get("SHIPIT_ANTHROPIC_MODEL")
                    or os.getenv("SHIPIT_ANTHROPIC_MODEL", "claude-3-5-sonnet-latest")
                )
            )
        except RuntimeError as exc:
            if explicit_provider or "Install `anthropic`" not in str(exc):
                raise
            return build_llm_from_settings(
                {"provider": "bedrock", **config},
                provider="bedrock",
                load_env=False,
            )
    if selected == "gemini":
        _require_any(
            ["GEMINI_API_KEY", "GOOGLE_API_KEY"], provider="gemini", settings=config
        )
        return GeminiChatLLM(
            model=str(
                config.get("model")
                or config.get("SHIPIT_GEMINI_MODEL")
                or os.getenv("SHIPIT_GEMINI_MODEL", "gemini/gemini-1.5-pro")
            )
        )
    if selected in {"vertex", "vertex_ai", "vertexai"}:
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
                or os.getenv("SHIPIT_VERTEX_MODEL", "vertex_ai/gemini-1.5-pro")
            ),
            service_account_file=credentials_file,
            project_id=project_id,
            location=location,
        )
    if selected in {"litellm", "litellm_proxy", "proxy"}:
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
    if selected == "groq":
        _require_any(["GROQ_API_KEY"], provider="groq", settings=config)
        return GroqChatLLM(
            model=str(
                config.get("model")
                or config.get("SHIPIT_GROQ_MODEL")
                or os.getenv("SHIPIT_GROQ_MODEL", "groq/llama-3.3-70b-versatile")
            )
        )
    if selected == "together":
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
    if selected == "ollama":
        return OllamaChatLLM(
            model=str(
                config.get("model")
                or config.get("SHIPIT_OLLAMA_MODEL")
                or os.getenv("SHIPIT_OLLAMA_MODEL", "ollama/llama3.1")
            )
        )

    raise RuntimeError(
        f"Unsupported SHIPIT_LLM_PROVIDER={selected!r}. Supported values: {', '.join(SUPPORTED_PROVIDERS)}"
    )


def build_llm_from_env(provider: str | None = None):
    return build_llm_from_settings(provider=provider)
