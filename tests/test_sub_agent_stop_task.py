"""Stopping a background sub-agent: SubAgentTool.stop_task and AgentClient.stop_task."""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Any

import pytest

from shipit_agent import FunctionTool
from shipit_agent.core.models import ToolCall
from shipit_agent.llms.base import LLMResponse
from shipit_agent.sdk import AgentClient, AgentOptions
from shipit_agent.tools.base import ToolContext
from shipit_agent.tools.sub_agent import SubAgentTool


class _ChildKeepsWorking:
    """The child calls a slow tool every step until it is stopped."""

    model = "claude-sonnet-5-5"

    def __init__(self) -> None:
        self.steps = 0
        self.started = threading.Event()

    def complete(self, **_: Any) -> LLMResponse:
        self.steps += 1
        self.started.set()
        return LLMResponse(content="", tool_calls=[ToolCall(name="wait", arguments={})])


def _wait() -> str:
    """Wait a moment."""
    time.sleep(0.05)
    return "waited"


def _start(tool: SubAgentTool) -> str:
    output = tool.run(ToolContext(prompt="parent"), task="dig in", background=True)
    return output.text.split()[1].rstrip(":")


def test_a_running_task_stops_and_can_still_be_collected() -> None:
    llm = _ChildKeepsWorking()
    tool = SubAgentTool(llm, tools=[FunctionTool.from_callable(_wait, name="wait")])
    task_id = _start(tool)
    # Wait for the child to be running, so this stops it rather than a queued task.
    assert llm.started.wait(timeout=5)
    assert tool.running_tasks() == [task_id]
    assert tool.stop_task(task_id) is True
    deadline = time.monotonic() + 5
    while tool.running_tasks() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert tool.running_tasks() == []
    steps_when_stopped = llm.steps
    time.sleep(0.2)
    assert llm.steps == steps_when_stopped
    collected = tool.run(ToolContext(prompt="parent"), collect=task_id)
    assert collected.metadata["task"] == "dig in" and "cancelled" in collected.text


def test_stopping_an_unknown_task_says_so() -> None:
    assert SubAgentTool(_ChildKeepsWorking()).stop_task("task-99") is False


def test_a_finished_task_leaves_no_child_behind() -> None:
    class _Answers:
        model = "claude-sonnet-5-5"

        def complete(self, **_: Any) -> LLMResponse:
            return LLMResponse(content="found it")

    tool = SubAgentTool(_Answers())
    task_id = _start(tool)
    tool.run(ToolContext(prompt="parent"), collect=task_id)
    assert tool._children == {}


def test_the_client_stops_a_task_by_id() -> None:
    stopped: list[str] = []

    class _Stoppable:
        name = "sub_agent"

        def stop_task(self, task_id: str) -> bool:
            stopped.append(task_id)
            return task_id == "task-1"

    class _Quiet:
        model = "claude-sonnet-5-5"

        def complete(self, **_: Any) -> LLMResponse:
            return LLMResponse(content="ok")

    async def run() -> None:
        async with AgentClient(AgentOptions(llm=_Quiet(), tools=[_Stoppable()])) as client:
            await client.stop_task("task-1")
            with pytest.raises(KeyError):
                await client.stop_task("task-2")

    asyncio.run(run())
    assert stopped == ["task-1", "task-2"]
