"""Tests for Pipeline streaming and AgentTeam streaming."""
from __future__ import annotations

from shipit_agent import Agent, AgentTeam, TeamAgent, Pipeline, step, parallel
from shipit_agent.llms import LLMResponse, SimpleEchoLLM


class JSONReplyLLM:
    def __init__(self, json_text: str):
        self._json = json_text
    def complete(self, *, messages, tools=None, system_prompt=None, metadata=None, response_format=None):
        return LLMResponse(content=self._json)


class SequenceLLM:
    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self._index = 0
    def complete(self, *, messages, tools=None, system_prompt=None, metadata=None, response_format=None):
        text = self._responses[min(self._index, len(self._responses) - 1)]
        self._index += 1
        return LLMResponse(content=text)


# ===========================================================================
# PIPELINE STREAMING
# ===========================================================================

class TestPipelineStreaming:
    def test_stream_emits_run_started(self):
        pipe = Pipeline.sequential(step("x", fn=lambda x: "done"))
        events = list(pipe.stream())
        assert events[0].type == "run_started"
        assert "Pipeline" in events[0].message

    def test_stream_emits_step_events(self):
        pipe = Pipeline.sequential(
            step("a", fn=lambda x: "AAA"),
            step("b", fn=lambda x: "BBB"),
        )
        events = list(pipe.stream())
        step_events = [e for e in events if e.type == "step_started"]
        assert len(step_events) == 2
        assert step_events[0].payload["step"] == "a"
        assert step_events[1].payload["step"] == "b"

    def test_stream_emits_completion_events(self):
        pipe = Pipeline.sequential(step("x", fn=lambda x: "result"))
        events = list(pipe.stream())
        completed = [e for e in events if e.type == "tool_completed"]
        assert len(completed) == 1
        assert completed[0].payload["step"] == "x"
        assert "result" in completed[0].payload["output"]

    def test_stream_emits_run_completed(self):
        pipe = Pipeline.sequential(step("x", fn=lambda x: "done"))
        events = list(pipe.stream())
        assert events[-1].type == "run_completed"
        assert "done" in events[-1].payload["output"]

    def test_stream_parallel_shows_all_steps(self):
        pipe = Pipeline(
            parallel(
                step("a", fn=lambda x: "AA"),
                step("b", fn=lambda x: "BB"),
            ),
        )
        events = list(pipe.stream())
        parallel_start = next(e for e in events if e.type == "step_started")
        assert parallel_start.payload["parallel"] is True
        assert set(parallel_start.payload["steps"]) == {"a", "b"}
        completed = [e for e in events if e.type == "tool_completed"]
        assert len(completed) == 2

    def test_stream_with_agent_step_forwards_inner_events(self):
        pipe = Pipeline.sequential(
            step("agent_step", agent=Agent(llm=SimpleEchoLLM(), prompt="test"), prompt="Hello"),
        )
        events = list(pipe.stream())
        # Should have inner agent events tagged with pipeline_step
        inner = [e for e in events if e.payload.get("pipeline_step") == "agent_step"]
        assert len(inner) >= 1

    def test_stream_with_inputs(self):
        pipe = Pipeline.sequential(step("greet", fn=lambda x: f"Hello {x}", prompt="{name}"))
        events = list(pipe.stream(name="World"))
        assert events[0].payload["inputs"] == ["name"]

    def test_stream_shows_stage_count(self):
        pipe = Pipeline.sequential(
            step("a", fn=lambda x: "1"),
            step("b", fn=lambda x: "2"),
            step("c", fn=lambda x: "3"),
        )
        events = list(pipe.stream())
        assert events[0].payload["stages"] == 3
        assert events[-1].payload["steps_completed"] == 3


# ===========================================================================
# AGENT TEAM STREAMING
# ===========================================================================

class TestAgentTeamStreaming:
    def test_team_stream_emits_run_started(self):
        coordinator = JSONReplyLLM('{"done": true, "final_answer": "done"}')
        team = AgentTeam(
            coordinator=coordinator,
            agents=[TeamAgent(name="w", role="W", agent=Agent(llm=SimpleEchoLLM()))],
        )
        events = list(team.stream("task"))
        assert events[0].type == "run_started"
        assert "team" in events[0].message.lower() or "Team" in events[0].message

    def test_team_stream_emits_run_completed(self):
        coordinator = JSONReplyLLM('{"done": true, "final_answer": "result"}')
        team = AgentTeam(
            coordinator=coordinator,
            agents=[TeamAgent(name="w", role="W", agent=Agent(llm=SimpleEchoLLM()))],
        )
        events = list(team.stream("task"))
        assert events[-1].type == "run_completed"

    def test_team_stream_shows_delegation(self):
        coordinator = SequenceLLM([
            '{"next_agent": "worker", "prompt": "do it", "done": false}',
            '{"done": true, "final_answer": "all done"}',
        ])
        team = AgentTeam(
            coordinator=coordinator,
            agents=[TeamAgent(name="worker", role="W", agent=Agent(llm=SimpleEchoLLM()))],
        )
        events = list(team.stream("task"))
        delegations = [e for e in events if e.type == "tool_called"]
        assert len(delegations) >= 1
        assert "worker" in delegations[0].payload.get("agent", "")
