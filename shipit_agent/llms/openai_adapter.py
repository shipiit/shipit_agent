"""OpenAI Chat Completions adapter, also used for OpenAI-compatible endpoints."""

from __future__ import annotations

from typing import Any

from shipit_agent.core.models import Message, ToolCall
from shipit_agent.llms.base import LLMResponse
from shipit_agent.llms.litellm_adapter import (
    _extract_reasoning,
    _parse_tool_arguments,
    _serialize_message,
)
from shipit_agent.llms.openai_common import (
    _NON_OPENAI_PARAMS,
    _OPENAI_CLIENT_PARAMS,
    _is_reasoning_model,
    _usage_dict,
)
from shipit_agent.llms.openai_streaming import OpenAIStreamingMixin


class OpenAIChatLLM(OpenAIStreamingMixin):
    """A model adapter for OpenAI and OpenAI-compatible chat completion APIs."""
    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        *,
        reasoning_effort: str | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        **client_kwargs: Any,
    ) -> None:
        self.model = model
        self.api_key = api_key
        # "low" | "medium" | "high" — only applied for reasoning-capable models
        self.reasoning_effort = reasoning_effort or (
            "medium" if _is_reasoning_model(model) else None
        )
        # Pass-through for OpenAI's `tool_choice` kwarg. Set this to "required"
        # to force the model to call at least one tool per turn. Useful with
        # gpt-4o-mini and other lazy models that otherwise return prose-only
        # answers even when tools are clearly needed.
        self.tool_choice = tool_choice
        # Completion controls belong on chat.completions.create(), not on the
        # OpenAI client constructor. Keeping them separate is especially
        # important for OpenAI-compatible endpoints such as Bedrock Mantle.
        self.max_tokens = max_tokens
        self.temperature = temperature
        # Split remaining kwargs: real client config stays for OpenAI(), extra
        # sampling params (top_p, penalties, seed, …) ride the completion call,
        # and non-OpenAI flags (drop_params, …) are dropped.
        self.client_kwargs: dict[str, Any] = {}
        self.extra_completion: dict[str, Any] = {}
        for _k, _v in client_kwargs.items():
            if _k in _OPENAI_CLIENT_PARAMS:
                self.client_kwargs[_k] = _v
            elif _k in _NON_OPENAI_PARAMS:
                continue
            else:
                self.extra_completion[_k] = _v

    def _client_for(self, client_class: Any, timeout: float | None) -> Any:
        """The adapter's SDK client, with *timeout* applied to this call only.

        One client for the adapter's life, so calls share its connection
        pool; rebuilt only if the SDK's client class itself is replaced.
        """
        if getattr(self, "_client_class", None) is not client_class:
            self._client = client_class(api_key=self.api_key, **self.client_kwargs)
            self._client_class = client_class
        if timeout is None:
            return self._client
        with_options = getattr(self._client, "with_options", None)
        if with_options is not None:
            return with_options(timeout=timeout)
        # An SDK without per-request options: a one-off client for this call.
        return client_class(
            api_key=self.api_key, **{**self.client_kwargs, "timeout": timeout}
        )

    def complete(
        self,
        *,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        system_prompt: str | None = None,
        metadata: dict[str, Any] | None = None,
        response_format: dict[str, Any] | None = None,
        text_delta_callback: Any = None,
        tool_input_callback: Any = None,
        timeout: float | None = None,
        require_tool_call: bool = False,
    ) -> LLMResponse:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("Install `openai` to use OpenAIChatLLM.") from exc

        client = self._client_for(OpenAI, timeout)
        from shipit_agent.llms.capabilities import capabilities_for

        caps = capabilities_for(self.model)
        # Runtime requests already contain their system message, but helper
        # calls (notably compaction) pass the instruction separately.
        if system_prompt and not any(m.role == "system" for m in messages):
            messages = [Message(role="system", content=system_prompt), *messages]
        payload_messages = [
            _serialize_message(
                m, include_reasoning=caps.reasoning_history == "replay"
            )
            for m in messages
        ]

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": payload_messages,
            "tools": tools or None,
        }
        # Completion controls are normalized at the adapter boundary. This is
        # the classic Agent path (the graph runtime has its own resolved
        # parameter object), so without this step the declarative capability
        # table was documentation rather than enforcement here.
        requested_params = dict(self.extra_completion)
        if self.reasoning_effort:
            requested_params["reasoning_effort"] = self.reasoning_effort
        if self.max_tokens is not None:
            requested_params["max_tokens"] = self.max_tokens
        if self.temperature is not None:
            requested_params["temperature"] = self.temperature

        from shipit_agent.llms.parameters import resolve_parameters

        resolved_params = resolve_parameters(self.model, requested_params)
        kwargs.update(resolved_params.wire)
        # One shared ladder decides tool_choice (see llms/tool_choice.py); only
        # send it when we have tools, since OpenAI rejects the parameter
        # otherwise. No `default_auto` here — this endpoint does not need the
        # explicit "auto" the mantle route does.
        from shipit_agent.llms.tool_choice import resolve_tool_choice

        choice = resolve_tool_choice(
            tools, require_tool_call=require_tool_call, configured=self.tool_choice
        )
        if choice is not None:
            kwargs["tool_choice"] = choice
        if tools:
            from shipit_agent.llms.capabilities import capabilities_for

            if not capabilities_for(self.model).supports_parallel_tool_calls:
                kwargs["parallel_tool_calls"] = False
        if response_format:
            kwargs["response_format"] = response_format

        if text_delta_callback is not None or tool_input_callback is not None:
            return self._complete_streaming(
                client, kwargs, text_delta_callback, tool_input_callback,
                timeout=timeout if timeout is not None else self.client_kwargs.get("timeout"),
            )

        try:
            response = client.chat.completions.create(**kwargs)
        except Exception as exc:
            exc_name = type(exc).__name__
            status = getattr(exc, "status_code", None)
            if (
                status in (429, 500, 502, 503, 529)
                or "ServiceUnavailable" in exc_name
                or "RateLimitError" in exc_name
                or "InternalServerError" in exc_name
            ):
                raise ConnectionError(f"{exc_name}: {exc}") from exc
            raise
        choice = response.choices[0].message

        tool_calls = []
        for call in choice.tool_calls or []:
            arguments = call.function.arguments or "{}"
            tool_calls.append(
                ToolCall(
                    name=call.function.name,
                    arguments=_parse_tool_arguments(arguments),
                    id=str(getattr(call, "id", "") or ""),
                )
            )

        reasoning_content = _extract_reasoning(choice)

        usage = _usage_dict(response.usage)

        return LLMResponse(
            content=choice.content or "",
            tool_calls=tool_calls,
            metadata={
                "model": self.model,
                "provider": "openai",
                "finish_reason": getattr(response.choices[0], "finish_reason", None),
                "prompt_tokens_include_cache": True,
                **(
                    {"reasoning_effort": self.reasoning_effort}
                    if self.reasoning_effort
                    else {}
                ),
            },
            reasoning_content=reasoning_content,
            usage=usage,
        )


def __getattr__(name: str) -> Any:
    # BedrockGemmaChatLLM subclasses OpenAIChatLLM, so it lives in its own
    # module; resolving it lazily keeps this old import path working.
    if name == "BedrockGemmaChatLLM":
        from shipit_agent.llms.bedrock_gemma import BedrockGemmaChatLLM

        return BedrockGemmaChatLLM
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
