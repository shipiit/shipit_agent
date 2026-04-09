from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Callable

from shipit_agent.models import AgentEvent, AgentResult, Message
from shipit_agent.packets import event_packet, sse_event_packet, sse_result_packet, websocket_event_packet, websocket_result_packet
from shipit_agent.stores import InMemorySessionStore, SessionStore

if TYPE_CHECKING:
    from shipit_agent.agent import Agent


EventCallback = Callable[[AgentEvent], None]
PacketCallback = Callable[[dict[str, Any]], None]


@dataclass(slots=True)
class AgentChatSession:
    agent: "Agent"
    session_id: str
    trace_id: str | None = None
    session_store: SessionStore | None = None
    event_callbacks: list[EventCallback] = field(default_factory=list)
    packet_callbacks: list[PacketCallback] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.session_store is None:
            self.session_store = self.agent.session_store or InMemorySessionStore()

    def _session_agent(self) -> "Agent":
        return replace(
            self.agent,
            session_id=self.session_id,
            trace_id=self.trace_id or self.session_id,
            session_store=self.session_store,
        )

    def _emit_event(self, event: AgentEvent) -> None:
        for callback in self.event_callbacks:
            callback(event)
        packet = event_packet(event)
        for callback in self.packet_callbacks:
            callback(packet)

    def history(self) -> list[Message]:
        session_store = self.session_store
        if session_store is None:
            return list(self.agent.history)
        record = session_store.load(self.session_id)
        return list(record.messages) if record else list(self.agent.history)

    def send(self, user_prompt: str) -> AgentResult:
        result = self._session_agent().run(user_prompt)
        for event in result.events:
            self._emit_event(event)
        return result

    def stream(self, user_prompt: str):
        for event in self._session_agent().stream(user_prompt):
            self._emit_event(event)
            yield event

    def stream_packets(self, user_prompt: str, *, transport: str = "websocket"):
        if transport == "sse":
            for event in self.stream(user_prompt):
                yield sse_event_packet(event)
            return
        for event in self.stream(user_prompt):
            yield websocket_event_packet(event)

    def send_result_packet(self, user_prompt: str, *, transport: str = "websocket") -> Any:
        result = self.send(user_prompt)
        if transport == "sse":
            return sse_result_packet(result)
        return websocket_result_packet(result)

    def add_event_callback(self, callback: EventCallback) -> None:
        self.event_callbacks.append(callback)

    def add_packet_callback(self, callback: PacketCallback) -> None:
        self.packet_callbacks.append(callback)
