"""Adapters for providers reached through LiteLLM: Bedrock, Gemini, Vertex AI, Groq, Together, Ollama and more.
"""

from __future__ import annotations

from typing import Any

from shipit_agent.llms.litellm_base import LiteLLMChatLLM
from shipit_agent.llms.litellm_bedrock import (
    BedrockChatLLM,
    _litellm_supports_bedrock_mantle,
)
from shipit_agent.llms.litellm_messages import (
    _apply_prompt_caching,
    _bedrock_text_only_history,
    _is_anthropic_model,
    _normalize_content,
    _parse_tool_arguments,
    _plain_message_content,
    _serialize_message,
)
from shipit_agent.llms.litellm_streaming import _iter_with_deadline, _stream_completion
from shipit_agent.llms.litellm_usage import _extract_cache_usage, _extract_reasoning
from shipit_agent.llms.model_defaults import DEFAULT_MODELS

__all__ = [
    "LiteLLMChatLLM",
    "BedrockChatLLM",
    "GeminiChatLLM",
    "VertexAIChatLLM",
    "LiteLLMProxyChatLLM",
    "GroqChatLLM",
    "TogetherChatLLM",
    "OllamaChatLLM",
    "_parse_tool_arguments",
    "_normalize_content",
    "_serialize_message",
    "_plain_message_content",
    "_bedrock_text_only_history",
    "_is_anthropic_model",
    "_apply_prompt_caching",
    "_iter_with_deadline",
    "_stream_completion",
    "_extract_cache_usage",
    "_extract_reasoning",
    "_litellm_supports_bedrock_mantle",
]

class GeminiChatLLM(LiteLLMChatLLM):
    """Google Gemini models through the Gemini API."""
    def __init__(
        self, model: str = DEFAULT_MODELS["gemini"], **completion_kwargs: Any
    ) -> None:
        super().__init__(model=model, **completion_kwargs)


class VertexAIChatLLM(LiteLLMChatLLM):
    """Google Vertex AI adapter.

    Supports the full Vertex AI model catalog — Gemini, Claude-on-Vertex,
    Llama-on-Vertex, text-bison, etc. Accepts a service-account JSON file
    for authentication, plus the required ``project_id`` and ``location``.

    Example::

        llm = VertexAIChatLLM(
            model="vertex_ai/gemini-3.5-flash",
            service_account_file="/path/to/sa.json",
            project_id="my-gcp-project",
            location="us-central1",
        )

    If ``service_account_file`` is provided, the adapter sets
    ``GOOGLE_APPLICATION_CREDENTIALS`` in the process environment before the
    first ``complete()`` call, so LiteLLM can pick it up automatically.
    Alternatively, set ``GOOGLE_APPLICATION_CREDENTIALS`` in your shell or
    ``.env`` and omit ``service_account_file``.
    """

    def __init__(
        self,
        model: str = DEFAULT_MODELS["vertex"],
        *,
        service_account_file: str | None = None,
        project_id: str | None = None,
        location: str | None = None,
        **completion_kwargs: Any,
    ) -> None:
        import os as _os

        # Wire the service-account JSON file into the environment so LiteLLM
        # and google-auth can find it. Only sets if not already set.
        if service_account_file:
            _os.environ.setdefault(
                "GOOGLE_APPLICATION_CREDENTIALS", service_account_file
            )

        # Vertex AI requires project + location. LiteLLM reads these from
        # per-call kwargs OR from env vars. We inject into kwargs when
        # provided so they can't be silently dropped by env drift.
        if project_id:
            completion_kwargs.setdefault("vertex_project", project_id)
        if location:
            completion_kwargs.setdefault("vertex_location", location)

        self.service_account_file = service_account_file
        self.project_id = project_id
        self.location = location
        super().__init__(model=model, **completion_kwargs)


class LiteLLMProxyChatLLM(LiteLLMChatLLM):
    """Adapter for self-hosted LiteLLM proxy servers (``litellm --config``).

    Use this when you run your own LiteLLM proxy — typically as a centralized
    gateway for multiple teams — and want every shipit agent to point at it.
    The proxy handles credential management, rate limiting, routing, and
    cost tracking; shipit just talks OpenAI-compatible HTTP to it.

    Example::

        llm = LiteLLMProxyChatLLM(
            model="gpt-4o-mini",                        # whatever the proxy routes to
            api_base="https://litellm.my-company.internal",
            api_key="sk-proxy-token",
            custom_llm_provider="openai",               # the proxy speaks OpenAI format
        )

    Defaults to ``custom_llm_provider="openai"`` because the LiteLLM proxy
    always exposes an OpenAI-compatible API regardless of the upstream
    provider. Override only if you're pointing at a non-LiteLLM proxy.
    """

    def __init__(
        self,
        model: str,
        *,
        api_base: str | None = None,
        api_key: str | None = None,
        custom_llm_provider: str = "openai",
        **completion_kwargs: Any,
    ) -> None:
        if api_base:
            completion_kwargs.setdefault("api_base", api_base)
        if api_key:
            completion_kwargs.setdefault("api_key", api_key)
        completion_kwargs.setdefault("custom_llm_provider", custom_llm_provider)
        self.api_base = api_base
        self.api_key = api_key
        self.custom_llm_provider = custom_llm_provider
        super().__init__(model=model, **completion_kwargs)


class GroqChatLLM(LiteLLMChatLLM):
    """Models served by Groq."""
    def __init__(
        self, model: str = "groq/llama-3.3-70b-versatile", **completion_kwargs: Any
    ) -> None:
        super().__init__(model=model, **completion_kwargs)


class TogetherChatLLM(LiteLLMChatLLM):
    """Models served by Together AI."""
    def __init__(
        self,
        model: str = "together_ai/meta-llama/Llama-3.1-70B-Instruct-Turbo",
        **completion_kwargs: Any,
    ) -> None:
        super().__init__(model=model, **completion_kwargs)


class OllamaChatLLM(LiteLLMChatLLM):
    """Local models served by Ollama."""
    def __init__(
        self, model: str = "ollama/llama3.1", **completion_kwargs: Any
    ) -> None:
        super().__init__(model=model, **completion_kwargs)
