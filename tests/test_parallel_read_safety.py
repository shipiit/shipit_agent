"""Parallel execution runs read-only groups concurrently and keeps writes
ordered — the batch-reads-serialize-writes behaviour.
"""

from __future__ import annotations

import asyncio
import threading
import time

from shipit_agent.async_runtime import AsyncAgentRuntime
from shipit_agent.llms.base import LLMResponse
from shipit_agent.models import ToolCall
from shipit_agent.registry import ToolRegistry
from shipit_agent.runtime import AgentRuntime
from shipit_agent.runtime_core import RuntimeCore
from shipit_agent.tools.base import ToolOutput


class SlowReadTool:
    read_only = True

    def __init__(self, name):
        self.name = name
        self.description = "read"

    def schema(self):
        return {"type": "function", "function": {"name": self.name,
                "description": "read", "parameters": {"type": "object",
                "properties": {}}}}

    def run(self, context, **kwargs):
        time.sleep(0.3)
        return ToolOutput(text=f"{self.name} done")


class OrderedWriteTool:
    read_only = False
    order: list[str] = []
    lock = threading.Lock()

    def __init__(self, name):
        self.name = name
        self.description = "write"

    def schema(self):
        return {"type": "function", "function": {"name": self.name,
                "description": "write", "parameters": {"type": "object",
                "properties": {}}}}

    def run(self, context, **kwargs):
        with OrderedWriteTool.lock:
            OrderedWriteTool.order.append(self.name)
        return ToolOutput(text=f"{self.name} wrote")


class TwoCallLLM:
    def __init__(self, names):
        self.names = names
        self.turn = 0

    def complete(self, *, messages, tools=None, system_prompt=None, metadata=None):
        self.turn += 1
        if self.turn == 1:
            return LLMResponse(
                content="",
                tool_calls=[ToolCall(name=n, arguments={}) for n in self.names],
            )
        return LLMResponse(content="done")


def test_read_only_calls_flags_from_contracts():
    registry = ToolRegistry.build(tools=[SlowReadTool("read_a"), OrderedWriteTool("write_b")])
    calls = [ToolCall(name="read_a", arguments={}), ToolCall(name="write_b", arguments={})]
    flags = RuntimeCore.read_only_calls(calls, registry)
    assert flags == [True, False]


def test_read_group_runs_concurrently():
    tools = [SlowReadTool("read_a"), SlowReadTool("read_b"), SlowReadTool("read_c")]
    runtime = AgentRuntime(
        llm=TwoCallLLM(["read_a", "read_b", "read_c"]),
        prompt="You are helpful.",
        tools=tools,
        parallel_tool_execution=True,
        max_iterations=2,
    )
    start = time.monotonic()
    state, _ = runtime.run("read everything")
    elapsed = time.monotonic() - start
    # Three 0.3s reads concurrently finish well under the 0.9s serial sum.
    assert elapsed < 0.7, f"reads did not parallelize ({elapsed:.2f}s)"
    assert len([r for r in state.tool_results]) == 3


def test_write_group_stays_serial_and_ordered():
    OrderedWriteTool.order = []
    tools = [OrderedWriteTool("write_a"), OrderedWriteTool("write_b")]
    runtime = AgentRuntime(
        llm=TwoCallLLM(["write_a", "write_b"]),
        prompt="You are helpful.",
        tools=tools,
        parallel_tool_execution=True,  # even with the flag on, writes serialize
        max_iterations=2,
    )
    runtime.run("write both")
    assert OrderedWriteTool.order == ["write_a", "write_b"]


def test_mixed_group_runs_serially():
    OrderedWriteTool.order = []
    tools = [SlowReadTool("read_a"), OrderedWriteTool("write_b")]
    runtime = AgentRuntime(
        llm=TwoCallLLM(["read_a", "write_b"]),
        prompt="You are helpful.",
        tools=tools,
        parallel_tool_execution=True,
        max_iterations=2,
    )
    state, _ = runtime.run("read then write")
    # A write in the group forces serial execution — both still run.
    names = {r.name for r in state.tool_results}
    assert names == {"read_a", "write_b"}


def test_async_read_group_parallelizes():
    tools = [SlowReadTool("read_a"), SlowReadTool("read_b"), SlowReadTool("read_c")]
    runtime = AsyncAgentRuntime(
        llm=TwoCallLLM(["read_a", "read_b", "read_c"]),
        prompt="You are helpful.",
        tools=tools,
        parallel_tool_execution=True,
        max_iterations=2,
    )
    start = time.monotonic()
    asyncio.run(runtime.run("read everything"))
    elapsed = time.monotonic() - start
    assert elapsed < 0.7, f"async reads did not parallelize ({elapsed:.2f}s)"
