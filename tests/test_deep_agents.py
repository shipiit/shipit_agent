"""Full-proof test suite for SHIPIT Deep Agents.

Comprehensive tests for GoalAgent, ReflectiveAgent, AdaptiveAgent,
Supervisor, PersistentAgent, Channel, and AgentBenchmark.
"""

from __future__ import annotations

import tempfile

from shipit_agent import Agent, FunctionTool
from shipit_agent.llms import LLMResponse, SimpleEchoLLM
from shipit_agent.tools.base import ToolContext


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


class CountingLLM:
    """LLM that counts how many times it's been called."""

    def __init__(self):
        self.call_count = 0

    def complete(
        self,
        *,
        messages,
        tools=None,
        system_prompt=None,
        metadata=None,
        response_format=None,
    ):
        self.call_count += 1
        return LLMResponse(content=f"Response #{self.call_count}")


# ===========================================================================
# GOAL AGENT
# ===========================================================================


class TestGoalAgentComprehensive:
    def test_successful_goal_completion(self):
        from shipit_agent.deep import GoalAgent, Goal

        llm = SequenceLLM(
            [
                '{"subtasks": ["research", "implement", "test"]}',
                "Research done",
                '{"criteria_met": [true, false], "all_done": false, "next_action": "continue"}',
                "Implementation done",
                '{"criteria_met": [true, true], "all_done": true}',
            ]
        )
        result = GoalAgent(
            llm=llm,
            goal=Goal(objective="Build app", success_criteria=["Works", "Has tests"]),
        ).run()
        assert result.goal_status == "completed"
        assert all(result.criteria_met)

    def test_partial_goal(self):
        from shipit_agent.deep import GoalAgent, Goal

        llm = SequenceLLM(
            [
                '{"subtasks": ["task1"]}',
                "Did some work",
                '{"criteria_met": [true, false], "all_done": false}',
                '{"criteria_met": [true, false], "all_done": false}',
            ]
        )
        result = GoalAgent(
            llm=llm,
            goal=Goal(objective="Hard task", success_criteria=["A", "B"], max_steps=1),
        ).run()
        assert result.goal_status in ("partial", "failed")
        assert result.steps_taken >= 1

    def test_goal_with_no_criteria(self):
        from shipit_agent.deep import GoalAgent, Goal

        llm = SequenceLLM(
            [
                '{"subtasks": ["do it"]}',
                "Done",
                '{"criteria_met": [], "all_done": true}',
            ]
        )
        result = GoalAgent(llm=llm, goal=Goal(objective="Simple")).run()
        assert result.goal_status == "completed"

    def test_goal_result_has_step_outputs(self):
        from shipit_agent.deep import GoalAgent, Goal

        llm = SequenceLLM(
            [
                '{"subtasks": ["step1"]}',
                "Output of step 1",
                '{"criteria_met": [true], "all_done": true}',
            ]
        )
        result = GoalAgent(
            llm=llm,
            goal=Goal(objective="Test", success_criteria=["done"]),
        ).run()
        assert len(result.step_outputs) >= 1
        assert "step1" in result.step_outputs[0]["task"]

    def test_goal_result_to_dict(self):
        from shipit_agent.deep import GoalAgent, Goal

        llm = SequenceLLM(
            [
                '{"subtasks": ["x"]}',
                "done",
                '{"criteria_met": [true], "all_done": true}',
            ]
        )
        result = GoalAgent(
            llm=llm, goal=Goal(objective="Test", success_criteria=["c"])
        ).run()
        d = result.to_dict()
        assert "objective" in d
        assert "status" in d
        assert "criteria_met" in d

    def test_goal_with_tools(self):
        from shipit_agent.deep import GoalAgent, Goal

        def helper() -> str:
            return "helped"

        llm = SequenceLLM(
            [
                '{"subtasks": ["use helper"]}',
                "Used helper",
                '{"criteria_met": [true], "all_done": true}',
            ]
        )
        result = GoalAgent(
            llm=llm,
            tools=[FunctionTool.from_callable(helper)],
            goal=Goal(objective="Test", success_criteria=["helped"]),
        ).run()
        assert result.goal_status == "completed"


# ===========================================================================
# REFLECTIVE AGENT
# ===========================================================================


class TestReflectiveAgentComprehensive:
    def test_improves_through_reflections(self):
        from shipit_agent.deep import ReflectiveAgent

        llm = SequenceLLM(
            [
                "Draft v1",
                '{"feedback": "too short", "quality_score": 0.4, "revision_needed": true}',
                "Draft v2 with more detail",
                '{"feedback": "good", "quality_score": 0.85, "revision_needed": false}',
            ]
        )
        result = ReflectiveAgent(llm=llm, quality_threshold=0.8).run(
            "Write explanation"
        )
        assert result.final_quality >= 0.8
        assert len(result.revisions) == 2
        assert len(result.reflections) == 2

    def test_stops_immediately_if_good(self):
        from shipit_agent.deep import ReflectiveAgent

        llm = SequenceLLM(
            [
                "Perfect output",
                '{"feedback": "perfect", "quality_score": 0.99, "revision_needed": false}',
            ]
        )
        result = ReflectiveAgent(llm=llm, quality_threshold=0.8).run("Simple task")
        assert result.iterations == 1
        assert len(result.revisions) == 1

    def test_respects_max_reflections(self):
        from shipit_agent.deep import ReflectiveAgent

        llm = SequenceLLM(
            [
                "Draft",
                '{"feedback": "bad", "quality_score": 0.1, "revision_needed": true}',
                "Better draft",
                '{"feedback": "still bad", "quality_score": 0.2, "revision_needed": true}',
                "Another draft",
                '{"feedback": "still bad", "quality_score": 0.3, "revision_needed": true}',
            ]
        )
        result = ReflectiveAgent(llm=llm, max_reflections=2, quality_threshold=0.9).run(
            "Task"
        )
        assert result.iterations == 2  # stopped at max, not at quality

    def test_result_to_dict(self):
        from shipit_agent.deep import ReflectiveAgent

        llm = SequenceLLM(
            [
                "Output",
                '{"feedback": "ok", "quality_score": 0.9, "revision_needed": false}',
            ]
        )
        result = ReflectiveAgent(llm=llm).run("Task")
        d = result.to_dict()
        assert "output" in d
        assert "final_quality" in d
        assert "reflections" in d

    def test_custom_reflection_prompt(self):
        from shipit_agent.deep import ReflectiveAgent

        llm = SequenceLLM(
            [
                "Code output",
                '{"feedback": "no bugs", "quality_score": 0.95, "revision_needed": false}',
            ]
        )
        result = ReflectiveAgent(
            llm=llm,
            reflection_prompt="Check for bugs, edge cases, and performance issues.",
        ).run("Write a sort function")
        assert result.final_quality >= 0.9


# ===========================================================================
# ADAPTIVE AGENT
# ===========================================================================


class TestAdaptiveAgentComprehensive:
    def test_create_simple_tool(self):
        from shipit_agent.deep import AdaptiveAgent

        agent = AdaptiveAgent(llm=SimpleEchoLLM())
        tool = agent.create_tool(
            "greet",
            "Greets",
            "def greet(name: str) -> str:\n    return f'Hello {name}'",
        )
        assert tool.name == "greet"
        output = tool.run(ToolContext(prompt="test"), name="World")
        assert output.text == "Hello World"

    def test_create_multiple_tools(self):
        from shipit_agent.deep import AdaptiveAgent

        agent = AdaptiveAgent(llm=SimpleEchoLLM())
        agent.create_tool("t1", "Tool 1", "def t1() -> str:\n    return 'a'")
        agent.create_tool("t2", "Tool 2", "def t2() -> str:\n    return 'b'")
        assert len(agent.created_tools) == 2
        assert len(agent.tools) == 2

    def test_invalid_code_raises(self):
        from shipit_agent.deep import AdaptiveAgent

        agent = AdaptiveAgent(llm=SimpleEchoLLM())
        try:
            agent.create_tool("bad", "Bad", "not valid python")
            assert False, "Should raise"
        except SyntaxError:
            pass

    def test_no_callable_raises(self):
        from shipit_agent.deep import AdaptiveAgent

        agent = AdaptiveAgent(llm=SimpleEchoLLM())
        try:
            agent.create_tool("empty", "Empty", "x = 42")
            assert False, "Should raise ValueError"
        except ValueError:
            pass

    def test_created_tool_records(self):
        from shipit_agent.deep import AdaptiveAgent

        agent = AdaptiveAgent(llm=SimpleEchoLLM())
        agent.create_tool(
            "calc", "Calculator", "def calc(x: int) -> str:\n    return str(x * 2)"
        )
        record = agent.created_tools[0]
        assert record.name == "calc"
        assert record.description == "Calculator"
        assert "x * 2" in record.code


# ===========================================================================
# SUPERVISOR
# ===========================================================================


class TestSupervisorComprehensive:
    def test_single_delegation_then_done(self):
        from shipit_agent.deep import Supervisor, Worker

        llm = SequenceLLM(
            [
                '{"action": "delegate", "worker": "analyst", "task": "Analyze data"}',
                '{"action": "done", "final_answer": "Analysis: positive trends"}',
            ]
        )
        result = Supervisor(
            llm=llm,
            workers=[Worker(name="analyst", agent=Agent(llm=SimpleEchoLLM()))],
        ).run("Analyze sales")
        assert result.output == "Analysis: positive trends"
        assert len(result.delegations) == 1

    def test_multiple_delegations(self):
        from shipit_agent.deep import Supervisor, Worker

        llm = SequenceLLM(
            [
                '{"action": "delegate", "worker": "a", "task": "Do A"}',
                '{"action": "delegate", "worker": "b", "task": "Do B"}',
                '{"action": "done", "final_answer": "Both done"}',
            ]
        )
        result = Supervisor(
            llm=llm,
            workers=[
                Worker(name="a", agent=Agent(llm=SimpleEchoLLM())),
                Worker(name="b", agent=Agent(llm=SimpleEchoLLM())),
            ],
        ).run("Task")
        assert len(result.delegations) == 2

    def test_unknown_worker_handled(self):
        from shipit_agent.deep import Supervisor, Worker

        llm = SequenceLLM(
            [
                '{"action": "delegate", "worker": "ghost", "task": "Do stuff"}',
                '{"action": "done", "final_answer": "Handled"}',
            ]
        )
        result = Supervisor(
            llm=llm,
            workers=[Worker(name="real", agent=Agent(llm=SimpleEchoLLM()))],
        ).run("Task")
        assert "not found" in result.delegations[0].output

    def test_max_delegations_limit(self):
        from shipit_agent.deep import Supervisor, Worker

        llm = JSONReplyLLM('{"action": "delegate", "worker": "w", "task": "loop"}')
        result = Supervisor(
            llm=llm,
            workers=[Worker(name="w", agent=Agent(llm=SimpleEchoLLM()))],
            max_delegations=5,
        ).run("Infinite")
        assert len(result.delegations) == 5
        assert result.total_rounds == 5

    def test_result_serialization(self):
        from shipit_agent.deep import Supervisor, Worker

        llm = JSONReplyLLM('{"action": "done", "final_answer": "OK"}')
        result = Supervisor(
            llm=llm,
            workers=[Worker(name="w", agent=Agent(llm=SimpleEchoLLM()))],
        ).run("Task")
        d = result.to_dict()
        assert d["output"] == "OK"
        assert "delegations" in d

    def test_worker_capabilities(self):
        from shipit_agent.deep import Worker

        w = Worker(
            name="dev",
            agent=Agent(llm=SimpleEchoLLM()),
            capabilities=["python", "testing"],
        )
        assert "python" in w.capabilities


# ===========================================================================
# PERSISTENT AGENT
# ===========================================================================


class TestPersistentAgentComprehensive:
    def test_save_and_load_checkpoint(self):
        from shipit_agent.deep import PersistentAgent
        from shipit_agent.deep.persistent_agent import Checkpoint

        with tempfile.TemporaryDirectory() as tmpdir:
            agent = PersistentAgent(llm=SimpleEchoLLM(), checkpoint_dir=tmpdir)
            cp = Checkpoint(
                agent_id="test", step=5, state={"task": "x"}, outputs=["a", "b"]
            )
            agent._save_checkpoint(cp)

            loaded = agent._load_checkpoint("test")
            assert loaded is not None
            assert loaded.step == 5
            assert loaded.outputs == ["a", "b"]

    def test_delete_checkpoint(self):
        from shipit_agent.deep import PersistentAgent
        from shipit_agent.deep.persistent_agent import Checkpoint

        with tempfile.TemporaryDirectory() as tmpdir:
            agent = PersistentAgent(llm=SimpleEchoLLM(), checkpoint_dir=tmpdir)
            agent._save_checkpoint(Checkpoint(agent_id="del", step=1))
            agent._delete_checkpoint("del")
            assert agent._load_checkpoint("del") is None

    def test_status_not_found(self):
        from shipit_agent.deep import PersistentAgent

        with tempfile.TemporaryDirectory() as tmpdir:
            agent = PersistentAgent(llm=SimpleEchoLLM(), checkpoint_dir=tmpdir)
            assert agent.status("nope")["state"] == "not_found"

    def test_status_after_checkpoint(self):
        from shipit_agent.deep import PersistentAgent
        from shipit_agent.deep.persistent_agent import Checkpoint

        with tempfile.TemporaryDirectory() as tmpdir:
            agent = PersistentAgent(llm=SimpleEchoLLM(), checkpoint_dir=tmpdir)
            agent._save_checkpoint(
                Checkpoint(agent_id="s1", step=10, outputs=["x"] * 10)
            )
            status = agent.status("s1")
            assert status["state"] == "paused"
            assert status["steps_done"] == 10

    def test_resume_raises_if_no_checkpoint(self):
        from shipit_agent.deep import PersistentAgent

        with tempfile.TemporaryDirectory() as tmpdir:
            agent = PersistentAgent(llm=SimpleEchoLLM(), checkpoint_dir=tmpdir)
            try:
                agent.resume(agent_id="nonexistent")
                assert False, "Should raise ValueError"
            except ValueError:
                pass


# ===========================================================================
# CHANNEL
# ===========================================================================


class TestChannelComprehensive:
    def test_send_receive_roundtrip(self):
        from shipit_agent.deep import Channel, AgentMessage

        ch = Channel(name="test")
        ch.send(AgentMessage(from_agent="a", to_agent="b", type="info", data={"x": 1}))
        msg = ch.receive(agent="b")
        assert msg.data["x"] == 1

    def test_multiple_messages_ordered(self):
        from shipit_agent.deep import Channel, AgentMessage

        ch = Channel()
        ch.send(AgentMessage(from_agent="a", to_agent="b", type="t", data={"n": 1}))
        ch.send(AgentMessage(from_agent="a", to_agent="b", type="t", data={"n": 2}))
        assert ch.receive(agent="b").data["n"] == 1
        assert ch.receive(agent="b").data["n"] == 2

    def test_different_agents_different_queues(self):
        from shipit_agent.deep import Channel, AgentMessage

        ch = Channel()
        ch.send(AgentMessage(from_agent="a", to_agent="b", type="t"))
        ch.send(AgentMessage(from_agent="a", to_agent="c", type="t"))
        assert ch.pending(agent="b") == 1
        assert ch.pending(agent="c") == 1

    def test_ack_marks_message(self):
        from shipit_agent.deep import Channel, AgentMessage

        ch = Channel()
        ch.send(AgentMessage(from_agent="a", to_agent="b", type="t", requires_ack=True))
        msg = ch.receive(agent="b")
        assert not msg.acknowledged
        ch.ack(msg)
        assert msg.acknowledged

    def test_receive_empty_returns_none(self):
        from shipit_agent.deep import Channel

        ch = Channel()
        assert ch.receive(agent="nobody", timeout=0.01) is None

    def test_history_tracks_all_messages(self):
        from shipit_agent.deep import Channel, AgentMessage

        ch = Channel()
        for i in range(5):
            ch.send(AgentMessage(from_agent="a", to_agent="b", type=f"t{i}"))
        assert len(ch.history()) == 5


# ===========================================================================
# BENCHMARK
# ===========================================================================


class TestBenchmarkComprehensive:
    def test_all_pass(self):
        from shipit_agent.deep import AgentBenchmark, TestCase

        agent = Agent(llm=SimpleEchoLLM(), prompt="helpful")
        report = AgentBenchmark(
            name="all-pass",
            cases=[
                TestCase(input="hello world", expected_contains=["hello"]),
                TestCase(input="goodbye world", expected_contains=["goodbye"]),
            ],
        ).run(agent)
        assert report.passed == 2
        assert report.failed == 0
        assert report.pass_rate == 1.0

    def test_partial_pass(self):
        from shipit_agent.deep import AgentBenchmark, TestCase

        agent = Agent(llm=SimpleEchoLLM(), prompt="test")
        report = AgentBenchmark(
            name="partial",
            cases=[
                TestCase(input="hello", expected_contains=["hello"]),
                TestCase(input="hello", expected_contains=["nonexistent_word"]),
            ],
        ).run(agent)
        assert report.passed == 1
        assert report.failed == 1
        assert report.pass_rate == 0.5

    def test_not_contains_check(self):
        from shipit_agent.deep import AgentBenchmark, TestCase

        agent = Agent(llm=SimpleEchoLLM(), prompt="test")
        report = AgentBenchmark(
            name="not-contains",
            cases=[
                TestCase(input="safe text", expected_not_contains=["dangerous"]),
            ],
        ).run(agent)
        assert report.passed == 1

    def test_expected_tools_check(self):
        from shipit_agent.deep import AgentBenchmark, TestCase

        agent = Agent(llm=SimpleEchoLLM(), prompt="test")
        report = AgentBenchmark(
            name="tools",
            cases=[
                TestCase(input="test", expected_tools=["nonexistent_tool"]),
            ],
        ).run(agent)
        assert report.failed == 1
        assert "nonexistent_tool" in report.results[0].failures[0]

    def test_summary_format(self):
        from shipit_agent.deep import AgentBenchmark, TestCase

        agent = Agent(llm=SimpleEchoLLM(), prompt="test")
        report = AgentBenchmark(
            name="summary-test",
            cases=[TestCase(input="hi", expected_contains=["hi"])],
        ).run(agent)
        summary = report.summary()
        assert "summary-test" in summary
        assert "1 passed" in summary
        assert "Pass rate" in summary

    def test_empty_benchmark(self):
        from shipit_agent.deep import AgentBenchmark

        agent = Agent(llm=SimpleEchoLLM())
        report = AgentBenchmark(name="empty", cases=[]).run(agent)
        assert report.total == 0
        assert report.pass_rate == 0.0

    def test_to_dict_structure(self):
        from shipit_agent.deep import AgentBenchmark, TestCase

        agent = Agent(llm=SimpleEchoLLM(), prompt="test")
        report = AgentBenchmark(
            name="dict",
            cases=[TestCase(input="hi")],
        ).run(agent)
        d = report.to_dict()
        assert d["name"] == "dict"
        assert d["total"] == 1
        assert "pass_rate" in d
        assert len(d["results"]) == 1
