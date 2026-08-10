"""Watching a run costs nothing extra.

Progress narration used to call a second model once per iteration, and
with no `decision_llm` configured that second model was the run's own —
so turning narration on doubled the calls a run made, on the expensive
model, to produce a paraphrase of data the runtime was already holding.

It is composed now. These tests pin the property that matters: the number
of model calls does not depend on whether narration is on.
"""

from __future__ import annotations

from shipit_agent import Agent
from shipit_agent.llms.base import LLMResponse
from shipit_agent.models import ToolCall
from shipit_agent.tools.base import ToolOutput


class CountingLLM:
    """Answers a fixed script and counts how often it was asked."""

    model = "m"

    def __init__(self, script) -> None:
        self.script = list(script)
        self.calls = 0

    def complete(self, *, messages, tools=None, system_prompt=None,
                 metadata=None, text_delta_callback=None):
        step = self.script[self.calls] if self.calls < len(self.script) else ("", [])
        self.calls += 1
        return LLMResponse(
            content=step[0],
            tool_calls=[ToolCall(name=n, arguments=a) for n, a in step[1]],
            usage={"total_tokens": 10},
        )


def tool(name, output="ok", fail=False):
    class T:
        def __init__(self) -> None:
            self.name = name
            self.description = name
            self.prompt_instructions = ""

        def schema(self):
            return {"function": {"name": name, "parameters": {"properties": {
                "path": {"type": "string"}}}}}

        def run(self, context, **kwargs):
            if fail:
                return ToolOutput(text="boom", metadata={"error": "boom"})
            return ToolOutput(text=output)

    return T()


SCRIPT = [
    ("Looking now.", [("read_file", {"path": "app.py"})]),
    ("Done.", []),
]


def build(*, narrate: bool, decision_llm=None, tools=None):
    llm = CountingLLM(SCRIPT)
    agent = Agent(
        llm=llm,
        tools=tools if tools is not None else [tool("read_file")],
        progress_summaries=narrate,
        decision_llm=decision_llm,
        auto_use_skills=False,
        max_iterations=4,
    )
    return agent, llm


class TestNarrationIsFree:
    def test_it_costs_no_extra_model_call(self) -> None:
        quiet_agent, quiet = build(narrate=False)
        quiet_agent.run("look")

        loud_agent, loud = build(narrate=True)
        loud_agent.run("look")

        assert loud.calls == quiet.calls, (
            f"narration cost {loud.calls - quiet.calls} extra model calls"
        )

    def test_a_decision_llm_is_never_called(self) -> None:
        """Passing one is tolerated for compatibility, not honoured."""
        spare = CountingLLM([("", [])])
        agent, _ = build(narrate=True, decision_llm=spare)
        agent.run("look")
        assert spare.calls == 0

    def test_the_models_own_words_are_used_when_it_spoke(self) -> None:
        """A model that says why it is calling a tool has already written
        the best line available; composing one over the top is a downgrade
        the user pays for."""
        agent, _ = build(narrate=True)
        result = agent.run("look")
        decisions = [e for e in result.events if e.type == "agent_decision"]
        assert decisions, "narration produced no decision event"
        assert "Looking now." in " ".join(
            str(e.payload.get("summary", "")) for e in decisions
        )

    def test_a_label_is_composed_when_it_said_nothing(self) -> None:
        llm = CountingLLM([("", [("read_file", {"path": "app.py"})]), ("done", [])])
        agent = Agent(llm=llm, tools=[tool("read_file")], progress_summaries=True,
                      auto_use_skills=False, max_iterations=4)
        result = agent.run("look")
        assert "Reading app.py" in " ".join(
            str(e.payload.get("summary", "")) for e in result.events
            if e.type == "agent_decision"
        )

    def test_nothing_is_said_when_it_is_off(self) -> None:
        agent, _ = build(narrate=False)
        result = agent.run("look")
        assert not [e for e in result.events if e.type == "agent_decision"]


class TestWhatItSays:
    def _summaries(self, events, kind):
        return " ".join(
            str(e.payload.get("summary", "")) for e in events if e.type == kind
        )

    def test_a_failed_tool_is_named_as_failed(self) -> None:
        """The failure is the part a watcher is waiting for."""
        agent, _ = build(narrate=True, tools=[tool("read_file", fail=True)])
        result = agent.run("look")
        assert "failed" in self._summaries(result.events, "agent_observation")

    def test_a_successful_tool_is_not(self) -> None:
        agent, _ = build(narrate=True)
        result = agent.run("look")
        assert "failed" not in self._summaries(result.events, "agent_observation")

    def test_an_observation_names_what_it_acted_on(self) -> None:
        """"Read." is not worth emitting; "Read app.py" is."""
        agent, _ = build(narrate=True)
        result = agent.run("look")
        assert "Read app.py" in self._summaries(result.events, "agent_observation")

    def test_a_tool_may_describe_its_own_result(self) -> None:
        """The detail comes from the tool, which knows what its numbers
        mean — never from the runtime pattern-matching its payload."""
        class Counting:
            name = "read_file"
            description = "read"
            prompt_instructions = ""

            def schema(self):
                return {"function": {"name": "read_file",
                                     "parameters": {"properties": {}}}}

            def run(self, context, **kwargs):
                return ToolOutput(text="...", metadata={"summary": "6,746 matches"})

        agent, _ = build(narrate=True, tools=[Counting()])
        result = agent.run("look")
        assert "6,746 matches" in self._summaries(result.events, "agent_observation")

    def test_a_silent_tool_gets_no_invented_detail(self) -> None:
        agent, _ = build(narrate=True)
        result = agent.run("look")
        line = self._summaries(result.events, "agent_observation")
        assert "—" not in line, f"invented a detail: {line}"

    def test_the_final_turn_says_it_is_answering(self) -> None:
        """Only when the model itself is silent — its own closing line
        wins here too."""
        llm = CountingLLM([("", [("read_file", {"path": "app.py"})]), ("", [])])
        agent = Agent(llm=llm, tools=[tool("read_file")], progress_summaries=True,
                      auto_use_skills=False, max_iterations=4)
        result = agent.run("look")
        assert "final answer" in self._summaries(result.events, "agent_decision")


class TestTheClauseJoiner:
    def test_it_reads_as_english(self) -> None:
        from shipit_agent.runtime import _join_clauses

        assert _join_clauses(["a"]) == "a"
        assert _join_clauses(["a", "b"]) == "a and b"
        assert _join_clauses(["a", "b", "c"]) == "a, b and c"

    def test_it_drops_empties_rather_than_leaving_gaps(self) -> None:
        from shipit_agent.runtime import _join_clauses

        assert _join_clauses(["a", "", "c"]) == "a and c"
        assert _join_clauses([]) == ""
