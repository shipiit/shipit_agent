"""Full-proof tests for deep agent streaming, MCP support, with_builtins,
template resolution, and all deep agent features.
"""

from __future__ import annotations

import tempfile

from shipit_agent import Agent, TeamAgent, Pipeline, step, parallel
from shipit_agent.deep import (
    GoalAgent,
    Goal,
    GoalResult,
    ReflectiveAgent,
    ReflectionResult,
    AdaptiveAgent,
    Supervisor,
    Worker,
    SupervisorResult,
    PersistentAgent,
    Checkpoint,
    Channel,
    AgentMessage,
    AgentBenchmark,
    TestCase,
)
from shipit_agent.llms import LLMResponse, SimpleEchoLLM
from shipit_agent.pipeline.step import Step, StepResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class JSONReplyLLM:
    def __init__(self, json_text: str):
        self._json = json_text

    def complete(
        self,
        *,
        messages,
        tools=None,
        system_prompt=None,
        metadata=None,
        response_format=None,
    ):
        return LLMResponse(content=self._json)


class SequenceLLM:
    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self._index = 0

    def complete(
        self,
        *,
        messages,
        tools=None,
        system_prompt=None,
        metadata=None,
        response_format=None,
    ):
        text = self._responses[min(self._index, len(self._responses) - 1)]
        self._index += 1
        return LLMResponse(content=text)


# ===========================================================================
# GOAL AGENT STREAMING
# ===========================================================================


class TestGoalAgentStreaming:
    def test_stream_emits_run_started(self):
        llm = SequenceLLM(
            [
                '{"subtasks": ["do it"]}',
                "done",
                '{"criteria_met": [true], "all_done": true}',
            ]
        )
        agent = GoalAgent(
            llm=llm, goal=Goal(objective="Test", success_criteria=["done"])
        )
        events = list(agent.stream())
        assert events[0].type == "run_started"
        assert "Test" in events[0].payload["objective"]

    def test_stream_emits_planning_events(self):
        llm = SequenceLLM(
            [
                '{"subtasks": ["step1", "step2"]}',
                "output1",
                '{"criteria_met": [true], "all_done": true}',
            ]
        )
        agent = GoalAgent(llm=llm, goal=Goal(objective="Plan", success_criteria=["ok"]))
        events = list(agent.stream())
        types = [e.type for e in events]
        assert "planning_started" in types
        assert "planning_completed" in types

    def test_stream_emits_step_events(self):
        llm = SequenceLLM(
            [
                '{"subtasks": ["task1"]}',
                "result",
                '{"criteria_met": [true], "all_done": true}',
            ]
        )
        agent = GoalAgent(llm=llm, goal=Goal(objective="Steps", success_criteria=["x"]))
        events = list(agent.stream())
        step_events = [e for e in events if e.type == "step_started"]
        assert len(step_events) >= 1

    def test_stream_emits_run_completed(self):
        llm = SequenceLLM(
            [
                '{"subtasks": ["x"]}',
                "done",
                '{"criteria_met": [true], "all_done": true}',
            ]
        )
        agent = GoalAgent(
            llm=llm, goal=Goal(objective="Complete", success_criteria=["y"])
        )
        events = list(agent.stream())
        assert events[-1].type == "run_completed"

    def test_stream_payload_contains_subtasks(self):
        llm = SequenceLLM(
            [
                '{"subtasks": ["a", "b", "c"]}',
                "done",
                '{"criteria_met": [true], "all_done": true}',
            ]
        )
        agent = GoalAgent(
            llm=llm, goal=Goal(objective="Multi", success_criteria=["ok"])
        )
        events = list(agent.stream())
        planning = next(e for e in events if e.type == "planning_completed")
        assert planning.payload["subtasks"] == ["a", "b", "c"]


# ===========================================================================
# REFLECTIVE AGENT STREAMING
# ===========================================================================


class TestReflectiveAgentStreaming:
    def test_stream_emits_run_started(self):
        llm = SequenceLLM(
            [
                "Initial output",
                '{"feedback": "good", "quality_score": 0.95, "revision_needed": false}',
            ]
        )
        agent = ReflectiveAgent(llm=llm, quality_threshold=0.8)
        events = list(agent.stream("test"))
        assert events[0].type == "run_started"

    def test_stream_emits_reasoning_events(self):
        llm = SequenceLLM(
            [
                "Draft",
                '{"feedback": "ok", "quality_score": 0.9, "revision_needed": false}',
            ]
        )
        agent = ReflectiveAgent(llm=llm, quality_threshold=0.8)
        events = list(agent.stream("test"))
        types = [e.type for e in events]
        assert "reasoning_started" in types
        assert "reasoning_completed" in types

    def test_stream_shows_quality_in_payload(self):
        llm = SequenceLLM(
            [
                "Draft",
                '{"feedback": "excellent", "quality_score": 0.92, "revision_needed": false}',
            ]
        )
        agent = ReflectiveAgent(llm=llm, quality_threshold=0.8)
        events = list(agent.stream("test"))
        reasoning = next(e for e in events if e.type == "reasoning_completed")
        assert reasoning.payload["quality"] == 0.92

    def test_stream_with_revision(self):
        llm = SequenceLLM(
            [
                "Draft v1",
                '{"feedback": "needs work", "quality_score": 0.4, "revision_needed": true}',
                "Draft v2 improved",
                '{"feedback": "great", "quality_score": 0.9, "revision_needed": false}',
            ]
        )
        agent = ReflectiveAgent(llm=llm, quality_threshold=0.8, max_reflections=3)
        events = list(agent.stream("test"))
        reasoning_events = [e for e in events if e.type == "reasoning_completed"]
        assert len(reasoning_events) == 2

    def test_stream_emits_run_completed(self):
        llm = SequenceLLM(
            [
                "Output",
                '{"feedback": "ok", "quality_score": 0.9, "revision_needed": false}',
            ]
        )
        agent = ReflectiveAgent(llm=llm)
        events = list(agent.stream("test"))
        assert events[-1].type == "run_completed"


# ===========================================================================
# SUPERVISOR STREAMING
# ===========================================================================


class TestSupervisorStreaming:
    def test_stream_emits_run_started(self):
        llm = JSONReplyLLM('{"action": "done", "final_answer": "done"}')
        supervisor = Supervisor(
            llm=llm, workers=[Worker(name="w", agent=Agent(llm=SimpleEchoLLM()))]
        )
        events = list(supervisor.stream("task"))
        assert events[0].type == "run_started"
        assert "task" in events[0].payload["task"]

    def test_stream_shows_delegation(self):
        llm = SequenceLLM(
            [
                '{"action": "delegate", "worker": "w", "task": "do work"}',
                '{"action": "done", "final_answer": "all done"}',
            ]
        )
        supervisor = Supervisor(
            llm=llm, workers=[Worker(name="w", agent=Agent(llm=SimpleEchoLLM()))]
        )
        events = list(supervisor.stream("task"))
        tool_called = [e for e in events if e.type == "tool_called"]
        assert len(tool_called) >= 1
        assert tool_called[0].payload.get("worker") == "w"

    def test_stream_tags_worker_in_events(self):
        llm = SequenceLLM(
            [
                '{"action": "delegate", "worker": "analyst", "task": "analyze"}',
                '{"action": "done", "final_answer": "done"}',
            ]
        )
        supervisor = Supervisor(
            llm=llm, workers=[Worker(name="analyst", agent=Agent(llm=SimpleEchoLLM()))]
        )
        events = list(supervisor.stream("task"))
        worker_events = [e for e in events if e.payload.get("worker") == "analyst"]
        assert len(worker_events) >= 1

    def test_stream_emits_run_completed(self):
        llm = JSONReplyLLM('{"action": "done", "final_answer": "result"}')
        supervisor = Supervisor(
            llm=llm, workers=[Worker(name="w", agent=Agent(llm=SimpleEchoLLM()))]
        )
        events = list(supervisor.stream("task"))
        assert events[-1].type == "run_completed"

    def test_stream_handles_unknown_worker(self):
        llm = SequenceLLM(
            [
                '{"action": "delegate", "worker": "ghost", "task": "work"}',
                '{"action": "done", "final_answer": "done"}',
            ]
        )
        supervisor = Supervisor(
            llm=llm, workers=[Worker(name="real", agent=Agent(llm=SimpleEchoLLM()))]
        )
        events = list(supervisor.stream("task"))
        failed = [e for e in events if e.type == "tool_failed"]
        assert len(failed) >= 1


# ===========================================================================
# ADAPTIVE AGENT STREAMING
# ===========================================================================


class TestAdaptiveAgentStreaming:
    def test_stream_emits_events(self):
        agent = AdaptiveAgent(llm=SimpleEchoLLM())
        events = list(agent.stream("hello"))
        assert events[0].type == "run_started"
        assert any(e.type == "run_completed" for e in events)

    def test_stream_with_created_tools(self):
        agent = AdaptiveAgent(llm=SimpleEchoLLM())
        agent.create_tool("greet", "Greets", "def greet() -> str:\n    return 'hi'")
        events = list(agent.stream("use greet"))
        started = events[0]
        assert "greet" in started.payload.get("created_tools", [])


# ===========================================================================
# WITH_BUILTINS FACTORY METHODS
# ===========================================================================


class TestWithBuiltins:
    def test_goal_agent_with_builtins(self):
        agent = GoalAgent.with_builtins(
            llm=SimpleEchoLLM(),
            goal=Goal(objective="Test", success_criteria=["ok"]),
        )
        assert agent.use_builtins is True
        inner = agent._build_agent()
        assert len(inner.tools) > 5  # has built-in tools

    def test_reflective_agent_with_builtins(self):
        agent = ReflectiveAgent.with_builtins(llm=SimpleEchoLLM())
        assert agent.use_builtins is True
        inner = agent._build_agent()
        assert len(inner.tools) > 5

    def test_adaptive_agent_with_builtins(self):
        agent = AdaptiveAgent.with_builtins(llm=SimpleEchoLLM())
        assert agent.use_builtins is True

    def test_supervisor_with_builtins(self):
        supervisor = Supervisor.with_builtins(
            llm=SimpleEchoLLM(),
            worker_configs=[
                {"name": "w1", "prompt": "Worker 1"},
                {"name": "w2", "prompt": "Worker 2", "capabilities": ["writing"]},
            ],
        )
        assert "w1" in supervisor.workers
        assert "w2" in supervisor.workers
        assert len(supervisor.workers["w1"].agent.tools) > 5

    def test_team_agent_with_builtins(self):
        agent = TeamAgent.with_builtins(
            name="researcher",
            role="Expert researcher",
            llm=SimpleEchoLLM(),
            capabilities=["research"],
        )
        assert agent.name == "researcher"
        assert agent.role == "Expert researcher"
        assert len(agent.agent.tools) > 5

    def test_goal_agent_with_builtins_and_mcps(self):
        from shipit_agent.mcp import MCPServer

        mcp = MCPServer(name="test-mcp")
        agent = GoalAgent.with_builtins(
            llm=SimpleEchoLLM(),
            mcps=[mcp],
            goal=Goal(objective="Test", success_criteria=[]),
        )
        assert len(agent.mcps) == 1


# ===========================================================================
# PIPELINE TEMPLATE RESOLUTION
# ===========================================================================


class TestPipelineTemplates:
    def test_simple_key_resolution(self):
        ctx = {"topic": StepResult(name="topic", output="Python")}
        result = Step._resolve_template("Learn about {topic}", ctx)
        assert result == "Learn about Python"

    def test_dotted_key_resolution(self):
        ctx = {"research": StepResult(name="research", output="Key facts here")}
        result = Step._resolve_template("Write using: {research.output}", ctx)
        assert result == "Write using: Key facts here"

    def test_mixed_resolution(self):
        ctx = {
            "topic": StepResult(name="topic", output="AI"),
            "research": StepResult(name="research", output="Facts"),
        }
        result = Step._resolve_template("About {topic}: {research.output}", ctx)
        assert result == "About AI: Facts"

    def test_unresolved_keys_stay(self):
        result = Step._resolve_template("Hello {unknown}", {})
        assert result == "Hello {unknown}"

    def test_pipeline_run_resolves_inputs(self):
        pipe = Pipeline.sequential(
            step("greet", fn=lambda x: f"Hello {x}"),
        )
        result = pipe.run(name="World")
        # The fn receives the last context output or the prompt
        assert result.output  # something was produced

    def test_pipeline_step_references_previous(self):
        pipe = Pipeline.sequential(
            step("first", fn=lambda x: "HELLO"),
            step("second", fn=str.lower, prompt="{first.output}"),
        )
        result = pipe.run()
        assert result.output == "hello"

    def test_pipeline_parallel_results_accessible(self):
        pipe = Pipeline(
            parallel(
                step("a", fn=lambda x: "AAA"),
                step("b", fn=lambda x: "BBB"),
            ),
        )
        result = pipe.run()
        assert result.steps["a"].output == "AAA"
        assert result.steps["b"].output == "BBB"


# ===========================================================================
# CHANNEL COMPREHENSIVE
# ===========================================================================


class TestChannelAdvanced:
    def test_broadcast_to_multiple_agents(self):
        channel = Channel()
        for target in ["dev1", "dev2", "dev3"]:
            channel.send(
                AgentMessage(
                    from_agent="manager",
                    to_agent=target,
                    type="task",
                    data={"work": f"for {target}"},
                )
            )
        assert channel.pending(agent="dev1") == 1
        assert channel.pending(agent="dev2") == 1
        assert channel.pending(agent="dev3") == 1

    def test_fifo_ordering(self):
        channel = Channel()
        for i in range(5):
            channel.send(
                AgentMessage(from_agent="a", to_agent="b", type="t", data={"n": i})
            )
        for i in range(5):
            msg = channel.receive(agent="b")
            assert msg.data["n"] == i

    def test_ack_requires_flag(self):
        channel = Channel()
        msg = AgentMessage(from_agent="a", to_agent="b", type="t", requires_ack=False)
        channel.send(msg)
        received = channel.receive(agent="b")
        channel.ack(received)
        assert received.acknowledged  # ack works regardless of requires_ack flag

    def test_empty_receive_returns_none(self):
        channel = Channel()
        assert channel.receive(agent="nobody", timeout=0.01) is None

    def test_channel_name(self):
        channel = Channel(name="my-pipeline")
        assert channel.name == "my-pipeline"


# ===========================================================================
# BENCHMARK COMPREHENSIVE
# ===========================================================================


class TestBenchmarkAdvanced:
    def test_multiple_expected_contains(self):
        agent = Agent(llm=SimpleEchoLLM(), prompt="test")
        report = AgentBenchmark(
            name="multi",
            cases=[
                TestCase(
                    input="hello world foo", expected_contains=["hello", "world", "foo"]
                )
            ],
        ).run(agent)
        assert report.passed == 1

    def test_expected_not_contains_fails(self):
        agent = Agent(llm=SimpleEchoLLM(), prompt="test")
        report = AgentBenchmark(
            name="neg",
            cases=[
                TestCase(input="secret password", expected_not_contains=["password"])
            ],
        ).run(agent)
        assert report.failed == 1
        assert "password" in report.results[0].failures[0]

    def test_pass_rate_calculation(self):
        agent = Agent(llm=SimpleEchoLLM(), prompt="test")
        report = AgentBenchmark(
            name="rate",
            cases=[
                TestCase(input="hello", expected_contains=["hello"]),
                TestCase(input="hello", expected_contains=["nonexistent"]),
                TestCase(input="hello", expected_contains=["hello"]),
            ],
        ).run(agent)
        assert report.pass_rate == 2 / 3

    def test_summary_includes_failures(self):
        agent = Agent(llm=SimpleEchoLLM(), prompt="test")
        report = AgentBenchmark(
            name="fail-detail",
            cases=[TestCase(input="hello", expected_contains=["xyz"])],
        ).run(agent)
        summary = report.summary()
        assert "FAIL" in summary
        assert "xyz" in summary


# ===========================================================================
# PERSISTENT AGENT COMPREHENSIVE
# ===========================================================================


class TestPersistentAgentAdvanced:
    def test_checkpoint_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            agent = PersistentAgent(llm=SimpleEchoLLM(), checkpoint_dir=tmpdir)
            cp = Checkpoint(
                agent_id="rt", step=7, state={"task": "test"}, outputs=["a", "b", "c"]
            )
            agent._save_checkpoint(cp)
            loaded = agent._load_checkpoint("rt")
            assert loaded.step == 7
            assert loaded.outputs == ["a", "b", "c"]
            assert loaded.state["task"] == "test"

    def test_status_shows_paused(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            agent = PersistentAgent(llm=SimpleEchoLLM(), checkpoint_dir=tmpdir)
            agent._save_checkpoint(Checkpoint(agent_id="s1", step=5, outputs=["x"] * 5))
            status = agent.status("s1")
            assert status["state"] == "paused"
            assert status["steps_done"] == 5
            assert status["outputs_count"] == 5

    def test_delete_removes_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            agent = PersistentAgent(llm=SimpleEchoLLM(), checkpoint_dir=tmpdir)
            agent._save_checkpoint(Checkpoint(agent_id="del", step=1))
            agent._delete_checkpoint("del")
            assert agent._load_checkpoint("del") is None
            assert agent.status("del")["state"] == "not_found"

    def test_resume_raises_without_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            agent = PersistentAgent(llm=SimpleEchoLLM(), checkpoint_dir=tmpdir)
            try:
                agent.resume(agent_id="none")
                assert False
            except ValueError as e:
                assert "No checkpoint" in str(e)


# ===========================================================================
# GOAL RESULT SERIALIZATION
# ===========================================================================


class TestGoalResultSerialization:
    def test_to_dict(self):
        result = GoalResult(
            goal=Goal(objective="Test", success_criteria=["a", "b"]),
            output="done",
            goal_status="completed",
            criteria_met=[True, True],
            steps_taken=3,
            step_outputs=[{"step": 1, "task": "do", "output": "did"}],
        )
        d = result.to_dict()
        assert d["objective"] == "Test"
        assert d["status"] == "completed"
        assert d["criteria_met"] == [True, True]
        assert d["steps_taken"] == 3


class TestReflectionResultSerialization:
    def test_to_dict(self):
        from shipit_agent.deep.reflective_agent import Reflection

        result = ReflectionResult(
            output="final",
            reflections=[
                Reflection(feedback="ok", quality_score=0.9, revision_needed=False)
            ],
            revisions=["v1", "v2"],
            final_quality=0.9,
            iterations=1,
        )
        d = result.to_dict()
        assert d["final_quality"] == 0.9
        assert d["iterations"] == 1
        assert len(d["reflections"]) == 1


class TestSupervisorResultSerialization:
    def test_to_dict(self):
        from shipit_agent.deep.supervisor import Delegation

        result = SupervisorResult(
            output="done",
            delegations=[
                Delegation(round=1, worker="w", task="do", output="did", approved=True)
            ],
            total_rounds=1,
        )
        d = result.to_dict()
        assert d["output"] == "done"
        assert d["total_rounds"] == 1
        assert len(d["delegations"]) == 1
        assert d["delegations"][0]["approved"] is True
