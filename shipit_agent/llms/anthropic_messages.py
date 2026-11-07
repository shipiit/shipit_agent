"""Converting shipit messages to Anthropic's: tool calls and results, images,
preserved thinking, prompt-cache breakpoints and citation documents.

Mixed into :class:`~shipit_agent.llms.anthropic_adapter.AnthropicChatLLM`.
"""

from __future__ import annotations

from typing import Any

from shipit_agent.core.models import Message
from shipit_agent.llms.base import coerce_message


class AnthropicMessagesMixin:
    """Converting shipit messages to Anthropic's, with cache breakpoints and documents."""

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
                    getattr(message, "tool_call_id", None)
                    or message.metadata.get("tool_call_id")
                    or message.name
                    or ""
                )
                block = {
                    "type": "tool_result",
                    "tool_use_id": tool_call_id,
                    "content": message.content or "",
                }
                # Anthropic requires every result for one parallel assistant
                # turn in a single following user message. Internal ShipIt
                # messages stay one-per-result for provider portability; batch
                # only contiguous result messages at this adapter boundary.
                previous_content = converted[-1].get("content") if converted else None
                if (
                    converted
                    and converted[-1].get("role") == "user"
                    and isinstance(previous_content, list)
                    and previous_content
                    and all(
                        isinstance(item, dict) and item.get("type") == "tool_result"
                        for item in previous_content
                    )
                ):
                    previous_content.append(block)
                else:
                    converted.append({"role": "user", "content": [block]})
                continue
            typed_calls = getattr(message, "tool_calls", None) or []
            legacy_calls = message.metadata.get("tool_calls") or []
            if message.role == "assistant" and (typed_calls or legacy_calls):
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
                calls = (
                    [call.to_dict() for call in typed_calls]
                    if typed_calls
                    else legacy_calls
                )
                for call in calls:
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
            if message.role == "user" and converted and converted[-1].get("role") == "user":
                # A user turn right after another (a task notification after
                # tool results) joins it: one message, the earlier part first.
                blocks = _as_blocks(converted[-1])
                if isinstance(message.content, list):  # already Anthropic blocks
                    blocks.extend(message.content)
                elif message.content:
                    blocks.append({"type": "text", "text": message.content})
                continue
            converted.append(
                {
                    "role": message.role,
                    "content": message.content or "",
                }
            )
        return converted

    @staticmethod
    def _mark_message_prefix_cached(messages: list[dict[str, Any]]) -> None:
        """Put a cache breakpoint on the last content block of the history.

        Anthropic allows 4 breakpoints per request; system and tools use two,
        this uses a third. Bare-string content is promoted to the block form
        so the marker has somewhere to sit. Best-effort by design: an odd
        message shape means no marker, never a failed request.
        """
        try:
            last = messages[-1]
            content = last.get("content")
            if isinstance(content, str):
                if not content:
                    return
                content = [{"type": "text", "text": content}]
                last["content"] = content
            if isinstance(content, list) and content and isinstance(content[-1], dict):
                block_type = content[-1].get("type")
                if block_type in ("text", "tool_result", "tool_use", "document"):
                    content[-1] = {
                        **content[-1],
                        "cache_control": {"type": "ephemeral"},
                    }
        except Exception:
            pass

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


def _as_blocks(message: dict[str, Any]) -> list[dict[str, Any]]:
    """The message's content as a block list, converting a bare string in place."""
    content = message.get("content")
    if not isinstance(content, list):
        content = [{"type": "text", "text": content}] if content else []
        message["content"] = content
    return content

