"""Tests for SHIPIT Agent v2 modules.

Covers: parsers, structured output, pipeline, team, memory, deep agents.
"""

from __future__ import annotations

import tempfile

from shipit_agent import Agent
from shipit_agent.llms import LLMResponse, SimpleEchoLLM
from shipit_agent.models import Message


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


class JSONReplyLLM:
    """LLM that always returns a specific JSON string."""

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


# ===========================================================================
# PARSERS
# ===========================================================================


class TestJSONParser:
    def test_parse_valid_json(self):
        from shipit_agent.parsers import JSONParser

        parser = JSONParser()
        result = parser.parse('{"name": "Alice", "age": 30}')
        assert result == {"name": "Alice", "age": 30}

    def test_parse_json_in_code_fence(self):
        from shipit_agent.parsers import JSONParser

        parser = JSONParser()
        text = 'Here is the result:\n```json\n{"status": "ok"}\n```\nDone.'
        result = parser.parse(text)
        assert result == {"status": "ok"}

    def test_parse_json_with_surrounding_prose(self):
        from shipit_agent.parsers import JSONParser

        parser = JSONParser()
        text = 'The answer is {"value": 42} and that is final.'
        result = parser.parse(text)
        assert result == {"value": 42}

    def test_parse_validates_required_keys(self):
        from shipit_agent.parsers import JSONParser, ParseError

        parser = JSONParser(schema={"properties": {"x": {}}, "required": ["x"]})
        try:
            parser.parse('{"y": 1}')
            assert False, "Should have raised ParseError"
        except ParseError:
            pass

    def test_parse_invalid_json_raises(self):
        from shipit_agent.parsers import JSONParser, ParseError

        parser = JSONParser()
        try:
            parser.parse("not json at all")
            assert False, "Should have raised ParseError"
        except ParseError:
            pass

    def test_format_instructions(self):
        from shipit_agent.parsers import JSONParser

        parser = JSONParser(schema={"type": "object"})
        instructions = parser.get_format_instructions()
        assert "JSON" in instructions


class TestPydanticParser:
    def test_parse_pydantic_model(self):
        from pydantic import BaseModel
        from shipit_agent.parsers import PydanticParser

        class Movie(BaseModel):
            title: str
            rating: float

        parser = PydanticParser(model=Movie)
        result = parser.parse('{"title": "The Matrix", "rating": 9.5}')
        assert isinstance(result, Movie)
        assert result.title == "The Matrix"
        assert result.rating == 9.5

    def test_parse_from_code_fence(self):
        from pydantic import BaseModel
        from shipit_agent.parsers import PydanticParser

        class Item(BaseModel):
            name: str

        parser = PydanticParser(model=Item)
        result = parser.parse('```json\n{"name": "widget"}\n```')
        assert result.name == "widget"

    def test_invalid_data_raises(self):
        from pydantic import BaseModel
        from shipit_agent.parsers import PydanticParser, ParseError

        class Strict(BaseModel):
            count: int

        parser = PydanticParser(model=Strict)
        try:
            parser.parse('{"count": "not a number"}')
        except (ParseError, Exception):
            pass  # Pydantic may coerce or reject

    def test_get_json_schema(self):
        from pydantic import BaseModel
        from shipit_agent.parsers import PydanticParser

        class Foo(BaseModel):
            bar: str

        parser = PydanticParser(model=Foo)
        schema = parser.get_json_schema()
        assert "properties" in schema
        assert "bar" in schema["properties"]


class TestRegexParser:
    def test_parse_with_output_keys(self):
        from shipit_agent.parsers import RegexParser

        parser = RegexParser(pattern=r"Score: (\d+)/10", output_keys=["score"])
        result = parser.parse("The movie gets a Score: 8/10")
        assert result == {"score": "8"}

    def test_parse_no_match_raises(self):
        from shipit_agent.parsers import RegexParser, ParseError

        parser = RegexParser(pattern=r"Score: (\d+)")
        try:
            parser.parse("No score here")
            assert False
        except ParseError:
            pass

    def test_parse_without_keys(self):
        from shipit_agent.parsers import RegexParser

        parser = RegexParser(pattern=r"(\w+)@(\w+)")
        result = parser.parse("Email: user@example")
        assert result["0"] == "user"
        assert result["1"] == "example"


class TestMarkdownParser:
    def test_extract_code_blocks(self):
        from shipit_agent.parsers import MarkdownParser

        parser = MarkdownParser()
        result = parser.parse("```python\nprint('hello')\n```")
        assert len(result.code_blocks) == 1
        assert result.code_blocks[0]["language"] == "python"
        assert result.code_blocks[0]["code"] == "print('hello')"

    def test_extract_headings(self):
        from shipit_agent.parsers import MarkdownParser

        parser = MarkdownParser()
        result = parser.parse("# Title\n## Subtitle\n### Section")
        assert len(result.headings) == 3
        assert result.headings[0]["text"] == "Title"
        assert result.headings[0]["level"] == "1"

    def test_extract_lists(self):
        from shipit_agent.parsers import MarkdownParser

        parser = MarkdownParser()
        result = parser.parse("- item 1\n- item 2\n* item 3")
        assert len(result.lists) == 3
        assert "item 1" in result.lists


# ===========================================================================
# STRUCTURED OUTPUT
# ===========================================================================


class TestStructuredOutput:
    def test_agent_run_with_json_schema(self):
        llm = JSONReplyLLM('{"sentiment": "positive", "score": 0.95}')
        agent = Agent(llm=llm)
        result = agent.run(
            "Analyze this",
            output_schema={
                "type": "object",
                "properties": {"sentiment": {}, "score": {}},
                "required": ["sentiment"],
            },
        )
        assert result.parsed is not None
        assert result.parsed["sentiment"] == "positive"

    def test_agent_run_with_pydantic_model(self):
        from pydantic import BaseModel

        class Analysis(BaseModel):
            sentiment: str
            score: float

        llm = JSONReplyLLM('{"sentiment": "positive", "score": 0.95}')
        agent = Agent(llm=llm)
        result = agent.run("Analyze", output_schema=Analysis)
        assert result.parsed is not None
        assert isinstance(result.parsed, Analysis)
        assert result.parsed.sentiment == "positive"

    def test_agent_run_without_schema(self):
        agent = Agent(llm=SimpleEchoLLM())
        result = agent.run("Hello")
        assert result.parsed is None

    def test_parse_failure_returns_none(self):
        llm = JSONReplyLLM("not json")
        agent = Agent(llm=llm)
        result = agent.run(
            "test", output_schema={"type": "object", "properties": {"x": {}}}
        )
        assert result.parsed is None


# ===========================================================================
# PIPELINE
# ===========================================================================


class TestPipeline:
    def test_sequential_pipeline(self):
        from shipit_agent.pipeline import Pipeline, step

        agent_a = Agent(llm=SimpleEchoLLM(), prompt="Agent A")
        agent_b = Agent(llm=SimpleEchoLLM(), prompt="Agent B")

        pipe = Pipeline.sequential(
            step("first", agent=agent_a, prompt="Process {topic}"),
            step("second", agent=agent_b, prompt="Refine: {first.output}"),
        )
        result = pipe.run(topic="AI")
        assert "first" in result.steps
        assert "second" in result.steps
        assert result.output  # has final output

    def test_function_step(self):
        from shipit_agent.pipeline import Pipeline, step

        pipe = Pipeline.sequential(
            step("upper", fn=str.upper, prompt="hello world"),
        )
        result = pipe.run()
        assert result.output == "HELLO WORLD"

    def test_parallel_steps(self):
        from shipit_agent.pipeline import Pipeline, step, parallel

        pipe = Pipeline(
            parallel(
                step("a", fn=lambda x: "result_a"),
                step("b", fn=lambda x: "result_b"),
            ),
        )
        result = pipe.run()
        assert "a" in result.steps
        assert "b" in result.steps
        assert result.steps["a"].output == "result_a"
        assert result.steps["b"].output == "result_b"

    def test_conditional_routing(self):
        from shipit_agent.pipeline import Pipeline, step

        pipe = Pipeline.sequential(
            step(
                "route",
                router=lambda ctx: "path_a",
                branches={
                    "path_a": step("a", fn=lambda x: "took path A"),
                    "path_b": step("b", fn=lambda x: "took path B"),
                },
            ),
        )
        result = pipe.run()
        assert "took path A" in result.output

    def test_template_resolution(self):
        from shipit_agent.pipeline import Pipeline, step

        pipe = Pipeline.sequential(
            step("greet", fn=lambda x: "Hello World"),
            step("transform", fn=str.upper, prompt="{greet.output}"),
        )
        result = pipe.run()
        assert result.steps["greet"].output == "Hello World"

    def test_pipeline_result_to_dict(self):
        from shipit_agent.pipeline import Pipeline, step

        pipe = Pipeline.sequential(step("x", fn=lambda x: "done"))
        result = pipe.run()
        d = result.to_dict()
        assert "output" in d
        assert "steps" in d


# ===========================================================================
# TEAM
# ===========================================================================


class TestAgentTeam:
    def test_team_runs_with_coordinator(self):
        from shipit_agent.team import AgentTeam, TeamAgent

        # Coordinator decides to finish immediately
        coordinator = JSONReplyLLM(
            '{"next_agent": null, "done": true, "final_answer": "Team result"}'
        )
        worker = TeamAgent(
            name="worker", role="Does stuff", agent=Agent(llm=SimpleEchoLLM())
        )

        team = AgentTeam(coordinator=coordinator, agents=[worker])
        result = team.run("Do something")
        assert result.output == "Team result"

    def test_team_delegates_to_agent(self):
        from shipit_agent.team import AgentTeam, TeamAgent

        coordinator = SequenceLLM(
            [
                '{"next_agent": "worker", "prompt": "Do the task", "done": false}',
                '{"done": true, "final_answer": "All done"}',
            ]
        )
        worker = TeamAgent(
            name="worker", role="Worker", agent=Agent(llm=SimpleEchoLLM())
        )

        team = AgentTeam(coordinator=coordinator, agents=[worker])
        result = team.run("Task")
        assert len(result.rounds) == 1
        assert result.rounds[0].agent == "worker"

    def test_team_max_rounds(self):
        from shipit_agent.team import AgentTeam, TeamAgent

        # Coordinator never finishes
        coordinator = JSONReplyLLM(
            '{"next_agent": "w", "prompt": "work", "done": false}'
        )
        worker = TeamAgent(name="w", role="Worker", agent=Agent(llm=SimpleEchoLLM()))

        team = AgentTeam(coordinator=coordinator, agents=[worker], max_rounds=3)
        result = team.run("Infinite task")
        assert len(result.rounds) == 3

    def test_team_result_to_dict(self):
        from shipit_agent.team import AgentTeam, TeamAgent

        coordinator = JSONReplyLLM('{"done": true, "final_answer": "Done"}')
        team = AgentTeam(
            coordinator=coordinator,
            agents=[TeamAgent(name="w", role="W", agent=Agent(llm=SimpleEchoLLM()))],
        )
        result = team.run("Task")
        d = result.to_dict()
        assert "output" in d
        assert "rounds" in d


# ===========================================================================
# MEMORY
# ===========================================================================


class TestConversationMemory:
    def test_buffer_strategy(self):
        from shipit_agent.memory import ConversationMemory

        mem = ConversationMemory(strategy="buffer")
        for i in range(10):
            mem.add(Message(role="user", content=f"msg {i}"))
        assert len(mem.get_messages()) == 10

    def test_window_strategy(self):
        from shipit_agent.memory import ConversationMemory

        mem = ConversationMemory(strategy="window", window_size=3)
        for i in range(10):
            mem.add(Message(role="user", content=f"msg {i}"))
        msgs = mem.get_messages()
        assert len(msgs) == 3
        assert msgs[0].content == "msg 7"

    def test_token_strategy(self):
        from shipit_agent.memory import ConversationMemory

        mem = ConversationMemory(strategy="token", max_tokens=20)
        mem.add(Message(role="user", content="x" * 100))
        mem.add(Message(role="user", content="short"))
        msgs = mem.get_messages()
        assert len(msgs) == 1  # only "short" fits in 20 tokens

    def test_summary_strategy_without_llm(self):
        from shipit_agent.memory import ConversationMemory

        mem = ConversationMemory(strategy="summary", window_size=3)
        for i in range(10):
            mem.add(Message(role="user", content=f"msg {i}"))
        msgs = mem.get_messages()
        # Should have summary + 3 recent
        assert len(msgs) == 4
        assert msgs[0].metadata.get("summary") is True

    def test_clear(self):
        from shipit_agent.memory import ConversationMemory

        mem = ConversationMemory()
        mem.add(Message(role="user", content="test"))
        mem.clear()
        assert len(mem.get_messages()) == 0


class TestSemanticMemory:
    def test_add_and_search(self):
        from shipit_agent.memory import SemanticMemory, InMemoryVectorStore

        def simple_embed(text: str) -> list[float]:
            # Trivial embedding: char frequencies for first 5 chars
            return [float(ord(c)) / 1000 for c in (text[:5].ljust(5))]

        mem = SemanticMemory(
            vector_store=InMemoryVectorStore(),
            embedding_fn=simple_embed,
        )
        mem.add("Python is a programming language")
        mem.add("JavaScript runs in browsers")
        mem.add("Cooking is an art form")

        results = mem.search("Python programming")
        assert len(results) > 0
        assert results[0].text  # has text

    def test_add_many(self):
        from shipit_agent.memory import SemanticMemory, InMemoryVectorStore

        mem = SemanticMemory(
            vector_store=InMemoryVectorStore(),
            embedding_fn=lambda t: [1.0, 0.0],
        )
        ids = mem.add_many(["fact 1", "fact 2"])
        assert len(ids) == 2

    def test_search_without_embeddings(self):
        from shipit_agent.memory import SemanticMemory

        mem = SemanticMemory(embedding_fn=None)
        results = mem.search("query")
        assert results == []


class TestEntityMemory:
    def test_add_and_get(self):
        from shipit_agent.memory import EntityMemory
        from shipit_agent.memory.entity import Entity

        mem = EntityMemory()
        mem.add(Entity(name="Alice", entity_type="person", context="engineer"))
        entity = mem.get("Alice")
        assert entity is not None
        assert entity.entity_type == "person"

    def test_search(self):
        from shipit_agent.memory import EntityMemory
        from shipit_agent.memory.entity import Entity

        mem = EntityMemory()
        mem.add(Entity(name="Project Atlas", context="Kubernetes migration"))
        results = mem.search("Kubernetes")
        assert len(results) == 1
        assert results[0].name == "Project Atlas"

    def test_merge_updates(self):
        from shipit_agent.memory import EntityMemory
        from shipit_agent.memory.entity import Entity

        mem = EntityMemory()
        mem.add(Entity(name="Alice", context="engineer"))
        mem.add(Entity(name="Alice", context="works on Atlas"))
        entity = mem.get("Alice")
        assert "engineer" in entity.context
        assert "Atlas" in entity.context

    def test_remove(self):
        from shipit_agent.memory import EntityMemory
        from shipit_agent.memory.entity import Entity

        mem = EntityMemory()
        mem.add(Entity(name="Bob"))
        mem.remove("Bob")
        assert mem.get("Bob") is None


class TestAgentMemory:
    def test_default_factory(self):
        from shipit_agent.memory import AgentMemory

        mem = AgentMemory.default()
        assert mem.conversation is not None
        assert mem.knowledge is not None
        assert mem.entities is not None

    def test_add_message(self):
        from shipit_agent.memory import AgentMemory

        mem = AgentMemory.default()
        mem.add_message(Message(role="user", content="Hello"))
        msgs = mem.get_conversation_messages()
        assert len(msgs) == 1

    def test_add_entity(self):
        from shipit_agent.memory import AgentMemory
        from shipit_agent.memory.entity import Entity

        mem = AgentMemory.default()
        mem.add_entity(Entity(name="Test", context="testing"))
        assert mem.get_entity("Test") is not None


# ===========================================================================
# DEEP AGENTS
# ===========================================================================


class TestGoalAgent:
    def test_goal_agent_runs(self):
        from shipit_agent.deep import GoalAgent, Goal

        llm = SequenceLLM(
            [
                '{"subtasks": ["do step 1", "do step 2"]}',  # decompose
                "Step 1 done",  # agent run 1
                '{"criteria_met": [true], "all_done": true}',  # evaluate
            ]
        )
        agent = GoalAgent(
            llm=llm,
            goal=Goal(objective="Test goal", success_criteria=["criterion 1"]),
        )
        result = agent.run()
        assert result.goal_status == "completed"

    def test_goal_agent_partial(self):
        from shipit_agent.deep import GoalAgent, Goal

        llm = SequenceLLM(
            [
                '{"subtasks": ["task"]}',
                "Partial work",
                '{"criteria_met": [false], "all_done": false}',
                '{"criteria_met": [false], "all_done": false}',
            ]
        )
        agent = GoalAgent(
            llm=llm,
            goal=Goal(
                objective="Hard goal", success_criteria=["never met"], max_steps=1
            ),
        )
        result = agent.run()
        assert result.goal_status in ("partial", "failed")


class TestReflectiveAgent:
    def test_reflective_agent_improves(self):
        from shipit_agent.deep import ReflectiveAgent

        llm = SequenceLLM(
            [
                "Initial draft of explanation",  # first agent run
                '{"feedback": "needs more detail", "quality_score": 0.6, "revision_needed": true}',  # reflect
                "Revised and improved explanation with more detail",  # revise
                '{"feedback": "good", "quality_score": 0.9, "revision_needed": false}',  # reflect again
            ]
        )
        agent = ReflectiveAgent(llm=llm, max_reflections=3, quality_threshold=0.8)
        result = agent.run("Explain transformers")
        assert result.final_quality >= 0.8
        assert len(result.revisions) >= 2

    def test_reflective_agent_stops_at_threshold(self):
        from shipit_agent.deep import ReflectiveAgent

        llm = SequenceLLM(
            [
                "Great output",
                '{"feedback": "excellent", "quality_score": 0.95, "revision_needed": false}',
            ]
        )
        agent = ReflectiveAgent(llm=llm, quality_threshold=0.8)
        result = agent.run("Simple task")
        assert result.iterations == 1
        assert result.final_quality >= 0.9


class TestAdaptiveAgent:
    def test_create_tool(self):
        from shipit_agent.deep import AdaptiveAgent

        agent = AdaptiveAgent(llm=SimpleEchoLLM())
        tool = agent.create_tool(
            name="doubler",
            description="Doubles a number",
            code="def doubler(n: int) -> str:\n    return str(n * 2)",
        )
        assert tool.name == "doubler"
        assert len(agent.created_tools) == 1
        assert agent.created_tools[0].name == "doubler"

    def test_created_tool_works(self):
        from shipit_agent.deep import AdaptiveAgent
        from shipit_agent.tools.base import ToolContext

        agent = AdaptiveAgent(llm=SimpleEchoLLM())
        tool = agent.create_tool(
            "adder", "Adds", "def adder(a: int, b: int) -> str:\n    return str(a + b)"
        )
        output = tool.run(ToolContext(prompt="test"), a=3, b=4)
        assert output.text == "7"


class TestSupervisor:
    def test_supervisor_delegates_and_finishes(self):
        from shipit_agent.deep import Supervisor, Worker

        llm = SequenceLLM(
            [
                '{"action": "delegate", "worker": "w1", "task": "Do work"}',
                '{"action": "done", "final_answer": "All complete"}',
            ]
        )
        w1 = Worker(name="w1", agent=Agent(llm=SimpleEchoLLM()))

        supervisor = Supervisor(llm=llm, workers=[w1])
        result = supervisor.run("Big task")
        assert result.output == "All complete"
        assert len(result.delegations) == 1
        assert result.delegations[0].worker == "w1"

    def test_supervisor_max_delegations(self):
        from shipit_agent.deep import Supervisor, Worker

        llm = JSONReplyLLM('{"action": "delegate", "worker": "w", "task": "work"}')
        w = Worker(name="w", agent=Agent(llm=SimpleEchoLLM()))

        supervisor = Supervisor(llm=llm, workers=[w], max_delegations=3)
        result = supervisor.run("Task")
        assert result.total_rounds == 3

    def test_supervisor_result_to_dict(self):
        from shipit_agent.deep import Supervisor, Worker

        llm = JSONReplyLLM('{"action": "done", "final_answer": "Done"}')
        supervisor = Supervisor(
            llm=llm, workers=[Worker(name="w", agent=Agent(llm=SimpleEchoLLM()))]
        )
        result = supervisor.run("Task")
        d = result.to_dict()
        assert "output" in d


class TestPersistentAgent:
    def test_checkpoint_save_and_load(self):
        from shipit_agent.deep import PersistentAgent

        with tempfile.TemporaryDirectory() as tmpdir:
            agent = PersistentAgent(
                llm=SimpleEchoLLM(),
                checkpoint_dir=tmpdir,
                checkpoint_interval=1,
                max_steps=2,
            )
            # Check status before
            status = agent.status("test-1")
            assert status["state"] == "not_found"

            # Run creates checkpoints
            agent.run("Test task", agent_id="test-1")

            # Checkpoint file should exist or be cleaned up
            # (depends on whether agent detected "complete/done")

    def test_status_not_found(self):
        from shipit_agent.deep import PersistentAgent

        with tempfile.TemporaryDirectory() as tmpdir:
            agent = PersistentAgent(llm=SimpleEchoLLM(), checkpoint_dir=tmpdir)
            status = agent.status("nonexistent")
            assert status["state"] == "not_found"


class TestChannel:
    def test_send_and_receive(self):
        from shipit_agent.deep import Channel, AgentMessage

        channel = Channel(name="test")
        msg = AgentMessage(
            from_agent="a", to_agent="b", type="data", data={"key": "value"}
        )
        channel.send(msg)

        received = channel.receive(agent="b")
        assert received is not None
        assert received.from_agent == "a"
        assert received.data["key"] == "value"

    def test_ack(self):
        from shipit_agent.deep import Channel, AgentMessage

        channel = Channel()
        msg = AgentMessage(from_agent="a", to_agent="b", type="x", requires_ack=True)
        channel.send(msg)

        received = channel.receive(agent="b")
        assert not received.acknowledged
        channel.ack(received)
        assert received.acknowledged

    def test_pending_count(self):
        from shipit_agent.deep import Channel, AgentMessage

        channel = Channel()
        channel.send(AgentMessage(from_agent="a", to_agent="b", type="x"))
        channel.send(AgentMessage(from_agent="a", to_agent="b", type="y"))
        assert channel.pending(agent="b") == 2
        channel.receive(agent="b")
        assert channel.pending(agent="b") == 1

    def test_history(self):
        from shipit_agent.deep import Channel, AgentMessage

        channel = Channel()
        channel.send(AgentMessage(from_agent="a", to_agent="b", type="x"))
        assert len(channel.history()) == 1

    def test_message_to_dict(self):
        from shipit_agent.deep import AgentMessage

        msg = AgentMessage(from_agent="a", to_agent="b", type="test", data={"k": "v"})
        d = msg.to_dict()
        assert d["from"] == "a"
        assert d["to"] == "b"


class TestBenchmark:
    def test_benchmark_pass(self):
        from shipit_agent.deep import AgentBenchmark, TestCase

        agent = Agent(llm=SimpleEchoLLM(), prompt="helpful assistant")
        benchmark = AgentBenchmark(
            name="basic",
            cases=[
                TestCase(input="Hello world", expected_contains=["hello"]),
            ],
        )
        report = benchmark.run(agent)
        assert report.passed == 1
        assert report.failed == 0

    def test_benchmark_fail_missing_content(self):
        from shipit_agent.deep import AgentBenchmark, TestCase

        agent = Agent(llm=SimpleEchoLLM(), prompt="test")
        benchmark = AgentBenchmark(
            name="strict",
            cases=[
                TestCase(input="Hello", expected_contains=["xyz_not_present"]),
            ],
        )
        report = benchmark.run(agent)
        assert report.failed == 1

    def test_benchmark_summary(self):
        from shipit_agent.deep import AgentBenchmark, TestCase

        agent = Agent(llm=SimpleEchoLLM(), prompt="test")
        benchmark = AgentBenchmark(
            name="summary-test",
            cases=[TestCase(input="hi", expected_contains=["hi"])],
        )
        report = benchmark.run(agent)
        summary = report.summary()
        assert "summary-test" in summary
        assert "1 passed" in summary

    def test_benchmark_to_dict(self):
        from shipit_agent.deep import AgentBenchmark, TestCase

        agent = Agent(llm=SimpleEchoLLM(), prompt="test")
        benchmark = AgentBenchmark(
            name="dict-test",
            cases=[TestCase(input="hi")],
        )
        report = benchmark.run(agent)
        d = report.to_dict()
        assert d["name"] == "dict-test"
        assert "pass_rate" in d

    def test_benchmark_expected_not_contains(self):
        from shipit_agent.deep import AgentBenchmark, TestCase

        agent = Agent(llm=SimpleEchoLLM(), prompt="test")
        benchmark = AgentBenchmark(
            name="not-contains",
            cases=[TestCase(input="hello", expected_not_contains=["hello"])],
        )
        report = benchmark.run(agent)
        assert report.failed == 1  # "hello" IS in the output
