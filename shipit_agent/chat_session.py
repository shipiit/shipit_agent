from __future__ import annotations

from dataclasses import dataclass, field
from contextlib import aclosing, closing
from typing import TYPE_CHECKING, Any, Callable

from shipit_agent.models import AgentEvent, AgentResult, Message
from shipit_agent.packets import (
    event_packet,
    sse_event_packet,
    sse_result_packet,
    websocket_event_packet,
    websocket_result_packet,
)
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
    _runtime_state: dict[str, Any] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.session_store is None:
            self.session_store = self.agent.session_store or InMemorySessionStore()

    def _session_agent(self) -> "Agent":
        agent = self.agent.clone(
            session_id=self.session_id,
            trace_id=self.trace_id or self.session_id,
            session_store=self.session_store,
        )
        # dataclasses.replace resets init=False fields. Keep compaction and
        # discovery state across sends, but never share it with another chat.
        agent._session_runtime_state = self._runtime_state
        return agent

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
        with closing(self._session_agent().stream(user_prompt)) as events:
            for event in events:
                self._emit_event(event)
                yield event

    async def asend(self, user_prompt: str) -> AgentResult:
        """Run a turn through the native async runtime with shared chat state."""
        result = await self._session_agent().arun(user_prompt)
        for event in result.events:
            self._emit_event(event)
        return result

    async def astream(self, user_prompt: str):
        """Stream a turn; closing this iterator also closes its producer."""
        async with aclosing(self._session_agent().astream(user_prompt)) as events:
            async for event in events:
                self._emit_event(event)
                yield event

    def stream_packets(self, user_prompt: str, *, transport: str = "websocket"):
        packet = sse_event_packet if transport == "sse" else websocket_event_packet
        with closing(self.stream(user_prompt)) as events:
            for event in events:
                yield packet(event)

    async def astream_packets(self, user_prompt: str, *, transport: str = "websocket"):
        packet = sse_event_packet if transport == "sse" else websocket_event_packet
        async with aclosing(self.astream(user_prompt)) as events:
            async for event in events:
                yield packet(event)

    def send_result_packet(
        self, user_prompt: str, *, transport: str = "websocket"
    ) -> Any:
        result = self.send(user_prompt)
        if transport == "sse":
            return sse_result_packet(result)
        return websocket_result_packet(result)

    def add_event_callback(self, callback: EventCallback) -> None:
        self.event_callbacks.append(callback)

    def add_packet_callback(self, callback: PacketCallback) -> None:
        self.packet_callbacks.append(callback)
