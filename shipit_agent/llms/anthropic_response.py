"""Turning an Anthropic Messages response into shipit's ``LLMResponse``.

Text, thinking (kept whole for interleaved-thinking round trips), client
tool calls, server tool use and results, citations, and usage including the
prompt-cache counters.

Mixed into :class:`~shipit_agent.llms.anthropic_adapter.AnthropicChatLLM`.
"""

from __future__ import annotations

from typing import Any

from shipit_agent.core.models import ToolCall
from shipit_agent.llms import citations as _citations
from shipit_agent.llms import server_tools as _server_tools
from shipit_agent.llms.base import LLMResponse


class AnthropicResponseMixin:
    """Turning an Anthropic Messages response into shipit's ``LLMResponse``."""

    def _to_llm_response(self, response: Any) -> LLMResponse:
        """The ``LLMResponse`` for one Messages API *response*."""
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
                        id=str(getattr(block, "id", "") or ""),
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
                cache_read = getattr(response.usage, "cache_read_input_tokens", 0) or 0
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
        if getattr(response, "stop_reason", None):
            response_metadata["finish_reason"] = response.stop_reason
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
