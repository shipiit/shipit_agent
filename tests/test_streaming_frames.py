"""Two streams — what a browser needs to survive losing its connection."""

from __future__ import annotations

import json

import pytest

from shipit_agent.models import AgentEvent
from shipit_agent.streaming import (
    STREAM_GENERATION,
    Durability,
    classify,
    frame,
    hello_frame,
    replay_from,
    sse,
    sse_stream,
)


def event(kind: str, **payload) -> AgentEvent:
    return AgentEvent(type=kind, message=f"{kind} happened", payload=payload)


class TestClassification:
    @pytest.mark.parametrize(
        "kind",
        [
            "run_started",
            "tool_called",
            "tool_completed",
            "tool_failed",
            "tool_denied",
            "action_queued",
            "sub_agent_event",
            "run_completed",
            "lockdown_engaged",
            "context_compacted",
        ],
    )
    def test_things_that_happened_are_canonical(self, kind) -> None:
        assert classify(kind) is Durability.CANONICAL

    @pytest.mark.parametrize(
        "kind",
        [
            "text_delta",
            "tool_input_delta",
            "tool_input_started",
            "usage_tick",
            "tool_output_started",
            "tool_output_delta",
            "step_started",
            "llm_retry",
            "tool_call_healed",
        ],
    )
    def test_in_flight_moments_are_provisional(self, kind) -> None:
        assert classify(kind) is Durability.PROVISIONAL

    def test_unknown_events_default_to_provisional(self) -> None:
        """Dropping a durable event costs a redraw; keeping a stale one lies."""
        assert classify("some_future_event") is Durability.PROVISIONAL

    def test_every_declared_event_type_is_classified(self) -> None:
        import typing

        from shipit_agent.models import EventType

        for kind in typing.get_args(EventType):
            assert classify(kind) in (Durability.CANONICAL, Durability.PROVISIONAL)


class TestGeneration:
    def test_it_is_stable_within_a_process(self) -> None:
        assert hello_frame().payload["generation"] == STREAM_GENERATION
        assert frame(event("run_started")).generation == STREAM_GENERATION

    def test_it_identifies_the_worker(self) -> None:
        # Two workers behind a load balancer must be distinguishable: a client
        # bounced between them has to treat that as a restart.
        import os

        assert STREAM_GENERATION.startswith(f"{os.getpid()}-")

    def test_hello_tells_a_client_to_discard(self) -> None:
        hello = hello_frame()
        assert hello.durability is Durability.CONTROL
        assert hello.payload["discard_provisional"] is True


class TestFraming:
    def test_a_frame_carries_everything_a_client_needs(self) -> None:
        rendered = frame(event("tool_called", tool="bash"), sequence=7).to_dict()
        assert rendered["type"] == "tool_called"
        assert rendered["durability"] == "canonical"
        assert rendered["sequence"] == 7
        assert rendered["payload"]["tool"] == "bash"
        assert rendered["generation"] == STREAM_GENERATION

    def test_unserializable_payloads_do_not_kill_the_stream(self) -> None:
        rendered = frame(event("tool_called", arguments={"fn": object()})).to_dict()
        assert json.dumps(rendered)

    def test_nested_structures_survive(self) -> None:
        rendered = frame(
            event("tool_called", arguments={"a": [1, {"b": object()}]})
        ).to_dict()
        assert json.dumps(rendered)


class TestSSE:
    def test_the_wire_format_is_valid_sse(self) -> None:
        text = sse(event("tool_called", tool="bash"), sequence=3)
        assert text.startswith("id: 3\n")
        assert "event: tool_called\n" in text
        assert text.endswith("\n\n")
        body = json.loads(text.split("data: ", 1)[1])
        assert body["payload"]["tool"] == "bash"

    def test_events_are_named_so_a_browser_can_listen_selectively(self) -> None:
        # addEventListener('tool_called', …) beats parsing every message.
        assert "event: tool_called" in sse(event("tool_called"))
        assert "event: text_delta" in sse(event("text_delta", chunk="hi"))

    def test_an_id_lets_the_browser_reconnect_by_itself(self) -> None:
        # Last-Event-ID is built into EventSource; giving it an id means no
        # extra client code for the common case.
        assert sse(event("tool_called"), sequence=42).startswith("id: 42")

    def test_a_whole_run_opens_with_hello_and_ends_with_done(self) -> None:
        frames = list(sse_stream([event("run_started"), event("run_completed")]))
        assert "event: stream_hello" in frames[0]
        assert frames[-1] == "event: done\ndata: [DONE]\n\n"

    def test_sequences_count_up(self) -> None:
        frames = list(sse_stream([event("a"), event("b"), event("c")]))
        ids = [f.split("\n")[0] for f in frames if f.startswith("id: ")]
        assert ids == ["id: 0", "id: 1", "id: 2", "id: 3"]

    def test_a_frame_can_be_passed_directly(self) -> None:
        assert "event: stream_hello" in sse(hello_frame())


class TestReplay:
    def test_only_what_was_missed_comes_back(self) -> None:
        events = [event("run_started"), event("tool_called"), event("run_completed")]
        assert [e.type for e in replay_from(events, 1)] == [
            "tool_called",
            "run_completed",
        ]

    def test_provisional_events_are_never_replayed(self) -> None:
        """Replaying a half-written file puts back exactly what we said to drop."""
        events = [
            event("tool_called"),
            event("tool_input_delta", delta="def main():"),
            event("text_delta", chunk="thinking"),
            event("tool_completed"),
        ]
        assert [e.type for e in replay_from(events, 0)] == [
            "tool_called",
            "tool_completed",
        ]

    def test_replaying_from_the_end_yields_nothing(self) -> None:
        events = [event("run_started"), event("run_completed")]
        assert list(replay_from(events, 2)) == []


class TestServerIntegration:
    """The endpoint end to end, on a real socket."""

    @staticmethod
    def _serve(agent_output="done"):
        """Start a server on an ephemeral port; yield (port, stop)."""
        import contextlib
        import socket
        import threading
        import time

        from shipit_agent import Agent
        from shipit_agent.llms.base import LLMResponse
        from shipit_agent.serve import AgentServer

        class L:
            model = "m"

            def complete(self, **kw):
                return LLMResponse(content=agent_output, usage={"total_tokens": 12})

        # Ask the OS for a free port rather than guessing one; a fixed port
        # collides when the suite runs in parallel or twice in a row.
        with contextlib.closing(socket.socket()) as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]

        server = AgentServer(
            agent=Agent(llm=L(), auto_use_skills=False), model_name="test"
        )
        thread = threading.Thread(
            target=lambda: server.serve_forever(port=port), daemon=True
        )
        thread.start()
        for _ in range(100):
            try:
                with contextlib.closing(
                    socket.create_connection(("127.0.0.1", port), timeout=0.1)
                ):
                    break
            except OSError:
                time.sleep(0.02)
        return port, server.stop

    def test_health_exposes_the_generation(self) -> None:
        # So a client can detect a restart without opening a stream.
        import http.client

        port, stop = self._serve()
        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request("GET", "/health")
            body = json.loads(conn.getresponse().read())
        finally:
            stop()
        assert body["stream_generation"] == STREAM_GENERATION

    def test_the_sse_endpoint_streams_a_transcript(self) -> None:
        import http.client

        port, stop = self._serve()
        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            conn.request(
                "POST",
                "/v1/stream",
                body=json.dumps({"prompt": "hi"}),
                headers={"Content-Type": "application/json"},
            )
            response = conn.getresponse()
            headers = dict(response.headers)
            text = response.read().decode()
        finally:
            stop()

        assert headers["Content-Type"] == "text/event-stream"
        # Without this a proxy buffers the whole response and delivers it at
        # the end, which is the one thing a stream must not do.
        assert headers["X-Accel-Buffering"] == "no"
        assert "event: stream_hello" in text
        assert "event: run_started" in text
        assert "event: run_completed" in text
        assert text.rstrip().endswith("[DONE]")
        assert '"durability": "canonical"' in text

    def test_frames_carry_ids_so_the_browser_can_resume(self) -> None:
        import http.client

        port, stop = self._serve()
        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            conn.request(
                "POST",
                "/v1/stream",
                body=json.dumps({"prompt": "hi"}),
                headers={"Content-Type": "application/json"},
            )
            text = conn.getresponse().read().decode()
        finally:
            stop()
        assert "id: 1\n" in text

    def test_a_missing_prompt_is_a_400(self) -> None:
        import http.client

        port, stop = self._serve()
        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request(
                "POST",
                "/v1/stream",
                body="{}",
                headers={"Content-Type": "application/json"},
            )
            status = conn.getresponse().status
        finally:
            stop()
        assert status == 400


class TestAgentSurfaces:
    """The three ways to consume a run, all built on one event feed."""

    def _agent(self):
        from shipit_agent import Agent
        from shipit_agent.llms.base import LLMResponse
        from shipit_agent.models import ToolCall
        from shipit_agent.tools.base import ToolOutput

        class T:
            name = "read_file"
            description = "r"
            prompt_instructions = ""

            def schema(self):
                return {
                    "function": {
                        "name": "read_file",
                        "parameters": {"properties": {"path": {"type": "string"}}},
                    }
                }

            def run(self, context, **kwargs):
                return ToolOutput(text="contents")

        class L:
            model = "m"

            def __init__(self):
                self.n = 0

            def complete(
                self,
                *,
                messages,
                tools=None,
                system_prompt=None,
                metadata=None,
                text_delta_callback=None,
            ):
                script = [
                    ("", [("read_file", {"path": "auth.py"})]),
                    ("Login has no MFA.", []),
                ]
                step = script[self.n] if self.n < len(script) else ("", [])
                self.n += 1
                if step[0] and text_delta_callback:
                    text_delta_callback(step[0])
                return LLMResponse(
                    content=step[0],
                    tool_calls=[ToolCall(name=n, arguments=a) for n, a in step[1]],
                    usage={"total_tokens": 900},
                )

        return Agent(llm=L(), tools=[T()], auto_use_skills=False, max_iterations=3)

    def test_stream_yields_raw_events(self) -> None:
        kinds = [e.type for e in self._agent().stream("go")]
        assert "tool_called" in kinds and "run_completed" in kinds

    def test_narrate_yields_settled_transcript_rows(self) -> None:
        rows = list(self._agent().narrate("go"))
        assert [type(r).__name__ for r in rows] == ["WorkRow", "ProseRow"]
        assert rows[0].group.label == "Read auth.py"
        assert rows[1].text == "Login has no MFA."

    def test_narrate_flushes_the_tail(self) -> None:
        # A run ending on prose must still yield it.
        assert any(type(r).__name__ == "ProseRow" for r in self._agent().narrate("go"))

    def test_stream_sse_is_wire_ready(self) -> None:
        chunks = list(self._agent().stream_sse("go"))
        assert "event: stream_hello" in chunks[0]
        assert chunks[-1] == "event: done\ndata: [DONE]\n\n"
        assert all(c.endswith("\n\n") for c in chunks)

    def test_sse_frames_are_parseable_json(self) -> None:
        for chunk in self._agent().stream_sse("go"):
            if "data: [DONE]" in chunk:
                continue
            body = json.loads(chunk.split("data: ", 1)[1])
            assert body["type"] and body["durability"]

    def test_all_three_see_the_same_run(self) -> None:
        raw = [e.type for e in self._agent().stream("go")]
        sse_types = [
            json.loads(c.split("data: ", 1)[1])["type"]
            for c in self._agent().stream_sse("go")
            if "[DONE]" not in c
        ]
        # SSE adds the hello frame; otherwise identical, in order.
        assert sse_types[0] == "stream_hello"
        assert sse_types[1:] == raw
