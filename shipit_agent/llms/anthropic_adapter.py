from __future__ import annotations

import os
from typing import Any

from shipit_agent.llms import citations as _citations
from shipit_agent.llms import server_tools as _server_tools
from shipit_agent.llms.base import LLMResponse, coerce_message
from shipit_agent.models import Message, ToolCall

# Beta header for interleaved thinking (verified in
# anthropic.types.anthropic_beta_param, SDK 0.79.0).
INTERLEAVED_THINKING_BETA = "interleaved-thinking-2025-05-14"
# Beta header + request param for server-side context editing (verified:
# beta value "context-management-2025-06-27"; request param "context_management"
# exists only on client.beta.messages.create in 0.79.0).
CONTEXT_MANAGEMENT_BETA = "context-management-2025-06-27"


class AnthropicChatLLM:
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
        max_tokens: int = 4096,
        *,
        thinking_budget_tokens: int | None = None,
        prompt_caching: bool = True,
        interleaved_thinking: bool = False,
        context_management: dict[str, Any] | None = None,
        documents: list[dict[str, Any]] | None = None,
        **client_kwargs: Any,
    ) -> None:
        self.model = model
        self.api_key = api_key
        self.max_tokens = max_tokens
        # When set, Anthropic extended thinking is enabled for every call.
        # Example: AnthropicChatLLM("claude-opus-4-1", thinking_budget_tokens=2048)
        self.thinking_budget_tokens = thinking_budget_tokens
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

    def _convert_messages(self, messages: list[Message]) -> list[dict[str, Any]]:
        """Map shipit's Message model to Anthropic's user/assistant blocks.

        Accepts raw dict messages too (e.g. from ``ComputerUseAgent``) — their
        content is already in Anthropic block shape and passes through.
        """
        converted: list[dict[str, Any]] = []
        for raw_message in messages:
            message = coerce_message(raw_message)
            if message.role == "system":
                # System prompts are passed via the top-level `system` kwarg.
                continue
            if message.role == "tool":
                tool_call_id = (
                    message.metadata.get("tool_call_id") or message.name or ""
                )
                converted.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": tool_call_id,
                                "content": message.content or "",
                            }
                        ],
                    }
                )
                continue
            if message.role == "assistant" and message.metadata.get("tool_calls"):
                blocks: list[dict[str, Any]] = []
                # Interleaved thinking round-trip: re-emit any preserved
                # ``thinking`` blocks (with their signatures) BEFORE the text /
                # tool_use blocks, as the API requires when thinking is on.
                if self.interleaved_thinking:
                    for tb in message.metadata.get("thinking_blocks", []) or []:
                        if isinstance(tb, dict) and tb.get("type") in (
                            "thinking",
                            "redacted_thinking",
                        ):
                            blocks.append(tb)
                if message.content:
                    blocks.append({"type": "text", "text": message.content})
                for call in message.metadata["tool_calls"]:
                    blocks.append(
                        {
                            "type": "tool_use",
                            "id": call.get("id", ""),
                            "name": call["name"],
                            "input": call.get("arguments", {}),
                        }
                    )
                converted.append({"role": "assistant", "content": blocks})
                continue
            converted.append(
                {
                    "role": message.role,
                    "content": message.content or "",
                }
            )
        return converted

    def _fallback_to_bedrock(
        self,
        *,
        messages: list[Message],
        tools: list[dict[str, Any]] | None,
        system_prompt: str | None,
        metadata: dict[str, Any] | None,
        response_format: dict[str, Any] | None,
    ) -> LLMResponse:
        from shipit_agent.llms.litellm_adapter import BedrockChatLLM

        fallback = BedrockChatLLM(
            model=os.getenv("SHIPIT_BEDROCK_MODEL", "bedrock/openai.gpt-oss-120b-1:0")
        )
        response = fallback.complete(
            messages=messages,
            tools=tools,
            system_prompt=system_prompt,
            metadata=metadata,
            response_format=response_format,
        )
        response.metadata = {
            **dict(response.metadata),
            "provider": "bedrock",
            "fallback_from": "anthropic",
        }
        return response

    def _build_request_kwargs(
        self,
        *,
        messages: list[Message],
        tools: list[dict[str, Any]] | None,
        system_prompt: str | None,
        documents: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Build the kwargs passed to ``client.messages.create``.

        Split out from :meth:`complete` so the request payload — including
        prompt-caching breakpoints, server-tool declarations, interleaved-
        thinking / context-management betas, and citation documents — can be
        inspected directly in tests without mocking the Anthropic SDK.

        When any opt-in power feature requires a beta header, a ``betas`` key is
        added to the returned kwargs (and ``context_management`` when set). The
        caller (:meth:`complete`) routes such requests to ``client.beta``; with
        all flags off the kwargs are byte-identical to the legacy payload.

        When :attr:`prompt_caching` is on, two ``cache_control`` breakpoints
        are added to the stable request prefix:

        * one on the **last** tool definition — Anthropic caches the entire
          ``tools`` array up to and including the marked block, so a single
          breakpoint on the final tool covers every tool def, and
        * one on the (single) **system** prompt block — the string system
          prompt is promoted to the list-of-blocks form so the breakpoint has
          somewhere to live.
        """
        # Translate OpenAI-style tool schemas to Anthropic's flat shape.
        # Server-side tools (those already carrying a top-level ``type``) are
        # forwarded verbatim — the model runs them in Anthropic's sandbox, so
        # they must NOT be reshaped into client-tool declarations.
        anthropic_tools: list[dict[str, Any]] | None = None
        if tools:
            anthropic_tools = []
            for t in tools:
                if _server_tools.is_server_tool(t):
                    anthropic_tools.append(dict(t))
                    continue
                fn = t.get("function", t)
                anthropic_tools.append(
                    {
                        "name": fn["name"],
                        "description": fn.get("description", ""),
                        "input_schema": fn.get(
                            "parameters", {"type": "object", "properties": {}}
                        ),
                    }
                )

        system: Any = system_prompt or ""
        if self.prompt_caching:
            # System: convert the string prompt into a single cached text block.
            if system_prompt:
                system = [
                    {
                        "type": "text",
                        "text": system_prompt,
                        "cache_control": {"type": "ephemeral"},
                    }
                ]
            # Tools: mark the last tool so the whole array is cached.
            if anthropic_tools:
                anthropic_tools[-1] = {
                    **anthropic_tools[-1],
                    "cache_control": {"type": "ephemeral"},
                }

        converted_messages = self._convert_messages(messages)

        # Citations (#8): attach document content blocks to the LAST user
        # message so the model can ground its answer in them. Documents are
        # prepended to that message's content (before any text), promoting a
        # bare-string content to the list-of-blocks form as needed.
        docs = documents if documents is not None else self.documents
        if docs:
            self._attach_documents(converted_messages, docs)

        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": system,
            "messages": converted_messages,
        }
        if anthropic_tools:
            kwargs["tools"] = anthropic_tools
        if self.thinking_budget_tokens:
            kwargs["thinking"] = {
                "type": "enabled",
                "budget_tokens": self.thinking_budget_tokens,
            }

        # Assemble beta headers required by opt-in features. Empty list ->
        # the request stays on the GA endpoint and is identical to legacy.
        betas: list[str] = list(_server_tools.required_betas(tools))
        if (
            self.interleaved_thinking
            and self.thinking_budget_tokens
            and INTERLEAVED_THINKING_BETA not in betas
        ):
            betas.append(INTERLEAVED_THINKING_BETA)
        if self.context_management is not None:
            kwargs["context_management"] = self.context_management
            if CONTEXT_MANAGEMENT_BETA not in betas:
                betas.append(CONTEXT_MANAGEMENT_BETA)
        if betas:
            kwargs["betas"] = betas
        return kwargs

    @staticmethod
    def _attach_documents(
        messages: list[dict[str, Any]], documents: list[dict[str, Any]]
    ) -> None:
        """Prepend ``document`` content blocks to the last user message."""
        target = None
        for msg in reversed(messages):
            if msg.get("role") == "user":
                target = msg
                break
        if target is None:
            target = {"role": "user", "content": []}
            messages.append(target)
        content = target.get("content", "")
        if isinstance(content, str):
            content = [{"type": "text", "text": content}] if content else []
        target["content"] = [*documents, *content]

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
    ) -> LLMResponse:
        try:
            import anthropic
        except ImportError as exc:
            try:
                return self._fallback_to_bedrock(
                    messages=messages,
                    tools=tools,
                    system_prompt=system_prompt,
                    metadata=metadata,
                    response_format=response_format,
                )
            except Exception:
                raise RuntimeError(
                    "Install `anthropic` to use AnthropicChatLLM."
                ) from exc

        client = anthropic.Anthropic(api_key=self.api_key, **self.client_kwargs)

        kwargs = self._build_request_kwargs(
            messages=messages,
            tools=tools,
            system_prompt=system_prompt,
            documents=documents,
        )

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

        try:
            # Token streaming: the SDK's stream helper yields text deltas and
            # then hands back the SAME final Message shape, so every parsing
            # branch below (thinking, tool_use, server tools, citations) works
            # unchanged. Beta-endpoint calls keep the non-streaming path.
            if text_delta_callback is not None and "betas" not in kwargs:
                stream_fn = getattr(client.messages, "stream", None)
                if stream_fn is not None:
                    with stream_fn(**kwargs) as _stream:
                        for _text in _stream.text_stream:
                            if _text:
                                text_delta_callback(_text)
                        response = _stream.get_final_message()
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

        text_parts: list[str] = []
        thinking_parts: list[str] = []
        thinking_blocks: list[dict[str, Any]] = []
        tool_calls: list[ToolCall] = []
        server_tool_uses: list[dict[str, Any]] = []
        server_tool_results: list[dict[str, Any]] = []
        for block in response.content:
            btype = getattr(block, "type", "")
            if btype == "text":
                text_parts.append(getattr(block, "text", "") or "")
            elif btype in ("thinking", "redacted_thinking"):
                thinking_parts.append(getattr(block, "thinking", "") or "")
                # Preserve the full block (incl. its ``signature``) so it can be
                # round-tripped on multi-turn interleaved-thinking tool use.
                try:
                    thinking_blocks.append(self._block_to_dict(block))
                except Exception:
                    pass
            elif btype == "tool_use":
                # Client-side tool: the runtime executes it locally.
                tool_calls.append(
                    ToolCall(
                        name=getattr(block, "name", ""),
                        arguments=dict(getattr(block, "input", {}) or {}),
                    )
                )
            elif btype == _server_tools.SERVER_TOOL_USE_BLOCK:
                # Server-side tool invocation: Anthropic runs it — do NOT add to
                # ``tool_calls`` (the client loop must not try to execute it).
                try:
                    server_tool_uses.append(self._block_to_dict(block))
                except Exception:
                    pass
            elif btype in _server_tools.SERVER_TOOL_RESULT_BLOCKS:
                # Inline result of a server-side tool — keep as metadata.
                try:
                    server_tool_results.append(self._block_to_dict(block))
                except Exception:
                    pass

        # Citations (#8): pull citation locations off the response text blocks.
        try:
            response_citations = _citations.extract_citations(response.content)
        except Exception:
            response_citations = []

        usage: dict[str, int] = {}
        if hasattr(response, "usage") and response.usage:
            usage = {
                "prompt_tokens": getattr(response.usage, "input_tokens", 0) or 0,
                "completion_tokens": getattr(response.usage, "output_tokens", 0) or 0,
            }
            usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]
            # Prompt-caching usage. These keys match exactly what
            # CostTracker.as_hooks() looks for, so cache reads bill at the
            # cheaper rate automatically. Wrapped defensively: older SDKs
            # simply won't have these attributes (getattr -> 0).
            try:
                cache_read = (
                    getattr(response.usage, "cache_read_input_tokens", 0) or 0
                )
                cache_creation = (
                    getattr(response.usage, "cache_creation_input_tokens", 0) or 0
                )
                if cache_read:
                    usage["cache_read_input_tokens"] = cache_read
                if cache_creation:
                    usage["cache_creation_input_tokens"] = cache_creation
            except Exception:
                pass

        response_metadata: dict[str, Any] = {
            "model": self.model,
            "provider": "anthropic",
        }
        if self.thinking_budget_tokens:
            response_metadata["thinking_budget_tokens"] = self.thinking_budget_tokens
        # Only surface power-feature metadata when present, so flags-off
        # responses carry exactly the legacy metadata keys.
        if response_citations:
            response_metadata["citations"] = response_citations
        if server_tool_uses:
            response_metadata["server_tool_use"] = server_tool_uses
        if server_tool_results:
            response_metadata["server_tool_results"] = server_tool_results
        if self.interleaved_thinking and thinking_blocks:
            response_metadata["thinking_blocks"] = thinking_blocks

        return LLMResponse(
            content="".join(text_parts),
            tool_calls=tool_calls,
            metadata=response_metadata,
            reasoning_content=("\n".join(thinking_parts) if thinking_parts else None),
            usage=usage,
        )

    @staticmethod
    def _block_to_dict(block: Any) -> dict[str, Any]:
        """Best-effort conversion of an SDK response block to a plain dict.

        Handles pydantic models (``model_dump``), already-dict blocks, and the
        ``SimpleNamespace`` fakes used in tests.
        """
        if isinstance(block, dict):
            return dict(block)
        if hasattr(block, "model_dump"):
            return block.model_dump()
        return {k: v for k, v in vars(block).items() if not k.startswith("_")}
