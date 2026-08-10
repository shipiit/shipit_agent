from __future__ import annotations

import asyncio
import io
import threading
from typing import Any

import pytest

from shipit_agent import (
    Agent,
    AsyncAgentRuntime,
    FunctionTool,
    Guardrails,
    ToolOutput,
    ToolOutputChunk,
)
from shipit_agent.activity import StreamRenderer
from shipit_agent.llms import LLMResponse
from shipit_agent.mcp import MCPServer, MCPTool
from shipit_agent.models import ToolCall
from shipit_agent.registry import ToolRegistry
from shipit_agent.tool_runner import ToolRunner
from shipit_agent.tools import ToolContext


class _OneToolLLM:
    def __init__(self, tool_name: str) -> None:
        self.tool_name = tool_name
        self.called = False

    def complete(
        self,
        *,
        messages: Any,
        tools: Any = None,
        system_prompt: str | None = None,
        metadata: dict[str, Any] | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> LLMResponse:
        if not self.called:
            self.called = True
            return LLMResponse(
                content="",
                tool_calls=[ToolCall(name=self.tool_name, arguments={})],
            )
        return LLMResponse(content="finished")


class _TwoToolLLM(_OneToolLLM):
    def complete(self, **kwargs: Any) -> LLMResponse:
        if not self.called:
            self.called = True
            return LLMResponse(
                content="",
                tool_calls=[
                    ToolCall(name="left", arguments={}),
                    ToolCall(name="right", arguments={}),
                ],
            )
        return LLMResponse(content="finished")


def _streaming_tool(name: str = "report") -> FunctionTool:
    def report():
        yield ToolOutputChunk("alpha", {"page": 1})
        yield "-beta"
        yield ToolOutputChunk("-gamma", {"page": 3})

    return FunctionTool.from_callable(report, name=name)


def test_sync_stream_publishes_ordered_chunks_and_complete_result() -> None:
    agent = Agent(
        llm=_OneToolLLM("report"),
        tools=[_streaming_tool()],
        auto_use_skills=False,
    )

    events = list(agent.stream("build the report"))

    deltas = [event for event in events if event.type == "tool_output_delta"]
    assert [event.payload["chunk"] for event in deltas] == [
        "alpha",
        "-beta",
        "-gamma",
    ]
    assert [event.payload["sequence"] for event in deltas] == [1, 2, 3]
    assert {event.payload["call_id"] for event in deltas} == {"call_1_1"}
    completed = next(event for event in events if event.type == "tool_completed")
    assert completed.payload["output"] == "alpha-beta-gamma"


def test_non_streaming_tool_still_publishes_one_output_delta() -> None:
    tool = FunctionTool.from_callable(lambda: "ordinary", name="ordinary")
    agent = Agent(
        llm=_OneToolLLM("ordinary"),
        tools=[tool],
        auto_use_skills=False,
    )

    events = list(agent.stream("run it"))

    deltas = [event for event in events if event.type == "tool_output_delta"]
    assert [event.payload["chunk"] for event in deltas] == ["ordinary"]


def test_large_non_streaming_tool_output_is_published_in_bounded_deltas() -> None:
    content = "x" * 40_000
    tool = FunctionTool.from_callable(lambda: content, name="large")
    agent = Agent(
        llm=_OneToolLLM("large"),
        tools=[tool],
        auto_use_skills=False,
    )

    events = list(agent.stream("run it"))

    deltas = [event for event in events if event.type == "tool_output_delta"]
    assert "".join(event.payload["chunk"] for event in deltas) == content
    assert len(deltas) == 3
    assert max(len(event.payload["chunk"]) for event in deltas) <= 16_384
    completed = next(event for event in events if event.type == "tool_completed")
    assert completed.payload["output"] == content


def test_live_events_do_not_duplicate_heavy_canonical_metadata() -> None:
    class RichOutputTool:
        name = "rich"
        description = "Return a rich payload."
        prompt_instructions = "Use for testing."

        def schema(self):
            return {
                "type": "function",
                "function": {
                    "name": self.name,
                    "description": self.description,
                    "parameters": {"type": "object", "properties": {}},
                },
            }

        def run(self, context):
            return ToolOutput(
                text="result",
                metadata={
                    "server": "demo",
                    "raw_result": {"content": "x" * 10_000},
                    "content_blocks": [{"text": "x" * 10_000}],
                    "structured_content": {"rows": ["x" * 10_000]},
                },
            )

    agent = Agent(
        llm=_OneToolLLM("rich"), tools=[RichOutputTool()], auto_use_skills=False
    )

    events = list(agent.stream("run it"))

    delta = next(event for event in events if event.type == "tool_output_delta")
    assert delta.payload["chunk_metadata"] == {"server": "demo"}
    completed = next(event for event in events if event.type == "tool_completed")
    assert completed.payload["metadata"] == {"server": "demo"}
    assert completed.payload["output_chars"] == 6
    assert completed.payload["model_output_chars"] == 6
    assert completed.payload["model_output_reduced"] is False


def test_first_chunk_reaches_consumer_before_tool_finishes() -> None:
    release = threading.Event()

    def live():
        yield "first"
        assert release.wait(timeout=2), "consumer never received the first chunk"
        yield "second"

    agent = Agent(
        llm=_OneToolLLM("live"),
        tools=[FunctionTool.from_callable(live, name="live")],
        auto_use_skills=False,
    )

    chunks: list[str] = []
    for event in agent.stream("stream live"):
        if event.type == "tool_output_delta":
            chunks.append(event.payload["chunk"])
            if chunks == ["first"]:
                release.set()

    assert chunks == ["first", "second"]


def test_parallel_tool_streams_have_distinct_call_ids() -> None:
    def chunks(label: str):
        yield f"{label}-1"
        yield f"{label}-2"

    agent = Agent(
        llm=_TwoToolLLM("unused"),
        tools=[
            FunctionTool.from_callable(lambda: chunks("L"), name="left"),
            FunctionTool.from_callable(lambda: chunks("R"), name="right"),
        ],
        parallel_tool_execution=True,
        auto_use_skills=False,
    )

    events = list(agent.stream("run both"))
    by_call: dict[str, list[str]] = {}
    for event in events:
        if event.type == "tool_output_delta":
            by_call.setdefault(event.payload["call_id"], []).append(
                event.payload["chunk"]
            )

    assert by_call == {
        "call_1_1": ["L-1", "L-2"],
        "call_1_2": ["R-1", "R-2"],
    }


def test_runner_merges_chunk_metadata_and_rejects_invalid_chunks() -> None:
    runner = ToolRunner(ToolRegistry.build(tools=[_streaming_tool()]))
    result = runner.run_tool_call(
        ToolCall(name="report", arguments={}), ToolContext(prompt="run")
    )
    assert result.output == "alpha-beta-gamma"
    assert result.metadata == {
        "page": 3,
        "streamed": True,
        "stream_chunk_count": 3,
    }

    def invalid():
        yield object()

    invalid_runner = ToolRunner(
        ToolRegistry.build(tools=[FunctionTool.from_callable(invalid, name="invalid")])
    )
    with pytest.raises(TypeError, match="yielded object"):
        invalid_runner.run_tool_call(
            ToolCall(name="invalid", arguments={}), ToolContext(prompt="run")
        )


def test_runner_keeps_legacy_duck_typed_tool_output_compatibility() -> None:
    class LegacyTool:
        name = "legacy"
        description = "Legacy output tool"
        prompt_instructions = "Use for compatibility testing."

        def schema(self) -> dict[str, Any]:
            return {
                "type": "function",
                "function": {
                    "name": self.name,
                    "description": self.description,
                    "parameters": {"type": "object", "properties": {}},
                },
            }

        def run(self, context: ToolContext, **kwargs: Any) -> Any:
            return type(
                "LegacyOutput",
                (),
                {"text": "compatible", "metadata": {"legacy": True}},
            )()

    chunks: list[str] = []
    runner = ToolRunner(ToolRegistry.build(tools=[LegacyTool()]))
    result = runner.run_tool_call(
        ToolCall(name="legacy", arguments={}),
        ToolContext(prompt="run"),
        lambda chunk: chunks.append(chunk.text),
    )

    assert result.output == "compatible"
    assert result.metadata == {"legacy": True}
    assert chunks == ["compatible"]


def test_local_mcp_output_is_streamed_with_server_provenance() -> None:
    server = MCPServer(name="knowledge").register(
        MCPTool(
            name="lookup",
            description="Look up knowledge",
            handler=lambda **kwargs: "mcp-result",
        )
    )
    agent = Agent(
        llm=_OneToolLLM("lookup"),
        mcps=[server],
        auto_use_skills=False,
    )

    events = list(agent.stream("look it up"))

    delta = next(event for event in events if event.type == "tool_output_delta")
    assert delta.payload["chunk"] == "mcp-result"
    assert delta.payload["chunk_metadata"]["server"] == "knowledge"
    completed = next(event for event in events if event.type == "tool_completed")
    assert completed.payload["output"] == "mcp-result"


def test_async_stream_publishes_chunks_before_completion() -> None:
    runtime = AsyncAgentRuntime(
        llm=_OneToolLLM("report"),
        prompt="System",
        tools=[_streaming_tool()],
    )

    async def collect():
        return [event async for event in runtime.stream("build the report")]

    events = asyncio.run(collect())
    event_types = [event.type for event in events]
    deltas = [event for event in events if event.type == "tool_output_delta"]
    assert [event.payload["chunk"] for event in deltas] == [
        "alpha",
        "-beta",
        "-gamma",
    ]
    completed_index = event_types.index("tool_completed")
    assert all(
        index < completed_index
        for index, event_type in enumerate(event_types)
        if event_type == "tool_output_delta"
    )
    assert (
        next(event for event in events if event.type == "tool_completed").payload[
            "output"
        ]
        == "alpha-beta-gamma"
    )


def test_guardrails_buffer_and_publish_only_sanitized_tool_output() -> None:
    secret = "sk-abcdefghijklmnopqrstuv0000"

    def credentials():
        yield "token="
        yield secret

    agent = Agent(
        llm=_OneToolLLM("credentials"),
        tools=[FunctionTool.from_callable(credentials, name="credentials")],
        guardrails=Guardrails(),
        auto_use_skills=False,
    )

    events = list(agent.stream("inspect credentials"))

    started = next(event for event in events if event.type == "tool_output_started")
    assert started.payload["buffered"] is True
    streamed = "".join(
        event.payload["chunk"] for event in events if event.type == "tool_output_delta"
    )
    assert secret not in streamed
    assert "[REDACTED:api-key]" in streamed


def test_terminal_renderer_displays_all_chunks_without_final_duplication() -> None:
    file = io.StringIO()
    renderer = StreamRenderer(file=file, style="plain")
    agent = Agent(
        llm=_OneToolLLM("report"),
        tools=[_streaming_tool()],
        auto_use_skills=False,
    )

    for event in agent.stream("build the report"):
        renderer.feed(event)
    renderer.close()

    rendered = file.getvalue()
    assert "alpha" in rendered
    assert "-beta" in rendered
    assert "-gamma" in rendered
    assert rendered.count("alpha-beta-gamma") == 0
    assert "tool completed" in rendered
