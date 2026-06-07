"""Regression test for Pipeline.stream double-execution (DEEP-1).

An agent step in stream() must run the agent exactly once — previously it
streamed once for events, then called stage.execute() which ran agent.run()
again (double LLM call + re-run side-effecting tools).
"""

from __future__ import annotations

from shipit_agent.models import AgentEvent
from shipit_agent.pipeline import Pipeline, step


class CountingAgent:
    """Fake agent counting run() and stream() invocations."""

    def __init__(self, output: str = "AGENT-OUT"):
        self.output = output
        self.run_calls = 0
        self.stream_calls = 0

    def run(self, prompt, **kwargs):  # pragma: no cover - should not be called
        self.run_calls += 1

        class _R:
            output = self.output
            parsed = None

        return _R()

    def stream(self, prompt):
        self.stream_calls += 1
        yield AgentEvent(type="step_started", message="inner started", payload={})
        yield AgentEvent(
            type="run_completed",
            message="inner done",
            payload={"output": self.output, "content": self.output},
        )


def test_agent_step_runs_once_in_stream():
    agent = CountingAgent()
    pipe = Pipeline.sequential(step("a", agent=agent, prompt="hi"))
    events = list(pipe.stream())

    assert agent.stream_calls == 1
    assert agent.run_calls == 0  # must NOT call run() a second time

    # The recorded step output should come from the streamed run.
    completed = [e for e in events if e.type == "tool_completed"]
    assert completed and completed[0].payload["output"] == "AGENT-OUT"
    assert events[-1].type == "run_completed"
    assert "AGENT-OUT" in events[-1].payload["output"]


def test_agent_step_output_feeds_next_step():
    agent = CountingAgent(output="FROM-AGENT")
    pipe = Pipeline.sequential(
        step("a", agent=agent, prompt="hi"),
        step("b", fn=lambda x: f"got:{x}", prompt="{a.output}"),
    )
    events = list(pipe.stream())
    assert agent.run_calls == 0
    completed = [e for e in events if e.type == "tool_completed"]
    b_event = next(e for e in completed if e.payload["step"] == "b")
    assert b_event.payload["output"] == "got:FROM-AGENT"
