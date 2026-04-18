"""Comprehensive test suite for ShipCrew multi-agent orchestration.

Tests cover: ShipTask, ShipAgent, ShipCoordinator, ShipCrew,
create_ship_crew factory, ShipCrewResult, and custom errors.
"""

from __future__ import annotations

import json

import pytest

from shipit_agent.llms import LLMResponse, SimpleEchoLLM
from shipit_agent.deep.ship_crew import (
    CyclicDependencyError,
    MissingAgentError,
    ShipAgent,
    ShipCrew,
    ShipCrewError,
    ShipCrewResult,
    ShipTask,
    TaskTimeoutError,
    create_ship_crew,
)
from shipit_agent.deep.ship_crew.coordinator import ShipCoordinator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class JSONReplyLLM:
    """LLM that always returns a fixed JSON string."""

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
    """LLM that returns responses from a list in order."""

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


class MockAgent:
    """Lightweight fake agent that returns a predetermined response."""

    def __init__(self, response: str = "mock output"):
        self._response = response
        self.name = "mock"

    def run(self, prompt):
        return type("Result", (), {"output": self._response, "metadata": {}})()

    def stream(self, prompt):
        yield type(
            "Event",
            (),
            {
                "type": "run_completed",
                "message": "done",
                "payload": {"output": self._response},
            },
        )()


# ===========================================================================
# SHIP TASK
# ===========================================================================


class TestShipTask:
    """Tests for ShipTask dataclass and template resolution."""

    # 1
    def test_default_output_key(self):
        """output_key defaults to the task name when not set."""
        task = ShipTask(name="research", description="Do research", agent="r")
        assert task.output_key == "research"

    # 2
    def test_explicit_output_key(self):
        """A custom output_key is preserved and not overwritten."""
        task = ShipTask(
            name="research",
            description="Do research",
            agent="r",
            output_key="findings",
        )
        assert task.output_key == "findings"

    # 3
    def test_resolve_description_simple(self):
        """Single template variable is resolved from outputs."""
        task = ShipTask(name="write", description="Write about {topic}", agent="w")
        resolved = task.resolve_description({"topic": "AI"})
        assert resolved == "Write about AI"

    # 4
    def test_resolve_description_multiple(self):
        """Multiple template variables are resolved simultaneously."""
        task = ShipTask(
            name="combine",
            description="Merge {a} with {b}",
            agent="m",
        )
        resolved = task.resolve_description({"a": "alpha", "b": "beta"})
        assert resolved == "Merge alpha with beta"

    # 5
    def test_resolve_description_missing_key(self):
        """Unresolved variables are left as {var} rather than raising."""
        task = ShipTask(name="t", description="Use {known} and {unknown}", agent="a")
        resolved = task.resolve_description({"known": "value"})
        assert resolved == "Use value and {unknown}"

    # 6
    def test_to_dict(self):
        """to_dict serialises all relevant fields."""
        task = ShipTask(
            name="task1",
            description="desc",
            agent="ag",
            depends_on=["dep"],
            output_key="out",
            output_schema={"type": "object", "required": ["summary"]},
            max_retries=3,
            timeout_seconds=60,
            context={"key": "val"},
        )
        d = task.to_dict()
        assert d["name"] == "task1"
        assert d["description"] == "desc"
        assert d["agent"] == "ag"
        assert d["depends_on"] == ["dep"]
        assert d["output_key"] == "out"
        assert d["output_schema"] == {
            "type": "object",
            "required": ["summary"],
        }
        assert d["max_retries"] == 3
        assert d["timeout_seconds"] == 60
        assert d["context"] == {"key": "val"}

    # 7
    def test_from_dict(self):
        """from_dict restores a ShipTask from a full dict."""
        data = {
            "name": "task1",
            "description": "desc",
            "agent": "ag",
            "depends_on": ["dep"],
            "output_key": "out",
            "output_schema": {"type": "json"},
            "max_retries": 2,
            "timeout_seconds": 120,
            "context": {"k": "v"},
        }
        task = ShipTask.from_dict(data)
        assert task.name == "task1"
        assert task.depends_on == ["dep"]
        assert task.output_key == "out"
        assert task.output_schema == {"type": "json"}
        assert task.max_retries == 2
        assert task.context == {"k": "v"}

    # 8
    def test_from_dict_minimal(self):
        """from_dict works with only the required fields."""
        data = {"name": "t", "description": "d", "agent": "a"}
        task = ShipTask.from_dict(data)
        assert task.name == "t"
        assert task.output_key == "t"  # defaults to name
        assert task.depends_on == []
        assert task.max_retries == 1
        assert task.timeout_seconds == 300

    # 9
    def test_roundtrip(self):
        """to_dict -> from_dict produces an equivalent ShipTask."""
        original = ShipTask(
            name="rt",
            description="roundtrip {x}",
            agent="a",
            depends_on=["dep1"],
            output_key="result",
            output_schema={"type": "markdown"},
            max_retries=5,
            timeout_seconds=999,
            context={"a": 1},
        )
        restored = ShipTask.from_dict(original.to_dict())
        assert restored.name == original.name
        assert restored.description == original.description
        assert restored.agent == original.agent
        assert restored.depends_on == original.depends_on
        assert restored.output_key == original.output_key
        assert restored.output_schema == original.output_schema
        assert restored.max_retries == original.max_retries
        assert restored.timeout_seconds == original.timeout_seconds
        assert restored.context == original.context


# ===========================================================================
# SHIP AGENT
# ===========================================================================


class TestShipAgent:
    """Tests for ShipAgent persona enrichment and delegation."""

    # 10
    def test_construction(self):
        """All fields are set correctly at construction time."""
        mock = MockAgent()
        agent = ShipAgent(
            name="researcher",
            agent=mock,
            role="Senior Researcher",
            goal="Find info",
            backstory="Expert in the field",
            capabilities=["search"],
        )
        assert agent.name == "researcher"
        assert agent.role == "Senior Researcher"
        assert agent.goal == "Find info"
        assert agent.backstory == "Expert in the field"
        assert agent.capabilities == ["search"]

    # 11
    def test_run_delegates(self):
        """run() delegates to the underlying agent and returns its result."""
        mock = MockAgent(response="delegated output")
        agent = ShipAgent(name="a", agent=mock)
        result = agent.run("do something")
        assert result.output == "delegated output"

    # 12
    def test_build_prompt_with_persona(self):
        """_build_prompt prepends role, goal, and backstory."""
        mock = MockAgent()
        agent = ShipAgent(
            name="a",
            agent=mock,
            role="Analyst",
            goal="Analyse data",
            backstory="10 years exp",
        )
        prompt = agent._build_prompt("raw prompt")
        assert "[Role: Analyst]" in prompt
        assert "[Goal: Analyse data]" in prompt
        assert "[Background: 10 years exp]" in prompt
        assert prompt.endswith("raw prompt")

    # 13
    def test_build_prompt_no_persona(self):
        """_build_prompt returns the raw prompt when no persona is set."""
        mock = MockAgent()
        agent = ShipAgent(name="a", agent=mock)
        prompt = agent._build_prompt("just the task")
        assert prompt == "just the task"

    # 14
    def test_from_registry(self):
        """from_registry loads an agent from the default registry."""
        llm = SimpleEchoLLM()
        agent = ShipAgent.from_registry("code-reviewer", llm)
        assert agent.name  # should have a name from the definition
        assert agent.role  # should have a role
        assert agent.agent is not None  # underlying Agent is built

    # 15
    def test_from_registry_missing(self):
        """Missing registry ids raise KeyError."""
        with pytest.raises(KeyError, match="missing-agent"):
            ShipAgent.from_registry("missing-agent", SimpleEchoLLM())


# ===========================================================================
# SHIP COORDINATOR
# ===========================================================================


class TestShipCoordinator:
    """Tests for DAG construction, validation, and execution modes."""

    # --- Helpers ---

    @staticmethod
    def _make_agent(name: str, response: str = "output") -> ShipAgent:
        """Create a ShipAgent wrapping a MockAgent."""
        return ShipAgent(name=name, agent=MockAgent(response=response))

    # 15
    def test_validate_agents_missing(self):
        """Raises MissingAgentError when a task references an unknown agent."""
        agents = {"writer": self._make_agent("writer")}
        tasks = [
            ShipTask(name="t1", description="d", agent="researcher"),
        ]
        with pytest.raises(MissingAgentError, match="researcher"):
            ShipCoordinator(
                llm=SimpleEchoLLM(),
                agents=agents,
                tasks=tasks,
            )

    # 16
    def test_build_dag_no_deps(self):
        """Independent tasks form a single layer."""
        agents = {
            "a": self._make_agent("a"),
            "b": self._make_agent("b"),
        }
        tasks = [
            ShipTask(name="t1", description="d1", agent="a"),
            ShipTask(name="t2", description="d2", agent="b"),
        ]
        coord = ShipCoordinator(llm=SimpleEchoLLM(), agents=agents, tasks=tasks)
        # All tasks in one layer (no dependencies).
        assert len(coord._layers) == 1
        layer_names = {t.name for t in coord._layers[0]}
        assert layer_names == {"t1", "t2"}

    # 17
    def test_build_dag_linear(self):
        """A -> B -> C produces three sequential layers."""
        agent = self._make_agent("a")
        agents = {"a": agent}
        tasks = [
            ShipTask(name="A", description="d", agent="a"),
            ShipTask(name="B", description="d", agent="a", depends_on=["A"]),
            ShipTask(name="C", description="d", agent="a", depends_on=["B"]),
        ]
        coord = ShipCoordinator(llm=SimpleEchoLLM(), agents=agents, tasks=tasks)
        assert len(coord._layers) == 3
        assert coord._layers[0][0].name == "A"
        assert coord._layers[1][0].name == "B"
        assert coord._layers[2][0].name == "C"

    # 18
    def test_build_dag_diamond(self):
        """Diamond: A -> (B, C) -> D produces three layers with parallel middle."""
        agent = self._make_agent("a")
        agents = {"a": agent}
        tasks = [
            ShipTask(name="A", description="d", agent="a"),
            ShipTask(name="B", description="d", agent="a", depends_on=["A"]),
            ShipTask(name="C", description="d", agent="a", depends_on=["A"]),
            ShipTask(name="D", description="d", agent="a", depends_on=["B", "C"]),
        ]
        coord = ShipCoordinator(llm=SimpleEchoLLM(), agents=agents, tasks=tasks)
        assert len(coord._layers) == 3
        # Layer 0: A
        assert [t.name for t in coord._layers[0]] == ["A"]
        # Layer 1: B and C (parallel, sorted alphabetically)
        middle = {t.name for t in coord._layers[1]}
        assert middle == {"B", "C"}
        # Layer 2: D
        assert [t.name for t in coord._layers[2]] == ["D"]

    # 19
    def test_build_dag_cycle(self):
        """Cyclic dependency (A -> B -> A) raises CyclicDependencyError."""
        agent = self._make_agent("a")
        agents = {"a": agent}
        tasks = [
            ShipTask(name="A", description="d", agent="a", depends_on=["B"]),
            ShipTask(name="B", description="d", agent="a", depends_on=["A"]),
        ]
        with pytest.raises(CyclicDependencyError):
            ShipCoordinator(llm=SimpleEchoLLM(), agents=agents, tasks=tasks)

    # 20
    def test_build_dag_unknown_dep(self):
        """Depending on a nonexistent task raises ShipCrewError."""
        agent = self._make_agent("a")
        agents = {"a": agent}
        tasks = [
            ShipTask(name="t1", description="d", agent="a", depends_on=["ghost"]),
        ]
        with pytest.raises(ShipCrewError, match="ghost"):
            ShipCoordinator(llm=SimpleEchoLLM(), agents=agents, tasks=tasks)

    # 21
    def test_execute_sequential(self):
        """Sequential mode runs tasks in order; outputs flow between tasks."""
        agents = {
            "a": self._make_agent("a", response="result_A"),
            "b": self._make_agent("b", response="result_B"),
        }
        tasks = [
            ShipTask(name="t1", description="first", agent="a"),
            ShipTask(
                name="t2",
                description="use {t1}",
                agent="b",
                depends_on=["t1"],
            ),
        ]
        coord = ShipCoordinator(llm=SimpleEchoLLM(), agents=agents, tasks=tasks)
        result = coord.run()
        assert "result_B" in result.output
        assert result.task_results["t1"] == "result_A"
        assert result.task_results["t2"] == "result_B"

    # 22
    def test_execute_parallel(self):
        """Parallel mode completes all independent tasks."""
        agents = {
            "a": self._make_agent("a", response="out_a"),
            "b": self._make_agent("b", response="out_b"),
        }
        tasks = [
            ShipTask(name="t1", description="d1", agent="a"),
            ShipTask(name="t2", description="d2", agent="b"),
        ]
        coord = ShipCoordinator(
            llm=SimpleEchoLLM(),
            agents=agents,
            tasks=tasks,
            process="parallel",
        )
        result = coord.run()
        assert "t1" in result.task_results
        assert "t2" in result.task_results
        assert result.total_tasks == 2

    # 23
    def test_execute_hierarchical(self):
        """Hierarchical mode uses the coordinator LLM to assign tasks."""
        # The LLM assigns t1, then signals done with a summary.
        # We use a single task so the "done" response fires while
        # there is still a round to process (task completes, then
        # remaining is empty so the loop exits naturally).
        llm = SequenceLLM(
            [
                json.dumps(
                    {
                        "action": "assign",
                        "task": "t1",
                        "agent": "a",
                        "instructions": "do it",
                    }
                ),
            ]
        )
        agents = {"a": self._make_agent("a", response="task_output")}
        tasks = [ShipTask(name="t1", description="d", agent="a")]
        coord = ShipCoordinator(
            llm=llm,
            agents=agents,
            tasks=tasks,
            process="hierarchical",
        )
        result = coord.run()
        # After the LLM assigns t1 and it completes, remaining is
        # empty so the loop exits.  Final output is the last task's result.
        assert result.task_results["t1"] == "task_output"
        assert result.output == "task_output"
        assert result.total_tasks == 1

    # 24
    def test_run_returns_result(self):
        """run() returns a ShipCrewResult with the correct structure."""
        agents = {"a": self._make_agent("a", response="final")}
        tasks = [ShipTask(name="t1", description="d", agent="a")]
        coord = ShipCoordinator(llm=SimpleEchoLLM(), agents=agents, tasks=tasks)
        result = coord.run()
        assert isinstance(result, ShipCrewResult)
        assert result.output == "final"
        assert result.total_tasks == 1
        assert result.failed_tasks == []
        assert "elapsed_seconds" in result.metadata

    # 25
    def test_stream_emits_events(self):
        """stream() yields run_started, task events, and run_completed."""
        agents = {"a": self._make_agent("a", response="streamed")}
        tasks = [ShipTask(name="t1", description="d", agent="a")]
        coord = ShipCoordinator(llm=SimpleEchoLLM(), agents=agents, tasks=tasks)
        events = list(coord.stream())
        event_types = [e.type for e in events]
        assert event_types[0] == "run_started"
        assert event_types[-1] == "run_completed"
        # Should have task_started (tool_called) and task_completed
        # (tool_completed) in between.
        assert "tool_called" in event_types
        assert "tool_completed" in event_types


# ===========================================================================
# SHIP CREW
# ===========================================================================


class TestShipCrew:
    """Tests for the ShipCrew high-level orchestration API."""

    @staticmethod
    def _make_agent(name: str, response: str = "output") -> ShipAgent:
        return ShipAgent(name=name, agent=MockAgent(response=response))

    # 26
    def test_validate_valid_crew(self):
        """A correctly configured crew returns an empty error list."""
        crew = ShipCrew(
            name="valid",
            coordinator_llm=SimpleEchoLLM(),
            agents=[self._make_agent("a")],
            tasks=[ShipTask(name="t", description="d", agent="a")],
        )
        errors = crew.validate()
        assert errors == []

    # 27
    def test_validate_missing_agent(self):
        """Validation reports when a task references an unknown agent."""
        crew = ShipCrew(
            name="bad",
            coordinator_llm=SimpleEchoLLM(),
            agents=[self._make_agent("a")],
            tasks=[ShipTask(name="t", description="d", agent="ghost")],
        )
        errors = crew.validate()
        assert any("ghost" in e for e in errors)

    # 28
    def test_validate_missing_dependency(self):
        """Validation reports when a task depends on an unknown task."""
        crew = ShipCrew(
            name="bad",
            coordinator_llm=SimpleEchoLLM(),
            agents=[self._make_agent("a")],
            tasks=[
                ShipTask(
                    name="t",
                    description="d",
                    agent="a",
                    depends_on=["nonexistent"],
                )
            ],
        )
        errors = crew.validate()
        assert any("nonexistent" in e for e in errors)

    # 29
    def test_run_sequential_simple(self):
        """Two-task sequential crew produces output with data flow."""
        crew = ShipCrew(
            name="seq",
            coordinator_llm=SimpleEchoLLM(),
            agents=[
                self._make_agent("researcher", response="findings"),
                self._make_agent("writer", response="report"),
            ],
            tasks=[
                ShipTask(
                    name="research",
                    description="Find info",
                    agent="researcher",
                    output_key="findings",
                ),
                ShipTask(
                    name="write",
                    description="Write using {findings}",
                    agent="writer",
                    depends_on=["research"],
                ),
            ],
        )
        result = crew.run()
        assert isinstance(result, ShipCrewResult)
        assert result.task_results["findings"] == "findings"
        assert result.output == "report"

    # 30
    def test_run_with_context_vars(self):
        """Context variables (e.g. topic='AI') are resolved in descriptions."""
        crew = ShipCrew(
            name="ctx",
            coordinator_llm=SimpleEchoLLM(),
            agents=[self._make_agent("a", response="done")],
            tasks=[
                ShipTask(
                    name="t",
                    description="Research {topic}",
                    agent="a",
                )
            ],
        )
        result = crew.run(topic="AI")
        assert isinstance(result, ShipCrewResult)
        # The task executed successfully (context var was resolved).
        assert result.output == "done"

    # 31
    def test_run_parallel_mode(self):
        """Parallel mode completes all tasks."""
        crew = ShipCrew(
            name="par",
            coordinator_llm=SimpleEchoLLM(),
            agents=[
                self._make_agent("a", response="out_a"),
                self._make_agent("b", response="out_b"),
            ],
            tasks=[
                ShipTask(name="t1", description="d1", agent="a"),
                ShipTask(name="t2", description="d2", agent="b"),
            ],
            process="parallel",
        )
        result = crew.run()
        assert "t1" in result.task_results
        assert "t2" in result.task_results
        assert result.total_tasks == 2

    # 32
    def test_stream_events(self):
        """stream() yields the expected event type sequence."""
        crew = ShipCrew(
            name="stream",
            coordinator_llm=SimpleEchoLLM(),
            agents=[self._make_agent("a", response="streamed")],
            tasks=[ShipTask(name="t", description="d", agent="a")],
        )
        events = list(crew.stream())
        event_types = [e.type for e in events]
        assert "run_started" in event_types
        assert "run_completed" in event_types

    # 33
    def test_add_agent(self):
        """Dynamically adding an agent makes it available to the crew."""
        crew = ShipCrew(
            name="dynamic",
            coordinator_llm=SimpleEchoLLM(),
            agents=[self._make_agent("a", response="out_a")],
            tasks=[
                ShipTask(name="t1", description="d1", agent="a"),
                ShipTask(name="t2", description="d2", agent="b"),
            ],
        )
        # Before adding agent "b", validation should fail.
        errors = crew.validate()
        assert any("b" in e for e in errors)

        # After adding it, validation passes.
        crew.add_agent(self._make_agent("b", response="out_b"))
        errors = crew.validate()
        assert errors == []

    # 34
    def test_add_task(self):
        """Dynamically adding a task includes it in the workflow."""
        crew = ShipCrew(
            name="dynamic",
            coordinator_llm=SimpleEchoLLM(),
            agents=[self._make_agent("a")],
            tasks=[ShipTask(name="t1", description="d1", agent="a")],
        )
        assert len(crew.tasks) == 1
        crew.add_task(ShipTask(name="t2", description="d2", agent="a"))
        assert len(crew.tasks) == 2
        assert crew.tasks[-1].name == "t2"


# ===========================================================================
# CREATE SHIP CREW FACTORY
# ===========================================================================


class TestCreateShipCrew:
    """Tests for the create_ship_crew convenience factory."""

    # 35
    def test_create_from_dicts(self):
        """Factory accepts plain dicts for agents and tasks."""
        mock = MockAgent(response="factory_out")
        crew = create_ship_crew(
            name="from-dicts",
            coordinator_llm=SimpleEchoLLM(),
            agents=[{"name": "a", "agent": mock}],
            tasks=[{"name": "t", "description": "d", "agent": "a"}],
        )
        assert isinstance(crew, ShipCrew)
        assert crew.agents[0].name == "a"
        assert crew.tasks[0].name == "t"

    # 36
    def test_create_from_objects(self):
        """Factory accepts ShipAgent and ShipTask objects directly."""
        agent = ShipAgent(name="a", agent=MockAgent())
        task = ShipTask(name="t", description="d", agent="a")
        crew = create_ship_crew(
            name="from-objects",
            coordinator_llm=SimpleEchoLLM(),
            agents=[agent],
            tasks=[task],
        )
        assert isinstance(crew, ShipCrew)
        assert crew.agents[0] is agent
        assert crew.tasks[0] is task

    # 37
    def test_create_mixed(self):
        """Factory handles a mix of dicts and objects."""
        agent_obj = ShipAgent(name="a", agent=MockAgent())
        mock_b = MockAgent(response="b_out")
        task_obj = ShipTask(name="t1", description="d1", agent="a")

        crew = create_ship_crew(
            name="mixed",
            coordinator_llm=SimpleEchoLLM(),
            agents=[
                agent_obj,
                {"name": "b", "agent": mock_b},
            ],
            tasks=[
                task_obj,
                {"name": "t2", "description": "d2", "agent": "b"},
            ],
        )
        assert len(crew.agents) == 2
        assert len(crew.tasks) == 2
        assert crew.agents[0] is agent_obj
        assert crew.agents[1].name == "b"


# ===========================================================================
# SHIP CREW RESULT
# ===========================================================================


class TestShipCrewResult:
    """Tests for ShipCrewResult serialisation and defaults."""

    # 38
    def test_to_dict(self):
        """to_dict serialises all fields to a plain dict."""
        result = ShipCrewResult(
            output="final",
            task_results={"t1": "r1"},
            execution_order=["t1"],
            total_tasks=1,
            failed_tasks=[],
            metadata={"elapsed_seconds": 1.5},
        )
        d = result.to_dict()
        assert d["output"] == "final"
        assert d["task_results"] == {"t1": "r1"}
        assert d["execution_order"] == ["t1"]
        assert d["total_tasks"] == 1
        assert d["failed_tasks"] == []
        assert d["metadata"]["elapsed_seconds"] == 1.5

    # 39
    def test_default_values(self):
        """An empty result has correct defaults for all collection fields."""
        result = ShipCrewResult(output="")
        assert result.task_results == {}
        assert result.execution_order == []
        assert result.total_tasks == 0
        assert result.failed_tasks == []
        assert result.metadata == {}


# ===========================================================================
# SHIP CREW ERRORS
# ===========================================================================


class TestShipCrewErrors:
    """Tests for custom exception hierarchy."""

    # 40
    def test_cyclic_dependency_error(self):
        """CyclicDependencyError can be raised and caught."""
        with pytest.raises(CyclicDependencyError):
            raise CyclicDependencyError("cycle detected")

    # 41
    def test_missing_agent_error(self):
        """MissingAgentError can be raised and caught."""
        with pytest.raises(MissingAgentError):
            raise MissingAgentError("agent not found")

    # 42
    def test_task_timeout_error(self):
        """TaskTimeoutError can be raised and caught."""
        with pytest.raises(TaskTimeoutError):
            raise TaskTimeoutError("task timed out")

    # 43
    def test_error_inheritance(self):
        """All custom errors inherit from ShipCrewError."""
        assert issubclass(CyclicDependencyError, ShipCrewError)
        assert issubclass(MissingAgentError, ShipCrewError)
        assert issubclass(TaskTimeoutError, ShipCrewError)

        # Can be caught with the base class.
        with pytest.raises(ShipCrewError):
            raise CyclicDependencyError("caught as base")
        with pytest.raises(ShipCrewError):
            raise MissingAgentError("caught as base")
        with pytest.raises(ShipCrewError):
            raise TaskTimeoutError("caught as base")
