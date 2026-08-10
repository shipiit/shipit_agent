"""A structured tool call arrives already parsed, and can still be broken.

Healing only inspects calls a model wrote as *text*. A call that came back
through the provider's tool-call field skips that path entirely — and a weak
model produces wreckage there too. Observed live from Gemma 4:

    search_echo  <-  {",'query'": ""}

The tool saw no ``query``, read "no filter" as "everything", returned its
whole corpus, and the model answered about the corpus instead of the
question. Every layer reported success.
"""

from __future__ import annotations

from shipit_agent.tool_healing import call_carries_nothing, repair_argument_names

SEARCH = {
    "type": "object",
    "properties": {"query": {"type": "string"}, "limit": {"type": "number"}},
    "required": ["query"],
}

#: A tool whose required list does not hold for every valid call.
MODED = {
    "type": "object",
    "properties": {"task": {"type": "string"}, "collect": {"type": "string"}},
    "required": ["task"],
}


class TestRepairingMangledNames:
    def test_the_observed_wreckage_is_repaired(self) -> None:
        assert repair_argument_names({",'query'": "qilin"}, SEARCH) == {
            "query": "qilin"
        }

    def test_a_good_call_is_untouched(self) -> None:
        arguments = {"query": "qilin", "limit": 5}
        assert repair_argument_names(arguments, SEARCH) == arguments

    def test_it_never_overwrites_what_the_model_supplied(self) -> None:
        """If the real name is already there, the junk key is not promoted."""
        out = repair_argument_names({"query": "real", "'query'": "junk"}, SEARCH)
        assert out["query"] == "real"

    def test_an_unrelated_key_is_left_alone(self) -> None:
        """Repair renames; it must not invent a parameter."""
        assert repair_argument_names({"nonsense": 1}, SEARCH) == {"nonsense": 1}


class TestRefusingAnEmptyCall:
    def test_a_call_with_no_arguments_is_refused(self) -> None:
        assert call_carries_nothing({}, SEARCH) == ["query"]

    def test_an_empty_required_value_is_refused(self) -> None:
        """An empty query is exactly what a tool reads as "no filter"."""
        assert call_carries_nothing({"query": ""}, SEARCH) == ["query"]

    def test_a_real_argument_runs(self) -> None:
        assert call_carries_nothing({"query": "qilin"}, SEARCH) == []

    def test_any_real_argument_is_enough(self) -> None:
        """A schema's required list does not hold for every valid call — a
        tool with modes legitimately omits what another mode demands. A call
        that supplied something has expressed an intent, so it runs."""
        assert call_carries_nothing({"collect": "all"}, MODED) == []

    def test_a_tool_that_requires_nothing_is_never_refused(self) -> None:
        assert call_carries_nothing({}, {"properties": {"a": {}}}) == []


class TestEndToEnd:
    """The gate must reject the call, tell the model what to do, and let the
    run continue — not raise, and not run the tool."""

    def _run(self, arguments: dict):
        from shipit_agent import Agent
        from shipit_agent.llms.base import LLMResponse
        from shipit_agent.models import ToolCall
        from shipit_agent.tools.base import ToolOutput

        ran: list[dict] = []

        class Echo:
            name = "search_echo"
            description = "Search echo"
            prompt_instructions = ""

            def schema(self):
                return {"function": {"name": "search_echo", "parameters": SEARCH}}

            def run(self, context, **kwargs):
                ran.append(kwargs)
                return ToolOutput(text="EVERYTHING" * 500)

        class LLM:
            def __init__(self) -> None:
                self.turn = 0

            def complete(self, **_kw) -> LLMResponse:
                self.turn += 1
                if self.turn == 1:
                    return LLMResponse(
                        tool_calls=[ToolCall(name="search_echo", arguments=arguments)]
                    )
                return LLMResponse(content="done")

        result = Agent(
            llm=LLM(), tools=[Echo()], auto_use_skills=False, max_iterations=4
        ).run("qilin in detail")
        return result, ran

    def test_the_empty_call_never_reaches_the_tool(self) -> None:
        _result, ran = self._run({",'query'": ""})
        assert ran == []

    def test_the_model_is_told_what_to_pass(self) -> None:
        result, _ran = self._run({",'query'": ""})
        tool_messages = [m for m in result.messages if m.role == "tool"]
        assert any("'query'" in (m.content or "") for m in tool_messages)

    def test_the_run_still_finishes(self) -> None:
        """A refusal is recoverable; it must not end the turn."""
        result, _ran = self._run({})
        assert result.output == "done"

    def test_a_repaired_call_does_reach_the_tool(self) -> None:
        """Repair comes first — a fixable call is not refused."""
        _result, ran = self._run({",'query'": "qilin"})
        assert ran and ran[0]["query"] == "qilin"
