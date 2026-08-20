"""A typed live stream of what the agent is doing, tool output included.

The runtime already emits fine-grained events — text deltas, tool input deltas,
tool output chunks. What a caller building a UI, an SSE endpoint or a CLI wants
is not that raw firehose but a small set of typed packets with the incidental
differences smoothed out:

* text and tool output arrive as **deltas that can be concatenated blindly**,
  with the buffering variants folded in so a consumer never has to know whether
  a tool streamed or returned whole;
* every packet carries the **tool call id**, so parallel tool calls can be
  rendered as separate live panes instead of interleaved text;
* the stream ends **exactly once**, with either a final answer or an error, so a
  consumer's loop has one clear termination.

This is a translation layer, not a second event system: it consumes the existing
``AgentEvent`` stream and yields packets. Anything it does not recognise passes
through as a ``PacketKind.EVENT`` so a new event type is visible immediately
rather than silently dropped.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Iterable, Iterator, Mapping

__all__ = ["PacketKind", "Packet", "to_packets", "to_packets_async", "PacketAccumulator"]


class PacketKind(str, Enum):
    """The small vocabulary a consumer actually needs."""

    RUN_STARTED = "run_started"
    TEXT = "text"                    # assistant prose delta
    REASONING = "reasoning"          # thinking delta, when the model exposes it
    TOOL_STARTED = "tool_started"
    TOOL_INPUT = "tool_input"        # streamed arguments delta
    TOOL_OUTPUT = "tool_output"      # live tool result delta
    TOOL_FINISHED = "tool_finished"
    TOOL_FAILED = "tool_failed"
    SKILL_LOADED = "skill_loaded"
    MCP_ATTACHED = "mcp_attached"
    TOOLS_DISCOVERED = "tools_discovered"
    COMPACTED = "compacted"
    USAGE = "usage"
    EVENT = "event"                  # anything unrecognised, passed through
    FINAL = "final"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class Packet:
    """One item of the live stream."""

    kind: PacketKind
    text: str = ""
    tool: str = ""
    tool_call_id: str = ""
    data: Mapping[str, Any] = field(default_factory=dict)

    @property
    def is_terminal(self) -> bool:
        return self.kind in (PacketKind.FINAL, PacketKind.ERROR)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"kind": self.kind.value}
        if self.text:
            payload["text"] = self.text
        if self.tool:
            payload["tool"] = self.tool
        if self.tool_call_id:
            payload["tool_call_id"] = self.tool_call_id
        if self.data:
            payload["data"] = dict(self.data)
        return payload


#: Event type → packet kind, for the events that map one-to-one.
_DIRECT: dict[str, PacketKind] = {
    "run_started": PacketKind.RUN_STARTED,
    "text_delta": PacketKind.TEXT,
    "tool_called": PacketKind.TOOL_STARTED,
    "tool_input_started": PacketKind.TOOL_STARTED,
    "tool_input_delta": PacketKind.TOOL_INPUT,
    "tool_output_delta": PacketKind.TOOL_OUTPUT,
    "tool_output_started": PacketKind.TOOL_OUTPUT,
    "tool_completed": PacketKind.TOOL_FINISHED,
    "tool_failed": PacketKind.TOOL_FAILED,
    "tool_denied": PacketKind.TOOL_FAILED,
    "tool_arguments_rejected": PacketKind.TOOL_FAILED,
    "reasoning_started": PacketKind.REASONING,
    "skills_selected": PacketKind.SKILL_LOADED,
    "skill_loaded": PacketKind.SKILL_LOADED,
    "mcp_attached": PacketKind.MCP_ATTACHED,
    "tools_discovered": PacketKind.TOOLS_DISCOVERED,
    "tools_rebound": PacketKind.TOOLS_DISCOVERED,
    "subagent_started": PacketKind.EVENT,
    "subagent_event": PacketKind.EVENT,
    "subagent_completed": PacketKind.EVENT,
    "context_compacted": PacketKind.COMPACTED,
    "usage_tick": PacketKind.USAGE,
    "run_summary": PacketKind.USAGE,
    "final_answer": PacketKind.FINAL,
    "run_completed": PacketKind.FINAL,
    "run_failed": PacketKind.ERROR,
    "run_cancelled": PacketKind.ERROR,
}

#: Payload keys that carry incremental text, in order of preference.
_TEXT_KEYS = ("chunk", "delta", "text", "content", "output", "summary")


def _payload(event: Any) -> Mapping[str, Any]:
    payload = getattr(event, "payload", None)
    return payload if isinstance(payload, Mapping) else {}


def _text_of(event: Any, payload: Mapping[str, Any]) -> str:
    for key in _TEXT_KEYS:
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    message = getattr(event, "message", "")
    return message if isinstance(message, str) else ""


def _packet(event: Any) -> Packet:
    kind = _DIRECT.get(str(getattr(event, "type", "")), PacketKind.EVENT)
    payload = _payload(event)
    return Packet(
        kind=kind,
        text=_text_of(event, payload),
        tool=str(payload.get("tool", "") or payload.get("name", "")),
        tool_call_id=str(payload.get("tool_call_id", "") or payload.get("id", "")),
        data=payload,
    )


def to_packets(events: Iterable[Any], *, drop_empty: bool = True) -> Iterator[Packet]:
    """Translate an ``AgentEvent`` stream into packets.

    Guarantees exactly one terminal packet. Empty text deltas are dropped by
    default — several event types carry an empty ``chunk`` as a heartbeat, and
    forwarding those makes a consumer's concatenation logic noisier for nothing.
    """
    final: Packet | None = None
    for event in events:
        packet = _packet(event)
        if (
            drop_empty
            and not packet.text
            and packet.kind in (PacketKind.TEXT, PacketKind.TOOL_OUTPUT, PacketKind.TOOL_INPUT)
        ):
            continue
        if packet.is_terminal:
            # Held back rather than forwarded: a run emits its answer and then
            # its accounting, and a consumer whose loop ends on the terminal
            # packet would never see the summary. Exactly one terminal packet
            # is emitted, and it is always last.
            if final is None or (not final.text and packet.text):
                final = packet
            continue
        yield packet
    yield final or Packet(kind=PacketKind.FINAL)


async def to_packets_async(
    events: AsyncIterator[Any], *, drop_empty: bool = True
) -> AsyncIterator[Packet]:
    """Async twin of :func:`to_packets`, with identical semantics."""
    final: Packet | None = None
    async for event in events:
        packet = _packet(event)
        if (
            drop_empty
            and not packet.text
            and packet.kind in (PacketKind.TEXT, PacketKind.TOOL_OUTPUT, PacketKind.TOOL_INPUT)
        ):
            continue
        if packet.is_terminal:
            if final is None or (not final.text and packet.text):
                final = packet
            continue
        yield packet
    yield final or Packet(kind=PacketKind.FINAL)


class PacketAccumulator:
    """Rebuilds the complete text and per-tool output from a packet stream.

    Useful for a UI that renders live and also needs the finished artefacts, and
    for tests that assert a stream reassembles to the same content the
    non-streaming path returns.
    """

    __slots__ = ("text", "reasoning", "tool_output", "errors")

    def __init__(self) -> None:
        self.text: list[str] = []
        self.reasoning: list[str] = []
        self.tool_output: dict[str, list[str]] = {}
        self.errors: list[str] = []

    def feed(self, packet: Packet) -> Packet:
        if packet.kind is PacketKind.TEXT:
            self.text.append(packet.text)
        elif packet.kind is PacketKind.REASONING:
            self.reasoning.append(packet.text)
        elif packet.kind is PacketKind.TOOL_OUTPUT:
            key = packet.tool_call_id or packet.tool or "?"
            self.tool_output.setdefault(key, []).append(packet.text)
        elif packet.kind in (PacketKind.TOOL_FAILED, PacketKind.ERROR):
            if packet.text:
                self.errors.append(packet.text)
        elif packet.kind is PacketKind.FINAL and packet.text:
            # FINAL is the canonical whole answer, not another delta. Replace
            # provisional chunks so consumers never render the answer twice.
            self.text[:] = [packet.text]
        return packet

    @property
    def answer(self) -> str:
        return "".join(self.text)

    def output_for(self, key: str) -> str:
        return "".join(self.tool_output.get(key, ()))
