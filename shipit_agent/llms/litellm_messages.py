"""Serialising shipit messages for LiteLLM, and Anthropic-style prompt-cache markers."""

from __future__ import annotations

import json
from typing import Any


def _parse_tool_arguments(arguments: Any) -> dict[str, Any]:
    """Parse provider arguments without turning one bad call into a dead run."""
    if isinstance(arguments, dict):
        return arguments
    raw = arguments or "{}"
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError, ValueError):
        return {"_raw": str(raw)}
    return parsed if isinstance(parsed, dict) else {"_raw": str(raw)}


def _normalize_content(content: Any) -> Any:
    """Make multimodal content portable across providers.

    Callers like ``ComputerUseAgent`` build Anthropic-shape image blocks
    (``{"type": "image", "source": {"type": "base64", ...}}``). LiteLLM (and
    OpenAI) speak the ``image_url`` shape, so translate base64 image blocks to a
    ``data:`` URL. Plain-string content and already-``image_url`` blocks pass
    through unchanged.
    """
    if not isinstance(content, list):
        return content
    normalized: list[Any] = []
    for block in content:
        source = block.get("source") if isinstance(block, dict) else None
        block_type = block.get("type") if isinstance(block, dict) else None
        if block_type == "image" and isinstance(source, dict):
            if source.get("type") == "base64":
                url = (
                    f"data:{source.get('media_type', 'image/png')};"
                    f"base64,{source.get('data', '')}"
                )
                normalized.append({"type": "image_url", "image_url": {"url": url}})
                continue
            if source.get("type") == "url":
                # A URL-source Anthropic block forwarded untranslated is
                # rejected by every OpenAI-shaped endpoint.
                normalized.append(
                    {"type": "image_url", "image_url": {"url": source.get("url", "")}}
                )
                continue
        if block_type == "document" and isinstance(source, dict):
            # OpenAI-shaped endpoints have no document block; degrade to a
            # named placeholder rather than forwarding a rejected shape.
            name = source.get("url") or source.get("media_type") or "attached"
            normalized.append(
                {
                    "type": "text",
                    "text": f"[document attachment: {name} — "
                    "content not displayable on this provider]",
                }
            )
            continue
        if block_type in ("audio", "video"):
            normalized.append(
                {
                    "type": "text",
                    "text": f"[{block_type} attachment — "
                    "not supported on this provider]",
                }
            )
            continue
        normalized.append(block)
    return normalized


def _serialize_message(
    message: Any, *, include_reasoning: bool = False
) -> dict[str, Any]:
    # Accept raw dict messages (e.g. from ComputerUseAgent) as well as Message
    # objects — a dict is already in OpenAI message shape; just normalize media.
    if isinstance(message, dict):
        payload: dict[str, Any] = {
            "role": message.get("role", "user"),
            "content": _normalize_content(message.get("content", "")),
        }
        if message.get("name"):
            payload["name"] = message["name"]
        if message.get("tool_calls"):
            payload["tool_calls"] = message["tool_calls"]
        if message.get("tool_call_id"):
            payload["tool_call_id"] = message["tool_call_id"]
        return payload

    payload = {
        "role": message.role,
        "content": _normalize_content(message.content),
        **({"name": message.name} if message.name else {}),
    }
    typed_calls = getattr(message, "tool_calls", None) or []
    tool_calls = (
        [call.to_dict() for call in typed_calls]
        if typed_calls
        else message.metadata.get("tool_calls", [])
    )
    # A tool's own metadata is merged onto its message, so any tool can land
    # a value here. Only a list of records is meaningful; anything else is a
    # key collision and must not take the request down.
    if not isinstance(tool_calls, (list, tuple)):
        tool_calls = []
    if tool_calls:
        payload["tool_calls"] = [
            {
                "id": item.get("id", f"call_{index}"),
                "type": "function",
                "function": {
                    "name": item.get("name", ""),
                    "arguments": json.dumps(item.get("arguments", {}), sort_keys=True),
                },
            }
            for index, item in enumerate(tool_calls, start=1)
            if isinstance(item, dict)
        ]
    tool_call_id = getattr(message, "tool_call_id", None) or message.metadata.get(
        "tool_call_id"
    )
    if message.role == "tool" and tool_call_id:
        payload["tool_call_id"] = tool_call_id
    if include_reasoning and message.role == "assistant":
        reasoning = message.metadata.get("reasoning_content")
        if reasoning:
            payload["reasoning_content"] = reasoning
    return payload


def _plain_message_content(content: Any) -> str:
    """Losslessly-enough flatten content blocks for a text-only fallback."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
            else:
                parts.append(str(block))
        return "\n".join(parts)
    return str(content)


def _bedrock_text_only_history(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Remove structured tool blocks when Converse receives no tool config.

    Bedrock Converse rejects historical ``toolUse``/``toolResult`` blocks if
    the current request does not include ``toolConfig``. The final synthesis
    step intentionally sends no tools, so preserve the evidence as ordinary
    text while removing only the protocol-level structure. Mantle/Gemma uses
    the OpenAI endpoint and never enters this path.
    """
    converted: list[dict[str, Any]] = []
    for message in messages:
        role = message.get("role")
        calls = message.get("tool_calls") or []
        if role == "assistant" and calls:
            lines = [_plain_message_content(message.get("content"))]
            for call in calls:
                function = call.get("function", {}) if isinstance(call, dict) else {}
                lines.append(
                    "[Tool call completed] "
                    f"{function.get('name', 'unknown')} "
                    f"arguments={function.get('arguments', '{}')}"
                )
            converted.append(
                {
                    "role": "assistant",
                    "content": "\n".join(part for part in lines if part),
                }
            )
            continue
        if role == "tool":
            text = (
                "[Tool result] "
                f"call_id={message.get('tool_call_id', '')}\n"
                f"{_plain_message_content(message.get('content'))}"
            )
            # Consecutive tool results become one user turn. This preserves
            # the evidence and satisfies Converse's strict role alternation.
            if (
                converted
                and converted[-1].get("role") == "user"
                and str(converted[-1].get("content", "")).startswith("[Tool result]")
            ):
                converted[-1]["content"] += "\n\n" + text
            else:
                converted.append({"role": "user", "content": text})
            continue
        converted.append(message)
    return converted


def _is_anthropic_model(model: str) -> bool:
    """True for Anthropic-family models (direct, on Bedrock, or on Vertex).

    Only these accept Anthropic ``cache_control`` breakpoints, which LiteLLM
    forwards to the Messages API and translates to Bedrock ``cachePoint``
    blocks for ``bedrock/anthropic.*`` models. Any other provider would reject
    the unknown field, so caching is gated behind this predicate.
    """
    m = model.lower()
    return "anthropic" in m or "claude" in m


def _with_cache_control(block: dict[str, Any]) -> dict[str, Any]:
    """Return a shallow copy of ``block`` with an ephemeral cache breakpoint."""
    return {**block, "cache_control": {"type": "ephemeral"}}


def _apply_prompt_caching(
    payload_messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]] | None]:
    """Inject ``cache_control`` breakpoints on the system message + last tool.

    Returns new lists; the caller's ``tools`` / message objects are never
    mutated in place (they are reused across calls). The system message's
    string content is promoted to Anthropic's list-of-blocks form so the
    breakpoint has a home; LiteLLM forwards this verbatim to the Anthropic /
    Bedrock-Anthropic backends.
    """
    new_messages: list[dict[str, Any]] = []
    system_marked = False
    for msg in payload_messages:
        if msg.get("role") == "system" and not system_marked:
            content = msg.get("content")
            if isinstance(content, str) and content:
                new_messages.append(
                    {
                        **msg,
                        "content": [
                            {
                                "type": "text",
                                "text": content,
                                "cache_control": {"type": "ephemeral"},
                            }
                        ],
                    }
                )
                system_marked = True
                continue
            if isinstance(content, list) and content:
                marked = list(content)
                last = marked[-1]
                if isinstance(last, dict):
                    marked[-1] = _with_cache_control(last)
                    new_messages.append({**msg, "content": marked})
                    system_marked = True
                    continue
        new_messages.append(msg)

    new_tools = tools
    if tools:
        new_tools = list(tools)
        new_tools[-1] = _with_cache_control(new_tools[-1])

    # Third breakpoint: the last message, so the whole conversation prefix
    # is cached. Each step of an agent run extends the previous request;
    # without this marker the growing history is re-billed as uncached
    # input every iteration. String content is promoted to the block form
    # so the marker has a home.
    if new_messages:
        last_msg = new_messages[-1]
        if last_msg.get("role") != "system":
            content = last_msg.get("content")
            if isinstance(content, str) and content:
                new_messages[-1] = {
                    **last_msg,
                    "content": [
                        {
                            "type": "text",
                            "text": content,
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                }
            elif (
                isinstance(content, list) and content and isinstance(content[-1], dict)
            ):
                marked = list(content)
                marked[-1] = _with_cache_control(marked[-1])
                new_messages[-1] = {**last_msg, "content": marked}

    return new_messages, new_tools
