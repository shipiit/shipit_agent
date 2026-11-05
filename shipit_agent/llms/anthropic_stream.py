"""Reading an Anthropic stream: live text and tool-argument deltas, and stopping early."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from shipit_agent.llms import server_tools as _server_tools


def _pump_stream_events(stream: Any, on_text: Any, on_tool_input: Any) -> bool:
    """Forward text and tool-argument deltas from the raw event stream.

    The SDK's ``text_stream`` helper only yields text, so streaming a tool
    call's arguments as the model writes them means reading raw events:
    ``content_block_start`` names the tool, and each ``input_json_delta``
    carries the next fragment of its argument JSON.

    A failure here costs a preview, not the turn — the caller still fetches
    the final message afterwards. Returns True when a callback returned
    ``False`` (a runtime guard asking the generation to stop).
    """
    active: dict[int, tuple[str, str]] = {}
    for event in stream:
        etype = getattr(event, "type", "")
        if etype == "content_block_start":
            block = getattr(event, "content_block", None)
            if getattr(block, "type", "") == "tool_use":
                active[getattr(event, "index", -1)] = (
                    getattr(block, "id", "") or "",
                    getattr(block, "name", "") or "",
                )
        elif etype == "content_block_delta":
            delta = getattr(event, "delta", None)
            dtype = getattr(delta, "type", "")
            if dtype == "text_delta" and on_text is not None:
                text = getattr(delta, "text", "") or ""
                if text and on_text(text) is False:
                    return True
            elif dtype == "input_json_delta":
                found = active.get(getattr(event, "index", -1))
                if found is not None:
                    fragment = getattr(delta, "partial_json", "") or ""
                    if fragment:
                        try:
                            keep_going = on_tool_input(found[0], found[1], fragment)
                        except Exception:
                            keep_going = None
                        if keep_going is False:
                            return True
        elif etype == "content_block_stop":
            active.pop(getattr(event, "index", -1), None)
    return False


def _stopped_early(snapshot: Any) -> Any:
    """What a guard-stopped stream produced, minus any half-written tool call.

    A call cut off mid-argument must never run, so tool-use blocks are dropped
    and only the text so far is kept. There is no stop reason: the provider
    never finished.
    """
    blocks = [
        block
        for block in (getattr(snapshot, "content", None) or [])
        if getattr(block, "type", "")
        not in ("tool_use", _server_tools.SERVER_TOOL_USE_BLOCK)
    ]
    return SimpleNamespace(
        content=blocks, usage=getattr(snapshot, "usage", None), stop_reason=None
    )
