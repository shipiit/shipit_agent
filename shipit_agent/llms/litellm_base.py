"""The LiteLLM adapter: any LiteLLM-supported provider through one class."""

from __future__ import annotations

from typing import Any, Callable

from shipit_agent.core.models import Message, ToolCall
from shipit_agent.llms.base import LLMResponse
from shipit_agent.llms.litellm_messages import (
    _apply_prompt_caching,
    _bedrock_text_only_history,
    _is_anthropic_model,
    _parse_tool_arguments,
    _serialize_message,
)
from shipit_agent.llms.litellm_streaming import _stream_completion
from shipit_agent.llms.litellm_usage import _extract_cache_usage, _extract_reasoning


class LiteLLMChatLLM:
    """A model adapter that calls any LiteLLM-supported provider."""

    def __init__(
        self, model: str, *, prompt_caching: bool = True, **completion_kwargs: Any
    ) -> None:
        self.model = model
        # Forward Anthropic ``cache_control`` breakpoints through LiteLLM for
        # Anthropic-family models (incl. Bedrock/Vertex Claude). Gated per-call
        # on the model id so non-Anthropic providers never see the field.
        # Extracted as an explicit kwarg so it is NOT forwarded into
        # ``litellm.completion`` (which would reject the unknown argument).
        self.prompt_caching = prompt_caching
        self.completion_kwargs = completion_kwargs

    def complete(
        self,
        *,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        system_prompt: str | None = None,
        metadata: dict[str, Any] | None = None,
        response_format: dict[str, Any] | None = None,
        text_delta_callback: Callable[[str], bool | None] | None = None,
        tool_input_callback: Callable[[str, str, str], bool | None] | None = None,
        timeout: float | None = None,
        require_tool_call: bool = False,
    ) -> LLMResponse:
        """Run a chat completion.

        If ``text_delta_callback`` is provided, switches to streaming mode and
        invokes the callback synchronously for each text chunk as it arrives.
        Returns the same ``LLMResponse`` shape in both modes so callers don't
        branch — the runtime just opts in by passing the callback.
        """
        try:
            from litellm import completion
        except ImportError as exc:
            raise RuntimeError("Install `litellm` to use LiteLLMChatLLM.") from exc

        from shipit_agent.llms.capabilities import capabilities_for

        caps = capabilities_for(self.model)
        if system_prompt and not any(m.role == "system" for m in messages):
            messages = [Message(role="system", content=system_prompt), *messages]
        payload_messages = [
            _serialize_message(m, include_reasoning=caps.reasoning_history == "replay")
            for m in messages
        ]
        request_tools = tools or None
        # Bedrock Converse requires `toolConfig` whenever any historical
        # message contains structured tool blocks. A final/synthesis request
        # deliberately has no tools, so convert those old blocks to text at
        # the provider boundary. OpenAI-compatible Mantle/Gemma is delegated
        # before this adapter and is intentionally unaffected.
        if (
            self.model.lower().startswith("bedrock/")
            and not request_tools
            and any(
                message.get("role") == "tool" or message.get("tool_calls")
                for message in payload_messages
            )
        ):
            payload_messages = _bedrock_text_only_history(payload_messages)
        # Inline `$ref`/`$defs` and dialect-sanitize each tool's parameter schema
        # BEFORE it goes on the wire. Pydantic/FastMCP MCP servers emit `$defs` +
        # `$ref` for nested argument models; OpenAI tolerates it, but a strict
        # OpenAI-*compatible* validator like Bedrock Mantle often does not —
        # simple tools keep working, nested ones fail quietly, and the model
        # reads as stupid rather than blocked. Cached and never-raising.
        if request_tools:
            try:
                from shipit_agent.llms.capabilities import capabilities_for
                from shipit_agent.llms.schema_prep import prepare_tool_schema

                # `$ref` inlining is dialect-independent; the dialect only tunes
                # the sanitize step. Default to the strictest (openai_strict) so
                # Bedrock Mantle gets clean schemas even where the capability
                # row carries no dialect.
                _dialect = (
                    getattr(
                        capabilities_for(self.model), "schema_dialect", "openai_strict"
                    )
                    or "openai_strict"
                )
                request_tools = [
                    prepare_tool_schema(t, dialect=_dialect) for t in request_tools
                ]
            except Exception:  # noqa: BLE001 — schema prep must never break a call
                pass
        # Add prompt-caching breakpoints for Anthropic-family models. Guarded so
        # non-Anthropic providers never receive the unsupported field and
        # nothing crashes if message/tool shapes are unexpected.
        if self.prompt_caching and _is_anthropic_model(self.model):
            try:
                payload_messages, request_tools = _apply_prompt_caching(
                    payload_messages, request_tools
                )
            except Exception:
                # Defensive: never let caching break a real call.
                pass

        extra_kwargs = dict(self.completion_kwargs)
        # Per-model parameter hygiene: drop params this model rejects (Gemma on
        # Mantle takes temperature/top_p only — top_k, penalties, logprobs,
        # thinking_budget all 400) and fill AWS-recommended defaults the caller
        # left unset (Gemma: temperature=1.0, top_p=0.95). Unknown models get a
        # permissive default that strips/fills nothing.
        try:
            from shipit_agent.llms.capabilities import (
                apply_recommended_params,
                sanitize_params,
            )

            accepted, _dropped = sanitize_params(self.model, extra_kwargs)
            extra_kwargs = apply_recommended_params(self.model, accepted)
        except Exception:  # noqa: BLE001 — param hygiene must never break a call
            pass
        # Host params are instructions to shipit's own compactor/loop, not fields
        # any provider knows — forwarding one is a 400 naming a parameter never
        # aimed at the model. Strip them before the wire.
        for _host in (
            "max_context_tokens",
            "file_token_limit",
            "fileTokenLimit",
            "max_iterations",
            "max_tool_output_chars",
            "context_window_tokens",
        ):
            extra_kwargs.pop(_host, None)
        if response_format:
            extra_kwargs["response_format"] = response_format
        if timeout is not None:
            # LiteLLM accepts a per-call `timeout` and forwards it to every
            # provider it wraps; the per-request value wins.
            extra_kwargs["timeout"] = timeout
        # One shared ladder decides tool_choice (see llms/tool_choice.py). When
        # tools are offered we always send a value: most providers assume
        # "auto", but some OpenAI-compatible endpoints — notably Bedrock's Gemma
        # (`bedrock-mantle`) route, per AWS's own examples — only engage function
        # calling reliably when `tool_choice` is present; without it the model
        # narrates the call as prose. A caller can still override via
        # ``completion_kwargs``.
        if "tool_choice" not in extra_kwargs:
            from shipit_agent.llms.tool_choice import resolve_tool_choice

            choice = resolve_tool_choice(
                request_tools,
                require_tool_call=require_tool_call,
                default_auto=True,
            )
            if choice is not None:
                extra_kwargs["tool_choice"] = choice
        if request_tools and "parallel_tool_calls" not in extra_kwargs:
            from shipit_agent.llms.capabilities import capabilities_for

            if not capabilities_for(self.model).supports_parallel_tool_calls:
                extra_kwargs["parallel_tool_calls"] = False

        # Strip parameters this model family is known to reject, rather than
        # letting the provider 400 mid-turn on a field the caller never set
        # deliberately (`temperature` usually arrives from a default). Blocks
        # nothing for an unmatched model. See llms/capabilities.py.
        extra_kwargs, _dropped = sanitize_params(self.model, extra_kwargs)

        if text_delta_callback is not None or tool_input_callback is not None:
            return _stream_completion(
                completion_fn=completion,
                model=self.model,
                payload_messages=payload_messages,
                tools=request_tools,
                extra_kwargs=extra_kwargs,
                text_delta_callback=text_delta_callback,
                tool_input_callback=tool_input_callback,
            )

        try:
            response = completion(
                model=self.model,
                messages=payload_messages,
                tools=request_tools,
                **extra_kwargs,
            )
        except Exception as exc:
            # Re-raise transient provider errors (503, 429, 500) as
            # ConnectionError so the runtime's RetryPolicy can catch them.
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
        message = response.choices[0].message
        tool_calls = []
        for call in getattr(message, "tool_calls", []) or []:
            arguments = call.function.arguments or "{}"
            tool_calls.append(
                ToolCall(
                    name=call.function.name,
                    arguments=_parse_tool_arguments(arguments),
                    id=str(getattr(call, "id", "") or ""),
                )
            )
        reasoning_content = _extract_reasoning(message)

        usage: dict[str, int] = {}
        if hasattr(response, "usage") and response.usage:
            u = response.usage
            usage = {
                "prompt_tokens": getattr(u, "prompt_tokens", 0) or 0,
                "completion_tokens": getattr(u, "completion_tokens", 0) or 0,
                "total_tokens": getattr(u, "total_tokens", 0) or 0,
            }
            usage.update(_extract_cache_usage(u))

        return LLMResponse(
            content=getattr(message, "content", "") or "",
            tool_calls=tool_calls,
            metadata={
                "model": self.model,
                "provider": "litellm",
                "prompt_tokens_include_cache": True,
                "finish_reason": getattr(response.choices[0], "finish_reason", None),
            },
            reasoning_content=reasoning_content,
            usage=usage,
        )
