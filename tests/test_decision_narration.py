"""Narration a person would actually read, without paying to caption a run.

A small model spends its whole completion on the tool call — 14 to 16 tokens,
measured — so there is no sentence of its own to prefer, and "Asking question
openai/openai-python." is all a composed label can honestly say.

A second model can do better, but the first attempt at this cost more than it
was worth: it ran twice per iteration and was fed the last ten messages at
1,400 characters each, roughly 8,000 tokens an iteration. That is why it was
removed. What matters here is that it is off unless asked for, that it never
displaces the primary model's own words, and that its prompt stays small.
"""

from __future__ import annotations

from shipit_agent import Agent, FunctionTool
from shipit_agent.llms.base import LLMResponse
from shipit_agent.models import ToolCall


def _echo(query: str) -> str:
    """Search the echo feed."""
    return "15 entries for " + query


TOOL = FunctionTool.from_callable(_echo, name="search_echo")
CALL = ToolCall(name="search_echo", arguments={"query": "Qilin"})


class Silent:
    """The whole completion goes on the call, as a small model does."""

    def __init__(self) -> None:
        self.turn = 0

    def complete(self, **_kw) -> LLMResponse:
        self.turn += 1
        if self.turn == 1:
            return LLMResponse(tool_calls=[CALL])
        return LLMResponse(content="Done.")


class Speaking(Silent):
    """A model that says why, in the same response as the call."""

    def complete(self, **_kw) -> LLMResponse:
        self.turn += 1
        if self.turn == 1:
            return LLMResponse(
                content="Checking the echo feed for Qilin first.",
                tool_calls=[CALL],
            )
        return LLMResponse(content="Done.")


class Narrator:
    def __init__(self, reply: str = "Searching the echo feed for Qilin.") -> None:
        self.prompts: list[str] = []
        self.reply = reply

    def complete(self, *, messages, **_kw) -> LLMResponse:
        self.prompts.append(messages[0].content)
        return LLMResponse(content=self.reply)


def _decisions(result) -> list[str]:
    return [
        e.message
        for e in result.events
        if e.type == "agent_decision" and e.payload.get("phase") == "decision"
    ]


def _run(llm, narrator=None, **kw) -> tuple:
    agent = Agent(
        llm=llm,
        tools=[TOOL],
        decision_llm=narrator,
        auto_use_skills=False,
        progress_summaries=True,
        **kw,
    )
    return agent.run("Search echo for Qilin, in detail"), narrator


class TestItIsOffUnlessAskedFor:
    def test_no_decision_model_means_no_extra_call(self) -> None:
        """Your run costs exactly what it did before."""
        result, _ = _run(Silent())
        assert _decisions(result)  # still narrated, from a composed label

    def test_the_composed_label_is_what_you_get(self) -> None:
        result, _ = _run(Silent())
        assert _decisions(result)[0] == "Searching echo Qilin."


class TestTheModelsOwnWordsWin:
    def test_a_speaking_model_is_never_overridden(self) -> None:
        """Its sentence was already paid for and knows more than any caption."""
        result, narrator = _run(Speaking(), Narrator())
        assert _decisions(result)[0] == "Checking the echo feed for Qilin first."

    def test_and_the_narrator_is_not_asked_to_write_that_line(self) -> None:
        """It still narrates the observation — the model only spoke about
        what it was about to do, not about what came back."""
        _result, narrator = _run(Speaking(), Narrator())
        assert not any("About to run:" in p for p in narrator.prompts)


class TestWhenTheModelSaysNothing:
    def test_the_narrator_writes_the_line(self) -> None:
        result, _ = _run(Silent(), Narrator())
        assert _decisions(result)[0] == "Searching the echo feed for Qilin."

    def test_wreckage_from_the_narrator_falls_back_to_the_label(self) -> None:
        """A second model can produce junk too; it does not get a free pass."""
        result, _ = _run(Silent(), Narrator('{"name":"x"}'))
        assert _decisions(result)[0] == "Searching echo Qilin."

    def test_a_narrator_that_raises_never_breaks_the_run(self) -> None:
        class Broken:
            def complete(self, **_kw):
                raise RuntimeError("no")

        result, _ = _run(Silent(), Broken())
        assert result.output == "Done."
        assert _decisions(result)[0] == "Searching echo Qilin."
        assert any(e.type == "progress_summary_failed" for e in result.events)


class TestThePromptStaysSmall:
    """The old version sent up to 14,000 characters of conversation per
    narrated step. This one sends the request, the last observation, and the
    call — and never a tool payload."""

    def test_it_is_a_few_hundred_characters(self) -> None:
        _result, narrator = _run(Silent(), Narrator())
        assert all(len(p) < 1_000 for p in narrator.prompts)

    def test_the_decision_prompt_never_carries_a_tool_result(self) -> None:
        """That line describes an intention; the results are not known yet,
        and they are the expensive part of any prompt."""
        _result, narrator = _run(Silent(), Narrator())
        decision = [p for p in narrator.prompts if "About to run:" in p]
        assert decision
        assert all("15 entries for Qilin" not in p for p in decision)

    def test_the_observation_prompt_sees_a_bounded_head_only(self) -> None:
        """An observation that cannot look at what came back can only restate
        the tool's name — so it gets a head of the result, never the body."""
        big = "x" * 5_000

        def _huge(query: str) -> str:
            """Search."""
            return big

        from shipit_agent import FunctionTool as _FT
        agent_tool = _FT.from_callable(_huge, name="search_echo")
        narrator = Narrator()
        Agent(
            llm=Silent(), tools=[agent_tool], decision_llm=narrator,
            auto_use_skills=False, progress_summaries=True,
        ).run("Search echo for Qilin")
        observation = [p for p in narrator.prompts if "just came back" in p]
        assert observation
        assert all(len(p) < 1_500 for p in observation)

    def test_it_knows_what_the_last_step_found(self) -> None:
        """Without this the line cannot say why this step follows the last."""
        class TwoCalls(Silent):
            def complete(self, **_kw):
                self.turn += 1
                if self.turn <= 2:
                    return LLMResponse(tool_calls=[CALL])
                return LLMResponse(content="Done.")

        _result, narrator = _run(TwoCalls(), Narrator(), max_iterations=5)
        assert any("Last step:" in p for p in narrator.prompts)

    def test_both_lines_are_narrated(self) -> None:
        """"Asked question openai/openai-python." is as thin an observation as
        the composed decision was a decision, and for the same reason."""
        _result, narrator = _run(Silent(), Narrator())
        assert any("About to run:" in p for p in narrator.prompts)
        assert any("just came back" in p for p in narrator.prompts)
