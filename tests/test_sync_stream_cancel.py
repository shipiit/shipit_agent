"""Cancelling a run while the sync stream is read still delivers how it ended.

The sync stream dropped every event after cancel(), so a caller that
interrupted a run never saw run_cancelled or run_completed; the async
stream delivered them. Leaving the loop early still stops delivery.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from shipit_agent import Agent, FunctionTool
from shipit_agent.core.models import ToolCall
from shipit_agent.llms.base import LLMResponse


class _KeepsCalling:
    model = "claude-sonnet-5-5"

    def __init__(self) -> None:
        self.started = threading.Event()

    def complete(self, **_: Any) -> LLMResponse:
        self.started.set()
        return LLMResponse(content="", tool_calls=[ToolCall(name="slow", arguments={})])


def _slow() -> str:
    """Takes a moment."""
    time.sleep(0.2)
    return "slow done"


def _agent(llm: _KeepsCalling) -> Agent:
    return Agent(llm=llm, tools=[FunctionTool.from_callable(_slow, name="slow")])


def test_an_interrupted_sync_stream_ends_with_run_completed() -> None:
    llm = _KeepsCalling()
    agent = _agent(llm)
    threading.Thread(target=lambda: (llm.started.wait(5), agent.cancel()), daemon=True).start()
    types = [event.type for event in agent.stream("go")]
    assert "run_cancelled" in types
    assert types[-1] == "run_completed"


def test_leaving_the_sync_stream_early_still_stops_the_run() -> None:
    llm = _KeepsCalling()
    agent = _agent(llm)
    for event in agent.stream("go"):
        if event.type == "tool_called":
            break
    calls_when_left = llm.started.is_set()
    time.sleep(0.5)
    assert calls_when_left and agent._active_runtime is None
