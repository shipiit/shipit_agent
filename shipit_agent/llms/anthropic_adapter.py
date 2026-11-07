"""Anthropic Messages API adapter, with prompt caching, thinking and server tools."""

from __future__ import annotations

import logging
from typing import Any

from shipit_agent.core.models import Message
from shipit_agent.llms.anthropic_messages import AnthropicMessagesMixin
from shipit_agent.llms.anthropic_request import (
    _EFFORTS,
    CONTEXT_MANAGEMENT_BETA,
    INTERLEAVED_THINKING_BETA,
    AnthropicRequestMixin,
)
from shipit_agent.llms.anthropic_response import AnthropicResponseMixin
from shipit_agent.llms.anthropic_stream import _pump_stream_events, _stopped_early
from shipit_agent.llms.base import LLMResponse
from shipit_agent.llms.claude_models import (
    NON_STREAMING_OUTPUT_CAP,
    STREAMING_OUTPUT_CAP,
    claude_model,
)

logger = logging.getLogger(__name__)

__all__ = [
    "AnthropicChatLLM",
    "CONTEXT_MANAGEMENT_BETA",
    "INTERLEAVED_THINKING_BETA",
    "_pump_stream_events",
]

#: Raised at the first call when the package is missing; the provider
#: factory also matches its leading "Install `anthropic`".
_MISSING_PACKAGE = (
    "Install `anthropic` to use AnthropicChatLLM: "
    "pip install anthropic (or shipit-agent[anthropic])."
)


class AnthropicChatLLM(
    AnthropicRequestMixin, AnthropicMessagesMixin, AnthropicResponseMixin
):
    """Native Anthropic Messages API adapter.

    Extracts tool_use blocks as ``ToolCall``s and ``thinking`` blocks as
    ``reasoning_content``, so the runtime can emit ``reasoning_started`` /
    ``reasoning_completed`` events just like the OpenAI and LiteLLM/Bedrock
    adapters do.
    """

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        max_tokens: int | None = None,
        *,
        thinking: str | dict[str, Any] | None = None,
        effort: str | None = None,
        thinking_budget_tokens: int | None = None,
        betas: list[str] | None = None,
        prompt_caching: bool = True,
        interleaved_thinking: bool = False,
        context_management: dict[str, Any] | None = None,
        documents: list[dict[str, Any]] | None = None,
        **client_kwargs: Any,
    ) -> None:
        self.model = model
        self.api_key = api_key
        self.facts = claude_model(model)
        #: ``None`` sends the model's limit, capped for a non-streaming call.
        self.max_tokens = max_tokens
        #: ``"adaptive"``, a full ``thinking`` dict, or ``None`` for the
        #: model's own default. Thinking depth is set with ``effort``.
        if thinking is not None and not (thinking == "adaptive" or isinstance(thinking, dict)):
            raise ValueError("thinking must be 'adaptive', a thinking dict, or None")
        self.thinking = thinking
        if effort is not None and effort not in _EFFORTS:
            raise ValueError(f"effort must be one of {sorted(_EFFORTS)} or None")
        self.effort = effort
        # The pre-adaptive way to think. Kept for older models; on models that
        # reject a budget it is sent as adaptive thinking instead of a 400.
        self.thinking_budget_tokens = thinking_budget_tokens
        #: Beta headers sent with every request, beside those features need.
        self.betas: list[str] = list(betas or [])
        # Interleaved thinking (#10): when on AND thinking is enabled, attach the
        # ``interleaved-thinking-2025-05-14`` beta header so the model can think
        # between tool calls. The adapter side of the round-trip is wired:
        # response ``thinking`` blocks (with their signatures) are surfaced in
        # ``LLMResponse.metadata["thinking_blocks"]`` and re-emitted first in
        # assistant messages whose metadata carries them. NOTE: completing the
        # round-trip across a multi-turn tool loop also requires the runtime to
        # copy that metadata onto the next assistant Message — runtime.py/agent.py
        # are owned elsewhere, so this is a degrade-gracefully passthrough until
        # they propagate ``thinking_blocks``.
        self.interleaved_thinking = interleaved_thinking
        # Server-side context editing (#9): an opt-in BetaContextManagementConfig
        # dict, e.g. {"edits": [{"type": "clear_tool_uses_20250919"}]}. When set,
        # forwarded as the ``context_management`` request param (with its beta
        # header) so Anthropic auto-clears old tool results server-side.
        self.context_management = context_management
        # Citations (#8): default documents attached to every ``complete`` call.
        # Each is a ``document`` content block (see ``llms.citations`` helpers).
        # A per-call ``documents=`` arg to ``complete`` overrides this.
        self.documents = documents
        # Prompt caching marks the stable prefix (tool definitions + system
        # prompt) with ``cache_control: {"type": "ephemeral"}`` breakpoints so
        # Anthropic bills repeated calls' cached prefix at ~10% of input and
        # serves them faster. Always safe on this native adapter (it only ever
        # talks to Anthropic), so it defaults on.
        self.prompt_caching = prompt_caching
        self.client_kwargs = client_kwargs
        # One SDK client for the adapter's life, so calls share its connection
        # pool. Rebuilt only if the ``anthropic`` module itself is replaced.
        self._client: Any = None
        self._client_module: Any = None

    def _client_for(self, anthropic: Any, timeout: float | None) -> Any:
        """The adapter's SDK client, with *timeout* applied to this call only."""
        if self._client is None or self._client_module is not anthropic:
            self._client = anthropic.Anthropic(api_key=self.api_key, **self.client_kwargs)
            self._client_module = anthropic
        if timeout is None:
            return self._client
        with_options = getattr(self._client, "with_options", None)
        if with_options is not None:
            return with_options(timeout=timeout)
        # An SDK without per-request options: a one-off client for this call.
        return anthropic.Anthropic(
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
        documents: list[dict[str, Any]] | None = None,
        text_delta_callback: Any = None,
        tool_input_callback: Any = None,
        timeout: float | None = None,
        require_tool_call: bool = False,
    ) -> LLMResponse:
        try:
            import anthropic
        except ImportError as exc:
            # Never answer with another provider instead: a missing package
            # once turned "Claude" into gpt-oss on Bedrock, silently.
            raise RuntimeError(_MISSING_PACKAGE) from exc

        client = self._client_for(anthropic, timeout)

        kwargs = self._build_request_kwargs(
            messages=messages,
            tools=tools,
            system_prompt=system_prompt,
            documents=documents,
        )
        tool_choice = self._tool_choice_for(require_tool_call=require_tool_call)
        if tools and tool_choice:
            kwargs["tool_choice"] = tool_choice

        # Route to the beta endpoint only when an opt-in feature needs a beta
        # header / beta-only param (``betas`` / ``context_management``). With
        # all flags off, ``betas`` is absent and the legacy GA call is used
        # unchanged.
        create = client.messages.create
        if "betas" in kwargs:
            try:
                create = client.beta.messages.create
            except AttributeError:
                # Very old SDK without a beta client: forward the betas as an
                # extra header so the feature still degrades gracefully.
                betas = kwargs.pop("betas")
                kwargs.setdefault("extra_headers", {})["anthropic-beta"] = ",".join(
                    betas
                )

        # Stream for live deltas, and whenever the output may be too large to
        # wait for in one response (the SDK refuses those without streaming).
        # The stream helper hands back the SAME final Message shape, so every
        # parsing branch below works unchanged.
        live = text_delta_callback is not None or tool_input_callback is not None
        if live and self.max_tokens is None:
            kwargs["max_tokens"] = min(
                self.facts.max_output_tokens, STREAMING_OUTPUT_CAP
            )
        streaming = live or kwargs["max_tokens"] > NON_STREAMING_OUTPUT_CAP
        endpoint = client.beta.messages if "betas" in kwargs else client.messages

        try:
            if streaming:
                stream_fn = getattr(endpoint, "stream", None)
                if stream_fn is not None:
                    with stream_fn(**kwargs) as _stream:
                        stopped = False
                        if tool_input_callback is not None:
                            stopped = _pump_stream_events(
                                _stream, text_delta_callback, tool_input_callback
                            )
                        elif text_delta_callback is not None:
                            # text_stream is simpler and well-trodden; only
                            # drop to raw events when someone wants tool input.
                            for _text in _stream.text_stream:
                                if _text and text_delta_callback(_text) is False:
                                    stopped = True
                                    break
                        # With no callback the stream is only for size; the
                        # final message below reads it to the end.
                        # A guard said stop. get_final_message() would read —
                        # and bill — the rest of the stream; take what was
                        # produced instead. Leaving this block closes it.
                        response = (
                            _stopped_early(_stream.current_message_snapshot)
                            if stopped
                            else _stream.get_final_message()
                        )
                else:  # very old SDK without stream helper
                    response = create(**kwargs)
            else:
                response = create(**kwargs)
        except Exception as exc:
            exc_name = type(exc).__name__
            status = getattr(exc, "status_code", None)
            if (
                status in (429, 500, 502, 503, 529)
                or "ServiceUnavailable" in exc_name
                or "RateLimitError" in exc_name
                or "InternalServerError" in exc_name
                or "OverloadedError" in exc_name
            ):
                raise ConnectionError(f"{exc_name}: {exc}") from exc
            raise

        return self._to_llm_response(response)

