"""Building an Anthropic Messages request from shipit's messages and settings.

Message conversion (tool calls and results, images, preserved thinking),
prompt-cache breakpoints, citation documents, and the request fields that
depend on the model: ``max_tokens``, ``thinking``, ``output_config.effort``,
``tool_choice`` and the beta headers.

Mixed into :class:`~shipit_agent.llms.anthropic_adapter.AnthropicChatLLM`.
"""

from __future__ import annotations

import logging
from typing import Any

from shipit_agent.core.models import Message
from shipit_agent.llms import server_tools as _server_tools
from shipit_agent.llms.claude_models import (
    NON_STREAMING_OUTPUT_CAP,
)

logger = logging.getLogger("shipit_agent.llms.anthropic_adapter")

# Beta header for interleaved thinking (verified in
# anthropic.types.anthropic_beta_param, SDK 0.79.0).
INTERLEAVED_THINKING_BETA = "interleaved-thinking-2025-05-14"

#: ``output_config.effort`` levels the Messages API accepts.
_EFFORTS = frozenset({"low", "medium", "high", "xhigh", "max"})

# Beta header + request param for server-side context editing (verified:
# beta value "context-management-2025-06-27"; request param "context_management"
# exists only on client.beta.messages.create in 0.79.0).
CONTEXT_MANAGEMENT_BETA = "context-management-2025-06-27"


class AnthropicRequestMixin:
    """Building an Anthropic Messages request from shipit's messages and settings."""

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
        if self.prompt_caching and converted_messages:
            # Messages: mark the last content block so the whole conversation
            # prefix is cached. Each step's request extends the previous one,
            # so without this breakpoint a multi-turn agent re-pays the full
            # history as uncached input on every iteration — the growing part
            # of the prompt, and by far the largest by mid-run.
            self._mark_message_prefix_cached(converted_messages)

        # Citations (#8): attach document content blocks to the LAST user
        # message so the model can ground its answer in them. Documents are
        # prepended to that message's content (before any text), promoting a
        # bare-string content to the list-of-blocks form as needed.
        docs = documents if documents is not None else self.documents
        if docs:
            self._attach_documents(converted_messages, docs)

        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens
            or min(self.facts.max_output_tokens, NON_STREAMING_OUTPUT_CAP),
            "system": system,
            "messages": converted_messages,
        }
        if anthropic_tools:
            kwargs["tools"] = anthropic_tools
        thinking = self._thinking_param()
        if thinking is not None:
            kwargs["thinking"] = thinking
        if self.effort:
            kwargs["output_config"] = {"effort": self.effort}

        # Assemble beta headers required by opt-in features. Empty list ->
        # the request stays on the GA endpoint and is identical to legacy.
        betas: list[str] = list(_server_tools.required_betas(tools))
        betas += [b for b in getattr(self, "betas", []) if b not in betas]
        # Adaptive thinking interleaves on its own; the beta is for budgets.
        if (
            self.interleaved_thinking
            and (thinking or {}).get("type") == "enabled"
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

    def _thinking_param(self) -> dict[str, Any] | None:
        """The ``thinking`` request field for this model, or ``None`` to omit it."""
        if isinstance(self.thinking, dict):
            return dict(self.thinking)
        if self.thinking == "adaptive":
            return {"type": "adaptive"}
        if not self.thinking_budget_tokens:
            return None
        if self.facts.rejects_thinking_budget:
            logger.info(
                "%s rejects thinking budgets; sending adaptive thinking instead "
                "(set effort to control depth)",
                self.model,
            )
            return {"type": "adaptive"}
        return {"type": "enabled", "budget_tokens": self.thinking_budget_tokens}

    def _tool_choice_for(self, *, require_tool_call: bool) -> dict[str, Any] | None:
        """Force a tool call where the model allows it.

        Models that reject forced ``tool_choice`` are left on ``auto``; the
        loop's required-tool instruction and retry still apply.
        """
        if require_tool_call and self.facts.accepts_forced_tool_choice:
            return {"type": "any"}
        return None

